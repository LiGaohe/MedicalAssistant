from pathlib import Path
from typing import Optional, Union
import re
import sys
import logging

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.asr import FunASREngine, Qwen3ASREngine
from src.asr.factory import ASRFactory
from .postprocessor import ASRPostprocessor
from ..utils.logger import logger


class ASRService:
    def __init__(self, config: dict):
        self.config = config
        self.engine: Optional[Union[FunASREngine, Qwen3ASREngine]] = None
        self.punc_engine = None
        self.postprocessor: Optional[ASRPostprocessor] = None
        self.enable_sentence_split = config.get("enable_sentence_split", True)
        self.split_gap_threshold_ms = config.get("split_gap_threshold_ms", 800)
        self.engine_type = config.get("engine_type", "funasr")
        self.language = config.get("language", "zh")
        logger.info(f"ASRService初始化, 语言: {self.language}, 引擎类型: {self.engine_type}")
    
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
        
        hotword_path = self.config.get("hotword_path")
        if self.language == "en" and self.config.get("hotword_path_en"):
            hotword_path = self.config.get("hotword_path_en")
        
        if self.language == "en":
            from funasr import AutoModel
            self.engine = AutoModel(
                model="iic/SenseVoiceSmall",
                device=self.config.get("device", "cpu"),
                disable_update=True
            )
            self.punc_engine = AutoModel(
                model="ct-punc",
                device=self.config.get("device", "cpu"),
                disable_update=True
            )
            self.engine_type = "sensevoice"
            logger.info("英文模式: 使用SenseVoice引擎")
        else:
            self.engine = ASRFactory.create(
                engine_type="funasr",
                device=self.config.get("device", "cpu"),
                hotword_path=hotword_path,
                language=self.language,
                spk_model="cam++" if enable_diarization else None
            )
            self.engine.load_model()
            self.engine_type = "funasr"
            logger.info("中文模式: 使用FunASR引擎")
    
    def _init_qwen3_asr(self):
        model_size = self.config.get("qwen3_asr_model_size", "1.7B")
        language = "Chinese" if self.language == "zh" else "English"
        self.engine = Qwen3ASREngine(
            device=self.config.get("device", "cpu"),
            model_size=model_size,
            language=language
        )
        self.engine.load_model()
    
    def _clean_sensevoice_output(self, text: str) -> str:
        logger.debug(f"SenseVoice原始输出: {text[:200]}...")
        
        text = re.sub(r'<\|[^|]*\|>', '', text)
        
        text = re.sub(r'\s+', ' ', text).strip()
        
        logger.debug(f"清理后文本: {text[:200]}...")
        return text
    
    def _add_punctuation(self, text: str) -> str:
        if self.punc_engine:
            try:
                result = self.punc_engine.generate(input=text)
                if result and len(result) > 0:
                    punctuated = result[0].get("text", text)
                    logger.debug(f"标点处理后: {punctuated[:200]}...")
                    return punctuated
            except Exception as e:
                logger.warning(f"标点处理失败: {e}")
        return text
    
    def _format_english_text(self, text: str) -> str:
        logger.debug(f"格式化英文文本输入: {text[:200]}...")
        
        text = re.sub(r'\s+', ' ', text).strip()
        
        text = re.sub(r'([.!?])\s*([A-Z])', r'\1 \2', text)
        
        text = re.sub(r'([.!?])\s*([a-z])', r'\1 \2', text)
        
        text = re.sub(r'([,;:])\s*', r'\1 ', text)
        
        text = re.sub(r'\s+', ' ', text).strip()
        
        logger.debug(f"格式化英文文本输出: {text[:200]}...")
        return text
    
    def transcribe(self, audio_path: str | Path) -> dict:
        if self.engine is None:
            self.initialize()
        
        if self.language == "en" and self.engine_type == "sensevoice":
            return self._transcribe_sensevoice(audio_path)
        elif self.engine_type == "qwen3-asr" and isinstance(self.engine, Qwen3ASREngine):
            audio_path = Path(audio_path)
            duration = self.engine._get_audio_duration(audio_path)
            if duration > 30:
                result = self.engine.transcribe_long_audio(audio_path)
            else:
                result = self.engine.transcribe(audio_path)
            return {
                "text": result.text,
                "segments": result.segments,
                "duration": result.duration_seconds,
                "inference_time": result.inference_time,
                "engine": self.engine_type
            }
        else:
            result = self.engine.transcribe(audio_path)
            return {
                "text": result.text,
                "segments": result.segments,
                "duration": result.duration_seconds,
                "inference_time": result.inference_time,
                "engine": self.engine_type
            }
    
    def _transcribe_sensevoice(self, audio_path: str | Path) -> dict:
        import time
        from pydub import AudioSegment
        
        audio_path = Path(audio_path)
        logger.info(f"开始SenseVoice转写: {audio_path.name}")
        
        audio = AudioSegment.from_file(str(audio_path))
        duration = len(audio) / 1000.0
        
        start_time = time.time()
        result = self.engine.generate(input=str(audio_path))
        inference_time = time.time() - start_time
        
        logger.info(f"SenseVoice推理完成, 耗时: {inference_time:.2f}秒, 音频时长: {duration:.2f}秒")
        
        if result and len(result) > 0:
            raw_text = result[0].get("text", "")
            logger.info(f"SenseVoice原始结果长度: {len(raw_text)}字符")
            
            clean_text = self._clean_sensevoice_output(raw_text)
            punctuated_text = self._add_punctuation(clean_text)
            formatted_text = self._format_english_text(punctuated_text)
            
            logger.info(f"最终转写结果: {formatted_text[:100]}...")
            
            return {
                "text": formatted_text,
                "raw_text": raw_text,
                "segments": [],
                "duration": duration,
                "inference_time": inference_time,
                "engine": "sensevoice"
            }
        
        logger.warning("SenseVoice返回空结果")
        return {
            "text": "",
            "segments": [],
            "duration": duration,
            "inference_time": inference_time,
            "engine": "sensevoice"
        }
    
    def transcribe_with_diarization(self, audio_path: str | Path) -> dict:
        if self.engine is None:
            self.initialize()
        
        if self.language == "en" and self.engine_type == "sensevoice":
            return self._transcribe_sensevoice_with_diarization(audio_path)
        elif self.engine_type == "qwen3-asr":
            return self._transcribe_qwen3_asr(audio_path)
        else:
            return self._transcribe_funasr_with_diarization(audio_path)
    
    def _transcribe_sensevoice_with_diarization(self, audio_path: str | Path) -> dict:
        import time
        from pydub import AudioSegment
        
        audio_path = Path(audio_path)
        logger.info(f"开始SenseVoice转写(带说话人分离): {audio_path.name}")
        
        audio = AudioSegment.from_file(str(audio_path))
        duration = len(audio) / 1000.0
        
        start_time = time.time()
        result = self.engine.generate(input=str(audio_path))
        inference_time = time.time() - start_time
        
        logger.info(f"SenseVoice推理完成, 耗时: {inference_time:.2f}秒, 音频时长: {duration:.2f}秒")
        
        if result and len(result) > 0:
            raw_text = result[0].get("text", "")
            logger.info(f"SenseVoice原始结果长度: {len(raw_text)}字符")
            
            clean_text = self._clean_sensevoice_output(raw_text)
            punctuated_text = self._add_punctuation(clean_text)
            formatted_text = self._format_english_text(punctuated_text)
            
            logger.info(f"格式化后文本: {formatted_text[:100]}...")
            
            sentences = re.split(r'(?<=[.!?])\s+', formatted_text)
            logger.info(f"分割为{len(sentences)}个句子")
            
            turns = []
            current_speaker = "spk0"
            for i, sentence in enumerate(sentences):
                if sentence.strip():
                    if i % 2 == 0:
                        current_speaker = "spk0"
                    else:
                        current_speaker = "spk1"
                    
                    turns.append({
                        "turn_index": i,
                        "speaker_id": current_speaker,
                        "text": sentence.strip(),
                        "start_ms": i * 5000,
                        "end_ms": (i + 1) * 5000,
                        "confidence": 1.0
                    })
            
            logger.info(f"生成{len(turns)}个对话轮次")
            
            return {
                "turns": turns,
                "duration": duration,
                "inference_time": inference_time,
                "engine": "sensevoice",
                "note": "SenseVoice不支持说话人分离，使用交替分配"
            }
        
        logger.warning("SenseVoice返回空结果")
        return {
            "turns": [],
            "duration": duration,
            "inference_time": inference_time,
            "engine": "sensevoice"
        }
    
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
                    "end_ms": segment.get("end", 0),
                    "confidence": segment.get("confidence", 1.0)
                })
        else:
            turns.append({
                "turn_index": 0,
                "speaker_id": "spk0",
                "text": result.text,
                "start_ms": 0,
                "end_ms": int(result.duration_seconds * 1000),
                "confidence": 1.0
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
                    "end_ms": segment.get("end_ms", 0),
                    "confidence": segment.get("confidence", 1.0)
                })
        elif segments:
            for i, segment in enumerate(segments):
                speaker_id = f"spk{segment.get('spk', 0)}" if "spk" in segment else "unknown"
                turns.append({
                    "turn_index": i,
                    "speaker_id": speaker_id,
                    "text": segment.get("text", ""),
                    "start_ms": segment.get("start", 0),
                    "end_ms": segment.get("end", 0),
                    "confidence": segment.get("confidence", 1.0)
                })
        else:
            turns.append({
                "turn_index": 0,
                "speaker_id": "unknown",
                "text": result.text,
                "start_ms": 0,
                "end_ms": int(result.duration_seconds * 1000),
                "confidence": 1.0
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
