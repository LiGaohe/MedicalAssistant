"""
测试 funASR 说话人分离功能
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.asr import FunASREngine


def test_diarization():
    print("=" * 60)
    print("测试 funASR 说话人分离功能")
    print("=" * 60)
    
    engine = FunASREngine(
        device="cpu",
        model_id="paraformer-zh",
        vad_model="fsmn-vad",
        punc_model="ct-punc",
        spk_model="cam++"
    )
    
    print("\n正在加载模型...")
    engine.load_model()
    print("模型加载完成！")
    
    audio_path = input("\n请输入音频文件路径（或按回车使用默认测试音频）: ").strip()
    
    if not audio_path:
        print("未提供音频文件，测试结束")
        return
    
    audio_path = Path(audio_path)
    if not audio_path.exists():
        print(f"音频文件不存在: {audio_path}")
        return
    
    print(f"\n正在处理音频: {audio_path}")
    result = engine.transcribe(audio_path)
    
    print("\n" + "=" * 60)
    print("转写结果")
    print("=" * 60)
    print(f"完整文本: {result.text}")
    print(f"音频时长: {result.duration_seconds:.2f} 秒")
    print(f"推理时间: {result.inference_time:.2f} 秒")
    print(f"实时率(RTF): {result.real_time_factor:.3f}")
    
    if result.speaker_segments:
        print("\n" + "=" * 60)
        print("说话人分离结果")
        print("=" * 60)
        for i, segment in enumerate(result.speaker_segments):
            speaker = segment.get("speaker", "unknown")
            text = segment.get("text", "")
            start_ms = segment.get("start_ms", 0)
            end_ms = segment.get("end_ms", 0)
            confidence = segment.get("confidence", 0.0)
            
            start_sec = start_ms / 1000
            end_sec = end_ms / 1000
            
            print(f"\n[{i}] 说话人: {speaker}")
            print(f"    时间: {start_sec:.2f}s - {end_sec:.2f}s")
            print(f"    文本: {text}")
            print(f"    置信度: {confidence:.2f}")
    else:
        print("\n未检测到说话人分离信息")
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)


if __name__ == "__main__":
    test_diarization()
