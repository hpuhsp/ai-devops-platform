"""Agent management API — CRUD for Agent entities."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
import structlog

from app.core.database import get_db
from app.models import Agent, AIModel
from app.services.skills.registry import skill_registry
from app.services.skills.runtime import skill_runtime

logger = structlog.get_logger()

router = APIRouter()

VALID_STAGE_TYPES = {"code_review", "change_intelligence", "generator", "validate_repair", "quality_scorer"}

INTERNAL_STAGE_SKILLS = {
    "validate_repair": {
        "name": "validate_repair",
        "description": "验证修复 — WorkTree 沙箱执行测试并按策略自动修复",
        "stage_type": "validate_repair",
        "skill_type": "builtin",
        "model_required": True,
        "runtime": "unit_test_engine",
    },
    "quality_scorer": {
        "name": "quality_scorer",
        "description": "质量评分 — 评估生成测试的覆盖、断言、边界和可维护性",
        "stage_type": "quality_scorer",
        "skill_type": "builtin",
        "model_required": True,
        "runtime": "unit_test_engine",
    },
}


class AgentCreate(BaseModel):
    name: str
    description: Optional[str] = None
    stage_type: str
    skill_type: str = "builtin"
    skill_name: Optional[str] = None
    model_id: Optional[int] = None
    enabled: bool = True


class AgentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    stage_type: Optional[str] = None
    skill_type: Optional[str] = None
    skill_name: Optional[str] = None
    model_id: Optional[int] = None
    enabled: Optional[bool] = None


def _skill_catalog() -> dict[str, dict]:
    catalog = {meta["name"]: meta for meta in skill_runtime.list_metadata()}
    catalog.update(INTERNAL_STAGE_SKILLS)
    return catalog


def _validate_builtin_skill(skill_name: str):
    available = _skill_catalog()
    if skill_name not in available:
        raise HTTPException(
            status_code=400,
            detail=f"Skill '{skill_name}' not found. Available: {list(available)}",
        )


def _serialize_agent(a: Agent) -> dict:
    return {
        "id": a.id,
        "name": a.name,
        "description": a.description,
        "stage_type": a.stage_type,
        "skill_type": a.skill_type,
        "skill_name": a.skill_name,
        "model_id": a.model_id,
        "enabled": a.enabled,
        "is_system": a.is_system,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "updated_at": a.updated_at.isoformat() if a.updated_at else None,
    }


# ── Metadata endpoints ──────────────────────────────────────────────────────

@router.get("/skills")
async def list_agent_skills():
    """List all registered skills with metadata."""
    return list(_skill_catalog().values())


@router.get("/stages")
async def list_agent_stages():
    """List all stage types with descriptions."""
    return skill_registry.get_stage_types()


# ── CRUD ────────────────────────────────────────────────────────────────────

@router.get("")
async def list_agents(
    stage_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """List all agents, optionally filtered by stage_type."""
    query = select(Agent)
    if stage_type:
        if stage_type not in VALID_STAGE_TYPES:
            raise HTTPException(status_code=400, detail=f"Invalid stage_type: {stage_type}")
        query = query.where(Agent.stage_type == stage_type)
    result = await db.execute(query.order_by(Agent.stage_type, Agent.id))
    agents = result.scalars().all()
    return [_serialize_agent(a) for a in agents]


@router.post("", status_code=201)
async def create_agent(body: AgentCreate, db: AsyncSession = Depends(get_db)):
    """Create a new agent."""
    if body.stage_type not in VALID_STAGE_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid stage_type: {body.stage_type}")

    if not body.skill_name:
        raise HTTPException(status_code=400, detail="skill_name is required")

    if body.skill_type == "builtin":
        _validate_builtin_skill(body.skill_name)

    if body.model_id is not None:
        model = (await db.execute(select(AIModel).where(AIModel.id == body.model_id))).scalar_one_or_none()
        if not model:
            raise HTTPException(status_code=400, detail=f"Model {body.model_id} not found")

    agent = Agent(
        name=body.name,
        description=body.description,
        stage_type=body.stage_type,
        skill_type=body.skill_type,
        skill_name=body.skill_name,
        model_id=body.model_id,
        enabled=body.enabled,
        is_system=False,
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    logger.info("agent.created", agent_id=agent.id, name=agent.name, stage_type=agent.stage_type)
    return _serialize_agent(agent)


@router.get("/{agent_id}")
async def get_agent(agent_id: int, db: AsyncSession = Depends(get_db)):
    """Get agent detail."""
    agent = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return _serialize_agent(agent)


@router.put("/{agent_id}")
async def update_agent(agent_id: int, body: AgentUpdate, db: AsyncSession = Depends(get_db)):
    """Update an agent. System agents can be reconfigured but not change stage_type/skill_name."""
    agent = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    if body.stage_type is not None and body.stage_type != agent.stage_type:
        if body.stage_type not in VALID_STAGE_TYPES:
            raise HTTPException(status_code=400, detail=f"Invalid stage_type: {body.stage_type}")
        if agent.is_system:
            raise HTTPException(status_code=403, detail="Cannot change stage_type of system agent")
        agent.stage_type = body.stage_type

    if body.skill_name is not None and body.skill_name != agent.skill_name:
        if agent.is_system:
            raise HTTPException(status_code=403, detail="Cannot change skill_name of system agent")
        next_skill_type = body.skill_type or agent.skill_type
        if next_skill_type == "builtin":
            _validate_builtin_skill(body.skill_name)
        else:
            validation = skill_runtime.validate(body.skill_name, agent.stage_type, skill_type=next_skill_type)
            if not validation.valid:
                raise HTTPException(status_code=400, detail="; ".join(validation.errors))
        agent.skill_name = body.skill_name

    if body.skill_type is not None:
        agent.skill_type = body.skill_type

    if "model_id" in body.model_fields_set:
        if body.model_id is None:
            agent.model_id = None
        else:
            model = (await db.execute(select(AIModel).where(AIModel.id == body.model_id))).scalar_one_or_none()
            if not model:
                raise HTTPException(status_code=400, detail=f"Model {body.model_id} not found")
            agent.model_id = body.model_id

    if body.name is not None:
        agent.name = body.name
    if body.description is not None:
        agent.description = body.description
    if body.enabled is not None:
        agent.enabled = body.enabled

    await db.commit()
    await db.refresh(agent)
    logger.info("agent.updated", agent_id=agent.id)
    return _serialize_agent(agent)


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(agent_id: int, db: AsyncSession = Depends(get_db)):
    """Delete an agent. System agents cannot be deleted."""
    agent = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent.is_system:
        raise HTTPException(status_code=403, detail="System agents cannot be deleted")
    await db.delete(agent)
    await db.commit()
    logger.info("agent.deleted", agent_id=agent_id)


@router.post("/{agent_id}/validate")
async def validate_agent(agent_id: int, db: AsyncSession = Depends(get_db)):
    """Validate Agent configuration without executing the pipeline."""
    agent = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    errors: list[str] = []
    warnings: list[str] = []

    if agent.stage_type not in VALID_STAGE_TYPES:
        errors.append(f"Invalid stage_type: {agent.stage_type}")
    skill_type = getattr(agent, "skill_type", None) or "builtin"
    validation = skill_runtime.validate(agent.skill_name, agent.stage_type, skill_type=skill_type)
    if skill_type == "builtin" and agent.skill_name in INTERNAL_STAGE_SKILLS:
        validation.valid = True
        validation.errors = []
    if not validation.valid:
        errors.extend(validation.errors)
    warnings.extend(validation.warnings)
    if agent.model_id is not None:
        model = (await db.execute(select(AIModel).where(AIModel.id == agent.model_id))).scalar_one_or_none()
        if not model:
            errors.append(f"Model {agent.model_id} not found")

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "agent": _serialize_agent(agent),
    }


@router.post("/{agent_id}/clone", status_code=201)
async def clone_agent(agent_id: int, db: AsyncSession = Depends(get_db)):
    """Clone an agent for customization. The clone is never a system agent."""
    agent = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    clone = Agent(
        name=f"{agent.name} (副本)",
        description=agent.description,
        stage_type=agent.stage_type,
        skill_type=agent.skill_type,
        skill_name=agent.skill_name,
        model_id=agent.model_id,
        enabled=agent.enabled,
        is_system=False,
    )
    db.add(clone)
    await db.commit()
    await db.refresh(clone)
    logger.info("agent.cloned", source_id=agent_id, clone_id=clone.id)
    return _serialize_agent(clone)
