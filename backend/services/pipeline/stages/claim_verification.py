import json
import re
import time
from typing import Dict, Any, List

from ..base import PipelineContext, PipelineStage
from ..utils import parse_json_response
from ..debug_interactor import DebugInteractor
from ....utils.logger import logger


class ClaimVerificationStage(PipelineStage):
    """后置核查阶段：对SOAP草稿进行Claim核查、Checklist核查和硬规则核查。"""

    def stage_name(self) -> str:
        return "后置核查"

    def execute(self, ctx: PipelineContext) -> Dict[str, Any]:
        logger.info(f">>> 阶段: {self.stage_name()}")
        stage_start = time.time()

        draft_emr = ctx.emr_draft
        combined_text = ctx.combined_text

        draft_emr_json = json.dumps(draft_emr, ensure_ascii=False, indent=2)

        unsupported_claims: List[Dict] = []
        not_addressed_claims: List[Dict] = []
        missing_items: List[Dict] = []
        hard_rule_violations: List[Dict] = []

        # ---- 步骤A: Claim核查 ----
        logger.info("后置核查 - 步骤A: Claim核查")
        unsupported_claims, not_addressed_claims = self._step_claim_verification(
            ctx, combined_text, draft_emr_json
        )

        # ---- 步骤B: Checklist核查 ----
        logger.info("后置核查 - 步骤B: Checklist核查")
        missing_items = self._step_checklist_verification(
            ctx, combined_text, draft_emr_json
        )

        # ---- 步骤C: 硬规则核查 ----
        logger.info("后置核查 - 步骤C: 硬规则核查")
        hard_rule_violations = self._check_hard_rules(draft_emr)
        logger.info(
            f"硬规则核查完成: 发现 {len(hard_rule_violations)} 条违规"
        )

        # ---- 步骤D: 确定性核查 ----
        logger.info("后置核查 - 步骤D: 确定性核查")
        certainty_errors = self._step_certainty_verification(
            ctx, combined_text, draft_emr_json
        )
        logger.info(
            f"确定性核查完成: 发现 {len(certainty_errors)} 条确定性错误"
        )

        # ---- 汇总 ----
        issues = {
            "unsupported_claims": unsupported_claims,
            "not_addressed_claims": not_addressed_claims,
            "missing_items": missing_items,
            "hard_rule_violations": hard_rule_violations,
            "certainty_errors": certainty_errors,
        }
        ctx.verification_issues = issues

        total_issues = (
            len(unsupported_claims)
            + len(not_addressed_claims)
            + len(missing_items)
            + len(hard_rule_violations)
            + len(certainty_errors)
        )
        stage_time = time.time() - stage_start
        logger.info(
            f"后置核查完成: Claim核查(无证据={len(unsupported_claims)}, "
            f"未处理={len(not_addressed_claims)}), "
            f"Checklist遗漏={len(missing_items)}, "
            f"硬规则违规={len(hard_rule_violations)}, "
            f"确定性错误={len(certainty_errors)}, "
            f"总问题数={total_issues}, 耗时: {stage_time:.2f}秒"
        )

        return {
            "issues": issues,
            "issues_count": total_issues,
        }

    # ---- 步骤A: Claim核查 ----
    def _step_claim_verification(
        self,
        ctx: PipelineContext,
        transcript: str,
        draft_emr_json: str,
    ) -> tuple:
        """调用LLM进行逐claim核查，返回 (unsupported_claims, not_addressed_claims)"""
        try:
            prompt = ctx.prompt_manager.render(
                "claim_verification",
                transcript=transcript,
                draft_emr=draft_emr_json,
            )
            logger.debug(f"Claim核查提示词长度: {len(prompt)} 字符")
        except Exception as e:
            logger.error(f"Claim核查提示词渲染失败: {e}")
            return [], []

        debug_interactor = DebugInteractor(ctx.llm_service)

        if ctx.debug_mode:
            try:
                response_text = debug_interactor.interact(
                    stage="claim_verification",
                    prompt=prompt,
                )
            except Exception as e:
                logger.error(f"Claim核查Debug交互失败: {e}")
                return [], []
        else:
            if not ctx.llm_service:
                logger.warning("LLM服务不可用，跳过Claim核查")
                return [], []

            try:
                response = ctx.llm_service.generate(prompt)
                logger.debug("Claim核查阶段: thinking模式已启用（默认）")
                response_text = response.text
            except Exception as e:
                logger.error(f"Claim核查LLM调用失败: {e}")
                return [], []

        parsed = parse_json_response(response_text, "Claim核查")
        if not parsed:
            logger.warning("Claim核查JSON解析失败，使用空结果")
            return [], []

        unsupported = parsed.get("unsupported_claims", [])
        not_addressed = parsed.get("not_addressed_claims", [])
        logger.info(
            f"Claim核查完成: 无证据声明={len(unsupported)}, "
            f"未处理声明={len(not_addressed)}"
        )
        return unsupported, not_addressed

    # ---- 步骤B: Checklist核查 ----
    def _step_checklist_verification(
        self,
        ctx: PipelineContext,
        transcript: str,
        draft_emr_json: str,
    ) -> List[Dict]:
        """调用LLM进行checklist核查，返回missing_items列表"""
        try:
            prompt = ctx.prompt_manager.render(
                "checklist_verification",
                transcript=transcript,
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
                response = ctx.llm_service.generate(prompt)
                logger.debug("Checklist核查阶段: thinking模式已启用（默认）")
                response_text = response.text
            except Exception as e:
                logger.error(f"Checklist核查LLM调用失败: {e}")
                return []

        parsed = parse_json_response(response_text, "Checklist核查")
        if not parsed:
            logger.warning("Checklist核查JSON解析失败，使用空结果")
            return []

        missing = parsed.get("missing_items", [])
        logger.info(f"Checklist核查完成: 遗漏项={len(missing)}")
        return missing

    # ---- 步骤C: 硬规则核查（纯Python实现，不调用LLM） ----
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

        try:
            prompt = ctx.prompt_manager.render(
                "certainty_verification",
                transcript=transcript,
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
                response = ctx.llm_service.generate(prompt)
                logger.debug("确定性核查阶段: thinking模式已启用（默认）")
                response_text = response.text
            except Exception as e:
                logger.error(f"确定性核查LLM调用失败: {e}")
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
