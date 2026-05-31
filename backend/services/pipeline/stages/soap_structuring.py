import time
from typing import Dict, Any

from ..base import PipelineContext, PipelineStage
from ..utils import parse_json_response, JSONParseError
from ..debug_interactor import DebugInteractor
from .direct_soap_generation import DirectSOAPGenerationStage
from ....utils.logger import logger


class SoapStructuringStage(PipelineStage):

    def stage_name(self) -> str:
        return "草稿结构化"

    def execute(self, ctx: PipelineContext) -> Dict[str, Any]:
        logger.info(f">>> 阶段: {self.stage_name()}")
        stage_start = time.time()

        draft_text = ctx.draft_text
        combined_text = ctx.combined_text

        if not draft_text:
            logger.warning("draft_text为空，返回空SOAP结构")
            empty_draft = DirectSOAPGenerationStage._empty_draft()
            ctx.emr_draft = empty_draft
            return {"emr_draft": empty_draft, "status": "skipped"}

        prompt = ctx.prompt_manager.render(
            "soap_structuring",
            draft_text=draft_text,
            transcript=combined_text
        )
        logger.debug(f"草稿结构化提示词长度: {len(prompt)} 字符")

        debug_interactor = DebugInteractor(ctx.llm_service)

        if ctx.debug_mode:
            try:
                response_text = debug_interactor.interact(
                    stage="soap_structuring",
                    prompt=prompt
                )
            except RuntimeError as e:
                logger.error(f"DEBUG模式交互失败: {e}")
                empty_draft = DirectSOAPGenerationStage._empty_draft()
                ctx.emr_draft = empty_draft
                return {"emr_draft": empty_draft, "status": "debug_cancelled"}
        else:
            if not ctx.llm_service:
                logger.warning("LLM服务不可用，返回空SOAP结构")
                empty_draft = DirectSOAPGenerationStage._empty_draft()
                ctx.emr_draft = empty_draft
                return {"emr_draft": empty_draft, "status": "llm_unavailable"}

            try:
                response = ctx.llm_service.generate(prompt, thinking_enabled=False)
                logger.debug("草稿结构化阶段: thinking模式已禁用")
                response_text = response.text
            except Exception as e:
                logger.error(f"草稿结构化LLM调用失败: {e}")
                empty_draft = DirectSOAPGenerationStage._empty_draft()
                ctx.emr_draft = empty_draft
                return {"emr_draft": empty_draft, "status": "llm_error"}

        try:
            draft = parse_json_response(response_text, "草稿结构化", raise_on_error=True)
        except JSONParseError as e:
            logger.error(f"草稿结构化JSON解析失败")
            logger.error(f"=== LLM完整响应内容 ===")
            logger.error(e.get_full_response())
            logger.error(f"=== 响应内容结束 ===")
            empty_draft = DirectSOAPGenerationStage._empty_draft()
            ctx.emr_draft = empty_draft
            return {"emr_draft": empty_draft, "status": "parse_error"}

        draft = DirectSOAPGenerationStage._build_evidence_traces(draft, ctx.turns)

        ctx.emr_draft = draft

        stage_time = time.time() - stage_start
        logger.info(f"草稿结构化完成, 耗时: {stage_time:.2f}秒")

        return {"emr_draft": draft, "status": "success"}
