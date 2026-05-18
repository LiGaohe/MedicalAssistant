import json
import re
import logging
from typing import Dict, Optional, List
from pathlib import Path

logger = logging.getLogger(__name__)


class EvaluationNormalizer:
    FIELD_TERM_TYPE_MAP = {
        "主诉": "symptom",
        "现病史": "symptom",
        "辅助检查": "diagnosis",
        "既往史": "symptom",
        "诊断": "diagnosis",
        "建议": "diagnosis",
    }

    def __init__(self, synonyms_path: Optional[str] = None):
        self.synonym_map: Dict[str, str] = {}
        self._load_synonyms(synonyms_path)
        logger.info(f"EvaluationNormalizer initialized with {len(self.synonym_map)} synonym mappings")

    def _load_synonyms(self, synonyms_path: Optional[str]):
        if not synonyms_path:
            default_path = Path(__file__).parent.parent.parent.parent / "data" / "text" / "colloquial_synonyms.json"
            if default_path.exists():
                synonyms_path = str(default_path)
            else:
                logger.warning("No synonyms file found, normalizer will be identity-only")
                return

        try:
            with open(synonyms_path, 'r', encoding='utf-8') as f:
                raw: Dict[str, List[str]] = json.load(f)

            for colloquial, standard_list in raw.items():
                if standard_list:
                    self.synonym_map[colloquial] = standard_list[0]

            logger.info(f"Loaded {len(self.synonym_map)} synonym mappings from {synonyms_path}")
        except Exception as e:
            logger.error(f"Failed to load synonyms: {e}")

    def normalize_text(self, text: str) -> str:
        if not text or not self.synonym_map:
            return text or ""

        sorted_keys = sorted(self.synonym_map.keys(), key=len, reverse=True)

        result = text
        for colloquial in sorted_keys:
            if colloquial in result:
                standard = self.synonym_map[colloquial]
                result = result.replace(colloquial, standard)

        return result

    def normalize_field(self, field_name: str, text: str) -> str:
        return self.normalize_text(text)

    def normalize_report(self, report: Dict[str, str]) -> Dict[str, str]:
        normalized = {}
        for field_name, text in report.items():
            normalized[field_name] = self.normalize_field(field_name, text)
        return normalized
