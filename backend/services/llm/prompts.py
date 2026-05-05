from typing import Dict, Any, Optional
from string import Template


class PromptTemplate:
    def __init__(self, template: str, required_vars: list):
        self.template = Template(template)
        self.required_vars = required_vars
        
    def render(self, **kwargs) -> str:
        missing_vars = set(self.required_vars) - set(kwargs.keys())
        if missing_vars:
            raise ValueError(f"Missing required variables: {missing_vars}")
        return self.template.safe_substitute(**kwargs)


class PromptManager:
    def __init__(self, language: str = "zh"):
        self.templates: Dict[str, PromptTemplate] = {}
        self.language = language
        self._load_default_templates()
        
    def _load_default_templates(self):
        if self.language == "en":
            self._load_english_templates()
        else:
            self._load_chinese_templates()
    
    def _load_chinese_templates(self):
        self.templates["evidence_selection"] = PromptTemplate(
            template="""你是一个医疗病历生成助手。请从以下医患对话中识别并提取与病历生成相关的证据片段。

对话内容：
$transcript

请按以下格式输出JSON：
{
  "evidence": [
    {
      "field": "chief_complaint|history|diagnosis|advice",
      "content": "证据内容",
      "turn_ids": [相关对话轮次ID],
      "confidence": 0.0-1.0,
      "reasoning": "为什么这段对话是证据"
    }
  ]
}""",
            required_vars=["transcript"]
        )
        
        self.templates["item_extraction"] = PromptTemplate(
            template="""你是一个医疗病历生成专家。请从以下规范化文本中抽取SOAP格式的病历要素。

规范化文本：$normalized_text

请按SOAP格式输出JSON：
{
  "subjective": {
    "chief_complaint": {
      "value": "主诉内容",
      "evidence_ids": [证据ID列表],
      "confidence": 0.0-1.0
    },
    "history_present_illness": {
      "value": "现病史内容",
      "evidence_ids": [证据ID列表],
      "confidence": 0.0-1.0
    }
  },
  "objective": {
    "physical_examination": {
      "value": "体格检查内容",
      "evidence_ids": [证据ID列表],
      "confidence": 0.0-1.0
    },
    "auxiliary_examination": {
      "value": "辅助检查内容",
      "evidence_ids": [证据ID列表],
      "confidence": 0.0-1.0
    }
  },
  "assessment": {
    "diagnosis": {
      "value": "诊断内容",
      "evidence_ids": [证据ID列表],
      "confidence": 0.0-1.0
    }
  },
  "plan": {
    "treatment": {
      "value": "治疗方案",
      "evidence_ids": [证据ID列表],
      "confidence": 0.0-1.0
    },
    "advice": {
      "value": "医嘱内容",
      "evidence_ids": [证据ID列表],
      "confidence": 0.0-1.0
    }
  }
}""",
            required_vars=["normalized_text"]
        )
        
        self.templates["emr_generation"] = PromptTemplate(
            template="""你是一个医疗病历撰写专家。请根据以下结构化数据生成符合医疗规范的病历文本。

结构化数据：$extracted_data
模板要求：$template_requirements

请生成自然流畅的病历文本，并标注每段内容的证据来源。输出JSON格式：
{
  "subjective": {
    "text": "患者主诉头痛三天...",
    "evidence_mapping": [
      {"text_segment": "头痛三天", "evidence_ids": [1, 2]}
    ]
  },
  "objective": {
    "text": "体格检查：...",
    "evidence_mapping": [...]
  },
  "assessment": {
    "text": "诊断：...",
    "evidence_mapping": [...]
  },
  "plan": {
    "text": "治疗方案：...",
    "evidence_mapping": [...]
  }
}""",
            required_vars=["extracted_data", "template_requirements"]
        )
        
        self.templates["emr_generation_with_role"] = PromptTemplate(
            template="""你是一个医疗病历撰写专家。请根据以下医患对话和结构化数据生成符合医疗规范的病历文本。

## 原始对话（说话人ID为spk0, spk1等，需要你判断谁是医生谁是患者）
$transcript

## 初步抽取的结构化数据（可能存在角色识别错误，请根据对话内容修正）
$extracted_data

## 模板要求
$template_requirements

## 任务要求
1. 首先判断每个说话人(spk0, spk1等)的角色（医生/患者）
2. 根据角色修正结构化数据中的内容：
   - 主诉、现病史、既往史：应该是患者说的话
   - 体格检查、辅助检查、诊断、治疗方案、医嘱：应该是医生说的话
3. 如果发现角色错误，请从正确的说话人对话中提取正确内容
4. **纠正转写错误**：原始对话可能包含语音识别错误，请根据上下文和医学常识纠正：
   - 拼音相似错误：如"搞血压"→"高血压"、"堂尿病"→"糖尿病"
   - 医学术语错误：如"阿莫希林"→"阿莫西林"、"青梅素"→"青霉素"
   - 同音字错误：如"头疼"→"头痛"、"发骚"→"发烧"
   - 注意：只在病历文本中使用纠正后的正确术语，不要在输出中标注纠正过程
5. 生成自然流畅的病历文本，确保使用规范的医学术语
6. **标注证据来源**：为每个字段标注evidence_ids（对话轮次索引turn_index）：
   - evidence_ids是对话中的turn_index（从0开始）
   - 一个字段可能对应多个turn，需要标注所有相关的turn_index
   - 例如：医嘱包含"每天早上吃一片"（turn 17）、"注意休息"（turn 21）、"一周后复查"（turn 23），则evidence_ids为[17, 21, 23]

请输出JSON格式：
{
  "role_mapping": {
    "spk0": "doctor或patient",
    "spk1": "doctor或patient"
  },
  "subjective": {
    "text": "患者主诉...",
    "chief_complaint": {"value": "...", "evidence_ids": [0, 1, 2]},
    "history_present_illness": {"value": "...", "evidence_ids": [3, 4]}
  },
  "objective": {
    "text": "体格检查：...",
    "physical_examination": {"value": "...", "evidence_ids": [10, 11]}
  },
  "assessment": {
    "text": "诊断：...",
    "diagnosis": {"value": "...", "evidence_ids": [15]}
  },
  "plan": {
    "text": "治疗方案：...",
    "treatment": {"value": "...", "evidence_ids": [16, 17]},
    "advice": {"value": "...", "evidence_ids": [17, 21, 22, 23]}
  }
}""",
            required_vars=["extracted_data", "transcript", "template_requirements"]
        )
        
        self._load_chinese_evaluation_templates()
    
    def _load_chinese_evaluation_templates(self):
        self.templates["consistency_check"] = PromptTemplate(
            template="""你是一个医疗病历质量评估专家。请评估病历中的内容是否被原始对话支持。

## 原始对话
$transcript

## 待评估病历
$emr_content

## 评估任务
请对病历中的每个关键事实进行二值判断：该事实是否能在原始对话中找到依据？

关键事实包括：
1. 主诉症状及持续时间
2. 伴随症状
3. 既往史
4. 过敏史
5. 体格检查结果
6. 辅助检查结果
7. 诊断结论
8. 治疗药物
9. 医嘱建议

## 重要评估原则
**仅评估原始对话中实际涉及的内容**：
- 如果原始对话中**未提及**既往史，则不将"未提及既往史"作为评估项，跳过此项评估
- 如果原始对话中**未提及**过敏史，则不将"未提及过敏史"作为评估项，跳过此项评估
- 如果原始对话中**未提及**辅助检查，则不将"未行辅助检查"作为评估项，跳过此项评估
- 只有当原始对话中明确涉及某类信息，而病历中缺失或矛盾时，才将其标记为不支持

**证据为"无"的情况不作为扣分依据**：
- 当某类信息在原始对话中完全未出现时，病历中是否记录该信息不纳入一致性评估
- 仅评估原始对话中存在明确信息的事实项

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
        
        self.templates["internal_consistency_check"] = PromptTemplate(
            template="""你是一个医疗病历质量评估专家。请检查病历内部是否存在自相矛盾。

## 待评估病历
$emr_content

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
        
        self.templates["key_fact_extraction"] = PromptTemplate(
            template="""你是一个医疗病历质量评估专家。请从医患对话中提取病历生成的关键事实清单。

## 原始对话
$transcript

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
        
        self.templates["completeness_check"] = PromptTemplate(
            template="""你是一个医疗病历质量评估专家。请评估病历对关键事实的覆盖情况。

## 关键事实清单
$key_facts

## 待评估病历
$emr_content

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
        
        self.templates["document_quality_check"] = PromptTemplate(
            template="""你是一个医疗病历质量评估专家。请评估病历的文档质量。

## 待评估病历
$emr_content

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
        
        self.templates["safety_risk_check"] = PromptTemplate(
            template="""你是一个医疗安全风险评估专家。请评估病历中是否存在高风险错误。

## 原始对话
$transcript

## 待评估病历
$emr_content

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
    
    def _load_english_templates(self):
        self.templates["evidence_selection"] = PromptTemplate(
            template="""You are a medical record generation assistant. Please identify and extract evidence fragments relevant to medical record generation from the following doctor-patient conversation.

Conversation:
$transcript

Please output JSON in the following format:
{
  "evidence": [
    {
      "field": "chief_complaint|history|diagnosis|advice",
      "content": "evidence content",
      "turn_ids": [relevant conversation turn IDs],
      "confidence": 0.0-1.0,
      "reasoning": "why this conversation is evidence"
    }
  ]
}""",
            required_vars=["transcript"]
        )
        
        self.templates["item_extraction"] = PromptTemplate(
            template="""You are a medical record generation expert. Please extract SOAP format medical record elements from the following normalized text.

Normalized text: $normalized_text

Please output JSON in SOAP format:
{
  "subjective": {
    "chief_complaint": {
      "value": "chief complaint content",
      "evidence_ids": [evidence ID list],
      "confidence": 0.0-1.0
    },
    "history_present_illness": {
      "value": "history of present illness content",
      "evidence_ids": [evidence ID list],
      "confidence": 0.0-1.0
    }
  },
  "objective": {
    "physical_examination": {
      "value": "physical examination content",
      "evidence_ids": [evidence ID list],
      "confidence": 0.0-1.0
    },
    "auxiliary_examination": {
      "value": "auxiliary examination content",
      "evidence_ids": [evidence ID list],
      "confidence": 0.0-1.0
    }
  },
  "assessment": {
    "diagnosis": {
      "value": "diagnosis content",
      "evidence_ids": [evidence ID list],
      "confidence": 0.0-1.0
    }
  },
  "plan": {
    "treatment": {
      "value": "treatment plan",
      "evidence_ids": [evidence ID list],
      "confidence": 0.0-1.0
    },
    "advice": {
      "value": "medical advice content",
      "evidence_ids": [evidence ID list],
      "confidence": 0.0-1.0
    }
  }
}""",
            required_vars=["normalized_text"]
        )
        
        self.templates["emr_generation"] = PromptTemplate(
            template="""You are a medical record writing expert. Please generate medical record text that complies with medical standards based on the following structured data.

Structured data: $extracted_data
Template requirements: $template_requirements

Please generate natural and fluent medical record text, and annotate the evidence source for each section. Output JSON format:
{
  "subjective": {
    "text": "Patient presents with headache for three days...",
    "evidence_mapping": [
      {"text_segment": "headache for three days", "evidence_ids": [1, 2]}
    ]
  },
  "objective": {
    "text": "Physical examination: ...",
    "evidence_mapping": [...]
  },
  "assessment": {
    "text": "Diagnosis: ...",
    "evidence_mapping": [...]
  },
  "plan": {
    "text": "Treatment plan: ...",
    "evidence_mapping": [...]
  }
}""",
            required_vars=["extracted_data", "template_requirements"]
        )
        
        self.templates["emr_generation_with_role"] = PromptTemplate(
            template="""You are a medical record writing expert. Please generate medical record text that complies with medical standards based on the following doctor-patient conversation and structured data.

## Original conversation (speaker IDs are spk0, spk1, etc., you need to determine who is the doctor and who is the patient)
$transcript

## Preliminary extracted structured data (there may be role identification errors, please correct based on conversation content)
$extracted_data

## Template requirements
$template_requirements

## Task requirements
1. First determine the role of each speaker (spk0, spk1, etc.) (doctor/patient)
2. Correct the content in structured data based on roles:
   - Chief complaint, history of present illness, past medical history: should be what the patient said
   - Physical examination, auxiliary examination, diagnosis, treatment plan, medical advice: should be what the doctor said
3. If role errors are found, extract correct content from the correct speaker's conversation
4. **Correct transcription errors**: The original conversation may contain speech recognition errors, please correct based on context and medical knowledge:
   - Phonetically similar errors: e.g., "hi blood pressure" → "high blood pressure"
   - Medical terminology errors: e.g., "amoxicillin" misspelled → correct to "amoxicillin"
   - Homophone errors: e.g., "head ache" → "headache"
   - Note: Only use corrected terms in the medical record text, do not annotate the correction process in output
5. Generate natural and fluent medical record text, ensure using standard medical terminology
6. **Annotate evidence sources**: For each field, annotate evidence_ids (turn_index in conversation):
   - evidence_ids are turn_index in the conversation (starting from 0)
   - One field may correspond to multiple turns, annotate all relevant turn_index
   - Example: Advice contains "take one pill every morning" (turn 17), "rest well" (turn 21), "follow up in one week" (turn 23), then evidence_ids is [17, 21, 23]

Please output JSON format:
{
  "role_mapping": {
    "spk0": "doctor or patient",
    "spk1": "doctor or patient"
  },
  "subjective": {
    "text": "Patient presents with...",
    "chief_complaint": {"value": "...", "evidence_ids": [0, 1, 2]},
    "history_present_illness": {"value": "...", "evidence_ids": [3, 4]}
  },
  "objective": {
    "text": "Physical examination: ...",
    "physical_examination": {"value": "...", "evidence_ids": [10, 11]}
  },
  "assessment": {
    "text": "Diagnosis: ...",
    "diagnosis": {"value": "...", "evidence_ids": [15]}
  },
  "plan": {
    "text": "Treatment plan: ...",
    "treatment": {"value": "...", "evidence_ids": [16, 17]},
    "advice": {"value": "...", "evidence_ids": [17, 21, 22, 23]}
  }
}""",
            required_vars=["extracted_data", "transcript", "template_requirements"]
        )
        
        self._load_english_evaluation_templates()
    
    def _load_english_evaluation_templates(self):
        self.templates["consistency_check"] = PromptTemplate(
            template="""You are a medical record quality assessment expert. Please evaluate whether the content in the medical record is supported by the original conversation.

## Original conversation
$transcript

## Medical record to evaluate
$emr_content

## Assessment task
Please make a binary judgment for each key fact in the medical record: can this fact find basis in the original conversation?

Key facts include:
1. Chief complaint symptoms and duration
2. Associated symptoms
3. Past medical history
4. Allergy history
5. Physical examination results
6. Auxiliary examination results
7. Diagnosis conclusions
8. Treatment medications
9. Medical advice

## Important Assessment Principles
**Only evaluate content actually mentioned in the original conversation**:
- If past medical history is **not mentioned** in the original conversation, do not include "past medical history not mentioned" as an evaluation item, skip this assessment
- If allergy history is **not mentioned** in the original conversation, do not include "allergy history not mentioned" as an evaluation item, skip this assessment
- If auxiliary examination is **not mentioned** in the original conversation, do not include "auxiliary examination not performed" as an evaluation item, skip this assessment
- Only mark as unsupported when the original conversation clearly involves certain information but the medical record is missing or contradictory

**Evidence being "none" is not a basis for deduction**:
- When certain information does not appear at all in the original conversation, whether the medical record records it is not included in consistency evaluation
- Only evaluate facts where explicit information exists in the original conversation

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
        
        self.templates["internal_consistency_check"] = PromptTemplate(
            template="""You are a medical record quality assessment expert. Please check if there are internal contradictions in the medical record.

## Medical record to evaluate
$emr_content

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
        
        self.templates["key_fact_extraction"] = PromptTemplate(
            template="""You are a medical record quality assessment expert. Please extract a key fact list for medical record generation from the doctor-patient conversation.

## Original conversation
$transcript

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
        
        self.templates["completeness_check"] = PromptTemplate(
            template="""You are a medical record quality assessment expert. Please evaluate the coverage of key facts in the medical record.

## Key fact list
$key_facts

## Medical record to evaluate
$emr_content

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
        
        self.templates["document_quality_check"] = PromptTemplate(
            template="""You are a medical record quality assessment expert. Please evaluate the document quality of the medical record.

## Medical record to evaluate
$emr_content

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
        
        self.templates["safety_risk_check"] = PromptTemplate(
            template="""You are a medical safety risk assessment expert. Please evaluate if there are high-risk errors in the medical record.

## Original conversation
$transcript

## Medical record to evaluate
$emr_content

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
        
        self.templates["emr_generation"] = PromptTemplate(
            template="""你是一个医疗病历撰写专家。请根据以下结构化数据生成符合医疗规范的病历文本。

结构化数据：$extracted_data
模板要求：$template_requirements

请生成自然流畅的病历文本，并标注每段内容的证据来源。输出JSON格式：
{
  "subjective": {
    "text": "患者主诉头痛三天...",
    "evidence_mapping": [
      {"text_segment": "头痛三天", "evidence_ids": [1, 2]}
    ]
  },
  "objective": {
    "text": "体格检查：...",
    "evidence_mapping": [...]
  },
  "assessment": {
    "text": "诊断：...",
    "evidence_mapping": [...]
  },
  "plan": {
    "text": "治疗方案：...",
    "evidence_mapping": [...]
  }
}""",
            required_vars=["extracted_data", "template_requirements"]
        )
        
        self.templates["emr_generation_with_role"] = PromptTemplate(
            template="""你是一个医疗病历撰写专家。请根据以下医患对话和结构化数据生成符合医疗规范的病历文本。

## 原始对话（说话人ID为spk0, spk1等，需要你判断谁是医生谁是患者）
$transcript

## 初步抽取的结构化数据（可能存在角色识别错误，请根据对话内容修正）
$extracted_data

## 模板要求
$template_requirements

## 任务要求
1. 首先判断每个说话人(spk0, spk1等)的角色（医生/患者）
2. 根据角色修正结构化数据中的内容：
   - 主诉、现病史、既往史：应该是患者说的话
   - 体格检查、辅助检查、诊断、治疗方案、医嘱：应该是医生说的话
3. 如果发现角色错误，请从正确的说话人对话中提取正确内容
4. **纠正转写错误**：原始对话可能包含语音识别错误，请根据上下文和医学常识纠正：
   - 拼音相似错误：如"搞血压"→"高血压"、"堂尿病"→"糖尿病"
   - 医学术语错误：如"阿莫希林"→"阿莫西林"、"青梅素"→"青霉素"
   - 同音字错误：如"头疼"→"头痛"、"发骚"→"发烧"
   - 注意：只在病历文本中使用纠正后的正确术语，不要在输出中标注纠正过程
5. 生成自然流畅的病历文本，确保使用规范的医学术语
6. **标注证据来源**：为每个字段标注evidence_ids（对话轮次索引turn_index）：
   - evidence_ids是对话中的turn_index（从0开始）
   - 一个字段可能对应多个turn，需要标注所有相关的turn_index
   - 例如：医嘱包含"每天早上吃一片"（turn 17）、"注意休息"（turn 21）、"一周后复查"（turn 23），则evidence_ids为[17, 21, 23]

请输出JSON格式：
{
  "role_mapping": {
    "spk0": "doctor或patient",
    "spk1": "doctor或patient"
  },
  "subjective": {
    "text": "患者主诉...",
    "chief_complaint": {"value": "...", "evidence_ids": [0, 1, 2]},
    "history_present_illness": {"value": "...", "evidence_ids": [3, 4]}
  },
  "objective": {
    "text": "体格检查：...",
    "physical_examination": {"value": "...", "evidence_ids": [10, 11]}
  },
  "assessment": {
    "text": "诊断：...",
    "diagnosis": {"value": "...", "evidence_ids": [15]}
  },
  "plan": {
    "text": "治疗方案：...",
    "treatment": {"value": "...", "evidence_ids": [16, 17]},
    "advice": {"value": "...", "evidence_ids": [17, 21, 22, 23]}
  }
}""",
            required_vars=["extracted_data", "transcript", "template_requirements"]
        )
        
        self.templates["consistency_check"] = PromptTemplate(
            template="""你是一个医疗病历质量评估专家。请评估病历中的内容是否被原始对话支持。

## 原始对话
$transcript

## 待评估病历
$emr_content

## 评估任务
请对病历中的每个关键事实进行二值判断：该事实是否能在原始对话中找到依据？

关键事实包括：
1. 主诉症状及持续时间
2. 伴随症状
3. 既往史
4. 过敏史
5. 体格检查结果
6. 辅助检查结果
7. 诊断结论
8. 治疗药物
9. 医嘱建议

## 重要评估原则
**仅评估原始对话中实际涉及的内容**：
- 如果原始对话中**未提及**既往史，则不将"未提及既往史"作为评估项，跳过此项评估
- 如果原始对话中**未提及**过敏史，则不将"未提及过敏史"作为评估项，跳过此项评估
- 如果原始对话中**未提及**辅助检查，则不将"未行辅助检查"作为评估项，跳过此项评估
- 只有当原始对话中明确涉及某类信息，而病历中缺失或矛盾时，才将其标记为不支持

**证据为"无"的情况不作为扣分依据**：
- 当某类信息在原始对话中完全未出现时，病历中是否记录该信息不纳入一致性评估
- 仅评估原始对话中存在明确信息的事实项

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
        
        self.templates["internal_consistency_check"] = PromptTemplate(
            template="""你是一个医疗病历质量评估专家。请检查病历内部是否存在自相矛盾。

## 待评估病历
$emr_content

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
        
        self.templates["key_fact_extraction"] = PromptTemplate(
            template="""你是一个医疗病历质量评估专家。请从医患对话中提取病历生成的关键事实清单。

## 原始对话
$transcript

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
        
        self.templates["completeness_check"] = PromptTemplate(
            template="""你是一个医疗病历质量评估专家。请评估病历对关键事实的覆盖情况。

## 关键事实清单
$key_facts

## 待评估病历
$emr_content

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
        
        self.templates["document_quality_check"] = PromptTemplate(
            template="""你是一个医疗病历质量评估专家。请评估病历的文档质量。

## 待评估病历
$emr_content

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
        
        self.templates["safety_risk_check"] = PromptTemplate(
            template="""你是一个医疗安全风险评估专家。请评估病历中是否存在高风险错误。

## 原始对话
$transcript

## 待评估病历
$emr_content

## 评估任务
请检查以下类型的高风险错误：

1. **重大幻觉**（major_hallucination）
   - 凭空生成诊断、药物、检查结果
   - 编造患者未提及的症状
   - severity: high

2. **重大遗漏**（major_omission）
   - 漏掉关键阳性症状
   - 漏掉药物过敏史
   - 漏掉明确的处置建议
   - severity: high

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
        
    def get_template(self, name: str) -> PromptTemplate:
        if name not in self.templates:
            raise ValueError(f"Template '{name}' not found")
        return self.templates[name]
    
    def add_template(self, name: str, template: str, required_vars: list):
        self.templates[name] = PromptTemplate(template, required_vars)
        
    def render(self, template_name: str, **kwargs) -> str:
        template = self.get_template(template_name)
        return template.render(**kwargs)
