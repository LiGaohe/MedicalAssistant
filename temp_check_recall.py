import json

f = open('data/experiments/results/ablation_no_field_revision_20260531_171229_eval_20260531_181523.jsonl')
lines = [json.loads(line) for line in f]
f.close()

print("=== 样本详细分析 ===")
print(f"总样本数: {len(lines)}")
print()

for i, line in enumerate(lines):
    sample_id = line.get('sample_id', 'unknown')
    config = line.get('config', 'unknown')
    recall_data = line.get('llm_evaluation', {}).get('completeness', {}).get('summary', {})
    recall_rate = recall_data.get('recall_rate', 0)
    
    # 获取EMR各节text长度
    emr_result = line.get('emr_result', {})
    subjective_text = emr_result.get('subjective', {}).get('text', '')
    objective_text = emr_result.get('objective', {}).get('text', '')
    assessment_text = emr_result.get('assessment', {}).get('text', '')
    plan_text = emr_result.get('plan', {}).get('text', '')
    
    print(f"样本{i+1}: {sample_id} ({config})")
    print(f"  关键召回率: {recall_rate:.4f}")
    print(f"  总事实数: {recall_data.get('total_facts', 0)}")
    print(f"  完全覆盖: {recall_data.get('full_coverage_count', 0)}")
    print(f"  部分覆盖: {recall_data.get('partial_coverage_count', 0)}")
    print(f"  未覆盖: {recall_data.get('none_coverage_count', 0)}")
    print(f"  Subjective text长度: {len(subjective_text)}")
    print(f"  Objective text长度: {len(objective_text)}")
    print(f"  Assessment text长度: {len(assessment_text)}")
    print(f"  Plan text长度: {len(plan_text)}")
    print(f"  所有text都为空: {all(len(t)==0 for t in [subjective_text, objective_text, assessment_text, plan_text])}")
    print()
