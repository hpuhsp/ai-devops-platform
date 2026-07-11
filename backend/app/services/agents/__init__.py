"""Agents package — multi-step AI agents for test generation pipeline."""


def __getattr__(name: str):
    if name == "ContextAgent":
        from .context_agent import ContextAgent

        return ContextAgent
    if name in {"ValidatorAgent", "ValidationResult"}:
        from .validator_agent import ValidatorAgent, ValidationResult

        return {"ValidatorAgent": ValidatorAgent, "ValidationResult": ValidationResult}[name]
    if name in {"RepairAgent", "RepairResult"}:
        from .repair_agent import RepairAgent, RepairResult

        return {"RepairAgent": RepairAgent, "RepairResult": RepairResult}[name]
    if name == "QualityScorer":
        from .quality_scorer import QualityScorer

        return QualityScorer
    if name in {"TestManagerAgent", "UnitTestWorkflow", "PipelineContext"}:
        from .test_manager import PipelineContext, TestManagerAgent, UnitTestWorkflow

        return {
            "PipelineContext": PipelineContext,
            "TestManagerAgent": TestManagerAgent,
            "UnitTestWorkflow": UnitTestWorkflow,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "ContextAgent", "ValidatorAgent", "ValidationResult",
    "RepairAgent", "RepairResult", "QualityScorer",
    "TestManagerAgent", "UnitTestWorkflow", "PipelineContext",
]
