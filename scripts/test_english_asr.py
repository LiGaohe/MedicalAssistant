import sys
sys.path.insert(0, ".")

from pathlib import Path
from src.asr.factory import ASRFactory

AUDIO_FILE = Path("data/test_audio/english_dialogue_test.mp3")

def test_english_asr():
    print("=" * 60)
    print("测试英文ASR识别")
    print("=" * 60)
    
    print("\n1. 创建英文ASR引擎...")
    engine = ASRFactory.create(
        engine_type="funasr",
        device="cpu",
        language="en"
    )
    
    print(f"   模型ID: {engine.model_id}")
    print(f"   标点模型: {engine.punc_model}")
    print(f"   语言: {engine.language}")
    
    print("\n2. 加载模型...")
    engine.load_model()
    print("   模型加载完成")
    
    print(f"\n3. 识别音频: {AUDIO_FILE}")
    result = engine.transcribe(AUDIO_FILE)
    
    print("\n" + "=" * 60)
    print("识别结果:")
    print("=" * 60)
    print(f"\n完整文本:\n{result.text}")
    print(f"\n时长: {result.duration_seconds:.1f}秒")
    print(f"推理时间: {result.inference_time:.2f}秒")
    
    if result.segments:
        print(f"\n分段数: {len(result.segments)}")
        print("\n前5个分段:")
        for i, seg in enumerate(result.segments[:5]):
            text = seg.get("text", "")
            start = seg.get("start", 0) / 1000
            end = seg.get("end", 0) / 1000
            print(f"  [{start:.1f}s - {end:.1f}s] {text}")

if __name__ == "__main__":
    test_english_asr()
