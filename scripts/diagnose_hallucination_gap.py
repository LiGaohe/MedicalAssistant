"""
诊断脚本：对比 full 和 standard 配置的幻觉率差异

目的：定位 full 配置幻觉率（4.0%）高于 standard（3.1%）的根本原因

分析维度：
1. 逐样本对比 support_rate / hallucination_rate
2. 对比一致性评估结果中的 unsupported_facts 详情
3. 对比管线内部幻觉检查（hallucination_result）与评估阶段一致性检查的差异
4. 检查 full 管线幻觉检查是否修改了 EMR（导致评估输入不同）

用法:
  python scripts/diagnose_hallucination_gap.py
  python scripts/diagnose_hallucination_gap.py --sample 10348652  # 只看特定样本
"""

import argparse
import json
import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models.benchmark import BenchmarkRun, BenchmarkEvaluation
from backend.benchmark_db import BENCHMARK_DATABASE_URL

import logging
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


def get_session():
    engine = create_engine(BENCHMARK_DATABASE_URL)
    Session = sessionmaker(bind=engine)
    return Session()


def get_deduped_runs(session, config_key: str):
    """获取去重后的运行记录"""
    runs = session.query(BenchmarkRun).filter(
        BenchmarkRun.config_key == config_key
    ).order_by(BenchmarkRun.created_at).all()

    seen = {}
    for run in runs:
        sid = run.sample_id
        if sid not in seen:
            seen[sid] = run
        else:
            existing = seen[sid]
            if run.status == "completed" and existing.status != "completed":
                seen[sid] = run
            elif run.status == existing.status and run.created_at > existing.created_at:
                seen[sid] = run
    return seen


def analyze_sample_comparison(session, sample_id: str, full_runs: dict, standard_runs: dict):
    """对比单个样本的 full 和 standard 数据"""
    full_run = full_runs.get(sample_id)
    standard_run = standard_runs.get(sample_id)

    if not full_run or full_run.status != "completed":
        return None
    if not standard_run or standard_run.status != "completed":
        return None

    # 获取评估结果
    full_eval = session.query(BenchmarkEvaluation).filter(
        BenchmarkEvaluation.run_id == full_run.id
    ).first()
    standard_eval = session.query(BenchmarkEvaluation).filter(
        BenchmarkEvaluation.run_id == standard_run.id
    ).first()

    if not full_eval or not standard_eval:
        return None

    result = {
        "sample_id": sample_id,
        "full": {
            "support_rate": full_eval.support_rate,
            "hallucination_rate": full_eval.hallucination_rate,
            "recall_rate": full_eval.recall_rate,
            "omission_rate": full_eval.omission_rate,
        },
        "standard": {
            "support_rate": standard_eval.support_rate,
            "hallucination_rate": standard_eval.hallucination_rate,
            "recall_rate": standard_eval.recall_rate,
            "omission_rate": standard_eval.omission_rate,
        },
        "delta_support": None,
        "delta_hallucination": None,
    }

    if full_eval.support_rate is not None and standard_eval.support_rate is not None:
        result["delta_support"] = full_eval.support_rate - standard_eval.support_rate
    if full_eval.hallucination_rate is not None and standard_eval.hallucination_rate is not None:
        result["delta_hallucination"] = full_eval.hallucination_rate - standard_eval.hallucination_rate

    # 对比一致性评估中的 unsupported_facts
    full_consistency = full_eval.consistency_result or {}
    standard_consistency = standard_eval.consistency_result or {}

    full_unsupported = []
    for fact in full_consistency.get("facts", []):
        if not fact.get("is_supported", True):
            full_unsupported.append(fact)

    standard_unsupported = []
    for fact in standard_consistency.get("facts", []):
        if not fact.get("is_supported", True):
            standard_unsupported.append(fact)

    result["full_unsupported_facts"] = full_unsupported
    result["standard_unsupported_facts"] = standard_unsupported

    # 对比管线内部幻觉检查结果
    full_hallucination = full_run.hallucination_result or {}
    full_hall_summary = full_hallucination.get("summary", {})
    result["full_pipeline_hallucination"] = {
        "total_facts": full_hall_summary.get("total_facts", 0),
        "supported_count": full_hall_summary.get("supported_count", 0),
        "unsupported_count": full_hall_summary.get("unsupported_count", 0),
        "support_rate": full_hall_summary.get("support_rate", 0),
        "unsupported_facts": [
            f.get("fact", "")[:80]
            for f in full_hallucination.get("unsupported_facts", [])
        ],
    }

    # 对比 EMR 差异
    full_emr = full_run.emr_result or {}
    standard_emr = standard_run.emr_result or {}
    result["emr_diff"] = compare_emr(full_emr, standard_emr)

    return result


def compare_emr(emr_a: dict, emr_b: dict) -> dict:
    """对比两个 EMR 的字段值差异"""
    diff = {}
    for section in ["subjective", "objective", "assessment", "plan"]:
        sec_a = emr_a.get(section, {}) or {}
        sec_b = emr_b.get(section, {}) or {}
        if not isinstance(sec_a, dict) or not isinstance(sec_b, dict):
            continue
        all_keys = set(list(sec_a.keys()) + list(sec_b.keys()))
        section_diff = {}
        for key in all_keys:
            val_a = sec_a.get(key, "")
            val_b = sec_b.get(key, "")
            if val_a != val_b:
                section_diff[key] = {
                    "full": str(val_a)[:100],
                    "standard": str(val_b)[:100],
                }
        if section_diff:
            diff[section] = section_diff
    return diff


def main():
    parser = argparse.ArgumentParser(description="诊断 full vs standard 幻觉率差异")
    parser.add_argument("--sample", type=str, help="只分析特定样本")
    args = parser.parse_args()

    session = get_session()

    full_runs = get_deduped_runs(session, "full")
    standard_runs = get_deduped_runs(session, "standard")

    # 找到两个配置共有的成功样本
    common_samples = set(full_runs.keys()) & set(standard_runs.keys())
    common_completed = [
        s for s in common_samples
        if full_runs[s].status == "completed" and standard_runs[s].status == "completed"
    ]

    print(f"=" * 80)
    print(f"full 配置: {len(full_runs)} 个去重样本, {sum(1 for r in full_runs.values() if r.status == 'completed')} 个成功")
    print(f"standard 配置: {len(standard_runs)} 个去重样本, {sum(1 for r in standard_runs.values() if r.status == 'completed')} 个成功")
    print(f"共有成功样本: {len(common_completed)} 个")
    print(f"=" * 80)

    if args.sample:
        common_completed = [s for s in common_completed if s == args.sample]

    # 逐样本对比
    all_results = []
    full_hallucination_higher = []
    full_support_lower = []

    for sample_id in sorted(common_completed):
        result = analyze_sample_comparison(session, sample_id, full_runs, standard_runs)
        if not result:
            continue
        all_results.append(result)

        if result["delta_hallucination"] is not None and result["delta_hallucination"] > 0:
            full_hallucination_higher.append(result)
        if result["delta_support"] is not None and result["delta_support"] < 0:
            full_support_lower.append(result)

    # 输出汇总
    print(f"\n## 一、逐样本幻觉率对比")
    print(f"{'sample_id':<12} {'full_hall':>10} {'std_hall':>10} {'delta':>8} {'full_sup':>10} {'std_sup':>10} {'delta_sup':>8}")
    print("-" * 80)

    for r in sorted(all_results, key=lambda x: x.get("delta_hallucination") or 0, reverse=True):
        fh = r["full"]["hallucination_rate"]
        sh = r["standard"]["hallucination_rate"]
        dh = r["delta_hallucination"]
        fs = r["full"]["support_rate"]
        ss = r["standard"]["support_rate"]
        ds = r["delta_support"]
        fh_str = f"{fh:.3f}" if fh is not None else "N/A"
        sh_str = f"{sh:.3f}" if sh is not None else "N/A"
        dh_str = f"{dh:+.3f}" if dh is not None else "N/A"
        fs_str = f"{fs:.3f}" if fs is not None else "N/A"
        ss_str = f"{ss:.3f}" if ss is not None else "N/A"
        ds_str = f"{ds:+.3f}" if ds is not None else "N/A"
        marker = " <<<" if dh is not None and dh > 0 else ""
        print(f"{r['sample_id']:<12} {fh_str:>10} {sh_str:>10} {dh_str:>8} {fs_str:>10} {ss_str:>10} {ds_str:>8}{marker}")

    # 输出 full 幻觉率更高的样本详情
    print(f"\n## 二、full 幻觉率高于 standard 的样本（{len(full_hallucination_higher)} 个）")
    for r in full_hallucination_higher:
        print(f"\n### 样本 {r['sample_id']}")
        print(f"  full 幻觉率: {r['full']['hallucination_rate']:.3f}, standard 幻觉率: {r['standard']['hallucination_rate']:.3f}, 差值: {r['delta_hallucination']:+.3f}")

        # 管线内部幻觉检查结果
        hall = r.get("full_pipeline_hallucination", {})
        if hall:
            print(f"  管线幻觉检查: 总事实={hall.get('total_facts', 0)}, 不支持={hall.get('unsupported_count', 0)}, 支持率={hall.get('support_rate', 0):.3f}")
            if hall.get("unsupported_facts"):
                print(f"  管线标记的幻觉事实:")
                for fact in hall["unsupported_facts"]:
                    print(f"    - {fact}")

        # 评估阶段一致性检查的不支持事实
        full_unsup = r.get("full_unsupported_facts", [])
        std_unsup = r.get("standard_unsupported_facts", [])
        if full_unsup:
            print(f"  评估阶段 full 不支持事实 ({len(full_unsup)} 条):")
            for f in full_unsup:
                print(f"    - [{f.get('section', '?')}] {f.get('fact', '')[:80]}")
        if std_unsup:
            print(f"  评估阶段 standard 不支持事实 ({len(std_unsup)} 条):")
            for f in std_unsup:
                print(f"    - [{f.get('section', '?')}] {f.get('fact', '')[:80]}")

        # EMR 差异
        emr_diff = r.get("emr_diff", {})
        if emr_diff:
            print(f"  EMR 差异:")
            for section, fields in emr_diff.items():
                for field_name, vals in fields.items():
                    print(f"    [{section}] {field_name}:")
                    print(f"      full:    {vals['full']}")
                    print(f"      standard: {vals['standard']}")
        else:
            print(f"  EMR 无差异")

    # 分析 EMR 差异对幻觉率的影响
    print(f"\n## 三、EMR 差异分析")
    emr_diff_count = sum(1 for r in all_results if r.get("emr_diff"))
    emr_diff_with_higher_hall = sum(
        1 for r in full_hallucination_higher if r.get("emr_diff")
    )
    print(f"  有 EMR 差异的样本: {emr_diff_count}/{len(all_results)}")
    print(f"  full 幻觉率更高且有 EMR 差异的样本: {emr_diff_with_higher_hall}/{len(full_hallucination_higher)}")

    # 分析管线幻觉检查结果与评估结果的关系
    print(f"\n## 四、管线幻觉检查 vs 评估一致性检查")
    for r in all_results:
        hall = r.get("full_pipeline_hallucination", {})
        if not hall:
            continue
        pipeline_hall_rate = 1 - hall.get("support_rate", 1.0)
        eval_hall_rate = r["full"]["hallucination_rate"]
        if pipeline_hall_rate > 0 or (eval_hall_rate and eval_hall_rate > 0):
            eval_hall_str = f"{eval_hall_rate:.3f}" if eval_hall_rate is not None else "0.000"
            print(f"  样本 {r['sample_id']}: 管线幻觉率={pipeline_hall_rate:.3f}, 评估幻觉率={eval_hall_str}")

    # 关键结论
    print(f"\n## 五、结论")
    print(f"  full 幻觉率高于 standard 的样本数: {len(full_hallucination_higher)}/{len(all_results)}")
    if full_hallucination_higher:
        avg_delta = sum(r["delta_hallucination"] for r in full_hallucination_higher if r["delta_hallucination"] is not None) / len(full_hallucination_higher)
        print(f"  平均幻觉率差值: {avg_delta:+.4f}")
        print(f"  这些样本中:")
        has_emr_diff = sum(1 for r in full_hallucination_higher if r.get("emr_diff"))
        print(f"    - 有 EMR 差异的: {has_emr_diff}/{len(full_hallucination_higher)}")
        print(f"    - 无 EMR 差异的: {len(full_hallucination_higher) - has_emr_diff}/{len(full_hallucination_higher)}")

        if has_emr_diff > 0:
            print(f"\n  **根本原因假设1**: 幻觉检查阶段修改了 EMR（通过 field_revision），")
            print(f"  修改后的 EMR 中可能包含新的事实，这些新事实在评估时被标记为不支持。")
        else:
            print(f"\n  **根本原因假设2**: EMR 内容相同但评估结果不同，")
            print(f"  可能是评估 LLM 的非确定性导致（temperature=0.1 仍有微小随机性）。")

    session.close()


if __name__ == "__main__":
    main()
