"""
Benchmark 评估编排器

调用四层评估（一致性/完整性/质量/安全），记录每次 LLM 调用的 prompt/response 长度。
"""

import logging
import json
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field

from backend.services.evaluation.base import BaseEvaluator
from backend.services.evaluation.consistency import ConsistencyEvaluator
from backend.services.evaluation.completeness import CompletenessEvaluator
from backend.services.evaluation.quality import QualityEvaluator
from backend.services.evaluation.safety import SafetyEvaluator

logger = logging.getLogger(__name__)


@dataclass
class LLMCallRecord:
    stage: str
    evaluator: str
    prompt_length: int
    response_length: int
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    success: bool = True
    error_message: Optional[str] = None


class LoggedEvaluator(BaseEvaluator):
    def __init__(self, llm_service, evaluator_name: str, call_records: List[LLMCallRecord]):
        self.llm_service = llm_service
        self.evaluator_name = evaluator_name
        self.call_records = call_records
        self._original_call_llm_json = None

    def _call_llm_json(
        self,
        template_name: str,
        temperature: float = 0.1,
        **kwargs
    ) -> Dict[str, Any]:
        prompt = self.llm_service.prompt_manager.render(template_name, **kwargs)
        prompt_length = len(prompt)

        logger.info(f"[{self.evaluator_name}] LLM调用 - 模板: {template_name}, prompt长度: {prompt_length}")

        try:
            # 关闭thinking模式：评估是模式匹配任务，不需要深度推理
            response = self.llm_service.generate(
                prompt=prompt,
                temperature=temperature,
                thinking_enabled=False
            )
            response_length = len(response.text)
            
            usage = response.usage if hasattr(response, 'usage') else {}
            prompt_tokens = usage.get('prompt_tokens')
            completion_tokens = usage.get('completion_tokens')
            total_tokens = usage.get('total_tokens')

            self.call_records.append(LLMCallRecord(
                stage="evaluation",
                evaluator=self.evaluator_name,
                prompt_length=prompt_length,
                response_length=response_length,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                success=True
            ))

            logger.info(f"[{self.evaluator_name}] LLM响应长度: {response_length}, tokens: {total_tokens}")

            return self._parse_json_response(response.text)

        except Exception as e:
            error_msg = str(e)
            self.call_records.append(LLMCallRecord(
                stage="evaluation",
                evaluator=self.evaluator_name,
                prompt_length=prompt_length,
                response_length=0,
                success=False,
                error_message=error_msg
            ))
            logger.error(f"[{self.evaluator_name}] LLM调用失败: {error_msg}")
            raise

    def _parse_json_response(self, text: str) -> Dict[str, Any]:
        try:
            json_start = text.find("{")
            json_end = text.rfind("}") + 1
            if json_start != -1 and json_end > json_start:
                json_str = text[json_start:json_end]
                return json.loads(json_str)
            else:
                raise ValueError("No JSON found in response")
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse JSON response: {e}")

    def evaluate(self, *args, **kwargs) -> Dict[str, Any]:
        raise NotImplementedError("Subclass must implement evaluate()")


class LoggedConsistencyEvaluator(LoggedEvaluator):
    def __init__(self, llm_service, call_records: List[LLMCallRecord]):
        super().__init__(llm_service, "consistency", call_records)
        self._base_evaluator = ConsistencyEvaluator(llm_service)

    def evaluate(
        self,
        transcript: str,
        emr_content: Dict[str, Any],
        key_facts: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        logger.info(f"[consistency] 开始一致性评估, use_key_facts={key_facts is not None}")

        emr_text = self._format_emr_content(emr_content)

        # 优先使用 key_facts：合并事实一致性检查和内部一致性检查为一次 LLM 调用
        if key_facts:
            combined_result = self._call_llm_json(
                "consistency_combined_check",
                transcript=transcript,
                key_facts=json.dumps(key_facts, ensure_ascii=False, indent=2),
                emr_content=emr_text
            )

            result = {
                "facts": combined_result.get("facts", []),
                "summary": combined_result.get("summary", {
                    "total_facts": 0,
                    "supported_count": 0,
                    "unsupported_count": 0,
                    "support_rate": 0.0
                }),
                "internal_conflicts": combined_result.get("internal_conflicts", []),
                "consistency_score": combined_result.get("consistency_score", 1.0)
            }
        else:
            # 无 key_facts 时仍使用两次调用（consistency_check 不含内部一致性）
            consistency_result = self._call_llm_json(
                "consistency_check",
                transcript=transcript,
                emr_content=emr_text
            )

            internal_result = self._call_llm_json(
                "internal_consistency_check",
                emr_content=emr_text
            )

            result = {
                "facts": consistency_result.get("facts", []),
                "summary": consistency_result.get("summary", {
                    "total_facts": 0,
                    "supported_count": 0,
                    "unsupported_count": 0,
                    "support_rate": 0.0
                }),
                "internal_conflicts": internal_result.get("conflicts", []),
                "consistency_score": internal_result.get("consistency_score", 1.0)
            }

        support_rate = result["summary"].get("support_rate", 0)
        logger.info(f"[consistency] 评估完成: support_rate={support_rate}")

        return result


class LoggedCompletenessEvaluator(LoggedEvaluator):
    def __init__(self, llm_service, call_records: List[LLMCallRecord]):
        super().__init__(llm_service, "completeness", call_records)
        self._base_evaluator = CompletenessEvaluator(llm_service)

    def extract_key_facts(self, transcript: str) -> Dict[str, Any]:
        logger.info(f"[completeness] 提取关键事实")

        result = self._call_llm_json(
            "key_fact_extraction",
            transcript=transcript
        )

        total_count = result.get("total_count", 0)
        logger.info(f"[completeness] 提取到 {total_count} 条关键事实")

        return result

    def evaluate(self, key_facts: Dict[str, Any], emr_content: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"[completeness] 开始完整性评估")

        emr_text = self._format_emr_content(emr_content)

        result = self._call_llm_json(
            "completeness_check",
            key_facts=json.dumps(key_facts, ensure_ascii=False, indent=2),
            emr_content=emr_text
        )

        recall_rate = result.get("summary", {}).get("recall_rate", 0)
        omission_rate = result.get("summary", {}).get("omission_rate", 0)
        logger.info(f"[completeness] 评估完成: recall_rate={recall_rate}, omission_rate={omission_rate}")

        return result


class LoggedQualityEvaluator(LoggedEvaluator):
    def __init__(self, llm_service, call_records: List[LLMCallRecord]):
        super().__init__(llm_service, "quality", call_records)
        self._base_evaluator = QualityEvaluator(llm_service)

    def evaluate(self, emr_content: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"[quality] 开始文档质量评估")

        emr_text = self._format_emr_content(emr_content)

        result = self._call_llm_json(
            "document_quality_check",
            emr_content=emr_text
        )

        total_score = result.get("total_score", 0)
        logger.info(f"[quality] 评估完成: total_score={total_score}")

        return result


class LoggedSafetyEvaluator(LoggedEvaluator):
    def __init__(self, llm_service, call_records: List[LLMCallRecord]):
        super().__init__(llm_service, "safety", call_records)
        self._base_evaluator = SafetyEvaluator(llm_service)

    def evaluate(self, transcript: str, emr_content: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"[safety] 开始安全风险评估")

        emr_text = self._format_emr_content(emr_content)

        result = self._call_llm_json(
            "safety_risk_check",
            transcript=transcript,
            emr_content=emr_text
        )

        has_high_risk = result.get("has_high_risk", False)
        high_risk_count = result.get("high_risk_count", 0)
        logger.info(f"[safety] 评估完成: has_high_risk={has_high_risk}, count={high_risk_count}")

        return result


@dataclass
class BenchmarkEvaluationResult:
    consistency: Optional[Dict[str, Any]] = None
    completeness: Optional[Dict[str, Any]] = None
    quality: Optional[Dict[str, Any]] = None
    safety: Optional[Dict[str, Any]] = None
    llm_calls: List[LLMCallRecord] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def get_support_rate(self) -> Optional[float]:
        if self.consistency and "summary" in self.consistency:
            return self.consistency["summary"].get("support_rate")
        return None

    def get_hallucination_rate(self) -> Optional[float]:
        if self.consistency and "summary" in self.consistency:
            support_rate = self.consistency["summary"].get("support_rate", 1.0)
            return 1.0 - support_rate
        return None

    def get_recall_rate(self) -> Optional[float]:
        if self.completeness and "summary" in self.completeness:
            return self.completeness["summary"].get("recall_rate")
        return None

    def get_omission_rate(self) -> Optional[float]:
        if self.completeness and "summary" in self.completeness:
            summary = self.completeness["summary"]
            if "omission_rate" in summary:
                return summary["omission_rate"]
            total_facts = summary.get("total_facts", 0)
            none_coverage_count = summary.get("none_coverage_count", 0)
            if total_facts > 0:
                return none_coverage_count / total_facts
        return None

    def get_quality_score(self) -> Optional[float]:
        if self.quality:
            return self.quality.get("total_score")
        return None

    def get_has_high_risk(self) -> Optional[bool]:
        if self.safety:
            return self.safety.get("has_high_risk")
        return None

    def get_total_llm_calls(self) -> int:
        return len(self.llm_calls)

    def get_total_char_count(self) -> int:
        return sum(c.prompt_length + c.response_length for c in self.llm_calls)

    def get_total_tokens(self) -> Optional[int]:
        tokens = [c.total_tokens for c in self.llm_calls if c.total_tokens is not None]
        return sum(tokens) if tokens else None

    def get_avg_tokens(self) -> Optional[float]:
        tokens = [c.total_tokens for c in self.llm_calls if c.total_tokens is not None]
        return sum(tokens) / len(tokens) if tokens else None


class BenchmarkEvaluator:
    def __init__(self, llm_service):
        self.llm_service = llm_service

    def evaluate_all(
        self,
        transcript: str,
        emr_content: Dict[str, Any],
        sample_id: str = "",
        key_facts: Optional[Dict[str, Any]] = None,
        skip_quality_safety: bool = False
    ) -> BenchmarkEvaluationResult:
        """
        四层评估

        Args:
            skip_quality_safety: 跳过 quality 和 safety 评估器，仅运行 consistency + completeness，
                                 适用于量化评估场景（所需指标仅依赖前两层）
        """
        result = BenchmarkEvaluationResult()
        call_records: List[LLMCallRecord] = []

        logger.info(f"[BenchmarkEvaluator] 开始评估 - sample_id={sample_id}, key_facts={key_facts is not None}, skip_quality_safety={skip_quality_safety}")

        # 先提取 key_facts，供 consistency 和 completeness 共用
        if key_facts is None:
            try:
                completeness_eval_for_extraction = LoggedCompletenessEvaluator(self.llm_service, call_records)
                key_facts = completeness_eval_for_extraction.extract_key_facts(transcript)
                logger.info(f"[BenchmarkEvaluator] 提取key_facts完成")
            except Exception as e:
                error_msg = f"Key fact extraction failed: {str(e)}"
                logger.error(f"[BenchmarkEvaluator] {error_msg}")
                result.errors.append(error_msg)
        else:
            logger.info(f"[BenchmarkEvaluator] 使用传入的key_facts，跳过提取")

        try:
            consistency_eval = LoggedConsistencyEvaluator(self.llm_service, call_records)
            result.consistency = consistency_eval.evaluate(transcript, emr_content, key_facts=key_facts)
        except Exception as e:
            error_msg = f"ConsistencyEvaluator failed: {str(e)}"
            logger.error(f"[BenchmarkEvaluator] {error_msg}")
            result.errors.append(error_msg)

        try:
            completeness_eval = LoggedCompletenessEvaluator(self.llm_service, call_records)
            result.completeness = completeness_eval.evaluate(key_facts, emr_content)
        except Exception as e:
            error_msg = f"CompletenessEvaluator failed: {str(e)}"
            logger.error(f"[BenchmarkEvaluator] {error_msg}")
            result.errors.append(error_msg)

        if not skip_quality_safety:
            try:
                quality_eval = LoggedQualityEvaluator(self.llm_service, call_records)
                result.quality = quality_eval.evaluate(emr_content)
            except Exception as e:
                error_msg = f"QualityEvaluator failed: {str(e)}"
                logger.error(f"[BenchmarkEvaluator] {error_msg}")
                result.errors.append(error_msg)

            try:
                safety_eval = LoggedSafetyEvaluator(self.llm_service, call_records)
                result.safety = safety_eval.evaluate(transcript, emr_content)
            except Exception as e:
                error_msg = f"SafetyEvaluator failed: {str(e)}"
                logger.error(f"[BenchmarkEvaluator] {error_msg}")
                result.errors.append(error_msg)

        result.llm_calls = call_records

        logger.info(f"[BenchmarkEvaluator] 评估完成 - LLM调用次数: {len(call_records)}, "
                    f"support_rate: {result.get_support_rate()}, "
                    f"recall_rate: {result.get_recall_rate()}")

        return result