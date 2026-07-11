"""Ports for side effects emitted by the reusable unit test workflow."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class WorkflowPorts(Protocol):
    """Side-effect boundary for persistence, audit records, notifications, and MR feedback."""

    async def persist(self, ctx: Any, key: str, value: dict):
        ...

    async def record_execution(
        self,
        ctx: Any,
        agent_type: str,
        status: str,
        input_data: dict | None = None,
        output_data: dict | None = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        duration_ms: int = 0,
        round_number: int = 1,
    ):
        ...

    async def notify(self, ctx: Any, notif_data: dict, stage_type: str):
        ...

    async def publish_mr_feedback(self, ctx: Any) -> dict:
        ...


@dataclass
class InMemoryWorkflowPorts:
    """No-external-side-effect ports for tests, CLI dry-runs, and future library use."""

    persisted: list[tuple[str, dict]]
    records: list[dict]
    notifications: list[dict]
    mr_feedback: list[dict]

    def __init__(self):
        self.persisted = []
        self.records = []
        self.notifications = []
        self.mr_feedback = []

    async def persist(self, ctx: Any, key: str, value: dict):
        self.persisted.append((key, value))

    async def record_execution(
        self,
        ctx: Any,
        agent_type: str,
        status: str,
        input_data: dict | None = None,
        output_data: dict | None = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        duration_ms: int = 0,
        round_number: int = 1,
    ):
        self.records.append({
            "task_id": getattr(ctx, "task_id", ""),
            "agent_type": agent_type,
            "status": status,
            "input_data": input_data,
            "output_data": output_data,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "duration_ms": duration_ms,
            "round_number": round_number,
        })

    async def notify(self, ctx: Any, notif_data: dict, stage_type: str):
        self.notifications.append({
            "stage_type": stage_type,
            "data": notif_data,
        })

    async def publish_mr_feedback(self, ctx: Any) -> dict:
        result = {"ai_branch": None, "mr_iid": getattr(ctx, "event_data", {}).get("mr_iid")}
        self.mr_feedback.append(result)
        return result
