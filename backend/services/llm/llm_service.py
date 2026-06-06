import logging
import threading
import time
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List, Generator
from sqlalchemy.orm import Session
from .base import LLMAdapter, LLMRequest, LLMResponse, LLMStreamChunk
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
        call_id: Optional[str] = None,
        compression_dict: Optional[str] = None
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
            timeout=timeout,
            compression_dict=compression_dict
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

        # 记录缓存命中信息
        cached_tokens = response.cached_tokens if hasattr(response, 'cached_tokens') else 0
        if cached_tokens > 0:
            total_input = response.usage.get("prompt_tokens", 0)
            cache_rate = cached_tokens / total_input if total_input > 0 else 0
            logger.info(f"Prompt缓存命中: cached_tokens={cached_tokens}, cache_rate={cache_rate:.1%}")
        
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
        
    def generate_stream(
        self, 
        prompt: str, 
        config_name: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        json_mode: Optional[bool] = None,
        thinking_enabled: Optional[bool] = None,
        thinking_effort: Optional[str] = None,
        timeout: Optional[float] = None,
        call_id: Optional[str] = None,
        on_chunk: Optional[callable] = None,
        compression_dict: Optional[str] = None
    ) -> Generator[LLMStreamChunk, None, None]:
        """流式生成响应，避免一次性发送大量token导致限流和超时
        
        Args:
            prompt: 提示词
            config_name: 配置名称
            max_tokens: 最大token数
            temperature: 温度参数
            json_mode: JSON模式
            thinking_enabled: 是否启用思考模式
            thinking_effort: 思考模式强度
            timeout: 超时时间
            call_id: 调用ID
            on_chunk: chunk回调函数，用于实时处理每个chunk
            
        Yields:
            LLMStreamChunk: 流式响应的每个chunk
        """
        if not self.adapters:
            with self._config_lock:
                all_configs = self.db.query(LLMConfig).all()
            logger.error(f"No active LLM adapters available. 数据库中共有{len(all_configs)}条配置:")
            for c in all_configs:
                logger.error(f"  - config_name={c.config_name}, is_active={c.is_active}, provider={c.provider}")
            raise RuntimeError("No active LLM adapters available")
            
        adapter_name = config_name or list(self.adapters.keys())[0]
        logger.debug(f"流式请求使用adapter: {adapter_name}, 可用adapters: {list(self.adapters.keys())}")
        
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
            timeout=timeout,
            stream=True,
            compression_dict=compression_dict
        )
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        call_id = call_id or f"{adapter_name}_{timestamp}"
        
        logger.info(f"=== LLM流式调用开始 === call_id={call_id}, adapter={adapter_name}")
        logger.debug(f"[{call_id}] 流式请求提示词长度: {len(prompt)} 字符")
        logger.debug(f"[{call_id}] 流式请求配置: max_tokens={request.max_tokens}, temperature={request.temperature}, json_mode={request.json_mode}, thinking_enabled={request.thinking_enabled}")
        
        accumulated_text = ""
        accumulated_thinking = ""
        stream_start_time = time.time()
        chunk_count = 0
        
        try:
            for chunk in adapter.generate_stream(request):
                chunk_count += 1
                
                if not chunk.is_final:
                    if chunk.text:
                        accumulated_text += chunk.text
                        if on_chunk:
                            on_chunk(chunk)
                    yield chunk
                else:
                    final_latency = time.time() - stream_start_time
                    logger.info(f"LLM流式响应完成 - 总文本长度: {len(accumulated_text)} 字符, chunk数: {chunk_count}, 耗时: {final_latency:.2f}s")
                    logger.debug(f"LLM流式响应 - finish_reason: {chunk.finish_reason}, usage: {chunk.usage}")
                    
                    self._llm_raw_logger.info(f"\n{'='*80}\n[LLM STREAM RESPONSE] call_id={call_id}, adapter={adapter_name}, timestamp={timestamp}\n{'='*80}\n[PROMPT]\n{prompt}\n\n[RESPONSE - {chunk.model}]\n{accumulated_text}\n{'='*80}\n")
                    
                    yield chunk
                    
        except Exception as e:
            logger.error(f"LLM流式调用失败: {e}")
            raise
        
    def generate_stream_to_response(
        self,
        prompt: str,
        config_name: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        json_mode: Optional[bool] = None,
        thinking_enabled: Optional[bool] = None,
        thinking_effort: Optional[str] = None,
        timeout: Optional[float] = None,
        call_id: Optional[str] = None,
        on_chunk: Optional[callable] = None,
        compression_dict: Optional[str] = None
    ) -> LLMResponse:
        """流式生成响应，但返回完整的LLMResponse对象（兼容现有代码）
        
        这个方法内部使用流式处理，但对外返回完整的响应对象，
        方便现有代码逐步迁移到流式处理。
        """
        accumulated_text = ""
        accumulated_thinking = ""
        final_chunk = None
        stream_start_time = time.time()
        
        for chunk in self.generate_stream(
            prompt=prompt,
            config_name=config_name,
            max_tokens=max_tokens,
            temperature=temperature,
            json_mode=json_mode,
            thinking_enabled=thinking_enabled,
            thinking_effort=thinking_effort,
            timeout=timeout,
            call_id=call_id,
            on_chunk=on_chunk,
            compression_dict=compression_dict
        ):
            if chunk.is_final:
                final_chunk = chunk
                if chunk.text:
                    accumulated_text = chunk.text
                if chunk.thinking_content:
                    accumulated_thinking = chunk.thinking_content
            elif chunk.text:
                accumulated_text += chunk.text
        
        if final_chunk is None:
            raise RuntimeError("Stream ended without final chunk")

        final_latency = time.time() - stream_start_time

        # 从流式响应的usage中提取cached_tokens
        cached_tokens = 0
        if final_chunk.usage:
            prompt_tokens_details = final_chunk.usage.get("prompt_tokens_details", {})
            cached_tokens = prompt_tokens_details.get("cached_tokens", 0)
            if cached_tokens == 0:
                cached_tokens = final_chunk.usage.get("cache_read_input_tokens", 0)
        if cached_tokens > 0:
            total_input = final_chunk.usage.get("prompt_tokens", 0) if final_chunk.usage else 0
            cache_rate = cached_tokens / total_input if total_input > 0 else 0
            logger.info(f"Prompt缓存命中(流式): cached_tokens={cached_tokens}, cache_rate={cache_rate:.1%}")

        return LLMResponse(
            text=accumulated_text,
            model=final_chunk.model,
            provider=final_chunk.provider,
            usage=final_chunk.usage or {},
            finish_reason=final_chunk.finish_reason or "stop",
            thinking_content=accumulated_thinking,
            actual_latency=final_latency,
            cached_tokens=cached_tokens
        )
