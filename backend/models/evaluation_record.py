"""
病历质量评估记录模型

存储基于LLM的病历质量评估结果
"""

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Float, JSON
from sqlalchemy.orm import relationship
from datetime import datetime

from ..database import Base


class EvaluationRecord(Base):
    __tablename__ = "evaluation_records"
    
    evaluation_id = Column(Integer, primary_key=True, autoincrement=True)
    record_id = Column(Integer, ForeignKey("emr_records.record_id"), nullable=False)
    
    consistency_result = Column(JSON, nullable=True)
    support_rate = Column(Float, nullable=True)
    hallucination_rate = Column(Float, nullable=True)
    internal_consistency_score = Column(Float, nullable=True)
    
    completeness_result = Column(JSON, nullable=True)
    recall_rate = Column(Float, nullable=True)
    weighted_recall = Column(Float, nullable=True)
    
    quality_result = Column(JSON, nullable=True)
    quality_total_score = Column(Float, nullable=True)
    
    safety_result = Column(JSON, nullable=True)
    has_high_risk = Column(Integer, nullable=True)
    high_risk_count = Column(Integer, nullable=True)
    
    overall_score = Column(Float, nullable=True)
    evaluation_metadata = Column(JSON, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    emr_record = relationship("EMRRecord", back_populates="evaluations")
    
    def to_dict(self):
        return {
            "evaluation_id": self.evaluation_id,
            "record_id": self.record_id,
            "support_rate": self.support_rate,
            "hallucination_rate": self.hallucination_rate,
            "internal_consistency_score": self.internal_consistency_score,
            "recall_rate": self.recall_rate,
            "weighted_recall": self.weighted_recall,
            "quality_total_score": self.quality_total_score,
            "has_high_risk": bool(self.has_high_risk) if self.has_high_risk is not None else None,
            "high_risk_count": self.high_risk_count,
            "overall_score": self.overall_score,
            "consistency_result": self.consistency_result,
            "completeness_result": self.completeness_result,
            "quality_result": self.quality_result,
            "safety_result": self.safety_result,
            "evaluation_metadata": self.evaluation_metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }
