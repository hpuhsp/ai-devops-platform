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
# --cov=. measures coverage across the whole target repo (the worktree root),
# so the reported % reflects how much of the codebase the AI-generated tests
# actually exercise. coverage.xml is parsed afterwards to extract the number.
SAFE_TEST_COMMANDS: dict[str, list[str]] = {
    "pytest": ["pytest", "-q", "--cov=.", "--cov-report=xml:coverage.xml", "--cov-report=term"],
    "python": ["pytest", "-q", "--cov=.", "--cov-report=xml:coverage.xml", "--cov-report=term"],
    "unittest": ["python", "-m", "pytest", "-q", "--cov=.", "--cov-report=xml:coverage.xml", "--cov-report=term"],
}


COVERAGE_XML_NAME = "coverage.xml"


def _safe_test_command(framework: str | None) -> list[str] | None:
    return SAFE_TEST_COMMANDS.get((framework or "").strip().lower())


def _select_event_diff(git_agent, before_sha: str, commit_sha: str, branch: str = "") -> tuple[str, list[str]]:
    """Select the most useful diff for a webhook event.

    GitLab's Webhook Test can send the same SHA for before/after. A range diff
    for that payload is empty, so fall back to the single commit diff.
    """
    all_zeros = "0" * 40
    if commit_sha and commit_sha != all_zeros:
        if before_sha and before_sha != all_zeros and before_sha != commit_sha:
            if hasattr(git_agent, "ensure_commit"):
                git_agent.ensure_commit(commit_sha, branch)
            try:
                return git_agent.get_diff(before_sha, commit_sha)
            except Exception:
                logger.warning(
                    "git.range_diff_failed_fallback_commit",
                    before_sha=before_sha,
                    commit_sha=commit_sha,
                    branch=branch,
                )
                return git_agent.get_commit_diff(commit_sha, branch)
        return git_agent.get_commit_diff(commit_sha, branch)

    try:
        return git_agent.get_latest_diff()
    except Exception:
        return "", []


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


def _record_agent_execution(
    task_id: str, agent_type: str, status: str,
    input_data: dict = None, output_data: dict = None,
    prompt_tokens: int = 0, completion_tokens: int = 0,
    duration_ms: int = 0, round_number: int = 1,
):
    """Insert a row into agent_executions via psycopg2 (thread-safe, no asyncpg)."""
    import json as _json
    import psycopg2
    dsn = settings.DATABASE_PURE_URL
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO agent_executions "
                "(task_id, agent_type, round_number, input_data, output_data, "
                " prompt_tokens, completion_tokens, duration_ms, status) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    task_id, agent_type, round_number,
                    _json.dumps(input_data) if input_data else None,
                    _json.dumps(output_data) if output_data else None,
                    prompt_tokens, completion_tokens, duration_ms, status,
                ),
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


def _resolve_notify_config(db: Session, repo, task_id: str) -> dict | None:
    """Resolve notification channel and repo-level routing settings.

    Repo config lives under skills_config.notifications:
    {
      "notify_config_id": 1,              # optional; falls back to default
      "enabled_events": ["code_review_result"],
      "min_severity": "high",            # all/low/medium/high/critical
      "blocked_only": false
    }
    """
    from app.models import NotifyConfig

    repo_settings = ((getattr(repo, "skills_config", None) or {}).get("notifications") or {})
    notify_config_id = repo_settings.get("notify_config_id")

    query = select(NotifyConfig).where(NotifyConfig.enabled == True)
    if notify_config_id:
        query = query.where(NotifyConfig.id == notify_config_id)
    else:
        query = query.where(NotifyConfig.is_default == True)

    row = db.execute(query).scalar_one_or_none()
    if not row:
        return None

    return {
        "id": row.id,
        "name": row.name,
        "provider": row.provider,
        "config": row.config,
        "settings": repo_settings,
        "task_id": task_id,
        "repo_id": getattr(repo, "id", None),
    }


def _record_notification_log(
    task_id: str | None,
    notify_config_id: int | None,
    event_type: str,
    target: str | None,
    status: str,
    reason: str | None = None,
    payload: dict | None = None,
    error: str | None = None,
):
    import json as _json
    import psycopg2

    dsn = settings.DATABASE_PURE_URL
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO notification_logs "
                "(task_id, notify_config_id, event_type, target, status, reason, payload, error) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s)",
                (
                    task_id,
                    notify_config_id,
                    event_type,
                    target,
                    status,
                    reason,
                    _json.dumps(payload) if payload is not None else None,
                    error,
                ),
            )
        conn.commit()
    finally:
        conn.close()


_SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def _code_review_severity(data: dict) -> int:
    findings = data.get("findings", []) or []
    worst = 0
    for finding in findings:
        worst = max(worst, _SEVERITY_RANK.get(str(finding.get("severity", "")).lower(), 0))
    if data.get("blocked"):
        worst = max(worst, _SEVERITY_RANK["high"])
    return worst


def _notification_skip_reason(notif_data: dict, routing_settings: dict) -> str | None:
    event_type = notif_data.get("type", "generic")
    enabled_events = routing_settings.get("enabled_events")
    if enabled_events is not None and event_type not in enabled_events:
        return f"event disabled: {event_type}"

    if event_type == "code_review_result":
        data = notif_data.get("data", {}) or {}
        if routing_settings.get("blocked_only") and not data.get("blocked"):
            return "code review not blocked"

        min_severity = str(routing_settings.get("min_severity", "all")).lower()
        if min_severity != "all":
            threshold = _SEVERITY_RANK.get(min_severity, 0)
            if _code_review_severity(data) < threshold:
                return f"severity below threshold: {min_severity}"

    return None


@celery_app.task(bind=True, name="ai_tasks.process_push_event", max_retries=2)
def process_push_event(self, repo_id: int, event_data: dict):
    """Handle push event: run code review on the commit diff."""
    from app.models import AITask, AIModel, Repository

    task_id = self.request.id
    start_time = time.time()

    with SyncSession() as db:
        # Mark analyzing (pipeline starting)
        db.execute(
            update(AITask)
            .where(AITask.task_id == task_id)
            .values(status="analyzing", updated_at=datetime.now(timezone.utc))
        )
        db.commit()

        # Load repo + platform default model + resolve pipeline stages via RuleEngine
        repo = db.execute(select(Repository).where(Repository.id == repo_id)).scalar_one_or_none()
        if not repo:
            _mark_failed(db, task_id, f"Repository {repo_id} not found")
            return

        # Platform default model — used as ultimate fallback when no agent binding
        # specifies a model. No longer sourced from repo.ai_model_id.
        platform_model = db.execute(
            select(AIModel).where(AIModel.is_default == True)
        ).scalar_one_or_none()

        from app.services.rules.engine import get_stages_sync
        branch = event_data.get("branch", "")
        enabled_stages = get_stages_sync(repo_id, branch, db)

        # Pre-load notification route synchronously — avoids asyncpg inside the async block.
        notify_cfg = _resolve_notify_config(db, repo, task_id)

    def _sync_status_update(new_status: str):
        with SyncSession() as sdb:
            sdb.execute(
                update(AITask)
                .where(AITask.task_id == task_id)
                .values(status=new_status, updated_at=datetime.now(timezone.utc))
            )
            sdb.commit()

    async def _async_status_callback(new_status: str):
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _sync_status_update, new_status)

    try:
        # ── Async block: git + AI inference only, no DB ────────────────
        output = _run_async(_ai_pipeline(
            repo, platform_model, event_data, task_id, notify_cfg, enabled_stages,
            status_callback=_async_status_callback,
        ))
        # ──────────────────────────────────────────────────────────────

        duration_ms = int((time.time() - start_time) * 1000)
        output_data = output.get("output_data") or {}
        pipeline_status = output_data.get("pipeline_status") or {}
        final_status = "failed" if pipeline_status.get("status") in ("failed", "blocked") else "success"
        error_message = pipeline_status.get("reason") if final_status == "failed" else None
        with SyncSession() as db:
            db.execute(
                update(AITask)
                .where(AITask.task_id == task_id)
                .values(
                    status=final_status,
                    error_message=error_message,
                    output_data=output_data,
                    prompt_tokens=output.get("prompt_tokens", 0),
                    completion_tokens=output.get("completion_tokens", 0),
                    duration_ms=duration_ms,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            db.commit()
        logger.info("task.completed", task_id=task_id, status=final_status, duration_ms=duration_ms)

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


async def _persist_output_key(task_id: str, key: str, value: dict | list):
    if not task_id:
        return
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _write_partial_output, task_id, key, value)


def _stage_record(stage: str, status: str, output: dict, duration_ms: int = 0,
                  prompt_tokens: int = 0, completion_tokens: int = 0) -> dict:
    return {
        "stage": stage,
        "status": "skipped" if status == "gated" else status,
        "reason": output.get("reason") or output.get("error"),
        "metrics": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "duration_ms": duration_ms,
        },
        "artifacts": [],
    }


async def _run_code_review_stage(
    context,
    agent_resolver,
    platform_engine,
    skills_config: dict,
    notify_cfg: dict | None,
    task_id: str,
) -> dict:
    """Run the outer code review pipeline stage before unit-test orchestration."""
    from app.services.skills.runtime import skill_runtime

    start = time.time()
    engine = agent_resolver.get_engine("code_review") if agent_resolver else platform_engine
    skill_name = agent_resolver.get_skill_name("code_review") if agent_resolver else None
    skill_type = agent_resolver.get_skill_type("code_review") if agent_resolver else "builtin"
    result = await skill_runtime.execute(
        skill_name or "code_review",
        context,
        engine,
        skill_config=(skills_config or {}).get("code_review", {}),
        skill_type=skill_type or "builtin",
    )
    duration_ms = int((time.time() - start) * 1000)

    details = dict(result.details or {})
    status = "success"
    if not result.success:
        status = "failed"
        details.setdefault("status", "failed")
        details.setdefault("reason", details.get("error", "code review failed"))
    elif result.blocked or details.get("blocked"):
        status = "blocked"
        details.setdefault("status", "blocked")
        details.setdefault("reason", "code review policy blocked this change")
    else:
        details.setdefault("status", "success")

    await _persist_output_key(task_id, "code_review", details)
    if task_id:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            _record_agent_execution,
            task_id,
            "code_review",
            status,
            {"changed_files": context.changed_files[:20]},
            details,
            result.prompt_tokens,
            result.completion_tokens,
            duration_ms,
            1,
        )

    for notif in result.notifications:
        await _send_notification(
            notif,
            notify_cfg,
            repo_id=context.repo_id,
            branch=context.branch,
            stage_type="code_review",
        )

    return {
        "status": status,
        "output": details,
        "stage_result": _stage_record(
            "code_review",
            status,
            details,
            duration_ms,
            result.prompt_tokens,
            result.completion_tokens,
        ),
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
    }


async def _ai_pipeline(repo, platform_model, event_data: dict, task_id: str, notify_cfg: dict | None = None, enabled_stages: list | None = None, status_callback=None) -> dict:
    """Pure async: git diff + AI pipeline orchestration. No DB access."""
    from app.services.ai.engine import build_engine_from_db_model, AIEngine
    from app.services.skills.base import SkillContext
    from app.services.git.agent import GitAgent
    from app.core.security import decrypt

    # Platform default engine — ultimate fallback when no agent binding specifies a model
    platform_engine = build_engine_from_db_model(platform_model) if platform_model else AIEngine()

    git_token = decrypt(repo.git_token_encrypted) if repo.git_token_encrypted else None
    git_agent = GitAgent(repo.repo_url, git_token)

    commit_sha = event_data.get("commit_sha", "")
    before_sha = event_data.get("before_sha", "")

    # Fetch/clone repo
    git_agent.ensure_repo()

    branch = event_data.get("branch", "")
    diff, changed_files = _select_event_diff(git_agent, before_sha, commit_sha, branch)

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

    # Delegate to the reusable unit test workflow engine
    from app.services.unit_test_engine import UnitTestWorkflow, PipelineContext
    from app.services.ai.agent_resolver import build_agent_resolver_sync

    # Always build AgentResolver — system built-in agents serve as defaults
    with SyncSession() as resolver_db:
        agent_resolver = build_agent_resolver_sync(repo, platform_engine, resolver_db)

    skills_config = repo.skills_config or {}

    selected_stages = set(enabled_stages or ["code_review"])
    output_data: dict = {}
    prompt_tokens = 0
    completion_tokens = 0

    if "code_review" in selected_stages:
        if status_callback:
            try:
                await status_callback("analyzing")
            except Exception:
                pass
        cr_result = await _run_code_review_stage(
            context,
            agent_resolver,
            platform_engine,
            skills_config,
            notify_cfg,
            task_id,
        )
        output_data["code_review"] = cr_result["output"]
        output_data["stage_results"] = [cr_result["stage_result"]]
        prompt_tokens += cr_result["prompt_tokens"]
        completion_tokens += cr_result["completion_tokens"]
        await _persist_output_key(task_id, "stage_results", output_data["stage_results"])

        if cr_result["status"] in {"failed", "blocked"}:
            reason = (
                cr_result["output"].get("reason")
                or cr_result["output"].get("error")
                or f"code_review {cr_result['status']}"
            )
            pipeline_status = {
                "status": cr_result["status"],
                "failed_stage": "code_review",
                "reason": reason,
            }
            output_data["pipeline_status"] = pipeline_status
            if "test_generation" in selected_stages:
                blocked = {
                    "status": "blocked",
                    "blocked_by": "code_review",
                    "reason": f"Blocked because code_review {cr_result['status']}: {reason}",
                }
                output_data["test_generation"] = blocked
                output_data["stage_results"].append(_stage_record("test_generation", "blocked", blocked))
                await _persist_output_key(task_id, "test_generation", blocked)
                await _persist_output_key(task_id, "stage_results", output_data["stage_results"])
            await _persist_output_key(task_id, "pipeline_status", pipeline_status)
            if agent_resolver:
                output_data["model_usage"] = agent_resolver.get_model_usage()
            return {
                "output_data": output_data,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
            }
    else:
        skipped = {"status": "skipped", "reason": "code_review stage is not enabled"}
        output_data["code_review"] = skipped
        output_data["stage_results"] = [_stage_record("code_review", "skipped", skipped)]
        await _persist_output_key(task_id, "code_review", skipped)
        await _persist_output_key(task_id, "stage_results", output_data["stage_results"])

    if "test_generation" not in selected_stages:
        pipeline_status = {"status": "success", "reason": "selected pipeline stages completed"}
        output_data["pipeline_status"] = pipeline_status
        await _persist_output_key(task_id, "pipeline_status", pipeline_status)
        if agent_resolver:
            output_data["model_usage"] = agent_resolver.get_model_usage()
        return {
            "output_data": output_data,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        }

    context.extra["code_review_result"] = output_data.get("code_review")

    pipeline_ctx = PipelineContext(
        repo=repo,
        engine=platform_engine,
        git_agent=git_agent,
        git_token=git_token,
        skill_context=context,
        event_data=event_data,
        task_id=task_id,
        enabled_stages={"test_generation"},
        skills_config=skills_config,
        notify_cfg=notify_cfg,
        agent_resolver=agent_resolver,
        status_callback=status_callback,
        output_data=output_data,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )

    manager = UnitTestWorkflow()
    return await manager.run(pipeline_ctx)


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

        # Read real coverage BEFORE cleanup wipes the worktree directory.
        coverage = worktree.read_coverage(COVERAGE_XML_NAME)
        measured = coverage.get("line_rate")
        logger.info(
            "worktree.coverage",
            measured=measured,
            lines_covered=coverage.get("lines_covered"),
            lines_valid=coverage.get("lines_valid"),
        )

        return {
            "status": "passed" if result["success"] else "failed",
            "exit_code": result["exit_code"],
            "stdout": result["stdout"],
            "stderr": result["stderr"],
            "run_command": cmd_display,
            "coverage": coverage,
            # Convenience field for MR comments / notifications. Kept separate
            # from the legacy LLM-sourced `estimated_coverage_delta` so downstream
            # consumers can prefer the measured number when present.
            "measured_coverage_delta": f"+{measured:.2f}%" if measured is not None else None,
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


async def _validate_repair_loop(
    git_agent,
    engine,
    branch_or_sha: str,
    generated_files: list[dict],
    run_command: list[str],
    task_id: str,
    loop,
    context_hint: str = "",
    repair_enabled: bool = True,
    timeout: int = 60,
    status_callback=None,
    max_rounds_override: int = None,
) -> tuple[dict, list[dict]]:
    """
    Run tests → validate → repair → retry loop.
    When repair_enabled=False, only runs validation once (no repair attempts).
    Returns (final worktree_result_dict, repair_history list).
    """
    from app.services.agents.validator_agent import ValidatorAgent
    from app.services.agents.repair_agent import RepairAgent

    validator = ValidatorAgent()
    repair_agent = RepairAgent()
    max_rounds = max_rounds_override if max_rounds_override else (settings.MAX_REPAIR_ROUNDS if repair_enabled else 1)
    current_files = list(generated_files)
    repair_history: list[dict] = []

    for round_num in range(1, max_rounds + 1):
        # Run tests in WorkTree
        run_start = time.time()
        wr = await _run_worktree_tests(git_agent, branch_or_sha, current_files, run_command, timeout)
        run_ms = int((time.time() - run_start) * 1000)

        # Validate
        vr = validator.parse_worktree_result(wr, duration_ms=run_ms)

        await loop.run_in_executor(None, _record_agent_execution,
            task_id, "validator", vr.status,
            {"round": round_num}, vr.to_dict(),
            0, 0, run_ms, round_num)

        if vr.status == "all_pass":
            wr["repair_rounds"] = round_num - 1
            return wr, repair_history

        if not vr.can_repair or round_num == max_rounds:
            wr["repair_rounds"] = round_num - 1
            wr["final_validation"] = vr.to_dict()
            return wr, repair_history

        # Repair — emit REPAIRING status
        if status_callback:
            try:
                await status_callback("repairing")
            except Exception:
                pass

        repair_start = time.time()
        rr = await repair_agent.repair(
            engine, vr, current_files, round_number=round_num, context_hint=context_hint,
        )
        repair_ms = int((time.time() - repair_start) * 1000)

        await loop.run_in_executor(None, _record_agent_execution,
            task_id, "repair",
            "success" if rr.success else "failed",
            {"round": round_num, "failures_count": len(vr.failures)},
            rr.to_dict(),
            rr.prompt_tokens, rr.completion_tokens, repair_ms, round_num)

        if not rr.success or not rr.repaired_files:
            wr["repair_rounds"] = round_num
            wr["final_validation"] = vr.to_dict()
            return wr, repair_history

        # Apply repairs to current_files for next round
        repair_map = {rf["path"]: rf["content"] for rf in rr.repaired_files}
        current_files = [
            {"path": f["path"], "content": repair_map.get(f["path"], f["content"])}
            for f in current_files
        ]

        repair_history.append({
            "round": round_num,
            "fixes": [a.fix_description for a in rr.actions],
            "summary": rr.summary,
        })

        logger.info("repair.round_complete", round=round_num, task_id=task_id)

    # Should not reach here, but safety fallback
    return wr, repair_history


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
    if ntype == "quality_score_result":
        score = data.get("total_score")
        risk = data.get("risk_level")
        if risk == "high" or (score is not None and score < 6):
            return "red"
        if risk == "medium" or (score is not None and score < 8):
            return "yellow"
    return "green"


async def _send_notification(notif_data: dict, notify_cfg: dict | None,
                             repo_id: int = None, branch: str = "", stage_type: str = ""):
    """Send notification via repo-level config."""
    if notify_cfg:
        await _send_one(notif_data, notify_cfg)


async def _send_one(notif_data: dict, notify_cfg: dict):
    from app.services.notify.feishu import build_notify_provider
    from app.services.notify.base import NotifyMessage
    event_type = notif_data.get("type", "generic")
    task_id = notify_cfg.get("task_id")
    notify_config_id = notify_cfg.get("id")
    target = notify_cfg.get("target_label") or notify_cfg.get("name") or notify_cfg.get("provider")
    skip_reason = _notification_skip_reason(notif_data, notify_cfg.get("settings") or {})
    if skip_reason:
        try:
            _record_notification_log(
                task_id, notify_config_id, event_type, target,
                "skipped", reason=skip_reason, payload=notif_data,
            )
        except Exception as exc:
            logger.warning("notification.log_failed", error=str(exc))
        return

    try:
        provider = build_notify_provider(notify_cfg)
        msg = NotifyMessage(
            title=notif_data.get("type", "AI DevOps 通知"),
            content="",
            message_type=event_type,
            data=notif_data,
            color=_notification_color(notif_data),
        )
        ok = await provider.send(msg)
        _record_notification_log(
            task_id, notify_config_id, event_type, target,
            "sent" if ok else "failed", payload=notif_data,
            error=None if ok else "provider returned false",
        )
    except Exception as e:
        logger.warning("notification.failed", error=str(e))
        try:
            _record_notification_log(
                task_id, notify_config_id, event_type, target,
                "failed", payload=notif_data, error=str(e),
            )
        except Exception as log_exc:
            logger.warning("notification.log_failed", error=str(log_exc))
