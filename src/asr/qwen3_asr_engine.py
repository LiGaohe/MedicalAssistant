import os
from pathlib import Path
from typing import Optional, List

_DEFAULT_CACHE_DIR = Path("D:/models/modelscope_cache")
_DEFAULT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MODELSCOPE_CACHE", str(_DEFAULT_CACHE_DIR))
os.environ.setdefault("HF_HOME", str(_DEFAULT_CACHE_DIR))

import torch

from .base import ASRBase, ASRResult


class Qwen3ASREngine(ASRBase):
    MODEL_SIZES = {
        "1.7B": "Qwen/Qwen3-ASR-1.7B",
        "0.6B": "Qwen/Qwen3-ASR-0.6B",
    }
    
    def __init__(
        self,
        device: str = "cpu",
        model_size: str = "1.7B",
        language: str = "Chinese",
        model_path: Optional[str] = None,
    ):
        super().__init__(model_name=f"Qwen3-ASR-{model_size}", device=device)
        self.model_size = model_size
        self.language = language
        self.model_path = model_path or self.MODEL_SIZES.get(model_size, self.MODEL_SIZES["1.7B"])
        self._audio_duration = 0.0
    
    def load_model(self) -> None:
        try:
            from transformers import Qwen2AudioForConditionalGeneration, AutoProcessor
        except ImportError:
            raise ImportError(
                "transformers 未安装或版本过低，请运行: pip install -U qwen-asr"
            )
        
        device_map = "auto" if self.device == "cuda" else "cpu"
        
        if self.device == "cpu":
            self._processor = AutoProcessor.from_pretrained(
                self.model_path,
                trust_remote_code=True,
            )
            self._model = Qwen2AudioForConditionalGeneration.from_pretrained(
                self.model_path,
                device_map=device_map,
                trust_remote_code=True,
                torch_dtype=torch.float32,
            )
        else:
            self._processor = AutoProcessor.from_pretrained(
                self.model_path,
                trust_remote_code=True,
            )
            self._model = Qwen2AudioForConditionalGeneration.from_pretrained(
                self.model_path,
                device_map=device_map,
                trust_remote_code=True,
                torch_dtype=torch.float16,
            )
        
        self._model.eval()
        self._is_loaded = True
    
    def transcribe(self, audio_path: str | Path, **kwargs) -> ASRResult:
        if not self._is_loaded:
            self.load_model()
        
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"音频文件不存在: {audio_path}")
        
        self._audio_duration = self._get_audio_duration(audio_path)
        
        import librosa
        
        audio_data, sr = librosa.load(
            str(audio_path),
            sr=self._processor.feature_extractor.sampling_rate
        )
        
        conversation = [
            {"role": "user", "content": "<|AUDIO|>"},
            {"role": "assistant", "content": "将这段语音输出为文本，直接输出文本内容即可，不要输出多余的话"},
        ]
        
        text = self._processor.tokenizer.apply_chat_template(
            conversation,
            tokenize=False,
            add_generation_prompt=True
        )
        
        inputs = self._processor(
            text=text,
            audios=[audio_data],
            return_tensors="pt",
            padding=True
        )
        
        if self.device == "cuda":
            inputs = {k: v.to("cuda") for k, v in inputs.items()}
        
        result, inference_time = self._measure_time(
            self._generate_text,
            inputs,
            max_new_tokens=kwargs.get("max_new_tokens", 2048)
        )
        
        text = self._extract_text(result)
        
        segments = []
        if self._audio_duration > 0:
            segments = [{
                "text": text,
                "start": 0,
                "end": int(self._audio_duration * 1000),
                "confidence": 1.0
            }]
        
        return ASRResult(
            text=text,
            language=self._detect_language(text),
            duration_seconds=self._audio_duration,
            inference_time=inference_time,
            model_name=self.model_name,
            segments=segments,
            speaker_segments=[],
        )
    
    def _generate_text(self, inputs: dict, max_new_tokens: int = 2048) -> str:
        with torch.no_grad():
            response_ids = self._model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
            )
        
        response = self._processor.tokenizer.batch_decode(
            response_ids,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False
        )[0]
        
        return response
    
    def _extract_text(self, response: str) -> str:
        import re
        
        parts = response.split("assistant")
        if len(parts) >= 2:
            text = parts[-1].strip()
        else:
            text = response
        
        text = re.sub(r"这段音频的原始内容是[：:]\s*", "", text)
        text = re.sub(r"这段语音的原始文本内容是[：:]\s*", "", text)
        text = re.sub(r"^(文本|转录|转写)[是为][：:]\s*", "", text)
        
        return text.strip()
    
    def _detect_language(self, text: str) -> str:
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        if chinese_chars > len(text) * 0.3:
            return "zh"
        return "en"
    
    def _get_audio_duration(self, audio_path: Path) -> float:
        try:
            import librosa
            duration, _ = librosa.duration(path=str(audio_path))
            return duration
        except Exception:
            try:
                from pydub import AudioSegment
                audio = AudioSegment.from_file(str(audio_path))
                return len(audio) / 1000.0
            except Exception:
                try:
                    import soundfile as sf
                    info = sf.info(str(audio_path))
                    return info.duration
                except Exception:
                    return 0.0
    
    def transcribe_long_audio(
        self,
        audio_path: str | Path,
        chunk_duration: float = 30.0,
        **kwargs
    ) -> ASRResult:
        if not self._is_loaded:
            self.load_model()
        
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"音频文件不存在: {audio_path}")
        
        import librosa
        import numpy as np
        
        audio_data, sr = librosa.load(
            str(audio_path),
            sr=self._processor.feature_extractor.sampling_rate
        )
        
        self._audio_duration = len(audio_data) / sr
        
        chunk_samples = int(chunk_duration * sr)
        num_chunks = int(np.ceil(len(audio_data) / chunk_samples))
        
        all_text = []
        segments = []
        total_inference_time = 0.0
        
        for i in range(num_chunks):
            start_sample = i * chunk_samples
            end_sample = min((i + 1) * chunk_samples, len(audio_data))
            chunk_audio = audio_data[start_sample:end_sample]
            
            if len(chunk_audio) < sr * 0.5:
                continue
            
            conversation = [
                {"role": "user", "content": "<|AUDIO|>"},
                {"role": "assistant", "content": "将这段语音输出为文本，直接输出文本内容即可，不要输出多余的话"},
            ]
            
            text = self._processor.tokenizer.apply_chat_template(
                conversation,
                tokenize=False,
                add_generation_prompt=True
            )
            
            inputs = self._processor(
                text=text,
                audios=[chunk_audio],
                return_tensors="pt",
                padding=True
            )
            
            if self.device == "cuda":
                inputs = {k: v.to("cuda") for k, v in inputs.items()}
            
            import time
            start_time = time.perf_counter()
            
            with torch.no_grad():
                response_ids = self._model.generate(
                    **inputs,
                    max_new_tokens=kwargs.get("max_new_tokens", 2048)
                )
            
            end_time = time.perf_counter()
            chunk_inference_time = end_time - start_time
            total_inference_time += chunk_inference_time
            
            response = self._processor.tokenizer.batch_decode(
                response_ids,
                skip_special_tokens=True,
                clean_up_tokenization_spaces=False
            )[0]
            
            chunk_text = self._extract_text(response)
            
            if chunk_text:
                all_text.append(chunk_text)
                start_ms = int(start_sample / sr * 1000)
                end_ms = int(end_sample / sr * 1000)
                segments.append({
                    "text": chunk_text,
                    "start": start_ms,
                    "end": end_ms,
                    "confidence": 1.0,
                    "chunk_index": i
                })
        
        full_text = " ".join(all_text)
        
        return ASRResult(
            text=full_text,
            language=self._detect_language(full_text),
            duration_seconds=self._audio_duration,
            inference_time=total_inference_time,
            model_name=self.model_name,
            segments=segments,
            speaker_segments=[],
        )
    
    @classmethod
    def create_medical_version(
        cls,
        device: str = "cpu",
        model_size: str = "1.7B",
    ):
        return cls(
            device=device,
            model_size=model_size,
            language="Chinese",
        )
