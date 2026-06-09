import copy
import json
import re
import time
from typing import Dict, Any, List, Optional

from ..base import PipelineContext, PipelineStage
from ..utils import parse_json_response
from ..debug_interactor import DebugInteractor
from ....utils.logger import logger


def _clean_text_after_removal(text: str) -> str:
    """清理删除幻觉文本后产生的多余标点和空格。

    例如："患者为9岁小儿。。今晨" -> "患者为9岁小儿。今晨"
    例如："患者为9岁小儿。（具体结果未提及）。今晨" -> "患者为9岁小儿。今晨"
    """
    # 删除空括号或仅含解释性短语的括号（幻觉删除后的残留）
    text = re.sub(r'[（(]\s*(具体结果未提及|具体结果不详|未提及|不详)?\s*[）)]', '', text)
    # 合并连续的中文句号为单个
    text = re.sub(r'。+', '。', text)
    # 合并连续的中文逗号为单个
    text = re.sub(r'，+', '，', text)
    # 删除句号前的空格
    text = re.sub(r'\s+。', '。', text)
    # 删除逗号前的空格
    text = re.sub(r'\s+，', '，', text)
    # 删除句号后紧跟逗号的情况
    text = re.sub(r'。，', '，', text)
    # 删除逗号后紧跟句号的情况
    text = re.sub(r'，。', '。', text)
    # 合并多余空格
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


class FieldRevisionStage(PipelineStage):
    """字段级修订与落盘阶段：根据核查问题清单对SOAP草稿进行定点修订。

    使用补丁模式：LLM只输出需要修改的字段（补丁），而非完整SOAP JSON。
    代码将补丁应用到原始SOAP上，避免LLM重复输出未变更字段。
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
            logger.info("核查问题清单为空，跳过LLM修订，直接执行schema校验")
        else:
            logger.info(
                f"核查问题清单非空: 无证据={unsupported_count}, "
                f"遗漏={missing_count}, "
                f"硬规则违规={hard_rule_count}, 确定性错误={certainty_error_count}，"
                f"执行LLM字段级修订（补丁模式）"
            )

            patches = self._call_llm_patch_revision(ctx, draft_emr, issues)
            if patches:
                revised_soap = self._apply_patches(revised_soap, patches)
                revised = True
                logger.info(f"LLM字段级修订完成，应用了 {len(patches)} 个补丁")
            else:
                logger.warning("LLM字段级修订未返回有效补丁，使用原始草稿进入schema校验")

            # 基于unsupported_claims同步修正残留幻觉内容
            revised_soap, cleanup_count = self._cleanup_unsupported_claims(
                revised_soap, issues
            )
            if cleanup_count > 0:
                revised = True
                logger.info(f"幻觉残留清理完成，修正了 {cleanup_count} 处")

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

    # ---- 幻觉残留清理 ----
    @staticmethod
    def _cleanup_unsupported_claims(
        revised_soap: dict, issues: dict
    ) -> tuple:
        """基于unsupported_claims清理EMR中text汇总字段的残留幻觉内容。

        当幻觉检查发现某条声明不支持时，LLM补丁可能只修正了对应字段，
        但同一section的text汇总字段中可能仍残留该幻觉内容。
        此方法只在text字段中删除已确认被补丁修正的字段对应的幻觉片段。

        安全策略：
        - 只处理text汇总字段（不是value字段），因为text是其他字段的汇总
        - 只删除unsupported_claims中soap_field对应的幻觉片段
        - 只在补丁已修正了该soap_field时才清理text

        Returns:
            (revised_soap, cleanup_count): 修正后的SOAP和清理次数
        """
        result = copy.deepcopy(revised_soap)
        cleanup_count = 0

        unsupported_claims = issues.get("unsupported_claims", [])
        if not unsupported_claims:
            return result, cleanup_count

        # 按section分组unsupported_claims
        section_claims = {}
        for claim in unsupported_claims:
            soap_field = claim.get("soap_field", "")
            claim_text = claim.get("claim_text", "").strip()
            if not soap_field or not claim_text or len(claim_text) < 2:
                continue
            # 解析soap_field: "section.field"
            parts = soap_field.split(".")
            if len(parts) < 2:
                continue
            section_name = parts[0]
            field_key = parts[1]
            if section_name not in section_claims:
                section_claims[section_name] = []
            section_claims[section_name].append({
                "field_key": field_key,
                "claim_text": claim_text,
            })

        # 对每个section，检查text字段是否包含幻觉片段
        for section_name, claims in section_claims.items():
            section = result.get(section_name, {})
            if not isinstance(section, dict):
                continue

            text_value = section.get("text", "")
            if not isinstance(text_value, str) or not text_value.strip():
                continue

            modified = False
            new_text = text_value

            for claim in claims:
                field_key = claim["field_key"]
                claim_text = claim["claim_text"]

                if claim_text in new_text:
                    # 检查对应的字段是否仍包含该幻觉
                    field_data = section.get(field_key)
                    if isinstance(field_data, dict):
                        field_value = field_data.get("value", "")
                    else:
                        field_value = ""

                    # 如果对应字段的value中已不包含该幻觉，说明已被补丁修正
                    # 此时可以安全地从text中删除
                    if claim_text not in field_value:
                        new_text = new_text.replace(claim_text, "")
                        modified = True
                        cleanup_count += 1
                        logger.info(
                            f"幻觉残留清理: {section_name}.text, "
                            f"删除幻觉片段 '{claim_text[:50]}'"
                        )

            if modified:
                new_text = _clean_text_after_removal(new_text)
                result[section_name]["text"] = new_text

        if cleanup_count > 0:
            logger.info(f"幻觉残留清理: 共清理 {cleanup_count} 处残留内容")
        return result, cleanup_count

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
