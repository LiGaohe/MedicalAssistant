"""修复完整管线结果中text字段为空的样本"""
import json
import shutil
from pathlib import Path
from typing import Dict, Any


def build_text_from_structured(section_data: Dict[str, Any], section_name: str) -> str:
    """从SOAP节的结构化字段构建纯文本。"""
    text = section_data.get("text", "")
    if text:
        return text
    
    field_labels = {
        "subjective": {
            "chief_complaint": "主诉",
            "history_present_illness": "现病史",
            "denied_symptoms": "否认症状",
            "past_history": "既往史",
        },
        "objective": {
            "physical_examination": "体格检查",
            "auxiliary_examination": "辅助检查",
        },
        "assessment": {
            "diagnosis": "诊断",
        },
        "plan": {
            "treatment": "治疗方案",
            "advice": "医嘱",
        },
    }
    
    labels = field_labels.get(section_name, {})
    parts = []
    
    for field_key, label in labels.items():
        field_data = section_data.get(field_key, {})
        if isinstance(field_data, dict):
            value = field_data.get("value", "")
        elif isinstance(field_data, str):
            value = field_data
        else:
            value = ""
        
        if value:
            parts.append(f"{label}：{value}")
    
    return "；".join(parts) if parts else ""


def fix_emr_text_fields(emr: Dict[str, Any]) -> None:
    """修复EMR中各SOAP节的text字段。"""
    for section in ['subjective', 'objective', 'assessment', 'plan']:
        if section in emr:
            emr[section]["text"] = build_text_from_structured(emr[section], section)


def fix_ablation_results(input_file: str, output_file: str, sample_ids: list):
    """修复消融实验结果文件中指定样本的text字段。"""
    input_path = Path(input_file)
    output_path = Path(output_file)
    
    sample_ids_set = set(sample_ids)
    fixed_count = 0
    total_count = 0
    
    records = []
    with open(input_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    
    with open(output_path, 'w', encoding='utf-8') as f_out:
        for record in records:
            total_count += 1
            
            if record.get('sample_id') in sample_ids_set:
                emr = record.get('emr_result')
                if emr and isinstance(emr, dict):
                    old_texts = {
                        sec: emr.get(sec, {}).get("text", "")
                        for sec in ['subjective', 'objective', 'assessment', 'plan']
                    }
                    
                    fix_emr_text_fields(emr)
                    
                    new_texts = {
                        sec: emr.get(sec, {}).get("text", "")
                        for sec in ['subjective', 'objective', 'assessment', 'plan']
                    }
                    
                    if any(old_texts[sec] != new_texts[sec] for sec in old_texts):
                        fixed_count += 1
                        print(f"  样本 {record['sample_id']}: text字段已修复")
                        for sec in old_texts:
                            if old_texts[sec] != new_texts[sec]:
                                print(f"    [{sec}] 长度: {len(old_texts[sec])} -> {len(new_texts[sec])}")
            
            f_out.write(json.dumps(record, ensure_ascii=False) + "\n")
    
    print(f"\n修复完成:")
    print(f"  总样本数: {total_count}")
    print(f"  修复样本数: {fixed_count}")


def main():
    # 修复完整管线的10个样本
    input_file = r'd:\practice\MedicalAssisstant\data\experiments\results\results_full_20260530_233325.jsonl'
    output_file = r'd:\practice\MedicalAssisstant\data\experiments\results\results_full_20260530_233325_fixed.jsonl'
    
    # 获取所有样本ID
    records = []
    with open(input_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    
    zero_recall_samples = [r['sample_id'] for r in records if r.get('status') == 'completed']
    
    print(f"修复完整管线的 {len(zero_recall_samples)} 个样本:")
    for sid in zero_recall_samples:
        print(f"  - {sid}")
    print()
    
    fix_ablation_results(input_file, output_file, zero_recall_samples)
    
    backup_file = input_file.replace('.jsonl', '_backup.jsonl')
    shutil.copy2(input_file, backup_file)
    shutil.move(output_file, input_file)
    
    print(f"\n原文件已备份至: {backup_file}")
    print(f"修复后的文件已替换原文件")


if __name__ == "__main__":
    main()
