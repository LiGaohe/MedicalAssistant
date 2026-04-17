from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text, JSON
from sqlalchemy.orm import relationship
from datetime import datetime

from ..database import Base


class ExtractedItem(Base):
    __tablename__ = "extracted_items"
    
    item_id = Column(Integer, primary_key=True, autoincrement=True)
    visit_id = Column(String, ForeignKey("visits.visit_id"), nullable=False)
    field_name = Column(String, nullable=False)
    field_value = Column(Text, nullable=False)
    evidence_ids = Column(JSON, nullable=True)
    confidence = Column(Float, nullable=False, default=0.0)
    status = Column(String, default="extracted")
    created_at = Column(DateTime, default=datetime.utcnow)
    
    visit = relationship("Visit", back_populates="extracted_items")
