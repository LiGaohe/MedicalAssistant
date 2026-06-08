"""
质量指标计算模块

包含EMR空检查、诊断匹配、质量指标计算、LLM统计计算等纯计算逻辑。
"""

import re
import logging
from typing import Dict, Any, Optional, Tuple

from scripts.run_full_benchmark.configs import (
    SOAP_SECTIONS, REQUIRED_FIELDS, CONFIG_STAGE_GROUPS
)

logger = logging.getLogger(__name__)


def normalize_text(text: str) -> str:
    """文本标准化：去除标点和空白，转小写"""
    if not text:
        return ""
    text = text.strip()
    text = re.sub(r'[，。、；：！？\s]', '', text)
    return text.lower()


def check_diagnosis_match(predicted: str, ground_truth: str) -> bool:
    """检查预测诊断与真实诊断是否匹配"""
    pred_norm = normalize_text(predicted)
    truth_norm = normalize_text(ground_truth)

    if not pred_norm or not truth_norm:
        return False

    if pred_norm == truth_norm:
        return True

    if pred_norm in truth_norm or truth_norm in pred_norm:
        return True

    common_chars = set(pred_norm) & set(truth_norm)
    if len(common_chars) >= min(len(pred_norm), len(truth_norm)) * 0.5:
        return True

    return False


def is_emr_empty(emr: Optional[Dict]) -> bool:
    """检查EMR结果是否为空"""
    if not emr or not isinstance(emr, dict):
        return True

    for section in SOAP_SECTIONS:
        sec = emr.get(section, {})
        if isinstance(sec, dict) and len(sec) > 0:
            if "text" in sec and str(sec.get("text", "")).strip():
                return False
            for field, val in sec.items():
                if field == "text":
                    continue
                if isinstance(val, dict):
                    if str(val.get("value", "")).strip():
                        return False
                elif isinstance(val, str) and val.strip():
                    return False
    return True


def compute_quality_metrics(emr: Optional[Dict], sample_diagnosis: str) -> Optional[Dict]:
    """计算EMR质量指标：结构完整率、字段缺失率、诊断一致性"""
    if not emr or not isinstance(emr, dict):
        return None

    present_sections = 0
    for section in SOAP_SECTIONS:
        sec = emr.get(section, {})
        if isinstance(sec, dict) and len(sec) > 0:
            present_sections += 1

    structure_completeness = present_sections / len(SOAP_SECTIONS)

    total_required = 0
    missing_required = 0
    for section, fields in REQUIRED_FIELDS.items():
        sec = emr.get(section, {})
        if not isinstance(sec, dict):
            continue

        if not fields:
            continue

        has_text_only = "text" in sec and len(sec) == 1
        if has_text_only:
            text_val = str(sec.get("text", "")).strip()
            for field in fields:
                total_required += 1
                if not text_val:
                    missing_required += 1
        else:
            for field in fields:
                total_required += 1
                fd = sec.get(field, {})
                val = fd.get("value", "") if isinstance(fd, dict) else ""
                if not val or not str(val).strip():
                    missing_required += 1

    field_missing_rate = missing_required / total_required if total_required > 0 else 0

    diagnosis_match = None
    if sample_diagnosis:
        assessment = emr.get("assessment", {})
        if isinstance(assessment, dict):
            diag_val = ""
            diag_field = assessment.get("diagnosis", {})
            if isinstance(diag_field, dict):
                diag_val = str(diag_field.get("value", "")).strip()
            if not diag_val:
                diag_val = str(assessment.get("text", "")).strip()

            if diag_val:
                diagnosis_match = check_diagnosis_match(diag_val, sample_diagnosis)

    return {
        "structure_completeness": round(structure_completeness, 4),
        "present_sections": present_sections,
        "total_sections": len(SOAP_SECTIONS),
        "field_missing_rate": round(field_missing_rate, 4),
        "missing_required_fields": missing_required,
        "total_required_fields": total_required,
        "diagnosis_match": diagnosis_match,
    }


def compute_llm_stats_for_config(
    config_key: str,
    llm_stats: Dict[str, Any]
) -> Tuple[int, int, int, float]:
    """
    根据配置和LLM统计stage_breakdown计算配置对应的LLM调用次数、字符数和实际延迟

    每个配置包含的阶段由 CONFIG_STAGE_GROUPS 定义，从对应路径的 llm_stats 中提取。

    Args:
        config_key: 配置键名
        llm_stats: 对应路径的LLM统计（llm_stats_full/llm_stats_no_term_norm/llm_stats_no_hallucination）

    Returns:
        Tuple[int, int, int, float]: (llm_call_count, char_count, token_count, actual_latency)
    """
    logger.info(f"[DEBUG] compute_llm_stats_for_config开始 - config_key={config_key}")
    logger.info(f"[DEBUG]   - llm_stats存在: {llm_stats is not None}")
    logger.info(f"[DEBUG]   - llm_stats keys: {list(llm_stats.keys()) if llm_stats else 'N/A'}")

    if not llm_stats:
        logger.info(f"[DEBUG] 返回(0,0,0,0.0) - 原因: llm_stats为空")
        return 0, 0, 0, 0.0

    stage_breakdown = llm_stats.get("stage_breakdown", {})
    stage_group = CONFIG_STAGE_GROUPS.get(config_key)

    logger.info(f"[DEBUG]   - stage_breakdown keys: {list(stage_breakdown.keys()) if stage_breakdown else 'N/A'}")
    logger.info(f"[DEBUG]   - stage_group={stage_group}")

    if not stage_group:
        logger.warning(f"[DEBUG] config_key={config_key} 没有定义stage_group，返回(0,0,0,0.0)")
        return 0, 0, 0, 0.0

    llm_call_count = 0
    char_count = 0
    token_count = 0
    actual_latency = 0.0

    logger.info(f"[DEBUG] 按stage_group计算 - config_key={config_key}, stages={stage_group}")

    for stage in stage_group:
        stage_stats = stage_breakdown.get(stage, {})
        stage_call_count = stage_stats.get("call_count") or 0
        stage_char_count = stage_stats.get("total_chars") or 0
        stage_token_count = stage_stats.get("total_tokens") or 0
        stage_latency = stage_stats.get("total_latency") or 0.0

        logger.info(f"[DEBUG]   - stage={stage}: calls={stage_call_count}, chars={stage_char_count}, tokens={stage_token_count}, latency={stage_latency}")

        llm_call_count += stage_call_count
        char_count += stage_char_count
        token_count += stage_token_count
        actual_latency += stage_latency

    logger.info(f"[DEBUG] compute_llm_stats_for_config完成 - config_key={config_key}")
    logger.info(f"[DEBUG]   - 结果: calls={llm_call_count}, chars={char_count}, tokens={token_count}, latency={actual_latency}")

    return llm_call_count, char_count, token_count, actual_latency


def compute_diagnosis_match_from_consistency(consistency_result: Optional[Dict]) -> Optional[bool]:
    """从一致性评估结果中提取诊断匹配"""
    if not consistency_result or "facts" not in consistency_result:
        return None

    facts = consistency_result.get("facts", [])
    assessment_facts = [f for f in facts if f.get("section") == "assessment"]

    if not assessment_facts:
        return None

    all_supported = all(f.get("is_supported", False) for f in assessment_facts)
    return all_supported
