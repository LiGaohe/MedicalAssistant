from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime

from ..database import Base


class Task(Base):
    __tablename__ = "tasks"
    
    task_id = Column(String, primary_key=True, index=True)
    visit_id = Column(String, ForeignKey("visits.visit_id"), nullable=False)
    task_type = Column(String, nullable=False)
    status = Column(String, default="pending")
    progress = Column(Integer, default=0)
    error_message = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    visit = relationship("Visit", back_populates="tasks")
