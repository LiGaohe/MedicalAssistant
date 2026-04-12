import os
from pathlib import Path
from typing import Optional

_DEFAULT_CACHE_DIR = Path("D:/models/modelscope_cache")
_DEFAULT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MODELSCOPE_CACHE", str(_DEFAULT_CACHE_DIR))

import torch

from .base import ASRBase, ASRResult


class FunASREngine(ASRBase):
    def __init__(
        self,
        device: str = "cpu",
        model_id: str = "paraformer-zh",
        vad_model: str = "fsmn-vad",
        punc_model: str = "ct-punc",
        hotword_path: Optional[str] = None,
    ):
        super().__init__(model_name="FunASR-Paraformer", device=device)
        self.model_id = model_id
        self.vad_model = vad_model
        self.punc_model = punc_model
        self.hotword_path = hotword_path
        self._audio_duration = 0.0
    
    def load_model(self) -> None:
        try:
            from funasr import AutoModel
        except ImportError:
            raise ImportError(
                "FunASR 未安装，请运行: pip install funasr modelscope"
            )
        
        model_kwargs = {
            "model": self.model_id,
            "vad_model": self.vad_model,
            "punc_model": self.punc_model,
            "device": self.device,
        }
        
        if self.hotword_path and Path(self.hotword_path).exists():
            model_kwargs["hotword"] = self.hotword_path
        
        self._model = AutoModel(**model_kwargs)
        self._is_loaded = True
    
    def transcribe(self, audio_path: str | Path, **kwargs) -> ASRResult:
        if not self._is_loaded:
            self.load_model()
        
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"音频文件不存在: {audio_path}")
        
        self._audio_duration = self._get_audio_duration(audio_path)
        
        result, inference_time = self._measure_time(
            self._model.generate,
            input=str(audio_path),
            **kwargs
        )
        
        text = ""
        segments = []
        if result and len(result) > 0:
            text = result[0].get("text", "")
            if "sentences" in result[0]:
                segments = result[0]["sentences"]
        
        return ASRResult(
            text=text,
            language="zh",
            duration_seconds=self._audio_duration,
            inference_time=inference_time,
            model_name=self.model_name,
            segments=segments,
        )
    
    def _get_audio_duration(self, audio_path: Path) -> float:
        try:
            import librosa
            duration, _ = librosa.duration(path=str(audio_path))
            return duration
        except Exception:
            return 0.0
    
    @classmethod
    def create_medical_version(cls, hotword_path: Optional[str] = None, device: str = "cpu"):
        return cls(
            device=device,
            model_id="paraformer-zh",
            vad_model="fsmn-vad",
            punc_model="ct-punc",
            hotword_path=hotword_path,
        )
