from sqlalchemy import Column, Integer, String, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from sqlalchemy import DateTime
from app.core.database import Base


class PipelineRule(Base):
    """
    Branch-to-stages mapping rule.
    Rules are matched in descending priority order; first match wins.
    Stages: code_review, test_generation, auto_merge, build (p2), deploy (p2)
    """
    __tablename__ = "pipeline_rules"

    id       = Column(Integer, primary_key=True)
    repo_id  = Column(Integer, ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False)
    name     = Column(String(100), nullable=False)
    pattern  = Column(String(200), nullable=False)   # fnmatch pattern, e.g. feature/*
    stages   = Column(JSONB, nullable=False, default=["code_review"])
    priority = Column(Integer, nullable=False, default=50)
    enabled  = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
