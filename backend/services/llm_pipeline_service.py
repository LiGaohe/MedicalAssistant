import json
from typing import Dict, Any, Optional, List, Tuple
from sqlalchemy.orm import Session
from ..models import TranscriptTurn, EMRRecord, EvidenceSpan
from .llm.llm_service import LLMService
from .llm.prompts import PromptManager
from ..config import settings
from ..utils.logger import logger


class LLMPipelineService:
    def __init__(self, db: Session, llm_service: Optional[LLMService] = None):
        self.db = db
        self.llm_service = llm_service
        self.prompt_manager = PromptManager()
        self.debug_mode = settings.LLM_DEBUG_MODE
        self.segment_turns = settings.LLM_SEGMENT_TURNS
        logger.info(f"LLMPipelineService initialized, debug_mode={self.debug_mode}")
        
    def process_transcript(
        self,
        visit_id: str
    ) -> Dict[str, Any]:
        logger.info(f"=== 开始多阶段LLM处理: {visit_id} ===")
        
        turns = self.db.query(TranscriptTurn).filter(
            TranscriptTurn.visit_id == visit_id
        ).order_by(TranscriptTurn.turn_index).all()
        
        if not turns:
            logger.warning("没有找到对话轮次")
            return {"status": "failed", "error": "No transcript turns found"}
        
        segments = self._segment_turns(turns)
        logger.info(f"对话分为 {len(segments)} 个段落")
        
        all_role_mappings = {}
        all_annotated_texts = []
        
        for i, segment in enumerate(segments):
            logger.info(f">>> 处理段落 {i+1}/{len(segments)}")
            
            result = self._process_segment(segment, i)
            
            if result.get("role_mapping"):
                all_role_mappings.update(result["role_mapping"])
            if result.get("annotated_text"):
                all_annotated_texts.append(result["annotated_text"])
        
        combined_text = "\n\n".join(all_annotated_texts)
        logger.info(f"合并后的标注文本长度: {len(combined_text)} 字符")
        
        normalized_result = self._normalize_terms_stage(combined_text, all_role_mappings)
        
        extraction_result = self._extract_fields_stage(
            normalized_result.get("normalized_text", combined_text),
            all_role_mappings
        )
        
        emr_result = self._generate_emr_stage(
            extraction_result,
            all_role_mappings,
            turns
        )
        
        return {
            "status": "completed",
            "role_mapping": all_role_mappings,
            "annotated_text": combined_text,
            "normalized_result": normalized_result,
            "extraction_result": extraction_result,
            "emr_result": emr_result
        }
    
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
    
    def _process_segment(
        self,
        segment: List[TranscriptTurn],
        segment_index: int
    ) -> Dict[str, Any]:
        transcript_text = self._format_segment(segment)
        
        prompt = self._build_role_annotation_prompt(transcript_text)
        
        if self.debug_mode:
            response_text = self._debug_interact(
                stage="role_annotation",
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
        
        return self._parse_role_annotation_response(response_text, segment)
    
    def _format_segment(self, segment: List[TranscriptTurn]) -> str:
        lines = []
        for turn in segment:
            lines.append(f"[{turn.speaker}]: {turn.text}")
        return "\n".join(lines)
    
    def _build_role_annotation_prompt(self, transcript: str) -> str:
        return f"""你是一个医疗对话分析专家。请分析以下医患对话，完成两个任务：

## 任务1：角色识别
判断每个说话人(spk0, spk1等)是医生还是患者。

## 任务2：证据标注
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

## 对话内容
{transcript}

## 输出格式
请按以下JSON格式输出：
{{
  "role_mapping": {{
    "spk0": "doctor或patient",
    "spk1": "doctor或patient"
  }},
  "annotated_text": "标注后的对话文本，保留原始格式，在证据周围添加XML标签"
}}

注意：
1. 角色识别依据：医生通常提问、检查、诊断、开药；患者通常描述症状、回答问题
2. 证据标注要准确，不要遗漏重要信息
3. 一段话可能包含多个证据字段
4. 保持原始对话的完整性"""
    
    def _parse_role_annotation_response(
        self,
        response_text: str,
        segment: List[TranscriptTurn]
    ) -> Dict[str, Any]:
        try:
            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1
            if json_start != -1 and json_end > json_start:
                json_str = response_text[json_start:json_end]
                result = json.loads(json_str)
                return {
                    "role_mapping": result.get("role_mapping", {}),
                    "annotated_text": result.get("annotated_text", "")
                }
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {e}")
        
        return self._fallback_role_annotation(segment)
    
    def _fallback_role_annotation(self, segment: List[TranscriptTurn]) -> Dict[str, Any]:
        role_mapping = self._infer_roles_by_rules(segment)
        
        annotated_lines = []
        for turn in segment:
            annotated_lines.append(f"[{turn.speaker}]: {turn.text}")
        
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
    
    def _normalize_terms_stage(
        self,
        annotated_text: str,
        role_mapping: Dict[str, str]
    ) -> Dict[str, Any]:
        logger.info(">>> 阶段2: 术语规范化")
        
        prompt = self._build_normalization_prompt(annotated_text)
        
        if self.debug_mode:
            response_text = self._debug_interact(
                stage="term_normalization",
                prompt=prompt,
                annotated_text=annotated_text
            )
        else:
            if not self.llm_service:
                logger.warning("LLM服务不可用，跳过术语规范化")
                return {"normalized_text": annotated_text, "terms": []}
            
            try:
                response = self.llm_service.generate(prompt)
                response_text = response.text
            except Exception as e:
                logger.error(f"术语规范化LLM调用失败: {e}")
                return {"normalized_text": annotated_text, "terms": []}
        
        return self._parse_normalization_response(response_text, annotated_text)
    
    def _build_normalization_prompt(self, annotated_text: str) -> str:
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
        try:
            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1
            if json_start != -1 and json_end > json_start:
                json_str = response_text[json_start:json_end]
                result = json.loads(json_str)
                return {
                    "normalized_text": result.get("normalized_text", original_text),
                    "terms": result.get("terms", [])
                }
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {e}")
        
        return {"normalized_text": original_text, "terms": []}
    
    def _extract_fields_stage(
        self,
        normalized_text: str,
        role_mapping: Dict[str, str]
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
                return self._fallback_extraction(normalized_text)
            
            try:
                response = self.llm_service.generate(prompt)
                response_text = response.text
            except Exception as e:
                logger.error(f"字段抽取LLM调用失败: {e}")
                return self._fallback_extraction(normalized_text)
        
        return self._parse_extraction_response(response_text)
    
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
    
    def _parse_extraction_response(self, response_text: str) -> Dict[str, Any]:
        try:
            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1
            if json_start != -1 and json_end > json_start:
                json_str = response_text[json_start:json_end]
                return json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {e}")
        
        return self._fallback_extraction("")
    
    def _fallback_extraction(self, text: str) -> Dict[str, Any]:
        return {
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
    
    def _generate_emr_stage(
        self,
        extraction_result: Dict[str, Any],
        role_mapping: Dict[str, str],
        turns: List[TranscriptTurn]
    ) -> Dict[str, Any]:
        logger.info(">>> 阶段4: 病历生成")
        
        prompt = self._build_emr_generation_prompt(extraction_result, role_mapping)
        
        if self.debug_mode:
            response_text = self._debug_interact(
                stage="emr_generation",
                prompt=prompt,
                extraction_result=extraction_result
            )
        else:
            if not self.llm_service:
                logger.warning("LLM服务不可用，使用模板生成")
                return self._template_emr_generation(extraction_result)
            
            try:
                response = self.llm_service.generate(prompt)
                response_text = response.text
            except Exception as e:
                logger.error(f"病历生成LLM调用失败: {e}")
                return self._template_emr_generation(extraction_result)
        
        return self._parse_emr_response(response_text, extraction_result)
    
    def _build_emr_generation_prompt(
        self,
        extraction_result: Dict[str, Any],
        role_mapping: Dict[str, str]
    ) -> str:
        extraction_json = json.dumps(extraction_result, ensure_ascii=False, indent=2)
        
        return f"""你是一个医疗病历撰写专家。请根据以下抽取的结构化数据生成符合中国医疗病历书写规范的病历文本。

## 结构化数据
{extraction_json}

## 任务要求
1. 生成自然流畅的病历文本
2. 符合SOAP格式（主观数据、客观数据、评估、计划）
3. 使用规范的医学术语
4. 保持内容的准确性和完整性

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
3. 如果某个字段为空，可以省略或写"未见异常"等"""
    
    def _parse_emr_response(
        self,
        response_text: str,
        extraction_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        try:
            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1
            if json_start != -1 and json_end > json_start:
                json_str = response_text[json_start:json_end]
                return json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {e}")
        
        return self._template_emr_generation(extraction_result)
    
    def _template_emr_generation(self, extraction_result: Dict[str, Any]) -> Dict[str, Any]:
        def get_value(section: str, field: str) -> str:
            try:
                return extraction_result.get(section, {}).get(field, {}).get("value", "")
            except:
                return ""
        
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
        
        return {
            "subjective": {
                "text": "\n".join(subjective_text),
                "chief_complaint": chief_complaint,
                "history_present_illness": history,
                "past_history": past_history
            },
            "objective": {
                "text": "\n".join(objective_text),
                "physical_examination": physical,
                "auxiliary_examination": auxiliary
            },
            "assessment": {
                "text": assessment_text,
                "diagnosis": diagnosis
            },
            "plan": {
                "text": "\n".join(plan_text),
                "treatment": treatment,
                "advice": advice
            }
        }
    
    def _debug_interact(
        self,
        stage: str,
        prompt: str,
        **context
    ) -> str:
        print("\n" + "=" * 80)
        print(f"[DEBUG模式] 阶段: {stage}")
        print("=" * 80)
        print("\n>>> 即将发送给大模型的完整内容：\n")
        print(prompt)
        print("\n" + "-" * 80)
        
        while True:
            user_input = input("\n请选择操作：\n  y - 确认发送给大模型\n  n - 不发送，手动输入结果\n  q - 取消操作\n\n请输入选择: ").strip().lower()
            
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
                
                if stage == "role_annotation":
                    print("""
1. 分析对话内容，判断每个说话人(spk0, spk1等)是医生还是患者
2. 用XML标签标注证据字段：
   - <主诉>...</主诉>
   - <现病史>...</现病史>
   - <既往史>...</既往史>
   - <体格检查>...</体格检查>
   - <辅助检查>...</辅助检查>
   - <诊断>...</诊断>
   - <治疗>...</治疗>
   - <医嘱>...</医嘱>
3. 按JSON格式输出结果
""")
                elif stage == "term_normalization":
                    print("""
1. 识别文本中的口语化医学术语
2. 将口语化术语替换为标准医学术语
3. 保持XML标签和对话格式不变
4. 按JSON格式输出结果
""")
                elif stage == "field_extraction":
                    print("""
1. 从XML标签中提取对应字段的内容
2. 合并相同字段的内容（去重）
3. 处理可能的冲突
4. 按JSON格式输出结果
""")
                elif stage == "emr_generation":
                    print("""
1. 根据结构化数据生成病历文本
2. 符合SOAP格式
3. 使用规范的医学术语
4. 按JSON格式输出结果
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
