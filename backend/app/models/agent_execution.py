from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.core.database import Base


class AgentExecution(Base):
    __tablename__ = "agent_executions"

    id = Column(Integer, primary_key=True)
    task_id = Column(String(100), ForeignKey("ai_tasks.task_id"), nullable=False, index=True)
    agent_type = Column(String(50), nullable=False)
    round_number = Column(Integer, default=1)
    input_data = Column(JSONB)
    output_data = Column(JSONB)
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    duration_ms = Column(Integer)
    status = Column(String(20), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
