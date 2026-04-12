"""
ASR一键测试脚本
自动合成音频并测试，无需准备音频文件
"""
import os
import sys
import asyncio
import subprocess
from pathlib import Path
from datetime import datetime

_DEFAULT_CACHE_DIR = Path("D:/models/modelscope_cache")
_DEFAULT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
os.environ["MODELSCOPE_CACHE"] = str(_DEFAULT_CACHE_DIR)

FFMPEG_PATHS = [
    Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links",
    Path("C:/ffmpeg/bin"),
    Path(os.environ.get("PROGRAMFILES", "")) / "ffmpeg" / "bin",
    Path(os.environ.get("LOCALAPPDATA", "")) / "ffmpeg" / "bin",
]

for ffmpeg_dir in FFMPEG_PATHS:
    if ffmpeg_dir.exists():
        current_path = os.environ.get("PATH", "")
        if str(ffmpeg_dir) not in current_path:
            os.environ["PATH"] = str(ffmpeg_dir) + os.pathsep + current_path
            print(f"[INFO] 添加 ffmpeg 路径: {ffmpeg_dir}")
        break

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def check_ffmpeg():
    """检查ffmpeg是否可用"""
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
            shell=True
        )
        return result.returncode == 0
    except:
        return False


def check_dependencies():
    """检查依赖是否安装"""
    missing = []
    warnings = []
    
    try:
        import edge_tts
    except ImportError:
        missing.append("edge-tts")
    
    try:
        import funasr
    except ImportError:
        missing.append("funasr")
    
    try:
        import librosa
    except ImportError:
        missing.append("librosa")
    
    if not check_ffmpeg():
        warnings.append("ffmpeg (可选)")
    
    return missing, warnings


def calculate_cer(reference: str, hypothesis: str) -> float:
    """计算字符错误率（忽略标点符号）"""
    import difflib
    import re
    
    def remove_punctuation(text: str) -> str:
        return re.sub(r'[，。！？、；：""''（）【】《》\s,.!?;:\'"()\[\]<>]', '', text)
    
    ref_clean = remove_punctuation(reference)
    hyp_clean = remove_punctuation(hypothesis)
    
    ref_chars = list(ref_clean)
    hyp_chars = list(hyp_clean)
    
    if len(ref_chars) == 0:
        return 0.0
    
    matcher = difflib.SequenceMatcher(None, ref_chars, hyp_chars)
    
    s = d = i = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'replace':
            s += max(i2 - i1, j2 - j1)
        elif tag == 'delete':
            d += (i2 - i1)
        elif tag == 'insert':
            i += (j2 - j1)
    
    return (s + d + i) / len(ref_chars)


async def synthesize_audio(text: str, output_path: Path) -> bool:
    """使用edge-tts合成音频"""
    try:
        import edge_tts
        communicate = edge_tts.Communicate(text, "zh-CN-XiaoxiaoNeural")
        await communicate.save(str(output_path))
        
        if output_path.exists() and output_path.stat().st_size > 0:
            print(f"    文件大小: {output_path.stat().st_size} bytes")
            return True
        else:
            print(f"    ✗ 文件未生成或为空")
            return False
    except Exception as e:
        print(f"    ✗ 合成失败: {e}")
        return False


def run_quick_test():
    """运行快速测试"""
    print("\n" + "="*60)
    print("  ASR 一键测试")
    print("  " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("="*60)
    
    print("\n[步骤1] 检查依赖...")
    missing, warnings = check_dependencies()
    
    if warnings:
        print(f"  ⚠ 警告: {', '.join(warnings)}")
        print("  提示: FunASR需要ffmpeg或torchcodec来加载音频")
        print("  解决方案:")
        print("    - 重启终端让ffmpeg PATH生效")
        print("    - 或运行: pip install torchcodec")
    
    if missing:
        print(f"  ✗ 缺少必需依赖: {', '.join(missing)}")
        print(f"\n  安装命令:")
        for dep in missing:
            print(f"    pip install {dep}")
        return False
    
    print("  ✓ 必需依赖完整")
    
    print("\n[步骤2] 加载ASR模型...")
    try:
        from src.asr.factory import ASRFactory
        asr = ASRFactory.create("funasr", device="cpu")
        asr.load_model()
        print("  ✓ 模型加载成功")
    except Exception as e:
        print(f"  ✗ 模型加载失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    test_cases = [
        "患者主诉头痛三天",
        "建议服用布洛芬",
        "高血压需要定期测量血压",
    ]
    
    print("\n[步骤3] 合成测试音频...")
    temp_dir = project_root / "data" / "temp_test"
    temp_dir.mkdir(parents=True, exist_ok=True)
    print(f"  临时目录: {temp_dir}")
    
    audio_files = []
    for i, text in enumerate(test_cases):
        audio_path = temp_dir / f"test_{i}.wav"
        print(f"  合成 [{i+1}/{len(test_cases)}]: {text}")
        
        success = asyncio.run(synthesize_audio(text, audio_path))
        if success:
            audio_files.append((audio_path, text))
            print(f"    ✓ 成功")
        else:
            print(f"    ✗ 失败")
    
    if not audio_files:
        print("\n  ✗ 音频合成失败")
        print("\n  可能原因:")
        print("    1. 网络问题（edge-tts需要联网）")
        print("    2. ffmpeg未正确配置")
        print("\n  解决方案:")
        print("    - 重启终端后再试")
        print("    - 或手动测试: edge-tts --text \"测试\" --write-media test.wav")
        return False
    
    print(f"\n  ✓ 成功合成 {len(audio_files)} 个音频文件")
    
    print("\n[步骤4] 运行ASR识别...")
    results = []
    total_cer = 0
    
    for i, (audio_path, ref_text) in enumerate(audio_files):
        print(f"\n  测试 [{i+1}/{len(audio_files)}]")
        print(f"    参考: {ref_text}")
        
        if not audio_path.exists():
            print(f"    ✗ 音频文件不存在")
            continue
        
        try:
            result = asr.transcribe(audio_path)
            cer = calculate_cer(ref_text, result.text)
            total_cer += cer
            
            print(f"    识别: {result.text}")
            print(f"    CER:  {cer:.2%}")
            print(f"    耗时: {result.inference_time:.2f}s")
            
            results.append({
                "reference": ref_text,
                "hypothesis": result.text,
                "cer": cer,
                "time": result.inference_time
            })
        except Exception as e:
            print(f"    ✗ 识别失败: {e}")
            if "ffmpeg" in str(e).lower() or "WinError 2" in str(e):
                print("\n    >>> 音频加载失败，请执行以下任一操作:")
                print("        1. 重启终端（让ffmpeg PATH生效）")
                print("        2. pip install torchcodec")
    
    print("\n[步骤5] 清理临时文件...")
    for audio_path, _ in audio_files:
        if audio_path.exists():
            audio_path.unlink()
            print(f"  删除: {audio_path.name}")
    if temp_dir.exists():
        try:
            temp_dir.rmdir()
        except:
            pass
    print("  ✓ 清理完成")
    
    print("\n" + "="*60)
    print("  测试结果汇总")
    print("="*60)
    
    if results:
        avg_cer = total_cer / len(results)
        avg_time = sum(r['time'] for r in results) / len(results)
        
        print(f"\n  测试样本: {len(results)} 条")
        print(f"  平均CER:  {avg_cer:.2%}")
        print(f"  平均耗时: {avg_time:.2f}s")
        
        if avg_cer < 0.05:
            print("\n  ✓ ASR工作正常，识别准确率较高")
        elif avg_cer < 0.15:
            print("\n  ⚠ ASR可用，但存在一定误差")
        else:
            print("\n  ✗ ASR误差较大，建议检查配置")
    else:
        print("\n  ✗ 没有成功的测试结果")
    
    return True


if __name__ == "__main__":
    run_quick_test()
