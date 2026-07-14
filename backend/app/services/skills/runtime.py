"""Skill runtime abstraction for built-in skills and future SkillsHub adapters."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any

from app.services.skills.base import SkillContext, SkillResult
from app.services.skills.open_registry import open_skill_registry
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


class OpenSkillPackageAdapter:
    """Executes approved local SKILL.md packages through the configured LLM.

    This adapter deliberately does not execute arbitrary bundled scripts. It
    loads the full SKILL.md plus small declared references and asks the model to
    perform the task inside the normal platform context.
    """

    skill_type = "open"

    def list_metadata(self) -> list[dict]:
        return [
            {
                **card.to_prompt_card(),
                "skill_type": self.skill_type,
                "path": card.path,
            }
            for card in open_skill_registry.list_cards(limit=50)
        ]

    def validate(self, skill_name: str, stage_type: str | None = None) -> SkillValidationResult:
        package = open_skill_registry.get_package(skill_name, allowed_agent=stage_type, max_chars=1)
        if package is None:
            return SkillValidationResult(False, [f"Open skill package '{skill_name}' not found"])
        return SkillValidationResult(True)

    async def execute(
        self,
        skill_name: str,
        context: SkillContext,
        engine: Any,
        skill_config: dict | None = None,
    ) -> SkillResult:
        package = open_skill_registry.get_package(
            skill_name,
            allowed_agent=(skill_config or {}).get("allowed_agent"),
            max_chars=(skill_config or {}).get("max_skill_chars", 12000),
        )
        if package is None:
            return SkillResult(
                success=False,
                summary=f"Open skill package '{skill_name}' not found.",
                details={"status": "failed", "reason": "open skill package not found"},
            )
        if engine is None:
            return SkillResult(
                success=False,
                summary=f"Open skill package '{skill_name}' cannot run without an LLM engine.",
                details={"status": "failed", "reason": "llm engine not configured"},
            )

        system_prompt = (
            "You are executing an approved local SKILL.md capability package inside an AI DevOps "
            "unit-test workflow. Follow the skill instructions exactly, but do not request arbitrary "
            "shell execution, secrets, network calls, or production-code mutation. Return strict JSON."
        )
        user_prompt = json.dumps({
            "skill_package": package.to_prompt_package(),
            "skill_config": skill_config or {},
            "context": {
                "repo_url": context.repo_url,
                "platform": context.platform,
                "branch": context.branch,
                "commit_sha": context.commit_sha,
                "changed_files": context.changed_files[:50],
                "diff": context.diff[:12000],
                "extra": context.extra,
            },
        }, ensure_ascii=False)

        response = await engine.complete_with_system(
            system_prompt,
            user_prompt,
            temperature=(skill_config or {}).get("temperature", 0.1),
        )
        try:
            details = json.loads(response.content)
            if not isinstance(details, dict):
                details = {"raw_output": details}
            success = not bool(details.get("blocked") or details.get("failed"))
        except (json.JSONDecodeError, ValueError):
            details = {"raw_output": response.content}
            success = True
        return SkillResult(
            success=success,
            summary=details.get("summary") or "Open skill executed",
            details=details,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
        )


class SkillRuntime:
    def __init__(self, skills_hub_endpoint: str | None = None):
        self._builtin = BuiltinSkillAdapter()
        self._open = OpenSkillPackageAdapter()
        self._skillshub = SkillsHubAdapter(skills_hub_endpoint)

    def _adapter(self, skill_type: str | None):
        normalized = (skill_type or "builtin").lower()
        if normalized in {"builtin", "internal"}:
            return self._builtin
        if normalized in {"open", "project", "local"}:
            return self._open
        if normalized in {"skillshub", "external"}:
            return self._skillshub
        return None

    def list_metadata(self) -> list[dict]:
        return [
            *self._builtin.list_metadata(),
            *self._open.list_metadata(),
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
