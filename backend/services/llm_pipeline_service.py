import json
import re
import time
import asyncio
import uuid
from typing import Dict, Any, Optional, List, Tuple
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy.orm import Session
from ..models import TranscriptTurn, EMRRecord, EvidenceSpan, NormalizedTerm, AtomicFact
from .llm.llm_service import LLMService
from .llm.prompts import PromptManager
from .evaluation_service import EMREvaluationService
from .validation_service import ValidationService
from .terminology_service import TerminologyService
from .fact_service import FactService
from ..config import settings
from ..utils.logger import logger


def run_async(coro):
    """
    在同步上下文中运行异步协程的辅助函数
    
    解决问题：在FastAPI的事件循环中不能使用asyncio.run()
    
    策略：
    1. 尝试获取当前运行的事件循环
    2. 如果存在事件循环且正在运行，使用ThreadPoolExecutor在新线程中运行
    3. 如果不存在事件循环，使用asyncio.run()
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    
    if loop and loop.is_running():
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(asyncio.run, coro)
            return future.result()
    else:
        return asyncio.run(coro)


class LLMPipelineService:
    FIELD_TYPE_MAPPING = {
        "主诉": "chief_complaint",
        "现病史": "history_present_illness",
        "既往史": "past_history",
        "体格检查": "physical_examination",
        "辅助检查": "auxiliary_examination",
        "诊断": "diagnosis",
        "治疗": "treatment",
        "医嘱": "advice",
        "其他": "other"
    }
    
    STAGE_DELAY = 3.0
    
    def __init__(self, db: Session, llm_service: Optional[LLMService] = None, language: str = "zh"):
        self.db = db
        self.llm_service = llm_service
        self.language = language
        self.prompt_manager = PromptManager(language=language)
        self.debug_mode = settings.LLM_DEBUG_MODE
        self.segment_turns = settings.LLM_SEGMENT_TURNS
        self.evaluation_service = EMREvaluationService()
        self.validation_service = ValidationService()
        self.terminology_service = TerminologyService(db, llm_service, language=language)
        logger.info(f"LLMPipelineService initialized, debug_mode={self.debug_mode}, language={language}, UMLS={'enabled' if self.terminology_service.umls_client else 'disabled'}")
    
    def _extract_json_from_response(self, response_text: str, stage_name: str = "") -> Optional[Dict[str, Any]]:
        """
        从LLM响应中提取JSON对象。
        
        处理以下情况：
        1. 标准JSON：{...}
        2. Markdown代码块包裹：```json ... ```
        3. 缺少开头 { 的JSON：直接以 "key": 开头
        4. 缺少开头 {" 的JSON：直接以 key": 开头
        5. 末尾有多余文字
        6. 开头有多余文字
        7. JSON中有语法错误（缺少逗号、引号不匹配、控制字符等）
        
        Args:
            response_text: LLM返回的原始文本
            stage_name: 阶段名称，用于日志
        
        Returns:
            解析后的字典，失败返回None
        """
        logger.info(f"开始解析JSON响应, 阶段: {stage_name}, 响应长度: {len(response_text)} 字符")
        logger.debug(f"原始响应内容:\n{response_text}")
        
        response_text = response_text.strip()
        
        response_text = self._remove_markdown_code_block(response_text)
        
        response_text = self._remove_control_characters(response_text)
        
        json_start = response_text.find("{")
        json_end = response_text.rfind("}")
        
        if json_start != -1 and json_end > json_start:
            json_str = response_text[json_start:json_end + 1]
            try:
                result = json.loads(json_str)
                logger.info(f"JSON解析成功, 阶段: {stage_name}")
                return result
            except json.JSONDecodeError as e:
                logger.warning(f"标准JSON解析失败, 阶段: {stage_name}, 错误: {e}")
                logger.debug(f"尝试解析的JSON字符串:\n{json_str}")
                
                fixed_json = self._try_fix_json(json_str)
                if fixed_json:
                    logger.info(f"JSON修复成功, 阶段: {stage_name}")
                    return fixed_json
                else:
                    logger.warning(f"JSON修复失败, 阶段: {stage_name}")
        
        all_jsons = self._extract_all_json_objects(response_text)
        if all_jsons:
            logger.info(f"从响应中提取到 {len(all_jsons)} 个JSON对象，使用第一个, 阶段: {stage_name}")
            return all_jsons[0]
        
        if json_end != -1:
            potential_json = response_text[:json_end + 1]
        else:
            potential_json = response_text
        
        if potential_json.startswith('"'):
            json_str = "{" + potential_json
            try:
                result = json.loads(json_str)
                logger.info(f"补全开头大括号后解析成功, 阶段: {stage_name}")
                return result
            except json.JSONDecodeError as e:
                logger.warning(f"补全开头大括号后解析失败, 阶段: {stage_name}, 错误: {e}")
        
        if potential_json and potential_json[0].isalpha():
            colon_pos = potential_json.find('":')
            if colon_pos != -1:
                key = potential_json[:colon_pos]
                rest = potential_json[colon_pos + 1:]
                json_str = '{"' + key + '"' + rest
                try:
                    result = json.loads(json_str)
                    logger.info(f"补全开头引号和大括号后解析成功, 阶段: {stage_name}")
                    return result
                except json.JSONDecodeError as e:
                    logger.warning(f"补全开头引号和大括号后解析失败, 阶段: {stage_name}, 错误: {e}")
        
        if potential_json and potential_json[0].isalpha():
            json_str = "{" + potential_json
            try:
                result = json.loads(json_str)
                logger.info(f"仅补全大括号后解析成功, 阶段: {stage_name}")
                return result
            except json.JSONDecodeError as e:
                logger.warning(f"仅补全大括号后解析失败, 阶段: {stage_name}, 错误: {e}")
        
        logger.error(f"无法从响应中提取有效JSON, 阶段: {stage_name}")
        logger.error(f"响应内容前500字符: {response_text[:500]}")
        logger.debug(f"完整响应内容:\n{response_text}")
        return None
    
    def _remove_markdown_code_block(self, text: str) -> str:
        """移除markdown代码块标记"""
        import re
        
        text = re.sub(r'^```(?:json)?\s*\n?', '', text)
        text = re.sub(r'\n?```\s*$', '', text)
        
        return text.strip()
    
    def _remove_control_characters(self, text: str) -> str:
        """移除JSON中的无效控制字符"""
        import re
        
        result = []
        in_string = False
        escape_next = False
        
        for char in text:
            if escape_next:
                result.append(char)
                escape_next = False
                continue
            
            if char == '\\' and in_string:
                result.append(char)
                escape_next = True
                continue
            
            if char == '"':
                in_string = not in_string
                result.append(char)
                continue
            
            if in_string:
                if ord(char) < 32 and char not in '\n\r\t':
                    continue
                result.append(char)
            else:
                result.append(char)
        
        return ''.join(result)
    
    def _try_fix_json(self, json_str: str) -> Optional[Dict[str, Any]]:
        """尝试修复常见的JSON语法错误"""
        import re
        
        fixed = json_str
        
        fixed = re.sub(r',\s*}', '}', fixed)
        fixed = re.sub(r',\s*]', ']', fixed)
        
        fixed = re.sub(r',\s*\n\s*"', ',', fixed)
        fixed = re.sub(r',\s*\n\s*}', '}', fixed)
        
        fixed = re.sub(r':\s*,', ': null,', fixed)
        fixed = re.sub(r':\s*}', ': null}', fixed)
        
        fixed = re.sub(r'"\s*,\s*,', '",', fixed)
        fixed = re.sub(r',\s*,', ',', fixed)
        
        fixed = re.sub(r'"\s*:\s*"', '": "', fixed)
        fixed = re.sub(r'"\s*:\s*\[', '": [', fixed)
        fixed = re.sub(r'"\s*:\s*\{', '": {', fixed)
        
        fixed = re.sub(r'(?<!\\)"(?=[a-zA-Z0-9_\u4e00-\u9fff])', '"', fixed)
        
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass
        
        brace_count = fixed.count('{') - fixed.count('}')
        bracket_count = fixed.count('[') - fixed.count(']')
        
        if brace_count > 0:
            fixed += '}' * brace_count
        if bracket_count > 0:
            fixed += ']' * bracket_count
        
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            return None
    
    def _extract_all_json_objects(self, text: str) -> List[Dict[str, Any]]:
        """从文本中提取所有完整的JSON对象"""
        import re
        
        results = []
        depth = 0
        start = -1
        
        for i, char in enumerate(text):
            if char == '{':
                if depth == 0:
                    start = i
                depth += 1
            elif char == '}':
                depth -= 1
                if depth == 0 and start != -1:
                    json_str = text[start:i+1]
                    try:
                        obj = json.loads(json_str)
                        if isinstance(obj, dict):
                            results.append(obj)
                    except json.JSONDecodeError:
                        pass
                    start = -1
        
        return results
        
    def process_transcript(
        self,
        visit_id: str,
        save_evidence: bool = True
    ) -> Dict[str, Any]:
        logger.info(f"=== 开始多阶段LLM处理: {visit_id} ===")
        start_time = time.time()
        
        turns = self.db.query(TranscriptTurn).filter(
            TranscriptTurn.visit_id == visit_id
        ).order_by(TranscriptTurn.turn_index).all()
        
        if not turns:
            logger.warning("没有找到对话轮次")
            return {"status": "failed", "error": "No transcript turns found"}
        
        segments = self._segment_turns(turns)
        logger.info(f"对话分为 {len(segments)} 个段落")
        
        all_role_mappings = {}
        all_cleaned_turns = []
        
        segment_start = time.time()
        for i, segment in enumerate(segments):
            logger.info(f">>> 处理段落 {i+1}/{len(segments)}")
            
            result = self._process_segment(segment, i)
            
            if result.get("role_mapping"):
                all_role_mappings.update(result["role_mapping"])
            if result.get("turns"):
                all_cleaned_turns.extend(result["turns"])
        
        logger.info(f"段落处理完成，耗时: {time.time() - segment_start:.2f}秒")
        
        combined_text = self._build_text_from_cleaned_turns(all_cleaned_turns, turns)
        logger.info(f"合并后的清洗文本长度: {len(combined_text)} 字符")
        logger.info(f"收集到 {len(all_cleaned_turns)} 个清洗后的turn")
        
        time.sleep(self.STAGE_DELAY)
        
        fact_start = time.time()
        fact_result = self._fact_extraction_stage(all_cleaned_turns, all_role_mappings, visit_id)
        logger.info(f"事实抽取阶段完成，共 {fact_result.get('fact_count', 0)} 条事实，耗时: {time.time() - fact_start:.2f}秒")
        
        time.sleep(self.STAGE_DELAY)
        
        normalize_start = time.time()
        fact_service = FactService(self.db)
        fact_records = fact_service.get_facts_by_visit(visit_id)
        logger.info(f"从数据库查询到 {len(fact_records)} 条原子事实用于阶段3规范化")
        normalized_result = self._normalize_terms_stage(fact_records, all_role_mappings, visit_id, save_evidence)
        logger.info(f"术语规范化阶段完成，耗时: {time.time() - normalize_start:.2f}秒")
        
        time.sleep(self.STAGE_DELAY)
        
        # DEPRECATED: _extract_fields_stage() 已被阶段2(fact_extraction)替代
        # 事实表本身已是结构化数据，不再需要从文本中抽取字段
        # extraction_result 现在直接来自 fact_result
        # extract_start = time.time()
        # extraction_result = self._extract_fields_stage(
        #     normalized_result.get("normalized_text", combined_text),
        #     all_role_mappings,
        #     []
        # )
        # logger.info(f"字段抽取阶段完成，耗时: {time.time() - extract_start:.2f}秒")
        extraction_result = fact_result
        
        time.sleep(self.STAGE_DELAY)
        
        emr_start = time.time()
        so_result = self._generate_so_stage(fact_records, all_role_mappings)
        ap_result = self._generate_ap_stage(so_result, fact_records, all_role_mappings)
        emr_draft = {
            "subjective": so_result.get("subjective", {}),
            "objective": so_result.get("objective", {}),
            "assessment": ap_result.get("assessment", {}),
            "plan": ap_result.get("plan", {}),
            "so_used_fact_ids": so_result.get("used_fact_ids", []),
            "assessment_items": ap_result.get("assessment_items", []),
            "plan_items": ap_result.get("plan_items", {})
        }
        so_used_fact_ids = emr_draft.get("so_used_fact_ids", [])
        assessment_items = emr_draft.get("assessment_items", [])
        plan_items = emr_draft.get("plan_items", {})
        logger.info(f"病历生成阶段完成（SO/AP分节），S/O使用fact数={len(so_used_fact_ids)}, 评估项数={len(assessment_items)}, 耗时: {time.time() - emr_start:.2f}秒")
        
        time.sleep(self.STAGE_DELAY)
        
        verify_start = time.time()
        fact_records = fact_service.get_facts_by_visit(visit_id)
        verification_result = self._verification_stage(emr_draft, fact_records, all_role_mappings)
        logger.info(f"核查修订阶段完成，耗时: {time.time() - verify_start:.2f}秒")
        
        emr_final = verification_result.get("soap_final", emr_draft)
        emr_final["so_used_fact_ids"] = so_used_fact_ids
        emr_final["assessment_items"] = assessment_items
        emr_final["plan_items"] = plan_items
        
        emr_final = self._normalize_emr_format(emr_final)
        emr_final = self._enrich_evidence_traces(emr_final, fact_records, turns)
        if save_evidence and visit_id:
            self._save_evidence_spans_from_emr(emr_final, visit_id)
            self._save_emr_record(emr_final, visit_id)
            logger.info(f"已保存最终病历记录及证据溯源到数据库: visit_id={visit_id}")
        
        # self._run_evaluation(dialogue_text, emr_result)  # 暂时禁用评估，评估标准需要改进
        
        total_time = time.time() - start_time
        logger.info(f"=== 多阶段LLM处理完成: {visit_id}, 总耗时: {total_time:.2f}秒 ===")
        
        return {
            "status": "completed",
            "role_mapping": all_role_mappings,
            "cleaned_turns": all_cleaned_turns,
            "combined_text": combined_text,
            "fact_result": fact_result,
            "normalized_result": normalized_result,
            "extraction_result": extraction_result,
            "emr_result": emr_final,
            "emr_draft": emr_draft,
            "verification_result": verification_result,
            "processing_time": total_time
        }
    
    def _run_evaluation(self, dialogue_text: str, emr_result: Dict[str, Any]):
        """运行评估并输出结果到日志"""
        try:
            matched = self.evaluation_service.find_matching_test_sample(dialogue_text)
            
            if not matched:
                logger.info("未匹配到测试数据集样本，跳过评估")
                return
            
            sample_id = matched["sample_id"]
            test_sample = matched["test_sample"]
            
            if not test_sample:
                logger.info(f"样本 {sample_id} 无标注数据，跳过评估")
                return
            
            eval_result = self.evaluation_service.evaluate(emr_result, test_sample)
            
            if eval_result:
                ground_truth_diagnosis = test_sample.get("diagnosis", "")
                ground_truth_symptoms = self.evaluation_service._extract_symptoms_from_test(test_sample)
                predicted_diagnosis = self.evaluation_service._extract_diagnosis_from_emr(emr_result)
                predicted_symptoms = self.evaluation_service._extract_symptoms_from_emr(emr_result)
                
                self.evaluation_service.log_evaluation_result(
                    sample_id=sample_id,
                    result=eval_result,
                    ground_truth_diagnosis=ground_truth_diagnosis,
                    predicted_diagnosis=predicted_diagnosis,
                    ground_truth_symptoms=ground_truth_symptoms,
                    predicted_symptoms=predicted_symptoms
                )
        except Exception as e:
            logger.warning(f"评估过程出错: {e}")
    
    def _segment_turns(self, turns: List[TranscriptTurn]) -> List[List[TranscriptTurn]]:
        segments = []
        current_segment = []
        
        for turn in turns:
            current_segment.append(turn)
            
            if len(current_segment) >= self.segment_turns:
                segments.append(current_segment)
                current_segment = []
        
        if current_segment:
            segments.append(current_segment)
            
        return segments
    
    def _build_text_from_cleaned_turns(
        self,
        cleaned_turns: List[Dict[str, Any]],
        original_turns: List[TranscriptTurn]
    ) -> str:
        """
        从清洗后的turn JSON构建合并文本，供后续阶段使用。
        
        优先使用 corrected_text，没有修正时使用原始文本。
        
        Args:
            cleaned_turns: 阶段1输出的清洗后turn列表
            original_turns: 原始数据库turn列表（用于回退）
        
        Returns:
            合并后的文本字符串
        """
        logger.info(f"从 {len(cleaned_turns)} 个清洗turn构建文本")
        
        if cleaned_turns:
            turn_text_map = {}
            for ct in cleaned_turns:
                tid = ct.get("turn_id")
                ct_text = ct.get("corrected_text", "")
                if tid is not None and ct_text:
                    turn_text_map[tid] = ct_text
            
            lines = []
            for turn in original_turns:
                text = turn_text_map.get(turn.turn_index, turn.text)
                speaker = turn.corrected_speaker or turn.speaker
                if speaker and speaker not in ("unknown", "", "None"):
                    lines.append(f"[#{turn.turn_index}] [{speaker}]: {text}")
                else:
                    lines.append(f"[#{turn.turn_index}] {text}")
            
            combined = "\n".join(lines)
            logger.info(f"构建文本完成: {len(combined)} 字符, 使用了 {len(turn_text_map)} 个修正后的turn")
            return combined
        
        lines = []
        for turn in original_turns:
            speaker = turn.speaker
            if speaker and speaker not in ("unknown", "", "None"):
                lines.append(f"[#{turn.turn_index}] [{speaker}]: {turn.text}")
            else:
                lines.append(f"[#{turn.turn_index}] {turn.text}")
        
        return "\n".join(lines)
    
    def _process_segment(
        self,
        segment: List[TranscriptTurn],
        segment_index: int
    ) -> Dict[str, Any]:
        transcript_text = self._format_segment(segment)
        
        prompt = self._build_cleaning_prompt(transcript_text)
        
        if self.debug_mode:
            response_text = self._debug_interact(
                stage="turn_cleaning",
                segment_index=segment_index,
                prompt=prompt,
                transcript_text=transcript_text
            )
        else:
            if not self.llm_service:
                logger.warning("LLM服务不可用，使用规则推断")
                return self._fallback_role_annotation(segment)
            
            try:
                response = self.llm_service.generate(prompt)
                response_text = response.text
            except Exception as e:
                logger.error(f"LLM调用失败: {e}")
                return self._fallback_role_annotation(segment)
        
        cleaning_result = self._parse_cleaning_response(response_text, segment)
        
        if "turns" in cleaning_result:
            self._apply_asr_corrections(cleaning_result, segment)
        
        return cleaning_result
    
    def _format_segment(self, segment: List[TranscriptTurn]) -> str:
        """
        格式化对话轮次为文本。
        
        输出格式包含turn_index，便于后续证据溯源时精确定位：
        - 有标签：[#0] [spk0]: 对话内容
        - 无标签：[#0] 对话内容
        
        turn_index是全局唯一的轮次索引，用于证据溯源时精确匹配原始转写。
        """
        has_valid_speakers = False
        for turn in segment:
            if turn.speaker and turn.speaker not in ("unknown", "", "None"):
                has_valid_speakers = True
                break
        
        lines = []
        for turn in segment:
            if has_valid_speakers:
                lines.append(f"[#{turn.turn_index}] [{turn.speaker}]: {turn.text}")
            else:
                lines.append(f"[#{turn.turn_index}] {turn.text}")
        
        return "\n".join(lines)
    
    # DEPRECATED: replaced by _build_cleaning_prompt()
    def _build_role_annotation_prompt(self, transcript: str) -> str:
        return f"""你是一个医疗对话分析专家。请分析以下医患对话，完成三个任务：

## 任务1：说话人识别与纠错

首先判断对话格式：
- **有说话人标签**：如 [#0] [spk0]: 对话内容 格式，其中[#0]是轮次索引
- **无说话人标签**：如 [#0] 对话内容 格式，没有说话人标签

**重要：轮次索引[#N]是全局唯一标识，必须在输出中完整保留，不能修改或删除。**

### 情况A：有说话人标签
语音识别的说话人分离可能存在错误。请检查每句话的内容，判断说话人标签是否正确。
- 医生特征：提问、检查、诊断、开药、给出建议、使用专业术语
- 患者特征：描述症状、回答问题、表达感受、询问病情

如果发现某句话的说话人标签与内容不符，请在纠正后的对话中使用正确的说话人标签。

### 情况B：无说话人标签
请根据对话内容为每句话分配说话人标签：
- 使用 [医生] 和 [患者] 作为标签
- 根据内容特征判断每句话的说话人

## 任务2：角色映射
列出对话中出现的所有说话人标签，并判断每个是医生还是患者。
- 如果进行了说话人纠错，这里的映射应基于纠正后的标签
- 如果原始对话无标签，则映射 [医生] -> doctor, [患者] -> patient

## 任务3：证据标注
用XML标签标注可能与病历生成相关的证据字段。可用的标签包括：
- <主诉>...</主诉>：患者描述的主要症状或问题
- <现病史>...</现病史>：症状的详细发展过程
- <既往史>...</既往史>：过去的疾病史、手术史、过敏史等
- <体格检查>...</体格检查>：医生的检查过程和结果
- <辅助检查>...</辅助检查>：实验室检查、影像检查等
- <诊断>...</诊断>：医生的诊断结论
- <治疗>...</治疗>：治疗方案、用药等
- <医嘱>...</医嘱>：医生的建议和嘱咐
- <其他>...</其他>：其他相关信息

## 重要约束
1. **严禁幻觉**：只能标注原文中明确存在的内容，绝对不能添加、编造或推测任何原文中没有的信息
2. **完整性**：必须保留原始对话的所有内容，不能删除或省略任何对话
3. **准确性**：证据标注必须准确对应原文内容，不能歪曲原意
4. **忠实原文**：标注内容必须与原文完全一致，不能修改、添加或删除任何词语
5. **保留轮次索引**：轮次索引[#N]必须完整保留，这是证据溯源的关键标识

## 原始对话内容
{transcript}

## 输出格式
请按以下JSON格式输出：
{{
  "dialog_format": "labeled或unlabeled",
  "speakers_found": ["说话人标签列表"],
  "corrections": [
    {{"turn_index": 0, "original_speaker": "原标签", "corrected_speaker": "纠正后标签", "reason": "纠正原因"}}
  ],
  "role_mapping": {{
    "说话人标签1": "doctor或patient",
    "说话人标签2": "doctor或patient"
  }},
  "annotated_text": "处理后的对话文本，保留轮次索引[#N]，在证据周围添加XML标签"
}}

注意：
1. dialog_format: "labeled"表示原始对话有说话人标签，"unlabeled"表示没有
2. corrections: 仅在有说话人标签且发现错误时填写，否则为空列表
3. role_mapping: 列出所有说话人标签及其角色，不要遗漏
4. annotated_text: 
   - 必须保留轮次索引[#N]格式
   - 有标签时：[#N] [说话人]: 对话内容
   - 无标签时：[#N] [医生/患者]: 对话内容
5. 证据标注要准确，不要遗漏重要信息
6. 一段话可能包含多个证据字段
7. **必须保留所有原始对话内容，不能删除任何对话**
8. **轮次索引[#N]是证据溯源的关键，必须完整保留**"""
    
    def _build_cleaning_prompt(self, transcript: str) -> str:
        """
        构建阶段1转写清洗与角色纠错提示词。
        
        使用 prompt_manager 中的 turn_cleaning 模板，仅包含角色纠错和ASR清洗，
        不再包含证据标注（证据标注已移至阶段2）。
        
        Args:
            transcript: 格式化的对话文本
        
        Returns:
            渲染后的提示词字符串
        """
        logger.info("构建转写清洗提示词")
        prompt = self.prompt_manager.render("turn_cleaning", transcript=transcript)
        logger.debug(f"转写清洗提示词长度: {len(prompt)} 字符")
        return prompt
    
    # DEPRECATED: replaced by _parse_cleaning_response()
    def _parse_role_annotation_response(
        self,
        response_text: str,
        segment: List[TranscriptTurn]
    ) -> Dict[str, Any]:
        result = self._extract_json_from_response(response_text, "角色标注")
        
        if result:
            dialog_format = result.get("dialog_format", "labeled")
            role_mapping = result.get("role_mapping", {})
            annotated_text = result.get("annotated_text", "")
            corrections = result.get("corrections", [])
            speakers_found = result.get("speakers_found", [])
            
            if dialog_format == "unlabeled":
                correction_map = self._assign_speakers_from_unlabeled(
                    annotated_text, segment, role_mapping
                )
            else:
                correction_map = self._apply_speaker_corrections(corrections, segment)
            
            evidence_traces = self._extract_evidence_traces(
                annotated_text, segment, role_mapping, correction_map
            )
            
            return {
                "dialog_format": dialog_format,
                "role_mapping": role_mapping,
                "annotated_text": annotated_text,
                "evidence_traces": evidence_traces,
                "speaker_corrections": corrections,
                "speakers_found": speakers_found
            }
        
        return self._fallback_role_annotation(segment)
    
    def _parse_cleaning_response(
        self,
        response_text: str,
        segment: List[TranscriptTurn]
    ) -> Dict[str, Any]:
        """
        解析阶段1的转写清洗LLM响应。
        
        解析LLM返回的turn JSON列表，提取角色映射和清理后的turn数据。
        如果JSON解析失败，回退到 _fallback_role_annotation()。
        
        Args:
            response_text: LLM返回的原始文本
            segment: 对话轮次列表
        
        Returns:
            {
                "turns": [...],           # 清洗后的turn JSON列表
                "role_mapping": {...},     # 角色映射
                "speaker_corrections": [...] # 说话人纠正记录
            }
        """
        logger.info("解析转写清洗响应")
        
        result = self._extract_json_from_response(response_text, "转写清洗")
        
        if result:
            turns_data = result.get("turns", [])
            logger.info(f"解析到 {len(turns_data)} 个清洗后的turn")
            
            role_mapping = {}
            speaker_corrections = []
            
            turn_by_index = {turn.turn_index: turn for turn in segment}
            
            for turn_json in turns_data:
                turn_id = turn_json.get("turn_id")
                speaker_role = turn_json.get("speaker_role")
                
                if turn_id is None or speaker_role is None:
                    logger.warning(f"turn JSON缺少必要字段: turn_id={turn_id}, speaker_role={speaker_role}")
                    continue
                
                role_mapping[str(turn_id)] = speaker_role
                
                turn = turn_by_index.get(turn_id)
                if turn:
                    original_speaker = turn.speaker
                    if original_speaker and original_speaker not in ("unknown", "", "None"):
                        if speaker_role == "doctor":
                            expected_label = "spk0" if original_speaker != "spk0" else original_speaker
                        else:
                            expected_label = "spk1" if original_speaker != "spk1" else original_speaker
                    else:
                        expected_label = f"spk_{turn_id}"
                    
                    if original_speaker and original_speaker != speaker_role and original_speaker not in ("unknown", "", "None"):
                        speaker_corrections.append({
                            "turn_index": turn_id,
                            "original_speaker": original_speaker,
                            "corrected_speaker": speaker_role,
                            "reason": turn_json.get("reason", "")
                        })
                
                turn.corrected_speaker = speaker_role
            
            if speaker_corrections:
                self._apply_speaker_corrections(speaker_corrections, segment)
            
            for turn in segment:
                if turn.corrected_speaker:
                    role_mapping[turn.speaker] = turn.corrected_speaker
            
            return {
                "turns": turns_data,
                "role_mapping": role_mapping,
                "speaker_corrections": speaker_corrections
            }
        
        logger.warning("转写清洗JSON解析失败，回退到规则推断")
        return self._fallback_role_annotation(segment)
    
    def _apply_asr_corrections(
        self,
        cleaning_result: Dict[str, Any],
        segment: List[TranscriptTurn]
    ) -> Dict[int, str]:
        """
        将清洗结果中的ASR修正应用到数据库。
        
        遍历 cleaning_result 中的 turns 列表，对于每个 changed_spans 非空的turn，
        将 corrected_text 更新到数据库的 TranscriptTurn.corrected_text 字段。
        
        Args:
            cleaning_result: _parse_cleaning_response 的返回结果
            segment: 对话轮次列表
        
        Returns:
            {turn_index: corrected_text} 修正映射
        """
        logger.info("应用ASR修正结果")
        
        turns_data = cleaning_result.get("turns", [])
        if not turns_data:
            logger.info("没有需要应用的ASR修正")
            return {}
        
        turn_by_index = {turn.turn_index: turn for turn in segment}
        correction_map = {}
        applied_count = 0
        
        for turn_json in turns_data:
            turn_id = turn_json.get("turn_id")
            corrected_text = turn_json.get("corrected_text", "")
            changed_spans = turn_json.get("changed_spans", [])
            
            if turn_id is None:
                continue
            
            turn = turn_by_index.get(turn_id)
            if not turn:
                logger.warning(f"ASR修正跳过: 找不到turn_index={turn_id}对应的turn")
                continue
            
            if changed_spans and corrected_text:
                turn.corrected_text = corrected_text
                correction_map[turn_id] = corrected_text
                applied_count += 1
                logger.info(
                    f"ASR修正: turn_index={turn_id}, "
                    f"修改了 {len(changed_spans)} 处, "
                    f"置信度: {turn_json.get('correction_confidence', 'N/A')}"
                )
        
        if self.db and correction_map:
            try:
                self.db.commit()
                logger.info(f"已保存 {applied_count} 条ASR修正记录到数据库")
            except Exception as e:
                self.db.rollback()
                logger.error(f"保存ASR修正记录失败: {e}")
        
        logger.info(f"ASR修正完成: 共修正 {applied_count} 个turn")
        return correction_map
    
    def _fact_extraction_stage(
        self,
        cleaned_turns: List[Dict],
        role_mapping: Dict[str, str],
        visit_id: str = None
    ) -> Dict[str, Any]:
        logger.info(">>> 阶段2: 事实抽取与证据绑定")
        stage_start = time.time()
        
        turns_json = json.dumps(cleaned_turns, ensure_ascii=False, indent=2)
        logger.info(f"清理后的turn数: {len(cleaned_turns)}")
        
        prompt = self.prompt_manager.render("fact_extraction", turns_json=turns_json)
        logger.debug(f"事实抽取提示词长度: {len(prompt)} 字符")
        
        if self.debug_mode:
            response_text = self._debug_interact(
                stage="fact_extraction",
                prompt=prompt,
                clean_turns=cleaned_turns
            )
        else:
            if not self.llm_service:
                logger.warning("LLM服务不可用，事实抽取失败")
                return {"facts": [], "fact_count": 0}
            
            try:
                response = self.llm_service.generate(prompt)
                response_text = response.text
            except Exception as e:
                logger.error(f"事实抽取LLM调用失败: {e}")
                return {"facts": [], "fact_count": 0}
        
        result = self._extract_json_from_response(response_text, "事实抽取")
        
        facts = []
        if result and "facts" in result:
            raw_facts = result.get("facts", [])
            logger.info(f"LLM返回 {len(raw_facts)} 条原始事实")
            
            facts = self._deduplicate_facts(raw_facts)
            logger.info(f"去重后剩余 {len(facts)} 条事实")
        
        if facts and visit_id and self.db:
            self._save_atomic_facts(facts, visit_id)
        
        stage_time = time.time() - stage_start
        logger.info(f"事实抽取完成，共 {len(facts)} 条事实，耗时: {stage_time:.2f}秒")
        
        return {
            "facts": facts,
            "fact_count": len(facts)
        }
    
    def _deduplicate_facts(self, facts: List[Dict]) -> List[Dict]:
        logger.info("开始事实去重")
        
        merged = {}
        for fact in facts:
            mention = fact.get("mention", "").strip()
            section = fact.get("section_candidate", "")
            speaker = fact.get("speaker", "")
            
            key = f"{mention}|{section}|{speaker}"
            
            if key in merged:
                existing = merged[key]
                existing_turn_ids = set(existing.get("evidence_turn_ids", []))
                new_turn_ids = set(fact.get("evidence_turn_ids", []))
                existing_turn_ids.update(new_turn_ids)
                existing["evidence_turn_ids"] = sorted(list(existing_turn_ids))
                
                existing_texts = existing.get("evidence_text", [])
                new_texts = fact.get("evidence_text", [])
                for text in new_texts:
                    if text not in existing_texts:
                        existing_texts.append(text)
                existing["evidence_text"] = existing_texts
                
                if fact.get("certainty") == "explicit" and existing.get("certainty") != "explicit":
                    existing["certainty"] = "explicit"
                
                logger.debug(f"合并事实: '{mention}' (section={section}), turn_ids={existing['evidence_turn_ids']}")
            else:
                merged[key] = dict(fact)
        
        logger.info(f"事实去重完成: {len(facts)} -> {len(merged)}")
        return list(merged.values())
    
    def _save_atomic_facts(self, facts: List[Dict], visit_id: str):
        try:
            saved_count = 0
            for fact_data in facts:
                fact_id = f"fact_{visit_id}_{uuid.uuid4().hex[:12]}"
                
                atomic_fact = AtomicFact(
                    fact_id=fact_id,
                    visit_id=visit_id,
                    section_candidate=fact_data.get("section_candidate", ""),
                    concept_type=fact_data.get("concept_type", "other"),
                    mention=fact_data.get("mention", ""),
                    polarity=fact_data.get("polarity", "present"),
                    temporality=fact_data.get("temporality", "unknown"),
                    certainty=fact_data.get("certainty", "supported"),
                    speaker=fact_data.get("speaker", "patient"),
                    evidence_turn_ids=fact_data.get("evidence_turn_ids", []),
                    evidence_text=fact_data.get("evidence_text", []),
                    asr_risk="low",
                    normalization_needed=True
                )
                
                self.db.add(atomic_fact)
                saved_count += 1
            
            self.db.commit()
            logger.info(f"已保存 {saved_count} 条原子事实到数据库")
        except Exception as e:
            self.db.rollback()
            logger.error(f"保存原子事实失败: {e}")
    
    def _assign_speakers_from_unlabeled(
        self,
        annotated_text: str,
        segment: List[TranscriptTurn],
        role_mapping: Dict[str, str]
    ) -> Dict[int, str]:
        """
        从无标签对话的标注结果中提取说话人分配。
        
        当原始对话没有说话人标签时，LLM会为每句话分配[医生]或[患者]标签。
        此方法解析标注文本，更新数据库中的说话人信息。
        
        Args:
            annotated_text: LLM标注后的文本（包含[医生]/[患者]标签）
            segment: 对话轮次列表
            role_mapping: 角色映射（如 {"医生": "doctor", "患者": "patient"}）
        
        Returns:
            说话人分配映射 {turn_index: assigned_speaker}
        """
        assignment_map = {}
        
        speaker_pattern = r'\[(医生|患者)\]:\s*([^\n\[]+)'
        matches = re.findall(speaker_pattern, annotated_text)
        
        if not matches:
            logger.warning("无标签对话解析失败：未找到[医生]/[患者]标签")
            return assignment_map
        
        turn_index = 0
        for speaker_label, text_content in matches:
            text_content = text_content.strip()
            if not text_content:
                continue
            
            if turn_index < len(segment):
                turn = segment[turn_index]
                turn.corrected_speaker = speaker_label
                assignment_map[turn_index] = speaker_label
                logger.info(
                    f"无标签对话分配说话人: turn_index={turn_index}, "
                    f"speaker={speaker_label}, text={text_content[:30]}..."
                )
                turn_index += 1
        
        if self.db and assignment_map:
            try:
                self.db.commit()
                logger.info(f"已保存 {len(assignment_map)} 条说话人分配记录")
            except Exception as e:
                self.db.rollback()
                logger.error(f"保存说话人分配记录失败: {e}")
        
        return assignment_map
    
    def _apply_speaker_corrections(
        self,
        corrections: List[Dict[str, Any]],
        segment: List[TranscriptTurn]
    ) -> Dict[int, str]:
        """
        应用说话人纠正到对话轮次。
        
        Args:
            corrections: 纠正列表，每项包含 turn_index, original_speaker, corrected_speaker, reason
            segment: 对话轮次列表
        
        Returns:
            纠正映射字典 {turn_index: corrected_speaker}
        """
        correction_map = {}
        
        if not corrections:
            return correction_map
        
        turn_by_index = {turn.turn_index: turn for turn in segment}
        
        for correction in corrections:
            turn_index = correction.get("turn_index")
            original_speaker = correction.get("original_speaker")
            corrected_speaker = correction.get("corrected_speaker")
            reason = correction.get("reason", "")
            
            if turn_index is None or corrected_speaker is None:
                continue
            
            if original_speaker:
                original_speaker = re.sub(r'^\[|\]$', '', original_speaker)
            
            turn = turn_by_index.get(turn_index)
            if turn:
                if turn.speaker == original_speaker:
                    turn.corrected_speaker = corrected_speaker
                    correction_map[turn_index] = corrected_speaker
                    logger.info(
                        f"说话人纠正: turn_index={turn_index}, "
                        f"{original_speaker} -> {corrected_speaker}, "
                        f"原因: {reason}"
                    )
                else:
                    logger.warning(
                        f"说话人纠正跳过: turn_index={turn_index}, "
                        f"原始说话人不匹配 (期望={original_speaker}, 实际={turn.speaker})"
                    )
        
        if self.db and correction_map:
            try:
                self.db.commit()
                logger.info(f"已保存 {len(correction_map)} 条说话人纠正记录")
            except Exception as e:
                self.db.rollback()
                logger.error(f"保存说话人纠正记录失败: {e}")
        
        return correction_map
    
    FIELD_EXPECTED_ROLE = {
        "chief_complaint": "patient",
        "history_present_illness": "patient",
        "past_history": "patient",
        "physical_examination": "doctor",
        "auxiliary_examination": "doctor",
        "diagnosis": "doctor",
        "treatment": "doctor",
        "advice": "doctor",
        "other": None
    }
    
    # DEPRECATED: 证据标注职责已移交给阶段2(fact_extraction)，此方法将在后续版本中移除。
    # 当前仅保留以防兼容性需要，不再在新流程中使用。
    def _extract_evidence_traces(
        self,
        annotated_text: str,
        segment: List[TranscriptTurn],
        role_mapping: Dict[str, str] = None,
        correction_map: Dict[int, str] = None
    ) -> List[Dict[str, Any]]:
        """
        从标注文本中提取证据溯源信息。
        
        优先从标注文本中解析turn_index（格式：[#N]），确保证据与原始转写精确对应。
        
        Args:
            annotated_text: LLM标注后的文本，格式如：[#0] [spk0]: 你好，<主诉>...</主诉>
            segment: 对话轮次列表
            role_mapping: 角色映射字典
            correction_map: 说话人纠正映射 {turn_index: corrected_speaker}
        
        Returns:
            证据溯源列表
        """
        evidence_traces = []
        correction_map = correction_map or {}
        role_mapping = role_mapping or {}
        
        tag_pattern = r'<(主诉|现病史|既往史|体格检查|辅助检查|诊断|治疗|医嘱|其他)>(.*?)</\1>'
        turn_index_pattern = r'\[#(\d+)\]'
        
        turn_by_index = {}
        for turn in segment:
            turn_by_index[turn.turn_index] = turn
        
        for match in re.finditer(tag_pattern, annotated_text, re.DOTALL):
            field_type_cn = match.group(1)
            content = match.group(2).strip()
            
            field_type = self.FIELD_TYPE_MAPPING.get(field_type_cn, "other")
            
            start_char = match.start()
            end_char = match.end()
            
            speaker = None
            original_speaker = None
            turn_id = None
            turn_index = None
            turn_text = None
            matched_turns = []
            
            turn_index_matches = re.findall(turn_index_pattern, content)
            
            if not turn_index_matches:
                line_start = annotated_text.rfind('\n', 0, start_char) + 1
                line_end = annotated_text.find('\n', start_char)
                if line_end == -1:
                    line_end = len(annotated_text)
                line = annotated_text[line_start:line_end]
                turn_index_matches = re.findall(turn_index_pattern, line)
            
            if turn_index_matches:
                for idx_str in turn_index_matches:
                    idx = int(idx_str)
                    if idx in turn_by_index:
                        turn = turn_by_index[idx]
                        if turn not in matched_turns:
                            matched_turns.append(turn)
                
                matched_turns.sort(key=lambda t: t.turn_index)
                
                if matched_turns:
                    first_turn = matched_turns[0]
                    turn_id = first_turn.turn_id
                    turn_index = first_turn.turn_index
                    original_speaker = first_turn.speaker
                    speaker = correction_map.get(first_turn.turn_index, first_turn.speaker)
                    
                    if len(matched_turns) == 1:
                        turn_text = first_turn.text
                    else:
                        turn_text = "\n".join([
                            f"[{correction_map.get(t.turn_index, t.speaker)}]: {t.text}" 
                            for t in matched_turns
                        ])
                    
                    logger.debug(f"通过turn_index精确匹配: turn_index={turn_index}, content={content[:30]}...")
            
            if turn_id is None:
                logger.warning(f"无法从标注文本中解析turn_index，使用后备匹配: {content[:50]}...")
                matched_turns = self._fallback_match_turns(
                    content, segment, role_mapping, correction_map, field_type
                )
                
                if matched_turns:
                    first_turn = matched_turns[0]
                    turn_id = first_turn.turn_id
                    turn_index = first_turn.turn_index
                    original_speaker = first_turn.speaker
                    speaker = correction_map.get(first_turn.turn_index, first_turn.speaker)
                    
                    if len(matched_turns) == 1:
                        turn_text = first_turn.text
                    else:
                        turn_text = "\n".join([
                            f"[{correction_map.get(t.turn_index, t.speaker)}]: {t.text}" 
                            for t in matched_turns
                        ])
                    
                    logger.debug(f"后备匹配成功: turn_index={turn_index}, content={content[:30]}...")
            
            evidence_trace = {
                "field_type": field_type,
                "field_type_cn": field_type_cn,
                "content": content,
                "speaker": speaker,
                "original_speaker": original_speaker,
                "speaker_corrected": original_speaker is not None and original_speaker != speaker,
                "turn_id": turn_id,
                "turn_index": turn_index,
                "turn_text": turn_text,
                "start_char": start_char,
                "end_char": end_char
            }
            
            evidence_traces.append(evidence_trace)
            logger.debug(f"提取证据: {field_type_cn} - {content[:30]}... (turn_id={turn_id}, turn_index={turn_index})")
        
        return evidence_traces
    
    def _fallback_match_turns(
        self,
        content: str,
        segment: List[TranscriptTurn],
        role_mapping: Dict[str, str],
        correction_map: Dict[int, str],
        field_type: str
    ) -> List[TranscriptTurn]:
        """
        后备匹配方法：当无法从标注文本中解析turn_index时，通过内容匹配找到对应的turn。
        """
        turn_by_speaker = {}
        for turn in segment:
            effective_speaker = correction_map.get(turn.turn_index, turn.speaker)
            if effective_speaker not in turn_by_speaker:
                turn_by_speaker[effective_speaker] = []
            turn_by_speaker[effective_speaker].append(turn)
        
        role_to_speaker = {}
        for spk, role in role_mapping.items():
            if role not in role_to_speaker:
                role_to_speaker[role] = []
            role_to_speaker[role].append(spk)
        
        def find_turns_by_role_label(label: str) -> List[TranscriptTurn]:
            if label in turn_by_speaker:
                return turn_by_speaker[label]
            if label in ["医生", "doctor"]:
                for spk in role_to_speaker.get("doctor", []):
                    if spk in turn_by_speaker:
                        return turn_by_speaker[spk]
            elif label in ["患者", "patient"]:
                for spk in role_to_speaker.get("patient", []):
                    if spk in turn_by_speaker:
                        return turn_by_speaker[spk]
            return []
        
        matched_turns = []
        
        speaker_markers = re.findall(r'\[(spk\d+|医生|患者)\]:\s*([^[]+)', content)
        
        if speaker_markers:
            for spk_label, text_part in speaker_markers:
                text_part = text_part.strip().rstrip('，。,')
                if not text_part:
                    continue
                
                candidate_turns = find_turns_by_role_label(spk_label)
                for turn in candidate_turns:
                    if text_part in turn.text or turn.text in text_part:
                        if turn not in matched_turns:
                            matched_turns.append(turn)
                        break
        
        if not matched_turns:
            clean_content = re.sub(r'<[^>]+>', '', content)
            clean_content = re.sub(r'\[#\d+\]\s*', '', clean_content)
            clean_content = re.sub(r'\[(spk\d+|医生|患者)\]:\s*', '', clean_content)
            clean_content = clean_content.strip()
            
            expected_role = self.FIELD_EXPECTED_ROLE.get(field_type)
            candidate_turns_for_fallback = []
            
            if expected_role:
                for spk, role in role_mapping.items():
                    if role == expected_role:
                        if spk in turn_by_speaker:
                            candidate_turns_for_fallback.extend(turn_by_speaker[spk])
            
            if not candidate_turns_for_fallback:
                candidate_turns_for_fallback = segment
            
            best_match_turn = None
            best_match_score = 0
            
            for turn in candidate_turns_for_fallback:
                if clean_content:
                    turn_text_clean = turn.text.strip()
                    if clean_content in turn_text_clean:
                        match_score = len(clean_content) / len(turn_text_clean) if turn_text_clean else 0
                        if match_score > best_match_score:
                            best_match_score = match_score
                            best_match_turn = turn
            
            if best_match_turn:
                matched_turns.append(best_match_turn)
        
        return matched_turns
    
    def _fallback_role_annotation(self, segment: List[TranscriptTurn]) -> Dict[str, Any]:
        role_mapping = self._infer_roles_by_rules(segment)
        
        annotated_lines = []
        for turn in segment:
            annotated_lines.append(f"[#{turn.turn_index}] [{turn.speaker}]: {turn.text}")
        
        return {
            "role_mapping": role_mapping,
            "annotated_text": "\n".join(annotated_lines)
        }
    
    def _infer_roles_by_rules(self, segment: List[TranscriptTurn]) -> Dict[str, str]:
        doctor_indicators = [
            "请问", "哪里不舒服", "持续多长时间", "有没有", "我给你",
            "量一下", "检查", "诊断", "考虑是", "开点", "注意", "复查",
            "需要", "建议", "治疗"
        ]
        
        patient_indicators = [
            "医生", "我", "头疼", "不舒服", "几天了", "有时候", "没有",
            "好的", "谢谢"
        ]
        
        speaker_scores = {}
        
        for turn in segment:
            speaker = turn.speaker
            if speaker not in speaker_scores:
                speaker_scores[speaker] = {"doctor": 0, "patient": 0}
            
            text = turn.text
            
            for indicator in doctor_indicators:
                if indicator in text:
                    speaker_scores[speaker]["doctor"] += 1
            
            for indicator in patient_indicators:
                if indicator in text:
                    speaker_scores[speaker]["patient"] += 1
            
            if text.endswith("？") or text.endswith("?"):
                speaker_scores[speaker]["doctor"] += 2
            
            if text.startswith("医生"):
                speaker_scores[speaker]["patient"] += 3
        
        role_mapping = {}
        for speaker, scores in speaker_scores.items():
            if scores["doctor"] > scores["patient"]:
                role_mapping[speaker] = "doctor"
            elif scores["patient"] > scores["doctor"]:
                role_mapping[speaker] = "patient"
            else:
                role_mapping[speaker] = "unknown"
        
        return role_mapping
    
    # DEPRECATED: _normalize_terms_stage() has been replaced by a new version that
    # accepts AtomicFact records instead of full text. The old implementation is
    # preserved as _normalize_terms_stage_legacy() for backward compatibility.
    def _normalize_terms_stage_legacy(
        self,
        annotated_text: str,
        role_mapping: Dict[str, str],
        visit_id: str = None,
        save_to_db: bool = True
    ) -> Dict[str, Any]:
        logger.warning("DEPRECATED: _normalize_terms_stage_legacy() is called. Use the new _normalize_terms_stage() with AtomicFact records instead.")
        logger.info(">>> 阶段2(旧): 术语规范化（全文模式）")
        stage_start = time.time()
        
        identified_terms = self.terminology_service.identify_colloquial_terms(annotated_text)
        
        if not identified_terms:
            logger.info("未识别到任何医学术语")
            return {"normalized_text": annotated_text, "terms": []}
        
        logger.info(f"识别到 {len(identified_terms)} 个医学术语")
        
        seen_terms = set()
        unique_terms = []
        for term_info in identified_terms:
            term = term_info.get("term", "")
            if term not in seen_terms:
                seen_terms.add(term)
                unique_terms.append(term_info)
        
        logger.info(f"去重后剩余 {len(unique_terms)} 个术语")
        
        normalized_terms = []
        terms_for_result = []
        
        parallel_enabled = getattr(settings, 'TERMINOLOGY_PARALLEL_ENABLED', True)
        
        if parallel_enabled and self.terminology_service.async_umls_client and len(unique_terms) > 1:
            logger.info("使用并行模式规范化术语")
            
            try:
                normalized_terms = run_async(
                    self._normalize_terms_parallel(unique_terms, annotated_text)
                )
            except Exception as e:
                logger.warning(f"并行规范化失败，回退到串行模式: {e}")
                normalized_terms = self._normalize_terms_serial(unique_terms)
        else:
            logger.info("使用串行模式规范化术语")
            normalized_terms = self._normalize_terms_serial(unique_terms)
        
        for i, normalized in enumerate(normalized_terms):
            term_info = unique_terms[i] if i < len(unique_terms) else {}
            term = term_info.get("term", "")
            term_type = term_info.get("term_type", "unknown")
            is_colloquial = term_info.get("is_colloquial", True)
            
            terms_for_result.append({
                "original": term,
                "normalized": normalized.normalized_term,
                "category": term_type,
                "source": normalized.source,
                "confidence": normalized.confidence,
                "cui": normalized.cui,
                "code": normalized.code,
                "code_system": normalized.code_system,
                "is_colloquial": is_colloquial
            })
            
            logger.info(f"  术语规范化: '{term}' -> '{normalized.normalized_term}' (source: {normalized.source}, confidence: {normalized.confidence:.2f})")
        
        normalized_text = annotated_text
        for term_result in terms_for_result:
            original = term_result["original"]
            normalized = term_result["normalized"]
            if isinstance(normalized, dict):
                logger.warning(f"术语规范化结果为dict类型: original='{original}', normalized={normalized}, 跳过替换")
                continue
            if not isinstance(normalized, str):
                normalized = str(normalized)
                term_result["normalized"] = normalized
            if original and normalized != original:
                normalized_text = normalized_text.replace(original, normalized)
        
        if save_to_db and visit_id and normalized_terms:
            try:
                self.terminology_service.save_normalized_terms(normalized_terms, visit_id)
                logger.info(f"保存了 {len(normalized_terms)} 个规范化术语到数据库")
            except Exception as e:
                logger.error(f"保存规范化术语失败: {e}")
        
        stage_time = time.time() - stage_start
        logger.info(f"术语规范化完成(旧)，共规范化 {len(normalized_terms)} 个术语，耗时: {stage_time:.2f}秒")
        
        return {
            "normalized_text": normalized_text,
            "terms": terms_for_result
        }

    def _normalize_terms_stage(
        self,
        fact_records: List[AtomicFact],
        role_mapping: Dict[str, str],
        visit_id: str = None,
        save_to_db: bool = True
    ) -> Dict[str, Any]:
        logger.info(">>> 阶段3: 选择性术语规范化（基于事实表）")
        stage_start = time.time()

        qualifying_facts = [
            f for f in fact_records
            if f.normalization_needed and f.mention and f.mention.strip()
        ]
        logger.info(f"共 {len(fact_records)} 条事实，其中 {len(qualifying_facts)} 条需要规范化")

        if not qualifying_facts:
            logger.info("没有需要规范化的事实，跳过术语规范化阶段")
            return {
                "terms": [],
                "processed_count": 0,
                "skipped_count": len(fact_records),
                "total_count": len(fact_records)
            }

        terms_for_result = []
        processed_count = 0
        skipped_count = 0

        for fact in qualifying_facts:
            try:
                term_type = fact.concept_type or "unknown"
                result = self.terminology_service.normalize_single_term(
                    term=fact.mention,
                    context="",
                    term_type=term_type
                )

                logger.info(
                    f"  事实规范化: fact_id={fact.fact_id}, "
                    f"'{fact.mention}' -> '{result.normalized_term}' "
                    f"(source: {result.source}, confidence: {result.confidence:.2f})"
                )

                terms_for_result.append({
                    "fact_id": fact.fact_id,
                    "original": fact.mention,
                    "normalized": result.normalized_term,
                    "category": term_type,
                    "source": result.source,
                    "confidence": result.confidence,
                    "cui": result.cui,
                    "code": result.code,
                    "code_system": result.code_system,
                    "section_candidate": fact.section_candidate
                })

                if save_to_db and self.db:
                    fact.normalized_term = result.normalized_term
                    fact.normalized_code = result.code
                    fact.normalization_needed = False

                processed_count += 1

            except Exception as e:
                logger.error(f"规范化事实 {fact.fact_id} (mention='{fact.mention}') 失败: {e}")
                skipped_count += 1

        if save_to_db and self.db:
            try:
                self.db.commit()
                logger.info(f"已更新 {processed_count} 条原子事实的规范化结果到数据库")
            except Exception as e:
                self.db.rollback()
                logger.error(f"保存原子事实规范化结果失败: {e}")

        stage_time = time.time() - stage_start
        logger.info(
            f"选择性术语规范化完成: 处理 {processed_count} 条, "
            f"跳过 {skipped_count} 条, 总事实 {len(fact_records)} 条, "
            f"耗时: {stage_time:.2f}秒"
        )

        return {
            "terms": terms_for_result,
            "processed_count": processed_count,
            "skipped_count": skipped_count,
            "total_count": len(fact_records)
        }

    # DEPRECATED: _normalize_terms_serial() is part of the old full-text
    # normalization pipeline. Preserved for backward compatibility, replaced
    # by the selective per-fact approach in the new _normalize_terms_stage().
    def _normalize_terms_serial(self, unique_terms: List[Dict[str, Any]]) -> List[Any]:
        """串行规范化术语（旧版，已弃用）"""
        logger.warning("DEPRECATED: _normalize_terms_serial() is called. Use the new _normalize_terms_stage() with AtomicFact records instead.")
        normalized_terms = []
        for term_info in unique_terms:
            term = term_info.get("term", "")
            term_type = term_info.get("term_type", "unknown")
            context = term_info.get("context", "")
            
            normalized = self.terminology_service.normalize_term(term, context, term_type)
            normalized_terms.append(normalized)
        
        return normalized_terms
    
    async def _normalize_terms_parallel(self, unique_terms: List[Dict[str, Any]], context: str) -> List[Any]:
        """并行规范化术语（旧版，已弃用） - 优先使用中文术语搜索"""
        logger.warning("DEPRECATED: _normalize_terms_parallel() is called. Use the new _normalize_terms_stage() with AtomicFact records instead.")
        terms = [t.get("term", "") for t in unique_terms]
        contexts = {t.get("term", ""): t.get("context", context) for t in unique_terms}
        term_types = {t.get("term", ""): t.get("term_type", "unknown") for t in unique_terms}
        
        chinese_results = {}
        if self.terminology_service.chinese_term_client:
            chinese_start = time.time()
            chinese_results = self.terminology_service.chinese_term_client.batch_search(terms)
            matched_count = sum(1 for r in chinese_results.values() if r is not None)
            logger.info(f"中文术语批量搜索完成: {matched_count}/{len(terms)} 匹配, 耗时: {time.time() - chinese_start:.2f}秒")
        
        umls_results = {}
        if self.terminology_service.async_umls_client:
            unmatched_terms = [t for t in terms if t not in chinese_results or chinese_results[t] is None]
            if unmatched_terms:
                search_start = time.time()
                umls_results = await self.terminology_service.async_umls_client.batch_search(
                    unmatched_terms,
                    language="ENG"
                )
                logger.info(f"并行UMLS检索完成（{len(unmatched_terms)}个未匹配术语）, 耗时: {time.time() - search_start:.2f}秒")
        
        term_candidates = {}
        for term in terms:
            if term in umls_results:
                result = umls_results.get(term)
                if result and hasattr(result, 'candidates') and result.candidates:
                    term_candidates[term] = result.candidates[:5]
        
        selections = {}
        if term_candidates and self.llm_service:
            select_start = time.time()
            selections = self.terminology_service._batch_select_candidates(term_candidates, contexts, {})
            logger.info(f"批量LLM选择完成，耗时: {time.time() - select_start:.2f}秒")
        
        code_tasks = {}
        for term in terms:
            if term in selections:
                code_tasks[term] = self.terminology_service._async_get_code_from_candidate(selections[term])
        
        code_results = {}
        if code_tasks:
            import asyncio
            code_start = time.time()
            code_results_list = await asyncio.gather(*code_tasks.values(), return_exceptions=True)
            for term, result in zip(code_tasks.keys(), code_results_list):
                if isinstance(result, Exception):
                    logger.warning(f"获取code失败 for {term}: {result}")
                    code_results[term] = (None, None)
                else:
                    code_results[term] = result
            logger.info(f"并行获取code完成，耗时: {time.time() - code_start:.2f}秒")
        
        normalized_terms = []
        for term_info in unique_terms:
            term = term_info.get("term", "")
            term_type = term_types.get(term, "unknown")
            
            normalized = term
            confidence = 0.3
            reasoning = "无法规范化，保留原术语"
            code = None
            code_system = None
            source = "none"
            candidates_data = None
            cui = None
            
            if term in chinese_results and chinese_results[term]:
                chinese_result = chinese_results[term]
                normalized = chinese_result.matched_term
                confidence = chinese_result.confidence
                code = chinese_result.code
                code_system = chinese_result.code_system
                source = "ChineseTerm"
                
                match_type_desc = "精确匹配" if chinese_result.match_type == "exact" else "同义词匹配" if chinese_result.match_type == "synonym" else "模糊匹配"
                reasoning = f"中文术语库{match_type_desc}: {term} -> {normalized}"
                if code:
                    reasoning += f" ({code_system}: {code})"
                
                if chinese_result.candidates:
                    candidates_data = [
                        {
                            "term": c.term,
                            "code": c.code,
                            "code_system": c.code_system,
                            "term_type": c.term_type,
                            "source": c.source
                        }
                        for c in chinese_result.candidates[:5]
                    ]
                
                logger.info(f"ChineseTerm并行规范化: '{term}' -> '{normalized}' (confidence: {confidence:.2f})")
            
            elif term in selections:
                best_candidate = selections[term]
                code, code_system = code_results.get(term, (None, None))
                
                candidates = term_candidates.get(term, [])
                candidates_data = [
                    {
                        "term": c.term,
                        "cui": c.cui,
                        "score": c.score,
                        "preferred": c.preferred
                    }
                    for c in candidates
                ]
                
                confidence = min(0.95, 0.6 + best_candidate.score * 0.35)
                reasoning = f"UMLS匹配: {term} -> {best_candidate.term} (CUI: {best_candidate.cui})"
                source = "UMLS"
                cui = best_candidate.cui
                normalized = best_candidate.term
            
            elif confidence < 0.5 and self.llm_service:
                llm_result = self.terminology_service._normalize_by_llm(term, contexts.get(term, ""))
                if llm_result and llm_result[1] > confidence:
                    normalized, confidence, reasoning = llm_result
                    source = "LLM"
            
            is_risky = confidence < 0.5
            
            from ..models import NormalizedTerm
            normalized_term = NormalizedTerm(
                original_term=term,
                normalized_term=normalized,
                term_type=term_type,
                confidence=confidence,
                is_risky=is_risky,
                reasoning=reasoning,
                code=code,
                code_system=code_system,
                source=source,
                candidates=candidates_data,
                cui=cui
            )
            normalized_terms.append(normalized_term)
        
        return normalized_terms
    
    # DEPRECATED: _build_normalization_prompt() was used in the old full-text
    # normalization pipeline. Now replaced by the selective per-fact approach
    # in the new _normalize_terms_stage() which calls normalize_single_term().
    def _build_normalization_prompt(self, annotated_text: str) -> str:
        logger.warning("DEPRECATED: _build_normalization_prompt() is called. Use normalize_single_term() instead.")
        return f"""你是一个医学术语规范化专家。请将以下标注文本中的口语化医学术语规范化为标准医学术语。

## 标注文本
{annotated_text}

## 任务要求
1. 识别文本中的口语化医学术语（如"头疼"->"头痛"，"血压高"->"高血压"）
2. 将口语化术语替换为标准医学术语
3. 保持XML标签不变
4. 保持对话格式不变

## 输出格式
请按以下JSON格式输出：
{{
  "normalized_text": "规范化后的完整文本",
  "terms": [
    {{
      "original": "原始术语",
      "normalized": "标准术语",
      "category": "症状|药物|诊断|检查|其他"
    }}
  ]
}}

注意：
1. 只规范化医学术语，不要修改其他内容
2. 保持原文的语义和语气
3. 如果术语已经是标准形式，不需要修改"""
    
    def _parse_normalization_response(
        self,
        response_text: str,
        original_text: str
    ) -> Dict[str, Any]:
        result = self._extract_json_from_response(response_text, "术语规范化")
        
        if result:
            return {
                "normalized_text": result.get("normalized_text", original_text),
                "terms": result.get("terms", [])
            }
        
        return {"normalized_text": original_text, "terms": []}
    
    # DEPRECATED: 阶段3字段抽取已被阶段2(fact_extraction)替代。
    # 事实表本身已是结构化数据，不再需要从文本中抽取字段。
    # 当前仅保留以防兼容性需要，不再在新流程中使用。
    def _extract_fields_stage(
        self,
        normalized_text: str,
        role_mapping: Dict[str, str],
        evidence_traces: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        logger.info(">>> 阶段3: 字段抽取")
        
        prompt = self._build_extraction_prompt(normalized_text, role_mapping)
        
        if self.debug_mode:
            response_text = self._debug_interact(
                stage="field_extraction",
                prompt=prompt,
                normalized_text=normalized_text
            )
        else:
            if not self.llm_service:
                logger.warning("LLM服务不可用，使用规则抽取")
                return self._fallback_extraction(normalized_text, evidence_traces)
            
            try:
                response = self.llm_service.generate(prompt)
                response_text = response.text
            except Exception as e:
                logger.error(f"字段抽取LLM调用失败: {e}")
                return self._fallback_extraction(normalized_text, evidence_traces)
        
        return self._parse_extraction_response(response_text, evidence_traces)
    
    def _build_extraction_prompt(
        self,
        normalized_text: str,
        role_mapping: Dict[str, str]
    ) -> str:
        role_desc = "\n".join([f"- {spk}: {role}" for spk, role in role_mapping.items()])
        
        return f"""你是一个医疗病历生成专家。请从以下规范化文本中抽取病历字段。

## 角色映射
{role_desc}

## 规范化文本
{normalized_text}

## 任务要求
1. 从XML标签中提取对应字段的内容
2. 合并相同字段的内容（去重）
3. 处理可能的冲突（保留更详细、更准确的内容）
4. 为每个字段标注来源说话人

## 输出格式
请按以下JSON格式输出：
{{
  "subjective": {{
    "chief_complaint": {{
      "value": "主诉内容",
      "speaker": "说话人ID",
      "confidence": 0.0-1.0
    }},
    "history_present_illness": {{
      "value": "现病史内容",
      "speaker": "说话人ID",
      "confidence": 0.0-1.0
    }},
    "past_history": {{
      "value": "既往史内容",
      "speaker": "说话人ID",
      "confidence": 0.0-1.0
    }}
  }},
  "objective": {{
    "physical_examination": {{
      "value": "体格检查内容",
      "speaker": "说话人ID",
      "confidence": 0.0-1.0
    }},
    "auxiliary_examination": {{
      "value": "辅助检查内容",
      "speaker": "说话人ID",
      "confidence": 0.0-1.0
    }}
  }},
  "assessment": {{
    "diagnosis": {{
      "value": "诊断内容",
      "speaker": "说话人ID",
      "confidence": 0.0-1.0
    }}
  }},
  "plan": {{
    "treatment": {{
      "value": "治疗方案",
      "speaker": "说话人ID",
      "confidence": 0.0-1.0
    }},
    "advice": {{
      "value": "医嘱内容",
      "speaker": "说话人ID",
      "confidence": 0.0-1.0
    }}
  }}
}}

注意：
1. 如果某个字段没有内容，value设为空字符串
2. confidence表示对抽取结果的置信度
3. 确保抽取的内容与角色匹配（主诉来自患者，诊断来自医生等）"""
    
    def _parse_extraction_response(
        self,
        response_text: str,
        evidence_traces: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        result = self._extract_json_from_response(response_text, "字段抽取")
        
        if result:
            result = self._attach_evidence_traces(result, evidence_traces)
            return result
        
        return self._fallback_extraction("", evidence_traces)
    
    def _attach_evidence_traces(
        self,
        extraction_result: Dict[str, Any],
        evidence_traces: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        field_to_section = {
            "chief_complaint": "subjective",
            "history_present_illness": "subjective",
            "past_history": "subjective",
            "physical_examination": "objective",
            "auxiliary_examination": "objective",
            "diagnosis": "assessment",
            "treatment": "plan",
            "advice": "plan",
            "other": None
        }
        
        for trace in evidence_traces:
            field_type = trace.get("field_type")
            section = field_to_section.get(field_type)
            
            if section and section in extraction_result:
                field_data = extraction_result[section].get(field_type, {})
                
                if "evidence_traces" not in field_data:
                    field_data["evidence_traces"] = []
                
                field_data["evidence_traces"].append({
                    "turn_id": trace.get("turn_id"),
                    "turn_index": trace.get("turn_index"),
                    "turn_text": trace.get("turn_text"),
                    "speaker": trace.get("speaker"),
                    "content": trace.get("content"),
                    "start_char": trace.get("start_char"),
                    "end_char": trace.get("end_char"),
                    "confidence": trace.get("confidence", 0.5)
                })
                
                extraction_result[section][field_type] = field_data
        
        return extraction_result
    
    def _fallback_extraction(
        self,
        text: str,
        evidence_traces: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        result = {
            "subjective": {
                "chief_complaint": {"value": "", "speaker": "", "confidence": 0.0},
                "history_present_illness": {"value": "", "speaker": "", "confidence": 0.0},
                "past_history": {"value": "", "speaker": "", "confidence": 0.0}
            },
            "objective": {
                "physical_examination": {"value": "", "speaker": "", "confidence": 0.0},
                "auxiliary_examination": {"value": "", "speaker": "", "confidence": 0.0}
            },
            "assessment": {
                "diagnosis": {"value": "", "speaker": "", "confidence": 0.0}
            },
            "plan": {
                "treatment": {"value": "", "speaker": "", "confidence": 0.0},
                "advice": {"value": "", "speaker": "", "confidence": 0.0}
            }
        }
        
        return self._attach_evidence_traces(result, evidence_traces)
    
    # DEPRECATED: _generate_emr_stage() has been replaced by _generate_so_stage() and _generate_ap_stage().
    # The new approach splits SOAP generation into two steps: (4a) S+O first, then (4b) A+P based on S+O.
    # This method is preserved for backward compatibility.
    def _generate_emr_stage(
        self,
        extraction_result: Dict[str, Any],
        role_mapping: Dict[str, str],
        turns: List[TranscriptTurn],
        visit_id: str,
        save_evidence: bool = True,
        dialogue_text: str = ""
    ) -> Dict[str, Any]:
        logger.warning("DEPRECATED: _generate_emr_stage() is called. Use _generate_so_stage() and _generate_ap_stage() instead.")
        logger.info(">>> 阶段4: 病历生成")
        
        prompt = self._build_emr_generation_prompt(extraction_result, role_mapping, dialogue_text)
        
        if self.debug_mode:
            response_text = self._debug_interact(
                stage="emr_generation",
                prompt=prompt,
                extraction_result=extraction_result
            )
        else:
            if not self.llm_service:
                logger.warning("LLM服务不可用，使用模板生成")
                return self._template_emr_generation(extraction_result, visit_id, save_evidence)
            
            try:
                response = self.llm_service.generate(prompt)
                response_text = response.text
            except Exception as e:
                logger.error(f"病历生成LLM调用失败: {e}")
                return self._template_emr_generation(extraction_result, visit_id, save_evidence)
        
        return self._parse_emr_response(response_text, extraction_result, visit_id, save_evidence)
    
    # DEPRECATED: _build_emr_generation_prompt() has been replaced by the new prompt templates
    # emr_generation_so, emr_generation_assessment, and emr_generation_plan.
    # These new templates enable the three-level diagnosis strategy and structured plan.
    def _build_emr_generation_prompt(
        self,
        extraction_result: Dict[str, Any],
        role_mapping: Dict[str, str],
        dialogue_text: str = ""
    ) -> str:
        logger.warning("DEPRECATED: _build_emr_generation_prompt() is called. Use emr_generation_so/assessment/plan templates instead.")
        extraction_json = json.dumps(extraction_result, ensure_ascii=False, indent=2)
        
        return f"""你是一个医疗病历撰写专家。请根据以下信息生成符合中国医疗病历书写规范的病历文本。

## 原始对话
{dialogue_text}

## 结构化数据
{extraction_json}

## 任务要求
1. 生成自然流畅的病历文本
2. 符合SOAP格式（主观数据、客观数据、评估、计划）
3. 使用规范的医学术语
4. 保持内容的准确性和完整性

## 诊断推断要求（重要）
诊断字段需要结合上下文进行综合推断，而不是简单复述对话中提到的诊断：

1. **综合分析**：结合症状持续时间、症状特点、治疗效果、既往病史等信息进行综合判断
2. **症状演变**：注意症状的发展过程，如"时好时坏"、"反复发作"等提示慢性或迁延性疾病
3. **治疗反应**：关注患者对治疗的反应，如"未痊愈"、"效果不佳"等提示可能需要调整诊断
4. **医生建议**：重视医生在对话中提到的后续检查建议和可能的诊断方向
5. **证据溯源**：诊断必须基于原始对话中的证据，不能凭空编造

**示例**：
- 对话中患者提到"医生诊断为上呼吸道感染，但至今未痊愈，时好时坏"
- 医生后续建议检查支原体，提到"支原体感染会导致反复呼吸道感染"
- 患者提到"孩子一直特别容易咳嗽"
- 综合判断：症状持续时间长、反复发作、医生建议检查支原体，更倾向于支气管炎

## 重要约束
1. **严禁幻觉**：只能使用上述结构化数据中明确存在的内容，绝对不能添加、编造或推测任何原文中没有的信息
2. **内容一致性**：生成的病历内容必须完全来自结构化数据，不能添加任何额外的描述、推断或假设
3. **空字段处理**：如果某个字段在结构化数据中为空或不存在，则该字段保持为空，不要编造内容
4. **忠实原文**：病历内容必须忠实于原始对话，不能添加患者未提及的症状、医生未做出的诊断等
5. **诊断推断例外**：诊断字段可以根据上下文进行综合推断，但必须有充分的证据支持

## 输出格式
请按以下JSON格式输出：
{{
  "subjective": {{
    "text": "主观数据部分的病历文本",
    "chief_complaint": "主诉",
    "history_present_illness": "现病史",
    "past_history": "既往史"
  }},
  "objective": {{
    "text": "客观数据部分的病历文本",
    "physical_examination": "体格检查",
    "auxiliary_examination": "辅助检查"
  }},
  "assessment": {{
    "text": "评估部分的病历文本",
    "diagnosis": "诊断"
  }},
  "plan": {{
    "text": "计划部分的病历文本",
    "treatment": "治疗方案",
    "advice": "医嘱"
  }}
}}

注意：
1. text字段应该是完整的病历段落，适合直接展示
2. 各子字段是结构化的数据
3. 如果某个字段为空，可以省略或写"未见异常"等，但不要编造任何内容"""
    
    def _parse_emr_response(
        self,
        response_text: str,
        extraction_result: Dict[str, Any],
        visit_id: str = None,
        save_evidence: bool = True
    ) -> Dict[str, Any]:
        result = self._extract_json_from_response(response_text, "病历生成")
        
        if result:
            result = self._attach_evidence_to_emr(result, extraction_result)
            
            if save_evidence and visit_id:
                self._save_evidence_spans(extraction_result, visit_id, result)
                self._save_emr_record(result, visit_id)
            
            return result
        
        return self._template_emr_generation(extraction_result, visit_id, save_evidence)
    
    def _attach_evidence_to_emr(
        self,
        emr_result: Dict[str, Any],
        extraction_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        for section in ["subjective", "objective", "assessment", "plan"]:
            if section in emr_result and section in extraction_result:
                for field_name, field_data in extraction_result[section].items():
                    if isinstance(field_data, dict) and "evidence_traces" in field_data:
                        evidence_traces = field_data["evidence_traces"]
                        
                        if field_name in emr_result[section]:
                            if isinstance(emr_result[section][field_name], str):
                                emr_result[section][field_name] = {
                                    "value": emr_result[section][field_name],
                                    "evidence_traces": evidence_traces
                                }
                            else:
                                emr_result[section][field_name]["evidence_traces"] = evidence_traces
        
        return emr_result
    
    def _save_evidence_spans(
        self,
        extraction_result: Dict[str, Any],
        visit_id: str,
        emr_result: Dict[str, Any] = None
    ) -> int:
        saved_count = 0
        
        self.db.query(EvidenceSpan).filter(
            EvidenceSpan.visit_id == visit_id
        ).delete()
        
        for section in ["subjective", "objective", "assessment", "plan"]:
            if section not in extraction_result:
                continue
            
            for field_name, field_data in extraction_result[section].items():
                if not isinstance(field_data, dict):
                    continue
                
                evidence_traces = field_data.get("evidence_traces", [])
                
                field_value = None
                if emr_result and section in emr_result:
                    field_info = emr_result[section].get(field_name, {})
                    if isinstance(field_info, dict):
                        field_value = field_info.get("value", "")
                    elif isinstance(field_info, str):
                        field_value = field_info
                
                for trace in evidence_traces:
                    turn_id = trace.get("turn_id")
                    turn_index = trace.get("turn_index")
                    
                    if turn_id is None and turn_index is not None:
                        turn = self.db.query(TranscriptTurn).filter(
                            TranscriptTurn.visit_id == visit_id,
                            TranscriptTurn.turn_index == turn_index
                        ).first()
                        if turn:
                            turn_id = turn.turn_id
                            logger.debug(f"通过turn_index找到turn_id: turn_index={turn_index}, turn_id={turn_id}")
                    
                    if turn_id is None:
                        logger.warning(f"证据溯源跳过: 无法找到对应的turn_id, field={field_name}, content={trace.get('content', '')[:30]}...")
                        continue
                    
                    evidence = EvidenceSpan(
                        visit_id=visit_id,
                        turn_id=turn_id,
                        field_type=field_name,
                        field_value=field_value,
                        content=trace.get("content", ""),
                        turn_text=trace.get("turn_text", ""),
                        start_char=trace.get("start_char"),
                        end_char=trace.get("end_char"),
                        confidence=trace.get("confidence", 0.8),
                        score=trace.get("confidence", 0.8),
                        reasoning=f"来源: {trace.get('speaker', 'unknown')}"
                    )
                    
                    self.db.add(evidence)
                    saved_count += 1
        
        try:
            self.db.commit()
            logger.info(f"保存了 {saved_count} 条证据溯源记录到数据库")
        except Exception as e:
            self.db.rollback()
            logger.error(f"保存证据溯源记录失败: {e}")
        
        return saved_count
    
    def _save_emr_record(
        self,
        emr_result: Dict[str, Any],
        visit_id: str
    ) -> Optional[EMRRecord]:
        try:
            from ..models import Visit
            visit = self.db.query(Visit).filter(Visit.visit_id == visit_id).first()
            language = visit.language if visit and visit.language else "zh"
            
            validation_result = self.validation_service.validate(emr_result, language=language)
            validation_errors = self.validation_service.to_dict(validation_result)
            
            max_version = self.db.query(EMRRecord).filter(
                EMRRecord.visit_id == visit_id
            ).count()
            
            new_version = max_version + 1
            
            emr_record = EMRRecord(
                visit_id=visit_id,
                version=new_version,
                record_type="llm_generated",
                emr_json=emr_result,
                evidence_mapping=None,
                validation_errors=validation_errors
            )
            
            self.db.add(emr_record)
            self.db.commit()
            
            logger.info(f"保存病历记录成功: visit_id={visit_id}, version={new_version}, 验证评分: {validation_result.score:.2%}")
            return emr_record
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"保存病历记录失败: {e}")
            return None
    
    def _normalize_emr_format(self, emr_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        将分节生成的新格式归一化为前端兼容的旧格式。
        
        前端 displaySection() 期望每个子字段为 {value, evidence_traces} 格式。
        新prompt输出的是直接字符串，需要包装。
        Assessment 从 assessment_items 构建 diagnosis 字段。
        Plan 从 plan_items 构建 treatment 和 advice 字段。
        """
        result = dict(emr_result)
        
        subject_section = dict(result.get("subjective", {}))
        objective_section = dict(result.get("objective", {}))
        assessment_section = dict(result.get("assessment", {}))
        plan_section = dict(result.get("plan", {}))
        
        for section_data, section_name in [
            (subject_section, "subjective"),
            (objective_section, "objective")
        ]:
            for field, val in list(section_data.items()):
                if field in ("text", "evidence_traces"):
                    continue
                if isinstance(val, str):
                    section_data[field] = {"value": val or "", "evidence_traces": []}
        
        assessment_items = result.get("assessment_items", [])
        if assessment_items:
            explicit_diags = [item for item in assessment_items if item.get("diagnosis_type") == "explicit_diagnosis"]
            suspected_diags = [item for item in assessment_items if item.get("diagnosis_type") == "suspected_diagnosis"]
            symptom_assessments = [item for item in assessment_items if item.get("diagnosis_type") == "symptom_based_assessment"]
            
            diagnosis_parts = []
            for diag in explicit_diags:
                diagnosis_parts.append(diag.get("text", ""))
            for diag in suspected_diags:
                diagnosis_parts.append(diag.get("text", ""))
            for diag in symptom_assessments:
                diagnosis_parts.append(diag.get("text", ""))
            
            diagnosis_value = "；".join(filter(None, diagnosis_parts))
            if diagnosis_value:
                assessment_section["diagnosis"] = {"value": diagnosis_value, "evidence_traces": []}
        
        plan_items = result.get("plan_items", {})
        if plan_items:
            medications = plan_items.get("medications", [])
            tests = plan_items.get("tests", [])
            follow_up = plan_items.get("follow_up", {})
            education = plan_items.get("education", {})
            
            treatment_parts = []
            for med in medications:
                if isinstance(med, dict):
                    parts = [med.get("name", "")]
                    dosage = med.get("dosage", "")
                    freq = med.get("frequency", "")
                    duration = med.get("duration", "")
                    detail = " ".join(filter(None, [dosage, freq, duration]))
                    if detail:
                        parts.append(detail)
                    treatment_parts.append(" ".join(filter(None, parts)))
            for test in tests:
                if isinstance(test, dict):
                    name = test.get("name", "")
                    reason = test.get("reason", "")
                    if name:
                        treatment_parts.append(f"{name}（{reason}）" if reason else name)
            
            treatment_value = "；".join(filter(None, treatment_parts))
            if treatment_value:
                plan_section["treatment"] = {"value": treatment_value, "evidence_traces": []}
            
            advice_parts = []
            if isinstance(follow_up, dict) and follow_up.get("text"):
                advice_parts.append(follow_up["text"])
            if isinstance(education, dict) and education.get("text"):
                advice_parts.append(education["text"])
            
            advice_value = "；".join(filter(None, advice_parts))
            if advice_value:
                plan_section["advice"] = {"value": advice_value, "evidence_traces": []}
        
        result["subjective"] = subject_section
        result["objective"] = objective_section
        result["assessment"] = assessment_section
        result["plan"] = plan_section
        
        logger.info(f"EMR格式归一化完成"
                    f", assessment_items={len(assessment_items)}"
                    f", plan_medications={len(plan_items.get('medications', [])) if plan_items else 0}"
                    f", plan_tests={len(plan_items.get('tests', [])) if plan_items else 0}")
        return result

    def _build_evidence_traces_from_fact_ids(
        self,
        fact_ids: set,
        fact_by_id: Dict[str, AtomicFact],
        turn_by_index: Dict[int, TranscriptTurn]
    ) -> List[Dict[str, Any]]:
        traces = []
        seen_turn_ids = set()

        for fid in fact_ids:
            fact = fact_by_id.get(fid)
            if not fact:
                continue

            turn_ids = fact.evidence_turn_ids or []
            evidence_texts = fact.evidence_text or []

            for i, tid in enumerate(turn_ids):
                if tid in seen_turn_ids:
                    continue
                seen_turn_ids.add(tid)

                turn = turn_by_index.get(tid)
                if not turn:
                    continue

                trace = {
                    "turn_id": turn.turn_id,
                    "turn_index": turn.turn_index,
                    "turn_text": turn.text,
                    "speaker": turn.corrected_speaker or turn.speaker,
                    "original_speaker": turn.speaker,
                    "speaker_corrected": bool(
                        turn.corrected_speaker
                        and turn.corrected_speaker != turn.speaker
                    ),
                    "content": evidence_texts[i] if i < len(evidence_texts) else turn.text[:100],
                    "confidence": 0.8
                }
                traces.append(trace)

        logger.info(f"从 {len(fact_ids)} 个fact_id构建了 {len(traces)} 条证据溯源")
        return traces

    def _enrich_evidence_traces(
        self,
        emr_result: Dict[str, Any],
        fact_records: List[AtomicFact],
        turns: List[TranscriptTurn]
    ) -> Dict[str, Any]:
        logger.info("开始证据溯源富化")
        enrichment_start = time.time()

        fact_by_id = {f.fact_id: f for f in fact_records}
        turn_by_index = {t.turn_index: t for t in turns}

        so_used_fact_ids = emr_result.get("so_used_fact_ids", [])
        assessment_items = emr_result.get("assessment_items", [])
        plan_items = emr_result.get("plan_items", {})

        logger.info(
            f"证据溯源输入: so_fact_ids={len(so_used_fact_ids)}, "
            f"assessment_items={len(assessment_items)}, "
            f"plan_items_keys={list(plan_items.keys()) if plan_items else []}"
        )

        s_fact_ids = set()
        o_fact_ids = set()
        for fid in so_used_fact_ids:
            fact = fact_by_id.get(fid)
            if fact:
                if fact.section_candidate == "S":
                    s_fact_ids.add(fid)
                elif fact.section_candidate == "O":
                    o_fact_ids.add(fid)

        s_evidence_traces = self._build_evidence_traces_from_fact_ids(
            s_fact_ids, fact_by_id, turn_by_index
        )
        o_evidence_traces = self._build_evidence_traces_from_fact_ids(
            o_fact_ids, fact_by_id, turn_by_index
        )

        subject_section = dict(emr_result.get("subjective", {}))
        for field in ["chief_complaint", "history_present_illness", "past_history", "denied_symptoms"]:
            if field in subject_section and isinstance(subject_section[field], dict):
                subject_section[field]["evidence_traces"] = s_evidence_traces

        objective_section = dict(emr_result.get("objective", {}))
        for field in ["physical_examination", "auxiliary_examination"]:
            if field in objective_section and isinstance(objective_section[field], dict):
                objective_section[field]["evidence_traces"] = o_evidence_traces

        diagnosis_fact_ids = set()
        for item in assessment_items:
            if isinstance(item, dict):
                sids = item.get("supporting_fact_ids", [])
                diagnosis_fact_ids.update(sids)
        a_evidence_traces = self._build_evidence_traces_from_fact_ids(
            diagnosis_fact_ids, fact_by_id, turn_by_index
        )

        assessment_section = dict(emr_result.get("assessment", {}))
        if "diagnosis" in assessment_section and isinstance(assessment_section["diagnosis"], dict):
            assessment_section["diagnosis"]["evidence_traces"] = a_evidence_traces

        treatment_fact_ids = set()
        advice_fact_ids = set()

        if isinstance(plan_items, dict):
            for med in plan_items.get("medications", []):
                if isinstance(med, dict):
                    treatment_fact_ids.update(med.get("used_fact_ids", []))
            for test in plan_items.get("tests", []):
                if isinstance(test, dict):
                    treatment_fact_ids.update(test.get("used_fact_ids", []))
            follow_up = plan_items.get("follow_up", {})
            if isinstance(follow_up, dict):
                advice_fact_ids.update(follow_up.get("used_fact_ids", []))
            education = plan_items.get("education", {})
            if isinstance(education, dict):
                advice_fact_ids.update(education.get("used_fact_ids", []))

        t_evidence_traces = self._build_evidence_traces_from_fact_ids(
            treatment_fact_ids, fact_by_id, turn_by_index
        )
        adv_evidence_traces = self._build_evidence_traces_from_fact_ids(
            advice_fact_ids, fact_by_id, turn_by_index
        )

        plan_section = dict(emr_result.get("plan", {}))
        if "treatment" in plan_section and isinstance(plan_section["treatment"], dict):
            plan_section["treatment"]["evidence_traces"] = t_evidence_traces
        if "advice" in plan_section and isinstance(plan_section["advice"], dict):
            plan_section["advice"]["evidence_traces"] = adv_evidence_traces

        emr_result["subjective"] = subject_section
        emr_result["objective"] = objective_section
        emr_result["assessment"] = assessment_section
        emr_result["plan"] = plan_section

        total_traces = (
            len(s_evidence_traces)
            + len(o_evidence_traces)
            + len(a_evidence_traces)
            + len(t_evidence_traces)
            + len(adv_evidence_traces)
        )
        logger.info(
            f"证据溯源富化完成: S={len(s_evidence_traces)}, O={len(o_evidence_traces)}, "
            f"A={len(a_evidence_traces)}, P_T={len(t_evidence_traces)}, P_Adv={len(adv_evidence_traces)}, "
            f"总计={total_traces}, 耗时={time.time() - enrichment_start:.2f}秒"
        )

        return emr_result

    def _save_evidence_spans_from_emr(
        self,
        emr_result: Dict[str, Any],
        visit_id: str
    ) -> int:
        logger.info(f"保存证据溯源记录到EvidenceSpan表: visit_id={visit_id}")

        self.db.query(EvidenceSpan).filter(
            EvidenceSpan.visit_id == visit_id
        ).delete()

        saved_count = 0
        field_to_section_name = {}
        for section_name in ["subjective", "objective", "assessment", "plan"]:
            section = emr_result.get(section_name, {})
            for field_name in section.keys():
                if field_name not in ("text", "evidence_traces"):
                    field_to_section_name[field_name] = section_name

        for section_name in ["subjective", "objective", "assessment", "plan"]:
            section = emr_result.get(section_name, {})
            for field_name, field_data in section.items():
                if field_name in ("text", "evidence_traces"):
                    continue
                if not isinstance(field_data, dict):
                    continue

                traces = field_data.get("evidence_traces", [])
                field_value = field_data.get("value", "")

                for trace in traces:
                    evidence = EvidenceSpan(
                        visit_id=visit_id,
                        turn_id=trace.get("turn_id"),
                        field_type=field_name,
                        field_value=field_value,
                        content=trace.get("content", ""),
                        turn_text=trace.get("turn_text", ""),
                        confidence=trace.get("confidence", 0.8),
                        score=trace.get("confidence", 0.8),
                        reasoning=f"来源: {trace.get('speaker', 'unknown')}"
                    )
                    self.db.add(evidence)
                    saved_count += 1

        try:
            self.db.commit()
            logger.info(f"保存了 {saved_count} 条证据溯源记录到EvidenceSpan表")
        except Exception as e:
            self.db.rollback()
            logger.error(f"保存证据溯源记录失败: {e}")
            return 0

        return saved_count

    def _template_emr_generation(
        self,
        extraction_result: Dict[str, Any],
        visit_id: str = None,
        save_evidence: bool = True
    ) -> Dict[str, Any]:
        def get_value(section: str, field: str) -> str:
            try:
                return extraction_result.get(section, {}).get(field, {}).get("value", "")
            except:
                return ""
        
        def get_evidence_traces(section: str, field: str) -> List[Dict[str, Any]]:
            try:
                return extraction_result.get(section, {}).get(field, {}).get("evidence_traces", [])
            except:
                return []
        
        chief_complaint = get_value("subjective", "chief_complaint")
        history = get_value("subjective", "history_present_illness")
        past_history = get_value("subjective", "past_history")
        physical = get_value("objective", "physical_examination")
        auxiliary = get_value("objective", "auxiliary_examination")
        diagnosis = get_value("assessment", "diagnosis")
        treatment = get_value("plan", "treatment")
        advice = get_value("plan", "advice")
        
        subjective_text = []
        if chief_complaint:
            subjective_text.append(f"主诉：{chief_complaint}")
        if history:
            subjective_text.append(f"现病史：{history}")
        if past_history:
            subjective_text.append(f"既往史：{past_history}")
        
        objective_text = []
        if physical:
            objective_text.append(f"体格检查：{physical}")
        if auxiliary:
            objective_text.append(f"辅助检查：{auxiliary}")
        
        assessment_text = f"诊断：{diagnosis}" if diagnosis else "诊断：待定"
        
        plan_text = []
        if treatment:
            plan_text.append(f"治疗方案：{treatment}")
        if advice:
            plan_text.append(f"医嘱：{advice}")
        
        result = {
            "subjective": {
                "text": "\n".join(subjective_text),
                "chief_complaint": {
                    "value": chief_complaint,
                    "evidence_traces": get_evidence_traces("subjective", "chief_complaint")
                },
                "history_present_illness": {
                    "value": history,
                    "evidence_traces": get_evidence_traces("subjective", "history_present_illness")
                },
                "past_history": {
                    "value": past_history,
                    "evidence_traces": get_evidence_traces("subjective", "past_history")
                }
            },
            "objective": {
                "text": "\n".join(objective_text),
                "physical_examination": {
                    "value": physical,
                    "evidence_traces": get_evidence_traces("objective", "physical_examination")
                },
                "auxiliary_examination": {
                    "value": auxiliary,
                    "evidence_traces": get_evidence_traces("objective", "auxiliary_examination")
                }
            },
            "assessment": {
                "text": assessment_text,
                "diagnosis": {
                    "value": diagnosis,
                    "evidence_traces": get_evidence_traces("assessment", "diagnosis")
                }
            },
            "plan": {
                "text": "\n".join(plan_text),
                "treatment": {
                    "value": treatment,
                    "evidence_traces": get_evidence_traces("plan", "treatment")
                },
                "advice": {
                    "value": advice,
                    "evidence_traces": get_evidence_traces("plan", "advice")
                }
            }
        }
        
        if save_evidence and visit_id:
            self._save_evidence_spans(extraction_result, visit_id, result)
            self._save_emr_record(result, visit_id)
        
        return result

    def _format_facts_for_prompt(self, fact_records: List[AtomicFact]) -> str:
        """
        将AtomicFact记录格式化为prompt用的JSON字符串。

        Args:
            fact_records: 原子事实列表

        Returns:
            JSON字符串
        """
        facts_data = []
        for fact in fact_records:
            facts_data.append({
                "fact_id": fact.fact_id,
                "section_candidate": fact.section_candidate,
                "concept_type": fact.concept_type,
                "mention": fact.mention,
                "normalized_term": fact.normalized_term,
                "polarity": fact.polarity,
                "temporality": fact.temporality,
                "certainty": fact.certainty,
                "speaker": fact.speaker,
                "evidence_turn_ids": fact.evidence_turn_ids or [],
                "evidence_text": fact.evidence_text or []
            })
        return json.dumps(facts_data, ensure_ascii=False, indent=2)

    def _filter_facts_by_section(
        self,
        fact_records: List[AtomicFact],
        sections: List[str]
    ) -> List[AtomicFact]:
        """过滤指定section的事实"""
        return [f for f in fact_records if f.section_candidate in sections]

    def _build_compact_context(
        self,
        fact_records: List[AtomicFact],
        max_items: int = 10
    ) -> str:
        """构建紧凑的上下文摘要，列出关键事实，用于减少后续阶段的输入长度"""
        context_items = []
        for f in fact_records:
            label = f.normalized_term or f.mention
            if not label:
                continue
            speaker = f.speaker or ""
            context_items.append(f"[{speaker}][{f.section_candidate}] {label}")
        if len(context_items) > max_items:
            context_items = context_items[:max_items] + [f"... 共 {len(fact_records)} 条事实"]
        return "\n".join(context_items)

    def _lightweight_normalize(self, facts_data: List[Dict[str, Any]]) -> None:
        """轻量术语规范化：使用ChineseTerm本地库快速匹配，为事实添加normalized_term"""
        if not hasattr(self, 'terminology_service') or not self.terminology_service:
            logger.info("术语服务不可用，跳过轻量规范化")
            return
        try:
            normalized_count = 0
            for fact in facts_data:
                if fact.get("normalized_term"):
                    continue
                mention = fact.get("mention", "")
                if not mention or not mention.strip():
                    continue
                result = self.terminology_service._normalize_by_chinese_term(
                    mention,
                    fact.get("concept_type")
                )
                if result:
                    fact["normalized_term"] = result[0]
                    normalized_count += 1
            logger.info(f"轻量规范化完成: {normalized_count}/{len(facts_data)} 条事实匹配到标准术语")
        except Exception as e:
            logger.warning(f"轻量规范化失败: {e}")

    def _generate_so_stage(
        self,
        fact_records: List[AtomicFact],
        role_mapping: Dict[str, str]
    ) -> Dict[str, Any]:
        """
        阶段4a：分节生成SO（主观数据 + 客观数据）。

        使用 emr_generation_so 模板，只生成 S 和 O 部分，不生成诊断和计划。
        仅传入 section_candidate 为 S 或 O 的事实。

        Args:
            fact_records: 规范化后的原子事实列表
            role_mapping: 角色映射

        Returns:
            {"subjective": {...}, "objective": {...}, "used_fact_ids": [...]}
        """
        logger.info(">>> 阶段4a: 分节生成SO（主观+客观）")
        stage_start = time.time()

        so_facts = self._filter_facts_by_section(fact_records, ["S", "O"])
        logger.info(f"SO生成输入: {len(fact_records)} 条事实，过滤后 {len(so_facts)} 条S/O事实")

        facts_json = self._format_facts_for_prompt(so_facts)

        dialogue_parts = []
        for fact in so_facts:
            mention = fact.normalized_term or fact.mention
            speaker_label = fact.speaker or "unknown"
            dialogue_parts.append(f"[{speaker_label}]: {mention}")
        dialogue_summary = "\n".join(dialogue_parts)

        prompt = self.prompt_manager.render(
            "emr_generation_so",
            facts_json=facts_json,
            dialogue_summary=dialogue_summary
        )
        logger.debug(f"SO生成提示词长度: {len(prompt)} 字符")

        if self.debug_mode:
            response_text = self._debug_interact(
                stage="emr_generation_so",
                prompt=prompt,
                facts_json=facts_json
            )
        else:
            if not self.llm_service:
                logger.warning("LLM服务不可用，SO生成失败")
                return {"subjective": {}, "objective": {}, "used_fact_ids": []}

            try:
                response = self.llm_service.generate(prompt)
                response_text = response.text
            except Exception as e:
                logger.error(f"SO生成LLM调用失败: {e}")
                return {"subjective": {}, "objective": {}, "used_fact_ids": []}

        result = self._extract_json_from_response(response_text, "SO生成")

        if result:
            stage_time = time.time() - stage_start
            logger.info(f"SO生成完成: 使用 {len(result.get('used_fact_ids', []))} 条事实, 耗时: {stage_time:.2f}秒")
            return result

        logger.warning("SO生成JSON解析失败，返回空结果")
        return {"subjective": {}, "objective": {}, "used_fact_ids": []}

    def _generate_ap_stage(
        self,
        so_result: Dict[str, Any],
        fact_records: List[AtomicFact],
        role_mapping: Dict[str, str]
    ) -> Dict[str, Any]:
        """
        阶段4b：分节生成AP（评估 + 计划）。

        分两步：
        (1) 基于 S+O 和事实表生成 Assessment（采用三层诊断策略）
        (2) 基于 S+O+A 和事实表生成 Plan（拆分为4个子字段）

        Args:
            so_result: 阶段4a的输出，包含 subjective, objective, used_fact_ids
            fact_records: 规范化后的原子事实列表
            role_mapping: 角色映射

        Returns:
            {"assessment": {...}, "plan": {...}, "assessment_items": [...], "plan_items": {...}}
        """
        logger.info(">>> 阶段4b: 分节生成AP（评估+计划）")
        stage_start = time.time()

        a_facts = self._filter_facts_by_section(fact_records, ["A"])
        p_facts = self._filter_facts_by_section(fact_records, ["P"])
        logger.info(f"AP生成输入: {len(fact_records)} 条事实，A事实 {len(a_facts)} 条，P事实 {len(p_facts)} 条")

        subjective_text = json.dumps(so_result.get("subjective", {}), ensure_ascii=False, indent=2)
        objective_text = json.dumps(so_result.get("objective", {}), ensure_ascii=False, indent=2)

        time.sleep(self.STAGE_DELAY)

        logger.info(">>> 阶段4b-1: 生成评估(Assessment)")
        assessment_facts_json = self._format_facts_for_prompt(a_facts)
        assessment_prompt = self.prompt_manager.render(
            "emr_generation_assessment",
            subjective_text=subjective_text,
            objective_text=objective_text,
            facts_json=assessment_facts_json
        )
        logger.debug(f"Assessment生成提示词长度: {len(assessment_prompt)} 字符")

        if self.debug_mode:
            assessment_response_text = self._debug_interact(
                stage="emr_generation_assessment",
                prompt=assessment_prompt,
                subjective_text=subjective_text,
                objective_text=objective_text,
                facts_json=facts_json
            )
        else:
            if not self.llm_service:
                logger.warning("LLM服务不可用，Assessment生成失败")
                return {"assessment": {}, "plan": {}, "assessment_items": [], "plan_items": {}}

            try:
                response = self.llm_service.generate(assessment_prompt)
                assessment_response_text = response.text
            except Exception as e:
                logger.error(f"Assessment生成LLM调用失败: {e}")
                return {"assessment": {}, "plan": {}, "assessment_items": [], "plan_items": {}}

        assessment_result = self._extract_json_from_response(assessment_response_text, "Assessment生成")

        if not assessment_result:
            logger.warning("Assessment JSON解析失败")
            assessment_result = {}

        assessment = assessment_result.get("assessment", {})
        assessment_items = assessment_result.get("assessment_items", [])
        assessment_text = json.dumps(assessment, ensure_ascii=False, indent=2)

        logger.info(f"Assessment生成完成: {len(assessment_items)} 条评估项")

        time.sleep(self.STAGE_DELAY)

        logger.info(">>> 阶段4b-2: 生成计划(Plan)")
        plan_facts_json = self._format_facts_for_prompt(p_facts)
        plan_prompt = self.prompt_manager.render(
            "emr_generation_plan",
            subjective_text=subjective_text,
            objective_text=objective_text,
            assessment_text=assessment_text,
            facts_json=plan_facts_json
        )
        logger.debug(f"Plan生成提示词长度: {len(plan_prompt)} 字符")

        if self.debug_mode:
            plan_response_text = self._debug_interact(
                stage="emr_generation_plan",
                prompt=plan_prompt,
                subjective_text=subjective_text,
                objective_text=objective_text,
                assessment_text=assessment_text,
                facts_json=facts_json
            )
        else:
            if not self.llm_service:
                logger.warning("LLM服务不可用，Plan生成失败")
                return {"assessment": assessment, "plan": {}, "assessment_items": assessment_items, "plan_items": {}}

            try:
                response = self.llm_service.generate(plan_prompt)
                plan_response_text = response.text
            except Exception as e:
                logger.error(f"Plan生成LLM调用失败: {e}")
                return {"assessment": assessment, "plan": {}, "assessment_items": assessment_items, "plan_items": {}}

        plan_result = self._extract_json_from_response(plan_response_text, "Plan生成")

        if not plan_result:
            logger.warning("Plan JSON解析失败")
            plan_result = {}

        plan = plan_result.get("plan", {})
        plan_items = plan_result.get("plan_items", {})

        stage_time = time.time() - stage_start
        logger.info(f"AP生成完成，耗时: {stage_time:.2f}秒")

        return {
            "assessment": assessment,
            "plan": plan,
            "assessment_items": assessment_items,
            "plan_items": plan_items
        }

    def _verification_stage(
        self,
        draft_emr: Dict[str, Any],
        fact_records: List[AtomicFact],
        role_mapping: Dict[str, str]
    ) -> Dict[str, Any]:
        logger.info(">>> 阶段5: 核查与修订")
        stage_start = time.time()

        draft_emr_json = json.dumps(draft_emr, ensure_ascii=False, indent=2)

        fact_table_json = self._format_facts_for_prompt(fact_records)
        fact_table_count = len(fact_records)

        role_mapping_json = json.dumps(role_mapping, ensure_ascii=False, indent=2)

        logger.info(f"核查输入: 事实表 {fact_table_count} 条, 角色映射 {len(role_mapping)} 个")

        prompt = self.prompt_manager.render(
            "soap_verification",
            draft_emr=draft_emr_json,
            fact_table=fact_table_json,
            role_mapping=role_mapping_json
        )
        logger.debug(f"核查提示词长度: {len(prompt)} 字符")

        if self.debug_mode:
            response_text = self._debug_interact(
                stage="verification",
                prompt=prompt,
                draft_emr=draft_emr,
                fact_count=fact_table_count
            )
        else:
            if not self.llm_service:
                logger.warning("LLM服务不可用，跳过核查修订阶段，使用原始草稿")
                return {"issues": {}, "soap_final": draft_emr}

            try:
                response = self.llm_service.generate(prompt)
                response_text = response.text
            except Exception as e:
                logger.error(f"核查修订LLM调用失败: {e}")
                return {"issues": {}, "soap_final": draft_emr}

        result = self._extract_json_from_response(response_text, "核查修订")

        if result and "soap_final" in result:
            issues = result.get("issues", {})
            soap_final = result["soap_final"]

            unsupported_count = len(issues.get("unsupported_claims", []))
            missing_count = len(issues.get("missing_critical_facts", []))
            conflict_count = len(issues.get("internal_conflicts", []))
            certainty_error_count = len(issues.get("certainty_errors", []))

            logger.info(
                f"核查完成: "
                f"无证据声明={unsupported_count}, "
                f"关键遗漏={missing_count}, "
                f"内部冲突={conflict_count}, "
                f"确定性错误={certainty_error_count}"
            )

            stage_time = time.time() - stage_start
            logger.info(f"核查修订阶段完成，耗时: {stage_time:.2f}秒")

            return {
                "issues": issues,
                "soap_final": soap_final
            }

        logger.warning("核查修订JSON解析失败，使用原始草稿作为最终版本")
        stage_time = time.time() - stage_start
        logger.info(f"核查修订阶段完成（回退），耗时: {stage_time:.2f}秒")
        return {"issues": {}, "soap_final": draft_emr}
    
    def _debug_interact(
        self,
        stage: str,
        prompt: str,
        **context
    ) -> str:
        import sys
        
        if not sys.stdin.isatty():
            logger.warning(f"DEBUG模式在HTTP请求中不可用，跳过阶段: {stage}")
            raise RuntimeError(f"DEBUG模式需要在终端中运行。阶段: {stage}")
        
        print("\n" + "=" * 80)
        print(f"[DEBUG模式] 阶段: {stage}")
        print("=" * 80)
        print("\n>>> 即将发送给大模型的完整内容：\n")
        print(prompt)
        print("\n" + "-" * 80)
        
        while True:
            try:
                user_input = input("\n请选择操作：\n  y - 确认发送给大模型\n  n - 不发送，手动输入结果\n  q - 取消操作\n\n请输入选择: ").strip().lower()
            except EOFError:
                logger.warning("无法读取用户输入，跳过DEBUG交互")
                raise RuntimeError("DEBUG模式需要终端交互")
            
            if user_input == 'y':
                if not self.llm_service:
                    print("\n[警告] LLM服务不可用！请先配置LLM或选择 'n' 手动输入结果。")
                    continue
                
                try:
                    print("\n>>> 正在调用大模型...")
                    response = self.llm_service.generate(prompt)
                    print("\n>>> 大模型返回结果：\n")
                    print(response.text)
                    return response.text
                except Exception as e:
                    print(f"\n[错误] LLM调用失败: {e}")
                    print("请选择 'n' 手动输入结果，或 'q' 取消操作。")
                    continue
            
            elif user_input == 'n':
                print("\n" + "=" * 80)
                print(">>> 手动输入模式")
                print("=" * 80)
                print(f"\n阶段: {stage}")
                print("\n指导步骤：")
                
                if stage == "turn_cleaning":
                    print("""
1. 判断每个turn的说话人角色（doctor/patient），纠正ASR角色分配错误
2. 修正明显的ASR文本错误（同音字、医学术语拼写错误）
3. 不确定则保留原文，correction_confidence设为"low"
4. 严禁添加原文没有的信息

按JSON格式输出：
{
  "turns": [{
    "turn_id": 0,
    "speaker_role": "doctor或patient",
    "corrected_text": "修正后文本",
    "changed_spans": [{"original": "原词", "corrected": "修正词", "position": "位置"}],
    "correction_confidence": "high|medium|low",
    "reason": "理由"
  }]
}
""")
                elif stage == "fact_extraction":
                    print("""
从对话轮次中抽取原子级临床事实。每条事实是不可再分的独立陈述。

字段说明：
- section_candidate: S / O / A / P
- concept_type: symptom / disease / test / drug / plan / other
- mention: 对话中的原始口语表述
- polarity: present / absent / possible / planned / recommended
- temporality: current / past / unknown
- certainty: explicit / supported / weak
- speaker: patient / doctor
- evidence_turn_ids: 支撑事实的turn_id列表
- evidence_text: 对应的原文片段列表

严禁编造事实。同一事实在多轮提及则合并。

按JSON格式输出：
{
  "facts": [{
    "section_candidate": "S",
    "concept_type": "symptom",
    "mention": "原文",
    "polarity": "present",
    "temporality": "current",
    "certainty": "supported",
    "speaker": "patient",
    "evidence_turn_ids": [0],
    "evidence_text": ["原文"]
  }]
}
""")
                elif stage == "emr_generation_so":
                    print("""
根据事实表生成病历的S(主观)和O(客观)部分，不可生成诊断和计划。

S部分（仅患者角度）：
- chief_complaint: 主诉
- history_present_illness: 现病史
- denied_symptoms: 否认症状
- past_history: 既往史

O部分（仅医方检查结果）：
- physical_examination: 体格检查
- auxiliary_examination: 辅助检查

规则：每句话必须对应事实表fact_id；优先用normalized_term；无证据则留空。

按JSON格式输出：
{
  "subjective": {
    "text": "主诉：...",
    "chief_complaint": {"value": "...", "evidence_traces": []},
    "history_present_illness": {"value": "...", "evidence_traces": []},
    "denied_symptoms": {"value": "...", "evidence_traces": []},
    "past_history": {"value": "...", "evidence_traces": []}
  },
  "objective": {
    "text": "体格检查：...",
    "physical_examination": {"value": "...", "evidence_traces": []},
    "auxiliary_examination": {"value": "...", "evidence_traces": []}
  },
  "used_fact_ids": ["fact_id_1"]
}
""")
                elif stage == "emr_generation_assessment":
                    print("""
按三层诊断策略生成评估(A)：

1. 明确诊断(explicit_diagnosis)：certainty=explicit,disease,doctor → 直接写疾病名
2. 倾向性诊断(suspected_diagnosis)：仅有supported证据 → 用"考虑XXX""XXX待排"
3. 症状性评估(symptom_based)：仅有症状 → 只描述症状，禁止发明疾病名

assessment_items每项含：text, certainty_level(high/medium/low), supporting_fact_ids, diagnosis_type

严禁编造诊断。无诊断级事实时只做症状性评估。

按JSON格式输出：
{
  "assessment": {
    "text": "诊断：...",
    "diagnosis": {"value": "...", "evidence_traces": []}
  },
  "assessment_items": [{
    "text": "...",
    "certainty_level": "high",
    "supporting_fact_ids": ["fact_id_1"],
    "diagnosis_type": "explicit_diagnosis"
  }]
}
""")
                elif stage == "emr_generation_plan":
                    print("""
生成病历的计划(P)，拆分为4个子字段：

1. medications（用药方案）：name, dosage, frequency, duration, used_fact_ids
2. tests（检查建议）：name, reason, used_fact_ids
3. follow_up（复诊）：text, used_fact_ids
4. education（健康教育）：text, used_fact_ids

每条计划必须有事实依据。无证据则留空。优先用normalized_term。

按JSON格式输出：
{
  "plan": {
    "text": "治疗方案：...",
    "treatment": {"value": "...", "evidence_traces": []},
    "advice": {"value": "...", "evidence_traces": []}
  },
  "plan_items": {
    "medications": [{"name": "", "dosage": "", "frequency": "", "duration": "", "used_fact_ids": []}],
    "tests": [{"name": "", "reason": "", "used_fact_ids": []}],
    "follow_up": {"text": "", "used_fact_ids": []},
    "education": {"text": "", "used_fact_ids": []}
  }
}
""")
                elif stage == "verification":
                    print("""
对SOAP草稿进行四个维度核查并修订：

1. 无证据声明(unsupported_claims)：标记病历中无事实支撑的声明
2. 遗漏关键事实(missing_critical_facts)：标记高重要性事实是否被遗漏
3. 内部冲突(internal_conflicts)：检查age/gender/body_part/time/negation/drug_name矛盾
4. 确定性错误(certainty_errors)：检查疑似诊断是否被写成明确诊断

修订优先级：删除无证据声明 → 补充遗漏事实 → 修正矛盾和确定性错误

按JSON格式输出：
{
  "issues": {
    "unsupported_claims": [{"claim_text": "", "soap_location": "", "reason": ""}],
    "missing_critical_facts": [{"fact_id": "", "fact_content": "", "importance_reason": ""}],
    "internal_conflicts": [{"conflict_type": "", "location_1": "", "content_1": "", "location_2": "", "content_2": ""}],
    "certainty_errors": [{"soap_text": "", "correct_certainty": "", "reason": ""}]
  },
  "soap_final": {"subjective": {...}, "objective": {...}, "assessment": {...}, "plan": {...}}
}
如果某维度无问题，对应数组为空。
""")
                elif stage == "role_annotation":
                    print("""
[DEPRECATED] 该阶段已废弃。新版流程使用 turn_cleaning + fact_extraction 替代。
""")
                elif stage == "term_normalization":
                    print("""
[DEPRECATED] 全文本术语规范化已废弃。新版使用基于事实表的逐条规范化(阶段3)，不需要手动输入。
""")
                elif stage == "field_extraction":
                    print("""
[DEPRECATED] 字段抽取阶段已废弃。新版流程中事实表本身已是结构化数据。
""")
                elif stage == "emr_generation":
                    print("""
[DEPRECATED] 旧版单体病历生成已废弃。新版使用分节生成(emr_generation_so + emr_generation_assessment + emr_generation_plan)。
""")
                
                print("\n请输入大模型的返回结果（JSON格式）：")
                print("（输入完成后按回车，然后输入 'END' 并回车结束）\n")
                
                lines = []
                while True:
                    line = input()
                    if line.strip() == "END":
                        break
                    lines.append(line)
                
                result = "\n".join(lines)
                print("\n>>> 已接收手动输入的结果")
                return result
            
            elif user_input == 'q':
                print("\n>>> 操作已取消")
                raise RuntimeError("User cancelled the operation")
            
            else:
                print("\n无效输入，请重新选择。")
    
    def get_all_prompts(self, turns: List[TranscriptTurn]) -> List[Dict[str, Any]]:
        stages = []

        segments = self._segment_turns(turns)
        total_segments = len(segments)

        for i, segment in enumerate(segments):
            transcript_text = self._format_segment(segment)
            prompt = self.prompt_manager.render("turn_cleaning", transcript=transcript_text)

            stages.append({
                "stage": "turn_cleaning",
                "segment_index": i,
                "total_segments": total_segments,
                "prompt": prompt,
                "description": f"阶段1.{i+1}/{total_segments}: 转写清洗与角色纠错",
                "instructions": """
判断每个turn角色(doctor/patient)、修正ASR错误。
输出turns数组，每项含turn_id、speaker_role、corrected_text、changed_spans、correction_confidence。
详见 turn_cleaning 模板。
"""
            })

        stages.append({
            "stage": "fact_extraction",
            "prompt": "[待阶段1完成后生成]",
            "description": "阶段2: 事实抽取与证据绑定",
            "instructions": """
从清洗后的对话轮次中抽取原子临床事实。
每条事实含：section_candidate(S/O/A/P)、concept_type、mention、polarity、temporality、certainty、speaker、evidence_turn_ids、evidence_text。
详见 fact_extraction 模板。
""",
            "pending": True
        })

        stages.append({
            "stage": "emr_generation_so",
            "prompt": "[待阶段2完成后生成]",
            "description": "阶段3: 分节生成SO（主观+客观）",
            "instructions": """
根据S/O事实表生成Subjective和Objective两部分。
S: chief_complaint、history_present_illness、denied_symptoms、past_history
O: physical_examination、auxiliary_examination
禁止生成诊断和计划。详见 emr_generation_so 模板。
""",
            "pending": True
        })

        stages.append({
            "stage": "emr_generation_assessment",
            "prompt": "[待阶段3完成后生成]",
            "description": "阶段4-1: 生成评估(Assessment)",
            "instructions": """
按三层诊断策略生成评估：explicit_diagnosis / suspected_diagnosis / symptom_based_assessment。
输出assessment_items数组。详见 emr_generation_assessment 模板。
""",
            "pending": True
        })

        stages.append({
            "stage": "emr_generation_plan",
            "prompt": "[待阶段4-1完成后生成]",
            "description": "阶段4-2: 生成计划(Plan)",
            "instructions": """
拆分为4个子字段：medications、tests、follow_up、education。
每条必须有fact_id依据。详见 emr_generation_plan 模板。
""",
            "pending": True
        })

        stages.append({
            "stage": "verification",
            "prompt": "[待阶段4-2完成后生成]",
            "description": "阶段5: 核查与修订",
            "instructions": """
四维度核查：unsupported_claims、missing_critical_facts、internal_conflicts、certainty_errors。
输出issues问题清单和修订后的soap_final。详见 soap_verification 模板。
""",
            "pending": True
        })

        return stages
    
    def process_stage_with_user_input(
        self,
        visit_id: str,
        stage: str,
        user_response: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        turns = self.db.query(TranscriptTurn).filter(
            TranscriptTurn.visit_id == visit_id
        ).order_by(TranscriptTurn.turn_index).all()
        
        if not turns:
            return {"error": "没有找到对话轮次"}
        
        segments = self._segment_turns(turns)
        total_segments = len(segments)
        
        if stage == "turn_cleaning":
            segment_index = context.get("segment_index", 0)
            segment = segments[segment_index] if segment_index < len(segments) else segments[0]
            
            cleaning_result = self._parse_cleaning_response(user_response, segment)
            
            if "turns" in cleaning_result:
                self._apply_asr_corrections(cleaning_result, segment)
            
            all_cleaned_turns = context.get("all_cleaned_turns", [])
            all_cleaned_turns.extend(cleaning_result.get("turns", []))
            
            next_stage = None
            next_prompt = None
            next_segment_index = None
            next_description = None
            
            if segment_index + 1 < total_segments:
                next_stage = "turn_cleaning"
                next_segment_index = segment_index + 1
                next_segment = segments[next_segment_index]
                next_prompt = self.prompt_manager.render(
                    "turn_cleaning",
                    transcript=self._format_segment(next_segment)
                )
                next_description = f"阶段1.{next_segment_index + 1}/{total_segments}: 转写清洗与角色纠错"
            else:
                next_stage = "fact_extraction"
                compact_turns = self._build_compact_turns(all_cleaned_turns)
                turns_json = json.dumps(compact_turns, ensure_ascii=False, indent=2)
                next_prompt = self.prompt_manager.render(
                    "fact_extraction",
                    turns_json=turns_json
                )
                logger.info(f"阶段1完成，共{len(all_cleaned_turns)}个清洗后轮次")
                next_description = f"阶段2: 事实抽取与证据绑定 (共{len(all_cleaned_turns)}个轮次，{total_segments}段)"
            
            return {
                "result": cleaning_result,
                "next_stage": next_stage,
                "next_prompt": next_prompt,
                "next_segment_index": next_segment_index,
                "next_description": next_description,
                "context_update": {
                    "all_cleaned_turns": all_cleaned_turns,
                    "role_mapping": {**context.get("role_mapping", {}), **cleaning_result.get("role_mapping", {})}
                }
            }
        
        elif stage == "fact_extraction":
            all_cleaned_turns = context.get("all_cleaned_turns", [])
            logger.info(f"收到用户输入的事实抽取结果，处理 {len(all_cleaned_turns)} 个轮次")
            
            parsed = self._extract_json_from_response(user_response, "事实抽取")
            facts_data = parsed.get("facts", []) if parsed else []
            logger.info(f"手动提取到 {len(facts_data)} 条事实")
            
            if not facts_data:
                return {
                    "result": {"error": "未能从输入中提取事实JSON"},
                    "next_stage": "fact_extraction",
                    "next_prompt": self.prompt_manager.render(
                        "fact_extraction",
                        turns_json=json.dumps(all_cleaned_turns, ensure_ascii=False, indent=2)
                    ),
                    "next_description": "请重新输入: 阶段2: 事实抽取与证据绑定"
                }
            
            so_facts = [f for f in facts_data if f.get("section_candidate") in ("S", "O")]
            a_facts = [f for f in facts_data if f.get("section_candidate") == "A"]
            p_facts = [f for f in facts_data if f.get("section_candidate") == "P"]
            logger.info(f"事实分类: S+O={len(so_facts)}, A={len(a_facts)}, P={len(p_facts)}")
            
            self._lightweight_normalize(facts_data)
            
            dialogue_parts = []
            for fact in so_facts:
                mention = fact.get("normalized_term") or fact.get("mention", "")
                speaker = fact.get("speaker", "unknown")
                dialogue_parts.append(f"[{speaker}]: {mention}")
            dialogue_summary = "\n".join(dialogue_parts)
            
            next_prompt_so = self.prompt_manager.render(
                "emr_generation_so",
                facts_json=json.dumps(so_facts, ensure_ascii=False, indent=2),
                dialogue_summary=dialogue_summary
            )
            
            return {
                "result": {"facts_count": len(facts_data), "facts": facts_data},
                "next_stage": "emr_generation_so",
                "next_prompt": next_prompt_so,
                "next_description": f"阶段3: 分节生成SO（共{len(so_facts)}条S/O事实）",
                "context_update": {
                    "facts": facts_data,
                    "so_facts": so_facts,
                    "a_facts": a_facts,
                    "p_facts": p_facts
                }
            }
        
        elif stage == "emr_generation_so":
            facts = context.get("facts", [])
            logger.info("收到用户输入的SO生成结果")
            
            parsed = self._extract_json_from_response(user_response, "SO生成")
            
            subjective = parsed.get("subjective", {}) if parsed else {}
            objective = parsed.get("objective", {}) if parsed else {}
            so_result = {"subjective": subjective, "objective": objective}
            
            a_facts = context.get("a_facts", [])
            subjective_text = json.dumps(subjective, ensure_ascii=False, indent=2)
            objective_text = json.dumps(objective, ensure_ascii=False, indent=2)
            
            next_prompt_assessment = self.prompt_manager.render(
                "emr_generation_assessment",
                subjective_text=subjective_text,
                objective_text=objective_text,
                facts_json=json.dumps(a_facts, ensure_ascii=False, indent=2)
            )
            
            return {
                "result": so_result,
                "next_stage": "emr_generation_assessment",
                "next_prompt": next_prompt_assessment,
                "next_description": f"阶段4-1: 生成评估（共{len(a_facts)}条A事实）",
                "context_update": {
                    "subjective": subjective,
                    "objective": objective,
                    "subjective_text": subjective_text,
                    "objective_text": objective_text,
                    "so_result": so_result
                }
            }
        
        elif stage == "emr_generation_assessment":
            logger.info("收到用户输入的评估生成结果")
            
            parsed = self._extract_json_from_response(user_response, "评估生成")
            assessment = parsed.get("assessment", {}) if parsed else {}
            assessment_items = parsed.get("assessment_items", []) if parsed else []
            assessment_text = json.dumps(assessment, ensure_ascii=False, indent=2)
            
            p_facts = context.get("p_facts", [])
            subjective_text = context.get("subjective_text", "{}")
            objective_text = context.get("objective_text", "{}")
            
            next_prompt_plan = self.prompt_manager.render(
                "emr_generation_plan",
                subjective_text=subjective_text,
                objective_text=objective_text,
                assessment_text=assessment_text,
                facts_json=json.dumps(p_facts, ensure_ascii=False, indent=2)
            )
            
            return {
                "result": {"assessment": assessment, "assessment_items": assessment_items},
                "next_stage": "emr_generation_plan",
                "next_prompt": next_prompt_plan,
                "next_description": f"阶段4-2: 生成计划（共{len(p_facts)}条P事实）",
                "context_update": {
                    "assessment": assessment,
                    "assessment_items": assessment_items,
                    "assessment_text": assessment_text
                }
            }
        
        elif stage == "emr_generation_plan":
            logger.info("收到用户输入的计划生成结果")
            
            parsed = self._extract_json_from_response(user_response, "计划生成")
            plan = parsed.get("plan", {}) if parsed else {}
            plan_items = parsed.get("plan_items", {}) if parsed else {}
            
            subjective = context.get("subjective", {})
            objective = context.get("objective", {})
            assessment = context.get("assessment", {})
            
            draft_emr = json.dumps({
                "subjective": subjective,
                "objective": objective,
                "assessment": assessment,
                "plan": plan
            }, ensure_ascii=False, indent=2)
            
            facts = context.get("facts", [])
            facts_table = json.dumps(facts, ensure_ascii=False, indent=2)
            role_mapping = json.dumps(context.get("role_mapping", {}), ensure_ascii=False, indent=2)
            
            next_prompt_verify = self.prompt_manager.render(
                "soap_verification",
                draft_emr=draft_emr,
                fact_table=facts_table,
                role_mapping=role_mapping
            )
            
            return {
                "result": {"plan": plan, "plan_items": plan_items},
                "next_stage": "verification",
                "next_prompt": next_prompt_verify,
                "next_description": f"阶段5: 核查与修订（共{len(facts)}条事实）",
                "context_update": {
                    "plan": plan,
                    "plan_items": plan_items,
                    "draft_emr": draft_emr
                }
            }
        
        elif stage == "verification":
            logger.info("收到用户输入的核查结果，处理完成")
            
            parsed = self._extract_json_from_response(user_response, "SOAP核查")
            soap_final = parsed.get("soap_final", {}) if parsed else {}
            issues = parsed.get("issues", {}) if parsed else {}
            
            logger.info(f"核查完成: unsupported={len(issues.get('unsupported_claims',[]))}, missing={len(issues.get('missing_critical_facts',[]))}, conflicts={len(issues.get('internal_conflicts',[]))}")
            
            return {
                "result": {"soap_final": soap_final, "issues": issues},
                "next_stage": None,
                "next_prompt": None,
                "next_description": None,
                "completed": True,
                "context_update": {
                    "soap_final": soap_final,
                    "issues": issues
                }
            }
        
        elif stage == "role_annotation":
            return self._legacy_role_annotation_stage(stage, user_response, context, segments, total_segments)
        elif stage == "term_normalization":
            return self._legacy_term_normalization_stage(stage, user_response, context, segments)        
        elif stage == "field_extraction":
            return self._legacy_field_extraction_stage(stage, user_response, context, segments)
        elif stage == "emr_generation":
            return self._legacy_emr_generation_stage(stage, user_response, context, segments)
        
        return {"error": f"未知阶段: {stage}"}

    def _build_compact_turns(self, all_cleaned_turns):
        compact = []
        for turn in all_cleaned_turns:
            compact.append({
                "turn_id": turn.get("turn_id"),
                "speaker_role": turn.get("speaker_role"),
                "corrected_text": turn.get("corrected_text", "")
            })
        return compact

    def _legacy_role_annotation_stage(self, stage, user_response, context, segments, total_segments):
        segment_index = context.get("segment_index", 0)
        segment = segments[segment_index] if segment_index < len(segments) else segments[0]
        result = self._parse_role_annotation_response(user_response, segment)
        all_annotated_texts = context.get("all_annotated_texts", [])
        if result.get("annotated_text"):
            all_annotated_texts.append(result["annotated_text"])
        if segment_index + 1 < total_segments:
            next_stage = "role_annotation"
            next_segment_index = segment_index + 1
            next_prompt = self._build_role_annotation_prompt(self._format_segment(segments[next_segment_index]))
            next_description = f"阶段1.{next_segment_index + 1}/{total_segments}: 角色识别与证据标注"
        else:
            next_stage = "term_normalization"
            next_prompt = self._build_normalization_prompt("\n\n".join(all_annotated_texts))
            next_description = "阶段2: 术语规范化"
        return {
            "result": result,
            "next_stage": next_stage,
            "next_prompt": next_prompt,
            "next_segment_index": next_segment_index if segment_index + 1 < total_segments else None,
            "next_description": next_description,
            "context_update": {
                "all_annotated_texts": all_annotated_texts,
                "role_mapping": {**context.get("role_mapping", {}), **result.get("role_mapping", {})}
            }
        }

    def _legacy_term_normalization_stage(self, stage, user_response, context, segments):
        all_annotated_texts = context.get("all_annotated_texts", [])
        combined = "\n\n".join(all_annotated_texts) if all_annotated_texts else "\n\n".join([self._format_segment(s) for s in segments])
        result = self._parse_normalization_response(user_response, combined)
        normalized_text = result.get("normalized_text", combined)
        return {
            "result": result,
            "next_stage": "field_extraction",
            "next_prompt": self._build_extraction_prompt(normalized_text, context.get("role_mapping", {})),
            "next_description": "阶段3: 字段抽取",
            "context_update": {"normalized_text": normalized_text}
        }

    def _legacy_field_extraction_stage(self, stage, user_response, context, segments):
        normalized_text = context.get("normalized_text", "")
        result = self._parse_extraction_response(user_response, context.get("all_evidence_traces", []))
        return {
            "result": result,
            "next_stage": "emr_generation",
            "next_prompt": self._build_emr_generation_prompt(result, context.get("role_mapping", {})),
            "next_description": "阶段4: 病历生成",
            "context_update": {"extraction_result": result}
        }

    def _legacy_emr_generation_stage(self, stage, user_response, context, segments):
        extraction_result = context.get("extraction_result", {})
        result = self._parse_emr_response(user_response, extraction_result, context.get("visit_id", ""), True)
        return {
            "result": result,
            "next_stage": None,
            "next_prompt": None,
            "next_description": None,
            "completed": True
        }
