"""
Agent-based stage resolution. Single entry point for all per-stage model/agent
resolution. Replaces both the legacy StageRouter and repository default models.

Architecture:
  Model (capability) → Agent (behavior) → Repository (binding, optional)

When a repository has no explicit agent binding for a stage, the system built-in
agent for that stage_type serves as the default fallback. If the built-in agent
has no model assigned, the platform default model (or settings fallback) is used.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Any

try:
    import structlog
except ModuleNotFoundError:
    import logging

    class _KeywordLogger:
        def __init__(self, name: str):
            self._logger = logging.getLogger(name)

        def warning(self, event: str, **kwargs):
            self._logger.warning("%s %s", event, kwargs)

        def info(self, event: str, **kwargs):
            self._logger.info("%s %s", event, kwargs)

    class _StructlogFallback:
        @staticmethod
        def get_logger():
            return _KeywordLogger(__name__)

    structlog = _StructlogFallback()

logger = structlog.get_logger()


@dataclass
class AgentBinding:
    """Resolved agent binding for a pipeline stage."""
    agent_id: int
    agent_name: str
    stage_type: str
    skill_name: str
    skill_type: str = "builtin"
    model_id: Optional[int] = None
    instructions: Optional[str] = None
    skills: list[dict] = field(default_factory=list)
    mcp_tools: list[dict] = field(default_factory=list)
    guardrails: dict = field(default_factory=dict)
    skill_config: dict = field(default_factory=dict)
    model_config: dict = field(default_factory=dict)
    policy_config: dict = field(default_factory=dict)


@dataclass
class AgentResolver:
    """Resolves agent bindings per stage_type.

    Always constructed with built-in system agents as base defaults.
    Repository bindings overlay on top per stage_type.
    When a binding's model_id is null, falls back to the platform default engine.
    """

    _bindings: dict[str, AgentBinding] = field(default_factory=dict)
    _engines_by_id: dict[int, Any] = field(default_factory=dict)
    _fallback_engine: Any = None

    def get_binding(self, stage_type: str) -> Optional[AgentBinding]:
        """Return the AgentBinding for a stage, or None."""
        return self._bindings.get(stage_type)

    def get_engine(self, stage_type: str):
        """Return the AIEngine for a stage, with fallback to platform default."""
        binding = self._bindings.get(stage_type)
        if binding and binding.model_id:
            engine = self._engines_by_id.get(binding.model_id)
            if engine:
                return engine
            logger.warning(
                "agent_resolver.engine_not_found",
                stage_type=stage_type,
                model_id=binding.model_id,
                fallback="platform_default",
            )
        return self._fallback_engine

    def get_skill_config(self, stage_type: str) -> dict:
        """Return merged skill config for a stage."""
        binding = self._bindings.get(stage_type)
        return binding.skill_config if binding else {}

    def get_model_config(self, stage_type: str) -> dict:
        """Return model config overrides for a stage."""
        binding = self._bindings.get(stage_type)
        return binding.model_config if binding else {}

    def get_policy_config(self, stage_type: str) -> dict:
        """Return policy config for a stage (max_retry, require_review, etc.)."""
        binding = self._bindings.get(stage_type)
        return binding.policy_config if binding else {}

    def get_skill_name(self, stage_type: str) -> Optional[str]:
        """Return the skill_name override for a stage, or None to use default."""
        binding = self._bindings.get(stage_type)
        return binding.skill_name if binding else None

    def get_skill_type(self, stage_type: str) -> str:
        """Return configured skill type for a stage."""
        binding = self._bindings.get(stage_type)
        return binding.skill_type if binding else "builtin"

    def get_skills(self, stage_type: str) -> list[dict]:
        """Return configured skills for a stage."""
        binding = self._bindings.get(stage_type)
        return binding.skills if binding else []

    def get_guardrails(self, stage_type: str) -> dict:
        """Return guardrails for a stage."""
        binding = self._bindings.get(stage_type)
        return binding.guardrails if binding else {}

    def get_model_usage(self) -> dict[str, str]:
        """Return {stage_type: model_label} for all bound stages."""
        usage: dict[str, str] = {}
        for stage_type, binding in self._bindings.items():
            if binding.model_id and binding.model_id in self._engines_by_id:
                usage[stage_type] = self._engines_by_id[binding.model_id].model_config.model_id
            elif self._fallback_engine:
                usage[stage_type] = self._fallback_engine.model_config.model_id
            else:
                usage[stage_type] = "default"
        return usage

    def get_agent_summary(self) -> list[dict]:
        """Return summary of all bindings for logging/notifications."""
        summaries = []
        for stage_type, binding in self._bindings.items():
            model_label = "default"
            if binding.model_id and binding.model_id in self._engines_by_id:
                model_label = self._engines_by_id[binding.model_id].model_config.model_id
            summaries.append({
                "stage_type": stage_type,
                "agent_id": binding.agent_id,
                "agent_name": binding.agent_name,
                "skill_type": binding.skill_type,
                "skill_name": binding.skill_name,
                "skills": binding.skills,
                "mcp_tools": binding.mcp_tools,
                "model": model_label,
            })
        return summaries


def _skills_for_agent(agent) -> list[dict]:
    skills = getattr(agent, "skills", None) or []
    if skills:
        return skills
    return [{"name": agent.skill_name, "version": "1.0.0", "config": {}}]


def _binding_from_agent(agent, stage_type: str | None = None) -> AgentBinding:
    return AgentBinding(
        agent_id=agent.id,
        agent_name=agent.name,
        stage_type=stage_type or agent.stage_type,
        skill_type=getattr(agent, "skill_type", None) or "builtin",
        skill_name=agent.skill_name,
        model_id=agent.model_id,
        instructions=getattr(agent, "instructions", None),
        skills=_skills_for_agent(agent),
        mcp_tools=getattr(agent, "mcp_tools", None) or [],
        guardrails=getattr(agent, "guardrails", None) or {},
        skill_config=agent.skill_config or {},
        model_config=agent.model_config or {},
        policy_config=agent.policy_config or {},
    )


def build_agent_resolver_sync(repo, fallback_engine, sync_session) -> AgentResolver:
    """Build an AgentResolver for a repository.

    Always returns a resolver — never None. The resolver is built in two layers:

    1. Base layer — all is_system=True, enabled=True agents are loaded as the
       default binding for their stage_type.
    2. Overlay layer — repo.agent_bindings entries override the base for matching
       stage_types.

    When a binding's model_id is null (typical for unconfigured system agents),
    get_engine() returns the platform fallback_engine.
    """
    from app.models.agent import Agent
    from app.models.ai_model import AIModel
    from app.services.ai.engine import build_engine_from_db_model

    bindings: dict[str, AgentBinding] = {}

    # ── Layer 1: System built-in agents as base defaults ──────────────────
    system_agents = sync_session.query(Agent).filter(
        Agent.is_system == True, Agent.enabled == True
    ).all()

    for agent in system_agents:
        bindings[agent.stage_type] = _binding_from_agent(agent)

    # ── Layer 2: Repo bindings overlay ────────────────────────────────────
    bindings_raw = getattr(repo, "agent_bindings", None) or {}
    agent_ids = {aid for aid in bindings_raw.values() if isinstance(aid, int)}

    if agent_ids:
        repo_agents: dict[int, Agent] = {}
        for agent in sync_session.query(Agent).filter(Agent.id.in_(agent_ids)).all():
            if agent.enabled:
                repo_agents[agent.id] = agent

        for stage_type, agent_id in bindings_raw.items():
            agent = repo_agents.get(agent_id)
            if not agent:
                logger.warning(
                    "agent_resolver.repo_agent_not_found",
                    stage_type=stage_type, agent_id=agent_id,
                )
                continue
            bindings[stage_type] = _binding_from_agent(agent, stage_type=stage_type)

    # ── Build engines for all referenced models ───────────────────────────
    model_ids = {b.model_id for b in bindings.values() if b.model_id is not None}
    engines_by_id: dict[int, Any] = {}

    if model_ids:
        for model in sync_session.query(AIModel).filter(AIModel.id.in_(model_ids)).all():
            try:
                engines_by_id[model.id] = build_engine_from_db_model(model)
            except Exception as exc:
                logger.warning(
                    "agent_resolver.build_engine_failed",
                    model_id=model.id, error=str(exc),
                )

    logger.info(
        "agent_resolver.built",
        system_agent_count=len(system_agents),
        repo_binding_count=len(bindings_raw),
        total_bindings=len(bindings),
        model_count=len(engines_by_id),
    )

    return AgentResolver(
        _bindings=bindings,
        _engines_by_id=engines_by_id,
        _fallback_engine=fallback_engine,
    )
