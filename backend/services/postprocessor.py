import json
from pathlib import Path
from typing import Tuple, List, Dict, Optional
from dataclasses import dataclass


@dataclass
class SentenceSegment:
    text: str
    start: int
    end: int
    timestamp: List[List[int]]
    spk: int


class ASRPostprocessor:
    def __init__(
        self,
        rules_path: str = "config/asr_correction_rules.json",
        split_gap_threshold_ms: int = 800,
        min_segment_duration_ms: int = 200
    ):
        self.rules_path = Path(rules_path)
        self.rules = self._load_rules()
        self.correction_index = self._build_correction_index()
        self.split_gap_threshold_ms = split_gap_threshold_ms
        self.min_segment_duration_ms = min_segment_duration_ms
    
    def _load_rules(self) -> dict:
        if self.rules_path.exists():
            with open(self.rules_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"medical_terms": {}, "pinyin_similar": {}}
    
    def _build_correction_index(self) -> dict:
        index = {}
        
        for standard_term, variants in self.rules.get("medical_terms", {}).items():
            for variant in variants:
                index[variant] = {
                    "standard": standard_term,
                    "type": "medical_term",
                    "confidence": 0.9
                }
        
        for standard_term, variants in self.rules.get("pinyin_similar", {}).items():
            for variant in variants:
                index[variant] = {
                    "standard": standard_term,
                    "type": "pinyin_similar",
                    "confidence": 0.8
                }
        
        return index
    
    def correct(self, text: str) -> Tuple[str, List[Dict]]:
        corrections = []
        corrected_text = text
        
        for wrong_word, correction_info in self.correction_index.items():
            if wrong_word in corrected_text:
                corrected_text = corrected_text.replace(
                    wrong_word,
                    correction_info["standard"]
                )
                corrections.append({
                    "original": wrong_word,
                    "corrected": correction_info["standard"],
                    "type": correction_info["type"],
                    "confidence": correction_info["confidence"]
                })
        
        return corrected_text, corrections
    
    def split_sentences_by_gap(
        self,
        sentence_info: List[Dict],
        audio_duration_ms: Optional[int] = None
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        根据时间间隔拆分句子。
        
        当句子内部的timestamp之间存在明显的时间间隔（停顿）时，
        将句子拆分成多个独立的句子。
        
        注意：由于FunASR不提供字级别的时间戳，文本分割依赖语义分析。
        如果找不到合适的语义分割点，将保留原始文本。
        
        Args:
            sentence_info: FunASR输出的sentence_info列表
            audio_duration_ms: 音频总时长（毫秒），可选
            
        Returns:
            Tuple[List[Dict], List[Dict]]: (拆分后的sentence_info, 拆分记录)
        """
        if not sentence_info:
            return [], []
        
        new_sentence_info = []
        split_records = []
        
        for sentence in sentence_info:
            text = sentence.get("text", "")
            timestamps = sentence.get("timestamp", [])
            spk = sentence.get("spk", 0)
            
            if not timestamps or len(timestamps) == 0:
                new_sentence_info.append(sentence)
                continue
            
            gaps = self._find_gaps(timestamps)
            
            if not gaps:
                new_sentence_info.append(sentence)
                continue
            
            split_segments = self._split_by_gaps(
                text=text,
                timestamps=timestamps,
                gaps=gaps,
                spk=spk
            )
            
            if len(split_segments) > 1:
                split_records.append({
                    "original_text": text,
                    "original_spk": spk,
                    "split_count": len(split_segments),
                    "gap_positions": gaps,
                    "split_segments": [
                        {
                            "text": seg.text,
                            "start": seg.start,
                            "end": seg.end,
                            "spk": seg.spk
                        }
                        for seg in split_segments
                    ]
                })
            
            for seg in split_segments:
                new_sentence_info.append({
                    "text": seg.text,
                    "start": seg.start,
                    "end": seg.end,
                    "timestamp": seg.timestamp,
                    "spk": seg.spk
                })
        
        return new_sentence_info, split_records
    
    def _find_gaps(self, timestamps: List[List[int]]) -> List[int]:
        """
        找出timestamps中存在明显时间间隔的位置。
        
        Args:
            timestamps: 时间戳列表 [[start, end], ...]
            
        Returns:
            List[int]: 存在间隔的位置索引列表
        """
        gaps = []
        
        for i in range(len(timestamps) - 1):
            current_end = timestamps[i][1]
            next_start = timestamps[i + 1][0]
            gap_duration = next_start - current_end
            
            if gap_duration >= self.split_gap_threshold_ms:
                gaps.append(i)
        
        return gaps
    
    def _split_by_gaps(
        self,
        text: str,
        timestamps: List[List[int]],
        gaps: List[int],
        spk: int
    ) -> List[SentenceSegment]:
        """
        根据间隔位置拆分句子。        
        当检测到明显的时间间隔时，直接根据timestamp的比例来分割文本。
        不再依赖语义分析，而是使用时间戳的比例来估算文本分割位置。
        
        Args:
            text: 原始文本
            timestamps: 时间戳列表
            gaps: 间隔位置列表
            spk: 原始说话人标签
            
        Returns:
            List[SentenceSegment]: 拆分后的句子片段列表
        """
        if not gaps:
            return [SentenceSegment(
                text=text,
                start=timestamps[0][0],
                end=timestamps[-1][1],
                timestamp=timestamps,
                spk=spk
            )]
        
        segments = []
        split_indices = [-1] + gaps + [len(timestamps) - 1]
        
        for i in range(len(split_indices) - 1):
            start_idx = split_indices[i] + 1
            end_idx = split_indices[i + 1] + 1
            
            segment_timestamps = timestamps[start_idx:end_idx]
            
            if not segment_timestamps:
                continue
            
            segment_start = segment_timestamps[0][0]
            segment_end = segment_timestamps[-1][1]
            
            duration = segment_end - segment_start
            if duration < self.min_segment_duration_ms:
                continue
            
            segment_text = self._estimate_text_by_timestamp_ratio(
                text=text,
                timestamps=timestamps,
                start_idx=start_idx,
                end_idx=end_idx
            )
            
            segments.append(SentenceSegment(
                text=segment_text,
                start=segment_start,
                end=segment_end,
                timestamp=segment_timestamps,
                spk=spk
            ))
        
        return segments
    
    def _estimate_text_by_timestamp_ratio(
        self,
        text: str,
        timestamps: List[List[int]],
        start_idx: int,
        end_idx: int
    ) -> str:
        """
        根据timestamp的比例估算文本片段。
        
        Args:
            text: 完整文本
            timestamps: 完整时间戳列表
            start_idx: 片段开始索引
            end_idx: 片段结束索引
            
        Returns:
            str: 估算的文本片段
        """
        total_timestamps = len(timestamps)
        segment_timestamps = end_idx - start_idx
        
        start_ratio = start_idx / total_timestamps
        end_ratio = end_idx / total_timestamps
        
        start_pos = int(len(text) * start_ratio)
        end_pos = int(len(text) * end_ratio)
        
        segment_text = text[start_pos:end_pos].strip()
        
        segment_text = self._add_punctuation(segment_text)
        
        return segment_text
    
    def _add_punctuation(self, text: str) -> str:
        """
        为文本片段添加标点符号。
        
        规则：
        1. 如果文本以标点符号结尾，保持不变
        2. 如果文本以"的时候"、"了"等结尾，添加句号
        3. 如果文本包含疑问词（"吗"、"呢"），添加问号
        4. 否则添加逗号
        
        Args:
            text: 原始文本
            
        Returns:
            str: 添加标点后的文本
        """
        if not text:
            return text
        
        if text[-1] in ["，", "。", "？", "！", ",", ".", "?", "!"]:
            return text
        
        question_indicators = ["吗", "呢", "什么", "怎么", "哪里", "谁", "几"]
        if any(indicator in text for indicator in question_indicators):
            return text + "？"
        
        sentence_end_indicators = ["的时候", "了", "的", "着", "过"]
        if any(text.endswith(indicator) for indicator in sentence_end_indicators):
            return text + "。"
        
        return text + "，"
    
    def _split_text_at_positions(self, text: str, split_positions: List[int]) -> List[str]:
        """
        在指定位置分割文本。
        
        Args:
            text: 完整文本
            split_positions: 分割位置列表
            
        Returns:
            List[str]: 分割后的文本列表
        """
        parts = []
        prev_pos = 0
        for pos in split_positions:
            parts.append(text[prev_pos:pos].strip())
            prev_pos = pos
        
        if prev_pos < len(text):
            parts.append(text[prev_pos:].strip())
        
        return parts
    
    def _find_semantic_split_positions(self, text: str, num_parts: int) -> List[int]:
        """
        找出文本中的语义分割位置。
        
        优先在以下位置分割：
        1. 标点符号后
        2. 语义转折词后（如"的时候"、"了"等）
        
        如果找不到合适的分割点，返回空列表。
        
        Args:
            text: 完整文本
            num_parts: 需要的分割点数量
            
        Returns:
            List[int]: 分割位置列表
        """
        if num_parts <= 1:
            return []
        
        split_positions = []
        
        semantic_markers = [
            "的时候", "的时候。", "的时候，",
            "了，", "了。", "了",
            "，", "。", "？", "！"
        ]
        
        for marker in semantic_markers:
            pos = text.find(marker)
            if pos > 0:
                split_pos = pos + len(marker)
                if split_pos < len(text):
                    ratio = split_pos / len(text)
                    if 0.2 <= ratio <= 0.8:
                        split_positions.append(split_pos)
                        if len(split_positions) >= num_parts - 1:
                            break
        
        return split_positions
    
    def process_asr_result(
        self,
        asr_result: Dict,
        enable_sentence_split: bool = True
    ) -> Dict:
        """
        处理ASR结果，应用所有后处理逻辑。
        
        Args:
            asr_result: ASR引擎输出的原始结果
            enable_sentence_split: 是否启用句子拆分
            
        Returns:
            Dict: 处理后的结果
        """
        result = asr_result.copy()
        
        text = result.get("text", "")
        corrected_text, text_corrections = self.correct(text)
        result["text"] = corrected_text
        result["text_corrections"] = text_corrections
        
        if enable_sentence_split and "sentence_info" in result:
            sentence_info = result["sentence_info"]
            new_sentence_info, split_records = self.split_sentences_by_gap(sentence_info)
            
            if split_records:
                result["sentence_info"] = new_sentence_info
                result["sentence_splits"] = split_records
                
                full_text = "".join(seg.get("text", "") for seg in new_sentence_info)
                result["text"] = full_text
        
        return result
