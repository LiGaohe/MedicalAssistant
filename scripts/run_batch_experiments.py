"""
批量实验运行脚本（重构版）

功能:
  --single: 单样本测试模式，完整展示每个阶段的内部输出，验证 Pipeline 工作正常
  --resume: 断点续跑，跳过已完成的样本
  --interval: LLM 调用间隔（秒），避免 API 限流
  --dry-run: 估算运行时间而不实际调用 LLM

四种实验方案:
  A: 端到端基线    B: 简化管线    C: 标准管线    D: 完整管线

五种消融配置:
  full / no_term_norm / no_hallucination / no_verification / no_field_revision

增量保存: 每完成一个样本立即写盘，不怕中途崩溃。
Token 统计: 从 PipelineOrchestrator 日志提取每次 LLM 调用的 token 消耗。

用法:
  # 单样本测试（推荐先用这个验证）
  python scripts/run_batch_experiments.py --single

  # 试运行估算
  python scripts/run_batch_experiments.py --dry-run

  # 运行完整管线，50 样本
  python scripts/run_batch_experiments.py --config full --limit 50

  # 运行全部四种方案 + 五种消融，断点续跑
  python scripts/run_batch_experiments.py --config all --samples data/experiments/test_samples.json --resume
"""

import json
import time
import argparse
import sys
import os
import copy
import uuid
import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
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
from backend.services.evaluation.consistency import ConsistencyEvaluator
from backend.services.evaluation.completeness import CompletenessEvaluator
from backend.services.evaluation.quality import QualityEvaluator
from backend.services.evaluation.safety import SafetyEvaluator
from backend.database import get_db

LOG_DIR = Path("data/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / "run_batch_experiments.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


EXPERIMENT_CONFIGS = {
    "end_to_end": {
        "name": "端到端基线", "code": "A",
        "skip_cleaning": True, "skip_hallucination_check": True,
        "stop_after_draft": True, "skip_verification": False
    },
    "simplified": {
        "name": "简化管线", "code": "B",
        "skip_cleaning": True, "skip_hallucination_check": True,
        "stop_after_draft": False, "skip_verification": True
    },
    "standard": {
        "name": "标准管线", "code": "C",
        "skip_cleaning": False, "skip_hallucination_check": True,
        "stop_after_draft": False, "skip_verification": False
    },
    "full": {
        "name": "完整管线", "code": "D",
        "skip_cleaning": False, "skip_hallucination_check": False,
        "stop_after_draft": False, "skip_verification": False
    }
}

ABLATION_CONFIGS = {
    "full":               {"name": "完整管线（六阶段）",   "skip_term_norm": False, "skip_hallucination": False, "skip_verification": False, "skip_field_revision": False},
    "no_term_norm":       {"name": "-术语规范化",         "skip_term_norm": True,  "skip_hallucination": False, "skip_verification": False, "skip_field_revision": False},
    "no_hallucination":   {"name": "-幻觉检查",           "skip_term_norm": False, "skip_hallucination": True,  "skip_verification": False, "skip_field_revision": False},
    "no_verification":    {"name": "-后置核查",           "skip_term_norm": False, "skip_hallucination": False, "skip_verification": True,  "skip_field_revision": False},
    "no_field_revision":  {"name": "-字段修订",           "skip_term_norm": False, "skip_hallucination": False, "skip_verification": False, "skip_field_revision": True}
}


class BatchExperimentRunner:
    def __init__(self, samples_file: str, output_dir: str, request_interval: float = 2.0):
        self.samples = self._load_samples(samples_file)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.request_interval = request_interval
        self.stats = defaultdict(list)

    def _load_samples(self, path: str) -> List[Dict[str, Any]]:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get("samples", [])

    def _build_db_session(self):
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

    def _extract_token_usage(self) -> Dict[str, int]:
        """从 LLM 原始日志中提取最近一次调用的 token 统计"""
        log_dir = Path("data/logs/llm_raw")
        if not log_dir.exists():
            return {}
        log_files = sorted(log_dir.glob("llm_raw_*.log"), key=lambda f: f.stat().st_mtime, reverse=True)
        if not log_files:
            return {}
        try:
            with open(log_files[0], 'r', encoding='utf-8') as f:
                content = f.read()[-3000:]
            prompt_match = re.search(r'\[PROMPT\]\n(.*?)\n\n\[RESPONSE', content, re.DOTALL)
            response_match = re.search(r'\[RESPONSE.*?\]\n(.*?)\n={80}', content, re.DOTALL)
            from ...utils.logger import logger as unused
            return {}
        except Exception:
            return {}

    def run_single_sample_test(self):
        """单样本测试模式：展示全部中间输出，验证 Pipeline 可用性"""
        if not self.samples:
            print("错误: 未加载到任何样本。请先运行 scripts/prepare_test_data.py")
            return

        sample = self.samples[0]
        sample_id = sample["sample_id"]
        diagnosis = sample.get("diagnosis", "")
        turn_count = len(sample.get("turns", []))

        print("\n" + "=" * 70)
        print(f"  单样本测试模式")
        print("=" * 70)
        print(f"  Sample ID:   {sample_id}")
        print(f"  Diagnosis:   {diagnosis}")
        print(f"  Turns:       {turn_count}")
        print(f"  Self Report: {sample.get('self_report', '')[:80]}...")
        print("=" * 70)

        print("\n[初始化] 创建数据库会话和 Pipeline...")
        db = self._build_db_session()
        try:
            visit_id, _ = self._create_visit_and_turns(db, sample)
            llm_service = LLMService(db)
            orchestrator = PipelineOrchestrator(db=db, llm_service=llm_service, language="zh")
            print(f"  visit_id={visit_id}, LLM adapters={list(llm_service.adapters.keys())}")

            print("\n[运行] 启动完整管线（六阶段）...\n")
            t0 = time.time()
            result = orchestrator.process_transcript(
                visit_id=visit_id,
                save_evidence=False,
                skip_cleaning=False,
                skip_hallucination_check=False
            )
            elapsed = time.time() - t0

            print("\n" + "=" * 70)
            print(f"  运行完成，耗时 {elapsed:.1f}s")
            print("=" * 70)
            print(f"\n  Status: {result.get('status')}")

            halluc = result.get("hallucination_result")
            if halluc:
                print(f"\n[阶段4 幻觉检查]")
                severity = halluc.get("severity", "?")
                support_rate = halluc.get("summary", {}).get("support_rate", 0)
                print(f"  Severity:     {severity}")
                print(f"  Support Rate: {support_rate:.2%}")
                facts = halluc.get("facts", [])
                if facts:
                    unsupported = [f for f in facts if f.get("status") == "unsupported"]
                    print(f"  Facts:        {len(facts)} total, {len(unsupported)} unsupported")
                    for uf in unsupported[:5]:
                        print(f"    ✗ [{uf.get('id')}] {uf.get('claim', '')[:60]}")

            v_issues = result.get("verification_issues")
            if v_issues:
                print(f"\n[阶段5 后置核查]")
                if isinstance(v_issues, list):
                    print(f"  Issues: {len(v_issues)}")
                    for issue in v_issues[:5]:
                        print(f"    - [{issue.get('type', '?')}] {issue.get('detail', '')[:80]}")
                elif isinstance(v_issues, dict):
                    print(f"  Issue categories: {list(v_issues.keys())}")
                    for cat, items in v_issues.items():
                        if isinstance(items, list):
                            print(f"    [{cat}]: {len(items)} 条")
                            for item in items[:2]:
                                print(f"      - {str(item)[:80]}")

            emr = result.get("emr_result")
            if emr:
                print(f"\n[最终 SOAP 病历]")
                self._print_emr_summary(emr)

            print(f"\n[耗时] 总计 {elapsed:.1f}s")
            print("\n提示: 如果以上输出完整且无明显错误，说明 Pipeline 工作正常。")
            print("可以继续运行批量实验: python scripts/run_batch_experiments.py --config full --limit 50")

        except Exception as e:
            print(f"\n[错误] 单样本测试失败: {e}")
            import traceback
            traceback.print_exc()
        finally:
            db.close()

    def _print_emr_summary(self, emr: Dict):
        for section in ["subjective", "objective", "assessment", "plan"]:
            sec = emr.get(section, {})
            if not isinstance(sec, dict):
                continue
            print(f"  [{section.upper()}]")
            for field, fdata in sec.items():
                if field in ("text", "evidence_traces", "assessment_items", "plan_items"):
                    continue
                if isinstance(fdata, dict):
                    val = fdata.get("value", "")
                    lbl = fdata.get("label", "")
                    if val:
                        print(f"    {lbl or field}: {str(val)[:80]}")

    def run_single_single_llm_baseline(self):
        """单样本测试端到端基线：一次 LLM 调用直出 SOAP"""
        if not self.samples:
            print("错误: 未加载到任何样本")
            return
        sample = self.samples[0]
        dialogue_text = sample.get("dialogue_text", "")
        diagnosis = sample.get("diagnosis", "")

        print("\n" + "=" * 70)
        print(f"  端到端基线测试")
        print("=" * 70)
        print(f"  Sample: {sample['sample_id']}, Diagnosis: {diagnosis}")
        print(f"  Dialogue length: {len(dialogue_text)} chars")

        db = self._build_db_session()
        try:
            llm_service = LLMService(db)
            from backend.services.llm.prompts import PromptManager
            pm = PromptManager(language="zh")

            prompt = pm.render("direct_soap_generation", transcript=dialogue_text)
            print(f"\n[Prompt] {len(prompt)} chars")

            t0 = time.time()
            response = llm_service.generate(prompt=prompt)
            elapsed = time.time() - t0

            print(f"\n[Response] {len(response.text)} chars, model={response.model}")
            usage = response.usage
            print(f"[Tokens] prompt={usage.get('prompt_tokens','?')}, "
                  f"completion={usage.get('completion_tokens','?')}, "
                  f"total={usage.get('total_tokens','?')}")

            from backend.services.pipeline.utils import parse_json_response
            emr, parsed = parse_json_response(response.text)
            if emr:
                print(f"\n[Generated SOAP]")
                self._print_emr_summary(emr)
            else:
                print(f"\n[Warning] JSON 解析失败，原始输出前 500 字符:\n{response.text[:500]}")

            print(f"\n[耗时] {elapsed:.1f}s")
        except Exception as e:
            print(f"\n[错误] {e}")
            import traceback
            traceback.print_exc()
        finally:
            db.close()

    def estimate_runtime(self):
        """估算运行时间（不实际调用 LLM）"""
        total = len(self.samples)
        # 基于经验的预估值
        stage_estimates = {
            "end_to_end":   20,
            "simplified":   35,
            "standard":     50,
            "full":         65,
        }

        print("\n" + "=" * 70)
        print(f"  运行时间预估（基于 {total} 条样本）")
        print("=" * 70)

        for config_key, est_sec in stage_estimates.items():
            info = EXPERIMENT_CONFIGS[config_key]
            total_sec = total * est_sec
            total_min = total_sec / 60
            print(f"  {info['name']} ({info['code']}): "
                  f"{est_sec}s/样本 → 约 {total_min:.0f} 分钟 ({total_min/60:.1f} 小时)")

        all_sec = sum(stage_estimates.values()) * total
        all_min = all_sec / 60
        print(f"\n  四种方案合计: 约 {all_min:.0f} 分钟 ({all_min/60:.1f} 小时)")

        ablation_total = 5 * 65 * total
        ablation_min = ablation_total / 60
        print(f"  五种消融合计: 约 {ablation_min:.0f} 分钟 ({ablation_min/60:.1f} 小时)")

        print(f"\n  建议:")
        print(f"    1. 先用 --single 验证 Pipeline 正常")
        print(f"    2. 用小样本 (--limit 5) 试跑获取准确耗时")
        print(f"    3. 根据实际耗时调整样本量")

    def run_batch(self, config_key: str, limit: int = 0, resume: bool = False, run_evaluation: bool = False):
        """批量运行指定配置"""
        config_info = EXPERIMENT_CONFIGS[config_key]
        config_name = config_info["name"]
        samples = self.samples[:limit] if limit > 0 else self.samples

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = self.output_dir / f"results_{config_key}_{timestamp}.jsonl"
        state_file = self.output_dir / f".state_{config_key}.json"

        completed_ids = set()
        if resume and state_file.exists():
            with open(state_file, 'r', encoding='utf-8') as f:
                state = json.load(f)
            completed_ids = set(state.get("completed_ids", []))
            print(f"[resume] 已完成 {len(completed_ids)} 条，跳过重跑")

        t_start = time.time()
        results = []
        success_count = 0
        total_tokens = 0

        print(f"\n{'='*60}")
        print(f"  批量运行: {config_name}")
        print(f"  样本数: {len(samples)}, 已跳过: {len(completed_ids & {s['sample_id'] for s in samples})}")
        print(f"{'='*60}")

        for i, sample in enumerate(samples):
            sid = sample["sample_id"]
            if sid in completed_ids:
                continue

            t_sample = time.time()

            if i > 0 and (i % 5 == 0):
                elapsed_total = time.time() - t_start
                avg_per_sample = elapsed_total / max(i, 1)
                remaining_samples = len(samples) - i
                eta = remaining_samples * avg_per_sample
                print(f"  [{i}/{len(samples)}] avg={avg_per_sample:.1f}s, "
                      f"ETA={timedelta(seconds=int(eta))} (elapsed={timedelta(seconds=int(elapsed_total))})")

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
                    skip_verification=config_info.get("skip_verification", False)
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

                if run_evaluation and status == "completed" and emr:
                    dialogue_text = sample.get("dialogue_text", "")
                    if dialogue_text:
                        print(f"(eval...)", end=" ", flush=True)
                        eval_result = self._run_llm_evaluation(dialogue_text, emr, llm_service, sample_id=sid)
                        entry["llm_evaluation"] = eval_result

                results.append(entry)
                if status == "completed":
                    success_count += 1
                    print(f"OK ({elapsed:.1f}s)")
                else:
                    print(f"FAIL ({elapsed:.1f}s)")

                self._append_result(output_file, entry)
                completed_ids.add(sid)
                self._save_state(state_file, completed_ids)

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
                completed_ids.add(sid)
                self._save_state(state_file, completed_ids)
            finally:
                db.close()

        t_total = time.time() - t_start
        print(f"\n  完成: {success_count}/{len(results)} 成功, "
              f"耗时 {timedelta(seconds=int(t_total))} "
              f"(avg {t_total/len(results):.1f}s/样本)")

        summary_file = self.output_dir / f"summary_{config_key}_{timestamp}.json"
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

        if state_file.exists():
            state_file.unlink()

        return results

    def _summarize_hallucination(self, halluc: Optional[Dict]) -> Optional[Dict]:
        if not halluc:
            return None
        summary = halluc.get("summary", {})
        return {
            "severity": halluc.get("severity", "unknown"),
            "support_rate": summary.get("support_rate", 0),
            "total_facts": summary.get("total_facts", 0),
            "unsupported_count": summary.get("unsupported_count", 0)
        }

    def _summarize_verification_issues(self, issues: Optional[Dict]) -> Optional[Dict]:
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

    def _compute_quality_metrics(self, emr: Optional[Dict], sample_diagnosis: str) -> Optional[Dict]:
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

    def _format_emr_for_evaluation(self, emr: Dict) -> str:
        section_labels = {
            "subjective": "【主观资料(S)】",
            "objective": "【客观资料(O)】",
            "assessment": "【评估(A)】",
            "plan": "【计划(P)】",
        }
        sections = []
        for section_key, label in section_labels.items():
            sec = emr.get(section_key, {})
            if not isinstance(sec, dict) or len(sec) == 0:
                continue
            lines = [label]
            for field_key, field_val in sec.items():
                if isinstance(field_val, dict):
                    val = str(field_val.get("value", "")).strip()
                    lbl = field_val.get("label", field_key)
                else:
                    val = str(field_val).strip() if field_val else ""
                    lbl = field_key
                if val:
                    lines.append(f"  [{lbl}]: {val}")
            if len(lines) > 1:
                sections.append("\n".join(lines))
        return "\n\n".join(sections)

    def _run_llm_evaluation(self, transcript: str, emr: Dict, llm_service, sample_id: str = "unknown") -> Dict[str, Any]:
        emr_text = self._format_emr_for_evaluation(emr)
        if not emr_text:
            error_msg = f"样本 {sample_id}: EMR格式化后为空，停止评估流程"
            logger.error(error_msg)
            logger.error(f"样本 {sample_id}: EMR结构: {json.dumps(emr, ensure_ascii=False, indent=2)[:500]}...")
            
            exception_log_path = Path("data/logs/evaluation_exceptions.log")
            exception_log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(exception_log_path, 'a', encoding='utf-8') as f:
                f.write(f"\n{'='*80}\n")
                f.write(f"[{datetime.now().isoformat()}] 样本评估异常\n")
                f.write(f"样本ID: {sample_id}\n")
                f.write(f"异常类型: EMR格式化后为空\n")
                f.write(f"异常详情: _format_emr_for_evaluation 返回空字符串\n")
                f.write(f"EMR结构预览:\n{json.dumps(emr, ensure_ascii=False, indent=2)[:1000]}\n")
                f.write(f"{'='*80}\n")
            
            return {
                "error": "emr text is empty after formatting",
                "error_type": "EMR_FORMAT_EMPTY",
                "sample_id": sample_id,
                "stopped_at": "evaluation_formatting"
            }

        result = {}
        logger.info(f"样本 {sample_id}: 开始LLM评估：一致性 → 完整性 → 质量 → 安全")

        try:
            consistency_evaluator = ConsistencyEvaluator(llm_service)
            consistency_result = consistency_evaluator.evaluate(transcript, emr)
            result["consistency"] = consistency_result
            support_rate = consistency_result.get("summary", {}).get("support_rate", 0)
            hallucination_rate = 1 - support_rate
            consistency_score = consistency_result.get("consistency_score", 1.0)
            logger.info(f"样本 {sample_id}: 一致性评估完成: support_rate={support_rate}, hallucination_rate={hallucination_rate}, consistency_score={consistency_score}")
        except Exception as e:
            logger.error(f"样本 {sample_id}: 一致性评估失败: {e}")
            result["consistency"] = None

        try:
            completeness_evaluator = CompletenessEvaluator(llm_service)
            key_facts = completeness_evaluator.extract_key_facts(transcript)
            completeness_result = completeness_evaluator.evaluate(key_facts, emr)
            result["completeness"] = completeness_result
            recall = completeness_result.get("summary", {}).get("recall_rate", 0)
            omission = completeness_result.get("summary", {}).get("omission_rate", 0)
            logger.info(f"样本 {sample_id}: 完整性评估完成: recall={recall}, omission={omission}")
        except Exception as e:
            logger.error(f"样本 {sample_id}: 完整性评估失败: {e}")
            result["completeness"] = None

        try:
            quality_evaluator = QualityEvaluator(llm_service)
            quality_result = quality_evaluator.evaluate(emr)
            result["quality"] = quality_result
            total_score = quality_result.get("total_score", 0)
            logger.info(f"样本 {sample_id}: 质量评估完成: total_score={total_score}")
        except Exception as e:
            logger.error(f"样本 {sample_id}: 质量评估失败: {e}")
            result["quality"] = None

        try:
            safety_evaluator = SafetyEvaluator(llm_service)
            safety_result = safety_evaluator.evaluate(transcript, emr)
            result["safety"] = safety_result
            high_risk = safety_result.get("has_high_risk", False)
            high_risk_count = safety_result.get("high_risk_count", 0)
            logger.info(f"样本 {sample_id}: 安全评估完成: has_high_risk={high_risk}, count={high_risk_count}")
        except Exception as e:
            logger.error(f"样本 {sample_id}: 安全评估失败: {e}")
            result["safety"] = None

        return result

    def _append_result(self, filepath: Path, entry: Dict):
        with open(filepath, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def run_evaluate_only(self, results_source: str):
        source_path = Path(results_source)
        logger.info(f"run_evaluate_only: source={source_path}")

        if source_path.is_dir():
            jsonl_files = sorted(source_path.glob("results_*.jsonl"))
            jsonl_files += sorted(source_path.glob("ablation_*.jsonl"))
            logger.info(f"目录模式，找到 {len(jsonl_files)} 个jsonl文件")
        elif source_path.is_file() and source_path.suffix == ".jsonl":
            jsonl_files = [source_path]
            logger.info(f"单文件模式: {source_path.name}")
        else:
            logger.error(f"无效的评估源: {results_source}")
            print(f"错误: {results_source} 不是有效的jsonl文件或目录")
            return

        for jsonl_file in jsonl_files:
            logger.info(f"处理: {jsonl_file.name}")
            self._evaluate_existing_jsonl(jsonl_file)

        logger.info("所有评估完成")

    def _evaluate_existing_jsonl(self, jsonl_file: Path):
        entries = []
        with open(jsonl_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        if not entries:
            logger.info(f"{jsonl_file.name}: 无条目")
            return

        entries_with_eval = 0
        updated_entries = []
        llm_service = None

        for entry in entries:
            if entry.get("status") != "completed":
                updated_entries.append(entry)
                continue
            if entry.get("llm_evaluation"):
                entries_with_eval += 1
                updated_entries.append(entry)
                continue

            emr = entry.get("emr_result")
            if not emr:
                updated_entries.append(entry)
                continue
            sample_id = entry.get("sample_id", "")
            sample = next((s for s in self.samples if s.get("sample_id") == sample_id), None)
            if not sample:
                logger.warning(f"样本 {sample_id} 不在样本列表中，跳过评估")
                updated_entries.append(entry)
                continue
            dialogue_text = sample.get("dialogue_text", "")
            if not dialogue_text:
                updated_entries.append(entry)
                continue

            if llm_service is None:
                db = self._build_db_session()
                llm_service = LLMService(db)
                db.close()

            logger.info(f"评估: {sample_id} ({entry.get('config', '')})")
            print(f"  [{jsonl_file.stem}] 评估 {sample_id}...", end=" ", flush=True)
            eval_result = self._run_llm_evaluation(dialogue_text, emr, llm_service, sample_id=sample_id)
            entry["llm_evaluation"] = eval_result
            print("OK")
            updated_entries.append(entry)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = jsonl_file.parent / f"{jsonl_file.stem}_eval_{timestamp}.jsonl"
        with open(output_file, 'w', encoding='utf-8') as f:
            for entry in updated_entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        logger.info(f"{jsonl_file.name}: {entries_with_eval} 已评估, 输出: {output_file.name}")
        print(f"  {jsonl_file.name}: {entries_with_eval} 已有评估, "
              f"{len(updated_entries) - entries_with_eval} 新增, 输出 {output_file.name}")

    def _save_state(self, state_file: Path, completed_ids: set):
        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump({"completed_ids": list(completed_ids)}, f)


def main():
    parser = argparse.ArgumentParser(description="批量实验运行脚本")
    parser.add_argument("--single", action="store_true",
                        help="单样本测试模式：运行1条样本，展示完整中间输出")
    parser.add_argument("--single-baseline", action="store_true",
                        help="单样本端到端基线测试：1次 LLM 调用直出 SOAP")
    parser.add_argument("--dry-run", action="store_true",
                        help="估算运行时间，不实际调用 LLM")
    parser.add_argument("--config", default="full",
                        choices=["end_to_end", "simplified", "standard", "full", "all", "ablations"],
                        help="实验配置 (default: full)")
    parser.add_argument("--samples", default="data/experiments/test_samples.json",
                        help="测试样本文件路径")
    parser.add_argument("--output_dir", default="data/experiments/results",
                        help="结果输出目录")
    parser.add_argument("--limit", type=int, default=0,
                        help="限制样本数量 (0=全部)")
    parser.add_argument("--resume", action="store_true",
                        help="断点续跑：跳过已完成的样本")
    parser.add_argument("--interval", type=float, default=2.0,
                        help="LLM 调用间隔秒数 (default: 2.0)")
    parser.add_argument("--evaluate", action="store_true",
                        help="实验完成后运行LLM评估（完整性/质量/安全）")
    parser.add_argument("--evaluate-only", default="",
                        help="只对已有结果运行评估，填入结果文件路径或目录")
    args = parser.parse_args()

    runner = BatchExperimentRunner(
        samples_file=args.samples,
        output_dir=args.output_dir,
        request_interval=args.interval
    )

    if not runner.samples:
        print("未加载到样本。请先运行:")
        print("  python scripts/prepare_test_data.py --num_samples 50 --output data/experiments/test_samples.json")
        return

    if args.single:
        runner.run_single_sample_test()
        return

    if args.single_baseline:
        runner.run_single_single_llm_baseline()
        return

    if args.dry_run:
        runner.estimate_runtime()
        return

    if args.evaluate_only:
        runner.run_evaluate_only(args.evaluate_only)
        return

    if args.config == "all":
        for ck in ["end_to_end", "simplified", "standard", "full"]:
            runner.run_batch(ck, limit=args.limit, resume=args.resume, run_evaluation=args.evaluate)
    elif args.config == "ablations":
        print("消融实验需要在 run_batch 中实现配置切换逻辑，当前建议逐配置手动运行。")
        return
    else:
        runner.run_batch(args.config, limit=args.limit, resume=args.resume, run_evaluation=args.evaluate)


if __name__ == "__main__":
    main()