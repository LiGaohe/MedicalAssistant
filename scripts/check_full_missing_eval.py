"""
检查 full 配置中哪些 sample 完全没有评估记录
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "database" / "benchmark.db"

conn = sqlite3.connect(str(DB_PATH))
cursor = conn.cursor()

# 1. 找出 full 配置中完全没有评估的 sample
print("\n" + "="*80)
print("full 配置：完全没有评估记录的 sample")
print("="*80)

cursor.execute("""
    SELECT br.sample_id, COUNT(*) as run_count,
           SUM(CASE WHEN be.id IS NOT NULL THEN 1 ELSE 0 END) as eval_count
    FROM benchmark_runs br
    LEFT JOIN benchmark_evaluations be ON br.id = be.run_id
    WHERE br.config_key = 'full'
    GROUP BY br.sample_id
    HAVING eval_count = 0
    ORDER BY br.sample_id
""")

no_eval_samples = cursor.fetchall()
if no_eval_samples:
    for sample_id, run_count, eval_count in no_eval_samples:
        print(f"  sample_id={sample_id}, 运行次数={run_count}, 评估次数={eval_count}")
else:
    print("  无")

# 2. 找出 full 配置中有评估的 sample
print("\n" + "="*80)
print("full 配置：有评估记录的 sample")
print("="*80)

cursor.execute("""
    SELECT br.sample_id, COUNT(*) as run_count,
           SUM(CASE WHEN be.id IS NOT NULL THEN 1 ELSE 0 END) as eval_count
    FROM benchmark_runs br
    LEFT JOIN benchmark_evaluations be ON br.id = be.run_id
    WHERE br.config_key = 'full'
    GROUP BY br.sample_id
    HAVING eval_count > 0
    ORDER BY br.sample_id
""")

has_eval_samples = cursor.fetchall()
for sample_id, run_count, eval_count in has_eval_samples:
    print(f"  sample_id={sample_id}, 运行次数={run_count}, 评估次数={eval_count}")

# 3. 检查其他配置是否有类似问题
print("\n" + "="*80)
print("所有配置：缺少评估的 sample 统计")
print("="*80)

cursor.execute("""
    SELECT br.config_key,
           COUNT(DISTINCT br.sample_id) as total_samples,
           COUNT(DISTINCT CASE WHEN be.id IS NULL THEN br.sample_id END) as no_eval_samples
    FROM benchmark_runs br
    LEFT JOIN benchmark_evaluations be ON br.id = be.run_id
    WHERE br.status = 'completed'
    GROUP BY br.config_key
    ORDER BY br.config_key
""")

for config_key, total, no_eval in cursor.fetchall():
    # 需要更精确地计算：一个sample只要有一个run有eval就算有
    cursor.execute("""
        SELECT COUNT(DISTINCT sub.sample_id)
        FROM (
            SELECT br.sample_id, SUM(CASE WHEN be.id IS NOT NULL THEN 1 ELSE 0 END) as eval_count
            FROM benchmark_runs br
            LEFT JOIN benchmark_evaluations be ON br.id = be.run_id
            WHERE br.config_key = ? AND br.status = 'completed'
            GROUP BY br.sample_id
            HAVING eval_count = 0
        ) sub
    """, (config_key,))
    truly_no_eval = cursor.fetchone()[0]
    print(f"  {config_key}: 总sample={total}, 完全无评估的sample={truly_no_eval}")

# 4. 检查 full 配置的重复运行问题
print("\n" + "="*80)
print("full 配置：每个 sample 的运行次数分布")
print("="*80)

cursor.execute("""
    SELECT run_count, COUNT(*) as sample_count
    FROM (
        SELECT sample_id, COUNT(*) as run_count
        FROM benchmark_runs
        WHERE config_key = 'full'
        GROUP BY sample_id
    )
    GROUP BY run_count
    ORDER BY run_count
""")

for run_count, sample_count in cursor.fetchall():
    print(f"  运行{run_count}次的sample: {sample_count}个")

# 5. 检查 full 配置中无评估的 run 是否有 emr_result
print("\n" + "="*80)
print("full 配置：无评估 run 的 emr_result 状态")
print("="*80)

cursor.execute("""
    SELECT br.id, br.sample_id,
           CASE WHEN br.emr_result IS NOT NULL THEN 'HAS_EMR' ELSE 'NO_EMR' END as emr_status,
           br.created_at
    FROM benchmark_runs br
    LEFT JOIN benchmark_evaluations be ON br.id = be.run_id
    WHERE br.config_key = 'full' AND be.id IS NULL AND br.status = 'completed'
    ORDER BY br.id
""")

has_emr = 0
no_emr = 0
for run_id, sample_id, emr_status, created_at in cursor.fetchall():
    if emr_status == 'HAS_EMR':
        has_emr += 1
    else:
        no_emr += 1
        print(f"  [NO_EMR] run_id={run_id}, sample_id={sample_id}, created_at={created_at}")

print(f"\n  无评估的completed运行: 有EMR={has_emr}, 无EMR={no_emr}")

conn.close()
