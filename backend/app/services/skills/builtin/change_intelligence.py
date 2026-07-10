"""
Built-in skill: Change Intelligence
Decides whether AI test generation is needed based on diff analysis,
CodeGraph impact radius, and historical defect data.
"""
import json
import shutil
import subprocess
from pathlib import Path

from app.core.config import settings
from app.services.skills.base import SkillBase, SkillContext, SkillResult
import structlog

logger = structlog.get_logger()

SKIP_EXTENSIONS = set(settings.CHANGE_INTEL_SKIP_EXTENSIONS)

SYSTEM_PROMPT = """你是一位代码变更影响分析专家。请根据以下信息判断是否需要为本次变更生成单元测试。

分析维度：
1. 变更是否涉及业务逻辑（新增/修改函数、核心分支逻辑、错误处理）
2. 变更的影响面（被多少调用者依赖）
3. 变更的风险等级（高：支付/权限/数据写入；中：通用业务；低：工具类/格式化）

输出格式（严格 JSON）：
{
  "need_test": true,
  "risk_level": "high|medium|low|none",
  "reason": "中文简述判断原因",
  "targets": [
    {"file": "path/to/file.py", "functions": ["func1", "func2"]}
  ],
  "skip_reason": null
}

规则：
- 纯文档/配置/删除变更 → need_test=false, risk_level="none"
- 新增业务方法 → need_test=true, risk_level 至少 "medium"
- targets 只列出需要被测试覆盖的函数，不要列配置类/数据类
- 如果 CodeGraph 影响面数据存在，结合调用者数量评估风险"""


class ChangeIntelligenceSkill(SkillBase):
    name = "change_intelligence"
    stage_type = "change_intelligence"
    description = "Analyze code changes to decide if test generation is needed"
    default_config = {
        "max_diff_lines": 3000,
    }

    async def execute(self, context: SkillContext, engine) -> SkillResult:
        changed_files = context.changed_files or []

        fast_skip = self._fast_path_skip(changed_files, context.diff)
        if fast_skip:
            return SkillResult(
                success=True,
                summary=fast_skip["skip_reason"],
                details=fast_skip,
            )

        codegraph_data = self._run_codegraph(context)
        historical_defects = context.extra.get("historical_defects", 0)

        user_content = self._build_prompt(context, codegraph_data, historical_defects)
        response = await engine.complete_with_system(SYSTEM_PROMPT, user_content)

        try:
            data = json.loads(response.content)
        except (json.JSONDecodeError, ValueError):
            data = {
                "need_test": True,
                "risk_level": "medium",
                "reason": "LLM 返回解析失败，默认生成测试",
                "targets": [{"file": f, "functions": []} for f in changed_files if f.endswith(".py")],
                "skip_reason": None,
            }

        data["impact_radius"] = len(codegraph_data.get("affected_symbols", []))
        data["historical_defects"] = historical_defects
        data["codegraph_available"] = codegraph_data.get("available", False)

        return SkillResult(
            success=True,
            summary=data.get("reason", "Analysis complete"),
            details=data,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
        )

    def _fast_path_skip(self, changed_files: list[str], diff: str) -> dict | None:
        """Return skip-result dict if changes are trivially non-testable."""
        if not diff or not diff.strip():
            return self._skip_result("diff 为空")

        if not changed_files:
            return self._skip_result("无修改文件")

        all_doc_or_config = all(
            Path(f).suffix.lower() in SKIP_EXTENSIONS for f in changed_files
        )
        if all_doc_or_config:
            return self._skip_result("纯文档/配置变更，无需测试")

        all_deleted = all(
            line.startswith("-") and not line.startswith("---")
            for line in diff.split("\n")
            if line.strip() and not line.startswith("@@") and not line.startswith("diff")
        )
        if all_deleted and diff.strip():
            return self._skip_result("仅删除代码，无新增逻辑")

        return None

    def _skip_result(self, reason: str) -> dict:
        return {
            "need_test": False,
            "risk_level": "none",
            "reason": reason,
            "targets": [],
            "impact_radius": 0,
            "historical_defects": 0,
            "skip_reason": reason,
            "codegraph_available": False,
        }

    def _run_codegraph(self, context: SkillContext) -> dict:
        """Query pre-built codegraph.db via CLI. No runtime indexing (zero intrusion)."""
        if not shutil.which("codegraph"):
            logger.info("codegraph.not_installed")
            return {"available": False, "affected_symbols": []}

        worktree_path = context.extra.get("worktree_path")
        if not worktree_path:
            return {"available": False, "affected_symbols": []}

        db_rel_path = context.extra.get("codegraph_db_path", "codegraph.db")
        db_path = Path(worktree_path) / db_rel_path
        if not db_path.exists():
            logger.info("codegraph.db_not_found", path=str(db_path))
            return {"available": False, "affected_symbols": []}

        try:
            changed_input = "\n".join(context.changed_files or [])
            result = subprocess.run(
                ["codegraph", "diff-impact", "--db", str(db_path), "--format", "json"],
                input=changed_input,
                cwd=worktree_path,
                capture_output=True, text=True, timeout=15,
            )

            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout)
                data["available"] = True
                return data

        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as exc:
            logger.warning("codegraph.query_failed", error=str(exc))

        return {"available": False, "affected_symbols": []}

    def _build_prompt(self, context: SkillContext, codegraph_data: dict, historical_defects: int) -> str:
        diff = context.diff
        max_lines = self.get_config("max_diff_lines", 3000)
        diff_lines = diff.split("\n")
        if len(diff_lines) > max_lines:
            diff = "\n".join(diff_lines[:max_lines]) + f"\n\n[... truncated at {max_lines} lines ...]"

        parts = [
            f"**修改文件**: {', '.join(context.changed_files[:30])}",
            f"**分支**: {context.branch}",
            f"**作者**: {context.author}",
            f"**历史缺陷数（近30天同文件）**: {historical_defects}",
        ]

        if codegraph_data.get("available"):
            symbols = codegraph_data.get("affected_symbols", [])
            if symbols:
                symbol_desc = "\n".join(
                    f"  - {s.get('symbol', '?')} (file: {s.get('file', '?')}, callers: {len(s.get('callers', []))})"
                    for s in symbols[:10]
                )
                parts.append(f"**CodeGraph 影响面分析**:\n{symbol_desc}")
            else:
                parts.append("**CodeGraph**: 无受影响符号")
        else:
            parts.append("**CodeGraph**: 未安装或不可用（仅基于 diff 分析）")

        parts.append(f"\n**代码 Diff**:\n```diff\n{diff}\n```")

        return "\n".join(parts)
