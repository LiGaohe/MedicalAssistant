"""
检查 full 配置缺失评估记录的时间线分析
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "database" / "benchmark.db"

conn = sqlite3.connect(str(DB_PATH))
cursor = conn.cursor()

print("\n" + "="*80)
print("full 配置运行记录时间线")
print("="*80)

cursor.execute("""
    SELECT br.id, br.sample_id, br.status, br.created_at,
           be.id as eval_id, be.error_message as eval_error
    FROM benchmark_runs br
    LEFT JOIN benchmark_evaluations be ON br.id = be.run_id
    WHERE br.config_key = 'full'
    ORDER BY br.id
""")

rows = cursor.fetchall()

print(f"\n{'run_id':<8} {'sample_id':<12} {'status':<12} {'eval_id':<8} {'created_at':<22} {'eval_error'}")
print("-"*100)

no_eval_count = 0
has_eval_count = 0
failed_count = 0

for run_id, sample_id, status, created_at, eval_id, eval_error in rows:
    eval_status = str(eval_id) if eval_id else "NONE"
    error_short = (eval_error[:40] + "...") if eval_error else ""

    if status == "failed":
        failed_count += 1
        marker = "[FAIL]"
    elif eval_id is None:
        no_eval_count += 1
        marker = "[NO_EVAL]"
    else:
        has_eval_count += 1
        marker = "[OK]"

    print(f"{run_id:<8} {sample_id:<12} {status:<12} {eval_status:<8} {created_at:<22} {error_short}  {marker}")

print(f"\n统计: 有评估={has_eval_count}, 无评估={no_eval_count}, 失败={failed_count}, 总计={len(rows)}")

# 检查无评估记录的创建时间分布
print("\n" + "="*80)
print("无评估记录的时间分布")
print("="*80)

cursor.execute("""
    SELECT date(br.created_at) as date, COUNT(*) as cnt
    FROM benchmark_runs br
    LEFT JOIN benchmark_evaluations be ON br.id = be.run_id
    WHERE br.config_key = 'full' AND be.id IS NULL
    GROUP BY date(br.created_at)
    ORDER BY date(br.created_at)
""")

for date, cnt in cursor.fetchall():
    print(f"  {date}: {cnt}条")

# 检查有评估记录的创建时间分布
print("\n" + "="*80)
print("有评估记录的时间分布")
print("="*80)

cursor.execute("""
    SELECT date(br.created_at) as date, COUNT(*) as cnt
    FROM benchmark_runs br
    JOIN benchmark_evaluations be ON br.id = be.run_id
    WHERE br.config_key = 'full'
    GROUP BY date(br.created_at)
    ORDER BY date(br.created_at)
""")

for date, cnt in cursor.fetchall():
    print(f"  {date}: {cnt}条")

conn.close()
