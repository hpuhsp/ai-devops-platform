"""Unit tests for Skills Engine."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.skills.registry import SkillRegistry
from app.services.skills.base import SkillContext


@pytest.fixture
def registry():
    return SkillRegistry()


@pytest.fixture
def sample_context():
    return SkillContext(
        repo_id=1,
        repo_url="https://github.com/test/repo",
        platform="github",
        branch="feature/test",
        commit_sha="abc1234567890",
        author="test-user",
        diff="""diff --git a/app.py b/app.py
+++ b/app.py
@@ -1,5 +1,10 @@
+def get_user(user_id):
+    query = f"SELECT * FROM users WHERE id = {user_id}"  # SQL injection!
+    return db.execute(query)
""",
        changed_files=["app.py"],
    )


@pytest.fixture
def mock_engine():
    engine = MagicMock()
    engine.complete_with_system = AsyncMock(return_value=MagicMock(
        content='{"summary":"发现SQL注入漏洞","score":30,"blocked":true,"findings":[{"severity":"critical","file":"app.py","line":2,"message":"SQL注入漏洞","suggestion":"使用参数化查询"}]}',
        prompt_tokens=100,
        completion_tokens=50,
    ))
    return engine


def test_registry_loads_builtin_skills(registry):
    skills = registry.list_skills()
    assert "code_review" in skills, "code_review skill should be registered"
    assert "test_generation" in skills, "test_generation skill should be registered"


def test_registry_get_unknown_skill(registry):
    result = registry.get("nonexistent_skill")
    assert result is None


@pytest.mark.asyncio
async def test_code_review_skill_blocks_on_critical(registry, sample_context, mock_engine):
    result = await registry.execute("code_review", sample_context, mock_engine)
    assert result.success is True
    assert result.blocked is True
    assert result.details["critical_count"] >= 1
    assert result.prompt_tokens == 100
    assert result.completion_tokens == 50


@pytest.mark.asyncio
async def test_code_review_empty_diff(registry, mock_engine):
    ctx = SkillContext(
        repo_id=1, repo_url="https://github.com/test/repo",
        platform="github", branch="main", commit_sha="abc", author="user", diff="",
    )
    result = await registry.execute("code_review", ctx, mock_engine)
    assert result.success is True
    assert result.blocked is False
    assert "Empty diff" in result.summary


@pytest.mark.asyncio
async def test_test_generation_skill(registry, sample_context, mock_engine):
    mock_engine.complete_with_system = AsyncMock(return_value=MagicMock(
        content='{"framework":"pytest","files":[{"path":"tests/test_app.py","content":"import pytest\\ndef test_get_user(): pass","description":"Test for get_user"}],"run_command":"pytest","estimated_coverage_delta":"+3%"}',
        prompt_tokens=80,
        completion_tokens=120,
    ))
    result = await registry.execute("test_generation", sample_context, mock_engine)
    assert result.success is True
    assert len(result.details["generated_files"]) == 1
    assert result.details["framework"] == "pytest"


@pytest.mark.asyncio
async def test_code_review_handles_invalid_json(registry, sample_context):
    engine = MagicMock()
    engine.complete_with_system = AsyncMock(return_value=MagicMock(
        content="This is not JSON — the code looks problematic.",
        prompt_tokens=50,
        completion_tokens=20,
    ))
    result = await registry.execute("code_review", sample_context, engine)
    assert result.success is True  # degrades gracefully
