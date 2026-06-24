"""Task management, push-event pipeline list, and SSE log streaming."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from typing import Optional
import asyncio
import json

from app.core.database import get_db, AsyncSessionLocal
from app.models import AITask

router = APIRouter()


def _build_pipeline_nodes(task: AITask) -> dict:
    """Derive per-node status from output_data and overall task status."""
    od = task.output_data or {}
    overall = task.status  # pending / running / success / failed

    def _node(key: str, build_fn) -> dict:
        if key in od:
            return build_fn(od[key])
        # Not written yet — infer from overall status
        if overall in ("pending", "running"):
            return {"status": "pending"}
        return {"status": "skipped"}

    def _cr_node(data: dict) -> dict:
        blocked = data.get("blocked", False)
        return {
            "status": "blocked" if blocked else "done",
            "score": data.get("score"),
            "findings": len(data.get("findings", [])),
            "critical_count": data.get("critical_count", 0),
            "high_count": data.get("high_count", 0),
        }

    def _tg_node(data: dict) -> dict:
        wr = data.get("worktree_run", {})
        wr_status = wr.get("status", "unknown")
        # "running" when worktree_run key is absent but test_generation key exists
        return {
            "status": wr_status if wr_status != "unknown" else "running",
            "framework": data.get("framework"),
            "files_count": len(data.get("generated_files", [])),
            "pytest_status": wr.get("status"),
            "pytest_passed": _count_from_stdout(wr.get("stdout", ""), "passed"),
            "pytest_failed": _count_from_stdout(wr.get("stdout", ""), "failed"),
        }

    def _am_node(data: dict) -> dict:
        return {
            "status": "done" if data.get("success") else "failed",
            "message": data.get("message", ""),
        }

    cr = _node("code_review", _cr_node)
    # If overall task is running and code_review is already done, mark tg as running
    if overall == "running" and cr.get("status") in ("done", "blocked"):
        tg_default = {"status": "running"}
    else:
        tg_default = {"status": "pending"}

    tg = od["test_generation"] and _tg_node(od["test_generation"]) if "test_generation" in od else tg_default
    am = _node("auto_merge", _am_node)

    return {
        "code_review": cr,
        "test_generation": tg,
        "auto_merge": am,
        # Phase 2 placeholders
        "ci_build": {"status": "phase2"},
        "deploy": {"status": "phase2"},
    }


def _count_from_stdout(stdout: str, keyword: str) -> int:
    import re
    m = re.search(rf"(\d+) {keyword}", stdout)
    return int(m.group(1)) if m else 0


def _task_to_event(task: AITask) -> dict:
    ti = task.trigger_event or {}
    return {
        "task_id": task.task_id,
        "repo_id": task.repo_id,
        "status": task.status,
        "branch": ti.get("branch", ""),
        "commit_sha": (ti.get("commit_sha") or "")[:8],
        "author": ti.get("author", ""),
        "prompt_tokens": task.prompt_tokens,
        "completion_tokens": task.completion_tokens,
        "duration_ms": task.duration_ms,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        "pipeline": _build_pipeline_nodes(task),
    }


# ── Push event list (pipeline chain view) ────────────────────────────────────

@router.get("/events")
async def list_events(
    page: int = 1,
    page_size: int = 20,
    repo_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
):
    q = (
        select(AITask)
        .where(AITask.task_type.in_(["push_event", "code_review"]))  # include legacy type
        .order_by(desc(AITask.created_at))
    )
    if repo_id:
        q = q.where(AITask.repo_id == repo_id)

    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar()
    tasks = (await db.execute(q.offset((page - 1) * page_size).limit(page_size))).scalars().all()

    return {
        "total": int(total),
        "page": page,
        "page_size": page_size,
        "items": [_task_to_event(t) for t in tasks],
    }


@router.get("/events/{task_id}/stream")
async def stream_pipeline(task_id: str):
    """SSE: poll every 2s and push pipeline node updates until task completes.

    Uses a short-lived session per poll instead of holding one connection open for
    the whole stream — long-lived SSE clients would otherwise exhaust the pool.
    """
    async def event_stream():
        for _ in range(120):  # max 4 minutes
            async with AsyncSessionLocal() as db:
                task = (await db.execute(
                    select(AITask).where(AITask.task_id == task_id)
                )).scalar_one_or_none()
                payload = _task_to_event(task) if task else None

            if payload is None:
                yield f"data: {json.dumps({'error': 'not found'})}\n\n"
                break

            yield f"data: {json.dumps(payload)}\n\n"

            if payload["status"] in ("success", "failed"):
                break
            await asyncio.sleep(2)

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── Task list (existing) ──────────────────────────────────────────────────────

@router.get("")
async def list_tasks(
    page: int = 1,
    page_size: int = 20,
    status: Optional[str] = None,
    task_type: Optional[str] = None,
    repo_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
):
    q = select(AITask).order_by(desc(AITask.created_at))
    if status:
        q = q.where(AITask.status == status)
    if task_type:
        q = q.where(AITask.task_type == task_type)
    if repo_id:
        q = q.where(AITask.repo_id == repo_id)

    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar()
    tasks = (await db.execute(q.offset((page - 1) * page_size).limit(page_size))).scalars().all()

    return {
        "total": int(total),
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": t.id,
                "task_id": t.task_id,
                "repo_id": t.repo_id,
                "task_type": t.task_type,
                "status": t.status,
                "prompt_tokens": t.prompt_tokens,
                "completion_tokens": t.completion_tokens,
                "duration_ms": t.duration_ms,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in tasks
        ],
    }


@router.get("/{task_id}")
async def get_task(task_id: str, db: AsyncSession = Depends(get_db)):
    task = (await db.execute(
        select(AITask).where(AITask.task_id == task_id)
    )).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {
        **_task_to_event(task),
        "task_type": task.task_type,
        "error_message": task.error_message,
        "input_data": task.input_data,
        "output_data": task.output_data,
    }


@router.get("/{task_id}/logs")
async def stream_task_logs(task_id: str):
    """Legacy SSE endpoint kept for compatibility. Short-lived session per poll."""
    async def event_stream():
        for _ in range(60):
            async with AsyncSessionLocal() as db:
                task = (await db.execute(
                    select(AITask).where(AITask.task_id == task_id)
                )).scalar_one_or_none()
                if not task:
                    data = None
                else:
                    data = {"status": task.status,
                            "updated_at": task.updated_at.isoformat() if task.updated_at else None}
                    if task.output_data:
                        data["output"] = task.output_data
                    if task.error_message:
                        data["error"] = task.error_message

            if data is None:
                yield f"data: {json.dumps({'error': 'task not found'})}\n\n"
                break

            yield f"data: {json.dumps(data)}\n\n"
            if data["status"] in ("success", "failed"):
                break
            await asyncio.sleep(2)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
