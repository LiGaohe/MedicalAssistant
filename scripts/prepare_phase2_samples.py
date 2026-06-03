"""
准备第二阶段样本文件

从全集中排除第一阶段样本，生成第二阶段样本文件。

用法:
    python scripts/prepare_phase2_samples.py --phase1 data/experiments/test_samples_phase1.json --output data/experiments/test_samples_phase2.json
"""

import json
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

LOG_DIR = Path("data/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / "prepare_phase2_samples.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="准备第二阶段样本文件")
    parser.add_argument("--phase1", default="data/experiments/test_samples_phase1.json",
                        help="第一阶段样本文件路径")
    parser.add_argument("--dataset", default="data/text/imcs21-dataset/test.json",
                        help="IMCS-MRG 数据集路径")
    parser.add_argument("--output", default="data/experiments/test_samples_phase2.json",
                        help="第二阶段样本文件路径")
    args = parser.parse_args()

    logger.info(f"加载第一阶段样本: {args.phase1}")
    with open(args.phase1, 'r', encoding='utf-8') as f:
        phase1_data = json.load(f)
    
    phase1_ids = set()
    for sample in phase1_data.get("samples", []):
        phase1_ids.add(sample.get("sample_id"))
    
    logger.info(f"第一阶段样本数: {len(phase1_ids)}")

    logger.info(f"加载全集: {args.dataset}")
    with open(args.dataset, 'r', encoding='utf-8') as f:
        full_data = json.load(f)
    
    all_ids = set(full_data.keys())
    logger.info(f"全集样本数: {len(all_ids)}")

    phase2_ids = all_ids - phase1_ids
    logger.info(f"第二阶段样本数: {len(phase2_ids)}")

    phase2_samples = []
    for sample_id in sorted(phase2_ids):
        sample = full_data[sample_id]
        
        turns = []
        for turn in sample.get("dialogue", []):
            turns.append({
                "turn_index": int(turn.get("sentence_id", "0")),
                "speaker": turn.get("speaker", ""),
                "text": turn.get("sentence", ""),
                "dialogue_act": turn.get("dialogue_act", "")
            })
        
        from backend.services.evaluation.imcs_adapter import IMCSAdapter
        adapter = IMCSAdapter(args.dataset)
        
        phase2_samples.append({
            "sample_id": sample_id,
            "diagnosis": adapter.get_diagnosis(sample_id),
            "self_report": sample.get("self_report", ""),
            "dialogue_text": adapter.get_dialogue_text(sample_id),
            "turns": turns,
            "turn_count": len(turns),
            "references": adapter.get_reference_reports(sample_id),
            "reference_count": len(adapter.get_reference_reports(sample_id))
        })

    turn_counts = [s["turn_count"] for s in phase2_samples]
    diagnoses = [s["diagnosis"] for s in phase2_samples]
    
    diagnosis_dist = {}
    for d in diagnoses:
        diagnosis_dist[d] = diagnosis_dist.get(d, 0) + 1

    stats = {
        "total_samples": len(phase2_samples),
        "avg_turns": sum(turn_counts) / len(turn_counts) if turn_counts else 0,
        "min_turns": min(turn_counts) if turn_counts else 0,
        "max_turns": max(turn_counts) if turn_counts else 0,
        "unique_diagnoses": len(diagnosis_dist),
        "top_diagnoses": sorted(diagnosis_dist.items(), key=lambda x: x[1], reverse=True)[:10]
    }

    logger.info("=" * 60)
    logger.info("第二阶段样本统计信息")
    logger.info("=" * 60)
    logger.info(f"总样本数: {stats['total_samples']}")
    logger.info(f"平均对话轮次: {stats['avg_turns']:.1f}")
    logger.info(f"最小/最大轮次: {stats['min_turns']}/{stats['max_turns']}")
    logger.info(f"不同诊断数: {stats['unique_diagnoses']}")
    logger.info("高频诊断 Top 10:")
    for diag, count in stats["top_diagnoses"]:
        logger.info(f"  {diag}: {count}")

    output_dir = Path(args.output).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    output_data = {
        "metadata": {
            "source_dataset": args.dataset,
            "num_samples": len(phase2_samples),
            "phase1_excluded": len(phase1_ids),
            "statistics": stats
        },
        "samples": phase2_samples
    }

    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    logger.info(f"已保存 {len(phase2_samples)} 条样本到: {args.output}")
    print(f"\n统计: {len(phase2_samples)} 条样本, 平均 {stats['avg_turns']:.1f} 轮对话, {stats['unique_diagnoses']} 种诊断")


if __name__ == "__main__":
    main()