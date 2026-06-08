import json
import re
import time
from typing import Dict, Any, List

from ..base import PipelineContext, PipelineStage
from ..utils import parse_json_response, extract_section_fields, collect_turn_indices, build_section_transcript
from ..debug_interactor import DebugInteractor
from ....utils.logger import logger


class ClaimVerificationStage(PipelineStage):
    """后置核查阶段：对SOAP草稿进行Checklist核查、硬规则核查和确定性核查。

    幻觉检查阶段已覆盖S/O/A/P全部章节的事实支持检测，
    本阶段不再重复Claim核查，仅做幻觉检查不覆盖的核查项：
    - Checklist遗漏核查
    - 硬规则核查
    - 确定性核查

    幻觉检查的 unsupported_facts 直接转换为 unsupported_claims 供下游字段修订使用。
    """

    def stage_name(self) -> str:
        return "后置核查"

    def execute(self, ctx: PipelineContext) -> Dict[str, Any]:
        logger.info(f">>> 阶段: {self.stage_name()}")
        stage_start = time.time()

        draft_emr = ctx.emr_draft
        combined_text = ctx.combined_text

        if not draft_emr:
            logger.error("draft_emr为空，无法进行后置核查")
            ctx.verification_issues = {}
            return {"status": "skipped_empty_draft", "issues_count": 0}

        if not combined_text:
            logger.error("combined_text为空，无法进行后置核查")
            ctx.verification_issues = {}
            return {"status": "skipped_empty_transcript", "issues_count": 0}

        draft_emr_json = json.dumps(draft_emr, ensure_ascii=False, indent=2)

        unsupported_claims: List[Dict] = []
        missing_items: List[Dict] = []
        hard_rule_violations: List[Dict] = []

        # ---- 从幻觉检查结果直接构建 unsupported_claims ----
        hallucination_result = ctx.hallucination_result
        if hallucination_result and hallucination_result.get("unsupported_facts"):
            all_unsupported_facts = hallucination_result.get("unsupported_facts", [])
            section_to_abbr = {
                "subjective": "S", "objective": "O",
                "assessment": "A", "plan": "P",
            }
            for fact in all_unsupported_facts:
                field_name = fact.get("field_name", "")
                section = fact.get("section", "")
                soap_field = f"{section}.{field_name}" if field_name else section
                unsupported_claims.append({
                    "claim_text": fact.get("fact", ""),
                    "soap_section": section_to_abbr.get(section, ""),
                    "soap_field": soap_field,
                    "verdict": "unsupported",
                    "evidence_text": "",
                    "reasoning": fact.get("reasoning", "幻觉检查阶段已识别为无依据"),
                    "source": "hallucination_check",
                })
            if unsupported_claims:
                logger.info(
                    f"从幻觉检查结果转换 {len(unsupported_claims)} 条 unsupported_claims"
                )

        # ---- 步骤A: Checklist核查 ----
        logger.info("后置核查 - 步骤A: Checklist核查")
        missing_items = self._step_checklist_verification(
            ctx, combined_text, draft_emr_json
        )

        # ---- 步骤B: 硬规则核查 ----
        logger.info("后置核查 - 步骤B: 硬规则核查")
        hard_rule_violations = self._check_hard_rules(draft_emr)
        logger.info(
            f"硬规则核查完成: 发现 {len(hard_rule_violations)} 条违规"
        )

        # ---- 步骤C: 确定性核查 ----
        logger.info("后置核查 - 步骤C: 确定性核查")
        certainty_transcript = self._crop_transcript_for_sections(
            ctx, draft_emr, ["assessment"], "确定性核查"
        )
        certainty_errors = self._step_certainty_verification(
            ctx, certainty_transcript, draft_emr_json
        )
        logger.info(
            f"确定性核查完成: 发现 {len(certainty_errors)} 条确定性错误"
        )

        # ---- 汇总 ----
        issues = {
            "unsupported_claims": unsupported_claims,
            "missing_items": missing_items,
            "hard_rule_violations": hard_rule_violations,
            "certainty_errors": certainty_errors,
        }
        ctx.verification_issues = issues

        total_issues = (
            len(unsupported_claims)
            + len(missing_items)
            + len(hard_rule_violations)
            + len(certainty_errors)
        )
        stage_time = time.time() - stage_start
        logger.info(
            f"后置核查完成: 无证据={len(unsupported_claims)}, "
            f"Checklist遗漏={len(missing_items)}, "
            f"硬规则违规={len(hard_rule_violations)}, "
            f"确定性错误={len(certainty_errors)}, "
            f"总问题数={total_issues}, 耗时: {stage_time:.2f}秒"
        )

        return {
            "status": "success",
            "issues": issues,
            "issues_count": total_issues,
        }

    # ---- 步骤A: Checklist核查 ----
    def _step_checklist_verification(
        self,
        ctx: PipelineContext,
        transcript: str,
        draft_emr_json: str,
    ) -> List[Dict]:
        """调用LLM进行checklist核查，返回missing_items列表"""
        # 压缩transcript（完整转写，使用缓存）
        compressed_transcript, dict_str = ctx.get_compressed_transcript()
        if dict_str:
            logger.info(f"Checklist核查: transcript已压缩, 原文{len(transcript)}字符 -> 压缩后{len(compressed_transcript)}字符")
        else:
            logger.info(f"Checklist核查: transcript未压缩, 使用原文{len(transcript)}字符")

        try:
            prompt = ctx.prompt_manager.render(
                "checklist_verification",
                compression_dict=dict_str,
                transcript=compressed_transcript,
                draft_emr=draft_emr_json,
            )
            logger.debug(f"Checklist核查提示词长度: {len(prompt)} 字符")
        except Exception as e:
            logger.error(f"Checklist核查提示词渲染失败: {e}")
            return []

        debug_interactor = DebugInteractor(ctx.llm_service)

        if ctx.debug_mode:
            try:
                response_text = debug_interactor.interact(
                    stage="checklist_verification",
                    prompt=prompt,
                )
            except Exception as e:
                logger.error(f"Checklist核查Debug交互失败: {e}")
                return []
        else:
            if not ctx.llm_service:
                logger.warning("LLM服务不可用，跳过Checklist核查")
                return []

            try:
                # 关闭thinking模式：Checklist核查是模式匹配任务，不需要深度推理
                response = ctx.llm_service.generate_stream_to_response(prompt, thinking_enabled=False, compression_dict=dict_str)
                logger.debug("Checklist核查阶段: thinking模式已禁用，使用流式处理")
                ctx.llm_stats.record_from_response("checklist_verification", prompt, response)
                response_text = response.text
            except Exception as e:
                logger.error(f"Checklist核查LLM调用失败: {e}")
                ctx.llm_stats.record_call("checklist_verification", len(prompt), 0, success=False, error_message=str(e))
                return []

        parsed = parse_json_response(response_text, "Checklist核查")
        if not parsed:
            logger.warning("Checklist核查JSON解析失败，使用空结果")
            return []

        missing = parsed.get("missing_items", [])
        logger.info(f"Checklist核查完成: 遗漏项={len(missing)}")
        return missing

    # ---- 步骤B: 硬规则核查（纯Python实现，不调用LLM） ----
    @staticmethod
    def _check_hard_rules(draft: dict) -> List[Dict]:
        """对SOAP草稿执行确定性硬规则核查，返回violations列表。"""
        violations: List[Dict] = []

        # 提取所有文本
        all_text = ""
        for section_name in ["subjective", "objective", "assessment", "plan"]:
            section = draft.get(section_name, {})
            if not isinstance(section, dict):
                continue
            for field, value in section.items():
                if isinstance(value, dict):
                    all_text += value.get("value", "") + " "

        if not all_text.strip():
            logger.debug("硬规则核查: 无可检查文本内容")
            return violations

        # --- 检查部位矛盾 ---
        if "左侧" in all_text and "右侧" in all_text:
            body_parts = ["肺", "胸", "眼", "耳", "手", "脚", "腿", "臂", "肾"]
            for part in body_parts:
                left = f"左{part}" in all_text
                right = f"右{part}" in all_text
                if left and right:
                    violations.append({
                        "type": "laterality_conflict",
                        "description": f"可能存在部位矛盾：同时提及左{part}和右{part}",
                        "severity": "medium",
                    })

        # --- 检查否定冲突 ---
        # 在S/O section中收集被否定的症状
        negated_terms: List[str] = []
        for section_name in ["subjective", "objective"]:
            section = draft.get(section_name, {})
            if not isinstance(section, dict):
                continue
            for field, value in section.items():
                if isinstance(value, dict):
                    text = value.get("value", "")
                    neg_matches = re.findall(
                        r'(?:无|否认|未)[^\。，,;；\n]{1,10}',
                        text,
                    )
                    negated_terms.extend(neg_matches)

        if negated_terms:
            logger.debug(
                f"硬规则核查: 发现 {len(negated_terms)} 个否定表述: {negated_terms[:5]}..."
            )
            # 提取否定表述中的核心症状词
            for neg_term in negated_terms:
                core = re.sub(r'^[无否认未]+', '', neg_term).strip()
                if not core:
                    continue
                # 检查在assessment中是否有肯定表述（A中不应出现与S/O否定矛盾的症状）
                assessment_section = draft.get("assessment", {})
                if isinstance(assessment_section, dict):
                    for field, value in assessment_section.items():
                        if isinstance(value, dict):
                            a_text = value.get("value", "")
                            if core in a_text:
                                violations.append({
                                    "type": "negation_conflict",
                                    "description": (
                                        f"S/O中否定了「{core}」，"
                                        f"但Assessment中提及了相同症状"
                                    ),
                                    "severity": "high",
                                })

        return violations

    def _step_certainty_verification(
        self,
        ctx: PipelineContext,
        transcript: str,
        draft_emr_json: str,
    ) -> List[Dict]:
        """调用LLM进行确定性层级核查，检查诊断确定性是否被拔高。

        提取草稿中assessment_items的诊断声明，与对话原文对比，
        判定diagnosis_type和certainty_level是否与实际证据力度匹配。
        只检查拔高（suspected → explicit），不检查降级。
        """
        try:
            draft_dict = json.loads(draft_emr_json)
        except json.JSONDecodeError:
            logger.warning("确定性核查: 草稿JSON解析失败")
            return []

        assessment = draft_dict.get("assessment", {})
        if not assessment:
            logger.info("确定性核查: SOAP草稿中无assessment，跳过")
            return []

        assessment_items = assessment.get("assessment_items", [])
        diagnosis = assessment.get("diagnosis", {})
        if not assessment_items and not diagnosis.get("value"):
            logger.info("确定性核查: assessment中无诊断内容，跳过")
            return []

        assessment_json = json.dumps(assessment, ensure_ascii=False, indent=2)

        # 压缩transcript（裁剪后的转写）
        compressed_transcript, dict_str = ctx.compress_text(transcript)
        if dict_str:
            logger.info(f"确定性核查: transcript已压缩, 原文{len(transcript)}字符 -> 压缩后{len(compressed_transcript)}字符")
        else:
            logger.info(f"确定性核查: transcript未压缩, 使用原文{len(transcript)}字符")

        try:
            prompt = ctx.prompt_manager.render(
                "certainty_verification",
                compression_dict=dict_str,
                transcript=compressed_transcript,
                assessment_json=assessment_json,
            )
            logger.debug(f"确定性核查提示词长度: {len(prompt)} 字符")
        except Exception as e:
            logger.error(f"确定性核查提示词渲染失败: {e}")
            return []

        debug_interactor = DebugInteractor(ctx.llm_service)

        if ctx.debug_mode:
            try:
                response_text = debug_interactor.interact(
                    stage="certainty_verification",
                    prompt=prompt,
                )
            except Exception as e:
                logger.error(f"确定性核查Debug交互失败: {e}")
                return []
        else:
            if not ctx.llm_service:
                logger.warning("LLM服务不可用，跳过确定性核查")
                return []

            try:
                # 关闭thinking模式：确定性核查是模式匹配任务，不需要深度推理
                response = ctx.llm_service.generate_stream_to_response(prompt, thinking_enabled=False, compression_dict=dict_str)
                logger.debug("确定性核查阶段: thinking模式已禁用，使用流式处理")
                ctx.llm_stats.record_from_response("certainty_verification", prompt, response)
                response_text = response.text
            except Exception as e:
                logger.error(f"确定性核查LLM调用失败: {e}")
                ctx.llm_stats.record_call("certainty_verification", len(prompt), 0, success=False, error_message=str(e))
                return []

        parsed = parse_json_response(response_text, "确定性核查")
        if not parsed:
            logger.warning("确定性核查JSON解析失败，使用空结果")
            return []

        errors = parsed.get("certainty_errors", [])
        summary = parsed.get("summary", {})
        logger.info(
            f"确定性核查完成: 检查{summary.get('total_checked', 0)}条, "
            f"发现{len(errors)}个错误"
        )
        return errors

    # ---- 裁剪工具方法 ----
    @staticmethod
    def _crop_transcript_for_sections(
        ctx: "PipelineContext",
        draft_emr: dict,
        section_names: list,
        step_label: str,
    ) -> str:
        """对指定SOAP章节的字段提取source_turn_indices并裁剪转写。

        如果有字段value非空但无source_turn_indices（可疑字段），回退到完整转写。

        Args:
            ctx: Pipeline上下文
            draft_emr: SOAP草稿
            section_names: 需要裁剪的章节名列表，如 ["assessment", "plan"]
            step_label: 步骤名称（用于日志）

        Returns:
            裁剪后或完整的转写文本
        """
        all_fields = []
        for section_name in section_names:
            section = draft_emr.get(section_name, {})
            if not isinstance(section, dict):
                continue
            normal, suspect, _ = extract_section_fields(section, section_name)
            all_fields.extend(normal)
            # 任何章节有可疑字段 → 回退完整转写
            if suspect:
                logger.info(
                    f"{step_label}: 章节 {section_name} 存在可疑字段"
                    f"（value非空但无source_turn_indices），回退到完整转写"
                )
                return ctx.combined_text

        if not all_fields:
            logger.info(f"{step_label}: 指定章节无可裁剪字段，使用完整转写")
            return ctx.combined_text

        relevant_indices = collect_turn_indices(all_fields)
        if not relevant_indices:
            logger.info(f"{step_label}: 无可收集的turn indices，使用完整转写")
            return ctx.combined_text

        cropped = build_section_transcript(ctx.turns, relevant_indices, buffer=1)
        logger.info(
            f"{step_label}: 使用裁剪转写，"
            f"涉及 {len(relevant_indices)} 个对话轮次, "
            f"转写长度 {len(cropped)} 字符 (完整转写 {len(ctx.combined_text)} 字符)"
        )
        return cropped
