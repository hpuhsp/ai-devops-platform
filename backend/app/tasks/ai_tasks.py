"""
Celery tasks for AI processing pipeline.
DB operations use synchronous SQLAlchemy (psycopg2) to avoid asyncpg
event-loop conflicts in Celery's fork-based worker model.
AI inference is the only async part, isolated in its own short-lived loop.
"""
import asyncio
import time
from datetime import datetime, timezone

from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import sessionmaker, Session

from .celery_app import celery_app
from app.core.config import settings
import structlog

logger = structlog.get_logger()

# Synchronous engine — one per worker process, no event-loop dependency
_sync_engine = create_engine(settings.DATABASE_SYNC_URL, pool_pre_ping=True)
SyncSession = sessionmaker(bind=_sync_engine)

# Whitelist of test runners we will execute in a WorkTree. Keyed by the framework
# name the LLM reports. Values are fixed argv lists run WITHOUT a shell — the
# LLM's own run_command string is intentionally ignored. Frameworks absent here
# are not executed (test files are still generated and reported).
SAFE_TEST_COMMANDS: dict[str, list[str]] = {
    "pytest": ["pytest", "-q"],
    "python": ["pytest", "-q"],
    "unittest": ["python", "-m", "pytest", "-q"],
}


def _safe_test_command(framework: str | None) -> list[str] | None:
    return SAFE_TEST_COMMANDS.get((framework or "").strip().lower())


def _run_async(coro):
    """Run a single async coroutine in a fresh, self-contained event loop."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        loop.close()
        asyncio.set_event_loop(None)


def _write_partial_output(task_id: str, key: str, value: dict):
    """Merge one skill result into output_data JSONB while the task is still running.
    Uses a short-lived psycopg2 connection to avoid sharing state with the main pool.
    Safe to call from a thread-pool executor inside an async context.
    """
    import json as _json
    import psycopg2
    dsn = settings.DATABASE_PURE_URL
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE ai_tasks "
                "SET output_data = COALESCE(output_data, '{}') || %s::jsonb, "
                "    updated_at  = NOW() "
                "WHERE task_id = %s",
                (_json.dumps({key: value}), task_id),
            )
        conn.commit()
    finally:
        conn.close()


def _mark_failed(db: Session, task_id: str, error: str):
    from app.models import AITask
    db.execute(
        update(AITask)
        .where(AITask.task_id == task_id)
        .values(status="failed", error_message=error[:2000],
                updated_at=datetime.now(timezone.utc))
    )
    db.commit()


@celery_app.task(bind=True, name="ai_tasks.process_push_event", max_retries=2)
def process_push_event(self, repo_id: int, event_data: dict):
    """Handle push event: run code review on the commit diff."""
    from app.models import AITask, AIModel, Repository

    task_id = self.request.id
    start_time = time.time()

    with SyncSession() as db:
        # Mark running
        db.execute(
            update(AITask)
            .where(AITask.task_id == task_id)
            .values(status="running", updated_at=datetime.now(timezone.utc))
        )
        db.commit()

        # Load repo + model + resolve pipeline stages via RuleEngine
        repo = db.execute(select(Repository).where(Repository.id == repo_id)).scalar_one_or_none()
        if not repo:
            _mark_failed(db, task_id, f"Repository {repo_id} not found")
            return

        model = None
        if repo.ai_model_id:
            model = db.execute(select(AIModel).where(AIModel.id == repo.ai_model_id)).scalar_one_or_none()

        from app.services.rules.engine import get_stages_sync
        branch = event_data.get("branch", "")
        enabled_stages = get_stages_sync(repo_id, branch, db)

        # Pre-load notify config synchronously — avoids asyncpg inside the async block
        from app.models import NotifyConfig
        notify_cfg_row = db.execute(
            select(NotifyConfig).where(
                NotifyConfig.is_default == True,
                NotifyConfig.enabled == True,
            )
        ).scalar_one_or_none()
        notify_cfg = (
            {"provider": notify_cfg_row.provider, "config": notify_cfg_row.config}
            if notify_cfg_row else None
        )

    try:
        # ── Async block: git + AI inference only, no DB ────────────────
        output = _run_async(_ai_pipeline(repo, model, event_data, task_id, notify_cfg, enabled_stages))
        # ──────────────────────────────────────────────────────────────

        duration_ms = int((time.time() - start_time) * 1000)
        with SyncSession() as db:
            db.execute(
                update(AITask)
                .where(AITask.task_id == task_id)
                .values(
                    status="success",
                    output_data=output.get("output_data"),
                    prompt_tokens=output.get("prompt_tokens", 0),
                    completion_tokens=output.get("completion_tokens", 0),
                    duration_ms=duration_ms,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            db.commit()
        logger.info("task.completed", task_id=task_id, duration_ms=duration_ms)

    except Exception as exc:
        logger.exception("task.failed", task_id=task_id,
                         attempt=self.request.retries, error=str(exc))
        # Only persist a terminal "failed" state once retries are exhausted, so the
        # status doesn't flicker failed -> running across transient retries.
        if self.request.retries >= self.max_retries:
            with SyncSession() as db:
                _mark_failed(db, task_id, str(exc))
            raise
        raise self.retry(exc=exc, countdown=30)


async def _ai_pipeline(repo, model, event_data: dict, task_id: str, notify_cfg: dict | None = None, enabled_stages: list | None = None) -> dict:
    """Pure async: git diff + AI skills + notifications. No DB access."""
    from app.services.ai.engine import build_engine_from_db_model, AIEngine
    from app.services.skills.registry import skill_registry
    from app.services.skills.base import SkillContext
    from app.services.git.agent import GitAgent
    from app.core.security import decrypt

    engine = build_engine_from_db_model(model) if model else AIEngine()

    git_token = decrypt(repo.git_token_encrypted) if repo.git_token_encrypted else None
    git_agent = GitAgent(repo.repo_url, git_token)

    commit_sha = event_data.get("commit_sha", "")
    before_sha = event_data.get("before_sha", "")

    # Fetch/clone repo
    git_agent.ensure_repo()

    all_zeros = "0" * 40
    if before_sha and before_sha != all_zeros and commit_sha and commit_sha != all_zeros:
        diff, changed_files = git_agent.get_diff(before_sha, commit_sha)
    elif commit_sha and commit_sha != all_zeros:
        diff, changed_files = git_agent.get_commit_diff(commit_sha)
    else:
        # No valid SHA (e.g. test webhook) — diff HEAD against parent
        try:
            diff, changed_files = git_agent.get_latest_diff()
        except Exception:
            diff, changed_files = "", []

    if not diff.strip():
        logger.info("task.no_diff", task_id=task_id)
        return {"output_data": {"summary": "No diff to review"}, "prompt_tokens": 0, "completion_tokens": 0}

    context = SkillContext(
        repo_id=repo.id,
        repo_url=repo.repo_url,
        platform=repo.platform,
        branch=event_data.get("branch", ""),
        commit_sha=commit_sha,
        author=event_data.get("author", ""),
        diff=diff,
        changed_files=changed_files,
    )

    stages = set(enabled_stages or ["code_review"])
    skills_config = repo.skills_config or {}
    pt = ct = 0
    output_data: dict = {}
    loop = asyncio.get_event_loop()

    async def _persist(key: str, val: dict):
        output_data[key] = val
        await loop.run_in_executor(None, _write_partial_output, task_id, key, val)

    # ── Code review ───────────────────────────────────────────────────────
    if "code_review" not in stages:
        logger.info("stage.skipped", stage="code_review")
        await _persist("code_review", {"status": "skipped"})
    else:
        cr = await skill_registry.execute("code_review", context, engine)
        pt += cr.prompt_tokens; ct += cr.completion_tokens
        await _persist("code_review", cr.details)
        for notif in cr.notifications:
            await _send_notification(notif, notify_cfg)

    # ── Test generation ───────────────────────────────────────────────────
    if "test_generation" not in stages:
        logger.info("stage.skipped", stage="test_generation")
        await _persist("test_generation", {"status": "skipped"})
    else:
        test_cfg = skills_config.get("test_generation", {})
        tg = await skill_registry.execute(
            "test_generation", context, engine,
            skill_config={k: v for k, v in test_cfg.items() if k != "enabled"},
        )
        pt += tg.prompt_tokens; ct += tg.completion_tokens
        tg_details = dict(tg.details)
        files = tg_details.get("generated_files", [])
        # SECURITY: never execute the LLM-provided run_command. Derive a fixed,
        # whitelisted argv from the detected framework instead (avoids shell injection
        # via a prompt-injected diff). Frameworks we can't safely run are skipped.
        cmd = _safe_test_command(tg_details.get("framework"))

        if files and cmd:
            wr = await _run_worktree_tests(git_agent, context.branch or commit_sha, files, cmd)
        elif files and not cmd:
            wr = {"status": "skipped",
                  "reason": f"framework '{tg_details.get('framework')}' not runnable in sandbox"}
        else:
            wr = {"status": "skipped", "reason": "no files generated"}

        tg_details["worktree_run"] = wr
        await _persist("test_generation", tg_details)
        for notif in tg.notifications:
            await _send_notification(
                {**notif, "data": {**notif.get("data", {}), "worktree_run": wr}},
                notify_cfg,
            )

    return {"output_data": output_data, "prompt_tokens": pt, "completion_tokens": ct}


async def _run_worktree_tests(
    git_agent,
    branch_or_sha: str,
    generated_files: list[dict],
    run_command: list[str],
    timeout: int = 60,
) -> dict:
    """
    Create an isolated WorkTree, write AI-generated test files, run a whitelisted
    test command (argv list, no shell), return results.
    WorkTree is always cleaned up, even on error.
    """
    import asyncio
    cmd_display = " ".join(run_command)
    worktree = None
    try:
        worktree = git_agent.create_worktree(branch_or_sha)
        # conftest.py makes the repo root importable so `from main import x` works
        conftest = [{
            "path": "conftest.py",
            "content": (
                "import sys, os\n"
                "sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))\n"
            ),
        }]
        worktree.write_files(conftest + generated_files)

        # subprocess.run is blocking — offload to thread so event loop stays live
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: worktree.run_command(run_command, timeout=timeout)
        )
        logger.info(
            "worktree.pytest_done",
            exit_code=result["exit_code"],
            success=result["success"],
        )
        return {
            "status": "passed" if result["success"] else "failed",
            "exit_code": result["exit_code"],
            "stdout": result["stdout"],
            "stderr": result["stderr"],
            "run_command": cmd_display,
        }
    except Exception as exc:
        logger.warning("worktree.pytest_error", error=str(exc))
        return {"status": "error", "error": str(exc), "run_command": cmd_display}
    finally:
        if worktree:
            try:
                worktree.cleanup()
            except Exception:
                pass


def _notification_color(notif_data: dict) -> str:
    """Pick a card color reflecting the actual outcome (not always green)."""
    ntype = notif_data.get("type")
    data = notif_data.get("data", {}) or {}
    if ntype == "code_review_result":
        return "red" if data.get("blocked") else "green"
    if ntype == "test_generation_result":
        status = (data.get("worktree_run") or {}).get("status")
        if status in ("failed", "error"):
            return "red"
        if status not in ("passed", None):
            return "yellow"
    return "green"


async def _send_notification(notif_data: dict, notify_cfg: dict | None):
    """Send notification. notify_cfg is pre-loaded synchronously by the Celery task."""
    if not notify_cfg:
        return
    from app.services.notify.feishu import build_notify_provider
    from app.services.notify.base import NotifyMessage
    try:
        provider = build_notify_provider(notify_cfg)
        msg = NotifyMessage(
            title=notif_data.get("type", "AI DevOps 通知"),
            content="",
            message_type=notif_data.get("type", "generic"),
            data=notif_data,
            color=_notification_color(notif_data),
        )
        await provider.send(msg)
    except Exception as e:
        logger.warning("notification.failed", error=str(e))
