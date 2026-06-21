"""Dashboard statistics API."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text
from datetime import date, timedelta

from app.core.database import get_db
from app.models import AITask

router = APIRouter()


@router.get("/overview")
async def get_overview(db: AsyncSession = Depends(get_db)):
    """Three-dimension stats for dashboard overview cards."""

    # ── Code review ───────────────────────────────────────────────────────
    cr = await db.execute(text("""
        SELECT
            COUNT(*)                                                        AS total,
            COUNT(*) FILTER (
                WHERE (output_data->'code_review'->>'blocked')::boolean = true
            )                                                               AS blocked,
            AVG((output_data->'code_review'->>'score')::numeric)
                FILTER (WHERE output_data ? 'code_review')                  AS avg_score
        FROM ai_tasks
        WHERE output_data ? 'code_review'
    """))
    cr_row = cr.fetchone()
    cr_total   = int(cr_row.total or 0)
    cr_blocked = int(cr_row.blocked or 0)
    cr_score   = round(float(cr_row.avg_score or 0), 1)

    # ── Test generation ───────────────────────────────────────────────────
    tg = await db.execute(text("""
        SELECT
            COUNT(*)                                                        AS total,
            COUNT(*) FILTER (
                WHERE output_data->'test_generation'->'worktree_run'->>'status' = 'passed'
            )                                                               AS passed
        FROM ai_tasks
        WHERE output_data ? 'test_generation'
    """))
    tg_row    = tg.fetchone()
    tg_total  = int(tg_row.total or 0)
    tg_passed = int(tg_row.passed or 0)
    tg_pass_rate = round(tg_passed / tg_total * 100, 1) if tg_total else 0

    # ── Auto merge (Phase 1: reserved) ────────────────────────────────────
    am = await db.execute(text("""
        SELECT
            COUNT(*)                                                        AS total,
            COUNT(*) FILTER (
                WHERE (output_data->'auto_merge'->>'success')::boolean = true
            )                                                               AS success
        FROM ai_tasks
        WHERE output_data ? 'auto_merge'
    """))
    am_row     = am.fetchone()
    am_total   = int(am_row.total or 0)
    am_success = int(am_row.success or 0)

    # ── Token usage ───────────────────────────────────────────────────────
    tok = await db.execute(
        select(func.sum(AITask.prompt_tokens + AITask.completion_tokens))
    )
    total_tokens = int(tok.scalar() or 0)

    # ── Week activity ─────────────────────────────────────────────────────
    week_ago = date.today() - timedelta(days=7)
    week_tasks = (await db.execute(
        select(func.count()).where(AITask.created_at >= week_ago)
    )).scalar() or 0

    return {
        "code_review": {
            "total": cr_total,
            "blocked": cr_blocked,
            "block_rate": round(cr_blocked / cr_total * 100, 1) if cr_total else 0,
            "avg_score": cr_score,
        },
        "test_generation": {
            "total": tg_total,
            "passed": tg_passed,
            "pass_rate": tg_pass_rate,
        },
        "auto_merge": {
            "total": am_total,
            "success": am_success,
            "success_rate": round(am_success / am_total * 100, 1) if am_total else 0,
        },
        "total_tokens_used": total_tokens,
        "week_tasks": int(week_tasks),
        # Phase 2 reserved
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
                DATE(created_at AT TIME ZONE 'Asia/Shanghai') AS day,
                task_type,
                COUNT(*)                                       AS count,
                SUM(prompt_tokens + completion_tokens)         AS tokens
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
        select(AITask.repo_id, AITask.task_type, func.count().label("count"))
        .group_by(AITask.repo_id, AITask.task_type)
    )
    return [{"repo_id": r.repo_id, "task_type": r.task_type, "count": r.count} for r in result.fetchall()]


# Phase 2 reserved
@router.get("/jenkins/builds")
async def get_jenkins_builds():
    return {"items": [], "message": "Jenkins integration available in Phase 2"}


@router.get("/jenkins/stats")
async def get_jenkins_stats():
    return {"total_builds": None, "success_rate": None, "avg_duration_ms": None,
            "message": "Jenkins integration available in Phase 2"}
