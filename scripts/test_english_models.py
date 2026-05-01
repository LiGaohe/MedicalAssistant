import sys
sys.path.insert(0, ".")

from pathlib import Path
from funasr import AutoModel

AUDIO_FILE = Path("data/test_audio/english_dialogue_test.mp3")

def test_english_models():
    print("=" * 60)
    print("测试不同的英文ASR模型")
    print("=" * 60)
    
    models_to_test = [
        ("paraformer-en", "简写名称"),
        ("iic/speech_paraformer-large-vad-punc_asr_nat-en-16k-common-vocab10020", "完整ModelScope ID"),
    ]
    
    for model_id, desc in models_to_test:
        print(f"\n{'='*60}")
        print(f"测试模型: {model_id} ({desc})")
        print("=" * 60)
        
        try:
            print("加载模型...")
            model = AutoModel(
                model=model_id,
                vad_model="fsmn-vad",
                punc_model="ct-punc",
                device="cpu"
            )
            
            print("识别音频...")
            result = model.generate(input=str(AUDIO_FILE), batch_size_s=300)
            
            if result and len(result) > 0:
                text = result[0].get("text", "")
                print(f"\n识别结果:\n{text[:500]}...")
            else:
                print("无识别结果")
                
        except Exception as e:
            print(f"错误: {e}")

if __name__ == "__main__":
    test_english_models()
