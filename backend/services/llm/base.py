from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List


@dataclass
class LLMRequest:
    prompt: str
    max_tokens: int = 2048
    temperature: float = 0.7
    top_p: float = 0.9
    stop_sequences: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None
    json_mode: bool = False
    thinking_enabled: bool = False
    thinking_effort: str = "high"
    timeout: Optional[float] = None
    

@dataclass
class LLMResponse:
    text: str
    model: str
    provider: str
    usage: Dict[str, int]
    finish_reason: str
    raw_response: Optional[Dict[str, Any]] = None
    thinking_content: Optional[str] = None
    

class LLMAdapter(ABC):
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.model_name = config.get("model_name")
        self.api_endpoint = config.get("api_endpoint")
        self.json_mode = config.get("json_mode", False)
        self.thinking_enabled = config.get("thinking_enabled", False)
        self.thinking_effort = config.get("thinking_effort", "high")
        
    @abstractmethod
    def generate(self, request: LLMRequest) -> LLMResponse:
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        pass
    
    def validate_response(self, response: LLMResponse) -> bool:
        if not response.text:
            return False
        if response.finish_reason not in ["stop", "length", "content_filter"]:
            return False
        return True
