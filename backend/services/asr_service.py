from pathlib import Path
from typing import Optional
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.asr import FunASREngine


class ASRService:
    def __init__(self, config: dict):
        self.config = config
        self.engine: Optional[FunASREngine] = None
    
    def initialize(self):
        if self.engine is None:
            enable_diarization = self.config.get("enable_diarization", True)
            self.engine = FunASREngine(
                device=self.config.get("device", "cpu"),
                hotword_path=self.config.get("hotword_path"),
                spk_model="cam++" if enable_diarization else None
            )
            self.engine.load_model()
    
    def transcribe(self, audio_path: str | Path) -> dict:
        if self.engine is None:
            self.initialize()
        
        result = self.engine.transcribe(audio_path)
        
        return {
            "text": result.text,
            "segments": result.segments,
            "duration": result.duration_seconds,
            "inference_time": result.inference_time
        }
    
    def transcribe_with_diarization(self, audio_path: str | Path) -> dict:
        if self.engine is None:
            self.initialize()
        
        result = self.engine.transcribe(audio_path)
        
        turns = []
        if result.speaker_segments:
            for i, segment in enumerate(result.speaker_segments):
                speaker_id = segment.get("speaker", "unknown")
                speaker = self._map_speaker_id(speaker_id, i)
                turns.append({
                    "turn_index": i,
                    "speaker": speaker,
                    "speaker_id": speaker_id,
                    "text": segment.get("text", ""),
                    "start_ms": segment.get("start_ms", 0),
                    "end_ms": segment.get("end_ms", 0),
                    "confidence": segment.get("confidence", 0.0)
                })
        elif result.segments:
            for i, segment in enumerate(result.segments):
                speaker = self._map_speaker(i)
                turns.append({
                    "turn_index": i,
                    "speaker": speaker,
                    "speaker_id": "unknown",
                    "text": segment.get("text", ""),
                    "start_ms": int(segment.get("start", 0) * 1000),
                    "end_ms": int(segment.get("end", 0) * 1000),
                    "confidence": segment.get("confidence", 0.0)
                })
        else:
            turns.append({
                "turn_index": 0,
                "speaker": "unknown",
                "speaker_id": "unknown",
                "text": result.text,
                "start_ms": 0,
                "end_ms": int(result.duration_seconds * 1000),
                "confidence": 0.0
            })
        
        return {
            "turns": turns,
            "duration": result.duration_seconds,
            "inference_time": result.inference_time
        }
    
    def _map_speaker(self, index: int) -> str:
        if index % 2 == 0:
            return "doctor"
        else:
            return "patient"
    
    def _map_speaker_id(self, speaker_id: str, index: int) -> str:
        if speaker_id == "unknown":
            return self._map_speaker(index)
        
        try:
            spk_num = int(speaker_id.replace("spk", ""))
            if spk_num == 0:
                return "doctor"
            elif spk_num == 1:
                return "patient"
            else:
                return f"speaker_{spk_num}"
        except (ValueError, AttributeError):
            return self._map_speaker(index)
