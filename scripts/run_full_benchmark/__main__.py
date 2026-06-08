"""
run_full_benchmark CLI入口

用法:
  python -m scripts.run_full_benchmark --config full --samples data/experiments/test_samples.json
  python -m scripts.run_full_benchmark --config all --limit 10
  python -m scripts.run_full_benchmark --config multi --re-evaluate
"""

import argparse
import logging
from pathlib import Path

LOG_DIR = Path("data/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / "run_full_benchmark.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)

from scripts.run_full_benchmark.runner import FullBenchmarkRunner


def main():
    parser = argparse.ArgumentParser(description="全量化指标一键评估脚本")
    parser.add_argument("--config", default="full",
                        choices=["end_to_end", "simplified", "standard", "full", "all", "ablations", "multi"],
                        help="实验配置 (default: full)")
    parser.add_argument("--samples", default="data/experiments/test_samples.json",
                        help="测试样本文件路径")
    parser.add_argument("--output-dir", default="data/experiments/results",
                        help="结果输出目录")
    parser.add_argument("--limit", type=int, default=0,
                        help="限制样本数量 (0=全部)")
    parser.add_argument("--sample-id", type=str, default=None,
                        help="指定样本ID进行评估（优先级高于--limit）")
    parser.add_argument("--interval", type=float, default=2.0,
                        help="LLM 调用间隔秒数 (default: 2.0)")
    parser.add_argument("--sequential", action="store_true",
                        help="串行处理：禁用并行处理以避免API速率限制")
    parser.add_argument("--re-evaluate", action="store_true",
                        help="重新评估：对已有结果重新运行LLM评估（默认跳过已完成的样本）")
    args = parser.parse_args()

    runner = FullBenchmarkRunner(
        samples_file=args.samples,
        output_dir=args.output_dir,
        request_interval=args.interval,
        re_evaluate=args.re_evaluate,
        sample_id=args.sample_id,
        sequential=args.sequential
    )

    if not runner.samples:
        print("未加载到样本。请先运行:")
        print("  python scripts/prepare_test_data.py --num_samples 50 --output data/experiments/test_samples.json")
        return

    if args.config == "all":
        runner.run_all_configs(limit=args.limit)
    elif args.config == "ablations":
        runner.run_ablations(limit=args.limit)
    elif args.config == "multi":
        runner.run_multi_variant(limit=args.limit)
    else:
        runner.run_batch(args.config, limit=args.limit)


if __name__ == "__main__":
    main()
