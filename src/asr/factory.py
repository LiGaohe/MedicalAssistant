from typing import Literal, Optional

from .base import ASRBase
from .funasr_engine import FunASREngine
from .medasr_engine import MedASREngine
from .qwen3_asr_engine import Qwen3ASREngine


class ASRFactory:
    _registry: dict[str, type[ASRBase]] = {
        "funasr": FunASREngine,
        "medasr": MedASREngine,
        "qwen3-asr": Qwen3ASREngine,
    }
    
    @classmethod
    def create(
        cls,
        engine_type: Literal["funasr", "medasr", "qwen3-asr"],
        device: str = "cpu",
        hotword_path: Optional[str] = None,
        language: str = "zh",
        **kwargs,
    ) -> ASRBase:
        if engine_type not in cls._registry:
            raise ValueError(
                f"未知的 ASR 引擎: {engine_type}, "
                f"支持的引擎: {list(cls._registry.keys())}"
            )
        
        engine_class = cls._registry[engine_type]
        
        if engine_type == "funasr":
            model_id = kwargs.pop("model_id", None)
            if not model_id:
                model_id = "paraformer-zh" if language == "zh" else "paraformer-en"
            
            punc_model = kwargs.pop("punc_model", "ct-punc")
            
            return engine_class(
                device=device, 
                hotword_path=hotword_path,
                model_id=model_id,
                punc_model=punc_model,
                language=language,
                **kwargs
            )
        elif engine_type == "medasr":
            return engine_class(device=device, **kwargs)
        elif engine_type == "qwen3-asr":
            return engine_class(device=device, language=language, **kwargs)
        
        return engine_class(device=device, **kwargs)
    
    @classmethod
    def create_all(
        cls,
        device: str = "cpu",
        hotword_path: Optional[str] = None,
        language: str = "zh",
    ) -> dict[str, ASRBase]:
        engines = {}
        for engine_type in cls._registry:
            try:
                engines[engine_type] = cls.create(
                    engine_type, 
                    device=device, 
                    hotword_path=hotword_path,
                    language=language
                )
            except Exception as e:
                print(f"警告: 无法创建 {engine_type} 引擎: {e}")
        return engines
    
    @classmethod
    def register(cls, name: str, engine_class: type[ASRBase]) -> None:
        cls._registry[name] = engine_class
    
    @classmethod
    def list_available(cls) -> list[str]:
        return list(cls._registry.keys())
