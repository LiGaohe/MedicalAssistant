"""
补充缺失评估记录的脚本

针对 full 配置中缺少评估记录的 sample，从数据库读取已有 EMR 结果，
重新运行评估并保存评估记录。

用法:
  python scripts/backfill_evaluations.py --dry-run    # 预览模式，不实际写入
  python scripts/backfill_evaluations.py              # 实际执行
  python scripts/backfill_evaluations.py --sample-ids 10134898,10252824,10275183
"""

import json
import sys
import traceback
from pathlib import Path
from typing import Dict, Any, Optional, List

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.config import settings
from backend.models.benchmark import (
    BenchmarkRun, BenchmarkEvaluation, BenchmarkLLMCall, BenchmarkBase
)
from backend.benchmark_db import (
    init_benchmark_db, get_benchmark_session, close_benchmark_session,
    BENCHMARK_DATABASE_URL
)
from backend.services.llm.llm_service import LLMService
from backend.services.evaluation.benchmark_evaluator import BenchmarkEvaluator
from backend.database import get_db

LOG_DIR = Path("data/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

import logging

logger = logging.getLogger("backfill_evaluations")
logger.setLevel(logging.INFO)

# 添加独立的日志文件
fh = logging.FileHandler(LOG_DIR / "backfill_evaluations.log", encoding="utf-8")
fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(fh)
sh = logging.StreamHandler()
sh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(sh)

SOAP_SECTIONS = ["subjective", "objective", "assessment", "plan"]
REQUIRED_FIELDS = {
    "subjective": ["chief_complaint", "history_present_illness"],
    "objective": [],
    "assessment": ["diagnosis"],
    "plan": ["treatment"],
}

SAMPLES_FILE = Path("data/experiments/test_samples.json")


def load_samples() -> Dict[str, Dict[str, Any]]:
    """加载样本数据，返回 sample_id -> sample 的映射"""
    with open(SAMPLES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    samples = data.get("samples", [])
    return {s.get("sample_id"): s for s in samples}


def compute_quality_metrics(emr: Optional[Dict], sample_diagnosis: str) -> Optional[Dict]:
    """计算质量指标"""
    if not emr or not isinstance(emr, dict):
        return None

    present_sections = 0
    for section in SOAP_SECTIONS:
        sec = emr.get(section, {})
        if isinstance(sec, dict) and len(sec) > 0:
            present_sections += 1

    structure_completeness = present_sections / len(SOAP_SECTIONS)

    total_required = 0
    missing_required = 0
    for section, fields in REQUIRED_FIELDS.items():
        sec = emr.get(section, {})
        if not isinstance(sec, dict):
            continue
        if not fields:
            continue

        has_text_only = "text" in sec and len(sec) == 1
        if has_text_only:
            text_val = str(sec.get("text", "")).strip()
            for _ in fields:
                total_required += 1
                if not text_val:
                    missing_required += 1
        else:
            for field in fields:
                total_required += 1
                fd = sec.get(field, {})
                val = fd.get("value", "") if isinstance(fd, dict) else ""
                if not val or not str(val).strip():
                    missing_required += 1

    field_missing_rate = missing_required / total_required if total_required > 0 else 0

    diagnosis_match = None
    if sample_diagnosis:
        assessment = emr.get("assessment", {})
        if isinstance(assessment, dict):
            diag_val = ""
            diag_field = assessment.get("diagnosis", {})
            if isinstance(diag_field, dict):
                diag_val = str(diag_field.get("value", "")).strip()
            if not diag_val:
                diag_val = str(assessment.get("text", "")).strip()
            if diag_val:
                import re
                def normalize_text(text):
                    if not text:
                        return ""
                    text = text.strip()
                    text = re.sub(r'[，。、；：！？\s]', '', text)
                    return text.lower()

                pred_norm = normalize_text(diag_val)
                truth_norm = normalize_text(sample_diagnosis)
                if pred_norm and truth_norm:
                    if pred_norm == truth_norm:
                        diagnosis_match = True
                    elif pred_norm in truth_norm or truth_norm in pred_norm:
                        diagnosis_match = True
                    else:
                        common_chars = set(pred_norm) & set(truth_norm)
                        if len(common_chars) >= min(len(pred_norm), len(truth_norm)) * 0.5:
                            diagnosis_match = True
                        else:
                            diagnosis_match = False

    return {
        "structure_completeness": round(structure_completeness, 4),
        "present_sections": present_sections,
        "total_sections": len(SOAP_SECTIONS),
        "field_missing_rate": round(field_missing_rate, 4),
        "missing_required_fields": missing_required,
        "total_required_fields": total_required,
        "diagnosis_match": diagnosis_match,
    }


def compute_diagnosis_match_from_consistency(consistency_result: Optional[Dict]) -> Optional[bool]:
    """从一致性评估结果中提取诊断匹配"""
    if not consistency_result or "facts" not in consistency_result:
        return None

    facts = consistency_result.get("facts", [])
    assessment_facts = [f for f in facts if f.get("section") == "assessment"]

    if not assessment_facts:
        return None

    all_supported = all(f.get("is_supported", False) for f in assessment_facts)
    return all_supported


def find_missing_evaluations(benchmark_db) -> List[Dict]:
    """找出 full 配置中真正需要补充评估的 sample

    筛选条件：该 sample 在 full 配置的所有运行中，没有任何一条有效的评估记录
    （即：无评估记录，或所有评估记录都有 error_message）
    """
    # 找出所有 full 配置的 completed 运行
    runs = benchmark_db.query(BenchmarkRun).filter(
        BenchmarkRun.config_key == "full",
        BenchmarkRun.status == "completed",
        BenchmarkRun.emr_result.isnot(None)
    ).order_by(BenchmarkRun.created_at.desc()).all()

    # 按 sample_id 分组
    sample_runs = {}
    for run in runs:
        if run.sample_id not in sample_runs:
            sample_runs[run.sample_id] = []
        sample_runs[run.sample_id].append(run)

    missing = []
    for sample_id, sample_run_list in sample_runs.items():
        # 检查该 sample 是否有任意一条有效评估（无 error_message）
        has_valid_eval = False
        needs_reeval_run = None  # 需要重新评估的运行（优先选有错误评估的）

        for run in sample_run_list:
            existing_eval = benchmark_db.query(BenchmarkEvaluation).filter(
                BenchmarkEvaluation.run_id == run.id
            ).first()

            if existing_eval:
                if not existing_eval.error_message:
                    has_valid_eval = True
                    break
                else:
                    # 有评估但有错误，需要重新评估
                    if needs_reeval_run is None:
                        needs_reeval_run = run
            else:
                # 无评估记录，可作为重新评估的目标
                if needs_reeval_run is None:
                    needs_reeval_run = run

        if not has_valid_eval and needs_reeval_run is not None:
            missing.append({
                "run_id": needs_reeval_run.id,
                "sample_id": sample_id,
                "config_key": needs_reeval_run.config_key,
                "has_emr": needs_reeval_run.emr_result is not None,
            })
        elif has_valid_eval:
            logger.info(f"[skip] sample_id={sample_id} 已有有效评估，无需补充")

    missing.reverse()
    return missing


def backfill_sample(benchmark_db, run: BenchmarkRun, sample: Dict, dry_run: bool = False) -> bool:
    """为单个 sample 补充评估"""
    sample_id = run.sample_id
    dialogue_text = sample.get("dialogue_text", "")
    emr_result = run.emr_result

    if not dialogue_text:
        logger.error(f"[backfill] sample_id={sample_id}: 无 dialogue_text，跳过")
        return False

    if not emr_result:
        logger.error(f"[backfill] sample_id={sample_id}: 无 emr_result，跳过")
        return False

    logger.info(f"[backfill] 开始评估 - sample_id={sample_id}, run_id={run.id}")

    if dry_run:
        logger.info(f"[backfill] [DRY-RUN] 将评估 sample_id={sample_id}, run_id={run.id}")
        return True

    # 删除该 run 已有的错误评估记录
    existing_evals = benchmark_db.query(BenchmarkEvaluation).filter(
        BenchmarkEvaluation.run_id == run.id
    ).all()
    for old_eval in existing_evals:
        # 先删除关联的 LLM 调用记录
        benchmark_db.query(BenchmarkLLMCall).filter(
            BenchmarkLLMCall.evaluation_id == old_eval.id
        ).delete()
        logger.info(f"[backfill] 删除旧评估记录 - eval_id={old_eval.id}, error={old_eval.error_message[:50] if old_eval.error_message else None}")
        benchmark_db.delete(old_eval)
    if existing_evals:
        benchmark_db.commit()

    db = None
    try:
        engine = create_engine(settings.DATABASE_URL)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()

        llm_service = LLMService(db)
        evaluator = BenchmarkEvaluator(llm_service)

        eval_result = evaluator.evaluate_all(
            dialogue_text,
            emr_result,
            sample_id=sample_id,
            key_facts=None,
            skip_quality_safety=True
        )

        logger.info(
            f"[backfill] 评估完成 - sample_id={sample_id}, "
            f"support_rate={eval_result.get_support_rate()}, "
            f"recall_rate={eval_result.get_recall_rate()}, "
            f"hallucination_rate={eval_result.get_hallucination_rate()}, "
            f"omission_rate={eval_result.get_omission_rate()}"
        )

        # 计算质量指标
        sample_diagnosis = sample.get("diagnosis", "")
        quality_metrics = compute_quality_metrics(emr_result, sample_diagnosis)

        # 计算诊断匹配
        diagnosis_match = compute_diagnosis_match_from_consistency(eval_result.consistency)
        if diagnosis_match is None and quality_metrics:
            diagnosis_match = quality_metrics.get("diagnosis_match")

        # 保存评估记录
        evaluation = BenchmarkEvaluation(
            run_id=run.id,
            consistency_result=eval_result.consistency,
            completeness_result=eval_result.completeness,
            quality_result=eval_result.quality,
            safety_result=eval_result.safety,
            support_rate=eval_result.get_support_rate(),
            hallucination_rate=eval_result.get_hallucination_rate(),
            recall_rate=eval_result.get_recall_rate(),
            omission_rate=eval_result.get_omission_rate(),
            structure_completeness=quality_metrics.get("structure_completeness") if quality_metrics else None,
            field_missing_rate=quality_metrics.get("field_missing_rate") if quality_metrics else None,
            diagnosis_match=diagnosis_match,
            overall_score=eval_result.get_quality_score(),
            error_message="; ".join(eval_result.errors) if eval_result.errors else None
        )
        benchmark_db.add(evaluation)
        benchmark_db.commit()
        benchmark_db.refresh(evaluation)

        logger.info(f"[backfill] 评估记录已保存 - evaluation_id={evaluation.id}, run_id={run.id}")

        # 保存 LLM 调用记录
        for call_record in eval_result.llm_calls:
            llm_call = BenchmarkLLMCall(
                run_id=run.id,
                evaluation_id=evaluation.id,
                stage=call_record.stage,
                evaluator=call_record.evaluator,
                prompt_length=call_record.prompt_length,
                response_length=call_record.response_length,
                prompt_tokens=call_record.prompt_tokens,
                completion_tokens=call_record.completion_tokens,
                total_tokens=call_record.total_tokens,
                success=call_record.success,
                error_message=call_record.error_message
            )
            benchmark_db.add(llm_call)
        benchmark_db.commit()

        logger.info(f"[backfill] LLM调用记录已保存 - {len(eval_result.llm_calls)}条")
        return True

    except Exception as e:
        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        logger.error(f"[backfill] 评估失败 - sample_id={sample_id}, error={error_msg}")
        return False

    finally:
        if db:
            db.close()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="补充缺失的评估记录")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不实际写入数据库")
    parser.add_argument("--sample-ids", type=str, default=None,
                        help="指定要补充的 sample_id，逗号分隔（默认自动检测）")
    args = parser.parse_args()

    logger.info("="*60)
    logger.info("补充缺失评估记录 - 开始")
    logger.info(f"  dry_run: {args.dry_run}")
    logger.info(f"  sample_ids: {args.sample_ids or '自动检测'}")
    logger.info("="*60)

    # 加载样本数据
    samples_map = load_samples()
    logger.info(f"已加载样本数据: {len(samples_map)}个")

    # 初始化数据库
    init_benchmark_db()
    benchmark_db = get_benchmark_session()

    # 找出缺失评估的记录
    missing = find_missing_evaluations(benchmark_db)
    logger.info(f"发现缺失评估的记录: {len(missing)}条")

    if not missing:
        logger.info("无缺失评估记录，退出")
        close_benchmark_session(benchmark_db)
        return

    for item in missing:
        logger.info(f"  run_id={item['run_id']}, sample_id={item['sample_id']}, has_emr={item['has_emr']}")

    # 过滤指定的 sample_id
    if args.sample_ids:
        target_ids = set(args.sample_ids.split(","))
        missing = [m for m in missing if m["sample_id"] in target_ids]
        logger.info(f"过滤后: {len(missing)}条")

    # 执行补充
    success_count = 0
    fail_count = 0

    for item in missing:
        run_id = item["run_id"]
        sample_id = item["sample_id"]

        run = benchmark_db.query(BenchmarkRun).filter(BenchmarkRun.id == run_id).first()
        if not run:
            logger.error(f"[backfill] run_id={run_id} 不存在，跳过")
            fail_count += 1
            continue

        sample = samples_map.get(sample_id)
        if not sample:
            logger.error(f"[backfill] sample_id={sample_id} 在样本数据中不存在，跳过")
            fail_count += 1
            continue

        ok = backfill_sample(benchmark_db, run, sample, dry_run=args.dry_run)
        if ok:
            success_count += 1
        else:
            fail_count += 1

    logger.info("="*60)
    logger.info(f"补充完成: 成功={success_count}, 失败={fail_count}")
    logger.info("="*60)

    close_benchmark_session(benchmark_db)


if __name__ == "__main__":
    main()
