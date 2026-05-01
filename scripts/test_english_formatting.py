import sys
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

sys.path.insert(0, ".")

from pathlib import Path
from backend.services.asr_service import ASRService

AUDIO_FILE = Path("data/test_audio/english_dialogue_test.mp3")

def test_english_formatting():
    print("=" * 60)
    print("测试英文文本格式化")
    print("=" * 60)
    
    config = {
        "engine_type": "funasr",
        "device": "cpu",
        "language": "en",
        "enable_diarization": False
    }
    
    service = ASRService(config)
    
    print("\n测试文本格式化方法...")
    test_cases = [
        "It'smostlyinthefrontandaroundmytemples,itthrobswhenimovesuddenly",
        "Goodmorning.Whatbringsyouintoday?",
        "I'vebeenhavingareallybadheadacheforthepastthreedays.",
    ]
    
    for test in test_cases:
        formatted = service._format_english_text(test)
        print(f"\n输入: {test}")
        print(f"输出: {formatted}")
    
    print("\n" + "=" * 60)
    print("测试完整转写流程...")
    print("=" * 60)
    
    result = service.transcribe_with_diarization(AUDIO_FILE)
    
    print(f"\n引擎: {result.get('engine', 'unknown')}")
    print(f"时长: {result.get('duration', 0):.1f}秒")
    print(f"推理时间: {result.get('inference_time', 0):.2f}秒")
    
    turns = result.get('turns', [])
    if turns:
        print(f"\n共{len(turns)}轮对话:")
        for i, turn in enumerate(turns[:5]):
            speaker = turn.get('speaker_id', 'unknown')
            text = turn.get('text', '')
            print(f"  [{speaker}]: {text}")

if __name__ == "__main__":
    test_english_formatting()
