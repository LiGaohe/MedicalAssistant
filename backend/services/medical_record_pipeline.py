from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from ..models import EMRRecord, EvidenceSpan, NormalizedTerm, ExtractedItem, Visit
from .evidence_service import EvidenceService
from .terminology_service import TerminologyService
from .extraction_service import ExtractionService
from .emr_generation_service import EMRGenerationService
from .llm.llm_service import LLMService
from .llm.prompts import PromptManager
from ..utils.logger import logger


class MedicalRecordPipeline:
    def __init__(self, db: Session, llm_service: Optional[LLMService] = None):
        self.db = db
        self.llm_service = llm_service
        logger.info("MedicalRecordPipeline initialized")
    
    def _get_language(self, visit_id: str) -> str:
        visit = self.db.query(Visit).filter(Visit.visit_id == visit_id).first()
        return visit.language if visit and visit.language else "zh"
    
    def _init_services(self, language: str):
        self.evidence_service = EvidenceService(self.db, self.llm_service)
        self.terminology_service = TerminologyService(self.db, self.llm_service, language=language)
        self.extraction_service = ExtractionService(self.db, self.llm_service, language=language)
        self.emr_generation_service = EMRGenerationService(self.db, self.llm_service, language=language)
        self.prompt_manager = PromptManager(language=language)
        
    def process_visit(
        self, 
        visit_id: str,
        use_llm: bool = True,
        save_intermediate: bool = True
    ) -> Dict[str, Any]:
        logger.info(f"=== 开始处理就诊记录: {visit_id} ===")
        logger.info(f"参数: use_llm={use_llm}, save_intermediate={save_intermediate}")
        
        language = self._get_language(visit_id)
        logger.info(f"检测到语言: {language}")
        self._init_services(language)
        
        result = {
            "visit_id": visit_id,
            "language": language,
            "status": "processing",
            "evidence_count": 0,
            "normalized_terms_count": 0,
            "extracted_items_count": 0,
            "emr_record": None,
            "errors": []
        }
        
        try:
            logger.info(">>> 步骤1: 证据选择")
            evidence_spans = self._step_evidence_selection(
                visit_id, 
                use_llm, 
                save_intermediate
            )
            result["evidence_count"] = len(evidence_spans)
            logger.info(f"证据选择完成，共找到 {len(evidence_spans)} 条证据")
            for i, ev in enumerate(evidence_spans[:5]):
                logger.debug(f"  证据{i+1}: {ev.field_type} - {ev.content[:50]}...")
            
            logger.info(">>> 步骤2: 术语规范化")
            normalized_terms = self._step_terminology_normalization(
                visit_id,
                save_intermediate
            )
            result["normalized_terms_count"] = len(normalized_terms)
            logger.info(f"术语规范化完成，共规范化 {len(normalized_terms)} 个术语")
            for i, term in enumerate(normalized_terms[:5]):
                logger.debug(f"  术语{i+1}: {term.original_term} -> {term.normalized_term}")
            
            logger.info(">>> 步骤3: 病历要素抽取")
            extracted_items = self._step_extraction(
                visit_id,
                use_llm,
                save_intermediate
            )
            result["extracted_items_count"] = len(extracted_items)
            logger.info(f"病历要素抽取完成，共抽取 {len(extracted_items)} 个字段")
            for i, item in enumerate(extracted_items[:5]):
                logger.debug(f"  字段{i+1}: {item.field_name} = {item.field_value[:30]}...")
            
            logger.info(">>> 步骤4: 病历生成")
            emr_record = self._step_emr_generation(
                visit_id,
                use_llm,
                save_intermediate
            )
            result["emr_record"] = emr_record.to_dict() if emr_record else None
            
            if emr_record:
                logger.info(f"病历生成完成，版本: {emr_record.version}")
                logger.debug(f"病历JSON: {emr_record.emr_json}")
            else:
                logger.warning("病历生成失败，返回空病历")
            
            result["status"] = "completed"
            logger.info(f"=== 就诊记录处理完成: {visit_id} ===")
            
        except Exception as e:
            logger.error(f"处理失败: {str(e)}", exc_info=True)
            result["status"] = "failed"
            result["errors"].append(str(e))
            
        return result
        
    def _step_evidence_selection(
        self, 
        visit_id: str,
        use_llm: bool,
        save: bool
    ) -> list:
        if use_llm and self.llm_service:
            evidence_spans = self.evidence_service.select_evidence_by_llm(visit_id)
        else:
            evidence_spans = self.evidence_service.select_evidence_by_rules(visit_id)
            
        if save and evidence_spans:
            self.evidence_service.save_evidence(evidence_spans)
            
        return evidence_spans
        
    def _step_terminology_normalization(
        self, 
        visit_id: str,
        save: bool
    ) -> list:
        from ..models import TranscriptTurn
        
        turns = self.db.query(TranscriptTurn).filter(
            TranscriptTurn.visit_id == visit_id
        ).all()
        
        all_terms = []
        for turn in turns:
            terms = self.terminology_service.extract_and_normalize_terms(
                turn.text,
                context=f"Turn {turn.turn_index}"
            )
            
            if save and terms:
                self.terminology_service.save_normalized_terms(
                    terms, 
                    visit_id, 
                    turn.turn_id
                )
                
            all_terms.extend(terms)
            
        return all_terms
        
    def _step_extraction(
        self, 
        visit_id: str,
        use_llm: bool,
        save: bool
    ) -> list:
        extracted_items = self.extraction_service.extract_items(
            visit_id,
            use_llm=use_llm
        )
        
        if save and extracted_items:
            self.extraction_service.save_extracted_items(extracted_items)
            
        return extracted_items
        
    def _step_emr_generation(
        self, 
        visit_id: str,
        use_llm: bool,
        save: bool
    ) -> Optional[EMRRecord]:
        emr_record = self.emr_generation_service.generate_emr(
            visit_id,
            use_llm=use_llm
        )
        
        if save and emr_record:
            self.emr_generation_service.save_emr(emr_record)
            
        return emr_record
        
    def get_processing_status(self, visit_id: str) -> Dict[str, Any]:
        evidence_count = self.db.query(EvidenceSpan).filter(
            EvidenceSpan.visit_id == visit_id
        ).count()
        
        terms_count = self.db.query(NormalizedTerm).filter(
            NormalizedTerm.visit_id == visit_id
        ).count()
        
        items_count = self.db.query(ExtractedItem).filter(
            ExtractedItem.visit_id == visit_id
        ).count()
        
        emr = self.db.query(EMRRecord).filter(
            EMRRecord.visit_id == visit_id
        ).order_by(EMRRecord.version.desc()).first()
        
        return {
            "visit_id": visit_id,
            "evidence_count": evidence_count,
            "normalized_terms_count": terms_count,
            "extracted_items_count": items_count,
            "has_emr": emr is not None,
            "emr_version": emr.version if emr else 0,
            "latest_record_id": emr.record_id if emr else None
        }
