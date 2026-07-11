"""
Sprint D tests: Fine-grained task status machine.
"""
import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock
import asyncio
import pytest

_spec = importlib.util.spec_from_file_location(
    "task_status",
    Path(__file__).resolve().parents[2] / "app" / "models" / "task_status.py",
)
_task_status_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_task_status_mod)

TaskStatus = _task_status_mod.TaskStatus
LEGACY_STATUS_MAP = _task_status_mod.LEGACY_STATUS_MAP
STAGE_STATUS_MAP = _task_status_mod.STAGE_STATUS_MAP

# ── TaskStatus: transitions ──────────────────────────────────────────────────

class TestTaskStatusTransitions:
    def test_created_to_analyzing(self):
        assert TaskStatus.is_valid_transition(TaskStatus.CREATED, TaskStatus.ANALYZING)

    def test_created_to_failed(self):
        assert TaskStatus.is_valid_transition(TaskStatus.CREATED, TaskStatus.FAILED)

    def test_created_to_success_invalid(self):
        assert not TaskStatus.is_valid_transition(TaskStatus.CREATED, TaskStatus.SUCCESS)

    def test_analyzing_to_generating(self):
        assert TaskStatus.is_valid_transition(TaskStatus.ANALYZING, TaskStatus.GENERATING)

    def test_analyzing_to_success_gated(self):
        assert TaskStatus.is_valid_transition(TaskStatus.ANALYZING, TaskStatus.SUCCESS)

    def test_analyzing_to_failed(self):
        assert TaskStatus.is_valid_transition(TaskStatus.ANALYZING, TaskStatus.FAILED)

    def test_generating_to_executing(self):
        assert TaskStatus.is_valid_transition(TaskStatus.GENERATING, TaskStatus.EXECUTING)

    def test_executing_to_repairing(self):
        assert TaskStatus.is_valid_transition(TaskStatus.EXECUTING, TaskStatus.REPAIRING)

    def test_executing_to_success(self):
        assert TaskStatus.is_valid_transition(TaskStatus.EXECUTING, TaskStatus.SUCCESS)

    def test_repairing_to_executing(self):
        assert TaskStatus.is_valid_transition(TaskStatus.REPAIRING, TaskStatus.EXECUTING)

    def test_repairing_to_success(self):
        assert TaskStatus.is_valid_transition(TaskStatus.REPAIRING, TaskStatus.SUCCESS)

    def test_repairing_to_failed(self):
        assert TaskStatus.is_valid_transition(TaskStatus.REPAIRING, TaskStatus.FAILED)

    def test_success_is_terminal(self):
        assert TaskStatus.TRANSITIONS[TaskStatus.SUCCESS] == set()

    def test_failed_is_terminal(self):
        assert TaskStatus.TRANSITIONS[TaskStatus.FAILED] == set()

    def test_invalid_from_status(self):
        assert not TaskStatus.is_valid_transition("nonexistent", TaskStatus.SUCCESS)

    def test_invalid_to_status(self):
        assert not TaskStatus.is_valid_transition(TaskStatus.CREATED, "nonexistent")

    def test_repair_cycle(self):
        """EXECUTING → REPAIRING → EXECUTING cycle is valid."""
        assert TaskStatus.is_valid_transition(TaskStatus.EXECUTING, TaskStatus.REPAIRING)
        assert TaskStatus.is_valid_transition(TaskStatus.REPAIRING, TaskStatus.EXECUTING)

    def test_all_states_count(self):
        assert len(TaskStatus.ALL) == 7

    def test_terminal_set(self):
        assert TaskStatus.TERMINAL == {TaskStatus.SUCCESS, TaskStatus.FAILED}


# ── Legacy status mapping ────────────────────────────────────────────────────

class TestLegacyStatusMap:
    def test_pending_maps_to_created(self):
        assert LEGACY_STATUS_MAP["pending"] == TaskStatus.CREATED

    def test_running_maps_to_analyzing(self):
        assert LEGACY_STATUS_MAP["running"] == TaskStatus.ANALYZING

    def test_success_unchanged(self):
        assert "success" not in LEGACY_STATUS_MAP

    def test_failed_unchanged(self):
        assert "failed" not in LEGACY_STATUS_MAP


# ── Stage status mapping ─────────────────────────────────────────────────────

class TestStageStatusMap:
    def test_code_review_maps_to_analyzing(self):
        assert STAGE_STATUS_MAP["code_review"] == TaskStatus.ANALYZING

    def test_change_intelligence_maps_to_analyzing(self):
        assert STAGE_STATUS_MAP["change_intelligence"] == TaskStatus.ANALYZING

    def test_context_maps_to_analyzing(self):
        assert STAGE_STATUS_MAP["context"] == TaskStatus.ANALYZING

    def test_generator_maps_to_generating(self):
        assert STAGE_STATUS_MAP["generator"] == TaskStatus.GENERATING

    def test_validate_repair_maps_to_executing(self):
        assert STAGE_STATUS_MAP["validate_repair"] == TaskStatus.EXECUTING

    def test_quality_scorer_maps_to_executing(self):
        assert STAGE_STATUS_MAP["quality_scorer"] == TaskStatus.EXECUTING

    def test_mr_feedback_maps_to_success(self):
        assert STAGE_STATUS_MAP["mr_feedback"] == TaskStatus.SUCCESS

    def test_all_stages_covered(self):
        expected_stages = {
            "code_review", "change_intelligence", "context",
            "generator", "validate_repair", "quality_scorer", "mr_feedback",
        }
        assert set(STAGE_STATUS_MAP.keys()) == expected_stages


# ── PipelineContext integration ──────────────────────────────────────────────

class TestPipelineContextStatusCallback:
    def test_pipeline_context_has_status_callback_field(self):
        from app.services.agents.test_manager import PipelineContext
        ctx = PipelineContext()
        assert ctx.status_callback is None

    def test_pipeline_context_accepts_callback(self):
        from app.services.agents.test_manager import PipelineContext
        cb = AsyncMock()
        ctx = PipelineContext(status_callback=cb)
        assert ctx.status_callback is cb


# ── TestManagerAgent._emit_status ────────────────────────────────────────────

class TestEmitStatus:
    def _make_manager(self):
        from app.services.agents.test_manager import TestManagerAgent
        return TestManagerAgent()

    def test_emit_status_calls_callback(self):
        mgr = self._make_manager()
        cb = AsyncMock()
        from app.services.agents.test_manager import PipelineContext
        ctx = PipelineContext(status_callback=cb)

        loop = asyncio.new_event_loop()
        loop.run_until_complete(mgr._emit_status(ctx, "code_review"))
        loop.close()

        cb.assert_called_once_with(TaskStatus.ANALYZING)

    def test_emit_status_no_callback(self):
        mgr = self._make_manager()
        from app.services.agents.test_manager import PipelineContext
        ctx = PipelineContext()

        loop = asyncio.new_event_loop()
        loop.run_until_complete(mgr._emit_status(ctx, "code_review"))
        loop.close()

    def test_emit_status_callback_error_caught(self):
        mgr = self._make_manager()
        cb = AsyncMock(side_effect=RuntimeError("db down"))
        from app.services.agents.test_manager import PipelineContext
        ctx = PipelineContext(status_callback=cb)

        loop = asyncio.new_event_loop()
        loop.run_until_complete(mgr._emit_status(ctx, "generator"))
        loop.close()

    def test_emit_status_unknown_stage_ignored(self):
        mgr = self._make_manager()
        cb = AsyncMock()
        from app.services.agents.test_manager import PipelineContext
        ctx = PipelineContext(status_callback=cb)

        loop = asyncio.new_event_loop()
        loop.run_until_complete(mgr._emit_status(ctx, "unknown_stage"))
        loop.close()

        cb.assert_not_called()


# ── _build_pipeline_nodes with new statuses ──────────────────────────────────

def _load_tasks_endpoint():
    """Load tasks endpoint helpers without requiring FastAPI/SQLAlchemy runtime deps."""
    import types
    for mod_name in ["fastapi", "fastapi.responses", "sqlalchemy.ext.asyncio",
                     "sqlalchemy", "app.core.database"]:
        if mod_name not in sys.modules:
            sys.modules[mod_name] = MagicMock()
    # Also ensure app.api package stubs exist
    for pkg in ["app.api", "app.api.v1", "app.api.v1.endpoints"]:
        if pkg not in sys.modules:
            m = types.ModuleType(pkg)
            sys.modules[pkg] = m

    spec = importlib.util.spec_from_file_location(
        "tasks_endpoint",
        Path(__file__).resolve().parents[2] / "app" / "api" / "v1" / "endpoints" / "tasks.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_build_pipeline_nodes():
    return _load_tasks_endpoint()._build_pipeline_nodes


class TestBuildPipelineNodesNewStatuses:
    def _make_task(self, status: str, output_data: dict = None):
        task = MagicMock()
        task.status = status
        task.output_data = output_data or {}
        return task

    def test_created_all_pending(self):
        fn = _load_build_pipeline_nodes()
        task = self._make_task("created")
        nodes = fn(task)
        assert nodes["code_review"]["status"] == "pending"
        assert nodes["test_generation"]["status"] == "pending"

    def test_analyzing_shows_pending_nodes(self):
        fn = _load_build_pipeline_nodes()
        task = self._make_task("analyzing")
        nodes = fn(task)
        assert nodes["code_review"]["status"] == "pending"

    def test_generating_shows_running_tg(self):
        fn = _load_build_pipeline_nodes()
        task = self._make_task("generating")
        nodes = fn(task)
        assert nodes["test_generation"]["status"] == "running"

    def test_executing_shows_running_tg(self):
        fn = _load_build_pipeline_nodes()
        task = self._make_task("executing")
        nodes = fn(task)
        assert nodes["test_generation"]["status"] == "running"

    def test_repairing_shows_running_tg(self):
        fn = _load_build_pipeline_nodes()
        task = self._make_task("repairing")
        nodes = fn(task)
        assert nodes["test_generation"]["status"] == "running"

    def test_success_shows_skipped_for_missing(self):
        fn = _load_build_pipeline_nodes()
        task = self._make_task("success")
        nodes = fn(task)
        assert nodes["code_review"]["status"] == "skipped"
        assert nodes["test_generation"]["status"] == "skipped"

    def test_success_no_diff_marks_test_generation_skipped_with_reason(self):
        fn = _load_build_pipeline_nodes()
        task = self._make_task("success", {"summary": "No diff to review"})
        nodes = fn(task)
        assert nodes["test_generation"]["status"] == "skipped"
        assert nodes["test_generation"]["reason"] == "No diff to review"

    def test_quality_score_includes_risk_level(self):
        fn = _load_build_pipeline_nodes()
        task = self._make_task("success", {
            "quality_score": {"total_score": 8.0, "dimensions": {}, "risk_level": "low"},
        })
        nodes = fn(task)
        assert nodes["quality_score"]["risk_level"] == "low"

    def test_legacy_pending_still_works(self):
        """Backward compat: legacy 'pending' status still treated as active."""
        fn = _load_build_pipeline_nodes()
        task = self._make_task("pending")
        nodes = fn(task)
        assert nodes["code_review"]["status"] == "pending"

    def test_test_generation_failure_is_not_rendered_as_success(self):
        fn = _load_build_pipeline_nodes()
        task = self._make_task("failed", {
            "test_generation": {
                "status": "failed",
                "reason": "no files generated",
                "framework": "unknown",
                "generated_files": [],
                "worktree_run": {"status": "failed", "reason": "no files generated"},
                "repair_history": [],
            },
            "quality_score": {
                "status": "blocked",
                "reason": "Blocked because generator failed: no files generated",
            },
        })
        nodes = fn(task)
        assert nodes["test_generation"]["status"] == "failed"
        assert nodes["test_generation"]["reason"] == "no files generated"
        assert nodes["quality_score"]["status"] == "blocked"

    def test_legacy_no_files_generated_skip_is_rendered_as_failed(self):
        fn = _load_build_pipeline_nodes()
        task = self._make_task("success", {
            "test_generation": {
                "framework": "unknown",
                "generated_files": [],
                "worktree_run": {"status": "skipped", "reason": "no files generated"},
                "repair_history": [],
            },
        })
        nodes = fn(task)
        assert nodes["test_generation"]["status"] == "failed"
        assert nodes["test_generation"]["reason"] == "no files generated"
        assert nodes["quality_score"]["status"] == "blocked"
        assert nodes["auto_merge"]["status"] == "blocked"

    def test_code_review_failed_status_is_preserved(self):
        fn = _load_build_pipeline_nodes()
        task = self._make_task("failed", {
            "code_review": {
                "status": "failed",
                "error": "llm timeout",
                "findings": [],
            },
        })
        nodes = fn(task)
        assert nodes["code_review"]["status"] == "failed"
        assert nodes["code_review"]["error"] == "llm timeout"


class TestTaskStageArtifactsEvents:
    def _make_task(self, status: str = "success", output_data: dict = None):
        task = MagicMock()
        task.status = status
        task.output_data = output_data or {}
        task.task_id = "task-1"
        return task

    def test_stage_results_prefer_workflow_records(self):
        mod = _load_tasks_endpoint()
        task = self._make_task(output_data={
            "stage_results": [
                {"stage": "generator", "status": "failed", "reason": "no files"},
                "bad-record",
            ],
        })

        results = mod._task_stage_results(task)

        assert results == [
            {"stage": "generator", "status": "failed", "reason": "no files"},
        ]

    def test_stage_results_fallback_from_pipeline_nodes(self):
        mod = _load_tasks_endpoint()
        task = self._make_task(status="failed", output_data={
            "test_generation": {
                "status": "failed",
                "reason": "no files generated",
                "generated_files": [],
                "worktree_run": {"status": "failed"},
            },
        })

        results = mod._task_stage_results(task)
        generator = next(item for item in results if item["stage"] == "test_generation")
        quality = next(item for item in results if item["stage"] == "quality_score")

        assert generator["status"] == "failed"
        assert generator["reason"] == "no files generated"
        assert quality["status"] == "blocked"
        assert quality["blocked_by"] == "test_generation"

    def test_artifacts_include_stage_artifacts_and_generated_tests(self):
        mod = _load_tasks_endpoint()
        task = self._make_task(output_data={
            "stage_results": [
                {
                    "stage": "generator",
                    "status": "success",
                    "artifacts": [{"type": "summary", "content": {"files": 1}}],
                },
            ],
            "test_generation": {
                "generated_files": [
                    {"path": "tests/test_demo.py", "content": "def test_demo(): pass"},
                    "tests/test_legacy.py",
                ],
            },
        })

        artifacts = mod._task_artifacts(task)

        assert artifacts[0]["stage"] == "generator"
        assert artifacts[0]["type"] == "summary"
        assert artifacts[1]["type"] == "generated_test"
        assert artifacts[1]["path"] == "tests/test_demo.py"
        assert artifacts[2]["path"] == "tests/test_legacy.py"

    def test_events_prefer_workflow_events(self):
        mod = _load_tasks_endpoint()
        task = self._make_task(output_data={
            "events": [
                {"event": "stage_started", "stage": "generator"},
                "bad-record",
            ],
        })

        assert mod._task_events(task) == [
            {"event": "stage_started", "stage": "generator"},
        ]

    def test_events_fallback_from_stage_results(self):
        mod = _load_tasks_endpoint()
        task = self._make_task(output_data={
            "stage_results": [
                {"stage": "generator", "status": "failed", "reason": "no files"},
            ],
        })

        assert mod._task_events(task) == [
            {
                "event": "stage_status",
                "stage": "generator",
                "status": "failed",
                "reason": "no files",
            },
        ]


class TestManagerPipelineTerminalBehavior:
    def test_failed_stage_blocks_remaining_nodes(self):
        from app.services.agents.test_manager import (
            PipelineContext,
            StageResult,
            TestManagerAgent,
        )

        mgr = TestManagerAgent()
        calls = []

        async def fake_persist(ctx, key, val):
            ctx.output_data[key] = val

        async def ok_stage(ctx):
            calls.append("code_review")
            await fake_persist(ctx, "code_review", {"score": 100, "findings": []})
            return StageResult(status="success")

        async def failed_generator(ctx):
            calls.append("generator")
            await fake_persist(ctx, "test_generation", {
                "status": "failed",
                "reason": "no files generated",
            })
            return StageResult(status="failed", output={"reason": "no files generated"})

        async def should_not_run(ctx):
            calls.append("quality_scorer")
            return StageResult(status="success")

        mgr._persist = fake_persist
        mgr._stages = [
            ("code_review", ok_stage),
            ("generator", failed_generator),
            ("quality_scorer", should_not_run),
            ("mr_feedback", should_not_run),
        ]

        cb = AsyncMock()
        ctx = PipelineContext(task_id="task-1", status_callback=cb)
        result = asyncio.run(mgr.run(ctx))

        assert calls == ["code_review", "generator"]
        assert result["output_data"]["pipeline_status"]["status"] == "failed"
        assert result["output_data"]["pipeline_status"]["failed_stage"] == "generator"
        assert result["output_data"]["quality_score"]["status"] == "blocked"
        assert result["output_data"]["auto_merge"]["status"] == "blocked"
        cb.assert_any_call(TaskStatus.FAILED)
