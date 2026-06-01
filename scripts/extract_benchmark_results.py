"""
从 Benchmark 数据库提取量化指标并计算实验结果

用法:
  python scripts/extract_benchmark_results.py                    # 输出所有配置的汇总结果
  python scripts/extract_benchmark_results.py --config full      # 输出指定配置的详细结果
  python scripts/extract_benchmark_results.py --format table/paper     # 输出表格格式（用于论文）
  python scripts/extract_benchmark_results.py --output results.json  # 输出到JSON文件
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional
from collections import defaultdict
import statistics

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, func
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
        logging.FileHandler(LOG_DIR / "extract_benchmark_results.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class BenchmarkResultExtractor:
    def __init__(self, db_url: str = None):
        if db_url is None:
            db_url = BENCHMARK_DATABASE_URL
        self.engine = create_engine(db_url)
        self.Session = sessionmaker(bind=self.engine)
        logger.info(f"连接数据库: {db_url}")

    def get_all_configs(self) -> List[str]:
        session = self.Session()
        try:
            configs = session.query(BenchmarkRun.config_key).distinct().all()
            return [c[0] for c in configs]
        finally:
            session.close()

    def get_runs_by_config(self, config_key: str) -> List[BenchmarkRun]:
        session = self.Session()
        try:
            runs = session.query(BenchmarkRun).filter(
                BenchmarkRun.config_key == config_key
            ).order_by(BenchmarkRun.created_at).all()
            return runs
        finally:
            session.close()

    def get_evaluation_by_run(self, run_id: int) -> Optional[BenchmarkEvaluation]:
        session = self.Session()
        try:
            eval = session.query(BenchmarkEvaluation).filter(
                BenchmarkEvaluation.run_id == run_id
            ).first()
            return eval
        finally:
            session.close()

    def get_llm_calls_by_run(self, run_id: int) -> List[BenchmarkLLMCall]:
        session = self.Session()
        try:
            calls = session.query(BenchmarkLLMCall).filter(
                BenchmarkLLMCall.run_id == run_id
            ).all()
            return calls
        finally:
            session.close()

    def get_stages_by_run(self, run_id: int) -> List[BenchmarkStage]:
        session = self.Session()
        try:
            stages = session.query(BenchmarkStage).filter(
                BenchmarkStage.run_id == run_id
            ).order_by(BenchmarkStage.stage_index).all()
            return stages
        finally:
            session.close()

    def compute_config_summary(self, config_key: str) -> Dict[str, Any]:
        runs = self.get_runs_by_config(config_key)
        if not runs:
            logger.warning(f"配置 {config_key} 无运行记录")
            return {"config_key": config_key, "total": 0, "error": "no runs"}

        success_runs = [r for r in runs if r.status == "completed"]
        failed_runs = [r for r in runs if r.status == "failed"]

        metrics = {
            "config_key": config_key,
            "total_samples": len(runs),
            "success_samples": len(success_runs),
            "failed_samples": len(failed_runs),
        }

        if not success_runs:
            return metrics

        elapsed_list = [r.elapsed_seconds for r in success_runs if r.elapsed_seconds]
        llm_call_list = [r.llm_call_count for r in success_runs]
        char_count_list = [r.char_count for r in success_runs]

        metrics["avg_elapsed_seconds"] = statistics.mean(elapsed_list) if elapsed_list else None
        metrics["std_elapsed_seconds"] = statistics.stdev(elapsed_list) if len(elapsed_list) > 1 else None
        metrics["min_elapsed_seconds"] = min(elapsed_list) if elapsed_list else None
        metrics["max_elapsed_seconds"] = max(elapsed_list) if elapsed_list else None

        metrics["avg_llm_call_count"] = statistics.mean(llm_call_list) if llm_call_list else None
        metrics["total_llm_calls"] = sum(llm_call_list)

        metrics["avg_char_count"] = statistics.mean(char_count_list) if char_count_list else None
        metrics["total_char_count"] = sum(char_count_list)

        support_rates = []
        hallucination_rates = []
        recall_rates = []
        omission_rates = []
        structure_completenesses = []
        field_missing_rates = []
        diagnosis_matches = []

        for run in success_runs:
            eval = self.get_evaluation_by_run(run.id)
            if eval:
                if eval.support_rate is not None:
                    support_rates.append(eval.support_rate)
                if eval.hallucination_rate is not None:
                    hallucination_rates.append(eval.hallucination_rate)
                if eval.recall_rate is not None:
                    recall_rates.append(eval.recall_rate)
                if eval.omission_rate is not None:
                    omission_rates.append(eval.omission_rate)
                if eval.structure_completeness is not None:
                    structure_completenesses.append(eval.structure_completeness)
                if eval.field_missing_rate is not None:
                    field_missing_rates.append(eval.field_missing_rate)
                if eval.diagnosis_match is not None:
                    diagnosis_matches.append(1.0 if eval.diagnosis_match else 0.0)

        if support_rates:
            metrics["avg_support_rate"] = statistics.mean(support_rates)
            metrics["std_support_rate"] = statistics.stdev(support_rates) if len(support_rates) > 1 else None
        else:
            metrics["avg_support_rate"] = None
            metrics["std_support_rate"] = None

        if hallucination_rates:
            metrics["avg_hallucination_rate"] = statistics.mean(hallucination_rates)
        else:
            metrics["avg_hallucination_rate"] = None

        if recall_rates:
            metrics["avg_recall_rate"] = statistics.mean(recall_rates)
            metrics["std_recall_rate"] = statistics.stdev(recall_rates) if len(recall_rates) > 1 else None
        else:
            metrics["avg_recall_rate"] = None
            metrics["std_recall_rate"] = None

        if omission_rates:
            metrics["avg_omission_rate"] = statistics.mean(omission_rates)
        else:
            metrics["avg_omission_rate"] = None

        if structure_completenesses:
            metrics["avg_structure_completeness"] = statistics.mean(structure_completenesses)
        else:
            metrics["avg_structure_completeness"] = None

        if field_missing_rates:
            metrics["avg_field_missing_rate"] = statistics.mean(field_missing_rates)
        else:
            metrics["avg_field_missing_rate"] = None

        if diagnosis_matches:
            metrics["avg_diagnosis_match"] = statistics.mean(diagnosis_matches)
            metrics["diagnosis_match_count"] = int(sum(diagnosis_matches))
        else:
            metrics["avg_diagnosis_match"] = None
            metrics["diagnosis_match_count"] = 0

        sample_tokens = {}
        total_tokens_list = []
        prompt_tokens_list = []
        completion_tokens_list = []

        for run in success_runs:
            llm_calls = self.get_llm_calls_by_run(run.id)
            run_total_tokens = 0
            has_token_data = False
            for call in llm_calls:
                if call.total_tokens is not None:
                    total_tokens_list.append(call.total_tokens)
                    run_total_tokens += call.total_tokens
                    has_token_data = True
                if call.prompt_tokens is not None:
                    prompt_tokens_list.append(call.prompt_tokens)
                if call.completion_tokens is not None:
                    completion_tokens_list.append(call.completion_tokens)
            if has_token_data:
                sample_tokens[run.id] = run_total_tokens

        if total_tokens_list:
            metrics["total_tokens"] = sum(total_tokens_list)
            metrics["avg_tokens_per_call"] = statistics.mean(total_tokens_list)
            if sample_tokens:
                metrics["avg_tokens_per_sample"] = statistics.mean(list(sample_tokens.values()))
                metrics["samples_with_tokens"] = len(sample_tokens)
            else:
                metrics["avg_tokens_per_sample"] = None
                metrics["samples_with_tokens"] = 0
        else:
            metrics["total_tokens"] = None
            metrics["avg_tokens_per_call"] = None
            metrics["avg_tokens_per_sample"] = None
            metrics["samples_with_tokens"] = 0

        if prompt_tokens_list:
            metrics["total_prompt_tokens"] = sum(prompt_tokens_list)
            metrics["avg_prompt_tokens"] = statistics.mean(prompt_tokens_list)
        else:
            metrics["total_prompt_tokens"] = None
            metrics["avg_prompt_tokens"] = None

        if completion_tokens_list:
            metrics["total_completion_tokens"] = sum(completion_tokens_list)
            metrics["avg_completion_tokens"] = statistics.mean(completion_tokens_list)
        else:
            metrics["total_completion_tokens"] = None
            metrics["avg_completion_tokens"] = None

        return metrics

    def get_sample_details(self, config_key: str) -> List[Dict[str, Any]]:
        runs = self.get_runs_by_config(config_key)
        details = []

        for run in runs:
            detail = {
                "sample_id": run.sample_id,
                "config_key": run.config_key,
                "visit_id": run.visit_id,
                "status": run.status,
                "elapsed_seconds": run.elapsed_seconds,
                "llm_call_count": run.llm_call_count,
                "char_count": run.char_count,
                "error_message": run.error_message,
            }

            eval = self.get_evaluation_by_run(run.id)
            if eval:
                detail["support_rate"] = eval.support_rate
                detail["hallucination_rate"] = eval.hallucination_rate
                detail["recall_rate"] = eval.recall_rate
                detail["omission_rate"] = eval.omission_rate
                detail["structure_completeness"] = eval.structure_completeness
                detail["field_missing_rate"] = eval.field_missing_rate
                detail["diagnosis_match"] = eval.diagnosis_match
                detail["consistency_result"] = eval.consistency_result
                detail["completeness_result"] = eval.completeness_result
                detail["quality_result"] = eval.quality_result
                detail["safety_result"] = eval.safety_result
            else:
                detail["support_rate"] = None
                detail["hallucination_rate"] = None
                detail["recall_rate"] = None
                detail["omission_rate"] = None
                detail["structure_completeness"] = None
                detail["field_missing_rate"] = None
                detail["diagnosis_match"] = None

            details.append(detail)

        return details

    def format_table_row(self, metrics: Dict[str, Any], config_name: str) -> str:
        def fmt(val, suffix="", precision=1):
            if val is None:
                return "未检测"
            return f"{val:.{precision}f}{suffix}"

        row = f"| {config_name} | "
        row += fmt(metrics.get("avg_support_rate", None), "%") + " | "
        row += fmt(metrics.get("avg_recall_rate", None), "%") + " | "
        row += fmt(metrics.get("avg_hallucination_rate", None), "%") + " | "
        row += fmt(metrics.get("avg_elapsed_seconds", None), "s") + " | "
        row += fmt(metrics.get("avg_llm_call_count", None)) + " | "
        row += fmt(metrics.get("avg_char_count", None)) + " |"
        return row

    def format_paper_table(self, results: Dict[str, Dict[str, Any]]) -> str:
        config_names = {
            "end_to_end": "端到端基线",
            "simplified": "简化管线",
            "standard": "标准管线",
            "full": "完整管线",
        }

        table = "\n## 病历生成质量（四层评估框架）\n\n"
        table += "| 评估层 | 指标 | 端到端管线 | 简化管线 | 标准管线 | 完整管线 |\n"
        table += "| :--- | :--- | ---: | ---: | ---: | ---: |\n"

        def fmt(val, precision=1, default="未检测"):
            if val is None:
                return default
            return f"{val*100:.{precision}f}"

        def get_val(config, key):
            return results.get(config, {}).get(key)

        table += f"| 一致性 | 事实支持率 (%) | {fmt(get_val('end_to_end', 'avg_support_rate'))} | {fmt(get_val('simplified', 'avg_support_rate'))} | {fmt(get_val('standard', 'avg_support_rate'))} | {fmt(get_val('full', 'avg_support_rate'))} |\n"
        table += f"| 一致性 | 幻觉率 (%) | {fmt(get_val('end_to_end', 'avg_hallucination_rate'))} | {fmt(get_val('simplified', 'avg_hallucination_rate'))} | {fmt(get_val('standard', 'avg_hallucination_rate'))} | {fmt(get_val('full', 'avg_hallucination_rate'))} |\n"
        table += f"| 完整性 | 关键召回率 (%) | {fmt(get_val('end_to_end', 'avg_recall_rate'))} | {fmt(get_val('simplified', 'avg_recall_rate'))} | {fmt(get_val('standard', 'avg_recall_rate'))} | {fmt(get_val('full', 'avg_recall_rate'))} |\n"
        table += f"| 完整性 | 遗漏率 (%) | {fmt(get_val('end_to_end', 'avg_omission_rate'))} | {fmt(get_val('simplified', 'avg_omission_rate'))} | {fmt(get_val('standard', 'avg_omission_rate'))} | {fmt(get_val('full', 'avg_omission_rate'))} |\n"
        table += f"| 文档质量 | 结构完整率 (%) | {fmt(get_val('end_to_end', 'avg_structure_completeness'))} | {fmt(get_val('simplified', 'avg_structure_completeness'))} | {fmt(get_val('standard', 'avg_structure_completeness'))} | {fmt(get_val('full', 'avg_structure_completeness'))} |\n"
        table += f"| 文档质量 | 字段缺失率 (%) | {fmt(get_val('end_to_end', 'avg_field_missing_rate'))} | {fmt(get_val('simplified', 'avg_field_missing_rate'))} | {fmt(get_val('standard', 'avg_field_missing_rate'))} | {fmt(get_val('full', 'avg_field_missing_rate'))} |\n"
        table += f"| 安全风险 | 诊断一致性 (%) | {fmt(get_val('end_to_end', 'avg_diagnosis_match'))} | {fmt(get_val('simplified', 'avg_diagnosis_match'))} | {fmt(get_val('standard', 'avg_diagnosis_match'))} | {fmt(get_val('full', 'avg_diagnosis_match'))} |\n"

        table += "\n## LLM 调用效率\n\n"
        table += "| 配置 | 总 LLM 调用次数 | 平均延迟 (s) | 总字符消耗 | 平均 Token 消耗 | 总 Token 消耗 |\n"
        table += "| :--- | ---: | ---: | ---: | ---: | ---: |\n"

        def fmt_int(val, default="—"):
            if val is None:
                return default
            return f"{int(val)}"

        def fmt_avg(val, precision=1, default="—"):
            if val is None:
                return default
            return f"{val:.{precision}f}"

        for config_key, name in config_names.items():
            m = results.get(config_key, {})
            table += f"| {name} | {fmt_avg(m.get('avg_llm_call_count'))} | {fmt_avg(m.get('avg_elapsed_seconds'))} | {fmt_int(m.get('avg_char_count'))} | {fmt_int(m.get('avg_tokens_per_sample'))} | {fmt_int(m.get('total_tokens'))} |\n"

        return table

    def format_ablation_table(self, results: Dict[str, Dict[str, Any]]) -> str:
        ablation_names = {
            "full": "完整管线（六阶段）",
            "no_term_norm": "− 术语规范化",
            "no_hallucination": "− 幻觉检查",
            "no_verification": "− 后置核查",
            "no_field_revision": "− 字段修订",
        }

        def fmt(val, precision=1, default="未检测"):
            if val is None:
                return default
            return f"{val*100:.{precision}f}"

        def get_val(config, key):
            return results.get(config, {}).get(key)

        table = "\n## 消融实验结果\n\n"
        table += "| 配置 | 事实支持率 (%) | 关键召回率 (%) | 幻觉率 (%) |\n"
        table += "| :--- | ---: | ---: | ---: |\n"

        for config_key, name in ablation_names.items():
            m = results.get(config_key, {})
            if m and m.get("total_samples", 0) > 0:
                table += f"| {name} | {fmt(get_val(config_key, 'avg_support_rate'))} | {fmt(get_val(config_key, 'avg_recall_rate'))} | {fmt(get_val(config_key, 'avg_hallucination_rate'))} |\n"

        return table

    def export_all_results(self) -> Dict[str, Dict[str, Any]]:
        configs = self.get_all_configs()
        results = {}

        for config in configs:
            logger.info(f"提取配置: {config}")
            results[config] = self.compute_config_summary(config)

        return results


def main():
    parser = argparse.ArgumentParser(description="从 Benchmark 数据库提取量化指标")
    parser.add_argument("--config", type=str, help="指定配置名称（如 full, end_to_end）")
    parser.add_argument("--format", type=str, choices=["json", "table", "paper"], default="json",
                        help="输出格式：json（默认）、table（单行表格）、paper（论文表格）")
    parser.add_argument("--output", type=str, help="输出文件路径（JSON格式）")
    parser.add_argument("--details", action="store_true", help="输出样本级详情")
    parser.add_argument("--include-ablation", action="store_true", help="包含消融实验结果")

    args = parser.parse_args()

    extractor = BenchmarkResultExtractor()

    if args.config:
        if args.details:
            details = extractor.get_sample_details(args.config)
            if args.format == "json":
                output = json.dumps(details, indent=2, ensure_ascii=False)
            else:
                output = "\n".join([
                    f"{d['sample_id']}: support={d.get('support_rate')}, recall={d.get('recall_rate')}, elapsed={d.get('elapsed_seconds')}s"
                    for d in details
                ])
        else:
            metrics = extractor.compute_config_summary(args.config)
            if args.format == "json":
                output = json.dumps(metrics, indent=2, ensure_ascii=False)
            elif args.format == "table":
                config_names = {
                    "end_to_end": "端到端基线",
                    "simplified": "简化管线",
                    "standard": "标准管线",
                    "full": "完整管线",
                }
                output = extractor.format_table_row(metrics, config_names.get(args.config, args.config))
            else:
                output = json.dumps(metrics, indent=2, ensure_ascii=False)
    else:
        results = extractor.export_all_results()

        if args.include_ablation:
            ablation_configs = ["full", "no_term_norm", "no_hallucination", "no_verification", "no_field_revision"]
            for config in ablation_configs:
                if config not in results:
                    try:
                        results[config] = extractor.compute_config_summary(config)
                    except Exception as e:
                        logger.warning(f"消融配置 {config} 提取失败: {e}")

        if args.format == "paper":
            output = extractor.format_paper_table(results)
            if args.include_ablation:
                output += extractor.format_ablation_table(results)
        else:
            output = json.dumps(results, indent=2, ensure_ascii=False)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output, encoding="utf-8")
        logger.info(f"结果已保存到: {output_path}")
    else:
        print(output)


if __name__ == "__main__":
    main()