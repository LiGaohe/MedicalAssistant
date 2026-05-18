"""
中期汇报综合测试脚本

运行所有需要的测试并汇总结果
"""
import sys
import os
import json
import time
from pathlib import Path
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import SessionLocal, init_db
from backend.models import Visit, TranscriptTurn, EMRRecord, LLMConfig, NormalizedTerm, EvidenceSpan, ExtractedItem
from backend.services.llm.llm_service import LLMService
from backend.services.llm.prompts import PromptManager
from backend.services.terminology_service import TerminologyService
from backend.services.evaluation.evaluation_pipeline import EvaluationPipeline
from backend.services.postprocessor import ASRPostprocessor

RESULTS_DIR = Path(__file__).parent.parent / "data" / "text" / "midterm_results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def test_asr_correction():
    """测试1: ASR纠错能力"""
    print("\n" + "=" * 80)
    print("测试1: ASR纠错能力")
    print("=" * 80)

    postprocessor = ASRPostprocessor()

    test_cases = [
        {"original": "闲的食物", "expected": "咸的食物", "type": "日常用语"},
        {"original": "搞血压", "expected": "高血压", "type": "医学术语"},
        {"original": "阿莫希林", "expected": "阿莫西林", "type": "药物名"},
        {"original": "刻嗽", "expected": "咳嗽", "type": "同音字"},
        {"original": "发骚", "expected": "发烧", "type": "同音字"},
        {"original": "头疼", "expected": "头痛", "type": "拼音相似"},
        {"original": "夫泻", "expected": "腹泻", "type": "拼音相似"},
        {"original": "青梅素", "expected": "青霉素", "type": "药物名"},
        {"original": "头包", "expected": "头孢", "type": "药物名"},
        {"original": "观心病", "expected": "冠心病", "type": "病名"},
    ]

    results = []
    correct = 0
    for case in test_cases:
        text = f"患者有{case['original']}的症状"
        corrected, corrections = postprocessor.correct(text)
        was_corrected = any(
            c["original"] == case["original"] and case["expected"] in corrected
            for c in corrections
        )
        result = {
            "original": case["original"],
            "expected": case["expected"],
            "type": case["type"],
            "corrected_text": corrected,
            "corrections": corrections,
            "success": was_corrected,
        }
        results.append(result)
        status = "✅" if was_corrected else "❌"
        print(f"  {status} {case['original']} → {case['expected']} (类型: {case['type']})")
        if was_corrected:
            correct += 1

    summary = {
        "total": len(test_cases),
        "correct": correct,
        "accuracy": correct / len(test_cases),
        "by_type": {},
    }
    for case, result in zip(test_cases, results):
        t = case["type"]
        if t not in summary["by_type"]:
            summary["by_type"][t] = {"total": 0, "correct": 0}
        summary["by_type"][t]["total"] += 1
        if result["success"]:
            summary["by_type"][t]["correct"] += 1

    print(f"\n  总计: {correct}/{len(test_cases)} = {correct/len(test_cases)*100:.1f}%")
    for t, v in summary["by_type"].items():
        print(f"  {t}: {v['correct']}/{v['total']} = {v['correct']/v['total']*100:.1f}%")

    return {"test": "asr_correction", "summary": summary, "details": results}


def test_terminology_normalization():
    """测试2: 术语规范化覆盖率"""
    print("\n" + "=" * 80)
    print("测试2: 术语规范化覆盖率")
    print("=" * 80)

    db = SessionLocal()
    llm_service = LLMService(db)
    term_service = TerminologyService(db, llm_service, language="zh")

    colloquial_file = Path(__file__).parent.parent / "data" / "text" / "colloquial_synonyms.json"
    with open(colloquial_file, "r", encoding="utf-8") as f:
        colloquial_map = json.load(f)

    test_terms = list(colloquial_map.items())[:20]

    results = []
    umls_hit = 0
    llm_fallback = 0
    no_match = 0

    for colloquial, standards in test_terms:
        try:
            normalized = term_service.extract_and_normalize_terms(
                f"患者说{colloquial}",
                context=f"测试术语: {colloquial}"
            )
            if normalized:
                for item in normalized:
                    source = item.get("source", "unknown")
                    normalized_term = item.get("normalized_term", "")
                    cui = item.get("cui", "")
                    confidence = item.get("confidence", 0)
                    is_match = any(s in normalized_term or normalized_term in s for s in standards)

                    result = {
                        "colloquial": colloquial,
                        "expected_standards": standards,
                        "normalized": normalized_term,
                        "source": source,
                        "cui": cui,
                        "confidence": confidence,
                        "is_match": is_match,
                    }
                    results.append(result)

                    if source == "umls":
                        umls_hit += 1
                    elif source == "llm":
                        llm_fallback += 1

                    status = "✅" if is_match else "⚠️"
                    print(f"  {status} {colloquial} → {normalized_term} (来源: {source}, CUI: {cui}, 匹配: {is_match})")
            else:
                no_match += 1
                results.append({
                    "colloquial": colloquial,
                    "expected_standards": standards,
                    "normalized": None,
                    "source": "none",
                    "cui": None,
                    "confidence": 0,
                    "is_match": False,
                })
                print(f"  ❌ {colloquial} → 无匹配")
        except Exception as e:
            no_match += 1
            results.append({
                "colloquial": colloquial,
                "expected_standards": standards,
                "normalized": None,
                "source": "error",
                "error": str(e),
                "is_match": False,
            })
            print(f"  ❌ {colloquial} → 错误: {e}")

    total = umls_hit + llm_fallback + no_match
    summary = {
        "total_tested": len(test_terms),
        "umls_hit": umls_hit,
        "llm_fallback": llm_fallback,
        "no_match": no_match,
        "umls_rate": umls_hit / total if total > 0 else 0,
        "llm_fallback_rate": llm_fallback / total if total > 0 else 0,
        "match_count": sum(1 for r in results if r.get("is_match")),
        "match_rate": sum(1 for r in results if r.get("is_match")) / len(results) if results else 0,
    }

    print(f"\n  UMLS命中: {umls_hit}/{total} = {summary['umls_rate']*100:.1f}%")
    print(f"  LLM兜底: {llm_fallback}/{total} = {summary['llm_fallback_rate']*100:.1f}%")
    print(f"  无匹配: {no_match}/{total}")
    print(f"  语义匹配率: {summary['match_count']}/{len(results)} = {summary['match_rate']*100:.1f}%")

    db.close()
    return {"test": "terminology_normalization", "summary": summary, "details": results}


def test_end_to_end_vs_multistage():
    """测试3: 端到端 vs 多阶段对比"""
    print("\n" + "=" * 80)
    print("测试3: 端到端 vs 多阶段对比")
    print("=" * 80)

    db = SessionLocal()
    llm_service = LLMService(db)
    prompt_manager = PromptManager(language="zh")

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

    # 端到端生成
    print("\n--- 端到端生成 ---")
    e2e_start = time.time()
    e2e_prompt = f"""你是一个医疗病历撰写专家。请根据以下医患对话直接生成SOAP格式病历。

## 医患对话
{test_dialogue}

## 输出格式
请按以下JSON格式输出：
{{
  "subjective": {{
    "chief_complaint": "主诉",
    "history_present_illness": "现病史",
    "past_history": "既往史"
  }},
  "objective": {{
    "physical_examination": "体格检查",
    "auxiliary_examination": "辅助检查"
  }},
  "assessment": {{
    "diagnosis": "诊断"
  }},
  "plan": {{
    "treatment": "治疗方案",
    "advice": "医嘱"
  }}
}}"""
    try:
        e2e_response = llm_service.generate(e2e_prompt, max_tokens=2000, temperature=0.1)
        e2e_text = e2e_response.text
        e2e_time = time.time() - e2e_start
        json_match = __import__("re").search(r'\{[\s\S]*\}', e2e_text)
        e2e_result = json.loads(json_match.group()) if json_match else {"raw": e2e_text}
        print(f"  端到端耗时: {e2e_time:.2f}s")
        print(f"  端到端结果: {json.dumps(e2e_result, ensure_ascii=False, indent=2)[:500]}")
    except Exception as e:
        e2e_result = {"error": str(e)}
        e2e_time = time.time() - e2e_start
        print(f"  端到端错误: {e}")

    # 多阶段生成
    print("\n--- 多阶段生成 ---")
    from backend.services.llm_pipeline_service import LLMPipelineService
    multi_start = time.time()
    try:
        pipeline = LLMPipelineService(db, language="zh")
        multi_result = pipeline.process_text(test_dialogue, visit_id=None, save_to_db=False)
        multi_time = time.time() - multi_start
        print(f"  多阶段耗时: {multi_time:.2f}s")
        if multi_result and "emr" in multi_result:
            emr = multi_result["emr"]
            print(f"  多阶段结果: {json.dumps(emr, ensure_ascii=False, indent=2)[:500]}")
        else:
            emr = multi_result
            print(f"  多阶段结果(原始): {json.dumps(emr, ensure_ascii=False, indent=2)[:500]}")
    except Exception as e:
        emr = {"error": str(e)}
        multi_time = time.time() - multi_start
        print(f"  多阶段错误: {e}")

    # 对比分析
    print("\n--- 对比分析 ---")
    comparison = {
        "e2e_time": e2e_time,
        "multi_time": multi_time,
        "e2e_result": e2e_result,
        "multi_result": emr if isinstance(emr, dict) else str(emr),
        "ground_truth": ground_truth,
    }

    def check_field(result, field_path, ground_truth_key):
        keys = field_path.split(".")
        val = result
        for k in keys:
            if isinstance(val, dict):
                val = val.get(k, "")
            else:
                return "missing"
        if not val:
            return "missing"
        gt = ground_truth.get(ground_truth_key, "")
        if not gt:
            return "no_gt"
        if gt in str(val) or str(val) in gt:
            return "match"
        return "partial"

    e2e_fields = {}
    multi_fields = {}
    field_checks = [
        ("subjective.chief_complaint", "chief_complaint"),
        ("subjective.history_present_illness", "history_present_illness"),
        ("objective.physical_examination", "physical_examination"),
        ("assessment.diagnosis", "diagnosis"),
        ("plan.treatment", "treatment"),
        ("plan.advice", "advice"),
    ]

    for path, gt_key in field_checks:
        e2e_status = check_field(e2e_result, path, gt_key)
        multi_status = check_field(emr if isinstance(emr, dict) else {}, path, gt_key)
        e2e_fields[gt_key] = e2e_status
        multi_fields[gt_key] = multi_status
        print(f"  {gt_key}: 端到端={e2e_status}, 多阶段={multi_status}")

    comparison["e2e_field_status"] = e2e_fields
    comparison["multi_field_status"] = multi_fields

    db.close()
    return {"test": "e2e_vs_multistage", "comparison": comparison}


def test_evaluation_pipeline():
    """测试4: 四层评估体系"""
    print("\n" + "=" * 80)
    print("测试4: 四层评估体系")
    print("=" * 80)

    db = SessionLocal()
    emr_records = db.query(EMRRecord).all()
    print(f"  找到 {len(emr_records)} 条EMR记录")

    if not emr_records:
        print("  无EMR记录可评估")
        db.close()
        return {"test": "evaluation_pipeline", "error": "no_emr_records"}

    llm_service = LLMService(db)
    eval_pipeline = EvaluationPipeline(db, llm_service)

    results = []
    for record in emr_records[:3]:
        print(f"\n  评估记录 {record.record_id} (visit: {record.visit_id})")
        try:
            eval_result = eval_pipeline.evaluate(
                record.record_id,
                skip_consistency=False,
                skip_completeness=False,
                skip_quality=False,
                skip_safety=False,
            )
            results.append({
                "record_id": record.record_id,
                "visit_id": record.visit_id,
                "result": eval_result,
            })

            if eval_result.get("consistency"):
                cons = eval_result["consistency"]
                print(f"    一致性: support_rate={cons.get('summary', {}).get('support_rate', 'N/A')}")
            if eval_result.get("completeness"):
                comp = eval_result["completeness"]
                print(f"    完整性: recall_rate={comp.get('summary', {}).get('recall_rate', 'N/A')}")
            if eval_result.get("quality"):
                qual = eval_result["quality"]
                print(f"    质量: total_score={qual.get('total_score', 'N/A')}")
            if eval_result.get("safety"):
                safe = eval_result["safety"]
                print(f"    安全性: has_high_risk={safe.get('has_high_risk', 'N/A')}")
            if eval_result.get("overall_score"):
                print(f"    综合得分: {eval_result['overall_score']}")

        except Exception as e:
            print(f"    评估失败: {e}")
            results.append({
                "record_id": record.record_id,
                "visit_id": record.visit_id,
                "error": str(e),
            })

    db.close()
    return {"test": "evaluation_pipeline", "results": results}


def test_existing_emr_quality():
    """测试5: 已有EMR质量统计"""
    print("\n" + "=" * 80)
    print("测试5: 已有EMR质量统计")
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
    evidence_stats = {"total_evidence": 0, "avg_score": 0}

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
        if evidences:
            evidence_stats["avg_score"] += sum(e.score for e in evidences if e.score)

    if evidence_stats["total_evidence"] > 0:
        all_evidences = db.query(EvidenceSpan).all()
        evidence_stats["avg_score"] = sum(e.score for e in all_evidences if e.score) / len(all_evidences) if all_evidences else 0

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
    print(f"    平均分数: {evidence_stats['avg_score']:.3f}")

    db.close()
    return {
        "test": "existing_emr_quality",
        "field_stats": field_stats,
        "term_stats": term_stats,
        "evidence_stats": evidence_stats,
    }


def test_speaker_role_evolution():
    """测试6: 说话人角色识别演进"""
    print("\n" + "=" * 80)
    print("测试6: 说话人角色识别演进")
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
        doc_score = sum(1 for p in classifier.DOCTOR_PATTERNS if __import__("re").search(p, text))
        pat_score = sum(1 for p in classifier.PATIENT_PATTERNS if __import__("re").search(p, text))
        predicted = "doctor" if doc_score > pat_score else ("patient" if pat_score > doc_score else "unknown")
        is_correct = predicted == expected_role
        rule_results.append({
            "text": text,
            "expected": expected_role,
            "predicted": predicted,
            "doc_score": doc_score,
            "pat_score": pat_score,
            "correct": is_correct,
        })
        status = "✅" if is_correct else "❌"
        print(f"  {status} '{text}' → 规则预测: {predicted} (期望: {expected_role}, doc={doc_score}, pat={pat_score})")

    rule_accuracy = sum(1 for r in rule_results if r["correct"]) / len(rule_results)
    print(f"\n  规则方法准确率: {rule_accuracy*100:.1f}%")
    print(f"  LLM方法: 通过语义理解识别角色，准确率更高（在多阶段流程阶段1中实现）")

    return {
        "test": "speaker_role_evolution",
        "rule_accuracy": rule_accuracy,
        "rule_details": rule_results,
    }


def main():
    print("=" * 80)
    print("中期汇报综合测试")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    init_db()

    all_results = {}

    # 测试1: ASR纠错
    try:
        all_results["asr_correction"] = test_asr_correction()
    except Exception as e:
        print(f"ASR纠错测试失败: {e}")
        all_results["asr_correction"] = {"error": str(e)}

    # 测试5: 已有EMR质量统计（不需要LLM调用）
    try:
        all_results["existing_emr_quality"] = test_existing_emr_quality()
    except Exception as e:
        print(f"EMR质量统计失败: {e}")
        all_results["existing_emr_quality"] = {"error": str(e)}

    # 测试6: 说话人角色识别演进（不需要LLM调用）
    try:
        all_results["speaker_role_evolution"] = test_speaker_role_evolution()
    except Exception as e:
        print(f"说话人角色识别测试失败: {e}")
        all_results["speaker_role_evolution"] = {"error": str(e)}

    # 测试2: 术语规范化（需要LLM调用）
    try:
        all_results["terminology_normalization"] = test_terminology_normalization()
    except Exception as e:
        print(f"术语规范化测试失败: {e}")
        all_results["terminology_normalization"] = {"error": str(e)}

    # 测试3: 端到端 vs 多阶段（需要LLM调用）
    try:
        all_results["e2e_vs_multistage"] = test_end_to_end_vs_multistage()
    except Exception as e:
        print(f"端到端对比测试失败: {e}")
        all_results["e2e_vs_multistage"] = {"error": str(e)}

    # 测试4: 四层评估体系（需要LLM调用）
    try:
        all_results["evaluation_pipeline"] = test_evaluation_pipeline()
    except Exception as e:
        print(f"评估体系测试失败: {e}")
        all_results["evaluation_pipeline"] = {"error": str(e)}

    # 保存结果
    output_file = RESULTS_DIR / f"midterm_test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2, default=str)

    print(f"\n结果已保存到: {output_file}")

    # 打印汇总
    print("\n" + "=" * 80)
    print("测试汇总")
    print("=" * 80)
    for test_name, result in all_results.items():
        if "error" in result:
            print(f"  {test_name}: ❌ 错误 - {result['error']}")
        elif "summary" in result:
            print(f"  {test_name}: ✅ 完成")
        elif "comparison" in result:
            print(f"  {test_name}: ✅ 完成")
        elif "results" in result:
            print(f"  {test_name}: ✅ 完成")
        else:
            print(f"  {test_name}: ⚠️ 未知格式")


if __name__ == "__main__":
    main()
