from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.core.database import Base


class NotificationPolicy(Base):
    """Independent notification policy — matches events and routes to notify channels."""

    __tablename__ = "notification_policies"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    repo_ids = Column(JSONB, default=[])            # [] = all repos
    branch_patterns = Column(JSONB, default=[])      # [] = all branches
    event_types = Column(JSONB, default=[])          # [] = all events
    stage_types = Column(JSONB, default=[])          # [] = all stages
    status_filter = Column(JSONB, default=[])        # [] = all statuses
    min_severity = Column(String(20), default="all") # all/low/medium/high/critical
    blocked_only = Column(Boolean, default=False)
    notify_config_id = Column(Integer, ForeignKey("notify_configs.id"), nullable=True)
    targets = Column(JSONB, default=[])              # [{type, id}]
    enabled = Column(Boolean, default=True)
    priority = Column(Integer, default=50)           # higher = matched first
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
