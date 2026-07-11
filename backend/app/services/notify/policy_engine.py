"""
Notification Policy Engine — matches pipeline events to notification policies.
Replaces the inline repo.skills_config.notifications routing.
"""
from __future__ import annotations

import fnmatch
import structlog
from typing import Optional, Any

from sqlalchemy import select

logger = structlog.get_logger()

SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def _any_pattern_match(patterns: list[str], value: str) -> bool:
    """True if value matches any fnmatch pattern, or patterns is empty (match all)."""
    if not patterns:
        return True
    return any(fnmatch.fnmatch(value, p) for p in patterns)


def _any_in(items: list, values: list) -> bool:
    """True if any item is in values, or items is empty (match all)."""
    if not items:
        return True
    return bool(set(items) & set(values))


def _severity_ok(min_severity: str, actual_severity: str) -> bool:
    min_rank = SEVERITY_RANK.get(min_severity, 0)
    actual_rank = SEVERITY_RANK.get(actual_severity, 0)
    return actual_rank >= min_rank


def match_policy(
    policy,
    *,
    repo_id: int | None = None,
    branch: str = "",
    event_type: str = "",
    stage_type: str = "",
    status: str = "",
    severity: str = "low",
    blocked: bool = False,
) -> bool:
    """Check if a notification policy matches a pipeline event."""

    # Must be enabled
    if not policy.enabled:
        return False

    # Repo filter
    if policy.repo_ids and (repo_id is None or repo_id not in policy.repo_ids):
        return False

    # Branch filter
    if policy.branch_patterns and not _any_pattern_match(policy.branch_patterns, branch):
        return False

    # Event type filter
    if policy.event_types and event_type not in policy.event_types:
        return False

    # Stage type filter
    if policy.stage_types and stage_type not in policy.stage_types:
        return False

    # Status filter
    if policy.status_filter and status not in policy.status_filter:
        return False

    # Severity filter
    if policy.min_severity != "all" and not _severity_ok(policy.min_severity, severity):
        return False

    # Blocked-only filter
    if policy.blocked_only and not blocked:
        return False

    return True


def resolve_policies_sync(
    db,
    *,
    repo_id: int | None = None,
    branch: str = "",
    event_type: str = "",
    stage_type: str = "",
    status: str = "",
    severity: str = "low",
    blocked: bool = False,
) -> list[Any]:
    """Find all matching notification policies, ordered by priority desc."""
    from app.models.notification_policy import NotificationPolicy

    # Load all enabled policies and filter in Python (JSONB filters are hard in SQL)
    all_policies = db.execute(
        select(NotificationPolicy)
        .where(NotificationPolicy.enabled == True)
        .order_by(NotificationPolicy.priority.desc())
    ).scalars().all()

    matched = []
    for policy in all_policies:
        if match_policy(
            policy,
            repo_id=repo_id,
            branch=branch,
            event_type=event_type,
            stage_type=stage_type,
            status=status,
            severity=severity,
            blocked=blocked,
        ):
            matched.append(policy)

    return matched
