"""Unit tests for Agent Management Module."""
import pytest
from unittest.mock import MagicMock, patch
from dataclasses import dataclass

from app.services.ai.engine import AIEngine, ModelConfig
from app.services.ai.agent_resolver import (
    AgentBinding,
    AgentResolver,
    build_agent_resolver_sync,
)


def _make_engine(model_id: str) -> AIEngine:
    return AIEngine(ModelConfig(model_id=model_id))


# ── Agent Model Tests ───────────────────────────────────────────────────────

class TestAgentModel:
    """Tests for the Agent DB model."""

    def test_agent_model_import(self):
        from app.models.agent import Agent
        assert Agent.__tablename__ == "agents"

    def test_agent_model_exported(self):
        from app.models import Agent
        assert Agent is not None

    def test_agent_columns_exist(self):
        from app.models.agent import Agent
        columns = {c.name for c in Agent.__table__.columns}
        expected = {
            "id", "name", "description", "stage_type",
            "skill_type", "skill_name", "model_id",
            "skill_config", "model_config", "policy_config",
            "enabled", "is_system", "created_at", "updated_at",
        }
        assert expected.issubset(columns), f"Missing: {expected - columns}"


# ── AgentResolver Tests ─────────────────────────────────────────────────────

class TestAgentResolver:
    """Tests for AgentResolver dataclass."""

    def test_get_engine_returns_bound_model_engine(self):
        engine_a = _make_engine("claude-3-sonnet")
        fallback = _make_engine("gpt-4o-mini")

        resolver = AgentResolver(
            _bindings={
                "code_review": AgentBinding(
                    agent_id=1, agent_name="CR Agent", stage_type="code_review",
                    skill_name="code_review", model_id=10,
                ),
            },
            _engines_by_id={10: engine_a},
            _fallback_engine=fallback,
        )

        assert resolver.get_engine("code_review") is engine_a

    def test_get_engine_falls_back_when_no_binding(self):
        fallback = _make_engine("gpt-4o-mini")
        resolver = AgentResolver(
            _bindings={},
            _engines_by_id={},
            _fallback_engine=fallback,
        )
        assert resolver.get_engine("code_review") is fallback

    def test_get_engine_falls_back_when_model_not_found(self):
        fallback = _make_engine("gpt-4o-mini")
        resolver = AgentResolver(
            _bindings={
                "generator": AgentBinding(
                    agent_id=2, agent_name="Gen Agent", stage_type="generator",
                    skill_name="test_generation", model_id=999,
                ),
            },
            _engines_by_id={},
            _fallback_engine=fallback,
        )
        assert resolver.get_engine("generator") is fallback

    def test_get_engine_returns_fallback_when_no_model_id(self):
        fallback = _make_engine("gpt-4o-mini")
        resolver = AgentResolver(
            _bindings={
                "code_review": AgentBinding(
                    agent_id=1, agent_name="CR Agent", stage_type="code_review",
                    skill_name="code_review", model_id=None,
                ),
            },
            _engines_by_id={},
            _fallback_engine=fallback,
        )
        assert resolver.get_engine("code_review") is fallback

    def test_get_skill_config(self):
        resolver = AgentResolver(
            _bindings={
                "code_review": AgentBinding(
                    agent_id=1, agent_name="CR Agent", stage_type="code_review",
                    skill_name="code_review", model_id=None,
                    skill_config={"max_diff_lines": 500},
                ),
            },
            _engines_by_id={},
        )
        assert resolver.get_skill_config("code_review") == {"max_diff_lines": 500}

    def test_get_skill_config_empty_when_no_binding(self):
        resolver = AgentResolver(_bindings={})
        assert resolver.get_skill_config("code_review") == {}

    def test_get_model_config(self):
        resolver = AgentResolver(
            _bindings={
                "generator": AgentBinding(
                    agent_id=2, agent_name="Gen Agent", stage_type="generator",
                    skill_name="test_generation", model_id=1,
                    model_config={"temperature": 0.3, "max_tokens": 8192},
                ),
            },
            _engines_by_id={},
        )
        cfg = resolver.get_model_config("generator")
        assert cfg["temperature"] == 0.3
        assert cfg["max_tokens"] == 8192

    def test_get_policy_config(self):
        resolver = AgentResolver(
            _bindings={
                "validate_repair": AgentBinding(
                    agent_id=3, agent_name="Repair Agent", stage_type="validate_repair",
                    skill_name="validate_repair", model_id=None,
                    policy_config={"max_retry": 5, "require_review": True},
                ),
            },
            _engines_by_id={},
        )
        policy = resolver.get_policy_config("validate_repair")
        assert policy["max_retry"] == 5
        assert policy["require_review"] is True

    def test_get_policy_config_empty_when_no_binding(self):
        resolver = AgentResolver(_bindings={})
        assert resolver.get_policy_config("validate_repair") == {}

    def test_get_model_usage(self):
        engine_a = _make_engine("claude-3-sonnet")
        fallback = _make_engine("gpt-4o-mini")

        resolver = AgentResolver(
            _bindings={
                "code_review": AgentBinding(
                    agent_id=1, agent_name="CR", stage_type="code_review",
                    skill_name="code_review", model_id=10,
                ),
                "generator": AgentBinding(
                    agent_id=2, agent_name="Gen", stage_type="generator",
                    skill_name="test_generation", model_id=None,
                ),
            },
            _engines_by_id={10: engine_a},
            _fallback_engine=fallback,
        )

        usage = resolver.get_model_usage()
        assert usage["code_review"] == "claude-3-sonnet"
        assert usage["generator"] == "gpt-4o-mini"

    def test_get_skill_name(self):
        resolver = AgentResolver(
            _bindings={
                "code_review": AgentBinding(
                    agent_id=1, agent_name="CR", stage_type="code_review",
                    skill_name="custom_review", model_id=None,
                ),
            },
            _engines_by_id={},
        )
        assert resolver.get_skill_name("code_review") == "custom_review"
        assert resolver.get_skill_name("generator") is None


# ── build_agent_resolver_sync Tests ─────────────────────────────────────────

class TestBuildAgentResolverSync:
    """Tests for the synchronous factory function."""

    def test_no_agent_bindings_returns_resolver(self):
        repo = MagicMock()
        repo.agent_bindings = None
        fallback = _make_engine("gpt-4o-mini")
        session = MagicMock()
        # No system agents in DB
        q = MagicMock()
        session.query.return_value = q
        q.filter.return_value.all.return_value = []

        result = build_agent_resolver_sync(repo, fallback, session)
        assert isinstance(result, AgentResolver)
        assert result.get_engine("code_review") is fallback

    def test_empty_agent_bindings_returns_resolver(self):
        repo = MagicMock()
        repo.agent_bindings = {}
        fallback = _make_engine("gpt-4o-mini")
        session = MagicMock()
        q = MagicMock()
        session.query.return_value = q
        q.filter.return_value.all.return_value = []

        result = build_agent_resolver_sync(repo, fallback, session)
        assert isinstance(result, AgentResolver)
        assert result.get_engine("code_review") is fallback

    def test_with_bindings_loads_agents_and_engines(self):
        repo = MagicMock()
        repo.agent_bindings = {"code_review": 1, "generator": 2}
        fallback = _make_engine("gpt-4o-mini")

        mock_agent_1 = MagicMock()
        mock_agent_1.id = 1
        mock_agent_1.name = "CR Agent"
        mock_agent_1.stage_type = "code_review"
        mock_agent_1.skill_name = "code_review"
        mock_agent_1.skill_type = "builtin"
        mock_agent_1.model_id = 10
        mock_agent_1.skill_config = {"max_diff_lines": 500}
        mock_agent_1.model_config = {}
        mock_agent_1.policy_config = {}
        mock_agent_1.enabled = True

        mock_agent_2 = MagicMock()
        mock_agent_2.id = 2
        mock_agent_2.name = "Gen Agent"
        mock_agent_2.stage_type = "generator"
        mock_agent_2.skill_name = "test_generation"
        mock_agent_2.skill_type = "builtin"
        mock_agent_2.model_id = 20
        mock_agent_2.skill_config = {}
        mock_agent_2.model_config = {"temperature": 0.3}
        mock_agent_2.policy_config = {}
        mock_agent_2.enabled = True

        mock_model_10 = MagicMock()
        mock_model_10.id = 10
        mock_model_10.model_id = "claude-3-sonnet"
        mock_model_10.provider = "anthropic"
        mock_model_10.api_base = None
        mock_model_10.api_key_encrypted = None
        mock_model_10.config = {}

        mock_model_20 = MagicMock()
        mock_model_20.id = 20
        mock_model_20.model_id = "deepseek-chat"
        mock_model_20.provider = "deepseek"
        mock_model_20.api_base = None
        mock_model_20.api_key_encrypted = None
        mock_model_20.config = {}

        session = MagicMock()

        # First query: Agent, Second query: AIModel
        def query_side_effect(model_cls):
            q = MagicMock()
            if model_cls.__name__ == "Agent":
                q.filter.return_value.all.return_value = [mock_agent_1, mock_agent_2]
            elif model_cls.__name__ == "AIModel":
                q.filter.return_value.all.return_value = [mock_model_10, mock_model_20]
            return q

        session.query.side_effect = query_side_effect

        with patch("app.services.ai.engine.build_engine_from_db_model") as mock_build:
            mock_build.side_effect = lambda m: _make_engine(m.model_id)
            resolver = build_agent_resolver_sync(repo, fallback, session)

        assert resolver is not None
        assert resolver.get_engine("code_review").model_config.model_id == "claude-3-sonnet"
        assert resolver.get_engine("generator").model_config.model_id == "deepseek-chat"
        assert resolver.get_skill_config("code_review") == {"max_diff_lines": 500}
        assert resolver.get_model_config("generator") == {"temperature": 0.3}

    def test_disabled_agents_are_skipped(self):
        repo = MagicMock()
        repo.agent_bindings = {"code_review": 1}
        fallback = _make_engine("gpt-4o-mini")

        session = MagicMock()
        q = MagicMock()
        session.query.return_value = q
        q.filter.return_value.all.return_value = []

        result = build_agent_resolver_sync(repo, fallback, session)
        assert isinstance(result, AgentResolver)

    def test_missing_getattr_returns_resolver(self):
        repo = MagicMock(spec=[])
        fallback = _make_engine("gpt-4o-mini")
        session = MagicMock()

        q = MagicMock()
        session.query.return_value = q
        q.filter.return_value.all.return_value = []

        result = build_agent_resolver_sync(repo, fallback, session)
        assert isinstance(result, AgentResolver)


# ── Skill Metadata Tests ────────────────────────────────────────────────────

class TestSkillMetadata:
    """Tests for skill metadata enhancement."""

    def test_skill_base_has_stage_type(self):
        from app.services.skills.base import SkillBase
        assert hasattr(SkillBase, "stage_type")

    def test_skill_base_metadata(self):
        from app.services.skills.base import SkillBase
        meta = SkillBase.metadata()
        assert "name" in meta
        assert "stage_type" in meta
        assert "model_required" in meta

    def test_code_review_skill_has_stage_type(self):
        from app.services.skills.builtin.code_review import CodeReviewSkill
        assert CodeReviewSkill.stage_type == "code_review"

    def test_change_intelligence_skill_has_stage_type(self):
        from app.services.skills.builtin.change_intelligence import ChangeIntelligenceSkill
        assert ChangeIntelligenceSkill.stage_type == "change_intelligence"

    def test_test_generation_skill_has_stage_type(self):
        from app.services.skills.builtin.test_generation import TestGenerationSkill
        assert TestGenerationSkill.stage_type == "generator"

    def test_registry_list_skills_metadata(self):
        from app.services.skills.registry import skill_registry
        metas = skill_registry.list_skills_metadata()
        assert isinstance(metas, list)
        assert len(metas) > 0
        names = [m["name"] for m in metas]
        assert "code_review" in names

    def test_registry_list_by_stage(self):
        from app.services.skills.registry import skill_registry
        cr_skills = skill_registry.list_by_stage("code_review")
        assert len(cr_skills) == 1
        assert cr_skills[0]["name"] == "code_review"

        gen_skills = skill_registry.list_by_stage("generator")
        assert len(gen_skills) == 1
        assert gen_skills[0]["name"] == "test_generation"

    def test_registry_get_stage_types(self):
        from app.services.skills.registry import skill_registry
        stages = skill_registry.get_stage_types()
        assert isinstance(stages, list)
        values = [s["value"] for s in stages]
        assert "code_review" in values
        assert "generator" in values
        assert "validate_repair" in values
        assert "quality_scorer" in values
        assert "change_intelligence" in values


# ── Pipeline Integration Tests ──────────────────────────────────────────────

class TestPipelineAgentIntegration:
    """Test that PipelineContext and TestManagerAgent work with agent_resolver."""

    def test_pipeline_context_has_agent_resolver_field(self):
        from app.services.agents.test_manager import PipelineContext
        ctx = PipelineContext()
        assert ctx.agent_resolver is None

    def test_pipeline_context_can_set_agent_resolver(self):
        from app.services.agents.test_manager import PipelineContext
        resolver = AgentResolver(_bindings={}, _fallback_engine=_make_engine("test"))
        ctx = PipelineContext(agent_resolver=resolver)
        assert ctx.agent_resolver is resolver

    def test_engine_for_with_agent_resolver(self):
        from app.services.agents.test_manager import TestManagerAgent, PipelineContext

        agent_engine = _make_engine("claude-3-sonnet")
        fallback = _make_engine("gpt-4o-mini")

        resolver = AgentResolver(
            _bindings={
                "code_review": AgentBinding(
                    agent_id=1, agent_name="CR", stage_type="code_review",
                    skill_name="code_review", model_id=10,
                ),
            },
            _engines_by_id={10: agent_engine},
            _fallback_engine=fallback,
        )

        ctx = PipelineContext(
            engine=fallback,
            agent_resolver=resolver,
        )
        manager = TestManagerAgent()

        result = manager._engine_for(ctx, "code_review")
        assert result is agent_engine

    def test_engine_for_falls_to_resolver_fallback(self):
        """When agent_resolver has no binding for a stage, falls back to resolver's fallback."""
        from app.services.agents.test_manager import TestManagerAgent, PipelineContext

        fallback = _make_engine("gpt-4o-mini")

        resolver = AgentResolver(
            _bindings={},
            _fallback_engine=fallback,
        )

        ctx = PipelineContext(
            engine=fallback,
            agent_resolver=resolver,
        )
        manager = TestManagerAgent()

        result = manager._engine_for(ctx, "code_review")
        assert result is fallback

    def test_engine_for_falls_to_default_engine(self):
        """agent_resolver always available, get_engine handles fallback."""
        from app.services.agents.test_manager import TestManagerAgent, PipelineContext

        fallback = _make_engine("gpt-4o-mini")
        resolver = AgentResolver(_bindings={}, _fallback_engine=fallback)
        ctx = PipelineContext(engine=fallback, agent_resolver=resolver)
        manager = TestManagerAgent()

        assert manager._engine_for(ctx, "code_review") is fallback

    def test_skill_config_for_with_agent_resolver(self):
        """_skill_config_for returns agent's skill_config when agent_resolver is set."""
        from app.services.agents.test_manager import TestManagerAgent, PipelineContext

        resolver = AgentResolver(
            _bindings={
                "code_review": AgentBinding(
                    agent_id=1, agent_name="CR", stage_type="code_review",
                    skill_name="code_review", model_id=None,
                    skill_config={"max_diff_lines": 1000, "custom_prompt": "focus on security"},
                ),
            },
            _engines_by_id={},
        )

        ctx = PipelineContext(agent_resolver=resolver)
        manager = TestManagerAgent()

        cfg = manager._skill_config_for(ctx, "code_review")
        assert cfg["max_diff_lines"] == 1000
        assert cfg["custom_prompt"] == "focus on security"

    def test_skill_config_for_falls_to_repo_config(self):
        """Without agent_resolver, _skill_config_for uses repo skills_config."""
        from app.services.agents.test_manager import TestManagerAgent, PipelineContext

        ctx = PipelineContext(
            skills_config={"code_review": {"threshold": 50}},
        )
        manager = TestManagerAgent()

        cfg = manager._skill_config_for(ctx, "code_review")
        assert cfg == {"threshold": 50}

    def test_policy_config_for_with_agent_resolver(self):
        """_policy_config_for returns agent's policy_config."""
        from app.services.agents.test_manager import TestManagerAgent, PipelineContext

        resolver = AgentResolver(
            _bindings={
                "validate_repair": AgentBinding(
                    agent_id=3, agent_name="Repair", stage_type="validate_repair",
                    skill_name="validate_repair", model_id=None,
                    policy_config={"max_retry": 7, "require_review": False},
                ),
            },
            _engines_by_id={},
        )

        ctx = PipelineContext(agent_resolver=resolver)
        manager = TestManagerAgent()

        policy = manager._policy_config_for(ctx, "validate_repair")
        assert policy["max_retry"] == 7
        assert policy["require_review"] is False

    def test_policy_config_for_empty_without_resolver(self):
        from app.services.agents.test_manager import TestManagerAgent, PipelineContext

        ctx = PipelineContext()
        manager = TestManagerAgent()

        assert manager._policy_config_for(ctx, "validate_repair") == {}

    def test_stage_to_type_mapping(self):
        """Verify the _STAGE_TO_TYPE mapping covers all skill-using stages."""
        from app.services.agents.test_manager import TestManagerAgent

        expected = {
            "code_review": "code_review",
            "change_intelligence": "change_intelligence",
            "generator": "generator",
            "validate_repair": "validate_repair",
            "quality_scorer": "quality_scorer",
        }
        assert TestManagerAgent._STAGE_TO_TYPE == expected

    def test_get_model_config_for_with_agent(self):
        """_model_config_for returns agent's model_config."""
        from app.services.agents.test_manager import TestManagerAgent, PipelineContext

        resolver = AgentResolver(
            _bindings={
                "generator": AgentBinding(
                    agent_id=2, agent_name="Gen", stage_type="generator",
                    skill_name="test_generation", model_id=1,
                    model_config={"temperature": 0.7, "max_tokens": 4096},
                ),
            },
            _engines_by_id={},
        )

        ctx = PipelineContext(agent_resolver=resolver)
        manager = TestManagerAgent()

        cfg = manager._model_config_for(ctx, "generator")
        assert cfg["temperature"] == 0.7
        assert cfg["max_tokens"] == 4096
