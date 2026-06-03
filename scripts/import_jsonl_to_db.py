"""
从 JSONL 结果文件导入数据到 Benchmark 数据库

用法:
  python scripts/import_jsonl_to_db.py --dir data/experiments/results/phase1
  python scripts/import_jsonl_to_db.py --file data/experiments/results/phase1/results_full_20260602_000457.jsonl
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.benchmark_db import (
    init_benchmark_db, get_benchmark_session, close_benchmark_session,
    BENCHMARK_DATABASE_URL
)
from backend.models.benchmark import (
    BenchmarkRun, BenchmarkStage, BenchmarkEvaluation,
    BenchmarkLLMCall, BenchmarkSummary
)

LOG_DIR = Path("data/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / "import_jsonl_to_db.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class JSONLImporter:
    def __init__(self):
        init_benchmark_db()
        logger.info(f"Benchmark数据库初始化完成: {BENCHMARK_DATABASE_URL}")
    
    def _is_abnormal_entry(self, entry: Dict[str, Any]) -> bool:
        quality_metrics = entry.get("quality_metrics", {})
        field_missing_rate = quality_metrics.get("field_missing_rate", 0)
        
        emr_result = entry.get("emr_result", {})
        has_content = False
        if emr_result:
            for section in ["subjective", "objective", "assessment", "plan"]:
                sec = emr_result.get(section, {})
                if isinstance(sec, dict):
                    for field, val in sec.items():
                        if isinstance(val, dict):
                            if val.get("value") and val.get("value") != "unknown" and val.get("value") != "":
                                has_content = True
                                break
                        elif isinstance(val, str) and val.strip() and val != "unknown":
                            has_content = True
                            break
                if has_content:
                    break
        
        if field_missing_rate >= 0.5 and not has_content:
            return True
        
        if not emr_result or not has_content:
            return True
        
        return False
    
    def import_single_entry(self, benchmark_db, entry: Dict[str, Any]) -> Optional[BenchmarkRun]:
        sample_id = entry.get("sample_id")
        config_key = entry.get("config_key")
        
        if self._is_abnormal_entry(entry):
            logger.warning(f"SKIP - 异常数据: sample_id={sample_id}, config_key={config_key}, field_missing_rate={entry.get('quality_metrics', {}).get('field_missing_rate')}")
            return None
        
        existing = benchmark_db.query(BenchmarkRun).filter(
            BenchmarkRun.sample_id == sample_id,
            BenchmarkRun.config_key == config_key,
            BenchmarkRun.status == "completed"
        ).order_by(BenchmarkRun.created_at.desc()).first()
        
        if existing:
            logger.info(f"SKIP - 已存在: sample_id={sample_id}, config_key={config_key}")
            return existing
        
        run = BenchmarkRun(
            sample_id=sample_id,
            config_key=config_key,
            visit_id=entry.get("visit_id"),
            status=entry.get("status", "completed"),
            emr_result=entry.get("emr_result"),
            hallucination_result=entry.get("hallucination_result"),
            verification_issues=entry.get("verification_issues"),
            elapsed_seconds=entry.get("elapsed_seconds"),
            llm_call_count=entry.get("llm_call_count", 0),
            char_count=entry.get("char_count", 0),
            error_message=entry.get("error_message")
        )
        benchmark_db.add(run)
        benchmark_db.commit()
        benchmark_db.refresh(run)
        logger.info(f"IMPORT - BenchmarkRun: id={run.id}, sample_id={sample_id}, config_key={config_key}")
        
        llm_eval = entry.get("llm_evaluation", {})
        quality_metrics = entry.get("quality_metrics", {})
        hallucination = entry.get("hallucination", {})
        
        consistency = llm_eval.get("consistency")
        completeness = llm_eval.get("completeness")
        quality = llm_eval.get("quality")
        safety = llm_eval.get("safety")
        
        support_rate = None
        hallucination_rate = None
        recall_rate = None
        omission_rate = None
        
        if consistency and consistency.get("summary"):
            support_rate = consistency["summary"].get("support_rate")
            hallucination_rate = 1 - support_rate if support_rate else None
        
        if completeness and completeness.get("summary"):
            recall_rate = completeness["summary"].get("recall_rate")
            omission_rate = completeness["summary"].get("omission_rate")
        
        if hallucination:
            support_rate = hallucination.get("support_rate", support_rate)
            hallucination_rate = hallucination.get("severity") == "low" and support_rate == 1.0 and 0.0 or hallucination_rate
        
        diagnosis_match = quality_metrics.get("diagnosis_match")
        if diagnosis_match is not None:
            diagnosis_match = bool(diagnosis_match)
        
        evaluation = BenchmarkEvaluation(
            run_id=run.id,
            consistency_result=consistency,
            completeness_result=completeness,
            quality_result=quality,
            safety_result=safety,
            support_rate=support_rate,
            hallucination_rate=hallucination_rate,
            recall_rate=recall_rate,
            omission_rate=omission_rate,
            structure_completeness=quality_metrics.get("structure_completeness"),
            field_missing_rate=quality_metrics.get("field_missing_rate"),
            diagnosis_match=diagnosis_match,
            overall_score=None,
            error_message=None
        )
        benchmark_db.add(evaluation)
        benchmark_db.commit()
        benchmark_db.refresh(evaluation)
        logger.info(f"IMPORT - BenchmarkEvaluation: id={evaluation.id}, run_id={run.id}")
        
        return run
    
    def import_jsonl_file(self, jsonl_path: str) -> int:
        benchmark_db = get_benchmark_session()
        count = 0
        skip_count = 0
        
        try:
            with open(jsonl_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if not line.strip():
                        continue
                    
                    entry = json.loads(line)
                    result = self.import_single_entry(benchmark_db, entry)
                    if result:
                        count += 1
                    else:
                        skip_count += 1
            
            logger.info(f"导入完成: {jsonl_path}, 导入 {count} 条, 跳过异常 {skip_count} 条")
            return count
        
        except Exception as e:
            logger.error(f"导入失败: {jsonl_path}, error={e}")
            benchmark_db.rollback()
            return 0
        
        finally:
            close_benchmark_session(benchmark_db)
    
    def import_directory(self, dir_path: str, pattern: str = "results_*.jsonl") -> int:
        total_count = 0
        dir_path = Path(dir_path)
        
        jsonl_files = list(dir_path.glob(pattern))
        logger.info(f"发现 {len(jsonl_files)} 个 JSONL 文件")
        
        for jsonl_file in sorted(jsonl_files):
            count = self.import_jsonl_file(str(jsonl_file))
            total_count += count
        
        logger.info(f"目录导入完成: {dir_path}, 共 {total_count} 条记录")
        return total_count


def main():
    parser = argparse.ArgumentParser(description="从 JSONL 文件导入数据到 Benchmark 数据库")
    parser.add_argument("--dir", type=str, help="导入目录下所有 JSONL 文件")
    parser.add_argument("--file", type=str, help="导入单个 JSONL 文件")
    parser.add_argument("--pattern", type=str, default="results_*.jsonl", help="文件匹配模式")
    
    args = parser.parse_args()
    
    importer = JSONLImporter()
    
    if args.dir:
        importer.import_directory(args.dir, args.pattern)
    elif args.file:
        importer.import_jsonl_file(args.file)
    else:
        print("请指定 --dir 或 --file 参数")
        parser.print_help()


if __name__ == "__main__":
    main()