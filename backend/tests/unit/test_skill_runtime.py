"""SkillRuntime adapter boundary tests."""
import asyncio

from app.services.skills.base import SkillContext
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
