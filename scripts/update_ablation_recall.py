"""更新消融实验结果文件中的关键召回率数据"""
import json
from pathlib import Path

eval_path = Path(r'd:\practice\MedicalAssisstant\data\experiments\results\ablation_no_field_revision_20260531_171229_eval_20260531_202641.jsonl')
orig_path = Path(r'd:\practice\MedicalAssisstant\data\experiments\results\ablation_no_field_revision_20260531_171229.jsonl')

with open(eval_path, 'r', encoding='utf-8') as ef:
    eval_lines = [json.loads(l) for l in ef if l.strip()]

with open(orig_path, 'r', encoding='utf-8') as of:
    orig_lines = [json.loads(l) for l in of if l.strip()]

eval_map = {e['sample_id']: e['llm_evaluation']['completeness'] for e in eval_lines}

for orig in orig_lines:
    sid = orig['sample_id']
    if sid in eval_map:
        orig.setdefault('llm_evaluation', {})
        orig['llm_evaluation']['completeness'] = eval_map[sid]
        print(f'{sid}: recall={eval_map[sid]["summary"]["recall_rate"]:.3f}')

with open(orig_path, 'w', encoding='utf-8') as of:
    for r in orig_lines:
        of.write(json.dumps(r, ensure_ascii=False) + '\n')

print(f'\n已更新 {len(eval_map)} 个样本的关键召回率数据')
