import logging
import threading
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session
from .base import LLMAdapter, LLMRequest, LLMResponse
from .openai_compatible_adapter import OpenAICompatibleAdapter
from .prompts import PromptManager
from ...models.llm_config import LLMConfig
from ...utils.logger import logger


def setup_llm_raw_logger() -> logging.Logger:
    llm_logger = logging.getLogger("llm_raw_response")
    if llm_logger.handlers:
        return llm_logger
    
    llm_logger.setLevel(logging.DEBUG)
    
    log_dir = Path("data/logs/llm_raw")
    log_dir.mkdir(parents=True, exist_ok=True)
    
    log_file = log_dir / f"llm_raw_{datetime.now().strftime('%Y%m%d_%H')}.log"
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_format = logging.Formatter(
        '%(asctime)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_format)
    
    llm_logger.addHandler(file_handler)
    return llm_logger


class LLMService:
    def __init__(self, db: Session):
        self.db = db
        self.adapters: Dict[str, LLMAdapter] = {}
        self.adapter_configs: Dict[str, Dict[str, Any]] = {}
        self.prompt_manager = PromptManager()
        self._config_lock = threading.Lock()
        self._load_adapters()
        self._llm_raw_logger = setup_llm_raw_logger()
        
    def _load_adapters(self):
        configs = self.db.query(LLMConfig).filter(LLMConfig.is_active == True).all()
        for config in configs:
            try:
                adapter = self._create_adapter(config)
                self.adapters[config.config_name] = adapter
                self.adapter_configs[config.config_name] = {
                    "max_tokens": config.max_tokens,
                    "temperature": float(config.temperature),
                    "json_mode": config.json_mode,
                    "thinking_enabled": config.thinking_enabled,
                    "thinking_effort": config.thinking_effort
                }
            except Exception as e:
                print(f"Failed to load adapter {config.config_name}: {e}")
                
    def _create_adapter(self, config: LLMConfig) -> LLMAdapter:
        config_dict = {
            "model_name": config.model_name,
            "api_endpoint": config.api_endpoint,
            "api_key": config.api_key,
            "max_tokens": config.max_tokens,
            "temperature": float(config.temperature),
            "provider_name": config.provider,
            "json_mode": config.json_mode,
            "thinking_enabled": config.thinking_enabled,
            "thinking_effort": config.thinking_effort
        }
        
        return OpenAICompatibleAdapter(config_dict)
            
    def generate(
        self, 
        prompt: str, 
        config_name: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        json_mode: Optional[bool] = None,
        thinking_enabled: Optional[bool] = None,
        thinking_effort: Optional[str] = None,
        timeout: Optional[float] = None,
        call_id: Optional[str] = None
    ) -> LLMResponse:
        if not self.adapters:
            with self._config_lock:
                all_configs = self.db.query(LLMConfig).all()
            logger.error(f"No active LLM adapters available. 数据库中共有{len(all_configs)}条配置:")
            for c in all_configs:
                logger.error(f"  - config_name={c.config_name}, is_active={c.is_active}, provider={c.provider}")
            raise RuntimeError("No active LLM adapters available")
            
        adapter_name = config_name or list(self.adapters.keys())[0]
        logger.debug(f"请求使用adapter: {adapter_name}, 可用adapters: {list(self.adapters.keys())}")
        
        if adapter_name not in self.adapters:
            logger.error(f"Adapter '{adapter_name}' not found. 可用adapters: {list(self.adapters.keys())}")
            raise ValueError(f"Adapter '{adapter_name}' not found. Available: {list(self.adapters.keys())}")
            
        adapter = self.adapters[adapter_name]
        
        cached_config = self.adapter_configs.get(adapter_name)
        if cached_config is None:
            logger.error(f"缓存中未找到config_name={adapter_name}的配置")
            raise ValueError(f"LLM config '{adapter_name}' not found in cache")
        
        logger.debug(f"使用缓存配置: config_name={adapter_name}, max_tokens={cached_config['max_tokens']}, thinking_enabled={cached_config['thinking_enabled']}")
        
        request = LLMRequest(
            prompt=prompt,
            max_tokens=max_tokens or cached_config["max_tokens"],
            temperature=temperature or cached_config["temperature"],
            json_mode=json_mode if json_mode is not None else cached_config["json_mode"],
            thinking_enabled=thinking_enabled if thinking_enabled is not None else cached_config["thinking_enabled"],
            thinking_effort=thinking_effort or cached_config["thinking_effort"],
            timeout=timeout
        )
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        call_id = call_id or f"{adapter_name}_{timestamp}"
        
        logger.info(f"=== LLM调用开始 === call_id={call_id}, adapter={adapter_name}")
        logger.debug(f"[{call_id}] 请求提示词长度: {len(prompt)} 字符")
        logger.debug(f"[{call_id}] 请求配置: max_tokens={request.max_tokens}, temperature={request.temperature}, json_mode={request.json_mode}, thinking_enabled={request.thinking_enabled}")
        
        response = adapter.generate(request)
        
        logger.debug(f"LLM响应 - 模型: {response.model}, 提供商: {response.provider}")
        logger.debug(f"LLM响应 - finish_reason: {response.finish_reason}")
        logger.debug(f"LLM响应 - usage: {response.usage}")
        logger.info(f"LLM响应 - 返回文本长度: {len(response.text)} 字符")
        logger.debug(f"LLM响应 - 返回文本内容:\n{response.text}")
        
        self._llm_raw_logger.info(f"\n{'='*80}\n[LLM RAW RESPONSE] call_id={call_id}, adapter={adapter_name}, timestamp={timestamp}\n{'='*80}\n[PROMPT]\n{prompt}\n\n[RESPONSE - {response.model}]\n{response.text}\n{'='*80}\n")
        
        if not adapter.validate_response(response):
            logger.error(f"LLM响应验证失败")
            raise RuntimeError("Invalid LLM response")
            
        return response
        
    def generate_with_template(
        self,
        template_name: str,
        config_name: Optional[str] = None,
        **kwargs
    ) -> LLMResponse:
        prompt = self.prompt_manager.render(template_name, **kwargs)
        return self.generate(prompt, config_name)
        
    def generate_json(
        self,
        prompt: str,
        config_name: Optional[str] = None
    ) -> Dict[str, Any]:
        response = self.generate(prompt, config_name, json_mode=True)
        
        try:
            json_start = response.text.find("{")
            json_end = response.text.rfind("}") + 1
            if json_start != -1 and json_end > json_start:
                json_str = response.text[json_start:json_end]
                return json.loads(json_str)
            else:
                logger.error(f"LLM响应中未找到JSON对象")
                logger.error(f"原始响应内容:\n{response.text}")
                raise ValueError("No JSON found in response")
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {e}")
            logger.error(f"原始响应内容:\n{response.text}")
            raise ValueError(f"Failed to parse JSON response: {e}")
            
    def get_available_models(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": name,
                "model": adapter.model_name,
                "provider": adapter.provider_name,
                "available": adapter.is_available()
            }
            for name, adapter in self.adapters.items()
        ]
        
    def reload_adapters(self):
        self.adapters.clear()
        self.adapter_configs.clear()
        self._load_adapters()
