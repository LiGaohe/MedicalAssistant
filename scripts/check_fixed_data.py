import json

# 检查修复后的第一个样本
with open(r'd:\practice\MedicalAssisstant\data\experiments\results\ablation_no_field_revision_20260531_171229.jsonl', 'r', encoding='utf-8') as f:
    for line in f:
        record = json.loads(line)
        if record.get('sample_id') == '10027169':
            emr = record.get('emr_result', {})
            print("=== 样本 10027169 (修复后) ===")
            for section in ['subjective', 'objective', 'assessment', 'plan']:
                sec = emr.get(section, {})
                text = sec.get('text', '')
                print(f"[{section}].text: len={len(text)}")
                if text:
                    print(f"  内容: {text[:100]}...")
            break
