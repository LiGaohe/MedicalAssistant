"""已废弃的六阶段流水线提示词模板（保留兼容性）"""
from .template import PromptTemplate


def get_deprecated_templates_zh() -> dict:
    """获取已废弃的中文模板"""
    templates = {}

    templates["fact_extraction"] = PromptTemplate(
        template="""你是一个医疗临床事实抽取专家。从以下医患对话中抽取原子级临床事实。

## 新增对话轮次（JSON）
$new_turns_json

## 已有事实摘要（用于去重和合并）
$existing_facts_summary

## 抽取规则
每条事实是一个不可再分的独立临床陈述，包含以下字段：

- **section_candidate**: S（主观数据）/ O（客观数据）/ A（评估/诊断）/ P（计划）
- **subsection**: 该事实对应的细粒度EMR字段。取值约束：
  - section_candidate=S 时：chief_complaint（主诉）/ history_present_illness（现病史）/ past_history（既往史）/ denied_symptoms（否认症状）
  - section_candidate=O 时：physical_examination（体格检查）/ auxiliary_examination（辅助检查）
  - section_candidate=A 时：可留空（诊断事实自动归入diagnosis）
  - section_candidate=P 时：可留空（计划事实由下游plan_items细分）
  - 多条事实可能对应同一subsection（如多条现病史事实），应分别抽取
- **concept_type**: symptom / disease / test / drug / plan / other
- **mention**: 对话中的原始口语表述文本
- **polarity**: present（肯定）/ absent（否认）/ possible（可能）/ planned（计划）/ recommended（建议）
- **temporality**: current / past / unknown
- **certainty**: explicit（医生明确陈述）/ supported（有充分证据）/ weak（模糊表述）
- **speaker**: patient（患者陈述）/ doctor（医生判断）
- **evidence_turn_ids**: 支撑该事实的turn_id列表
- **evidence_text**: 与evidence_turn_ids对应的原文片段列表（仅保留短片段，不超过20字）

## 增量抽取规则
1. 只抽取新增对话中的事实，不要重复抽取已有事实
2. 如果新对话中的事实与已有事实相同，追加evidence_turn_ids和evidence_text
3. 在输出中标记operation字段：
   - "new": 新事实
   - "append": 追加到已有事实（需提供matched_fact_id）

## 约束
- 严禁编造事实
- evidence_text只保留短片段，不超过20字
- 同一事实在多轮提及则合并，合并evidence_turn_ids和evidence_text

## 输出格式
{
  "facts": [{
    "operation": "new或append",
    "matched_fact_id": "如果operation=append，填写已有事实的fact_id",
    "section_candidate": "S",
    "subsection": "chief_complaint",
    "concept_type": "symptom",
    "mention": "原文",
    "polarity": "present",
    "temporality": "current",
    "certainty": "supported",
    "speaker": "patient",
    "evidence_turn_ids": [0],
    "evidence_text": ["短片段"]
  }]
}""",
        required_vars=["new_turns_json", "existing_facts_summary"]
    )

    templates["fact_consolidation"] = PromptTemplate(
        template="""对以下事实表进行快速收束处理。**仅合并重复，标记冲突，不做复杂补判。**

## 原始事实表
$facts_json

## 收束任务

### 1. 重复事实合并
检查语义相同但表述不同的事实，合并为一条：
- 合并evidence_turn_ids
- 选择最规范的mention作为最终表述

### 2. 冲突事实标记
检查矛盾事实（如同一症状既肯定又否定），标记为需人工复核：
- 标记conflict_type：polarity_conflict（极性冲突）/ temporality_conflict（时序冲突）

## 输出格式

```json
{
  "merged_facts": [{
    "fact_id": "保留的fact_id",
    "merged_from": ["被合并的fact_id列表"],
    "mention": "最终表述",
    "evidence_turn_ids": [合并后的turn_id列表]
  }],
  "conflict_facts": [{
    "fact_id": "冲突事实ID",
    "conflict_with": ["冲突的fact_id列表"],
    "conflict_type": "冲突类型",
    "needs_review": true
  }],
  "final_fact_count": 最终事实数量
}
```

**重要**：
- 不做certainty/temporality补判，保留原值
- 仅处理明确的重复和冲突
- 不确定则保留原状""",
        required_vars=["facts_json"]
    )

    templates["soap_verification"] = PromptTemplate(
        template="""对以下SOAP病历草稿进行快速核查。**先输出问题清单，再按需修订。**

## 病历草稿
$draft_emr

## 事实表
$fact_table

## 角色映射
$role_mapping

## 核查任务（最多5个问题）

检查以下4类问题，每类最多标记1个最严重的问题：

1. **无证据声明**：病历中无事实支撑的陈述
2. **关键遗漏**：高重要性事实(certainty=explicit, polarity=present)未体现
3. **内部冲突**：病历内部矛盾（年龄/部位/时间/否定词）
4. **确定性错误**：疑似诊断被表述为明确诊断

## 输出格式

```json
{
  "issue_count": 问题数量(0-5),
  "issues": {
    "unsupported_claims": [{"claim_text": "", "soap_location": ""}],
    "missing_critical_facts": [{"fact_id": "", "fact_content": ""}],
    "internal_conflicts": [{"conflict_type": "", "description": ""}],
    "certainty_errors": [{"soap_text": "", "correct_certainty": ""}]
  },
  "soap_final": {"subjective": {...}, "objective": {...}, "assessment": {...}, "plan": {...}}
}
```

**重要**：
- 若issue_count=0，soap_final直接使用原草稿，无需修订
- 若有问题，仅修订有问题的字段，其他字段保持不变
- 禁止重写整份SOAP，仅做最小化修订""",
        required_vars=["draft_emr", "fact_table", "role_mapping"]
    )

    templates["emr_generation_so"] = PromptTemplate(
        template="""根据以下事实表生成病历的主观数据(S)和客观数据(O)部分，不可生成诊断和计划。

## 事实表
$facts_json

## 对话摘要
$dialogue_summary

## 任务
### 主观数据(S) — 仅患者角度
1. 主诉(chief_complaint)：主要症状、持续时间、就诊原因
2. 现病史(history_present_illness)：症状发展过程、伴随症状、诊疗经过
3. 否认症状(denied_symptoms)：患者明确否认的相关症状
4. 相关既往史(past_history)：相关既往疾病史、手术史、过敏史

### 客观数据(O) — 仅医方完成的检查和量化结果
1. 体格检查(physical_examination)：检查项目及量化结果
2. 辅助检查(auxiliary_examination)：已完成的实验室/影像学检查及量化结果

## 规则
- 禁止生成任何诊断结论或计划内容
- 每句话必须能对应事实表中至少一条fact_id
- 优先使用normalized_term，若无则使用mention
- 无证据则留空

## 输出格式
{
  "subjective": {
    "text": "主诉：...",
    "chief_complaint": {"value": "...", "evidence_traces": []},
    "history_present_illness": {"value": "...", "evidence_traces": []},
    "denied_symptoms": {"value": "...", "evidence_traces": []},
    "past_history": {"value": "...", "evidence_traces": []}
  },
  "objective": {
    "text": "体格检查：...",
    "physical_examination": {"value": "...", "evidence_traces": []},
    "auxiliary_examination": {"value": "...", "evidence_traces": []}
  },
  "used_fact_ids": ["fact_id_1", "fact_id_2"]
}""",
        required_vars=["facts_json", "dialogue_summary"]
    )

    templates["emr_generation_assessment"] = PromptTemplate(
        template="""根据已生成的S/O文本和事实表，按三层诊断策略生成评估(A)部分。

## 主观数据(S)
$subjective_text

## 客观数据(O)
$objective_text

## 事实表
$facts_json

## 三层诊断策略
1. **明确诊断(explicit_diagnosis)**：certainty=explicit，concept_type=disease，speaker=doctor → 直接写明疾病名称
2. **倾向性诊断(suspected_diagnosis)**：仅有supported级别证据，或医生有倾向未确诊 → 使用"考虑XXX""XXX待排"等措辞
3. **症状性评估(symptom_based_assessment)**：仅有症状无诊断 → 只描述症状，禁止发明疾病名称

### assessment_items
每项含：text, certainty_level(high/medium/low), supporting_fact_ids, diagnosis_type(explicit_diagnosis/suspected_diagnosis/symptom_based_assessment)

## 约束
- 严禁编造诊断结论
- 无诊断级事实时，只做症状性评估

## 输出格式
{
  "assessment": {
    "text": "诊断：...",
    "diagnosis": {"value": "...", "evidence_traces": []}
  },
  "assessment_items": [{
    "text": "...",
    "certainty_level": "high",
    "supporting_fact_ids": ["fact_id_1"],
    "diagnosis_type": "explicit_diagnosis"
  }]
}""",
        required_vars=["subjective_text", "objective_text", "facts_json"]
    )

    templates["emr_generation_plan"] = PromptTemplate(
        template="""根据已生成的S/O/A文本和事实表，生成病历的计划(P)部分，拆分为4个子字段。

## 主观数据(S)
$subjective_text

## 客观数据(O)
$objective_text

## 评估(A)
$assessment_text

## 事实表
$facts_json

## 子字段
1. **medications（用药方案）**：药物名称、剂量、频次、疗程，每条含used_fact_ids
2. **tests（检查建议）**：检查项目、建议原因，每条含used_fact_ids
3. **follow_up（复诊）**：复诊时间/条件，含used_fact_ids
4. **education（健康教育）**：生活方式指导、饮食建议、注意事项，含used_fact_ids

## 约束
- 每条计划必须有事实依据，对应至少一条fact_id
- 无证据则留空
- 优先使用normalized_term

## 输出格式
{
  "plan": {
    "text": "治疗方案：...",
    "treatment": {"value": "...", "evidence_traces": []},
    "advice": {"value": "...", "evidence_traces": []}
  },
  "plan_items": {
    "medications": [{"name": "", "dosage": "", "frequency": "", "duration": "", "used_fact_ids": []}],
    "tests": [{"name": "", "reason": "", "used_fact_ids": []}],
    "follow_up": {"text": "", "used_fact_ids": []},
    "education": {"text": "", "used_fact_ids": []}
  }
}""",
        required_vars=["subjective_text", "objective_text", "assessment_text", "facts_json"]
    )

    templates["emr_generation_ap"] = PromptTemplate(
        template="""根据已生成的S/O文本和事实表，同时生成评估(A)和计划(P)部分。

## 主观数据(S)
$subjective_text

## 客观数据(O)
$objective_text

## 事实表
$facts_json

## 评估(A)生成规则 - 三层诊断策略
1. **明确诊断(explicit_diagnosis)**：certainty=explicit，concept_type=disease，speaker=doctor → 直接写明疾病名称
2. **倾向性诊断(suspected_diagnosis)**：仅有supported级别证据，或医生有倾向未确诊 → 使用"考虑XXX""XXX待排"等措辞
3. **症状性评估(symptom_based_assessment)**：仅有症状无诊断 → 只描述症状，禁止发明疾病名称

## 计划(P)生成规则 - 四个子字段
1. **medications（用药方案）**：药物名称、剂量、频次、疗程
2. **tests（检查建议）**：检查项目、建议原因
3. **follow_up（复诊）**：复诊时间/条件
4. **education（健康教育）**：生活方式指导、饮食建议、注意事项

## 约束
- 严禁编造诊断结论
- 每条计划必须有事实依据，对应至少一条fact_id
- 无证据则留空
- 优先使用normalized_term

## 输出格式
{
  "assessment": {
    "text": "诊断：...",
    "diagnosis": {"value": "...", "evidence_traces": []}
  },
  "assessment_items": [{
    "text": "...",
    "certainty_level": "high",
    "supporting_fact_ids": ["fact_id_1"],
    "diagnosis_type": "explicit_diagnosis"
  }],
  "plan": {
    "text": "治疗方案：...",
    "treatment": {"value": "...", "evidence_traces": []},
    "advice": {"value": "...", "evidence_traces": []}
  },
  "plan_items": {
    "medications": [{"name": "", "dosage": "", "frequency": "", "duration": "", "used_fact_ids": []}],
    "tests": [{"name": "", "reason": "", "used_fact_ids": []}],
    "follow_up": {"text": "", "used_fact_ids": []},
    "education": {"text": "", "used_fact_ids": []}
  }
}""",
        required_vars=["subjective_text", "objective_text", "facts_json"]
    )

    return templates


def get_deprecated_templates_en() -> dict:
    """获取已废弃的英文模板（暂无，返回空字典）"""
    return {}
