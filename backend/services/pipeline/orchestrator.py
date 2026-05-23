import json
import re
import time
import asyncio
import uuid
from typing import Dict, Any, Optional, List, Tuple
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy.orm import Session
from ...models import TranscriptTurn, EMRRecord, EvidenceSpan, NormalizedTerm, AtomicFact
from ..llm.llm_service import LLMService
from ..llm.prompts import PromptManager
from ..evaluation_service import EMREvaluationService
from ..validation_service import ValidationService
from ..terminology_service import TerminologyService
from ..fact_service import FactService
from ...config import settings
from ...utils.logger import logger
from .utils import parse_json_response
from .base import PipelineContext
from .speaker_handler import SpeakerHandler, FIELD_TYPE_MAPPING, FIELD_EXPECTED_ROLE
from .debug_interactor import DebugInteractor
from .evidence_enricher import EvidenceEnricher
from .emr_persistence import EMRPersistence
from .interactive import InteractivePipelineService
from .stages.turn_cleaning import TurnCleaningStage
from .stages.fact_extraction import FactExtractionStage
from .stages.fact_consolidation import FactConsolidationStage
from .stages.term_normalization import TermNormalizationStage
from .stages.soap_generation import SOAPGenerationStage
from .stages.verification import VerificationStage


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


class PipelineOrchestrator:
    STAGE_DELAY = 0.5
    
    MAX_PARALLEL_SEGMENTS = 4
    
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
        self.speaker_handler = SpeakerHandler(db)
        self.debug_interactor = DebugInteractor(self.llm_service)
        self.emr_persistence = EMRPersistence(db, self.validation_service)
        self.interactive_service = InteractivePipelineService(self)
        logger.info(f"PipelineOrchestrator initialized, debug_mode={self.debug_mode}, language={language}, UMLS={'enabled' if self.terminology_service.umls_client else 'disabled'}")
    
    
        
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
        
        ctx = PipelineContext(
            db=self.db,
            llm_service=self.llm_service,
            prompt_manager=self.prompt_manager,
            language=self.language,
            debug_mode=self.debug_mode,
            visit_id=visit_id,
            turns=turns,
            save_evidence=save_evidence
        )
        
        TurnCleaningStage().execute(ctx)
        all_role_mappings = ctx.all_role_mappings
        all_cleaned_turns = ctx.all_cleaned_turns
        combined_text = ctx.combined_text
        
        time.sleep(self.STAGE_DELAY)
        
        fact_result = FactExtractionStage().execute(ctx)
        logger.info(f"事实抽取阶段完成，共 {fact_result.get('fact_count', 0)} 条事实，耗时统计见上")
        
        time.sleep(self.STAGE_DELAY)
        
        fact_service = FactService(self.db)
        fact_records = fact_service.get_facts_by_visit(visit_id)
        ctx.fact_records = fact_records
        consolidation_result = FactConsolidationStage().execute(ctx)
        logger.info(f"事实收束阶段完成，耗时统计见上")
        
        time.sleep(self.STAGE_DELAY)
        
        fact_records = fact_service.get_facts_by_visit(visit_id)
        ctx.fact_records = fact_records
        logger.info(f"从数据库查询到 {len(fact_records)} 条原子事实用于阶段3规范化")
        normalized_result = TermNormalizationStage().execute(ctx)
        logger.info(f"术语规范化阶段完成，耗时统计见上")
        
        time.sleep(self.STAGE_DELAY)
        
        extraction_result = fact_result
        
        time.sleep(self.STAGE_DELAY)
        
        fact_records = fact_service.get_facts_by_visit(visit_id)
        ctx.fact_records = fact_records
        soap_result = SOAPGenerationStage().execute(ctx)
        emr_draft = ctx.emr_draft
        so_used_fact_ids = emr_draft.get("so_used_fact_ids", [])
        assessment_items = emr_draft.get("assessment_items", [])
        plan_items = emr_draft.get("plan_items", {})
        logger.info(f"病历生成阶段完成（SO/AP分节），S/O使用fact数={len(so_used_fact_ids)}, 评估项数={len(assessment_items)}")
        
        time.sleep(self.STAGE_DELAY)
        
        fact_records = fact_service.get_facts_by_visit(visit_id)
        ctx.fact_records = fact_records
        verification_result = VerificationStage().execute(ctx)
        logger.info(f"核查修订阶段完成，耗时统计见上")
        
        emr_final = verification_result.get("soap_final", emr_draft)
        emr_final["so_used_fact_ids"] = so_used_fact_ids
        emr_final["assessment_items"] = assessment_items
        emr_final["plan_items"] = plan_items
        
        emr_final = self.emr_persistence.normalize_format(emr_final)
        emr_final = EvidenceEnricher.enrich(emr_final, fact_records, turns)
        if save_evidence and visit_id:
            self.emr_persistence.save_evidence_spans_from_emr(emr_final, visit_id)
            self.emr_persistence.save_emr_record(emr_final, visit_id)
            logger.info(f"已保存最终病历记录及证据溯源到数据库: visit_id={visit_id}")
        
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
    
    def process_with_callback(
        self,
        visit_id: str,
        progress_callback=None,
        save_evidence: bool = True
    ):
        """
        带进度回调的处理方法，用于SSE实时推送进度。
        
        Args:
            visit_id: 就诊ID
            progress_callback: 进度回调函数，签名为 callback(stage_num, stage_name, status, detail, extra)
            save_evidence: 是否保存证据
        
        Yields:
            进度事件字典 {"stage": int, "name": str, "status": str, "detail": str, "extra": dict}
        """
        def emit_progress(stage_num, stage_name, status, detail="", extra=None):
            event = {
                "stage": stage_num,
                "name": stage_name,
                "status": status,
                "detail": detail
            }
            if extra:
                event["extra"] = extra
            if progress_callback:
                progress_callback(event)
            return event
        
        logger.info(f"=== 开始多阶段LLM处理(带回调): {visit_id} ===")
        start_time = time.time()
        
        turns = self.db.query(TranscriptTurn).filter(
            TranscriptTurn.visit_id == visit_id
        ).order_by(TranscriptTurn.turn_index).all()
        
        if not turns:
            logger.warning("没有找到对话轮次")
            yield emit_progress(0, "初始化", "failed", "没有找到对话轮次")
            return
        
        ctx = PipelineContext(
            db=self.db,
            llm_service=self.llm_service,
            prompt_manager=self.prompt_manager,
            language=self.language,
            debug_mode=self.debug_mode,
            visit_id=visit_id,
            turns=turns,
            save_evidence=save_evidence
        )
        
        segment_start = time.time()
        yield emit_progress(1, "转写清洗与角色纠错", "running", "正在处理段落...")
        
        TurnCleaningStage().execute(ctx)
        all_role_mappings = ctx.all_role_mappings
        all_cleaned_turns = ctx.all_cleaned_turns
        combined_text = ctx.combined_text
        
        yield emit_progress(1, "转写清洗与角色纠错", "completed", 
                           f"完成，清洗 {len(all_cleaned_turns)} 个轮次，耗时 {time.time() - segment_start:.2f}秒")
        
        time.sleep(self.STAGE_DELAY)
        
        yield emit_progress(2, "事实抽取与证据绑定", "running", "正在抽取临床事实...")
        
        fact_result = FactExtractionStage().execute(ctx)
        logger.info(f"事实抽取阶段完成，共 {fact_result.get('fact_count', 0)} 条事实")
        
        yield emit_progress(2, "事实抽取与证据绑定", "completed", 
                           f"抽取 {fact_result.get('fact_count', 0)} 条原子事实")
        
        time.sleep(self.STAGE_DELAY)
        
        fact_service = FactService(self.db)
        fact_records = fact_service.get_facts_by_visit(visit_id)
        ctx.fact_records = fact_records
        
        yield emit_progress(2.5, "事实收束", "running", "正在合并重复事实...")
        
        consolidation_result = FactConsolidationStage().execute(ctx)
        
        resolved_count = consolidation_result.get("resolved_count", 0) if consolidation_result else 0
        yield emit_progress(2.5, "事实收束", "completed", 
                           f"合并 {resolved_count} 条重复事实")
        
        time.sleep(self.STAGE_DELAY)
        
        fact_records = fact_service.get_facts_by_visit(visit_id)
        ctx.fact_records = fact_records
        logger.info(f"从数据库查询到 {len(fact_records)} 条原子事实用于阶段3规范化")
        
        qualifying_count = len([f for f in fact_records if f.normalization_needed and f.mention])
        yield emit_progress(3, "选择性术语规范化", "running", 
                           f"正在规范化 {qualifying_count} 个术语...")
        
        normalized_result = TermNormalizationStage().execute(ctx)
        
        yield emit_progress(3, "选择性术语规范化", "completed", 
                           f"规范化 {normalized_result.get('processed_count', 0)} 个术语")
        
        time.sleep(self.STAGE_DELAY)
        
        extraction_result = fact_result
        
        fact_records = fact_service.get_facts_by_visit(visit_id)
        ctx.fact_records = fact_records
        yield emit_progress(4, "分节生成SOAP病历", "running", "正在生成主观和客观部分...")
        
        soap_result = SOAPGenerationStage().execute(ctx)
        emr_draft = ctx.emr_draft
        so_used_fact_ids = emr_draft.get("so_used_fact_ids", [])
        assessment_items = emr_draft.get("assessment_items", [])
        plan_items = emr_draft.get("plan_items", {})
        
        yield emit_progress(4, "分节生成SOAP病历", "completed", 
                           f"生成完成，S/O使用 {len(so_used_fact_ids)} 条事实")
        
        time.sleep(self.STAGE_DELAY)
        
        fact_records = fact_service.get_facts_by_visit(visit_id)
        ctx.fact_records = fact_records
        yield emit_progress(5, "核查与修订", "running", "正在核查病历完整性...")
        
        verification_result = VerificationStage().execute(ctx)
        
        emr_final = verification_result.get("soap_final", emr_draft)
        emr_final["so_used_fact_ids"] = so_used_fact_ids
        emr_final["assessment_items"] = assessment_items
        emr_final["plan_items"] = plan_items
        
        emr_final = self.emr_persistence.normalize_format(emr_final)
        emr_final = EvidenceEnricher.enrich(emr_final, fact_records, turns)
        if save_evidence and visit_id:
            self.emr_persistence.save_evidence_spans_from_emr(emr_final, visit_id)
            self.emr_persistence.save_emr_record(emr_final, visit_id)
            logger.info(f"已保存最终病历记录及证据溯源到数据库: visit_id={visit_id}")
        
        yield emit_progress(5, "核查与修订", "completed", "核查完成")
        
        total_time = time.time() - start_time
        logger.info(f"=== 多阶段LLM处理完成(带回调): {visit_id}, 总耗时: {total_time:.2f}秒 ===")
        
        result = {
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
        
        yield emit_progress(0, "完成", "completed", f"病历生成完成，总耗时 {total_time:.2f}秒", {"result": result})
    
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

    def _save_atomic_facts(self, facts_data: List[Dict[str, Any]], visit_id: str) -> None:
        try:
            saved_count = 0
            for fact_data in facts_data:
                fact_id = f"fact_{visit_id}_{uuid.uuid4().hex[:12]}"
                atomic_fact = AtomicFact(
                    fact_id=fact_id,
                    visit_id=visit_id,
                    section_candidate=fact_data.get("section_candidate", ""),
                    subsection=fact_data.get("subsection", None),
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

    def _parse_cleaning_response(self, response_text: str, segment: List[TranscriptTurn]) -> Dict[str, Any]:
        stage = TurnCleaningStage()
        ctx = PipelineContext(
            db=self.db, llm_service=None, prompt_manager=None,
            language=self.language, debug_mode=False, visit_id="", turns=[], save_evidence=False
        )
        return stage._parse_cleaning_response(ctx, response_text, segment, self.speaker_handler)

    def _apply_asr_corrections(self, cleaning_result: Dict[str, Any], segment: List[TranscriptTurn]):
        stage = TurnCleaningStage()
        ctx = PipelineContext(
            db=self.db, llm_service=None, prompt_manager=None,
            language=self.language, debug_mode=False, visit_id="", turns=[], save_evidence=False
        )
        return stage._apply_asr_corrections(ctx, cleaning_result, segment)

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
        return self.interactive_service.process_stage(visit_id, stage, user_response, context)

