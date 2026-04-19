import os
from pathlib import Path
from typing import Optional, Dict, Any

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
        spk_model: Optional[str] = None,
        hotword_path: Optional[str] = None,
        speaker_diarization_config: Optional[Dict[str, Any]] = None,
        vad_kwargs: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(model_name="FunASR-Paraformer", device=device)
        self.model_id = model_id
        self.vad_model = vad_model
        self.punc_model = punc_model
        self.spk_model = spk_model
        self.hotword_path = hotword_path
        self.speaker_diarization_config = speaker_diarization_config or {}
        self.vad_kwargs = vad_kwargs or {}
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
            "beam_search": True,
            "timestamp_extractor": True,
        }
        
        if self.vad_kwargs:
            model_kwargs["vad_kwargs"] = self.vad_kwargs
        
        if self.spk_model:
            model_kwargs["spk_model"] = self.spk_model
            
            if self.speaker_diarization_config:
                model_kwargs["speaker_diarization_conf"] = self.speaker_diarization_config
        
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
            batch_size_s=300,
            batch_type="seg",
            **kwargs
        )
        
        text = ""
        segments = []
        speaker_segments = []
        overall_confidence = 0.0
        
        if result and len(result) > 0:
            text = result[0].get("text", "")
            
            if "sentence_info" in result[0]:
                segments = result[0]["sentence_info"]
            elif "sentences" in result[0]:
                segments = result[0]["sentences"]
            
            confidences = []
            if self.spk_model and segments:
                for sentence in segments:
                    if "spk" in sentence:
                        start_ms = sentence.get("start", 0)
                        end_ms = sentence.get("end", 0)
                        
                        seg_confidence = self._extract_segment_confidence(sentence)
                        confidences.append(seg_confidence)
                        
                        speaker_segments.append({
                            "speaker": f"spk{sentence.get('spk', 0)}",
                            "text": sentence.get("text", ""),
                            "start_ms": start_ms,
                            "end_ms": end_ms,
                            "confidence": seg_confidence
                        })
            elif segments:
                for sentence in segments:
                    seg_confidence = self._extract_segment_confidence(sentence)
                    confidences.append(seg_confidence)
            
            if confidences:
                overall_confidence = sum(confidences) / len(confidences)
        
        return ASRResult(
            text=text,
            language="zh",
            duration_seconds=self._audio_duration,
            inference_time=inference_time,
            model_name=self.model_name,
            segments=segments,
            speaker_segments=speaker_segments,
            confidence=overall_confidence,
        )
    
    def _extract_segment_confidence(self, sentence: Dict[str, Any]) -> float:
        if "confidence" in sentence:
            return float(sentence["confidence"])
        elif "word_conf" in sentence:
            word_confs = sentence["word_conf"]
            if word_confs:
                return sum(word_confs) / len(word_confs)
        return 0.0
    
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
    
    @classmethod
    def create_medical_version(
        cls,
        hotword_path: Optional[str] = None,
        device: str = "cpu",
        enable_diarization: bool = True,
        speaker_threshold: float = 0.7,
        max_speakers: int = 2,
        max_single_segment_time: int = 3000,
        vad_speech_threshold: float = 0.5,
    ):
        """
        创建医疗场景优化的FunASR引擎实例。
        
        Args:
            hotword_path: 医疗热词文件路径
            device: 运行设备
            enable_diarization: 是否启用说话人分离
            speaker_threshold: 说话人聚类阈值，默认0.5
                - 提高阈值（如0.7-0.8）会更严格，更容易区分不同说话人
                - 降低阈值（如0.4-0.5）会更宽松，可能会合并相似说话人
            max_speakers: 最大说话人数量，默认2（医生+患者）
            max_single_segment_time: VAD最大单段语音时长（毫秒），默认3000ms
                - 减小此值可以让VAD更敏感地检测短暂停顿（如0.3-0.5秒）
                - 增大此值可以避免过度分割
            vad_speech_threshold: VAD语音检测阈值，默认0.5
                - 提高此值（如0.5-0.6）可以减少噪声误触发
                - 降低此值（如0.3-0.4）可以更敏感地检测语音边界
        
        Returns:
            FunASREngine实例
        """
        speaker_config = None
        if enable_diarization:
            speaker_config = {
                "threshold": speaker_threshold,
                "max_speakers": max_speakers,
            }
        
        vad_config = {
            "max_single_segment_time": max_single_segment_time,
            "vad_speech_threshold": vad_speech_threshold,
        }
        
        return cls(
            device=device,
            model_id="paraformer-zh",
            vad_model="fsmn-vad",
            punc_model="ct-punc",
            spk_model="cam++" if enable_diarization else None,
            hotword_path=hotword_path,
            speaker_diarization_config=speaker_config,
            vad_kwargs=vad_config,
        )
