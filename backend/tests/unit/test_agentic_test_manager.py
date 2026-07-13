"""Agentic TestManager and curated SKILL.md registry tests."""
import asyncio
from types import SimpleNamespace

from app.services.skills.open_registry import OpenSkillRegistry
from app.services.unit_test_engine.agentic import (
    DecisionValidationError,
    ManagerDecision,
    ManagerDecisionEngine,
    ManagerFallbackPolicy,
    parse_manager_decision,
)
from app.services.unit_test_engine import InMemoryWorkflowPorts, PipelineContext, StageResult, UnitTestWorkflow


class _FakeLLMResponse:
    def __init__(self, content: str, prompt_tokens: int = 11, completion_tokens: int = 7):
        self.content = content
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _FakeDecisionEngine:
    def __init__(self, content: str):
        self.content = content
        self.calls = []

    async def complete_with_system(self, system_prompt, user_prompt, **kwargs):
        self.calls.append({
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "kwargs": kwargs,
        })
        return _FakeLLMResponse(self.content)


def _decision_ctx(engine, **overrides):
    base = {
        "enabled_stages": {"test_generation"},
        "change_intel_data": {},
        "context_agent_output": {},
        "generated_files": [],
        "worktree_result": {},
        "quality_score": None,
        "output_data": {},
        "agent_resolver": None,
        "engine": engine,
        "skill_context": SimpleNamespace(
            branch="feature/demo",
            commit_sha="abc123456",
            diff="diff --git a/app.py b/app.py",
            changed_files=["app.py"],
            extra={
                "code_review_result": {
                    "status": "success",
                    "score": 91,
                    "blocked": False,
                    "findings": [
                        {"severity": "medium", "file": "app.py", "line": 12, "message": "edge case"}
                    ],
                }
            },
        ),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_parse_manager_decision_accepts_strict_json():
    decision = parse_manager_decision(
        '{"action":"generate_tests","reason":"need coverage","inputs":{"target":"svc"},"expected_outcome":"tests"}'
    )

    assert decision.action == "generate_tests"
    assert decision.inputs["target"] == "svc"


def test_parse_manager_decision_rejects_unsupported_action():
    try:
        parse_manager_decision('{"action":"run_shell","reason":"do it"}')
    except DecisionValidationError as exc:
        assert "unsupported manager action" in str(exc)
    else:
        raise AssertionError("unsupported action should fail validation")


def test_parse_manager_decision_rejects_outer_code_review_action():
    try:
        parse_manager_decision('{"action":"run_code_review","reason":"review first"}')
    except DecisionValidationError as exc:
        assert "unsupported manager action" in str(exc)
    else:
        raise AssertionError("code review should be owned by the outer pipeline")


def test_open_skill_registry_indexes_skill_md(tmp_path):
    skill_dir = tmp_path / "pytest-unit-test"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        """---
name: pytest-unit-test
description: Generate pytest tests with minimal mocking.
source: github
allowed_agents: GeneratorAgent,RepairAgent
token_budget: 900
---

# Pytest Unit Test Skill
""",
        encoding="utf-8",
    )

    registry = OpenSkillRegistry([tmp_path])
    cards = registry.list_cards()

    assert len(cards) == 1
    assert cards[0].name == "pytest-unit-test"
    assert cards[0].source == "github"
    assert cards[0].token_budget == 900
    assert "GeneratorAgent" in cards[0].allowed_agents


def test_manager_fallback_finishes_when_unit_test_stage_disabled():
    ctx = SimpleNamespace(enabled_stages={"code_review"}, change_intel_data={},
                          generated_files=[], worktree_result={})

    decision = ManagerFallbackPolicy.next_decision(ctx, set())

    assert decision.action == "finish"
    assert "not enabled" in decision.reason


def test_manager_fallback_starts_with_change_analysis_even_when_code_review_is_enabled():
    ctx = SimpleNamespace(enabled_stages={"code_review", "test_generation"}, change_intel_data={},
                          generated_files=[], worktree_result={})

    decision = ManagerFallbackPolicy.next_decision(ctx, set())

    assert decision.action == "analyze_change"


def test_manager_decision_engine_rejects_semantically_invalid_action():
    ctx = SimpleNamespace(
        enabled_stages={"test_generation"},
        change_intel_data={"need_test": True},
        generated_files=[],
        worktree_result={},
    )
    decision = ManagerDecision(action="validate_tests", reason="try validation")

    violation = ManagerDecisionEngine._state_policy_violation(ctx, decision)

    assert violation == "no generated tests are available"


def test_manager_decision_engine_accepts_valid_llm_decision_and_records_prompt_context():
    engine = _FakeDecisionEngine(
        '{"action":"analyze_change","reason":"need impact analysis","inputs":{},"expected_outcome":"test targets"}'
    )
    ctx = _decision_ctx(engine)

    decision, prompt_tokens, completion_tokens = asyncio.run(
        ManagerDecisionEngine().decide(ctx, 1, set())
    )

    assert decision.action == "analyze_change"
    assert decision.source == "llm"
    assert prompt_tokens == 11
    assert completion_tokens == 7
    assert "Code review is an outer pipeline" in engine.calls[0]["system_prompt"]
    assert '"code_review_result"' in engine.calls[0]["user_prompt"]
    assert '"code_review_is_read_only_context": true' in engine.calls[0]["user_prompt"]


def test_manager_decision_engine_falls_back_on_outer_code_review_action():
    engine = _FakeDecisionEngine(
        '{"action":"run_code_review","reason":"review first","inputs":{},"expected_outcome":"review"}'
    )
    ctx = _decision_ctx(engine)

    decision, prompt_tokens, completion_tokens = asyncio.run(
        ManagerDecisionEngine().decide(ctx, 1, set())
    )

    assert decision.action == "analyze_change"
    assert decision.source == "fallback"
    assert "unsupported manager action" in decision.reason
    assert prompt_tokens == 0
    assert completion_tokens == 0


def test_manager_decision_engine_falls_back_on_state_policy_violation():
    engine = _FakeDecisionEngine(
        '{"action":"validate_tests","reason":"run now","inputs":{},"expected_outcome":"validated"}'
    )
    ctx = _decision_ctx(engine)

    decision, prompt_tokens, completion_tokens = asyncio.run(
        ManagerDecisionEngine().decide(ctx, 1, set())
    )

    assert decision.action == "analyze_change"
    assert decision.source == "fallback"
    assert "no generated tests are available" in decision.reason
    assert prompt_tokens == 11
    assert completion_tokens == 7


class _GatedWorkflow(UnitTestWorkflow):
    async def _stage_change_intelligence(self, ctx):
        output = {"need_test": False, "skip_reason": "docs only"}
        ctx.change_intel_data = output
        await self._persist(ctx, "change_intelligence", output)
        return StageResult(status="gated", output=output)


def test_agentic_workflow_records_manager_trace_for_fallback_decision():
    ports = InMemoryWorkflowPorts()
    ctx = PipelineContext(
        task_id="task-agentic",
        ports=ports,
        engine=None,
        enabled_stages={"test_generation"},
        skill_context=SimpleNamespace(
            repo_id=1,
            repo_url="https://git.example.com/demo.git",
            platform="gitlab",
            branch="feature/demo",
            commit_sha="abc123456",
            author="tester",
            diff="diff --git a/README.md b/README.md",
            changed_files=["README.md"],
            extra={},
        ),
        skills_config={"agents": {"max_manager_rounds": 3}},
    )

    result = asyncio.run(_GatedWorkflow().run(ctx))

    assert result["output_data"]["manager_trace"][0]["action"] == "analyze_change"
    assert result["output_data"]["manager_trace"][0]["source"] == "fallback"
    assert result["output_data"]["pipeline_status"]["status"] == "success"
    assert result["output_data"]["stage_results"][0]["stage"] == "change_intelligence"
