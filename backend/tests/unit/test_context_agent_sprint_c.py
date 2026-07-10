"""
Sprint C tests: Context Agent project rules + historical defects + Generator prompt injection.
"""
import os
import sys
import tempfile
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Mock asyncpg to avoid import chain failures in test environment
sys.modules.setdefault("asyncpg", MagicMock())


# ── ContextAgent: _discover_project_rules ────────────────────────────────────

class TestDiscoverProjectRules:
    """Test project rules discovery from well-known file locations."""

    def _make_agent(self, tmpdir: str):
        from app.services.agents.context_agent import ContextAgent
        return ContextAgent(tmpdir)

    def test_ai_devops_rules_md(self, tmp_path):
        rules_dir = tmp_path / ".ai-devops"
        rules_dir.mkdir()
        (rules_dir / "rules.md").write_text("Use pytest fixtures for all DB deps.", encoding="utf-8")
        agent = self._make_agent(str(tmp_path))
        rules = agent._discover_project_rules()
        assert "pytest fixtures" in rules
        assert ".ai-devops" in rules
        assert "rules.md" in rules

    def test_ai_devops_test_rules_md(self, tmp_path):
        rules_dir = tmp_path / ".ai-devops"
        rules_dir.mkdir()
        (rules_dir / "test-rules.md").write_text("Always mock HTTP calls.", encoding="utf-8")
        agent = self._make_agent(str(tmp_path))
        rules = agent._discover_project_rules()
        assert "mock HTTP" in rules

    def test_rules_md_takes_priority_over_test_rules(self, tmp_path):
        rules_dir = tmp_path / ".ai-devops"
        rules_dir.mkdir()
        (rules_dir / "rules.md").write_text("Primary rules file.", encoding="utf-8")
        (rules_dir / "test-rules.md").write_text("Secondary test rules.", encoding="utf-8")
        agent = self._make_agent(str(tmp_path))
        rules = agent._discover_project_rules()
        assert "Primary rules file" in rules
        assert "Secondary test rules" not in rules

    def test_contributing_md_testing_section(self, tmp_path):
        contributing = tmp_path / "CONTRIBUTING.md"
        contributing.write_text(textwrap.dedent("""\
            # Contributing

            ## Development Setup
            Run make install first.

            ## Testing
            All tests must use pytest. Use fixtures for DB.

            ## Code Style
            Follow PEP8.
        """), encoding="utf-8")
        agent = self._make_agent(str(tmp_path))
        rules = agent._discover_project_rules()
        assert "pytest" in rules
        assert "CONTRIBUTING.md" in rules

    def test_contributing_no_testing_section(self, tmp_path):
        contributing = tmp_path / "CONTRIBUTING.md"
        contributing.write_text("# Contributing\n\nJust submit a PR.\n", encoding="utf-8")
        agent = self._make_agent(str(tmp_path))
        rules = agent._discover_project_rules()
        assert rules == ""

    def test_cursorrules_fallback(self, tmp_path):
        (tmp_path / ".cursorrules").write_text(
            "Always use pytest.\nUse mock for external APIs.\nKeep tests fast.",
            encoding="utf-8",
        )
        agent = self._make_agent(str(tmp_path))
        rules = agent._discover_project_rules()
        assert "pytest" in rules or "mock" in rules

    def test_no_rules_found(self, tmp_path):
        agent = self._make_agent(str(tmp_path))
        rules = agent._discover_project_rules()
        assert rules == ""

    def test_rules_truncated_at_2000_chars(self, tmp_path):
        rules_dir = tmp_path / ".ai-devops"
        rules_dir.mkdir()
        long_content = "A" * 3000
        (rules_dir / "rules.md").write_text(long_content, encoding="utf-8")
        agent = self._make_agent(str(tmp_path))
        rules = agent._discover_project_rules()
        assert len(rules) <= 2100  # 2000 + some overhead for header
        assert "truncated" in rules


# ── ContextAgent: _extract_section ───────────────────────────────────────────

class TestExtractSection:
    def _make_agent(self, tmpdir: str):
        from app.services.agents.context_agent import ContextAgent
        return ContextAgent(tmpdir)

    def test_extract_existing_section(self, tmp_path):
        agent = self._make_agent(str(tmp_path))
        text = "# Title\n\n## Testing\nUse pytest.\n\n## Deployment\nUse docker."
        result = agent._extract_section(text, "Testing")
        assert "pytest" in result
        assert "docker" not in result

    def test_extract_case_insensitive(self, tmp_path):
        agent = self._make_agent(str(tmp_path))
        text = "## testing guidelines\nFollow these rules."
        result = agent._extract_section(text, "Testing")
        assert "Follow these rules" in result

    def test_extract_nonexistent_section(self, tmp_path):
        agent = self._make_agent(str(tmp_path))
        text = "## Development\nSome content."
        result = agent._extract_section(text, "Testing")
        assert result is None


# ── ContextAgent: _extract_test_related ──────────────────────────────────────

class TestExtractTestRelated:
    def _make_agent(self, tmpdir: str):
        from app.services.agents.context_agent import ContextAgent
        return ContextAgent(tmpdir)

    def test_extracts_test_lines(self, tmp_path):
        agent = self._make_agent(str(tmp_path))
        text = "Use pytest for testing.\nAlways mock external services.\nKeep code clean."
        result = agent._extract_test_related(text)
        assert "pytest" in result
        assert "mock" in result
        assert "clean" not in result

    def test_no_test_related_lines(self, tmp_path):
        agent = self._make_agent(str(tmp_path))
        text = "Keep code clean.\nFollow PEP8.\nWrite docs."
        result = agent._extract_test_related(text)
        assert result == ""


# ── ContextAgent: scan_historical_defects ────────────────────────────────────

class TestScanHistoricalDefects:
    def _make_agent(self, tmpdir: str):
        from app.services.agents.context_agent import ContextAgent
        return ContextAgent(tmpdir)

    @patch("subprocess.run")
    def test_parses_git_log_output(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="abc1234 fix: handle null pointer in order.py\n"
                   "def5678 bug: timeout in http_client.py\n",
        )
        agent = self._make_agent(str(tmp_path))
        defects = agent.scan_historical_defects(["app/order.py"])
        assert len(defects) == 2
        assert defects[0]["commit"] == "abc1234"
        assert "null pointer" in defects[0]["message"]
        assert defects[0]["file"] == "app/order.py"

    @patch("subprocess.run")
    def test_empty_git_log(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        agent = self._make_agent(str(tmp_path))
        defects = agent.scan_historical_defects(["app/order.py"])
        assert defects == []

    @patch("subprocess.run")
    def test_git_error_handled(self, mock_run, tmp_path):
        mock_run.side_effect = OSError("git not found")
        agent = self._make_agent(str(tmp_path))
        defects = agent.scan_historical_defects(["app/order.py"])
        assert defects == []

    @patch("subprocess.run")
    def test_limits_to_15_defects(self, mock_run, tmp_path):
        lines = "\n".join(f"abc{i:04d} fix: bug #{i}" for i in range(20))
        mock_run.return_value = MagicMock(returncode=0, stdout=lines)
        agent = self._make_agent(str(tmp_path))
        defects = agent.scan_historical_defects(["app/order.py"])
        assert len(defects) <= 15

    @patch("subprocess.run")
    def test_skips_empty_file_paths(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        agent = self._make_agent(str(tmp_path))
        defects = agent.scan_historical_defects(["", ""])
        assert defects == []
        mock_run.assert_not_called()

    @patch("subprocess.run")
    def test_limits_target_files_to_5(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stdout="abc1234 fix: something\n")
        agent = self._make_agent(str(tmp_path))
        files = [f"app/file{i}.py" for i in range(10)]
        defects = agent.scan_historical_defects(files)
        assert mock_run.call_count == 5


# ── ContextAgent: build_context includes new fields ──────────────────────────

class TestBuildContextNewFields:
    def _make_agent(self, tmpdir: str):
        from app.services.agents.context_agent import ContextAgent
        return ContextAgent(tmpdir)

    def test_build_context_has_project_rules_key(self, tmp_path):
        agent = self._make_agent(str(tmp_path))
        ctx = agent.build_context([])
        assert "project_rules" in ctx
        assert isinstance(ctx["project_rules"], str)

    def test_build_context_has_historical_defects_key(self, tmp_path):
        agent = self._make_agent(str(tmp_path))
        ctx = agent.build_context([])
        assert "historical_defects" in ctx
        assert isinstance(ctx["historical_defects"], list)

    @patch.object(
        __import__("app.services.agents.context_agent", fromlist=["ContextAgent"]).ContextAgent,
        "scan_historical_defects",
        return_value=[{"commit": "abc", "message": "fix: bug", "file": "app/x.py"}],
    )
    def test_build_context_populates_defects(self, mock_scan, tmp_path):
        agent = self._make_agent(str(tmp_path))
        targets = [{"file": "app/x.py", "functions": ["do_stuff"]}]
        source = tmp_path / "app" / "x.py"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("def do_stuff():\n    pass\n", encoding="utf-8")
        ctx = agent.build_context(targets)
        assert len(ctx["historical_defects"]) == 1
        assert ctx["historical_defects"][0]["commit"] == "abc"


# ── TestGenerationSkill: prompt injection ────────────────────────────────────

class TestGeneratorPromptInjection:
    def _make_skill(self):
        from app.services.skills.builtin.test_generation import TestGenerationSkill
        return TestGenerationSkill()

    def _make_context(self):
        ctx = MagicMock()
        ctx.repo_url = "https://git.example.com/repo"
        ctx.branch = "feature/x"
        ctx.changed_files = ["app/order.py"]
        return ctx

    def test_prompt_includes_project_rules(self):
        skill = self._make_skill()
        ctx = self._make_context()
        context_data = {
            "project_test_framework": "pytest",
            "project_rules": "## Rules\nAlways mock DB calls.",
            "historical_defects": [],
        }
        prompt = skill._build_user_prompt(ctx, "diff --git a/...", context_data)
        assert "项目测试规则" in prompt
        assert "Always mock DB calls" in prompt

    def test_prompt_includes_historical_defects(self):
        skill = self._make_skill()
        ctx = self._make_context()
        context_data = {
            "project_test_framework": "pytest",
            "project_rules": "",
            "historical_defects": [
                {"commit": "abc1234", "message": "fix: null pointer", "file": "app/order.py"},
                {"commit": "def5678", "message": "bug: timeout", "file": "app/http.py"},
            ],
        }
        prompt = skill._build_user_prompt(ctx, "diff --git a/...", context_data)
        assert "历史缺陷记录" in prompt
        assert "null pointer" in prompt
        assert "timeout" in prompt

    def test_prompt_omits_rules_when_empty(self):
        skill = self._make_skill()
        ctx = self._make_context()
        context_data = {
            "project_test_framework": "pytest",
            "project_rules": "",
            "historical_defects": [],
        }
        prompt = skill._build_user_prompt(ctx, "diff --git a/...", context_data)
        assert "项目测试规则" not in prompt
        assert "历史缺陷记录" not in prompt

    def test_prompt_no_context_data(self):
        skill = self._make_skill()
        ctx = self._make_context()
        prompt = skill._build_user_prompt(ctx, "diff --git a/...", None)
        assert "无 Context Agent 上下文" in prompt

    def test_prompt_defects_limited_to_10(self):
        skill = self._make_skill()
        ctx = self._make_context()
        defects = [
            {"commit": f"abc{i:04d}", "message": f"fix: bug #{i}", "file": "app/x.py"}
            for i in range(15)
        ]
        context_data = {
            "project_test_framework": "pytest",
            "project_rules": "",
            "historical_defects": defects,
        }
        prompt = skill._build_user_prompt(ctx, "diff --git a/...", context_data)
        assert "bug #9" in prompt
        assert "bug #14" not in prompt
