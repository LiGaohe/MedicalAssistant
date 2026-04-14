"""
调试版本的说话人分离测试脚本
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.asr import FunASREngine
import json


def test_diarization_debug():
    """调试版本的说话人分离测试"""
    audio_path = Path("data/test_audio/dialogue_test.mp3")
    
    if not audio_path.exists():
        print(f"音频文件不存在: {audio_path}")
        return
    
    print("=" * 60)
    print("调试模式 - 说话人分离测试")
    print("=" * 60)
    
    engine = FunASREngine.create_medical_version(
        enable_diarization=True,
        device="cpu"
    )
    
    print("\n正在加载模型...")
    engine.load_model()
    print("✓ 模型加载完成")
    
    print(f"\n正在处理音频: {audio_path}")
    
    try:
        result = engine.transcribe(audio_path)
        
        print("\n" + "=" * 60)
        print("ASRResult 对象信息")
        print("=" * 60)
        print(f"text: {result.text[:100]}...")
        print(f"language: {result.language}")
        print(f"duration_seconds: {result.duration_seconds}")
        print(f"inference_time: {result.inference_time}")
        print(f"model_name: {result.model_name}")
        print(f"segments 数量: {len(result.segments) if result.segments else 0}")
        print(f"speaker_segments 数量: {len(result.speaker_segments) if result.speaker_segments else 0}")
        
        if result.segments:
            print("\n" + "=" * 60)
            print("segments 内容")
            print("=" * 60)
            for i, seg in enumerate(result.segments[:3]):
                print(f"\n[{i}] segment keys: {seg.keys()}")
                print(f"    text: {seg.get('text', '')[:50]}")
                print(f"    start: {seg.get('start', 'N/A')}")
                print(f"    end: {seg.get('end', 'N/A')}")
                if 'spk' in seg:
                    print(f"    spk: {seg.get('spk')}")
        
        if result.speaker_segments:
            print("\n" + "=" * 60)
            print("speaker_segments 内容")
            print("=" * 60)
            for i, seg in enumerate(result.speaker_segments[:3]):
                print(f"\n[{i}] {seg}")
        
        print("\n" + "=" * 60)
        print("原始结果调试")
        print("=" * 60)
        print("正在重新运行推理以获取原始结果...")
        
        raw_result = engine._model.generate(input=str(audio_path))
        
        if raw_result and len(raw_result) > 0:
            print(f"\nraw_result 类型: {type(raw_result)}")
            print(f"raw_result 长度: {len(raw_result)}")
            
            first_result = raw_result[0]
            print(f"\nfirst_result keys: {first_result.keys()}")
            
            if 'sentences' in first_result:
                sentences = first_result['sentences']
                print(f"\nsentences 数量: {len(sentences)}")
                
                for i, sent in enumerate(sentences[:3]):
                    print(f"\n[{i}] sentence keys: {sent.keys()}")
                    print(f"    text: {sent.get('text', '')[:50]}")
                    print(f"    start: {sent.get('start', 'N/A')}")
                    print(f"    end: {sent.get('end', 'N/A')}")
                    if 'spk' in sent:
                        print(f"    spk: {sent.get('spk')}")
                    else:
                        print("    ⚠ 没有 spk 字段")
            
            print("\n保存完整原始结果到文件...")
            output_file = Path("output/raw_asr_result.json")
            output_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(raw_result, f, ensure_ascii=False, indent=2, default=str)
            
            print(f"✓ 原始结果已保存到: {output_file}")
        
    except Exception as e:
        print(f"\n✗ 错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    test_diarization_debug()
