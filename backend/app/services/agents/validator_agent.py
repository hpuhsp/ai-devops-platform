"""
Validator Agent — executes tests in WorkTree and parses pytest output.
Determines pass/fail details and whether failures are repairable.
"""
import re
from dataclasses import dataclass, field


@dataclass
class TestFailure:
    test_name: str
    error_type: str
    message: str
    traceback: str = ""
    repairable: bool = True


@dataclass
class ValidationResult:
    status: str  # "all_pass" | "partial_fail" | "all_fail" | "error"
    total: int = 0
    passed: int = 0
    failed: int = 0
    failures: list[TestFailure] = field(default_factory=list)
    execution_time_ms: int = 0
    can_repair: bool = False
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "failures": [
                {
                    "test_name": f.test_name,
                    "error_type": f.error_type,
                    "message": f.message,
                    "traceback": f.traceback[:500],
                    "repairable": f.repairable,
                }
                for f in self.failures
            ],
            "execution_time_ms": self.execution_time_ms,
            "can_repair": self.can_repair,
        }


NON_REPAIRABLE_ERRORS = {"TimeoutError", "MemoryError", "SystemExit", "KeyboardInterrupt"}


class ValidatorAgent:
    """Parse pytest output and classify failures."""

    def parse_worktree_result(self, worktree_result: dict, duration_ms: int = 0) -> ValidationResult:
        """
        Parse the result dict from WorkTree.run_command().

        Args:
            worktree_result: {"exit_code": int, "stdout": str, "stderr": str, "success": bool}
            duration_ms: total execution time
        """
        stdout = worktree_result.get("stdout", "")
        stderr = worktree_result.get("stderr", "")
        exit_code = worktree_result.get("exit_code", -1)

        if worktree_result.get("status") == "error":
            return ValidationResult(
                status="error",
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                execution_time_ms=duration_ms,
            )

        total, passed, failed = self._parse_summary_line(stdout)
        failures = self._parse_failures(stdout + "\n" + stderr)

        if failed == 0 and exit_code == 0:
            status = "all_pass"
        elif passed > 0:
            status = "partial_fail"
        else:
            status = "all_fail"

        can_repair = (
            failed > 0
            and all(f.repairable for f in failures)
            and failed <= 10
        )

        return ValidationResult(
            status=status,
            total=total,
            passed=passed,
            failed=failed,
            failures=failures,
            execution_time_ms=duration_ms,
            can_repair=can_repair,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
        )

    def _parse_summary_line(self, stdout: str) -> tuple[int, int, int]:
        """Extract counts from pytest summary line like '3 passed, 2 failed'."""
        passed = 0
        failed = 0

        m_passed = re.search(r"(\d+) passed", stdout)
        if m_passed:
            passed = int(m_passed.group(1))

        m_failed = re.search(r"(\d+) failed", stdout)
        if m_failed:
            failed = int(m_failed.group(1))

        m_error = re.search(r"(\d+) error", stdout)
        if m_error:
            failed += int(m_error.group(1))

        total = passed + failed
        return total, passed, failed

    def _parse_failures(self, output: str) -> list[TestFailure]:
        """Extract individual test failures from pytest verbose output."""
        failures = []
        failure_blocks = re.split(r"_{3,} ([\w:.\[\]]+) _{3,}", output)

        i = 1
        while i < len(failure_blocks) - 1:
            test_name = failure_blocks[i].strip()
            block = failure_blocks[i + 1] if i + 1 < len(failure_blocks) else ""
            error_type = self._classify_error(block)
            message = self._extract_message(block)
            repairable = error_type not in NON_REPAIRABLE_ERRORS

            failures.append(TestFailure(
                test_name=test_name,
                error_type=error_type,
                message=message,
                traceback=block[:1000],
                repairable=repairable,
            ))
            i += 2

        if not failures and "FAILED" in output:
            for m in re.finditer(r"FAILED (.+?) - (.+)", output):
                test_name = m.group(1).strip()
                message = m.group(2).strip()
                error_type = self._classify_error(message)
                failures.append(TestFailure(
                    test_name=test_name,
                    error_type=error_type,
                    message=message,
                    repairable=error_type not in NON_REPAIRABLE_ERRORS,
                ))

        return failures

    def _classify_error(self, text: str) -> str:
        """Classify error type from traceback text."""
        error_patterns = [
            (r"ImportError", "ImportError"),
            (r"ModuleNotFoundError", "ModuleNotFoundError"),
            (r"AssertionError", "AssertionError"),
            (r"AttributeError", "AttributeError"),
            (r"TypeError", "TypeError"),
            (r"NameError", "NameError"),
            (r"ValueError", "ValueError"),
            (r"KeyError", "KeyError"),
            (r"TimeoutError", "TimeoutError"),
            (r"MemoryError", "MemoryError"),
            (r"SyntaxError", "SyntaxError"),
            (r"IndentationError", "IndentationError"),
            (r"FileNotFoundError", "FileNotFoundError"),
        ]
        for pattern, name in error_patterns:
            if re.search(pattern, text):
                return name
        return "UnknownError"

    def _extract_message(self, block: str) -> str:
        """Extract the most relevant error message from a failure block."""
        lines = block.strip().split("\n")
        for line in reversed(lines):
            line = line.strip()
            if line.startswith(("E ", "> ")):
                return line[2:].strip()[:200]
            if "Error:" in line or "assert" in line.lower():
                return line.strip()[:200]
        return lines[-1].strip()[:200] if lines else "Unknown error"
