from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.core.database import Base


class NotifyConfig(Base):
    __tablename__ = "notify_configs"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    provider = Column(String(30), nullable=False)   # feishu_webhook/feishu_app/slack
    config = Column(JSONB, nullable=False)           # provider-specific config (webhook_url, app_id, etc.)
    is_default = Column(Boolean, default=False)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
