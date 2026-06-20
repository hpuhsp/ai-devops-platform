from sqlalchemy import Column, Integer, String, Boolean, Text, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.core.database import Base


class AIModel(Base):
    __tablename__ = "ai_models"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    provider = Column(String(50), nullable=False)   # openai/deepseek/ollama/custom
    model_id = Column(String(200), nullable=False)
    api_base = Column(String(500))
    api_key_encrypted = Column(Text)                # AES encrypted
    is_default = Column(Boolean, default=False)
    config = Column(JSONB, default={})              # temperature, max_tokens, etc.
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
