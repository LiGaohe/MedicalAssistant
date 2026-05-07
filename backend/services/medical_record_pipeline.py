import asyncio
import time
from typing import Dict, Any, Optional, List, Tuple
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy.orm import Session
from ..models import EMRRecord, EvidenceSpan, NormalizedTerm, ExtractedItem, Visit, TranscriptTurn
from .evidence_service import EvidenceService
from .terminology_service import TerminologyService
from .extraction_service import ExtractionService
from .emr_generation_service import EMRGenerationService
from .llm.llm_service import LLMService
from .llm.prompts import PromptManager
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
        save_intermediate: bool = True,
        use_parallel: bool = True
    ) -> Dict[str, Any]:
        logger.info(f"=== 开始处理就诊记录: {visit_id} ===")
        logger.info(f"参数: use_llm={use_llm}, save_intermediate={save_intermediate}, use_parallel={use_parallel}")
        
        start_time = time.time()
        
        if use_parallel:
            try:
                result = run_async(
                    self._process_visit_parallel(visit_id, use_llm, save_intermediate)
                )
            except Exception as e:
                logger.warning(f"并行处理失败，回退到串行模式: {e}")
                result = self._process_visit_serial(visit_id, use_llm, save_intermediate)
        else:
            result = self._process_visit_serial(visit_id, use_llm, save_intermediate)
        
        elapsed_time = time.time() - start_time
        result["processing_time"] = elapsed_time
        logger.info(f"=== 就诊记录处理完成: {visit_id}, 耗时: {elapsed_time:.2f}秒 ===")
        
        return result
    
    async def _process_visit_parallel(
        self,
        visit_id: str,
        use_llm: bool,
        save_intermediate: bool
    ) -> Dict[str, Any]:
        logger.info("使用并行模式处理")
        
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
            "errors": [],
            "parallel_mode": True,
            "skipped_steps": []
        }
        
        try:
            turns_count = self.db.query(TranscriptTurn).filter(
                TranscriptTurn.visit_id == visit_id
            ).count()
            
            if turns_count == 0:
                logger.warning("没有对话轮次，跳过证据选择和术语规范化")
                result["skipped_steps"].extend(["evidence_selection", "terminology_normalization"])
                evidence_spans = []
                normalized_terms = []
            else:
                logger.info(">>> 并行执行: 证据选择 + 术语规范化")
                step_start = time.time()
                
                evidence_task = asyncio.create_task(
                    self._step_evidence_selection_async(visit_id, use_llm, save_intermediate)
                )
                terminology_task = asyncio.create_task(
                    self._step_terminology_normalization_async(visit_id, save_intermediate)
                )
                
                evidence_spans, normalized_terms = await asyncio.gather(
                    evidence_task,
                    terminology_task,
                    return_exceptions=True
                )
                
                if isinstance(evidence_spans, Exception):
                    logger.error(f"证据选择失败: {evidence_spans}")
                    evidence_spans = []
                    result["errors"].append(f"证据选择失败: {str(evidence_spans)}")
                
                if isinstance(normalized_terms, Exception):
                    logger.error(f"术语规范化失败: {normalized_terms}")
                    normalized_terms = []
                    result["errors"].append(f"术语规范化失败: {str(normalized_terms)}")
                
                parallel_time = time.time() - step_start
                logger.info(f"并行步骤完成，耗时: {parallel_time:.2f}秒")
            
            result["evidence_count"] = len(evidence_spans)
            result["normalized_terms_count"] = len(normalized_terms)
            logger.info(f"证据选择完成，共找到 {len(evidence_spans)} 条证据")
            logger.info(f"术语规范化完成，共规范化 {len(normalized_terms)} 个术语")
            
            if result["normalized_terms_count"] == 0:
                logger.info("未识别到术语，已跳过术语规范化")
                if "terminology_normalization" not in result["skipped_steps"]:
                    result["skipped_steps"].append("terminology_normalization_empty")
            
            logger.info(">>> 步骤3: 病历要素抽取")
            step_start = time.time()
            
            if result["evidence_count"] == 0:
                logger.warning("没有证据，使用默认模板生成病历")
                result["skipped_steps"].append("extraction_no_evidence")
                extracted_items = []
            else:
                extracted_items = self._step_extraction(visit_id, use_llm, save_intermediate)
            
            result["extracted_items_count"] = len(extracted_items)
            logger.info(f"病历要素抽取完成，耗时: {time.time() - step_start:.2f}秒，共抽取 {len(extracted_items)} 个字段")
            
            logger.info(">>> 步骤4: 病历生成")
            step_start = time.time()
            emr_record = self._step_emr_generation(visit_id, use_llm, save_intermediate)
            result["emr_record"] = emr_record.to_dict() if emr_record else None
            logger.info(f"病历生成完成，耗时: {time.time() - step_start:.2f}秒")
            
            result["status"] = "completed"
            
        except Exception as e:
            logger.error(f"并行处理失败: {str(e)}", exc_info=True)
            result["status"] = "failed"
            result["errors"].append(str(e))
            
        return result
    
    def _process_visit_serial(
        self,
        visit_id: str,
        use_llm: bool,
        save_intermediate: bool
    ) -> Dict[str, Any]:
        logger.info("使用串行模式处理")
        
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
            "errors": [],
            "parallel_mode": False,
            "skipped_steps": []
        }
        
        try:
            turns_count = self.db.query(TranscriptTurn).filter(
                TranscriptTurn.visit_id == visit_id
            ).count()
            
            if turns_count == 0:
                logger.warning("没有对话轮次，跳过证据选择和术语规范化")
                result["skipped_steps"].extend(["evidence_selection", "terminology_normalization"])
                evidence_spans = []
                normalized_terms = []
            else:
                logger.info(">>> 步骤1: 证据选择")
                step_start = time.time()
                evidence_spans = self._step_evidence_selection(visit_id, use_llm, save_intermediate)
                result["evidence_count"] = len(evidence_spans)
                logger.info(f"证据选择完成，耗时: {time.time() - step_start:.2f}秒，共找到 {len(evidence_spans)} 条证据")
                
                logger.info(">>> 步骤2: 术语规范化")
                step_start = time.time()
                normalized_terms = self._step_terminology_normalization(visit_id, save_intermediate)
                result["normalized_terms_count"] = len(normalized_terms)
                logger.info(f"术语规范化完成，耗时: {time.time() - step_start:.2f}秒，共规范化 {len(normalized_terms)} 个术语")
                
                if result["normalized_terms_count"] == 0:
                    logger.info("未识别到术语，术语规范化步骤实际未产生结果")
                    result["skipped_steps"].append("terminology_normalization_empty")
            
            logger.info(">>> 步骤3: 病历要素抽取")
            step_start = time.time()
            
            if result["evidence_count"] == 0:
                logger.warning("没有证据，跳过要素抽取")
                result["skipped_steps"].append("extraction_no_evidence")
                extracted_items = []
            else:
                extracted_items = self._step_extraction(visit_id, use_llm, save_intermediate)
            
            result["extracted_items_count"] = len(extracted_items)
            logger.info(f"病历要素抽取完成，耗时: {time.time() - step_start:.2f}秒，共抽取 {len(extracted_items)} 个字段")
            
            logger.info(">>> 步骤4: 病历生成")
            step_start = time.time()
            emr_record = self._step_emr_generation(visit_id, use_llm, save_intermediate)
            result["emr_record"] = emr_record.to_dict() if emr_record else None
            logger.info(f"病历生成完成，耗时: {time.time() - step_start:.2f}秒")
            
            result["status"] = "completed"
            
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
    
    async def _step_evidence_selection_async(
        self,
        visit_id: str,
        use_llm: bool,
        save: bool
    ) -> list:
        return self._step_evidence_selection(visit_id, use_llm, save)
        
    def _step_terminology_normalization(
        self, 
        visit_id: str,
        save: bool
    ) -> list:
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
    
    async def _step_terminology_normalization_async(
        self,
        visit_id: str,
        save: bool
    ) -> list:
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
