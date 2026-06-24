"""Unit tests for the branch rule engine and the test-runner whitelist."""
from types import SimpleNamespace

import pytest

from app.services.rules.engine import _match, get_stages_sync, TEMPLATES, ALL_STAGES
from app.tasks.ai_tasks import _safe_test_command


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


# ── test-runner whitelist (command-injection guard) ───────────────────────────

@pytest.mark.parametrize("framework,expected", [
    ("pytest", ["pytest", "-q"]),
    ("PyTest", ["pytest", "-q"]),
    ("python", ["pytest", "-q"]),
    ("jest", None),
    ("", None),
    (None, None),
])
def test_safe_test_command(framework, expected):
    assert _safe_test_command(framework) == expected
