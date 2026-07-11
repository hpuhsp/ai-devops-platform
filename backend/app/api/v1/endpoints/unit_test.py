"""Manual/API trigger for the AI unit test workflow."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import AITask, Repository

router = APIRouter()


class UnitTestTriggerRequest(BaseModel):
    repo_id: int
    branch: str = ""
    commit_sha: str = ""
    before_sha: str = ""
    author: str = "manual"
    author_email: str = ""
    mr_iid: int | None = None
    mr_title: str = ""
    mr_source_branch: str = ""
    mr_target_branch: str = ""
    metadata: dict = Field(default_factory=dict)


def _build_unit_test_event(repo: Repository, body: UnitTestTriggerRequest) -> dict:
    return {
        "repo_url": repo.repo_url,
        "branch": body.branch,
        "commit_sha": body.commit_sha,
        "before_sha": body.before_sha,
        "author": body.author,
        "author_email": body.author_email,
        "mr_iid": body.mr_iid,
        "mr_title": body.mr_title,
        "mr_source_branch": body.mr_source_branch,
        "mr_target_branch": body.mr_target_branch,
        "trigger_source": "manual_unit_test",
        "metadata": body.metadata,
    }


@router.post("/trigger", status_code=202)
async def trigger_unit_test(body: UnitTestTriggerRequest, db: AsyncSession = Depends(get_db)):
    repo = (await db.execute(
        select(Repository).where(Repository.id == body.repo_id, Repository.enabled == True)
    )).scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found or disabled")

    task_id = str(uuid.uuid4())
    event_data = _build_unit_test_event(repo, body)
    ai_task = AITask(
        task_id=task_id,
        repo_id=repo.id,
        task_type="unit_test",
        status="created",
        trigger_event={
            "platform": repo.platform,
            "event_type": "manual_unit_test",
            "branch": body.branch,
            "commit_sha": body.commit_sha,
            "author": body.author,
        },
        input_data=event_data,
    )
    db.add(ai_task)
    await db.commit()

    from app.tasks.ai_tasks import process_push_event

    process_push_event.apply_async(
        args=[repo.id, event_data],
        task_id=task_id,
    )

    return {
        "status": "accepted",
        "task_id": task_id,
        "repo_id": repo.id,
        "branch": body.branch,
        "commit_sha": body.commit_sha,
    }
