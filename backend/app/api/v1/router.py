from fastapi import APIRouter
from .endpoints import webhook, config, tasks, stats

api_router = APIRouter()

api_router.include_router(webhook.router, prefix="/webhook", tags=["webhook"])
api_router.include_router(config.router, prefix="/api/v1", tags=["config"])
api_router.include_router(tasks.router, prefix="/api/v1/tasks", tags=["tasks"])
api_router.include_router(stats.router, prefix="/api/v1/stats", tags=["stats"])
