"""Notification Policy API — CRUD + test-send."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.notification_policy import NotificationPolicy

router = APIRouter()


class PolicyCreate(BaseModel):
    name: str
    description: Optional[str] = None
    repo_ids: list[int] = Field(default_factory=list)
    branch_patterns: list[str] = Field(default_factory=list)
    event_types: list[str] = Field(default_factory=list)
    stage_types: list[str] = Field(default_factory=list)
    status_filter: list[str] = Field(default_factory=list)
    min_severity: str = "all"
    blocked_only: bool = False
    notify_config_id: Optional[int] = None
    targets: list[dict] = Field(default_factory=list)
    enabled: bool = True
    priority: int = 50


class PolicyUpdate(PolicyCreate):
    pass


def _serialize(p: NotificationPolicy) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "repo_ids": p.repo_ids or [],
        "branch_patterns": p.branch_patterns or [],
        "event_types": p.event_types or [],
        "stage_types": p.stage_types or [],
        "status_filter": p.status_filter or [],
        "min_severity": p.min_severity or "all",
        "blocked_only": p.blocked_only or False,
        "notify_config_id": p.notify_config_id,
        "targets": p.targets or [],
        "enabled": p.enabled,
        "priority": p.priority or 50,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


@router.get("/notification-policies")
async def list_policies(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(NotificationPolicy).order_by(NotificationPolicy.priority.desc())
    )
    return [_serialize(p) for p in result.scalars().all()]


@router.post("/notification-policies", status_code=201)
async def create_policy(body: PolicyCreate, db: AsyncSession = Depends(get_db)):
    policy = NotificationPolicy(
        name=body.name,
        description=body.description,
        repo_ids=body.repo_ids,
        branch_patterns=body.branch_patterns,
        event_types=body.event_types,
        stage_types=body.stage_types,
        status_filter=body.status_filter,
        min_severity=body.min_severity,
        blocked_only=body.blocked_only,
        notify_config_id=body.notify_config_id,
        targets=body.targets,
        enabled=body.enabled,
        priority=body.priority,
    )
    db.add(policy)
    await db.commit()
    await db.refresh(policy)
    return _serialize(policy)


@router.put("/notification-policies/{policy_id}")
async def update_policy(policy_id: int, body: PolicyUpdate, db: AsyncSession = Depends(get_db)):
    policy = (await db.execute(
        select(NotificationPolicy).where(NotificationPolicy.id == policy_id)
    )).scalar_one_or_none()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")

    for field in [
        "name", "description", "repo_ids", "branch_patterns", "event_types",
        "stage_types", "status_filter", "min_severity", "blocked_only",
        "notify_config_id", "targets", "enabled", "priority",
    ]:
        setattr(policy, field, getattr(body, field))

    await db.commit()
    return _serialize(policy)


@router.delete("/notification-policies/{policy_id}", status_code=204)
async def delete_policy(policy_id: int, db: AsyncSession = Depends(get_db)):
    await db.execute(delete(NotificationPolicy).where(NotificationPolicy.id == policy_id))
    await db.commit()


@router.post("/notification-policies/{policy_id}/test")
async def test_policy(policy_id: int, db: AsyncSession = Depends(get_db)):
    """Send a test notification through the matched policy."""
    policy = (await db.execute(
        select(NotificationPolicy).where(NotificationPolicy.id == policy_id)
    )).scalar_one_or_none()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")

    if not policy.notify_config_id:
        raise HTTPException(status_code=400, detail="Policy has no notify channel configured")

    from app.services.notify.feishu import build_notify_provider
    from app.services.notify.base import NotifyMessage
    from app.models.notify_config import NotifyConfig

    notify_config = (await db.execute(
        select(NotifyConfig).where(NotifyConfig.id == policy.notify_config_id)
    )).scalar_one_or_none()

    if not notify_config:
        raise HTTPException(status_code=404, detail="Notify config not found")

    sent = 0
    failed = 0
    targets = policy.targets or [{"type": "notify_config", "name": notify_config.name}]
    for target in targets:
        cfg = dict(notify_config.config or {})
        if target.get("webhook_url"):
            cfg["webhook_url"] = target["webhook_url"]
        if target.get("sign_key"):
            cfg["sign_key"] = target["sign_key"]

        provider = build_notify_provider({
            "id": notify_config.id,
            "name": notify_config.name,
            "provider": notify_config.provider,
            "config": cfg,
        })
        msg = NotifyMessage(
            title="通知策略测试",
            content=f"策略「{policy.name}」测试发送成功",
            message_type="test",
            data={"policy_name": policy.name, "target": target},
            color="green",
        )
        if await provider.send(msg):
            sent += 1
        else:
            failed += 1

    if sent == 0:
        raise HTTPException(status_code=500, detail="Test send failed")

    return {"status": "sent", "policy_id": policy.id, "sent": sent, "failed": failed}
