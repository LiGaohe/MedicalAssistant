from pathlib import Path
from typing import Optional
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.asr import FunASREngine
from .postprocessor import ASRPostprocessor


class ASRService:
    def __init__(self, config: dict):
        self.config = config
        self.engine: Optional[FunASREngine] = None
        self.postprocessor: Optional[ASRPostprocessor] = None
        self.enable_sentence_split = config.get("enable_sentence_split", True)
        self.split_gap_threshold_ms = config.get("split_gap_threshold_ms", 800)
    
    def initialize(self):
        if self.engine is None:
            enable_diarization = self.config.get("enable_diarization", True)
            self.engine = FunASREngine(
                device=self.config.get("device", "cpu"),
                hotword_path=self.config.get("hotword_path"),
                spk_model="cam++" if enable_diarization else None
            )
            self.engine.load_model()
        
        if self.postprocessor is None:
            self.postprocessor = ASRPostprocessor(
                split_gap_threshold_ms=self.split_gap_threshold_ms
            )
    
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
        """
        转写音频并进行说话人分离。
        
        注意：此方法只负责语音转文本和说话人分离，不进行角色识别。
        角色识别（医生/患者）应由后续模块（大模型）处理。
        
        Args:
            audio_path: 音频文件路径
            
        Returns:
            dict: 包含转写结果和说话人分离信息的字典
        """
        if self.engine is None:
            self.initialize()
        
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
            "inference_time": result.inference_time
        }
        
        if sentence_splits:
            response["sentence_splits"] = sentence_splits
        
        return response
