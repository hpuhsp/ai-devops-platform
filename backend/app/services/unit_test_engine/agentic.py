"""Agentic manager primitives for the AI unit-test workflow."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Any

from app.services.skills.open_registry import open_skill_registry


ALLOWED_MANAGER_ACTIONS = {
    "analyze_change",
    "build_context",
    "generate_tests",
    "validate_tests",
    "score_quality",
    "publish_feedback",
    "finish",
    "fail",
}


@dataclass
class ManagerDecision:
    action: str
    reason: str
    inputs: dict[str, Any] = field(default_factory=dict)
    expected_outcome: str = ""
    source: str = "llm"

    def as_trace(self, round_number: int) -> dict:
        return {
            "round": round_number,
            "action": self.action,
            "reason": self.reason,
            "inputs": self.inputs,
            "expected_outcome": self.expected_outcome,
            "source": self.source,
        }


class DecisionValidationError(ValueError):
    pass


def parse_manager_decision(content: str) -> ManagerDecision:
    """Parse a strict manager decision from LLM text."""
    raw = content.strip()
    if not raw:
        raise DecisionValidationError("empty decision")
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    if not raw.startswith("{"):
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise DecisionValidationError("decision is not JSON")
        raw = match.group(0)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DecisionValidationError(f"invalid JSON decision: {exc}") from exc

    action = data.get("action")
    reason = data.get("reason")
    if action not in ALLOWED_MANAGER_ACTIONS:
        raise DecisionValidationError(f"unsupported manager action: {action}")
    if not isinstance(reason, str) or not reason.strip():
        raise DecisionValidationError("decision.reason is required")
    inputs = data.get("inputs") or {}
    if not isinstance(inputs, dict):
        raise DecisionValidationError("decision.inputs must be an object")
    expected = data.get("expected_outcome") or ""
    if not isinstance(expected, str):
        expected = str(expected)
    return ManagerDecision(
        action=action,
        reason=reason.strip(),
        inputs=inputs,
        expected_outcome=expected.strip(),
    )


class ManagerFallbackPolicy:
    """Deterministic fallback when manager LLM is unavailable or invalid."""

    @staticmethod
    def next_decision(ctx: Any, executed_actions: set[str]) -> ManagerDecision:
        if "test_generation" not in ctx.enabled_stages:
            return ManagerDecision(
                action="finish",
                reason="fallback: AI unit-test stage is not enabled by pipeline rules",
                source="fallback",
            )

        ordered = [
            ("analyze_change", "fallback: inspect whether changed code needs tests"),
            ("build_context", "fallback: build minimal context before generation"),
            ("generate_tests", "fallback: generate candidate unit tests"),
            ("validate_tests", "fallback: validate generated tests and repair if needed"),
            ("score_quality", "fallback: score generated tests after validation"),
            ("publish_feedback", "fallback: publish feedback if configured"),
            ("finish", "fallback: default workflow completed"),
        ]
        for action, reason in ordered:
            if action not in executed_actions:
                if action == "build_context" and not ctx.change_intel_data:
                    continue
                if action == "generate_tests" and ctx.change_intel_data.get("need_test") is False:
                    return ManagerDecision(
                        action="finish",
                        reason="fallback: change analysis decided tests are not needed",
                        source="fallback",
                    )
                if action in {"validate_tests", "score_quality"} and not ctx.generated_files:
                    continue
                return ManagerDecision(action=action, reason=reason, source="fallback")
        return ManagerDecision(action="finish", reason="fallback: no remaining action", source="fallback")


class ManagerDecisionEngine:
    """LLM-backed decision engine with strict validation and safe fallback."""

    def __init__(self, max_tokens: int = 700):
        self.max_tokens = max_tokens

    async def decide(
        self,
        ctx: Any,
        round_number: int,
        executed_actions: set[str],
    ) -> tuple[ManagerDecision, int, int]:
        fallback = ManagerFallbackPolicy.next_decision(ctx, executed_actions)
        engine = self._manager_engine(ctx)
        if engine is None:
            return fallback, 0, 0

        try:
            response = await engine.complete_with_system(
                self._system_prompt(),
                self._user_prompt(ctx, round_number, executed_actions),
                temperature=0.1,
                max_tokens=self.max_tokens,
            )
            decision = parse_manager_decision(response.content)
            violation = self._state_policy_violation(ctx, decision)
            if violation:
                fallback.reason = (
                    f"{fallback.reason}; rejected manager action '{decision.action}' because {violation}"
                )
                return fallback, response.prompt_tokens, response.completion_tokens
            return decision, response.prompt_tokens, response.completion_tokens
        except Exception as exc:
            fallback.reason = f"{fallback.reason}; manager decision fallback because {exc}"
            return fallback, 0, 0

    @staticmethod
    def _manager_engine(ctx: Any):
        if ctx.agent_resolver:
            binding = ctx.agent_resolver.get_binding("test_manager")
            if binding:
                return ctx.agent_resolver.get_engine("test_manager")
        return ctx.engine

    @staticmethod
    def _system_prompt() -> str:
        actions = ", ".join(sorted(ALLOWED_MANAGER_ACTIONS))
        return (
            "You are TestManagerAgent, an AI unit-test manager inside a DevOps pipeline. "
            "Your scope is unit-test work only: change analysis, context selection, test generation, "
            "test validation/repair, quality scoring, and feedback. Code review is an outer pipeline "
            "stage. You may read code_review_result as context, but you must never request or simulate "
            "code review. Choose exactly one next action from the allowlist. Return only valid JSON, "
            "with no markdown and no prose outside the JSON object. Do not request arbitrary shell "
            "execution, secret access, repository mutation outside generated tests, or unlisted tools. "
            "Prefer minimal context and token-efficient skills. "
            f"Allowed actions: {actions}. "
            "Schema: {\"action\": string, \"reason\": string, \"inputs\": object, "
            "\"expected_outcome\": string}. "
            "Decision rules: "
            "1) If test_generation is not enabled, choose finish. "
            "2) If change analysis is missing, choose analyze_change. "
            "3) If change analysis says tests are not needed, choose finish. "
            "4) If context is missing after change analysis, choose build_context. "
            "5) If no tests exist and tests are needed, choose generate_tests. "
            "6) If tests exist but validation has not run or failed in a repairable way, choose validate_tests. "
            "7) If validation passed and quality is missing, choose score_quality. "
            "8) Choose publish_feedback only after quality scoring or a terminal skip/failure needs reporting. "
            "9) Choose fail only when no allowed action can make progress."
        )

    def _user_prompt(self, ctx: Any, round_number: int, executed_actions: set[str]) -> str:
        cards = [card.to_prompt_card() for card in open_skill_registry.list_cards(limit=8)]
        code_review_result = self._compact_code_review(
            (getattr(ctx.skill_context, "extra", {}) or {}).get("code_review_result")
        )
        state = {
            "round": round_number,
            "enabled_stages": sorted(ctx.enabled_stages),
            "executed_actions": sorted(executed_actions),
            "remaining_actions": sorted(ALLOWED_MANAGER_ACTIONS - set(executed_actions)),
            "changed_files": (ctx.skill_context.changed_files or [])[:20],
            "diff_chars": len(ctx.skill_context.diff or ""),
            "branch": getattr(ctx.skill_context, "branch", ""),
            "commit_sha": getattr(ctx.skill_context, "commit_sha", ""),
            "code_review_result": code_review_result,
            "has_change_analysis": bool(ctx.change_intel_data),
            "need_test": ctx.change_intel_data.get("need_test") if ctx.change_intel_data else None,
            "change_analysis": self._compact_change_analysis(ctx.change_intel_data),
            "has_context": bool(ctx.context_agent_output),
            "generated_files_count": len(ctx.generated_files),
            "generated_file_paths": [
                item.get("path")
                for item in (ctx.generated_files or [])[:10]
                if isinstance(item, dict) and item.get("path")
            ],
            "validation_status": ctx.worktree_result.get("status"),
            "validation_summary": self._compact_validation(ctx.worktree_result),
            "quality_score": self._compact_quality(ctx.quality_score),
            "recent_manager_trace": (ctx.output_data.get("manager_trace") or [])[-3:]
            if isinstance(getattr(ctx, "output_data", None), dict) else [],
            "policy": {
                "unit_test_only": True,
                "code_review_is_read_only_context": True,
                "no_arbitrary_shell": True,
                "allowed_write_scope": "generated test files only",
            },
            "available_skill_cards": cards,
        }
        return json.dumps(state, ensure_ascii=False)

    @staticmethod
    def _state_policy_violation(ctx: Any, decision: ManagerDecision) -> str | None:
        action = decision.action
        if action in {
            "analyze_change",
            "build_context",
            "generate_tests",
            "validate_tests",
            "score_quality",
        } and "test_generation" not in ctx.enabled_stages:
            return "test_generation stage is not enabled"
        if action == "build_context" and not ctx.change_intel_data:
            return "change analysis has not completed"
        if action == "generate_tests" and ctx.change_intel_data.get("need_test") is False:
            return "change analysis decided tests are not needed"
        if action in {"validate_tests", "score_quality"} and not ctx.generated_files:
            return "no generated tests are available"
        if action == "score_quality" and not ctx.worktree_result:
            return "validation result is not available"
        return None

    @staticmethod
    def _compact_quality(score: Any) -> Any:
        if not isinstance(score, dict):
            return None
        return {
            "overall": score.get("overall_score") or score.get("score"),
            "status": score.get("status"),
            "summary": score.get("summary"),
        }

    @staticmethod
    def _compact_code_review(result: Any) -> Any:
        if not isinstance(result, dict):
            return None
        findings = result.get("findings") or []
        return {
            "status": result.get("status"),
            "blocked": bool(result.get("blocked", False)),
            "score": result.get("score"),
            "critical_count": result.get("critical_count", 0),
            "high_count": result.get("high_count", 0),
            "top_findings": [
                {
                    "severity": item.get("severity"),
                    "file": item.get("file"),
                    "line": item.get("line"),
                    "message": item.get("message"),
                }
                for item in findings[:5]
                if isinstance(item, dict)
            ],
            "reason": result.get("reason") or result.get("error"),
        }

    @staticmethod
    def _compact_change_analysis(data: Any) -> Any:
        if not isinstance(data, dict):
            return None
        targets = data.get("targets") or []
        return {
            "need_test": data.get("need_test"),
            "risk_level": data.get("risk_level"),
            "impact_radius": data.get("impact_radius"),
            "skip_reason": data.get("skip_reason") or data.get("reason"),
            "target_count": len(targets),
            "targets": targets[:8],
        }

    @staticmethod
    def _compact_validation(result: Any) -> Any:
        if not isinstance(result, dict):
            return None
        stdout = result.get("stdout") or ""
        stderr = result.get("stderr") or ""
        return {
            "status": result.get("status"),
            "exit_code": result.get("exit_code"),
            "repair_rounds": result.get("repair_rounds", 0),
            "error": result.get("error"),
            "stdout_tail": stdout[-1200:] if stdout else "",
            "stderr_tail": stderr[-1200:] if stderr else "",
        }
