import json
from pathlib import Path
from typing import Tuple, List, Dict


class ASRPostprocessor:
    def __init__(self, rules_path: str = "config/asr_correction_rules.json"):
        self.rules_path = Path(rules_path)
        self.rules = self._load_rules()
        self.correction_index = self._build_correction_index()
    
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
