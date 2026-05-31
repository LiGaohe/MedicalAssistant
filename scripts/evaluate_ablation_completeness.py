"""
对消融实验结果运行完整性评估（关键召回率）

用法:
  python scripts/evaluate_ablation_completeness.py --results data/experiments/results/
  python scripts/evaluate_ablation_completeness.py --results data/experiments/results/ablation_no_term_norm_20260531_161309.jsonl --overwrite
"""

import json
import argparse
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.config import settings
from backend.services.llm.llm_service import LLMService
from backend.services.evaluation.completeness import CompletenessEvaluator

import logging

LOG_DIR = Path("data/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

LLM_IO_DIR = Path("data/logs/llm_io")
LLM_IO_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(
            LOG_DIR / "evaluate_ablation_completeness.log", encoding="utf-8"
        ),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


def load_samples(samples_file):
    with open(samples_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {s["sample_id"]: s for s in data.get("samples", [])}


def build_db_session():
    engine = create_engine(settings.DATABASE_URL)
    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal()


def log_llm_io(step, sample_id, config_name, prompt, response_text, error=None):
    entry = {
        "timestamp": datetime.now().isoformat(),
        "step": step,
        "sample_id": sample_id,
        "config": config_name,
        "prompt_length": len(prompt),
        "prompt": prompt,
        "response": response_text if response_text else None,
        "error": str(error) if error else None,
    }
    filename = LLM_IO_DIR / f"ablation_completeness_{datetime.now().strftime('%Y%m%d')}.jsonl"
    with open(filename, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


class LoggedCompletenessEvaluator(CompletenessEvaluator):
    def __init__(self, llm_service, sample_id="", config_name=""):
        super().__init__(llm_service)
        self._sid = sample_id
        self._config = config_name

    def _call_llm_json(self, template_name, temperature=0.1, **kwargs):
        prompt = self.llm_service.prompt_manager.render(template_name, **kwargs)
        response = self.llm_service.generate(prompt=prompt, temperature=temperature)
        log_llm_io(
            step=template_name,
            sample_id=self._sid,
            config_name=self._config,
            prompt=prompt,
            response_text=response.text,
        )
        return self._parse_json_response(response.text)


def evaluate_jsonl(jsonl_path, samples, overwrite, sample_ids=None):
    entries = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if not entries:
        logger.info(f"{jsonl_path.name}: 无条目")
        return

    # 如果指定了样本ID列表，只处理这些样本
    if sample_ids:
        sample_ids_set = set(sample_ids)
        entries = [e for e in entries if e.get("sample_id") in sample_ids_set]
        logger.info(f"过滤后剩余 {len(entries)} 个指定样本")

    if not entries:
        logger.info(f"{jsonl_path.name}: 无匹配的条目")
        return

    config_name = entries[0].get("config", jsonl_path.stem)
    logger.info(f"开始评估: {jsonl_path.name}, 配置={config_name}, 条目={len(entries)}")

    db = build_db_session()
    llm_service = LLMService(db)

    eval_count = 0
    skip_count = 0
    error_count = 0
    updated = []

    for e in entries:
        if e.get("status") != "completed":
            updated.append(e)
            continue

        if e.get("llm_evaluation") and e["llm_evaluation"].get("completeness"):
            if not overwrite:
                skip_count += 1
                updated.append(e)
                continue

        emr = e.get("emr_result")
        if not emr:
            updated.append(e)
            continue

        sid = e.get("sample_id", "")
        sample = samples.get(sid)
        if not sample:
            logger.warning(f"样本 {sid} 不在样本列表中")
            updated.append(e)
            continue

        dialogue = sample.get("dialogue_text", "")
        if not dialogue:
            updated.append(e)
            continue

        print(f"  [{jsonl_path.stem}] {sid}...", end=" ", flush=True)

        completeness_evaluator = LoggedCompletenessEvaluator(
            llm_service, sample_id=sid, config_name=config_name
        )
        recall = 0
        omission = 0
        completeness_result = None
        extract_error = False

        try:
            key_facts = completeness_evaluator.extract_key_facts(dialogue)
            logger.debug(
                "[%s] 关键事实提取完成: total_count=%d",
                sid,
                key_facts.get("total_count", 0),
            )
        except Exception as ex:
            logger.error("[%s] 关键事实提取失败: %s", sid, ex)
            extract_error = True
            completeness_result = {"error": f"extract_key_facts: {ex}"}

        if not extract_error:
            try:
                completeness_result = completeness_evaluator.evaluate(key_facts, emr)
                recall = completeness_result.get("summary", {}).get("recall_rate", 0)
                omission = completeness_result.get("summary", {}).get(
                    "omission_rate", 0
                )
                logger.debug(
                    "[%s] 覆盖评估完成: recall=%.4f, omission=%.4f",
                    sid,
                    recall,
                    omission,
                )
            except Exception as ex:
                logger.error("[%s] 覆盖评估失败: %s", sid, ex)
                completeness_result = {"error": f"evaluate: {ex}"}
                error_count += 1

        e.setdefault("llm_evaluation", {})
        e["llm_evaluation"]["completeness"] = completeness_result
        updated.append(e)

        if not extract_error and completeness_result and "error" not in completeness_result:
            eval_count += 1
            print(f"OK recall={recall:.3f} omission={omission:.3f}")
        else:
            print(f"ERROR")

    db.close()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = jsonl_path.parent / f"{jsonl_path.stem}_eval_{timestamp}.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        for e in updated:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    logger.info(
        "%s: 新评估=%d, 跳过(已有)=%d, 出错=%d → %s",
        jsonl_path.name,
        eval_count,
        skip_count,
        error_count,
        out_path.name,
    )
    print(
        f"\n  {jsonl_path.name}: 新评估={eval_count}, 跳过(已有)={skip_count}, 出错={error_count} → {out_path.name}"
    )


def main():
    parser = argparse.ArgumentParser(description="消融实验结果完整性评估")
    parser.add_argument(
        "--results",
        required=True,
        help="消融实验结果 jsonl 文件或目录",
    )
    parser.add_argument(
        "--samples",
        default="data/experiments/test_samples.json",
        help="测试样本文件路径",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="覆盖已有的评估结果",
    )
    parser.add_argument(
        "--sample-ids",
        nargs="+",
        help="只评估指定的样本ID（用空格分隔）",
    )
    args = parser.parse_args()

    logger.info("=== 消融实验完整性评估开始 ===")
    logger.info("results=%s, overwrite=%s", args.results, args.overwrite)
    if args.sample_ids:
        logger.info("指定评估的样本ID: %s", args.sample_ids)

    samples = load_samples(args.samples)
    if not samples:
        logger.error("未加载到样本")
        return

    results_path = Path(args.results)
    if results_path.is_dir():
        jsonl_files = sorted(results_path.glob("ablation_*.jsonl"))
        jsonl_files = [f for f in jsonl_files if "_eval_" not in f.name]
    elif results_path.is_file():
        jsonl_files = [results_path]
    else:
        logger.error("%s 不是有效的 jsonl 文件或目录", args.results)
        return

    if not jsonl_files:
        logger.warning("未找到消融实验结果文件")
        return

    logger.info("共 %d 个文件待评估", len(jsonl_files))
    for f in jsonl_files:
        logger.info("  - %s", f.name)

    for jsonl_file in jsonl_files:
        evaluate_jsonl(jsonl_file, samples, args.overwrite, args.sample_ids)

    logger.info("=== 所有评估完成 ===")


if __name__ == "__main__":
    main()
