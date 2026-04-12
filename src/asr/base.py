from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import time


@dataclass
class ASRResult:
    text: str
    language: str
    duration_seconds: float
    inference_time: float
    model_name: str
    word_error_rate: Optional[float] = None
    confidence: Optional[float] = None
    segments: Optional[list] = field(default_factory=list)
    
    @property
    def real_time_factor(self) -> float:
        if self.duration_seconds > 0:
            return self.inference_time / self.duration_seconds
        return 0.0
    
    def __str__(self) -> str:
        return (
            f"[{self.model_name}] "
            f"RTF: {self.real_time_factor:.3f} | "
            f"Time: {self.inference_time:.2f}s | "
            f"Text: {self.text[:100]}..."
        )


class ASRBase(ABC):
    def __init__(self, model_name: str, device: str = "cpu"):
        self.model_name = model_name
        self.device = device
        self._model = None
        self._is_loaded = False
    
    @abstractmethod
    def load_model(self) -> None:
        pass
    
    @abstractmethod
    def transcribe(self, audio_path: str | Path, **kwargs) -> ASRResult:
        pass
    
    def is_loaded(self) -> bool:
        return self._is_loaded
    
    def unload(self) -> None:
        self._model = None
        self._is_loaded = False
    
    def _measure_time(self, func, *args, **kwargs):
        start_time = time.perf_counter()
        result = func(*args, **kwargs)
        end_time = time.perf_counter()
        return result, end_time - start_time
