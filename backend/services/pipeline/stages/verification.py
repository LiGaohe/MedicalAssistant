# DEPRECATED: 六阶段流水线已重构为四阶段。依赖事实表的核查与修订已被 ClaimVerificationStage（基于对话文本核查）+ FieldRevisionStage 替代。
import json
import time
from typing import Dict, Any, List

from ..base import PipelineContext, PipelineStage
from ..utils import parse_json_response
from ..debug_interactor import DebugInteractor
from ....models import AtomicFact
from ....utils.logger import logger


class VerificationStage(PipelineStage):
    def stage_name(self) -> str:
        return "核查与修订"

    def execute(self, ctx: PipelineContext) -> Dict[str, Any]:
        logger.info(f">>> 阶段5: {self.stage_name()}")
        stage_start = time.time()

        draft_emr = ctx.emr_draft
        fact_records = ctx.fact_records
        role_mapping = ctx.all_role_mappings

        draft_emr_json = json.dumps(draft_emr, ensure_ascii=False, indent=2)

        fact_table_json = self._format_facts_for_prompt(fact_records)
        fact_table_count = len(fact_records)

        role_mapping_json = json.dumps(role_mapping, ensure_ascii=False, indent=2)

        logger.info(f"核查输入: 事实表 {fact_table_count} 条, 角色映射 {len(role_mapping)} 个")

        prompt = ctx.prompt_manager.render(
            "soap_verification",
            draft_emr=draft_emr_json,
            fact_table=fact_table_json,
            role_mapping=role_mapping_json
        )
        logger.debug(f"核查提示词长度: {len(prompt)} 字符")

        debug_interactor = DebugInteractor(ctx.llm_service)

        if ctx.debug_mode:
            response_text = debug_interactor.interact(
                stage="verification",
                prompt=prompt,
                draft_emr=draft_emr,
                fact_count=fact_table_count
            )
        else:
            if not ctx.llm_service:
                logger.warning("LLM服务不可用，跳过核查修订阶段，使用原始草稿")
                result = {"issues": {}, "soap_final": draft_emr}
                ctx.verification_result = result
                return result

            try:
                response = ctx.llm_service.generate_stream_to_response(prompt)
                logger.debug("核查修订阶段: thinking模式已启用（问题判断），使用流式处理")
                ctx.llm_stats.record_from_response("verification", prompt, response)
                response_text = response.text
            except Exception as e:
                logger.error(f"核查修订LLM调用失败: {e}")
                ctx.llm_stats.record_call("verification", len(prompt), 0, success=False, error_message=str(e))
                result = {"issues": {}, "soap_final": draft_emr}
                ctx.verification_result = result
                return result

        parsed = parse_json_response(response_text, "核查修订")

        if parsed and "soap_final" in parsed:
            issues = parsed.get("issues", {})
            soap_final = parsed["soap_final"]

            unsupported_count = len(issues.get("unsupported_claims", []))
            missing_count = len(issues.get("missing_critical_facts", []))
            conflict_count = len(issues.get("internal_conflicts", []))
            certainty_error_count = len(issues.get("certainty_errors", []))

            logger.info(
                f"核查完成: "
                f"无证据声明={unsupported_count}, "
                f"关键遗漏={missing_count}, "
                f"内部冲突={conflict_count}, "
                f"确定性错误={certainty_error_count}"
            )

            stage_time = time.time() - stage_start
            logger.info(f"核查修订阶段完成，耗时: {stage_time:.2f}秒")

            result = {
                "issues": issues,
                "soap_final": soap_final
            }
            ctx.verification_result = result
            return result

        logger.warning("核查修订JSON解析失败，使用原始草稿作为最终版本")
        stage_time = time.time() - stage_start
        logger.info(f"核查修订阶段完成（回退），耗时: {stage_time:.2f}秒")
        result = {"issues": {}, "soap_final": draft_emr}
        ctx.verification_result = result
        return result

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