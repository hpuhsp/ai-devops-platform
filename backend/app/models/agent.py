from sqlalchemy import Column, Integer, String, Boolean, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.core.database import Base


class Agent(Base):
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    stage_type = Column(String(50), nullable=False, index=True)
    skill_type = Column(String(20), nullable=False, default="builtin")
    skill_name = Column(String(100), nullable=False)
    model_id = Column(Integer, ForeignKey("ai_models.id"), nullable=True)

    skill_config = Column(JSONB, default={})
    model_config = Column(JSONB, default={})
    policy_config = Column(JSONB, default={})

    enabled = Column(Boolean, default=True)
    is_system = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
