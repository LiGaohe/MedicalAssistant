"""
多变量Pipeline执行模块

包含run_multi_variant核心逻辑：一次运行产出7份评估结果。
"""

import json
import time
import uuid
import traceback
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

from backend.models.benchmark import BenchmarkRun
from backend.models.transcript import TranscriptTurn
from backend.services.pipeline.orchestrator import PipelineOrchestrator
from backend.services.llm.llm_service import LLMService
from backend.services.evaluation.benchmark_evaluator import BenchmarkEvaluator, LoggedCompletenessEvaluator
from backend.benchmark_db import get_benchmark_session, close_benchmark_session

from scripts.run_full_benchmark.configs import (
    EXPERIMENT_CONFIGS, ABLATION_CONFIGS, CONFIG_LLM_STATS_SOURCE,
    CONFIG_STAGE_GROUPS, CONFIG_OUTPUT_MAPPING, EVAL_DEDUP_GROUPS,
    MULTI_VARIANT_CONFIG_ORDER
)
from scripts.run_full_benchmark.metrics import (
    compute_quality_metrics, compute_llm_stats_for_config, is_emr_empty
)
from scripts.run_full_benchmark.db_helper import (
    check_existing_run, check_run_has_evaluation, supplement_evaluation,
    check_intermediate_results, save_benchmark_run,
    save_benchmark_evaluation, save_benchmark_summary
)
from scripts.run_full_benchmark.pipeline_runner import (
    build_main_db_session, create_visit_and_turns, build_jsonl_entry
)

logger = logging.getLogger(__name__)


def _resolve_config_llm_stats(
    config_key: str,
    llm_stats_full: Dict,
    llm_stats_no_term_norm: Dict,
    llm_stats_no_hallucination: Dict,
    llm_stats: Dict
) -> Dict:
    """根据配置选择正确的LLM统计源"""
    stats_source_key = CONFIG_LLM_STATS_SOURCE.get(config_key)
    if stats_source_key == "llm_stats_full":
        return llm_stats_full
    elif stats_source_key == "llm_stats_no_term_norm":
        return llm_stats_no_term_norm
    elif stats_source_key == "llm_stats_no_hallucination":
        return llm_stats_no_hallucination
    else:
        return llm_stats  # fallback


def _extract_stage_breakdown(
    config_key: str,
    config_llm_stats: Dict
) -> Dict:
    """从对应路径的stage_breakdown中提取当前配置对应的阶段"""
    config_stage_breakdown_source = config_llm_stats.get("stage_breakdown", {})
    config_stage_group = CONFIG_STAGE_GROUPS.get(config_key)
    if config_stage_group and config_stage_breakdown_source:
        config_stage_breakdown = {
            stage: config_stage_breakdown_source.get(stage, {})
            for stage in config_stage_group
            if stage in config_stage_breakdown_source
        }
        logger.info(f"[DEBUG] {config_key}: 提取对应阶段的stage_breakdown - stages={config_stage_group}, extracted_keys={list(config_stage_breakdown.keys())}")
    else:
        config_stage_breakdown = {}
        logger.warning(f"[DEBUG] {config_key}: 无法提取stage_breakdown, config_stage_group={config_stage_group}")
    return config_stage_breakdown


def _process_existing_configs(
    sample: Dict[str, Any],
    existing_configs: Dict[str, BenchmarkRun]
) -> Dict[str, Dict]:
    """处理已存在的配置，构建JSONL条目"""
    sample_results = {}
    for config_key, existing_run in existing_configs.items():
        config_info = EXPERIMENT_CONFIGS.get(config_key, ABLATION_CONFIGS.get(config_key, {"name": config_key}))
        quality_metrics = compute_quality_metrics(existing_run.emr_result, sample.get("diagnosis", ""))
        entry = build_jsonl_entry(
            sample=sample,
            config_key=config_key,
            config_name=config_info.get("name", config_key),
            visit_id=existing_run.visit_id or "",
            status=existing_run.status,
            elapsed_seconds=existing_run.elapsed_seconds or 0,
            emr_result=existing_run.emr_result,
            hallucination_result=existing_run.hallucination_result,
            verification_issues=existing_run.verification_issues,
            quality_metrics=quality_metrics,
            eval_result=None,
            llm_call_count=existing_run.llm_call_count,
            char_count=existing_run.char_count,
            error_message=existing_run.error_message
        )
        sample_results[config_key] = entry
    return sample_results


def _run_fork_pipeline(
    db,
    sample: Dict[str, Any],
    sequential: bool
) -> Dict[str, Any]:
    """执行process_with_fork，返回fork结果"""
    visit_id, turn_count = create_visit_and_turns(db, sample)
    llm_service = LLMService(db)
    orchestrator = PipelineOrchestrator(db=db, llm_service=llm_service, language="zh", sequential=sequential)

    t_start = time.time()
    fork_result = orchestrator.process_with_fork(visit_id=visit_id, save_evidence=False)
    fork_elapsed = time.time() - t_start

    return {
        "visit_id": visit_id,
        "fork_result": fork_result,
        "fork_elapsed": fork_elapsed,
        "orchestrator": orchestrator,
        "llm_service": llm_service,
    }


def _extract_fork_data(fork_data: Dict) -> Dict:
    """从fork结果中提取EMR和LLM统计数据"""
    fork_result = fork_data["fork_result"]
    fork_elapsed = fork_data["fork_elapsed"]

    emr_raw_draft = fork_result.get("emr_raw_draft")
    emr_pre_revision = fork_result.get("emr_pre_revision")
    emr_result = fork_result.get("emr_result")
    emr_no_term_norm = fork_result.get("emr_no_term_norm")
    emr_no_hallucination = fork_result.get("emr_no_hallucination")
    hallucination_result = fork_result.get("hallucination_result")
    verification_issues = fork_result.get("verification_issues")

    llm_stats = fork_result.get("llm_stats", {})
    llm_stats_full = fork_result.get("llm_stats_full", llm_stats)
    llm_stats_no_term_norm = fork_result.get("llm_stats_no_term_norm", llm_stats)
    llm_stats_no_hallucination = fork_result.get("llm_stats_no_hallucination", llm_stats)

    stage_breakdown = llm_stats_full.get("stage_breakdown", {})

    llm_call_count = llm_stats_full.get("total_calls") or 0
    char_count = llm_stats_full.get("total_char_count") or 0
    token_count = llm_stats_full.get("total_tokens") or 0
    actual_latency = llm_stats_full.get("total_actual_latency") or 0.0

    fork_elapsed_actual = actual_latency if actual_latency > 0 else fork_elapsed

    logger.info(f"[multi_variant] process_with_fork完成, status={fork_result.get('status')}, elapsed={fork_elapsed:.1f}s, actual_latency={actual_latency:.2f}s, llm_calls={llm_call_count}")
    logger.info(f"[multi_variant] 各路径LLM统计: full_calls={llm_stats_full.get('total_calls')}, no_term_norm_calls={llm_stats_no_term_norm.get('total_calls')}, no_hallucination_calls={llm_stats_no_hallucination.get('total_calls')}")

    return {
        "emr_raw_draft": emr_raw_draft,
        "emr_pre_revision": emr_pre_revision,
        "emr_result": emr_result,
        "emr_no_term_norm": emr_no_term_norm,
        "emr_no_hallucination": emr_no_hallucination,
        "hallucination_result": hallucination_result,
        "verification_issues": verification_issues,
        "llm_stats": llm_stats,
        "llm_stats_full": llm_stats_full,
        "llm_stats_no_term_norm": llm_stats_no_term_norm,
        "llm_stats_no_hallucination": llm_stats_no_hallucination,
        "stage_breakdown": stage_breakdown,
        "llm_call_count": llm_call_count,
        "char_count": char_count,
        "token_count": token_count,
        "fork_elapsed_actual": fork_elapsed_actual,
        "fork_status": fork_result.get("status"),
        "fork_error": fork_result.get("error"),
    }


def _restore_cached_llm_stats(cached_run: Optional[BenchmarkRun]) -> Dict[str, Dict]:
    """从缓存的BenchmarkRun恢复LLM统计"""
    if cached_run:
        logger.info(f"[复用中间结果] 从cached_run恢复LLM统计 - sample_id={cached_run.sample_id}, calls={cached_run.llm_call_count}, chars={cached_run.char_count}")
        llm_stats_full = {
            "total_calls": cached_run.llm_call_count or 0,
            "total_char_count": cached_run.char_count or 0,
            "total_tokens": cached_run.token_count or 0,
            "total_actual_latency": cached_run.elapsed_seconds or 0,
            "stage_breakdown": cached_run.stage_breakdown or {}
        }
        # 复用路径A统计作为其他路径的近似值（无法精确恢复）
        llm_stats_no_term_norm = llm_stats_full
        llm_stats_no_hallucination = llm_stats_full
        llm_stats = llm_stats_full
        logger.warning(f"[复用中间结果] no_term_norm和no_hallucination使用路径A近似统计，可能不精确")
    else:
        llm_stats = {}
        llm_stats_full = {}
        llm_stats_no_term_norm = {}
        llm_stats_no_hallucination = {}
        logger.warning(f"[复用中间结果] 无法恢复llm_stats - cached_run不存在")

    return {
        "llm_stats": llm_stats,
        "llm_stats_full": llm_stats_full,
        "llm_stats_no_term_norm": llm_stats_no_term_norm,
        "llm_stats_no_hallucination": llm_stats_no_hallucination,
    }


def _extract_key_facts(
    llm_service,
    dialogue_text: str,
    sample_id: str,
    key_facts_cached: Optional[Dict],
    intermediate_results: Optional[Dict],
    benchmark_db
) -> Dict:
    """提取key_facts，优先使用缓存"""
    if key_facts_cached:
        return key_facts_cached

    completeness_eval = LoggedCompletenessEvaluator(llm_service, [])
    try:
        key_facts = completeness_eval.extract_key_facts(dialogue_text)
        logger.info(f"[multi_variant] key_facts提取完成")

        # 如果是复用中间结果，更新到数据库
        if intermediate_results:
            cached_run = benchmark_db.query(BenchmarkRun).filter(
                BenchmarkRun.sample_id == sample_id,
                BenchmarkRun.config_key == "full"
            ).order_by(BenchmarkRun.created_at.desc()).first()
            if cached_run:
                cached_run.key_facts = key_facts
                benchmark_db.commit()
                logger.info(f"[multi_variant] 已更新key_facts到数据库 - sample_id={sample_id}")

        return key_facts
    except Exception as e:
        logger.error(f"[multi_variant] key_facts提取失败: {e}")
        print(f"FAIL (key_facts提取失败)", flush=True)
        raise RuntimeError(f"key_facts extraction failed for sample {sample_id}: {e}")


def _run_simplified_pipeline(
    db,
    sample: Dict[str, Any],
    visit_id: str,
    orchestrator: Optional[PipelineOrchestrator],
    llm_service,
    sequential: bool
) -> Dict:
    """运行simplified独立Pipeline"""
    if orchestrator is None:
        existing_turns = db.query(TranscriptTurn).filter(
            TranscriptTurn.visit_id == visit_id
        ).count()
        if existing_turns == 0:
            logger.info(f"[multi_variant] visit_id={visit_id}没有turns记录，重新创建")
            for i, turn in enumerate(sample.get("turns", [])):
                db.add(TranscriptTurn(
                    visit_id=visit_id,
                    turn_index=i,
                    speaker=turn.get("speaker", "unknown"),
                    text=turn.get("text", ""),
                    confidence=1.0,
                    start_ms=i * 3000,
                    end_ms=(i + 1) * 3000
                ))
            db.commit()
        orchestrator = PipelineOrchestrator(db=db, llm_service=llm_service, language="zh", sequential=sequential)

    t_simplified_start = time.time()
    simplified_result = orchestrator.process_transcript(
        visit_id=visit_id,
        save_evidence=False,
        skip_cleaning=True,
        skip_hallucination_check=True,
        stop_after_draft=False,
        skip_verification=True,
        skip_term_norm=False,
        skip_field_revision=True
    )
    simplified_elapsed = time.time() - t_simplified_start
    simplified_status = simplified_result.get("status", "unknown")
    emr_to_eval = simplified_result.get("emr_result")
    logger.info(f"[multi_variant] simplified Pipeline完成, elapsed={simplified_elapsed:.1f}s, status={simplified_status}")

    return {
        "simplified_result": simplified_result,
        "simplified_elapsed": simplified_elapsed,
        "simplified_status": simplified_status,
        "emr_to_eval": emr_to_eval,
    }


def _evaluate_config(
    evaluator,
    dialogue_text: str,
    emr_to_eval: Dict,
    sample_id: str,
    config_key: str,
    key_facts: Dict,
    eval_cache: Dict
) -> Optional[Any]:
    """评估单个配置，支持去重缓存"""
    dedup_source = EVAL_DEDUP_GROUPS.get(config_key)
    eval_cache_key = dedup_source if dedup_source else config_key

    if eval_cache_key in eval_cache:
        eval_result = eval_cache[eval_cache_key]
        logger.info(f"[multi_variant] {config_key}: 复用 {eval_cache_key} 的评估结果 (去重), support_rate={eval_result.get_support_rate()}, recall_rate={eval_result.get_recall_rate()}")
        return eval_result

    try:
        eval_result = evaluator.evaluate_all(
            dialogue_text,
            emr_to_eval,
            sample_id=sample_id,
            key_facts=key_facts,
            skip_quality_safety=True
        )
        eval_cache[eval_cache_key] = eval_result
        logger.info(f"[multi_variant] {config_key}评估完成: support_rate={eval_result.get_support_rate()}, recall_rate={eval_result.get_recall_rate()}")
        return eval_result
    except Exception as e:
        logger.error(f"[multi_variant] {config_key}评估失败: {e}")
        return None


def _compute_config_llm_stats(
    config_key: str,
    config_llm_stats: Dict,
    simplified_result: Optional[Dict] = None
) -> Dict:
    """计算配置的LLM统计，simplified配置使用独立Pipeline的实际统计"""
    config_llm_calls, config_char_count, config_token_count, config_actual_latency = compute_llm_stats_for_config(
        config_key, config_llm_stats
    )

    config_stage_breakdown = {}

    if config_key == "simplified" and simplified_result:
        simplified_llm_stats = simplified_result.get("llm_stats", {})
        simplified_total_calls = simplified_llm_stats.get("total_calls") or 0
        if simplified_total_calls > 0:
            config_llm_calls = simplified_total_calls
            config_char_count = simplified_llm_stats.get("total_char_count") or 0
            config_actual_latency = simplified_llm_stats.get("total_actual_latency") or 0.0
            config_token_count = simplified_llm_stats.get("total_tokens") or 0
            config_stage_breakdown = simplified_llm_stats.get("stage_breakdown", {})
            logger.info(f"[DEBUG] {config_key}: 使用simplified的实际LLM stats - calls={config_llm_calls}, chars={config_char_count}, tokens={config_token_count}")
        else:
            logger.warning(f"[DEBUG] {config_key}: simplified_llm_stats.total_calls=0，保留compute_llm_stats_for_config的计算结果 - calls={config_llm_calls}, chars={config_char_count}, tokens={config_token_count}")
    else:
        config_stage_breakdown = _extract_stage_breakdown(config_key, config_llm_stats)

    return {
        "config_llm_calls": config_llm_calls,
        "config_char_count": config_char_count,
        "config_token_count": config_token_count,
        "config_actual_latency": config_actual_latency,
        "config_stage_breakdown": config_stage_breakdown,
    }


def run_multi_variant(
    samples: List[Dict[str, Any]],
    output_dir,
    request_interval: float,
    re_evaluate: bool,
    sequential: bool,
    limit: int = 0
) -> Dict[str, Dict[str, Any]]:
    """
    多变量Pipeline：一次运行产出7份评估结果

    流程：
    1. process_with_fork() → 5份EMR
    2. extract_key_facts() → key_facts（一次）
    3. 评估映射到7个配置
    4. 独立运行 simplified Pipeline

    Returns:
        {sample_id: {config_key: entry}}
    """
    from pathlib import Path

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    samples_to_run = samples[:limit] if limit > 0 else samples

    logger.info(f"开始多变量Pipeline评估 - samples={len(samples_to_run)}, limit={limit}")
    print(f"\n{'='*60}")
    print(f"  多变量Pipeline评估 (multi)")
    print(f"  样本数: {len(samples_to_run)}")
    print(f"{'='*60}\n")

    benchmark_db = get_benchmark_session()
    all_results = {}

    for sample in samples_to_run:
        sample_id = sample.get("sample_id", "")
        dialogue_text = sample.get("dialogue_text", "")

        print(f"处理样本: {sample_id}...", flush=True)
        logger.info(f"[multi_variant] 处理样本: {sample_id}")

        # 检查已有配置
        existing_configs = {}
        missing_configs = []
        configs_needing_eval = []

        for config_key in CONFIG_OUTPUT_MAPPING.keys():
            existing_run = check_existing_run(benchmark_db, sample_id, config_key)
            if existing_run and not re_evaluate:
                existing_configs[config_key] = existing_run
                # 检查是否缺少evaluation
                if not check_run_has_evaluation(benchmark_db, existing_run.id):
                    configs_needing_eval.append(config_key)
            else:
                missing_configs.append(config_key)

        # 补充缺失的evaluation（不重新运行Pipeline）
        if configs_needing_eval:
            logger.info(f"[补充评估] 补充缺失evaluation - sample_id={sample_id}, configs={configs_needing_eval}")
            for ck in configs_needing_eval:
                er = existing_configs[ck]
                print(f"  补充评估 {ck}...", end=" ", flush=True)
                qm = supplement_evaluation(benchmark_db, sample, er, ck)
                if qm:
                    print(f"OK", flush=True)
                else:
                    print(f"WARN (评估补充失败)", flush=True)

        if not missing_configs:
            logger.info(f"[multi_variant] SKIP - 所有配置已存在 - sample_id={sample_id}")
            print(f"SKIP (所有{len(CONFIG_OUTPUT_MAPPING)}个配置已存在)", flush=True)
            sample_results = _process_existing_configs(sample, existing_configs)
            all_results[sample_id] = sample_results
            continue

        if existing_configs:
            logger.info(f"[multi_variant] 部分配置已存在，只评估缺失的 {len(missing_configs)} 个配置 - sample_id={sample_id}")
            print(f"  已存在: {list(existing_configs.keys())}, 需评估: {missing_configs}", flush=True)

        # 检查中间结果
        intermediate_results = check_intermediate_results(benchmark_db, sample_id, missing_configs=missing_configs)
        logger.info(f"[中间结果检查] 返回结果: sample_id={sample_id}, has_results={intermediate_results is not None}, re_evaluate={re_evaluate}")

        # 初始化EMR和统计变量
        emr_raw_draft = emr_pre_revision = emr_result = None
        emr_no_term_norm = emr_no_hallucination = None
        hallucination_result = verification_issues = None
        key_facts_cached = None
        visit_id_cached = None
        fork_elapsed = fork_elapsed_actual = 0
        llm_stats = llm_stats_full = llm_stats_no_term_norm = llm_stats_no_hallucination = {}
        orchestrator = None
        llm_service = None

        if intermediate_results and not re_evaluate:
            logger.info(f"[multi_variant] 发现已有中间结果，尝试复用 - sample_id={sample_id}")
            print(f"  复用中间结果: {list(intermediate_results.keys())}", flush=True)

            emr_raw_draft = intermediate_results.get("emr_raw_draft")
            emr_pre_revision = intermediate_results.get("emr_pre_revision")
            emr_result = intermediate_results.get("emr_result")
            emr_no_term_norm = intermediate_results.get("emr_no_term_norm")
            emr_no_hallucination = intermediate_results.get("emr_no_hallucination")
            hallucination_result = intermediate_results.get("hallucination_result")
            verification_issues = intermediate_results.get("verification_issues")
            key_facts_cached = intermediate_results.get("key_facts")

            cached_run = benchmark_db.query(BenchmarkRun).filter(
                BenchmarkRun.sample_id == sample_id,
                BenchmarkRun.config_key == "full"
            ).order_by(BenchmarkRun.created_at.desc()).first()

            if cached_run:
                logger.info(f"[复用中间结果] cached_run id={cached_run.id}, visit_id={cached_run.visit_id}")
                visit_id_cached = cached_run.visit_id
            else:
                logger.warning(f"[复用中间结果] 未找到cached_run - sample_id={sample_id}")

            fork_elapsed = cached_run.elapsed_seconds if cached_run else 0
            fork_elapsed_actual = fork_elapsed

            # 恢复LLM统计
            restored = _restore_cached_llm_stats(cached_run)
            llm_stats = restored["llm_stats"]
            llm_stats_full = restored["llm_stats_full"]
            llm_stats_no_term_norm = restored["llm_stats_no_term_norm"]
            llm_stats_no_hallucination = restored["llm_stats_no_hallucination"]
        else:
            intermediate_results = None
            logger.info(f"[复用中间结果] 不复用 - sample_id={sample_id}, 原因: {'re_evaluate=True' if re_evaluate else '中间结果不完整'}")

        db = build_main_db_session()
        try:
            if intermediate_results:
                visit_id = visit_id_cached or f"exp_{sample_id}_{uuid.uuid4().hex[:8]}"
                llm_service = LLMService(db)
            else:
                fork_data = _run_fork_pipeline(db, sample, sequential)
                visit_id = fork_data["visit_id"]
                orchestrator = fork_data["orchestrator"]
                llm_service = fork_data["llm_service"]

                extracted = _extract_fork_data(fork_data)
                emr_raw_draft = extracted["emr_raw_draft"]
                emr_pre_revision = extracted["emr_pre_revision"]
                emr_result = extracted["emr_result"]
                emr_no_term_norm = extracted["emr_no_term_norm"]
                emr_no_hallucination = extracted["emr_no_hallucination"]
                hallucination_result = extracted["hallucination_result"]
                verification_issues = extracted["verification_issues"]
                llm_stats = extracted["llm_stats"]
                llm_stats_full = extracted["llm_stats_full"]
                llm_stats_no_term_norm = extracted["llm_stats_no_term_norm"]
                llm_stats_no_hallucination = extracted["llm_stats_no_hallucination"]
                fork_elapsed_actual = extracted["fork_elapsed_actual"]

                if extracted["fork_status"] != "completed":
                    logger.error(f"[multi_variant] process_with_fork失败: {extracted['fork_error']}")
                    print(f"FAIL (fork failed, 保存中间结果到数据库)", flush=True)

                    save_benchmark_run(
                        benchmark_db,
                        sample_id=sample_id,
                        config_key="full",
                        visit_id=visit_id,
                        status="failed",
                        emr_raw_draft=emr_raw_draft,
                        emr_pre_revision=emr_pre_revision,
                        emr_result=emr_result,
                        emr_no_term_norm=emr_no_term_norm,
                        emr_no_hallucination=emr_no_hallucination,
                        hallucination_result=hallucination_result,
                        verification_issues=verification_issues,
                        elapsed_seconds=fork_elapsed_actual,
                        stage_breakdown=extracted["stage_breakdown"],
                        error_message=extracted["fork_error"]
                    )
                    logger.info(f"[multi_variant] 已保存失败状态和中间结果到数据库 - sample_id={sample_id}")

                    benchmark_db.close()
                    db.close()
                    raise RuntimeError(f"process_with_fork failed for sample {sample_id}: {extracted['fork_error']}")

                save_benchmark_run(
                    benchmark_db,
                    sample_id=sample_id,
                    config_key="full",
                    visit_id=visit_id,
                    status=extracted["fork_status"],
                    emr_raw_draft=emr_raw_draft,
                    emr_pre_revision=emr_pre_revision,
                    emr_result=emr_result,
                    emr_no_term_norm=emr_no_term_norm,
                    emr_no_hallucination=emr_no_hallucination,
                    hallucination_result=hallucination_result,
                    verification_issues=verification_issues,
                    elapsed_seconds=fork_elapsed_actual,
                    llm_call_count=extracted["llm_call_count"],
                    char_count=extracted["char_count"],
                    token_count=extracted["token_count"],
                    stage_breakdown=extracted["stage_breakdown"],
                    error_message=None
                )
                logger.info(f"[multi_variant] 已保存中间结果到数据库 - sample_id={sample_id}, llm_calls={extracted['llm_call_count']}")

            # 提取key_facts
            evaluator = BenchmarkEvaluator(llm_service)
            key_facts = _extract_key_facts(
                llm_service, dialogue_text, sample_id,
                key_facts_cached, intermediate_results, benchmark_db
            )

            # 处理已存在的配置
            sample_results = _process_existing_configs(sample, existing_configs)
            for config_key in existing_configs:
                print(f"  {config_key}: SKIP (已存在)", flush=True)

            # 评估缺失的配置
            simplified_elapsed = 0
            simplified_result = None
            eval_cache = {}

            logger.info(f"[DEBUG] 配置评估循环开始 - sample_id={sample_id}")
            logger.info(f"[DEBUG]   - existing_configs数量: {len(existing_configs)}")
            logger.info(f"[DEBUG]   - missing_configs数量: {len([k for k in CONFIG_OUTPUT_MAPPING.keys() if k not in existing_configs])}")

            for config_key, mapping in CONFIG_OUTPUT_MAPPING.items():
                if config_key in existing_configs:
                    continue

                logger.info(f"[DEBUG] 开始评估配置 - config_key={config_key}, sample_id={sample_id}")

                emr_key = mapping.get("emr_key")
                output_type = mapping.get("type")

                logger.info(f"[DEBUG]   - emr_key={emr_key}, output_type={output_type}")

                # 获取EMR
                if emr_key is None:
                    # simplified配置，独立运行Pipeline
                    simplified_data = _run_simplified_pipeline(
                        db, sample, visit_id, orchestrator, llm_service, sequential
                    )
                    simplified_result = simplified_data["simplified_result"]
                    simplified_elapsed = simplified_data["simplified_elapsed"]
                    emr_to_eval = simplified_data["emr_to_eval"]

                    if simplified_data["simplified_status"] != "completed":
                        error_msg = simplified_result.get("error", "Unknown error")
                        logger.error(f"[multi_variant] simplified Pipeline失败: {error_msg}, 保存失败状态并停止")
                        save_benchmark_run(
                            benchmark_db,
                            sample_id=sample_id,
                            config_key="simplified",
                            visit_id=visit_id,
                            status="failed",
                            emr_result=emr_to_eval,
                            elapsed_seconds=simplified_elapsed,
                            error_message=error_msg
                        )
                        benchmark_db.close()
                        db.close()
                        raise RuntimeError(f"simplified pipeline failed for sample {sample_id}: {error_msg}")
                else:
                    emr_map = {
                        "emr_raw_draft": emr_raw_draft,
                        "emr_pre_revision": emr_pre_revision,
                        "emr_result": emr_result,
                        "emr_no_term_norm": emr_no_term_norm,
                        "emr_no_hallucination": emr_no_hallucination
                    }
                    emr_to_eval = emr_map.get(emr_key)

                    logger.info(f"[DEBUG] EMR选择 - config_key={config_key}, emr_key={emr_key}")
                    logger.info(f"[DEBUG]   - emr_to_eval存在: {emr_to_eval is not None}")
                    if emr_to_eval:
                        logger.info(f"[DEBUG]   - emr_to_eval是否为空: {is_emr_empty(emr_to_eval)}")

                if not emr_to_eval:
                    logger.warning(f"[multi_variant] {config_key}: EMR为空，跳过评估 - emr_key={emr_key}")
                    continue

                # 计算质量指标
                quality_metrics = compute_quality_metrics(emr_to_eval, sample.get("diagnosis", ""))
                logger.info(f"[DEBUG] {config_key}: quality_metrics计算完成 - structure_completeness={quality_metrics.get('structure_completeness')}, field_missing_rate={quality_metrics.get('field_missing_rate')}")

                # 评估
                eval_result = _evaluate_config(
                    evaluator, dialogue_text, emr_to_eval, sample_id,
                    config_key, key_facts, eval_cache
                )

                config_info = EXPERIMENT_CONFIGS.get(config_key, ABLATION_CONFIGS.get(config_key, {"name": config_key}))

                # 计算LLM统计
                config_llm_stats = _resolve_config_llm_stats(
                    config_key, llm_stats_full, llm_stats_no_term_norm,
                    llm_stats_no_hallucination, llm_stats
                )
                logger.info(f"[DEBUG] {config_key}: 开始计算LLM stats, stats_source={CONFIG_LLM_STATS_SOURCE.get(config_key)}")

                llm_stats_result = _compute_config_llm_stats(config_key, config_llm_stats, simplified_result)
                config_llm_calls = llm_stats_result["config_llm_calls"]
                config_char_count = llm_stats_result["config_char_count"]
                config_token_count = llm_stats_result["config_token_count"]
                config_actual_latency = llm_stats_result["config_actual_latency"]
                config_stage_breakdown = llm_stats_result["config_stage_breakdown"]

                logger.info(f"[DEBUG] {config_key}: LLM stats计算完成")
                logger.info(f"[DEBUG]   - config_llm_calls={config_llm_calls}, config_char_count={config_char_count}, config_token_count={config_token_count}, config_actual_latency={config_actual_latency}")

                config_elapsed = config_actual_latency if config_actual_latency > 0 else (fork_elapsed_actual if emr_key else simplified_elapsed)
                logger.info(f"[DEBUG] {config_key}: elapsed计算 - config_elapsed={config_elapsed}, fork_elapsed_actual={fork_elapsed_actual}, simplified_elapsed={simplified_elapsed}")

                # 构建JSONL条目
                entry = build_jsonl_entry(
                    sample=sample,
                    config_key=config_key,
                    config_name=config_info.get("name", config_key),
                    visit_id=visit_id,
                    status="completed",
                    elapsed_seconds=config_elapsed,
                    emr_result=emr_to_eval,
                    hallucination_result=hallucination_result if config_key == "full" else None,
                    verification_issues=verification_issues if config_key in ["full", "no_verification"] else None,
                    quality_metrics=quality_metrics,
                    eval_result=eval_result,
                    llm_call_count=config_llm_calls,
                    char_count=config_char_count,
                    error_message=None
                )

                # 写入JSONL
                output_file = output_dir / f"results_{config_key}_{timestamp}.jsonl"
                with open(output_file, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")

                sample_results[config_key] = entry

                # full配置同时输出ablation
                if output_type == "both":
                    ablation_entry = entry.copy()
                    ablation_entry["config_type"] = "ablation"
                    ablation_output = output_dir / f"results_full_ablation_{timestamp}.jsonl"
                    with open(ablation_output, 'a', encoding='utf-8') as f:
                        f.write(json.dumps(ablation_entry, ensure_ascii=False) + "\n")

                # 保存到数据库
                run_record = save_benchmark_run(
                    benchmark_db,
                    sample_id=sample_id,
                    config_key=config_key,
                    visit_id=visit_id,
                    status="completed",
                    emr_raw_draft=emr_raw_draft if config_key == "full" else None,
                    emr_pre_revision=emr_pre_revision if config_key == "full" else None,
                    emr_result=emr_to_eval,
                    hallucination_result=hallucination_result if config_key == "full" else None,
                    verification_issues=verification_issues if config_key in ["full", "no_verification"] else None,
                    elapsed_seconds=config_elapsed,
                    llm_call_count=config_llm_calls,
                    char_count=config_char_count,
                    token_count=config_token_count,
                    stage_breakdown=config_stage_breakdown,
                    error_message=None
                )

                logger.info(f"[DEBUG] {config_key}: 数据库保存完成")
                logger.info(f"[DEBUG]   - run_record.id={run_record.id}, llm_call_count={run_record.llm_call_count}, char_count={run_record.char_count}, token_count={run_record.token_count}")

                if eval_result:
                    save_benchmark_evaluation(
                        benchmark_db, run_record, eval_result,
                        quality_metrics, error_message=None
                    )

                print(f"  {config_key}: OK", flush=True)

            all_results[sample_id] = sample_results
            time.sleep(request_interval)

        except Exception as e:
            error_msg = f"{str(e)}\n{traceback.format_exc()}"
            logger.error(f"[multi_variant] 样本处理异常: {sample_id}, error={error_msg}")
            print(f"FAIL ({error_msg})", flush=True)
        finally:
            db.close()

    close_benchmark_session(benchmark_db)

    # 输出汇总
    _write_multi_variant_summaries(all_results, output_dir, timestamp, benchmark_db)

    print(f"\n{'='*60}")
    print(f"  完成: {len(all_results)} 样本")
    print(f"{'='*60}\n")

    return all_results


def _write_multi_variant_summaries(
    all_results: Dict[str, Dict[str, Any]],
    output_dir,
    timestamp: str,
    benchmark_db
):
    """输出多变量Pipeline的各配置汇总"""
    from scripts.run_full_benchmark.runner import compute_summary

    for config_key in MULTI_VARIANT_CONFIG_ORDER:
        config_results = []
        for sample_id, sample_data in all_results.items():
            if config_key in sample_data:
                config_results.append(sample_data[config_key])

        if not config_results:
            continue

        config_info = EXPERIMENT_CONFIGS.get(config_key, ABLATION_CONFIGS.get(config_key, {"name": config_key}))
        summary = compute_summary(config_results, config_key, config_info.get("name", config_key), 0)

        summary_file = output_dir / f"summary_{config_key}_{timestamp}.json"
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        save_benchmark_summary(benchmark_db, summary)

        if config_key == "full":
            ablation_summary = summary.copy()
            ablation_summary["config_type"] = "ablation"
            ablation_summary_file = output_dir / f"summary_full_ablation_{timestamp}.json"
            with open(ablation_summary_file, 'w', encoding='utf-8') as f:
                json.dump(ablation_summary, f, ensure_ascii=False, indent=2)
