"""
评估结果汇总脚本

从实验运行结果中提取指标数据，生成可填入论文表格的汇总报告。

支持汇总以下指标:
  - ASR 转写性能 (CER, 术语错误率, 角色准确率)
  - 术语规范化性能 (Accuracy@1, Accuracy@5, 查询时间)
  - 病历生成质量 (四层评估框架: 一致性/完整性/文档质量/安全风险)
  - 消融实验结果
  - LLM 调用效率

用法:
    python scripts/aggregate_results.py --results_dir data/experiments/results/ --output data/experiments/summary_report.json
"""

import json
import argparse
import sys
import os
from pathlib import Path
from typing import Dict, Any, List, Optional
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.services.evaluation.imcs_adapter import IMCSAdapter, IMCS_FIELDS
from backend.services.evaluation.reference_based_evaluator import ReferenceBasedEvaluator
from backend.services.evaluation.evaluation_normalizer import EvaluationNormalizer
from backend.services.evaluation.benchmark_pipeline import BenchmarkPipeline

LOG_DIR = Path("data/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / "aggregate_results.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def load_result_files(results_dir: str) -> Dict[str, List[Dict[str, Any]]]:
    results_path = Path(results_dir)
    if not results_path.exists():
        logger.error(f"结果目录不存在: {results_dir}")
        return {}

    config_results = defaultdict(list)

    for f in sorted(results_path.glob("results_*.jsonl")):
        config_name = f.stem.replace("results_", "").rsplit("_", 1)[0]
        with open(f, 'r', encoding='utf-8') as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    config_results[config_name].append(entry)
                except json.JSONDecodeError:
                    continue

    for f in sorted(results_path.glob("summary_*.json")):
        with open(f, 'r', encoding='utf-8') as fp:
            data = json.load(fp)
        config_key = data.get("config_key", "unknown")
        if config_key not in config_results:
            logger.info(f"summary文件 {f.name} 无对应jsonl结果，跳过")

    logger.info(f"加载了 {sum(len(v) for v in config_results.values())} 条结果，{len(config_results)} 个配置")
    return dict(config_results)


def compute_field_level_metrics(
    predictions: List[Dict[str, Any]],
    dataset_path: str
) -> Dict[str, Any]:
    normalizer = EvaluationNormalizer()
    evaluator = ReferenceBasedEvaluator(normalizer=normalizer)
    adapter = IMCSAdapter(dataset_path)

    field_metrics = defaultdict(list)
    overall_metrics = {
        "rouge1": [], "rouge2": [], "rougeL": [],
        "bleu4": [], "avg_rouge": []
    }

    for pred_info in predictions:
        emr = pred_info.get("emr_result")
        sample_id = pred_info.get("sample_id", "")
        if not emr:
            continue

        imcs_pred = adapter.convert_soap_to_imcs(emr)
        references = adapter.get_reference_reports(sample_id)
        if not references:
            continue

        eval_result = evaluator.evaluate(
            prediction=imcs_pred,
            references=references,
            compute_bertscore=False
        )

        overall_metrics["rouge1"].append(eval_result.get("raw_rouge", {}).get("rouge-1", 0))
        overall_metrics["rouge2"].append(eval_result.get("raw_rouge", {}).get("rouge-2", 0))
        overall_metrics["rougeL"].append(eval_result.get("raw_rouge", {}).get("rouge-l", 0))
        overall_metrics["bleu4"].append(eval_result.get("raw_bleu", {}).get("bleu-4", 0))
        overall_metrics["avg_rouge"].append(eval_result.get("avg_rouge", 0))

        field_results = eval_result.get("field_results", {})
        for field, fr in field_results.items():
            field_metrics[field].append({
                "rouge1": fr.get("raw_rouge", {}).get("rouge-1", 0),
                "rouge2": fr.get("raw_rouge", {}).get("rouge-2", 0),
                "rougeL": fr.get("raw_rouge", {}).get("rouge-l", 0)
            })

    def avg(lst):
        return round(sum(lst) / len(lst), 4) if lst else 0

    summary = {
        "overall": {k: avg(v) for k, v in overall_metrics.items()},
        "field_level": {}
    }

    for field, metrics_list in field_metrics.items():
        summary["field_level"][field] = {
            "rouge1": avg([m["rouge1"] for m in metrics_list]),
            "rouge2": avg([m["rouge2"] for m in metrics_list]),
            "rougeL": avg([m["rougeL"] for m in metrics_list]),
            "count": len(metrics_list)
        }

    return summary


def compute_efficiency_metrics(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    elapsed_times = [r.get("elapsed_seconds", 0) for r in results
                     if r.get("status") in ("completed",)]
    completed = sum(1 for r in results if r.get("status") in ("completed",))
    failed = sum(1 for r in results if r.get("status") not in ("completed",))

    return {
        "total": len(results),
        "completed": completed,
        "failed": failed,
        "avg_elapsed_seconds": round(sum(elapsed_times) / len(elapsed_times), 2) if elapsed_times else 0,
        "min_elapsed_seconds": round(min(elapsed_times), 2) if elapsed_times else 0,
        "max_elapsed_seconds": round(max(elapsed_times), 2) if elapsed_times else 0,
        "total_elapsed_seconds": round(sum(elapsed_times), 2)
    }


def compute_quality_aggregates(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    structure_scores = []
    field_missing_rates = []
    all_field_missing_rates = []
    diagnosis_matches = []
    present_sections_total = 0
    total_sections_total = 0
    missing_required_total = 0
    total_required_total = 0
    missing_all_total = 0
    total_all_total = 0
    sample_count = 0

    for r in results:
        if r.get("status") not in ("completed",):
            continue
        qm = r.get("quality_metrics")
        if not qm:
            continue
        sample_count += 1
        structure_scores.append(qm.get("structure_completeness", 0))
        field_missing_rates.append(qm.get("field_missing_rate", 0))
        all_field_missing_rates.append(qm.get("all_field_missing_rate", 0))
        if qm.get("diagnosis_match") is not None:
            diagnosis_matches.append(qm["diagnosis_match"])
        present_sections_total += qm.get("present_sections", 0)
        total_sections_total += qm.get("total_sections", 4)
        missing_required_total += qm.get("missing_required_fields", 0)
        total_required_total += qm.get("total_required_fields", 4)
        missing_all_total += qm.get("missing_all_fields", 0)
        total_all_total += qm.get("total_all_fields", 9)

    def avg(lst):
        return round(sum(lst) / len(lst), 4) if lst else 0

    return {
        "sample_count": sample_count,
        "avg_structure_completeness": avg(structure_scores),
        "avg_field_missing_rate": avg(field_missing_rates),
        "avg_all_field_missing_rate": avg(all_field_missing_rates),
        "diagnosis_consistency": round(sum(diagnosis_matches) / len(diagnosis_matches), 4) if diagnosis_matches else 0,
        "diagnosis_match_count": sum(diagnosis_matches),
        "diagnosis_total": len(diagnosis_matches),
        "aggregate_structure_completeness": round(present_sections_total / total_sections_total, 4) if total_sections_total > 0 else 0,
        "aggregate_field_missing_rate": round(missing_required_total / total_required_total, 4) if total_required_total > 0 else 0,
        "aggregate_all_field_missing_rate": round(missing_all_total / total_all_total, 4) if total_all_total > 0 else 0,
    }


def compute_hallucination_aggregates(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    support_rates = []
    hallucination_rates = []
    total_facts_all = 0
    unsupported_all = 0
    severity_counts = defaultdict(int)

    for r in results:
        if r.get("status") not in ("completed",):
            continue
        h = r.get("hallucination")
        if not h:
            continue
        sr = h.get("support_rate", 0)
        support_rates.append(sr)
        hallucination_rates.append(1 - sr)
        total_facts_all += h.get("total_facts", 0)
        unsupported_all += h.get("unsupported_count", 0)
        severity_counts[h.get("severity", "unknown")] += 1

    def avg(lst):
        return round(sum(lst) / len(lst), 4) if lst else 0

    return {
        "sample_count": len(support_rates),
        "avg_support_rate": avg(support_rates),
        "avg_hallucination_rate": avg(hallucination_rates),
        "aggregate_support_rate": round((total_facts_all - unsupported_all) / total_facts_all, 4) if total_facts_all > 0 else 0,
        "aggregate_hallucination_rate": round(unsupported_all / total_facts_all, 4) if total_facts_all > 0 else 0,
        "total_facts": total_facts_all,
        "total_unsupported": unsupported_all,
        "severity_distribution": dict(severity_counts),
    }


def compute_verification_aggregates(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    category_totals = defaultdict(int)
    issue_counts = []
    sample_count = 0

    for r in results:
        if r.get("status") not in ("completed",):
            continue
        vi = r.get("verification_issues")
        if not vi:
            continue
        sample_count += 1
        issue_counts.append(vi.get("total", 0))
        for cat, count in vi.get("categories", {}).items():
            category_totals[cat] += count

    def avg(lst):
        return round(sum(lst) / len(lst), 4) if lst else 0

    return {
        "sample_count": sample_count,
        "avg_issues_per_sample": avg(issue_counts),
        "total_issues": sum(issue_counts),
        "category_totals": dict(category_totals),
    }


def compute_llm_evaluation_aggregates(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    recall_rates = []
    omission_rates = []
    quality_scores = []
    safety_high_risk_counts = []
    safety_has_risk_samples = 0
    sample_count = 0

    for r in results:
        if r.get("status") not in ("completed",):
            continue
        le = r.get("llm_evaluation")
        if not le or le.get("error"):
            continue
        sample_count += 1

        completeness = le.get("completeness")
        if completeness:
            summary = completeness.get("summary", {})
            recall_rates.append(summary.get("recall_rate", 0))
            omission_rates.append(summary.get("omission_rate", 0))

        quality = le.get("quality")
        if quality:
            quality_scores.append(quality.get("total_score", 0))

        safety = le.get("safety")
        if safety:
            safety_high_risk_counts.append(safety.get("high_risk_count", 0))
            if safety.get("has_high_risk"):
                safety_has_risk_samples += 1

    def avg(lst):
        return round(sum(lst) / len(lst), 4) if lst else 0

    return {
        "sample_count": sample_count,
        "avg_recall_rate": avg(recall_rates),
        "avg_omission_rate": avg(omission_rates),
        "avg_quality_score": avg(quality_scores),
        "avg_safety_high_risk_count": avg(safety_high_risk_counts),
        "safety_has_risk_rate": round(safety_has_risk_samples / sample_count, 4) if sample_count > 0 else 0,
    }


def generate_comparison_table(
    all_config_results: Dict[str, List[Dict[str, Any]]],
    dataset_path: str
) -> List[Dict[str, Any]]:
    rows = []
    for config_key, results in all_config_results.items():
        efficiency = compute_efficiency_metrics(results)
        quality = compute_quality_aggregates(results)
        hallucination = compute_hallucination_aggregates(results)
        verification = compute_verification_aggregates(results)
        llm_eval = compute_llm_evaluation_aggregates(results)
        field_metrics = compute_field_level_metrics(results, dataset_path)

        row = {
            "config": config_key,
            "samples_count": efficiency["total"],
            "completed_count": efficiency["completed"],
            "avg_elapsed_s": efficiency["avg_elapsed_seconds"],
            "avg_rouge1": field_metrics["overall"]["rouge1"],
            "avg_rouge2": field_metrics["overall"]["rouge2"],
            "avg_rougeL": field_metrics["overall"]["rougeL"],
            "avg_bleu4": field_metrics["overall"]["bleu4"],
            "avg_avg_rouge": field_metrics["overall"]["avg_rouge"],
            "structure_completeness": quality["avg_structure_completeness"],
            "aggregate_structure_completeness": quality["aggregate_structure_completeness"],
            "field_missing_rate": quality["avg_field_missing_rate"],
            "aggregate_field_missing_rate": quality["aggregate_field_missing_rate"],
            "diagnosis_consistency": quality["diagnosis_consistency"],
            "hallucination_avg_support_rate": hallucination["avg_support_rate"],
            "hallucination_aggregate_support_rate": hallucination["aggregate_support_rate"],
            "hallucination_aggregate_rate": hallucination["aggregate_hallucination_rate"],
            "hallucination_total_facts": hallucination["total_facts"],
            "hallucination_total_unsupported": hallucination["total_unsupported"],
            "verification_avg_issues": verification["avg_issues_per_sample"],
            "verification_category_totals": verification["category_totals"],
            "llm_eval_recall_rate": llm_eval["avg_recall_rate"],
            "llm_eval_omission_rate": llm_eval["avg_omission_rate"],
            "llm_eval_quality_score": llm_eval["avg_quality_score"],
            "llm_eval_safety_high_risk_rate": llm_eval["safety_has_risk_rate"],
            "llm_eval_sample_count": llm_eval["sample_count"],
        }

        for field, metrics in field_metrics.get("field_level", {}).items():
            row[f"field_{field}_rougeL"] = metrics["rougeL"]

        rows.append(row)
    return rows


def generate_summary_markdown(
    rows: List[Dict[str, Any]],
    output_path: str
):
    header = "| 配置 | 样本数 | 完成数 | 平均耗时(s) | ROUGE-1 | ROUGE-2 | ROUGE-L | BLEU-4 | Avg ROUGE |\n"
    header += "|:---|---:|---:|---:|---:|---:|---:|---:|---:|\n"

    lines = [header]
    for row in rows:
        line = (f"| {row['config']} | {row['samples_count']} | {row['completed_count']} | "
                f"{row['avg_elapsed_s']} | {row['avg_rouge1']} | {row['avg_rouge2']} | "
                f"{row['avg_rougeL']} | {row['avg_bleu4']} | {row['avg_avg_rouge']} |\n")
        lines.append(line)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.writelines(lines)

    logger.info(f"汇总Markdown表格已保存: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="汇总实验结果")
    parser.add_argument("--results_dir", default="data/experiments/results",
                        help="实验结果目录")
    parser.add_argument("--dataset", default="data/text/imcs21-dataset/test.json",
                        help="IMCS-MRG 数据集路径")
    parser.add_argument("--output", default="data/experiments/summary_report.json",
                        help="汇总报告输出路径")
    args = parser.parse_args()

    all_config_results = load_result_files(args.results_dir)
    if not all_config_results:
        logger.error("未找到任何结果文件")
        return

    comparison_rows = generate_comparison_table(all_config_results, args.dataset)

    markdown_path = Path(args.output).with_suffix(".md")
    generate_summary_markdown(comparison_rows, str(markdown_path))

    report = {
        "comparison": comparison_rows,
        "dataset": args.dataset,
        "config_names": list(all_config_results.keys())
    }

    output_dir = Path(args.output).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    logger.info(f"汇总报告已保存: {args.output}")

    print("\n" + "=" * 80)
    print("实验结果汇总")
    print("=" * 80)
    for row in comparison_rows:
        print(f"\n  [{row['config']}]")
        print(f"    ROUGE-L={row['avg_rougeL']:.4f}, 耗时={row['avg_elapsed_s']}s")
        print(f"    结构完整率={row['structure_completeness']:.2%}, "
              f"字段缺失率={row['field_missing_rate']:.2%}, "
              f"诊断一致性={row['diagnosis_consistency']:.2%}")
        print(f"    幻觉支持率={row['hallucination_avg_support_rate']:.2%}, "
              f"幻觉率={row['hallucination_aggregate_rate']:.2%}, "
              f"({row['hallucination_total_facts']}事实/{row['hallucination_total_unsupported']}无依据)")
        print(f"    核查问题: 均{row['verification_avg_issues']:.1f}/样本, "
              f"分类={row['verification_category_totals']}")
        if row.get("llm_eval_sample_count", 0) > 0:
            print(f"    完整性: 召回={row['llm_eval_recall_rate']:.2%}, "
                  f"遗漏={row['llm_eval_omission_rate']:.2%}")
            print(f"    质量评分: {row['llm_eval_quality_score']:.1f}/10")
            print(f"    安全风险: {row['llm_eval_safety_high_risk_rate']:.2%} 样本含高风险错误")


if __name__ == "__main__":
    main()