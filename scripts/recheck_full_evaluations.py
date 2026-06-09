"""
重新检查full配置的评估记录，对比提取脚本的结果
"""
import sqlite3
import statistics

def recheck_full_evaluations():
    db_path = "data/database/benchmark.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print("=" * 80)
    print("重新检查full配置的评估记录")
    print("=" * 80)

    # 1. 检查所有full配置的运行记录
    cursor.execute("""
        SELECT
            r.id,
            r.sample_id,
            r.status,
            e.id as eval_id,
            e.support_rate,
            e.hallucination_rate,
            e.recall_rate,
            e.omission_rate
        FROM benchmark_runs r
        LEFT JOIN benchmark_evaluations e ON r.id = e.run_id
        WHERE r.config_key = 'full'
        ORDER BY r.id
    """)

    all_runs = cursor.fetchall()

    print(f"\n共 {len(all_runs)} 条full配置运行记录:")
    print("-" * 80)

    # 分类统计
    completed_with_eval = []
    completed_without_eval = []
    failed_runs = []

    for run in all_runs:
        run_id, sample_id, status, eval_id, support, hallucination, recall, omission = run

        if status == 'failed':
            failed_runs.append(run)
            print(f"Run {run_id} (样本{sample_id}): FAILED")
        elif status == 'completed':
            if eval_id and support is not None:
                completed_with_eval.append(run)
                print(f"Run {run_id} (样本{sample_id}): COMPLETED, 有评估 (support={support:.4f}, hallucination={hallucination:.4f}, recall={recall:.4f}, omission={omission:.4f})")
            else:
                completed_without_eval.append(run)
                print(f"Run {run_id} (样本{sample_id}): COMPLETED, 无评估")

    print("\n" + "=" * 80)
    print("统计汇总")
    print("=" * 80)
    print(f"失败运行: {len(failed_runs)} 条")
    print(f"成功运行（有评估）: {len(completed_with_eval)} 条")
    print(f"成功运行（无评估）: {len(completed_without_eval)} 条")
    print(f"总成功运行: {len(completed_with_eval) + len(completed_without_eval)} 条")

    # 2. 基于有评估记录计算平均值
    if completed_with_eval:
        support_rates = [r[4] for r in completed_with_eval if r[4] is not None]
        hallucination_rates = [r[5] for r in completed_with_eval if r[5] is not None]
        recall_rates = [r[6] for r in completed_with_eval if r[6] is not None]
        omission_rates = [r[7] for r in completed_with_eval if r[7] is not None]

        print(f"\n基于 {len(completed_with_eval)} 条有评估记录的平均值:")
        print(f"  事实支持率: {statistics.mean(support_rates)*100:.2f}%")
        print(f"  幻觉率: {statistics.mean(hallucination_rates)*100:.2f}%")
        print(f"  关键召回率: {statistics.mean(recall_rates)*100:.2f}%")
        print(f"  遗漏率: {statistics.mean(omission_rates)*100:.2f}%")

    # 3. 检查提取脚本的逻辑
    print("\n" + "=" * 80)
    print("检查提取脚本的逻辑")
    print("=" * 80)

    # 提取脚本只计算status='completed'且有评估记录的样本
    cursor.execute("""
        SELECT
            COUNT(*) as total_runs,
            COUNT(CASE WHEN r.status = 'completed' THEN 1 END) as completed_runs,
            COUNT(CASE WHEN r.status = 'failed' THEN 1 END) as failed_runs
        FROM benchmark_runs r
        WHERE r.config_key = 'full'
    """)

    result = cursor.fetchone()
    print(f"总运行: {result[0]}")
    print(f"成功运行: {result[1]}")
    print(f"失败运行: {result[2]}")

    # 检查有多少成功运行有评估记录
    cursor.execute("""
        SELECT COUNT(DISTINCT r.id)
        FROM benchmark_runs r
        INNER JOIN benchmark_evaluations e ON r.id = e.run_id
        WHERE r.config_key = 'full' AND r.status = 'completed' AND e.support_rate IS NOT NULL
    """)

    eval_count = cursor.fetchone()[0]
    print(f"有评估记录的成功运行: {eval_count}")

    # 4. 检查benchmark_evaluations表的所有记录
    print("\n" + "=" * 80)
    print("检查benchmark_evaluations表的所有记录")
    print("=" * 80)

    cursor.execute("""
        SELECT
            e.run_id,
            r.config_key,
            r.sample_id,
            e.support_rate,
            e.hallucination_rate,
            e.recall_rate,
            e.omission_rate
        FROM benchmark_evaluations e
        INNER JOIN benchmark_runs r ON r.id = e.run_id
        WHERE r.config_key = 'full'
        ORDER BY e.run_id
    """)

    eval_records = cursor.fetchall()
    print(f"\n共 {len(eval_records)} 条full配置的评估记录:")
    print("-" * 80)

    for record in eval_records:
        run_id, config_key, sample_id, support, hallucination, recall, omission = record
        print(f"Run {run_id} (样本{sample_id}): support={support:.4f}, hallucination={hallucination:.4f}, recall={recall:.4f}, omission={omission:.4f}")

    if eval_records:
        support_rates = [r[3] for r in eval_records if r[3] is not None]
        hallucination_rates = [r[4] for r in eval_records if r[4] is not None]
        recall_rates = [r[5] for r in eval_records if r[5] is not None]
        omission_rates = [r[6] for r in eval_records if r[6] is not None]

        print(f"\n基于评估表记录的平均值:")
        print(f"  事实支持率: {statistics.mean(support_rates)*100:.2f}%")
        print(f"  幻觉率: {statistics.mean(hallucination_rates)*100:.2f}%")
        print(f"  关键召回率: {statistics.mean(recall_rates)*100:.2f}%")
        print(f"  遗漏率: {statistics.mean(omission_rates)*100:.2f}%")

    conn.close()

if __name__ == "__main__":
    recheck_full_evaluations()