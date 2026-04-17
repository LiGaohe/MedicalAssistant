from typing import Dict, Any
import httpx
import json
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
            
        try:
            with httpx.Client(timeout=120.0) as client:
                response = client.post(
                    self.api_endpoint,
                    headers=headers,
                    json=payload
                )
                response.raise_for_status()
                data = response.json()
                
                choices = data.get("choices", [])
                if not choices:
                    error_info = data.get("error", {})
                    if error_info:
                        raise RuntimeError(f"{self.provider_name} API error: {error_info}")
                    raise RuntimeError(f"{self.provider_name} API returned no choices. Response: {json.dumps(data, ensure_ascii=False)[:500]}")
                
                message = choices[0].get("message", {})
                content = message.get("content")
                
                if content is None:
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
            raise RuntimeError(f"{self.provider_name} API error: {str(e)}")
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"Invalid {self.provider_name} response format: {str(e)}")
    
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
