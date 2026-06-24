from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import structlog

from app.core.config import settings
from app.core.database import engine, Base
from app.api.v1.router import api_router

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Refuse to boot with the repo's default crypto secrets outside DEBUG —
    # otherwise stored Git tokens / API keys are "encrypted" with a public key.
    if settings.has_insecure_secrets:
        if settings.DEBUG:
            logger.warning("app.insecure_secrets",
                           detail="Using default SECRET_KEY/ENCRYPTION_KEY — DEBUG only, never deploy like this.")
        else:
            raise RuntimeError(
                "Refusing to start: default SECRET_KEY/ENCRYPTION_KEY detected in non-DEBUG mode. "
                "Set strong random values via the ENCRYPTION_KEY / SECRET_KEY environment variables."
            )

    # Startup: create tables.
    # DEBUG = local convenience (auto-create). Non-DEBUG relies on Alembic migrations
    # (`alembic upgrade head`) so schema changes are versioned — see backend/alembic.
    if settings.DEBUG:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    logger.info("app.startup", version=settings.APP_VERSION)
    yield
    # Shutdown
    await engine.dispose()
    logger.info("app.shutdown")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/health")
async def health():
    return {"status": "ok", "version": settings.APP_VERSION}
