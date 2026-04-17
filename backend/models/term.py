from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text, Boolean
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
    created_at = Column(DateTime, default=datetime.utcnow)
    
    visit = relationship("Visit", back_populates="normalized_terms")
    turn = relationship("TranscriptTurn", back_populates="normalized_terms")
