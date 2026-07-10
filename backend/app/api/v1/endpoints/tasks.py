"""Task management, push-event pipeline list, and SSE log streaming."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from typing import Optional
import asyncio
import json

from app.core.database import get_db, AsyncSessionLocal
from app.models import AITask, AgentExecution

router = APIRouter()


def _build_pipeline_nodes(task: AITask) -> dict:
    """Derive per-node status from output_data and overall task status."""
    od = task.output_data or {}
    overall = task.status  # created/analyzing/generating/executing/repairing/success/failed

    _ACTIVE = {"created", "analyzing", "generating", "executing", "repairing", "pending", "running"}
    _EXPLICIT_STATUSES = {"failed", "blocked", "skipped"}

    def _node(key: str, build_fn) -> dict:
        if key in od:
            return build_fn(od[key])
        if overall in _ACTIVE:
            return {"status": "pending"}
        return {"status": "skipped"}

    def _explicit_node(data: dict) -> dict | None:
        status = data.get("status")
        if status not in _EXPLICIT_STATUSES:
            return None
        node = {"status": status}
        for key in ("reason", "error", "blocked_by"):
            if data.get(key):
                node[key] = data.get(key)
        return node

    def _cr_node(data: dict) -> dict:
        explicit = _explicit_node(data)
        blocked = data.get("blocked", False)
        node = {
            "status": explicit["status"] if explicit else ("blocked" if blocked else "done"),
            "score": data.get("score"),
            "findings": len(data.get("findings", [])),
            "critical_count": data.get("critical_count", 0),
            "high_count": data.get("high_count", 0),
        }
        if explicit:
            node.update({k: v for k, v in explicit.items() if k != "status"})
        return node

    def _tg_node(data: dict) -> dict:
        explicit = _explicit_node(data)
        wr = data.get("worktree_run", {})
        wr_status = wr.get("status", "unknown")
        reason = data.get("reason") or wr.get("reason") or data.get("error") or wr.get("error")
        status = wr_status if wr_status != "unknown" else "running"
        if explicit:
            status = explicit["status"]
        elif wr_status == "skipped" and reason:
            status = "failed"
        node = {
            "status": status,
            "framework": data.get("framework"),
            "files_count": len(data.get("generated_files", [])),
            "pytest_status": wr.get("status"),
            "pytest_passed": _count_from_stdout(wr.get("stdout", ""), "passed"),
            "pytest_failed": _count_from_stdout(wr.get("stdout", ""), "failed"),
            "repair_rounds": wr.get("repair_rounds", 0),
            "repair_history": data.get("repair_history", []),
        }
        if reason:
            node["reason"] = reason
        return node

    def _am_node(data: dict) -> dict:
        explicit = _explicit_node(data)
        if explicit:
            return {
                **explicit,
                "message": data.get("message", explicit.get("reason", "")),
            }
        return {
            "status": "done" if data.get("success") else "failed",
            "message": data.get("message", ""),
        }

    cr = _node("code_review", _cr_node)

    # Change Intelligence node
    def _ci_node(data: dict) -> dict:
        explicit = _explicit_node(data)
        if explicit:
            return {
                **explicit,
                "need_test": data.get("need_test", False),
                "risk_level": data.get("risk_level", "none"),
                "impact_radius": data.get("impact_radius", 0),
                "targets_count": len(data.get("targets", [])),
            }
        return {
            "status": "skip" if not data.get("need_test") else "done",
            "need_test": data.get("need_test", False),
            "risk_level": data.get("risk_level", "none"),
            "impact_radius": data.get("impact_radius", 0),
            "targets_count": len(data.get("targets", [])),
        }
    ci = _node("change_intelligence", _ci_node)

    tg_raw = od.get("test_generation")
    if tg_raw and tg_raw.get("status") == "skipped":
        tg = {"status": "skipped", "reason": tg_raw.get("reason", "")}
    elif tg_raw:
        tg = _tg_node(tg_raw)
    elif overall in ("generating", "executing", "repairing"):
        tg = {"status": "running"}
    elif overall in _ACTIVE:
        tg = {"status": "pending"}
    else:
        tg = {"status": "skipped"}
        if od.get("summary") == "No diff to review":
            tg["reason"] = "No diff to review"
    am = _node("auto_merge", _am_node)

    # Quality score node
    def _qs_node(data: dict) -> dict:
        explicit = _explicit_node(data)
        if explicit:
            return {
                **explicit,
                "total_score": data.get("total_score"),
                "dimensions": data.get("dimensions", {}),
                "risk_level": data.get("risk_level"),
            }
        return {
            "status": "done",
            "total_score": data.get("total_score"),
            "dimensions": data.get("dimensions", {}),
            "risk_level": data.get("risk_level"),
        }
    qs = _node("quality_score", _qs_node)

    if tg.get("status") in ("failed", "blocked"):
        block_reason = tg.get("reason") or "Blocked because test_generation failed"
        if "quality_score" not in od:
            qs = {
                "status": "blocked",
                "blocked_by": "test_generation",
                "reason": block_reason,
            }
        if "auto_merge" not in od:
            am = {
                "status": "blocked",
                "blocked_by": "test_generation",
                "message": block_reason,
                "reason": block_reason,
            }

    return {
        "code_review": cr,
        "change_intelligence": ci,
        "test_generation": tg,
        "quality_score": qs,
        "auto_merge": am,
    }


def _count_from_stdout(stdout: str, keyword: str) -> int:
    import re
    m = re.search(rf"(\d+) {keyword}", stdout)
    return int(m.group(1)) if m else 0


def _task_to_event(task: AITask) -> dict:
    ti = task.trigger_event or {}
    pipeline = _build_pipeline_nodes(task)
    status = task.status
    if status == "success" and any(
        node.get("status") in ("failed", "blocked")
        for node in pipeline.values()
        if isinstance(node, dict)
    ):
        status = "failed"
    return {
        "task_id": task.task_id,
        "repo_id": task.repo_id,
        "status": status,
        "branch": ti.get("branch", ""),
        "commit_sha": (ti.get("commit_sha") or "")[:8],
        "author": ti.get("author", ""),
        "prompt_tokens": task.prompt_tokens,
        "completion_tokens": task.completion_tokens,
        "duration_ms": task.duration_ms,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        "pipeline": pipeline,
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


@router.get("/{task_id}/agents")
async def list_task_agents(task_id: str, db: AsyncSession = Depends(get_db)):
    """Agent execution chain for a given task (Change Intel → Generator → Validator → Repair)."""
    rows = (await db.execute(
        select(AgentExecution)
        .where(AgentExecution.task_id == task_id)
        .order_by(AgentExecution.created_at)
    )).scalars().all()
    return [
        {
            "id": r.id,
            "agent_type": r.agent_type,
            "round_number": r.round_number,
            "status": r.status,
            "prompt_tokens": r.prompt_tokens,
            "completion_tokens": r.completion_tokens,
            "duration_ms": r.duration_ms,
            "output_data": r.output_data,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


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
