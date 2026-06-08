"""
FullBenchmarkRunner 主类

组合各模块，提供run_batch、run_single_sample、run_all_configs、run_ablations等方法。
"""

import json
import time
import uuid
import traceback
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from collections import defaultdict
import statistics

from backend.benchmark_db import (
    init_benchmark_db, get_benchmark_session, close_benchmark_session,
    BENCHMARK_DATABASE_URL
)

from scripts.run_full_benchmark.configs import (
    EXPERIMENT_CONFIGS, ABLATION_CONFIGS
)
from scripts.run_full_benchmark.metrics import compute_quality_metrics
from scripts.run_full_benchmark.db_helper import (
    check_existing_run, save_benchmark_run, save_benchmark_evaluation,
    save_benchmark_summary
)
from scripts.run_full_benchmark.pipeline_runner import (
    run_pipeline, run_evaluation, build_jsonl_entry
)
from scripts.run_full_benchmark.multi_variant import run_multi_variant

logger = logging.getLogger(__name__)


def compute_summary(
    results: List[Dict[str, Any]],
    config_key: str,
    config_name: str,
    total_seconds: float
) -> Dict[str, Any]:
    """计算汇总统计"""
    completed = [r for r in results if r.get("status") == "completed"]

    def safe_mean(vals):
        if not vals:
            return None
        return sum(vals) / len(vals)

    def safe_std(vals):
        if len(vals) < 2:
            return None
        return statistics.stdev(vals)

    elapsed_vals = [r.get("elapsed_seconds", 0) for r in completed]
    llm_call_vals = [r.get("llm_call_count", 0) for r in completed]
    char_count_vals = [r.get("char_count", 0) for r in completed]

    support_rates = []
    hallucination_rates = []
    recall_rates = []
    omission_rates = []
    structure_completenesses = []
    field_missing_rates = []
    diagnosis_matches = []

    for r in completed:
        eval_data = r.get("llm_evaluation", {})
        if eval_data:
            if eval_data.get("consistency"):
                support_rates.append(eval_data["consistency"].get("summary", {}).get("support_rate", 0))
                hallucination_rates.append(1 - eval_data["consistency"].get("summary", {}).get("support_rate", 1))
            if eval_data.get("completeness"):
                recall_rates.append(eval_data["completeness"].get("summary", {}).get("recall_rate", 0))
                omission_rates.append(eval_data["completeness"].get("summary", {}).get("omission_rate", 0))

        qm = r.get("quality_metrics", {})
        if qm:
            structure_completenesses.append(qm.get("structure_completeness", 0))
            field_missing_rates.append(qm.get("field_missing_rate", 0))
            if qm.get("diagnosis_match") is not None:
                diagnosis_matches.append(1 if qm.get("diagnosis_match") else 0)

    return {
        "config": config_name,
        "config_key": config_key,
        "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "total": len(results),
        "success": len(completed),
        "failed": len(results) - len(completed),
        "total_seconds": round(total_seconds, 1),
        "avg_seconds": safe_mean(elapsed_vals),
        "std_seconds": safe_std(elapsed_vals),
        "avg_llm_call_count": safe_mean(llm_call_vals),
        "avg_char_count": safe_mean(char_count_vals),
        "avg_support_rate": safe_mean(support_rates),
        "std_support_rate": safe_std(support_rates),
        "avg_hallucination_rate": safe_mean(hallucination_rates),
        "avg_recall_rate": safe_mean(recall_rates),
        "std_recall_rate": safe_std(recall_rates),
        "avg_omission_rate": safe_mean(omission_rates),
        "avg_structure_completeness": safe_mean(structure_completenesses),
        "avg_field_missing_rate": safe_mean(field_missing_rates),
        "avg_diagnosis_match": safe_mean(diagnosis_matches),
        "diagnosis_match_count": len(diagnosis_matches),
    }


class FullBenchmarkRunner:
    """全量化指标评估运行器"""

    def __init__(
        self,
        samples_file: str,
        output_dir: str,
        request_interval: float = 2.0,
        re_evaluate: bool = False,
        sample_id: str = None,
        sequential: bool = False
    ):
        self.samples = self._load_samples(samples_file)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.request_interval = request_interval
        self.re_evaluate = re_evaluate
        self.sample_id = sample_id
        self.sequential = sequential

        # 如果指定了sample_id，筛选样本
        if self.sample_id:
            self.samples = [s for s in self.samples if s.get("sample_id") == self.sample_id]
            if not self.samples:
                logger.warning(f"未找到指定样本: sample_id={self.sample_id}")
            else:
                logger.info(f"筛选样本: sample_id={self.sample_id}, 找到 {len(self.samples)} 个")

        init_benchmark_db()
        logger.info(f"Benchmark数据库初始化完成: {BENCHMARK_DATABASE_URL}")

    @staticmethod
    def _load_samples(path: str) -> List[Dict[str, Any]]:
        """加载测试样本"""
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get("samples", [])

    def run_single_sample(
        self,
        sample: Dict[str, Any],
        config_key: str,
        config_info: Dict[str, Any],
        benchmark_db
    ) -> Dict[str, Any]:
        """运行单个样本的单个配置"""
        sample_id = sample.get("sample_id", "")
        config_name = config_info.get("name", config_key)

        logger.info(f"处理样本: {sample_id} ({config_name})")
        print(f"  [{config_key}] {sample_id}...", end=" ", flush=True)

        existing_run = check_existing_run(benchmark_db, sample_id, config_key)

        if existing_run and not self.re_evaluate:
            logger.info(f"[Skip] 样本已存在且成功 - sample_id={sample_id}, config={config_key}")
            print(f"SKIP (已存在)", flush=True)

            quality_metrics = compute_quality_metrics(existing_run.emr_result, sample.get("diagnosis", ""))

            return build_jsonl_entry(
                sample=sample,
                config_key=config_key,
                config_name=config_name,
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

        visit_id = ""
        status = "failed"
        elapsed_seconds = 0.0
        emr_result = None
        hallucination_result = None
        verification_issues = None
        quality_metrics = None
        eval_result = None
        llm_call_count = 0
        char_count = 0
        token_count = 0
        stage_breakdown = None
        pipeline_error = None
        eval_error = None

        emr_result, hallucination_result, verification_issues, elapsed_seconds, llm_call_count, char_count, token_count, stage_breakdown, pipeline_error = \
            run_pipeline(sample, config_key, config_info, self.sequential)

        if emr_result:
            status = "completed"
            visit_id = f"exp_{sample_id}_{uuid.uuid4().hex[:8]}"
            quality_metrics = compute_quality_metrics(emr_result, sample.get("diagnosis", ""))

            eval_result, eval_error = run_evaluation(sample, emr_result, config_key)

            if eval_result:
                llm_call_count += eval_result.get_total_llm_calls()
                char_count += eval_result.get_total_char_count()
                eval_tokens = eval_result.get_total_tokens()
                if eval_tokens:
                    token_count += eval_tokens
        else:
            status = "failed"
            visit_id = f"exp_{sample_id}_{uuid.uuid4().hex[:8]}"

        run = save_benchmark_run(
            benchmark_db,
            sample_id=sample_id,
            config_key=config_key,
            visit_id=visit_id,
            status=status,
            emr_result=emr_result,
            hallucination_result=hallucination_result,
            verification_issues=verification_issues,
            elapsed_seconds=elapsed_seconds,
            llm_call_count=llm_call_count,
            char_count=char_count,
            token_count=token_count,
            stage_breakdown=stage_breakdown,
            error_message=pipeline_error or eval_error
        )

        if eval_result and status == "completed":
            save_benchmark_evaluation(benchmark_db, run, eval_result, quality_metrics, eval_error)

        if status == "completed":
            print(f"OK ({elapsed_seconds:.1f}s, {llm_call_count} calls)", flush=True)
        else:
            print(f"FAIL ({pipeline_error or eval_error})", flush=True)

        return build_jsonl_entry(
            sample=sample,
            config_key=config_key,
            config_name=config_name,
            visit_id=visit_id,
            status=status,
            elapsed_seconds=elapsed_seconds,
            emr_result=emr_result,
            hallucination_result=hallucination_result,
            verification_issues=verification_issues,
            quality_metrics=quality_metrics,
            eval_result=eval_result,
            llm_call_count=llm_call_count,
            char_count=char_count,
            error_message=pipeline_error or eval_error
        )

    def run_batch(
        self,
        config_key: str,
        limit: int = 0
    ) -> List[Dict[str, Any]]:
        """批量运行单个配置"""
        if config_key in EXPERIMENT_CONFIGS:
            config_info = EXPERIMENT_CONFIGS[config_key]
        elif config_key in ABLATION_CONFIGS:
            config_info = ABLATION_CONFIGS[config_key]
        else:
            logger.error(f"未知配置: {config_key}")
            print(f"错误: 未知配置 {config_key}")
            return []

        config_name = config_info.get("name", config_key)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        output_file = self.output_dir / f"results_{config_key}_{timestamp}.jsonl"
        summary_file = self.output_dir / f"summary_{config_key}_{timestamp}.json"

        logger.info(f"开始批量运行 - config={config_name}, samples={len(self.samples)}, limit={limit}")
        print(f"\n{'='*60}")
        print(f"  配置: {config_name} ({config_key})")
        print(f"  样本数: {len(self.samples)}")
        print(f"  输出: {output_file}")
        print(f"{'='*60}\n")

        samples_to_run = self.samples[:limit] if limit > 0 else self.samples

        benchmark_db = get_benchmark_session()
        results = []
        success_count = 0
        failed_count = 0

        t_total_start = time.time()

        for sample in samples_to_run:
            try:
                entry = self.run_single_sample(sample, config_key, config_info, benchmark_db)
                results.append(entry)

                if entry.get("status") == "completed":
                    success_count += 1
                else:
                    failed_count += 1

                with open(output_file, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")

                time.sleep(self.request_interval)

            except Exception as e:
                error_msg = f"{str(e)}\n{traceback.format_exc()}"
                logger.error(f"样本处理异常: {sample.get('sample_id', '')}, error={error_msg}")

                entry = {
                    "sample_id": sample.get("sample_id", ""),
                    "config": config_name,
                    "config_key": config_key,
                    "status": "error",
                    "error_message": error_msg,
                }
                results.append(entry)
                failed_count += 1

                with open(output_file, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        close_benchmark_session(benchmark_db)

        t_total = time.time() - t_total_start

        summary = compute_summary(results, config_key, config_name, t_total)

        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        save_benchmark_summary(benchmark_db, summary)

        print(f"\n{'='*60}")
        print(f"  完成: {success_count}/{len(results)} 成功, {failed_count} 失败")
        print(f"  耗时: {timedelta(seconds=int(t_total))} (avg {t_total/len(results):.1f}s/样本)")
        print(f"  汇总: {summary_file}")
        print(f"{'='*60}\n")

        return results

    def run_all_configs(self, limit: int = 0):
        """运行所有实验配置"""
        all_results = {}
        for config_key in EXPERIMENT_CONFIGS.keys():
            results = self.run_batch(config_key, limit=limit)
            all_results[config_key] = results
        return all_results

    def run_ablations(self, limit: int = 0):
        """运行所有消融配置"""
        all_results = {}
        for config_key in ABLATION_CONFIGS.keys():
            results = self.run_batch(config_key, limit=limit)
            all_results[config_key] = results
        return all_results

    def run_multi_variant(self, limit: int = 0):
        """多变量Pipeline：委托给multi_variant模块"""
        return run_multi_variant(
            samples=self.samples,
            output_dir=self.output_dir,
            request_interval=self.request_interval,
            re_evaluate=self.re_evaluate,
            sequential=self.sequential,
            limit=limit
        )
