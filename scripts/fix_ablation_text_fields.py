"""
从结构化SOAP字段构建可读文本的方法。
当text字段为空时，从结构化字段（chief_complaint、history_present_illness等）提取内容。
"""

import json
from pathlib import Path
from typing import Dict, Any

def build_text_from_structured(section_data: Dict[str, Any], section_name: str) -> str:
    """
    从SOAP节的结构化字段构建纯文本。
    
    Args:
        section_data: SOAP节的字典数据
        section_name: 节名称（subjective/objective/assessment/plan）
    
    Returns:
        拼接后的纯文本，如果text字段非空则直接返回text
    """
    # 如果text字段非空，优先使用
    text = section_data.get("text", "")
    if text:
        return text
    
    # 从结构化字段构建文本
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
        else:
            value = str(field_data) if field_data else ""
        
        if value:
            parts.append(f"{label}：{value}")
    
    return "；".join(parts) if parts else ""


def fix_emr_text_fields(emr_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    修复EMR结果中的text字段，如果为空则从结构化字段构建。
    
    Args:
        emr_result: EMR结果字典
    
    Returns:
        修复后的EMR结果（原地修改）
    """
    section_names = {
        "subjective": "主观资料",
        "objective": "客观资料",
        "assessment": "评估",
        "plan": "计划",
    }
    
    for section_name in ["subjective", "objective", "assessment", "plan"]:
        section_data = emr_result.get(section_name, {})
        if isinstance(section_data, dict):
            fixed_text = build_text_from_structured(section_data, section_name)
            section_data["text"] = fixed_text
    
    return emr_result


def fix_ablation_results(input_file: str, output_file: str, sample_ids: list):
    """
    修复消融实验结果文件中指定样本的text字段。
    
    Args:
        input_file: 输入的.jsonl文件路径
        output_file: 输出的.jsonl文件路径
        sample_ids: 需要修复的样本ID列表
    """
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
    
    # 在内存中修复
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
                    
                    # 检查是否有变化
                    if any(old_texts[sec] != new_texts[sec] for sec in old_texts):
                        fixed_count += 1
                        print(f"  样本 {record['sample_id']}: text字段已修复")
                        for sec in old_texts:
                            if old_texts[sec] != new_texts[sec]:
                                print(f"    [{sec}] 长度: {len(old_texts[sec])} -> {len(new_texts[sec])}")
            
            # 写入修复后的记录
            f_out.write(json.dumps(record, ensure_ascii=False) + "\n")
    
    print(f"\n修复完成:")
    print(f"  总样本数: {total_count}")
    print(f"  修复样本数: {fixed_count}")


if __name__ == "__main__":
    # 修复消融实验结果中的4个召回率为0的样本
    input_file = r'd:\practice\MedicalAssisstant\data\experiments\results\ablation_no_field_revision_20260531_171229.jsonl'
    output_file = r'd:\practice\MedicalAssisstant\data\experiments\results\ablation_no_field_revision_20260531_171229_fixed.jsonl'
    
    # 召回率为0的4个样本
    zero_recall_samples = ["10027169", "10055575", "10078738", "10134898"]
    
    print(f"修复 {len(zero_recall_samples)} 个召回率为0的样本:")
    for sid in zero_recall_samples:
        print(f"  - {sid}")
    print()
    
    fix_ablation_results(input_file, output_file, zero_recall_samples)
    
    # 备份原文件，替换为修复后的文件
    import shutil
    backup_file = input_file.replace('.jsonl', '_backup.jsonl')
    shutil.copy2(input_file, backup_file)
    shutil.move(output_file, input_file)
    
    print(f"\n原文件已备份至: {backup_file}")
    print(f"修复后的文件已替换原文件")
