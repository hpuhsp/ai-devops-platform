"""
Skill Registry — register, load, and execute skills.
Supports built-in skills and project-level .ai-skills.yml overrides.
"""
import importlib
import yaml
import os
from pathlib import Path
from typing import Type
import structlog

from .base import SkillBase, SkillContext, SkillResult

logger = structlog.get_logger()


class SkillRegistry:
    STAGE_DESCRIPTIONS = {
        "code_review": "代码审查 — 审查diff中的安全和质量问题",
        "change_intelligence": "变更智能 — 分析变更是否需要测试",
        "generator": "单元测试生成 — 基于上下文生成测试用例",
        "validate_repair": "验证修复 — WorkTree沙箱执行+自动修复",
        "quality_scorer": "质量评分 — 4维度评估测试质量",
    }

    def __init__(self):
        self._skills: dict[str, Type[SkillBase]] = {}
        self._load_builtin_skills()

    def _load_builtin_skills(self):
        """Auto-load all built-in skills from the builtin/ package."""
        builtin_dir = Path(__file__).parent / "builtin"
        if builtin_dir.exists():
            for f in builtin_dir.glob("*.py"):
                if f.stem.startswith("_"):
                    continue
                module_path = f"app.services.skills.builtin.{f.stem}"
                try:
                    mod = importlib.import_module(module_path)
                    for attr in dir(mod):
                        cls = getattr(mod, attr)
                        if (
                            isinstance(cls, type)
                            and issubclass(cls, SkillBase)
                            and cls is not SkillBase
                            and hasattr(cls, "name")
                            and cls.name != "base"
                        ):
                            self.register(cls)
                except Exception as e:
                    logger.warning("skill.load_failed", module=module_path, error=str(e))

    def register(self, skill_cls: Type[SkillBase]):
        self._skills[skill_cls.name] = skill_cls
        logger.info("skill.registered", name=skill_cls.name)

    def get(self, name: str, config: dict = None) -> SkillBase | None:
        cls = self._skills.get(name)
        if cls is None:
            return None
        return cls(config)

    def list_skills(self) -> list[str]:
        return list(self._skills.keys())

    def list_skills_metadata(self) -> list[dict]:
        """Return metadata for all registered skills."""
        return [cls.metadata() for cls in self._skills.values()]

    def list_by_stage(self, stage_type: str) -> list[dict]:
        """Return skills available for a given stage type."""
        return [cls.metadata() for cls in self._skills.values() if cls.stage_type == stage_type]

    def get_stage_types(self) -> list[dict]:
        """Return all stage types with descriptions."""
        return [{"value": k, "label": v} for k, v in self.STAGE_DESCRIPTIONS.items()]

    def load_project_config(self, config_path: str) -> dict:
        """Load .ai-skills.yml from project root (if present)."""
        if not os.path.exists(config_path):
            return {}
        with open(config_path) as f:
            return yaml.safe_load(f) or {}

    async def execute(
        self,
        skill_name: str,
        context: SkillContext,
        engine,
        skill_config: dict = None,
    ) -> SkillResult:
        skill = self.get(skill_name, skill_config)
        if skill is None:
            logger.error("skill.not_found", name=skill_name)
            return SkillResult(
                success=False,
                summary=f"Skill '{skill_name}' not found in registry.",
            )

        logger.info("skill.executing", name=skill_name, repo=context.repo_url)
        try:
            result = await skill.execute(context, engine)
            logger.info(
                "skill.completed",
                name=skill_name,
                success=result.success,
                blocked=result.blocked,
            )
            return result
        except Exception as e:
            logger.exception("skill.execution_error", name=skill_name, error=str(e))
            return SkillResult(
                success=False,
                summary=f"Skill '{skill_name}' failed: {str(e)}",
            )


skill_registry = SkillRegistry()
