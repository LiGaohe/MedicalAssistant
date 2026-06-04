"""SOAP病历生成阶段提示词模板"""
from .template import PromptTemplate


def get_soap_generation_templates_zh() -> dict:
    """获取中文SOAP生成模板"""
    templates = {}

    templates["emr_generation"] = PromptTemplate(
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

    templates["emr_generation_with_role"] = PromptTemplate(
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

    templates["direct_soap_generation"] = PromptTemplate(
        template="""你是一个医疗病历撰写专家。请根据以下医患对话生成SOAP病历草稿。

## 原始对话
$transcript

## 字段说明
- **S**：chief_complaint（主诉）、history_present_illness（现病史）、denied_symptoms（否认症状）、past_history（既往史）
- **O**：physical_examination（体格检查）、auxiliary_examination（辅助检查）
- **A**：diagnosis（诊断）
- **P**：treatment（治疗方案）、advice（医嘱）

每个字段包含 value（文本内容）和 source_turn_indices（对话turn序号数组，从0开始）。
对话中未提及的字段 value 为空字符串，source_turn_indices 为空数组。

## 输出JSON格式
{
  "subjective": {
    "text": "",
    "chief_complaint": {"value": "", "source_turn_indices": []},
    "history_present_illness": {"value": "", "source_turn_indices": []},
    "denied_symptoms": {"value": "", "source_turn_indices": []},
    "past_history": {"value": "", "source_turn_indices": []}
  },
  "objective": {
    "text": "",
    "physical_examination": {"value": "", "source_turn_indices": []},
    "auxiliary_examination": {"value": "", "source_turn_indices": []}
  },
  "assessment": {
    "text": "",
    "diagnosis": {"value": "", "source_turn_indices": []}
  },
  "plan": {
    "text": "",
    "treatment": {"value": "", "source_turn_indices": []},
    "advice": {"value": "", "source_turn_indices": []}
  }
}""",
        required_vars=["transcript"]
    )

    templates["free_soap_generation"] = PromptTemplate(
        template="""你是一个医疗病历撰写专家。请根据以下医患对话，按SOAP格式撰写病历草稿。

## 原始对话
$transcript

## 撰写要求
1. 按以下四段组织内容，每段用标题标注：
   - **S（主观症状）**：患者主诉、现病史、否认症状、既往史
   - **O（客观体征）**：体格检查、辅助检查
   - **A（评估诊断）**：诊断
   - **P（治疗计划）**：治疗方案、医嘱
2. 必须忠实于对话原文，不得添加、推断或改写对话中未明确提及的内容
3. 对话中未提及的信息不要编造，直接不写
4. 时间表述必须与对话原文一致，不得改写（如"7月份至今"不能改为"7月余"）
5. 每段内自由叙述，不需要分字段""",
        required_vars=["transcript"]
    )

    templates["soap_structuring"] = PromptTemplate(
        template="""你是一个医疗病历结构化专家。请将以下自由文本SOAP病历草稿结构化为标准JSON格式。

## 自由文本草稿
$draft_text

## 原始对话（供参考）
$transcript

## 字段说明
- **S**：chief_complaint（主诉）、history_present_illness（现病史）、denied_symptoms（否认症状）、past_history（既往史）
- **O**：physical_examination（体格检查）、auxiliary_examination（辅助检查）
- **A**：diagnosis（诊断）
- **P**：treatment（治疗方案）、advice（医嘱）

每个字段包含 value（文本内容）和 source_turn_indices（对话turn序号数组，从0开始）。
草稿中未提及的字段 value 为空字符串，source_turn_indices 为空数组。

## 结构化原则
1. 以草稿文本为主要依据，从草稿中提取各字段内容
2. 不得添加草稿中未出现的内容
3. source_turn_indices 标注该字段内容引用了哪些对话turn序号

## 输出JSON格式
{
  "subjective": {
    "text": "",
    "chief_complaint": {"value": "", "source_turn_indices": []},
    "history_present_illness": {"value": "", "source_turn_indices": []},
    "denied_symptoms": {"value": "", "source_turn_indices": []},
    "past_history": {"value": "", "source_turn_indices": []}
  },
  "objective": {
    "text": "",
    "physical_examination": {"value": "", "source_turn_indices": []},
    "auxiliary_examination": {"value": "", "source_turn_indices": []}
  },
  "assessment": {
    "text": "",
    "diagnosis": {"value": "", "source_turn_indices": []}
  },
  "plan": {
    "text": "",
    "treatment": {"value": "", "source_turn_indices": []},
    "advice": {"value": "", "source_turn_indices": []}
  }
}""",
        required_vars=["draft_text", "transcript"]
    )

    templates["evidence_mapping"] = PromptTemplate(
        template="""你是一个医疗病历证据溯源专家。请为以下SOAP病历内容的每个部分标注来源对话轮次编号。

## 原始对话
$transcript

## SOAP病历
$emr_draft

## 任务说明
为每个SOAP部分的内容找出对应的对话轮次编号（从0开始）。
- 如果某个部分的内容来自多个对话轮次，列出所有相关轮次编号
- 如果某个部分的内容在对话中没有明确依据，返回空数组

## 输出JSON格式
{
  "subjective": {"source_turn_indices": [0, 1, 4]},
  "objective": {"source_turn_indices": [6]},
  "assessment": {"source_turn_indices": [17, 18, 19]},
  "plan": {"source_turn_indices": [22, 24]}
}

请严格按照上述JSON格式输出，不要添加其他字段。""",
        required_vars=["transcript", "emr_draft"]
    )

    return templates


def get_soap_generation_templates_en() -> dict:
    """获取英文SOAP生成模板"""
    templates = {}

    templates["emr_generation"] = PromptTemplate(
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

    templates["emr_generation_with_role"] = PromptTemplate(
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

    templates["free_soap_generation"] = PromptTemplate(
        template="""You are a medical record writing expert. Please write a medical record draft in SOAP format based on the following doctor-patient conversation.

## Original Conversation
$transcript

## Writing Requirements
1. Organize content into the following four sections, each with a heading:
   - **S (Subjective)**: Chief complaint, history of present illness, denied symptoms, past medical history
   - **O (Objective)**: Physical examination, auxiliary examination
   - **A (Assessment)**: Diagnosis
   - **P (Plan)**: Treatment plan, medical advice
2. Must be faithful to the original conversation, do not add, infer, or rewrite content not explicitly mentioned
3. Do not fabricate information not mentioned in the conversation, simply omit it
4. Time expressions must be consistent with the original conversation, do not rewrite (e.g., "since July" cannot be changed to "over 1 month")
5. Write freely within each section, no need to split into fields""",
        required_vars=["transcript"]
    )

    templates["soap_structuring"] = PromptTemplate(
        template="""You are a medical record structuring expert. Please structure the following free-text SOAP medical record draft into standard JSON format.

## Free-text Draft
$draft_text

## Original Conversation (for reference)
$transcript

## Field Descriptions
- **S**: chief_complaint, history_present_illness, denied_symptoms, past_history
- **O**: physical_examination, auxiliary_examination
- **A**: diagnosis
- **P**: treatment, advice

Each field contains value (text content) and source_turn_indices (conversation turn index array, starting from 0).
Fields not mentioned in the draft should have value as empty string and source_turn_indices as empty array.

## Structuring Principles
1. Use the draft text as the primary basis, extract field content from the draft
2. Do not add content not present in the draft
3. source_turn_indices indicates which conversation turn indices the field content references

## Output JSON Format
{
  "subjective": {
    "text": "",
    "chief_complaint": {"value": "", "source_turn_indices": []},
    "history_present_illness": {"value": "", "source_turn_indices": []},
    "denied_symptoms": {"value": "", "source_turn_indices": []},
    "past_history": {"value": "", "source_turn_indices": []}
  },
  "objective": {
    "text": "",
    "physical_examination": {"value": "", "source_turn_indices": []},
    "auxiliary_examination": {"value": "", "source_turn_indices": []}
  },
  "assessment": {
    "text": "",
    "diagnosis": {"value": "", "source_turn_indices": []}
  },
  "plan": {
    "text": "",
    "treatment": {"value": "", "source_turn_indices": []},
    "advice": {"value": "", "source_turn_indices": []}
  }
}""",
        required_vars=["draft_text", "transcript"]
    )

    return templates
