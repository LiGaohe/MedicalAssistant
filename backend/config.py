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
    
    QWEN3_ASR_MODEL_SIZE: str = "1.7B"
    QWEN3_ASR_LANGUAGE: str = "Chinese"
    
    ENABLE_DIARIZATION: bool = True
    ENABLE_ASR_CORRECTION: bool = True
    CORRECTION_CONFIDENCE_THRESHOLD: float = 0.7
    
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
