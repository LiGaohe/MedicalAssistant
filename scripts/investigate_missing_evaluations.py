"""
深入检查full配置缺失评估记录的原因
"""
import sqlite3
import json

def investigate_missing_evaluations():
    db_path = "data/database/benchmark.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print("=" * 80)
    print("深入检查full配置缺失评估记录的原因")
    print("=" * 80)

    # 找出缺失评估记录的成功运行
    cursor.execute("""
        SELECT
            r.id,
            r.sample_id,
            r.visit_id,
            r.status,
            r.elapsed_seconds,
            r.llm_call_count,
            r.char_count,
            r.token_count,
            r.emr_result,
            r.stage_breakdown,
            r.error_message,
            r.created_at
        FROM benchmark_runs r
        LEFT JOIN benchmark_evaluations e ON r.id = e.run_id
        WHERE r.config_key = 'full' AND r.status = 'completed' AND e.id IS NULL
        ORDER BY r.created_at
    """)

    missing_runs = cursor.fetchall()

    print(f"\n发现 {len(missing_runs)} 条成功运行缺失评估记录:")
    print("=" * 80)

    for run in missing_runs:
        run_id, sample_id, visit_id, status, elapsed, llm_calls, char_count, token_count, emr_result, stage_breakdown, error_msg, created_at = run

        print(f"\n{'='*80}")
        print(f"Run ID: {run_id}")
        print(f"样本ID: {sample_id}")
        print(f"Visit ID: {visit_id}")
        print(f"状态: {status}")
        print(f"耗时: {elapsed:.2f}秒")
        print(f"LLM调用次数: {llm_calls}")
        print(f"字符消耗: {char_count}")
        print(f"Token消耗: {token_count}")
        print(f"创建时间: {created_at}")
        print(f"错误信息: {error_msg}")

        # 检查EMR结果
        if emr_result:
            emr = json.loads(emr_result)
            print(f"\nEMR结果:")
            print(f"  Subjective: {len(emr.get('subjective', {}).get('text', ''))} 字符")
            print(f"  Objective: {len(emr.get('objective', {}).get('text', ''))} 字符")
            print(f"  Assessment: {len(emr.get('assessment', {}).get('text', ''))} 字符")
            print(f"  Plan: {len(emr.get('plan', {}).get('text', ''))} 字符")
        else:
            print(f"\nEMR结果: NULL")

        # 检查stage_breakdown
        if stage_breakdown:
            stages = json.loads(stage_breakdown)
            print(f"\n阶段明细:")
            for stage_name, stage_stats in stages.items():
                print(f"  {stage_name}:")
                print(f"    调用次数: {stage_stats.get('call_count', 0)}")
                print(f"    总字符: {stage_stats.get('total_chars', 0)}")
                print(f"    总token: {stage_stats.get('total_tokens', 0)}")
        else:
            print(f"\n阶段明细: NULL")

        # 检查LLM调用记录
        cursor.execute("""
            SELECT
                id,
                stage,
                evaluator,
                success,
                prompt_tokens,
                completion_tokens,
                total_tokens,
                error_message,
                created_at
            FROM benchmark_llm_calls
            WHERE run_id = ?
            ORDER BY created_at
        """, (run_id,))

        llm_call_records = cursor.fetchall()

        print(f"\nLLM调用记录 ({len(llm_call_records)} 条):")
        if llm_call_records:
            for call in llm_call_records:
                call_id, stage, evaluator, success, prompt_tokens, completion_tokens, total_tokens, call_error, call_created = call
                print(f"  Call {call_id}: stage={stage}, evaluator={evaluator}, success={success}, tokens={total_tokens}, error={call_error}")
        else:
            print("  无LLM调用记录")

        # 检查是否有evaluation阶段的LLM调用
        eval_calls = [c for c in llm_call_records if c[1] == 'evaluation']
        if eval_calls:
            print(f"\n  ⚠️ 发现 {len(eval_calls)} 条evaluation阶段的LLM调用，但未生成评估记录！")
        else:
            print(f"\n  ❌ 无evaluation阶段的LLM调用")

    # 统计分析
    print("\n" + "=" * 80)
    print("统计分析")
    print("=" * 80)

    # 检查所有full配置的运行记录的LLM调用情况
    cursor.execute("""
        SELECT
            r.id,
            r.sample_id,
            r.status,
            COUNT(l.id) as llm_call_count,
            COUNT(CASE WHEN l.stage = 'evaluation' THEN 1 END) as eval_call_count,
            COUNT(e.id) as has_evaluation
        FROM benchmark_runs r
        LEFT JOIN benchmark_llm_calls l ON r.id = l.run_id
        LEFT JOIN benchmark_evaluations e ON r.id = e.run_id
        WHERE r.config_key = 'full'
        GROUP BY r.id
        ORDER BY r.id
    """)

    all_runs_stats = cursor.fetchall()

    print("\n所有full配置运行记录的LLM调用情况:")
    print("-" * 80)
    print("Run ID | 样本ID | 状态 | 总LLM调用 | Evaluation调用 | 有评估记录")
    print("-" * 80)

    for stat in all_runs_stats:
        run_id, sample_id, status, total_calls, eval_calls, has_eval = stat
        eval_status = "有评估" if has_eval else "无评估"
        print(f"{run_id:6} | {sample_id:10} | {status:8} | {total_calls:8} | {eval_calls:13} | {eval_status}")

    # 检查时间分布
    print("\n" + "=" * 80)
    print("时间分布分析")
    print("=" * 80)

    cursor.execute("""
        SELECT
            DATE(created_at) as date,
            COUNT(*) as total_runs,
            COUNT(CASE WHEN e.id IS NOT NULL THEN 1 END) as with_eval,
            COUNT(CASE WHEN e.id IS NULL THEN 1 END) as without_eval
        FROM benchmark_runs r
        LEFT JOIN benchmark_evaluations e ON r.id = e.run_id
        WHERE r.config_key = 'full' AND r.status = 'completed'
        GROUP BY DATE(created_at)
        ORDER BY date
    """)

    time_stats = cursor.fetchall()

    print("\n按日期统计:")
    print("-" * 80)
    print("日期 | 总运行 | 有评估 | 无评估")
    print("-" * 80)

    for stat in time_stats:
        date, total, with_eval, without_eval = stat
        print(f"{date} | {total:6} | {with_eval:6} | {without_eval:6}")

    conn.close()

if __name__ == "__main__":
    investigate_missing_evaluations()