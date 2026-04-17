import re
from typing import List, Dict


class TranscriptNormalizer:
    def normalize(self, turns: List[Dict]) -> List[Dict]:
        """
        标准化转写结果。
        
        注意：不进行角色识别，直接输出原始 speaker_id。
        角色识别（医生/患者）应由后续模块（大模型）处理。
        """
        normalized_turns = []
        
        for i, turn in enumerate(turns):
            normalized_turn = {
                "turn_index": i,
                "speaker_id": turn.get("speaker_id", "unknown"),
                "text": self._normalize_text(turn.get("text", "")),
                "original_text": turn.get("text", ""),
                "start_ms": turn.get("start_ms", 0),
                "end_ms": turn.get("end_ms", 0)
            }
            normalized_turns.append(normalized_turn)
        
        return normalized_turns
    
    def _normalize_text(self, text: str) -> str:
        text = re.sub(r'\s+', '', text)
        text = self._normalize_punctuation(text)
        text = self._normalize_numbers(text)
        return text
    
    def _normalize_punctuation(self, text: str) -> str:
        punctuation_map = {
            ',': '，',
            '.': '。',
            '?': '？',
            '!': '！',
            ':': '：',
            ';': '；'
        }
        for en_punc, cn_punc in punctuation_map.items():
            text = text.replace(en_punc, cn_punc)
        return text
    
    def _normalize_numbers(self, text: str) -> str:
        return text
