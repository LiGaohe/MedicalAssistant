"""
安全风险评估服务

评估病历中是否存在高风险错误
"""

from typing import Dict, Any
from .base import BaseEvaluator
import logging

logger = logging.getLogger(__name__)


class SafetyEvaluator(BaseEvaluator):
    def evaluate(
        self, 
        transcript: str, 
        emr_content: Dict[str, Any]
    ) -> Dict[str, Any]:
        logger.info("Starting safety evaluation")
        
        emr_text = self._format_emr_content(emr_content)
        
        result = self._call_llm_json(
            "safety_risk_check",
            transcript=transcript,
            emr_content=emr_text
        )
        
        has_high_risk = result.get("has_high_risk", False)
        high_risk_count = result.get("high_risk_count", 0)
        
        logger.info(f"Safety evaluation completed: has_high_risk={has_high_risk}, count={high_risk_count}")
        
        return result
