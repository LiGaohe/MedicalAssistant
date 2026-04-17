from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime

from ..database import Base


class EvidenceSpan(Base):
    __tablename__ = "evidence_spans"
    
    evidence_id = Column(Integer, primary_key=True, autoincrement=True)
    visit_id = Column(String, ForeignKey("visits.visit_id"), nullable=False)
    turn_id = Column(Integer, ForeignKey("transcript_turns.turn_id"), nullable=False)
    field_type = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    start_char = Column(Integer, nullable=True)
    end_char = Column(Integer, nullable=True)
    confidence = Column(Float, nullable=False, default=0.0)
    score = Column(Float, nullable=False, default=0.0)
    reasoning = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    visit = relationship("Visit", back_populates="evidence_spans")
    turn = relationship("TranscriptTurn", back_populates="evidence_spans")
