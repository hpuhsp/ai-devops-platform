"""Platform side-effect ports for the unit test workflow."""
from __future__ import annotations

from typing import Any


class PlatformWorkflowPorts:
    """Default platform integration for persistence, audit records, notifications, and MR feedback."""

    def __init__(self, loop):
        self._loop = loop

    async def persist(self, ctx: Any, key: str, value: dict):
        if not getattr(ctx, "task_id", ""):
            return
        from app.tasks.ai_tasks import _write_partial_output

        await self._loop.run_in_executor(None, _write_partial_output, ctx.task_id, key, value)

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
        if not getattr(ctx, "task_id", ""):
            return
        from app.tasks.ai_tasks import _record_agent_execution

        await self._loop.run_in_executor(
            None,
            _record_agent_execution,
            ctx.task_id,
            agent_type,
            status,
            input_data,
            output_data,
            prompt_tokens,
            completion_tokens,
            duration_ms,
            round_number,
        )

    async def notify(self, ctx: Any, notif_data: dict, stage_type: str):
        from app.tasks.ai_tasks import _send_notification

        await _send_notification(
            notif_data,
            ctx.notify_cfg,
            repo_id=ctx.skill_context.repo_id,
            branch=ctx.skill_context.branch,
            stage_type=stage_type,
        )

    async def publish_mr_feedback(self, ctx: Any) -> dict:
        mr_iid = ctx.event_data.get("mr_iid") or ctx.event_data.get("pr_number")
        ai_branch = None

        if ctx.generated_files and ctx.worktree_result.get("status") == "passed":
            commit_sha = ctx.skill_context.commit_sha or "unknown"
            short_sha = commit_sha[:8]
            ai_branch = f"ai/test/{mr_iid or short_sha}"
            push_result = await self._loop.run_in_executor(
                None,
                ctx.git_agent.push_ai_branch,
                ctx.skill_context.branch or commit_sha,
                ai_branch,
                ctx.generated_files,
            )
            if not push_result.get("success"):
                ai_branch = None

        if mr_iid and ctx.git_token:
            from app.services.notify.mr_comment import MRCommentService, build_test_report_comment

            comment_body = build_test_report_comment(
                change_intel=ctx.change_intel_data,
                test_result=ctx.output_data.get("test_generation", {}),
                repair_history=ctx.repair_history,
                ai_branch=ai_branch,
                quality_score=ctx.quality_score,
            )
            mr_svc = MRCommentService(ctx.repo.platform, ctx.repo.repo_url, ctx.git_token)
            await mr_svc.post_comment(str(mr_iid), comment_body)

        return {"ai_branch": ai_branch, "mr_iid": mr_iid}
