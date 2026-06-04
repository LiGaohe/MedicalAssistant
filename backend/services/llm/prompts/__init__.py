"""提示词模块 - 按阶段拆分的提示词模板管理

子模块：
- template: PromptTemplate基类
- preprocessing: 对话预处理模板（turn_cleaning, evidence_selection, item_extraction）
- soap_generation: SOAP病历生成模板（direct_soap, free_soap, soap_structuring等）
- quality_check: 质量核查模板（claim_verification, checklist_verification, field_revision等）
- evaluation: 评估模板（consistency_check, completeness_check, safety_risk_check等）
- terminology: 术语处理模板（term_standardization, extract_medical_terms）
- deprecated: 已废弃的六阶段流水线模板
- manager: PromptManager管理器
"""
from .template import PromptTemplate
from .manager import PromptManager

__all__ = ["PromptTemplate", "PromptManager"]
