import sys
sys.path.insert(0, ".")

from pathlib import Path
from funasr import AutoModel

AUDIO_FILE = Path("data/test_audio/english_dialogue_test.mp3")

def test_sensevoice_english():
    print("=" * 60)
    print("测试SenseVoice英文识别")
    print("=" * 60)
    
    print("\n加载SenseVoice模型...")
    model = AutoModel(
        model="iic/SenseVoiceSmall",
        device="cpu",
        disable_update=True
    )
    
    print("识别音频...")
    result = model.generate(input=str(AUDIO_FILE))
    
    if result and len(result) > 0:
        text = result[0].get("text", "")
        print(f"\n识别结果:\n{text}")
        
        if "sentence_info" in result[0]:
            print("\n分段信息:")
            for i, seg in enumerate(result[0]["sentence_info"][:5]):
                print(f"  [{i}] {seg.get('text', '')}")
    else:
        print("无识别结果")

if __name__ == "__main__":
    test_sensevoice_english()
