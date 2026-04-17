import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.asr import Qwen3ASREngine


def test_qwen3_asr(audio_path: str, device: str = "cpu"):
    print(f"测试 Qwen3-ASR-1.7B 引擎")
    print(f"设备: {device}")
    print(f"音频文件: {audio_path}")
    print("-" * 50)
    
    engine = Qwen3ASREngine(
        device=device,
        model_size="1.7B",
        language="Chinese"
    )
    
    print("正在加载模型...")
    engine.load_model()
    print("模型加载完成")
    
    audio_path = Path(audio_path)
    duration = engine._get_audio_duration(audio_path)
    print(f"音频时长: {duration:.2f}秒")
    
    if duration > 30:
        print("检测到长音频，使用分块转写模式...")
        result = engine.transcribe_long_audio(audio_path)
    else:
        print("使用标准转写模式...")
        result = engine.transcribe(audio_path)
    
    print("-" * 50)
    print(f"转写结果:")
    print(result.text)
    print("-" * 50)
    print(f"推理时间: {result.inference_time:.2f}秒")
    print(f"实时率(RTF): {result.real_time_factor:.3f}")
    print(f"语言: {result.language}")
    
    if result.segments:
        print(f"\n分段信息 ({len(result.segments)}段):")
        for i, seg in enumerate(result.segments):
            print(f"  [{i}] {seg['start']//1000}s-{seg['end']//1000}s: {seg['text'][:50]}...")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="测试 Qwen3-ASR 引擎")
    parser.add_argument("audio", help="音频文件路径")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda"], help="运行设备")
    
    args = parser.parse_args()
    
    test_qwen3_asr(args.audio, args.device)
