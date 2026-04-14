"""
使用 edge-tts 生成医患对话音频并测试说话人分离功能
"""
import asyncio
import sys
from pathlib import Path
import subprocess

sys.path.insert(0, str(Path(__file__).parent.parent))


async def generate_dialogue_audio():
    """生成医患对话音频"""
    try:
        import edge_tts
    except ImportError:
        print("edge-tts 未安装，正在安装...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "edge-tts"])
        import edge_tts
    
    print("=" * 60)
    print("生成医患对话测试音频")
    print("=" * 60)
    
    output_dir = Path("data/test_audio")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    doctor_voice = "zh-CN-YunxiNeural"
    patient_voice = "zh-CN-XiaoxiaoNeural"
    
    dialogue = [
        {"speaker": "doctor", "text": "你好，请问哪里不舒服？"},
        {"speaker": "patient", "text": "医生，我这几天一直头疼，特别是早上起来的时候。"},
        {"speaker": "doctor", "text": "头疼持续多长时间了？有没有恶心呕吐的症状？"},
        {"speaker": "patient", "text": "大概三天了，有时候会恶心，但没有呕吐。"},
        {"speaker": "doctor", "text": "我给你量一下血压。血压偏高，一百四十五九十五。"},
        {"speaker": "patient", "text": "血压高会引起头疼吗？我需要吃什么药吗？"},
        {"speaker": "doctor", "text": "血压高确实会引起头疼。我给你开一些降压药，每天早上吃一片。"},
        {"speaker": "patient", "text": "好的，谢谢医生。还需要注意什么吗？"},
        {"speaker": "doctor", "text": "注意休息，少吃咸的食物，一周后再来复查。"},
        {"speaker": "patient", "text": "好的，谢谢医生。"},
    ]
    
    print(f"\n对话内容 ({len(dialogue)} 轮):")
    print("-" * 60)
    for i, turn in enumerate(dialogue):
        speaker_name = "医生" if turn["speaker"] == "doctor" else "患者"
        print(f"[{i+1}] {speaker_name}: {turn['text']}")
    
    print("\n正在生成音频...")
    
    audio_files = []
    for i, turn in enumerate(dialogue):
        voice = doctor_voice if turn["speaker"] == "doctor" else patient_voice
        output_file = output_dir / f"turn_{i:02d}_{turn['speaker']}.mp3"
        
        communicate = edge_tts.Communicate(turn["text"], voice)
        await communicate.save(str(output_file))
        
        audio_files.append({
            "file": output_file,
            "speaker": turn["speaker"],
            "text": turn["text"]
        })
        
        speaker_name = "医生" if turn["speaker"] == "doctor" else "患者"
        print(f"  ✓ [{i+1}] {speaker_name}: {turn['text'][:20]}...")
    
    print(f"\n✓ 已生成 {len(audio_files)} 个音频片段")
    
    merged_file = output_dir / "dialogue_test.mp3"
    print(f"\n正在合并音频到: {merged_file}")
    
    try:
        import pydub
        from pydub import AudioSegment
        
        combined = AudioSegment.empty()
        silence = AudioSegment.silent(duration=500)
        
        for audio_info in audio_files:
            segment = AudioSegment.from_mp3(str(audio_info["file"]))
            combined += segment + silence
        
        combined.export(str(merged_file), format="mp3")
        print(f"✓ 音频合并完成: {merged_file}")
        
        print("\n清理临时文件...")
        for audio_info in audio_files:
            audio_info["file"].unlink()
        
        print("✓ 临时文件已清理")
        
    except ImportError:
        print("\n⚠ pydub 未安装，无法合并音频")
        print("请安装: pip install pydub")
        print("\n单独的音频文件保存在:", output_dir)
        return None
    
    return merged_file


def test_diarization(audio_path: Path):
    """测试说话人分离功能"""
    print("\n" + "=" * 60)
    print("测试说话人分离功能")
    print("=" * 60)
    
    from src.asr import FunASREngine
    
    print("\n正在加载模型...")
    engine = FunASREngine.create_medical_version(
        enable_diarization=True,
        device="cpu"
    )
    engine.load_model()
    print("✓ 模型加载完成")
    
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
            
            print(f"\n[{i+1}] 说话人: {speaker}")
            print(f"    时间: {start_sec:.2f}s - {end_sec:.2f}s")
            print(f"    文本: {text}")
            print(f"    置信度: {confidence:.2f}")
        
        print("\n" + "=" * 60)
        print("说话人统计")
        print("=" * 60)
        
        speaker_count = {}
        for segment in result.speaker_segments:
            speaker = segment.get("speaker", "unknown")
            speaker_count[speaker] = speaker_count.get(speaker, 0) + 1
        
        for speaker, count in speaker_count.items():
            print(f"  {speaker}: {count} 个片段")
    else:
        print("\n⚠ 未检测到说话人分离信息")
    
    return result


def main():
    print("=" * 60)
    print("edge-tts 医患对话音频生成与说话人分离测试")
    print("=" * 60)
    
    audio_path = asyncio.run(generate_dialogue_audio())
    
    if audio_path and audio_path.exists():
        test_diarization(audio_path)
        
        print("\n" + "=" * 60)
        print("测试完成")
        print("=" * 60)
        print(f"\n测试音频保存在: {audio_path}")
        print("可以使用该音频继续测试其他功能")
    else:
        print("\n音频生成失败，请检查 edge-tts 和 pydub 是否正确安装")


if __name__ == "__main__":
    main()
