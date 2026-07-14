"""Agentic TestManager and curated SKILL.md registry tests."""
import asyncio
from pathlib import Path
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
from app.services.unit_test_engine.subagent_runtime import SubAgentContractError, SubAgentRuntime


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


def test_parse_manager_decision_accepts_subagent_action():
    decision = parse_manager_decision(
        '{"action":"run_test_generation_agent","reason":"need tests","inputs":{},"expected_outcome":"files"}'
    )

    assert decision.action == "run_test_generation_agent"


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


def test_open_skill_registry_defaults_to_project_skills_and_env_roots(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    project_skill = project_root / "skills" / "pytest-unit-test"
    external_root = tmp_path / "org-skills"
    external_skill = external_root / "vitest-unit-test"
    qoder_skill = project_root / ".qoder" / "skills" / "ignored-skill"

    for skill_dir in (project_skill, external_skill, qoder_skill):
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            f"""---
name: {skill_dir.name}
description: {skill_dir.name} description.
---

# {skill_dir.name}
""",
            encoding="utf-8",
        )

    monkeypatch.setattr(OpenSkillRegistry, "_project_root", staticmethod(lambda: project_root))
    monkeypatch.setenv("AI_DEVOPS_SKILLS_ROOTS", str(external_root))

    cards = OpenSkillRegistry().list_cards(limit=10)

    assert [card.name for card in cards] == ["pytest-unit-test", "vitest-unit-test"]
    assert cards[0].source == "project"
    assert cards[1].source == "external"


def test_open_skill_registry_project_root_can_be_set_by_env(tmp_path, monkeypatch):
    project_skill = tmp_path / "skills" / "pytest-unit-test"
    project_skill.mkdir(parents=True)
    (project_skill / "SKILL.md").write_text(
        """---
name: pytest-unit-test
description: Generate pytest tests.
---

# Pytest Unit Test Skill
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("AI_DEVOPS_PROJECT_ROOT", str(tmp_path))
    monkeypatch.delenv("AI_DEVOPS_SKILLS_ROOTS", raising=False)

    cards = OpenSkillRegistry().list_cards()

    assert [card.name for card in cards] == ["pytest-unit-test"]
    assert cards[0].source == "project"


def test_open_skill_registry_excludes_qoder_roots_even_when_explicit(tmp_path):
    project_skill = tmp_path / "skills" / "project-skill"
    qoder_root = tmp_path / ".qoder" / "skills"
    qoder_skill = qoder_root / "ignored-skill"

    for skill_dir in (project_skill, qoder_skill):
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            f"""---
name: {skill_dir.name}
description: {skill_dir.name} description.
---

# {skill_dir.name}
""",
            encoding="utf-8",
        )

    registry = OpenSkillRegistry([qoder_root, tmp_path / "skills"])
    cards = registry.list_cards(limit=10)

    assert [card.name for card in cards] == ["project-skill"]
    assert all(".qoder" not in card.path for card in cards)


def test_unit_test_subagent_definitions_exist_and_reject_qoder_skills():
    root = Path(__file__).resolve().parents[2] / "app" / "services" / "unit_test_engine" / "subagents"
    expected = {
        "change-understanding-agent.md",
        "test-planning-agent.md",
        "test-generation-agent.md",
        "test-review-agent.md",
        "test-runner-agent.md",
        "test-repair-agent.md",
        "quality-judge-agent.md",
        "feedback-agent.md",
    }

    files = {path.name for path in root.glob("*.md") if path.name != "README.md"}

    assert files == expected
    for path in root.glob("*.md"):
        if path.name == "README.md":
            continue
        text = path.read_text(encoding="utf-8")
        assert "skills from project-root skills/ directory" in text
        assert ".qoder/skills" not in text.split("allowed_skills:", 1)[-1].split("allowed_tools:", 1)[0]


def test_subagent_runtime_loads_definitions_and_enforces_tool_boundary():
    runtime = SubAgentRuntime()
    definition = runtime.load("test-runner-agent")

    assert definition.name == "test-runner-agent"
    assert "Bash" in definition.allowed_tools
    runtime.validate_tool_request("test-runner-agent", {"Bash", "Read"})

    try:
        runtime.validate_tool_request("test-generation-agent", {"Bash"})
    except SubAgentContractError as exc:
        assert "cannot use tools" in str(exc)
    else:
        raise AssertionError("test-generation-agent must not be allowed to use Bash")


def test_subagent_runtime_builds_prompt_with_skill_packages():
    runtime = SubAgentRuntime()
    system_prompt, user_prompt = runtime.build_prompt(
        "test-generation-agent",
        {"test_plan": {"cases": []}},
        skill_packages=[{"name": "pytest-unit"}],
    )

    assert "Test Generation Agent" in system_prompt
    assert "structured output contract" in system_prompt.lower()
    assert '"available_skill_packages"' in user_prompt


def test_subagent_runtime_invokes_engine_and_validates_json_output():
    class Engine:
        async def complete_with_system(self, system_prompt, user_prompt, **kwargs):
            assert "Return only strict JSON" in system_prompt
            assert "test-generation-agent" in user_prompt

            class Response:
                content = '{"agent":"test-generation-agent","status":"success","generated_files":[]}'
                prompt_tokens = 5
                completion_tokens = 4

            return Response()

    result = asyncio.run(SubAgentRuntime().invoke(
        "test-generation-agent",
        {"test_plan": {"cases": []}},
        Engine(),
        requested_tools={"Read", "Write"},
    ))

    assert result.success
    assert result.agent == "test-generation-agent"
    assert result.prompt_tokens == 5


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

    assert decision.action == "run_change_understanding_agent"


def test_manager_fallback_routes_failed_runner_to_repair_agent():
    ctx = SimpleNamespace(
        enabled_stages={"test_generation"},
        change_intel_data={"need_test": True},
        generated_files=[{"path": "tests/test_app.py", "content": "def test_x(): pass"}],
        worktree_result={"status": "failed", "final_validation": {"can_repair": True}},
    )

    decision = ManagerFallbackPolicy.next_decision(ctx, {
        "run_change_understanding_agent",
        "run_test_planning_agent",
        "run_test_generation_agent",
        "run_test_review_agent",
        "run_test_runner_agent",
    })

    assert decision.action == "run_test_repair_agent"


def test_manager_fallback_routes_passed_runner_to_quality_judge():
    ctx = SimpleNamespace(
        enabled_stages={"test_generation"},
        change_intel_data={"need_test": True},
        generated_files=[{"path": "tests/test_app.py", "content": "def test_x(): pass"}],
        worktree_result={"status": "passed", "final_validation": {"can_repair": False}},
    )

    decision = ManagerFallbackPolicy.next_decision(ctx, {
        "run_change_understanding_agent",
        "run_test_planning_agent",
        "run_test_generation_agent",
        "run_test_review_agent",
        "run_test_runner_agent",
    })

    assert decision.action == "run_quality_judge_agent"


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
    assert '"available_subagents"' in engine.calls[0]["user_prompt"]


def test_test_review_rejects_non_test_file_generation():
    ports = InMemoryWorkflowPorts()
    ctx = PipelineContext(
        task_id="task-review",
        ports=ports,
        generated_files=[{"path": "app/service.py", "content": "print('bad')"}],
    )

    result = asyncio.run(UnitTestWorkflow()._stage_test_review(ctx))

    assert result.status == "failed"
    assert result.output["violations"][0]["reason"] == "generated file is outside the allowed test-file scope"
    assert ctx.output_data["subagent_trace"][0]["agent"] == "test-review-agent"
    assert "Read" in ctx.output_data["subagent_trace"][0]["allowed_tools"]


def test_manager_decision_engine_falls_back_on_outer_code_review_action():
    engine = _FakeDecisionEngine(
        '{"action":"run_code_review","reason":"review first","inputs":{},"expected_outcome":"review"}'
    )
    ctx = _decision_ctx(engine)

    decision, prompt_tokens, completion_tokens = asyncio.run(
        ManagerDecisionEngine().decide(ctx, 1, set())
    )

    assert decision.action == "run_change_understanding_agent"
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

    assert decision.action == "run_change_understanding_agent"
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

    assert result["output_data"]["manager_trace"][0]["action"] == "run_change_understanding_agent"
    assert result["output_data"]["manager_trace"][0]["source"] == "fallback"
    assert result["output_data"]["pipeline_status"]["status"] == "success"
    assert result["output_data"]["stage_results"][0]["stage"] == "change_intelligence"
