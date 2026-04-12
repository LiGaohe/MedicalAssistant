"""
ASR 测试数据集下载脚本

支持的数据集:
- AISHELL-1: 178小时中文普通话 (推荐用于快速测试)
- 测试音频样例: 小规模测试文件

用法:
    python scripts/download_dataset.py --dataset aishell1 --output_dir ./data
    python scripts/download_dataset.py --dataset sample --output_dir ./data
"""

import argparse
import os
import sys
import urllib.request
import tarfile
import zipfile
from pathlib import Path


DATASETS = {
    "aishell1": {
        "name": "AISHELL-1",
        "url": "https://www.openslr.org/resources/33/data_aishell.tgz",
        "size": "约 15GB",
        "description": "178小时中文普通话语音数据集，包含训练集、开发集、测试集",
        "license": "Apache 2.0 (开源免费)",
    },
    "aishell1_test": {
        "name": "AISHELL-1 测试集",
        "url": "https://www.openslr.org/resources/33/data_aishell.tgz",
        "size": "约 2GB (仅测试集)",
        "description": "AISHELL-1 的测试集部分，用于快速验证",
        "license": "Apache 2.0",
    },
}


def download_file(url: str, output_path: Path, desc: str = "下载中") -> None:
    print(f"\n{desc}: {url}")
    print(f"保存到: {output_path}")
    
    def progress_hook(count, block_size, total_size):
        percent = int(count * block_size * 100 / total_size)
        sys.stdout.write(f"\r进度: {min(percent, 100)}%")
        sys.stdout.flush()
    
    urllib.request.urlretrieve(url, output_path, progress_hook)
    print("\n下载完成!")


def extract_tgz(tgz_path: Path, output_dir: Path) -> None:
    print(f"\n解压中: {tgz_path}")
    with tarfile.open(tgz_path, "r:gz") as tar:
        tar.extractall(output_dir)
    print("解压完成!")


def download_aishell1(output_dir: Path, test_only: bool = False) -> None:
    dataset_info = DATASETS["aishell1"]
    
    print(f"\n{'='*60}")
    print(f"数据集: {dataset_info['name']}")
    print(f"大小: {dataset_info['size']}")
    print(f"说明: {dataset_info['description']}")
    print(f"协议: {dataset_info['license']}")
    print(f"{'='*60}")
    
    output_dir.mkdir(parents=True, exist_ok=True)
    tgz_path = output_dir / "data_aishell.tgz"
    
    if tgz_path.exists():
        print(f"\n文件已存在: {tgz_path}")
    else:
        print(f"\n注意: 数据集约 15GB，下载可能需要较长时间")
        print(f"备用下载地址: https://opendatalab.org.cn/OpenDataLab/AISHELL-1")
        
        confirm = input("\n是否继续下载? (y/n): ")
        if confirm.lower() != 'y':
            print("已取消下载")
            return
        
        download_file(dataset_info["url"], tgz_path, "下载 AISHELL-1")
    
    extract_dir = output_dir / "aishell1"
    if not extract_dir.exists():
        extract_tgz(tgz_path, output_dir)
    
    print(f"\n数据集已准备就绪: {extract_dir}")
    print(f"\n目录结构:")
    print(f"  - wav/train/  训练集")
    print(f"  - wav/dev/    开发集")
    print(f"  - wav/test/   测试集")


def download_sample_audio(output_dir: Path) -> None:
    print(f"\n{'='*60}")
    print("下载测试音频样例")
    print(f"{'='*60}")
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    sample_dir = output_dir / "sample"
    sample_dir.mkdir(exist_ok=True)
    
    sample_wav = sample_dir / "test_zh.wav"
    
    if sample_wav.exists():
        print(f"\n样例文件已存在: {sample_wav}")
        return
    
    print("\n提示: 请手动准备测试音频文件")
    print(f"建议将测试音频放入: {sample_dir}")
    print("\n快速获取测试音频的方法:")
    print("1. 录制一段中文语音 (推荐医疗相关内容)")
    print("2. 从 AISHELL-1 测试集中选取几个文件")
    print("3. 使用在线 TTS 生成测试音频")


def create_test_script(output_dir: Path) -> None:
    script_path = output_dir / "test_with_aishell.py"
    
    content = '''"""
使用 AISHELL-1 测试集评估 ASR 模型

用法:
    python test_with_aishell.py --aishell_dir ./data/aishell1 --num_samples 10
"""

import argparse
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from asr import ASRFactory, ASRResult


def load_aishell_test_data(aishell_dir: Path, num_samples: int = 10):
    """加载 AISHELL-1 测试集数据"""
    test_dir = aishell_dir / "wav" / "test"
    transcript_file = aishell_dir / "transcript" / "aishell_transcript_v0.8.txt"
    
    if not test_dir.exists():
        raise FileNotFoundError(f"测试集目录不存在: {test_dir}")
    
    audio_files = []
    references = []
    
    # 读取转录文本
    transcripts = {}
    if transcript_file.exists():
        with open(transcript_file, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 2:
                    utt_id = parts[0]
                    text = "".join(parts[1:])
                    transcripts[utt_id] = text
    
    # 收集测试音频
    for speaker_dir in test_dir.iterdir():
        if speaker_dir.is_dir():
            for wav_file in speaker_dir.glob("*.wav"):
                utt_id = wav_file.stem
                if utt_id in transcripts:
                    audio_files.append(str(wav_file))
                    references.append(transcripts[utt_id])
                    
                    if len(audio_files) >= num_samples:
                        return audio_files, references
    
    return audio_files, references


def calculate_cer(hypothesis: str, reference: str) -> float:
    """计算字符错误率 (CER)"""
    import Levenshtein
    distance = Levenshtein.distance(hypothesis, reference)
    return distance / len(reference) if len(reference) > 0 else 0.0


def evaluate_asr(
    aishell_dir: str,
    num_samples: int = 10,
    device: str = "cpu",
    engine_type: str = "funasr",
):
    """评估 ASR 模型"""
    aishell_path = Path(aishell_dir)
    audio_files, references = load_aishell_test_data(aishell_path, num_samples)
    
    print(f"加载了 {len(audio_files)} 个测试样本")
    
    engine = ASRFactory.create(engine_type, device=device)
    engine.load_model()
    
    total_cer = 0.0
    results = []
    
    for i, (audio, ref) in enumerate(zip(audio_files, references)):
        result = engine.transcribe(audio)
        cer = calculate_cer(result.text, ref)
        total_cer += cer
        
        results.append({
            "audio": audio,
            "reference": ref,
            "hypothesis": result.text,
            "cer": cer,
        })
        
        print(f"\n[{i+1}/{len(audio_files)}] CER: {cer:.4f}")
        print(f"  参考: {ref}")
        print(f"  识别: {result.text}")
    
    avg_cer = total_cer / len(audio_files) if audio_files else 0.0
    print(f"\n{'='*60}")
    print(f"平均 CER: {avg_cer:.4f} ({avg_cer*100:.2f}%)")
    print(f"{'='*60}")
    
    return results, avg_cer


def main():
    parser = argparse.ArgumentParser(description="使用 AISHELL-1 评估 ASR")
    parser.add_argument("--aishell_dir", type=str, required=True,
                        help="AISHELL-1 数据集目录")
    parser.add_argument("--num_samples", type=int, default=10,
                        help="测试样本数量")
    parser.add_argument("--device", type=str, default="cpu",
                        choices=["cpu", "cuda"])
    parser.add_argument("--engine", type=str, default="funasr",
                        choices=["funasr", "medasr"])
    
    args = parser.parse_args()
    evaluate_asr(
        aishell_dir=args.aishell_dir,
        num_samples=args.num_samples,
        device=args.device,
        engine_type=args.engine,
    )


if __name__ == "__main__":
    main()
'''
    
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(content)
    
    print(f"\n已创建测试脚本: {script_path}")


def main():
    parser = argparse.ArgumentParser(description="ASR 测试数据集下载工具")
    parser.add_argument(
        "--dataset", "-d",
        type=str,
        choices=["aishell1", "sample"],
        default="sample",
        help="要下载的数据集"
    )
    parser.add_argument(
        "--output_dir", "-o",
        type=str,
        default="./data",
        help="输出目录"
    )
    
    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    
    print(f"\n{'='*60}")
    print("ASR 测试数据集下载工具")
    print(f"{'='*60}")
    
    if args.dataset == "aishell1":
        download_aishell1(output_dir)
        create_test_script(output_dir)
    elif args.dataset == "sample":
        download_sample_audio(output_dir)
        create_test_script(output_dir)
    
    print(f"\n{'='*60}")
    print("数据集准备完成!")
    print(f"{'='*60}")
    
    print("\n后续步骤:")
    print("1. 安装依赖: pip install -r requirements-asr.txt")
    print("2. 运行对比测试: python scripts/compare_asr.py --audio <音频文件>")
    if args.dataset == "aishell1":
        print("3. 批量评估: python data/test_with_aishell.py --aishell_dir ./data/aishell1")


if __name__ == "__main__":
    main()
