"""Unit tests for Sprint A: Per-stage model routing (StageRouter)."""
import pytest
from unittest.mock import MagicMock, patch

from app.services.ai.stage_router import (
    StageRouter,
    build_stage_router_sync,
    STAGE_ANALYSIS,
    STAGE_GENERATION,
    STAGE_REPAIR,
    STAGE_SCORING,
    ALL_STAGES,
)
from app.services.ai.engine import AIEngine, ModelConfig


def _make_engine(model_id: str) -> AIEngine:
    return AIEngine(ModelConfig(model_id=model_id))


class TestStageRouter:
    """Tests for StageRouter dataclass."""

    def test_configured_stages_return_correct_engine(self):
        engine_a = _make_engine("claude-3-sonnet")
        engine_b = _make_engine("deepseek-chat")

        router = StageRouter(
            _engines_by_id={1: engine_a, 2: engine_b},
            _stage_models={
                STAGE_ANALYSIS: 1,
                STAGE_GENERATION: 2,
                STAGE_REPAIR: 2,
                STAGE_SCORING: 1,
            },
            _fallback_engine=_make_engine("gpt-4o-mini"),
        )

        assert router.get_engine(STAGE_ANALYSIS) is engine_a
        assert router.get_engine(STAGE_GENERATION) is engine_b
        assert router.get_engine(STAGE_REPAIR) is engine_b
        assert router.get_engine(STAGE_SCORING) is engine_a

    def test_unconfigured_stage_falls_back(self):
        fallback = _make_engine("gpt-4o-mini")
        router = StageRouter(
            _engines_by_id={},
            _stage_models={},
            _fallback_engine=fallback,
        )

        for stage in ALL_STAGES:
            assert router.get_engine(stage) is fallback

    def test_invalid_model_id_falls_back(self):
        fallback = _make_engine("gpt-4o-mini")
        engine_a = _make_engine("claude-3-sonnet")

        router = StageRouter(
            _engines_by_id={1: engine_a},
            _stage_models={
                STAGE_ANALYSIS: 1,
                STAGE_GENERATION: 999,  # non-existent model
            },
            _fallback_engine=fallback,
        )

        assert router.get_engine(STAGE_ANALYSIS) is engine_a
        assert router.get_engine(STAGE_GENERATION) is fallback

    def test_empty_config_all_fallback(self):
        fallback = _make_engine("gpt-4o-mini")
        router = StageRouter(
            _engines_by_id={},
            _stage_models={},
            _fallback_engine=fallback,
            _fallback_model_id=5,
        )

        for stage in ALL_STAGES:
            assert router.get_engine(stage) is fallback

    def test_get_model_label_configured(self):
        engine_a = _make_engine("claude-3-sonnet")
        router = StageRouter(
            _engines_by_id={1: engine_a},
            _stage_models={STAGE_ANALYSIS: 1},
            _fallback_engine=_make_engine("gpt-4o-mini"),
        )

        assert router.get_model_label(STAGE_ANALYSIS) == "claude-3-sonnet"

    def test_get_model_label_fallback(self):
        router = StageRouter(
            _engines_by_id={},
            _stage_models={},
            _fallback_engine=_make_engine("gpt-4o-mini"),
        )

        assert router.get_model_label(STAGE_ANALYSIS) == "gpt-4o-mini"

    def test_get_model_usage_returns_all_stages(self):
        engine_a = _make_engine("claude-3-sonnet")
        engine_b = _make_engine("deepseek-chat")
        fallback = _make_engine("gpt-4o-mini")

        router = StageRouter(
            _engines_by_id={1: engine_a, 2: engine_b},
            _stage_models={
                STAGE_ANALYSIS: 1,
                STAGE_GENERATION: 2,
            },
            _fallback_engine=fallback,
        )

        usage = router.get_model_usage()
        assert usage[STAGE_ANALYSIS] == "claude-3-sonnet"
        assert usage[STAGE_GENERATION] == "deepseek-chat"
        assert usage[STAGE_REPAIR] == "gpt-4o-mini"
        assert usage[STAGE_SCORING] == "gpt-4o-mini"

    def test_no_fallback_engine_returns_none(self):
        router = StageRouter(
            _engines_by_id={},
            _stage_models={},
            _fallback_engine=None,
        )
        assert router.get_engine(STAGE_ANALYSIS) is None
        assert router.get_model_label(STAGE_ANALYSIS) == "unknown"


class TestBuildStageRouterSync:
    """Tests for the synchronous factory function."""

    def test_no_stage_models_returns_empty_router(self):
        repo = MagicMock()
        repo.skills_config = {}
        repo.ai_model_id = 5
        fallback = _make_engine("gpt-4o-mini")
        session = MagicMock()

        router = build_stage_router_sync(repo, fallback, session)

        assert router._stage_models == {}
        assert router._engines_by_id == {}
        assert router._fallback_engine is fallback

    def test_no_skills_config_returns_empty_router(self):
        repo = MagicMock()
        repo.skills_config = None
        repo.ai_model_id = None
        fallback = _make_engine("gpt-4o-mini")
        session = MagicMock()

        router = build_stage_router_sync(repo, fallback, session)

        assert router._stage_models == {}
        assert router._fallback_engine is fallback

    def test_with_stage_models_loads_engines(self):
        repo = MagicMock()
        repo.skills_config = {
            "stage_models": {
                STAGE_ANALYSIS: 1,
                STAGE_GENERATION: 2,
            }
        }
        repo.ai_model_id = 5
        fallback = _make_engine("gpt-4o-mini")

        mock_model_1 = MagicMock()
        mock_model_1.id = 1
        mock_model_1.model_id = "claude-3-sonnet"
        mock_model_1.provider = "anthropic"
        mock_model_1.api_base = None
        mock_model_1.api_key_encrypted = None
        mock_model_1.config = {}

        mock_model_2 = MagicMock()
        mock_model_2.id = 2
        mock_model_2.model_id = "deepseek-chat"
        mock_model_2.provider = "deepseek"
        mock_model_2.api_base = None
        mock_model_2.api_key_encrypted = None
        mock_model_2.config = {}

        session = MagicMock()
        query_mock = MagicMock()
        session.query.return_value = query_mock
        query_mock.filter.return_value.all.return_value = [mock_model_1, mock_model_2]

        with patch("app.services.ai.stage_router.build_engine_from_db_model") as mock_build:
            mock_build.side_effect = lambda m: _make_engine(m.model_id)
            router = build_stage_router_sync(repo, fallback, session)

        assert router.get_model_label(STAGE_ANALYSIS) == "claude-3-sonnet"
        assert router.get_model_label(STAGE_GENERATION) == "deepseek-chat"
        assert router.get_model_label(STAGE_REPAIR) == "gpt-4o-mini"

    def test_build_engine_failure_is_tolerated(self):
        repo = MagicMock()
        repo.skills_config = {
            "stage_models": {STAGE_ANALYSIS: 1, STAGE_GENERATION: 2}
        }
        repo.ai_model_id = None
        fallback = _make_engine("gpt-4o-mini")

        mock_model = MagicMock()
        mock_model.id = 1

        session = MagicMock()
        query_mock = MagicMock()
        session.query.return_value = query_mock
        query_mock.filter.return_value.all.return_value = [mock_model]

        with patch("app.services.ai.stage_router.build_engine_from_db_model") as mock_build:
            mock_build.side_effect = Exception("decrypt failed")
            router = build_stage_router_sync(repo, fallback, session)

        # Model 1 failed to build, should fall back
        assert router.get_engine(STAGE_ANALYSIS) is fallback


class TestPipelineContextIntegration:
    """Test that PipelineContext correctly uses StageRouter."""

    def test_pipeline_context_has_stage_router_field(self):
        from app.services.agents.test_manager import PipelineContext

        ctx = PipelineContext()
        assert ctx.stage_router is None

        router = StageRouter(_fallback_engine=_make_engine("test"))
        ctx.stage_router = router
        assert ctx.stage_router is router

    def test_engine_for_with_partial_router(self):
        """Router with only analysis+generation configured; repair+scoring fall back."""
        from app.services.agents.test_manager import TestManagerAgent, PipelineContext

        engine_analysis = _make_engine("claude-3-sonnet")
        engine_gen = _make_engine("deepseek-chat")
        fallback = _make_engine("gpt-4o-mini")

        router = StageRouter(
            _engines_by_id={1: engine_analysis, 2: engine_gen},
            _stage_models={STAGE_ANALYSIS: 1, STAGE_GENERATION: 2},
            _fallback_engine=fallback,
        )

        ctx = PipelineContext(engine=fallback, stage_router=router)
        manager = TestManagerAgent()

        assert manager._engine_for(ctx, STAGE_ANALYSIS) is engine_analysis
        assert manager._engine_for(ctx, STAGE_GENERATION) is engine_gen
        assert manager._engine_for(ctx, STAGE_REPAIR) is fallback
        assert manager._engine_for(ctx, STAGE_SCORING) is fallback

    def test_engine_for_without_router(self):
        from app.services.agents.test_manager import TestManagerAgent, PipelineContext

        fallback = _make_engine("gpt-4o-mini")
        ctx = PipelineContext(engine=fallback, stage_router=None)
        manager = TestManagerAgent()

        for stage in ALL_STAGES:
            assert manager._engine_for(ctx, stage) is fallback

    def test_engine_for_full_router(self):
        """All 4 stages configured to different models."""
        from app.services.agents.test_manager import TestManagerAgent, PipelineContext

        e1 = _make_engine("claude-3-sonnet")
        e2 = _make_engine("deepseek-chat")
        e3 = _make_engine("deepseek-coder")
        e4 = _make_engine("gpt-4o")
        fallback = _make_engine("gpt-4o-mini")

        router = StageRouter(
            _engines_by_id={1: e1, 2: e2, 3: e3, 4: e4},
            _stage_models={
                STAGE_ANALYSIS: 1,
                STAGE_GENERATION: 2,
                STAGE_REPAIR: 3,
                STAGE_SCORING: 4,
            },
            _fallback_engine=fallback,
        )

        ctx = PipelineContext(engine=fallback, stage_router=router)
        manager = TestManagerAgent()

        assert manager._engine_for(ctx, STAGE_ANALYSIS) is e1
        assert manager._engine_for(ctx, STAGE_GENERATION) is e2
        assert manager._engine_for(ctx, STAGE_REPAIR) is e3
        assert manager._engine_for(ctx, STAGE_SCORING) is e4
