"""
数据库操作模块

包含BenchmarkRun/Evaluation/Stage/Summary的CRUD操作、数据校验等。
"""

import logging
from typing import Dict, Any, Optional, List

from backend.models.benchmark import (
    BenchmarkRun, BenchmarkStage, BenchmarkEvaluation,
    BenchmarkLLMCall, BenchmarkSummary
)
from scripts.run_full_benchmark.metrics import is_emr_empty

logger = logging.getLogger(__name__)


def check_existing_run(benchmark_db, sample_id: str, config_key: str) -> Optional[BenchmarkRun]:
    """检查是否已有成功完成的运行记录"""
    existing = benchmark_db.query(BenchmarkRun).filter(
        BenchmarkRun.sample_id == sample_id,
        BenchmarkRun.config_key == config_key,
        BenchmarkRun.status == "completed"
    ).order_by(BenchmarkRun.created_at.desc()).first()
    return existing


def check_run_has_evaluation(benchmark_db, run_id: int) -> bool:
    """检查run是否至少有1个evaluation记录"""
    evaluation = benchmark_db.query(BenchmarkEvaluation).filter(
        BenchmarkEvaluation.run_id == run_id
    ).first()
    return evaluation is not None


def supplement_evaluation(
    benchmark_db,
    sample: Dict[str, Any],
    existing_run: BenchmarkRun,
    config_key: str
) -> Optional[Dict[str, Any]]:
    """
    为已有run补充evaluation记录。
    返回quality_metrics，如果补充失败返回None。
    """
    from scripts.run_full_benchmark.pipeline_runner import run_evaluation, build_main_db_session
    from scripts.run_full_benchmark.metrics import compute_quality_metrics

    sample_id = sample.get("sample_id", "")
    emr = existing_run.emr_result

    if not emr or is_emr_empty(emr):
        logger.warning(f"[补充评估] EMR为空，无法补充 - sample_id={sample_id}, config={config_key}")
        return None

    dialogue_text = sample.get("dialogue_text", "")
    if not dialogue_text:
        logger.warning(f"[补充评估] dialogue_text为空 - sample_id={sample_id}, config={config_key}")
        return None

    # 获取key_facts：优先从当前run获取，其次从full配置run获取，最后重新提取
    key_facts = existing_run.key_facts
    if not key_facts:
        full_run = benchmark_db.query(BenchmarkRun).filter(
            BenchmarkRun.sample_id == sample_id,
            BenchmarkRun.config_key == "full"
        ).order_by(BenchmarkRun.created_at.desc()).first()
        if full_run and full_run.key_facts:
            key_facts = full_run.key_facts
            logger.info(f"[补充评估] 从full配置run获取key_facts - sample_id={sample_id}")

    if not key_facts:
        from backend.services.llm.llm_service import LLMService
        from backend.services.evaluation.benchmark_evaluator import LoggedCompletenessEvaluator
        db = build_main_db_session()
        try:
            llm_service = LLMService(db)
            completeness_eval = LoggedCompletenessEvaluator(llm_service, [])
            key_facts = completeness_eval.extract_key_facts(dialogue_text)
            logger.info(f"[补充评估] key_facts提取完成 - sample_id={sample_id}")
        except Exception as e:
            logger.error(f"[补充评估] key_facts提取失败 - sample_id={sample_id}, error={e}")
        finally:
            db.close()

    # 运行评估
    eval_result, eval_error = run_evaluation(sample, emr, config_key, key_facts=key_facts)

    if eval_result:
        quality_metrics = compute_quality_metrics(emr, sample.get("diagnosis", ""))
        save_benchmark_evaluation(benchmark_db, existing_run, eval_result, quality_metrics, eval_error)
        logger.info(f"[补充评估] 完成 - sample_id={sample_id}, config={config_key}, support_rate={eval_result.get_support_rate()}")
        return quality_metrics
    else:
        logger.error(f"[补充评估] 评估失败 - sample_id={sample_id}, config={config_key}, error={eval_error}")
        return None


def check_intermediate_results(
    benchmark_db,
    sample_id: str,
    missing_configs: Optional[List[str]] = None
) -> Optional[Dict[str, Any]]:
    """检查已有full配置记录中的中间结果是否可复用"""
    from scripts.run_full_benchmark.configs import CONFIG_EMR_KEY_MAPPING

    logger.info(f"[中间结果检查] sample_id={sample_id}, missing_configs={missing_configs}")

    existing = benchmark_db.query(BenchmarkRun).filter(
        BenchmarkRun.sample_id == sample_id,
        BenchmarkRun.config_key == "full"
    ).order_by(BenchmarkRun.created_at.desc()).first()

    if not existing:
        logger.info(f"[中间结果检查] 未找到full配置记录 - sample_id={sample_id}")
        return None

    if existing.status == "failed":
        logger.info(f"[中间结果检查] full配置状态为failed - sample_id={sample_id}, error={existing.error_message[:100] if existing.error_message else None}")
        return None

    if not existing.emr_result or is_emr_empty(existing.emr_result):
        logger.info(f"[中间结果检查] emr_result为空 - sample_id={sample_id}")
        return None

    # 检查缺失配置对应的中间结果字段是否都存在
    if missing_configs:
        missing_fields = []
        for config_key in missing_configs:
            emr_key = CONFIG_EMR_KEY_MAPPING.get(config_key)
            if emr_key is None:
                continue  # simplified等无对应EMR字段的配置跳过
            field_value = getattr(existing, emr_key, None)
            if not field_value or is_emr_empty(field_value):
                missing_fields.append(emr_key)

        if missing_fields:
            logger.warning(f"[中间结果检查] 缺失配置对应的中间结果字段为空 - sample_id={sample_id}, missing_fields={missing_fields}, 将重新执行process_with_fork")
            return None

    # 构建中间结果字典
    results = {}
    if existing.emr_raw_draft and not is_emr_empty(existing.emr_raw_draft):
        results["emr_raw_draft"] = existing.emr_raw_draft
    if existing.emr_pre_revision and not is_emr_empty(existing.emr_pre_revision):
        results["emr_pre_revision"] = existing.emr_pre_revision
    if existing.emr_result and not is_emr_empty(existing.emr_result):
        results["emr_result"] = existing.emr_result
    if existing.emr_no_term_norm and not is_emr_empty(existing.emr_no_term_norm):
        results["emr_no_term_norm"] = existing.emr_no_term_norm
    if existing.emr_no_hallucination and not is_emr_empty(existing.emr_no_hallucination):
        results["emr_no_hallucination"] = existing.emr_no_hallucination
    if existing.hallucination_result:
        results["hallucination_result"] = existing.hallucination_result
    if existing.verification_issues:
        results["verification_issues"] = existing.verification_issues
    if existing.key_facts:
        results["key_facts"] = existing.key_facts

    logger.info(f"[中间结果检查] 检查通过 - sample_id={sample_id}, 可复用字段={list(results.keys())}")
    return results if results else None


def validate_run_before_save(
    sample_id: str,
    config_key: str,
    status: str,
    emr_result: Optional[Dict],
    llm_call_count: int,
    char_count: int,
    token_count: int,
    elapsed_seconds: float,
    error_message: Optional[str]
) -> None:
    """在保存到数据库前校验数据完整性，发现问题时抛出 ValueError 阻止保存"""
    errors = []

    if status == "completed":
        if emr_result is None or is_emr_empty(emr_result):
            errors.append(f"status=completed 但 emr_result 为空")

        if llm_call_count <= 0:
            errors.append(f"status=completed 但 llm_call_count={llm_call_count}（期望 > 0）")

        if token_count is None:
            errors.append(f"status=completed 但 token_count=None（禁止传入 None，会导致数据库使用默认值 0）")
        elif llm_call_count > 0 and token_count <= 0:
            errors.append(f"status=completed 且 llm_call_count={llm_call_count} 但 token_count={token_count}（期望 > 0）")

        if llm_call_count > 0 and char_count <= 0:
            errors.append(f"status=completed 且 llm_call_count={llm_call_count} 但 char_count={char_count}（期望 > 0）")

        if elapsed_seconds <= 0:
            errors.append(f"status=completed 但 elapsed_seconds={elapsed_seconds}（期望 > 0）")

    elif status == "failed":
        if error_message is None:
            logger.warning(f"[校验] status=failed 但 error_message 为空 - sample_id={sample_id}, config_key={config_key}")

    if errors:
        error_detail = "; ".join(errors)
        logger.error(f"[校验失败] sample_id={sample_id}, config_key={config_key}: {error_detail}")
        raise ValueError(
            f"数据校验失败（sample_id={sample_id}, config_key={config_key}），拒绝保存到数据库。"
            f"错误: {error_detail}"
        )


def save_benchmark_run(
    benchmark_db,
    sample_id: str,
    config_key: str,
    visit_id: str,
    status: str,
    emr_raw_draft: Optional[Dict] = None,
    emr_pre_revision: Optional[Dict] = None,
    emr_result: Optional[Dict] = None,
    emr_no_term_norm: Optional[Dict] = None,
    emr_no_hallucination: Optional[Dict] = None,
    hallucination_result: Optional[Dict] = None,
    verification_issues: Optional[Dict] = None,
    key_facts: Optional[Dict] = None,
    elapsed_seconds: float = 0,
    llm_call_count: int = 0,
    char_count: int = 0,
    token_count: int = 0,
    stage_breakdown: Optional[Dict] = None,
    error_message: Optional[str] = None
) -> BenchmarkRun:
    """保存BenchmarkRun记录到数据库"""
    logger.info(f"[DEBUG] save_benchmark_run开始 - sample_id={sample_id}, config_key={config_key}")
    logger.info(f"[DEBUG]   - visit_id={visit_id}")
    logger.info(f"[DEBUG]   - status={status}")
    logger.info(f"[DEBUG]   - elapsed_seconds={elapsed_seconds}")
    logger.info(f"[DEBUG]   - llm_call_count={llm_call_count}")
    logger.info(f"[DEBUG]   - char_count={char_count}")
    logger.info(f"[DEBUG]   - token_count={token_count}")
    logger.info(f"[DEBUG]   - stage_breakdown存在: {stage_breakdown is not None}, keys: {list(stage_breakdown.keys()) if stage_breakdown else 'N/A'}")
    logger.info(f"[DEBUG]   - emr_raw_draft存在: {emr_raw_draft is not None}, is_empty: {is_emr_empty(emr_raw_draft) if emr_raw_draft else 'N/A'}")
    logger.info(f"[DEBUG]   - emr_pre_revision存在: {emr_pre_revision is not None}, is_empty: {is_emr_empty(emr_pre_revision) if emr_pre_revision else 'N/A'}")
    logger.info(f"[DEBUG]   - emr_result存在: {emr_result is not None}, is_empty: {is_emr_empty(emr_result) if emr_result else 'N/A'}")

    # 保存前校验数据完整性
    validate_run_before_save(
        sample_id=sample_id,
        config_key=config_key,
        status=status,
        emr_result=emr_result,
        llm_call_count=llm_call_count,
        char_count=char_count,
        token_count=token_count,
        elapsed_seconds=elapsed_seconds,
        error_message=error_message
    )

    run = BenchmarkRun(
        sample_id=sample_id,
        config_key=config_key,
        visit_id=visit_id,
        status=status,
        emr_raw_draft=emr_raw_draft if emr_raw_draft and not is_emr_empty(emr_raw_draft) else None,
        emr_pre_revision=emr_pre_revision if emr_pre_revision and not is_emr_empty(emr_pre_revision) else None,
        emr_result=emr_result if emr_result and not is_emr_empty(emr_result) else None,
        emr_no_term_norm=emr_no_term_norm if emr_no_term_norm and not is_emr_empty(emr_no_term_norm) else None,
        emr_no_hallucination=emr_no_hallucination if emr_no_hallucination and not is_emr_empty(emr_no_hallucination) else None,
        hallucination_result=hallucination_result,
        verification_issues=verification_issues,
        key_facts=key_facts,
        elapsed_seconds=elapsed_seconds,
        llm_call_count=llm_call_count,
        char_count=char_count,
        token_count=token_count,
        stage_breakdown=stage_breakdown,
        error_message=error_message
    )
    benchmark_db.add(run)
    benchmark_db.commit()
    benchmark_db.refresh(run)

    logger.info(f"[DEBUG] save_benchmark_run完成 - run.id={run.id}")
    logger.info(f"[DEBUG]   - run.llm_call_count={run.llm_call_count}")
    logger.info(f"[DEBUG]   - run.char_count={run.char_count}")
    logger.info(f"[DEBUG]   - run.token_count={run.token_count}")

    return run


def save_benchmark_stages(
    benchmark_db,
    run: BenchmarkRun,
    stages_info: List[Dict[str, Any]]
):
    """保存阶段记录"""
    for i, stage_info in enumerate(stages_info):
        stage = BenchmarkStage(
            run_id=run.id,
            stage_name=stage_info.get("name", f"stage_{i}"),
            stage_index=i,
            input_summary=stage_info.get("input_summary"),
            output_summary=stage_info.get("output_summary"),
            elapsed_seconds=stage_info.get("elapsed_seconds"),
            success=stage_info.get("success", True),
            error_message=stage_info.get("error_message")
        )
        benchmark_db.add(stage)
    benchmark_db.commit()


def save_benchmark_evaluation(
    benchmark_db,
    run: BenchmarkRun,
    eval_result: Any,
    quality_metrics: Optional[Dict],
    error_message: Optional[str] = None
) -> BenchmarkEvaluation:
    """保存评估结果到数据库"""
    from scripts.run_full_benchmark.metrics import compute_diagnosis_match_from_consistency

    diagnosis_match = compute_diagnosis_match_from_consistency(eval_result.consistency)
    if diagnosis_match is None and quality_metrics:
        diagnosis_match = quality_metrics.get("diagnosis_match")

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
        error_message=error_message or "; ".join(eval_result.errors) if eval_result.errors else None
    )
    benchmark_db.add(evaluation)
    benchmark_db.commit()
    benchmark_db.refresh(evaluation)

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

    return evaluation


def save_benchmark_summary(benchmark_db, summary: Dict[str, Any]):
    """保存汇总记录到数据库"""
    try:
        summary_record = BenchmarkSummary(
            config_key=summary.get("config_key", ""),
            total_samples=summary.get("total", 0),
            success_samples=summary.get("success", 0),
            failed_samples=summary.get("failed", 0),
            avg_elapsed_seconds=summary.get("avg_seconds"),
            avg_llm_call_count=summary.get("avg_llm_call_count"),
            avg_char_count=summary.get("avg_char_count"),
            avg_support_rate=summary.get("avg_support_rate"),
            avg_hallucination_rate=summary.get("avg_hallucination_rate"),
            avg_recall_rate=summary.get("avg_recall_rate"),
            avg_omission_rate=summary.get("avg_omission_rate"),
            avg_structure_completeness=summary.get("avg_structure_completeness"),
            avg_field_missing_rate=summary.get("avg_field_missing_rate"),
            avg_diagnosis_match=summary.get("avg_diagnosis_match"),
        )
        benchmark_db.add(summary_record)
        benchmark_db.commit()
    except Exception as e:
        logger.error(f"保存BenchmarkSummary失败: {e}")
        benchmark_db.rollback()
