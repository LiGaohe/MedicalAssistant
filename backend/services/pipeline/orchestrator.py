import json
import copy
import time
import asyncio
import uuid
import jieba
from typing import Dict, Any, Optional, List, Tuple
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy.orm import Session
from ...models import TranscriptTurn, EMRRecord, EvidenceSpan, NormalizedTerm, AtomicFact
from ..llm.llm_service import LLMService
from ..llm.prompts import PromptManager
from ..evaluation_service import EMREvaluationService
from ..validation_service import ValidationService
from ..terminology_service import TerminologyService
from ..chinese_term_indexer import ChineseTermIndexer
from ...config import settings
from ...utils.logger import logger
from .utils import parse_json_response, JSONParseError
from .base import PipelineContext
from .speaker_handler import SpeakerHandler, FIELD_TYPE_MAPPING, FIELD_EXPECTED_ROLE
from .debug_interactor import DebugInteractor
from .emr_persistence import EMRPersistence
from .interactive import InteractivePipelineService
from .stages.turn_cleaning import TurnCleaningStage
from .stages.direct_soap_generation import DirectSOAPGenerationStage
from .stages.soap_structuring import SoapStructuringStage
from .stages.evidence_mapping import EvidenceMappingStage
from .stages.hallucination_check import HallucinationCheckStage
from .stages.claim_verification import ClaimVerificationStage
from .stages.field_revision import FieldRevisionStage


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
    
    def __init__(self, db: Session, llm_service: Optional[LLMService] = None, language: str = "zh", sequential: bool = False):
        self.db = db
        self.llm_service = llm_service
        self.language = language
        self.sequential = sequential
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
        logger.info(f"PipelineOrchestrator initialized, debug_mode={self.debug_mode}, language={language}, sequential={sequential}, UMLS={'enabled' if self.terminology_service.umls_client else 'disabled'}")
    
    
        
    def _run_stages_4_to_6(
        self,
        ctx: PipelineContext,
        skip_term_norm: bool = False,
        skip_hallucination_check: bool = False,
        skip_verification: bool = False,
        skip_field_revision: bool = False,
        save_evidence: bool = False,
        visit_id: str = ""
    ) -> Tuple[str, Optional[Dict], Optional[Dict], Dict[str, Any]]:
        """
        执行阶段4-6：术语规范化、幻觉检查、后置核查、字段修订
        
        Args:
            ctx: Pipeline上下文对象
            skip_term_norm: 是否跳过术语规范化
            skip_hallucination_check: 是否跳过幻觉检查
            skip_verification: 是否跳过后置核查
            skip_field_revision: 是否跳过字段修订
            save_evidence: 是否保存证据
            visit_id: 访问ID
            
        Returns:
            Tuple: (status, hallucination_result, verification_issues, emr_final)
            status: "completed" 或 "failed"
        """
        hallucination_result = None
        verification_issues = None
        failed_stage = None
        
        FAILED_STATUSES = ['llm_error', 'parse_error', 'llm_unavailable', 'debug_cancelled',
                          'skipped', 'skipped_empty_draft', 'skipped_empty_transcript', 'skipped_empty_content']
        
        if skip_term_norm:
            logger.info("skip_term_norm=True, 跳过术语规范化")
            emr_draft = ctx.emr_draft
        else:
            emr_draft, term_norm_calls, term_norm_chars, term_norm_tokens, term_norm_latency = self._normalize_terms_in_draft(ctx.emr_draft)
            ctx.emr_draft = emr_draft
            # 记录术语规范化的LLM调用到ctx.llm_stats
            if term_norm_calls > 0:
                ctx.llm_stats.record_call(
                    stage="term_norm",
                    prompt_length=term_norm_chars,
                    response_length=0,
                    completion_tokens=term_norm_tokens,
                    actual_latency=term_norm_latency,
                    success=True
                )
                logger.info(f"术语规范化LLM统计已记录: calls={term_norm_calls}, chars={term_norm_chars}, tokens={term_norm_tokens}, latency={term_norm_latency:.2f}s")
        
        if skip_hallucination_check:
            logger.info("skip_hallucination_check=True, 跳过阶段4: 幻觉检查")
        else:
            logger.info("阶段4: 幻觉检查")
            hallucination_result = HallucinationCheckStage().execute(ctx)
            hallucination_status = hallucination_result.get('status')
            logger.info(f"幻觉检查完成: 严重程度={hallucination_result.get('severity', 'unknown')}, "
                        f"支持率={hallucination_result.get('summary', {}).get('support_rate', 0)}, "
                        f"状态={hallucination_status}")
            
            if hallucination_status in FAILED_STATUSES:
                logger.error(f"幻觉检查失败(status={hallucination_status}), 停止管线, 不再调用大模型")
                failed_stage = "hallucination_check"
                emr_final = ctx.emr_draft
                emr_final = self.emr_persistence.normalize_format(emr_final)
                return "failed", hallucination_result, verification_issues, emr_final
        
        if skip_verification:
            logger.info("skip_verification=True, 跳过阶段5+6: 后置核查与字段修订")
            emr_final = emr_draft
            return "completed", hallucination_result, verification_issues, emr_final
        
        time.sleep(self.STAGE_DELAY)
        
        logger.info("阶段5: 后置核查")
        verification_result = ClaimVerificationStage().execute(ctx)
        verification_status = verification_result.get('status')
        verification_issues = ctx.verification_issues
        logger.info(f"后置核查完成, 问题数={verification_result.get('issues_count', 0)}, 状态={verification_status}")
        
        if verification_status in FAILED_STATUSES:
            logger.error(f"后置核查失败(status={verification_status}), 停止管线, 不再调用大模型")
            failed_stage = "verification"
            emr_final = ctx.emr_draft
            emr_final = self.emr_persistence.normalize_format(emr_final)
            return "failed", hallucination_result, verification_issues, emr_final
        
        time.sleep(self.STAGE_DELAY)
        
        if skip_field_revision:
            logger.info("skip_field_revision=True, 跳过阶段6: 字段级修订")
            emr_final = ctx.emr_draft
        else:
            logger.info("阶段6: 字段级修订与落盘")
            revision_result = FieldRevisionStage().execute(ctx)
            revision_status = revision_result.get('status')
            emr_final = ctx.emr_draft
            logger.info(f"字段级修订完成, 问题数={revision_result.get('issues_count', 0)}, "
                       f"修订={'是' if revision_result.get('revised') else '否'}, 状态={revision_status}")
            
            if revision_status in FAILED_STATUSES:
                logger.error(f"字段修订失败(status={revision_status}), 停止管线, 不再调用大模型")
                failed_stage = "field_revision"
                emr_final = self.emr_persistence.normalize_format(emr_final)
                return "failed", hallucination_result, verification_issues, emr_final
        
        emr_final = self.emr_persistence.normalize_format(emr_final)
        if save_evidence and visit_id:
            self.emr_persistence.save_evidence_spans_from_emr(emr_final, visit_id)
            self.emr_persistence.save_emr_record(emr_final, visit_id)
            logger.info(f"已保存最终病历记录及证据溯源到数据库: visit_id={visit_id}")
        
        return "completed", hallucination_result, verification_issues, emr_final
    
    def process_transcript(
        self,
        visit_id: str,
        save_evidence: bool = True,
        skip_cleaning: bool = False,
        skip_hallucination_check: bool = False,
        stop_after_draft: bool = False,
        skip_verification: bool = False,
        skip_term_norm: bool = False,
        skip_field_revision: bool = False
    ) -> Dict[str, Any]:
        logger.info(f"=== 开始多阶段LLM处理(6阶段): {visit_id} ===")
        logger.info(f"流程控制参数: skip_cleaning={skip_cleaning}, skip_hallucination_check={skip_hallucination_check}, stop_after_draft={stop_after_draft}, skip_verification={skip_verification}, skip_term_norm={skip_term_norm}, skip_field_revision={skip_field_revision}")
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
            sequential=self.sequential,
            visit_id=visit_id,
            turns=turns,
            save_evidence=save_evidence,
            skip_cleaning=skip_cleaning,
            skip_hallucination_check=skip_hallucination_check
        )
        
        all_role_mappings = None
        all_cleaned_turns = None
        
        if skip_cleaning:
            logger.info("skip_cleaning=True, 跳过阶段1: 转写清洗与角色纠错")
            combined_text = self._format_turns(turns)
            ctx.combined_text = combined_text
        else:
            TurnCleaningStage().execute(ctx)
            all_role_mappings = ctx.all_role_mappings
            all_cleaned_turns = ctx.all_cleaned_turns
            combined_text = ctx.combined_text
        
        time.sleep(self.STAGE_DELAY)
        
        logger.info("阶段2: 直接草稿生成")
        soap_result = DirectSOAPGenerationStage().execute(ctx)
        soap_status = soap_result.get('status')
        logger.info(f"直接草稿生成完成, 状态={soap_status}")
        
        FAILED_STATUSES = ['llm_error', 'parse_error', 'llm_unavailable', 'debug_cancelled', 
                          'skipped', 'skipped_empty_draft', 'skipped_empty_transcript', 'skipped_empty_content']
        if soap_status in FAILED_STATUSES:
            total_time = time.time() - start_time
            logger.error(f"草稿生成失败(status={soap_status}), 停止管线, 不再调用大模型")
            return {
                "status": "failed",
                "error": f"Draft generation failed with status: {soap_status}",
                "role_mapping": all_role_mappings,
                "cleaned_turns": all_cleaned_turns,
                "combined_text": combined_text,
                "emr_result": ctx.emr_draft,
                "emr_draft": ctx.emr_draft,
                "verification_issues": None,
                "hallucination_result": None,
                "processing_time": total_time
            }
        
        draft_text = ctx.draft_text
        
        # 草稿生成后立即保存到数据库，防止刷新丢失
        if save_evidence and visit_id and ctx.emr_draft:
            normalized_draft = self.emr_persistence.normalize_format(ctx.emr_draft)
            self.emr_persistence.save_emr_record(
                normalized_draft, 
                visit_id, 
                record_type="llm_draft",
                draft_text=draft_text
            )
            logger.info(f"已保存病历草稿到数据库: visit_id={visit_id}, record_type=llm_draft")
        
        if stop_after_draft:
            total_time = time.time() - start_time
            logger.info(f"stop_after_draft=True, 草稿阶段完成后停止, 总耗时: {total_time:.2f}秒")
            return {
                "status": "completed",
                "role_mapping": all_role_mappings,
                "cleaned_turns": all_cleaned_turns,
                "combined_text": combined_text,
                "emr_result": ctx.emr_draft,
                "emr_draft": ctx.emr_draft,
                "verification_issues": None,
                "hallucination_result": None,
                "processing_time": total_time
            }
        
        if settings.DRAFT_GENERATION_MODE == "free_text" and draft_text:
            logger.info("阶段3: 草稿结构化")
            struct_result = SoapStructuringStage().execute(ctx)
            struct_status = struct_result.get('status')
            logger.info(f"草稿结构化完成, 状态={struct_status}")
            
            if struct_status in FAILED_STATUSES:
                total_time = time.time() - start_time
                logger.error(f"草稿结构化失败(status={struct_status}), 停止管线, 不再调用大模型")
                return {
                    "status": "failed",
                    "error": f"Draft structuring failed with status: {struct_status}",
                    "role_mapping": all_role_mappings,
                    "cleaned_turns": all_cleaned_turns,
                    "combined_text": combined_text,
                    "emr_result": ctx.emr_draft,
                    "emr_draft": ctx.emr_draft,
                    "verification_issues": None,
                    "hallucination_result": None,
                    "processing_time": total_time
                }
        
        fork_status, hallucination_result, verification_issues, emr_final = self._run_stages_4_to_6(
            ctx,
            skip_term_norm=skip_term_norm,
            skip_hallucination_check=skip_hallucination_check,
            skip_verification=skip_verification,
            skip_field_revision=skip_field_revision,
            save_evidence=save_evidence,
            visit_id=visit_id
        )
        
        if fork_status == "failed":
            total_time = time.time() - start_time
            logger.error(f"阶段4-6失败, 停止管线")
            return {
                "status": "failed",
                "error": "Stages 4-6 failed",
                "role_mapping": all_role_mappings,
                "cleaned_turns": all_cleaned_turns,
                "combined_text": combined_text,
                "emr_result": emr_final,
                "emr_draft": ctx.emr_draft,
                "verification_issues": verification_issues,
                "hallucination_result": hallucination_result,
                "processing_time": total_time
            }
        
        total_time = time.time() - start_time
        logger.info(f"=== 多阶段LLM处理完成: {visit_id}, 总耗时: {total_time:.2f}秒 ===")
        
        llm_stats_summary = ctx.llm_stats.get_summary()
        logger.info(f"LLM调用统计: calls={llm_stats_summary.get('total_calls')}, "
                    f"chars={llm_stats_summary.get('total_char_count')}, "
                    f"tokens={llm_stats_summary.get('total_tokens')}")
        
        return {
            "status": "completed",
            "role_mapping": all_role_mappings,
            "cleaned_turns": all_cleaned_turns,
            "combined_text": combined_text,
            "emr_result": emr_final,
            "emr_draft": ctx.emr_draft,
            "verification_issues": verification_issues,
            "hallucination_result": hallucination_result,
            "processing_time": total_time,
            "llm_stats": llm_stats_summary
        }
    
    def process_with_fork(
        self,
        visit_id: str,
        save_evidence: bool = False
    ) -> Dict[str, Any]:
        """
        多变量Pipeline：一次运行产出5份不同配置的EMR
        
        流程：
        1. 阶段1-3（清洗→草稿→结构化）与 process_transcript() 相同
        2. 阶段2后保存 emr_raw_draft
        3. 阶段3后保存 ctx_before_fork（深拷贝）
        4. 路径A：在 ctx 上运行阶段4-6（全程）→ emr_result
        5. 路径B：在 ctx_before_fork 上运行阶段4-6（skip_term_norm=True）→ emr_no_term_norm
        6. 路径C：在 ctx_before_fork 上运行阶段4-6（skip_hallucination_check=True）→ emr_no_hallucination
        
        Returns:
            Dict: {
                "emr_raw_draft": 阶段2后的草稿,
                "emr_pre_revision": 阶段5前的EMR（修订前）,
                "emr_result": 路径A完整运行结果,
                "emr_no_term_norm": 路径B（skip_term_norm）结果,
                "emr_no_hallucination": 路径C（skip_hallucination_check）结果,
                "hallucination_result": 幻觉检查结果,
                "verification_issues": 后置核查问题
            }
        """
        logger.info(f"=== 开始多变量Pipeline(fork模式): {visit_id} ===")
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
            sequential=self.sequential,
            visit_id=visit_id,
            turns=turns,
            save_evidence=save_evidence,
            skip_cleaning=False,
            skip_hallucination_check=False
        )
        
        logger.info("阶段1: 转写清洗与角色纠错")
        TurnCleaningStage().execute(ctx)
        combined_text = ctx.combined_text
        logger.info(f"清洗完成, combined_text长度={len(combined_text)}")
        
        time.sleep(self.STAGE_DELAY)
        
        logger.info("阶段2: 直接草稿生成")
        soap_result = DirectSOAPGenerationStage().execute(ctx)
        soap_status = soap_result.get('status')
        logger.info(f"直接草稿生成完成, 状态={soap_status}")
        
        FAILED_STATUSES = ['llm_error', 'parse_error', 'llm_unavailable', 'debug_cancelled',
                          'skipped', 'skipped_empty_draft', 'skipped_empty_transcript', 'skipped_empty_content']
        if soap_status in FAILED_STATUSES:
            total_time = time.time() - start_time
            logger.error(f"草稿生成失败(status={soap_status}), 停止管线, 不再调用大模型")
            return {
                "status": "failed",
                "error": f"Draft generation failed with status: {soap_status}",
                "emr_raw_draft": None,
                "emr_pre_revision": None,
                "emr_result": None,
                "emr_no_term_norm": None,
                "emr_no_hallucination": None,
                "hallucination_result": None,
                "verification_issues": None,
                "processing_time": total_time
            }
        
        emr_raw_draft = copy.deepcopy(ctx.emr_draft) if ctx.emr_draft else None
        logger.info(f"保存emr_raw_draft: {type(emr_raw_draft).__name__}")
        
        draft_text = ctx.draft_text
        
        if settings.DRAFT_GENERATION_MODE == "free_text" and draft_text:
            logger.info("阶段3: 草稿结构化")
            struct_result = SoapStructuringStage().execute(ctx)
            struct_status = struct_result.get('status')
            logger.info(f"草稿结构化完成, 状态={struct_status}")
            
            if struct_status in FAILED_STATUSES:
                total_time = time.time() - start_time
                logger.error(f"草稿结构化失败(status={struct_status}), 停止管线, 不再调用大模型")
                return {
                    "status": "failed",
                    "error": f"Draft structuring failed with status: {struct_status}",
                    "emr_raw_draft": emr_raw_draft,
                    "emr_pre_revision": None,
                    "emr_result": None,
                    "emr_no_term_norm": None,
                    "emr_no_hallucination": None,
                    "hallucination_result": None,
                    "verification_issues": None,
                    "processing_time": total_time
                }
        
        emr_draft_before_fork = copy.deepcopy(ctx.emr_draft) if ctx.emr_draft else {}
        combined_text_before_fork = ctx.combined_text
        draft_text_before_fork = ctx.draft_text
        logger.info(f"保存fork前数据: emr_draft keys={list(emr_draft_before_fork.keys())[:3] if emr_draft_before_fork else 'None'}")

        # 保存阶段1-3的共享LLM统计（fork前），用于后续各路径独立统计
        shared_llm_stats = copy.deepcopy(ctx.llm_stats)
        logger.info(f"保存共享LLM统计（阶段1-3）: calls={shared_llm_stats.get_total_calls()}, chars={shared_llm_stats.get_total_char_count()}")

        logger.info("路径A: 完整运行阶段4-6")
        fork_status_a, hallucination_result, verification_issues, emr_pre_revision_raw = self._run_stages_4_to_6(
            ctx,
            skip_term_norm=False,
            skip_hallucination_check=False,
            skip_verification=False,
            skip_field_revision=False,
            save_evidence=save_evidence,
            visit_id=visit_id
        )
        
        if fork_status_a == "failed":
            total_time = time.time() - start_time
            logger.error(f"路径A阶段4-6失败, 停止管线, 不执行路径B")
            emr_pre_revision = copy.deepcopy(ctx.emr_draft) if ctx.emr_draft else None
            emr_result = self.emr_persistence.normalize_format(emr_pre_revision_raw)
            return {
                "status": "failed",
                "error": "Path A stages 4-6 failed",
                "emr_raw_draft": emr_raw_draft,
                "emr_pre_revision": emr_pre_revision,
                "emr_result": emr_result,
                "emr_no_term_norm": None,
                "emr_no_hallucination": None,
                "hallucination_result": hallucination_result,
                "verification_issues": verification_issues,
                "processing_time": total_time
            }
        
        emr_pre_revision = copy.deepcopy(ctx.emr_draft) if ctx.emr_draft else None
        logger.info(f"保存emr_pre_revision（修订前）: {type(emr_pre_revision).__name__}")

        # _run_stages_4_to_6 已包含字段级修订，直接使用其返回结果
        emr_result = self.emr_persistence.normalize_format(emr_pre_revision_raw)
        logger.info(f"路径A完成: emr_result keys={list(emr_result.keys())[:3] if emr_result else 'None'}")
        
        logger.info("路径B: 创建新ctx并运行阶段4-6（skip_term_norm=True）")
        ctx_fork = PipelineContext(
            db=self.db,
            llm_service=self.llm_service,
            prompt_manager=self.prompt_manager,
            language=self.language,
            debug_mode=self.debug_mode,
            sequential=self.sequential,
            visit_id=visit_id,
            turns=turns,
            save_evidence=False,
            skip_cleaning=True,
            skip_hallucination_check=False
        )
        ctx_fork.emr_draft = emr_draft_before_fork
        ctx_fork.combined_text = combined_text_before_fork
        ctx_fork.draft_text = draft_text_before_fork
        
        fork_status_b, hallucination_result_b, verification_issues_b, emr_no_term_norm = self._run_stages_4_to_6(
            ctx_fork,
            skip_term_norm=True,
            skip_hallucination_check=False,
            skip_verification=False,
            skip_field_revision=False,
            save_evidence=False,
            visit_id=""
        )
        
        if fork_status_b == "failed":
            logger.warning(f"路径B阶段4-6失败, 但路径A已完成, 继续返回路径A结果")
            emr_no_term_norm = None
        
        emr_no_term_norm = self.emr_persistence.normalize_format(emr_no_term_norm) if emr_no_term_norm else None
        logger.info(f"路径B完成: emr_no_term_norm keys={list(emr_no_term_norm.keys())[:3] if emr_no_term_norm else 'None'}")
        
        # 路径C: 跳过幻觉检查，保留其他所有阶段 → emr_no_hallucination（对应standard配置）
        logger.info("路径C: 创建新ctx并运行阶段4-6（skip_hallucination_check=True）")
        ctx_fork_c = PipelineContext(
            db=self.db,
            llm_service=self.llm_service,
            prompt_manager=self.prompt_manager,
            language=self.language,
            debug_mode=self.debug_mode,
            sequential=self.sequential,
            visit_id=visit_id,
            turns=turns,
            save_evidence=False,
            skip_cleaning=True,
            skip_hallucination_check=True
        )
        ctx_fork_c.emr_draft = copy.deepcopy(emr_draft_before_fork)
        ctx_fork_c.combined_text = combined_text_before_fork
        ctx_fork_c.draft_text = draft_text_before_fork
        
        fork_status_c, hallucination_result_c, verification_issues_c, emr_no_hallucination_raw = self._run_stages_4_to_6(
            ctx_fork_c,
            skip_term_norm=False,
            skip_hallucination_check=True,
            skip_verification=False,
            skip_field_revision=False,
            save_evidence=False,
            visit_id=""
        )
        
        if fork_status_c == "failed":
            logger.warning(f"路径C阶段4-6失败, 但路径A已完成, 继续返回路径A结果")
            emr_no_hallucination = None
        else:
            emr_no_hallucination = self.emr_persistence.normalize_format(emr_no_hallucination_raw) if emr_no_hallucination_raw else None
        logger.info(f"路径C完成: emr_no_hallucination keys={list(emr_no_hallucination.keys())[:3] if emr_no_hallucination else 'None'}")
        
        total_time = time.time() - start_time
        logger.info(f"=== 多变量Pipeline完成: {visit_id}, 总耗时: {total_time:.2f}秒 ===")

        # 保存各路径的独立LLM统计（不再合并为总数）
        # 路径A: 阶段1-3 + 路径A阶段4-6（完整管线）
        llm_stats_full = ctx.llm_stats.get_summary()
        logger.info(f"路径A(full) LLM统计: calls={llm_stats_full.get('total_calls')}, "
                    f"chars={llm_stats_full.get('total_char_count')}, "
                    f"tokens={llm_stats_full.get('total_tokens')}")

        # 路径B: 阶段1-3 + 路径B阶段4-6（skip_term_norm）
        shared_copy_b = copy.deepcopy(shared_llm_stats)
        if ctx_fork.llm_stats.get_total_calls() > 0:
            shared_copy_b.merge(ctx_fork.llm_stats)
        llm_stats_no_term_norm = shared_copy_b.get_summary()
        logger.info(f"路径B(no_term_norm) LLM统计: calls={llm_stats_no_term_norm.get('total_calls')}, "
                    f"chars={llm_stats_no_term_norm.get('total_char_count')}, "
                    f"tokens={llm_stats_no_term_norm.get('total_tokens')}")

        # 路径C: 阶段1-3 + 路径C阶段4-6（skip_hallucination_check）
        shared_copy_c = copy.deepcopy(shared_llm_stats)
        if ctx_fork_c.llm_stats.get_total_calls() > 0:
            shared_copy_c.merge(ctx_fork_c.llm_stats)
        llm_stats_no_hallucination = shared_copy_c.get_summary()
        logger.info(f"路径C(no_hallucination) LLM统计: calls={llm_stats_no_hallucination.get('total_calls')}, "
                    f"chars={llm_stats_no_hallucination.get('total_char_count')}, "
                    f"tokens={llm_stats_no_hallucination.get('total_tokens')}")

        return {
            "status": "completed",
            "emr_raw_draft": emr_raw_draft,
            "emr_pre_revision": emr_pre_revision,
            "emr_result": emr_result,
            "emr_no_term_norm": emr_no_term_norm,
            "emr_no_hallucination": emr_no_hallucination,
            "hallucination_result": hallucination_result,
            "verification_issues": verification_issues,
            "processing_time": total_time,
            "llm_stats": llm_stats_full,
            "llm_stats_full": llm_stats_full,
            "llm_stats_no_term_norm": llm_stats_no_term_norm,
            "llm_stats_no_hallucination": llm_stats_no_hallucination
        }
    
    def process_with_callback(
        self,
        visit_id: str,
        progress_callback=None,
        save_evidence: bool = True,
        stop_after_draft: bool = True,
        skip_cleaning: bool = False,
        skip_hallucination_check: bool = False
    ):
        logger.info(f"=== 开始多阶段LLM处理(带回调, 6阶段): {visit_id} ===")
        logger.info(f"流程控制参数: stop_after_draft={stop_after_draft}, skip_cleaning={skip_cleaning}, skip_hallucination_check={skip_hallucination_check}")
        start_time = time.time()
        
        def emit_progress(stage_num, stage_name, status, detail="", extra=None, is_phase_complete=False):
            event = {
                "stage": stage_num,
                "name": stage_name,
                "status": status,
                "detail": detail
            }
            if extra:
                event["extra"] = extra
            if is_phase_complete:
                event["is_phase_complete"] = True
            if progress_callback:
                progress_callback(event)
            return event
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
            sequential=self.sequential,
            visit_id=visit_id,
            turns=turns,
            save_evidence=save_evidence,
            skip_cleaning=skip_cleaning,
            skip_hallucination_check=skip_hallucination_check,
            stop_after_draft=stop_after_draft
        )
        
        all_role_mappings = None
        all_cleaned_turns = None
        
        if skip_cleaning:
            logger.info("skip_cleaning=True, 跳过阶段1进度事件，直接构建combined_text")
            combined_text = self._format_turns(turns)
            ctx.combined_text = combined_text
        else:
            segment_start = time.time()
            yield emit_progress(1, "转写清洗与角色纠错", "running", "正在处理段落...")
            
            TurnCleaningStage().execute(ctx)
            all_role_mappings = ctx.all_role_mappings
            all_cleaned_turns = ctx.all_cleaned_turns
            combined_text = ctx.combined_text
            
            yield emit_progress(1, "转写清洗与角色纠错", "completed", 
                               f"完成，清洗 {len(all_cleaned_turns)} 个轮次，耗时 {time.time() - segment_start:.2f}秒")
        
        time.sleep(self.STAGE_DELAY)
        
        yield emit_progress(2, "直接草稿生成", "running", "正在基于清洗文本直接生成SOAP草稿...")
        
        soap_result = DirectSOAPGenerationStage().execute(ctx)
        soap_status = soap_result.get('status')
        
        FAILED_STATUSES = ['llm_error', 'parse_error', 'llm_unavailable', 'debug_cancelled',
                          'skipped', 'skipped_empty_draft', 'skipped_empty_transcript', 'skipped_empty_content']
        if soap_status in FAILED_STATUSES:
            yield emit_progress(2, "直接草稿生成", "failed", 
                               f"草稿生成失败(status={soap_status}), 停止管线")
            logger.error(f"草稿生成失败(status={soap_status}), 停止管线, 不再调用大模型")
            return
        
        yield emit_progress(2, "直接草稿生成", "completed", 
                           f"草稿生成完成，状态={soap_status}")
        
        draft_text = ctx.draft_text
        
        if settings.DRAFT_GENERATION_MODE == "free_text" and draft_text:
            # 草稿生成后立即保存到数据库，防止刷新丢失
            if save_evidence and visit_id:
                # 自由文本模式下，如果emr_draft为空，创建空结构用于保存draft_text
                if not ctx.emr_draft:
                    ctx.emr_draft = DirectSOAPGenerationStage._empty_draft()
                    logger.info("自由文本模式下emr_draft为空，创建空结构用于保存draft_text")
                
                normalized_draft = self.emr_persistence.normalize_format(ctx.emr_draft)
                self.emr_persistence.save_emr_record(
                    normalized_draft, 
                    visit_id, 
                    record_type="llm_draft",
                    draft_text=ctx.draft_text
                )
                logger.info(f"已保存病历草稿到数据库: visit_id={visit_id}, record_type=llm_draft, draft_text长度={len(ctx.draft_text)}")
            
            draft_text_event = emit_progress(2, "直接草稿生成", "completed", "草稿已就绪")
            draft_text_event["is_draft_text_ready"] = True
            draft_text_event["draft_text"] = ctx.draft_text
            logger.info(f"yield draft_text_ready事件: draft_text长度={len(ctx.draft_text)}")
            yield draft_text_event
            
            # 自由文本模式下，也发送draft_ready事件，将草稿文本包装成EMR结构供前端显示
            draft_event = emit_progress(2, "直接草稿生成", "completed", "草稿已就绪")
            draft_event["is_draft_ready"] = True
            draft_event["emr_draft"] = ctx.emr_draft
            logger.info(f"yield draft_ready事件: emr_draft类型={type(ctx.emr_draft).__name__}")
            yield draft_event
            
            if ctx.skip_structuring:
                logger.info("LLM返回JSON已解析为标准格式，跳过结构化阶段")
                
                if stop_after_draft:
                    logger.info(f"stop_after_draft=True, 草稿阶段完成后停止, visit_id={visit_id}")
                    yield emit_progress(
                        2, "直接草稿生成", "completed",
                        "草稿阶段完成",
                        {"phase": "draft_generation", "status": "completed"},
                        is_phase_complete=True
                    )
                    return
            else:
                if stop_after_draft:
                    logger.info(f"stop_after_draft=True, 自由文本草稿阶段完成后停止, visit_id={visit_id}")
                    yield emit_progress(
                        2, "直接草稿生成", "completed",
                        "草稿阶段完成",
                        {"phase": "draft_generation", "status": "completed"},
                        is_phase_complete=True
                    )
                    return
                
                yield emit_progress(3, "草稿结构化", "running", "正在将自由文本草稿结构化为SOAP JSON...")
                struct_result = SoapStructuringStage().execute(ctx)
                struct_status = struct_result.get('status')
                
                FAILED_STATUSES = ['llm_error', 'parse_error', 'llm_unavailable', 'debug_cancelled',
                                  'skipped', 'skipped_empty_draft', 'skipped_empty_transcript', 'skipped_empty_content']
                if struct_status in FAILED_STATUSES:
                    yield emit_progress(3, "草稿结构化", "failed", 
                                       f"草稿结构化失败(status={struct_status}), 停止管线")
                    logger.error(f"草稿结构化失败(status={struct_status}), 停止管线, 不再调用大模型")
                    return
                
                yield emit_progress(3, "草稿结构化", "completed", "草稿结构化完成")
        else:
            # JSON模式下草稿生成后立即保存到数据库，防止刷新丢失
            if save_evidence and visit_id and ctx.emr_draft:
                normalized_draft = self.emr_persistence.normalize_format(ctx.emr_draft)
                self.emr_persistence.save_emr_record(
                    normalized_draft, 
                    visit_id, 
                    record_type="llm_draft"
                )
                logger.info(f"已保存病历草稿到数据库: visit_id={visit_id}, record_type=llm_draft")
            
            if stop_after_draft:
                logger.info(f"stop_after_draft=True, JSON草稿阶段完成后停止, visit_id={visit_id}")
                draft_event = emit_progress(2, "直接草稿生成", "completed", "草稿已就绪")
                draft_event["is_draft_ready"] = True
                draft_event["emr_draft"] = ctx.emr_draft
                logger.info(f"yield draft_ready事件: emr_draft类型={type(ctx.emr_draft).__name__}")
                yield draft_event
                yield emit_progress(
                    2, "直接草稿生成", "completed",
                    "草稿阶段完成",
                    {"phase": "draft_generation", "status": "completed"},
                    is_phase_complete=True
                )
                return
        
        emr_draft, term_norm_calls, term_norm_chars, term_norm_tokens, term_norm_latency = self._normalize_terms_in_draft(ctx.emr_draft)
        ctx.emr_draft = emr_draft
        # 记录术语规范化的LLM调用到ctx.llm_stats
        if term_norm_calls > 0:
            ctx.llm_stats.record_call(
                stage="term_norm",
                prompt_length=term_norm_chars,
                response_length=0,
                completion_tokens=term_norm_tokens,
                actual_latency=term_norm_latency,
                success=True
            )
        
        yield emit_progress(3, "证据溯源构建", "running", "正在为病历内容标注来源对话轮次...")
        EvidenceMappingStage().execute(ctx)
        yield emit_progress(3, "证据溯源构建", "completed", "证据溯源构建完成")
        
        # 证据溯源构建完成后立即保存到数据库
        if save_evidence and visit_id:
            normalized_emr = self.emr_persistence.normalize_format(ctx.emr_draft)
            self.emr_persistence.save_evidence_spans_from_emr(normalized_emr, visit_id)
            logger.info(f"证据溯源已保存到数据库: visit_id={visit_id}")
        
        hallucination_result = None
        
        if skip_hallucination_check:
            logger.info("skip_hallucination_check=True, 跳过阶段4进度事件")
        else:
            yield emit_progress(4, "幻觉检查", "running", "正在逐事实核查草稿是否存在对话中没有依据的虚假内容...")
            
            hallucination_result = HallucinationCheckStage().execute(ctx)
            logger.info(f"幻觉检查完成: 严重程度={hallucination_result.get('severity', 'unknown')}, "
                        f"支持率={hallucination_result.get('summary', {}).get('support_rate', 0)}")
            
            h_status = hallucination_result.get("status", "completed")
            h_detail = f"检查完成，支持率={hallucination_result.get('summary', {}).get('support_rate', 0):.0%}"
            yield emit_progress(4, "幻觉检查", "completed", h_detail)
        
        draft_event = emit_progress(3, "草稿结构化", "completed", "草稿已就绪")
        draft_event["is_draft_ready"] = True
        draft_event["emr_draft"] = ctx.emr_draft
        if not skip_hallucination_check:
            draft_event["hallucination_result"] = ctx.hallucination_result
        logger.info(f"yield draft_ready事件: emr_draft类型={type(ctx.emr_draft).__name__}, "
                    f"subjective keys={list(ctx.emr_draft.get('subjective', {}).keys())[:3] if ctx.emr_draft else 'None'}")
        yield draft_event

        logger.info(f"继续执行阶段5和阶段6, visit_id={visit_id}")

        time.sleep(self.STAGE_DELAY)
        
        yield emit_progress(5, "后置核查", "running", "正在进行Claim核查、Checklist核查和硬规则核查...")
        
        verification_result = ClaimVerificationStage().execute(ctx)
        verification_issues = ctx.verification_issues
        
        yield emit_progress(5, "后置核查", "completed", 
                           f"核查完成，发现 {verification_result.get('issues_count', 0)} 个问题")
        
        time.sleep(self.STAGE_DELAY)
        
        yield emit_progress(6, "字段级修订与落盘", "running", "正在根据核查问题修订SOAP草稿...")
        
        FieldRevisionStage().execute(ctx)
        emr_final = ctx.emr_draft
        
        emr_final = self.emr_persistence.normalize_format(emr_final)
        if save_evidence and visit_id:
            self.emr_persistence.save_evidence_spans_from_emr(emr_final, visit_id)
            self.emr_persistence.save_emr_record(emr_final, visit_id)
            logger.info(f"已保存最终病历记录及证据溯源到数据库: visit_id={visit_id}")
        
        yield emit_progress(6, "字段级修订与落盘", "completed", "修订完成，病历已落盘")
        
        total_time = time.time() - start_time
        logger.info(f"=== 多阶段LLM处理完成(带回调): {visit_id}, 总耗时: {total_time:.2f}秒 ===")
        
        result = {
            "status": "completed",
            "role_mapping": all_role_mappings,
            "cleaned_turns": all_cleaned_turns,
            "combined_text": combined_text,
            "emr_result": emr_final,
            "emr_draft": emr_draft,
            "verification_issues": verification_issues,
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
    
    def _format_turns(self, turns: List[TranscriptTurn]) -> str:
        """
        格式化全部对话轮次为文本（用于跳过清洗阶段时直接构建combined_text）。
        
        与 _format_segment() 类似，但处理全部 turns 而不是单个 segment。
        输出格式：
        - 有标签：[#0] [spk0]: 对话内容
        - 无标签：[#0] 对话内容
        
        Args:
            turns: 全部对话轮次列表
            
        Returns:
            格式化后的对话文本字符串
        """
        if not turns:
            logger.warning("_format_turns: turns列表为空")
            return ""
        
        has_valid_speakers = False
        for turn in turns:
            if turn.speaker and turn.speaker not in ("unknown", "", "None"):
                has_valid_speakers = True
                break
        
        lines = []
        for turn in turns:
            if has_valid_speakers:
                lines.append(f"[#{turn.turn_index}] [{turn.speaker}]: {turn.text}")
            else:
                lines.append(f"[#{turn.turn_index}] {turn.text}")
        
        combined_text = "\n".join(lines)
        logger.info(f"_format_turns: 格式化 {len(turns)} 个轮次，文本长度={len(combined_text)}")
        return combined_text
    
    def _normalize_terms_in_draft(self, emr_draft: Dict[str, Any]) -> Tuple[Dict[str, Any], int, int, int, float]:
        """术语规范化，返回 (emr_draft, llm_call_count, char_count, token_count, latency)"""
        if not self.terminology_service:
            logger.info("术语服务不可用，跳过术语规范化")
            return emr_draft, 0, 0, 0, 0.0

        logger.info(f"开始术语规范化（后处理SOAP草稿），language={self.language}")
        norm_start = time.time()

        sections = ["subjective", "objective", "assessment", "plan"]

        if self.language == "zh":
            chinese_client = self.terminology_service.chinese_term_client
            colloquial_synonyms = {}
            if chinese_client and chinese_client.indexer:
                colloquial_synonyms = chinese_client.indexer.colloquial_synonyms

            if colloquial_synonyms:
                sorted_synonyms = sorted(
                    colloquial_synonyms.items(),
                    key=lambda x: len(x[0]),
                    reverse=True
                )
                synonym_count = 0
                for section_name in sections:
                    section = emr_draft.get(section_name, {})
                    if not isinstance(section, dict):
                        continue
                    for field_name, field_data in section.items():
                        if field_name in ("text", "evidence_traces", "assessment_items", "plan_items"):
                            continue
                        if not isinstance(field_data, dict):
                            continue
                        value = field_data.get("value", "")
                        if not value or not isinstance(value, str) or not value.strip():
                            continue
                        original_value = value
                        tokens = jieba.lcut(value)
                        for colloquial, standard_terms in sorted_synonyms:
                            if not isinstance(standard_terms, list) or not standard_terms:
                                continue
                            standard = standard_terms[0]
                            if colloquial == standard:
                                continue
                            new_tokens = []
                            for token in tokens:
                                if token == colloquial:
                                    new_tokens.append(standard)
                                    synonym_count += 1
                                    logger.debug(
                                        f"同义词替换: '{colloquial}' -> '{standard}' "
                                        f"在 {section_name}.{field_name}"
                                    )
                                else:
                                    new_tokens.append(token)
                            tokens = new_tokens
                        value = "".join(tokens)
                        if value != original_value:
                            field_data["value"] = value
                            logger.info(
                                f"同义词预处理: {section_name}.{field_name}: "
                                f"'{original_value[:50]}...' -> '{value[:50]}...'"
                            )
                logger.info(f"同义词预处理完成: {synonym_count} 处替换")

        field_texts = []
        for section_name in sections:
            section = emr_draft.get(section_name, {})
            if not isinstance(section, dict):
                continue
            for field_name, field_data in section.items():
                if field_name in ("text", "evidence_traces", "assessment_items", "plan_items"):
                    continue
                if not isinstance(field_data, dict):
                    continue
                value = field_data.get("value", "")
                if value and isinstance(value, str) and value.strip():
                    field_texts.append(value)

        if not field_texts:
            logger.info("草稿中无有效文本，跳过术语规范化")
            return emr_draft, 0, 0, 0, 0.0

        combined_text = "\n".join(field_texts)
        logger.info(f"收集到 {len(field_texts)} 个字段文本，总长度: {len(combined_text)}")

        try:
            replacement_map, term_norm_calls, term_norm_chars, term_norm_tokens = self.terminology_service.normalize_draft_terms(combined_text)
        except Exception as e:
            logger.error(f"调用 normalize_draft_terms 失败: {e}")
            return emr_draft, 0, 0, 0, 0.0

        if not replacement_map:
            norm_time = time.time() - norm_start
            logger.info(f"术语规范化完成: 无需替换, 耗时: {norm_time:.2f}秒")
            return emr_draft, term_norm_calls, term_norm_chars, term_norm_tokens, norm_time

        total_replacements = 0
        for section_name in sections:
            section = emr_draft.get(section_name, {})
            if not isinstance(section, dict):
                continue
            for field_name, field_data in section.items():
                if field_name in ("text", "evidence_traces", "assessment_items", "plan_items"):
                    continue
                if not isinstance(field_data, dict):
                    continue
                value = field_data.get("value", "")
                if not value or not isinstance(value, str) or not value.strip():
                    continue
                original_value = value
                tokens = jieba.lcut(value)
                for original_term, normalized_term in replacement_map.items():
                    if original_term == normalized_term:
                        continue
                    new_tokens = []
                    for token in tokens:
                        if token == original_term:
                            new_tokens.append(normalized_term)
                            total_replacements += 1
                            logger.info(
                                f"术语替换: '{original_term}' -> '{normalized_term}' "
                                f"在 {section_name}.{field_name}"
                            )
                        else:
                            new_tokens.append(token)
                    tokens = new_tokens
                value = "".join(tokens)
                if value != original_value:
                    field_data["value"] = value
                    logger.info(
                        f"术语规范化: {section_name}.{field_name}: "
                        f"'{original_value[:50]}...' -> '{value[:50]}...'"
                    )

        norm_time = time.time() - norm_start
        logger.info(
            f"术语规范化完成: {total_replacements} 处替换, "
            f"耗时: {norm_time:.2f}秒, LLM调用: {term_norm_calls}次, "
            f"字符: {term_norm_chars}, Token: {term_norm_tokens}"
        )

        return emr_draft, term_norm_calls, term_norm_chars, term_norm_tokens, norm_time

    # DEPRECATED: replaced by _normalize_terms_in_draft which uses ICD-11 local KB
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

    # DEPRECATED: replaced by DirectSOAPGenerationStage (no longer uses atomic facts)
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
            "stage": "direct_soap_generation",
            "prompt": "[待阶段1完成后生成]",
            "description": "阶段2: 直接草稿生成",
            "instructions": """
根据清洗后的完整对话文本，一次性生成完整的SOAP病历草稿。
每个字段包含value和source_turn_indices，用于后续证据溯源。
详见 direct_soap_generation 模板。
""",
            "pending": True
        })

        stages.append({
            "stage": "claim_verification",
            "prompt": "[待阶段2完成后生成]",
            "description": "阶段3: 后置核查",
            "instructions": """
三步核查流程：
A. Claim核查 - 逐claim原子核查（supported/unsupported/not_addressed）
B. Checklist核查 - 检查SOAP关键信息遗漏
C. 硬规则核查 - 确定性规则检查（部位矛盾、否定冲突等）
详见 claim_verification 和 checklist_verification 模板。
""",
            "pending": True
        })

        stages.append({
            "stage": "field_revision",
            "prompt": "[待阶段3完成后生成]",
            "description": "阶段4: 字段级修订与落盘",
            "instructions": """
根据核查问题清单对SOAP草稿进行定点修订。
仅修改有问题的字段，保留无问题字段不变。
修订后执行schema确定性约束校验。
详见 field_revision 模板。
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

    def run_postprocess_stage(self, stage: str, emr_draft: Dict, visit_id: str) -> Dict:
        verification_issues = None
        hallucination_result = None
        emr_draft_before = None
        try:
            emr_draft_before = copy.deepcopy(emr_draft)
            logger.info(f"run_postprocess_stage: stage={stage}, visit_id={visit_id}")
            
            turns = self.db.query(TranscriptTurn).filter(
                TranscriptTurn.visit_id == visit_id
            ).order_by(TranscriptTurn.turn_index).all()
            
            ctx = PipelineContext(
                db=self.db,
                llm_service=self.llm_service,
                prompt_manager=self.prompt_manager,
                language=self.language,
                debug_mode=False,
                sequential=self.sequential,
                visit_id=visit_id,
                turns=turns,
                save_evidence=False
            )
            ctx.emr_draft = emr_draft
            
            if stage == "term_norm":
                emr_draft_after, tn_calls, tn_chars, tn_tokens, tn_latency = self._normalize_terms_in_draft(emr_draft)
                if tn_calls > 0:
                    ctx.llm_stats.record_call(
                        stage="term_norm",
                        prompt_length=tn_chars,
                        response_length=0,
                        completion_tokens=tn_tokens,
                        actual_latency=tn_latency,
                        success=True
                    )
            elif stage == "evidence_mapping":
                combined_text = self._format_turns(turns)
                ctx.combined_text = combined_text
                EvidenceMappingStage().execute(ctx)
                emr_draft_after = ctx.emr_draft
                # 证据溯源构建完成后立即保存到数据库
                normalized_emr = self.emr_persistence.normalize_format(emr_draft_after)
                self.emr_persistence.save_evidence_spans_from_emr(normalized_emr, visit_id)
                logger.info(f"证据溯源已保存到数据库: visit_id={visit_id}")
            elif stage == "hallucination_check":
                combined_text = self._format_turns(turns)
                ctx.combined_text = combined_text
                hallucination_result = HallucinationCheckStage().execute(ctx)
                emr_draft_after = ctx.emr_draft
            elif stage == "verification_revision":
                ClaimVerificationStage().execute(ctx)
                verification_issues = ctx.verification_issues
                FieldRevisionStage().execute(ctx)
                emr_draft_after = ctx.emr_draft
            else:
                logger.warning(f"run_postprocess_stage: 未知stage={stage}")
                emr_draft_after = emr_draft
            
            changes = self._compute_changes(emr_draft_before, emr_draft_after, stage)
            logger.info(f"run_postprocess_stage: stage={stage} 完成, 变更数={len(changes)}")
            return {
                "stage": stage,
                "changes": changes,
                "emr_draft_after": emr_draft_after,
                "verification_issues": verification_issues if stage == "verification_revision" else None,
                "hallucination_result": hallucination_result if stage == "hallucination_check" else None
            }
        except Exception as e:
            logger.error(f"run_postprocess_stage: stage={stage} 失败, error={e}")
            return {
                "stage": stage,
                "changes": [],
                "emr_draft_after": emr_draft_before if emr_draft_before is not None else emr_draft,
                "verification_issues": None,
                "hallucination_result": None,
                "error": str(e)
            }

    def _compute_changes(self, before: Dict, after: Dict, stage: str) -> List[Dict]:
        changes = []
        index = 0
        skip_fields = {"text", "evidence_traces", "assessment_items", "plan_items"}
        sections = ["subjective", "objective", "assessment", "plan"]

        certainty_downgrade_patterns = [
            ("确诊", "考虑"), ("确诊", "疑似"), ("确诊", "可能"),
            ("确诊", "待排"), ("明确", "考虑"), ("明确", "疑似"),
            ("明确", "可能"), ("考虑", "待排"), ("诊断", "印象"),
        ]

        for section in sections:
            before_section = before.get(section, {})
            after_section = after.get(section, {})
            if not isinstance(before_section, dict) or not isinstance(after_section, dict):
                continue

            all_fields = set(before_section.keys()) | set(after_section.keys())
            for field in all_fields:
                if field in skip_fields:
                    continue

                before_field = before_section.get(field)
                after_field = after_section.get(field)

                if not isinstance(before_field, dict) or not isinstance(after_field, dict):
                    continue

                before_value = before_field.get("value", "")
                after_value = after_field.get("value", "")

                if before_value == after_value:
                    continue

                change_type = self._determine_change_type(
                    before_value, after_value, stage, certainty_downgrade_patterns
                )

                detail = self._build_change_detail(section, field, before_value, after_value, change_type)

                changes.append({
                    "id": f"change_{index}",
                    "section": section,
                    "field": field,
                    "before": before_value,
                    "after": after_value,
                    "type": change_type,
                    "detail": detail
                })
                index += 1

        type_distribution = {}
        for change in changes:
            t = change["type"]
            type_distribution[t] = type_distribution.get(t, 0) + 1
        logger.info(f"_compute_changes: stage={stage}, 变更数={len(changes)}, 类型分布={type_distribution}")

        return changes

    def _determine_change_type(
        self,
        before_value: str,
        after_value: str,
        stage: str,
        downgrade_patterns: List[tuple]
    ) -> str:
        if stage == "term_norm":
            return "term_replacement"

        if stage == "verification_revision":
            if not before_value or (isinstance(before_value, str) and not before_value.strip()):
                return "missing_item_added"
            if not after_value or (isinstance(after_value, str) and not after_value.strip()):
                return "unsupported_claim_removed"
            if isinstance(before_value, str) and isinstance(after_value, str):
                for high_cert, low_cert in downgrade_patterns:
                    if high_cert in before_value and low_cert in after_value:
                        return "downgrade"
            return "revision"

        return "revision"

    def _build_change_detail(
        self,
        section: str,
        field: str,
        before_value: str,
        after_value: str,
        change_type: str
    ) -> str:
        type_descriptions = {
            "term_replacement": "术语规范化替换",
            "unsupported_claim_removed": "无依据声明移除",
            "missing_item_added": "遗漏项补充",
            "downgrade": "确定性降级",
            "revision": "内容修订"
        }

        desc = type_descriptions.get(change_type, "变更")
        before_preview = str(before_value)[:50] if before_value else "(空)"
        after_preview = str(after_value)[:50] if after_value else "(空)"
        return f"{desc}: {section}.{field} 从 '{before_preview}' 变更为 '{after_preview}'"

