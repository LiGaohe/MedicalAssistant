from typing import Dict, Any
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
    def __init__(self):
        self.templates: Dict[str, PromptTemplate] = {}
        self._load_default_templates()
        
    def _load_default_templates(self):
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
        
        self.templates["term_normalization"] = PromptTemplate(
            template="""你是一个医学术语规范化专家。请将以下口语化医疗术语映射到标准医学术语。

口语化术语：$term
上下文：$context

请按以下格式输出JSON：
{
  "original_term": "原始术语",
  "normalized_term": "标准术语",
  "term_type": "symptom|drug|diagnosis|examination",
  "confidence": 0.0-1.0,
  "is_risky": true/false,
  "reasoning": "映射理由"
}""",
            required_vars=["term", "context"]
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
4. 生成自然流畅的病历文本

请输出JSON格式：
{
  "role_mapping": {
    "spk0": "doctor或patient",
    "spk1": "doctor或patient"
  },
  "subjective": {
    "text": "患者主诉...",
    "chief_complaint": {"value": "...", "evidence_ids": []},
    "history_present_illness": {"value": "...", "evidence_ids": []}
  },
  "objective": {
    "text": "体格检查：...",
    "physical_examination": {"value": "...", "evidence_ids": []}
  },
  "assessment": {
    "text": "诊断：...",
    "diagnosis": {"value": "...", "evidence_ids": []}
  },
  "plan": {
    "text": "治疗方案：...",
    "treatment": {"value": "...", "evidence_ids": []},
    "advice": {"value": "...", "evidence_ids": []}
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
