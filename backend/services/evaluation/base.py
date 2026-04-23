"""
评估器基类

提供LLM调用和JSON解析的通用功能
"""

from abc import ABC, abstractmethod
from typing import Dict, Any
import logging
import json

logger = logging.getLogger(__name__)


class BaseEvaluator(ABC):
    def __init__(self, llm_service):
        self.llm_service = llm_service
        
    @abstractmethod
    def evaluate(self, *args, **kwargs) -> Dict[str, Any]:
        pass
        
    def _call_llm_json(
        self, 
        template_name: str, 
        temperature: float = 0.1,
        **kwargs
    ) -> Dict[str, Any]:
        prompt = self.llm_service.prompt_manager.render(template_name, **kwargs)
        
        response = self.llm_service.generate(
            prompt=prompt,
            temperature=temperature
        )
        
        return self._parse_json_response(response.text)
        
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
            logger.error(f"Failed to parse JSON: {e}")
            logger.error(f"Response text: {text[:500]}")
            raise ValueError(f"Failed to parse JSON response: {e}")
            
    def _validate_result(
        self, 
        result: Dict[str, Any], 
        required_fields: list
    ) -> bool:
        for field in required_fields:
            if field not in result:
                logger.error(f"Missing required field: {field}")
                return False
        return True
        
    def _format_emr_content(self, emr_content: Dict[str, Any]) -> str:
        sections = []
        
        if "subjective" in emr_content:
            text = emr_content["subjective"].get("text", "")
            if text:
                sections.append(f"【主观资料(S)】\n{text}")
            
        if "objective" in emr_content:
            text = emr_content["objective"].get("text", "")
            if text:
                sections.append(f"【客观资料(O)】\n{text}")
            
        if "assessment" in emr_content:
            text = emr_content["assessment"].get("text", "")
            if text:
                sections.append(f"【评估(A)】\n{text}")
            
        if "plan" in emr_content:
            text = emr_content["plan"].get("text", "")
            if text:
                sections.append(f"【计划(P)】\n{text}")
            
        return "\n\n".join(sections)
