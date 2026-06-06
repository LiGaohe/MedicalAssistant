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
    "no_verification":    {"name": "-后置核查与字段修订",  "skip_cleaning": False, "stop_after_draft": False, "skip_term_norm": False, "skip_hallucination_check": False, "skip_verification": True,  "skip_field_revision": False}
}

# 定义每个配置包含的LLM调用阶段（全局变量）
# 阶段名称对应各Stage中record_call使用的名称
# 有LLM调用的阶段：turn_cleaning, draft_generation_free_text, draft_generation_json,
#   soap_structuring, hallucination_check, claim_verification, checklist_verification,
#   certainty_verification, field_revision
# 注意：term_norm无LLM调用，不出现在此列表中
CONFIG_STAGE_GROUPS = {
    "end_to_end": [
        # 端到端：仅草稿生成
        "draft_generation_free_text",
        "draft_generation_json"
    ],
    "simplified": [
        # 简化管线：skip_cleaning=True, skip_hallucination_check=True, skip_verification=True
        # 实际LLM调用：draft_generation → soap_structuring
        "draft_generation_free_text",
        "draft_generation_json",
        "soap_structuring"
    ],
    "standard": [
        # 标准管线：skip_hallucination_check=True，不包含hallucination_check
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
    "no_verification": [
        # 消融：跳过后置核查与字段修订，不包含claim/checklist/certainty_verification和field_revision
        "turn_cleaning",
        "draft_generation_free_text",
        "draft_generation_json",
        "soap_structuring",
        "term_norm",
        "hallucination_check"
    ],
    "full": [
        # 完整管线：全部阶段（包含term_norm）
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
    "no_hallucination": [
        # 消融：跳过幻觉检查，与standard相同（不含hallucination_check）
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
        # 消融：跳过术语规范化（不含term_norm），其余与full相同
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

# 配置到LLM统计源的映射
# 每个配置使用对应fork路径的LLM统计，而不是合并后的统计
# - llm_stats_full: 路径A（阶段1-3 + 路径A阶段4-6，完整管线）
# - llm_stats_no_term_norm: 路径B（阶段1-3 + 路径B阶段4-6，skip_term_norm）
# - llm_stats_no_hallucination: 路径C（阶段1-3 + 路径C阶段4-6，skip_hallucination_check）
CONFIG_LLM_STATS_SOURCE = {
    "end_to_end": "llm_stats_full",            # 路径A的子集（阶段1-2）
    "no_verification": "llm_stats_full",        # 路径A的子集（阶段1-5）
    "full": "llm_stats_full",                   # 路径A完整
    "standard": "llm_stats_no_hallucination",   # 路径C完整（skip_hallucination_check）
    "no_hallucination": "llm_stats_no_hallucination",  # 路径C完整
    "no_term_norm": "llm_stats_no_term_norm",   # 路径B完整
    "simplified": None  # 独立管线，使用自己的统计
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

    def _is_emr_empty(self, emr: Optional[Dict]) -> bool:
        if not emr or not isinstance(emr, dict):
            return True
        
        for section in SOAP_SECTIONS:
            sec = emr.get(section, {})
            if isinstance(sec, dict) and len(sec) > 0:
                if "text" in sec and str(sec.get("text", "")).strip():
                    return False
                for field, val in sec.items():
                    if field == "text":
                        continue
                    if isinstance(val, dict):
                        if str(val.get("value", "")).strip():
                            return False
                    elif isinstance(val, str) and val.strip():
                        return False
        return True

    def _check_existing_run(self, benchmark_db, sample_id: str, config_key: str) -> Optional[BenchmarkRun]:
        existing = benchmark_db.query(BenchmarkRun).filter(
            BenchmarkRun.sample_id == sample_id,
            BenchmarkRun.config_key == config_key,
            BenchmarkRun.status == "completed"
        ).order_by(BenchmarkRun.created_at.desc()).first()
        return existing

    # 缺失配置与中间结果字段的映射
    CONFIG_EMR_KEY_MAPPING = {
        "end_to_end": "emr_raw_draft",
        "no_verification": "emr_pre_revision",
        "full": "emr_result",
        "standard": "emr_no_hallucination",
        "no_hallucination": "emr_no_hallucination",
        "no_term_norm": "emr_no_term_norm",
    }

    def _check_intermediate_results(self, benchmark_db, sample_id: str, missing_configs: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
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

        if not existing.emr_result or self._is_emr_empty(existing.emr_result):
            logger.info(f"[中间结果检查] emr_result为空 - sample_id={sample_id}")
            return None

        # 检查缺失配置对应的中间结果字段是否都存在
        if missing_configs:
            missing_fields = []
            for config_key in missing_configs:
                emr_key = self.CONFIG_EMR_KEY_MAPPING.get(config_key)
                if emr_key is None:
                    continue  # simplified等无对应EMR字段的配置跳过
                field_value = getattr(existing, emr_key, None)
                if not field_value or self._is_emr_empty(field_value):
                    missing_fields.append(emr_key)

            if missing_fields:
                logger.warning(f"[中间结果检查] 缺失配置对应的中间结果字段为空 - sample_id={sample_id}, missing_fields={missing_fields}, 将重新执行process_with_fork")
                return None

        # 构建中间结果字典
        results = {}
        if existing.emr_raw_draft and not self._is_emr_empty(existing.emr_raw_draft):
            results["emr_raw_draft"] = existing.emr_raw_draft
        if existing.emr_pre_revision and not self._is_emr_empty(existing.emr_pre_revision):
            results["emr_pre_revision"] = existing.emr_pre_revision
        if existing.emr_result and not self._is_emr_empty(existing.emr_result):
            results["emr_result"] = existing.emr_result
        if existing.emr_no_term_norm and not self._is_emr_empty(existing.emr_no_term_norm):
            results["emr_no_term_norm"] = existing.emr_no_term_norm
        if existing.emr_no_hallucination and not self._is_emr_empty(existing.emr_no_hallucination):
            results["emr_no_hallucination"] = existing.emr_no_hallucination
        if existing.hallucination_result:
            results["hallucination_result"] = existing.hallucination_result
        if existing.verification_issues:
            results["verification_issues"] = existing.verification_issues
        if existing.key_facts:
            results["key_facts"] = existing.key_facts

        logger.info(f"[中间结果检查] 检查通过 - sample_id={sample_id}, 可复用字段={list(results.keys())}")
        return results if results else None

    def _compute_llm_stats_for_config(
        self,
        config_key: str,
        llm_stats: Dict[str, Any]
    ) -> Tuple[int, int, int, float]:
        """
        根据配置和LLM统计stage_breakdown计算配置对应的LLM调用次数、字符数和实际延迟

        每个配置包含的阶段由 CONFIG_STAGE_GROUPS 定义，从对应路径的 llm_stats 中提取。

        Args:
            config_key: 配置键名
            llm_stats: 对应路径的LLM统计（llm_stats_full/llm_stats_no_term_norm/llm_stats_no_hallucination）

        Returns:
            Tuple[int, int, int, float]: (llm_call_count, char_count, token_count, actual_latency)
        """
        logger.info(f"[DEBUG] _compute_llm_stats_for_config开始 - config_key={config_key}")
        logger.info(f"[DEBUG]   - llm_stats存在: {llm_stats is not None}")
        logger.info(f"[DEBUG]   - llm_stats keys: {list(llm_stats.keys()) if llm_stats else 'N/A'}")

        if not llm_stats:
            logger.info(f"[DEBUG] 返回(0,0,0,0.0) - 原因: llm_stats为空")
            return 0, 0, 0, 0.0

        stage_breakdown = llm_stats.get("stage_breakdown", {})
        stage_group = CONFIG_STAGE_GROUPS.get(config_key)

        logger.info(f"[DEBUG]   - stage_breakdown keys: {list(stage_breakdown.keys()) if stage_breakdown else 'N/A'}")
        logger.info(f"[DEBUG]   - stage_group={stage_group}")

        if not stage_group:
            # stage_group为空列表或未定义，返回0
            logger.warning(f"[DEBUG] config_key={config_key} 没有定义stage_group，返回(0,0,0,0.0)")
            return 0, 0, 0, 0.0

        llm_call_count = 0
        char_count = 0
        token_count = 0
        actual_latency = 0.0
        
        # [DEBUG] 记录按stage计算的情况
        logger.info(f"[DEBUG] 按stage_group计算 - config_key={config_key}, stages={stage_group}")
        
        for stage in stage_group:
            stage_stats = stage_breakdown.get(stage, {})
            stage_call_count = stage_stats.get("call_count") or 0
            stage_char_count = stage_stats.get("total_chars") or 0
            stage_token_count = stage_stats.get("total_tokens") or 0
            stage_latency = stage_stats.get("total_latency") or 0.0
            
            # [DEBUG] 记录每个stage的统计
            logger.info(f"[DEBUG]   - stage={stage}: calls={stage_call_count}, chars={stage_char_count}, tokens={stage_token_count}, latency={stage_latency}")
            
            llm_call_count += stage_call_count
            char_count += stage_char_count
            token_count += stage_token_count
            actual_latency += stage_latency
        
        # [DEBUG] 记录最终计算结果
        logger.info(f"[DEBUG] _compute_llm_stats_for_config完成 - config_key={config_key}")
        logger.info(f"[DEBUG]   - 结果: calls={llm_call_count}, chars={char_count}, tokens={token_count}, latency={actual_latency}")
        
        return llm_call_count, char_count, token_count, actual_latency

    def _validate_run_before_save(
        self,
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
        """
        在保存到数据库前校验数据完整性，发现问题时抛出 ValueError 阻止保存。
        """
        errors = []

        if status == "completed":
            # emr_result 必须存在且非空
            if emr_result is None or self._is_emr_empty(emr_result):
                errors.append(f"status=completed 但 emr_result 为空")
            
            # llm_call_count 必须 > 0（completed 状态至少有一次 LLM 调用）
            if llm_call_count <= 0:
                errors.append(f"status=completed 但 llm_call_count={llm_call_count}（期望 > 0）")
            
            # token_count 不能为 None，且当有 LLM 调用时必须 > 0
            if token_count is None:
                errors.append(f"status=completed 但 token_count=None（禁止传入 None，会导致数据库使用默认值 0）")
            elif llm_call_count > 0 and token_count <= 0:
                errors.append(f"status=completed 且 llm_call_count={llm_call_count} 但 token_count={token_count}（期望 > 0）")
            
            # char_count 当有 LLM 调用时必须 > 0
            if llm_call_count > 0 and char_count <= 0:
                errors.append(f"status=completed 且 llm_call_count={llm_call_count} 但 char_count={char_count}（期望 > 0）")
            
            # elapsed_seconds 必须 > 0
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

    def _save_benchmark_run(
        self,
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
        # [DEBUG] 记录保存参数
        logger.info(f"[DEBUG] _save_benchmark_run开始 - sample_id={sample_id}, config_key={config_key}")
        logger.info(f"[DEBUG]   - visit_id={visit_id}")
        logger.info(f"[DEBUG]   - status={status}")
        logger.info(f"[DEBUG]   - elapsed_seconds={elapsed_seconds}")
        logger.info(f"[DEBUG]   - llm_call_count={llm_call_count}")
        logger.info(f"[DEBUG]   - char_count={char_count}")
        logger.info(f"[DEBUG]   - token_count={token_count}")
        logger.info(f"[DEBUG]   - stage_breakdown存在: {stage_breakdown is not None}, keys: {list(stage_breakdown.keys()) if stage_breakdown else 'N/A'}")
        logger.info(f"[DEBUG]   - emr_raw_draft存在: {emr_raw_draft is not None}, is_empty: {self._is_emr_empty(emr_raw_draft) if emr_raw_draft else 'N/A'}")
        logger.info(f"[DEBUG]   - emr_pre_revision存在: {emr_pre_revision is not None}, is_empty: {self._is_emr_empty(emr_pre_revision) if emr_pre_revision else 'N/A'}")
        logger.info(f"[DEBUG]   - emr_result存在: {emr_result is not None}, is_empty: {self._is_emr_empty(emr_result) if emr_result else 'N/A'}")
        
        # 保存前校验数据完整性
        self._validate_run_before_save(
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
            emr_raw_draft=emr_raw_draft if emr_raw_draft and not self._is_emr_empty(emr_raw_draft) else None,
            emr_pre_revision=emr_pre_revision if emr_pre_revision and not self._is_emr_empty(emr_pre_revision) else None,
            emr_result=emr_result if emr_result and not self._is_emr_empty(emr_result) else None,
            emr_no_term_norm=emr_no_term_norm if emr_no_term_norm and not self._is_emr_empty(emr_no_term_norm) else None,
            emr_no_hallucination=emr_no_hallucination if emr_no_hallucination and not self._is_emr_empty(emr_no_hallucination) else None,
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
        
        # [DEBUG] 记录保存后的状态
        logger.info(f"[DEBUG] _save_benchmark_run完成 - run.id={run.id}")
        logger.info(f"[DEBUG]   - run.llm_call_count={run.llm_call_count}")
        logger.info(f"[DEBUG]   - run.char_count={run.char_count}")
        logger.info(f"[DEBUG]   - run.token_count={run.token_count}")
        
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
                prompt_tokens=call_record.prompt_tokens,
                completion_tokens=call_record.completion_tokens,
                total_tokens=call_record.total_tokens,
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
    ) -> Tuple[Optional[Dict], Optional[Dict], Optional[Dict], float, int, int, int, Optional[Dict], Optional[str]]:
        """
        返回值新增stage_breakdown参数
        """
        sample_id = sample.get("sample_id", "")
        logger.info(f"[Pipeline] 开始运行 - sample_id={sample_id}, config={config_key}")

        db = self._build_main_db_session()
        try:
            visit_id, turn_count = self._create_visit_and_turns(db, sample)
            llm_service = LLMService(db)
            orchestrator = PipelineOrchestrator(db=db, llm_service=llm_service, language="zh", sequential=self.sequential)

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
            llm_stats = result.get("llm_stats", {})
            stage_breakdown = llm_stats.get("stage_breakdown", {})  # 新增：获取stage_breakdown

            llm_call_count, char_count, token_count, actual_latency = self._compute_llm_stats_for_config(
                config_key, llm_stats
            )

            logger.info(f"[Pipeline] 完成 - sample_id={sample_id}, status={status}, elapsed={elapsed:.1f}s, "
                        f"llm_calls={llm_call_count}, tokens={token_count}")

            return emr, hallucination, verification, elapsed, llm_call_count, char_count, token_count, stage_breakdown, None

        except Exception as e:
            error_msg = f"{str(e)}\n{traceback.format_exc()}"
            logger.error(f"[Pipeline] 失败 - sample_id={sample_id}, error={error_msg}")
            return None, None, None, 0, 0, 0, 0, None, error_msg

        finally:
            db.close()

    def _run_evaluation(
        self,
        sample: Dict[str, Any],
        emr: Dict[str, Any],
        config_key: str,
        skip_quality_safety: bool = True,
        key_facts: Optional[Dict] = None
    ) -> Tuple[Any, Optional[str]]:
        sample_id = sample.get("sample_id", "")
        dialogue_text = sample.get("dialogue_text", "")

        if not dialogue_text:
            return None, "No dialogue_text in sample"

        if not emr:
            return None, "No emr_result to evaluate"

        logger.info(f"[Evaluation] 开始评估 - sample_id={sample_id}, config={config_key}, skip_quality_safety={skip_quality_safety}, has_key_facts={key_facts is not None}")

        db = self._build_main_db_session()
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

    def _build_jsonl_entry(
        self,
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
        token_count = 0
        stage_breakdown = None  # 新增：接收stage_breakdown
        pipeline_error = None
        eval_error = None

        emr_result, hallucination_result, verification_issues, elapsed_seconds, llm_call_count, char_count, token_count, stage_breakdown, pipeline_error = \
            self._run_pipeline(sample, config_key, config_info)

        if emr_result:
            status = "completed"
            visit_id = f"exp_{sample_id}_{uuid.uuid4().hex[:8]}"
            quality_metrics = self._compute_quality_metrics(emr_result, sample.get("diagnosis", ""))

            eval_result, eval_error = self._run_evaluation(sample, emr_result, config_key)

            if eval_result:
                llm_call_count += eval_result.get_total_llm_calls()
                char_count += eval_result.get_total_char_count()
                eval_tokens = eval_result.get_total_tokens()
                if eval_tokens:
                    token_count += eval_tokens
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
            token_count=token_count,
            stage_breakdown=stage_breakdown,  # 新增：传入stage_breakdown
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
        1. process_with_fork() → 5份EMR (emr_raw_draft, emr_pre_revision, emr_result, emr_no_term_norm, emr_no_hallucination)
        2. extract_key_facts() → key_facts（一次）
        3. 评估映射：
           - emr_raw_draft → end_to_end (experiment)
           - emr_pre_revision → no_verification (ablation)
           - emr_result → full (experiment + ablation)
           - emr_no_hallucination → standard (experiment) + no_hallucination (ablation)
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
        
        # 评估去重组：相同EMR的配置只评估一次，结果复用
        # standard 和 no_hallucination 配置相同（均跳过幻觉检查），EMR相同，只需评估一次
        EVAL_DEDUP_GROUPS = {
            "standard": "standard",       # 首次评估的配置
            "no_hallucination": "standard" # 复用 standard 的评估结果
        }

        config_output_mapping = {
            "end_to_end": {"type": "experiment", "emr_key": "emr_raw_draft"},
            "no_verification": {"type": "ablation", "emr_key": "emr_pre_revision"},
            "full": {"type": "both", "emr_key": "emr_result"},
            "standard": {"type": "experiment", "emr_key": "emr_no_hallucination"},
            "no_hallucination": {"type": "ablation", "emr_key": "emr_no_hallucination"},
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
            
            intermediate_results = self._check_intermediate_results(benchmark_db, sample_id, missing_configs=missing_configs)

            logger.info(f"[中间结果检查] 返回结果: sample_id={sample_id}, has_results={intermediate_results is not None}, re_evaluate={self.re_evaluate}")

            if intermediate_results and not self.re_evaluate:
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
                
                visit_id_cached = None
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
            else:
                intermediate_results = None
                logger.info(f"[复用中间结果] 不复用 - sample_id={sample_id}, 原因: {'re_evaluate=True' if self.re_evaluate else '中间结果不完整'}")
            
            db = self._build_main_db_session()
            try:
                if intermediate_results:
                    visit_id = visit_id_cached or f"exp_{sample_id}_{uuid.uuid4().hex[:8]}"
                    llm_service = LLMService(db)
                    orchestrator = None
                    
                    # 复用中间结果时，从cached_run恢复LLM统计
                    if cached_run:
                        logger.info(f"[复用中间结果] 从cached_run恢复LLM统计 - sample_id={sample_id}, calls={cached_run.llm_call_count}, chars={cached_run.char_count}")
                        # 注意：cached_run保存的是路径A(full)的统计
                        # 对于no_term_norm和no_hallucination，无法从缓存恢复精确统计
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
                else:
                    visit_id, turn_count = self._create_visit_and_turns(db, sample)
                    llm_service = LLMService(db)
                    orchestrator = PipelineOrchestrator(db=db, llm_service=llm_service, language="zh", sequential=self.sequential)
                    
                    t_start = time.time()
                    fork_result = orchestrator.process_with_fork(visit_id=visit_id, save_evidence=False)
                    fork_elapsed = time.time() - t_start
                    
                    fork_status = fork_result.get("status")
                    
                    emr_raw_draft = fork_result.get("emr_raw_draft")
                    emr_pre_revision = fork_result.get("emr_pre_revision")
                    emr_result = fork_result.get("emr_result")
                    emr_no_term_norm = fork_result.get("emr_no_term_norm")
                    emr_no_hallucination = fork_result.get("emr_no_hallucination")
                    hallucination_result = fork_result.get("hallucination_result")
                    verification_issues = fork_result.get("verification_issues")

                    # 提取各路径独立LLM统计
                    llm_stats = fork_result.get("llm_stats", {})
                    llm_stats_full = fork_result.get("llm_stats_full", llm_stats)
                    llm_stats_no_term_norm = fork_result.get("llm_stats_no_term_norm", llm_stats)
                    llm_stats_no_hallucination = fork_result.get("llm_stats_no_hallucination", llm_stats)

                    # 使用路径A统计作为full配置的默认统计
                    stage_breakdown = llm_stats_full.get("stage_breakdown", {})

                    llm_call_count = llm_stats_full.get("total_calls") or 0
                    char_count = llm_stats_full.get("total_char_count") or 0
                    token_count = llm_stats_full.get("total_tokens") or 0
                    actual_latency = llm_stats_full.get("total_actual_latency") or 0.0

                    fork_elapsed_actual = actual_latency if actual_latency > 0 else fork_elapsed

                    logger.info(f"[multi_variant] process_with_fork完成, status={fork_status}, elapsed={fork_elapsed:.1f}s, actual_latency={actual_latency:.2f}s, llm_calls={llm_call_count}")
                    logger.info(f"[multi_variant] 各路径LLM统计: full_calls={llm_stats_full.get('total_calls')}, no_term_norm_calls={llm_stats_no_term_norm.get('total_calls')}, no_hallucination_calls={llm_stats_no_hallucination.get('total_calls')}")
                    
                    if fork_status != "completed":
                        logger.error(f"[multi_variant] process_with_fork失败: {fork_result.get('error')}")
                        print(f"FAIL (fork failed, 保存中间结果到数据库)", flush=True)
                        
                        self._save_benchmark_run(
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
                            stage_breakdown=stage_breakdown,
                            error_message=fork_result.get('error')
                        )
                        logger.info(f"[multi_variant] 已保存失败状态和中间结果到数据库 - sample_id={sample_id}")
                        
                        benchmark_db.close()
                        db.close()
                        raise RuntimeError(f"process_with_fork failed for sample {sample_id}: {fork_result.get('error')}")
                    
                    self._save_benchmark_run(
                        benchmark_db,
                        sample_id=sample_id,
                        config_key="full",
                        visit_id=visit_id,
                        status=fork_status,
                        emr_raw_draft=emr_raw_draft,
                        emr_pre_revision=emr_pre_revision,
                        emr_result=emr_result,
                        emr_no_term_norm=emr_no_term_norm,
                        emr_no_hallucination=emr_no_hallucination,
                        hallucination_result=hallucination_result,
                        verification_issues=verification_issues,
                        elapsed_seconds=fork_elapsed_actual,
                        llm_call_count=llm_call_count,
                        char_count=char_count,
                        token_count=token_count,
                        stage_breakdown=stage_breakdown,
                        error_message=None
                    )
                    logger.info(f"[multi_variant] 已保存中间结果到数据库 - sample_id={sample_id}, llm_calls={llm_call_count}")
                
                evaluator = BenchmarkEvaluator(llm_service)
                key_facts = key_facts_cached if intermediate_results else None
                
                if not key_facts:
                    completeness_eval = LoggedCompletenessEvaluator(llm_service, [])
                    try:
                        key_facts = completeness_eval.extract_key_facts(dialogue_text)
                        logger.info(f"[multi_variant] key_facts提取完成")
                        
                        if intermediate_results:
                            cached_run = benchmark_db.query(BenchmarkRun).filter(
                                BenchmarkRun.sample_id == sample_id,
                                BenchmarkRun.config_key == "full"
                            ).order_by(BenchmarkRun.created_at.desc()).first()
                            if cached_run:
                                cached_run.key_facts = key_facts
                                benchmark_db.commit()
                                logger.info(f"[multi_variant] 已更新key_facts到数据库 - sample_id={sample_id}")
                    except Exception as e:
                        logger.error(f"[multi_variant] key_facts提取失败: {e}")
                        print(f"FAIL (key_facts提取失败)", flush=True)
                        raise RuntimeError(f"key_facts extraction failed for sample {sample_id}: {e}")
                
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
                eval_cache = {}  # 评估结果缓存：{emr_key: eval_result}，相同EMR只评估一次
                
                # [DEBUG] 记录配置评估循环开始状态
                logger.info(f"[DEBUG] 配置评估循环开始 - sample_id={sample_id}")
                logger.info(f"[DEBUG]   - existing_configs数量: {len(existing_configs)}")
                logger.info(f"[DEBUG]   - missing_configs数量: {len([k for k in config_output_mapping.keys() if k not in existing_configs])}")
                logger.info(f"[DEBUG]   - llm_stats状态: total_calls={llm_stats.get('total_calls', 0)}, stage_breakdown_keys={list(llm_stats.get('stage_breakdown', {}).keys())}")
                logger.info(f"[DEBUG]   - emr_raw_draft存在: {emr_raw_draft is not None}")
                logger.info(f"[DEBUG]   - emr_pre_revision存在: {emr_pre_revision is not None}")
                logger.info(f"[DEBUG]   - emr_result存在: {emr_result is not None}")
                logger.info(f"[DEBUG]   - emr_no_term_norm存在: {emr_no_term_norm is not None}")
                logger.info(f"[DEBUG]   - emr_no_hallucination存在: {emr_no_hallucination is not None}")
                
                for config_key, mapping in config_output_mapping.items():
                    if config_key in existing_configs:
                        continue
                    
                    # [DEBUG] 记录每个配置的评估状态
                    logger.info(f"[DEBUG] 开始评估配置 - config_key={config_key}, sample_id={sample_id}")
                    
                    emr_key = mapping.get("emr_key")
                    output_type = mapping.get("type")
                    
                    # [DEBUG] 记录配置映射
                    logger.info(f"[DEBUG]   - emr_key={emr_key}, output_type={output_type}")
                    
                    if emr_key is None:
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
                            orchestrator = PipelineOrchestrator(db=db, llm_service=llm_service, language="zh", sequential=self.sequential)
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
                        
                        if simplified_status != "completed":
                            error_msg = simplified_result.get("error", "Unknown error")
                            logger.error(f"[multi_variant] simplified Pipeline失败: {error_msg}, 保存失败状态并停止")
                            self._save_benchmark_run(
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
                        
                        # [DEBUG] 记录EMR选择结果
                        logger.info(f"[DEBUG] EMR选择 - config_key={config_key}, emr_key={emr_key}")
                        logger.info(f"[DEBUG]   - emr_map内容: {list(emr_map.keys())}")
                        logger.info(f"[DEBUG]   - emr_to_eval存在: {emr_to_eval is not None}")
                        if emr_to_eval:
                            logger.info(f"[DEBUG]   - emr_to_eval是否为空: {self._is_emr_empty(emr_to_eval)}")
                            logger.info(f"[DEBUG]   - emr_to_eval的keys: {list(emr_to_eval.keys()) if isinstance(emr_to_eval, dict) else 'N/A'}")
                    
                    if not emr_to_eval:
                        logger.warning(f"[DEBUG] {config_key}: EMR为空，跳过评估 - emr_key={emr_key}")
                        logger.warning(f"[multi_variant] {config_key}: EMR为空，跳过评估")
                        continue
                    
                    # [DEBUG] 记录EMR非空状态
                    logger.info(f"[DEBUG] {config_key}: EMR非空，继续评估 - emr_key={emr_key}")
                    
                    quality_metrics = self._compute_quality_metrics(emr_to_eval, sample.get("diagnosis", ""))
                    
                    # [DEBUG] 记录quality_metrics
                    logger.info(f"[DEBUG] {config_key}: quality_metrics计算完成 - structure_completeness={quality_metrics.get('structure_completeness')}, field_missing_rate={quality_metrics.get('field_missing_rate')}")
                    
                    # 评估去重：检查是否可以复用已有评估结果
                    dedup_source = EVAL_DEDUP_GROUPS.get(config_key)
                    eval_cache_key = dedup_source if dedup_source else config_key
                    
                    if eval_cache_key in eval_cache:
                        eval_result = eval_cache[eval_cache_key]
                        logger.info(f"[multi_variant] {config_key}: 复用 {eval_cache_key} 的评估结果 (去重), support_rate={eval_result.get_support_rate()}, recall_rate={eval_result.get_recall_rate()}")
                    else:
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
                        except Exception as e:
                            logger.error(f"[multi_variant] {config_key}评估失败: {e}")
                            eval_result = None
                    
                    config_info = EXPERIMENT_CONFIGS.get(config_key, ABLATION_CONFIGS.get(config_key, {"name": config_key}))

                    # 根据配置选择正确的LLM统计源
                    stats_source_key = CONFIG_LLM_STATS_SOURCE.get(config_key)
                    if stats_source_key == "llm_stats_full":
                        config_llm_stats = llm_stats_full
                    elif stats_source_key == "llm_stats_no_term_norm":
                        config_llm_stats = llm_stats_no_term_norm
                    elif stats_source_key == "llm_stats_no_hallucination":
                        config_llm_stats = llm_stats_no_hallucination
                    else:
                        config_llm_stats = llm_stats  # fallback

                    logger.info(f"[DEBUG] {config_key}: 开始计算LLM stats, stats_source={stats_source_key}")
                    logger.info(f"[DEBUG]   - config_llm_stats: total_calls={config_llm_stats.get('total_calls', 0)}, stage_breakdown存在={config_llm_stats.get('stage_breakdown') is not None}")

                    config_llm_calls, config_char_count, config_token_count, config_actual_latency = self._compute_llm_stats_for_config(
                        config_key, config_llm_stats
                    )

                    # [DEBUG] 记录LLM stats计算结果
                    logger.info(f"[DEBUG] {config_key}: LLM stats计算完成")
                    logger.info(f"[DEBUG]   - config_llm_calls={config_llm_calls}")
                    logger.info(f"[DEBUG]   - config_char_count={config_char_count}")
                    logger.info(f"[DEBUG]   - config_token_count={config_token_count}")
                    logger.info(f"[DEBUG]   - config_actual_latency={config_actual_latency}")

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
                            logger.warning(f"[DEBUG] {config_key}: simplified_llm_stats.total_calls=0，保留_compute_llm_stats_for_config的计算结果 - calls={config_llm_calls}, chars={config_char_count}, tokens={config_token_count}")
                    else:
                        # 使用对应路径的stage_breakdown，根据CONFIG_STAGE_GROUPS提取对应阶段
                        config_stage_breakdown_source = config_llm_stats.get("stage_breakdown", {})
                        config_stage_group = CONFIG_STAGE_GROUPS.get(config_key)
                        if config_stage_group and config_stage_breakdown_source:
                            # 提取对应阶段的stage_breakdown
                            config_stage_breakdown = {
                                stage: config_stage_breakdown_source.get(stage, {})
                                for stage in config_stage_group
                                if stage in config_stage_breakdown_source
                            }
                            logger.info(f"[DEBUG] {config_key}: 提取对应阶段的stage_breakdown - stages={config_stage_group}, extracted_keys={list(config_stage_breakdown.keys())}")
                        else:
                            # 无法提取，使用空dict
                            config_stage_breakdown = {}
                            logger.warning(f"[DEBUG] {config_key}: 无法提取stage_breakdown, config_stage_group={config_stage_group}")
                    
                    config_elapsed = config_actual_latency if config_actual_latency > 0 else (fork_elapsed_actual if emr_key else simplified_elapsed)
                    
                    # [DEBUG] 记录最终elapsed计算
                    logger.info(f"[DEBUG] {config_key}: elapsed计算 - config_elapsed={config_elapsed}, fork_elapsed_actual={fork_elapsed_actual}, simplified_elapsed={simplified_elapsed}")
                    
                    entry = self._build_jsonl_entry(
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
                    
                    run_record = self._save_benchmark_run(
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
                        stage_breakdown=config_stage_breakdown,  # 新增：传入对应配置的stage_breakdown
                        error_message=None
                    )
                    
                    # [DEBUG] 记录数据库保存结果
                    logger.info(f"[DEBUG] {config_key}: 数据库保存完成")
                    logger.info(f"[DEBUG]   - run_record.id={run_record.id}")
                    logger.info(f"[DEBUG]   - run_record.llm_call_count={run_record.llm_call_count}")
                    logger.info(f"[DEBUG]   - run_record.char_count={run_record.char_count}")
                    logger.info(f"[DEBUG]   - run_record.token_count={run_record.token_count}")
                    logger.info(f"[DEBUG]   - run_record.elapsed_seconds={run_record.elapsed_seconds}")
                    
                    if eval_result:
                        self._save_benchmark_evaluation(
                            benchmark_db,
                            run_record,
                            eval_result,
                            quality_metrics,
                            error_message=None
                        )
                    
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
        
        for config_key in ["end_to_end", "no_verification", "full", "standard", "no_hallucination", "no_term_norm", "simplified"]:
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
    parser.add_argument("--sample-id", type=str, default=None,
                        help="指定样本ID进行评估（优先级高于--limit）")
    parser.add_argument("--interval", type=float, default=2.0,
                        help="LLM 调用间隔秒数 (default: 2.0)")
    parser.add_argument("--sequential", action="store_true",
                        help="串行处理：禁用并行处理以避免API速率限制")
    parser.add_argument("--re-evaluate", action="store_true",
                        help="重新评估：对已有结果重新运行LLM评估（默认跳过已完成的样本）")
    args = parser.parse_args()

    runner = FullBenchmarkRunner(
        samples_file=args.samples,
        output_dir=args.output_dir,
        request_interval=args.interval,
        re_evaluate=args.re_evaluate,
        sample_id=args.sample_id,
        sequential=args.sequential
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