"""Unit tests for the branch rule engine and the test-runner whitelist."""
import asyncio
from types import SimpleNamespace

import pytest

from app.api.v1.endpoints.rules import list_templates
from app.services.rules.engine import _match, get_stages_sync, TEMPLATES, ALL_STAGES
from app.tasks.ai_tasks import _safe_test_command, _select_event_diff, SAFE_TEST_COMMANDS


# ── _match ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("pattern,branch,expected", [
    ("feature/*", "feature/login", True),
    ("feature/*", "feature/a/b", True),
    ("feature/*", "hotfix/x", False),
    ("main", "main", True),
    ("main", "develop", False),
    ("*", "anything", True),
])
def test_match(pattern, branch, expected):
    assert _match(pattern, branch) is expected


# ── get_stages_sync (priority order + fallback) ───────────────────────────────

class _FakeScalars:
    def __init__(self, items): self._items = items
    def all(self): return self._items


class _FakeResult:
    def __init__(self, items): self._items = items
    def scalars(self): return _FakeScalars(self._items)


class _FakeSession:
    """Returns pre-sorted rules regardless of the query (order_by is SQL-side)."""
    def __init__(self, rules): self._rules = rules
    def execute(self, *_a, **_k): return _FakeResult(self._rules)


def _rule(name, pattern, stages, priority=50):
    return SimpleNamespace(name=name, pattern=pattern, stages=stages,
                           priority=priority, enabled=True)


def test_first_matching_rule_wins():
    rules = [  # already in priority-desc order, as the real query returns
        _rule("feat", "feature/*", ["code_review", "test_generation"], 80),
        _rule("all", "*", ["code_review"], 1),
    ]
    assert get_stages_sync(1, "feature/login", _FakeSession(rules)) == \
        ["code_review", "test_generation"]


def test_falls_through_to_wildcard():
    rules = [
        _rule("feat", "feature/*", ["code_review", "test_generation"], 80),
        _rule("all", "*", ["code_review"], 1),
    ]
    assert get_stages_sync(1, "random-branch", _FakeSession(rules)) == ["code_review"]


def test_no_rules_uses_safe_fallback():
    assert get_stages_sync(1, "feature/login", _FakeSession([])) == ["code_review"]


# ── templates ─────────────────────────────────────────────────────────────────

def test_every_template_has_catch_all_and_valid_stages():
    for key, rules in TEMPLATES.items():
        assert any(r["pattern"] == "*" for r in rules), f"{key} missing catch-all"
        for r in rules:
            assert set(r["stages"]).issubset(set(ALL_STAGES)), f"{key} has unknown stage"


def test_public_templates_are_branch_strategies():
    visible_keys = {tpl["key"] for tpl in asyncio.run(list_templates())}

    assert visible_keys == {"gitflow", "trunk", "github_flow", "gitlab_flow"}


def test_review_only_remains_internal_compatibility_template():
    assert "review_only" in TEMPLATES
    assert TEMPLATES["review_only"][0]["pattern"] == "*"
    assert TEMPLATES["review_only"][0]["stages"] == ["code_review"]


def test_github_and_gitlab_flow_templates_are_available():
    assert "github_flow" in TEMPLATES
    assert "gitlab_flow" in TEMPLATES
    assert any(rule["pattern"] == "main" for rule in TEMPLATES["github_flow"])
    assert any(rule["pattern"] == "production" for rule in TEMPLATES["gitlab_flow"])


# ── test-runner whitelist (command-injection guard) ───────────────────────────

@pytest.mark.parametrize("framework,expected", [
    ("pytest", SAFE_TEST_COMMANDS["pytest"]),
    ("PyTest", SAFE_TEST_COMMANDS["pytest"]),
    ("python", SAFE_TEST_COMMANDS["python"]),
    ("jest", None),
    ("", None),
    (None, None),
])
def test_safe_test_command(framework, expected):
    assert _safe_test_command(framework) == expected


def test_select_event_diff_falls_back_when_before_equals_commit():
    git_agent = SimpleNamespace(
        get_diff=lambda *_args: (_ for _ in ()).throw(AssertionError("must not call range diff")),
        get_commit_diff=lambda commit_sha, branch=None: (f"commit diff {commit_sha} {branch}", ["app.py"]),
        get_latest_diff=lambda: ("latest diff", ["fallback.py"]),
    )

    diff, changed_files = _select_event_diff(git_agent, "abc123", "abc123", "feature/demo")

    assert diff == "commit diff abc123 feature/demo"
    assert changed_files == ["app.py"]


def test_select_event_diff_for_new_branch_uses_commit_diff_with_branch():
    all_zeros = "0" * 40
    git_agent = SimpleNamespace(
        get_diff=lambda *_args: (_ for _ in ()).throw(AssertionError("must not call range diff")),
        get_commit_diff=lambda commit_sha, branch=None: (f"commit diff {commit_sha} {branch}", ["app.py"]),
        get_latest_diff=lambda: ("latest diff", ["fallback.py"]),
    )

    diff, changed_files = _select_event_diff(git_agent, all_zeros, "abc123", "feature/demo")

    assert diff == "commit diff abc123 feature/demo"
    assert changed_files == ["app.py"]
