import json
import time
from typing import Dict, Any, List

from ..base import PipelineContext, PipelineStage
from ..utils import parse_json_response
from ..debug_interactor import DebugInteractor
from ....utils.logger import logger


class FieldRevisionStage(PipelineStage):
    """字段级修订与落盘阶段：根据核查问题清单对SOAP草稿进行定点修订。"""

    # SOAP必须存在的四个section
    REQUIRED_SECTIONS = ["subjective", "objective", "assessment", "plan"]

    def stage_name(self) -> str:
        return "字段级修订与落盘"

    def execute(self, ctx: PipelineContext) -> Dict[str, Any]:
        logger.info(f">>> 阶段: {self.stage_name()}")
        stage_start = time.time()

        draft_emr = ctx.emr_draft
        issues = ctx.verification_issues or {}

        # 统计各类问题数量
        unsupported_count = len(issues.get("unsupported_claims", []))
        not_addressed_count = len(issues.get("not_addressed_claims", []))
        missing_count = len(issues.get("missing_items", []))
        hard_rule_count = len(issues.get("hard_rule_violations", []))
        total_issues_count = (
            unsupported_count + not_addressed_count + missing_count + hard_rule_count
        )

        revised = False
        revised_soap = dict(draft_emr)  # shallow copy，先保留原始

        if total_issues_count == 0:
            # 没有核查问题，跳过LLM修订，直接进入schema校验
            logger.info("核查问题清单为空，跳过LLM修订，直接执行schema校验")
        else:
            logger.info(
                f"核查问题清单非空: 无证据={unsupported_count}, "
                f"未处理={not_addressed_count}, 遗漏={missing_count}, "
                f"硬规则违规={hard_rule_count}，执行LLM字段级修订"
            )

            draft_emr_json = json.dumps(draft_emr, ensure_ascii=False, indent=2)
            issues_json = json.dumps(issues, ensure_ascii=False, indent=2)

            llm_revised = self._call_llm_revision(ctx, draft_emr_json, issues_json)
            if llm_revised is not None:
                # 部分修订处理：缺失字段从原始draft回填
                revised_soap = self._backfill_missing_fields(llm_revised, draft_emr)
                # 确保evidence_traces不丢失
                revised_soap = self._preserve_evidence_traces(revised_soap, draft_emr)
                revised = True
                logger.info("LLM字段级修订完成")
            else:
                logger.warning("LLM字段级修订失败，使用原始草稿进入schema校验")
                revised_soap = dict(draft_emr)

        # ---- schema确定性约束校验 ----
        revised_soap = self._apply_schema_constraints(revised_soap)

        # 写入ctx
        ctx.emr_draft = revised_soap

        stage_time = time.time() - stage_start
        logger.info(
            f"字段级修订与落盘完成: 问题数={total_issues_count}, "
            f"修订={'是' if revised else '否'}, 耗时: {stage_time:.2f}秒"
        )

        return {
            "issues_count": total_issues_count,
            "revised": revised,
        }

    # ---- LLM修订调用 ----
    def _call_llm_revision(
        self,
        ctx: PipelineContext,
        draft_emr_json: str,
        issues_json: str,
    ) -> dict | None:
        """调用LLM进行字段级修订，返回修订后的SOAP dict或None（失败时）。"""
        try:
            prompt = ctx.prompt_manager.render(
                "field_revision",
                draft_emr=draft_emr_json,
                issues_json=issues_json,
                transcript=ctx.combined_text,
            )
            logger.debug(f"字段级修订提示词长度: {len(prompt)} 字符")
        except Exception as e:
            logger.error(f"字段级修订提示词渲染失败: {e}")
            return None

        debug_interactor = DebugInteractor(ctx.llm_service)

        if ctx.debug_mode:
            try:
                response_text = debug_interactor.interact(
                    stage="field_revision",
                    prompt=prompt,
                )
            except Exception as e:
                logger.error(f"字段级修订Debug交互失败: {e}")
                return None
        else:
            if not ctx.llm_service:
                logger.warning("LLM服务不可用，跳过字段级修订")
                return None

            try:
                response = ctx.llm_service.generate(prompt)
                logger.debug("字段级修订阶段: thinking模式已启用（默认）")
                response_text = response.text
            except Exception as e:
                logger.error(f"字段级修订LLM调用失败: {e}")
                return None

        parsed = parse_json_response(response_text, "字段级修订")
        if not parsed:
            logger.warning("字段级修订JSON解析失败，使用原始草稿")
            return None

        logger.debug(f"字段级修订LLM返回keys: {list(parsed.keys())}")
        return parsed

    # ---- 部分修订处理：缺失字段回填 ----
    @staticmethod
    def _backfill_missing_fields(revised: dict, original: dict) -> dict:
        """如果LLM修订后的SOAP中某个field丢失，从原始draft回填。"""
        result = dict(revised)
        # 确保四个section都存在
        for section in ["subjective", "objective", "assessment", "plan"]:
            if section not in result or not result[section]:
                logger.warning(
                    f"修订后SOAP缺少section '{section}'，从原始草稿回填"
                )
                result[section] = original.get(section, {})
        return result

    # ---- 确保evidence_traces不丢失 ----
    @staticmethod
    def _preserve_evidence_traces(revised: dict, original: dict) -> dict:
        """检查修订后每个field是否仍有evidence_traces，没有则从原draft复制。"""
        sections = ["subjective", "objective", "assessment", "plan"]
        preserved_count = 0
        for section_name in sections:
            revised_section = revised.get(section_name, {})
            original_section = original.get(section_name, {})
            if not isinstance(revised_section, dict) or not isinstance(original_section, dict):
                continue
            for field_name, revised_value in revised_section.items():
                if not isinstance(revised_value, dict):
                    continue
                # 检查修订后是否有evidence_traces
                if not revised_value.get("evidence_traces"):
                    original_field = original_section.get(field_name)
                    if isinstance(original_field, dict) and original_field.get("evidence_traces"):
                        revised_value["evidence_traces"] = original_field["evidence_traces"]
                        preserved_count += 1
                        logger.debug(
                            f"从原始草稿恢复evidence_traces: "
                            f"{section_name}.{field_name}, "
                            f"traces数={len(original_field['evidence_traces'])}"
                        )
        if preserved_count > 0:
            logger.info(f"共恢复 {preserved_count} 个字段的evidence_traces")
        return revised

    # ---- schema确定性约束校验 ----
    def _apply_schema_constraints(self, soap: dict) -> dict:
        """对SOAP执行确定性schema约束校验，确保必填字段和安全性约束。"""
        # 1. 确保四个section存在且为dict
        for section in self.REQUIRED_SECTIONS:
            if section not in soap or not isinstance(soap[section], dict):
                logger.warning(f"schema约束: 补充缺失section '{section}'")
                soap[section] = {}

        # 2. 高风险字段检查
        # assessment.diagnosis.value 为空时设为 "unknown"
        assessment = soap.get("assessment", {})
        if isinstance(assessment, dict):
            diagnosis = assessment.get("diagnosis")
            if isinstance(diagnosis, dict):
                if not diagnosis.get("value"):
                    logger.warning("schema约束: assessment.diagnosis.value 为空，设为 'unknown'")
                    diagnosis["value"] = "unknown"
            else:
                logger.warning("schema约束: assessment.diagnosis 为空，初始化占位")
                soap["assessment"]["diagnosis"] = {"value": "unknown", "evidence_traces": []}

        # plan.treatment.value 为空时设为 "unknown"
        plan = soap.get("plan", {})
        if isinstance(plan, dict):
            treatment = plan.get("treatment")
            if isinstance(treatment, dict):
                if not treatment.get("value"):
                    logger.warning("schema约束: plan.treatment.value 为空，设为 'unknown'")
                    treatment["value"] = "unknown"
            else:
                logger.warning("schema约束: plan.treatment 为空，初始化占位")
                soap["plan"]["treatment"] = {"value": "unknown", "evidence_traces": []}

        # 3. 否定一致性快速检查
        # 如果S/O中明确否认的症状出现在A中作为诊断依据，记录日志
        # 此检查为非阻塞，不修改数据
        for section_name in ["subjective", "objective"]:
            section = soap.get(section_name, {})
            if not isinstance(section, dict):
                continue
            for field, value in section.items():
                if isinstance(value, dict):
                    text = value.get("value", "")
                    if "否认" in text or "无" in text or "未及" in text:
                        logger.debug(
                            f"schema约束: {section_name}.{field} 含否定表述，"
                            f"请人工确认与Assessment一致性"
                        )
                        break

        return soap
