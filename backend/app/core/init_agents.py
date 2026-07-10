"""Initialize default system agents on application startup."""
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent

logger = structlog.get_logger()

DEFAULT_AGENTS = [
    {
        "name": "默认代码审查",
        "description": "系统默认代码审查 Agent — 审查 diff 中的安全和质量问题",
        "stage_type": "code_review",
        "skill_name": "code_review",
    },
    {
        "name": "默认变更智能",
        "description": "系统默认变更智能 Agent — 分析变更是否需要测试",
        "stage_type": "change_intelligence",
        "skill_name": "change_intelligence",
    },
    {
        "name": "默认测试生成",
        "description": "系统默认测试生成 Agent — 基于上下文生成测试用例",
        "stage_type": "generator",
        "skill_name": "test_generation",
    },
    {
        "name": "默认验证修复",
        "description": "系统默认验证修复 Agent — WorkTree 沙箱执行+自动修复",
        "stage_type": "validate_repair",
        "skill_name": "validate_repair",
    },
    {
        "name": "默认质量评分",
        "description": "系统默认质量评分 Agent — 4 维度评估测试质量",
        "stage_type": "quality_scorer",
        "skill_name": "quality_scorer",
    },
]


async def init_default_agents(db: AsyncSession):
    """Create default system agents if they don't exist."""
    created = 0
    for spec in DEFAULT_AGENTS:
        existing = (
            await db.execute(
                select(Agent).where(
                    Agent.stage_type == spec["stage_type"],
                    Agent.is_system == True,
                )
            )
        ).scalar_one_or_none()

        if existing:
            continue

        agent = Agent(
            name=spec["name"],
            description=spec["description"],
            stage_type=spec["stage_type"],
            skill_type="builtin",
            skill_name=spec["skill_name"],
            model_id=None,
            skill_config={},
            model_config={},
            policy_config={},
            enabled=True,
            is_system=True,
        )
        db.add(agent)
        created += 1

    if created:
        await db.commit()
        logger.info("init_agents.created_defaults", count=created)
