"""Config management API — CRUD for models, repositories, notify configs."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, desc
from pydantic import BaseModel
from typing import Optional
import copy
import httpx

from app.core.database import get_db
from app.core.security import encrypt, decrypt
from app.models import AIModel, Repository, NotifyConfig, NotificationLog, NotificationPolicy
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


class ModelDiscoverRequest(BaseModel):
    provider: str
    api_base: str
    api_key: Optional[str] = None


MODEL_PRESETS = {
    "openai": {
        "label": "OpenAI",
        "api_base": "https://api.openai.com/v1",
        "models": [
            {"id": "gpt-4o-mini", "label": "GPT-4o mini"},
            {"id": "gpt-4o", "label": "GPT-4o"},
            {"id": "gpt-4.1-mini", "label": "GPT-4.1 mini"},
            {"id": "gpt-4.1", "label": "GPT-4.1"},
        ],
    },
    "deepseek": {
        "label": "DeepSeek",
        "api_base": "https://api.deepseek.com/v1",
        "models": [
            {"id": "deepseek-v4-pro", "label": "DeepSeek V4 Pro"},
            {"id": "deepseek-v4-flash", "label": "DeepSeek V4 Flash"},
            {"id": "deepseek-chat", "label": "DeepSeek Chat"},
            {"id": "deepseek-reasoner", "label": "DeepSeek Reasoner"},
        ],
    },
    "ollama": {
        "label": "Ollama",
        "api_base": "http://localhost:11434",
        "models": [
            {"id": "llama3.1", "label": "Llama 3.1"},
            {"id": "qwen2.5-coder", "label": "Qwen2.5 Coder"},
            {"id": "deepseek-coder", "label": "DeepSeek Coder"},
        ],
    },
    "azure": {
        "label": "Azure OpenAI",
        "api_base": "",
        "models": [
            {"id": "gpt-4o-mini", "label": "GPT-4o mini deployment"},
            {"id": "gpt-4o", "label": "GPT-4o deployment"},
        ],
    },
    "custom": {
        "label": "自定义 OpenAI-Compatible",
        "api_base": "",
        "models": [],
    },
}


def _fallback_models(provider: str) -> list[dict]:
    preset = MODEL_PRESETS.get(provider) or {}
    return preset.get("models") or []


def _model_urls(provider: str, api_base: str) -> list[str]:
    base = api_base.rstrip("/")
    if provider == "ollama":
        return [f"{base}/api/tags", f"{base}/v1/models", f"{base}/models"]
    if base.endswith("/v1"):
        return [f"{base}/models"]
    return [f"{base}/v1/models", f"{base}/models"]


def _extract_model_ids(provider: str, payload: dict) -> list[str]:
    if provider == "ollama" and isinstance(payload.get("models"), list):
        values = payload["models"]
    else:
        values = payload.get("data") or payload.get("models") or []

    model_ids: list[str] = []
    for item in values:
        if isinstance(item, str):
            model_id = item
        elif isinstance(item, dict):
            model_id = item.get("id") or item.get("name") or item.get("model")
            if isinstance(model_id, str) and model_id.startswith("models/"):
                model_id = model_id.split("/", 1)[1]
        else:
            continue
        if model_id and model_id not in model_ids:
            model_ids.append(model_id)
    return model_ids


@router.get("/models/presets")
async def list_model_presets():
    return MODEL_PRESETS


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


@router.post("/models/validate")
async def validate_model(body: AIModelCreate):
    from app.services.ai.engine import AIEngine, ModelConfig

    engine = AIEngine(ModelConfig(
        model_id=body.model_id,
        provider=body.provider,
        api_base=body.api_base,
        api_key=body.api_key,
        temperature=body.config.get("temperature", 0.1),
        max_tokens=min(int(body.config.get("max_tokens", 128)), 256),
    ))
    try:
        resp = await engine.complete([
            {"role": "user", "content": "请只回复 OK，用于模型连通性测试。"},
        ], max_tokens=16)
        return {
            "success": True,
            "model": resp.model,
            "content": resp.content[:200],
            "prompt_tokens": resp.prompt_tokens,
            "completion_tokens": resp.completion_tokens,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)[:1000]}


@router.post("/models/discover")
async def discover_models(body: ModelDiscoverRequest):
    provider = body.provider.lower().strip()
    api_base = body.api_base.strip()
    if not api_base:
        raise HTTPException(status_code=400, detail="API Base URL is required")

    headers = {}
    if body.api_key:
        headers["Authorization"] = f"Bearer {body.api_key}"
        if provider == "azure":
            headers["api-key"] = body.api_key

    errors: list[str] = []
    async with httpx.AsyncClient(timeout=15.0) as client:
        for url in _model_urls(provider, api_base):
            try:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                model_ids = _extract_model_ids(provider, response.json())
                if model_ids:
                    return {
                        "success": True,
                        "source": "remote",
                        "models": [{"id": model_id, "label": model_id} for model_id in model_ids],
                    }
                errors.append(f"{url}: empty model list")
            except Exception as exc:
                errors.append(f"{url}: {str(exc)[:200]}")

    fallback = _fallback_models(provider)
    if fallback:
        return {
            "success": True,
            "source": "fallback",
            "models": fallback,
            "warning": "Remote discovery failed; using local fallback models.",
            "error": "; ".join(errors)[-1000:],
        }

    return {
        "success": False,
        "source": "none",
        "models": [],
        "error": "; ".join(errors)[-1000:] or "No models discovered.",
    }


@router.post("/models/{model_id}/validate")
async def validate_saved_model(model_id: int, db: AsyncSession = Depends(get_db)):
    from app.services.ai.engine import AIEngine, ModelConfig

    model = (await db.execute(select(AIModel).where(AIModel.id == model_id))).scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    engine = AIEngine(ModelConfig(
        model_id=model.model_id,
        provider=model.provider,
        api_base=model.api_base,
        api_key=decrypt(model.api_key_encrypted) if model.api_key_encrypted else None,
        temperature=(model.config or {}).get("temperature", 0.1),
        max_tokens=min(int((model.config or {}).get("max_tokens", 128)), 256),
    ))
    try:
        resp = await engine.complete([
            {"role": "user", "content": "请只回复 OK，用于模型连通性测试。"},
        ], max_tokens=16)
        return {
            "success": True,
            "model": resp.model,
            "content": resp.content[:200],
            "prompt_tokens": resp.prompt_tokens,
            "completion_tokens": resp.completion_tokens,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)[:1000]}


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
    skills_config: dict = {}
    agent_bindings: dict = {}
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
            "skills_config": r.skills_config,
            "agent_bindings": getattr(r, "agent_bindings", None) or {},
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
        skills_config=body.skills_config,
        agent_bindings=body.agent_bindings,
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
    repo.skills_config = body.skills_config
    if "agent_bindings" in body.model_fields_set:
        repo.agent_bindings = body.agent_bindings
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


def _without_notify_config_reference(skills_config: dict | None, notify_config_id: int) -> tuple[dict, bool]:
    """Remove a deleted notify config reference from repository skills_config."""
    next_config = copy.deepcopy(skills_config or {})
    notifications = next_config.get("notifications")
    if not isinstance(notifications, dict):
        return next_config, False
    if notifications.get("notify_config_id") != notify_config_id:
        return next_config, False
    notifications.pop("notify_config_id", None)
    return next_config, True


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


@router.put("/notify-configs/{nc_id}")
async def update_notify(nc_id: int, body: NotifyCreate, db: AsyncSession = Depends(get_db)):
    nc = (await db.execute(select(NotifyConfig).where(NotifyConfig.id == nc_id))).scalar_one_or_none()
    if not nc:
        raise HTTPException(status_code=404, detail="Notify config not found")

    if body.is_default:
        await db.execute(update(NotifyConfig).where(NotifyConfig.id != nc_id).values(is_default=False))

    nc.name = body.name
    nc.provider = body.provider
    nc.config = body.config
    nc.is_default = body.is_default
    nc.enabled = body.enabled
    await db.commit()
    return {"success": True}


@router.post("/notify-configs/{nc_id}/default")
async def set_default_notify(nc_id: int, db: AsyncSession = Depends(get_db)):
    nc = (await db.execute(select(NotifyConfig).where(NotifyConfig.id == nc_id))).scalar_one_or_none()
    if not nc:
        raise HTTPException(status_code=404, detail="Notify config not found")

    await db.execute(update(NotifyConfig).where(NotifyConfig.id != nc_id).values(is_default=False))
    nc.is_default = True
    nc.enabled = True
    await db.commit()
    return {"success": True}


@router.delete("/notify-configs/{nc_id}", status_code=204)
async def delete_notify(nc_id: int, db: AsyncSession = Depends(get_db)):
    nc = (await db.execute(select(NotifyConfig).where(NotifyConfig.id == nc_id))).scalar_one_or_none()
    if not nc:
        raise HTTPException(status_code=404, detail="Notify config not found")

    await db.execute(
        update(NotificationLog)
        .where(NotificationLog.notify_config_id == nc_id)
        .values(notify_config_id=None)
    )
    await db.execute(
        update(NotificationPolicy)
        .where(NotificationPolicy.notify_config_id == nc_id)
        .values(notify_config_id=None)
    )

    repos = (await db.execute(select(Repository))).scalars().all()
    for repo in repos:
        next_config, changed = _without_notify_config_reference(repo.skills_config, nc_id)
        if changed:
            repo.skills_config = next_config

    await db.delete(nc)
    await db.commit()


@router.get("/notify-logs")
async def list_notify_logs(
    task_id: Optional[str] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    q = select(NotificationLog).order_by(desc(NotificationLog.created_at)).limit(min(limit, 200))
    if task_id:
        q = q.where(NotificationLog.task_id == task_id)
    rows = (await db.execute(q)).scalars().all()
    return [
        {
            "id": row.id,
            "task_id": row.task_id,
            "notify_config_id": row.notify_config_id,
            "event_type": row.event_type,
            "target": row.target,
            "status": row.status,
            "reason": row.reason,
            "error": row.error,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]
