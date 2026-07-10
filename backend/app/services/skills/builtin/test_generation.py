"""
Built-in skill: Test Generation
AI generates unit tests for changed code, runs them in a Git WorkTree.
Enhanced in V2 to accept Context Agent output for richer prompt.
"""
import json
from app.services.skills.base import SkillBase, SkillContext, SkillResult

SYSTEM_PROMPT = """你是一位资深测试工程师。请根据提供的代码变更和上下文，生成对应的单元测试。

要求：
1. 使用与项目相同的测试框架（从上下文推断，默认 pytest）
2. 覆盖正常路径、边界条件、异常路径
3. 测试代码要独立、可运行，不依赖外部服务（使用 mock）
4. 测试命名清晰，注释说明测试意图
5. 如果提供了已有测试样例，遵循其风格（命名、fixture 使用、import 方式）
6. Mock 候选列表中的依赖应 mock，避免 mock 被测函数本身的逻辑

输出格式（严格 JSON）：
{
  "framework": "pytest",
  "files": [
    {
      "path": "tests/test_xxx.py",
      "content": "完整的测试文件内容",
      "description": "测试文件说明",
      "covers_functions": ["func1", "func2"],
      "test_cases": ["test_xxx_success", "test_xxx_error"]
    }
  ],
  "run_command": "pytest tests/ -v",
  "estimated_coverage_delta": "+5%",
  "quality_hints": {
    "boundary_covered": true,
    "exception_covered": true,
    "mock_minimal": true
  }
}"""


class TestGenerationSkill(SkillBase):
    name = "test_generation"
    stage_type = "generator"
    description = "AI generates unit tests for changed code using Git WorkTree isolation"
    default_config = {
        "max_diff_lines": 3000,
        "run_tests": True,
    }

    async def execute(self, context: SkillContext, engine) -> SkillResult:
        diff = context.diff
        if not diff or len(diff.strip()) == 0:
            return SkillResult(success=True, summary="Empty diff, no tests to generate.")

        max_lines = self.get_config("max_diff_lines", 3000)
        diff_lines = diff.split("\n")
        if len(diff_lines) > max_lines:
            diff = "\n".join(diff_lines[:max_lines])

        context_data = context.extra.get("context_agent_output")
        user_content = self._build_user_prompt(context, diff, context_data)

        response = await engine.complete_with_system(SYSTEM_PROMPT, user_content)

        try:
            data = json.loads(response.content)
        except (json.JSONDecodeError, ValueError):
            data = {
                "framework": "unknown",
                "files": [],
                "run_command": "",
                "estimated_coverage_delta": "unknown",
                "quality_hints": {},
            }

        run_result = None
        if self.get_config("run_tests", True) and data.get("files"):
            run_result = {"status": "pending_worktree_execution"}

        return SkillResult(
            success=True,
            summary=f"Generated {len(data.get('files', []))} test file(s) | Framework: {data.get('framework')}",
            details={
                "framework": data.get("framework"),
                "generated_files": data.get("files", []),
                "run_command": data.get("run_command"),
                "estimated_coverage_delta": data.get("estimated_coverage_delta"),
                "quality_hints": data.get("quality_hints", {}),
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

    def _build_user_prompt(self, context: SkillContext, diff: str, context_data: dict | None) -> str:
        """Build user prompt with optional rich context from Context Agent."""
        parts = [
            f"**仓库**: {context.repo_url}",
            f"**分支**: {context.branch}",
            f"**变更文件**: {', '.join(context.changed_files[:20])}",
        ]

        if context_data:
            framework = context_data.get("project_test_framework", "pytest")
            parts.append(f"\n**项目测试框架**: {framework}")

            fixtures = context_data.get("fixtures_available", [])
            if fixtures:
                parts.append(f"**可用 Fixtures**: {', '.join(fixtures[:10])}")

            target_fns = context_data.get("target_functions", [])
            if target_fns:
                parts.append("\n**目标函数详情**:")
                for tf in target_fns[:5]:
                    parts.append(f"\n--- `{tf['function']}` (file: {tf['file']}) ---")
                    parts.append(f"```python\n{tf.get('source_code', '# unavailable')}\n```")
                    if tf.get("callers"):
                        parts.append(f"调用者: {', '.join(tf['callers'][:5])}")
                    if tf.get("mock_candidates"):
                        parts.append(f"建议 Mock: {', '.join(tf['mock_candidates'][:5])}")

            style = context_data.get("test_style_example", "")
            if style:
                parts.append(f"\n**已有测试风格参考**:\n```python\n{style[:1500]}\n```")

            rules = context_data.get("project_rules", "")
            if rules:
                parts.append(f"\n**项目测试规则**:\n{rules}")

            defects = context_data.get("historical_defects", [])
            if defects:
                parts.append("\n**历史缺陷记录（请针对性覆盖）**:")
                for d in defects[:10]:
                    parts.append(f"- `{d.get('file', '')}`: {d.get('message', '')} ({d.get('commit', '')})")
        else:
            parts.append("\n（无 Context Agent 上下文，基于 diff 生成）")

        parts.append(f"\n**代码 Diff**:\n```diff\n{diff}\n```")
        return "\n".join(parts)

