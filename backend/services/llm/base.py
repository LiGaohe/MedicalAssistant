from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from enum import Enum


class LLMProvider(Enum):
    MODELSCOPE = "modelscope"
    OPENROUTER = "openrouter"


@dataclass
class LLMRequest:
    prompt: str
    max_tokens: int = 2048
    temperature: float = 0.7
    top_p: float = 0.9
    stop_sequences: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None
    

@dataclass
class LLMResponse:
    text: str
    model: str
    provider: str
    usage: Dict[str, int]
    finish_reason: str
    raw_response: Optional[Dict[str, Any]] = None
    

class LLMAdapter(ABC):
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.model_name = config.get("model_name")
        self.api_endpoint = config.get("api_endpoint")
        
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
