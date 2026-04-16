from typing import Dict, Any
import httpx
from .base import LLMAdapter, LLMRequest, LLMResponse


class OpenAICompatibleAdapter(LLMAdapter):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.api_key = config.get("api_key")
        self.api_endpoint = config.get(
            "api_endpoint",
            "https://api.openai.com/v1/chat/completions"
        )
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
            with httpx.Client(timeout=60.0) as client:
                response = client.post(
                    self.api_endpoint,
                    headers=headers,
                    json=payload
                )
                response.raise_for_status()
                data = response.json()
                
                return LLMResponse(
                    text=data["choices"][0]["message"]["content"],
                    model=self.model_name,
                    provider=self.provider_name,
                    usage=data.get("usage", {}),
                    finish_reason=data["choices"][0].get("finish_reason", "stop"),
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
