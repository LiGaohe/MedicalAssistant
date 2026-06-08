"""评估阶段提示词模板"""
from .template import PromptTemplate


def get_evaluation_templates_zh() -> dict:
    """获取中文评估模板"""
    templates = {}

    templates["consistency_check"] = PromptTemplate(
        template="""## 原始对话
$transcript

## 待评估病历
$emr_content

你是一个医疗病历质量评估专家。请评估病历中已写的内容是否被原始对话支持（即幻觉检查）。

## 评估任务
从病历中提取所有原子事实，逐条判断每个事实是否能在原始对话中找到依据。

**核心原则：只检查病历中已经写了的内容是否有依据，不检查病历是否遗漏了对话中的信息。**

具体规则：
1. 从病历文本中提取原子事实（如：症状、诊断、药物、检查结果等）
2. 对每个提取出的事实，判断原始对话中是否有对应依据
3. **病历中没写的内容不算幻觉**——遗漏是完整性问题，不是一致性问题
4. 只有病历中写了但原始对话中找不到依据的，才标记为不支持（幻觉）
5. 原始对话中有但病历中没写的，不纳入本次评估

**示例**：
- 病历写了"诊断为上呼吸道感染"，对话中有此诊断依据 → 支持
- 病历写了"诊断为肺炎"，但对话中无此诊断依据 → 不支持（幻觉）
- 对话中提到"发热38.5度"，但病历中没写体温 → 不评估（遗漏，非幻觉）

## 输出格式（JSON）
请严格按照以下格式输出，不要添加任何额外内容：
{
  "facts": [
    {
      "fact": "从病历中提取的原子事实",
      "section": "subjective|objective|assessment|plan",
      "is_supported": true或false,
      "evidence_text": "对话中支持该事实的原文（如果is_supported为true，否则为空字符串）",
      "reasoning": "判断理由（简要说明为什么支持或不支持）"
    }
  ],
  "summary": {
    "total_facts": 事实总数（整数）,
    "supported_count": 支持的事实数（整数）,
    "unsupported_count": 不支持的事实数（整数）,
    "support_rate": 支持率（0.0-1.0的小数）
  }
}""",
        required_vars=["transcript", "emr_content"]
    )

    templates["consistency_check_section"] = PromptTemplate(
        template="""## 对话片段（仅包含与该章节相关的轮次）
$transcript_section

## 待评估病历【$section_name】章节
$emr_section

你是医疗病历质量评估专家。请评估【$section_name】章节中哪些事实无法被对话支持（即幻觉检查）。

## 评估任务
从病历该章节中提取所有原子事实，逐条判断每个事实是否能在对话中找到依据。

**核心原则：只检查病历中已经写了的内容是否有依据，不检查病历是否遗漏了对话中的信息。**

具体规则：
1. 从病历该章节文本中提取原子事实
2. 对每个提取出的事实，判断对话中是否有对应依据
3. **病历中没写的内容不算幻觉**——遗漏是完整性问题，不是一致性问题
4. 只有病历中写了但对话中找不到依据的，才标记为不支持（幻觉）
5. 对话中有但病历中没写的，不纳入本次评估

## 输出格式（JSON）
只输出不支持的事实，支持的事实不需要列出。
reasoning必须简短，不超过30字，不要展开推理过程：
{
  "unsupported_facts": [
    {
      "fact": "不支持的事实",
      "field_name": "该事实对应的病历字段名（如chief_complaint、diagnosis、treatment等）",
      "reasoning": "简短原因（不超过30字）"
    }
  ],
  "total_facts_in_section": 该章节事实总数（整数）,
  "supported_count": 支持的事实数（整数）
}

**field_name说明**：对应病历输入中的字段名（即"  - 字段名: 值"中的字段名），如chief_complaint、history_present_illness、physical_examination、diagnosis、treatment等。""",
        required_vars=["transcript_section", "emr_section", "section_name"]
    )

    templates["internal_consistency_check"] = PromptTemplate(
        template="""## 待评估病历
$emr_content

你是一个医疗病历质量评估专家。请检查病历内部是否存在自相矛盾。

## 评估任务
检查以下类型的内部冲突：
1. 年龄、性别在不同位置是否一致
2. 身体部位（左/右）在不同位置是否一致
3. 时间信息（病程、用药时间）是否自洽
4. 诊断与治疗方案是否对应
5. 主诉与现病史是否矛盾

## 输出格式（JSON）
请严格按照以下格式输出：
{
  "conflicts": [
    {
      "conflict_type": "age|gender|body_part|time|diagnosis_treatment|chief_complaint_history",
      "description": "冲突描述",
      "location_1": "第一个矛盾位置",
      "content_1": "第一个矛盾内容",
      "location_2": "第二个矛盾位置",
      "content_2": "第二个矛盾内容",
      "severity": "high|medium|low"
    }
  ],
  "is_consistent": true或false,
  "consistency_score": 0.0-1.0（无冲突为1.0，每个冲突扣0.1-0.2）
}

如果没有发现冲突，conflicts数组为空，is_consistent为true，consistency_score为1.0。""",
        required_vars=["emr_content"]
    )

    templates["key_fact_extraction"] = PromptTemplate(
        template="""## 原始对话
$transcript

你是一个医疗病历质量评估专家。请从医患对话中提取病历生成的关键事实清单。

## 提取任务
请提取以下类型的关键事实：
1. 主诉症状及持续时间
2. 关键阳性症状
3. 关键阴性症状（否认的症状）
4. 重要既往史和过敏史
5. 体格检查结果
6. 辅助检查结果或建议
7. 医生明确表达的诊断判断
8. 治疗方案和用药建议
9. 复诊和转诊建议

## 重要性判断标准
- high：影响诊断和治疗的关键信息（主诉、关键症状、过敏史、诊断、用药）
- medium：补充诊断信息（伴随症状、检查结果）
- low：辅助信息（一般医嘱、复诊建议）

## 输出格式（JSON）
请严格按照以下格式输出：
{
  "key_facts": [
    {
      "fact": "事实内容",
      "category": "chief_complaint|symptom|denied_symptom|history|allergy|physical_exam|auxiliary_exam|diagnosis|treatment|advice",
      "soap_section": "S|O|A|P",
      "importance": "high|medium|low",
      "evidence_text": "对话中的原文依据"
    }
  ],
  "total_count": 关键事实总数（整数）,
  "high_importance_count": 高重要性事实数（整数）
}""",
        required_vars=["transcript"]
    )

    templates["completeness_check"] = PromptTemplate(
        template="""## 关键事实清单
$key_facts

## 待评估病历
$emr_content

你是一个医疗病历质量评估专家。请评估病历对关键事实的覆盖情况。

## 评估任务
对每个关键事实，判断病历是否已覆盖。覆盖标准：
- full（完全覆盖）：事实内容完整出现在病历中，关键信息无遗漏
- partial（部分覆盖）：事实的部分内容出现在病历中，有信息遗漏
- none（未覆盖）：事实未出现在病历中

## 输出格式（JSON）
请严格按照以下格式输出：
{
  "coverage": [
    {
      "fact": "关键事实内容",
      "importance": "high|medium|low",
      "coverage_status": "full|partial|none",
      "emr_text": "病历中对应的内容（如果有）",
      "reasoning": "判断理由"
    }
  ],
  "summary": {
    "total_facts": 事实总数（整数）,
    "full_coverage_count": 完全覆盖数（整数）,
    "partial_coverage_count": 部分覆盖数（整数）,
    "none_coverage_count": 未覆盖数（整数）,
    "recall_rate": 召回率（0.0-1.0，计算方式：(full + 0.5*partial) / total）,
    "weighted_recall": 加权召回率（0.0-1.0，按重要性加权：high=1.0, medium=0.6, low=0.3）
  }
}""",
        required_vars=["key_facts", "emr_content"]
    )

    templates["document_quality_check"] = PromptTemplate(
        template="""## 待评估病历
$emr_content

你是一个医疗病历质量评估专家。请评估病历的文档质量。

## 评估维度
请对以下五个维度进行评分（0-2分）：

1. **结构完整**（structure_completeness）
   - 2分：SOAP四部分齐全，字段落在正确章节
   - 1分：SOAP基本完整，但有少量字段错放
   - 0分：SOAP部分缺失或严重错乱

2. **组织清楚**（organization_clarity）
   - 2分：顺序合理，逻辑清晰，易于阅读
   - 1分：基本有序，但部分内容组织欠佳
   - 0分：顺序混乱，难以理解

3. **表达简洁**（conciseness）
   - 2分：无重复，无冗余，表达精炼
   - 1分：有少量重复或冗余
   - 0分：重复严重，废话较多

4. **可理解性**（readability）
   - 2分：句子通顺，代词指代清楚，无歧义
   - 1分：基本通顺，有少量表达不清
   - 0分：句子不通顺，指代混乱

5. **术语规范**（terminology_appropriateness）
   - 2分：症状、药物、检查名称符合医学表达习惯
   - 1分：大部分术语规范，有少量口语化表达
   - 0分：术语不规范，口语化严重

## 输出格式（JSON）
请严格按照以下格式输出：
{
  "scores": {
    "structure_completeness": {
      "score": 0-2（整数）,
      "reasoning": "评分理由"
    },
    "organization_clarity": {
      "score": 0-2（整数）,
      "reasoning": "评分理由"
    },
    "conciseness": {
      "score": 0-2（整数）,
      "reasoning": "评分理由"
    },
    "readability": {
      "score": 0-2（整数）,
      "reasoning": "评分理由"
    },
    "terminology_appropriateness": {
      "score": 0-2（整数）,
      "reasoning": "评分理由"
    }
  },
  "total_score": 总分（0-10的整数）,
  "overall_assessment": "整体评价（一句话总结）"
}""",
        required_vars=["emr_content"]
    )

    templates["safety_risk_check"] = PromptTemplate(
        template="""## 原始对话
$transcript

## 待评估病历
$emr_content

你是一个医疗安全风险评估专家。请评估病历中是否存在高风险错误。

## 评估任务
请检查以下类型的高风险错误：

1. **重大幻觉**（major_hallucination）
   - 凭空生成诊断、药物、检查结果
   - 编造患者未提及的症状
   - severity: high

2. **重大遗漏**（major_omission）
   - 漏掉对话中明确提及的关键阳性症状
   - 漏掉对话中明确提及的药物过敏史
   - 漏掉对话中医生明确给出的处置建议
   - severity: high
   
   **重要**：只有当对话中明确存在该信息，但病历中未记录时，才构成"遗漏"。
   如果对话中本身未涉及该内容（如医生未问过敏史），则不属于病历遗漏问题，
   不应标记为风险。

3. **否定反转**（negation_reversal）
   - 把"无发热"写成"有发热"
   - 把"否认"写成"有"
   - severity: high

4. **部位侧别错误**（laterality_error）
   - 左侧写成右侧
   - 具体部位写错
   - severity: medium

5. **时间错误**（time_error）
   - 病程时间错误（两天写成两周）
   - 用药频次错误
   - severity: medium

6. **章节错放**（section_misplacement）
   - 检查结果写进主诉
   - 诊断写进现病史
   - severity: low

## 输出格式（JSON）
请严格按照以下格式输出：
{
  "risks": [
    {
      "risk_type": "major_hallucination|major_omission|negation_reversal|laterality_error|time_error|section_misplacement",
      "severity": "high|medium|low",
      "description": "错误描述",
      "emr_location": "病历中的位置",
      "emr_content": "病历中的错误内容",
      "correct_content": "正确内容（基于对话）",
      "evidence_text": "对话中的依据"
    }
  ],
  "has_high_risk": true或false（是否有severity为high的错误）,
  "high_risk_count": 高风险错误数（整数）,
  "total_risk_count": 总风险数（整数）,
  "safety_assessment": "安全评估结论（一句话总结）"
}

如果没有发现风险，risks数组为空，has_high_risk为false，各项count为0。""",
        required_vars=["transcript", "emr_content"]
    )

    templates["consistency_combined_check"] = PromptTemplate(
        template="""## 关键事实清单（从原始对话中提取）
$key_facts

## 待评估病历
$emr_content

你是一个医疗病历质量评估专家。请同时完成以下两项评估任务。

## 任务一：事实一致性检查（幻觉检查）
从病历中提取所有原子事实，逐条判断每个事实是否被关键事实清单支持。

**核心原则：只检查病历中已经写了的内容是否有依据，不检查病历是否遗漏了关键事实。**

具体规则：
1. 从病历文本中提取原子事实（如：症状、诊断、药物、检查结果等）
2. 对每个提取出的事实，判断关键事实清单中是否有对应依据
3. **病历中没写的内容不算幻觉**——遗漏是完整性问题，不是一致性问题
4. 只有病历中写了但关键事实清单中找不到依据的，才标记为不支持（幻觉）
5. 关键事实清单中有但病历中没写的，不纳入本次评估

**示例**：
- 病历写了"诊断为上呼吸道感染"，关键事实清单中有此诊断 → 支持
- 病历写了"诊断为肺炎"，但关键事实清单中无此诊断 → 不支持（幻觉）
- 关键事实清单中有"发热38.5度"，但病历中没写体温 → 不评估（遗漏，非幻觉）

## 任务二：内部一致性检查
检查病历内部是否存在自相矛盾：
1. 年龄、性别在不同位置是否一致
2. 身体部位（左/右）在不同位置是否一致
3. 时间信息（病程、用药时间）是否自洽
4. 诊断与治疗方案是否对应
5. 主诉与现病史是否矛盾

## 输出格式（JSON）
请严格按照以下格式输出，不要添加任何额外内容：
{
  "facts": [
    {
      "fact": "从病历中提取的原子事实",
      "section": "subjective|objective|assessment|plan",
      "is_supported": true或false,
      "evidence_text": "关键事实清单中支持该事实的原文（如果is_supported为true，否则为空字符串）",
      "reasoning": "判断理由（简要说明为什么支持或不支持）"
    }
  ],
  "summary": {
    "total_facts": 事实总数（整数）,
    "supported_count": 支持的事实数（整数）,
    "unsupported_count": 不支持的事实数（整数）,
    "support_rate": 支持率（0.0-1.0的小数）
  },
  "internal_conflicts": [
    {
      "conflict_type": "age|gender|body_part|time|diagnosis_treatment|chief_complaint_history",
      "description": "冲突描述",
      "location_1": "第一个矛盾位置",
      "content_1": "第一个矛盾内容",
      "location_2": "第二个矛盾位置",
      "content_2": "第二个矛盾内容",
      "severity": "high|medium|low"
    }
  ],
  "is_consistent": true或false,
  "consistency_score": 0.0-1.0（无冲突为1.0，每个冲突扣0.1-0.2）
}

如果没有发现内部冲突，internal_conflicts数组为空，is_consistent为true，consistency_score为1.0。""",
        required_vars=["key_facts", "emr_content"]
    )

    return templates


def get_evaluation_templates_en() -> dict:
    """获取英文评估模板"""
    templates = {}

    templates["consistency_check"] = PromptTemplate(
        template="""## Original conversation
$transcript

## Medical record to evaluate
$emr_content

You are a medical record quality assessment expert. Please evaluate whether content WRITTEN in the medical record is supported by the original conversation (i.e., hallucination check).

## Assessment task
Extract all atomic facts from the medical record, then judge whether each fact is supported by the original conversation.

**Core Principle: Only check whether content WRITTEN in the medical record has supporting evidence. Do NOT check whether the medical record has omitted information from the conversation.**

Specific rules:
1. Extract atomic facts from the medical record text (e.g., symptoms, diagnoses, medications, examination results)
2. For each extracted fact, determine if the original conversation contains corresponding evidence
3. **Content NOT written in the medical record is NOT hallucination** — omissions are a completeness issue, not a consistency issue
4. Only mark as unsupported (hallucination) when the medical record states something that cannot be found in the original conversation
5. Information present in the conversation but absent from the medical record should NOT be included in this evaluation

**Examples**:
- Medical record states "diagnosed with upper respiratory infection", conversation has evidence for this → Supported
- Medical record states "diagnosed with pneumonia", but conversation has no such evidence → Unsupported (hallucination)
- Conversation mentions "fever 38.5°C", but medical record does not mention temperature → Not evaluated (omission, not hallucination)

## Output format (JSON)
Please strictly follow this format, do not add any extra content:
{
  "facts": [
    {
      "fact": "atomic fact extracted from medical record",
      "section": "subjective|objective|assessment|plan",
      "is_supported": true or false,
      "evidence_text": "original text in conversation supporting this fact (if is_supported is true, otherwise empty string)",
      "reasoning": "judgment rationale (briefly explain why supported or not supported)"
    }
  ],
  "summary": {
    "total_facts": total number of facts (integer),
    "supported_count": number of supported facts (integer),
    "unsupported_count": number of unsupported facts (integer),
    "support_rate": support rate (decimal 0.0-1.0)
  }
}""",
        required_vars=["transcript", "emr_content"]
    )

    templates["consistency_check_section"] = PromptTemplate(
        template="""## Conversation snippet (only turns relevant to this section)
$transcript_section

## Medical record [$section_name] section to evaluate
$emr_section

You are a medical record quality assessment expert. Please evaluate which facts in the [$section_name] section are not supported by the conversation (i.e., hallucination check).

## Assessment task
Extract all atomic facts from this section of the medical record, then judge whether each fact is supported by the conversation.

**Core Principle: Only check whether content WRITTEN in the medical record has supporting evidence. Do NOT check whether the medical record has omitted information from the conversation.**

Specific rules:
1. Extract atomic facts from the medical record section text
2. For each extracted fact, determine if the conversation contains corresponding evidence
3. **Content NOT written in the medical record is NOT hallucination** — omissions are a completeness issue, not a consistency issue
4. Only mark as unsupported (hallucination) when the medical record states something that cannot be found in the conversation
5. Information present in the conversation but absent from the medical record should NOT be included in this evaluation

## Output format (JSON)
Only output unsupported facts, supported facts do not need to be listed.
Reasoning must be concise, no more than 20 words, do not elaborate the reasoning process:
{
  "unsupported_facts": [
    {
      "fact": "unsupported fact",
      "reasoning": "brief reason (max 20 words)"
    }
  ],
  "total_facts_in_section": total number of facts in this section (integer),
  "supported_count": number of supported facts (integer)
}""",
        required_vars=["transcript_section", "emr_section", "section_name"]
    )

    templates["internal_consistency_check"] = PromptTemplate(
        template="""## Medical record to evaluate
$emr_content

You are a medical record quality assessment expert. Please check whether there are internal contradictions in the medical record.

## Assessment task
Check for the following types of internal conflicts:
1. Are age and gender consistent in different locations
2. Are body parts (left/right) consistent in different locations
3. Is time information (disease duration, medication time) self-consistent
4. Does diagnosis correspond to treatment plan
5. Is there contradiction between chief complaint and history of present illness

## Output format (JSON)
Please strictly follow this format:
{
  "conflicts": [
    {
      "conflict_type": "age|gender|body_part|time|diagnosis_treatment|chief_complaint_history",
      "description": "conflict description",
      "location_1": "first contradictory location",
      "content_1": "first contradictory content",
      "location_2": "second contradictory location",
      "content_2": "second contradictory content",
      "severity": "high|medium|low"
    }
  ],
  "is_consistent": true or false,
  "consistency_score": 0.0-1.0 (1.0 if no conflicts, deduct 0.1-0.2 for each conflict)
}

If no conflicts found, conflicts array is empty, is_consistent is true, consistency_score is 1.0.""",
        required_vars=["emr_content"]
    )

    templates["key_fact_extraction"] = PromptTemplate(
        template="""## Original conversation
$transcript

You are a medical record quality assessment expert. Please extract a key fact list for medical record generation from the doctor-patient conversation.

## Extraction task
Please extract the following types of key facts:
1. Chief complaint symptoms and duration
2. Key positive symptoms
3. Key negative symptoms (denied symptoms)
4. Important past medical history and allergy history
5. Physical examination results
6. Auxiliary examination results or suggestions
7. Diagnosis judgments clearly expressed by doctor
8. Treatment plans and medication suggestions
9. Follow-up and referral suggestions

## Importance judgment criteria
- high: key information affecting diagnosis and treatment (chief complaint, key symptoms, allergy history, diagnosis, medication)
- medium: supplementary diagnostic information (associated symptoms, examination results)
- low: auxiliary information (general medical advice, follow-up suggestions)

## Output format (JSON)
Please strictly follow this format:
{
  "key_facts": [
    {
      "fact": "fact content",
      "category": "chief_complaint|symptom|denied_symptom|history|allergy|physical_exam|auxiliary_exam|diagnosis|treatment|advice",
      "soap_section": "S|O|A|P",
      "importance": "high|medium|low",
      "evidence_text": "original text basis in conversation"
    }
  ],
  "total_count": total number of key facts (integer),
  "high_importance_count": number of high importance facts (integer)
}""",
        required_vars=["transcript"]
    )

    templates["completeness_check"] = PromptTemplate(
        template="""## Key fact list
$key_facts

## Medical record to evaluate
$emr_content

You are a medical record quality assessment expert. Please evaluate the coverage of key facts in the medical record.

## Assessment task
For each key fact, determine if the medical record has covered it. Coverage criteria:
- full (fully covered): fact content completely appears in medical record, no key information missing
- partial (partially covered): part of fact content appears in medical record, some information missing
- none (not covered): fact does not appear in medical record

## Output format (JSON)
Please strictly follow this format:
{
  "coverage": [
    {
      "fact": "key fact content",
      "importance": "high|medium|low",
      "coverage_status": "full|partial|none",
      "emr_text": "corresponding content in medical record (if any)",
      "reasoning": "judgment rationale"
    }
  ],
  "summary": {
    "total_facts": total number of facts (integer),
    "full_coverage_count": number of fully covered (integer),
    "partial_coverage_count": number of partially covered (integer),
    "none_coverage_count": number of not covered (integer),
    "recall_rate": recall rate (0.0-1.0, calculated as: (full + 0.5*partial) / total),
    "weighted_recall": weighted recall rate (0.0-1.0, weighted by importance: high=1.0, medium=0.6, low=0.3)
  }
}""",
        required_vars=["key_facts", "emr_content"]
    )

    templates["document_quality_check"] = PromptTemplate(
        template="""## Medical record to evaluate
$emr_content

You are a medical record quality assessment expert. Please evaluate the document quality of the medical record.

## Assessment dimensions
Please score the following five dimensions (0-2 points):

1. **Structure Completeness** (structure_completeness)
   - 2 points: All four SOAP parts present, fields in correct sections
   - 1 point: SOAP basically complete, but a few fields misplaced
   - 0 points: SOAP parts missing or severely disordered

2. **Organization Clarity** (organization_clarity)
   - 2 points: Reasonable order, clear logic, easy to read
   - 1 point: Basically ordered, but some content poorly organized
   - 0 points: Disordered, difficult to understand

3. **Conciseness** (conciseness)
   - 2 points: No repetition, no redundancy, concise expression
   - 1 point: Some repetition or redundancy
   - 0 points: Severe repetition, much redundancy

4. **Readability** (readability)
   - 2 points: Smooth sentences, clear pronoun references, unambiguous
   - 1 point: Basically smooth, some unclear expressions
   - 0 points: Sentences not smooth, confused references

5. **Terminology Appropriateness** (terminology_appropriateness)
   - 2 points: Symptoms, medications, examination names conform to medical expression conventions
   - 1 point: Most terminology standard, some colloquial expressions
   - 0 points: Non-standard terminology, severely colloquial

## Output format (JSON)
Please strictly follow this format:
{
  "scores": {
    "structure_completeness": {
      "score": 0-2 (integer),
      "reasoning": "scoring rationale"
    },
    "organization_clarity": {
      "score": 0-2 (integer),
      "reasoning": "scoring rationale"
    },
    "conciseness": {
      "score": 0-2 (integer),
      "reasoning": "scoring rationale"
    },
    "readability": {
      "score": 0-2 (integer),
      "reasoning": "scoring rationale"
    },
    "terminology_appropriateness": {
      "score": 0-2 (integer),
      "reasoning": "scoring rationale"
    }
  },
  "total_score": total score (integer 0-10),
  "overall_assessment": "overall assessment (one sentence summary)"
}""",
        required_vars=["emr_content"]
    )

    templates["safety_risk_check"] = PromptTemplate(
        template="""## Original conversation
$transcript

## Medical record to evaluate
$emr_content

You are a medical safety risk assessment expert. Please evaluate if there are high-risk errors in the medical record.

## Assessment task
Please check for the following types of high-risk errors:

1. **Major Hallucination** (major_hallucination)
   - Fabricating diagnoses, medications, examination results
   - Inventing symptoms not mentioned by patient
   - severity: high

2. **Major Omission** (major_omission)
   - Missing key positive symptoms explicitly mentioned in conversation
   - Missing drug allergy history explicitly mentioned in conversation
   - Missing clear treatment recommendations explicitly given by doctor in conversation
   - severity: high
   
   **IMPORTANT**: An "omission" only occurs when the information clearly exists in the 
   conversation but is not recorded in the medical record. If the conversation itself 
   does not involve that content (e.g., doctor did not ask about allergy history), 
   it is NOT a medical record omission and should NOT be flagged as a risk.

3. **Negation Reversal** (negation_reversal)
   - Writing "no fever" as "has fever"
   - Writing "denies" as "has"
   - severity: high

4. **Laterality Error** (laterality_error)
   - Writing left side as right side
   - Wrong specific body part
   - severity: medium

5. **Time Error** (time_error)
   - Wrong disease duration (two days written as two weeks)
   - Wrong medication frequency
   - severity: medium

6. **Section Misplacement** (section_misplacement)
   - Examination results written in chief complaint
   - Diagnosis written in history of present illness
   - severity: low

## Output format (JSON)
Please strictly follow this format:
{
  "risks": [
    {
      "risk_type": "major_hallucination|major_omission|negation_reversal|laterality_error|time_error|section_misplacement",
      "severity": "high|medium|low",
      "description": "error description",
      "emr_location": "location in medical record",
      "emr_content": "wrong content in medical record",
      "correct_content": "correct content (based on conversation)",
      "evidence_text": "basis in conversation"
    }
  ],
  "has_high_risk": true or false (whether there are errors with severity high),
  "high_risk_count": number of high risk errors (integer),
  "total_risk_count": total number of risks (integer),
  "safety_assessment": "safety assessment conclusion (one sentence summary)"
}

If no risks found, risks array is empty, has_high_risk is false, all counts are 0.""",
        required_vars=["transcript", "emr_content"]
    )

    templates["consistency_combined_check"] = PromptTemplate(
        template="""## Key fact list (extracted from original conversation)
$key_facts

## Medical record to evaluate
$emr_content

You are a medical record quality assessment expert. Please complete both assessment tasks below simultaneously.

## Task 1: Fact Consistency Check (Hallucination Check)
Extract all atomic facts from the medical record, then judge whether each fact is supported by the key fact list.

**Core Principle: Only check whether content WRITTEN in the medical record has supporting evidence. Do NOT check whether the medical record has omitted key facts.**

Specific rules:
1. Extract atomic facts from the medical record text (e.g., symptoms, diagnoses, medications, examination results)
2. For each extracted fact, determine if the key fact list contains corresponding evidence
3. **Content NOT written in the medical record is NOT hallucination** — omissions are a completeness issue, not a consistency issue
4. Only mark as unsupported (hallucination) when the medical record states something that cannot be found in the key fact list
5. Key facts present in the list but absent from the medical record should NOT be included in this evaluation

**Examples**:
- Medical record states "diagnosed with upper respiratory infection", key fact list has this diagnosis → Supported
- Medical record states "diagnosed with pneumonia", but key fact list has no such diagnosis → Unsupported (hallucination)
- Key fact list has "fever 38.5°C", but medical record does not mention temperature → Not evaluated (omission, not hallucination)

## Task 2: Internal Consistency Check
Check for internal contradictions in the medical record:
1. Are age and gender consistent in different locations
2. Are body parts (left/right) consistent in different locations
3. Is time information (disease duration, medication time) self-consistent
4. Does diagnosis correspond to treatment plan
5. Is there contradiction between chief complaint and history of present illness

## Output format (JSON)
Please strictly follow this format, do not add any extra content:
{
  "facts": [
    {
      "fact": "atomic fact extracted from medical record",
      "section": "subjective|objective|assessment|plan",
      "is_supported": true or false,
      "evidence_text": "original text in key fact list supporting this fact (if is_supported is true, otherwise empty string)",
      "reasoning": "judgment rationale (briefly explain why supported or not supported)"
    }
  ],
  "summary": {
    "total_facts": total number of facts (integer),
    "supported_count": number of supported facts (integer),
    "unsupported_count": number of unsupported facts (integer),
    "support_rate": support rate (decimal 0.0-1.0)
  },
  "internal_conflicts": [
    {
      "conflict_type": "age|gender|body_part|time|diagnosis_treatment|chief_complaint_history",
      "description": "conflict description",
      "location_1": "first contradictory location",
      "content_1": "first contradictory content",
      "location_2": "second contradictory location",
      "content_2": "second contradictory content",
      "severity": "high|medium|low"
    }
  ],
  "is_consistent": true or false,
  "consistency_score": 0.0-1.0 (1.0 if no conflicts, deduct 0.1-0.2 for each conflict)
}

If no internal conflicts found, internal_conflicts array is empty, is_consistent is true, consistency_score is 1.0.""",
        required_vars=["key_facts", "emr_content"]
    )

    return templates
