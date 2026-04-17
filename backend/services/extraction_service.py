import json
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from ..models import ExtractedItem, EvidenceSpan
from .llm.llm_service import LLMService
from ..utils.logger import logger


class ExtractionService:
    def __init__(self, db: Session, llm_service: Optional[LLMService] = None):
        self.db = db
        self.llm_service = llm_service
        logger.info("ExtractionService initialized")
        
    def extract_items(
        self, 
        visit_id: str,
        use_llm: bool = True
    ) -> List[ExtractedItem]:
        logger.info(f"开始抽取病历要素，visit_id={visit_id}")
        
        evidence_list = self.db.query(EvidenceSpan).filter(
            EvidenceSpan.visit_id == visit_id
        ).order_by(EvidenceSpan.score.desc()).all()
        
        logger.info(f"查询到 {len(evidence_list)} 条证据")
        
        if not evidence_list:
            logger.warning("没有找到证据，返回空列表")
            return []
            
        if use_llm and self.llm_service:
            logger.info("使用LLM进行抽取")
            return self._extract_by_llm(visit_id, evidence_list)
        else:
            logger.info("使用规则进行抽取")
            return self._extract_by_rules(visit_id, evidence_list)
            
    def _extract_by_llm(
        self, 
        visit_id: str,
        evidence_list: List[EvidenceSpan]
    ) -> List[ExtractedItem]:
        normalized_text = self._format_evidence(evidence_list)
        
        try:
            response = self.llm_service.generate_with_template(
                "item_extraction",
                normalized_text=normalized_text
            )
            
            result = json.loads(response.text)
            items = []
            
            for section, fields in result.items():
                if isinstance(fields, dict):
                    for field_name, field_data in fields.items():
                        if isinstance(field_data, dict) and "value" in field_data:
                            item = ExtractedItem(
                                visit_id=visit_id,
                                field_name=f"{section}.{field_name}",
                                field_value=field_data.get("value", ""),
                                evidence_ids=field_data.get("evidence_ids", []),
                                confidence=field_data.get("confidence", 0.5)
                            )
                            items.append(item)
                            
            return items
            
        except Exception as e:
            print(f"LLM extraction failed: {e}")
            return self._extract_by_rules(visit_id, evidence_list)
            
    def _extract_by_rules(
        self, 
        visit_id: str,
        evidence_list: List[EvidenceSpan]
    ) -> List[ExtractedItem]:
        logger.info("开始规则抽取")
        items = []
        
        field_mapping = {
            "chief_complaint": "subjective.chief_complaint",
            "history_present_illness": "subjective.history_present_illness",
            "past_history": "subjective.past_history",
            "physical_examination": "objective.physical_examination",
            "auxiliary_examination": "objective.auxiliary_examination",
            "diagnosis": "assessment.diagnosis",
            "treatment_plan": "plan.treatment",
            "advice": "plan.advice"
        }
        
        for evidence in evidence_list:
            field_type = evidence.field_type
            if field_type in field_mapping:
                item = ExtractedItem(
                    visit_id=visit_id,
                    field_name=field_mapping[field_type],
                    field_value=evidence.content,
                    evidence_ids=[evidence.evidence_id],
                    confidence=evidence.confidence
                )
                items.append(item)
                logger.debug(f"  抽取字段: {field_mapping[field_type]} = {evidence.content[:30]}...")
                
        logger.info(f"规则抽取完成，共 {len(items)} 个字段")
        return items
        
    def _format_evidence(self, evidence_list: List[EvidenceSpan]) -> str:
        lines = []
        for evidence in evidence_list:
            lines.append(
                f"[{evidence.evidence_id}] {evidence.field_type}: {evidence.content}"
            )
        return "\n".join(lines)
        
    def save_extracted_items(self, items: List[ExtractedItem]):
        for item in items:
            self.db.add(item)
        self.db.commit()
        
    def get_extracted_items_by_visit(
        self, 
        visit_id: str
    ) -> List[ExtractedItem]:
        return self.db.query(ExtractedItem).filter(
            ExtractedItem.visit_id == visit_id
        ).order_by(ExtractedItem.field_name).all()
        
    def aggregate_items(
        self, 
        visit_id: str
    ) -> Dict[str, Any]:
        items = self.get_extracted_items_by_visit(visit_id)
        
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
