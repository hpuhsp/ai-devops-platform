"""
Repair Agent — analyzes test failures and generates fixes using LLM.
Supports iterative repair loop (max rounds configurable).
"""
import json
import structlog
from dataclasses import dataclass, field

from .validator_agent import ValidationResult, TestFailure

logger = structlog.get_logger()

REPAIR_SYSTEM_PROMPT = """你是一位资深测试修复工程师。你的任务是修复失败的单元测试代码。

分析失败信息后，按照以下策略修复：
1. ImportError / ModuleNotFoundError → 修正 import 路径，或添加必要的 mock.patch
2. AssertionError → 分析期望值 vs 实际值，调整断言或修正 mock 返回值
3. AttributeError → 检查对象结构，修正属性名或添加 mock 属性
4. TypeError → 检查函数签名，修正参数传递
5. NameError → 补充缺失的变量定义或 import
6. SyntaxError / IndentationError → 修正语法

修复原则：
- 只修改测试代码，不修改被测代码
- 保持测试意图不变，只修正执行错误
- 优先使用 mock 隔离外部依赖
- 保持代码风格与原始测试一致

输出格式（严格 JSON）：
{
  "repaired_files": [
    {
      "path": "tests/test_xxx.py",
      "content": "完整的修复后测试文件内容",
      "fix_description": "简述修复了什么"
    }
  ],
  "repair_summary": "总体修复说明",
  "confidence": 0.85
}"""


@dataclass
class RepairAction:
    round_number: int
    file_path: str
    fix_description: str
    confidence: float = 0.0


@dataclass
class RepairResult:
    success: bool
    repaired_files: list[dict] = field(default_factory=list)
    actions: list[RepairAction] = field(default_factory=list)
    summary: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "repaired_files": self.repaired_files,
            "actions": [
                {
                    "round": a.round_number,
                    "file": a.file_path,
                    "fix": a.fix_description,
                    "confidence": a.confidence,
                }
                for a in self.actions
            ],
            "summary": self.summary,
        }


class RepairAgent:
    """LLM-based test repair agent. Analyzes failures and generates fixed test code."""

    async def repair(
        self,
        engine,
        validation_result: ValidationResult,
        test_files: list[dict],
        round_number: int = 1,
        context_hint: str = "",
    ) -> RepairResult:
        """
        Attempt to repair failed tests using LLM analysis.

        Args:
            engine: AI engine for LLM calls
            validation_result: Parsed test execution result with failures
            test_files: List of {"path": str, "content": str} for current test files
            round_number: Current repair round (for logging/tracking)
            context_hint: Optional extra context (target function signatures, etc.)

        Returns:
            RepairResult with repaired file contents
        """
        if not validation_result.failures:
            return RepairResult(success=True, summary="No failures to repair")

        repairable = [f for f in validation_result.failures if f.repairable]
        if not repairable:
            return RepairResult(
                success=False,
                summary="All failures are non-repairable (Timeout/Memory/System errors)",
            )

        user_prompt = self._build_repair_prompt(repairable, test_files, context_hint)

        try:
            response = await engine.complete_with_system(REPAIR_SYSTEM_PROMPT, user_prompt)
        except Exception as exc:
            logger.error("repair_agent.llm_failed", round=round_number, error=str(exc))
            return RepairResult(success=False, summary=f"LLM call failed: {exc}")

        try:
            data = json.loads(response.content)
        except (json.JSONDecodeError, ValueError):
            logger.warning("repair_agent.parse_failed", round=round_number)
            return RepairResult(
                success=False,
                summary="Failed to parse LLM repair output as JSON",
                prompt_tokens=response.prompt_tokens,
                completion_tokens=response.completion_tokens,
            )

        repaired_files = data.get("repaired_files", [])
        if not repaired_files:
            return RepairResult(
                success=False,
                summary="LLM returned no repaired files",
                prompt_tokens=response.prompt_tokens,
                completion_tokens=response.completion_tokens,
            )

        actions = []
        for rf in repaired_files:
            actions.append(RepairAction(
                round_number=round_number,
                file_path=rf.get("path", "unknown"),
                fix_description=rf.get("fix_description", ""),
                confidence=data.get("confidence", 0.5),
            ))

        return RepairResult(
            success=True,
            repaired_files=repaired_files,
            actions=actions,
            summary=data.get("repair_summary", "Repair applied"),
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
        )

    def _build_repair_prompt(
        self,
        failures: list[TestFailure],
        test_files: list[dict],
        context_hint: str,
    ) -> str:
        failures_text = self._format_failures(failures)
        files_text = self._format_test_files(test_files)

        parts = [
            "请修复以下失败的测试代码：\n",
            "## 失败信息\n",
            failures_text,
            "\n## 当前测试文件\n",
            files_text,
        ]

        if context_hint:
            parts.append(f"\n## 被测代码上下文\n{context_hint}\n")

        parts.append("\n请输出修复后的完整测试文件内容（JSON 格式）。")
        return "".join(parts)

    def _format_failures(self, failures: list[TestFailure]) -> str:
        lines = []
        for i, f in enumerate(failures, 1):
            lines.append(f"### 失败 {i}: `{f.test_name}`")
            lines.append(f"- 错误类型: {f.error_type}")
            lines.append(f"- 错误信息: {f.message}")
            if f.traceback:
                tb = f.traceback[:800]
                lines.append(f"- Traceback:\n```\n{tb}\n```")
            lines.append("")
        return "\n".join(lines)

    def _format_test_files(self, test_files: list[dict]) -> str:
        lines = []
        for tf in test_files:
            path = tf.get("path", "unknown")
            content = tf.get("content", "")
            if len(content) > 5000:
                content = content[:5000] + "\n# ... (truncated)"
            lines.append(f"### `{path}`\n```python\n{content}\n```\n")
        return "\n".join(lines)
