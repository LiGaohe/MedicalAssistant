"""术语处理阶段提示词模板"""
from .template import PromptTemplate


def get_terminology_templates_zh() -> dict:
    """获取中文术语处理模板"""
    templates = {}

    templates["term_standardization"] = PromptTemplate(
        template="""你是医学术语规范化助手。

任务：
对以下候选术语列表进行两项处理：
1. **过滤**：剔除非医学术语的词汇，只保留真正的医学术语
2. **规范化**：将口语化医学术语改写为标准医学用语

## 过滤规则（重要）
以下类型的词**不是医学术语**，必须从输出中移除：
- 普通动词："出现"、"使用"、"进行"、"给予"、"建议"
- 时间副词："至今"、"期间"、"当时"、"近期"
- 程度副词："反复"、"明显"、"显著"、"为主"
- 通用名词："患者"、"药物"、"原因"、"问题"
- 连词/介词："及其"、"以及"、"根据"
- 判断性动词："考虑"、"排除"、"确认"、"待查"
- 状态描述："正常"、"异常"、"好转"、"暂无"、"稳定"
- 地点/机构："当地"、"外院"
- 量词/数词片段："至少"、"十个"、"半个"
- 破碎的语法片段："后易"、"以晨起"、"未行"、"行肺"（这些是分词错误产生的碎片）

**只保留与医学相关的词汇**：症状、疾病名、检查项目、药物名、身体部位、治疗方案等。

## 去重规则
如果多个术语实质相同，只保留一个最优表述：
- "月余" / "1月余" / "一个月余" → 统一为 "1月余"，只输出一次
- "周前" / "1周前" → 统一为 "1周前"
- "疗程" / "半个月" / "半月" → 统一为 "半月"

## 规范化要求
1. 保留原始语义，不把症状升级为诊断
2. 如果术语已足够规范，原样返回
3. 输出为术语（词或短语），不是句子
4. 不输出编码或解释性内容

类型指导：
- symptom（症状）：保留症状属性，补全部位和性质，不升级为诊断
- diagnosis（诊断）：拆解并列和省略表达，避免把症状升级为疾病
- examination（检查）：统一俗称与正式检查名称，明确检查方式和部位
- treatment（治疗）：统一俗称与规范术式名称，明确操作类型和部位

术语列表：
$terms

输出格式（JSON）：
{"医学术语1": "规范化结果1", "医学术语2": "规范化结果2", ...}

注意：
- 只输出JSON，不要输出其他内容
- 非医学术语直接不输出，不要出现在JSON中
- 重复的术语合并为一个输出""",
        required_vars=["terms"]
    )

    templates["extract_medical_terms"] = PromptTemplate(
        template="""你是医学术语提取助手。

任务：
从以下病历草稿文本中，识别并提取所有**真正需要标准化的医学术语**。只提取医学术语，不提取非医学术语。

## 什么是医学术语
- **症状**：咳嗽、发热、淋巴结肿大、鼻塞、流涕、喘息、胸痛、乏力、头晕等
- **体征**：肺部啰音、咽部充血、皮疹、浮肿等
- **疾病名称**：支气管哮喘、过敏性鼻炎、贫血、上呼吸道感染、支原体肺炎等
- **检查项目**：血常规、胸片、肺功能检查、支原体抗体检测等
- **药物名称**：免疫调节剂、抗生素、糖皮质激素等
- **治疗方案**：口服给药、雾化吸入、静脉输液等
- **身体部位**：颈部、淋巴结、咽喉、肺部等
- **时间描述与医学结合体**：1周前（作为病程时间描述）、1月余（作为病程时间描述）等

## 什么是非医学术语（必须排除）
- 普通动词/副词："出现"、"使用"、"进行"、"给予"、"建议"、"继续"、"反复"
- 纯时间词："至今"、"期间"、"当时"、"近期"
- 通用名词："患者"、"药物"、"原因"、"问题"
- 连词/介词："及其"、"以及"、"根据"
- 判断动词："考虑"、"排除"、"确认"、"待查"
- 状态描述："正常"、"异常"、"好转"、"暂无"、"稳定"
- 地点/机构："当地"、"外院"
- 量词碎片："至少"、"十个"、"半个"
- 分词错误碎片："后易"、"以晨起"、"未行"、"行肺"、"十声"
- 普通形容词："特殊"、"明确"、"明显"、"显著"

## 去重规则（重要）
如果多个术语描述同一医学概念，只保留最完整的表述：
- "淋巴结" / "淋巴结肿大" / "颈部淋巴结肿大" → 只保留 "颈部淋巴结肿大"
- "月余" / "1月余" → 只保留 "1月余"
- "周前" / "1周前" → 只保留 "1周前"
- "口服" / "口服给药" → 只保留 "口服给药"（如果是给药途径）
- "发烧" / "发热" → 只保留 "发热"

## 术语归类
为每个术语标注类型：
- symptom：症状
- sign：体征
- diagnosis：疾病/诊断
- examination：检查
- drug：药物
- treatment：治疗
- body_part：身体部位

病历文本：
$draft_text

输出格式（JSON数组，只输出JSON）：
[
  {"term": "医学术语1", "type": "类型"},
  {"term": "医学术语2", "type": "类型"}
]

注意：
- 不输出非医学术语
- 不输出重复术语，保留最完整表述
- 不输出破碎的分词片段
- 只输出JSON数组""",
        required_vars=["draft_text"]
    )

    return templates


def get_terminology_templates_en() -> dict:
    """获取英文术语处理模板"""
    templates = {}

    templates["term_standardization"] = PromptTemplate(
        template="""You are a medical terminology standardization assistant.

Task:
Standardize the following colloquial medical terms into formal medical terminology. Output terms (words or short phrases), not sentences.

Requirements:
1. Output only one best standardization result per term
2. Preserve original semantics, do not upgrade symptoms to diagnoses
3. If a term is already standardized, return it as-is
4. Output terms (words or short phrases), not sentences
5. Do not output codes or explanatory content

Type guidance:
- symptom: Preserve symptom attributes, supplement body part and quality; do not upgrade to diagnosis
- diagnosis: Decompose parallel/abbreviated expressions; avoid upgrading symptoms to diseases
- examination: Unify colloquial names with formal examination names; clarify method and body part
- treatment: Unify colloquial names with standard procedure names; clarify procedure type and body part

Terms:
$terms

Output format (JSON):
{"term1": "standardized_result1", "term2": "standardized_result2", ...}

Note: Only output JSON, no other content.""",
        required_vars=["terms"]
    )

    return templates
