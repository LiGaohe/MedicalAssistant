"""
Benchmark 数据库完整性检查脚本

检查内容：
  1. 样本量统计：各配置的唯一样本数、总运行数、成功/失败数
  2. 重复运行检测：同一配置下同一 sample_id 被多次运行
  3. 评估数据缺失：已完成运行但缺少评估记录
  4. 评估指标缺失：评估记录中关键字段为 NULL
  5. 延迟异常检测：耗时超过阈值的运行（疑似超时/卡死）
  6. 失败运行统计：状态为 failed 的运行及错误信息
  7. 阶段数据完整性：stage_breakdown 是否与配置阶段一致
  8. 数据质量汇总：各配置能否满足论文表格填写需求

用法：
  python scripts/check_benchmark_data.py                     # 执行全部检查
  python scripts/check_benchmark_data.py --config full       # 只检查指定配置
  python scripts/check_benchmark_data.py --fix-duplicates    # 清理重复运行（保留最近一条）
  python scripts/check_benchmark_data.py --latency-threshold 2000  # 自定义延迟阈值（秒）

输出：
  控制台打印检查报告，日志写入 data/logs/check_benchmark_data.log
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import create_engine, func, text
from sqlalchemy.orm import sessionmaker

from backend.models.benchmark import (
    BenchmarkRun, BenchmarkStage, BenchmarkEvaluation,
    BenchmarkLLMCall, BenchmarkSummary
)
from backend.benchmark_db import BENCHMARK_DATABASE_URL

LOG_DIR = Path("data/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / "check_benchmark_data.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 各配置包含的 LLM 调用阶段（与 extract_benchmark_results.py 一致）
CONFIG_STAGE_GROUPS = {
    "end_to_end": [
        "draft_generation_free_text",
        "draft_generation_json"
    ],
    "simplified": [
        "draft_generation_free_text",
        "draft_generation_json",
        "soap_structuring"
    ],
    "standard": [
        "turn_cleaning",
        "draft_generation_free_text",
        "draft_generation_json",
        "soap_structuring",
        "claim_verification",
        "checklist_verification",
        "certainty_verification",
        "field_revision"
    ],
    "full": [
        "turn_cleaning",
        "draft_generation_free_text",
        "draft_generation_json",
        "soap_structuring",
        "term_norm",
        "hallucination_check",
        "claim_verification",
        "checklist_verification",
        "certainty_verification",
        "field_revision"
    ],
    "no_verification": [
        "turn_cleaning",
        "draft_generation_free_text",
        "draft_generation_json",
        "soap_structuring",
        "term_norm",
        "hallucination_check"
    ],
    "no_hallucination": [
        "turn_cleaning",
        "draft_generation_free_text",
        "draft_generation_json",
        "soap_structuring",
        "term_norm",
        "claim_verification",
        "checklist_verification",
        "certainty_verification",
        "field_revision"
    ],
    "no_term_norm": [
        "turn_cleaning",
        "draft_generation_free_text",
        "draft_generation_json",
        "soap_structuring",
        "hallucination_check",
        "claim_verification",
        "checklist_verification",
        "certainty_verification",
        "field_revision"
    ]
}

# 评估指标字段
EVAL_METRICS = [
    "support_rate", "hallucination_rate", "recall_rate", "omission_rate",
    "structure_completeness", "field_missing_rate", "diagnosis_match"
]

# 运行指标字段
RUN_METRICS = ["elapsed_seconds", "llm_call_count", "char_count"]

# 论文要求的样本量
REQUIRED_SAMPLES_SCREENING = 30
REQUIRED_SAMPLES_FORMAL = 100


class BenchmarkDataChecker:
    """Benchmark 数据库完整性检查器"""

    def __init__(self, db_url: str = None, latency_threshold: float = 2000):
        if db_url is None:
            db_url = BENCHMARK_DATABASE_URL
        self.engine = create_engine(db_url)
        self.Session = sessionmaker(bind=self.engine)
        self.latency_threshold = latency_threshold
        self.issues: List[Dict[str, Any]] = []
        logger.info(f"连接数据库: {db_url}")
        logger.info(f"延迟异常阈值: {latency_threshold}s")

    def _add_issue(self, category: str, severity: str, config: str,
                   sample_id: str = "", detail: str = ""):
        """记录一个问题"""
        self.issues.append({
            "category": category,
            "severity": severity,
            "config": config,
            "sample_id": sample_id,
            "detail": detail
        })

    def check_sample_quantity(self, config_key: str = None) -> Dict[str, Any]:
        """
        检查1：样本量统计

        统计各配置的唯一样本数、总运行数、成功/失败数，
        判断是否满足论文要求的样本量。
        """
        session = self.Session()
        try:
            configs = [config_key] if config_key else [
                r[0] for r in session.query(BenchmarkRun.config_key).distinct().all()
            ]

            results = {}
            for cfg in configs:
                runs = session.query(BenchmarkRun).filter(
                    BenchmarkRun.config_key == cfg
                ).all()

                unique_samples = set(r.sample_id for r in runs)
                completed = [r for r in runs if r.status == "completed"]
                failed = [r for r in runs if r.status == "failed"]

                results[cfg] = {
                    "unique_samples": len(unique_samples),
                    "total_runs": len(runs),
                    "completed_runs": len(completed),
                    "failed_runs": len(failed),
                    "sample_ids": sorted(unique_samples)
                }

                # 判断是否满足筛选阶段样本量
                if len(unique_samples) < REQUIRED_SAMPLES_SCREENING:
                    self._add_issue(
                        category="样本量不足",
                        severity="高",
                        config=cfg,
                        detail=f"唯一样本数 {len(unique_samples)}，"
                               f"筛选阶段要求 {REQUIRED_SAMPLES_SCREENING}，"
                               f"正式评测要求 {REQUIRED_SAMPLES_FORMAL}"
                    )

            return results
        finally:
            session.close()

    def check_duplicate_runs(self, config_key: str = None) -> Dict[str, Any]:
        """
        检查2：重复运行检测

        同一配置下同一 sample_id 被多次运行会导致统计偏差。
        检测所有重复运行，列出重复次数最多的样本。
        """
        session = self.Session()
        try:
            configs = [config_key] if config_key else [
                r[0] for r in session.query(BenchmarkRun.config_key).distinct().all()
            ]

            results = {}
            for cfg in configs:
                runs = session.query(BenchmarkRun).filter(
                    BenchmarkRun.config_key == cfg
                ).order_by(BenchmarkRun.created_at).all()

                sample_run_map = defaultdict(list)
                for r in runs:
                    sample_run_map[r.sample_id].append({
                        "run_id": r.id,
                        "status": r.status,
                        "created_at": str(r.created_at) if r.created_at else None,
                        "elapsed_seconds": r.elapsed_seconds
                    })

                duplicates = {
                    sid: run_list for sid, run_list in sample_run_map.items()
                    if len(run_list) > 1
                }

                results[cfg] = {
                    "total_samples": len(sample_run_map),
                    "duplicate_samples": len(duplicates),
                    "duplicates": duplicates
                }

                if duplicates:
                    max_dup_sid = max(duplicates.keys(), key=lambda s: len(duplicates[s]))
                    self._add_issue(
                        category="重复运行",
                        severity="高",
                        config=cfg,
                        sample_id=max_dup_sid,
                        detail=f"共 {len(duplicates)} 个样本有重复运行，"
                               f"最多重复 {len(duplicates[max_dup_sid])} 次 "
                               f"(sample_id={max_dup_sid})"
                    )

            return results
        finally:
            session.close()

    def check_missing_evaluations(self, config_key: str = None) -> Dict[str, Any]:
        """
        检查3：评估数据缺失

        已完成运行（status=completed）但没有对应的评估记录，
        说明评估阶段未执行或执行失败。
        """
        session = self.Session()
        try:
            configs = [config_key] if config_key else [
                r[0] for r in session.query(BenchmarkRun.config_key).distinct().all()
            ]

            results = {}
            for cfg in configs:
                completed_runs = session.query(BenchmarkRun).filter(
                    BenchmarkRun.config_key == cfg,
                    BenchmarkRun.status == "completed"
                ).all()

                missing = []
                for run in completed_runs:
                    eval_exists = session.query(BenchmarkEvaluation).filter(
                        BenchmarkEvaluation.run_id == run.id
                    ).first()

                    if not eval_exists:
                        missing.append({
                            "run_id": run.id,
                            "sample_id": run.sample_id,
                            "created_at": str(run.created_at) if run.created_at else None
                        })

                results[cfg] = {
                    "completed_runs": len(completed_runs),
                    "missing_evaluations": len(missing),
                    "missing_details": missing
                }

                if missing:
                    self._add_issue(
                        category="评估数据缺失",
                        severity="高",
                        config=cfg,
                        detail=f"{len(missing)}/{len(completed_runs)} 个已完成运行缺少评估记录"
                    )

            return results
        finally:
            session.close()

    def check_missing_metrics(self, config_key: str = None) -> Dict[str, Any]:
        """
        检查4：评估指标缺失

        评估记录存在但关键字段为 NULL，说明该层评估未完成。
        分别统计各指标的非空率。
        """
        session = self.Session()
        try:
            configs = [config_key] if config_key else [
                r[0] for r in session.query(BenchmarkRun.config_key).distinct().all()
            ]

            results = {}
            for cfg in configs:
                runs = session.query(BenchmarkRun).filter(
                    BenchmarkRun.config_key == cfg,
                    BenchmarkRun.status == "completed"
                ).all()

                metric_stats = {m: {"total": 0, "null": 0, "samples": []} for m in EVAL_METRICS}
                run_metric_stats = {m: {"total": 0, "null_or_zero": 0} for m in RUN_METRICS}

                for run in runs:
                    # 运行指标
                    for metric in RUN_METRICS:
                        val = getattr(run, metric, None)
                        run_metric_stats[metric]["total"] += 1
                        if val is None or val == 0:
                            run_metric_stats[metric]["null_or_zero"] += 1

                    # 评估指标
                    eval_record = session.query(BenchmarkEvaluation).filter(
                        BenchmarkEvaluation.run_id == run.id
                    ).first()

                    if not eval_record:
                        continue

                    for metric in EVAL_METRICS:
                        metric_stats[metric]["total"] += 1
                        val = getattr(eval_record, metric, None)
                        if val is None:
                            metric_stats[metric]["null"] += 1
                            metric_stats[metric]["samples"].append({
                                "run_id": run.id,
                                "sample_id": run.sample_id
                            })

                results[cfg] = {
                    "eval_metrics": metric_stats,
                    "run_metrics": run_metric_stats
                }

                # 报告缺失严重的指标
                for metric, stats in metric_stats.items():
                    if stats["total"] > 0 and stats["null"] > 0:
                        null_rate = stats["null"] / stats["total"]
                        if null_rate > 0.3:
                            self._add_issue(
                                category="评估指标缺失",
                                severity="中",
                                config=cfg,
                                detail=f"{metric} 缺失率 {null_rate:.0%} "
                                       f"({stats['null']}/{stats['total']})"
                            )

            return results
        finally:
            session.close()

    def check_latency_anomalies(self, config_key: str = None) -> Dict[str, Any]:
        """
        检查5：延迟异常检测

        耗时超过阈值的运行可能存在超时、网络卡死或 LLM 响应异常。
        同时检查各阶段的耗时，定位异常阶段。
        """
        session = self.Session()
        try:
            configs = [config_key] if config_key else [
                r[0] for r in session.query(BenchmarkRun.config_key).distinct().all()
            ]

            results = {}
            for cfg in configs:
                completed_runs = session.query(BenchmarkRun).filter(
                    BenchmarkRun.config_key == cfg,
                    BenchmarkRun.status == "completed"
                ).all()

                anomalies = []
                for run in completed_runs:
                    if run.elapsed_seconds and run.elapsed_seconds > self.latency_threshold:
                        # 检查阶段耗时
                        stage_breakdown = run.stage_breakdown or {}
                        slowest_stage = None
                        slowest_time = 0
                        for stage_name, stage_data in stage_breakdown.items():
                            stage_latency = stage_data.get("total_latency", 0)
                            if stage_latency and stage_latency > slowest_time:
                                slowest_time = stage_latency
                                slowest_stage = stage_name

                        anomalies.append({
                            "run_id": run.id,
                            "sample_id": run.sample_id,
                            "elapsed_seconds": run.elapsed_seconds,
                            "slowest_stage": slowest_stage,
                            "slowest_stage_latency": slowest_time,
                            "stage_breakdown": stage_breakdown
                        })

                results[cfg] = {
                    "threshold": self.latency_threshold,
                    "anomaly_count": len(anomalies),
                    "anomalies": anomalies
                }

                for anomaly in anomalies:
                    self._add_issue(
                        category="延迟异常",
                        severity="中",
                        config=cfg,
                        sample_id=anomaly["sample_id"],
                        detail=f"耗时 {anomaly['elapsed_seconds']:.0f}s，"
                               f"最慢阶段 {anomaly['slowest_stage']} "
                               f"({anomaly['slowest_stage_latency']:.0f}s)"
                    )

            return results
        finally:
            session.close()

    def check_failed_runs(self, config_key: str = None) -> Dict[str, Any]:
        """
        检查6：失败运行统计

        列出所有状态为 failed 的运行及错误信息，
        帮助定位系统性失败原因。
        """
        session = self.Session()
        try:
            configs = [config_key] if config_key else [
                r[0] for r in session.query(BenchmarkRun.config_key).distinct().all()
            ]

            results = {}
            for cfg in configs:
                failed_runs = session.query(BenchmarkRun).filter(
                    BenchmarkRun.config_key == cfg,
                    BenchmarkRun.status == "failed"
                ).all()

                failures = []
                for run in failed_runs:
                    failures.append({
                        "run_id": run.id,
                        "sample_id": run.sample_id,
                        "error_message": run.error_message or "无错误信息",
                        "created_at": str(run.created_at) if run.created_at else None
                    })

                results[cfg] = {
                    "failed_count": len(failures),
                    "failures": failures
                }

                if failures:
                    for f in failures:
                        self._add_issue(
                            category="运行失败",
                            severity="高",
                            config=cfg,
                            sample_id=f["sample_id"],
                            detail=f["error_message"][:100]
                        )

            return results
        finally:
            session.close()

    def check_stage_breakdown(self, config_key: str = None) -> Dict[str, Any]:
        """
        检查7：阶段数据完整性

        检查 stage_breakdown 字段是否包含该配置应有的阶段，
        以及各阶段的 token/latency 数据是否完整。
        """
        session = self.Session()
        try:
            configs = [config_key] if config_key else [
                r[0] for r in session.query(BenchmarkRun.config_key).distinct().all()
            ]

            results = {}
            for cfg in configs:
                expected_stages = CONFIG_STAGE_GROUPS.get(cfg, [])
                runs = session.query(BenchmarkRun).filter(
                    BenchmarkRun.config_key == cfg,
                    BenchmarkRun.status == "completed"
                ).all()

                no_breakdown = 0
                missing_stages_map = defaultdict(int)
                incomplete_stages = 0

                for run in runs:
                    breakdown = run.stage_breakdown
                    if not breakdown:
                        no_breakdown += 1
                        continue

                    actual_stages = set(breakdown.keys())
                    for stage in expected_stages:
                        if stage not in actual_stages:
                            missing_stages_map[stage] += 1

                    for stage_name, stage_data in breakdown.items():
                        if not isinstance(stage_data, dict):
                            continue
                        has_tokens = stage_data.get("total_tokens") is not None
                        has_latency = stage_data.get("total_latency") is not None
                        if not has_tokens and not has_latency:
                            incomplete_stages += 1

                results[cfg] = {
                    "expected_stages": expected_stages,
                    "total_runs": len(runs),
                    "no_breakdown": no_breakdown,
                    "missing_stages": dict(missing_stages_map),
                    "incomplete_stage_records": incomplete_stages
                }

                if no_breakdown > 0:
                    self._add_issue(
                        category="阶段数据缺失",
                        severity="中",
                        config=cfg,
                        detail=f"{no_breakdown}/{len(runs)} 个运行缺少 stage_breakdown"
                    )

                for stage, count in missing_stages_map.items():
                    self._add_issue(
                        category="阶段数据缺失",
                        severity="低",
                        config=cfg,
                        detail=f"阶段 {stage} 在 {count}/{len(runs)} 个运行中缺失"
                    )

            return results
        finally:
            session.close()

    def check_paper_readiness(self, config_key: str = None) -> Dict[str, Any]:
        """
        检查8：论文数据就绪度

        综合判断各配置的数据是否足以填写论文中的三张表格：
        - 表二：病历生成质量（四层评估框架）
        - 表三：消融实验结果
        - 表四：LLM 调用效率
        """
        session = self.Session()
        try:
            main_configs = ["end_to_end", "simplified", "standard", "full"]
            ablation_configs = ["full", "no_term_norm", "no_hallucination", "no_verification"]
            all_configs = list(set(main_configs + ablation_configs))

            if config_key:
                all_configs = [config_key]

            results = {}
            for cfg in all_configs:
                runs = session.query(BenchmarkRun).filter(
                    BenchmarkRun.config_key == cfg,
                    BenchmarkRun.status == "completed"
                ).all()

                unique_samples = set(r.sample_id for r in runs)

                # 检查评估数据
                eval_count = 0
                metrics_available = {m: 0 for m in EVAL_METRICS}
                for run in runs:
                    eval_record = session.query(BenchmarkEvaluation).filter(
                        BenchmarkEvaluation.run_id == run.id
                    ).first()
                    if not eval_record:
                        continue
                    eval_count += 1
                    for m in EVAL_METRICS:
                        if getattr(eval_record, m, None) is not None:
                            metrics_available[m] += 1

                # 检查效率数据
                has_elapsed = sum(1 for r in runs if r.elapsed_seconds and r.elapsed_seconds > 0)
                has_llm_calls = sum(1 for r in runs if r.llm_call_count and r.llm_call_count > 0)
                has_char_count = sum(1 for r in runs if r.char_count and r.char_count > 0)

                # 判断就绪度
                sample_ok = len(unique_samples) >= REQUIRED_SAMPLES_SCREENING
                eval_ok = eval_count >= REQUIRED_SAMPLES_SCREENING
                metrics_ok = all(
                    metrics_available[m] >= REQUIRED_SAMPLES_SCREENING
                    for m in ["recall_rate", "omission_rate", "structure_completeness",
                              "field_missing_rate", "diagnosis_match"]
                )

                results[cfg] = {
                    "unique_samples": len(unique_samples),
                    "completed_runs": len(runs),
                    "eval_count": eval_count,
                    "metrics_available": metrics_available,
                    "has_elapsed": has_elapsed,
                    "has_llm_calls": has_llm_calls,
                    "has_char_count": has_char_count,
                    "sample_sufficient": sample_ok,
                    "eval_sufficient": eval_ok,
                    "metrics_sufficient": metrics_ok,
                    "ready_for_paper": sample_ok and eval_ok and metrics_ok
                }

            return results
        finally:
            session.close()

    def fix_duplicate_runs(self, config_key: str = None) -> Dict[str, int]:
        """
        修复：清理重复运行

        对同一配置下同一 sample_id 的多次运行，只保留最近的一条，
        删除其余重复记录（级联删除关联的 stages, evaluations, llm_calls）。
        """
        session = self.Session()
        try:
            configs = [config_key] if config_key else [
                r[0] for r in session.query(BenchmarkRun.config_key).distinct().all()
            ]

            total_deleted = 0
            for cfg in configs:
                runs = session.query(BenchmarkRun).filter(
                    BenchmarkRun.config_key == cfg
                ).order_by(BenchmarkRun.created_at.desc()).all()

                seen_samples = {}
                for run in runs:
                    if run.sample_id in seen_samples:
                        # 删除较早的重复运行（级联删除关联数据）
                        logger.info(
                            f"删除重复运行: config={cfg}, sample_id={run.sample_id}, "
                            f"run_id={run.id} (保留 run_id={seen_samples[run.sample_id]})"
                        )
                        session.delete(run)
                        total_deleted += 1
                    else:
                        seen_samples[run.sample_id] = run.id

            session.commit()
            logger.info(f"共删除 {total_deleted} 条重复运行记录")
            return {"deleted_count": total_deleted}
        except Exception as e:
            session.rollback()
            logger.error(f"清理重复运行失败: {e}")
            raise
        finally:
            session.close()

    def run_all_checks(self, config_key: str = None) -> Dict[str, Any]:
        """执行全部检查"""
        self.issues = []

        logger.info("=" * 60)
        logger.info("开始 Benchmark 数据完整性检查")
        logger.info("=" * 60)

        results = {}
        results["sample_quantity"] = self.check_sample_quantity(config_key)
        results["duplicate_runs"] = self.check_duplicate_runs(config_key)
        results["missing_evaluations"] = self.check_missing_evaluations(config_key)
        results["missing_metrics"] = self.check_missing_metrics(config_key)
        results["latency_anomalies"] = self.check_latency_anomalies(config_key)
        results["failed_runs"] = self.check_failed_runs(config_key)
        results["stage_breakdown"] = self.check_stage_breakdown(config_key)
        results["paper_readiness"] = self.check_paper_readiness(config_key)

        return results

    def format_report(self, results: Dict[str, Any]) -> str:
        """将检查结果格式化为可读报告"""
        lines = []
        lines.append("=" * 70)
        lines.append("Benchmark 数据完整性检查报告")
        lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("=" * 70)

        # ---- 检查1：样本量统计 ----
        lines.append("")
        lines.append("【检查1】样本量统计")
        lines.append("-" * 50)
        sq = results.get("sample_quantity", {})
        lines.append(f"{'配置':<20} {'唯一样本':>8} {'总运行':>8} {'成功':>8} {'失败':>8} {'是否达标':>10}")
        for cfg, data in sq.items():
            ok = "达标" if data["unique_samples"] >= REQUIRED_SAMPLES_SCREENING else "不足"
            lines.append(
                f"{cfg:<20} {data['unique_samples']:>8} {data['total_runs']:>8} "
                f"{data['completed_runs']:>8} {data['failed_runs']:>8} {ok:>10}"
            )
        lines.append(f"筛选阶段要求: {REQUIRED_SAMPLES_SCREENING} 条唯一样本")
        lines.append(f"正式评测要求: {REQUIRED_SAMPLES_FORMAL} 条唯一样本")

        # ---- 检查2：重复运行检测 ----
        lines.append("")
        lines.append("【检查2】重复运行检测")
        lines.append("-" * 50)
        dr = results.get("duplicate_runs", {})
        for cfg, data in dr.items():
            if data["duplicate_samples"] > 0:
                lines.append(f"配置 {cfg}: {data['duplicate_samples']} 个样本有重复运行")
                for sid, run_list in data["duplicates"].items():
                    lines.append(f"  sample_id={sid}: 重复 {len(run_list)} 次")
                    for r in run_list:
                        lines.append(
                            f"    run_id={r['run_id']}, status={r['status']}, "
                            f"elapsed={r['elapsed_seconds']}s"
                        )
            else:
                lines.append(f"配置 {cfg}: 无重复运行")

        # ---- 检查3：评估数据缺失 ----
        lines.append("")
        lines.append("【检查3】评估数据缺失（已完成运行但无评估记录）")
        lines.append("-" * 50)
        me = results.get("missing_evaluations", {})
        for cfg, data in me.items():
            if data["missing_evaluations"] > 0:
                lines.append(
                    f"配置 {cfg}: {data['missing_evaluations']}/{data['completed_runs']} "
                    f"个已完成运行缺少评估记录"
                )
                for m in data["missing_details"][:10]:
                    lines.append(f"  run_id={m['run_id']}, sample_id={m['sample_id']}")
                if len(data["missing_details"]) > 10:
                    lines.append(f"  ... 还有 {len(data['missing_details']) - 10} 条")
            else:
                lines.append(f"配置 {cfg}: 无缺失")

        # ---- 检查4：评估指标缺失 ----
        lines.append("")
        lines.append("【检查4】评估指标缺失（评估记录中字段为 NULL）")
        lines.append("-" * 50)
        mm = results.get("missing_metrics", {})
        for cfg, data in mm.items():
            lines.append(f"配置 {cfg}:")
            # 评估指标
            for metric, stats in data.get("eval_metrics", {}).items():
                if stats["total"] > 0:
                    null_rate = stats["null"] / stats["total"]
                    status = "完整" if null_rate == 0 else f"缺失 {null_rate:.0%}"
                    lines.append(f"  {metric}: {stats['total'] - stats['null']}/{stats['total']} {status}")
            # 运行指标
            for metric, stats in data.get("run_metrics", {}).items():
                if stats["total"] > 0:
                    ok_rate = 1 - stats["null_or_zero"] / stats["total"]
                    status = "完整" if ok_rate == 1 else f"缺失 {(1-ok_rate):.0%}"
                    lines.append(f"  {metric}: {stats['total'] - stats['null_or_zero']}/{stats['total']} {status}")

        # ---- 检查5：延迟异常 ----
        lines.append("")
        lines.append("【检查5】延迟异常检测")
        lines.append("-" * 50)
        la = results.get("latency_anomalies", {})
        for cfg, data in la.items():
            lines.append(f"配置 {cfg}: 阈值={data['threshold']}s, 异常数={data['anomaly_count']}")
            for a in data["anomalies"]:
                lines.append(
                    f"  sample_id={a['sample_id']}, 耗时={a['elapsed_seconds']:.0f}s, "
                    f"最慢阶段={a['slowest_stage']}({a['slowest_stage_latency']:.0f}s)"
                )

        # ---- 检查6：失败运行 ----
        lines.append("")
        lines.append("【检查6】失败运行统计")
        lines.append("-" * 50)
        fr = results.get("failed_runs", {})
        for cfg, data in fr.items():
            if data["failed_count"] > 0:
                lines.append(f"配置 {cfg}: {data['failed_count']} 个失败运行")
                for f in data["failures"]:
                    lines.append(f"  sample_id={f['sample_id']}: {f['error_message'][:80]}")
            else:
                lines.append(f"配置 {cfg}: 无失败运行")

        # ---- 检查7：阶段数据完整性 ----
        lines.append("")
        lines.append("【检查7】阶段数据完整性")
        lines.append("-" * 50)
        sb = results.get("stage_breakdown", {})
        for cfg, data in sb.items():
            lines.append(f"配置 {cfg}:")
            lines.append(f"  期望阶段: {', '.join(data['expected_stages'])}")
            lines.append(f"  缺少 stage_breakdown: {data['no_breakdown']}/{data['total_runs']}")
            if data["missing_stages"]:
                for stage, count in data["missing_stages"].items():
                    lines.append(f"  缺失阶段 {stage}: {count}/{data['total_runs']} 个运行")
            lines.append(f"  不完整阶段记录: {data['incomplete_stage_records']}")

        # ---- 检查8：论文数据就绪度 ----
        lines.append("")
        lines.append("【检查8】论文数据就绪度")
        lines.append("-" * 50)
        pr = results.get("paper_readiness", {})
        lines.append(f"{'配置':<20} {'唯一样本':>8} {'评估数':>8} {'样本达标':>8} {'评估达标':>8} {'指标达标':>8} {'可填论文':>8}")
        for cfg, data in pr.items():
            lines.append(
                f"{cfg:<20} {data['unique_samples']:>8} {data['eval_count']:>8} "
                f"{'是' if data['sample_sufficient'] else '否':>8} "
                f"{'是' if data['eval_sufficient'] else '否':>8} "
                f"{'是' if data['metrics_sufficient'] else '否':>8} "
                f"{'是' if data['ready_for_paper'] else '否':>8}"
            )

        # ---- 问题汇总 ----
        lines.append("")
        lines.append("=" * 70)
        lines.append("问题汇总")
        lines.append("=" * 70)

        if not self.issues:
            lines.append("未发现问题，数据完整。")
        else:
            # 按严重程度分组
            by_severity = defaultdict(list)
            for issue in self.issues:
                by_severity[issue["severity"]].append(issue)

            for severity in ["高", "中", "低"]:
                issues = by_severity.get(severity, [])
                if issues:
                    lines.append(f"\n--- {severity}优先级 ({len(issues)} 条) ---")
                    for i, issue in enumerate(issues, 1):
                        lines.append(
                            f"  {i}. [{issue['category']}] 配置={issue['config']}"
                            + (f", sample_id={issue['sample_id']}" if issue["sample_id"] else "")
                            + f": {issue['detail']}"
                        )

        return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Benchmark 数据库完整性检查",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python scripts/check_benchmark_data.py                     # 执行全部检查
  python scripts/check_benchmark_data.py --config full       # 只检查指定配置
  python scripts/check_benchmark_data.py --fix-duplicates    # 清理重复运行
  python scripts/check_benchmark_data.py --latency-threshold 2000  # 自定义延迟阈值
  python scripts/check_benchmark_data.py --output report.json     # 保存JSON报告
        """
    )
    parser.add_argument("--config", type=str, help="只检查指定配置")
    parser.add_argument("--fix-duplicates", action="store_true",
                        help="清理重复运行（保留最近一条，删除其余）")
    parser.add_argument("--latency-threshold", type=float, default=2000,
                        help="延迟异常阈值（秒），默认2000")
    parser.add_argument("--output", type=str, help="保存JSON格式报告到文件")

    args = parser.parse_args()

    checker = BenchmarkDataChecker(latency_threshold=args.latency_threshold)

    if args.fix_duplicates:
        logger.info("执行重复运行清理...")
        result = checker.fix_duplicate_runs(args.config)
        print(f"已删除 {result['deleted_count']} 条重复运行记录")
        # 清理后重新检查
        logger.info("清理完成，重新执行检查...")

    results = checker.run_all_checks(args.config)

    # 打印报告
    report = checker.format_report(results)
    print(report)

    # 保存JSON报告
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # 将 results 中不可序列化的部分转换
        serializable = json.dumps(results, indent=2, ensure_ascii=False, default=str)
        output_path.write_text(serializable, encoding="utf-8")
        logger.info(f"JSON报告已保存到: {output_path}")


if __name__ == "__main__":
    main()
