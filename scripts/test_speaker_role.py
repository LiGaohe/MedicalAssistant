"""测试说话人角色识别模块"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

# Mock torch to avoid dependency
sys.modules['torch'] = MagicMock()

from backend.services.speaker_role_classifier import SpeakerRoleClassifier, SpeakerRole


def load_raw_asr_result(file_path: str = "output/raw_asr_result.json") -> list:
    """加载原始ASR结果"""
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    segments = []
    for item in data:
        if "spk" in item:
            segments.append({
                "speaker_id": f"spk{item['spk']}",
                "text": item.get("text", ""),
                "start_ms": item.get("start", 0),
                "end_ms": item.get("end", 0)
            })
        elif "sentence_info" in item:
            for sentence in item["sentence_info"]:
                if "spk" in sentence:
                    segments.append({
                        "speaker_id": f"spk{sentence.get('spk', 0)}",
                        "text": sentence.get("text", ""),
                        "start_ms": sentence.get("start", 0),
                        "end_ms": sentence.get("end", 0)
                    })
        elif "sentences" in item:
            for sentence in item["sentences"]:
                if "spk" in sentence:
                    segments.append({
                        "speaker_id": f"spk{sentence.get('spk', 0)}",
                        "text": sentence.get("text", ""),
                        "start_ms": sentence.get("start", 0),
                        "end_ms": sentence.get("end", 0)
                    })
    
    return segments


def display_comparison(segments: list, classified_segments: list):
    """显示修正前后的对比"""
    print("\n" + "=" * 80)
    print("说话人角色识别结果对比")
    print("=" * 80)
    
    print("\n{:<4} {:<12} {:<12} {:<8} {}".format(
        "序号", "原始角色", "修正角色", "置信度", "文本内容"
    ))
    print("-" * 80)
    
    for i, seg in enumerate(classified_segments):
        original = seg.original_role.value
        corrected = seg.corrected_role.value
        confidence = f"{seg.confidence:.2f}"
        text = seg.text[:40] + "..." if len(seg.text) > 40 else seg.text
        
        changed = "✓" if seg.original_role != seg.corrected_role else ""
        
        print("{:<4} {:<12} {:<12} {:<8} {} {}".format(
            i + 1, original, corrected, confidence, text, changed
        ))
        
        if seg.correction_reason and seg.original_role != seg.corrected_role:
            print("      └─ 原因: {}".format(seg.correction_reason))


def display_summary(summary: dict):
    """显示统计摘要"""
    print("\n" + "=" * 80)
    print("统计摘要")
    print("=" * 80)
    
    print(f"总片段数: {summary['total_segments']}")
    print(f"修正数量: {summary['corrected_count']}")
    print(f"修正率: {summary['correction_rate']:.1%}")
    print(f"医生片段: {summary['doctor_segments']}")
    print(f"患者片段: {summary['patient_segments']}")
    print(f"未知片段: {summary['unknown_segments']}")
    print(f"平均置信度: {summary['avg_confidence']:.2f}")


def display_dialogue(classified_segments: list):
    """以对话形式显示结果"""
    print("\n" + "=" * 80)
    print("对话内容（修正后）")
    print("=" * 80 + "\n")
    
    for seg in classified_segments:
        role = "医生" if seg.corrected_role == SpeakerRole.DOCTOR else "患者"
        print(f"[{role}]: {seg.text}")


def main():
    print("=" * 80)
    print("说话人角色识别模块测试")
    print("=" * 80)
    
    segments = load_raw_asr_result()
    
    if not segments:
        print("错误: 未找到任何片段数据")
        return
    
    print(f"\n加载了 {len(segments)} 个片段")
    
    classifier = SpeakerRoleClassifier()
    
    speaker_mapping, classified_segments = classifier.correct_speaker_mapping(segments)
    
    display_comparison(segments, classified_segments)
    
    summary = classifier.get_correction_summary(classified_segments)
    display_summary(summary)
    
    display_dialogue(classified_segments)
    
    print("\n" + "=" * 80)
    print("说话人映射结果")
    print("=" * 80)
    for speaker_id, role in speaker_mapping.items():
        print(f"  {speaker_id} → {role}")


if __name__ == "__main__":
    main()
