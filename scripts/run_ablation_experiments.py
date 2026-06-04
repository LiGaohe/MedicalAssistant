"""
消融实验运行脚本

两种消融配置（完整管线和-幻觉检查复用已有结果）:
  no_term_norm / no_verification

用法:
  python scripts/run_ablation_experiments.py --config no_term_norm --limit 10
  python scripts/run_ablation_experiments.py --config all --limit 10

注意:
  - 完整管线（六阶段）结果复用 results_full_*.jsonl
  - -幻觉检查结果复用 results_standard_*.jsonl（标准管线）
"""

import json
import time
import argparse
import sys
import uuid
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.config import settings
from backend.models.transcript import TranscriptTurn
from backend.models.visit import Visit
from backend.services.pipeline.orchestrator import PipelineOrchestrator
from backend.services.llm.llm_service import LLMService
from backend.services.evaluation.completeness import CompletenessEvaluator
from backend.services.evaluation.quality import QualityEvaluator
from backend.services.evaluation.safety import SafetyEvaluator

LOG_DIR = Path("data/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / "run_ablation_experiments.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


ABLATION_CONFIGS = {
    "no_term_norm": {
        "name": "-术语规范化",
        "skip_cleaning": False,
        "skip_hallucination_check": False,
        "stop_after_draft": False,
        "skip_verification": False,
        "skip_term_norm": True,
        "skip_field_revision": False
    },
    "no_verification": {
        "name": "-后置核查与字段修订",
        "skip_cleaning": False,
        "skip_hallucination_check": False,
        "stop_after_draft": False,
        "skip_verification": True,
        "skip_term_norm": False,
        "skip_field_revision": False
    }
}


class AblationExperimentRunner:
    def __init__(self, samples_file: str, output_dir: str):
        self.samples = self._load_samples(samples_file)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.stats = defaultdict(list)

    def _load_samples(self, path: str):
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get("samples", [])

    def _build_db_session(self):
        engine = create_engine(settings.DATABASE_URL)
        SessionLocal = sessionmaker(bind=engine)
        return SessionLocal()

    def _create_visit_and_turns(self, db, sample):
        sample_id = sample["sample_id"]
        visit = Visit(
            visit_id=f"abl_{sample_id}_{uuid.uuid4().hex[:8]}",
            audio_path=f"abl://{sample_id}",
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

    def _compute_quality_metrics(self, emr, sample_diagnosis):
        if not emr or not isinstance(emr, dict):
            return None

        SOAP_SECTIONS = ["subjective", "objective", "assessment", "plan"]
        REQUIRED_FIELDS = {
            "subjective": ["chief_complaint", "history_present_illness"],
            "objective": [],
            "assessment": ["diagnosis"],
            "plan": ["treatment"],
        }
        ALL_FIELDS = {
            "subjective": ["chief_complaint", "history_present_illness", "past_history"],
            "objective": ["physical_examination", "auxiliary_examination"],
            "assessment": ["diagnosis", "differential_diagnosis"],
            "plan": ["treatment", "advice"],
        }

        present_sections = 0
        total_required = 0
        missing_required = 0
        total_all = 0
        missing_all = 0

        for section in SOAP_SECTIONS:
            sec = emr.get(section, {})
            if isinstance(sec, dict) and len(sec) > 0:
                present_sections += 1

            required = REQUIRED_FIELDS.get(section, [])
            all_fields = ALL_FIELDS.get(section, [])

            for field in required:
                total_required += 1
                fd = sec.get(field, {}) if isinstance(sec, dict) else {}
                val = fd.get("value", "") if isinstance(fd, dict) else ""
                if not val or not str(val).strip():
                    missing_required += 1

            for field in all_fields:
                total_all += 1
                fd = sec.get(field, {}) if isinstance(sec, dict) else {}
                val = fd.get("value", "") if isinstance(fd, dict) else ""
                if not val or not str(val).strip():
                    missing_all += 1

        structure_completeness = present_sections / len(SOAP_SECTIONS) if SOAP_SECTIONS else 0
        field_missing_rate = missing_required / total_required if total_required > 0 else 0
        all_field_missing_rate = missing_all / total_all if total_all > 0 else 0

        diagnosis_match = None
        if sample_diagnosis:
            assessment = emr.get("assessment", {})
            if isinstance(assessment, dict):
                diag_field = assessment.get("diagnosis", {})
                if isinstance(diag_field, dict):
                    diag_val = str(diag_field.get("value", "")).strip()
                    if diag_val:
                        diagnosis_match = sample_diagnosis in diag_val or diag_val in sample_diagnosis

        return {
            "structure_completeness": round(structure_completeness, 4),
            "present_sections": present_sections,
            "total_sections": len(SOAP_SECTIONS),
            "field_missing_rate": round(field_missing_rate, 4),
            "missing_required_fields": missing_required,
            "total_required_fields": total_required,
            "all_field_missing_rate": round(all_field_missing_rate, 4),
            "missing_all_fields": missing_all,
            "total_all_fields": total_all,
            "diagnosis_match": diagnosis_match,
        }

    def _summarize_hallucination(self, halluc):
        if not halluc:
            return None
        summary = halluc.get("summary", {})
        return {
            "severity": halluc.get("severity", "unknown"),
            "support_rate": summary.get("support_rate", 0),
            "total_facts": summary.get("total_facts", 0),
            "unsupported_count": summary.get("unsupported_count", 0)
        }

    def _summarize_verification_issues(self, issues):
        if not issues:
            return None
        if not isinstance(issues, dict):
            return {"total": len(issues) if isinstance(issues, list) else 0, "categories": {}}
        categories = {}
        total = 0
        for cat, items in issues.items():
            count = len(items) if isinstance(items, list) else 0
            categories[cat] = count
            total += count
        return {"total": total, "categories": categories}

    def run_ablation(self, config_key: str, limit: int = 0, run_evaluation: bool = False):
        config_info = ABLATION_CONFIGS[config_key]
        config_name = config_info["name"]
        samples = self.samples[:limit] if limit > 0 else self.samples

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = self.output_dir / f"ablation_{config_key}_{timestamp}.jsonl"

        t_start = time.time()
        results = []
        success_count = 0

        print(f"\n{'='*60}")
        print(f"  消融实验: {config_name}")
        print(f"  样本数: {len(samples)}")
        print(f"{'='*60}")

        for i, sample in enumerate(samples):
            sid = sample["sample_id"]
            t_sample = time.time()

            print(f"  [{i+1}/{len(samples)}] {sid}...", end=" ", flush=True)

            db = self._build_db_session()
            try:
                visit_id, turn_count = self._create_visit_and_turns(db, sample)
                llm_service = LLMService(db)
                orchestrator = PipelineOrchestrator(db=db, llm_service=llm_service, language="zh")

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

                elapsed = time.time() - t_sample
                status = result.get("status", "unknown")

                emr = result.get("emr_result")
                quality = self._compute_quality_metrics(emr, sample.get("diagnosis", ""))

                entry = {
                    "sample_id": sid,
                    "config": config_name,
                    "config_key": config_key,
                    "visit_id": visit_id,
                    "status": status,
                    "elapsed_seconds": round(elapsed, 2),
                    "turn_count": turn_count,
                    "diagnosis": sample.get("diagnosis", ""),
                    "has_emr": emr is not None,
                    "hallucination": self._summarize_hallucination(result.get("hallucination_result")),
                    "verification_issues": self._summarize_verification_issues(result.get("verification_issues")),
                    "quality_metrics": quality,
                    "emr_result": emr,
                }

                results.append(entry)
                if status == "completed":
                    success_count += 1
                    print(f"OK ({elapsed:.1f}s)")
                else:
                    print(f"FAIL ({elapsed:.1f}s)")

                self._append_result(output_file, entry)

            except Exception as e:
                print(f"ERROR: {e}")
                entry = {
                    "sample_id": sid,
                    "config": config_name,
                    "status": "error",
                    "error": str(e),
                    "diagnosis": sample.get("diagnosis", "")
                }
                results.append(entry)
                self._append_result(output_file, entry)
            finally:
                db.close()

        t_total = time.time() - t_start
        print(f"\n  完成: {success_count}/{len(results)} 成功, "
              f"耗时 {timedelta(seconds=int(t_total))} "
              f"(avg {t_total/len(results):.1f}s/样本)")

        summary_file = self.output_dir / f"summary_ablation_{config_key}_{timestamp}.json"
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump({
                "config": config_name,
                "config_key": config_key,
                "timestamp": timestamp,
                "total": len(results),
                "success": success_count,
                "failed": len(results) - success_count,
                "total_seconds": round(t_total, 1),
                "avg_seconds": round(t_total / len(results), 1) if results else 0,
                "results": results
            }, f, ensure_ascii=False, indent=2)

        return results

    def _append_result(self, filepath, entry):
        with open(filepath, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description="消融实验运行脚本")
    parser.add_argument("--config", default="no_term_norm",
                        choices=["no_term_norm", "no_verification", "all"],
                        help="消融配置 (default: no_term_norm)")
    parser.add_argument("--samples", default="data/experiments/test_samples.json",
                        help="测试样本文件路径")
    parser.add_argument("--output_dir", default="data/experiments/results",
                        help="结果输出目录")
    parser.add_argument("--limit", type=int, default=0,
                        help="限制样本数量 (0=全部)")
    args = parser.parse_args()

    runner = AblationExperimentRunner(
        samples_file=args.samples,
        output_dir=args.output_dir
    )

    if not runner.samples:
        print("未加载到样本。请先运行:")
        print("  python scripts/prepare_test_data.py --num_samples 50 --output data/experiments/test_samples.json")
        return

    if args.config == "all":
        for ck in ["no_term_norm", "no_verification"]:
            runner.run_ablation(ck, limit=args.limit)
    else:
        runner.run_ablation(args.config, limit=args.limit)


if __name__ == "__main__":
    main()