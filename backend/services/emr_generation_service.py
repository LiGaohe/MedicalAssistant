import json
import asyncio
import time
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from ..models import EMRRecord, ExtractedItem, TranscriptTurn, Visit
from .llm.llm_service import LLMService
from .llm.prompts import PromptManager
from .validation_service import ValidationService
from ..utils.logger import logger


class EMRGenerationService:
    def __init__(self, db: Session, llm_service: Optional[LLMService] = None, language: str = "zh"):
        self.db = db
        self.llm_service = llm_service
        self.language = language
        self.prompt_manager = PromptManager(language=language)
        self.validation_service = ValidationService()
        logger.info(f"EMRGenerationService initialized with language: {language}")
        
    def generate_emr(
        self, 
        visit_id: str,
        use_llm: bool = True
    ) -> EMRRecord:
        logger.info(f"开始生成病历，visit_id={visit_id}")
        
        items = self.db.query(ExtractedItem).filter(
            ExtractedItem.visit_id == visit_id
        ).all()
        
        turns = self.db.query(TranscriptTurn).filter(
            TranscriptTurn.visit_id == visit_id
        ).order_by(TranscriptTurn.turn_index).all()
        
        logger.info(f"查询到 {len(items)} 个抽取字段, {len(turns)} 条对话")
        
        if not items:
            logger.warning("没有抽取字段，创建空病历")
            return self._create_empty_emr(visit_id)
            
        if use_llm and self.llm_service:
            logger.info("使用LLM生成病历")
            return self._generate_by_llm(visit_id, items, turns)
        else:
            logger.info("使用模板生成病历")
            return self._generate_by_template(visit_id, items, turns)
            
    def _generate_by_llm(
        self, 
        visit_id: str,
        items: list,
        turns: list
    ) -> EMRRecord:
        extracted_data = self._aggregate_items(items)
        transcript = self._format_transcript(turns)
        
        if self.language == "en":
            template_requirements = "Compliant with international medical record writing standards (SOAP format)"
        else:
            template_requirements = "符合中国医疗病历书写规范"
        
        try:
            response = self.llm_service.generate_with_template(
                "emr_generation_with_role",
                extracted_data=json.dumps(extracted_data, ensure_ascii=False),
                transcript=transcript,
                template_requirements=template_requirements
            )
            
            result = json.loads(response.text)
            
            latest_version = self._get_latest_version(visit_id)
            
            emr = EMRRecord(
                visit_id=visit_id,
                version=latest_version + 1,
                record_type="system_draft",
                emr_json=result,
                evidence_mapping=self._build_evidence_mapping(items)
            )
            
            return emr
            
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            return self._generate_by_template(visit_id, items, turns)
            
    def _generate_by_template(
        self, 
        visit_id: str,
        items: list,
        turns: list
    ) -> EMRRecord:
        logger.info("开始模板生成病历")
        start_time = time.time()
        
        role_mapping = self._infer_roles(turns)
        logger.info(f"推断角色映射: {role_mapping}")
        
        aggregated = self._aggregate_items(items)
        logger.debug(f"聚合数据: {aggregated}")
        
        subjective = self._generate_subjective(aggregated, role_mapping, turns)
        objective = self._generate_objective(aggregated, role_mapping, turns)
        assessment = self._generate_assessment(aggregated, role_mapping, turns)
        plan = self._generate_plan(aggregated, role_mapping, turns)
        
        emr_json = {
            "subjective": subjective,
            "objective": objective,
            "assessment": assessment,
            "plan": plan
        }
        
        logger.info(f"生成的病历JSON: {emr_json}")
        
        latest_version = self._get_latest_version(visit_id)
        
        emr = EMRRecord(
            visit_id=visit_id,
            version=latest_version + 1,
            record_type="system_draft",
            emr_json=emr_json,
            evidence_mapping=self._build_evidence_mapping(items)
        )
        
        elapsed_time = time.time() - start_time
        logger.info(f"病历生成完成，版本: {emr.version}，耗时: {elapsed_time:.2f}秒")
        return emr
        
    def _generate_subjective(self, aggregated: Dict[str, Any], role_mapping: Dict[str, str], turns: list) -> Dict[str, Any]:
        subjective = aggregated.get("subjective", {})
        
        chief_complaint = subjective.get("chief_complaint", {})
        history = subjective.get("history_present_illness", {})
        past_history = subjective.get("past_history", {})
        
        patient_speaker = self._get_patient_speaker(role_mapping)
        
        patient_texts = []
        for turn in turns:
            if turn.speaker == patient_speaker:
                patient_texts.append(turn.text)
        
        text_parts = []
        
        if chief_complaint.get("value"):
            corrected_value = self._correct_content_by_role(
                chief_complaint["value"], 
                "chief_complaint", 
                role_mapping, 
                turns
            )
            text_parts.append(f"主诉：{corrected_value}")
            chief_complaint = {**chief_complaint, "value": corrected_value}
            
        if history.get("value"):
            corrected_value = self._correct_content_by_role(
                history["value"], 
                "history_present_illness", 
                role_mapping, 
                turns
            )
            text_parts.append(f"现病史：{corrected_value}")
            history = {**history, "value": corrected_value}
            
        if past_history.get("value"):
            corrected_value = self._correct_content_by_role(
                past_history["value"], 
                "past_history", 
                role_mapping, 
                turns
            )
            text_parts.append(f"既往史：{corrected_value}")
            past_history = {**past_history, "value": corrected_value}
            
        return {
            "text": "\n".join(text_parts),
            "chief_complaint": chief_complaint,
            "history_present_illness": history,
            "past_history": past_history
        }
        
    def _generate_objective(self, aggregated: Dict[str, Any], role_mapping: Dict[str, str], turns: list) -> Dict[str, Any]:
        objective = aggregated.get("objective", {})
        
        physical = objective.get("physical_examination", {})
        auxiliary = objective.get("auxiliary_examination", {})
        
        text_parts = []
        
        if physical.get("value"):
            corrected_value = self._correct_content_by_role(
                physical["value"], 
                "physical_examination", 
                role_mapping, 
                turns
            )
            text_parts.append(f"体格检查：{corrected_value}")
            physical = {**physical, "value": corrected_value}
            
        if auxiliary.get("value"):
            corrected_value = self._correct_content_by_role(
                auxiliary["value"], 
                "auxiliary_examination", 
                role_mapping, 
                turns
            )
            text_parts.append(f"辅助检查：{corrected_value}")
            auxiliary = {**auxiliary, "value": corrected_value}
            
        return {
            "text": "\n".join(text_parts),
            "physical_examination": physical,
            "auxiliary_examination": auxiliary
        }
        
    def _generate_assessment(self, aggregated: Dict[str, Any], role_mapping: Dict[str, str], turns: list) -> Dict[str, Any]:
        assessment = aggregated.get("assessment", {})
        
        diagnosis = assessment.get("diagnosis", {})
        
        if diagnosis.get("value"):
            corrected_value = self._correct_content_by_role(
                diagnosis["value"], 
                "diagnosis", 
                role_mapping, 
                turns
            )
            diagnosis = {**diagnosis, "value": corrected_value}
            text = f"诊断：{corrected_value}"
        else:
            text = "诊断：待定"
        
        return {
            "text": text,
            "diagnosis": diagnosis
        }
        
    def _generate_plan(self, aggregated: Dict[str, Any], role_mapping: Dict[str, str], turns: list) -> Dict[str, Any]:
        plan = aggregated.get("plan", {})
        
        treatment = plan.get("treatment", {})
        advice = plan.get("advice", {})
        
        text_parts = []
        
        if treatment.get("value"):
            corrected_value = self._correct_content_by_role(
                treatment["value"], 
                "treatment", 
                role_mapping, 
                turns
            )
            text_parts.append(f"治疗方案：{corrected_value}")
            treatment = {**treatment, "value": corrected_value}
            
        if advice.get("value"):
            corrected_value = self._correct_content_by_role(
                advice["value"], 
                "advice", 
                role_mapping, 
                turns
            )
            text_parts.append(f"医嘱：{corrected_value}")
            advice = {**advice, "value": corrected_value}
            
        return {
            "text": "\n".join(text_parts),
            "treatment": treatment,
            "advice": advice
        }
        
    def _infer_roles(self, turns: list) -> Dict[str, str]:
        if not turns:
            return {}
        
        if self.language == "en":
            doctor_indicators = [
                "how can I help", "what brings you", "how long", "do you have",
                "let me", "examine", "diagnosis", "I think", "prescribe", 
                "need to", "recommend", "treatment", "please", "have you",
                "are you", "does it", "where does", "when did"
            ]
            
            patient_indicators = [
                "doctor", "I have", "I feel", "my", "hurting", "pain",
                "discomfort", "days", "sometimes", "no", "okay", "thank you",
                "I've been", "it hurts", "I'm having"
            ]
        else:
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
        
        for turn in turns:
            speaker = turn.speaker
            if speaker not in speaker_scores:
                speaker_scores[speaker] = {"doctor": 0, "patient": 0}
            
            text = turn.text.lower() if self.language == "en" else turn.text
            
            for indicator in doctor_indicators:
                if indicator.lower() in text if self.language == "en" else indicator in text:
                    speaker_scores[speaker]["doctor"] += 1
            
            for indicator in patient_indicators:
                if indicator.lower() in text if self.language == "en" else indicator in text:
                    speaker_scores[speaker]["patient"] += 1
            
            if text.endswith("？") or text.endswith("?"):
                speaker_scores[speaker]["doctor"] += 2
            
            if self.language == "zh" and text.startswith("医生"):
                speaker_scores[speaker]["patient"] += 3
            
            if self.language == "en" and text.startswith("doctor"):
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
    
    def _get_patient_speaker(self, role_mapping: Dict[str, str]) -> Optional[str]:
        for speaker, role in role_mapping.items():
            if role == "patient":
                return speaker
        return None
    
    def _get_doctor_speaker(self, role_mapping: Dict[str, str]) -> Optional[str]:
        for speaker, role in role_mapping.items():
            if role == "doctor":
                return speaker
        return None
    
    def _format_transcript(self, turns: list) -> str:
        lines = []
        for turn in turns:
            lines.append(f"[{turn.speaker}]: {turn.text}")
        return "\n".join(lines)
    
    def _correct_content_by_role(
        self, 
        content: str, 
        field_type: str, 
        role_mapping: Dict[str, str], 
        turns: list
    ) -> str:
        doctor_speaker = self._get_doctor_speaker(role_mapping)
        patient_speaker = self._get_patient_speaker(role_mapping)
        
        field_role_preference = {
            "chief_complaint": "patient",
            "history_present_illness": "patient",
            "past_history": "patient",
            "physical_examination": "doctor",
            "auxiliary_examination": "doctor",
            "diagnosis": "doctor",
            "treatment": "doctor",
            "advice": "doctor"
        }
        
        field_keywords = {
            "chief_complaint": ["头疼", "不舒服", "痛", "难受", "症状"],
            "history_present_illness": ["天", "周", "月", "开始", "加重", "缓解", "恶心", "呕吐"],
            "physical_examination": ["血压", "心率", "体温", "检查", "听诊", "触诊"],
            "diagnosis": ["诊断", "考虑", "可能是", "引起"],
            "treatment": ["开", "药", "治疗", "输液"],
            "advice": ["注意", "休息", "少吃", "多吃", "复查", "避免"]
        }
        
        expected_role = field_role_preference.get(field_type, "unknown")
        keywords = field_keywords.get(field_type, [])
        
        matched_turn = None
        for turn in turns:
            if content in turn.text or turn.text in content:
                matched_turn = turn
                break
        
        if matched_turn:
            speaker_role = role_mapping.get(matched_turn.speaker, "unknown")
            
            if speaker_role == expected_role:
                return content
            
            for turn in turns:
                turn_role = role_mapping.get(turn.speaker, "unknown")
                if turn_role == expected_role:
                    if any(kw in turn.text for kw in keywords):
                        return turn.text
        
        if expected_role == "patient" and patient_speaker:
            patient_turns = [t for t in turns if t.speaker == patient_speaker]
            for turn in patient_turns:
                if any(kw in turn.text for kw in keywords):
                    return turn.text
            if patient_turns:
                return patient_turns[0].text
        
        if expected_role == "doctor" and doctor_speaker:
            doctor_turns = [t for t in turns if t.speaker == doctor_speaker]
            for turn in doctor_turns:
                if any(kw in turn.text for kw in keywords):
                    return turn.text
        
        return content
        
    def _aggregate_items(self, items: list) -> Dict[str, Any]:
        aggregated = {
            "subjective": {},
            "objective": {},
            "assessment": {},
            "plan": {}
        }
        
        for item in items:
            parts = item.field_name.split(".")
            if len(parts) == 2:
                section, field = parts
                if section in aggregated:
                    if field not in aggregated[section]:
                        aggregated[section][field] = {
                            "value": item.field_value,
                            "evidence_ids": item.evidence_ids or [],
                            "confidence": item.confidence
                        }
                    else:
                        existing = aggregated[section][field]
                        if item.confidence > existing["confidence"]:
                            aggregated[section][field] = {
                                "value": item.field_value,
                                "evidence_ids": item.evidence_ids or [],
                                "confidence": item.confidence
                            }
                    
        return aggregated
        
    def _build_evidence_mapping(self, items: list) -> Dict[str, Any]:
        mapping = {}
        
        for item in items:
            if item.evidence_ids:
                mapping[item.field_name] = item.evidence_ids
                
        return mapping
        
    def _get_latest_version(self, visit_id: str) -> int:
        latest = self.db.query(EMRRecord).filter(
            EMRRecord.visit_id == visit_id
        ).order_by(EMRRecord.version.desc()).first()
        
        return latest.version if latest else 0
        
    def _create_empty_emr(self, visit_id: str) -> EMRRecord:
        return EMRRecord(
            visit_id=visit_id,
            version=1,
            record_type="system_draft",
            emr_json={
                "subjective": {"text": ""},
                "objective": {"text": ""},
                "assessment": {"text": ""},
                "plan": {"text": ""}
            }
        )
        
    def save_emr(self, emr: EMRRecord):
        validation_result = self.validation_service.validate(emr.emr_json)
        emr.validation_errors = self.validation_service.to_dict(validation_result)
        
        self.db.add(emr)
        self.db.commit()
        
        logger.info(f"病历保存成功，验证评分: {validation_result.score:.2%}")
        
    def get_emr_by_visit(
        self, 
        visit_id: str,
        version: Optional[int] = None
    ) -> Optional[EMRRecord]:
        query = self.db.query(EMRRecord).filter(
            EMRRecord.visit_id == visit_id
        )
        
        if version:
            query = query.filter(EMRRecord.version == version)
        else:
            query = query.order_by(EMRRecord.version.desc())
            
        return query.first()
        
    def get_all_versions(self, visit_id: str) -> list:
        return self.db.query(EMRRecord).filter(
            EMRRecord.visit_id == visit_id
        ).order_by(EMRRecord.version).all()
