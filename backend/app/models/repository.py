from sqlalchemy import Column, Integer, String, Boolean, Text, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.core.database import Base


class Repository(Base):
    __tablename__ = "repositories"
    __table_args__ = (
        # Hot path: webhook handler filters repos by (platform, enabled).
        Index("ix_repositories_platform_enabled", "platform", "enabled"),
    )

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    platform = Column(String(20), nullable=False)   # gitlab/github/gitea
    repo_url = Column(String(500), nullable=False)
    webhook_secret = Column(String(200))
    git_token_encrypted = Column(Text)              # AES encrypted
    branch_rules = Column(JSONB, default={
        "feature/*": "develop",
        "develop": "main",
    })
    ai_model_id = Column(Integer, ForeignKey("ai_models.id"), nullable=True)
    skills_config = Column(JSONB, default={})       # override default skills config
    agent_bindings = Column(JSONB, default={})      # {stage_type: agent_id}
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
