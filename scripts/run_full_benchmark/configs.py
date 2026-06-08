"""
实验配置常量

包含所有实验/消融配置、阶段分组、LLM统计源映射等常量定义。
"""

# 实验配置：4种管线变体
EXPERIMENT_CONFIGS = {
    "end_to_end": {
        "name": "端到端基线", "code": "A",
        "skip_cleaning": True, "skip_hallucination_check": True,
        "stop_after_draft": True, "skip_verification": False,
        "skip_term_norm": True, "skip_field_revision": True
    },
    "simplified": {
        "name": "简化管线", "code": "B",
        "skip_cleaning": True, "skip_hallucination_check": True,
        "stop_after_draft": False, "skip_verification": True,
        "skip_term_norm": False, "skip_field_revision": True
    },
    "standard": {
        "name": "标准管线", "code": "C",
        "skip_cleaning": False, "skip_hallucination_check": True,
        "stop_after_draft": False, "skip_verification": False,
        "skip_term_norm": False, "skip_field_revision": False
    },
    "full": {
        "name": "完整管线", "code": "D",
        "skip_cleaning": False, "skip_hallucination_check": False,
        "stop_after_draft": False, "skip_verification": False,
        "skip_term_norm": False, "skip_field_revision": False
    }
}

# 消融配置
ABLATION_CONFIGS = {
    "full":               {"name": "完整管线（六阶段）",   "skip_cleaning": False, "stop_after_draft": False, "skip_term_norm": False, "skip_hallucination_check": False, "skip_verification": False, "skip_field_revision": False},
    "no_term_norm":       {"name": "-术语规范化",         "skip_cleaning": False, "stop_after_draft": False, "skip_term_norm": True,  "skip_hallucination_check": False, "skip_verification": False, "skip_field_revision": False},
    "no_hallucination":   {"name": "-幻觉检查",           "skip_cleaning": False, "stop_after_draft": False, "skip_term_norm": False, "skip_hallucination_check": True,  "skip_verification": False, "skip_field_revision": False},
    "no_verification":    {"name": "-后置核查与字段修订",  "skip_cleaning": False, "stop_after_draft": False, "skip_term_norm": False, "skip_hallucination_check": False, "skip_verification": True,  "skip_field_revision": False}
}

# 每个配置包含的LLM调用阶段
# 阶段名称对应各Stage中record_call使用的名称
# 有LLM调用的阶段：turn_cleaning, draft_generation_free_text, draft_generation_json,
#   soap_structuring, hallucination_check, claim_verification, checklist_verification,
#   certainty_verification, field_revision
# 注意：term_norm无LLM调用，不出现在此列表中
CONFIG_STAGE_GROUPS = {
    "end_to_end": [
        # 端到端：仅草稿生成
        "draft_generation_free_text",
        "draft_generation_json"
    ],
    "simplified": [
        # 简化管线：skip_cleaning=True, skip_hallucination_check=True, skip_verification=True
        # 实际LLM调用：draft_generation → soap_structuring
        "draft_generation_free_text",
        "draft_generation_json",
        "soap_structuring"
    ],
    "standard": [
        # 标准管线：skip_hallucination_check=True，不包含hallucination_check
        "turn_cleaning",
        "draft_generation_free_text",
        "draft_generation_json",
        "soap_structuring",
        "term_norm",
        "claim_verification",
        "checklist_verification",
        "certainty_verification",
        "field_revision"
    ],
    "no_verification": [
        # 消融：跳过后置核查与字段修订，不包含claim/checklist/certainty_verification和field_revision
        "turn_cleaning",
        "draft_generation_free_text",
        "draft_generation_json",
        "soap_structuring",
        "term_norm",
        "hallucination_check"
    ],
    "full": [
        # 完整管线：全部阶段（包含term_norm）
        "turn_cleaning",
        "draft_generation_free_text",
        "draft_generation_json",
        "soap_structuring",
        "term_norm",
        "hallucination_check",
        "claim_verification",
        "checklist_verification",
        "certainty_verification",
        "field_revision"
    ],
    "no_hallucination": [
        # 消融：跳过幻觉检查，与standard相同（不含hallucination_check）
        "turn_cleaning",
        "draft_generation_free_text",
        "draft_generation_json",
        "soap_structuring",
        "term_norm",
        "claim_verification",
        "checklist_verification",
        "certainty_verification",
        "field_revision"
    ],
    "no_term_norm": [
        # 消融：跳过术语规范化（不含term_norm），其余与full相同
        "turn_cleaning",
        "draft_generation_free_text",
        "draft_generation_json",
        "soap_structuring",
        "hallucination_check",
        "claim_verification",
        "checklist_verification",
        "certainty_verification",
        "field_revision"
    ]
}

# 配置到LLM统计源的映射
# 每个配置使用对应fork路径的LLM统计，而不是合并后的统计
# - llm_stats_full: 路径A（阶段1-3 + 路径A阶段4-6，完整管线）
# - llm_stats_no_term_norm: 路径B（阶段1-3 + 路径B阶段4-6，skip_term_norm）
# - llm_stats_no_hallucination: 路径C（阶段1-3 + 路径C阶段4-6，skip_hallucination_check）
CONFIG_LLM_STATS_SOURCE = {
    "end_to_end": "llm_stats_full",            # 路径A的子集（阶段1-2）
    "no_verification": "llm_stats_full",        # 路径A的子集（阶段1-5）
    "full": "llm_stats_full",                   # 路径A完整
    "standard": "llm_stats_no_hallucination",   # 路径C完整（skip_hallucination_check）
    "no_hallucination": "llm_stats_no_hallucination",  # 路径C完整
    "no_term_norm": "llm_stats_no_term_norm",   # 路径B完整
    "simplified": None  # 独立管线，使用自己的统计
}

# SOAP节和必填字段定义
SOAP_SECTIONS = ["subjective", "objective", "assessment", "plan"]
REQUIRED_FIELDS = {
    "subjective": ["chief_complaint", "history_present_illness"],
    "objective": [],
    "assessment": ["diagnosis"],
    "plan": ["treatment"],
}

# 缺失配置与中间结果字段的映射
CONFIG_EMR_KEY_MAPPING = {
    "end_to_end": "emr_raw_draft",
    "no_verification": "emr_pre_revision",
    "full": "emr_result",
    "standard": "emr_no_hallucination",
    "no_hallucination": "emr_no_hallucination",
    "no_term_norm": "emr_no_term_norm",
}

# 多变量Pipeline中配置到输出类型的映射
CONFIG_OUTPUT_MAPPING = {
    "end_to_end": {"type": "experiment", "emr_key": "emr_raw_draft"},
    "no_verification": {"type": "ablation", "emr_key": "emr_pre_revision"},
    "full": {"type": "both", "emr_key": "emr_result"},
    "standard": {"type": "experiment", "emr_key": "emr_no_hallucination"},
    "no_hallucination": {"type": "ablation", "emr_key": "emr_no_hallucination"},
    "no_term_norm": {"type": "ablation", "emr_key": "emr_no_term_norm"},
    "simplified": {"type": "experiment", "emr_key": None}
}

# 评估去重组：相同EMR的配置只评估一次，结果复用
EVAL_DEDUP_GROUPS = {
    "standard": "standard",       # 首次评估的配置
    "no_hallucination": "standard" # 复用 standard 的评估结果
}

# 多变量Pipeline输出的配置顺序
MULTI_VARIANT_CONFIG_ORDER = [
    "end_to_end", "no_verification", "full",
    "standard", "no_hallucination", "no_term_norm", "simplified"
]
