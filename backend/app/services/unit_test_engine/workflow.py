"""Unit test workflow public entry point.

The implementation is kept compatible with the existing TestManagerAgent module
while exposing a stable engine-level API for platform, manual trigger, and
future GitLab CI integration.
"""

from app.services.agents.test_manager import PipelineContext, UnitTestWorkflow
from app.services.unit_test_engine.platform_ports import PlatformWorkflowPorts
from app.services.unit_test_engine.ports import InMemoryWorkflowPorts, WorkflowPorts
from app.services.unit_test_engine.schemas import StageResult

__all__ = [
    "InMemoryWorkflowPorts",
    "PipelineContext",
    "PlatformWorkflowPorts",
    "StageResult",
    "UnitTestWorkflow",
    "WorkflowPorts",
]
