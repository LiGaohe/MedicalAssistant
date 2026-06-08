"""
检查 benchmark.db 数据库中是否有缺少评估指标的配置

检查指标：
- 事实支持率 (support_rate)
- 幻觉率 (hallucination_rate)
- 关键召回率 (recall_rate)
- 遗漏率 (omission_rate)
- 结构完整率 (structure_completeness)
- 字段缺失率 (field_missing_rate)
- 诊断一致性 (diagnosis_match)
- 大模型调用次数 (llm_call_count)
- 延迟 (elapsed_seconds)
- 字符消耗 (char_count)
"""

import sqlite3
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

DB_PATH = project_root / "data" / "database" / "benchmark.db"

# 需要检查的评估指标字段
EVALUATION_METRICS = [
    "support_rate",
    "hallucination_rate",
    "recall_rate",
    "omission_rate",
    "structure_completeness",
    "field_missing_rate",
    "diagnosis_match",
]

# 需要检查的运行指标字段
RUN_METRICS = [
    "elapsed_seconds",
    "llm_call_count",
    "char_count",
]


def check_database():
    """检查数据库完整性"""
    if not DB_PATH.exists():
        print(f"错误：数据库文件不存在 - {DB_PATH}")
        return

    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    # 获取所有配置
    cursor.execute("SELECT DISTINCT config_key FROM benchmark_runs ORDER BY config_key")
    configs = [row[0] for row in cursor.fetchall()]

    print(f"\n{'='*60}")
    print(f"数据库路径: {DB_PATH}")
    print(f"配置数量: {len(configs)}")
    print(f"配置列表: {configs}")
    print(f"{'='*60}\n")

    issues_found = False

    for config in configs:
        print(f"\n--- 检查配置: {config} ---")

        # 获取该配置的所有运行记录
        cursor.execute("""
            SELECT id, sample_id, status, llm_call_count, char_count, elapsed_seconds
            FROM benchmark_runs
            WHERE config_key = ?
            ORDER BY id
        """, (config,))
        runs = cursor.fetchall()

        print(f"运行记录数: {len(runs)}")

        # 检查运行记录的指标
        missing_run_metrics = []
        for run in runs:
            run_id, sample_id, status, llm_call_count, char_count, elapsed_seconds = run

            if status == "failed":
                print(f"  [跳过] run_id={run_id}, sample_id={sample_id} - 状态为failed")
                continue

            # 检查运行指标是否为空或0
            if llm_call_count is None or llm_call_count == 0:
                missing_run_metrics.append(f"run_id={run_id}, sample_id={sample_id}: llm_call_count为空或0")
            if char_count is None or char_count == 0:
                missing_run_metrics.append(f"run_id={run_id}, sample_id={sample_id}: char_count为空或0")
            if elapsed_seconds is None or elapsed_seconds == 0:
                missing_run_metrics.append(f"run_id={run_id}, sample_id={sample_id}: elapsed_seconds为空或0")

        if missing_run_metrics:
            issues_found = True
            print(f"\n  [警告] 运行指标缺失 ({len(missing_run_metrics)}条):")
            for msg in missing_run_metrics[:10]:  # 只显示前10条
                print(f"    - {msg}")
            if len(missing_run_metrics) > 10:
                print(f"    ... 还有 {len(missing_run_metrics) - 10} 条")

        # 获取该配置的所有评估记录
        cursor.execute("""
            SELECT be.id, be.run_id, br.sample_id,
                   be.support_rate, be.hallucination_rate, be.recall_rate,
                   be.omission_rate, be.structure_completeness, be.field_missing_rate,
                   be.diagnosis_match, be.error_message
            FROM benchmark_evaluations be
            JOIN benchmark_runs br ON be.run_id = br.id
            WHERE br.config_key = ?
            ORDER BY be.id
        """, (config,))
        evaluations = cursor.fetchall()

        print(f"评估记录数: {len(evaluations)}")

        # 检查评估指标是否缺失
        missing_eval_metrics = []
        for eval_record in evaluations:
            (eval_id, run_id, sample_id, support_rate, hallucination_rate, recall_rate,
             omission_rate, structure_completeness, field_missing_rate,
             diagnosis_match, error_message) = eval_record

            # 如果有错误消息，跳过
            if error_message:
                print(f"  [跳过] eval_id={eval_id}, sample_id={sample_id} - 有错误: {error_message[:50]}...")
                continue

            # 检查每个指标
            missing = []
            if support_rate is None:
                missing.append("support_rate")
            if hallucination_rate is None:
                missing.append("hallucination_rate")
            if recall_rate is None:
                missing.append("recall_rate")
            if omission_rate is None:
                missing.append("omission_rate")
            if structure_completeness is None:
                missing.append("structure_completeness")
            if field_missing_rate is None:
                missing.append("field_missing_rate")
            if diagnosis_match is None:
                missing.append("diagnosis_match")

            if missing:
                missing_eval_metrics.append({
                    "eval_id": eval_id,
                    "run_id": run_id,
                    "sample_id": sample_id,
                    "missing": missing
                })

        if missing_eval_metrics:
            issues_found = True
            print(f"\n  [警告] 评估指标缺失 ({len(missing_eval_metrics)}条):")
            for item in missing_eval_metrics[:10]:  # 只显示前10条
                print(f"    - eval_id={item['eval_id']}, sample_id={item['sample_id']}: 缺失 {', '.join(item['missing'])}")
            if len(missing_eval_metrics) > 10:
                print(f"    ... 还有 {len(missing_eval_metrics) - 10} 条")

        # 检查运行记录和评估记录是否匹配
        cursor.execute("""
            SELECT br.id, br.sample_id
            FROM benchmark_runs br
            LEFT JOIN benchmark_evaluations be ON br.id = be.run_id
            WHERE br.config_key = ? AND br.status = 'completed' AND be.id IS NULL
        """, (config,))
        missing_evaluations = cursor.fetchall()

        if missing_evaluations:
            issues_found = True
            print(f"\n  [警告] 缺少评估记录的运行 ({len(missing_evaluations)}条):")
            for run_id, sample_id in missing_evaluations[:10]:
                print(f"    - run_id={run_id}, sample_id={sample_id}")
            if len(missing_evaluations) > 10:
                print(f"    ... 还有 {len(missing_evaluations) - 10} 条")

    # 汇总统计
    print(f"\n{'='*60}")
    print("汇总统计:")
    print(f"{'='*60}")

    cursor.execute("SELECT COUNT(*) FROM benchmark_runs")
    total_runs = cursor.fetchone()[0]
    print(f"总运行记录数: {total_runs}")

    cursor.execute("SELECT COUNT(*) FROM benchmark_runs WHERE status = 'completed'")
    completed_runs = cursor.fetchone()[0]
    print(f"完成的运行记录数: {completed_runs}")

    cursor.execute("SELECT COUNT(*) FROM benchmark_runs WHERE status = 'failed'")
    failed_runs = cursor.fetchone()[0]
    print(f"失败的运行记录数: {failed_runs}")

    cursor.execute("SELECT COUNT(*) FROM benchmark_evaluations")
    total_evals = cursor.fetchone()[0]
    print(f"总评估记录数: {total_evals}")

    # 检查各指标的非空数量
    print(f"\n各指标非空统计:")
    for metric in EVALUATION_METRICS:
        cursor.execute(f"SELECT COUNT(*) FROM benchmark_evaluations WHERE {metric} IS NOT NULL")
        count = cursor.fetchone()[0]
        cursor.execute(f"SELECT COUNT(*) FROM benchmark_evaluations")
        total = cursor.fetchone()[0]
        pct = (count / total * 100) if total > 0 else 0
        print(f"  {metric}: {count}/{total} ({pct:.1f}%)")

    conn.close()

    if issues_found:
        print(f"\n{'='*60}")
        print("发现问题：存在缺失指标的数据")
        print(f"{'='*60}")
    else:
        print(f"\n{'='*60}")
        print("检查完成：所有配置的指标完整")
        print(f"{'='*60}")


if __name__ == "__main__":
    check_database()