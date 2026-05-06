from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    APP_NAME: str = "中文门诊病历生成系统"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True
    
    DATABASE_URL: str = "sqlite:///data/database/medical.db"
    
    AUDIO_STORAGE_PATH: str = "data/audio"
    MAX_AUDIO_SIZE: int = 100 * 1024 * 1024
    
    ASR_ENGINE: str = "funasr"
    ASR_DEVICE: str = "cpu"
    HOTWORD_PATH: str = "config/hotwords_medical.txt"
    HOTWORD_PATH_EN: str = "config/hotwords_medical_en.txt"
    
    ASR_MODEL_ZH: str = "paraformer-zh"
    ASR_MODEL_EN: str = "paraformer-en"
    
    QWEN3_ASR_MODEL_SIZE: str = "1.7B"
    QWEN3_ASR_LANGUAGE: str = "Chinese"
    
    ENABLE_DIARIZATION: bool = True
    ENABLE_ASR_CORRECTION: bool = True
    CORRECTION_CONFIDENCE_THRESHOLD: float = 0.7
    
    LLM_DEBUG_MODE: bool = False
    LLM_SEGMENT_TURNS: int = 10
    
    DEFAULT_LANGUAGE: str = "zh"
    SUPPORTED_LANGUAGES: list = ["zh", "en"]
    
    UMLS_API_KEY: str = ""
    UMLS_ENABLED: bool = False
    UMLS_CACHE_DIR: str = "data/cache/umls"
    UMLS_CACHE_TTL_HOURS: int = 168
    UMLS_REQUEST_TIMEOUT: int = 30
    UMLS_MAX_RETRIES: int = 3
    UMLS_RATE_LIMIT_DELAY: float = 0.1
    UMLS_MAX_CONCURRENT: int = 5

    TERMINOLOGY_PARALLEL_ENABLED: bool = True
    
    TRANSLATION_ENABLED: bool = True
    TRANSLATION_MODEL: str = "Helsinki-NLP/opus-mt-zh-en"
    TRANSLATION_DEVICE: str = "cpu"
    
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
