"""
详细检查缺失指标的记录
"""

import sqlite3
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

DB_PATH = project_root / "data" / "database" / "benchmark.db"


def check_missing_details():
    """详细检查缺失指标"""
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    print("\n" + "="*80)
    print("详细检查缺失指标的记录")
    print("="*80)

    # 1. 检查缺少评估记录的运行
    print("\n【1】缺少评估记录的运行记录:")
    print("-"*80)
    cursor.execute("""
        SELECT br.id, br.sample_id, br.config_key, br.status, br.error_message
        FROM benchmark_runs br
        LEFT JOIN benchmark_evaluations be ON br.id = be.run_id
        WHERE be.id IS NULL
        ORDER BY br.config_key, br.id
    """)
    missing_evals = cursor.fetchall()

    if missing_evals:
        for run_id, sample_id, config_key, status, error_msg in missing_evals:
            print(f"  run_id={run_id}, sample_id={sample_id}, config={config_key}, status={status}")
            if error_msg:
                print(f"    错误: {error_msg[:100]}...")
    else:
        print("  无")

    # 2. 检查评估指标为NULL的记录
    print("\n【2】评估指标为NULL的记录:")
    print("-"*80)

    metrics = ["support_rate", "hallucination_rate", "recall_rate", "omission_rate"]

    for metric in metrics:
        cursor.execute(f"""
            SELECT be.id, br.sample_id, br.config_key, be.error_message
            FROM benchmark_evaluations be
            JOIN benchmark_runs br ON be.run_id = br.id
            WHERE be.{metric} IS NULL
        """)
        null_records = cursor.fetchall()

        if null_records:
            print(f"\n  {metric} 为 NULL 的记录 ({len(null_records)}条):")
            for eval_id, sample_id, config_key, error_msg in null_records:
                print(f"    eval_id={eval_id}, sample_id={sample_id}, config={config_key}")
                if error_msg:
                    print(f"      错误: {error_msg[:100]}...")
        else:
            print(f"  {metric}: 无NULL记录")

    # 3. 检查full配置的详细情况
    print("\n【3】full 配置的详细情况:")
    print("-"*80)

    cursor.execute("""
        SELECT br.id, br.sample_id, br.status, be.id as eval_id, be.error_message
        FROM benchmark_runs br
        LEFT JOIN benchmark_evaluations be ON br.id = be.run_id
        WHERE br.config_key = 'full'
        ORDER BY br.id
    """)
    full_records = cursor.fetchall()

    has_eval = 0
    no_eval = 0
    failed = 0

    for run_id, sample_id, status, eval_id, error_msg in full_records:
        if status == "failed":
            failed += 1
            print(f"  [FAILED] run_id={run_id}, sample_id={sample_id}")
        elif eval_id is None:
            no_eval += 1
            print(f"  [NO_EVAL] run_id={run_id}, sample_id={sample_id}")
        else:
            has_eval += 1
            if error_msg:
                print(f"  [ERROR] run_id={run_id}, sample_id={sample_id}, eval_id={eval_id}")
                print(f"          错误: {error_msg[:80]}...")

    print(f"\n  统计: 有评估={has_eval}, 无评估={no_eval}, 失败={failed}")

    # 4. 检查运行指标为0或NULL的记录
    print("\n【4】运行指标为0或NULL的记录:")
    print("-"*80)

    cursor.execute("""
        SELECT id, sample_id, config_key, llm_call_count, char_count, elapsed_seconds, status
        FROM benchmark_runs
        WHERE llm_call_count = 0 OR char_count = 0 OR elapsed_seconds = 0
           OR llm_call_count IS NULL OR char_count IS NULL OR elapsed_seconds IS NULL
    """)
    zero_metrics = cursor.fetchall()

    if zero_metrics:
        for run_id, sample_id, config_key, llm_calls, char_count, elapsed, status in zero_metrics:
            print(f"  run_id={run_id}, sample_id={sample_id}, config={config_key}, status={status}")
            print(f"    llm_call_count={llm_calls}, char_count={char_count}, elapsed_seconds={elapsed}")
    else:
        print("  无")

    conn.close()

    print("\n" + "="*80)


if __name__ == "__main__":
    check_missing_details()