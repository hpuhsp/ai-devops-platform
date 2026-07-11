"""Skill runtime abstraction for built-in skills and future SkillsHub adapters."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.skills.base import SkillContext, SkillResult
from app.services.skills.registry import skill_registry


@dataclass
class SkillValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class BuiltinSkillAdapter:
    skill_type = "builtin"

    def list_metadata(self) -> list[dict]:
        return [
            {**meta, "skill_type": self.skill_type, "source": "builtin"}
            for meta in skill_registry.list_skills_metadata()
        ]

    def validate(self, skill_name: str, stage_type: str | None = None) -> SkillValidationResult:
        catalog = {meta["name"]: meta for meta in skill_registry.list_skills_metadata()}
        meta = catalog.get(skill_name)
        if not meta:
            return SkillValidationResult(False, [f"Skill '{skill_name}' not found"])
        if stage_type and meta.get("stage_type") and meta["stage_type"] != stage_type:
            return SkillValidationResult(
                False,
                [f"Skill '{skill_name}' belongs to stage '{meta['stage_type']}', not '{stage_type}'"],
            )
        return SkillValidationResult(True)

    async def execute(
        self,
        skill_name: str,
        context: SkillContext,
        engine: Any,
        skill_config: dict | None = None,
    ) -> SkillResult:
        return await skill_registry.execute(skill_name, context, engine, skill_config=skill_config)


class SkillsHubAdapter:
    """Placeholder adapter boundary for organization-managed external skills.

    The current phase intentionally does not call a remote SkillsHub. It accepts
    external skill metadata as configuration shape, but execution returns a
    controlled failure unless a concrete adapter is wired later.
    """

    skill_type = "skillshub"

    def __init__(self, endpoint: str | None = None):
        self.endpoint = endpoint

    def list_metadata(self) -> list[dict]:
        return []

    def validate(self, skill_name: str, stage_type: str | None = None) -> SkillValidationResult:
        warnings = [
            f"External skill '{skill_name}' will require a configured SkillsHub adapter before execution"
        ]
        return SkillValidationResult(True, warnings=warnings)

    async def execute(
        self,
        skill_name: str,
        context: SkillContext,
        engine: Any,
        skill_config: dict | None = None,
    ) -> SkillResult:
        return SkillResult(
            success=False,
            summary=f"External SkillsHub skill '{skill_name}' is not executable until a SkillsHub adapter is configured.",
            details={"status": "failed", "reason": "skillshub adapter not configured"},
        )


class SkillRuntime:
    def __init__(self, skills_hub_endpoint: str | None = None):
        self._builtin = BuiltinSkillAdapter()
        self._skillshub = SkillsHubAdapter(skills_hub_endpoint)

    def _adapter(self, skill_type: str | None):
        normalized = (skill_type or "builtin").lower()
        if normalized in {"builtin", "internal"}:
            return self._builtin
        if normalized in {"skillshub", "external"}:
            return self._skillshub
        return None

    def list_metadata(self) -> list[dict]:
        return [
            *self._builtin.list_metadata(),
            *self._skillshub.list_metadata(),
        ]

    def validate(
        self,
        skill_name: str,
        stage_type: str | None = None,
        skill_type: str | None = "builtin",
    ) -> SkillValidationResult:
        adapter = self._adapter(skill_type)
        if adapter is None:
            return SkillValidationResult(False, [f"Unsupported skill_type: {skill_type}"])
        return adapter.validate(skill_name, stage_type)

    async def execute(
        self,
        skill_name: str,
        context: SkillContext,
        engine: Any,
        skill_config: dict | None = None,
        skill_type: str | None = "builtin",
    ) -> SkillResult:
        adapter = self._adapter(skill_type)
        if adapter is None:
            return SkillResult(
                success=False,
                summary=f"Unsupported skill_type: {skill_type}",
                details={"status": "failed", "reason": f"unsupported skill_type: {skill_type}"},
            )
        return await adapter.execute(skill_name, context, engine, skill_config=skill_config)


skill_runtime = SkillRuntime()
