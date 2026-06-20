"""
Webhook receiver — handles Push/MR events from GitLab/GitHub/Gitea.
"""
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Request, HTTPException, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models import Repository, AITask
from app.services.git.webhook_parser import parse_gitlab, parse_github, parse_gitea

router = APIRouter()


def _verify_gitlab_signature(payload: bytes, token: str, secret: str) -> bool:
    return hmac.compare_digest(token, secret)


def _verify_github_signature(payload: bytes, signature: str, secret: str) -> bool:
    expected = "sha256=" + hmac.new(
        secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(signature, expected)


@router.post("/{platform}")
async def receive_webhook(
    platform: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    if platform not in ("gitlab", "github", "gitea"):
        raise HTTPException(status_code=400, detail=f"Unsupported platform: {platform}")

    payload_bytes = await request.body()
    payload = json.loads(payload_bytes)

    # Get event header and signature
    if platform == "gitlab":
        event_header = request.headers.get("X-Gitlab-Event", "")
        token = request.headers.get("X-Gitlab-Token", "")
    elif platform == "github":
        event_header = request.headers.get("X-Github-Event", "")
        token = request.headers.get("X-Hub-Signature-256", "")
    else:  # gitea
        event_header = request.headers.get("X-Gitea-Event", "")
        token = request.headers.get("X-Gitea-Token", "")

    # Parse event
    parsers = {"gitlab": parse_gitlab, "github": parse_github, "gitea": parse_gitea}
    event = parsers[platform](payload, event_header)

    if not event.repo_url:
        return {"status": "ignored", "reason": "no repo_url"}

    # Find matching repository config
    result = await db.execute(
        select(Repository).where(
            Repository.repo_url == event.repo_url,
            Repository.platform == platform,
            Repository.enabled == True,
        )
    )
    repo = result.scalar_one_or_none()

    if repo is None:
        return {"status": "ignored", "reason": "repository not configured"}

    # Verify webhook secret
    if repo.webhook_secret:
        valid = False
        if platform == "gitlab":
            valid = _verify_gitlab_signature(payload_bytes, token, repo.webhook_secret)
        elif platform == "github":
            valid = _verify_github_signature(payload_bytes, token, repo.webhook_secret)
        elif platform == "gitea":
            valid = hmac.compare_digest(token, repo.webhook_secret)

        if not valid:
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    # Skip non-actionable events
    if event.event_type not in ("push", "mr_open", "mr_reopened", "mr_update"):
        return {"status": "ignored", "reason": f"event_type '{event.event_type}' not handled"}

    # Create task record
    task_id = str(uuid.uuid4())
    ai_task = AITask(
        task_id=task_id,
        repo_id=repo.id,
        task_type="code_review" if event.event_type == "push" else "mr_review",
        status="pending",
        trigger_event={
            "platform": platform,
            "event_type": event.event_type,
            "branch": event.branch,
            "commit_sha": event.commit_sha,
            "author": event.author,
        },
        input_data={
            "repo_url": event.repo_url,
            "branch": event.branch,
            "commit_sha": event.commit_sha,
            "before_sha": event.before_sha,
            "author": event.author,
            "author_email": event.author_email,
            "mr_iid": event.mr_iid,
            "mr_title": event.mr_title,
            "mr_source_branch": event.mr_source_branch,
            "mr_target_branch": event.mr_target_branch,
        },
    )
    db.add(ai_task)
    await db.commit()

    # Dispatch Celery task
    from app.tasks.ai_tasks import process_push_event
    process_push_event.apply_async(
        args=[repo.id, ai_task.input_data],
        task_id=task_id,
    )

    return {"status": "accepted", "task_id": task_id}
