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
        
        logger.info(f"评估器LLM调用 - 模板: {template_name}")
        logger.debug(f"评估器LLM调用 - prompt长度: {len(prompt)} 字符")
        
        # 关闭thinking模式：评估是模式匹配任务，不需要深度推理
        response = self.llm_service.generate(
            prompt=prompt,
            temperature=temperature,
            thinking_enabled=False
        )
        
        logger.info(f"评估器LLM响应长度: {len(response.text)} 字符")
        logger.debug(f"评估器LLM响应内容:\n{response.text}")
        
        return self._parse_json_response(response.text)
        
    def _parse_json_response(self, text: str) -> Dict[str, Any]:
        logger.info(f"开始解析评估器JSON响应, 响应长度: {len(text)} 字符")
        try:
            json_start = text.find("{")
            json_end = text.rfind("}") + 1
            if json_start != -1 and json_end > json_start:
                json_str = text[json_start:json_end]
                result = json.loads(json_str)
                logger.info(f"评估器JSON解析成功")
                return result
            else:
                logger.error(f"评估器响应中未找到JSON对象")
                logger.error(f"响应内容:\n{text}")
                raise ValueError("No JSON found in response")
        except json.JSONDecodeError as e:
            logger.error(f"评估器JSON解析失败: {e}")
            logger.error(f"响应内容:\n{text}")
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
        """将EMR JSON格式化为评估器可读的文本。

        同时输出章节概要(text)和各子字段的详细内容(value)，
        确保评估器能看到完整信息，避免因只看到概要而误判遗漏。
        """
        sections = []

        section_configs = {
            "subjective": {
                "label": "【主观资料(S)】",
                "subfields": ["chief_complaint", "history_present_illness", "denied_symptoms", "past_history"]
            },
            "objective": {
                "label": "【客观资料(O)】",
                "subfields": ["physical_examination", "auxiliary_examination"]
            },
            "assessment": {
                "label": "【评估(A)】",
                "subfields": ["diagnosis"]
            },
            "plan": {
                "label": "【计划(P)】",
                "subfields": ["treatment", "advice"]
            }
        }

        for section_key, config in section_configs.items():
            if section_key not in emr_content:
                continue

            sec = emr_content[section_key]
            if not isinstance(sec, dict):
                continue

            lines = [config["label"]]

            # 输出章节概要（如有）
            text = sec.get("text", "")
            if text and isinstance(text, str) and text.strip():
                lines.append(f"  [概要]: {text.strip()}")

            # 始终输出各子字段的详细内容
            for subfield in config["subfields"]:
                if subfield in sec and isinstance(sec[subfield], dict):
                    val = sec[subfield].get("value", "")
                    if val and isinstance(val, str) and val.strip():
                        lines.append(f"  [{subfield}]: {val.strip()}")

            if len(lines) > 1:
                sections.append("\n".join(lines))

        return "\n\n".join(sections)
