"""SkillRuntime adapter boundary tests."""
import asyncio

from app.services.skills.base import SkillContext
from app.services.skills.open_registry import OpenSkillRegistry
import app.services.skills.runtime as runtime_module
from app.services.skills.runtime import SkillRuntime


def test_skill_runtime_lists_builtin_skills():
    runtime = SkillRuntime()
    names = {meta["name"] for meta in runtime.list_metadata()}

    assert {"code_review", "change_intelligence", "test_generation"}.issubset(names)


def test_skill_runtime_validates_builtin_stage_type():
    runtime = SkillRuntime()

    assert runtime.validate("code_review", "code_review").valid
    result = runtime.validate("test_generation", "code_review")

    assert not result.valid
    assert "belongs to stage" in result.errors[0]


def test_skill_runtime_accepts_skillshub_placeholder_with_warning():
    runtime = SkillRuntime()

    result = runtime.validate("org.python_unit_test", "generator", skill_type="skillshub")

    assert result.valid
    assert result.warnings


def test_skill_runtime_skillshub_execution_fails_closed():
    runtime = SkillRuntime()
    context = SkillContext(
        repo_id=1,
        repo_url="https://git.example.com/group/project.git",
        platform="gitlab",
        branch="feature/demo",
        commit_sha="abc123",
        author="tester",
    )

    result = asyncio.run(runtime.execute(
        "org.python_unit_test",
        context,
        engine=None,
        skill_type="skillshub",
    ))

    assert not result.success
    assert result.details["reason"] == "skillshub adapter not configured"


def test_skill_runtime_lists_and_executes_open_skill_package(monkeypatch, tmp_path):
    skill_dir = tmp_path / "pytest-unit"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        """---
name: pytest-unit
description: Pytest unit test skill
allowed_agents: generator
token_budget: 900
---
# Pytest Unit Test Skill

Generate focused pytest tests.
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_module, "open_skill_registry", OpenSkillRegistry([tmp_path]))

    class Engine:
        async def complete_with_system(self, system_prompt, user_prompt, **kwargs):
            assert "SKILL.md capability package" in system_prompt
            assert "pytest-unit" in user_prompt

            class Response:
                content = '{"summary":"done","files":[]}'
                prompt_tokens = 3
                completion_tokens = 2

            return Response()

    runtime = SkillRuntime()

    assert any(meta["name"] == "pytest-unit" for meta in runtime.list_metadata())
    result = asyncio.run(runtime.execute(
        "pytest-unit",
        SkillContext(
            repo_id=1,
            repo_url="https://git.example.com/group/project.git",
            platform="gitlab",
            branch="feature/demo",
            commit_sha="abc123",
            author="tester",
            diff="diff",
            changed_files=["app.py"],
        ),
        Engine(),
        skill_type="open",
        skill_config={"allowed_agent": "generator"},
    ))

    assert result.success
    assert result.summary == "done"
