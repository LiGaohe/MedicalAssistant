import time
from typing import Dict, Any, List, Tuple

from ..base import PipelineContext, PipelineStage
from ..utils import parse_json_response, extract_section_fields, collect_turn_indices, build_section_transcript
from ..debug_interactor import DebugInteractor
from ....utils.logger import logger


class HallucinationCheckStage(PipelineStage):
    """幻觉检查阶段：按SOAP章节分段核查，利用source_turn_indices裁剪转写以减少token消耗。

    将一次大调用拆分为4次小调用（S/O/A/P各一次），每次：
    - 只发送该章节的病历字段
    - 只发送该章节字段对应的对话轮次（从source_turn_indices提取，加前后各1轮缓冲）
    - 只输出不支持的事实（大幅减少输出token）

    对于value非空但source_turn_indices为空的可疑字段，回退到发送完整转写。
    """

    STAGE_DELAY = 0.5

    HALLUCINATION_WARN_THRESHOLD = 0.75

    SECTION_LABELS = {
        "subjective": "主观数据 S",
        "objective": "客观数据 O",
        "assessment": "评估 A",
        "plan": "计划 P",
    }

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

        # 按SOAP章节分段核查
        section_results: List[Tuple[str, Dict[str, Any]]] = []

        for section_name in ["subjective", "objective", "assessment", "plan"]:
            section = draft_emr.get(section_name, {})
            if not isinstance(section, dict):
                continue

            # 提取字段，区分：空值字段/有source字段/无source字段
            normal_fields, suspect_fields, skipped_count = extract_section_fields(section, section_name)

            if not normal_fields and not suspect_fields:
                logger.debug(f"章节 {section_name} 无可核查字段（跳过{skipped_count}个空值字段）")
                continue

            # 确定转写范围
            if suspect_fields:
                logger.info(
                    f"章节 {section_name} 有 {len(suspect_fields)} 个可疑字段"
                    f"（value非空但无source_turn_indices），回退到完整转写"
                )
                transcript_section = combined_text
            else:
                relevant_indices = collect_turn_indices(normal_fields)
                transcript_section = build_section_transcript(
                    ctx.turns, relevant_indices, buffer=1
                )
                logger.info(
                    f"章节 {section_name} 使用裁剪转写，"
                    f"涉及 {len(relevant_indices)} 个对话轮次"
                )

            # 格式化该章节病历
            emr_section = self._format_section_emr(
                normal_fields + suspect_fields, section_name
            )

            if not emr_section.strip():
                logger.debug(f"章节 {section_name} 格式化后为空，跳过")
                continue

            # 调用LLM核查该章节
            section_result = self._check_section(
                ctx, transcript_section, emr_section, section_name
            )

            # 检查是否失败，失败则立即停止管线
            if "status" in section_result:
                failed_status = section_result["status"]
                failed_section = section_result.get("section", section_name)
                logger.error(
                    f"章节 {failed_section} 幻觉检查失败(status={failed_status}), "
                    f"停止管线, 不再继续后续章节"
                )
                ctx.hallucination_result = {
                    **self._empty_result(),
                    "status": failed_status,
                }
                return {"status": failed_status}

            section_results.append((section_name, section_result))

        if not section_results:
            logger.warning("所有章节均无可核查内容")
            ctx.hallucination_result = self._empty_result()
            return {"status": "skipped_no_content"}

        # 合并为原格式输出（保持下游兼容）
        result = self._merge_section_results(section_results)
        ctx.hallucination_result = result

        stage_time = time.time() - stage_start
        total_facts = result["summary"]["total_facts"]
        supported_count = result["summary"]["supported_count"]
        unsupported_count = result["summary"]["unsupported_count"]
        support_rate = result["summary"]["support_rate"]

        logger.info("=" * 50)
        logger.info(f"幻觉检查完成 - 耗时: {stage_time:.2f}秒")
        logger.info(f"  - 总事实数: {total_facts}")
        logger.info(f"  - 有依据: {supported_count}")
        logger.info(f"  - 无依据(幻觉): {unsupported_count}")
        logger.info(f"  - 支持率: {support_rate:.2%}")
        logger.info(f"  - 严重程度: {result['severity']}")

        if result["unsupported_facts"]:
            logger.warning(f"!!! 发现 {unsupported_count} 条疑似幻觉 !!!")
            for i, fact in enumerate(result["unsupported_facts"][:10]):
                logger.warning(
                    f"  幻觉#{i+1}: [{fact.get('section', '?')}] "
                    f"{fact.get('fact', '')[:120]}"
                )
            if len(result["unsupported_facts"]) > 10:
                logger.warning(f"  ...还有 {len(result['unsupported_facts']) - 10} 条未显示")
        else:
            logger.info("未发现幻觉，所有事实均有对话依据")

        logger.info("=" * 50)

        return result

    def _format_section_emr(
        self, fields: List[Dict[str, Any]], section_name: str
    ) -> str:
        """格式化单章节病历内容。"""
        label = self.SECTION_LABELS.get(section_name, section_name)
        lines = [f"【{label}】"]
        for field in fields:
            lines.append(f"  - {field['field_name']}: {field['value']}")
        return "\n".join(lines)

    def _check_section(
        self,
        ctx: PipelineContext,
        transcript_section: str,
        emr_section: str,
        section_name: str,
    ) -> Dict[str, Any]:
        """对单个SOAP章节调用LLM进行幻觉检查。

        Returns:
            成功时返回 {"unsupported_facts": [...], "total_facts_in_section": int, "supported_count": int}
            失败时返回 {"status": "llm_error|parse_error|...", "section": section_name}
        """
        section_label = self.SECTION_LABELS.get(section_name, section_name)

        try:
            prompt = ctx.prompt_manager.render(
                "consistency_check_section",
                transcript_section=transcript_section,
                emr_section=emr_section,
                section_name=section_label,
            )
            logger.debug(f"章节 {section_name} 幻觉检查提示词长度: {len(prompt)} 字符")
        except Exception as e:
            logger.error(f"章节 {section_name} 幻觉检查提示词渲染失败: {e}")
            return {"status": "prompt_render_error", "section": section_name}

        debug_interactor = DebugInteractor(ctx.llm_service)

        if ctx.debug_mode:
            try:
                response_text = debug_interactor.interact(
                    stage=f"hallucination_check_{section_name}",
                    prompt=prompt,
                )
            except Exception as e:
                logger.error(f"章节 {section_name} 幻觉检查Debug交互失败: {e}")
                return {"status": "debug_cancelled", "section": section_name}
        else:
            if not ctx.llm_service:
                logger.warning("LLM服务不可用，跳过幻觉检查")
                return {"status": "llm_unavailable", "section": section_name}

            try:
                # 使用默认LLM配置（thinking模式+自动5倍max_tokens），不手动覆盖
                response = ctx.llm_service.generate_stream_to_response(prompt)
                logger.debug(f"章节 {section_name} 幻觉检查: 使用默认LLM配置")
                ctx.llm_stats.record_from_response("hallucination_check", prompt, response)
                response_text = response.text
                parsed = parse_json_response(response_text, f"幻觉检查_{section_name}")

            except Exception as e:
                logger.error(f"章节 {section_name} 幻觉检查LLM调用失败: {e}")
                ctx.llm_stats.record_call(
                    "hallucination_check", len(prompt), 0,
                    success=False, error_message=str(e),
                )
                return {"status": "llm_error", "section": section_name}

        if not parsed:
            logger.warning(f"章节 {section_name} 幻觉检查JSON解析失败")
            logger.error(f"响应内容前500字符: {response_text[:500]}")
            return {"status": "parse_error", "section": section_name}

        return {
            "unsupported_facts": parsed.get("unsupported_facts", []),
            "total_facts_in_section": parsed.get("total_facts_in_section", 0),
            "supported_count": parsed.get("supported_count", 0),
        }

    def _merge_section_results(
        self, section_results: List[Tuple[str, Dict[str, Any]]]
    ) -> Dict[str, Any]:
        """将4次分段调用的结果合并为原格式，保持下游兼容。"""
        all_facts = []
        all_unsupported = []
        total_facts = 0
        supported_count = 0

        for section_name, section_result in section_results:
            unsupported = section_result.get("unsupported_facts", [])
            section_total = section_result.get("total_facts_in_section", 0)
            section_supported = section_result.get("supported_count", 0)

            # 构建不支持的事实条目
            for fact_item in unsupported:
                fact_entry = {
                    "fact": fact_item.get("fact", ""),
                    "section": section_name,
                    "is_supported": False,
                    "evidence_text": "",
                    "reasoning": fact_item.get("reasoning", ""),
                }
                all_facts.append(fact_entry)
                all_unsupported.append(fact_entry)

            # 构建支持的事实条目（从总数反推）
            section_unsupported_count = len(unsupported)
            section_supported_count = section_total - section_unsupported_count
            if section_supported_count > 0:
                # 为支持的事实生成占位条目，保持facts列表完整
                for _ in range(section_supported_count):
                    all_facts.append({
                        "fact": "",
                        "section": section_name,
                        "is_supported": True,
                        "evidence_text": "",
                        "reasoning": "",
                    })

            total_facts += section_total
            supported_count += section_supported

        unsupported_count = total_facts - supported_count
        support_rate = supported_count / total_facts if total_facts > 0 else 1.0

        supported_facts = [f for f in all_facts if f.get("is_supported", True)]

        return {
            "facts": all_facts,
            "unsupported_facts": all_unsupported,
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
