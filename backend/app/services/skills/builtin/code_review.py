"""
Built-in skill: Code Review
Performs AI-powered code review on a diff, returns findings by severity.
"""
import json
from app.services.skills.base import SkillBase, SkillContext, SkillResult

SYSTEM_PROMPT = """你是一位资深代码审查专家。请对提供的代码 diff 进行专业审查。

审查维度：
1. 安全漏洞（SQL 注入、XSS、硬编码密钥等）
2. 逻辑错误和潜在 Bug
3. 性能问题
4. 代码规范和可读性
5. 异常处理

输出格式（严格 JSON）：
{
  "summary": "一句话总结",
  "score": 85,
  "blocked": false,
  "findings": [
    {
      "severity": "critical|high|medium|low",
      "file": "path/to/file.py",
      "line": 42,
      "message": "问题描述",
      "suggestion": "修改建议"
    }
  ]
}

规则：
- blocked=true 当存在 critical 或 high 级别问题时
- score 范围 0-100，越高越好
- findings 按 severity 降序排列"""


class CodeReviewSkill(SkillBase):
    name = "code_review"
    stage_type = "code_review"
    description = "AI-powered code review on git diff"
    default_config = {
        "max_diff_lines": 5000,
        "effort": "medium",
    }

    async def execute(self, context: SkillContext, engine) -> SkillResult:
        diff = context.diff
        if not diff or len(diff.strip()) == 0:
            return SkillResult(success=True, summary="Empty diff, skipping review.")

        max_lines = self.get_config("max_diff_lines", 5000)
        diff_lines = diff.split("\n")
        if len(diff_lines) > max_lines:
            diff = "\n".join(diff_lines[:max_lines]) + f"\n\n[... diff truncated at {max_lines} lines ...]"

        user_content = f"""请审查以下代码变更：

**仓库**: {context.repo_url}
**分支**: {context.branch}
**提交**: {context.commit_sha[:8]}
**作者**: {context.author}
**MR标题**: {context.mr_title or 'N/A'}

**代码 Diff**:
```diff
{diff}
```"""

        response = await engine.complete_with_system(SYSTEM_PROMPT, user_content)

        try:
            data = json.loads(response.content)
        except (json.JSONDecodeError, ValueError):
            # LLM returned non-JSON, extract best-effort
            data = {
                "summary": response.content[:500],
                "score": 70,
                "blocked": False,
                "findings": [],
            }

        critical_count = sum(1 for f in data.get("findings", []) if f.get("severity") == "critical")
        high_count = sum(1 for f in data.get("findings", []) if f.get("severity") == "high")

        return SkillResult(
            success=True,
            summary=data.get("summary", "Review completed."),
            blocked=data.get("blocked", critical_count > 0),
            details={
                "score": data.get("score", 80),
                "findings": data.get("findings", []),
                "critical_count": critical_count,
                "high_count": high_count,
            },
            notifications=[{
                "type": "code_review_result",
                "data": data,
                "context": {
                    "repo": context.repo_url,
                    "branch": context.branch,
                    "commit": context.commit_sha[:8],
                    "author": context.author,
                    "mr_title": context.mr_title,
                },
            }],
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
        )
