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
        logger.info(f"=== 开始多阶段LLM处理(4阶段): {visit_id} ===")
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
        
        # 阶段1: 转写清洗与角色纠错（不变）
        TurnCleaningStage().execute(ctx)
        all_role_mappings = ctx.all_role_mappings
        all_cleaned_turns = ctx.all_cleaned_turns
        combined_text = ctx.combined_text
        
        time.sleep(self.STAGE_DELAY)
        
        # 阶段2: 直接草稿生成
        logger.info("阶段2: 直接草稿生成")
        soap_result = DirectSOAPGenerationStage().execute(ctx)
        emr_draft = ctx.emr_draft
        logger.info(f"直接草稿生成完成, 状态={soap_result.get('status')}")
        
        # 阶段2.5: ICD-11术语规范化（后处理草稿）
        ctx.emr_draft = self._normalize_terms_in_draft(ctx.emr_draft)
        
        time.sleep(self.STAGE_DELAY)
        
        # 阶段3: 后置核查
        logger.info("阶段3: 后置核查")
        verification_result = ClaimVerificationStage().execute(ctx)
        verification_issues = ctx.verification_issues
        logger.info(f"后置核查完成, 问题数={verification_result.get('issues_count', 0)}")
        
        time.sleep(self.STAGE_DELAY)
        
        # 阶段4: 字段级修订与落盘
        logger.info("阶段4: 字段级修订与落盘")
        FieldRevisionStage().execute(ctx)
        emr_final = ctx.emr_draft  # FieldRevisionStage已更新ctx.emr_draft
        
        # 后处理
        emr_final = self.emr_persistence.normalize_format(emr_final)
        # 证据溯源已在DirectSOAPGenerationStage._build_evidence_traces()中完成
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
            "emr_result": emr_final,
            "emr_draft": emr_draft,
            "verification_issues": verification_issues,
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
        
        logger.info(f"=== 开始多阶段LLM处理(带回调, 4阶段): {visit_id} ===")
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
        
        # 阶段1: 转写清洗与角色纠错（不变）
        segment_start = time.time()
        yield emit_progress(1, "转写清洗与角色纠错", "running", "正在处理段落...")
        
        TurnCleaningStage().execute(ctx)
        all_role_mappings = ctx.all_role_mappings
        all_cleaned_turns = ctx.all_cleaned_turns
        combined_text = ctx.combined_text
        
        yield emit_progress(1, "转写清洗与角色纠错", "completed", 
                           f"完成，清洗 {len(all_cleaned_turns)} 个轮次，耗时 {time.time() - segment_start:.2f}秒")
        
        time.sleep(self.STAGE_DELAY)
        
        # 阶段2: 直接草稿生成
        yield emit_progress(2, "直接草稿生成", "running", "正在基于清洗文本直接生成SOAP草稿...")
        
        soap_result = DirectSOAPGenerationStage().execute(ctx)
        emr_draft = ctx.emr_draft
        
        # ICD-11术语规范化（后处理草稿）
        ctx.emr_draft = self._normalize_terms_in_draft(ctx.emr_draft)
        
        yield emit_progress(2, "直接草稿生成", "completed", 
                           f"草稿生成完成，状态={soap_result.get('status')}")
        
        # 发送draft_ready事件
        draft_event = emit_progress(2, "直接草稿生成", "completed", 
                                    "草稿已就绪")
        draft_event["is_draft_ready"] = True
        draft_event["emr_draft"] = ctx.emr_draft
        logger.info(f"yield draft_ready事件: emr_draft类型={type(ctx.emr_draft).__name__}, "
                    f"subjective keys={list(ctx.emr_draft.get('subjective', {}).keys())[:3] if ctx.emr_draft else 'None'}")
        yield draft_event
        
        time.sleep(self.STAGE_DELAY)
        
        # 阶段3: 后置核查
        yield emit_progress(3, "后置核查", "running", "正在进行Claim核查、Checklist核查和硬规则核查...")
        
        verification_result = ClaimVerificationStage().execute(ctx)
        verification_issues = ctx.verification_issues
        
        yield emit_progress(3, "后置核查", "completed", 
                           f"核查完成，发现 {verification_result.get('issues_count', 0)} 个问题")
        
        time.sleep(self.STAGE_DELAY)
        
        # 阶段4: 字段级修订与落盘
        yield emit_progress(4, "字段级修订与落盘", "running", "正在根据核查问题修订SOAP草稿...")
        
        FieldRevisionStage().execute(ctx)
        emr_final = ctx.emr_draft  # FieldRevisionStage已更新ctx.emr_draft
        
        # 后处理
        emr_final = self.emr_persistence.normalize_format(emr_final)
        # 证据溯源已在DirectSOAPGenerationStage._build_evidence_traces()中完成
        if save_evidence and visit_id:
            self.emr_persistence.save_evidence_spans_from_emr(emr_final, visit_id)
            self.emr_persistence.save_emr_record(emr_final, visit_id)
            logger.info(f"已保存最终病历记录及证据溯源到数据库: visit_id={visit_id}")
        
        yield emit_progress(4, "字段级修订与落盘", "completed", "修订完成，病历已落盘")
        
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
    
    def _normalize_terms_in_draft(self, emr_draft: Dict[str, Any]) -> Dict[str, Any]:
        """使用本地ICD-11知识库对SOAP草稿中的医学术语进行规范化。

        流程：
        1. 使用colloquial_synonyms.json中的口语化同义词映射进行直接替换
        2. 使用ChineseTermClient（含ICD-11术语）对剩余术语进行匹配规范化
        3. 遍历subjective/objective/assessment/plan各字段的value文本
        4. 日志记录所有替换操作
        """
        if not self.terminology_service or not self.terminology_service.chinese_term_client:
            logger.info("ChineseTermClient不可用，跳过ICD-11术语规范化")
            return emr_draft

        if self.language != "zh":
            logger.info("非中文模式，跳过ICD-11术语规范化")
            return emr_draft

        logger.info("开始ICD-11术语规范化（后处理SOAP草稿）")
        norm_start = time.time()

        chinese_client = self.terminology_service.chinese_term_client
        colloquial_synonyms = {}
        if chinese_client.indexer:
            colloquial_synonyms = chinese_client.indexer.colloquial_synonyms

        total_replacements = 0
        sections = ["subjective", "objective", "assessment", "plan"]

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

                for colloquial, standard_terms in colloquial_synonyms.items():
                    if not isinstance(standard_terms, list) or not standard_terms:
                        continue
                    standard = standard_terms[0]
                    if colloquial in value and colloquial != standard:
                        value = value.replace(colloquial, standard)
                        total_replacements += 1
                        logger.debug(
                            f"同义词替换: '{colloquial}' -> '{standard}' "
                            f"在 {section_name}.{field_name}"
                        )

                if value != original_value:
                    field_data["value"] = value
                    logger.info(
                        f"术语规范化: {section_name}.{field_name}: "
                        f"'{original_value[:50]}...' -> '{value[:50]}...'"
                    )

                chinese_terms = self._find_terms_in_text(value)
                if chinese_terms:
                    for term_text in chinese_terms:
                        try:
                            result = chinese_client.search_term(
                                term=term_text,
                                term_type=None,
                                use_fuzzy=True
                            )
                            if result and result.matched_term != term_text and result.confidence >= 0.7:
                                if term_text in value:
                                    value = value.replace(term_text, result.matched_term)
                                    total_replacements += 1
                                    logger.info(
                                        f"ICD-11术语匹配: '{term_text}' -> '{result.matched_term}' "
                                        f"(confidence: {result.confidence:.2f}, "
                                        f"code: {result.code or 'N/A'}) "
                                        f"在 {section_name}.{field_name}"
                                    )
                        except Exception as e:
                            logger.debug(f"术语搜索异常 '{term_text}': {e}")

                    if value != field_data.get("value", ""):
                        field_data["value"] = value

        norm_time = time.time() - norm_start
        if total_replacements > 0:
            logger.info(
                f"ICD-11术语规范化完成: {total_replacements} 处替换, "
                f"耗时: {norm_time:.2f}秒"
            )
        else:
            logger.info(f"ICD-11术语规范化完成: 无需替换, 耗时: {norm_time:.2f}秒")

        return emr_draft

    @staticmethod
    def _find_terms_in_text(text: str) -> List[str]:
        """从文本中提取可能的中文医学术语（2-6个中文字符的词组）。
        用于在ICD-11术语库中进行匹配查找。
        """
        terms = []
        chinese_chars = re.findall(r'[\u4e00-\u9fff]{2,6}', text)
        seen = set()
        for term in chinese_chars:
            if term not in seen:
                seen.add(term)
                terms.append(term)
        return terms

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

