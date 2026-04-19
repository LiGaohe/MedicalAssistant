"""
从测试数据集生成调试测试对话文件

将test.json中的对话转换为调试模式可用的格式
"""

import json
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data" / "text"

def load_test_data():
    """加载测试数据集"""
    test_file = DATA_DIR / "test.json"
    test_input_file = DATA_DIR / "test_input.json"
    
    with open(test_file, encoding='utf-8') as f:
        test_data = json.load(f)
    
    with open(test_input_file, encoding='utf-8') as f:
        test_input_data = json.load(f)
    
    return test_data, test_input_data


def convert_to_debug_format(dialogue: list) -> str:
    """将对话转换为调试模式格式"""
    lines = []
    for turn in dialogue:
        speaker = turn.get("speaker", "unknown")
        text = turn.get("sentence", "")
        lines.append(f"[{speaker}]: {text}")
    return "\n".join(lines)


def generate_test_dialogs(output_file: str = "test_dialogs.txt", num_samples: int = 10):
    """生成测试对话文件"""
    test_data, test_input_data = load_test_data()
    
    sample_ids = list(test_data.keys())[:num_samples]
    
    output_path = DATA_DIR / output_file
    
    with open(output_path, 'w', encoding='utf-8') as f:
        for i, sample_id in enumerate(sample_ids, 1):
            test_sample = test_data.get(sample_id, {})
            test_input_sample = test_input_data.get(sample_id, {})
            
            diagnosis = test_sample.get("diagnosis", "未知")
            symptoms = test_sample.get("explicit_info", {}).get("Symptom", [])
            
            dialogue = test_input_sample.get("dialogue", [])
            dialog_text = convert_to_debug_format(dialogue)
            
            all_symptoms = set(symptoms)
            for turn in test_sample.get("dialogue", []):
                for s in turn.get("symptom_norm", []):
                    all_symptoms.add(s)
            
            f.write(f"=== 样本 {i} (ID: {sample_id}) ===\n")
            f.write(f"诊断: {diagnosis}\n")
            f.write(f"症状: {', '.join(all_symptoms) if all_symptoms else '无'}\n")
            f.write(f"对话轮次: {len(dialogue)}\n")
            f.write("-" * 50 + "\n")
            f.write(dialog_text)
            f.write("\n" + "=" * 50 + "\n\n")
    
    print(f"已生成测试对话文件: {output_path}")
    print(f"包含 {len(sample_ids)} 个样本")


def generate_single_sample(sample_id: str, output_file: str = None):
    """生成单个样本的测试对话"""
    test_data, test_input_data = load_test_data()
    
    test_sample = test_data.get(sample_id, {})
    test_input_sample = test_input_data.get(sample_id, {})
    
    if not test_sample:
        print(f"未找到样本: {sample_id}")
        return
    
    diagnosis = test_sample.get("diagnosis", "未知")
    symptoms = test_sample.get("explicit_info", {}).get("Symptom", [])
    
    dialogue = test_input_sample.get("dialogue", [])
    dialog_text = convert_to_debug_format(dialogue)
    
    all_symptoms = set(symptoms)
    for turn in test_sample.get("dialogue", []):
        for s in turn.get("symptom_norm", []):
            all_symptoms.add(s)
    
    print("=" * 60)
    print(f"样本ID: {sample_id}")
    print(f"诊断: {diagnosis}")
    print(f"症状: {', '.join(all_symptoms) if all_symptoms else '无'}")
    print(f"对话轮次: {len(dialogue)}")
    print("=" * 60)
    print("\n【复制以下对话到调试模式】\n")
    print(dialog_text)
    print("\n" + "=" * 60)
    
    if output_file:
        output_path = DATA_DIR / output_file
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(f"样本ID: {sample_id}\n")
            f.write(f"诊断: {diagnosis}\n")
            f.write(f"症状: {', '.join(all_symptoms) if all_symptoms else '无'}\n")
            f.write("-" * 50 + "\n")
            f.write(dialog_text)
        print(f"\n已保存到: {output_path}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="生成测试对话")
    parser.add_argument("-n", "--num-samples", type=int, default=10,
                        help="生成样本数量")
    parser.add_argument("-i", "--sample-id", type=str, default=None,
                        help="指定样本ID")
    parser.add_argument("-o", "--output", type=str, default="test_dialogs.txt",
                        help="输出文件名")
    
    args = parser.parse_args()
    
    if args.sample_id:
        generate_single_sample(args.sample_id, args.output)
    else:
        generate_test_dialogs(args.output, args.num_samples)
