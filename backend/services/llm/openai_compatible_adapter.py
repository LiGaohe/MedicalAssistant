from typing import Dict, Any
import httpx
import json
import time
from .base import LLMAdapter, LLMRequest, LLMResponse


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
        
        last_error = None
        
        for attempt in range(self.max_retries):
            try:
                elapsed = time.time() - self._last_request_time
                if elapsed < self.request_interval:
                    wait_time = self.request_interval - elapsed
                    time.sleep(wait_time)
                
                with httpx.Client(timeout=120.0) as client:
                    response = client.post(
                        self.api_endpoint,
                        headers=headers,
                        json=payload
                    )
                    response.raise_for_status()
                    data = response.json()
                    
                    self._last_request_time = time.time()
                    
                    choices = data.get("choices", [])
                    if not choices:
                        error_info = data.get("error", {})
                        if error_info:
                            raise RuntimeError(f"{self.provider_name} API error: {error_info}")
                        
                        usage = data.get("usage", {})
                        if usage and usage.get("total_tokens", 0) == 0:
                            raise RuntimeError(f"{self.provider_name} API rate limited or request rejected")
                        
                        raise RuntimeError(f"{self.provider_name} API returned no choices. Response: {json.dumps(data, ensure_ascii=False)[:500]}")
                    
                    message = choices[0].get("message", {})
                    content = message.get("content")
                    
                    if content is None:
                        reasoning = message.get("reasoning")
                        if reasoning:
                            content = self._extract_final_answer(reasoning)
                            if content:
                                content = content.strip()
                        
                        if not content:
                            raise RuntimeError(f"{self.provider_name} API returned None content")
                    
                    return LLMResponse(
                        text=content,
                        model=self.model_name,
                        provider=self.provider_name,
                        usage=data.get("usage", {}),
                        finish_reason=choices[0].get("finish_reason", "stop"),
                        raw_response=data
                    )
                    
            except httpx.HTTPError as e:
                last_error = RuntimeError(f"{self.provider_name} API error: {str(e)}")
            except (KeyError, IndexError) as e:
                last_error = RuntimeError(f"Invalid {self.provider_name} response format: {str(e)}")
            except RuntimeError as e:
                last_error = e
            
            if attempt < self.max_retries - 1:
                wait_time = self.retry_delay * (attempt + 1)
                time.sleep(wait_time)
        
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
