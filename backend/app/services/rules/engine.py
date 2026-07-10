"""
Branch Rule Engine — matches a branch name against pipeline_rules to determine
which stages should run. Uses fnmatch-style wildcards (feature/*, hotfix/*).
Falls back to repo.skills_config for legacy compatibility when no rules exist.
"""
import fnmatch
import structlog
from sqlalchemy.orm import Session
from sqlalchemy import select

logger = structlog.get_logger()

ALL_STAGES = ["code_review", "test_generation", "auto_merge", "build", "deploy"]

# Built-in branch strategy templates (applied when user selects a template)
TEMPLATES: dict[str, list[dict]] = {
    "gitflow": [
        {"name": "feature/* — 审核+单测",      "pattern": "feature/*",  "stages": ["code_review", "test_generation"],                     "priority": 80},
        {"name": "hotfix/* — 审核+合并",        "pattern": "hotfix/*",   "stages": ["code_review", "auto_merge"],                          "priority": 70},
        {"name": "release/* — 审核+单测+合并",  "pattern": "release/*",  "stages": ["code_review", "test_generation", "auto_merge"],        "priority": 60},
        {"name": "develop — 审核+单测+合并",    "pattern": "develop",    "stages": ["code_review", "test_generation", "auto_merge"],        "priority": 50},
        {"name": "main — 全流程",               "pattern": "main",       "stages": ["code_review", "test_generation", "auto_merge"],        "priority": 40},
        {"name": "master — 全流程",             "pattern": "master",     "stages": ["code_review", "test_generation", "auto_merge"],        "priority": 39},
        {"name": "默认兜底 — 仅审核",           "pattern": "*",          "stages": ["code_review"],                                         "priority": 1},
    ],
    "trunk": [
        {"name": "main — 审核+单测",            "pattern": "main",       "stages": ["code_review", "test_generation"],                     "priority": 90},
        {"name": "feature/* — 审核+单测",       "pattern": "feature/*",  "stages": ["code_review", "test_generation"],                     "priority": 50},
        {"name": "默认兜底 — 仅审核",           "pattern": "*",          "stages": ["code_review"],                                         "priority": 1},
    ],
    "github_flow": [
        {"name": "main — 主干全量校验",          "pattern": "main",       "stages": ["code_review", "test_generation", "auto_merge"],        "priority": 90},
        {"name": "master — 主干全量校验",        "pattern": "master",     "stages": ["code_review", "test_generation", "auto_merge"],        "priority": 89},
        {"name": "feature/* — PR审核+单测",      "pattern": "feature/*",  "stages": ["code_review", "test_generation"],                     "priority": 70},
        {"name": "bugfix/* — PR审核+单测",       "pattern": "bugfix/*",   "stages": ["code_review", "test_generation"],                     "priority": 60},
        {"name": "hotfix/* — 快速审核+单测",     "pattern": "hotfix/*",   "stages": ["code_review", "test_generation"],                     "priority": 50},
        {"name": "默认兜底 — 仅审核",            "pattern": "*",          "stages": ["code_review"],                                         "priority": 1},
    ],
    "gitlab_flow": [
        {"name": "feature/* — 审核+单测",        "pattern": "feature/*",  "stages": ["code_review", "test_generation"],                     "priority": 90},
        {"name": "main — 集成分支校验",          "pattern": "main",       "stages": ["code_review", "test_generation"],                     "priority": 80},
        {"name": "master — 集成分支校验",        "pattern": "master",     "stages": ["code_review", "test_generation"],                     "priority": 79},
        {"name": "staging — 预发全量校验",       "pattern": "staging",    "stages": ["code_review", "test_generation", "auto_merge"],        "priority": 70},
        {"name": "production — 生产发布门禁",    "pattern": "production", "stages": ["code_review", "test_generation", "auto_merge"],        "priority": 60},
        {"name": "hotfix/* — 热修全量校验",      "pattern": "hotfix/*",   "stages": ["code_review", "test_generation", "auto_merge"],        "priority": 50},
        {"name": "默认兜底 — 仅审核",            "pattern": "*",          "stages": ["code_review"],                                         "priority": 1},
    ],
    "review_only": [
        {"name": "所有分支 — 仅审核",           "pattern": "*",          "stages": ["code_review"],                                         "priority": 1},
    ],
}


def _match(pattern: str, branch: str) -> bool:
    """Match branch against pattern using fnmatch wildcards."""
    return fnmatch.fnmatch(branch, pattern) or pattern == branch


def get_stages_sync(repo_id: int, branch: str, db: Session) -> list[str]:
    """
    Synchronous version for Celery tasks.
    Returns the list of stage names to execute for this branch.
    """
    from app.models.pipeline_rule import PipelineRule

    rules = db.execute(
        select(PipelineRule)
        .where(PipelineRule.repo_id == repo_id, PipelineRule.enabled == True)
        .order_by(PipelineRule.priority.desc())
    ).scalars().all()

    for rule in rules:
        if _match(rule.pattern, branch):
            stages = rule.stages or ["code_review"]
            logger.info("rule_engine.matched",
                        rule=rule.name, branch=branch, stages=stages)
            return stages

    # No rule matched — minimal fallback
    logger.info("rule_engine.no_match", branch=branch, fallback=["code_review"])
    return ["code_review"]
