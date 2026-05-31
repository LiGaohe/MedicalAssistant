import json
import time
from typing import Dict, Any, List

from ..base import PipelineContext, PipelineStage
from ..utils import parse_json_response
from ..debug_interactor import DebugInteractor
from ....utils.logger import logger


class HallucinationCheckStage(PipelineStage):
    """幻觉检查阶段：在SOAP草稿生成后立即核查是否存在对话中没有依据的虚假内容。

    使用 consistency_check 提示模板，对病历中所有字段进行逐事实核查，
    标记出 original transcript 中无法找到依据的声明（即幻觉）。
    覆盖 S/O/A/P 全部四个章节，与 ClaimVerificationStage 形成互补：
    - HallucinationCheckStage: 检查全SOAP，关注"是不是编的"
    - ClaimVerificationStage: 检查A/P，关注"是不是漏的"和"确定性对不对"
    """

    STAGE_DELAY = 0.5

    HALLUCINATION_WARN_THRESHOLD = 0.75

    def stage_name(self) -> str:
        return "幻觉检查"

    def execute(self, ctx: PipelineContext) -> Dict[str, Any]:
        logger.info(f">>> 阶段: {self.stage_name()}")
        stage_start = time.time()

        draft_emr = ctx.emr_draft
        combined_text = ctx.combined_text

        if not draft_emr:
            logger.warning("草稿为空，跳过幻觉检查")
            ctx.hallucination_result = self._empty_result()
            return {"status": "skipped_empty_draft"}

        if not combined_text:
            logger.warning("原始对话文本为空，跳过幻觉检查")
            ctx.hallucination_result = self._empty_result()
            return {"status": "skipped_empty_transcript"}

        emr_content = self._format_emr_for_check(draft_emr)
        if not emr_content.strip():
            logger.warning("草稿中无可检查文本，跳过幻觉检查")
            ctx.hallucination_result = self._empty_result()
            return {"status": "skipped_empty_content"}

        try:
            prompt = ctx.prompt_manager.render(
                "consistency_check",
                transcript=combined_text,
                emr_content=emr_content
            )
            logger.debug(f"幻觉检查提示词长度: {len(prompt)} 字符")
        except Exception as e:
            logger.error(f"幻觉检查提示词渲染失败: {e}")
            ctx.hallucination_result = self._empty_result()
            return {"status": "prompt_render_error"}

        debug_interactor = DebugInteractor(ctx.llm_service)

        if ctx.debug_mode:
            try:
                response_text = debug_interactor.interact(
                    stage="hallucination_check",
                    prompt=prompt
                )
            except Exception as e:
                logger.error(f"幻觉检查Debug交互失败: {e}")
                ctx.hallucination_result = self._empty_result()
                return {"status": "debug_cancelled"}
        else:
            if not ctx.llm_service:
                logger.warning("LLM服务不可用，跳过幻觉检查")
                ctx.hallucination_result = self._empty_result()
                return {"status": "llm_unavailable"}

            try:
                response = ctx.llm_service.generate(prompt)
                response_text = response.text
            except Exception as e:
                logger.error(f"幻觉检查LLM调用失败: {e}")
                ctx.hallucination_result = self._empty_result()
                return {"status": "llm_error"}

        parsed = parse_json_response(response_text, "幻觉检查")
        if not parsed:
            logger.warning("幻觉检查JSON解析失败，使用空结果")
            ctx.hallucination_result = self._empty_result()
            return {"status": "parse_error"}

        facts = parsed.get("facts", [])
        summary = parsed.get("summary", {})

        unsupported_facts = [f for f in facts if not f.get("is_supported", True)]
        supported_facts = [f for f in facts if f.get("is_supported", True)]

        total_facts = summary.get("total_facts", len(facts))
        supported_count = summary.get("supported_count", len(supported_facts))
        unsupported_count = summary.get("unsupported_count", len(unsupported_facts))
        support_rate = summary.get("support_rate", 0.0)

        if total_facts == 0 and len(unsupported_facts) > 0:
            total_facts = len(facts)
            supported_count = len(supported_facts)
            unsupported_count = len(unsupported_facts)
            support_rate = supported_count / total_facts if total_facts > 0 else 0.0

        result = {
            "facts": facts,
            "unsupported_facts": unsupported_facts,
            "supported_facts": supported_facts,
            "summary": {
                "total_facts": total_facts,
                "supported_count": supported_count,
                "unsupported_count": unsupported_count,
                "support_rate": round(support_rate, 4),
            },
            "has_hallucination": unsupported_count > 0,
            "severity": self._determine_severity(support_rate, unsupported_count),
        }

        ctx.hallucination_result = result

        stage_time = time.time() - stage_start
        logger.info("=" * 50)
        logger.info(f"幻觉检查完成 - 耗时: {stage_time:.2f}秒")
        logger.info(f"  - 总事实数: {total_facts}")
        logger.info(f"  - 有依据: {supported_count}")
        logger.info(f"  - 无依据(幻觉): {unsupported_count}")
        logger.info(f"  - 支持率: {support_rate:.2%}")
        logger.info(f"  - 严重程度: {result['severity']}")

        if unsupported_facts:
            logger.warning(f"!!! 发现 {unsupported_count} 条疑似幻觉 !!!")
            for i, fact in enumerate(unsupported_facts[:10]):
                logger.warning(
                    f"  幻觉#{i+1}: [{fact.get('section', '?')}] "
                    f"{fact.get('fact', '')[:120]}"
                )
            if len(unsupported_facts) > 10:
                logger.warning(f"  ...还有 {len(unsupported_facts) - 10} 条未显示")
        else:
            logger.info("未发现幻觉，所有事实均有对话依据")

        logger.info("=" * 50)

        return result

    @staticmethod
    def _format_emr_for_check(draft: Dict[str, Any]) -> str:
        """将SOAP草稿格式化为用于一致性检查的纯文本。

        提取所有字段的value值，按章节组织，便于LLM逐事实核查。
        """
        lines: List[str] = []
        section_labels = {
            "subjective": "【主观数据 S】",
            "objective": "【客观数据 O】",
            "assessment": "【评估 A】",
            "plan": "【计划 P】",
        }

        for section_name, label in section_labels.items():
            section = draft.get(section_name, {})
            if not isinstance(section, dict):
                continue

            field_lines: List[str] = []
            for field_name, field_data in section.items():
                if field_name in ("text", "evidence_traces", "assessment_items", "plan_items"):
                    continue
                if not isinstance(field_data, dict):
                    continue
                value = field_data.get("value", "")
                if value and isinstance(value, str) and value.strip():
                    field_lines.append(f"  - {field_name}: {value}")

            if field_lines:
                lines.append(label)
                lines.extend(field_lines)

        return "\n".join(lines)

    @staticmethod
    def _determine_severity(support_rate: float, unsupported_count: int) -> str:
        if support_rate < 0.5 or unsupported_count >= 3:
            return "high"
        elif support_rate < HallucinationCheckStage.HALLUCINATION_WARN_THRESHOLD or unsupported_count >= 1:
            return "medium"
        else:
            return "low"

    @staticmethod
    def _empty_result() -> Dict[str, Any]:
        return {
            "facts": [],
            "unsupported_facts": [],
            "supported_facts": [],
            "summary": {
                "total_facts": 0,
                "supported_count": 0,
                "unsupported_count": 0,
                "support_rate": 1.0,
            },
            "has_hallucination": False,
            "severity": "unknown",
        }