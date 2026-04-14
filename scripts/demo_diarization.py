"""
说话人分离功能演示脚本
演示如何使用 funASR 的说话人分离功能处理医患对话音频
"""
import sys
from pathlib import Path
import json

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.asr import FunASREngine
from backend.services.asr_service import ASRService


def demo_basic_usage():
    """基础用法演示"""
    print("\n" + "=" * 60)
    print("演示 1: 基础用法 - 直接使用 FunASREngine")
    print("=" * 60)
    
    engine = FunASREngine.create_medical_version(
        enable_diarization=True,
        device="cpu"
    )
    
    print("正在加载模型...")
    engine.load_model()
    print("✓ 模型加载完成")
    
    print("\n提示: 请准备一段医患对话音频文件进行测试")
    print("支持的格式: wav, mp3, pcm 等")
    
    return engine


def demo_service_usage():
    """服务层用法演示"""
    print("\n" + "=" * 60)
    print("演示 2: 服务层用法 - 使用 ASRService")
    print("=" * 60)
    
    config = {
        "device": "cpu",
        "hotword_path": "config/hotwords_medical.txt",
        "enable_diarization": True
    }
    
    service = ASRService(config)
    
    print("配置信息:")
    print(f"  - 设备: {config['device']}")
    print(f"  - 热词文件: {config['hotword_path']}")
    print(f"  - 说话人分离: {'启用' if config['enable_diarization'] else '禁用'}")
    
    return service


def process_audio_file(audio_path: str, engine=None, service=None):
    """处理音频文件并展示结果"""
    audio_path = Path(audio_path)
    if not audio_path.exists():
        print(f"✗ 音频文件不存在: {audio_path}")
        return None
    
    print(f"\n处理音频: {audio_path.name}")
    print("-" * 60)
    
    if service:
        result = service.transcribe_with_diarization(audio_path)
        display_service_result(result)
    elif engine:
        asr_result = engine.transcribe(audio_path)
        display_engine_result(asr_result)
    
    return result if service else asr_result


def display_engine_result(result):
    """显示引擎结果"""
    print(f"\n转写文本: {result.text[:100]}...")
    print(f"音频时长: {result.duration_seconds:.2f} 秒")
    print(f"推理时间: {result.inference_time:.2f} 秒")
    print(f"实时率: {result.real_time_factor:.3f}")
    
    if result.speaker_segments:
        print(f"\n检测到 {len(result.speaker_segments)} 个说话人片段:")
        print("-" * 60)
        
        for i, segment in enumerate(result.speaker_segments[:5]):  # 只显示前5个
            speaker = segment.get("speaker", "unknown")
            text = segment.get("text", "")
            start_sec = segment.get("start_ms", 0) / 1000
            end_sec = segment.get("end_ms", 0) / 1000
            
            print(f"\n[{i+1}] 说话人: {speaker}")
            print(f"    时间: {start_sec:.2f}s - {end_sec:.2f}s")
            print(f"    文本: {text}")
        
        if len(result.speaker_segments) > 5:
            print(f"\n... 还有 {len(result.speaker_segments) - 5} 个片段")


def display_service_result(result):
    """显示服务结果"""
    turns = result.get("turns", [])
    
    print(f"\n音频时长: {result.get('duration', 0):.2f} 秒")
    print(f"推理时间: {result.get('inference_time', 0):.2f} 秒")
    
    if turns:
        print(f"\n检测到 {len(turns)} 个对话轮次:")
        print("-" * 60)
        
        for turn in turns[:5]:  # 只显示前5个
            speaker = turn.get("speaker", "unknown")
            text = turn.get("text", "")
            start_sec = turn.get("start_ms", 0) / 1000
            
            print(f"\n[{turn.get('turn_index', 0)}] {speaker}: {text}")
        
        if len(turns) > 5:
            print(f"\n... 还有 {len(turns) - 5} 个轮次")


def demo_speaker_mapping():
    """说话人映射演示"""
    print("\n" + "=" * 60)
    print("演示 3: 说话人映射逻辑")
    print("=" * 60)
    
    from backend.services.asr_service import ASRService
    
    service = ASRService({"device": "cpu"})
    
    test_cases = [
        ("spk0", 0),
        ("spk1", 1),
        ("spk2", 2),
        ("unknown", 0),
        ("spk3", 3)
    ]
    
    print("\n说话人ID映射规则:")
    print("  spk0 → doctor (医生)")
    print("  spk1 → patient (患者)")
    print("  spk2+ → speaker_N (其他说话人)")
    print("  unknown → 根据索引奇偶映射")
    
    print("\n测试用例:")
    for speaker_id, index in test_cases:
        mapped = service._map_speaker_id(speaker_id, index)
        print(f"  {speaker_id} (index={index}) → {mapped}")


def save_result_to_json(result, output_path: str):
    """保存结果到JSON文件"""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"\n✓ 结果已保存到: {output_path}")


def main():
    print("=" * 60)
    print("funASR 说话人分离功能演示")
    print("=" * 60)
    
    print("\n本演示将展示:")
    print("1. 基础用法 - 直接使用 FunASREngine")
    print("2. 服务层用法 - 使用 ASRService")
    print("3. 说话人映射逻辑")
    print("4. 实际音频处理（可选）")
    
    demo_basic_usage()
    demo_service_usage()
    demo_speaker_mapping()
    
    print("\n" + "=" * 60)
    print("实际音频处理演示")
    print("=" * 60)
    
    audio_path = input("\n请输入音频文件路径（按回车跳过）: ").strip()
    
    if audio_path:
        engine = FunASREngine.create_medical_version(enable_diarization=True)
        engine.load_model()
        
        result = process_audio_file(audio_path, engine=engine)
        
        if result:
            save = input("\n是否保存结果到JSON文件？(y/n): ").strip().lower()
            if save == 'y':
                output_path = "output/diarization_result.json"
                result_dict = {
                    "text": result.text,
                    "duration": result.duration_seconds,
                    "inference_time": result.inference_time,
                    "speaker_segments": result.speaker_segments
                }
                save_result_to_json(result_dict, output_path)
    
    print("\n" + "=" * 60)
    print("演示完成")
    print("=" * 60)
    print("\n更多使用方法请参考: docs/说话人分离使用说明.md")


if __name__ == "__main__":
    main()
