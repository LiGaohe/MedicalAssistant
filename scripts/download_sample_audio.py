"""
下载示例音频用于ASR测试

此脚本会下载一些公开的中文语音样本用于测试
"""

import urllib.request
import json
from pathlib import Path
import sys


def download_sample_audios():
    """下载示例音频文件"""
    
    # 创建输出目录
    output_dir = Path("data/audio/samples")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 示例音频信息（使用公开可用的中文语音样本）
    # 注意：这里使用的是示例URL，实际使用时需要替换为真实的音频URL
    samples = [
        {
            "name": "sample_medical_1.wav",
            "description": "医疗对话示例1",
            "reference_text": "医生您好，我最近头痛，还有点发烧。",
            "url": None  # 需要用户提供真实音频
        },
        {
            "name": "sample_medical_2.wav", 
            "description": "医疗对话示例2",
            "reference_text": "患者服用阿莫西林后症状有所缓解。",
            "url": None
        }
    ]
    
    print("="*60)
    print("示例音频下载工具")
    print("="*60)
    print("\n由于版权限制，此脚本不会自动下载音频文件。")
    print("请使用以下方法之一获取测试音频：\n")
    
    print("方法1: 使用公开数据集")
    print("-" * 40)
    print("1. AISHELL-1 数据集")
    print("   下载地址: http://www.openslr.org/33/")
    print("   说明: 开源中文语音数据集，包含178小时录音")
    print()
    print("2. ST-CMDS 数据集")
    print("   下载地址: http://www.openslr.org/38/")
    print("   说明: 中文普通话语音语料库")
    print()
    
    print("方法2: 自己录制音频")
    print("-" * 40)
    print("使用手机或电脑录制医疗对话：")
    print("1. 格式: WAV 或 MP3")
    print("2. 采样率: 16kHz（推荐）")
    print("3. 声道: 单声道")
    print("4. 内容: 医患对话场景")
    print()
    
    print("方法3: 使用在线语音样本")
    print("-" * 40)
    print("1. Mozilla Common Voice (中文)")
    print("   网址: https://commonvoice.mozilla.org/zh-CN")
    print("2. OpenSLR")
    print("   网址: https://www.openslr.org/")
    print()
    
    # 创建示例参考文本文件
    print("创建示例参考文本文件...")
    for sample in samples:
        ref_file = output_dir / f"{sample['name'].replace('.wav', '.txt')}"
        ref_file.write_text(sample['reference_text'], encoding='utf-8')
        print(f"  创建: {ref_file}")
    
    # 创建示例音频信息文件
    info_file = output_dir / "samples_info.json"
    with open(info_file, 'w', encoding='utf-8') as f:
        json.dump(samples, f, ensure_ascii=False, indent=2)
    print(f"  创建: {info_file}")
    
    print("\n" + "="*60)
    print("下一步操作")
    print("="*60)
    print("\n1. 下载或录制音频文件")
    print(f"2. 将音频文件放到: {output_dir}")
    print("3. 编辑对应的.txt文件，写入准确的转录文本")
    print("4. 运行测试脚本:")
    print()
    print("   # 测试单个文件")
    print(f"   python scripts/test_asr_performance.py --audio {output_dir}/sample_medical_1.wav")
    print()
    print("   # 测试整个目录")
    print(f"   python scripts/test_asr_performance.py --audio-dir {output_dir}")
    print()
    
    # 创建一个简单的测试音频占位符
    placeholder_file = output_dir / "PLACEHOLDER.txt"
    placeholder_file.write_text(
        "请将您的测试音频文件（WAV或MP3格式）放在此目录中。\n"
        "每个音频文件可以对应一个同名的.txt文件，包含准确的转录文本。\n"
        "例如:\n"
        "  - test1.wav\n"
        "  - test1.txt (包含准确的转录文本)\n",
        encoding='utf-8'
    )
    
    print(f"已创建占位符文件: {placeholder_file}")
    print()


def create_test_audio_with_sox():
    """使用SoX生成测试音频（如果安装了SoX）"""
    import subprocess
    
    output_dir = Path("data/audio/samples")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print("\n尝试使用SoX生成测试音频...")
    
    try:
        # 检查SoX是否安装
        subprocess.run(["sox", "--version"], capture_output=True, check=True)
        print("检测到SoX，可以生成测试音频")
        print("但SoX只能生成静音或简单音调，无法生成语音")
        print("建议使用真实音频进行测试")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("未检测到SoX")
        print("SoX无法生成语音，建议使用真实音频")


if __name__ == "__main__":
    download_sample_audios()
    
    # 尝试使用SoX（可选）
    try:
        create_test_audio_with_sox()
    except Exception as e:
        print(f"\n提示: {e}")
