"""Reusable AI unit test workflow engine."""

from .schemas import Stage, StageResult, WorkflowContext, WorkflowResult
from .ports import InMemoryWorkflowPorts, WorkflowPorts
from .platform_ports import PlatformWorkflowPorts


def __getattr__(name: str):
    if name in {"PipelineContext", "UnitTestWorkflow"}:
        from .workflow import PipelineContext, UnitTestWorkflow

        return {
            "PipelineContext": PipelineContext,
            "UnitTestWorkflow": UnitTestWorkflow,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "PipelineContext",
    "InMemoryWorkflowPorts",
    "PlatformWorkflowPorts",
    "Stage",
    "StageResult",
    "UnitTestWorkflow",
    "WorkflowContext",
    "WorkflowPorts",
    "WorkflowResult",
]
