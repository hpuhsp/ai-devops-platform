from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.core.database import Base


class NotificationLog(Base):
    __tablename__ = "notification_logs"

    id = Column(Integer, primary_key=True)
    task_id = Column(String(100), ForeignKey("ai_tasks.task_id"), nullable=True, index=True)
    notify_config_id = Column(Integer, ForeignKey("notify_configs.id"), nullable=True, index=True)
    event_type = Column(String(80), nullable=False, index=True)
    target = Column(String(200))
    status = Column(String(20), nullable=False)  # sent/skipped/failed
    reason = Column(String(300))
    payload = Column(JSONB)
    error = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
