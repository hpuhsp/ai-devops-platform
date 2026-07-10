"""
Context Agent — builds rich context for the Generator Agent.
Pure file-system scanning + CodeGraph CLI queries. No LLM calls.
"""
import ast
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import structlog

logger = structlog.get_logger()


class ContextAgent:
    """Collect project context to feed into test generation prompt."""

    def __init__(self, worktree_path: str, codegraph_db_path: str = "codegraph.db"):
        self.root = Path(worktree_path)
        self.db_path = self.root / codegraph_db_path
        self.codegraph_available = (
            shutil.which("codegraph") is not None and self.db_path.exists()
        )

    def build_context(self, targets: list[dict]) -> dict:
        """
        Build full context for test generation.

        Args:
            targets: from change_intelligence output, e.g.
                [{"file": "app/services/order.py", "functions": ["create_order"]}]

        Returns:
            Context dict matching spec 3.2 output schema.
        """
        framework = self._detect_test_framework()
        fixtures = self._discover_fixtures()
        style_example = self._find_test_style_example()
        target_functions = []

        for target in targets:
            file_path = target.get("file", "")
            functions = target.get("functions", [])
            full_path = self.root / file_path

            if not full_path.exists():
                continue

            source_code = full_path.read_text(encoding="utf-8", errors="ignore")
            imports = self._extract_imports(source_code)
            existing_test = self._find_existing_test(file_path)

            for func_name in functions:
                func_source = self._extract_function_source(source_code, func_name)
                callers, callees = self._query_codegraph(func_name, file_path)

                target_functions.append({
                    "file": file_path,
                    "function": func_name,
                    "source_code": func_source or f"# Could not extract {func_name}",
                    "imports": imports,
                    "existing_test_file": existing_test,
                    "callers": callers,
                    "callees": callees,
                    "mock_candidates": self._infer_mock_candidates(callees),
                })

        return {
            "target_functions": target_functions,
            "project_test_framework": framework,
            "fixtures_available": fixtures,
            "test_style_example": style_example,
            "dependencies": self._detect_dependencies(),
            "codegraph_available": self.codegraph_available,
            "project_rules": self._discover_project_rules(),
            "historical_defects": self.scan_historical_defects(
                [t.get("file", "") for t in targets]
            ),
        }

    def _detect_test_framework(self) -> str:
        """Detect pytest/unittest from project config files."""
        if (self.root / "pytest.ini").exists():
            return "pytest"
        if (self.root / "setup.cfg").exists():
            content = (self.root / "setup.cfg").read_text(errors="ignore")
            if "[tool:pytest]" in content:
                return "pytest"
        if (self.root / "pyproject.toml").exists():
            content = (self.root / "pyproject.toml").read_text(errors="ignore")
            if "[tool.pytest" in content:
                return "pytest"
        if list(self.root.rglob("conftest.py")):
            return "pytest"
        return "pytest"

    def _discover_fixtures(self) -> list[str]:
        """Extract fixture names from conftest.py files."""
        fixtures = []
        for conftest in self.root.rglob("conftest.py"):
            try:
                content = conftest.read_text(encoding="utf-8", errors="ignore")
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        for dec in node.decorator_list:
                            dec_name = ""
                            if isinstance(dec, ast.Attribute):
                                dec_name = dec.attr
                            elif isinstance(dec, ast.Name):
                                dec_name = dec.id
                            elif isinstance(dec, ast.Call):
                                if isinstance(dec.func, ast.Attribute):
                                    dec_name = dec.func.attr
                                elif isinstance(dec.func, ast.Name):
                                    dec_name = dec.func.id
                            if dec_name == "fixture":
                                fixtures.append(node.name)
            except (SyntaxError, OSError):
                continue
        return fixtures[:20]

    def _find_test_style_example(self) -> str:
        """Find an existing test file as style reference (first 60 lines)."""
        test_dirs = [self.root / "tests", self.root / "test"]
        for td in test_dirs:
            if td.is_dir():
                for tf in td.rglob("test_*.py"):
                    try:
                        lines = tf.read_text(encoding="utf-8", errors="ignore").split("\n")
                        return "\n".join(lines[:60])
                    except OSError:
                        continue
        for tf in self.root.rglob("test_*.py"):
            try:
                lines = tf.read_text(encoding="utf-8", errors="ignore").split("\n")
                return "\n".join(lines[:60])
            except OSError:
                continue
        return ""

    def _find_existing_test(self, source_file: str) -> Optional[str]:
        """Find existing test file for a given source file."""
        base_name = Path(source_file).stem
        patterns = [
            f"tests/test_{base_name}.py",
            f"test/test_{base_name}.py",
            f"tests/{base_name}_test.py",
        ]
        for p in patterns:
            if (self.root / p).exists():
                return p
        return None

    def _extract_imports(self, source_code: str) -> list[str]:
        """Extract import statements from source code."""
        imports = []
        try:
            tree = ast.parse(source_code)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append(f"import {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    names = ", ".join(a.name for a in node.names)
                    imports.append(f"from {module} import {names}")
        except SyntaxError:
            imports = re.findall(r"^(?:from .+ import .+|import .+)$", source_code, re.MULTILINE)
        return imports

    def _extract_function_source(self, source_code: str, func_name: str) -> Optional[str]:
        """Extract a function's full source from the file."""
        try:
            tree = ast.parse(source_code)
        except SyntaxError:
            return None

        lines = source_code.split("\n")
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == func_name:
                    start = node.lineno - 1
                    end = node.end_lineno or (start + 1)
                    return "\n".join(lines[start:end])
        return None

    def _query_codegraph(self, symbol: str, file_path: str) -> tuple[list[str], list[str]]:
        """Query CodeGraph for callers (refs) and callees (impact) of a symbol."""
        if not self.codegraph_available:
            return [], []

        callers = self._codegraph_cmd("refs", symbol)
        callees = self._codegraph_cmd("impact", symbol)
        return callers, callees

    def _codegraph_cmd(self, command: str, symbol: str) -> list[str]:
        """Run a codegraph CLI command and return list of symbol names."""
        try:
            result = subprocess.run(
                ["codegraph", command, symbol, "--db", str(self.db_path), "--format", "json"],
                cwd=str(self.root),
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout)
                if isinstance(data, list):
                    return [item.get("symbol", str(item)) for item in data][:10]
                if isinstance(data, dict):
                    return data.get("symbols", data.get("results", []))[:10]
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as exc:
            logger.debug("codegraph.cmd_failed", command=command, symbol=symbol, error=str(exc))
        return []

    def _infer_mock_candidates(self, callees: list[str]) -> list[str]:
        """Infer which callees should be mocked (external deps, DB, network)."""
        mock_keywords = {"db", "session", "redis", "http", "request", "send", "publish", "commit", "save"}
        candidates = []
        for callee in callees:
            lower = callee.lower()
            if any(kw in lower for kw in mock_keywords):
                candidates.append(callee)
        return candidates

    def _detect_dependencies(self) -> list[str]:
        """Detect project dependencies from requirements or pyproject."""
        deps = []
        req_file = self.root / "requirements.txt"
        if req_file.exists():
            for line in req_file.read_text(errors="ignore").split("\n"):
                line = line.strip()
                if line and not line.startswith("#"):
                    pkg = re.split(r"[><=!~]", line)[0].strip()
                    if pkg:
                        deps.append(pkg)
            return deps[:30]

        pyproject = self.root / "pyproject.toml"
        if pyproject.exists():
            content = pyproject.read_text(errors="ignore")
            in_deps = False
            for line in content.split("\n"):
                if "dependencies" in line and "=" in line:
                    in_deps = True
                    continue
                if in_deps:
                    if line.strip().startswith("]"):
                        break
                    m = re.match(r'\s*"([^">=<!\s]+)', line)
                    if m:
                        deps.append(m.group(1))
        return deps[:30]

    def _discover_project_rules(self) -> str:
        """Scan well-known locations for project-specific test rules."""
        rules_parts = []

        for rule_path in [
            self.root / ".ai-devops" / "rules.md",
            self.root / ".ai-devops" / "test-rules.md",
        ]:
            if rule_path.exists():
                content = rule_path.read_text(encoding="utf-8", errors="replace")
                rules_parts.append(f"## From {rule_path.relative_to(self.root)}\n{content.strip()}")
                break

        contributing = self.root / "CONTRIBUTING.md"
        if contributing.exists() and not rules_parts:
            text = contributing.read_text(encoding="utf-8", errors="replace")
            testing_section = self._extract_section(text, "Testing")
            if testing_section:
                rules_parts.append(f"## From CONTRIBUTING.md (Testing)\n{testing_section}")

        pyproject = self.root / "pyproject.toml"
        if pyproject.exists() and not rules_parts:
            try:
                import tomllib
                data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
                ai_rules = data.get("tool", {}).get("ai-devops", {})
                if "test_rules" in ai_rules:
                    rules_parts.append(f"## From pyproject.toml [tool.ai-devops]\n{ai_rules['test_rules']}")
            except Exception:
                pass

        for rule_file in [".cursorrules", ".clinerules"]:
            rule_path = self.root / rule_file
            if rule_path.exists() and not rules_parts:
                text = rule_path.read_text(encoding="utf-8", errors="replace")
                test_rules = self._extract_test_related(text)
                if test_rules:
                    rules_parts.append(f"## From {rule_file} (test-related)\n{test_rules}")
                break

        if not rules_parts:
            return ""

        combined = "\n\n".join(rules_parts)
        max_chars = 2000
        if len(combined) > max_chars:
            combined = combined[:max_chars] + "\n\n[... rules truncated ...]"
        return combined

    def _extract_section(self, text: str, section_name: str) -> str | None:
        """Extract a markdown section by heading name."""
        lines = text.split("\n")
        capturing = False
        section_lines = []
        heading_level = 0

        for line in lines:
            if line.startswith("#"):
                level = len(line) - len(line.lstrip("#"))
                title = line.lstrip("#").strip().lower()
                if section_name.lower() in title:
                    capturing = True
                    heading_level = level
                    continue
                elif capturing and level <= heading_level:
                    break
            if capturing:
                section_lines.append(line)

        result = "\n".join(section_lines).strip()
        return result if result else None

    def _extract_test_related(self, text: str) -> str:
        """Extract test-related lines from generic AI rules."""
        keywords = ["test", "pytest", "unittest", "mock", "fixture", "assert"]
        lines = text.split("\n")
        relevant = [line for line in lines if any(kw in line.lower() for kw in keywords)]
        return "\n".join(relevant[:30]) if relevant else ""

    def scan_historical_defects(self, target_files: list[str]) -> list[dict]:
        """Scan git log for recent bug fixes in target files."""
        defects = []
        try:
            for file_path in target_files[:5]:
                if not file_path:
                    continue
                result = subprocess.run(
                    [
                        "git", "log", "--oneline",
                        "--since=30 days ago",
                        "--grep=fix|bug|hotfix",
                        "--all-match",
                        "--", file_path,
                    ],
                    cwd=str(self.root),
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0 and result.stdout.strip():
                    for line in result.stdout.strip().split("\n")[:5]:
                        parts = line.split(" ", 1)
                        if len(parts) == 2:
                            defects.append({
                                "commit": parts[0],
                                "message": parts[1],
                                "file": file_path,
                            })
        except (subprocess.TimeoutExpired, OSError):
            pass
        return defects[:15]
