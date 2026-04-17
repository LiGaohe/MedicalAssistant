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
        
    def get_template(self, name: str) -> PromptTemplate:
        if name not in self.templates:
            raise ValueError(f"Template '{name}' not found")
        return self.templates[name]
    
    def add_template(self, name: str, template: str, required_vars: list):
        self.templates[name] = PromptTemplate(template, required_vars)
        
    def render(self, template_name: str, **kwargs) -> str:
        template = self.get_template(template_name)
        return template.render(**kwargs)
