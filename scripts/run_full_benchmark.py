"""
全量化指标一键评估脚本

单次运行产出所有量化指标，Pipeline 结果和评估结果持久化到独立数据库。

用法:
  python scripts/run_full_benchmark.py --config full --samples data/experiments/test_samples.json
  python scripts/run_full_benchmark.py --config all --limit 10
  python scripts/run_full_benchmark.py --config full --re-evaluate
"""

import json
import time
import argparse
import sys
import uuid
import traceback
import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict
import statistics

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.config import settings
from backend.models.visit import Visit
from backend.models.transcript import TranscriptTurn
from backend.models.benchmark import (
    BenchmarkRun, BenchmarkStage, BenchmarkEvaluation,
    BenchmarkLLMCall, BenchmarkSummary, BenchmarkBase
)
from backend.benchmark_db import (
    init_benchmark_db, get_benchmark_session, close_benchmark_session,
    BENCHMARK_DATABASE_URL
)
from backend.services.pipeline.orchestrator import PipelineOrchestrator
from backend.services.llm.llm_service import LLMService
from backend.services.evaluation.benchmark_evaluator import BenchmarkEvaluator, LoggedCompletenessEvaluator
from backend.database import get_db

LOG_DIR = Path("data/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / "run_full_benchmark.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


EXPERIMENT_CONFIGS = {
    "end_to_end": {
        "name": "端到端基线", "code": "A",
        "skip_cleaning": True, "skip_hallucination_check": True,
        "stop_after_draft": True, "skip_verification": False,
        "skip_term_norm": True, "skip_field_revision": True
    },
    "simplified": {
        "name": "简化管线", "code": "B",
        "skip_cleaning": True, "skip_hallucination_check": True,
        "stop_after_draft": False, "skip_verification": True,
        "skip_term_norm": False, "skip_field_revision": True
    },
    "standard": {
        "name": "标准管线", "code": "C",
        "skip_cleaning": False, "skip_hallucination_check": True,
        "stop_after_draft": False, "skip_verification": False,
        "skip_term_norm": False, "skip_field_revision": False
    },
    "full": {
        "name": "完整管线", "code": "D",
        "skip_cleaning": False, "skip_hallucination_check": False,
        "stop_after_draft": False, "skip_verification": False,
        "skip_term_norm": False, "skip_field_revision": False
    }
}

ABLATION_CONFIGS = {
    "full":               {"name": "完整管线（六阶段）",   "skip_cleaning": False, "stop_after_draft": False, "skip_term_norm": False, "skip_hallucination_check": False, "skip_verification": False, "skip_field_revision": False},
    "no_term_norm":       {"name": "-术语规范化",         "skip_cleaning": False, "stop_after_draft": False, "skip_term_norm": True,  "skip_hallucination_check": False, "skip_verification": False, "skip_field_revision": False},
    "no_hallucination":   {"name": "-幻觉检查",           "skip_cleaning": False, "stop_after_draft": False, "skip_term_norm": False, "skip_hallucination_check": True,  "skip_verification": False, "skip_field_revision": False},
    "no_verification":    {"name": "-后置核查",           "skip_cleaning": False, "stop_after_draft": False, "skip_term_norm": False, "skip_hallucination_check": False, "skip_verification": True,  "skip_field_revision": False},
    "no_field_revision":  {"name": "-字段修订",           "skip_cleaning": False, "stop_after_draft": False, "skip_term_norm": False, "skip_hallucination_check": False, "skip_verification": False, "skip_field_revision": True}
}

SOAP_SECTIONS = ["subjective", "objective", "assessment", "plan"]
REQUIRED_FIELDS = {
    "subjective": ["chief_complaint", "history_present_illness"],
    "objective": [],
    "assessment": ["diagnosis"],
    "plan": ["treatment"],
}


class FullBenchmarkRunner:
    def __init__(
        self,
        samples_file: str,
        output_dir: str,
        request_interval: float = 2.0,
        re_evaluate: bool = False
    ):
        self.samples = self._load_samples(samples_file)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.request_interval = request_interval
        self.re_evaluate = re_evaluate

        init_benchmark_db()
        logger.info(f"Benchmark数据库初始化完成: {BENCHMARK_DATABASE_URL}")

    def _normalize_text(self, text: str) -> str:
        if not text:
            return ""
        text = text.strip()
        text = re.sub(r'[，。、；：！？\s]', '', text)
        return text.lower()

    def _check_diagnosis_match(self, predicted: str, ground_truth: str) -> bool:
        pred_norm = self._normalize_text(predicted)
        truth_norm = self._normalize_text(ground_truth)
        
        if not pred_norm or not truth_norm:
            return False
        
        if pred_norm == truth_norm:
            return True
        
        if pred_norm in truth_norm or truth_norm in pred_norm:
            return True
        
        common_chars = set(pred_norm) & set(truth_norm)
        if len(common_chars) >= min(len(pred_norm), len(truth_norm)) * 0.5:
            return True
        
        return False

    def _load_samples(self, path: str) -> List[Dict[str, Any]]:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get("samples", [])

    def _build_main_db_session(self):
        engine = create_engine(settings.DATABASE_URL)
        SessionLocal = sessionmaker(bind=engine)
        return SessionLocal()

    def _create_visit_and_turns(self, db, sample: Dict[str, Any]) -> Tuple[str, int]:
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

    def _compute_quality_metrics(self, emr: Optional[Dict], sample_diagnosis: str) -> Optional[Dict]:
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
                for field in fields:
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
                    diagnosis_match = self._check_diagnosis_match(diag_val, sample_diagnosis)

        return {
            "structure_completeness": round(structure_completeness, 4),
            "present_sections": present_sections,
            "total_sections": len(SOAP_SECTIONS),
            "field_missing_rate": round(field_missing_rate, 4),
            "missing_required_fields": missing_required,
            "total_required_fields": total_required,
            "diagnosis_match": diagnosis_match,
        }

    def _check_existing_run(self, benchmark_db, sample_id: str, config_key: str) -> Optional[BenchmarkRun]:
        existing = benchmark_db.query(BenchmarkRun).filter(
            BenchmarkRun.sample_id == sample_id,
            BenchmarkRun.config_key == config_key,
            BenchmarkRun.status == "completed"
        ).order_by(BenchmarkRun.created_at.desc()).first()
        return existing

    def _save_benchmark_run(
        self,
        benchmark_db,
        sample_id: str,
        config_key: str,
        visit_id: str,
        status: str,
        emr_result: Optional[Dict],
        hallucination_result: Optional[Dict],
        verification_issues: Optional[Dict],
        elapsed_seconds: float,
        llm_call_count: int,
        char_count: int,
        error_message: Optional[str] = None
    ) -> BenchmarkRun:
        run = BenchmarkRun(
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
            error_message=error_message
        )
        benchmark_db.add(run)
        benchmark_db.commit()
        benchmark_db.refresh(run)
        return run

    def _save_benchmark_stages(
        self,
        benchmark_db,
        run: BenchmarkRun,
        stages_info: List[Dict[str, Any]]
    ):
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

    def _compute_diagnosis_match_from_consistency(self, consistency_result: Optional[Dict]) -> Optional[bool]:
        if not consistency_result or "facts" not in consistency_result:
            return None
        
        facts = consistency_result.get("facts", [])
        assessment_facts = [f for f in facts if f.get("section") == "assessment"]
        
        if not assessment_facts:
            return None
        
        all_supported = all(f.get("is_supported", False) for f in assessment_facts)
        return all_supported

    def _save_benchmark_evaluation(
        self,
        benchmark_db,
        run: BenchmarkRun,
        eval_result: Any,
        quality_metrics: Optional[Dict],
        error_message: Optional[str] = None
    ) -> BenchmarkEvaluation:
        diagnosis_match = self._compute_diagnosis_match_from_consistency(eval_result.consistency)
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
                success=call_record.success,
                error_message=call_record.error_message
            )
            benchmark_db.add(llm_call)
        benchmark_db.commit()

        return evaluation

    def _run_pipeline(
        self,
        sample: Dict[str, Any],
        config_key: str,
        config_info: Dict[str, Any]
    ) -> Tuple[Optional[Dict], Optional[Dict], Optional[Dict], float, int, int, Optional[str]]:
        sample_id = sample.get("sample_id", "")
        logger.info(f"[Pipeline] 开始运行 - sample_id={sample_id}, config={config_key}")

        db = self._build_main_db_session()
        try:
            visit_id, turn_count = self._create_visit_and_turns(db, sample)
            llm_service = LLMService(db)
            orchestrator = PipelineOrchestrator(db=db, llm_service=llm_service, language="zh")

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

            status = result.get("status", "unknown")
            emr = result.get("emr_result")
            hallucination = result.get("hallucination_result")
            verification = result.get("verification_issues")

            llm_call_count = 0
            char_count = 0

            logger.info(f"[Pipeline] 完成 - sample_id={sample_id}, status={status}, elapsed={elapsed:.1f}s")

            return emr, hallucination, verification, elapsed, llm_call_count, char_count, None

        except Exception as e:
            error_msg = f"{str(e)}\n{traceback.format_exc()}"
            logger.error(f"[Pipeline] 失败 - sample_id={sample_id}, error={error_msg}")
            return None, None, None, 0, 0, 0, error_msg

        finally:
            db.close()

    def _run_evaluation(
        self,
        sample: Dict[str, Any],
        emr: Dict[str, Any],
        config_key: str
    ) -> Tuple[Any, Optional[str]]:
        sample_id = sample.get("sample_id", "")
        dialogue_text = sample.get("dialogue_text", "")

        if not dialogue_text:
            return None, "No dialogue_text in sample"

        if not emr:
            return None, "No emr_result to evaluate"

        logger.info(f"[Evaluation] 开始评估 - sample_id={sample_id}, config={config_key}")

        db = self._build_main_db_session()
        try:
            llm_service = LLMService(db)
            evaluator = BenchmarkEvaluator(llm_service)

            t_start = time.time()
            eval_result = evaluator.evaluate_all(dialogue_text, emr, sample_id)
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

    def _build_jsonl_entry(
        self,
        sample: Dict[str, Any],
        config_key: str,
        config_name: str,
        visit_id: str,
        status: str,
        elapsed_seconds: float,
        emr_result: Optional[Dict],
        hallucination_result: Optional[Dict],
        verification_issues: Optional[Dict],
        quality_metrics: Optional[Dict],
        eval_result: Optional[Any],
        llm_call_count: int,
        char_count: int,
        error_message: Optional[str]
    ) -> Dict[str, Any]:
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

    def run_single_sample(
        self,
        sample: Dict[str, Any],
        config_key: str,
        config_info: Dict[str, Any],
        benchmark_db
    ) -> Dict[str, Any]:
        sample_id = sample.get("sample_id", "")
        config_name = config_info.get("name", config_key)

        logger.info(f"处理样本: {sample_id} ({config_name})")
        print(f"  [{config_key}] {sample_id}...", end=" ", flush=True)

        existing_run = self._check_existing_run(benchmark_db, sample_id, config_key)

        if existing_run and not self.re_evaluate:
            logger.info(f"[Skip] 样本已存在且成功 - sample_id={sample_id}, config={config_key}")
            print(f"SKIP (已存在)", flush=True)

            quality_metrics = self._compute_quality_metrics(existing_run.emr_result, sample.get("diagnosis", ""))

            return self._build_jsonl_entry(
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
        pipeline_error = None
        eval_error = None

        emr_result, hallucination_result, verification_issues, elapsed_seconds, llm_call_count, char_count, pipeline_error = \
            self._run_pipeline(sample, config_key, config_info)

        if emr_result:
            status = "completed"
            visit_id = f"exp_{sample_id}_{uuid.uuid4().hex[:8]}"
            quality_metrics = self._compute_quality_metrics(emr_result, sample.get("diagnosis", ""))

            eval_result, eval_error = self._run_evaluation(sample, emr_result, config_key)

            if eval_result:
                llm_call_count += eval_result.get_total_llm_calls()
                char_count += eval_result.get_total_char_count()
        else:
            status = "failed"
            visit_id = f"exp_{sample_id}_{uuid.uuid4().hex[:8]}"

        run = self._save_benchmark_run(
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
            error_message=pipeline_error or eval_error
        )

        if eval_result and status == "completed":
            self._save_benchmark_evaluation(benchmark_db, run, eval_result, quality_metrics, eval_error)

        if status == "completed":
            print(f"OK ({elapsed_seconds:.1f}s, {llm_call_count} calls)", flush=True)
        else:
            print(f"FAIL ({pipeline_error or eval_error})", flush=True)

        return self._build_jsonl_entry(
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

        summary = self._compute_summary(results, config_key, config_name, t_total)

        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        self._save_benchmark_summary(benchmark_db, summary)

        print(f"\n{'='*60}")
        print(f"  完成: {success_count}/{len(results)} 成功, {failed_count} 失败")
        print(f"  耗时: {timedelta(seconds=int(t_total))} (avg {t_total/len(results):.1f}s/样本)")
        print(f"  汇总: {summary_file}")
        print(f"{'='*60}\n")

        return results

    def _compute_summary(
        self,
        results: List[Dict[str, Any]],
        config_key: str,
        config_name: str,
        total_seconds: float
    ) -> Dict[str, Any]:
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

    def _save_benchmark_summary(self, benchmark_db, summary: Dict[str, Any]):
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

    def run_all_configs(self, limit: int = 0):
        all_results = {}
        for config_key in EXPERIMENT_CONFIGS.keys():
            results = self.run_batch(config_key, limit=limit)
            all_results[config_key] = results
        return all_results

    def run_ablations(self, limit: int = 0):
        all_results = {}
        for config_key in ABLATION_CONFIGS.keys():
            results = self.run_batch(config_key, limit=limit)
            all_results[config_key] = results
        return all_results

    def run_multi_variant(self, limit: int = 0):
        """
        多变量Pipeline：一次运行产出7份评估结果
        
        流程：
        1. process_with_fork() → 4份EMR (emr_raw_draft, emr_pre_revision, emr_result, emr_no_term_norm)
        2. extract_key_facts() → key_facts（一次）
        3. 评估映射：
           - emr_raw_draft → end_to_end (experiment)
           - emr_pre_revision → no_verification + no_field_revision (ablation)
           - emr_result → full (experiment + ablation) + standard (experiment) + no_hallucination (ablation)
           - emr_no_term_norm → no_term_norm (ablation)
        4. 独立运行 simplified Pipeline → simplified (experiment)
        
        输出：7个JSONL + 7个Summary（full同时输出experiment和ablation两个Summary）
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        samples_to_run = self.samples[:limit] if limit > 0 else self.samples
        
        logger.info(f"开始多变量Pipeline评估 - samples={len(samples_to_run)}, limit={limit}")
        print(f"\n{'='*60}")
        print(f"  多变量Pipeline评估 (multi)")
        print(f"  样本数: {len(samples_to_run)}")
        print(f"{'='*60}\n")
        
        benchmark_db = get_benchmark_session()
        all_results = {}
        
        config_output_mapping = {
            "end_to_end": {"type": "experiment", "emr_key": "emr_raw_draft"},
            "no_verification": {"type": "ablation", "emr_key": "emr_pre_revision"},
            "no_field_revision": {"type": "ablation", "emr_key": "emr_pre_revision"},
            "full": {"type": "both", "emr_key": "emr_result"},
            "standard": {"type": "experiment", "emr_key": "emr_result"},
            "no_hallucination": {"type": "ablation", "emr_key": "emr_result"},
            "no_term_norm": {"type": "ablation", "emr_key": "emr_no_term_norm"},
            "simplified": {"type": "experiment", "emr_key": None}
        }
        
        for sample in samples_to_run:
            sample_id = sample.get("sample_id", "")
            dialogue_text = sample.get("dialogue_text", "")
            
            print(f"处理样本: {sample_id}...", flush=True)
            logger.info(f"[multi_variant] 处理样本: {sample_id}")
            
            existing_configs = {}
            missing_configs = []
            
            for config_key in config_output_mapping.keys():
                existing_run = self._check_existing_run(benchmark_db, sample_id, config_key)
                if existing_run and not self.re_evaluate:
                    existing_configs[config_key] = existing_run
                else:
                    missing_configs.append(config_key)
            
            if not missing_configs:
                logger.info(f"[multi_variant] SKIP - 所有配置已存在 - sample_id={sample_id}")
                print(f"SKIP (所有8个配置已存在)", flush=True)
                
                sample_results = {}
                for config_key, existing_run in existing_configs.items():
                    config_info = EXPERIMENT_CONFIGS.get(config_key, ABLATION_CONFIGS.get(config_key, {"name": config_key}))
                    quality_metrics = self._compute_quality_metrics(existing_run.emr_result, sample.get("diagnosis", ""))
                    entry = self._build_jsonl_entry(
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
                all_results[sample_id] = sample_results
                continue
            
            if existing_configs:
                logger.info(f"[multi_variant] 部分配置已存在，只评估缺失的 {len(missing_configs)} 个配置 - sample_id={sample_id}")
                print(f"  已存在: {list(existing_configs.keys())}, 需评估: {missing_configs}", flush=True)
            
            db = self._build_main_db_session()
            try:
                visit_id, turn_count = self._create_visit_and_turns(db, sample)
                llm_service = LLMService(db)
                orchestrator = PipelineOrchestrator(db=db, llm_service=llm_service, language="zh")
                
                t_start = time.time()
                fork_result = orchestrator.process_with_fork(visit_id=visit_id, save_evidence=False)
                fork_elapsed = time.time() - t_start
                
                if fork_result.get("status") != "completed":
                    logger.error(f"[multi_variant] process_with_fork失败: {fork_result.get('error')}")
                    print(f"FAIL (fork failed)", flush=True)
                    continue
                
                emr_raw_draft = fork_result.get("emr_raw_draft")
                emr_pre_revision = fork_result.get("emr_pre_revision")
                emr_result = fork_result.get("emr_result")
                emr_no_term_norm = fork_result.get("emr_no_term_norm")
                hallucination_result = fork_result.get("hallucination_result")
                verification_issues = fork_result.get("verification_issues")
                
                logger.info(f"[multi_variant] process_with_fork完成, elapsed={fork_elapsed:.1f}s")
                
                evaluator = BenchmarkEvaluator(llm_service)
                key_facts = None
                
                completeness_eval = LoggedCompletenessEvaluator(llm_service, [])
                try:
                    key_facts = completeness_eval.extract_key_facts(dialogue_text)
                    logger.info(f"[multi_variant] key_facts提取完成")
                except Exception as e:
                    logger.error(f"[multi_variant] key_facts提取失败: {e}")
                
                sample_results = {}
                
                for config_key, existing_run in existing_configs.items():
                    config_info = EXPERIMENT_CONFIGS.get(config_key, ABLATION_CONFIGS.get(config_key, {"name": config_key}))
                    quality_metrics = self._compute_quality_metrics(existing_run.emr_result, sample.get("diagnosis", ""))
                    entry = self._build_jsonl_entry(
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
                    print(f"  {config_key}: SKIP (已存在)", flush=True)
                
                simplified_elapsed = 0
                
                for config_key, mapping in config_output_mapping.items():
                    if config_key in existing_configs:
                        continue
                    
                    emr_key = mapping.get("emr_key")
                    output_type = mapping.get("type")
                    
                    if emr_key is None:
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
                        emr_to_eval = simplified_result.get("emr_result")
                        logger.info(f"[multi_variant] simplified Pipeline完成, elapsed={simplified_elapsed:.1f}s")
                    else:
                        emr_map = {
                            "emr_raw_draft": emr_raw_draft,
                            "emr_pre_revision": emr_pre_revision,
                            "emr_result": emr_result,
                            "emr_no_term_norm": emr_no_term_norm
                        }
                        emr_to_eval = emr_map.get(emr_key)
                    
                    if not emr_to_eval:
                        logger.warning(f"[multi_variant] {config_key}: EMR为空，跳过评估")
                        continue
                    
                    quality_metrics = self._compute_quality_metrics(emr_to_eval, sample.get("diagnosis", ""))
                    
                    try:
                        eval_result = evaluator.evaluate_all(
                            dialogue_text,
                            emr_to_eval,
                            sample_id=sample_id,
                            key_facts=key_facts
                        )
                        logger.info(f"[multi_variant] {config_key}评估完成: support_rate={eval_result.get_support_rate()}, recall_rate={eval_result.get_recall_rate()}")
                    except Exception as e:
                        logger.error(f"[multi_variant] {config_key}评估失败: {e}")
                        eval_result = None
                    
                    config_info = EXPERIMENT_CONFIGS.get(config_key, ABLATION_CONFIGS.get(config_key, {"name": config_key}))
                    
                    entry = self._build_jsonl_entry(
                        sample=sample,
                        config_key=config_key,
                        config_name=config_info.get("name", config_key),
                        visit_id=visit_id,
                        status="completed",
                        elapsed_seconds=fork_elapsed if emr_key else simplified_elapsed,
                        emr_result=emr_to_eval,
                        hallucination_result=hallucination_result if config_key == "full" else None,
                        verification_issues=verification_issues if config_key in ["full", "no_verification", "no_field_revision"] else None,
                        quality_metrics=quality_metrics,
                        eval_result=eval_result,
                        llm_call_count=0,
                        char_count=0,
                        error_message=None
                    )
                    
                    output_file = self.output_dir / f"results_{config_key}_{timestamp}.jsonl"
                    with open(output_file, 'a', encoding='utf-8') as f:
                        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    
                    sample_results[config_key] = entry
                    
                    if output_type == "both":
                        ablation_entry = entry.copy()
                        ablation_entry["config_type"] = "ablation"
                        ablation_output = self.output_dir / f"results_full_ablation_{timestamp}.jsonl"
                        with open(ablation_output, 'a', encoding='utf-8') as f:
                            f.write(json.dumps(ablation_entry, ensure_ascii=False) + "\n")
                    
                    print(f"  {config_key}: OK", flush=True)
                
                all_results[sample_id] = sample_results
                time.sleep(self.request_interval)
                
            except Exception as e:
                error_msg = f"{str(e)}\n{traceback.format_exc()}"
                logger.error(f"[multi_variant] 样本处理异常: {sample_id}, error={error_msg}")
                print(f"FAIL ({error_msg})", flush=True)
            finally:
                db.close()
        
        close_benchmark_session(benchmark_db)
        
        for config_key in ["end_to_end", "no_verification", "no_field_revision", "full", "standard", "no_hallucination", "no_term_norm", "simplified"]:
            config_results = []
            for sample_id, sample_data in all_results.items():
                if config_key in sample_data:
                    config_results.append(sample_data[config_key])
            
            if not config_results:
                continue
            
            config_info = EXPERIMENT_CONFIGS.get(config_key, ABLATION_CONFIGS.get(config_key, {"name": config_key}))
            summary = self._compute_summary(config_results, config_key, config_info.get("name", config_key), 0)
            
            summary_file = self.output_dir / f"summary_{config_key}_{timestamp}.json"
            with open(summary_file, 'w', encoding='utf-8') as f:
                json.dump(summary, f, ensure_ascii=False, indent=2)
            
            self._save_benchmark_summary(benchmark_db, summary)
            
            if config_key == "full":
                ablation_summary = summary.copy()
                ablation_summary["config_type"] = "ablation"
                ablation_summary_file = self.output_dir / f"summary_full_ablation_{timestamp}.json"
                with open(ablation_summary_file, 'w', encoding='utf-8') as f:
                    json.dump(ablation_summary, f, ensure_ascii=False, indent=2)
        
        print(f"\n{'='*60}")
        print(f"  完成: {len(all_results)} 样本")
        print(f"{'='*60}\n")
        
        return all_results


def main():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        samples_to_run = self.samples[:limit] if limit > 0 else self.samples
        
        logger.info(f"开始多变量Pipeline评估 - samples={len(samples_to_run)}, limit={limit}")
        print(f"\n{'='*60}")
        print(f"  多变量Pipeline评估 (multi)")
        print(f"  样本数: {len(samples_to_run)}")
        print(f"{'='*60}\n")
        
        benchmark_db = get_benchmark_session()
        all_results = {}
        
        config_output_mapping = {
            "end_to_end": {"type": "experiment", "emr_key": "emr_raw_draft"},
            "no_verification": {"type": "ablation", "emr_key": "emr_pre_revision"},
            "no_field_revision": {"type": "ablation", "emr_key": "emr_pre_revision"},
            "full": {"type": "both", "emr_key": "emr_result"},
            "standard": {"type": "experiment", "emr_key": "emr_result"},
            "no_hallucination": {"type": "ablation", "emr_key": "emr_result"},
            "no_term_norm": {"type": "ablation", "emr_key": "emr_no_term_norm"},
            "simplified": {"type": "experiment", "emr_key": None}
        }
        
        for sample in samples_to_run:
            sample_id = sample.get("sample_id", "")
            dialogue_text = sample.get("dialogue_text", "")
            
            print(f"处理样本: {sample_id}...", flush=True)
            logger.info(f"[multi_variant] 处理样本: {sample_id}")
            
            db = self._build_main_db_session()
            try:
                visit_id, turn_count = self._create_visit_and_turns(db, sample)
                llm_service = LLMService(db)
                orchestrator = PipelineOrchestrator(db=db, llm_service=llm_service, language="zh")
                
                t_start = time.time()
                fork_result = orchestrator.process_with_fork(visit_id=visit_id, save_evidence=False)
                fork_elapsed = time.time() - t_start
                
                if fork_result.get("status") != "completed":
                    logger.error(f"[multi_variant] process_with_fork失败: {fork_result.get('error')}")
                    print(f"FAIL (fork failed)", flush=True)
                    continue
                
                emr_raw_draft = fork_result.get("emr_raw_draft")
                emr_pre_revision = fork_result.get("emr_pre_revision")
                emr_result = fork_result.get("emr_result")
                emr_no_term_norm = fork_result.get("emr_no_term_norm")
                hallucination_result = fork_result.get("hallucination_result")
                verification_issues = fork_result.get("verification_issues")
                
                logger.info(f"[multi_variant] process_with_fork完成, elapsed={fork_elapsed:.1f}s")
                
                evaluator = BenchmarkEvaluator(llm_service)
                key_facts = None
                
                completeness_eval = LoggedCompletenessEvaluator(llm_service, [])
                try:
                    key_facts = completeness_eval.extract_key_facts(dialogue_text)
                    logger.info(f"[multi_variant] key_facts提取完成")
                except Exception as e:
                    logger.error(f"[multi_variant] key_facts提取失败: {e}")
                
                sample_results = {}
                
                for config_key, mapping in config_output_mapping.items():
                    emr_key = mapping.get("emr_key")
                    output_type = mapping.get("type")
                    
                    if emr_key is None:
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
                        emr_to_eval = simplified_result.get("emr_result")
                        logger.info(f"[multi_variant] simplified Pipeline完成, elapsed={simplified_elapsed:.1f}s")
                    else:
                        emr_map = {
                            "emr_raw_draft": emr_raw_draft,
                            "emr_pre_revision": emr_pre_revision,
                            "emr_result": emr_result,
                            "emr_no_term_norm": emr_no_term_norm
                        }
                        emr_to_eval = emr_map.get(emr_key)
                    
                    if not emr_to_eval:
                        logger.warning(f"[multi_variant] {config_key}: EMR为空，跳过评估")
                        continue
                    
                    quality_metrics = self._compute_quality_metrics(emr_to_eval, sample.get("diagnosis", ""))
                    
                    try:
                        eval_result = evaluator.evaluate_all(
                            dialogue_text,
                            emr_to_eval,
                            sample_id=sample_id,
                            key_facts=key_facts
                        )
                        logger.info(f"[multi_variant] {config_key}评估完成: support_rate={eval_result.get_support_rate()}, recall_rate={eval_result.get_recall_rate()}")
                    except Exception as e:
                        logger.error(f"[multi_variant] {config_key}评估失败: {e}")
                        eval_result = None
                    
                    entry = self._build_jsonl_entry(
                        sample=sample,
                        config_key=config_key,
                        config_name=config_info.get("name", config_key),
                        visit_id=visit_id,
                        status="completed",
                        elapsed_seconds=fork_elapsed if emr_key else simplified_elapsed,
                        emr_result=emr_to_eval,
                        hallucination_result=hallucination_result if config_key == "full" else None,
                        verification_issues=verification_issues if config_key in ["full", "no_verification", "no_field_revision"] else None,
                        quality_metrics=quality_metrics,
                        eval_result=eval_result,
                        llm_call_count=0,
                        char_count=0,
                        error_message=None
                    )
                    
                    output_file = self.output_dir / f"results_{config_key}_{timestamp}.jsonl"
                    with open(output_file, 'a', encoding='utf-8') as f:
                        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    
                    sample_results[config_key] = entry
                    
                    if output_type == "both":
                        ablation_entry = entry.copy()
                        ablation_entry["config_type"] = "ablation"
                        ablation_output = self.output_dir / f"results_full_ablation_{timestamp}.jsonl"
                        with open(ablation_output, 'a', encoding='utf-8') as f:
                            f.write(json.dumps(ablation_entry, ensure_ascii=False) + "\n")
                    
                    print(f"  {config_key}: OK", flush=True)
                
                all_results[sample_id] = sample_results
                time.sleep(self.request_interval)
                
            except Exception as e:
                error_msg = f"{str(e)}\n{traceback.format_exc()}"
                logger.error(f"[multi_variant] 样本处理异常: {sample_id}, error={error_msg}")
                print(f"FAIL ({error_msg})", flush=True)
            finally:
                db.close()
        
        close_benchmark_session(benchmark_db)
        
        for config_key in ["end_to_end", "no_verification", "no_field_revision", "full", "standard", "no_hallucination", "no_term_norm", "simplified"]:
            config_results = []
            for sample_id, sample_data in all_results.items():
                if config_key in sample_data:
                    config_results.append(sample_data[config_key])
            
            if not config_results:
                continue
            
            config_name = config_info.get("name", config_key)
            
            total_elapsed = sum(r.get("elapsed_seconds", 0) for r in config_results)
            summary = self._compute_summary(config_results, config_key, config_name, total_elapsed)
            
            summary_file = self.output_dir / f"summary_{config_key}_{timestamp}.json"
            with open(summary_file, 'w', encoding='utf-8') as f:
                json.dump(summary, f, ensure_ascii=False, indent=2)
            
            self._save_benchmark_summary(benchmark_db, summary)
            
            if config_key == "full":
                ablation_summary = summary.copy()
                ablation_summary["config_type"] = "ablation"
                ablation_summary_file = self.output_dir / f"summary_full_ablation_{timestamp}.json"
                with open(ablation_summary_file, 'w', encoding='utf-8') as f:
                    json.dump(ablation_summary, f, ensure_ascii=False, indent=2)
        
        print(f"\n{'='*60}")
        print(f"  完成: {len(all_results)} 样本")
        print(f"{'='*60}\n")
        
        return all_results


def main():
    parser = argparse.ArgumentParser(description="全量化指标一键评估脚本")
    parser.add_argument("--config", default="full",
                        choices=["end_to_end", "simplified", "standard", "full", "all", "ablations", "multi"],
                        help="实验配置 (default: full)")
    parser.add_argument("--samples", default="data/experiments/test_samples.json",
                        help="测试样本文件路径")
    parser.add_argument("--output-dir", default="data/experiments/results",
                        help="结果输出目录")
    parser.add_argument("--limit", type=int, default=0,
                        help="限制样本数量 (0=全部)")
    parser.add_argument("--interval", type=float, default=2.0,
                        help="LLM 调用间隔秒数 (default: 2.0)")
    parser.add_argument("--re-evaluate", action="store_true",
                        help="重新评估：对已有结果重新运行LLM评估（默认跳过已完成的样本）")
    args = parser.parse_args()

    runner = FullBenchmarkRunner(
        samples_file=args.samples,
        output_dir=args.output_dir,
        request_interval=args.interval,
        re_evaluate=args.re_evaluate
    )

    if not runner.samples:
        print("未加载到样本。请先运行:")
        print("  python scripts/prepare_test_data.py --num_samples 50 --output data/experiments/test_samples.json")
        return

    if args.config == "all":
        runner.run_all_configs(limit=args.limit)
    elif args.config == "ablations":
        runner.run_ablations(limit=args.limit)
    elif args.config == "multi":
        runner.run_multi_variant(limit=args.limit)
    else:
        runner.run_batch(args.config, limit=args.limit)


if __name__ == "__main__":
    main()