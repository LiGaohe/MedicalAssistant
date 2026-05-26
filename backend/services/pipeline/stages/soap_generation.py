import json
import time
from typing import Dict, Any, List

from ..base import PipelineContext, PipelineStage
from ..utils import parse_json_response
from ..debug_interactor import DebugInteractor
from ....models import AtomicFact
from ....utils.logger import logger


class SOAPGenerationStage(PipelineStage):
    STAGE_DELAY = 0.5

    def stage_name(self) -> str:
        return "分节生成SOAP病历"

    def execute(self, ctx: PipelineContext) -> Dict[str, Any]:
        logger.info(f">>> 阶段4: {self.stage_name()}")
        stage_start = time.time()

        fact_records = ctx.fact_records
        role_mapping = ctx.all_role_mappings

        so_result = self._generate_so(ctx, fact_records, role_mapping)
        ap_result = self._generate_ap(ctx, so_result, fact_records, role_mapping)

        emr_draft = {
            "subjective": so_result.get("subjective", {}),
            "objective": so_result.get("objective", {}),
            "assessment": ap_result.get("assessment", {}),
            "plan": ap_result.get("plan", {}),
            "so_used_fact_ids": so_result.get("used_fact_ids", []),
            "assessment_items": ap_result.get("assessment_items", []),
            "plan_items": ap_result.get("plan_items", {})
        }

        so_used_fact_ids = emr_draft.get("so_used_fact_ids", [])
        assessment_items = emr_draft.get("assessment_items", [])
        logger.info(
            f"病历生成阶段完成（SO/AP分节），S/O使用fact数={len(so_used_fact_ids)}, "
            f"评估项数={len(assessment_items)}, 耗时: {time.time() - stage_start:.2f}秒"
        )

        ctx.emr_draft = emr_draft

        return {
            "so_result": so_result,
            "ap_result": ap_result,
            "emr_draft": emr_draft
        }

    def _generate_so(
        self,
        ctx: PipelineContext,
        fact_records: List[AtomicFact],
        role_mapping: Dict[str, str]
    ) -> Dict[str, Any]:
        logger.info(">>> 阶段4a: 分节生成SO（主观+客观）")
        stage_start = time.time()

        so_facts = self._filter_facts_by_section(fact_records, ["S", "O"])
        logger.info(f"SO生成输入: {len(fact_records)} 条事实，过滤后 {len(so_facts)} 条S/O事实")

        facts_json = self._format_facts_for_prompt(so_facts)

        dialogue_parts = []
        for fact in so_facts:
            mention = fact.normalized_term or fact.mention
            speaker_label = fact.speaker or "unknown"
            dialogue_parts.append(f"[{speaker_label}]: {mention}")
        dialogue_summary = "\n".join(dialogue_parts)

        prompt = ctx.prompt_manager.render(
            "emr_generation_so",
            facts_json=facts_json,
            dialogue_summary=dialogue_summary
        )
        logger.debug(f"SO生成提示词长度: {len(prompt)} 字符")

        debug_interactor = DebugInteractor(ctx.llm_service)

        if ctx.debug_mode:
            response_text = debug_interactor.interact(
                stage="emr_generation_so",
                prompt=prompt,
                facts_json=facts_json
            )
        else:
            if not ctx.llm_service:
                logger.warning("LLM服务不可用，SO生成失败")
                return {"subjective": {}, "objective": {}, "used_fact_ids": []}

            try:
                response = ctx.llm_service.generate(prompt, thinking_enabled=False)
                logger.debug("SO生成阶段: thinking模式已禁用")
                response_text = response.text
            except Exception as e:
                logger.error(f"SO生成LLM调用失败: {e}")
                return {"subjective": {}, "objective": {}, "used_fact_ids": []}

        result = parse_json_response(response_text, "SO生成")

        if result:
            stage_time = time.time() - stage_start
            logger.info(f"SO生成完成: 使用 {len(result.get('used_fact_ids', []))} 条事实, 耗时: {stage_time:.2f}秒")
            return result

        logger.warning("SO生成JSON解析失败，返回空结果")
        return {"subjective": {}, "objective": {}, "used_fact_ids": []}

    def _generate_ap(
        self,
        ctx: PipelineContext,
        so_result: Dict[str, Any],
        fact_records: List[AtomicFact],
        role_mapping: Dict[str, str],
        merged: bool = True
    ) -> Dict[str, Any]:
        logger.info(">>> 阶段4b: 分节生成AP（评估+计划）")
        stage_start = time.time()

        ap_facts = self._filter_facts_by_section(fact_records, ["A", "P"])
        logger.info(f"AP生成输入: {len(fact_records)} 条事实，A/P事实 {len(ap_facts)} 条")

        subjective_text = json.dumps(so_result.get("subjective", {}), ensure_ascii=False, indent=2)
        objective_text = json.dumps(so_result.get("objective", {}), ensure_ascii=False, indent=2)
        facts_json = self._format_facts_for_prompt(ap_facts)

        debug_interactor = DebugInteractor(ctx.llm_service)

        if merged:
            logger.info(">>> 使用合并模式: 单次LLM调用同时生成A和P")
            prompt = ctx.prompt_manager.render(
                "emr_generation_ap",
                subjective_text=subjective_text,
                objective_text=objective_text,
                facts_json=facts_json
            )
            logger.debug(f"AP合并生成提示词长度: {len(prompt)} 字符")

            if ctx.debug_mode:
                response_text = debug_interactor.interact(
                    stage="emr_generation_ap",
                    prompt=prompt,
                    facts_json=facts_json
                )
            else:
                if not ctx.llm_service:
                    logger.warning("LLM服务不可用，AP生成失败")
                    return {"assessment": {}, "plan": {}, "assessment_items": [], "plan_items": {}}

                try:
                    response = ctx.llm_service.generate(prompt)
                    response_text = response.text
                except Exception as e:
                    logger.error(f"AP合并生成LLM调用失败: {e}")
                    return {"assessment": {}, "plan": {}, "assessment_items": [], "plan_items": {}}

            result = parse_json_response(response_text, "AP合并生成")

            if result:
                assessment = result.get("assessment", {})
                assessment_items = result.get("assessment_items", [])
                if not assessment_items and isinstance(assessment, dict):
                    assessment_items = assessment.get("assessment_items", [])
                plan = result.get("plan", {})
                plan_items = result.get("plan_items", {})
                if (not plan_items or plan_items == {}) and isinstance(plan, dict):
                    plan_items = plan.get("plan_items", {})

                stage_time = time.time() - stage_start
                logger.info(
                    f"AP合并生成完成: 评估项={len(assessment_items)}, "
                    f"计划项={len(plan_items.get('medications', [])) + len(plan_items.get('tests', []))}, "
                    f"耗时: {stage_time:.2f}秒"
                )

                return {
                    "assessment": assessment,
                    "plan": plan,
                    "assessment_items": assessment_items,
                    "plan_items": plan_items
                }

            logger.warning("AP合并生成JSON解析失败，返回空结果")
            return {"assessment": {}, "plan": {}, "assessment_items": [], "plan_items": {}}

        else:
            logger.info(">>> 使用分离模式: 分两次LLM调用分别生成A和P")
            time.sleep(self.STAGE_DELAY)

            a_facts = self._filter_facts_by_section(fact_records, ["A"])
            p_facts = self._filter_facts_by_section(fact_records, ["P"])

            logger.info(">>> 阶段4b-1: 生成评估(Assessment)")
            assessment_facts_json = self._format_facts_for_prompt(a_facts)
            assessment_prompt = ctx.prompt_manager.render(
                "emr_generation_assessment",
                subjective_text=subjective_text,
                objective_text=objective_text,
                facts_json=assessment_facts_json
            )
            logger.debug(f"Assessment生成提示词长度: {len(assessment_prompt)} 字符")

            if ctx.debug_mode:
                assessment_response_text = debug_interactor.interact(
                    stage="emr_generation_assessment",
                    prompt=assessment_prompt,
                    facts_json=assessment_facts_json
                )
            else:
                if not ctx.llm_service:
                    logger.warning("LLM服务不可用，Assessment生成失败")
                    return {"assessment": {}, "plan": {}, "assessment_items": [], "plan_items": {}}

                try:
                    response = ctx.llm_service.generate(assessment_prompt)
                    logger.debug("Assessment生成阶段: thinking模式已启用（诊断推断）")
                    assessment_response_text = response.text
                except Exception as e:
                    logger.error(f"Assessment生成LLM调用失败: {e}")
                    return {"assessment": {}, "plan": {}, "assessment_items": [], "plan_items": {}}

            assessment_result = parse_json_response(assessment_response_text, "Assessment生成")

            if not assessment_result:
                logger.warning("Assessment JSON解析失败")
                assessment_result = {}

            assessment = assessment_result.get("assessment", {})
            assessment_items = assessment_result.get("assessment_items", [])
            if not assessment_items and isinstance(assessment, dict):
                assessment_items = assessment.get("assessment_items", [])
            assessment_text = json.dumps(assessment, ensure_ascii=False, indent=2)

            logger.info(f"Assessment生成完成: {len(assessment_items)} 条评估项")

            time.sleep(self.STAGE_DELAY)

            logger.info(">>> 阶段4b-2: 生成计划(Plan)")
            plan_facts_json = self._format_facts_for_prompt(p_facts)
            plan_prompt = ctx.prompt_manager.render(
                "emr_generation_plan",
                subjective_text=subjective_text,
                objective_text=objective_text,
                assessment_text=assessment_text,
                facts_json=plan_facts_json
            )
            logger.debug(f"Plan生成提示词长度: {len(plan_prompt)} 字符")

            if ctx.debug_mode:
                plan_response_text = debug_interactor.interact(
                    stage="emr_generation_plan",
                    prompt=plan_prompt,
                    facts_json=plan_facts_json
                )
            else:
                if not ctx.llm_service:
                    logger.warning("LLM服务不可用，Plan生成失败")
                    return {"assessment": assessment, "plan": {}, "assessment_items": assessment_items, "plan_items": {}}

                try:
                    response = ctx.llm_service.generate(plan_prompt)
                    logger.debug("Plan生成阶段: thinking模式已启用（诊断推断）")
                    plan_response_text = response.text
                except Exception as e:
                    logger.error(f"Plan生成LLM调用失败: {e}")
                    return {"assessment": assessment, "plan": {}, "assessment_items": assessment_items, "plan_items": {}}

            plan_result = parse_json_response(plan_response_text, "Plan生成")

            if not plan_result:
                logger.warning("Plan JSON解析失败")
                plan_result = {}

            plan = plan_result.get("plan", {})
            plan_items = plan_result.get("plan_items", {})
            if (not plan_items or plan_items == {}) and isinstance(plan, dict):
                plan_items = plan.get("plan_items", {})

            stage_time = time.time() - stage_start
            logger.info(f"AP分离生成完成，耗时: {stage_time:.2f}秒")

        return {
            "assessment": assessment,
            "plan": plan,
            "assessment_items": assessment_items,
            "plan_items": plan_items
        }

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

    @staticmethod
    def _filter_facts_by_section(
        fact_records: List[AtomicFact],
        sections: List[str]
    ) -> List[AtomicFact]:
        return [f for f in fact_records if f.section_candidate in sections]

    @staticmethod
    def _build_compact_context(
        fact_records: List[AtomicFact],
        max_items: int = 10
    ) -> str:
        context_items = []
        for f in fact_records:
            label = f.normalized_term or f.mention
            if not label:
                continue
            speaker = f.speaker or ""
            context_items.append(f"[{speaker}][{f.section_candidate}] {label}")
        if len(context_items) > max_items:
            context_items = context_items[:max_items] + [f"... 共 {len(fact_records)} 条事实"]
        return "\n".join(context_items)