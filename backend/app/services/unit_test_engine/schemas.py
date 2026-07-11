"""Public schemas for the reusable AI unit test workflow engine."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class StageResult:
    """Normalized result produced by every workflow stage."""

    status: str
    reason: str | None = None
    output: dict = field(default_factory=dict)
    artifacts: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    duration_ms: int = 0


class WorkflowContext(Protocol):
    """Structural protocol for workflow context objects."""

    output_data: dict
    prompt_tokens: int
    completion_tokens: int


class Stage(Protocol):
    """Executable workflow stage contract."""

    name: str
    required_inputs: list[str]
    produced_outputs: list[str]

    async def run(self, context: WorkflowContext) -> StageResult:
        ...


@dataclass
class WorkflowResult:
    """Top-level result shape returned by the workflow engine."""

    output_data: dict[str, Any]
    prompt_tokens: int = 0
    completion_tokens: int = 0
