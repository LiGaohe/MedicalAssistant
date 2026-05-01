import sys
sys.path.insert(0, ".")

from pathlib import Path
from backend.services.asr_service import ASRService

AUDIO_FILE = Path("data/test_audio/english_dialogue_test.mp3")

def test_english_asr_service():
    print("=" * 60)
    print("测试英文ASR服务（使用SenseVoice）")
    print("=" * 60)
    
    config = {
        "engine_type": "funasr",
        "device": "cpu",
        "language": "en",
        "enable_diarization": False
    }
    
    service = ASRService(config)
    
    print("\n1. 测试基本识别...")
    result = service.transcribe(AUDIO_FILE)
    
    print(f"\n引擎: {result.get('engine', 'unknown')}")
    print(f"时长: {result.get('duration', 0):.1f}秒")
    print(f"推理时间: {result.get('inference_time', 0):.2f}秒")
    print(f"\n识别结果:\n{result.get('text', '')[:500]}...")
    
    print("\n" + "=" * 60)
    print("2. 测试带说话人分离的识别...")
    result2 = service.transcribe_with_diarization(AUDIO_FILE)
    
    print(f"\n引擎: {result2.get('engine', 'unknown')}")
    print(f"轮次数: {len(result2.get('turns', []))}")
    
    turns = result2.get('turns', [])
    if turns:
        print("\n前10轮对话:")
        for turn in turns[:10]:
            speaker = turn.get('speaker_id', 'unknown')
            text = turn.get('text', '')
            print(f"  [{speaker}]: {text}")

if __name__ == "__main__":
    test_english_asr_service()
