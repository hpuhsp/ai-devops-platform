"""Dashboard statistics API."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text
from datetime import date, timedelta

from app.core.database import get_db
from app.models import AITask, StatsSnapshot

router = APIRouter()


@router.get("/overview")
async def get_overview(db: AsyncSession = Depends(get_db)):
    """Total counts for dashboard overview cards."""
    today = date.today()
    week_ago = today - timedelta(days=7)

    total_reviews = (await db.execute(
        select(func.count()).where(AITask.task_type == "code_review")
    )).scalar() or 0

    total_test_gen = (await db.execute(
        select(func.count()).where(AITask.task_type.in_(["test_generation"]))
    )).scalar() or 0

    blocked_count = (await db.execute(
        select(func.count()).where(
            AITask.task_type == "code_review",
            AITask.output_data["blocked"].as_boolean() == True,
        )
    )).scalar() or 0

    total_tokens = (await db.execute(
        select(func.sum(AITask.prompt_tokens + AITask.completion_tokens))
    )).scalar() or 0

    week_tasks = (await db.execute(
        select(func.count()).where(AITask.created_at >= week_ago)
    )).scalar() or 0

    return {
        "total_reviews": total_reviews,
        "total_test_gen": total_test_gen,
        "blocked_count": blocked_count,
        "block_rate": round(blocked_count / total_reviews * 100, 1) if total_reviews else 0,
        "total_tokens_used": total_tokens,
        "week_tasks": week_tasks,
        # Phase 2 reserved fields
        "jenkins_builds_total": None,
        "jenkins_success_rate": None,
        "deploy_count": None,
    }


@router.get("/trends")
async def get_trends(days: int = 7, db: AsyncSession = Depends(get_db)):
    """Daily task trend data for charts."""
    result = await db.execute(
        text("""
            SELECT
                DATE(created_at AT TIME ZONE 'Asia/Shanghai') as day,
                task_type,
                COUNT(*) as count,
                SUM(prompt_tokens + completion_tokens) as tokens
            FROM ai_tasks
            WHERE created_at >= NOW() - INTERVAL ':days days'
            GROUP BY day, task_type
            ORDER BY day
        """).bindparams(days=days)
    )
    rows = result.fetchall()
    return [{"day": str(r.day), "task_type": r.task_type, "count": r.count, "tokens": r.tokens} for r in rows]


@router.get("/by-repo")
async def get_by_repo(db: AsyncSession = Depends(get_db)):
    """Per-repository statistics."""
    result = await db.execute(
        select(
            AITask.repo_id,
            AITask.task_type,
            func.count().label("count"),
        ).group_by(AITask.repo_id, AITask.task_type)
    )
    rows = result.fetchall()
    return [{"repo_id": r.repo_id, "task_type": r.task_type, "count": r.count} for r in rows]


# Phase 2 reserved: Jenkins data endpoints
@router.get("/jenkins/builds")
async def get_jenkins_builds():
    """Phase 2 placeholder — Jenkins build data will be populated by Jenkins adapter."""
    return {"items": [], "message": "Jenkins integration available in Phase 2"}


@router.get("/jenkins/stats")
async def get_jenkins_stats():
    """Phase 2 placeholder — Jenkins statistics."""
    return {
        "total_builds": None,
        "success_rate": None,
        "avg_duration_ms": None,
        "message": "Jenkins integration available in Phase 2",
    }
