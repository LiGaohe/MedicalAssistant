from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text, Boolean, JSON
from sqlalchemy.orm import relationship
from datetime import datetime

from ..database import Base


class NormalizedTerm(Base):
    __tablename__ = "normalized_terms"
    
    term_id = Column(Integer, primary_key=True, autoincrement=True)
    visit_id = Column(String, ForeignKey("visits.visit_id"), nullable=False)
    turn_id = Column(Integer, ForeignKey("transcript_turns.turn_id"), nullable=True)
    original_term = Column(String, nullable=False)
    normalized_term = Column(String, nullable=False)
    term_type = Column(String, nullable=False)
    confidence = Column(Float, nullable=False, default=0.0)
    is_risky = Column(Boolean, default=False)
    reasoning = Column(Text, nullable=True)
    
    code = Column(String, nullable=True)
    code_system = Column(String, nullable=True)
    source = Column(String, nullable=True, default="LLM")
    candidates = Column(JSON, nullable=True)
    cui = Column(String, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    visit = relationship("Visit", back_populates="normalized_terms")
    turn = relationship("TranscriptTurn", back_populates="normalized_terms")
    
    def to_dict(self) -> dict:
        return {
            "term_id": self.term_id,
            "visit_id": self.visit_id,
            "turn_id": self.turn_id,
            "original_term": self.original_term,
            "normalized_term": self.normalized_term,
            "term_type": self.term_type,
            "confidence": self.confidence,
            "is_risky": self.is_risky,
            "reasoning": self.reasoning,
            "code": self.code,
            "code_system": self.code_system,
            "source": self.source,
            "candidates": self.candidates,
            "cui": self.cui,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }
