"""Task management and log streaming API."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from typing import Optional
import asyncio
import json

from app.core.database import get_db
from app.models import AITask

router = APIRouter()


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
    q = q.offset((page - 1) * page_size).limit(page_size)
    tasks = (await db.execute(q)).scalars().all()

    return {
        "total": total,
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
    task = (await db.execute(select(AITask).where(AITask.task_id == task_id))).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {
        "task_id": task.task_id,
        "task_type": task.task_type,
        "status": task.status,
        "trigger_event": task.trigger_event,
        "input_data": task.input_data,
        "output_data": task.output_data,
        "error_message": task.error_message,
        "prompt_tokens": task.prompt_tokens,
        "completion_tokens": task.completion_tokens,
        "duration_ms": task.duration_ms,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
    }


@router.get("/{task_id}/logs")
async def stream_task_logs(task_id: str, db: AsyncSession = Depends(get_db)):
    """SSE endpoint for real-time task log streaming."""
    async def event_stream():
        for _ in range(60):  # poll up to 60s
            task = (await db.execute(select(AITask).where(AITask.task_id == task_id))).scalar_one_or_none()
            if not task:
                yield f"data: {json.dumps({'error': 'task not found'})}\n\n"
                break

            data = {"status": task.status, "updated_at": task.updated_at.isoformat() if task.updated_at else None}
            if task.output_data:
                data["output"] = task.output_data
            if task.error_message:
                data["error"] = task.error_message

            yield f"data: {json.dumps(data)}\n\n"

            if task.status in ("success", "failed"):
                break
            await asyncio.sleep(2)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
