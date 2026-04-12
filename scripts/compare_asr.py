"""
ASR 模型对比测试脚本

用法:
    python scripts/compare_asr.py --audio <音频文件路径> --device cpu
    python scripts/compare_asr.py --audio <音频文件路径> --device cuda
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from asr import ASRFactory, ASRResult


def print_result(result: ASRResult, engine_type: str) -> None:
    print(f"\n{'='*60}")
    print(f"模型: {result.model_name} ({engine_type})")
    print(f"{'='*60}")
    print(f"语言: {result.language}")
    print(f"音频时长: {result.duration_seconds:.2f} 秒")
    print(f"推理时间: {result.inference_time:.2f} 秒")
    print(f"实时因子 (RTF): {result.real_time_factor:.3f}")
    print(f"\n转写结果:\n{result.text}")
    print(f"{'='*60}")


def compare_engines(
    audio_path: str,
    device: str = "cpu",
    hotword_path: str | None = None,
) -> dict[str, ASRResult]:
    results = {}
    
    print(f"\n音频文件: {audio_path}")
    print(f"设备: {device}")
    print(f"热词文件: {hotword_path or '无'}")
    
    engines = ASRFactory.create_all(
        device=device,
        hotword_path=hotword_path,
    )
    
    for engine_type, engine in engines.items():
        try:
            print(f"\n正在加载 {engine_type}...")
            engine.load_model()
            print(f"加载完成，开始转写...")
            
            if engine_type == "medasr":
                result = engine.transcribe_with_warning(audio_path)
            else:
                result = engine.transcribe(audio_path)
            
            results[engine_type] = result
            print_result(result, engine_type)
            
        except Exception as e:
            print(f"\n[错误] {engine_type} 转写失败: {e}")
            import traceback
            traceback.print_exc()
    
    return results


def print_comparison_table(results: dict[str, ASRResult]) -> None:
    if not results:
        print("\n没有可比较的结果")
        return
    
    print(f"\n{'='*80}")
    print("对比汇总")
    print(f"{'='*80}")
    print(f"{'模型':<20} {'语言':<8} {'RTF':<10} {'推理时间':<12} {'音频时长':<10}")
    print(f"{'-'*80}")
    
    for engine_type, result in results.items():
        print(
            f"{result.model_name:<20} "
            f"{result.language:<8} "
            f"{result.real_time_factor:<10.3f} "
            f"{result.inference_time:<12.2f}s "
            f"{result.duration_seconds:<10.2f}s"
        )
    
    print(f"{'='*80}")
    
    print("\n转写文本对比:")
    print(f"{'-'*80}")
    for engine_type, result in results.items():
        print(f"\n[{result.model_name}]:")
        print(result.text)
    print(f"{'-'*80}")


def main():
    parser = argparse.ArgumentParser(
        description="ASR 模型对比测试工具"
    )
    parser.add_argument(
        "--audio", "-a",
        type=str,
        required=True,
        help="音频文件路径"
    )
    parser.add_argument(
        "--device", "-d",
        type=str,
        default="cpu",
        choices=["cpu", "cuda"],
        help="推理设备 (默认: cpu)"
    )
    parser.add_argument(
        "--hotword", "-hw",
        type=str,
        default=None,
        help="热词文件路径 (用于 FunASR)"
    )
    parser.add_argument(
        "--engine", "-e",
        type=str,
        default=None,
        choices=["funasr", "medasr"],
        help="只测试指定引擎 (默认: 测试全部)"
    )
    
    args = parser.parse_args()
    
    if not Path(args.audio).exists():
        print(f"错误: 音频文件不存在: {args.audio}")
        sys.exit(1)
    
    if args.engine:
        engine = ASRFactory.create(
            args.engine,
            device=args.device,
            hotword_path=args.hotword,
        )
        engine.load_model()
        if args.engine == "medasr":
            result = engine.transcribe_with_warning(args.audio)
        else:
            result = engine.transcribe(args.audio)
        print_result(result, args.engine)
    else:
        results = compare_engines(
            audio_path=args.audio,
            device=args.device,
            hotword_path=args.hotword,
        )
        print_comparison_table(results)


if __name__ == "__main__":
    main()
