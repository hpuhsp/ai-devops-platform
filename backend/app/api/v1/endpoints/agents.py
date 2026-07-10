"""Agent management API — CRUD for Agent entities."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
import structlog

from app.core.database import get_db
from app.models import Agent, AIModel
from app.services.skills.registry import skill_registry

logger = structlog.get_logger()

router = APIRouter()

VALID_STAGE_TYPES = {"code_review", "change_intelligence", "generator", "validate_repair", "quality_scorer"}


class AgentCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    description: Optional[str] = None
    stage_type: str
    skill_type: str = "builtin"
    skill_name: str
    model_id: Optional[int] = None
    skill_config: dict = {}
    model_cfg: dict = Field(default={}, alias="model_config")
    policy_config: dict = {}
    enabled: bool = True


class AgentUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: Optional[str] = None
    description: Optional[str] = None
    stage_type: Optional[str] = None
    skill_type: Optional[str] = None
    skill_name: Optional[str] = None
    model_id: Optional[int] = None
    skill_config: Optional[dict] = None
    model_cfg: Optional[dict] = Field(default=None, alias="model_config")
    policy_config: Optional[dict] = None
    enabled: Optional[bool] = None


def _serialize_agent(a: Agent) -> dict:
    return {
        "id": a.id,
        "name": a.name,
        "description": a.description,
        "stage_type": a.stage_type,
        "skill_type": a.skill_type,
        "skill_name": a.skill_name,
        "model_id": a.model_id,
        "skill_config": a.skill_config or {},
        "model_config": a.model_config or {},
        "policy_config": a.policy_config or {},
        "enabled": a.enabled,
        "is_system": a.is_system,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "updated_at": a.updated_at.isoformat() if a.updated_at else None,
    }


# ── Metadata endpoints ──────────────────────────────────────────────────────

@router.get("/skills")
async def list_agent_skills():
    """List all registered skills with metadata."""
    return skill_registry.list_skills_metadata()


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

    if body.skill_type == "builtin":
        available = skill_registry.list_skills()
        if body.skill_name not in available:
            raise HTTPException(
                status_code=400,
                detail=f"Skill '{body.skill_name}' not found in registry. Available: {available}",
            )

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
        skill_config=body.skill_config,
        model_config=body.model_cfg,
        policy_config=body.policy_config,
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

    if body.stage_type is not None:
        if body.stage_type not in VALID_STAGE_TYPES:
            raise HTTPException(status_code=400, detail=f"Invalid stage_type: {body.stage_type}")
        if agent.is_system:
            raise HTTPException(status_code=403, detail="Cannot change stage_type of system agent")
        agent.stage_type = body.stage_type

    if body.skill_name is not None:
        if agent.is_system:
            raise HTTPException(status_code=403, detail="Cannot change skill_name of system agent")
        if body.skill_type and body.skill_type == "builtin":
            available = skill_registry.list_skills()
            if body.skill_name not in available:
                raise HTTPException(
                    status_code=400,
                    detail=f"Skill '{body.skill_name}' not found in registry",
                )
        agent.skill_name = body.skill_name

    if body.skill_type is not None:
        agent.skill_type = body.skill_type

    if body.model_id is not None:
        model = (await db.execute(select(AIModel).where(AIModel.id == body.model_id))).scalar_one_or_none()
        if not model:
            raise HTTPException(status_code=400, detail=f"Model {body.model_id} not found")
        agent.model_id = body.model_id

    if body.name is not None:
        agent.name = body.name
    if body.description is not None:
        agent.description = body.description
    if body.skill_config is not None:
        agent.skill_config = body.skill_config
    if body.model_cfg is not None:
        agent.model_config = body.model_cfg
    if body.policy_config is not None:
        agent.policy_config = body.policy_config
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
        skill_config=agent.skill_config or {},
        model_config=agent.model_config or {},
        policy_config=agent.policy_config or {},
        enabled=agent.enabled,
        is_system=False,
    )
    db.add(clone)
    await db.commit()
    await db.refresh(clone)
    logger.info("agent.cloned", source_id=agent_id, clone_id=clone.id)
    return _serialize_agent(clone)
