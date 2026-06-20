from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # App
    APP_NAME: str = "AI DevOps Platform"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    SECRET_KEY: str = "change-me-in-production-use-strong-random-key"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://devops:devops123@localhost:5432/ai_devops"
    DATABASE_SYNC_URL: str = "postgresql://devops:devops123@localhost:5432/ai_devops"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # Security
    ENCRYPTION_KEY: str = "change-me-32-bytes-encryption-key!!"  # 32 chars for AES-256

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    # Webhook
    WEBHOOK_BASE_URL: str = "http://localhost:8000"

    # Default AI (fallback when DB has no config)
    DEFAULT_AI_MODEL: str = "gpt-4o-mini"
    DEFAULT_AI_API_BASE: Optional[str] = None
    DEFAULT_AI_API_KEY: Optional[str] = None

    # Git WorkTree base directory
    WORKTREE_BASE_DIR: str = "/tmp/ai-devops-worktrees"

    model_config = {"env_file": ".env", "case_sensitive": True}


settings = Settings()
