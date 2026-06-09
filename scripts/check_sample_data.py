"""
检查缺失评估记录的样本数据
"""
import sqlite3
import json

def check_sample_data():
    db_path = "data/database/benchmark.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print("=" * 80)
    print("检查缺失评估记录的样本数据")
    print("=" * 80)

    # 找出缺失评估记录的成功运行
    cursor.execute("""
        SELECT
            r.id,
            r.sample_id,
            r.visit_id,
            r.status,
            r.emr_result,
            r.error_message,
            r.created_at
        FROM benchmark_runs r
        LEFT JOIN benchmark_evaluations e ON r.id = e.run_id
        WHERE r.config_key = 'full' AND r.status = 'completed' AND e.id IS NULL
        ORDER BY r.created_at
    """)

    missing_runs = cursor.fetchall()

    print(f"\n共 {len(missing_runs)} 条缺失评估记录的运行:")
    print("=" * 80)

    for run in missing_runs:
        run_id, sample_id, visit_id, status, emr_result, error_msg, created_at = run

        print(f"\nRun ID: {run_id}, 样本ID: {sample_id}")
        print(f"状态: {status}, 创建时间: {created_at}")
        print(f"错误信息: {error_msg}")

        # 检查EMR结果
        if emr_result:
            emr = json.loads(emr_result)
            print(f"EMR结果:")
            print(f"  Subjective: {emr.get('subjective', {}).get('text', 'N/A')[:50]}...")
            print(f"  Objective: {emr.get('objective', {}).get('text', 'N/A')[:50]}...")
            print(f"  Assessment: {emr.get('assessment', {}).get('text', 'N/A')[:50]}...")
            print(f"  Plan: {emr.get('plan', {}).get('text', 'N/A')[:50]}...")
        else:
            print("EMR结果: NULL")

        # 检查样本文件中是否有dialogue_text
        # 需要读取样本文件
        sample_file_path = "data/experiments/test_samples.json"
        try:
            with open(sample_file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 正确读取samples数组
            samples = data.get("samples", [])

            # 找到对应的样本
            matching_sample = None
            for s in samples:
                if isinstance(s, dict) and s.get("sample_id") == sample_id:
                    matching_sample = s
                    break

            if matching_sample:
                dialogue_text = matching_sample.get("dialogue_text", "")
                print(f"\n样本文件中的dialogue_text:")
                if dialogue_text:
                    print(f"  长度: {len(dialogue_text)} 字符")
                    print(f"  前100字符: {dialogue_text[:100]}...")
                else:
                    print(f"  ❌ dialogue_text为空或不存在")
            else:
                print(f"\n❌ 样本文件中未找到sample_id={sample_id}")

        except Exception as e:
            print(f"\n读取样本文件失败: {e}")

    # 检查所有full配置的运行记录的error_message
    print("\n" + "=" * 80)
    print("检查所有full配置运行记录的error_message")
    print("=" * 80)

    cursor.execute("""
        SELECT
            r.id,
            r.sample_id,
            r.status,
            r.error_message,
            e.id as eval_id
        FROM benchmark_runs r
        LEFT JOIN benchmark_evaluations e ON r.id = e.run_id
        WHERE r.config_key = 'full'
        ORDER BY r.id
    """)

    all_runs = cursor.fetchall()

    print("\nRun ID | 样本ID | 状态 | 错误信息 | 有评估")
    print("-" * 80)

    for run in all_runs:
        run_id, sample_id, status, error_msg, eval_id = run
        has_eval = "有" if eval_id else "无"
        error_display = error_msg[:50] if error_msg else "None"
        print(f"{run_id:6} | {sample_id:10} | {status:8} | {error_display:50} | {has_eval}")

    conn.close()

if __name__ == "__main__":
    check_sample_data()