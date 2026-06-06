from typing import Dict, Any, Generator
import httpx
import json
import time
from .base import LLMAdapter, LLMRequest, LLMResponse, LLMStreamChunk
from ...utils.logger import logger


class OpenAICompatibleAdapter(LLMAdapter):
    # 使用 chat_template_kwargs.enable_thinking 启用思考模式的模型前缀列表
    AGNES_MODEL_PREFIXES = ("agnes",)

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.api_key = config.get("api_key")
        self._is_agnes = any(
            config.get("model_name", "").startswith(prefix)
            for prefix in self.AGNES_MODEL_PREFIXES
        )
        
        api_endpoint = config.get("api_endpoint", "https://api.openai.com/v1")
        
        if not api_endpoint.endswith("/chat/completions"):
            if api_endpoint.endswith("/v1"):
                api_endpoint = f"{api_endpoint}/chat/completions"
            elif not api_endpoint.endswith("/"):
                api_endpoint = f"{api_endpoint}/v1/chat/completions"
            else:
                api_endpoint = f"{api_endpoint}v1/chat/completions"
        
        self.api_endpoint = api_endpoint
        self.provider_name = config.get("provider_name", "openai")
        self.max_retries = config.get("max_retries", 5)
        self.retry_delay = config.get("retry_delay", 5.0)
        self.request_interval = config.get("request_interval", 2.0)
        self._last_request_time = 0
        
    def generate(self, request: LLMRequest) -> LLMResponse:
        headers = {
            "Content-Type": "application/json"
        }
        
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        
        use_json_mode = request.json_mode or self.json_mode

        messages = []

        # system message: JSON指令 + 压缩字典（如有）
        system_parts = []
        if use_json_mode:
            system_parts.append("请以JSON格式输出结果。")
        if request.compression_dict:
            system_parts.append(request.compression_dict)
        if system_parts:
            messages.append({"role": "system", "content": "\n\n".join(system_parts)})

        # user message: 完整prompt
        messages.append({"role": "user", "content": request.prompt})
        
        payload = {
            "model": self.model_name,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "top_p": request.top_p
        }
        
        if request.stop_sequences:
            payload["stop"] = request.stop_sequences
        
        if use_json_mode:
            payload["response_format"] = {"type": "json_object"}
        
        use_thinking = request.thinking_enabled
        if use_thinking:
            if self._is_agnes:
                # Agnes模型使用 chat_template_kwargs.enable_thinking 启用思考
                payload["chat_template_kwargs"] = {"enable_thinking": True}
                payload["max_tokens"] = request.max_tokens * 5
                logger.debug(f"Agnes思考模式启用(chat_template_kwargs)，max_tokens从{request.max_tokens}调整为{payload['max_tokens']}")
            else:
                effort = request.thinking_effort if request.thinking_enabled else self.thinking_effort
                payload["thinking"] = {
                    "type": "enabled",
                    "reasoning_effort": effort
                }
                payload["max_tokens"] = request.max_tokens * 5
                logger.debug(f"思考模式启用，max_tokens从{request.max_tokens}调整为{payload['max_tokens']}以补偿reasoning_tokens")
        
        logger.info(f"LLM API请求 - 模型: {self.model_name}, 提供商: {self.provider_name}")
        logger.debug(f"LLM API请求 - endpoint: {self.api_endpoint}")
        logger.debug(f"LLM API请求 - max_tokens: {payload.get('max_tokens', request.max_tokens)}, temperature: {request.temperature}")
        logger.debug(f"LLM API请求 - json_mode: {use_json_mode}, thinking_enabled: {use_thinking}")
        logger.debug(f"LLM API请求 - payload: {json.dumps(payload, ensure_ascii=False)[:500]}")
        
        last_error = None
        total_actual_latency = 0.0
        
        for attempt in range(self.max_retries):
            try:
                elapsed = time.time() - self._last_request_time
                if elapsed < self.request_interval:
                    wait_time = self.request_interval - elapsed
                    time.sleep(wait_time)
                
                call_start = time.time()
                timeout = request.timeout if request.timeout else (300.0 if use_thinking else 120.0)
                logger.debug(f"LLM API请求超时设置: {timeout}秒 (请求级={request.timeout is not None})")
                with httpx.Client(timeout=timeout) as client:
                    response = client.post(
                        self.api_endpoint,
                        headers=headers,
                        json=payload
                    )
                    response.raise_for_status()
                    call_elapsed = time.time() - call_start
                    total_actual_latency += call_elapsed
                    
                    try:
                        data = response.json()
                    except (UnicodeDecodeError, json.JSONDecodeError) as e:
                        logger.warning(f"默认编码解析响应失败: {e}，尝试GBK/GB18030编码")
                        raw_bytes = response.content
                        for enc in ['gbk', 'gb18030', 'latin-1']:
                            try:
                                text = raw_bytes.decode(enc)
                                data = json.loads(text)
                                logger.info(f"使用 {enc} 编码成功解析响应")
                                break
                            except Exception:
                                continue
                        else:
                            raise RuntimeError(f"API响应解码失败(utf-8/gbk/gb18030/latin-1): {e}")
                    
                    logger.debug(f"LLM API原始响应: {json.dumps(data, ensure_ascii=False)[:2000]}")
                    logger.debug(f"LLM API实际调用耗时: {call_elapsed:.2f}s, 累计: {total_actual_latency:.2f}s")
                    
                    self._last_request_time = time.time()
                    
                    choices = data.get("choices", [])
                    if not choices:
                        error_info = data.get("error", {})
                        if error_info:
                            logger.error(f"LLM API返回错误: {error_info}")
                            raise RuntimeError(f"{self.provider_name} API error: {error_info}")
                        
                        usage = data.get("usage", {})
                        if usage and usage.get("total_tokens", 0) == 0:
                            logger.error(f"LLM API可能被限流或请求被拒绝")
                            raise RuntimeError(f"{self.provider_name} API rate limited or request rejected")
                        
                        logger.error(f"LLM API返回空choices, 原始响应: {json.dumps(data, ensure_ascii=False)[:500]}")
                        raise RuntimeError(f"{self.provider_name} API returned no choices. Response: {json.dumps(data, ensure_ascii=False)[:500]}")
                    
                    message = choices[0].get("message", {})
                    content = message.get("content")
                    thinking_content = message.get("reasoning_content") or message.get("reasoning")
                    finish_reason = choices[0].get("finish_reason", "stop")
                    
                    if thinking_content:
                        logger.debug(f"LLM API返回thinking内容, 长度: {len(thinking_content)} 字符")
                    
                    if finish_reason == "length":
                        logger.warning(f"LLM输出被截断 (finish_reason=length), max_tokens可能不足")
                        usage = data.get("usage", {})
                        reasoning_tokens = usage.get("completion_tokens_details", {}).get("reasoning_tokens", 0)
                        if reasoning_tokens > 0:
                            logger.warning(f"思考模式消耗reasoning_tokens: {reasoning_tokens}, 建议增大max_tokens")
                    
                    if not content:
                        if thinking_content and finish_reason == "length" and attempt < self.max_retries - 1:
                            current_max_tokens = payload.get("max_tokens", request.max_tokens)
                            new_max_tokens = min(current_max_tokens * 2, 131072)
                            if new_max_tokens > current_max_tokens:
                                logger.warning(
                                    f"内容为空且因max_tokens不足被截断(reasoning占用了token预算), "
                                    f"max_tokens: {current_max_tokens} → {new_max_tokens}, 重试..."
                                )
                                payload["max_tokens"] = new_max_tokens
                                time.sleep(self.retry_delay)
                                continue
                        logger.error(f"LLM API返回空content, finish_reason={finish_reason}, message: {message}")
                        raise RuntimeError(f"{self.provider_name} API returned empty content (finish_reason={finish_reason})")
                    
                    if content and len(content) > 0:
                        stripped_len = len(content.replace(' ', '').replace('\t', '').replace('\n', ''))
                        if stripped_len < len(content) * 0.1:
                            logger.warning(f"LLM响应疑似空白填充 (原始{len(content)}字符, 去空白后{stripped_len}字符), 可能因token截断导致")

                    # 提取cached tokens信息
                    cached_tokens = 0
                    usage_data = data.get("usage", {})
                    # OpenAI格式
                    prompt_tokens_details = usage_data.get("prompt_tokens_details", {})
                    cached_tokens = prompt_tokens_details.get("cached_tokens", 0)
                    # Anthropic格式（可能在顶层）
                    if cached_tokens == 0:
                        cached_tokens = usage_data.get("cache_read_input_tokens", 0)
                    if cached_tokens > 0:
                        logger.info(f"Prompt缓存命中: cached_tokens={cached_tokens}")

                    return LLMResponse(
                        text=content,
                        model=self.model_name,
                        provider=self.provider_name,
                        usage=data.get("usage", {}),
                        finish_reason=finish_reason,
                        raw_response=data,
                        thinking_content=thinking_content,
                        actual_latency=total_actual_latency,
                        cached_tokens=cached_tokens
                    )
                    
            except httpx.HTTPStatusError as e:
                error_detail = ""
                try:
                    error_body = e.response.text
                    error_detail = f", 响应内容: {error_body[:500]}"
                except:
                    pass
                logger.error(f"LLM API HTTP错误 (尝试 {attempt + 1}/{self.max_retries}): {str(e)}{error_detail}")
                last_error = RuntimeError(f"{self.provider_name} API error: {str(e)}{error_detail}")
            except httpx.HTTPError as e:
                logger.error(f"LLM API HTTP错误 (尝试 {attempt + 1}/{self.max_retries}): {str(e)}")
                last_error = RuntimeError(f"{self.provider_name} API error: {str(e)}")
            except (KeyError, IndexError) as e:
                logger.error(f"LLM API响应格式错误 (尝试 {attempt + 1}/{self.max_retries}): {str(e)}")
                last_error = RuntimeError(f"Invalid {self.provider_name} response format: {str(e)}")
            except RuntimeError as e:
                last_error = e
            
            if attempt < self.max_retries - 1:
                wait_time = self.retry_delay * (attempt + 1)
                logger.info(f"LLM API将在 {wait_time} 秒后重试...")
                time.sleep(wait_time)
        
        logger.error(f"LLM API调用失败, 已达到最大重试次数 {self.max_retries}")
        raise last_error
    
    def is_available(self) -> bool:
        try:
            if not self.api_key and "openai.com" not in self.api_endpoint:
                return True
            
            with httpx.Client(timeout=5.0) as client:
                base_url = self.api_endpoint.rsplit("/chat/completions", 1)[0]
                response = client.get(
                    f"{base_url}/models",
                    headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
                )
                return response.status_code == 200
        except:
            return False
    
    def generate_stream(self, request: LLMRequest) -> Generator[LLMStreamChunk, None, None]:
        """流式生成响应，避免一次性发送大量token导致限流和超时"""
        headers = {
            "Content-Type": "application/json"
        }
        
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        
        messages = []

        # system message: JSON指令 + 压缩字典（如有）
        system_parts = []
        if request.json_mode or self.json_mode:
            system_parts.append("请以JSON格式输出结果。")
        if request.compression_dict:
            system_parts.append(request.compression_dict)
        if system_parts:
            messages.append({"role": "system", "content": "\n\n".join(system_parts)})

        # user message: 完整prompt
        messages.append({"role": "user", "content": request.prompt})
        
        payload = {
            "model": self.model_name,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "top_p": request.top_p,
            "stream": True,
            "stream_options": {"include_usage": True}
        }
        
        if request.stop_sequences:
            payload["stop"] = request.stop_sequences
        
        if request.json_mode or self.json_mode:
            payload["response_format"] = {"type": "json_object"}
        
        use_thinking = request.thinking_enabled
        if use_thinking:
            if self._is_agnes:
                # Agnes模型使用 chat_template_kwargs.enable_thinking 启用思考
                payload["chat_template_kwargs"] = {"enable_thinking": True}
                payload["max_tokens"] = request.max_tokens * 5
                logger.debug(f"Agnes思考模式启用(chat_template_kwargs)，max_tokens从{request.max_tokens}调整为{payload['max_tokens']}")
            else:
                effort = request.thinking_effort if request.thinking_enabled else self.thinking_effort
                payload["thinking"] = {
                    "type": "enabled",
                    "reasoning_effort": effort
                }
                payload["max_tokens"] = request.max_tokens * 5
                logger.debug(f"思考模式启用，max_tokens从{request.max_tokens}调整为{payload['max_tokens']}")
        
        logger.info(f"LLM API流式请求 - 模型: {self.model_name}, 提供商: {self.provider_name}")
        logger.debug(f"LLM API流式请求 - endpoint: {self.api_endpoint}")
        logger.debug(f"LLM API流式请求 - max_tokens: {payload.get('max_tokens', request.max_tokens)}, temperature: {request.temperature}")
        
        last_error = None
        
        for attempt in range(self.max_retries):
            try:
                elapsed = time.time() - self._last_request_time
                if elapsed < self.request_interval:
                    wait_time = self.request_interval - elapsed
                    time.sleep(wait_time)
                
                timeout = request.timeout if request.timeout else (300.0 if use_thinking else 120.0)
                logger.debug(f"LLM API流式请求超时设置: {timeout}秒")
                
                accumulated_text = ""
                accumulated_thinking = ""
                finish_reason = None
                final_usage = None
                
                with httpx.Client(timeout=timeout) as client:
                    with client.stream(
                        "POST",
                        self.api_endpoint,
                        headers=headers,
                        json=payload
                    ) as response:
                        response.raise_for_status()
                        
                        self._last_request_time = time.time()
                        
                        for line in response.iter_lines():
                            if not line:
                                continue
                            
                            if line.startswith("data: "):
                                data_str = line[6:]
                                
                                if data_str == "[DONE]":
                                    logger.debug(f"LLM API流式响应完成，总文本长度: {len(accumulated_text)} 字符")
                                    yield LLMStreamChunk(
                                        text=accumulated_text,
                                        model=self.model_name,
                                        provider=self.provider_name,
                                        finish_reason=finish_reason,
                                        thinking_content=accumulated_thinking,
                                        is_final=True,
                                        usage=final_usage
                                    )
                                    return
                                
                                try:
                                    chunk_data = json.loads(data_str)
                                except json.JSONDecodeError as e:
                                    logger.warning(f"流式响应JSON解析失败: {e}, data_str: {data_str[:100]}")
                                    continue
                                
                                choices = chunk_data.get("choices", [])
                                if not choices:
                                    continue
                                
                                delta = choices[0].get("delta", {})
                                chunk_finish_reason = choices[0].get("finish_reason")
                                
                                content = delta.get("content", "")
                                thinking_chunk = delta.get("reasoning_content") or delta.get("reasoning", "")
                                
                                if content:
                                    accumulated_text += content
                                    yield LLMStreamChunk(
                                        text=content,
                                        model=self.model_name,
                                        provider=self.provider_name,
                                        finish_reason=None,
                                        thinking_content=None,
                                        is_final=False
                                    )
                                
                                if thinking_chunk:
                                    accumulated_thinking += thinking_chunk
                                    logger.debug(f"收到thinking chunk, 长度: {len(thinking_chunk)} 字符")
                                
                                if chunk_finish_reason:
                                    finish_reason = chunk_finish_reason
                                    logger.debug(f"流式响应finish_reason: {finish_reason}")
                                
                                usage_data = chunk_data.get("usage")
                                if usage_data:
                                    final_usage = usage_data
                                    logger.debug(f"流式响应usage: {final_usage}")
                        
                        if finish_reason == "length":
                            logger.warning(f"LLM流式输出被截断 (finish_reason=length), max_tokens可能不足")
                        
                        yield LLMStreamChunk(
                            text=accumulated_text,
                            model=self.model_name,
                            provider=self.provider_name,
                            finish_reason=finish_reason or "stop",
                            thinking_content=accumulated_thinking,
                            is_final=True,
                            usage=final_usage
                        )
                        return
                        
            except httpx.HTTPStatusError as e:
                error_detail = ""
                try:
                    error_body = e.response.text
                    error_detail = f", 响应内容: {error_body[:500]}"
                except:
                    pass
                logger.error(f"LLM API流式HTTP错误 (尝试 {attempt + 1}/{self.max_retries}): {str(e)}{error_detail}")
                last_error = RuntimeError(f"{self.provider_name} API error: {str(e)}{error_detail}")
            except httpx.HTTPError as e:
                logger.error(f"LLM API流式HTTP错误 (尝试 {attempt + 1}/{self.max_retries}): {str(e)}")
                last_error = RuntimeError(f"{self.provider_name} API error: {str(e)}")
            except Exception as e:
                logger.error(f"LLM API流式未知错误 (尝试 {attempt + 1}/{self.max_retries}): {str(e)}")
                last_error = RuntimeError(f"{self.provider_name} API stream error: {str(e)}")
            
            if attempt < self.max_retries - 1:
                wait_time = self.retry_delay * (attempt + 1)
                logger.info(f"LLM API流式请求将在 {wait_time} 秒后重试...")
                time.sleep(wait_time)
        
        logger.error(f"LLM API流式调用失败, 已达到最大重试次数 {self.max_retries}")
        raise last_error
