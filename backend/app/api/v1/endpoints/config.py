"""Config management API — CRUD for models, repositories, notify configs."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from pydantic import BaseModel
from typing import Optional

from app.core.database import get_db
from app.core.security import encrypt, decrypt
from app.models import AIModel, Repository, NotifyConfig
from app.services.git.webhook_parser import _normalize_url

router = APIRouter()


# ── AI Models ──────────────────────────────────────────────────────────────

class AIModelCreate(BaseModel):
    name: str
    provider: str
    model_id: str
    api_base: Optional[str] = None
    api_key: Optional[str] = None
    is_default: bool = False
    config: dict = {}


@router.get("/models")
async def list_models(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AIModel))
    models = result.scalars().all()
    return [
        {
            "id": m.id,
            "name": m.name,
            "provider": m.provider,
            "model_id": m.model_id,
            "api_base": m.api_base,
            "is_default": m.is_default,
            "config": m.config,
        }
        for m in models
    ]


@router.post("/models", status_code=201)
async def create_model(body: AIModelCreate, db: AsyncSession = Depends(get_db)):
    if body.is_default:
        await db.execute(update(AIModel).values(is_default=False))

    model = AIModel(
        name=body.name,
        provider=body.provider,
        model_id=body.model_id,
        api_base=body.api_base,
        api_key_encrypted=encrypt(body.api_key) if body.api_key else None,
        is_default=body.is_default,
        config=body.config,
    )
    db.add(model)
    await db.commit()
    await db.refresh(model)
    return {"id": model.id, "name": model.name}


@router.put("/models/{model_id}")
async def update_model(model_id: int, body: AIModelCreate, db: AsyncSession = Depends(get_db)):
    model = (await db.execute(select(AIModel).where(AIModel.id == model_id))).scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    if body.is_default:
        await db.execute(update(AIModel).where(AIModel.id != model_id).values(is_default=False))

    model.name = body.name
    model.provider = body.provider
    model.model_id = body.model_id
    model.api_base = body.api_base
    if body.api_key:
        model.api_key_encrypted = encrypt(body.api_key)
    model.is_default = body.is_default
    model.config = body.config
    await db.commit()
    return {"success": True}


@router.delete("/models/{model_id}", status_code=204)
async def delete_model(model_id: int, db: AsyncSession = Depends(get_db)):
    await db.execute(delete(AIModel).where(AIModel.id == model_id))
    await db.commit()


# ── Repositories ───────────────────────────────────────────────────────────

class RepoCreate(BaseModel):
    name: str
    platform: str
    repo_url: str
    webhook_secret: Optional[str] = None
    git_token: Optional[str] = None
    branch_rules: dict = {"feature/*": "develop", "develop": "main"}
    ai_model_id: Optional[int] = None
    skills_config: dict = {}
    enabled: bool = True


@router.get("/repositories")
async def list_repos(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Repository))
    repos = result.scalars().all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "platform": r.platform,
            "repo_url": r.repo_url,
            "branch_rules": r.branch_rules,
            "ai_model_id": r.ai_model_id,
            "skills_config": r.skills_config,
            "enabled": r.enabled,
        }
        for r in repos
    ]


@router.post("/repositories", status_code=201)
async def create_repo(body: RepoCreate, db: AsyncSession = Depends(get_db)):
    repo = Repository(
        name=body.name,
        platform=body.platform,
        repo_url=_normalize_url(body.repo_url),
        webhook_secret=body.webhook_secret,
        git_token_encrypted=encrypt(body.git_token) if body.git_token else None,
        branch_rules=body.branch_rules,
        ai_model_id=body.ai_model_id,
        skills_config=body.skills_config,
        enabled=body.enabled,
    )
    db.add(repo)
    await db.commit()
    await db.refresh(repo)
    return {"id": repo.id, "name": repo.name}


@router.put("/repositories/{repo_id}")
async def update_repo(repo_id: int, body: RepoCreate, db: AsyncSession = Depends(get_db)):
    repo = (await db.execute(select(Repository).where(Repository.id == repo_id))).scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    repo.name = body.name
    repo.platform = body.platform
    repo.repo_url = _normalize_url(body.repo_url)
    if body.webhook_secret:
        repo.webhook_secret = body.webhook_secret
    if body.git_token:
        repo.git_token_encrypted = encrypt(body.git_token)
    repo.branch_rules = body.branch_rules
    repo.ai_model_id = body.ai_model_id
    repo.skills_config = body.skills_config
    repo.enabled = body.enabled
    await db.commit()
    return {"success": True}


@router.delete("/repositories/{repo_id}", status_code=204)
async def delete_repo(repo_id: int, db: AsyncSession = Depends(get_db)):
    await db.execute(delete(Repository).where(Repository.id == repo_id))
    await db.commit()


# ── Notify Configs ─────────────────────────────────────────────────────────

class NotifyCreate(BaseModel):
    name: str
    provider: str
    config: dict
    is_default: bool = False
    enabled: bool = True


@router.get("/notify-configs")
async def list_notify(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(NotifyConfig))
    items = result.scalars().all()
    return [{"id": n.id, "name": n.name, "provider": n.provider, "is_default": n.is_default, "enabled": n.enabled} for n in items]


@router.post("/notify-configs", status_code=201)
async def create_notify(body: NotifyCreate, db: AsyncSession = Depends(get_db)):
    if body.is_default:
        await db.execute(update(NotifyConfig).values(is_default=False))
    nc = NotifyConfig(**body.model_dump())
    db.add(nc)
    await db.commit()
    await db.refresh(nc)
    return {"id": nc.id}


@router.delete("/notify-configs/{nc_id}", status_code=204)
async def delete_notify(nc_id: int, db: AsyncSession = Depends(get_db)):
    await db.execute(delete(NotifyConfig).where(NotifyConfig.id == nc_id))
    await db.commit()
