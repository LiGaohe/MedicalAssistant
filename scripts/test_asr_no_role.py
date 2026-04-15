"""
测试简化后的ASR模块（无角色识别）
"""
import sys
from pathlib import Path
import json

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.services.asr_service import ASRService


def test_asr_without_role_classification():
    """测试简化后的ASR模块"""
    print("=" * 80)
    print("测试简化后的ASR模块（无角色识别）")
    print("=" * 80)
    
    audio_path = input("请输入音频文件路径: ").strip()
    
    if not audio_path:
        print("未提供音频文件，测试结束")
        return
    
    audio_path = Path(audio_path)
    if not audio_path.exists():
        print(f"音频文件不存在: {audio_path}")
        return
    
    print(f"\n正在处理音频: {audio_path}")
    
    config = {
        "device": "cpu",
        "enable_diarization": True,
        "enable_sentence_split": True,
        "split_gap_threshold_ms": 800,
    }
    
    service = ASRService(config)
    
    print("\n正在初始化ASR服务...")
    service.initialize()
    print("✓ 初始化完成")
    
    try:
        result = service.transcribe_with_diarization(audio_path)
        
        print("\n" + "=" * 80)
        print("转写结果")
        print("=" * 80)
        print(f"音频时长: {result['duration']:.2f} 秒")
        print(f"推理时间: {result['inference_time']:.2f} 秒")
        print(f"对话轮数: {len(result['turns'])}")
        
        if "sentence_splits" in result:
            print(f"句子拆分记录: {len(result['sentence_splits'])} 条")
        
        print("\n" + "=" * 80)
        print("对话内容")
        print("=" * 80)
        
        for turn in result["turns"]:
            speaker_id = turn["speaker_id"]
            text = turn["text"]
            start_ms = turn["start_ms"]
            end_ms = turn["end_ms"]
            
            start_sec = start_ms / 1000
            end_sec = end_ms / 1000
            
            print(f"\n[{turn['turn_index']}] {speaker_id}")
            print(f"    时间: {start_sec:.2f}s - {end_sec:.2f}s")
            print(f"    文本: {text}")
        
        output_file = Path("output/asr_result_no_role.json")
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        print(f"\n✓ 结果已保存到: {output_file}")
        
    except Exception as e:
        print(f"\n✗ 错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    test_asr_without_role_classification()
