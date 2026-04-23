"""
完整性评估服务

评估病历对关键事实的覆盖情况
"""

from typing import Dict, Any
from .base import BaseEvaluator
import logging
import json

logger = logging.getLogger(__name__)


class CompletenessEvaluator(BaseEvaluator):
    def extract_key_facts(self, transcript: str) -> Dict[str, Any]:
        logger.info("Extracting key facts from transcript")
        
        result = self._call_llm_json(
            "key_fact_extraction",
            transcript=transcript
        )
        
        total_count = result.get("total_count", 0)
        logger.info(f"Extracted {total_count} key facts")
        
        return result
        
    def evaluate(
        self, 
        key_facts: Dict[str, Any], 
        emr_content: Dict[str, Any]
    ) -> Dict[str, Any]:
        logger.info("Starting completeness evaluation")
        
        emr_text = self._format_emr_content(emr_content)
        
        result = self._call_llm_json(
            "completeness_check",
            key_facts=json.dumps(key_facts, ensure_ascii=False, indent=2),
            emr_content=emr_text
        )
        
        recall_rate = result.get("summary", {}).get("recall_rate", 0)
        logger.info(f"Completeness evaluation completed: recall_rate={recall_rate}")
        
        return result
