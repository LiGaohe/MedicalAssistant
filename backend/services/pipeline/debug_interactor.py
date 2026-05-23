import sys
from typing import Optional
from ...utils.logger import logger


class DebugInteractor:
    def __init__(self, llm_service=None):
        self.llm_service = llm_service

    def interact(
        self,
        stage: str,
        prompt: str,
        **context
    ) -> str:
        if not sys.stdin.isatty():
            logger.warning(f"DEBUG模式在HTTP请求中不可用，跳过阶段: {stage}")
            raise RuntimeError(f"DEBUG模式需要在终端中运行。阶段: {stage}")

        print("\n" + "=" * 80)
        print(f"[DEBUG模式] 阶段: {stage}")
        print("=" * 80)
        print("\n>>> 即将发送给大模型的完整内容：\n")
        print(prompt)
        print("\n" + "-" * 80)

        while True:
            try:
                user_input = input("\n请选择操作：\n  y - 确认发送给大模型\n  n - 不发送，手动输入结果\n  q - 取消操作\n\n请输入选择: ").strip().lower()
            except EOFError:
                logger.warning("无法读取用户输入，跳过DEBUG交互")
                raise RuntimeError("DEBUG模式需要终端交互")

            if user_input == 'y':
                if not self.llm_service:
                    print("\n[警告] LLM服务不可用！请先配置LLM或选择 'n' 手动输入结果。")
                    continue

                try:
                    print("\n>>> 正在调用大模型...")
                    response = self.llm_service.generate(prompt)
                    print("\n>>> 大模型返回结果：\n")
                    print(response.text)
                    return response.text
                except Exception as e:
                    print(f"\n[错误] LLM调用失败: {e}")
                    print("请选择 'n' 手动输入结果，或 'q' 取消操作。")
                    continue

            elif user_input == 'n':
                print("\n" + "=" * 80)
                print(">>> 手动输入模式")
                print("=" * 80)
                print(f"\n阶段: {stage}")
                print("\n指导步骤：")

                if stage == "turn_cleaning":
                    print("""
1. 判断每个turn的说话人角色（doctor/patient），纠正ASR角色分配错误
2. 修正明显的ASR文本错误（同音字、医学术语拼写错误）
3. 不确定则保留原文，correction_confidence设为"low"
4. 严禁添加原文没有的信息

按JSON格式输出：
{
  "turns": [{
    "turn_id": 0,
    "speaker_role": "doctor或patient",
    "corrected_text": "修正后文本",
    "changed_spans": [{"original": "原词", "corrected": "修正词", "position": "位置"}],
    "correction_confidence": "high|medium|low",
    "reason": "理由"
  }]
}
""")
                elif stage == "fact_extraction":
                    print("""
从对话轮次中抽取原子级临床事实。每条事实是不可再分的独立陈述。

字段说明：
- section_candidate: S / O / A / P
- concept_type: symptom / disease / test / drug / plan / other
- mention: 对话中的原始口语表述
- polarity: present / absent / possible / planned / recommended
- temporality: current / past / unknown
- certainty: explicit / supported / weak
- speaker: patient / doctor
- evidence_turn_ids: 支撑事实的turn_id列表
- evidence_text: 对应的原文片段列表

严禁编造事实。同一事实在多轮提及则合并。

按JSON格式输出：
{
  "facts": [{
    "section_candidate": "S",
    "concept_type": "symptom",
    "mention": "原文",
    "polarity": "present",
    "temporality": "current",
    "certainty": "supported",
    "speaker": "patient",
    "evidence_turn_ids": [0],
    "evidence_text": ["原文"]
  }]
}
""")
                elif stage == "emr_generation_so":
                    print("""
根据事实表生成病历的S(主观)和O(客观)部分，不可生成诊断和计划。

S部分（仅患者角度）：
- chief_complaint: 主诉
- history_present_illness: 现病史
- denied_symptoms: 否认症状
- past_history: 既往史

O部分（仅医方检查结果）：
- physical_examination: 体格检查
- auxiliary_examination: 辅助检查

规则：每句话必须对应事实表fact_id；优先用normalized_term；无证据则留空。

按JSON格式输出：
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
  "used_fact_ids": ["fact_id_1"]
}
""")
                elif stage == "emr_generation_assessment":
                    print("""
按三层诊断策略生成评估(A)：

1. 明确诊断(explicit_diagnosis)：certainty=explicit,disease,doctor → 直接写疾病名
2. 倾向性诊断(suspected_diagnosis)：仅有supported证据 → 用"考虑XXX""XXX待排"
3. 症状性评估(symptom_based)：仅有症状 → 只描述症状，禁止发明疾病名

assessment_items每项含：text, certainty_level(high/medium/low), supporting_fact_ids, diagnosis_type

严禁编造诊断。无诊断级事实时只做症状性评估。

按JSON格式输出：
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
}
""")
                elif stage == "emr_generation_plan":
                    print("""
生成病历的计划(P)，拆分为4个子字段：

1. medications（用药方案）：name, dosage, frequency, duration, used_fact_ids
2. tests（检查建议）：name, reason, used_fact_ids
3. follow_up（复诊）：text, used_fact_ids
4. education（健康教育）：text, used_fact_ids

每条计划必须有事实依据。无证据则留空。优先用normalized_term。

按JSON格式输出：
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
}
""")
                elif stage == "verification":
                    print("""
对SOAP草稿进行四个维度核查并修订：

1. 无证据声明(unsupported_claims)：标记病历中无事实支撑的声明
2. 遗漏关键事实(missing_critical_facts)：标记高重要性事实是否被遗漏
3. 内部冲突(internal_conflicts)：检查age/gender/body_part/time/negation/drug_name矛盾
4. 确定性错误(certainty_errors)：检查疑似诊断是否被写成明确诊断

修订优先级：删除无证据声明 → 补充遗漏事实 → 修正矛盾和确定性错误

按JSON格式输出：
{
  "issues": {
    "unsupported_claims": [{"claim_text": "", "soap_location": "", "reason": ""}],
    "missing_critical_facts": [{"fact_id": "", "fact_content": "", "importance_reason": ""}],
    "internal_conflicts": [{"conflict_type": "", "location_1": "", "content_1": "", "location_2": "", "content_2": ""}],
    "certainty_errors": [{"soap_text": "", "correct_certainty": "", "reason": ""}]
  },
  "soap_final": {"subjective": {...}, "objective": {...}, "assessment": {...}, "plan": {...}}
}
如果某维度无问题，对应数组为空。
""")
                elif stage == "role_annotation":
                    print("""
[DEPRECATED] 该阶段已废弃。新版流程使用 turn_cleaning + fact_extraction 替代。
""")
                elif stage == "term_normalization":
                    print("""
[DEPRECATED] 全文本术语规范化已废弃。新版使用基于事实表的逐条规范化(阶段3)，不需要手动输入。
""")
                elif stage == "field_extraction":
                    print("""
[DEPRECATED] 字段抽取阶段已废弃。新版流程中事实表本身已是结构化数据。
""")
                elif stage == "emr_generation":
                    print("""
[DEPRECATED] 旧版单体病历生成已废弃。新版使用分节生成(emr_generation_so + emr_generation_assessment + emr_generation_plan)。
""")

                print("\n请输入大模型的返回结果（JSON格式）：")
                print("（输入完成后按回车，然后输入 'END' 并回车结束）\n")

                lines = []
                while True:
                    line = input()
                    if line.strip() == "END":
                        break
                    lines.append(line)

                result = "\n".join(lines)
                print("\n>>> 已接收手动输入的结果")
                return result

            elif user_input == 'q':
                print("\n>>> 操作已取消")
                raise RuntimeError("User cancelled the operation")

            else:
                print("\n无效输入，请重新选择。")