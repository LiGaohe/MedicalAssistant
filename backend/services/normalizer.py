import re
from typing import List, Dict


class TranscriptNormalizer:
    def normalize(self, turns: List[Dict]) -> List[Dict]:
        normalized_turns = []
        
        for i, turn in enumerate(turns):
            normalized_turn = {
                "turn_index": i,
                "speaker": self._normalize_speaker(turn.get("speaker", "unknown")),
                "text": self._normalize_text(turn.get("text", "")),
                "original_text": turn.get("text", ""),
                "start_ms": turn.get("start_ms", 0),
                "end_ms": turn.get("end_ms", 0),
                "confidence": turn.get("confidence", 0.0)
            }
            normalized_turns.append(normalized_turn)
        
        return normalized_turns
    
    def _normalize_speaker(self, speaker: str) -> str:
        speaker_mapping = {
            "doctor": "doctor",
            "patient": "patient",
            "unknown": "unknown",
            "spk0": "doctor",
            "spk1": "patient"
        }
        return speaker_mapping.get(speaker.lower(), "unknown")
    
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
