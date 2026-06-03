"""
LLM调用统计收集器

用于收集Pipeline各阶段的LLM调用统计信息，包括：
- 调用次数
- 字符消耗（prompt_length + response_length）
- Token消耗（prompt_tokens, completion_tokens, total_tokens）

使用方式：
1. 在PipelineContext中初始化LLMStatsCollector实例
2. 各Stage通过ctx.llm_stats.record_call()记录每次LLM调用
3. process_with_fork返回时包含统计汇总
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


@dataclass
class LLMCallRecord:
    stage: str
    prompt_length: int
    response_length: int
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    actual_latency: Optional[float] = None
    success: bool = True
    error_message: Optional[str] = None


class LLMStatsCollector:
    def __init__(self):
        self._calls: List[LLMCallRecord] = []
        self._stage_counts: Dict[str, int] = {}
    
    def record_call(
        self,
        stage: str,
        prompt_length: int,
        response_length: int,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
        total_tokens: Optional[int] = None,
        actual_latency: Optional[float] = None,
        success: bool = True,
        error_message: Optional[str] = None
    ) -> LLMCallRecord:
        record = LLMCallRecord(
            stage=stage,
            prompt_length=prompt_length,
            response_length=response_length,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            actual_latency=actual_latency,
            success=success,
            error_message=error_message
        )
        self._calls.append(record)
        self._stage_counts[stage] = self._stage_counts.get(stage, 0) + 1
        
        logger.debug(
            f"[LLMStats] 记录调用: stage={stage}, "
            f"prompt_len={prompt_length}, response_len={response_length}, "
            f"tokens={total_tokens}, latency={actual_latency:.2f}s, success={success}"
        )
        
        return record
    
    def record_from_response(
        self,
        stage: str,
        prompt: str,
        response: Any,
        success: bool = True,
        error_message: Optional[str] = None
    ) -> LLMCallRecord:
        prompt_length = len(prompt) if prompt else 0
        response_length = len(response.text) if hasattr(response, 'text') else 0
        
        usage = {}
        if hasattr(response, 'usage') and response.usage:
            usage = response.usage
        
        actual_latency = None
        if hasattr(response, 'actual_latency') and response.actual_latency:
            actual_latency = response.actual_latency
        
        return self.record_call(
            stage=stage,
            prompt_length=prompt_length,
            response_length=response_length,
            prompt_tokens=usage.get('prompt_tokens'),
            completion_tokens=usage.get('completion_tokens'),
            total_tokens=usage.get('total_tokens'),
            actual_latency=actual_latency,
            success=success,
            error_message=error_message
        )
    
    def get_total_calls(self) -> int:
        return len(self._calls)
    
    def get_total_char_count(self) -> int:
        return sum(c.prompt_length + c.response_length for c in self._calls)
    
    def get_total_tokens(self) -> Optional[int]:
        tokens = [c.total_tokens for c in self._calls if c.total_tokens is not None]
        return sum(tokens) if tokens else None
    
    def get_prompt_tokens(self) -> Optional[int]:
        tokens = [c.prompt_tokens for c in self._calls if c.prompt_tokens is not None]
        return sum(tokens) if tokens else None
    
    def get_completion_tokens(self) -> Optional[int]:
        tokens = [c.completion_tokens for c in self._calls if c.completion_tokens is not None]
        return sum(tokens) if tokens else None
    
    def get_total_actual_latency(self) -> float:
        latencies = [c.actual_latency for c in self._calls if c.actual_latency is not None]
        return sum(latencies) if latencies else 0.0
    
    def get_stage_breakdown(self) -> Dict[str, Dict[str, Any]]:
        breakdown = {}
        for stage, count in self._stage_counts.items():
            stage_calls = [c for c in self._calls if c.stage == stage]
            breakdown[stage] = {
                "call_count": count,
                "total_chars": sum(c.prompt_length + c.response_length for c in stage_calls),
                "total_tokens": sum(c.total_tokens for c in stage_calls if c.total_tokens),
                "total_latency": sum(c.actual_latency for c in stage_calls if c.actual_latency),
            }
        return breakdown
    
    def get_summary(self) -> Dict[str, Any]:
        return {
            "total_calls": self.get_total_calls(),
            "total_char_count": self.get_total_char_count(),
            "total_tokens": self.get_total_tokens(),
            "prompt_tokens": self.get_prompt_tokens(),
            "completion_tokens": self.get_completion_tokens(),
            "total_actual_latency": self.get_total_actual_latency(),
            "stage_breakdown": self.get_stage_breakdown()
        }
    
    def merge(self, other: LLMStatsCollector) -> None:
        for call in other._calls:
            self._calls.append(call)
            self._stage_counts[call.stage] = self._stage_counts.get(call.stage, 0) + 1
    
    def reset(self) -> None:
        self._calls = []
        self._stage_counts = {}