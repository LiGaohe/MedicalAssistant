import time
from typing import Dict, Any, List

from ..base import PipelineContext, PipelineStage
from ..utils import parse_json_response, JSONParseError
from ..debug_interactor import DebugInteractor
from ....utils.logger import logger


class DirectSOAPGenerationStage(PipelineStage):
    """直接根据清洗后的对话全文生成SOAP草稿。

    与 SOAPGenerationStage 不同，本阶段不依赖事实抽取和分节流程，
    而是直接将完整对话文本送入LLM，一次性生成完整的SOAP病历草稿。
    """

    STAGE_DELAY = 0.5

    def stage_name(self) -> str:
        return "直接草稿生成"

    def execute(self, ctx: PipelineContext) -> Dict[str, Any]:
        logger.info(f">>> 阶段: {self.stage_name()}")
        stage_start = time.time()

        combined_text = ctx.combined_text
        if not combined_text:
            logger.warning("combined_text为空，无法生成SOAP草稿，返回空结构")
            empty_draft = self._empty_draft()
            ctx.emr_draft = empty_draft
            return {"emr_draft": empty_draft, "status": "skipped"}

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
                response = ctx.llm_service.generate(prompt, thinking_enabled=False)
                logger.debug("直接草稿生成阶段: thinking模式已禁用")
                response_text = response.text
            except Exception as e:
                logger.error(f"直接草稿生成LLM调用失败: {e}")
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
        """将LLM输出的 source_turn_indices 转换为 evidence_traces。

        遍历 subjective/objective/assessment/plan 每个section的每个子字段，
        将 source_turn_indices 中的 turn_index 匹配到 turns 列表中的具体轮次，
        构建包含对话原文证据的 evidence_trace 对象。

        Args:
            draft: LLM生成的SOAP草稿，每个子字段格式为
                   {"value": "...", "source_turn_indices": [...]}
            turns: 转写对话轮次列表（TranscriptTurn对象列表）

        Returns:
            转换后的草稿，source_turn_indices 被替换为 evidence_traces
        """
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
                    "evidence_traces": evidence_traces
                }
                total_traces += len(evidence_traces)

        logger.info(f"证据溯源构建完成: 共 {total_traces} 条trace")
        return draft

    @staticmethod
    def _empty_draft() -> Dict[str, Any]:
        """返回空的SOAP兜底结构。

        当LLM调用失败或JSON解析失败时，使用此结构作为兜底，
        确保流水线不会因单阶段失败而中断。
        """
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
