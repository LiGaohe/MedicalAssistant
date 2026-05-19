from sqlalchemy import Column, String, Text, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from datetime import datetime

from ..database import Base


class AtomicFact(Base):
    __tablename__ = "atomic_facts"

    fact_id = Column(String, primary_key=True, index=True)
    visit_id = Column(String, ForeignKey("visits.visit_id"), nullable=False)
    section_candidate = Column(String, nullable=False)
    concept_type = Column(String, nullable=False)
    mention = Column(Text, nullable=False)
    normalized_term = Column(String, nullable=True)
    normalized_code = Column(String, nullable=True)
    polarity = Column(String, nullable=False, default="present")
    temporality = Column(String, nullable=False, default="unknown")
    certainty = Column(String, nullable=False, default="supported")
    speaker = Column(String, nullable=False, default="patient")
    evidence_turn_ids = Column(JSON, nullable=True)
    evidence_text = Column(JSON, nullable=True)
    asr_risk = Column(String, nullable=False, default="low")
    normalization_needed = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    visit = relationship("Visit", back_populates="atomic_facts")