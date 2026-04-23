"""
文档质量评估服务

评估病历的文档质量，包括结构完整性、组织清晰度、表达简洁性、可理解性和术语规范性
"""

from typing import Dict, Any
from .base import BaseEvaluator
import logging

logger = logging.getLogger(__name__)


class QualityEvaluator(BaseEvaluator):
    def evaluate(self, emr_content: Dict[str, Any]) -> Dict[str, Any]:
        logger.info("Starting quality evaluation")
        
        emr_text = self._format_emr_content(emr_content)
        
        result = self._call_llm_json(
            "document_quality_check",
            emr_content=emr_text
        )
        
        total_score = result.get("total_score", 0)
        logger.info(f"Quality evaluation completed: total_score={total_score}")
        
        return result
