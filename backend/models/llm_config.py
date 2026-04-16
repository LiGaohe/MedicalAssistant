from sqlalchemy import Column, Integer, String, Boolean, DateTime
from datetime import datetime

from ..database import Base


class LLMConfig(Base):
    __tablename__ = "llm_configs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    config_name = Column(String(100), unique=True, nullable=False)
    provider = Column(String(50), nullable=False)
    model_name = Column(String(100), nullable=False)
    api_key = Column(String(200), nullable=True)
    api_endpoint = Column(String(200), nullable=True)
    is_active = Column(Boolean, default=True)
    max_tokens = Column(Integer, default=2048)
    temperature = Column(String(10), default="0.7")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            "id": self.id,
            "config_name": self.config_name,
            "provider": self.provider,
            "model_name": self.model_name,
            "is_active": self.is_active,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature
        }
