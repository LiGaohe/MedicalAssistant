from typing import Dict, Any
import httpx
import json
import time
from .base import LLMAdapter, LLMRequest, LLMResponse
from ...utils.logger import logger


class OpenAICompatibleAdapter(LLMAdapter):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.api_key = config.get("api_key")
        
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
        self.retry_delay = config.get("retry_delay", 3.0)
        self.request_interval = config.get("request_interval", 2.0)
        self._last_request_time = 0
        
    def generate(self, request: LLMRequest) -> LLMResponse:
        headers = {
            "Content-Type": "application/json"
        }
        
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "user", "content": request.prompt}
            ],
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "top_p": request.top_p
        }
        
        if request.stop_sequences:
            payload["stop"] = request.stop_sequences
        
        use_json_mode = request.json_mode or self.json_mode
        if use_json_mode:
            payload["response_format"] = {"type": "json_object"}
        
        use_thinking = request.thinking_enabled or self.thinking_enabled
        if use_thinking:
            effort = request.thinking_effort if request.thinking_enabled else self.thinking_effort
            payload["thinking"] = {
                "type": "enabled",
                "reasoning_effort": effort
            }
            payload["max_tokens"] = request.max_tokens * 3
            logger.debug(f"思考模式启用，max_tokens从{request.max_tokens}调整为{payload['max_tokens']}以补偿reasoning_tokens")
        
        logger.info(f"LLM API请求 - 模型: {self.model_name}, 提供商: {self.provider_name}")
        logger.debug(f"LLM API请求 - endpoint: {self.api_endpoint}")
        logger.debug(f"LLM API请求 - max_tokens: {payload.get('max_tokens', request.max_tokens)}, temperature: {request.temperature}")
        logger.debug(f"LLM API请求 - json_mode: {use_json_mode}, thinking_enabled: {use_thinking}")
        
        last_error = None
        
        for attempt in range(self.max_retries):
            try:
                elapsed = time.time() - self._last_request_time
                if elapsed < self.request_interval:
                    wait_time = self.request_interval - elapsed
                    time.sleep(wait_time)
                
                timeout = 300.0 if use_thinking else 120.0
                with httpx.Client(timeout=timeout) as client:
                    response = client.post(
                        self.api_endpoint,
                        headers=headers,
                        json=payload
                    )
                    response.raise_for_status()
                    data = response.json()
                    
                    logger.debug(f"LLM API原始响应: {json.dumps(data, ensure_ascii=False)[:2000]}")
                    
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
                    
                    if content is None:
                        if thinking_content:
                            logger.debug(f"LLM API返回reasoning字段, 尝试提取最终答案")
                            content = self._extract_final_answer(thinking_content)
                            if content:
                                content = content.strip()
                        
                        if not content:
                            logger.error(f"LLM API返回None content, message: {message}")
                            raise RuntimeError(f"{self.provider_name} API returned None content")
                    
                    if content and len(content) > 0:
                        stripped_len = len(content.replace(' ', '').replace('\t', '').replace('\n', ''))
                        if stripped_len < len(content) * 0.1:
                            logger.warning(f"LLM响应疑似空白填充 (原始{len(content)}字符, 去空白后{stripped_len}字符), 可能因token截断导致")
                    
                    return LLMResponse(
                        text=content,
                        model=self.model_name,
                        provider=self.provider_name,
                        usage=data.get("usage", {}),
                        finish_reason=finish_reason,
                        raw_response=data,
                        thinking_content=thinking_content
                    )
                    
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
    
    def _extract_final_answer(self, reasoning: str) -> str:
        import re
        
        if not reasoning:
            return ""
        
        json_match = re.search(r'\{[\s\S]*\}', reasoning)
        if json_match:
            return json_match.group()
        
        json_array_match = re.search(r'\[[\s\S]*\]', reasoning)
        if json_array_match:
            return json_array_match.group()
        
        lines = reasoning.strip().split('\n')
        
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            
            if line.startswith(('*', '-', '•', '1.', '2.', '3.', '4.', '5.')):
                line = re.sub(r'^[*\-•\d.]\s*', '', line).strip()
            
            if line and len(line) < 200 and not line.startswith('Thinking') and not line.startswith('##'):
                if re.search(r'[a-zA-Z\u4e00-\u9fff]', line):
                    return line
        
        last_non_empty = ""
        for line in reversed(lines):
            line = line.strip()
            if line and not line.startswith('Thinking') and not line.startswith('##'):
                last_non_empty = line
                break
        
        return last_non_empty
    
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
