"""质量核查阶段提示词模板"""
from .template import PromptTemplate


def get_quality_check_templates_zh() -> dict:
    """获取中文质量核查模板"""
    templates = {}

    templates["checklist_verification"] = PromptTemplate(
        template="""你是一个医疗病历审核专家。请检查以下SOAP病历草稿是否遗漏了对话中的**关键信息**。

## 原始对话
$transcript

## SOAP草稿
$draft_emr

## 检查清单
请逐项检查以下内容是否遗漏：

### 1. 主诉完整性
- 对话中患者明确表述的主诉症状是否完整记录？
- 症状持续时间是否记录？
- 就诊原因是否体现？

### 2. 关键阳性/阴性症状
- 对话中患者明确表述的关键阳性症状是否全部记录？
- 患者明确否认的症状（医生主动询问的）是否记录？
- 伴随症状是否完整？

### 3. 关键处置建议
- 医生明确给出的用药方案是否完整记录？
- 医生明确建议的检查项目是否记录？
- 医生明确要求的复诊安排是否记录？
- 医生明确给出的健康教育/注意事项是否记录？

### 4. 既往就诊与用药史
- 对话中提及的既往就诊次数是否记录？
- 既往用药名称及疗效评价是否记录？
- 既往对某种药物无效的陈述是否记录？

### 5. 体温与量化数据
- 对话中提及的体温数值是否记录？
- 发热持续时间是否记录？
- 呕吐/腹泻次数和性状是否记录？

### 6. 否定性事实
- 患者明确否认的症状是否记录到denied_symptoms？
- 患者明确否认的过敏史是否记录？
- 外院检查结果正常（否定性结果）是否记录？

### 7. 外院检查与体格检查
- 对话中提及的外院检查结果是否记录？
- 对话中提及的体格检查发现是否记录？

### 8. 进食与营养状况
- 对话中提及的进食情况是否记录？
- 对话中提及的饮食变化是否记录？

## 输出格式
请严格按照以下JSON格式输出：
{
  "missing_items": [
    {
      "item": "遗漏的具体内容描述",
      "importance": "high|medium|low",
      "soap_section": "S|O|A|P",
      "evidence_text": "对话中的原文依据（证明该信息存在但未被记录）"
    }
  ],
  "summary": {
    "total_missing": N,
    "high_importance_missing": N
  }
}

## 注意事项
- 只报告对话中**确实存在**但病历中**未记录**的信息
- 对话中未提及的内容不算遗漏，不要报告
- importance=high：影响诊断或治疗安全的关键信息（如药物过敏、关键症状、用药方案）
- importance=medium：影响诊断完整性的补充信息
- importance=low：辅助性信息（如一般性健康建议）
- 如果认为病历已完整覆盖对话信息，missing_items为空数组，各项count为0""",
        required_vars=["transcript", "draft_emr"]
    )

    templates["field_revision"] = PromptTemplate(
        template="""你是一个医疗病历修订专家。请根据核查问题清单对SOAP病历草稿做**定点修订**。

## SOAP草稿
$draft_emr

## 核查问题清单
$issues_json

## 原始对话（供核实）
$transcript

## 修订原则
**只修改失败的字段，其他字段严格保持不变。**

### 修订规则

#### 1. unsupported claim → 删除或改弱措辞
- 如果claim在对话中完全无依据：删除该claim对应的内容
- 如果claim的确定性被高估：改为更弱的措辞（如"确诊XXX"改为"考虑XXX"）

#### 2. missing item → 如果对话有依据则补充
- 从original transcript中找到对应原文
- 将内容补充到对应的SOAP字段中
- 补充时保持与原有内容的风格一致
- 如果对话中确实没有依据，则不要补充

#### 3. 确定性错误 → 降级
- 将明确诊断(explicit_diagnosis)降级为倾向性诊断(suspected_diagnosis)
- 将倾向性诊断降级为症状性评估(symptom_based_assessment)
- 对应assessment_items中的diagnosis_type和certainty_level同步更新

## 输出格式
输出修订后的完整SOAP JSON，格式必须与草稿完全一致（含value和source_turn_indices）：
{
  "subjective": {
    "text": "...",
    "chief_complaint": {"value": "...", "source_turn_indices": [0, 1]},
    "history_present_illness": {"value": "...", "source_turn_indices": [2, 3]},
    "denied_symptoms": {"value": "...", "source_turn_indices": []},
    "past_history": {"value": "...", "source_turn_indices": []}
  },
  "objective": {
    "text": "...",
    "physical_examination": {"value": "...", "source_turn_indices": []},
    "auxiliary_examination": {"value": "...", "source_turn_indices": []}
  },
  "assessment": {
    "text": "...",
    "diagnosis": {"value": "...", "source_turn_indices": []},
    "assessment_items": [
      {
        "text": "...",
        "certainty_level": "high",
        "source_turn_indices": [],
        "diagnosis_type": "explicit_diagnosis"
      }
    ]
  },
  "plan": {
    "text": "...",
    "treatment": {"value": "...", "source_turn_indices": []},
    "advice": {"value": "...", "source_turn_indices": []},
    "plan_items": {
      "medications": [{"name": "", "dosage": "", "frequency": "", "duration": "", "source_turn_indices": []}],
      "tests": [{"name": "", "reason": "", "source_turn_indices": []}],
      "follow_up": {"text": "", "source_turn_indices": []},
      "education": {"text": "", "source_turn_indices": []}
    }
  }
}

## 注意事项
- 严禁重写整份SOAP，只做最小化定点修订
- 未涉及问题的字段必须原样保留，不得修改
- source_turn_indices必须保持准确：删除内容时清空对应数组，补充内容时填入正确的turn序号""",
        required_vars=["draft_emr", "issues_json", "transcript"]
    )

    templates["field_revision_patch"] = PromptTemplate(
        template="""你是一个医疗病历修订专家。请根据核查问题清单，对SOAP病历草稿做**定点修订**。
你只需要输出需要修改的字段（补丁），不需要输出完整的SOAP。

**注意：无证据声明（unsupported_claims）已由程序自动删除，你不需要处理。你只需处理以下三类问题。**

## 需要修订的字段（从核查问题中定位）
$affected_fields

## 核查问题清单
$issues_json

## 原始对话（供核实）
$transcript

## 修订规则

### 1. missing item → 如果对话有依据则补充
- 从对话中找到对应原文，填入对应字段的value
- 补充的内容应与对话原文一致，不得推断或编造对话中未提及的内容
- source_turn_indices填入对话中的turn序号
- 如果对话中确实没有依据，则不输出该字段的补丁

### 2. 确定性错误 → 降级
- 将diagnosis_type降级：explicit_diagnosis → suspected_diagnosis → symptom_based_assessment
- 将certainty_level降级：high → medium → low
- 降级时只修改diagnosis_type和certainty_level字段，**不要修改诊断文本本身**
- 如果需要修改assessment_items中的某一项，只改diagnosis_type和certainty_level，其余字段原样保留

### 3. hard_rule_violation → 根据描述修正
- 按违规描述修正对应字段
- 修正时同样不得引入对话中没有的新内容

## 输出格式
只输出需要修改的字段补丁，格式为JSON数组。每个补丁包含path（字段路径）和value（新值）：

```json
{
  "patches": [
    {
      "path": "assessment.assessment_items",
      "value": [{"text": "考虑上呼吸道感染", "certainty_level": "medium", "source_turn_indices": [13], "diagnosis_type": "suspected_diagnosis"}]
    }
  ]
}
```

### path格式说明
- 普通字段：`section.field`，如 `assessment.diagnosis`、`plan.treatment`
- 数组字段：`section.array_field`，如 `assessment.assessment_items`，value为完整的新数组
- text字段：`section.text`，如 `subjective.text`

### 注意事项
- 只输出需要修改的字段，未涉及的字段不要输出
- value的格式必须与SOAP草稿中对应字段的格式一致（含value和source_turn_indices）
- 如果某个问题不需要修改（如对话中确实没有依据补充遗漏项），则不输出对应补丁
- 如果没有任何需要修改的字段，输出空数组：{"patches": []}
- **严禁重写整份SOAP，只做最小化定点修订**
- **严禁引入对话中没有的新内容**""",
        required_vars=["affected_fields", "issues_json", "transcript"]
    )

    templates["certainty_verification"] = PromptTemplate(
        template="""你是一个医疗病历审核专家。请检查以下SOAP病历草稿的A（评估）部分中诊断的**确定性层级**是否被拔高。

## 原始对话
$transcript

## SOAP草稿（仅A部分）
$assessment_json

## 任务
逐条检查assessment_items中的diagnosis_type和certainty_level是否与对话原文匹配：

### 判定规则
1. **explicit_diagnosis 检查**：如果 diagnosis_type=explicit_diagnosis，必须在对话中找到医生**明确下诊断**的原文
   - 医生明确说"你是XX病""诊断是XX""确诊XX" → 有效
   - 医生说"可能是XX""考虑XX""不排除XX""倾向XX" → **确定性被拔高**，应标记为certainty_mismatch
2. **certainty_level 检查**：dialogue证据力度与certainty_level不匹配
   - high：对话中有明确诊断语句
   - medium：对话中为倾向性表述
   - low：对话中仅推测或无直接诊断
3. **symptom_based_assessment 检查**：对话中只有症状描述无任何诊断线索时，若有诊断内容则为拔高

### 输出格式
{
  "certainty_errors": [
    {
      "soap_text": "SOAP中的诊断文本",
      "current_diagnosis_type": "explicit_diagnosis",
      "current_certainty_level": "high",
      "correct_diagnosis_type": "suspected_diagnosis",
      "correct_certainty_level": "medium",
      "evidence_text": "对话中表明仅为倾向性诊断的原文",
      "reasoning": "判定理由"
    }
  ],
  "summary": {
    "total_checked": N,
    "errors_found": N
  }
}

## 注意事项
- 如果没有发现确定性错误，certainty_errors为空数组，summary中errors_found为0
- 只检查确定性层级被拔高的情况，不检查降级（保守偏向安全侧）
- 不确定则不标记，避免误报""",
        required_vars=["transcript", "assessment_json"]
    )

    return templates


def get_quality_check_templates_en() -> dict:
    """获取英文质量核查模板（暂无，返回空字典）"""
    return {}
