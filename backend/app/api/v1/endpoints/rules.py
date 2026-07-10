"""Pipeline rule CRUD + template import API."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from pydantic import BaseModel
from typing import Optional

from app.core.database import get_db
from app.models import PipelineRule
from app.services.rules.engine import TEMPLATES, ALL_STAGES

router = APIRouter()


class RuleCreate(BaseModel):
    repo_id: int
    name: str
    pattern: str
    stages: list[str]
    priority: int = 50
    enabled: bool = True


class RuleUpdate(BaseModel):
    name: str
    pattern: str
    stages: list[str]
    priority: int
    enabled: bool = True


# ── CRUD ──────────────────────────────────────────────────────────────────────

@router.get("")
async def list_rules(repo_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(PipelineRule)
        .where(PipelineRule.repo_id == repo_id)
        .order_by(PipelineRule.priority.desc())
    )
    rules = result.scalars().all()
    return [_rule_to_dict(r) for r in rules]


@router.post("", status_code=201)
async def create_rule(body: RuleCreate, db: AsyncSession = Depends(get_db)):
    _validate_stages(body.stages)
    rule = PipelineRule(**body.model_dump())
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return _rule_to_dict(rule)


@router.put("/{rule_id}")
async def update_rule(rule_id: int, body: RuleUpdate, db: AsyncSession = Depends(get_db)):
    rule = (await db.execute(
        select(PipelineRule).where(PipelineRule.id == rule_id)
    )).scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    _validate_stages(body.stages)
    rule.name     = body.name
    rule.pattern  = body.pattern
    rule.stages   = body.stages
    rule.priority = body.priority
    rule.enabled  = body.enabled
    await db.commit()
    return _rule_to_dict(rule)


@router.delete("/{rule_id}", status_code=204)
async def delete_rule(rule_id: int, db: AsyncSession = Depends(get_db)):
    await db.execute(delete(PipelineRule).where(PipelineRule.id == rule_id))
    await db.commit()


@router.post("/batch-priority")
async def update_priorities(
    items: list[dict],   # [{id, priority}]
    db: AsyncSession = Depends(get_db),
):
    """Bulk update priorities after drag-reorder."""
    for item in items:
        rule = (await db.execute(
            select(PipelineRule).where(PipelineRule.id == item["id"])
        )).scalar_one_or_none()
        if rule:
            rule.priority = item["priority"]
    await db.commit()
    return {"success": True}


# ── Templates ─────────────────────────────────────────────────────────────────

@router.get("/templates")
async def list_templates():
    """Return available built-in templates."""
    return [
        {"key": "gitflow",     "label": "标准 Git Flow",   "description": "feature→审核+单测 / develop→+合并 / hotfix→审核+合并"},
        {"key": "trunk",       "label": "Trunk-Based",     "description": "main分支全量，feature仅审核+单测"},
        {"key": "github_flow", "label": "GitHub Flow",     "description": "main主干保护，短生命周期feature/bugfix/hotfix分支通过PR校验"},
        {"key": "gitlab_flow", "label": "GitLab Flow",     "description": "feature→main→staging→production，按环境分支逐级增强校验"},
    ]


@router.post("/templates/{template_key}/apply")
async def apply_template(template_key: str, repo_id: int, db: AsyncSession = Depends(get_db)):
    """Replace all rules for this repo with the chosen template's rules."""
    if template_key not in TEMPLATES:
        raise HTTPException(status_code=400, detail=f"Unknown template: {template_key}")

    # Remove existing rules
    await db.execute(delete(PipelineRule).where(PipelineRule.repo_id == repo_id))

    # Insert template rules
    for tpl in TEMPLATES[template_key]:
        rule = PipelineRule(
            repo_id=repo_id,
            name=tpl["name"],
            pattern=tpl["pattern"],
            stages=tpl["stages"],
            priority=tpl["priority"],
            enabled=True,
        )
        db.add(rule)

    await db.commit()
    return {"success": True, "applied": template_key, "count": len(TEMPLATES[template_key])}


@router.get("/stages")
async def list_stages():
    """Return all valid stage identifiers."""
    return ALL_STAGES


# ── Helpers ───────────────────────────────────────────────────────────────────

def _validate_stages(stages: list[str]):
    invalid = [s for s in stages if s not in ALL_STAGES]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Invalid stages: {invalid}. Valid: {ALL_STAGES}")


def _rule_to_dict(r: PipelineRule) -> dict:
    return {
        "id":         r.id,
        "repo_id":    r.repo_id,
        "name":       r.name,
        "pattern":    r.pattern,
        "stages":     r.stages,
        "priority":   r.priority,
        "enabled":    r.enabled,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }
