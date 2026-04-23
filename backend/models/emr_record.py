from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, JSON
from sqlalchemy.orm import relationship
from datetime import datetime

from ..database import Base


class EMRRecord(Base):
    __tablename__ = "emr_records"
    
    record_id = Column(Integer, primary_key=True, autoincrement=True)
    visit_id = Column(String, ForeignKey("visits.visit_id"), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    record_type = Column(String, nullable=False, default="system_draft")
    emr_json = Column(JSON, nullable=False)
    evidence_mapping = Column(JSON, nullable=True)
    validation_errors = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    visit = relationship("Visit", back_populates="emr_records")
    evaluations = relationship("EvaluationRecord", back_populates="emr_record")
    
    def to_dict(self):
        return {
            "record_id": self.record_id,
            "visit_id": self.visit_id,
            "version": self.version,
            "record_type": self.record_type,
            "emr_json": self.emr_json,
            "evidence_mapping": self.evidence_mapping,
            "validation_errors": self.validation_errors,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }
