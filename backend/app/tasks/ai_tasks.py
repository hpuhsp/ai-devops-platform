"""
Celery tasks for AI processing pipeline.
Each webhook event maps to one or more tasks here.
"""
import asyncio
import time
from datetime import datetime, timezone

from .celery_app import celery_app
from app.core.config import settings
import structlog

logger = structlog.get_logger()


def run_async(coro):
    """Run async coroutine in sync Celery context."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(bind=True, name="ai_tasks.process_push_event", max_retries=2)
def process_push_event(self, repo_id: int, event_data: dict):
    """Handle push event: run code review on the commit diff."""
    from app.core.database import AsyncSessionLocal
    from app.models import AITask, AIModel, Repository
    from app.services.ai.engine import build_engine_from_db_model, AIEngine
    from app.services.skills.registry import skill_registry
    from app.services.skills.base import SkillContext
    from app.services.git.agent import GitAgent
    from app.services.notify.feishu import build_notify_provider
    from app.services.notify.base import NotifyMessage
    from sqlalchemy import select, update

    task_id = self.request.id
    start_time = time.time()

    async def _run():
        async with AsyncSessionLocal() as db:
            # Update task status to running
            await db.execute(
                update(AITask)
                .where(AITask.task_id == task_id)
                .values(status="running", updated_at=datetime.now(timezone.utc))
            )
            await db.commit()

            # Load repo config
            repo = (await db.execute(select(Repository).where(Repository.id == repo_id))).scalar_one_or_none()
            if not repo:
                raise ValueError(f"Repository {repo_id} not found")

            # Load AI model
            model = None
            if repo.ai_model_id:
                model = (await db.execute(select(AIModel).where(AIModel.id == repo.ai_model_id))).scalar_one_or_none()

            engine = build_engine_from_db_model(model) if model else AIEngine()

            # Get diff
            from app.core.security import decrypt
            git_token = decrypt(repo.git_token_encrypted) if repo.git_token_encrypted else None
            git_agent = GitAgent(repo.repo_url, git_token)

            commit_sha = event_data.get("commit_sha", "")
            before_sha = event_data.get("before_sha", "")

            if before_sha and before_sha != "0" * 40:
                diff, changed_files = git_agent.get_diff(before_sha, commit_sha)
            else:
                diff, changed_files = git_agent.get_commit_diff(commit_sha)

            context = SkillContext(
                repo_id=repo_id,
                repo_url=repo.repo_url,
                platform=repo.platform,
                branch=event_data.get("branch", ""),
                commit_sha=commit_sha,
                author=event_data.get("author", ""),
                diff=diff,
                changed_files=changed_files,
            )

            # Execute code review skill
            result = await skill_registry.execute("code_review", context, engine)

            # Execute test generation if enabled
            skills_cfg = repo.skills_config or {}
            if skills_cfg.get("test_generation", {}).get("enabled", True):
                test_result = await skill_registry.execute("test_generation", context, engine)

                if test_result.success and test_result.details.get("generated_files"):
                    # Run tests in WorkTree
                    with git_agent.create_worktree(context.branch) as wt:
                        wt.write_files(test_result.details["generated_files"])
                        run_cmd = test_result.details.get("run_command", "")
                        if run_cmd:
                            run_out = wt.run_command(run_cmd)
                            test_result.details["worktree_run"] = run_out

                # Send test gen notification
                for notif in test_result.notifications:
                    await _send_notification(db, notif)

            # Send code review notification
            for notif in result.notifications:
                await _send_notification(db, notif)

            duration_ms = int((time.time() - start_time) * 1000)

            # Update task record
            await db.execute(
                update(AITask)
                .where(AITask.task_id == task_id)
                .values(
                    status="success",
                    output_data=result.details,
                    prompt_tokens=result.prompt_tokens,
                    completion_tokens=result.completion_tokens,
                    duration_ms=duration_ms,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await db.commit()

            logger.info("task.push_completed", task_id=task_id, duration_ms=duration_ms)

    async def _send_notification(db, notif_data: dict):
        from app.models import NotifyConfig
        from sqlalchemy import select as sa_select
        notify_cfg = (await db.execute(
            sa_select(NotifyConfig).where(NotifyConfig.is_default == True, NotifyConfig.enabled == True)
        )).scalar_one_or_none()

        if not notify_cfg:
            return

        try:
            provider = build_notify_provider({
                "provider": notify_cfg.provider,
                "config": notify_cfg.config,
            })
            msg = NotifyMessage(
                title=notif_data.get("type", "AI DevOps 通知"),
                content="",
                message_type=notif_data.get("type", "generic"),
                data=notif_data,
                color="green",
            )
            await provider.send(msg)
        except Exception as e:
            logger.warning("notification.failed", error=str(e))

    try:
        run_async(_run())
    except Exception as exc:
        logger.exception("task.push_failed", task_id=task_id, error=str(exc))
        run_async(_mark_failed(task_id, str(exc)))
        raise self.retry(exc=exc, countdown=30)


async def _mark_failed(task_id: str, error: str):
    from app.core.database import AsyncSessionLocal
    from app.models import AITask
    from sqlalchemy import update
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(AITask)
            .where(AITask.task_id == task_id)
            .values(status="failed", error_message=error[:2000])
        )
        await db.commit()
