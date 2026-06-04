import time
from typing import Dict, Any, List

from ..base import PipelineContext, PipelineStage
from ..utils import parse_json_response, JSONParseError
from ..debug_interactor import DebugInteractor
from ....utils.logger import logger
from ....config import settings


class DirectSOAPGenerationStage(PipelineStage):

    STAGE_DELAY = 0.5

    def stage_name(self) -> str:
        return "端到端草稿生成"

    def execute(self, ctx: PipelineContext) -> Dict[str, Any]:
        logger.info(f">>> 阶段: {self.stage_name()}")
        stage_start = time.time()

        combined_text = ctx.combined_text
        if not combined_text:
            if settings.DRAFT_GENERATION_MODE == "json":
                empty_draft = self._empty_draft()
                ctx.emr_draft = empty_draft
                return {"emr_draft": empty_draft, "status": "skipped"}
            else:
                ctx.draft_text = ""
                return {"draft_text": "", "status": "skipped"}

        if settings.DRAFT_GENERATION_MODE == "json":
            return self._execute_json_mode(ctx, combined_text, stage_start)
        else:
            return self._execute_free_text_mode(ctx, combined_text, stage_start)

    def _execute_free_text_mode(self, ctx: PipelineContext, combined_text: str, stage_start: float) -> Dict[str, Any]:
        prompt = ctx.prompt_manager.render(
            "free_soap_generation",
            transcript=combined_text
        )
        logger.debug(f"自由文本草稿生成提示词长度: {len(prompt)} 字符")

        debug_interactor = DebugInteractor(ctx.llm_service)

        if ctx.debug_mode:
            try:
                response_text = debug_interactor.interact(
                    stage="free_soap_generation",
                    prompt=prompt
                )
            except RuntimeError as e:
                logger.error(f"DEBUG模式交互失败: {e}")
                ctx.draft_text = ""
                ctx.emr_draft = self._empty_draft()
                return {"draft_text": "", "emr_draft": self._empty_draft(), "status": "debug_cancelled"}
        else:
            if not ctx.llm_service:
                logger.warning("LLM服务不可用，自由文本草稿生成跳过")
                ctx.draft_text = ""
                ctx.emr_draft = self._empty_draft()
                return {"draft_text": "", "emr_draft": self._empty_draft(), "status": "llm_unavailable"}

            try:
                response = ctx.llm_service.generate_stream_to_response(prompt, thinking_enabled=False)
                logger.debug("自由文本草稿生成阶段: thinking模式已禁用，使用流式处理")
                ctx.llm_stats.record_from_response("draft_generation_free_text", prompt, response)
                response_text = response.text
            except Exception as e:
                logger.error(f"自由文本草稿生成LLM调用失败: {e}")
                ctx.llm_stats.record_call("draft_generation_free_text", len(prompt), 0, success=False, error_message=str(e))
                ctx.draft_text = ""
                ctx.emr_draft = self._empty_draft()
                return {"draft_text": "", "emr_draft": self._empty_draft(), "status": "llm_error"}

        draft_json = self._parse_simple_soap_json(response_text)
        if draft_json:
            ctx.draft_text = self._format_draft_text_from_json(draft_json)
            ctx.emr_draft = draft_json
            ctx.skip_structuring = True
            stage_time = time.time() - stage_start
            logger.info(f"自由文本草稿生成完成（JSON已解析为标准格式），耗时: {stage_time:.2f}秒")
            return {"draft_text": ctx.draft_text, "emr_draft": draft_json, "skip_structuring": True, "status": "success"}
        
        ctx.draft_text = response_text
        stage_time = time.time() - stage_start
        logger.info(f"自由文本草稿生成完成（非JSON格式，需后续结构化），耗时: {stage_time:.2f}秒")
        return {"draft_text": response_text, "status": "success"}

    def _parse_simple_soap_json(self, response_text: str) -> Dict[str, Any]:
        try:
            simple_json = parse_json_response(response_text, "自由文本草稿", raise_on_error=False)
            if not simple_json or not isinstance(simple_json, dict):
                return None
            
            if not all(k in simple_json for k in ["S", "O", "A", "P"]):
                return None
            
            draft = {
                "subjective": {"text": simple_json.get("S", "")},
                "objective": {"text": simple_json.get("O", "")},
                "assessment": {"text": simple_json.get("A", "")},
                "plan": {"text": simple_json.get("P", "")}
            }
            logger.info(f"LLM返回S/O/A/P JSON，已转换为标准SOAP格式")
            return draft
        except Exception as e:
            logger.debug(f"JSON解析失败: {e}")
            return None

    def _format_draft_text_from_json(self, draft_json: Dict[str, Any]) -> str:
        sections = []

        def _text(val):
            if isinstance(val, list):
                return "\n".join(str(item) for item in val)
            return str(val) if val else ""

        subj_text = _text(draft_json.get("subjective", {}).get("text", ""))
        if subj_text:
            sections.append("S - 主观症状\n" + subj_text)
        obj_text = _text(draft_json.get("objective", {}).get("text", ""))
        if obj_text:
            sections.append("O - 客观体征\n" + obj_text)
        assessment_text = _text(draft_json.get("assessment", {}).get("text", ""))
        if assessment_text:
            sections.append("A - 评估诊断\n" + assessment_text)
        plan_text = _text(draft_json.get("plan", {}).get("text", ""))
        if plan_text:
            sections.append("P - 治疗计划\n" + plan_text)
        return "\n\n".join(sections) if sections else ""

    def _execute_json_mode(self, ctx: PipelineContext, combined_text: str, stage_start: float) -> Dict[str, Any]:
        prompt = ctx.prompt_manager.render(
            "direct_soap_generation",
            transcript=combined_text
        )
        logger.debug(f"直接草稿生成提示词长度: {len(prompt)} 字符")

        debug_interactor = DebugInteractor(ctx.llm_service)

        if ctx.debug_mode:
            try:
                response_text = debug_interactor.interact(
                    stage="direct_soap_generation",
                    prompt=prompt
                )
            except RuntimeError as e:
                logger.error(f"DEBUG模式交互失败: {e}")
                empty_draft = self._empty_draft()
                ctx.emr_draft = empty_draft
                return {"emr_draft": empty_draft, "status": "debug_cancelled"}
        else:
            if not ctx.llm_service:
                logger.warning("LLM服务不可用，返回空SOAP结构")
                empty_draft = self._empty_draft()
                ctx.emr_draft = empty_draft
                return {"emr_draft": empty_draft, "status": "llm_unavailable"}

            try:
                response = ctx.llm_service.generate_stream_to_response(prompt, thinking_enabled=False)
                logger.debug("直接草稿生成阶段: thinking模式已禁用，使用流式处理")
                ctx.llm_stats.record_from_response("draft_generation_json", prompt, response)
                response_text = response.text
            except Exception as e:
                logger.error(f"直接草稿生成LLM调用失败: {e}")
                ctx.llm_stats.record_call("draft_generation_json", len(prompt), 0, success=False, error_message=str(e))
                empty_draft = self._empty_draft()
                ctx.emr_draft = empty_draft
                return {"emr_draft": empty_draft, "status": "llm_error"}

        try:
            draft = parse_json_response(response_text, "直接草稿生成", raise_on_error=True)
        except JSONParseError as e:
            logger.error(f"直接草稿生成JSON解析失败")
            logger.error(f"=== LLM完整响应内容 ===")
            logger.error(e.get_full_response())
            logger.error(f"=== 响应内容结束 ===")
            empty_draft = self._empty_draft()
            ctx.emr_draft = empty_draft
            return {"emr_draft": empty_draft, "status": "parse_error"}

        draft = self._build_evidence_traces(draft, ctx.turns)

        ctx.emr_draft = draft

        stage_time = time.time() - stage_start
        logger.info(f"直接草稿生成完成, 耗时: {stage_time:.2f}秒")

        return {"emr_draft": draft, "status": "success"}

    @staticmethod
    def _build_evidence_traces(draft: Dict[str, Any], turns: List) -> Dict[str, Any]:
        logger.info("开始构建证据溯源")

        turn_map = {}
        for turn in turns:
            turn_map[turn.turn_index] = turn
        logger.debug(f"turn映射表包含 {len(turn_map)} 个turn")

        sections = ["subjective", "objective", "assessment", "plan"]
        total_traces = 0

        for section_name in sections:
            section = draft.get(section_name, {})
            if not isinstance(section, dict):
                logger.debug(f"section {section_name} 不是dict类型，跳过")
                continue

            for field_name, field_value in list(section.items()):
                if not isinstance(field_value, dict):
                    continue
                if "value" not in field_value:
                    continue

                source_indices = field_value.get("source_turn_indices", None)

                evidence_traces = []
                if source_indices and isinstance(source_indices, list):
                    for idx in source_indices:
                        turn = turn_map.get(idx)
                        if turn:
                            turn_text = turn.corrected_text or turn.text
                            evidence_trace = {
                                "turn_id": turn.turn_id,
                                "turn_index": turn.turn_index,
                                "speaker": turn.speaker,
                                "turn_text": turn_text,
                                "content": turn_text[:100] if turn_text else ""
                            }
                            evidence_traces.append(evidence_trace)
                        else:
                            logger.warning(
                                f"source_turn_index={idx} 在turns列表中未找到对应turn, "
                                f"section={section_name}, field={field_name}"
                            )
                else:
                    logger.debug(
                        f"字段 {section_name}.{field_name} 没有source_turn_indices, "
                        f"evidence_traces为空"
                    )

                section[field_name] = {
                    "value": field_value.get("value", ""),
                    "source_turn_indices": source_indices if source_indices else [],
                    "evidence_traces": evidence_traces
                }
                total_traces += len(evidence_traces)

        logger.info(f"证据溯源构建完成: 共 {total_traces} 条trace")
        return draft

    @staticmethod
    def _empty_draft() -> Dict[str, Any]:
        return {
            "subjective": {
                "chief_complaint": {"value": "", "evidence_traces": []},
                "history_present_illness": {"value": "", "evidence_traces": []},
                "denied_symptoms": {"value": "", "evidence_traces": []},
                "past_history": {"value": "", "evidence_traces": []}
            },
            "objective": {
                "physical_examination": {"value": "", "evidence_traces": []},
                "auxiliary_examination": {"value": "", "evidence_traces": []}
            },
            "assessment": {
                "diagnosis": {"value": "", "evidence_traces": []}
            },
            "plan": {
                "treatment": {"value": "", "evidence_traces": []},
                "advice": {"value": "", "evidence_traces": []}
            }
        }
