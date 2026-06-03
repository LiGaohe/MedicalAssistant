# DEPRECATED: 六阶段流水线已重构为四阶段。事实抽取阶段不再使用，证据溯源由 DirectSOAPGenerationStage._build_evidence_traces() 替代。
import json
import time
import uuid
from typing import Dict, Any, List

from ..base import PipelineContext, PipelineStage
from ..utils import parse_json_response, JSONParseError
from ..debug_interactor import DebugInteractor
from ....models import AtomicFact
from ....utils.logger import logger
from ...fact_service import FactService


class FactExtractionStage(PipelineStage):
    def stage_name(self) -> str:
        return "事实抽取与证据绑定"

    def execute(self, ctx: PipelineContext) -> Dict[str, Any]:
        logger.info(f">>> 阶段2: {self.stage_name()}")
        stage_start = time.time()

        cleaned_turns = ctx.all_cleaned_turns
        role_mapping = ctx.all_role_mappings
        visit_id = ctx.visit_id

        new_turns_json = json.dumps(cleaned_turns, ensure_ascii=False, indent=2)
        logger.info(f"清理后的turn数: {len(cleaned_turns)}")

        existing_facts_summary = "[]"
        existing_facts_map = {}

        incremental = False
        if incremental and visit_id and ctx.db:
            fact_service = FactService(ctx.db)
            existing_facts = fact_service.get_facts_by_visit(visit_id)
            if existing_facts:
                summary_items = []
                for fact in existing_facts:
                    existing_facts_map[fact.fact_id] = fact
                    summary_items.append({
                        "fact_id": fact.fact_id,
                        "mention": fact.mention,
                        "section_candidate": fact.section_candidate,
                        "subsection": fact.subsection,
                        "speaker": fact.speaker,
                        "evidence_turn_ids": fact.evidence_turn_ids or []
                    })
                existing_facts_summary = json.dumps(summary_items, ensure_ascii=False, indent=2)
                logger.info(f"增量模式: 已有 {len(existing_facts)} 条事实")

        prompt = ctx.prompt_manager.render(
            "fact_extraction",
            new_turns_json=new_turns_json,
            existing_facts_summary=existing_facts_summary
        )
        logger.debug(f"事实抽取提示词长度: {len(prompt)} 字符")

        debug_interactor = DebugInteractor(ctx.llm_service)

        if ctx.debug_mode:
            response_text = debug_interactor.interact(
                stage="fact_extraction",
                prompt=prompt,
                clean_turns=cleaned_turns
            )
        else:
            if not ctx.llm_service:
                logger.warning("LLM服务不可用，事实抽取失败")
                return {"facts": [], "fact_count": 0}

            try:
                response = ctx.llm_service.generate(prompt, thinking_enabled=False)
                logger.debug("事实抽取阶段: thinking模式已禁用")
                ctx.llm_stats.record_from_response("fact_extraction", prompt, response)
                response_text = response.text
            except Exception as e:
                logger.error(f"事实抽取LLM调用失败: {e}")
                ctx.llm_stats.record_call("fact_extraction", len(prompt), 0, success=False, error_message=str(e))
                return {"facts": [], "fact_count": 0}

        try:
            result = parse_json_response(response_text, "事实抽取", raise_on_error=True)
        except JSONParseError as e:
            logger.error(f"阶段2 JSON解析失败，停止后续执行")
            logger.error(f"=== LLM完整响应内容 ===")
            logger.error(e.get_full_response())
            logger.error(f"=== 响应内容结束 ===")
            raise

        facts = []
        if result and "facts" in result:
            raw_facts = result.get("facts", [])
            logger.info(f"LLM返回 {len(raw_facts)} 条原始事实")

            if incremental and existing_facts_map:
                facts = self._process_incremental_facts(ctx, raw_facts, existing_facts_map, visit_id)
            else:
                facts = self._deduplicate_facts(raw_facts)
            logger.info(f"去重后剩余 {len(facts)} 条事实")

        if facts and visit_id and ctx.db:
            self._save_atomic_facts(ctx, facts, visit_id)

        stage_time = time.time() - stage_start
        logger.info(f"事实抽取完成，共 {len(facts)} 条事实，耗时: {stage_time:.2f}秒")

        ctx.fact_result = {
            "facts": facts,
            "fact_count": len(facts)
        }

        return ctx.fact_result

    def _process_incremental_facts(
        self,
        ctx: PipelineContext,
        raw_facts: List[Dict],
        existing_facts_map: Dict[str, Any],
        visit_id: str
    ) -> List[Dict]:
        logger.info("处理增量事实")

        new_facts = []
        append_operations = []

        for fact in raw_facts:
            operation = fact.get("operation", "new")

            if operation == "append":
                matched_fact_id = fact.get("matched_fact_id")
                if matched_fact_id and matched_fact_id in existing_facts_map:
                    append_operations.append({
                        "fact_id": matched_fact_id,
                        "new_evidence_turn_ids": fact.get("evidence_turn_ids", []),
                        "new_evidence_text": fact.get("evidence_text", [])
                    })
                    logger.debug(f"追加事实: fact_id={matched_fact_id}, turn_ids={fact.get('evidence_turn_ids', [])}")
                else:
                    logger.warning(f"追加操作失败: 找不到matched_fact_id={matched_fact_id}，改为新建")
                    new_facts.append(fact)
            else:
                new_facts.append(fact)

        if append_operations and ctx.db:
            self._apply_fact_appends(ctx, append_operations)

        logger.info(f"增量处理完成: 新建 {len(new_facts)} 条, 追加 {len(append_operations)} 条")
        return new_facts

    def _apply_fact_appends(self, ctx: PipelineContext, append_operations: List[Dict]):
        try:
            for op in append_operations:
                fact_id = op["fact_id"]
                fact = ctx.db.query(AtomicFact).filter(AtomicFact.fact_id == fact_id).first()
                if fact:
                    existing_turn_ids = set(fact.evidence_turn_ids or [])
                    new_turn_ids = set(op.get("new_evidence_turn_ids", []))
                    existing_turn_ids.update(new_turn_ids)
                    fact.evidence_turn_ids = sorted(list(existing_turn_ids))

                    existing_texts = fact.evidence_text or []
                    new_texts = op.get("new_evidence_text", [])
                    for text in new_texts:
                        if text not in existing_texts:
                            existing_texts.append(text)
                    fact.evidence_text = existing_texts

                    logger.debug(f"已追加证据到事实 {fact_id}: turn_ids={fact.evidence_turn_ids}")

            ctx.db.commit()
            logger.info(f"已追加 {len(append_operations)} 条事实的证据")
        except Exception as e:
            ctx.db.rollback()
            logger.error(f"追加事实证据失败: {e}")

    @staticmethod
    def _deduplicate_facts(facts: List[Dict]) -> List[Dict]:
        logger.info("开始事实去重")

        merged = {}
        for fact in facts:
            mention = fact.get("mention", "").strip()
            section = fact.get("section_candidate", "")
            speaker = fact.get("speaker", "")

            key = f"{mention}|{section}|{speaker}"

            if key in merged:
                existing = merged[key]
                existing_turn_ids = set(existing.get("evidence_turn_ids", []))
                new_turn_ids = set(fact.get("evidence_turn_ids", []))
                existing_turn_ids.update(new_turn_ids)
                existing["evidence_turn_ids"] = sorted(list(existing_turn_ids))

                existing_texts = existing.get("evidence_text", [])
                new_texts = fact.get("evidence_text", [])
                for text in new_texts:
                    if text not in existing_texts:
                        existing_texts.append(text)
                existing["evidence_text"] = existing_texts

                if fact.get("certainty") == "explicit" and existing.get("certainty") != "explicit":
                    existing["certainty"] = "explicit"

                logger.debug(f"合并事实: '{mention}' (section={section}), turn_ids={existing['evidence_turn_ids']}")
            else:
                merged[key] = dict(fact)

        logger.info(f"事实去重完成: {len(facts)} -> {len(merged)}")
        return list(merged.values())

    @staticmethod
    def _save_atomic_facts(ctx: PipelineContext, facts: List[Dict], visit_id: str):
        try:
            saved_count = 0
            for fact_data in facts:
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

                ctx.db.add(atomic_fact)
                saved_count += 1

            ctx.db.commit()
            logger.info(f"已保存 {saved_count} 条原子事实到数据库")
        except Exception as e:
            ctx.db.rollback()
            logger.error(f"保存原子事实失败: {e}")