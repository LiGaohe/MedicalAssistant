"""
检查缺失评估记录的时间分布和运行批次
"""
import sqlite3
from datetime import datetime

def check_time_distribution():
    db_path = "data/database/benchmark.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print("=" * 80)
    print("检查缺失评估记录的时间分布")
    print("=" * 80)

    # 获取所有full配置的运行记录
    cursor.execute("""
        SELECT
            r.id,
            r.sample_id,
            r.status,
            r.created_at,
            e.id as eval_id,
            e.created_at as eval_created_at
        FROM benchmark_runs r
        LEFT JOIN benchmark_evaluations e ON r.id = e.run_id
        WHERE r.config_key = 'full'
        ORDER BY r.created_at
    """)

    all_runs = cursor.fetchall()

    print("\n所有full配置运行记录的时间分布:")
    print("-" * 80)
    print("Run ID | 样本ID | 状态 | 运行时间 | 有评估 | 评估时间")
    print("-" * 80)

    for run in all_runs:
        run_id, sample_id, status, created_at, eval_id, eval_created_at = run
        has_eval = "有" if eval_id else "无"
        eval_time = eval_created_at if eval_created_at else "N/A"
        print(f"{run_id:6} | {sample_id:10} | {status:8} | {created_at} | {has_eval:4} | {eval_time}")

    # 分析时间分布
    print("\n" + "=" * 80)
    print("时间分布分析")
    print("=" * 80)

    # 按小时分组
    cursor.execute("""
        SELECT
            strftime('%Y-%m-%d %H', r.created_at) as hour,
            COUNT(*) as total,
            COUNT(CASE WHEN e.id IS NOT NULL THEN 1 END) as with_eval,
            COUNT(CASE WHEN e.id IS NULL THEN 1 END) as without_eval
        FROM benchmark_runs r
        LEFT JOIN benchmark_evaluations e ON r.id = e.run_id
        WHERE r.config_key = 'full' AND r.status = 'completed'
        GROUP BY strftime('%Y-%m-%d %H', r.created_at)
        ORDER BY hour
    """)

    hourly_stats = cursor.fetchall()

    print("\n按小时统计:")
    print("-" * 80)
    print("时间 | 总运行 | 有评估 | 无评估 | 缺失率")
    print("-" * 80)

    for stat in hourly_stats:
        hour, total, with_eval, without_eval = stat
        missing_rate = (without_eval / total * 100) if total > 0 else 0
        print(f"{hour} | {total:6} | {with_eval:6} | {without_eval:6} | {missing_rate:.1f}%")

    # 检查是否有连续的缺失评估记录
    print("\n" + "=" * 80)
    print("检查连续缺失评估记录")
    print("=" * 80)

    # 找出缺失评估记录的时间段
    cursor.execute("""
        SELECT
            r.id,
            r.sample_id,
            r.created_at
        FROM benchmark_runs r
        LEFT JOIN benchmark_evaluations e ON r.id = e.run_id
        WHERE r.config_key = 'full' AND r.status = 'completed' AND e.id IS NULL
        ORDER BY r.created_at
    """)

    missing_runs = cursor.fetchall()

    if missing_runs:
        print(f"\n缺失评估记录的时间段:")
        print("-" * 80)

        # 计算时间间隔
        prev_time = None
        for i, run in enumerate(missing_runs):
            run_id, sample_id, created_at = run
            current_time = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")

            if prev_time:
                interval = (current_time - prev_time).total_seconds()
                print(f"Run {run_id} ({sample_id}): {created_at} (距上次 {interval:.0f}秒)")
            else:
                print(f"Run {run_id} ({sample_id}): {created_at} (首次缺失)")

            prev_time = current_time

    # 检查是否有其他配置在同一时间段也有缺失评估
    print("\n" + "=" * 80)
    print("检查其他配置在同一时间段的评估情况")
    print("=" * 80)

    # 获取缺失评估记录的时间范围
    if missing_runs:
        first_missing_time = missing_runs[0][2]
        last_missing_time = missing_runs[-1][2]

        print(f"\n缺失评估记录的时间范围: {first_missing_time} ~ {last_missing_time}")

        cursor.execute("""
            SELECT
                r.config_key,
                COUNT(*) as total,
                COUNT(CASE WHEN e.id IS NOT NULL THEN 1 END) as with_eval,
                COUNT(CASE WHEN e.id IS NULL THEN 1 END) as without_eval
            FROM benchmark_runs r
            LEFT JOIN benchmark_evaluations e ON r.id = e.run_id
            WHERE r.created_at BETWEEN ? AND ? AND r.status = 'completed'
            GROUP BY r.config_key
            ORDER BY r.config_key
        """, (first_missing_time, last_missing_time))

        config_stats = cursor.fetchall()

        print("\n各配置在该时间段的评估情况:")
        print("-" * 80)
        print("配置 | 总运行 | 有评估 | 无评估")
        print("-" * 80)

        for stat in config_stats:
            config, total, with_eval, without_eval = stat
            print(f"{config:20} | {total:6} | {with_eval:6} | {without_eval:6}")

    conn.close()

if __name__ == "__main__":
    check_time_distribution()