"""
Built-in skill: Test Generation
AI generates unit tests for changed code, runs them in a Git WorkTree.
"""
import json
from app.services.skills.base import SkillBase, SkillContext, SkillResult

SYSTEM_PROMPT = """你是一位资深测试工程师。请根据提供的代码变更，生成对应的单元测试。

要求：
1. 使用与项目相同的测试框架（从代码推断：Python→pytest, Java→JUnit5, JS→Jest/Vitest）
2. 覆盖正常路径、边界条件、异常路径
3. 测试代码要独立、可运行，不依赖外部服务（使用 mock）
4. 测试命名清晰，注释说明测试意图

输出格式（严格 JSON）：
{
  "framework": "pytest",
  "files": [
    {
      "path": "tests/test_user_service.py",
      "content": "完整的测试文件内容",
      "description": "测试文件说明"
    }
  ],
  "run_command": "pytest tests/ -v",
  "estimated_coverage_delta": "+5%"
}"""


class TestGenerationSkill(SkillBase):
    name = "test_generation"
    description = "AI generates unit tests for changed code using Git WorkTree isolation"
    default_config = {
        "max_diff_lines": 3000,
        "run_tests": True,      # whether to actually run tests in WorkTree
    }

    async def execute(self, context: SkillContext, engine) -> SkillResult:
        diff = context.diff
        if not diff or len(diff.strip()) == 0:
            return SkillResult(success=True, summary="Empty diff, no tests to generate.")

        max_lines = self.get_config("max_diff_lines", 3000)
        diff_lines = diff.split("\n")
        if len(diff_lines) > max_lines:
            diff = "\n".join(diff_lines[:max_lines])

        changed_files_str = "\n".join(context.changed_files[:20])

        user_content = f"""请为以下代码变更生成单元测试：

**仓库**: {context.repo_url}
**分支**: {context.branch}
**变更文件**:
{changed_files_str}

**代码 Diff**:
```diff
{diff}
```"""

        response = await engine.complete_with_system(SYSTEM_PROMPT, user_content)

        try:
            data = json.loads(response.content)
        except (json.JSONDecodeError, ValueError):
            data = {
                "framework": "unknown",
                "files": [],
                "run_command": "",
                "estimated_coverage_delta": "unknown",
            }

        run_result = None
        if self.get_config("run_tests", True) and data.get("files"):
            # WorkTree execution happens in the task layer (not here)
            # This flag tells the task runner to execute tests
            run_result = {"status": "pending_worktree_execution"}

        return SkillResult(
            success=True,
            summary=f"Generated {len(data.get('files', []))} test file(s) | Framework: {data.get('framework')}",
            details={
                "framework": data.get("framework"),
                "generated_files": data.get("files", []),
                "run_command": data.get("run_command"),
                "estimated_coverage_delta": data.get("estimated_coverage_delta"),
                "worktree_run": run_result,
            },
            notifications=[{
                "type": "test_generation_result",
                "data": data,
                "context": {
                    "repo": context.repo_url,
                    "branch": context.branch,
                    "commit": context.commit_sha[:8],
                    "files_count": len(data.get("files", [])),
                },
            }],
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
        )
