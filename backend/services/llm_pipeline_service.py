import json
import re
import time
from typing import Dict, Any, Optional, List, Tuple
from sqlalchemy.orm import Session
from ..models import TranscriptTurn, EMRRecord, EvidenceSpan
from .llm.llm_service import LLMService
from .llm.prompts import PromptManager
from ..config import settings
from ..utils.logger import logger


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
    
    def __init__(self, db: Session, llm_service: Optional[LLMService] = None):
        self.db = db
        self.llm_service = llm_service
        self.prompt_manager = PromptManager()
        self.debug_mode = settings.LLM_DEBUG_MODE
        self.segment_turns = settings.LLM_SEGMENT_TURNS
        logger.info(f"LLMPipelineService initialized, debug_mode={self.debug_mode}")
        
    def process_transcript(
        self,
        visit_id: str,
        save_evidence: bool = True
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
        all_evidence_traces = []
        
        for i, segment in enumerate(segments):
            logger.info(f">>> 处理段落 {i+1}/{len(segments)}")
            
            result = self._process_segment(segment, i)
            
            if result.get("role_mapping"):
                all_role_mappings.update(result["role_mapping"])
            if result.get("annotated_text"):
                all_annotated_texts.append(result["annotated_text"])
            if result.get("evidence_traces"):
                all_evidence_traces.extend(result["evidence_traces"])
        
        combined_text = "\n\n".join(all_annotated_texts)
        logger.info(f"合并后的标注文本长度: {len(combined_text)} 字符")
        logger.info(f"收集到 {len(all_evidence_traces)} 条证据溯源记录")
        
        time.sleep(self.STAGE_DELAY)
        
        normalized_result = self._normalize_terms_stage(combined_text, all_role_mappings)
        
        time.sleep(self.STAGE_DELAY)
        
        extraction_result = self._extract_fields_stage(
            normalized_result.get("normalized_text", combined_text),
            all_role_mappings,
            all_evidence_traces
        )
        
        time.sleep(self.STAGE_DELAY)
        
        emr_result = self._generate_emr_stage(
            extraction_result,
            all_role_mappings,
            turns,
            visit_id,
            save_evidence
        )
        
        return {
            "status": "completed",
            "role_mapping": all_role_mappings,
            "annotated_text": combined_text,
            "normalized_result": normalized_result,
            "extraction_result": extraction_result,
            "emr_result": emr_result,
            "evidence_traces": all_evidence_traces
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
                
                role_mapping = result.get("role_mapping", {})
                annotated_text = result.get("annotated_text", "")
                
                evidence_traces = self._extract_evidence_traces(annotated_text, segment, role_mapping)
                
                return {
                    "role_mapping": role_mapping,
                    "annotated_text": annotated_text,
                    "evidence_traces": evidence_traces
                }
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {e}")
        
        return self._fallback_role_annotation(segment)
    
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
    
    def _calculate_evidence_confidence(
        self,
        content: str,
        turn_text: str,
        field_type: str,
        speaker: str,
        role_mapping: Dict[str, str],
        turn_confidence: float = 1.0
    ) -> float:
        confidence = 0.5
        
        if turn_text and content:
            if content in turn_text:
                confidence += 0.3
            elif turn_text in content:
                confidence += 0.25
            else:
                content_words = set(content)
                turn_words = set(turn_text)
                if content_words and turn_words:
                    overlap = len(content_words & turn_words) / len(content_words)
                    confidence += overlap * 0.2
        
        expected_role = self.FIELD_EXPECTED_ROLE.get(field_type)
        if expected_role and speaker and role_mapping:
            actual_role = role_mapping.get(speaker)
            if actual_role == expected_role:
                confidence += 0.2
            elif actual_role and actual_role != expected_role:
                confidence -= 0.1
        
        if turn_confidence and turn_confidence > 0:
            confidence += turn_confidence * 0.1
        
        return min(1.0, max(0.1, confidence))
    
    def _extract_evidence_traces(
        self,
        annotated_text: str,
        segment: List[TranscriptTurn],
        role_mapping: Dict[str, str] = None
    ) -> List[Dict[str, Any]]:
        evidence_traces = []
        
        tag_pattern = r'<(主诉|现病史|既往史|体格检查|辅助检查|诊断|治疗|医嘱|其他)>(.*?)</\1>'
        
        turn_by_speaker = {}
        turn_by_index = {}
        for turn in segment:
            if turn.speaker not in turn_by_speaker:
                turn_by_speaker[turn.speaker] = []
            turn_by_speaker[turn.speaker].append(turn)
            turn_by_index[turn.turn_index] = turn
        
        for match in re.finditer(tag_pattern, annotated_text, re.DOTALL):
            field_type_cn = match.group(1)
            content = match.group(2).strip()
            
            field_type = self.FIELD_TYPE_MAPPING.get(field_type_cn, "other")
            
            start_char = match.start()
            end_char = match.end()
            
            speaker = None
            turn_id = None
            turn_index = None
            turn_text = None
            turn_confidence = 1.0
            
            speaker_markers = re.findall(r'\[(spk\d+)\]:\s*([^[]+)', content)
            
            if speaker_markers:
                matched_turns = []
                matched_speakers = set()
                
                first_marker_pos = content.find('[spk')
                if first_marker_pos > 0:
                    prefix_text = content[:first_marker_pos].strip().rstrip('，。,')
                    if prefix_text:
                        first_speaker = speaker_markers[0][0] if speaker_markers else None
                        if first_speaker and first_speaker in turn_by_speaker:
                            for turn in turn_by_speaker[first_speaker]:
                                if prefix_text in turn.text:
                                    if turn.turn_index not in [t.turn_index for t in matched_turns]:
                                        matched_turns.append(turn)
                                        matched_speakers.add(first_speaker)
                                    break
                
                for spk, text_part in speaker_markers:
                    text_part = text_part.strip().rstrip('，。,')
                    if not text_part:
                        continue
                    matched_speakers.add(spk)
                    
                    if spk in turn_by_speaker:
                        for turn in turn_by_speaker[spk]:
                            if text_part in turn.text or turn.text in text_part:
                                if turn.turn_index not in [t.turn_index for t in matched_turns]:
                                    matched_turns.append(turn)
                                break
                
                matched_turns.sort(key=lambda t: t.turn_index)
                
                if matched_turns:
                    speaker = matched_turns[0].speaker
                    turn_id = matched_turns[0].turn_id
                    turn_index = matched_turns[0].turn_index
                    turn_text = "\n".join([f"[{t.speaker}]: {t.text}" for t in matched_turns])
                    turn_confidence = matched_turns[0].confidence if matched_turns[0].confidence else 1.0
            else:
                line_start = annotated_text.rfind('\n', 0, start_char) + 1
                line_end = annotated_text.find('\n', start_char)
                if line_end == -1:
                    line_end = len(annotated_text)
                
                line = annotated_text[line_start:line_end]
                
                speaker_match = re.match(r'\[(spk\d+)\]', line)
                if speaker_match:
                    speaker = speaker_match.group(1)
                    
                    if speaker in turn_by_speaker:
                        for turn in turn_by_speaker[speaker]:
                            if content in turn.text or turn.text in content:
                                turn_id = turn.turn_id
                                turn_index = turn.turn_index
                                turn_text = turn.text
                                turn_confidence = turn.confidence if turn.confidence else 1.0
                                break
                        
                        if turn_id is None and turn_by_speaker[speaker]:
                            turn = turn_by_speaker[speaker][0]
                            turn_id = turn.turn_id
                            turn_index = turn.turn_index
                            turn_text = turn.text
                            turn_confidence = turn.confidence if turn.confidence else 1.0
            
            confidence = self._calculate_evidence_confidence(
                content, turn_text, field_type, speaker, role_mapping or {}, turn_confidence
            )
            
            evidence_trace = {
                "field_type": field_type,
                "field_type_cn": field_type_cn,
                "content": content,
                "speaker": speaker,
                "turn_id": turn_id,
                "turn_index": turn_index,
                "turn_text": turn_text,
                "start_char": start_char,
                "end_char": end_char,
                "confidence": round(confidence, 3)
            }
            
            evidence_traces.append(evidence_trace)
            logger.debug(f"提取证据: {field_type_cn} - {content[:30]}... (turn_id={turn_id}, confidence={confidence:.2f})")
        
        return evidence_traces
    
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
        try:
            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1
            if json_start != -1 and json_end > json_start:
                json_str = response_text[json_start:json_end]
                result = json.loads(json_str)
                
                result = self._attach_evidence_traces(result, evidence_traces)
                
                return result
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {e}")
        
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
    
    def _generate_emr_stage(
        self,
        extraction_result: Dict[str, Any],
        role_mapping: Dict[str, str],
        turns: List[TranscriptTurn],
        visit_id: str,
        save_evidence: bool = True
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
                return self._template_emr_generation(extraction_result, visit_id, save_evidence)
            
            try:
                response = self.llm_service.generate(prompt)
                response_text = response.text
            except Exception as e:
                logger.error(f"病历生成LLM调用失败: {e}")
                return self._template_emr_generation(extraction_result, visit_id, save_evidence)
        
        return self._parse_emr_response(response_text, extraction_result, visit_id, save_evidence)
    
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
        extraction_result: Dict[str, Any],
        visit_id: str = None,
        save_evidence: bool = True
    ) -> Dict[str, Any]:
        try:
            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1
            if json_start != -1 and json_end > json_start:
                json_str = response_text[json_start:json_end]
                result = json.loads(json_str)
                
                result = self._attach_evidence_to_emr(result, extraction_result)
                
                if save_evidence and visit_id:
                    self._save_evidence_spans(extraction_result, visit_id, result)
                    self._save_emr_record(result, visit_id)
                
                return result
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {e}")
        
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
                        if field_name in emr_result[section]:
                            if isinstance(emr_result[section][field_name], str):
                                emr_result[section][field_name] = {
                                    "value": emr_result[section][field_name],
                                    "evidence_traces": field_data["evidence_traces"]
                                }
                            else:
                                emr_result[section][field_name]["evidence_traces"] = field_data["evidence_traces"]
        
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
                    if turn_id is None:
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
                validation_errors=None
            )
            
            self.db.add(emr_record)
            self.db.commit()
            
            logger.info(f"保存病历记录成功: visit_id={visit_id}, version={new_version}")
            return emr_record
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"保存病历记录失败: {e}")
            return None
    
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
    
    def get_all_prompts(self, turns: List[TranscriptTurn]) -> List[Dict[str, Any]]:
        stages = []
        
        segments = self._segment_turns(turns)
        total_segments = len(segments)
        
        for i, segment in enumerate(segments):
            transcript_text = self._format_segment(segment)
            prompt = self._build_role_annotation_prompt(transcript_text)
            
            stages.append({
                "stage": "role_annotation",
                "segment_index": i,
                "total_segments": total_segments,
                "prompt": prompt,
                "description": f"阶段1.{i+1}/{total_segments}: 角色识别与证据标注",
                "instructions": """
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
3. 按JSON格式输出结果：
{
  "role_mapping": {"spk0": "doctor", "spk1": "patient"},
  "annotated_text": "标注后的对话文本..."
}
"""
            })
        
        stages.append({
            "stage": "term_normalization",
            "prompt": "[待阶段1全部完成后生成]",
            "description": "阶段2: 术语规范化",
            "instructions": """
1. 识别文本中的口语化医学术语
2. 将口语化术语替换为标准医学术语
3. 保持XML标签和对话格式不变
4. 按JSON格式输出结果：
{
  "normalized_text": "规范化后的完整文本",
  "terms": [{"original": "原术语", "normalized": "标准术语", "category": "类别"}]
}
""",
            "pending": True
        })
        
        stages.append({
            "stage": "field_extraction",
            "prompt": "[待阶段2完成后生成]",
            "description": "阶段3: 字段抽取",
            "instructions": """
1. 从XML标签中提取对应字段的内容
2. 合并相同字段的内容（去重）
3. 处理可能的冲突
4. 按JSON格式输出结果：
{
  "subjective": {"chief_complaint": {"value": "...", "speaker": "...", "confidence": 0.9}, ...},
  "objective": {...},
  "assessment": {...},
  "plan": {...}
}
""",
            "pending": True
        })
        
        stages.append({
            "stage": "emr_generation",
            "prompt": "[待阶段3完成后生成]",
            "description": "阶段4: 病历生成",
            "instructions": """
1. 根据结构化数据生成病历文本
2. 符合SOAP格式
3. 按JSON格式输出结果：
{
  "subjective": {"text": "主观数据段落", "chief_complaint": "...", ...},
  "objective": {"text": "客观数据段落", ...},
  "assessment": {"text": "评估段落", ...},
  "plan": {"text": "计划段落", ...}
}
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
        
        if stage == "role_annotation":
            segment_index = context.get("segment_index", 0)
            segment = segments[segment_index] if segment_index < len(segments) else segments[0]
            
            result = self._parse_role_annotation_response(user_response, segment)
            
            all_annotated_texts = context.get("all_annotated_texts", [])
            all_evidence_traces = context.get("all_evidence_traces", [])
            
            if result.get("annotated_text"):
                all_annotated_texts.append(result["annotated_text"])
            if result.get("evidence_traces"):
                all_evidence_traces.extend(result["evidence_traces"])
            
            next_stage = None
            next_prompt = None
            next_segment_index = None
            next_description = None
            
            if segment_index + 1 < total_segments:
                next_stage = "role_annotation"
                next_segment_index = segment_index + 1
                next_prompt = self._build_role_annotation_prompt(
                    self._format_segment(segments[next_segment_index])
                )
                next_description = f"阶段1.{next_segment_index + 1}/{total_segments}: 角色识别与证据标注"
            else:
                next_stage = "term_normalization"
                combined_annotated_text = "\n\n".join(all_annotated_texts)
                next_prompt = self._build_normalization_prompt(combined_annotated_text)
                next_description = "阶段2: 术语规范化"
            
            return {
                "result": result,
                "next_stage": next_stage,
                "next_prompt": next_prompt,
                "next_segment_index": next_segment_index,
                "next_description": next_description,
                "context_update": {
                    "all_annotated_texts": all_annotated_texts,
                    "all_evidence_traces": all_evidence_traces,
                    "role_mapping": {**context.get("role_mapping", {}), **result.get("role_mapping", {})}
                }
            }
        
        elif stage == "term_normalization":
            all_annotated_texts = context.get("all_annotated_texts", [])
            combined_annotated_text = "\n\n".join(all_annotated_texts) if all_annotated_texts else "\n\n".join([self._format_segment(s) for s in segments])
            
            result = self._parse_normalization_response(user_response, combined_annotated_text)
            
            normalized_text = result.get("normalized_text", combined_annotated_text)
            
            return {
                "result": result,
                "next_stage": "field_extraction",
                "next_prompt": self._build_extraction_prompt(normalized_text, context.get("role_mapping", {})),
                "next_description": "阶段3: 字段抽取",
                "context_update": {
                    "normalized_text": normalized_text
                }
            }
        
        elif stage == "field_extraction":
            normalized_text = context.get("normalized_text", "")
            if not normalized_text:
                all_annotated_texts = context.get("all_annotated_texts", [])
                normalized_text = "\n\n".join(all_annotated_texts) if all_annotated_texts else "\n\n".join([self._format_segment(s) for s in segments])
            
            all_evidence_traces = context.get("all_evidence_traces", [])
            result = self._parse_extraction_response(user_response, all_evidence_traces)
            
            return {
                "result": result,
                "next_stage": "emr_generation",
                "next_prompt": self._build_emr_generation_prompt(result, context.get("role_mapping", {})),
                "next_description": "阶段4: 病历生成",
                "context_update": {
                    "extraction_result": result
                }
            }
        
        elif stage == "emr_generation":
            extraction_result = context.get("extraction_result", {})
            result = self._parse_emr_response(user_response, extraction_result, visit_id, True)
            
            return {
                "result": result,
                "next_stage": None,
                "next_prompt": None,
                "next_description": None,
                "completed": True
            }
        
        return {"error": f"未知阶段: {stage}"}
