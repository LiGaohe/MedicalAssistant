from sqlalchemy import Column, String, Float, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime

from ..database import Base


class Visit(Base):
    __tablename__ = "visits"
    
    visit_id = Column(String, primary_key=True, index=True)
    patient_name = Column(String, nullable=True)
    visit_date = Column(String, nullable=True)
    audio_path = Column(String, nullable=False)
    audio_duration = Column(Float, nullable=True)
    status = Column(String, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    turns = relationship("TranscriptTurn", back_populates="visit", cascade="all, delete-orphan")
    tasks = relationship("Task", back_populates="visit", cascade="all, delete-orphan")
    corrections = relationship("ASRCorrection", back_populates="visit", cascade="all, delete-orphan")
    evidence_spans = relationship("EvidenceSpan", back_populates="visit", cascade="all, delete-orphan")
    normalized_terms = relationship("NormalizedTerm", back_populates="visit", cascade="all, delete-orphan")
    extracted_items = relationship("ExtractedItem", back_populates="visit", cascade="all, delete-orphan")
    emr_records = relationship("EMRRecord", back_populates="visit", cascade="all, delete-orphan")
