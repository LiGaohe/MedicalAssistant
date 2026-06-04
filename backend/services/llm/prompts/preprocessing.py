"""对话预处理阶段提示词模板"""
from .template import PromptTemplate


def get_preprocessing_templates_zh() -> dict:
    """获取中文对话预处理模板"""
    templates = {}

    templates["turn_cleaning"] = PromptTemplate(
        template="""你是一个医疗对话分析专家。请对以下医患对话进行角色纠错和ASR修正。

## 对话
$transcript

## 任务
1. 判断每个turn的说话人角色（doctor/patient），纠正ASR角色分配错误
2. 修正明显的ASR文本错误（同音字、医学术语拼写错误）
3. 判断每个turn的SOAP章节归属（section_hint），为后续路由提供信息
4. 不确定则保留原文，correction_confidence设为"low"

## section_hint说明
- S: 主诉、现病史、既往史相关内容（患者描述症状、病史）
- O: 体格检查、辅助检查相关内容（医生检查、检查结果）
- A: 诊断、评估相关内容（医生诊断判断）
- P: 用药、检查建议、复诊、健康指导（医生建议、处方）
- None: 无法归类或不相关内容
- 可多标签：如["S", "A"]表示同时涉及主诉和诊断

## 约束
- 严禁添加原文没有的信息
- 修正后保持原意和语气

## 输出格式
**重要**：turn_id必须使用对话中的[#N]编号，例如对话是[#30]则turn_id为30，不是位置索引。

{
  "turns": [{
    "turn_id": 30,
    "speaker_role": "doctor或patient",
    "corrected_text": "修正后文本（未修正则与原文一致）",
    "section_hint": ["S"]或["O"]或["A"]或["P"]或["None"]或["S", "A"]等多标签,
    "changed_spans": [{"original": "原词", "corrected": "修正词", "position": "位置描述"}],
    "correction_confidence": "high|medium|low",
    "reason": "修正或保留理由"
  }]
}""",
        required_vars=["transcript"]
    )

    templates["evidence_selection"] = PromptTemplate(
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

    templates["item_extraction"] = PromptTemplate(
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

    return templates


def get_preprocessing_templates_en() -> dict:
    """获取英文对话预处理模板"""
    templates = {}

    templates["evidence_selection"] = PromptTemplate(
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

    templates["item_extraction"] = PromptTemplate(
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

    return templates
