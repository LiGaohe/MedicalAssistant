"""
一致性评估服务

评估病历内容是否被原始对话支持，以及内部是否存在自相矛盾
"""

from typing import Dict, Any
from .base import BaseEvaluator
import logging
import json

logger = logging.getLogger(__name__)


class ConsistencyEvaluator(BaseEvaluator):
    def evaluate(
        self, 
        transcript: str, 
        emr_content: Dict[str, Any]
    ) -> Dict[str, Any]:
        logger.info("Starting consistency evaluation")
        
        emr_text = self._format_emr_content(emr_content)
        
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
        consistency_score = result.get("consistency_score", 1.0)
        logger.info(f"Consistency evaluation completed: support_rate={support_rate}, consistency_score={consistency_score}")
        
        return result
