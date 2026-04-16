from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session
from .base import LLMAdapter, LLMRequest, LLMResponse
from .openai_compatible_adapter import OpenAICompatibleAdapter
from .prompts import PromptManager
from ...models.llm_config import LLMConfig
import json


class LLMService:
    def __init__(self, db: Session):
        self.db = db
        self.adapters: Dict[str, LLMAdapter] = {}
        self.prompt_manager = PromptManager()
        self._load_adapters()
        
    def _load_adapters(self):
        configs = self.db.query(LLMConfig).filter(LLMConfig.is_active == True).all()
        for config in configs:
            try:
                adapter = self._create_adapter(config)
                self.adapters[config.config_name] = adapter
            except Exception as e:
                print(f"Failed to load adapter {config.config_name}: {e}")
                
    def _create_adapter(self, config: LLMConfig) -> LLMAdapter:
        config_dict = {
            "model_name": config.model_name,
            "api_endpoint": config.api_endpoint,
            "api_key": config.api_key,
            "max_tokens": config.max_tokens,
            "temperature": float(config.temperature),
            "provider_name": config.provider
        }
        
        return OpenAICompatibleAdapter(config_dict)
            
    def generate(
        self, 
        prompt: str, 
        config_name: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None
    ) -> LLMResponse:
        if not self.adapters:
            raise RuntimeError("No active LLM adapters available")
            
        adapter_name = config_name or list(self.adapters.keys())[0]
        if adapter_name not in self.adapters:
            raise ValueError(f"Adapter '{adapter_name}' not found")
            
        adapter = self.adapters[adapter_name]
        
        config = self.db.query(LLMConfig).filter(
            LLMConfig.config_name == adapter_name
        ).first()
        
        request = LLMRequest(
            prompt=prompt,
            max_tokens=max_tokens or config.max_tokens,
            temperature=temperature or float(config.temperature)
        )
        
        response = adapter.generate(request)
        
        if not adapter.validate_response(response):
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
        response = self.generate(prompt, config_name)
        
        try:
            json_start = response.text.find("{")
            json_end = response.text.rfind("}") + 1
            if json_start != -1 and json_end > json_start:
                json_str = response.text[json_start:json_end]
                return json.loads(json_str)
            else:
                raise ValueError("No JSON found in response")
        except json.JSONDecodeError as e:
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
        self._load_adapters()
