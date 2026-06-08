"""
检查特定 run_id 是否存在
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "database" / "benchmark.db"

conn = sqlite3.connect(str(DB_PATH))
cursor = conn.cursor()

# 检查日志中提到的 run_id
target_run_ids = [79, 82, 87, 90]

print("\n检查特定 run_id:")
for rid in target_run_ids:
    cursor.execute("SELECT id, sample_id, config_key, status, created_at FROM benchmark_runs WHERE id = ?", (rid,))
    row = cursor.fetchone()
    if row:
        print(f"  run_id={row[0]}, sample_id={row[1]}, config={row[2]}, status={row[3]}, created_at={row[4]}")
    else:
        print(f"  run_id={rid}: 不存在")

# 检查所有 10252824 和 10275183 的运行记录
print("\n\n10252824 的所有运行记录:")
cursor.execute("SELECT id, sample_id, config_key, status, created_at FROM benchmark_runs WHERE sample_id = '10252824' ORDER BY id")
for row in cursor.fetchall():
    cursor.execute("SELECT id FROM benchmark_evaluations WHERE run_id = ?", (row[0],))
    eval_id = cursor.fetchone()
    eval_status = f"eval_id={eval_id[0]}" if eval_id else "NO_EVAL"
    print(f"  run_id={row[0]}, config={row[2]}, status={row[3]}, created_at={row[4]}, {eval_status}")

print("\n10275183 的所有运行记录:")
cursor.execute("SELECT id, sample_id, config_key, status, created_at FROM benchmark_runs WHERE sample_id = '10275183' ORDER BY id")
for row in cursor.fetchall():
    cursor.execute("SELECT id FROM benchmark_evaluations WHERE run_id = ?", (row[0],))
    eval_id = cursor.fetchone()
    eval_status = f"eval_id={eval_id[0]}" if eval_id else "NO_EVAL"
    print(f"  run_id={row[0]}, config={row[2]}, status={row[3]}, created_at={row[4]}, {eval_status}")

# 检查 10134898 的所有运行记录
print("\n10134898 的所有运行记录:")
cursor.execute("SELECT id, sample_id, config_key, status, created_at FROM benchmark_runs WHERE sample_id = '10134898' ORDER BY id")
for row in cursor.fetchall():
    cursor.execute("SELECT id FROM benchmark_evaluations WHERE run_id = ?", (row[0],))
    eval_id = cursor.fetchone()
    eval_status = f"eval_id={eval_id[0]}" if eval_id else "NO_EVAL"
    print(f"  run_id={row[0]}, config={row[2]}, status={row[3]}, created_at={row[4]}, {eval_status}")

# 检查最大 run_id
cursor.execute("SELECT MAX(id) FROM benchmark_runs")
max_id = cursor.fetchone()[0]
print(f"\n最大 run_id: {max_id}")

# 检查是否有被删除的 run_id（ID不连续）
cursor.execute("SELECT id FROM benchmark_runs ORDER BY id")
all_ids = [row[0] for row in cursor.fetchall()]
missing_ids = set(range(1, max(all_ids) + 1)) - set(all_ids)
if missing_ids:
    print(f"\n缺失的 run_id (可能被删除): {sorted(missing_ids)[:30]}...")
else:
    print("\n无缺失的 run_id")

conn.close()
