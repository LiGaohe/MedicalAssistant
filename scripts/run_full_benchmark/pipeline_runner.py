"""
Pipeline执行模块

包含单样本Pipeline执行、评估执行、JSONL条目构建等逻辑。
"""

import time
import uuid
import traceback
import logging
from typing import Dict, Any, Optional, Tuple

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.config import settings
from backend.models.visit import Visit
from backend.models.transcript import TranscriptTurn
from backend.services.pipeline.orchestrator import PipelineOrchestrator
from backend.services.llm.llm_service import LLMService
from backend.services.evaluation.benchmark_evaluator import BenchmarkEvaluator
from scripts.run_full_benchmark.metrics import (
    compute_quality_metrics, compute_llm_stats_for_config
)
from scripts.run_full_benchmark.db_helper import save_benchmark_run, save_benchmark_evaluation

logger = logging.getLogger(__name__)


def build_main_db_session():
    """创建主数据库会话"""
    engine = create_engine(settings.DATABASE_URL)
    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal()


def create_visit_and_turns(db, sample: Dict[str, Any]) -> Tuple[str, int]:
    """创建Visit和TranscriptTurn记录，返回(visit_id, turn_count)"""
    sample_id = sample["sample_id"]
    visit = Visit(
        visit_id=f"exp_{sample_id}_{uuid.uuid4().hex[:8]}",
        audio_path=f"exp://{sample_id}",
        status="processing"
    )
    db.add(visit)
    db.commit()

    turn_count = 0
    for i, turn in enumerate(sample.get("turns", [])):
        db.add(TranscriptTurn(
            visit_id=visit.visit_id,
            turn_index=i,
            speaker=turn.get("speaker", "unknown"),
            text=turn.get("text", ""),
            confidence=1.0,
            start_ms=i * 3000,
            end_ms=(i + 1) * 3000
        ))
        turn_count += 1
    db.commit()
    return visit.visit_id, turn_count


def run_pipeline(
    sample: Dict[str, Any],
    config_key: str,
    config_info: Dict[str, Any],
    sequential: bool = False
) -> Tuple[Optional[Dict], Optional[Dict], Optional[Dict], float, int, int, int, Optional[Dict], Optional[str]]:
    """
    运行单样本Pipeline

    Returns:
        (emr, hallucination, verification, elapsed, llm_call_count, char_count, token_count, stage_breakdown, error)
    """
    sample_id = sample.get("sample_id", "")
    logger.info(f"[Pipeline] 开始运行 - sample_id={sample_id}, config={config_key}")

    db = build_main_db_session()
    try:
        visit_id, turn_count = create_visit_and_turns(db, sample)
        llm_service = LLMService(db)
        orchestrator = PipelineOrchestrator(db=db, llm_service=llm_service, language="zh", sequential=sequential)

        t_start = time.time()
        result = orchestrator.process_transcript(
            visit_id=visit_id,
            save_evidence=False,
            skip_cleaning=config_info.get("skip_cleaning", False),
            skip_hallucination_check=config_info.get("skip_hallucination_check", False),
            stop_after_draft=config_info.get("stop_after_draft", False),
            skip_verification=config_info.get("skip_verification", False),
            skip_term_norm=config_info.get("skip_term_norm", False),
            skip_field_revision=config_info.get("skip_field_revision", False)
        )
        elapsed = time.time() - t_start

        emr = result.get("emr_result")
        hallucination = result.get("hallucination_result")
        verification = result.get("verification_issues")
        llm_stats = result.get("llm_stats", {})
        stage_breakdown = llm_stats.get("stage_breakdown", {})

        llm_call_count, char_count, token_count, actual_latency = compute_llm_stats_for_config(
            config_key, llm_stats
        )

        logger.info(f"[Pipeline] 完成 - sample_id={sample_id}, elapsed={elapsed:.1f}s, "
                    f"llm_calls={llm_call_count}, tokens={token_count}")

        return emr, hallucination, verification, elapsed, llm_call_count, char_count, token_count, stage_breakdown, None

    except Exception as e:
        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        logger.error(f"[Pipeline] 失败 - sample_id={sample_id}, error={error_msg}")
        return None, None, None, 0, 0, 0, 0, None, error_msg

    finally:
        db.close()


def run_evaluation(
    sample: Dict[str, Any],
    emr: Dict[str, Any],
    config_key: str,
    skip_quality_safety: bool = True,
    key_facts: Optional[Dict] = None
) -> Tuple[Any, Optional[str]]:
    """
    运行评估

    Returns:
        (eval_result, error_message)
    """
    sample_id = sample.get("sample_id", "")
    dialogue_text = sample.get("dialogue_text", "")

    if not dialogue_text:
        return None, "No dialogue_text in sample"

    if not emr:
        return None, "No emr_result to evaluate"

    logger.info(f"[Evaluation] 开始评估 - sample_id={sample_id}, config={config_key}, skip_quality_safety={skip_quality_safety}, has_key_facts={key_facts is not None}")

    db = build_main_db_session()
    try:
        llm_service = LLMService(db)
        evaluator = BenchmarkEvaluator(llm_service)

        t_start = time.time()
        eval_result = evaluator.evaluate_all(dialogue_text, emr, sample_id, key_facts=key_facts, skip_quality_safety=skip_quality_safety)
        elapsed = time.time() - t_start

        logger.info(f"[Evaluation] 完成 - sample_id={sample_id}, elapsed={elapsed:.1f}s, "
                    f"support_rate={eval_result.get_support_rate()}, "
                    f"recall_rate={eval_result.get_recall_rate()}")

        return eval_result, None

    except Exception as e:
        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        logger.error(f"[Evaluation] 失败 - sample_id={sample_id}, error={error_msg}")
        return None, error_msg

    finally:
        db.close()


def build_jsonl_entry(
    sample: Dict[str, Any],
    config_key: str,
    config_name: str,
    visit_id: str,
    status: str,
    elapsed_seconds: float,
    emr_raw_draft: Optional[Dict] = None,
    emr_pre_revision: Optional[Dict] = None,
    emr_result: Optional[Dict] = None,
    hallucination_result: Optional[Dict] = None,
    verification_issues: Optional[Dict] = None,
    quality_metrics: Optional[Dict] = None,
    eval_result: Optional[Any] = None,
    llm_call_count: int = 0,
    char_count: int = 0,
    error_message: Optional[str] = None,
    include_intermediate: bool = False
) -> Dict[str, Any]:
    """构建JSONL输出条目"""
    entry = {
        "sample_id": sample.get("sample_id", ""),
        "config": config_name,
        "config_key": config_key,
        "visit_id": visit_id,
        "status": status,
        "elapsed_seconds": round(elapsed_seconds, 2),
        "turn_count": len(sample.get("turns", [])),
        "diagnosis": sample.get("diagnosis", ""),
        "has_emr": emr_result is not None,
        "llm_call_count": llm_call_count,
        "char_count": char_count,
        "error_message": error_message,
    }

    if include_intermediate:
        entry["emr_raw_draft"] = emr_raw_draft
        entry["emr_pre_revision"] = emr_pre_revision

    if hallucination_result:
        summary = hallucination_result.get("summary", {})
        entry["hallucination"] = {
            "severity": hallucination_result.get("severity", "unknown"),
            "support_rate": summary.get("support_rate", 0),
            "total_facts": summary.get("total_facts", 0),
            "unsupported_count": summary.get("unsupported_count", 0)
        }
    else:
        entry["hallucination"] = None

    if verification_issues:
        if isinstance(verification_issues, dict):
            categories = {}
            total = 0
            for cat, items in verification_issues.items():
                count = len(items) if isinstance(items, list) else 0
                categories[cat] = count
                total += count
            entry["verification_issues"] = {"total": total, "categories": categories}
        else:
            entry["verification_issues"] = {"total": len(verification_issues) if isinstance(verification_issues, list) else 0}
    else:
        entry["verification_issues"] = None

    entry["quality_metrics"] = quality_metrics

    if eval_result:
        entry["llm_evaluation"] = {
            "consistency": eval_result.consistency,
            "completeness": eval_result.completeness,
            "quality": eval_result.quality,
            "safety": eval_result.safety,
        }
    else:
        entry["llm_evaluation"] = None

    entry["emr_result"] = emr_result

    return entry
