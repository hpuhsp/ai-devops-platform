"""
Per-stage model routing. Resolves AIEngine for each pipeline stage.

Allows repositories to configure different AI models for analysis, generation,
repair, and scoring stages. Falls back to the repo default engine when a stage
is not configured or the referenced model is unavailable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Any

import structlog

from app.services.ai.engine import build_engine_from_db_model

logger = structlog.get_logger()

STAGE_ANALYSIS = "analysis"
STAGE_GENERATION = "generation"
STAGE_REPAIR = "repair"
STAGE_SCORING = "scoring"

ALL_STAGES = [STAGE_ANALYSIS, STAGE_GENERATION, STAGE_REPAIR, STAGE_SCORING]


@dataclass
class StageRouter:
    """Resolves per-stage AIEngine instances from repo config."""

    _engines_by_id: dict[int, Any] = field(default_factory=dict)
    _stage_models: dict[str, int] = field(default_factory=dict)
    _fallback_engine: Any = None
    _fallback_model_id: Optional[int] = None

    def get_engine(self, stage: str):
        """Return the AIEngine for a given stage, with fallback chain."""
        model_id = self._stage_models.get(stage)
        if model_id and model_id in self._engines_by_id:
            return self._engines_by_id[model_id]
        if model_id:
            logger.warning(
                "stage_router.model_not_found",
                stage=stage, model_id=model_id, fallback="repo_default",
            )
        return self._fallback_engine

    def get_model_label(self, stage: str) -> str:
        """Return human-readable model label for logging/notifications."""
        model_id = self._stage_models.get(stage)
        if model_id and model_id in self._engines_by_id:
            return self._engines_by_id[model_id].model_config.model_id
        if self._fallback_engine:
            return self._fallback_engine.model_config.model_id
        return "unknown"

    def get_model_usage(self) -> dict[str, str]:
        """Return a dict of stage -> model_label for all stages."""
        return {stage: self.get_model_label(stage) for stage in ALL_STAGES}


def build_stage_router_sync(repo, fallback_engine, sync_session) -> StageRouter:
    """Build a StageRouter from repository config (synchronous, for Celery)."""
    from app.models.ai_model import AIModel

    skills_config = repo.skills_config or {}
    stage_models = skills_config.get("stage_models", {})

    if not stage_models:
        return StageRouter(
            _fallback_engine=fallback_engine,
            _fallback_model_id=repo.ai_model_id,
        )

    needed_ids = {mid for mid in stage_models.values() if isinstance(mid, int)}
    engines_by_id: dict[int, Any] = {}

    if needed_ids:
        for model in sync_session.query(AIModel).filter(AIModel.id.in_(needed_ids)).all():
            try:
                engines_by_id[model.id] = build_engine_from_db_model(model)
            except Exception as exc:
                logger.warning(
                    "stage_router.build_engine_failed",
                    model_id=model.id, error=str(exc),
                )

    return StageRouter(
        _engines_by_id=engines_by_id,
        _stage_models=stage_models,
        _fallback_engine=fallback_engine,
        _fallback_model_id=repo.ai_model_id,
    )
