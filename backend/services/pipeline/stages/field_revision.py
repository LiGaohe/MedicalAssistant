import copy
import json
import time
from typing import Dict, Any, List, Optional, Set

from ..base import PipelineContext, PipelineStage
from ..utils import parse_json_response
from ..debug_interactor import DebugInteractor
from ..stages.hallucination_check import _delete_unsupported_from_emr
from ....utils.logger import logger


class FieldRevisionStage(PipelineStage):
    """字段级修订与落盘阶段：根据核查问题清单对SOAP草稿进行定点修订。

    使用补丁模式：LLM只输出需要修改的字段（补丁），而非完整SOAP JSON。
    代码将补丁应用到原始SOAP上，避免LLM重复输出未变更字段。

    处理流程：
    1. unsupported_claims二次验证：用完整转写验证疑似幻觉，确认后才删除
    2. missing_items补充：LLM补丁模式补充遗漏内容
    3. hard_rule_violations、certainty_errors修正
    4. schema确定性约束校验
    """

    # SOAP必须存在的四个section
    REQUIRED_SECTIONS = ["subjective", "objective", "assessment", "plan"]

    def stage_name(self) -> str:
        return "字段级修订与落盘"

    def execute(self, ctx: PipelineContext) -> Dict[str, Any]:
        logger.info(f">>> 阶段: {self.stage_name()}")
        stage_start = time.time()

        draft_emr = ctx.emr_draft
        issues = ctx.verification_issues or {}
        combined_text = ctx.combined_text

        if not draft_emr:
            logger.error("draft_emr为空，无法进行字段修订")
            return {"status": "skipped_empty_draft", "issues_count": 0, "revised": False}

        # 统计各类问题数量
        unsupported_count = len(issues.get("unsupported_claims", []))
        missing_count = len(issues.get("missing_items", []))
        hard_rule_count = len(issues.get("hard_rule_violations", []))
        certainty_error_count = len(issues.get("certainty_errors", []))
        total_issues_count = (
            unsupported_count
            + missing_count + hard_rule_count + certainty_error_count
        )

        revised = False
        revised_soap = copy.deepcopy(draft_emr)

        if total_issues_count == 0:
            logger.info("核查问题清单为空，跳过修订，直接执行schema校验")
        else:
            # ---- Step 1: unsupported_claims二次验证与删除 ----
            # 用完整转写验证疑似幻觉，确认后才删除
            if unsupported_count > 0:
                logger.info(
                    f"Step 1: 对 {unsupported_count} 条疑似幻觉进行二次验证"
                )
                confirmed_unsupported = self._reverify_unsupported_claims(
                    ctx, issues.get("unsupported_claims", []), combined_text
                )
                if confirmed_unsupported:
                    # 程序化删除确认的幻觉内容
                    revised_soap, delete_count = _delete_unsupported_from_emr(
                        revised_soap, confirmed_unsupported
                    )
                    if delete_count > 0:
                        revised = True
                        logger.info(
                            f"幻觉二次验证完成: 确认 {len(confirmed_unsupported)} 条幻觉，"
                            f"已删除 {delete_count} 条内容"
                        )
                    # 更新issues中的unsupported_claims为确认后的列表
                    issues["unsupported_claims"] = confirmed_unsupported
                else:
                    logger.info("幻觉二次验证完成: 所有疑似幻觉均有依据，无需删除")
                    issues["unsupported_claims"] = []

            # ---- Step 2: LLM补丁模式修订（处理非幻觉类问题）----
            non_hallucination_issues = {
                "missing_items": issues.get("missing_items", []),
                "hard_rule_violations": issues.get("hard_rule_violations", []),
                "certainty_errors": issues.get("certainty_errors", []),
            }
            non_hallucination_count = (
                missing_count + hard_rule_count + certainty_error_count
            )

            if non_hallucination_count > 0:
                logger.info(
                    f"Step 2: 非幻觉类问题: 遗漏={missing_count}, "
                    f"硬规则违规={hard_rule_count}, "
                    f"确定性错误={certainty_error_count}，"
                    f"执行LLM字段级修订（补丁模式）"
                )
                patches = self._call_llm_patch_revision(
                    ctx, revised_soap, non_hallucination_issues
                )
                if patches:
                    revised_soap = self._apply_patches(revised_soap, patches)
                    revised = True
                    logger.info(f"LLM字段级修订完成，应用了 {len(patches)} 个补丁")
                else:
                    logger.warning("LLM字段级修订未返回有效补丁，使用当前草稿进入schema校验")
            else:
                logger.info("Step 2: 无非幻觉类问题，跳过LLM补丁修订")

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
            "status": "success",
            "issues_count": total_issues_count,
            "revised": revised,
        }

    # ---- 从核查问题中提取受影响字段 ----
    @staticmethod
    def _extract_affected_fields(draft_emr: dict, issues: dict) -> str:
        """从核查问题清单中定位受影响的SOAP字段，构建精简的上下文。

        只提取与问题相关的字段内容，而非完整SOAP JSON。
        """
        affected_parts: List[str] = []

        # 1. unsupported_claims → 定位到对应section的字段
        for claim in issues.get("unsupported_claims", []):
            section_key = claim.get("soap_section", "")
            soap_field = claim.get("soap_field", "")
            claim_text = claim.get("claim_text", "")
            # 将A/P缩写映射为完整section名
            section_map = {"A": "assessment", "P": "plan", "S": "subjective", "O": "objective"}
            full_section = section_map.get(section_key, section_key)
            # soap_field 格式为 "section.field_name"，提供精确定位
            field_path = soap_field if soap_field and "." in soap_field else full_section
            affected_parts.append(f"[无证据声明] section={full_section}, field={field_path}, claim='{claim_text}'")

        # 2. missing_items → 定位到对应section
        for item in issues.get("missing_items", []):
            section = item.get("section", "")
            item_name = item.get("item_name", item.get("item", ""))
            affected_parts.append(f"[遗漏项] section={section}, item='{item_name}'")

        # 3. hard_rule_violations
        for violation in issues.get("hard_rule_violations", []):
            v_type = violation.get("type", "")
            desc = violation.get("description", "")
            affected_parts.append(f"[硬规则违规] type={v_type}, desc='{desc}'")

        # 4. certainty_errors → 定位到assessment
        for error in issues.get("certainty_errors", []):
            soap_text = error.get("soap_text", "")
            current_type = error.get("current_diagnosis_type", "")
            current_certainty = error.get("current_certainty_level", "")
            correct_type = error.get("correct_diagnosis_type", "")
            correct_certainty = error.get("correct_certainty_level", "")
            affected_parts.append(
                f"[确定性错误] text='{soap_text}', "
                f"当前: {current_type}/{current_certainty} → "
                f"应为: {correct_type}/{correct_certainty}"
            )

        # 提取涉及的section内容（精简版，只包含相关section）
        involved_sections = set()
        for part in affected_parts:
            for section in ["subjective", "objective", "assessment", "plan"]:
                if section in part.lower():
                    involved_sections.add(section)
        # 如果没有明确section，默认包含assessment和plan
        if not involved_sections:
            involved_sections = {"assessment", "plan"}

        section_contents: List[str] = []
        for section_name in sorted(involved_sections):
            section_data = draft_emr.get(section_name, {})
            if section_data:
                section_json = json.dumps(section_data, ensure_ascii=False, indent=2)
                section_contents.append(f"### {section_name}\n{section_json}")

        header = "## 受影响字段\n" + "\n".join(affected_parts)
        body = "\n\n## 相关SOAP章节内容\n" + "\n\n".join(section_contents) if section_contents else ""
        return header + body

    # ---- LLM补丁模式修订调用 ----
    def _call_llm_patch_revision(
        self,
        ctx: PipelineContext,
        draft_emr: dict,
        issues: dict,
    ) -> List[Dict]:
        """调用LLM进行补丁模式字段级修订，返回补丁列表。"""
        # 提取受影响字段
        affected_fields = self._extract_affected_fields(draft_emr, issues)

        # 压缩transcript
        compressed_transcript, dict_str = ctx.get_compressed_transcript()
        if dict_str:
            logger.info(
                f"字段级修订: transcript已压缩, "
                f"原文{len(ctx.combined_text)}字符 -> 压缩后{len(compressed_transcript)}字符"
            )
        else:
            logger.info(f"字段级修订: transcript未压缩, 使用原文{len(ctx.combined_text)}字符")

        issues_json = json.dumps(issues, ensure_ascii=False, indent=2)

        try:
            prompt = ctx.prompt_manager.render(
                "field_revision_patch",
                compression_dict=dict_str,
                affected_fields=affected_fields,
                issues_json=issues_json,
                transcript=compressed_transcript,
            )
            logger.debug(f"字段级修订（补丁模式）提示词长度: {len(prompt)} 字符")
        except Exception as e:
            logger.error(f"字段级修订提示词渲染失败: {e}")
            return []

        debug_interactor = DebugInteractor(ctx.llm_service)

        if ctx.debug_mode:
            try:
                response_text = debug_interactor.interact(
                    stage="field_revision",
                    prompt=prompt,
                )
            except Exception as e:
                logger.error(f"字段级修订Debug交互失败: {e}")
                return []
        else:
            if not ctx.llm_service:
                logger.warning("LLM服务不可用，跳过字段级修订")
                return []

            try:
                response = ctx.llm_service.generate_stream_to_response(
                    prompt,
                    thinking_enabled=False,
                    max_tokens=4096,
                    compression_dict=dict_str,
                )
                logger.debug("字段级修订阶段: thinking模式已禁用，补丁模式使用流式处理")
                ctx.llm_stats.record_from_response("field_revision", prompt, response)
                response_text = response.text
            except Exception as e:
                logger.error(f"字段级修订LLM调用失败: {e}")
                ctx.llm_stats.record_call(
                    "field_revision", len(prompt), 0,
                    success=False, error_message=str(e)
                )
                return []

        return self._parse_patches(response_text)

    # ---- 解析补丁响应 ----
    @staticmethod
    def _parse_patches(response_text: str) -> List[Dict]:
        """解析LLM返回的补丁JSON。"""
        parsed = parse_json_response(response_text, "字段级修订（补丁模式）")
        if not parsed:
            logger.warning("字段级修订补丁JSON解析失败")
            return []

        patches = parsed.get("patches", [])
        if not isinstance(patches, list):
            logger.warning(f"补丁格式错误: patches不是数组, type={type(patches)}")
            return []

        valid_patches = []
        for patch in patches:
            if not isinstance(patch, dict):
                continue
            path = patch.get("path", "")
            value = patch.get("value")
            if not path or value is None:
                logger.warning(f"跳过无效补丁: path='{path}', value={value}")
                continue
            valid_patches.append({"path": path, "value": value})

        logger.info(f"解析到 {len(valid_patches)} 个有效补丁")
        for p in valid_patches:
            logger.info(f"  补丁: {p['path']}")

        return valid_patches

    # ---- 应用补丁到SOAP ----
    @staticmethod
    def _apply_patches(soap: dict, patches: List[Dict]) -> dict:
        """将补丁列表应用到SOAP草稿上。"""
        result = copy.deepcopy(soap)
        applied_count = 0

        for patch in patches:
            path = patch["path"]
            value = patch["value"]

            # 解析路径: "section.field" 或 "section.field.subfield"
            parts = path.split(".")
            if len(parts) < 2:
                logger.warning(f"补丁路径格式无效: {path}，跳过")
                continue

            section_name = parts[0]
            field_path = parts[1:]

            # 导航到目标位置
            target = result.get(section_name)
            if not isinstance(target, dict):
                logger.warning(f"补丁目标section不存在或非dict: {section_name}，跳过")
                continue

            # 逐层导航到倒数第二层
            current = target
            for key in field_path[:-1]:
                if isinstance(current, dict) and key in current:
                    current = current[key]
                else:
                    logger.warning(f"补丁路径导航失败: {path}，在key='{key}'处中断，跳过")
                    break
            else:
                # 成功导航到倒数第二层
                final_key = field_path[-1]
                if isinstance(current, dict):
                    old_value = current.get(final_key)
                    current[final_key] = value
                    applied_count += 1
                    logger.info(
                        f"应用补丁: {path}, "
                        f"旧值类型={type(old_value).__name__}, "
                        f"新值类型={type(value).__name__}"
                    )
                else:
                    logger.warning(f"补丁目标非dict，无法设置: {path}，跳过")

        logger.info(f"成功应用 {applied_count}/{len(patches)} 个补丁")
        return result

    # ---- schema确定性约束校验 ----
    def _apply_schema_constraints(self, soap: dict) -> dict:
        """对SOAP执行确定性schema约束校验，确保必填字段和安全性约束。"""
        # 1. 确保四个section存在且为dict
        for section in self.REQUIRED_SECTIONS:
            if section not in soap or not isinstance(soap[section], dict):
                logger.warning(f"schema约束: 补充缺失section '{section}'")
                soap[section] = {}

        # 2. 高风险字段检查
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

        # 3. 否定一致性快速检查（非阻塞）
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

    # ---- 幻觉二次验证 ----
    def _reverify_unsupported_claims(
        self,
        ctx: PipelineContext,
        unsupported_claims: List[Dict],
        combined_text: str,
    ) -> List[Dict]:
        """用完整转写二次验证疑似幻觉，返回确认的幻觉列表。

        Args:
            ctx: 管线上下文
            unsupported_claims: 疑似幻觉列表（从幻觉检查阶段传递）
            combined_text: 完整对话原文

        Returns:
            确认的幻觉列表（经LLM验证后确实无依据的事实）
        """
        if not unsupported_claims or not combined_text:
            return []

        if not ctx.llm_service or ctx.debug_mode:
            logger.warning("LLM服务不可用或调试模式，跳过幻觉二次验证，保留所有疑似幻觉")
            return unsupported_claims

        # 构建待验证事实列表
        facts_text = "\n".join(
            f"{i+1}. [{claim.get('soap_section', '?')}] {claim.get('claim_text', '')}"
            for i, claim in enumerate(unsupported_claims)
        )

        # 截取对话原文（避免过长）
        transcript_for_verify = combined_text
        max_transcript_len = 8000
        if len(transcript_for_verify) > max_transcript_len:
            transcript_for_verify = transcript_for_verify[:max_transcript_len]
            logger.info(f"幻觉二次验证: 对话原文过长，截取前{max_transcript_len}字符")

        prompt = f"""## 完整对话原文
{transcript_for_verify}

## 以下事实被标记为"疑似幻觉"（在裁剪后的转写中未找到依据）
{facts_text}

请判断上述每个事实是否能在完整对话中找到依据。

**关键规则**：
- 患者的回答（包括否定回答如"没有"、"没去过"、"不疼"等）是事实的依据
- 医生的诊断判断、用药建议、检查建议等也是事实的依据
- 如果对话中能找到与事实内容匹配或语义相近的表述，则该事实有依据
- 只需判断事实是否有依据，不需要判断依据是否充分

请输出JSON格式：
{{
  "confirmed_hallucinations": [
    {{
      "index": 事实编号（对应输入列表中的序号）,
      "reasoning": "简短原因（不超过30字）"
    }}
  ]
}}

如果没有确认的幻觉（所有事实均有依据），confirmed_hallucinations为空数组。"""

        try:
            response = ctx.llm_service.generate_stream_to_response(
                prompt, thinking_enabled=False, max_tokens=2048
            )
            ctx.llm_stats.record_from_response("hallucination_reverify", prompt, response)
            response_text = response.text
            parsed = parse_json_response(response_text, "幻觉二次验证")

            if not parsed:
                logger.warning("幻觉二次验证: JSON解析失败，保留所有疑似幻觉")
                return unsupported_claims

            confirmed_indices = parsed.get("confirmed_hallucinations", [])
            if not isinstance(confirmed_indices, list):
                logger.warning(f"幻觉二次验证: confirmed_hallucinations格式错误, type={type(confirmed_indices)}")
                return unsupported_claims

            # 提取确认的幻觉
            confirmed_list = []
            restored_count = 0
            for i, claim in enumerate(unsupported_claims):
                is_confirmed = any(
                    item.get("index") == i + 1
                    for item in confirmed_indices
                    if isinstance(item, dict)
                )
                if is_confirmed:
                    confirmed_list.append(claim)
                else:
                    restored_count += 1
                    logger.info(
                        f"幻觉二次验证恢复: '{claim.get('claim_text', '')[:50]}' "
                        f"经LLM确认有对话依据，保留"
                    )

            logger.info(
                f"幻觉二次验证完成: 确认 {len(confirmed_list)} 条幻觉，"
                f"恢复 {restored_count} 条有依据的事实"
            )
            return confirmed_list

        except Exception as e:
            logger.error(f"幻觉二次验证LLM调用失败: {e}")
            ctx.llm_stats.record_call(
                "hallucination_reverify", len(prompt), 0,
                success=False, error_message=str(e),
            )
            return unsupported_claims
