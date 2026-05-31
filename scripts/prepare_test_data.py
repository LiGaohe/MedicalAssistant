"""
测试数据准备脚本

从 IMCS-MRG 数据集中抽取指定数量的样本，输出为统一格式的实验数据文件。

用法:
    python scripts/prepare_test_data.py --num_samples 50 --output data/experiments/test_samples.json
    python scripts/prepare_test_data.py --num_samples 0 --output data/experiments/test_samples.json  # 0 表示全部
"""

import json
import argparse
import random
import sys
import os
from pathlib import Path
from typing import Dict, Any, List

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.services.evaluation.imcs_adapter import IMCSAdapter, IMCS_FIELDS

LOG_DIR = Path("data/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / "prepare_test_data.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def load_dataset(dataset_path: str) -> Dict[str, Any]:
    logger.info(f"加载数据集: {dataset_path}")
    with open(dataset_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    logger.info(f"加载完成，共 {len(data)} 条样本")
    return data


def sample_ids(all_ids: List[str], num_samples: int, seed: int = 42) -> List[str]:
    if num_samples <= 0 or num_samples >= len(all_ids):
        return all_ids
    random.seed(seed)
    return sorted(random.sample(all_ids, num_samples))


def extract_sample(data: Dict[str, Any], sample_id: str, adapter: IMCSAdapter) -> Dict[str, Any]:
    sample = data[sample_id]
    dialogue_text = adapter.get_dialogue_text(sample_id)
    references = adapter.get_reference_reports(sample_id)
    diagnosis = adapter.get_diagnosis(sample_id)

    turns = []
    for turn in sample.get("dialogue", []):
        turns.append({
            "turn_index": int(turn.get("sentence_id", "0")),
            "speaker": turn.get("speaker", ""),
            "text": turn.get("sentence", ""),
            "dialogue_act": turn.get("dialogue_act", "")
        })

    return {
        "sample_id": sample_id,
        "diagnosis": diagnosis,
        "self_report": sample.get("self_report", ""),
        "dialogue_text": dialogue_text,
        "turns": turns,
        "turn_count": len(turns),
        "references": references,
        "reference_count": len(references)
    }


def compute_statistics(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    turn_counts = [s["turn_count"] for s in samples]
    diagnoses = [s["diagnosis"] for s in samples]

    diagnosis_dist = {}
    for d in diagnoses:
        diagnosis_dist[d] = diagnosis_dist.get(d, 0) + 1

    return {
        "total_samples": len(samples),
        "avg_turns": sum(turn_counts) / len(turn_counts) if turn_counts else 0,
        "min_turns": min(turn_counts) if turn_counts else 0,
        "max_turns": max(turn_counts) if turn_counts else 0,
        "unique_diagnoses": len(diagnosis_dist),
        "top_diagnoses": sorted(diagnosis_dist.items(), key=lambda x: x[1], reverse=True)[:10],
        "diagnosis_distribution": dict(sorted(diagnosis_dist.items(), key=lambda x: x[1], reverse=True))
    }


def main():
    parser = argparse.ArgumentParser(description="准备IMCS-MRG测试数据")
    parser.add_argument("--dataset", default="data/text/imcs21-dataset/test.json",
                        help="IMCS-MRG 数据集路径")
    parser.add_argument("--num_samples", type=int, default=50,
                        help="抽取样本数量（0=全部）")
    parser.add_argument("--output", default="data/experiments/test_samples.json",
                        help="输出文件路径")
    parser.add_argument("--seed", type=int, default=42,
                        help="随机种子")
    parser.add_argument("--stats_only", action="store_true",
                        help="仅输出统计信息，不生成样本文件")
    args = parser.parse_args()

    data = load_dataset(args.dataset)
    all_ids = list(data.keys())
    selected_ids = sample_ids(all_ids, args.num_samples, args.seed)

    adapter = IMCSAdapter(args.dataset)

    samples = []
    for sid in selected_ids:
        try:
            sample = extract_sample(data, sid, adapter)
            samples.append(sample)
        except Exception as e:
            logger.error(f"提取样本 {sid} 失败: {e}")

    stats = compute_statistics(samples)

    logger.info("=" * 60)
    logger.info("数据集统计信息")
    logger.info("=" * 60)
    logger.info(f"总样本数: {stats['total_samples']}")
    logger.info(f"平均对话轮次: {stats['avg_turns']:.1f}")
    logger.info(f"最小/最大轮次: {stats['min_turns']}/{stats['max_turns']}")
    logger.info(f"不同诊断数: {stats['unique_diagnoses']}")
    logger.info("高频诊断 Top 10:")
    for diag, count in stats["top_diagnoses"]:
        logger.info(f"  {diag}: {count}")

    if not args.stats_only:
        output_dir = Path(args.output).parent
        output_dir.mkdir(parents=True, exist_ok=True)

        output_data = {
            "metadata": {
                "source_dataset": args.dataset,
                "num_samples": len(samples),
                "seed": args.seed,
                "statistics": stats
            },
            "samples": samples
        }

        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)

        logger.info(f"已保存 {len(samples)} 条样本到: {args.output}")

    print(f"\n统计: {stats['total_samples']} 条样本, "
          f"平均 {stats['avg_turns']:.1f} 轮对话, "
          f"{stats['unique_diagnoses']} 种诊断")


if __name__ == "__main__":
    main()