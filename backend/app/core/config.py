from pydantic_settings import BaseSettings
from typing import Optional


# Insecure placeholder secrets shipped in the repo. The app refuses to start in
# non-DEBUG mode while either of these is still in use (see app.main lifespan).
INSECURE_SECRET_KEY = "change-me-in-production-use-strong-random-key"
INSECURE_ENCRYPTION_KEY = "change-me-32-bytes-encryption-key!!"


class Settings(BaseSettings):
    # App
    APP_NAME: str = "AI DevOps Platform"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    SECRET_KEY: str = INSECURE_SECRET_KEY

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://devops:devops123@localhost:5432/ai_devops"
    DATABASE_SYNC_URL: str = "postgresql://devops:devops123@localhost:5432/ai_devops"
    SQL_ECHO: bool = False   # log every SQL statement; decoupled from DEBUG to avoid log floods

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # Security
    ENCRYPTION_KEY: str = INSECURE_ENCRYPTION_KEY  # 32 chars for AES-256

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

    @property
    def DATABASE_PURE_URL(self) -> str:
        """psycopg2-compatible URL (no dialect prefix)."""
        return self.DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")

    @property
    def has_insecure_secrets(self) -> bool:
        """True if either crypto secret is still the repo's default placeholder."""
        return (
            self.SECRET_KEY == INSECURE_SECRET_KEY
            or self.ENCRYPTION_KEY == INSECURE_ENCRYPTION_KEY
        )

    model_config = {"env_file": ".env", "case_sensitive": True}


settings = Settings()
