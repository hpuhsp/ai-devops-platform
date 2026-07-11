import asyncio
from types import SimpleNamespace

from app.services.notify.policy_engine import match_policy
from app.tasks.ai_tasks import (
    _notification_event_attributes,
    _send_notifications_policy_aware,
    _notification_skip_reason,
)
from app.api.v1.endpoints.config import _without_notify_config_reference


def test_disabled_event_is_skipped():
    notif = {"type": "test_generation_result", "data": {}}
    settings = {"enabled_events": ["code_review_result"]}

    assert _notification_skip_reason(notif, settings) == "event disabled: test_generation_result"


def test_code_review_below_min_severity_is_skipped():
    notif = {
        "type": "code_review_result",
        "data": {
            "blocked": False,
            "findings": [{"severity": "medium"}],
        },
    }
    settings = {"enabled_events": ["code_review_result"], "min_severity": "high"}

    assert _notification_skip_reason(notif, settings) == "severity below threshold: high"


def test_code_review_at_min_severity_is_sent():
    notif = {
        "type": "code_review_result",
        "data": {
            "blocked": False,
            "findings": [{"severity": "high"}],
        },
    }
    settings = {"enabled_events": ["code_review_result"], "min_severity": "high"}

    assert _notification_skip_reason(notif, settings) is None


def test_blocked_only_skips_non_blocking_review():
    notif = {
        "type": "code_review_result",
        "data": {
            "blocked": False,
            "findings": [{"severity": "critical"}],
        },
    }
    settings = {"enabled_events": ["code_review_result"], "blocked_only": True}

    assert _notification_skip_reason(notif, settings) == "code review not blocked"


def test_deleted_notify_config_reference_is_removed_from_repo_config():
    cfg = {
        "notifications": {
            "notify_config_id": 12,
            "enabled_events": ["code_review_result"],
        },
        "test_generation": {"enabled": True},
    }

    next_cfg, changed = _without_notify_config_reference(cfg, 12)

    assert changed is True
    assert "notify_config_id" not in next_cfg["notifications"]
    assert next_cfg["notifications"]["enabled_events"] == ["code_review_result"]
    assert cfg["notifications"]["notify_config_id"] == 12


def test_unrelated_notify_config_reference_is_kept():
    cfg = {"notifications": {"notify_config_id": 12}}

    next_cfg, changed = _without_notify_config_reference(cfg, 99)

    assert changed is False
    assert next_cfg["notifications"]["notify_config_id"] == 12


def test_policy_with_repo_scope_does_not_match_missing_repo_context():
    policy = SimpleNamespace(
        enabled=True,
        repo_ids=[1],
        branch_patterns=[],
        event_types=["code_review_result"],
        stage_types=[],
        status_filter=[],
        min_severity="all",
        blocked_only=False,
    )

    assert match_policy(policy, repo_id=None, event_type="code_review_result") is False


def test_policy_with_repo_scope_matches_expected_repo():
    policy = SimpleNamespace(
        enabled=True,
        repo_ids=[1],
        branch_patterns=["feature/*"],
        event_types=["test_generation_result"],
        stage_types=["test_generation"],
        status_filter=["failed"],
        min_severity="all",
        blocked_only=False,
    )

    assert match_policy(
        policy,
        repo_id=1,
        branch="feature/demo",
        event_type="test_generation_result",
        stage_type="test_generation",
        status="failed",
    ) is True


def test_test_generation_event_attributes_use_worktree_status():
    attrs = _notification_event_attributes({
        "type": "test_generation_result",
        "data": {"worktree_run": {"status": "failed"}},
    })

    assert attrs["event_type"] == "test_generation_result"
    assert attrs["status"] == "failed"


def test_quality_score_event_attributes_use_risk_level():
    attrs = _notification_event_attributes({
        "type": "quality_score_result",
        "data": {"quality_score": {"risk_level": "high", "total_score": 4.5}},
    })

    assert attrs["severity"] == "high"
    assert attrs["status"] == "failed"


def test_policy_without_channel_falls_back_to_repo_notification(monkeypatch):
    import app.services.notify.policy_engine as policy_engine
    import app.tasks.ai_tasks as ai_tasks

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    async def fake_send_one(notif_data, notify_cfg):
        sent.append((notif_data, notify_cfg))

    sent = []
    policy = SimpleNamespace(notify_config_id=None)
    monkeypatch.setattr(ai_tasks, "SyncSession", lambda: FakeSession())
    monkeypatch.setattr(policy_engine, "resolve_policies_sync", lambda *args, **kwargs: [policy])
    monkeypatch.setattr(ai_tasks, "_send_one", fake_send_one)

    asyncio.run(_send_notifications_policy_aware(
        {"type": "test_generation_result", "data": {"worktree_run": {"status": "passed"}}},
        {"id": 7, "name": "repo-default", "settings": {}, "config": {}},
        repo_id=1,
        branch="feature/demo",
        stage_type="test_generation",
    ))

    assert len(sent) == 1
    assert sent[0][1]["id"] == 7
