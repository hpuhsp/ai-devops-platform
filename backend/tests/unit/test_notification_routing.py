from app.tasks.ai_tasks import _notification_skip_reason
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
