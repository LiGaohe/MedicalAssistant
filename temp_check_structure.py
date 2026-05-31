import json
import sys

# 检查第一个召回率为0的样本的原始emr_result结构
with open('data/experiments/results/ablation_no_field_revision_20260531_171229.jsonl', 'r') as f:
    for line in f:
        data = json.loads(line)
        if data['sample_id'] == '10027169':
            emr = data['emr_result']
            print("=== 样本10027169的emr_result结构 ===")
            print(f"subjective.keys(): {emr['subjective'].keys()}")
            print(f"subjective.text: '{emr['subjective'].get('text', 'MISSING')}'")
            print(f"subjective.chief_complaint: {emr['subjective'].get('chief_complaint', {})}")
            print(f"subjective.history_present_illness: {emr['subjective'].get('history_present_illness', {})}")
            print()
            print(f"objective.keys(): {emr['objective'].keys()}")
            print(f"objective.text: '{emr['objective'].get('text', 'MISSING')}'")
            print()
            print(f"assessment.keys(): {emr['assessment'].keys()}")
            print(f"assessment.text: '{emr['assessment'].get('text', 'MISSING')}'")
            print()
            print(f"plan.keys(): {emr['plan'].keys()}")
            print(f"plan.text: '{emr['plan'].get('text', 'MISSING')}'")
            sys.exit(0)
