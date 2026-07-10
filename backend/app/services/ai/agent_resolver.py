"""
Agent-based stage resolution. Replaces StageRouter for repos that use
agent_bindings. Each Agent encapsulates a bound model plus skill/model/policy
config, giving per-stage control that is richer than the legacy stage_models
approach.

Three-layer model: Model (capability) → Agent (behavior) → Repository (binding)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Any

import structlog

logger = structlog.get_logger()


@dataclass
class AgentBinding:
    """Resolved agent binding for a pipeline stage."""
    agent_id: int
    agent_name: str
    stage_type: str
    skill_name: str
    model_id: Optional[int] = None
    skill_config: dict = field(default_factory=dict)
    model_config: dict = field(default_factory=dict)
    policy_config: dict = field(default_factory=dict)


@dataclass
class AgentResolver:
    """Resolves agent bindings per stage_type.

    Priority: agent_bindings (new) > stage_router (legacy) > repo default engine.
    When a repo has no agent_bindings, build_agent_resolver_sync returns None
    and the pipeline falls back to the legacy StageRouter.
    """
    _bindings: dict[str, AgentBinding] = field(default_factory=dict)
    _engines_by_id: dict[int, Any] = field(default_factory=dict)
    _fallback_engine: Any = None

    def get_binding(self, stage_type: str) -> Optional[AgentBinding]:
        """Return the AgentBinding for a stage, or None."""
        return self._bindings.get(stage_type)

    def get_engine(self, stage_type: str):
        """Return the AIEngine for a stage, with fallback to repo default."""
        binding = self._bindings.get(stage_type)
        if binding and binding.model_id:
            engine = self._engines_by_id.get(binding.model_id)
            if engine:
                return engine
            logger.warning(
                "agent_resolver.engine_not_found",
                stage_type=stage_type,
                model_id=binding.model_id,
                fallback="repo_default",
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
                "skill_name": binding.skill_name,
                "model": model_label,
            })
        return summaries


def build_agent_resolver_sync(repo, fallback_engine, sync_session) -> Optional[AgentResolver]:
    """Build an AgentResolver from repo.agent_bindings (synchronous, for Celery).

    Returns None if the repo has no agent_bindings, signaling the pipeline
    to fall back to the legacy StageRouter.
    """
    from app.models.agent import Agent
    from app.models.ai_model import AIModel
    from app.services.ai.engine import build_engine_from_db_model

    bindings_raw = getattr(repo, "agent_bindings", None) or {}
    if not bindings_raw:
        return None

    # Collect agent IDs from the binding map
    agent_ids = {aid for aid in bindings_raw.values() if isinstance(aid, int)}
    if not agent_ids:
        return None

    # Load Agent records from DB
    agents_by_id: dict[int, Agent] = {}
    for agent in sync_session.query(Agent).filter(Agent.id.in_(agent_ids)).all():
        if agent.enabled:
            agents_by_id[agent.id] = agent

    if not agents_by_id:
        logger.warning("agent_resolver.no_enabled_agents", agent_ids=list(agent_ids))
        return None

    # Collect unique model IDs needed
    model_ids = {
        a.model_id for a in agents_by_id.values()
        if a.model_id is not None
    }

    # Build engines for each unique model
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

    # Build binding map: stage_type → AgentBinding
    bindings: dict[str, AgentBinding] = {}
    for stage_type, agent_id in bindings_raw.items():
        agent = agents_by_id.get(agent_id)
        if not agent:
            logger.warning(
                "agent_resolver.agent_not_found_or_disabled",
                stage_type=stage_type, agent_id=agent_id,
            )
            continue
        bindings[stage_type] = AgentBinding(
            agent_id=agent.id,
            agent_name=agent.name,
            stage_type=stage_type,
            skill_name=agent.skill_name,
            model_id=agent.model_id,
            skill_config=agent.skill_config or {},
            model_config=agent.model_config or {},
            policy_config=agent.policy_config or {},
        )

    if not bindings:
        return None

    return AgentResolver(
        _bindings=bindings,
        _engines_by_id=engines_by_id,
        _fallback_engine=fallback_engine,
    )
