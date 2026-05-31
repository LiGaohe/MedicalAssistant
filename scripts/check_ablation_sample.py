import json

with open(r'd:\practice\MedicalAssisstant\data\experiments\results\ablation_no_field_revision_20260531_171229.jsonl', 'r', encoding='utf-8') as f:
    for line in f:
        record = json.loads(line)
        if record.get('sample_id') == '10027169':
            emr = record.get('emr_result', {})
            print("=== 样本 10027169 (ablation_no_field_revision) ===")
            for section in ['subjective', 'objective', 'assessment', 'plan']:
                sec = emr.get(section, {})
                print(f"\n[{section}]:")
                for k, v in sec.items():
                    if k == 'text':
                        print(f"  text: '{v}' (len={len(v) if v else 0})")
                    elif k not in ('evidence_traces',):
                        if isinstance(v, dict):
                            print(f"  {k}: {{'value': '{v.get('value', '')[:50]}...', 'evidence_traces': []}}")
                        else:
                            print(f"  {k}: {v}")
            break
