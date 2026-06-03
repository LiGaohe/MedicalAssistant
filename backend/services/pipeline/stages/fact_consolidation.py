# DEPRECATED: 六阶段流水线已重构为四阶段。事实收束阶段不再使用。
import json
import time
from typing import Dict, Any, List

from ..base import PipelineContext, PipelineStage
from ..utils import parse_json_response
from ..debug_interactor import DebugInteractor
from ....models import AtomicFact
from ....utils.logger import logger
from ...fact_service import FactService


class FactConsolidationStage(PipelineStage):
    def stage_name(self) -> str:
        return "事实收束"

    def execute(self, ctx: PipelineContext) -> Dict[str, Any]:
        logger.info(f">>> 阶段2.5: {self.stage_name()}")
        stage_start = time.time()

        fact_records = ctx.fact_records
        visit_id = ctx.visit_id

        if not fact_records:
            logger.info("没有事实需要收束")
            result = {"merged_count": 0, "conflict_count": 0, "resolved_count": 0, "final_fact_count": 0}
            ctx.consolidation_result = result
            return result

        facts_json = self._format_facts_for_prompt(fact_records, lightweight=True)

        prompt = ctx.prompt_manager.render("fact_consolidation", facts_json=facts_json)
        logger.debug(f"事实收束提示词长度: {len(prompt)} 字符")

        debug_interactor = DebugInteractor(ctx.llm_service)

        if ctx.debug_mode:
            response_text = debug_interactor.interact(
                stage="fact_consolidation",
                prompt=prompt,
                fact_count=len(fact_records)
            )
        else:
            if not ctx.llm_service:
                logger.warning("LLM服务不可用，跳过事实收束")
                result = {"merged_count": 0, "conflict_count": 0, "resolved_count": 0, "final_fact_count": len(fact_records)}
                ctx.consolidation_result = result
                return result

            try:
                response = ctx.llm_service.generate(prompt, timeout=300.0, thinking_enabled=False)
                logger.debug("事实收束阶段: thinking模式已禁用")
                ctx.llm_stats.record_from_response("fact_consolidation", prompt, response)
                response_text = response.text
            except Exception as e:
                logger.error(f"事实收束LLM调用失败: {e}")
                ctx.llm_stats.record_call("fact_consolidation", len(prompt), 0, success=False, error_message=str(e))
                result = {"merged_count": 0, "conflict_count": 0, "resolved_count": 0, "final_fact_count": len(fact_records)}
                ctx.consolidation_result = result
                return result

        parsed = parse_json_response(response_text, "事实收束")

        merged_count = 0
        conflict_count = 0
        resolved_count = 0

        if parsed:
            merged_facts = parsed.get("merged_facts", [])
            conflict_facts = parsed.get("conflict_facts", [])
            resolved_facts = parsed.get("resolved_facts", [])

            if merged_facts and ctx.db:
                merged_count = self._apply_fact_merges(ctx, merged_facts)

            if conflict_facts and ctx.db:
                conflict_count = self._mark_conflict_facts(ctx, conflict_facts)

            if resolved_facts and ctx.db:
                resolved_count = self._apply_fact_resolutions(ctx, resolved_facts)

        fact_service = FactService(ctx.db)
        final_facts = fact_service.get_facts_by_visit(visit_id)
        final_count = len(final_facts)

        stage_time = time.time() - stage_start
        logger.info(
            f"事实收束完成: 合并={merged_count}, 冲突={conflict_count}, "
            f"补判={resolved_count}, 最终={final_count}, 耗时: {stage_time:.2f}秒"
        )

        result = {
            "merged_count": merged_count,
            "conflict_count": conflict_count,
            "resolved_count": resolved_count,
            "final_fact_count": final_count
        }
        ctx.consolidation_result = result
        return result

    def _apply_fact_merges(self, ctx: PipelineContext, merged_facts: List[Dict]) -> int:
        try:
            merged_count = 0
            for merge_info in merged_facts:
                keep_fact_id = merge_info.get("fact_id")
                merged_from_ids = merge_info.get("merged_from", [])

                if not keep_fact_id or not merged_from_ids:
                    continue

                keep_fact = ctx.db.query(AtomicFact).filter(AtomicFact.fact_id == keep_fact_id).first()
                if not keep_fact:
                    continue

                all_turn_ids = set(keep_fact.evidence_turn_ids or [])
                all_spans = keep_fact.evidence_spans or []

                for from_id in merged_from_ids:
                    if from_id == keep_fact_id:
                        continue
                    from_fact = ctx.db.query(AtomicFact).filter(AtomicFact.fact_id == from_id).first()
                    if from_fact:
                        all_turn_ids.update(from_fact.evidence_turn_ids or [])
                        for span in (from_fact.evidence_spans or []):
                            if span not in all_spans:
                                all_spans.append(span)
                        ctx.db.delete(from_fact)

                keep_fact.evidence_turn_ids = sorted(list(all_turn_ids))
                keep_fact.evidence_spans = all_spans
                merged_count += 1

            ctx.db.commit()
            logger.info(f"已合并 {merged_count} 组事实")
            return merged_count
        except Exception as e:
            ctx.db.rollback()
            logger.error(f"应用事实合并失败: {e}")
            return 0

    def _mark_conflict_facts(self, ctx: PipelineContext, conflict_facts: List[Dict]) -> int:
        try:
            conflict_count = 0
            for conflict_info in conflict_facts:
                fact_id = conflict_info.get("fact_id")
                if not fact_id:
                    continue

                fact = ctx.db.query(AtomicFact).filter(AtomicFact.fact_id == fact_id).first()
                if fact:
                    fact.asr_risk = "high"
                    conflict_count += 1

            ctx.db.commit()
            logger.info(f"已标记 {conflict_count} 条冲突事实")
            return conflict_count
        except Exception as e:
            ctx.db.rollback()
            logger.error(f"标记冲突事实失败: {e}")
            return 0

    def _apply_fact_resolutions(self, ctx: PipelineContext, resolved_facts: List[Dict]) -> int:
        try:
            resolved_count = 0
            for resolve_info in resolved_facts:
                fact_id = resolve_info.get("fact_id")
                resolved_field = resolve_info.get("resolved_field")
                resolved_value = resolve_info.get("resolved_value")

                if not fact_id or not resolved_field or not resolved_value:
                    continue

                fact = ctx.db.query(AtomicFact).filter(AtomicFact.fact_id == fact_id).first()
                if fact:
                    if resolved_field == "certainty":
                        fact.certainty = resolved_value
                    elif resolved_field == "temporality":
                        fact.temporality = resolved_value
                    resolved_count += 1

            ctx.db.commit()
            logger.info(f"已补判 {resolved_count} 条事实")
            return resolved_count
        except Exception as e:
            ctx.db.rollback()
            logger.error(f"应用事实补判失败: {e}")
            return 0

    @staticmethod
    def _format_facts_for_prompt(fact_records: List[AtomicFact], lightweight: bool = True) -> str:
        facts_data = []
        for fact in fact_records:
            fact_item = {
                "fact_id": fact.fact_id,
                "section_candidate": fact.section_candidate,
                "concept_type": fact.concept_type,
                "mention": fact.mention,
                "normalized_term": fact.normalized_term,
                "polarity": fact.polarity,
                "temporality": fact.temporality,
                "certainty": fact.certainty,
                "speaker": fact.speaker,
                "evidence_turn_ids": fact.evidence_turn_ids or []
            }

            if lightweight:
                evidence_spans = fact.evidence_spans or []
                if not evidence_spans and fact.evidence_text:
                    evidence_spans = [text[:20] if len(text) > 20 else text for text in fact.evidence_text[:3]]
                fact_item["evidence_spans"] = evidence_spans
            else:
                fact_item["evidence_text"] = fact.evidence_text or []

            facts_data.append(fact_item)
        return json.dumps(facts_data, ensure_ascii=False, indent=2)