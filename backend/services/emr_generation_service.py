import json
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from ..models import EMRRecord, ExtractedItem
from .llm.llm_service import LLMService
from ..utils.logger import logger


class EMRGenerationService:
    def __init__(self, db: Session, llm_service: Optional[LLMService] = None):
        self.db = db
        self.llm_service = llm_service
        logger.info("EMRGenerationService initialized")
        
    def generate_emr(
        self, 
        visit_id: str,
        use_llm: bool = True
    ) -> EMRRecord:
        logger.info(f"开始生成病历，visit_id={visit_id}")
        
        items = self.db.query(ExtractedItem).filter(
            ExtractedItem.visit_id == visit_id
        ).all()
        
        logger.info(f"查询到 {len(items)} 个抽取字段")
        
        if not items:
            logger.warning("没有抽取字段，创建空病历")
            return self._create_empty_emr(visit_id)
            
        if use_llm and self.llm_service:
            logger.info("使用LLM生成病历")
            return self._generate_by_llm(visit_id, items)
        else:
            logger.info("使用模板生成病历")
            return self._generate_by_template(visit_id, items)
            
    def _generate_by_llm(
        self, 
        visit_id: str,
        items: list
    ) -> EMRRecord:
        extracted_data = self._aggregate_items(items)
        
        try:
            response = self.llm_service.generate_with_template(
                "emr_generation",
                extracted_data=json.dumps(extracted_data, ensure_ascii=False),
                template_requirements="符合中国医疗病历书写规范"
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
            print(f"LLM generation failed: {e}")
            return self._generate_by_template(visit_id, items)
            
    def _generate_by_template(
        self, 
        visit_id: str,
        items: list
    ) -> EMRRecord:
        logger.info("开始模板生成病历")
        aggregated = self._aggregate_items(items)
        logger.debug(f"聚合数据: {aggregated}")
        
        emr_json = {
            "subjective": self._generate_subjective(aggregated),
            "objective": self._generate_objective(aggregated),
            "assessment": self._generate_assessment(aggregated),
            "plan": self._generate_plan(aggregated)
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
        
        logger.info(f"病历生成完成，版本: {emr.version}")
        return emr
        
    def _generate_subjective(self, aggregated: Dict[str, Any]) -> Dict[str, Any]:
        subjective = aggregated.get("subjective", {})
        
        chief_complaint = subjective.get("chief_complaint", {})
        history = subjective.get("history_present_illness", {})
        past_history = subjective.get("past_history", {})
        
        text_parts = []
        
        if chief_complaint.get("value"):
            text_parts.append(f"主诉：{chief_complaint['value']}")
            
        if history.get("value"):
            text_parts.append(f"现病史：{history['value']}")
            
        if past_history.get("value"):
            text_parts.append(f"既往史：{past_history['value']}")
            
        return {
            "text": "\n".join(text_parts),
            "chief_complaint": chief_complaint,
            "history_present_illness": history,
            "past_history": past_history
        }
        
    def _generate_objective(self, aggregated: Dict[str, Any]) -> Dict[str, Any]:
        objective = aggregated.get("objective", {})
        
        physical = objective.get("physical_examination", {})
        auxiliary = objective.get("auxiliary_examination", {})
        
        text_parts = []
        
        if physical.get("value"):
            text_parts.append(f"体格检查：{physical['value']}")
            
        if auxiliary.get("value"):
            text_parts.append(f"辅助检查：{auxiliary['value']}")
            
        return {
            "text": "\n".join(text_parts),
            "physical_examination": physical,
            "auxiliary_examination": auxiliary
        }
        
    def _generate_assessment(self, aggregated: Dict[str, Any]) -> Dict[str, Any]:
        assessment = aggregated.get("assessment", {})
        
        diagnosis = assessment.get("diagnosis", {})
        
        text = f"诊断：{diagnosis.get('value', '待定')}" if diagnosis.get("value") else "诊断：待定"
        
        return {
            "text": text,
            "diagnosis": diagnosis
        }
        
    def _generate_plan(self, aggregated: Dict[str, Any]) -> Dict[str, Any]:
        plan = aggregated.get("plan", {})
        
        treatment = plan.get("treatment", {})
        advice = plan.get("advice", {})
        
        text_parts = []
        
        if treatment.get("value"):
            text_parts.append(f"治疗方案：{treatment['value']}")
            
        if advice.get("value"):
            text_parts.append(f"医嘱：{advice['value']}")
            
        return {
            "text": "\n".join(text_parts),
            "treatment": treatment,
            "advice": advice
        }
        
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
        self.db.add(emr)
        self.db.commit()
        
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
