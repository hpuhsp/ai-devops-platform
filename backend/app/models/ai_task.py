from sqlalchemy import Column, Integer, String, Boolean, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.core.database import Base


class AITask(Base):
    __tablename__ = "ai_tasks"

    id = Column(Integer, primary_key=True)
    task_id = Column(String(100), unique=True, nullable=False)  # Celery task ID
    repo_id = Column(Integer, ForeignKey("repositories.id"), nullable=True)
    task_type = Column(String(50), nullable=False)  # code_review/test_generation/auto_merge
    status = Column(String(20), nullable=False, default="pending")  # pending/running/success/failed
    trigger_event = Column(JSONB)           # raw webhook event
    input_data = Column(JSONB)
    output_data = Column(JSONB)
    error_message = Column(Text)
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    duration_ms = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
