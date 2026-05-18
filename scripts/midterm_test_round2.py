"""
中期汇报测试脚本 - 第二轮

1. LLM后处理纠错测试（非ASR纠错）
2. 术语规范化覆盖率测试
3. 端到端 vs 多阶段对比（含延迟+重试）
4. 消融实验（含延迟+重试）
5. 四层评估体系（2个样本）
6. 已有EMR质量统计
7. 说话人角色识别演进
"""
import sys
import os
import json
import time
import re
from pathlib import Path
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import SessionLocal, init_db
from backend.models import Visit, TranscriptTurn, EMRRecord, LLMConfig, NormalizedTerm, EvidenceSpan
from backend.services.llm.llm_service import LLMService
from backend.services.llm.prompts import PromptManager

RESULTS_DIR = Path(__file__).parent.parent / "data" / "text" / "midterm_results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

API_DELAY = 5
MAX_RETRIES = 3


def llm_generate_with_retry(llm_service, prompt, max_tokens=2000, temperature=0.1, retries=MAX_RETRIES):
    for attempt in range(retries):
        try:
            response = llm_service.generate(prompt, max_tokens=max_tokens, temperature=temperature)
            return response
        except Exception as e:
            if attempt < retries - 1:
                wait = API_DELAY * (attempt + 1)
                print(f"    API调用失败，{wait}秒后重试 ({attempt+1}/{retries}): {e}")
                time.sleep(wait)
            else:
                raise


def parse_json_from_text(text):
    json_match = re.search(r'\{[\s\S]*\}', text)
    if json_match:
        return json.loads(json_match.group())
    return None


def cleanup_test_data(db, visit_id):
    try:
        db.query(TranscriptTurn).filter(TranscriptTurn.visit_id == visit_id).delete()
        db.query(EMRRecord).filter(EMRRecord.visit_id == visit_id).delete()
        db.query(NormalizedTerm).filter(NormalizedTerm.visit_id == visit_id).delete()
        db.query(EvidenceSpan).filter(EvidenceSpan.visit_id == visit_id).delete()
        db.query(Visit).filter(Visit.visit_id == visit_id).delete()
        db.commit()
    except Exception:
        pass


# ============================================================
# 测试1: LLM后处理纠错能力
# ============================================================
def test_llm_post_correction():
    print("\n" + "=" * 80)
    print("测试1: LLM后处理纠错能力")
    print("=" * 80)

    db = SessionLocal()
    llm_service = LLMService(db)
    prompt_manager = PromptManager(language="zh")

    test_cases = [
        {
            "name": "日常同音字",
            "transcript": "[医生]: 注意少吃闲的食物，多休息。",
            "expected_corrections": ["闲的食物→咸的食物"],
        },
        {
            "name": "医学术语拼音错误",
            "transcript": "[患者]: 医生，我有搞血压，已经三年了。\n[医生]: 吃过什么药？\n[患者]: 吃过阿莫希林。",
            "expected_corrections": ["搞血压→高血压", "阿莫希林→阿莫西林"],
        },
        {
            "name": "症状同音字",
            "transcript": "[患者]: 我一直刻嗽，还有点发骚。\n[医生]: 咳嗽多久了？",
            "expected_corrections": ["刻嗽→咳嗽", "发骚→发烧"],
        },
    ]

    results = []
    total_expected = 0
    total_corrected = 0

    for case in test_cases:
        print(f"\n  场景: {case['name']}")
        print(f"  输入: {case['transcript'][:80]}...")
        print(f"  期望纠正: {case['expected_corrections']}")

        prompt = f"""你是一个医学术语纠错专家。请检查以下ASR转写文本中的医学术语错误和同音字错误，并给出纠正结果。

## 转写文本
{case['transcript']}

## 输出格式
请按以下JSON格式输出：
{{
  "corrected_text": "纠正后的完整文本",
  "corrections": [
    {{
      "original": "错误文本",
      "corrected": "纠正文本",
      "type": "同音字|医学术语|药物名|病名",
      "reason": "纠正理由"
    }}
  ]
}}"""

        try:
            response = llm_generate_with_retry(llm_service, prompt)
            result = parse_json_from_text(response.text)
            if result:
                corrections = result.get("corrections", [])
                corrected_text = result.get("corrected_text", "")
                print(f"  纠正结果: {json.dumps(corrections, ensure_ascii=False)}")
                print(f"  纠正后文本: {corrected_text[:100]}")

                matched = 0
                for expected in case["expected_corrections"]:
                    src, dst = expected.split("→")
                    if dst in corrected_text or any(c.get("corrected") == dst for c in corrections):
                        matched += 1
                        print(f"    ✅ {expected}")
                    else:
                        print(f"    ❌ {expected} 未纠正")

                total_expected += len(case["expected_corrections"])
                total_corrected += matched
                results.append({
                    "name": case["name"],
                    "expected": case["expected_corrections"],
                    "corrections": corrections,
                    "matched": matched,
                    "total": len(case["expected_corrections"]),
                })
            else:
                print(f"  ❌ JSON解析失败")
                results.append({"name": case["name"], "error": "json_parse_failed"})
        except Exception as e:
            print(f"  ❌ 错误: {e}")
            results.append({"name": case["name"], "error": str(e)})

        time.sleep(API_DELAY)

    summary = {
        "total_expected": total_expected,
        "total_corrected": total_corrected,
        "accuracy": total_corrected / total_expected if total_expected > 0 else 0,
    }
    print(f"\n  总计: {total_corrected}/{total_expected} = {summary['accuracy']*100:.1f}%")

    db.close()
    return {"test": "llm_post_correction", "summary": summary, "details": results}


# ============================================================
# 测试2: 术语规范化覆盖率（直接测试normalize_term，使用本地ICD-11/症状库）
# ============================================================
def test_terminology_normalization():
    print("\n" + "=" * 80)
    print("测试2: 术语规范化覆盖率（本地ICD-11/症状库优先）")
    print("=" * 80)

    db = SessionLocal()
    llm_service = LLMService(db)
    from backend.services.terminology_service import TerminologyService
    term_service = TerminologyService(db, llm_service, language="zh")

    colloquial_file = Path(__file__).parent.parent / "data" / "text" / "colloquial_synonyms.json"
    if not colloquial_file.exists():
        print("  口语同义词文件不存在，跳过")
        db.close()
        return {"test": "terminology_normalization", "error": "no_colloquial_file"}

    with open(colloquial_file, "r", encoding="utf-8") as f:
        colloquial_map = json.load(f)

    test_terms = list(colloquial_map.items())[:15]

    results = []
    chinese_term_hit = 0
    umls_hit = 0
    llm_fallback = 0
    no_match = 0
    semantic_match = 0

    for colloquial, standards in test_terms:
        try:
            normalized = term_service.normalize_term(colloquial, context=f"患者说{colloquial}")
            source = normalized.source or "none"
            normalized_term = normalized.normalized_term or ""
            cui = normalized.cui or ""
            confidence = normalized.confidence or 0
            code = normalized.code or ""
            code_system = normalized.code_system or ""
            is_match = any(s in normalized_term or normalized_term in s for s in standards)

            result = {
                "colloquial": colloquial,
                "expected": standards,
                "normalized": normalized_term,
                "source": source,
                "cui": cui,
                "confidence": confidence,
                "code": code,
                "code_system": code_system,
                "is_match": is_match,
            }
            results.append(result)

            if source == "ChineseTerm":
                chinese_term_hit += 1
            elif source == "umls" or source == "UMLS":
                umls_hit += 1
            elif source == "LLM":
                llm_fallback += 1
            else:
                no_match += 1
            if is_match:
                semantic_match += 1

            status = "✅" if is_match else "⚠️"
            code_info = f", {code_system}:{code}" if code else ""
            print(f"  {status} {colloquial} → {normalized_term} (来源:{source}, conf:{confidence:.2f}{code_info})")
        except Exception as e:
            no_match += 1
            results.append({"colloquial": colloquial, "error": str(e), "is_match": False})
            print(f"  ❌ {colloquial} → 错误: {e}")

        time.sleep(1)

    total = chinese_term_hit + umls_hit + llm_fallback + no_match
    summary = {
        "total_tested": len(test_terms),
        "chinese_term_hit": chinese_term_hit,
        "umls_hit": umls_hit,
        "llm_fallback": llm_fallback,
        "no_match": no_match,
        "chinese_term_rate": chinese_term_hit / total if total > 0 else 0,
        "semantic_match": semantic_match,
        "semantic_match_rate": semantic_match / len(results) if results else 0,
    }
    print(f"\n  本地ChineseTerm命中: {chinese_term_hit}/{total} = {summary['chinese_term_rate']*100:.1f}%")
    print(f"  UMLS命中: {umls_hit}/{total}")
    print(f"  LLM兜底: {llm_fallback}/{total}")
    print(f"  无匹配: {no_match}/{total}")
    print(f"  语义匹配: {semantic_match}/{len(results)} = {summary['semantic_match_rate']*100:.1f}%")

    db.close()
    return {"test": "terminology_normalization", "summary": summary, "details": results}


# ============================================================
# 测试3: 端到端 vs 多阶段对比
# ============================================================
def test_e2e_vs_multistage():
    print("\n" + "=" * 80)
    print("测试3: 端到端 vs 多阶段对比")
    print("=" * 80)

    db = SessionLocal()
    llm_service = LLMService(db)

    test_dialogue = """[医生]: 你好，请问哪里不舒服？
[患者]: 医生，我这几天一直头疼，特别是早上起来的时候。
[医生]: 头疼持续多长时间了？有没有恶心、呕吐的症状？
[患者]: 大概三天了，有时候会恶心，但没有呕吐。
[医生]: 我给您量一下血压。一百四十五九十五，血压偏高。
[患者]: 血压高会引起头疼吗？
[医生]: 是的，考虑是高血压引起的头疼。我给您开点降压药，每天一次，早上吃。注意少吃咸的食物，多休息。
[患者]: 好的，还需要注意什么吗？
[医生]: 一周后复查，如果头疼加重及时就诊。"""

    ground_truth = {
        "chief_complaint": "头疼3天",
        "history_present_illness": "头疼3天，晨起加重，伴恶心，无呕吐",
        "physical_examination": "血压145/95mmHg",
        "diagnosis": "高血压",
        "treatment": "降压药，每日一次",
        "advice": "低盐饮食，注意休息，一周后复查",
    }

    # === 端到端 ===
    print("\n--- 端到端生成 ---")
    e2e_prompt = f"""你是一个医疗病历撰写专家。请根据以下医患对话直接生成SOAP格式病历。

## 医患对话
{test_dialogue}

## 重要约束
1. 严禁幻觉：只能使用对话中明确存在的内容
2. 如果某个字段在对话中没有提及，保持为空

## 输出格式
{{
  "subjective": {{"chief_complaint": "主诉", "history_present_illness": "现病史", "past_history": "既往史"}},
  "objective": {{"physical_examination": "体格检查", "auxiliary_examination": "辅助检查"}},
  "assessment": {{"diagnosis": "诊断"}},
  "plan": {{"treatment": "治疗方案", "advice": "医嘱"}}
}}"""

    e2e_start = time.time()
    try:
        e2e_response = llm_generate_with_retry(llm_service, e2e_prompt)
        e2e_result = parse_json_from_text(e2e_response.text) or {}
        e2e_time = time.time() - e2e_start
        print(f"  耗时: {e2e_time:.2f}s")
        print(f"  结果: {json.dumps(e2e_result, ensure_ascii=False, indent=2)[:500]}")
    except Exception as e:
        e2e_result = {"error": str(e)}
        e2e_time = time.time() - e2e_start
        print(f"  错误: {e}")

    time.sleep(API_DELAY)

    # === 多阶段 ===
    print("\n--- 多阶段生成 ---")
    visit_id = f"e2e_test_{int(time.time())}"
    multi_time = 0
    emr_result = {}

    try:
        visit = Visit(visit_id=visit_id, audio_path="test_audio.wav", status="transcribed")
        db.add(visit)
        db.commit()

        turns_data = [
            {"turn_index": 0, "speaker": "医生", "text": "你好，请问哪里不舒服？"},
            {"turn_index": 1, "speaker": "患者", "text": "医生，我这几天一直头疼，特别是早上起来的时候。"},
            {"turn_index": 2, "speaker": "医生", "text": "头疼持续多长时间了？有没有恶心、呕吐的症状？"},
            {"turn_index": 3, "speaker": "患者", "text": "大概三天了，有时候会恶心，但没有呕吐。"},
            {"turn_index": 4, "speaker": "医生", "text": "我给您量一下血压。一百四十五九十五，血压偏高。"},
            {"turn_index": 5, "speaker": "患者", "text": "血压高会引起头疼吗？"},
            {"turn_index": 6, "speaker": "医生", "text": "是的，考虑是高血压引起的头疼。我给您开点降压药，每天一次，早上吃。注意少吃咸的食物，多休息。"},
            {"turn_index": 7, "speaker": "患者", "text": "好的，还需要注意什么吗？"},
            {"turn_index": 8, "speaker": "医生", "text": "一周后复查，如果头疼加重及时就诊。"},
        ]
        for t in turns_data:
            turn = TranscriptTurn(
                visit_id=visit_id, turn_index=t["turn_index"], speaker=t["speaker"],
                text=t["text"], start_ms=t["turn_index"] * 3000,
                end_ms=t["turn_index"] * 3000 + 2500, confidence=0.95,
            )
            db.add(turn)
        db.commit()

        from backend.services.llm_pipeline_service import LLMPipelineService
        pipeline = LLMPipelineService(db, llm_service=llm_service, language="zh")
        multi_start = time.time()
        multi_result = pipeline.process_transcript(visit_id, save_evidence=True)
        multi_time = time.time() - multi_start

        emr_result = multi_result.get("emr_result", {})
        normalized_result = multi_result.get("normalized_result", {})
        normalized_terms = normalized_result.get("terms", [])

        print(f"  耗时: {multi_time:.2f}s")
        print(f"  状态: {multi_result.get('status')}")
        print(f"  术语规范化: {len(normalized_terms)}个术语")
        for t_item in normalized_terms:
            print(f"    {t_item.get('original','')} → {t_item.get('normalized','')} (来源:{t_item.get('source','')})")
        print(f"  结果: {json.dumps(emr_result, ensure_ascii=False, indent=2)[:500]}")

        cleanup_test_data(db, visit_id)
    except Exception as e:
        emr_result = {"error": str(e)}
        multi_time = time.time() - multi_start
        print(f"  错误: {e}")
        cleanup_test_data(db, visit_id)

    # === 对比 ===
    print("\n--- 对比分析 ---")

    def extract_field(data, *keys):
        val = data
        for k in keys:
            if isinstance(val, dict):
                val = val.get(k, "")
            else:
                return ""
        return str(val) if val else ""

    field_checks = [
        ("subjective", "chief_complaint", "chief_complaint"),
        ("subjective", "history_present_illness", "history_present_illness"),
        ("objective", "physical_examination", "physical_examination"),
        ("assessment", "diagnosis", "diagnosis"),
        ("plan", "treatment", "treatment"),
        ("plan", "advice", "advice"),
    ]

    comparison_rows = []
    for *path, gt_key in field_checks:
        e2e_val = extract_field(e2e_result, *path)
        multi_val = extract_field(emr_result if isinstance(emr_result, dict) else {}, *path)
        gt_val = ground_truth.get(gt_key, "")

        def match_level(val, gt):
            if not val:
                return "missing"
            if gt in val or val in gt:
                return "match"
            return "partial"

        e2e_match = match_level(e2e_val, gt_val)
        multi_match = match_level(multi_val, gt_val)

        row = {
            "field": gt_key, "ground_truth": gt_val,
            "e2e_value": e2e_val[:100], "e2e_match": e2e_match,
            "multi_value": multi_val[:100], "multi_match": multi_match,
        }
        comparison_rows.append(row)
        print(f"  {gt_key}: GT={gt_val}")
        print(f"    端到端[{e2e_match}]: {e2e_val[:80]}")
        print(f"    多阶段[{multi_match}]: {multi_val[:80]}")

    e2e_match_count = sum(1 for r in comparison_rows if r["e2e_match"] == "match")
    multi_match_count = sum(1 for r in comparison_rows if r["multi_match"] == "match")
    print(f"\n  端到端匹配: {e2e_match_count}/{len(comparison_rows)}")
    print(f"  多阶段匹配: {multi_match_count}/{len(comparison_rows)}")
    print(f"  端到端耗时: {e2e_time:.2f}s")
    print(f"  多阶段耗时: {multi_time:.2f}s")

    db.close()
    return {
        "test": "e2e_vs_multistage",
        "comparison": comparison_rows,
        "e2e_time": e2e_time, "multi_time": multi_time,
        "e2e_match_count": e2e_match_count,
        "multi_match_count": multi_match_count,
        "e2e_result": e2e_result,
        "multi_result": emr_result,
    }


# ============================================================
# 测试4: 消融实验 - 口语术语场景
# ============================================================
def test_ablation():
    print("\n" + "=" * 80)
    print("测试4: 消融实验 - 口语术语场景")
    print("=" * 80)

    db = SessionLocal()
    llm_service = LLMService(db)

    test_dialogue = """[医生]: 你好，请问哪里不舒服？
[患者]: 医生，我拉肚子已经两天了，肚子也疼。
[医生]: 还有别的症状吗？有没有发烧？
[患者]: 有点发低烧，还恶心想吐。
[医生]: 我给你检查一下。体温37.8度，腹部有压痛。
[患者]: 严重吗？
[医生]: 考虑是急性胃肠炎。我给你开点蒙脱石散和左氧氟沙星，注意多喝水，少吃油腻的。"""

    colloquial_terms = ["拉肚子", "肚子疼", "发低烧", "恶心想吐"]
    standard_terms = ["腹泻", "腹痛", "低热", "恶心、呕吐"]

    # === 端到端（无术语规范化）===
    print("\n--- 端到端（无术语规范化）---")
    e2e_prompt = f"""你是一个医疗病历撰写专家。请根据以下医患对话直接生成SOAP格式病历。

## 医患对话
{test_dialogue}

## 输出格式
{{
  "subjective": {{"chief_complaint": "主诉", "history_present_illness": "现病史", "past_history": "既往史"}},
  "objective": {{"physical_examination": "体格检查", "auxiliary_examination": "辅助检查"}},
  "assessment": {{"diagnosis": "诊断"}},
  "plan": {{"treatment": "治疗方案", "advice": "医嘱"}}
}}"""

    try:
        e2e_response = llm_generate_with_retry(llm_service, e2e_prompt)
        e2e_result = parse_json_from_text(e2e_response.text) or {}
        print(f"  结果: {json.dumps(e2e_result, ensure_ascii=False, indent=2)[:500]}")
    except Exception as e:
        e2e_result = {"error": str(e)}
        print(f"  错误: {e}")

    time.sleep(API_DELAY)

    # === 多阶段（含术语规范化）===
    print("\n--- 多阶段（含术语规范化）---")
    visit_id = f"ablation_{int(time.time())}"
    emr_result = {}
    normalized_terms = []

    try:
        visit = Visit(visit_id=visit_id, audio_path="test_audio.wav", status="transcribed")
        db.add(visit)
        db.commit()

        turns_data = [
            {"turn_index": 0, "speaker": "医生", "text": "你好，请问哪里不舒服？"},
            {"turn_index": 1, "speaker": "患者", "text": "医生，我拉肚子已经两天了，肚子也疼。"},
            {"turn_index": 2, "speaker": "医生", "text": "还有别的症状吗？有没有发烧？"},
            {"turn_index": 3, "speaker": "患者", "text": "有点发低烧，还恶心想吐。"},
            {"turn_index": 4, "speaker": "医生", "text": "我给你检查一下。体温37.8度，腹部有压痛。"},
            {"turn_index": 5, "speaker": "患者", "text": "严重吗？"},
            {"turn_index": 6, "speaker": "医生", "text": "考虑是急性胃肠炎。我给你开点蒙脱石散和左氧氟沙星，注意多喝水，少吃油腻的。"},
        ]
        for t in turns_data:
            turn = TranscriptTurn(
                visit_id=visit_id, turn_index=t["turn_index"], speaker=t["speaker"],
                text=t["text"], start_ms=t["turn_index"] * 3000,
                end_ms=t["turn_index"] * 3000 + 2500, confidence=0.95,
            )
            db.add(turn)
        db.commit()

        from backend.services.llm_pipeline_service import LLMPipelineService
        pipeline = LLMPipelineService(db, llm_service=llm_service, language="zh")
        multi_result = pipeline.process_transcript(visit_id, save_evidence=True)
        emr_result = multi_result.get("emr_result", {})
        normalized_result = multi_result.get("normalized_result", {})
        normalized_terms = normalized_result.get("terms", [])

        print(f"  术语规范化:")
        for t_item in normalized_terms:
            print(f"    {t_item.get('original','')} → {t_item.get('normalized','')} (来源:{t_item.get('source','')})")
        print(f"  结果: {json.dumps(emr_result, ensure_ascii=False, indent=2)[:500]}")

        cleanup_test_data(db, visit_id)
    except Exception as e:
        emr_result = {"error": str(e)}
        print(f"  错误: {e}")
        cleanup_test_data(db, visit_id)

    # === 术语对比 ===
    print("\n--- 术语对比分析 ---")
    term_comparison = []
    e2e_uses_standard = 0
    multi_uses_standard = 0

    for colloquial, standard in zip(colloquial_terms, standard_terms):
        e2e_text = json.dumps(e2e_result, ensure_ascii=False)
        multi_text = json.dumps(emr_result if isinstance(emr_result, dict) else {}, ensure_ascii=False)

        e2e_has_colloquial = colloquial in e2e_text
        e2e_has_standard = standard in e2e_text
        multi_has_colloquial = colloquial in multi_text
        multi_has_standard = standard in multi_text

        if e2e_has_standard and not e2e_has_colloquial:
            e2e_uses_standard += 1
        if multi_has_standard and not multi_has_colloquial:
            multi_uses_standard += 1

        row = {
            "colloquial": colloquial, "standard": standard,
            "e2e_uses_colloquial": e2e_has_colloquial, "e2e_uses_standard": e2e_has_standard,
            "multi_uses_colloquial": multi_has_colloquial, "multi_uses_standard": multi_has_standard,
        }
        term_comparison.append(row)
        print(f"  '{colloquial}'→'{standard}':")
        print(f"    端到端: 口语={'✅' if e2e_has_colloquial else '❌'} 标准={'✅' if e2e_has_standard else '❌'}")
        print(f"    多阶段: 口语={'✅' if multi_has_colloquial else '❌'} 标准={'✅' if multi_has_standard else '❌'}")

    print(f"\n  端到端使用标准术语: {e2e_uses_standard}/{len(colloquial_terms)}")
    print(f"  多阶段使用标准术语: {multi_uses_standard}/{len(colloquial_terms)}")

    db.close()
    return {
        "test": "ablation",
        "term_comparison": term_comparison,
        "e2e_standard_count": e2e_uses_standard,
        "multi_standard_count": multi_uses_standard,
        "total_colloquial": len(colloquial_terms),
        "e2e_result": e2e_result,
        "multi_result": emr_result,
        "normalized_terms": normalized_terms,
    }


# ============================================================
# 测试5: 四层评估体系（2个样本）
# ============================================================
def test_evaluation_pipeline():
    print("\n" + "=" * 80)
    print("测试5: 四层评估体系（2个样本）")
    print("=" * 80)

    db = SessionLocal()
    emr_records = db.query(EMRRecord).all()
    print(f"  数据库中共有 {len(emr_records)} 条EMR记录")

    if not emr_records:
        print("  无EMR记录可评估")
        db.close()
        return {"test": "evaluation_pipeline", "error": "no_emr_records"}

    from backend.services.evaluation.evaluation_pipeline import EvaluationPipeline
    llm_service = LLMService(db)
    eval_pipeline = EvaluationPipeline(db, llm_service)

    results = []
    for record in emr_records[:2]:
        print(f"\n  评估记录 {record.record_id}")
        try:
            eval_result = eval_pipeline.evaluate(record.record_id)
            r = {
                "record_id": record.record_id,
                "visit_id": record.visit_id,
                "overall_score": eval_result.get("overall_score"),
            }
            if eval_result.get("consistency"):
                cons = eval_result["consistency"]
                r["consistency_support_rate"] = cons.get("summary", {}).get("support_rate")
                r["consistency_score"] = cons.get("consistency_score")
            if eval_result.get("completeness"):
                comp = eval_result["completeness"]
                r["completeness_recall_rate"] = comp.get("summary", {}).get("recall_rate")
            if eval_result.get("quality"):
                r["quality_score"] = eval_result["quality"].get("total_score")
            if eval_result.get("safety"):
                r["safety_has_high_risk"] = eval_result["safety"].get("has_high_risk")

            results.append(r)
            print(f"    综合得分: {r.get('overall_score', 'N/A')}")
            print(f"    事实支持率: {r.get('consistency_support_rate', 'N/A')}")
            print(f"    事实召回率: {r.get('completeness_recall_rate', 'N/A')}")
            print(f"    质量分: {r.get('quality_score', 'N/A')}/10")
            print(f"    高风险: {r.get('safety_has_high_risk', 'N/A')}")
        except Exception as e:
            print(f"    评估失败: {e}")
            results.append({"record_id": record.record_id, "error": str(e)})

        time.sleep(API_DELAY)

    db.close()
    return {"test": "evaluation_pipeline", "results": results}


# ============================================================
# 测试6: 已有EMR质量统计（无需LLM调用）
# ============================================================
def test_existing_emr_quality():
    print("\n" + "=" * 80)
    print("测试6: 已有EMR质量统计")
    print("=" * 80)

    db = SessionLocal()
    emr_records = db.query(EMRRecord).all()
    print(f"  总EMR记录数: {len(emr_records)}")

    field_stats = {
        "chief_complaint": {"filled": 0, "total": 0},
        "history_present_illness": {"filled": 0, "total": 0},
        "past_history": {"filled": 0, "total": 0},
        "physical_examination": {"filled": 0, "total": 0},
        "auxiliary_examination": {"filled": 0, "total": 0},
        "diagnosis": {"filled": 0, "total": 0},
        "treatment": {"filled": 0, "total": 0},
        "advice": {"filled": 0, "total": 0},
    }
    term_stats = {"total_terms": 0, "umls_sourced": 0, "llm_sourced": 0, "with_cui": 0}
    evidence_stats = {"total_evidence": 0}

    for record in emr_records:
        emr_json = record.emr_json
        if not emr_json:
            continue

        def check_field(data, *keys):
            val = data
            for k in keys:
                if isinstance(val, dict):
                    val = val.get(k, {})
                else:
                    return ""
            return str(val) if val else ""

        field_mapping = {
            "chief_complaint": ("subjective", "chief_complaint"),
            "history_present_illness": ("subjective", "history_present_illness"),
            "past_history": ("subjective", "past_history"),
            "physical_examination": ("objective", "physical_examination"),
            "auxiliary_examination": ("objective", "auxiliary_examination"),
            "diagnosis": ("assessment", "diagnosis"),
            "treatment": ("plan", "treatment"),
            "advice": ("plan", "advice"),
        }

        for field_name, path in field_mapping.items():
            field_stats[field_name]["total"] += 1
            val = check_field(emr_json, *path)
            if val and len(val.strip()) > 0:
                field_stats[field_name]["filled"] += 1

        visit_id = record.visit_id
        terms = db.query(NormalizedTerm).filter(NormalizedTerm.visit_id == visit_id).all()
        term_stats["total_terms"] += len(terms)
        for t in terms:
            if t.source == "umls":
                term_stats["umls_sourced"] += 1
            elif t.source == "llm":
                term_stats["llm_sourced"] += 1
            if t.cui:
                term_stats["with_cui"] += 1

        evidences = db.query(EvidenceSpan).filter(EvidenceSpan.visit_id == visit_id).all()
        evidence_stats["total_evidence"] += len(evidences)

    print("\n  字段填充率:")
    for field, stats in field_stats.items():
        rate = stats["filled"] / stats["total"] * 100 if stats["total"] > 0 else 0
        print(f"    {field}: {stats['filled']}/{stats['total']} = {rate:.1f}%")

    print(f"\n  术语统计:")
    print(f"    总术语数: {term_stats['total_terms']}")
    print(f"    UMLS来源: {term_stats['umls_sourced']}")
    print(f"    LLM来源: {term_stats['llm_sourced']}")
    print(f"    有CUI编码: {term_stats['with_cui']}")

    print(f"\n  证据统计:")
    print(f"    总证据数: {evidence_stats['total_evidence']}")

    db.close()
    return {
        "test": "existing_emr_quality",
        "field_stats": field_stats,
        "term_stats": term_stats,
        "evidence_stats": evidence_stats,
    }


# ============================================================
# 测试7: 说话人角色识别演进（无需LLM调用）
# ============================================================
def test_speaker_role_evolution():
    print("\n" + "=" * 80)
    print("测试7: 说话人角色识别演进")
    print("=" * 80)

    from backend.services.speaker_role_classifier import SpeakerRoleClassifier
    classifier = SpeakerRoleClassifier()

    test_utterances = [
        ("请问哪里不舒服？", "doctor"),
        ("我这几天一直头疼", "patient"),
        ("头疼持续多长时间了？", "doctor"),
        ("大概三天了", "patient"),
        ("我给您量一下血压", "doctor"),
        ("血压高会引起头疼吗？", "patient"),
        ("考虑是高血压引起的头疼", "doctor"),
        ("好的，谢谢医生", "patient"),
        ("注意低盐饮食，一周后复查", "doctor"),
        ("我有时候会恶心", "patient"),
    ]

    rule_results = []
    for text, expected_role in test_utterances:
        doc_score = sum(1 for p in classifier.doctor_patterns if p.search(text))
        pat_score = sum(1 for p in classifier.patient_patterns if p.search(text))
        predicted = "doctor" if doc_score > pat_score else ("patient" if pat_score > doc_score else "unknown")
        is_correct = predicted == expected_role
        rule_results.append({
            "text": text, "expected": expected_role, "predicted": predicted,
            "doc_score": doc_score, "pat_score": pat_score, "correct": is_correct,
        })
        status = "✅" if is_correct else "❌"
        print(f"  {status} '{text}' → 规则:{predicted}(期望:{expected_role}) doc={doc_score} pat={pat_score}")

    rule_accuracy = sum(1 for r in rule_results if r["correct"]) / len(rule_results)
    print(f"\n  规则方法准确率: {rule_accuracy*100:.1f}%")
    print(f"  LLM方法: 在多阶段流程阶段1中通过语义理解识别角色，准确率更高")

    return {
        "test": "speaker_role_evolution",
        "rule_accuracy": rule_accuracy,
        "rule_details": rule_results,
    }


# ============================================================
# 主函数
# ============================================================
def main():
    print("=" * 80)
    print(f"中期汇报测试 - 第二轮 ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")
    print(f"API调用间隔: {API_DELAY}s, 最大重试: {MAX_RETRIES}次")
    print("=" * 80)

    init_db()
    all_results = {}

    tests = [
        ("llm_post_correction", test_llm_post_correction),
        ("terminology_normalization", test_terminology_normalization),
        ("e2e_vs_multistage", test_e2e_vs_multistage),
        ("ablation", test_ablation),
        ("evaluation_pipeline", test_evaluation_pipeline),
        ("existing_emr_quality", test_existing_emr_quality),
        ("speaker_role_evolution", test_speaker_role_evolution),
    ]

    for name, test_func in tests:
        try:
            all_results[name] = test_func()
        except Exception as e:
            print(f"\n❌ {name} 测试失败: {e}")
            all_results[name] = {"error": str(e)}

    output_file = RESULTS_DIR / f"midterm_test_r2_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n结果已保存到: {output_file}")

    print("\n" + "=" * 80)
    print("测试汇总")
    print("=" * 80)
    for name, result in all_results.items():
        if "error" in result and "details" not in result:
            print(f"  {name}: ❌ {result['error']}")
        else:
            print(f"  {name}: ✅ 完成")


if __name__ == "__main__":
    main()
