from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime

from ..database import Base


class TranscriptTurn(Base):
    __tablename__ = "transcript_turns"
    
    turn_id = Column(Integer, primary_key=True, autoincrement=True)
    visit_id = Column(String, ForeignKey("visits.visit_id"), nullable=False)
    turn_index = Column(Integer, nullable=False)
    speaker = Column(String, nullable=False)
    text = Column(String, nullable=False)
    original_text = Column(String, nullable=True)
    corrected_text = Column(String, nullable=True)
    start_ms = Column(Integer, nullable=False)
    end_ms = Column(Integer, nullable=False)
    confidence = Column(Float, nullable=True, default=1.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    visit = relationship("Visit", back_populates="turns")
    corrections = relationship("ASRCorrection", back_populates="turn", cascade="all, delete-orphan")
    evidence_spans = relationship("EvidenceSpan", back_populates="turn", cascade="all, delete-orphan")
    normalized_terms = relationship("NormalizedTerm", back_populates="turn", cascade="all, delete-orphan")


class ASRCorrection(Base):
    __tablename__ = "asr_corrections"
    
    correction_id = Column(Integer, primary_key=True, autoincrement=True)
    visit_id = Column(String, ForeignKey("visits.visit_id"), nullable=False)
    turn_id = Column(Integer, ForeignKey("transcript_turns.turn_id"), nullable=False)
    original_word = Column(String, nullable=False)
    corrected_word = Column(String, nullable=False)
    correction_type = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    visit = relationship("Visit", back_populates="corrections")
    turn = relationship("TranscriptTurn", back_populates="corrections")
