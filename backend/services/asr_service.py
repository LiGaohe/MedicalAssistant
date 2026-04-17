from pathlib import Path
from typing import Optional, Union
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.asr import FunASREngine, Qwen3ASREngine
from .postprocessor import ASRPostprocessor


class ASRService:
    def __init__(self, config: dict):
        self.config = config
        self.engine: Optional[Union[FunASREngine, Qwen3ASREngine]] = None
        self.postprocessor: Optional[ASRPostprocessor] = None
        self.enable_sentence_split = config.get("enable_sentence_split", True)
        self.split_gap_threshold_ms = config.get("split_gap_threshold_ms", 800)
        self.engine_type = config.get("engine_type", "funasr")
    
    def initialize(self):
        if self.engine is None:
            if self.engine_type == "qwen3-asr":
                self._init_qwen3_asr()
            else:
                self._init_funasr()
        
        if self.postprocessor is None and self.engine_type == "funasr":
            self.postprocessor = ASRPostprocessor(
                split_gap_threshold_ms=self.split_gap_threshold_ms
            )
    
    def _init_funasr(self):
        enable_diarization = self.config.get("enable_diarization", True)
        self.engine = FunASREngine(
            device=self.config.get("device", "cpu"),
            hotword_path=self.config.get("hotword_path"),
            spk_model="cam++" if enable_diarization else None
        )
        self.engine.load_model()
    
    def _init_qwen3_asr(self):
        model_size = self.config.get("qwen3_asr_model_size", "1.7B")
        language = self.config.get("qwen3_asr_language", "Chinese")
        self.engine = Qwen3ASREngine(
            device=self.config.get("device", "cpu"),
            model_size=model_size,
            language=language
        )
        self.engine.load_model()
    
    def transcribe(self, audio_path: str | Path) -> dict:
        if self.engine is None:
            self.initialize()
        
        if self.engine_type == "qwen3-asr" and isinstance(self.engine, Qwen3ASREngine):
            audio_path = Path(audio_path)
            duration = self.engine._get_audio_duration(audio_path)
            if duration > 30:
                result = self.engine.transcribe_long_audio(audio_path)
            else:
                result = self.engine.transcribe(audio_path)
        else:
            result = self.engine.transcribe(audio_path)
        
        return {
            "text": result.text,
            "segments": result.segments,
            "duration": result.duration_seconds,
            "inference_time": result.inference_time,
            "engine": self.engine_type
        }
    
    def transcribe_with_diarization(self, audio_path: str | Path) -> dict:
        if self.engine is None:
            self.initialize()
        
        if self.engine_type == "qwen3-asr":
            return self._transcribe_qwen3_asr(audio_path)
        else:
            return self._transcribe_funasr_with_diarization(audio_path)
    
    def _transcribe_qwen3_asr(self, audio_path: str | Path) -> dict:
        audio_path = Path(audio_path)
        duration = self.engine._get_audio_duration(audio_path)
        
        if duration > 30:
            result = self.engine.transcribe_long_audio(audio_path)
        else:
            result = self.engine.transcribe(audio_path)
        
        turns = []
        if result.segments:
            for i, segment in enumerate(result.segments):
                turns.append({
                    "turn_index": i,
                    "speaker_id": "spk0",
                    "text": segment.get("text", ""),
                    "start_ms": segment.get("start", 0),
                    "end_ms": segment.get("end", 0)
                })
        else:
            turns.append({
                "turn_index": 0,
                "speaker_id": "spk0",
                "text": result.text,
                "start_ms": 0,
                "end_ms": int(result.duration_seconds * 1000)
            })
        
        return {
            "turns": turns,
            "duration": result.duration_seconds,
            "inference_time": result.inference_time,
            "engine": self.engine_type,
            "note": "Qwen3-ASR不支持说话人分离，所有文本归为spk0"
        }
    
    def _transcribe_funasr_with_diarization(self, audio_path: str | Path) -> dict:
        result = self.engine.transcribe(audio_path)
        
        turns = []
        segments = result.segments
        sentence_splits = []
        
        if self.enable_sentence_split and self.postprocessor and segments:
            new_segments, split_records = self.postprocessor.split_sentences_by_gap(segments)
            if split_records:
                segments = new_segments
                sentence_splits = split_records
        
        if result.speaker_segments and not sentence_splits:
            for i, segment in enumerate(result.speaker_segments):
                turns.append({
                    "turn_index": i,
                    "speaker_id": segment.get("speaker", "unknown"),
                    "text": segment.get("text", ""),
                    "start_ms": segment.get("start_ms", 0),
                    "end_ms": segment.get("end_ms", 0)
                })
        elif segments:
            for i, segment in enumerate(segments):
                speaker_id = f"spk{segment.get('spk', 0)}" if "spk" in segment else "unknown"
                turns.append({
                    "turn_index": i,
                    "speaker_id": speaker_id,
                    "text": segment.get("text", ""),
                    "start_ms": segment.get("start", 0),
                    "end_ms": segment.get("end", 0)
                })
        else:
            turns.append({
                "turn_index": 0,
                "speaker_id": "unknown",
                "text": result.text,
                "start_ms": 0,
                "end_ms": int(result.duration_seconds * 1000)
            })
        
        response = {
            "turns": turns,
            "duration": result.duration_seconds,
            "inference_time": result.inference_time,
            "engine": self.engine_type
        }
        
        if sentence_splits:
            response["sentence_splits"] = sentence_splits
        
        return response
