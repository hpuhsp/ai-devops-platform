"""
Test Manager Agent — orchestrates the multi-agent test generation pipeline.
Replaces procedural if/else orchestration with a declarative stage-based state machine.
Each stage is self-contained: has a run function, can be skipped/gated, and records execution.
"""
import asyncio
import importlib.util
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

try:
    import structlog
except ModuleNotFoundError:
    import logging

    class _KeywordLogger:
        def __init__(self, name: str):
            self._logger = logging.getLogger(name)

        def debug(self, event: str, **kwargs):
            self._logger.debug("%s %s", event, kwargs)

        def info(self, event: str, **kwargs):
            self._logger.info("%s %s", event, kwargs)

        def warning(self, event: str, **kwargs):
            self._logger.warning("%s %s", event, kwargs)

        def exception(self, event: str, **kwargs):
            self._logger.exception("%s %s", event, kwargs)

    class _StructlogFallback:
        @staticmethod
        def get_logger():
            return _KeywordLogger(__name__)

    structlog = _StructlogFallback()

from app.services.unit_test_engine.schemas import StageResult

logger = structlog.get_logger()


try:
    from app.models.task_status import TaskStatus, STAGE_STATUS_MAP
except ModuleNotFoundError:
    _task_status_path = Path(__file__).resolve().parents[2] / "models" / "task_status.py"
    _task_status_spec = importlib.util.spec_from_file_location(
        "_unit_test_engine_task_status",
        _task_status_path,
    )
    _task_status_mod = importlib.util.module_from_spec(_task_status_spec)
    _task_status_spec.loader.exec_module(_task_status_mod)
    TaskStatus = _task_status_mod.TaskStatus
    STAGE_STATUS_MAP = _task_status_mod.STAGE_STATUS_MAP


def _setting(name: str, default: Any) -> Any:
    try:
        from app.core.config import settings

        return getattr(settings, name, default)
    except ModuleNotFoundError:
        return default


@dataclass
class PipelineContext:
    """Shared mutable state passed through all stages."""
    # Inputs
    repo: Any = None
    engine: Any = None
    git_agent: Any = None
    git_token: str = None
    skill_context: Any = None
    event_data: dict = field(default_factory=dict)
    task_id: str = ""
    enabled_stages: set = field(default_factory=set)
    skills_config: dict = field(default_factory=dict)
    notify_cfg: dict | None = None

    # Accumulated state
    output_data: dict = field(default_factory=dict)
    prompt_tokens: int = 0
    completion_tokens: int = 0

    # Per-stage agent resolution (always available — system agents serve as defaults)
    agent_resolver: Any = None

    # Status callback for fine-grained task status updates (Sprint D)
    status_callback: Optional[Callable] = None
    ports: Any = None

    # Inter-stage data (downstream stages read from here)
    change_intel_data: dict = field(default_factory=dict)
    context_agent_output: dict = field(default_factory=dict)
    generated_files: list = field(default_factory=list)
    test_framework: str = ""
    worktree_result: dict = field(default_factory=dict)
    repair_history: list = field(default_factory=list)
    quality_score: dict | None = None


class UnitTestWorkflow:
    """
    State-machine pipeline orchestrator.
    Drives Agent chain: code_review → change_intelligence → context → generator
    → validator/repair → quality_scorer → mr_feedback
    """

    # Pipeline stage_name → Agent stage_type
    _STAGE_TO_TYPE = {
        "code_review": "code_review",
        "change_intelligence": "change_intelligence",
        "generator": "generator",
        "validate_repair": "validate_repair",
        "quality_scorer": "quality_scorer",
    }

    _STAGE_OUTPUT_KEYS = {
        "code_review": "code_review",
        "change_intelligence": "change_intelligence",
        "context": "context",
        "generator": "test_generation",
        "validate_repair": "test_generation",
        "quality_scorer": "quality_score",
        "mr_feedback": "auto_merge",
    }

    _TERMINAL_FAILURES = {"failed", "blocked"}

    def __init__(self):
        self._stages = [
            ("code_review", self._stage_code_review),
            ("change_intelligence", self._stage_change_intelligence),
            ("context", self._stage_context),
            ("generator", self._stage_generator),
            ("validate_repair", self._stage_validate_repair),
            ("quality_scorer", self._stage_quality_scorer),
            ("mr_feedback", self._stage_mr_feedback),
        ]

    async def run(self, ctx: PipelineContext) -> dict:
        """Execute pipeline stages sequentially. Returns final output dict."""
        self._loop = asyncio.get_event_loop()
        if ctx.ports is None:
            from app.services.unit_test_engine.platform_ports import PlatformWorkflowPorts

            ctx.ports = PlatformWorkflowPorts(self._loop)

        for stage_name, stage_fn in self._stages:
            try:
                await self._emit_status(ctx, stage_name)
                result = await stage_fn(ctx)
                ctx.prompt_tokens += result.prompt_tokens
                ctx.completion_tokens += result.completion_tokens
                await self._record_stage_result(ctx, stage_name, result)
                logger.info("pipeline.stage_done", stage=stage_name, status=result.status)

                # Gate: if change_intelligence says no test needed, skip remaining
                if stage_name == "change_intelligence" and result.status == "gated":
                    await self._persist(ctx, "pipeline_status", {
                        "status": "success",
                        "terminal_stage": stage_name,
                        "reason": result.output.get("reason") or result.output.get("skip_reason"),
                    })
                    break

                if result.status in self._TERMINAL_FAILURES:
                    reason = self._stage_reason(result, stage_name)
                    await self._mark_pipeline_failed(ctx, stage_name, result.status, reason)
                    await self._block_remaining(ctx, stage_name, result.status, reason)
                    break

            except Exception as exc:
                logger.exception("pipeline.stage_error", stage=stage_name, error=str(exc))
                await self._persist(ctx, stage_name, {"status": "failed", "error": str(exc)})
                await self._mark_pipeline_failed(ctx, stage_name, "failed", str(exc))
                await self._block_remaining(ctx, stage_name, "failed", str(exc))
                break

        if "pipeline_status" not in ctx.output_data:
            await self._persist(ctx, "pipeline_status", {"status": "success"})

        # Record per-stage model usage
        if ctx.agent_resolver:
            ctx.output_data["model_usage"] = ctx.agent_resolver.get_model_usage()

        return {
            "output_data": ctx.output_data,
            "prompt_tokens": ctx.prompt_tokens,
            "completion_tokens": ctx.completion_tokens,
        }

    # ── Helpers ──────────────────────────────────────────────────────────────

    async def _persist(self, ctx: PipelineContext, key: str, val: dict):
        ctx.output_data[key] = val
        await ctx.ports.persist(ctx, key, val)

    def _stage_reason(self, result: StageResult, stage_name: str) -> str:
        return (
            result.reason
            or result.output.get("reason")
            or result.output.get("error")
            or result.output.get("message")
            or f"{stage_name} {result.status}"
        )

    async def _record_stage_result(self, ctx: PipelineContext, stage_name: str, result: StageResult):
        """Collect normalized stage status, metrics, artifacts, and events."""
        normalized_status = "skipped" if result.status == "gated" else result.status
        metrics = dict(result.metrics or {})
        metrics.setdefault("prompt_tokens", result.prompt_tokens)
        metrics.setdefault("completion_tokens", result.completion_tokens)
        metrics.setdefault("duration_ms", result.duration_ms)

        stage_record = {
            "stage": stage_name,
            "status": normalized_status,
            "reason": result.reason or result.output.get("reason") or result.output.get("error"),
            "metrics": metrics,
            "artifacts": result.artifacts,
        }

        ctx.output_data.setdefault("stage_results", [])
        ctx.output_data["stage_results"].append(stage_record)

        if result.events:
            ctx.output_data.setdefault("events", [])
            ctx.output_data["events"].extend(result.events)

        await self._persist(ctx, "stage_results", ctx.output_data["stage_results"])
        if result.events:
            await self._persist(ctx, "events", ctx.output_data["events"])

    async def _mark_pipeline_failed(
        self,
        ctx: PipelineContext,
        stage_name: str,
        status: str,
        reason: str,
    ):
        await self._persist(ctx, "pipeline_status", {
            "status": status,
            "failed_stage": stage_name,
            "reason": reason,
        })
        if ctx.status_callback:
            try:
                await ctx.status_callback(TaskStatus.FAILED)
            except Exception as exc:
                logger.debug("pipeline.failed_status_callback_failed", stage=stage_name, error=str(exc))

    async def _block_remaining(
        self,
        ctx: PipelineContext,
        stage_name: str,
        status: str,
        reason: str,
    ):
        stage_names = [name for name, _ in self._stages]
        try:
            start = stage_names.index(stage_name) + 1
        except ValueError:
            start = len(stage_names)

        block_reason = f"Blocked because {stage_name} {status}: {reason}"
        for downstream in stage_names[start:]:
            key = self._STAGE_OUTPUT_KEYS.get(downstream)
            if not key:
                continue
            blocked_output = {
                "status": "blocked",
                "blocked_by": stage_name,
                "reason": block_reason,
            }
            if key not in ctx.output_data:
                await self._persist(ctx, key, blocked_output)
            await self._record_stage_result(ctx, downstream, StageResult(
                status="blocked",
                reason=block_reason,
                output=blocked_output,
            ))

    async def _record(self, ctx: PipelineContext, agent_type: str, status: str,
                      input_data=None, output_data=None,
                      pt=0, ct=0, duration_ms=0, round_number=1):
        await ctx.ports.record_execution(
            ctx,
            agent_type,
            status,
            input_data=input_data,
            output_data=output_data,
            prompt_tokens=pt,
            completion_tokens=ct,
            duration_ms=duration_ms,
            round_number=round_number,
        )

    async def _notify(self, ctx: PipelineContext, notif_data: dict, stage_type: str):
        """Workflow notification outlet. Stages produce data; policies own routing."""
        await ctx.ports.notify(ctx, notif_data, stage_type)

    def _engine_for(self, ctx: PipelineContext, stage_name: str):
        """Resolve engine for a pipeline stage via AgentResolver."""
        if ctx.agent_resolver:
            stage_type = self._STAGE_TO_TYPE.get(stage_name)
            if stage_type:
                return ctx.agent_resolver.get_engine(stage_type)
        # Should never reach here — agent_resolver is always built
        return ctx.engine

    def _skill_config_for(self, ctx: PipelineContext, stage_name: str) -> dict:
        """Return merged skill config for a stage (agent config overrides repo config)."""
        if ctx.agent_resolver:
            stage_type = self._STAGE_TO_TYPE.get(stage_name)
            if stage_type:
                return ctx.agent_resolver.get_skill_config(stage_type)
        return ctx.skills_config.get(stage_name, {})

    def _model_config_for(self, ctx: PipelineContext, stage_name: str) -> dict:
        """Return model config overrides for a stage from agent binding."""
        if ctx.agent_resolver:
            stage_type = self._STAGE_TO_TYPE.get(stage_name)
            if stage_type:
                return ctx.agent_resolver.get_model_config(stage_type)
        return {}

    def _policy_config_for(self, ctx: PipelineContext, stage_name: str) -> dict:
        """Return policy config for a stage from agent binding."""
        if ctx.agent_resolver:
            stage_type = self._STAGE_TO_TYPE.get(stage_name)
            if stage_type:
                return ctx.agent_resolver.get_policy_config(stage_type)
        return {}

    async def _skill_name_for(self, ctx: PipelineContext, stage_type: str, default_name: str) -> str:
        """Resolve skill name for a stage from AgentResolver, with hardcoded fallback."""
        if ctx.agent_resolver:
            name = ctx.agent_resolver.get_skill_name(stage_type)
            if name:
                return name
        return default_name

    def _skill_type_for(self, ctx: PipelineContext, stage_type: str) -> str:
        """Resolve skill runtime type for a stage."""
        if ctx.agent_resolver and hasattr(ctx.agent_resolver, "get_skill_type"):
            return ctx.agent_resolver.get_skill_type(stage_type)
        return "builtin"

    async def _emit_status(self, ctx: PipelineContext, stage_name: str):
        """Emit task status update via callback if available."""
        new_status = STAGE_STATUS_MAP.get(stage_name)
        if new_status and ctx.status_callback:
            try:
                await ctx.status_callback(new_status)
            except Exception as exc:
                logger.debug("pipeline.status_callback_failed", stage=stage_name, error=str(exc))

    # ── Stage Implementations ────────────────────────────────────────────────

    async def _stage_code_review(self, ctx: PipelineContext) -> StageResult:
        if "code_review" not in ctx.enabled_stages:
            await self._persist(ctx, "code_review", {"status": "skipped"})
            return StageResult(status="skipped")

        from app.services.skills.runtime import skill_runtime
        engine = self._engine_for(ctx, "code_review")
        skill_cfg = self._skill_config_for(ctx, "code_review")
        skill_name = await self._skill_name_for(ctx, "code_review", "code_review")
        cr = await skill_runtime.execute(
            skill_name,
            ctx.skill_context,
            engine,
            skill_config=skill_cfg,
            skill_type=self._skill_type_for(ctx, "code_review"),
        )
        status = "success"
        cr_details = dict(cr.details)
        if not cr.success:
            status = "failed"
            cr_details.setdefault("status", "failed")
            cr_details.setdefault("reason", cr_details.get("error", "code review failed"))
        elif cr_details.get("blocked"):
            status = "blocked"
            cr_details.setdefault("status", "blocked")
            cr_details.setdefault("reason", "code review policy blocked this change")

        await self._persist(ctx, "code_review", cr_details)

        for notif in cr.notifications:
            await self._notify(ctx, notif, "code_review")

        return StageResult(
            status=status,
            output=cr_details,
            prompt_tokens=cr.prompt_tokens,
            completion_tokens=cr.completion_tokens,
        )

    async def _stage_change_intelligence(self, ctx: PipelineContext) -> StageResult:
        if "test_generation" not in ctx.enabled_stages:
            await self._persist(ctx, "test_generation", {"status": "skipped"})
            return StageResult(status="gated")

        from app.services.skills.runtime import skill_runtime
        start = time.time()
        engine = self._engine_for(ctx, "change_intelligence")
        ci_skill_cfg = self._skill_config_for(ctx, "change_intelligence")
        skill_name = await self._skill_name_for(ctx, "change_intelligence", "change_intelligence")
        ci_result = await skill_runtime.execute(
            skill_name,
            ctx.skill_context,
            engine,
            skill_config=ci_skill_cfg,
            skill_type=self._skill_type_for(ctx, "change_intelligence"),
        )
        ms = int((time.time() - start) * 1000)

        ci_data = ci_result.details
        if not ci_result.success:
            failed_data = dict(ci_data)
            failed_data.setdefault("status", "failed")
            failed_data.setdefault("reason", failed_data.get("error", "change intelligence failed"))
            await self._persist(ctx, "change_intelligence", failed_data)
            await self._record(ctx, "change_intelligence", "failed",
                               {"changed_files": ctx.skill_context.changed_files[:20]},
                               failed_data, ci_result.prompt_tokens, ci_result.completion_tokens, ms)
            return StageResult(status="failed", output=failed_data,
                               prompt_tokens=ci_result.prompt_tokens,
                               completion_tokens=ci_result.completion_tokens, duration_ms=ms)

        ctx.change_intel_data = ci_data
        await self._persist(ctx, "change_intelligence", ci_data)
        await self._record(ctx, "change_intelligence",
                           "success" if ci_result.success else "failed",
                           {"changed_files": ctx.skill_context.changed_files[:20]},
                           ci_data, ci_result.prompt_tokens, ci_result.completion_tokens, ms)

        # Gate: skip downstream if no test needed
        if not ci_data.get("need_test", True):
            logger.info("change_intel.skip", reason=ci_data.get("skip_reason"))
            if ctx.status_callback:
                try:
                    await ctx.status_callback(TaskStatus.SUCCESS)
                except Exception:
                    pass
            await self._persist(ctx, "test_generation", {
                "status": "skipped",
                "reason": ci_data.get("skip_reason", "Change intelligence decided no test needed"),
            })
            return StageResult(status="gated", output=ci_data,
                               prompt_tokens=ci_result.prompt_tokens,
                               completion_tokens=ci_result.completion_tokens, duration_ms=ms)

        return StageResult(status="success", output=ci_data,
                           prompt_tokens=ci_result.prompt_tokens,
                           completion_tokens=ci_result.completion_tokens, duration_ms=ms)

    async def _stage_context(self, ctx: PipelineContext) -> StageResult:
        test_cfg = ctx.skills_config.get("test_generation", {})
        codegraph_db = test_cfg.get("codegraph_db_path", "codegraph.db")
        context_output = {}
        start = time.time()

        worktree = None
        try:
            worktree = ctx.git_agent.create_worktree(
                ctx.skill_context.branch or ctx.skill_context.commit_sha
            )
            from app.services.agents.context_agent import ContextAgent
            agent = ContextAgent(str(worktree.path), codegraph_db)
            context_output = agent.build_context(ctx.change_intel_data.get("targets", []))
        except Exception as exc:
            logger.warning("context_agent.failed", error=str(exc))
            context_output = {"error": str(exc), "target_functions": []}
        finally:
            if worktree:
                try:
                    worktree.cleanup()
                except Exception:
                    pass

        ms = int((time.time() - start) * 1000)
        ctx.context_agent_output = context_output
        await self._persist(ctx, "context", context_output)
        await self._record(ctx, "context",
                           "success" if "error" not in context_output else "failed",
                           {"targets": ctx.change_intel_data.get("targets", [])},
                           context_output, 0, 0, ms)

        # Inject into skill context for Generator
        ctx.skill_context.extra["context_agent_output"] = context_output
        ctx.skill_context.extra["codegraph_db_path"] = codegraph_db

        return StageResult(status="success", output=context_output, duration_ms=ms)

    async def _stage_generator(self, ctx: PipelineContext) -> StageResult:
        from app.services.skills.runtime import skill_runtime
        test_cfg = ctx.skills_config.get("test_generation", {})
        agent_skill_cfg = self._skill_config_for(ctx, "generator")
        merged_cfg = {**{k: v for k, v in test_cfg.items() if k != "enabled"}, **agent_skill_cfg}
        engine = self._engine_for(ctx, "generator")

        start = time.time()
        skill_name = await self._skill_name_for(ctx, "generator", "test_generation")
        tg = await skill_runtime.execute(
            skill_name, ctx.skill_context, engine,
            skill_config=merged_cfg,
            skill_type=self._skill_type_for(ctx, "generator"),
        )
        ms = int((time.time() - start) * 1000)

        tg_details = dict(tg.details)
        ctx.generated_files = tg_details.get("generated_files", [])
        ctx.test_framework = tg_details.get("framework", "")
        if not tg.success or not ctx.generated_files:
            reason = tg_details.get("error") or tg_details.get("reason") or "no files generated"
            failed_output = {
                **tg_details,
                "status": "failed",
                "reason": reason,
                "framework": ctx.test_framework,
                "generated_files": ctx.generated_files,
                "worktree_run": {"status": "failed", "reason": reason},
                "repair_history": [],
            }
            await self._persist(ctx, "test_generation", failed_output)

        await self._record(ctx, "generator",
                           "success" if tg.success and ctx.generated_files else "failed",
                           None, {"framework": ctx.test_framework, "files_count": len(ctx.generated_files)},
                           tg.prompt_tokens, tg.completion_tokens, ms)

        status = "success" if tg.success and ctx.generated_files else "failed"
        output = tg_details if status == "success" else failed_output
        return StageResult(status=status, output=output,
                           prompt_tokens=tg.prompt_tokens,
                           completion_tokens=tg.completion_tokens, duration_ms=ms)

    async def _stage_validate_repair(self, ctx: PipelineContext) -> StageResult:
        from app.tasks.ai_tasks import _safe_test_command, _validate_repair_loop

        files = ctx.generated_files
        cmd = _safe_test_command(ctx.test_framework)
        agents_cfg = ctx.skills_config.get("agents", {})
        repair_enabled = agents_cfg.get("repair_enabled", True)
        repair_engine = self._engine_for(ctx, "validate_repair")

        # Agent policy_config can override max_repair_rounds
        policy = self._policy_config_for(ctx, "validate_repair")
        max_repair_rounds = policy.get("max_retry")
        if max_repair_rounds is None:
            max_repair_rounds = agents_cfg.get("max_repair_rounds")

        if files and cmd:
            wr, repair_history = await _validate_repair_loop(
                ctx.git_agent, repair_engine,
                ctx.skill_context.branch or ctx.skill_context.commit_sha,
                files, cmd, ctx.task_id, self._loop,
                context_hint=ctx.context_agent_output.get("test_style_example", ""),
                repair_enabled=repair_enabled,
                status_callback=ctx.status_callback,
                max_rounds_override=max_repair_rounds,
            )
            ctx.repair_history = repair_history
        elif files and not cmd:
            wr = {"status": "skipped",
                  "reason": f"framework '{ctx.test_framework}' not runnable in sandbox"}
        else:
            wr = {"status": "skipped", "reason": "no files generated"}

        ctx.worktree_result = wr
        wr_status = wr.get("status")
        stage_status = "success" if wr_status == "passed" else "failed"
        output_status = "success" if stage_status == "success" else "failed"
        reason = wr.get("reason") or wr.get("error")

        # Persist full test_generation output (generator output + worktree + repair)
        tg_output = ctx.output_data.get("test_generation", {})
        if not isinstance(tg_output, dict) or tg_output.get("status") == "skipped":
            tg_output = {}
        # Merge worktree result
        generator_output = {
            "status": output_status,
            "reason": reason,
            "framework": ctx.test_framework,
            "generated_files": ctx.generated_files,
            "worktree_run": wr,
            "repair_history": ctx.repair_history,
        }
        await self._persist(ctx, "test_generation", generator_output)

        # Send notifications
        notif_data = {
            "type": "test_generation_result",
            "data": {"worktree_run": wr, "files": ctx.generated_files},
            "context": {
                "repo": ctx.skill_context.repo_url,
                "branch": ctx.skill_context.branch,
                "commit": ctx.skill_context.commit_sha[:8],
                "files_count": len(ctx.generated_files),
            },
        }
        await self._notify(ctx, notif_data, "test_generation")

        return StageResult(status=stage_status, output=wr)

    async def _stage_quality_scorer(self, ctx: PipelineContext) -> StageResult:
        if not ctx.generated_files or not _setting("TEST_QUALITY_SCORING_ENABLED", True):
            return StageResult(status="skipped")

        from app.services.agents.quality_scorer import QualityScorer
        scorer = QualityScorer()
        start = time.time()
        scoring_engine = self._engine_for(ctx, "quality_scorer")
        quality_score = await scorer.score(
            scoring_engine, ctx.generated_files,
            validation_status=ctx.worktree_result.get("status", "unknown"),
            repair_rounds=ctx.worktree_result.get("repair_rounds", 0),
        )
        ms = int((time.time() - start) * 1000)
        pt = quality_score.get("prompt_tokens", 0)
        ct = quality_score.get("completion_tokens", 0)
        ctx.quality_score = quality_score

        await self._persist(ctx, "quality_score", quality_score)
        await self._record(ctx, "quality_scorer", "success", None, quality_score, pt, ct, ms)

        # Send notification with quality_score for Feishu card
        notif_data = {
            "type": "quality_score_result",
            "data": {
                "worktree_run": ctx.worktree_result,
                "files": ctx.generated_files,
                "quality_score": quality_score,
            },
            "context": {
                "repo": ctx.skill_context.repo_url,
                "branch": ctx.skill_context.branch,
                "commit": ctx.skill_context.commit_sha[:8],
                "files_count": len(ctx.generated_files),
            },
            "quality_score": quality_score,
        }
        await self._notify(ctx, notif_data, "quality_scorer")

        return StageResult(status="success", output=quality_score,
                           prompt_tokens=pt, completion_tokens=ct, duration_ms=ms)

    async def _stage_mr_feedback(self, ctx: PipelineContext) -> StageResult:
        if not _setting("MR_COMMENT_ENABLED", False):
            return StageResult(status="skipped")
        return StageResult(status="success", output=await ctx.ports.publish_mr_feedback(ctx))


class TestManagerAgent(UnitTestWorkflow):
    """Backward-compatible alias for the extracted unit test workflow."""

    pass
