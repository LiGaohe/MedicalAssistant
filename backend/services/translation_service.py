from typing import Optional, List, Dict
from ..utils.logger import logger


class TranslationService:
    def __init__(
        self,
        model_name: str = "Helsinki-NLP/opus-mt-zh-en",
        device: str = "cpu"
    ):
        self.model_name = model_name
        self.device = device
        self.translator = None
        self._load_model()

    def _load_model(self):
        try:
            logger.info(f"Loading translation model: {self.model_name}")
            from transformers import pipeline

            self.translator = pipeline(
                "translation",
                model=self.model_name,
                device=0 if self.device == "cuda" else -1
            )
            logger.info("Translation model loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load translation model: {e}")
            logger.warning("Translation service will be disabled, falling back to LLM translation")
            self.translator = None

    def translate_zh_to_en(self, text: str) -> Optional[str]:
        if not self.is_available():
            return None

        try:
            result = self.translator(text, max_length=512)
            translated_text = result[0]['translation_text']
            logger.info(f"Translated '{text}' to '{translated_text}'")
            return translated_text
        except Exception as e:
            logger.error(f"Translation failed for '{text}': {e}")
            return None

    def is_available(self) -> bool:
        return self.translator is not None

    def batch_translate_zh_to_en(
        self,
        texts: List[str],
        batch_size: int = 8
    ) -> Dict[str, str]:
        """
        批量翻译中文术语到英文

        Args:
            texts: 待翻译文本列表
            batch_size: 每批处理数量

        Returns:
            原文到译文的映射字典
        """
        if not self.is_available():
            logger.warning("Translation service not available for batch translation")
            return {}

        if not texts:
            return {}

        try:
            logger.info(f"Starting batch translation for {len(texts)} terms")

            results = self.translator(
                texts,
                max_length=512,
                batch_size=batch_size
            )

            translations = {}
            for text, result in zip(texts, results):
                translated = result['translation_text']
                translations[text] = translated
                logger.debug(f"Batch translated '{text}' -> '{translated}'")

            logger.info(f"Batch translation completed: {len(translations)} terms translated")
            return translations

        except Exception as e:
            logger.error(f"Batch translation failed: {e}")
            return {}
