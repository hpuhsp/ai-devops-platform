"""Agent management API — CRUD for Agent entities."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, Field, ConfigDict
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
    model_config = ConfigDict(populate_by_name=True)

    name: str
    description: Optional[str] = None
    stage_type: str
    skill_type: str = "builtin"
    skill_name: Optional[str] = None
    model_id: Optional[int] = None
    instructions: Optional[str] = None
    skills: list[dict] = Field(default_factory=list)
    mcp_tools: list[dict] = Field(default_factory=list)
    guardrails: dict = Field(default_factory=dict)
    skill_config: dict = Field(default_factory=dict)
    model_cfg: dict = Field(default_factory=dict, alias="model_config")
    policy_config: dict = Field(default_factory=dict)
    enabled: bool = True


class AgentUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: Optional[str] = None
    description: Optional[str] = None
    stage_type: Optional[str] = None
    skill_type: Optional[str] = None
    skill_name: Optional[str] = None
    model_id: Optional[int] = None
    instructions: Optional[str] = None
    skills: Optional[list[dict]] = None
    mcp_tools: Optional[list[dict]] = None
    guardrails: Optional[dict] = None
    skill_config: Optional[dict] = None
    model_cfg: Optional[dict] = Field(default=None, alias="model_config")
    policy_config: Optional[dict] = None
    enabled: Optional[bool] = None


def _skill_catalog() -> dict[str, dict]:
    catalog = {meta["name"]: meta for meta in skill_runtime.list_metadata()}
    catalog.update(INTERNAL_STAGE_SKILLS)
    return catalog


def _normalize_skills(skill_name: str | None, skills: list[dict] | None) -> list[dict]:
    if skills:
        return skills
    if not skill_name:
        return []
    return [{"name": skill_name, "version": "1.0.0", "config": {}}]


def _primary_skill_name(skill_name: str | None, skills: list[dict] | None) -> str | None:
    if skills:
        first = skills[0] or {}
        if isinstance(first, dict) and first.get("name"):
            return first["name"]
    return skill_name


def _validate_builtin_skill(skill_name: str):
    available = _skill_catalog()
    if skill_name not in available:
        raise HTTPException(
            status_code=400,
            detail=f"Skill '{skill_name}' not found. Available: {list(available)}",
        )


def _validate_skills_payload(skills: list[dict], stage_type: str, skill_type: str = "builtin"):
    catalog = _skill_catalog()
    for idx, skill in enumerate(skills):
        if not isinstance(skill, dict) or not skill.get("name"):
            raise HTTPException(status_code=400, detail=f"skills[{idx}].name is required")
        if skill_type != "builtin":
            validation = skill_runtime.validate(skill["name"], stage_type, skill_type=skill_type)
            if not validation.valid:
                raise HTTPException(status_code=400, detail="; ".join(validation.errors))
            continue
        meta = catalog.get(skill["name"])
        if not meta:
            raise HTTPException(status_code=400, detail=f"Skill '{skill['name']}' not found")
        if meta.get("stage_type") and meta["stage_type"] != stage_type:
            raise HTTPException(
                status_code=400,
                detail=f"Skill '{skill['name']}' belongs to stage '{meta['stage_type']}', not '{stage_type}'",
            )


def _validate_mcp_tools_payload(mcp_tools: list[dict]) -> list[str]:
    warnings: list[str] = []
    for idx, tool in enumerate(mcp_tools or []):
        permission = str(tool.get("permission") or "read")
        if permission != "read":
            warnings.append(f"mcp_tools[{idx}] ignored write permission '{permission}'; only read is supported")
    return warnings


def _validate_guardrails_payload(guardrails: dict | None) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not guardrails:
        return errors, warnings
    if not isinstance(guardrails, dict):
        return ["guardrails must be an object"], warnings

    allowed = guardrails.get("allowed_write_patterns")
    if allowed is not None and (
        not isinstance(allowed, list)
        or any(not isinstance(item, str) or not item.strip() for item in allowed)
    ):
        errors.append("guardrails.allowed_write_patterns must be a list of non-empty strings")

    deny_shell = guardrails.get("deny_shell")
    if deny_shell is not None and not isinstance(deny_shell, bool):
        errors.append("guardrails.deny_shell must be boolean")

    max_tool_calls = guardrails.get("max_tool_calls")
    if max_tool_calls is not None:
        if not isinstance(max_tool_calls, int) or max_tool_calls <= 0:
            errors.append("guardrails.max_tool_calls must be a positive integer")
        elif max_tool_calls > 100:
            warnings.append("guardrails.max_tool_calls is high; consider keeping it <= 100")

    if not allowed:
        warnings.append("guardrails.allowed_write_patterns is empty; write scope is not explicitly constrained")
    return errors, warnings


def _serialize_agent(a: Agent) -> dict:
    skills = getattr(a, "skills", None) or _normalize_skills(a.skill_name, None)
    return {
        "id": a.id,
        "name": a.name,
        "description": a.description,
        "stage_type": a.stage_type,
        "skill_type": a.skill_type,
        "skill_name": a.skill_name,
        "model_id": a.model_id,
        "instructions": getattr(a, "instructions", None),
        "skills": skills,
        "mcp_tools": getattr(a, "mcp_tools", None) or [],
        "guardrails": getattr(a, "guardrails", None) or {},
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
    return list(_skill_catalog().values())


@router.get("/stages")
async def list_agent_stages():
    """List all stage types with descriptions."""
    return skill_registry.get_stage_types()


@router.get("/mcp-tools")
async def list_agent_mcp_tools():
    """List MCP tool descriptors available for Agent configuration."""
    return [
        {
            "server": "codegraph",
            "tools": ["refs", "impact", "file_summary"],
            "permission": "read",
            "description": "CodeGraph read-only repository intelligence tools",
            "enabled": False,
        }
    ]


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

    primary_skill = _primary_skill_name(body.skill_name, body.skills)
    if not primary_skill:
        raise HTTPException(status_code=400, detail="skill_name or skills[0].name is required")
    body.skill_name = primary_skill

    if body.skill_type == "builtin":
        _validate_builtin_skill(body.skill_name)
    _validate_skills_payload(
        _normalize_skills(body.skill_name, body.skills),
        body.stage_type,
        body.skill_type,
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
        instructions=body.instructions,
        skills=_normalize_skills(body.skill_name, body.skills),
        mcp_tools=body.mcp_tools,
        guardrails=body.guardrails,
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

    if body.stage_type is not None and body.stage_type != agent.stage_type:
        if body.stage_type not in VALID_STAGE_TYPES:
            raise HTTPException(status_code=400, detail=f"Invalid stage_type: {body.stage_type}")
        if agent.is_system:
            raise HTTPException(status_code=403, detail="Cannot change stage_type of system agent")
        agent.stage_type = body.stage_type

    next_skill_name = _primary_skill_name(body.skill_name, body.skills)
    if next_skill_name is not None and next_skill_name != agent.skill_name:
        if agent.is_system:
            raise HTTPException(status_code=403, detail="Cannot change skill_name of system agent")
        next_skill_type = body.skill_type or agent.skill_type
        if next_skill_type == "builtin":
            _validate_builtin_skill(next_skill_name)
        else:
            validation = skill_runtime.validate(next_skill_name, agent.stage_type, skill_type=next_skill_type)
            if not validation.valid:
                raise HTTPException(status_code=400, detail="; ".join(validation.errors))
        agent.skill_name = next_skill_name

    if body.skills is not None:
        primary = _primary_skill_name(agent.skill_name, body.skills)
        if primary != agent.skill_name:
            if agent.is_system:
                raise HTTPException(status_code=403, detail="Cannot change skill_name of system agent")
            if body.skill_type == "builtin" or agent.skill_type == "builtin":
                _validate_builtin_skill(primary)
            agent.skill_name = primary
        _validate_skills_payload(body.skills, agent.stage_type, body.skill_type or agent.skill_type)
        agent.skills = _normalize_skills(agent.skill_name, body.skills)

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
    if body.instructions is not None:
        agent.instructions = body.instructions
    if body.mcp_tools is not None:
        agent.mcp_tools = body.mcp_tools
    if body.guardrails is not None:
        agent.guardrails = body.guardrails
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
    if getattr(agent, "mcp_tools", None):
        warnings.append("MCP tools are configured but only read-only placeholders are supported in this phase")
        warnings.extend(_validate_mcp_tools_payload(agent.mcp_tools or []))
    guardrail_errors, guardrail_warnings = _validate_guardrails_payload(getattr(agent, "guardrails", None) or {})
    errors.extend(guardrail_errors)
    warnings.extend(guardrail_warnings)
    if getattr(agent, "skills", None):
        for idx, skill in enumerate(agent.skills or []):
            if not isinstance(skill, dict) or not skill.get("name"):
                errors.append(f"skills[{idx}].name is required")
                continue
            if skill_type == "builtin":
                meta = _skill_catalog().get(skill.get("name"))
                if not meta:
                    errors.append(f"Skill '{skill.get('name')}' not found")
                elif meta.get("stage_type") and meta["stage_type"] != agent.stage_type:
                    errors.append(
                        f"Skill '{skill.get('name')}' belongs to stage '{meta['stage_type']}', not '{agent.stage_type}'"
                    )
            else:
                validation = skill_runtime.validate(skill.get("name"), agent.stage_type, skill_type=skill_type)
                if not validation.valid:
                    errors.extend(validation.errors)
                warnings.extend(validation.warnings)

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
        instructions=getattr(agent, "instructions", None),
        skills=getattr(agent, "skills", None) or _normalize_skills(agent.skill_name, None),
        mcp_tools=getattr(agent, "mcp_tools", None) or [],
        guardrails=getattr(agent, "guardrails", None) or {},
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
