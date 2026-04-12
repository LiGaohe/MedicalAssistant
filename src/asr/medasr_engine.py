from pathlib import Path
from typing import Optional
import time

from .base import ASRBase, ASRResult


class MedASREngine(ASRBase):
    def __init__(
        self,
        device: str = "cpu",
        model_id: str = "google/medasr-105m",
    ):
        super().__init__(model_name="MedASR", device=device)
        self.model_id = model_id
        self._audio_duration = 0.0
    
    def load_model(self) -> None:
        try:
            from transformers import AutoModelForCTC, AutoProcessor
            import torch
        except ImportError:
            raise ImportError(
                "Transformers 未安装，请运行: pip install transformers torch"
            )
        
        self._processor = AutoProcessor.from_pretrained(self.model_id)
        self._model = AutoModelForCTC.from_pretrained(self.model_id)
        
        if self.device == "cuda" and torch.cuda.is_available():
            self._model = self._model.to(self.device)
        
        self._model.eval()
        self._is_loaded = True
    
    def transcribe(self, audio_path: str | Path, **kwargs) -> ASRResult:
        if not self._is_loaded:
            self.load_model()
        
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"音频文件不存在: {audio_path}")
        
        import torch
        import librosa
        
        waveform, sample_rate = librosa.load(
            str(audio_path), 
            sr=16000, 
            mono=True
        )
        self._audio_duration = len(waveform) / sample_rate
        
        inputs = self._processor(
            waveform, 
            sampling_rate=16000, 
            return_tensors="pt",
            padding=True
        )
        
        if self.device == "cuda" and torch.cuda.is_available():
            inputs = {k: v.to(self.device) for k, v in inputs.items()}
        
        start_time = time.perf_counter()
        with torch.no_grad():
            logits = self._model(**inputs).logits
        
        predicted_ids = torch.argmax(logits, dim=-1)
        text = self._processor.batch_decode(predicted_ids)[0]
        inference_time = time.perf_counter() - start_time
        
        return ASRResult(
            text=text,
            language="en",
            duration_seconds=self._audio_duration,
            inference_time=inference_time,
            model_name=self.model_name,
        )
    
    def transcribe_with_warning(self, audio_path: str | Path, **kwargs) -> ASRResult:
        result = self.transcribe(audio_path, **kwargs)
        result.text = f"[警告: MedASR 仅支持英文] {result.text}"
        return result
