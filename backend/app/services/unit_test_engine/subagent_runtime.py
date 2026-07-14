"""Controlled runtime for unit-test subagent definitions.

The runtime turns the generated Markdown definitions into auditable execution
contracts. It does not grant tools by itself; callers must request tools and
the runtime validates them against the definition before building prompts or
calling an LLM.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Any


@dataclass(frozen=True)
class SubAgentDefinition:
    name: str
    description: str
    path: Path
    instructions: str
    allowed_tools: set[str] = field(default_factory=set)
    allowed_skills: list[str] = field(default_factory=list)
    forbidden_actions: list[str] = field(default_factory=list)
    output_contract: str = ""

    def to_prompt_card(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "allowed_tools": sorted(self.allowed_tools),
            "allowed_skills": self.allowed_skills,
        }


@dataclass
class SubAgentResult:
    success: bool
    agent: str
    status: str
    output: dict = field(default_factory=dict)
    reason: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0


class SubAgentContractError(ValueError):
    pass


class SubAgentRuntime:
    """Loads, validates, and invokes generated unit-test subagents."""

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root) if root else Path(__file__).resolve().parent / "subagents"

    def list_definitions(self) -> list[SubAgentDefinition]:
        return [self.load(path.stem) for path in sorted(self.root.glob("*.md")) if path.name != "README.md"]

    def list_cards(self) -> list[dict]:
        return [definition.to_prompt_card() for definition in self.list_definitions()]

    def load(self, name: str) -> SubAgentDefinition:
        path = self._definition_path(name)
        if not path.exists():
            raise SubAgentContractError(f"Subagent definition not found: {name}")
        text = path.read_text(encoding="utf-8", errors="replace")
        meta_text, instructions = self._split_front_matter(text)
        return SubAgentDefinition(
            name=self._scalar(meta_text, "name") or path.stem,
            description=self._scalar(meta_text, "description") or self._first_paragraph(instructions),
            path=path,
            instructions=instructions.strip(),
            allowed_tools=set(self._list(meta_text, "allowed_tools")),
            allowed_skills=self._list(meta_text, "allowed_skills"),
            forbidden_actions=self._list(meta_text, "forbidden_actions"),
            output_contract=self._block(meta_text, "structured_output_contract"),
        )

    def validate_tool_request(self, name: str, requested_tools: set[str] | list[str] | tuple[str, ...]) -> None:
        definition = self.load(name)
        requested = set(requested_tools)
        denied = requested - definition.allowed_tools
        if denied:
            raise SubAgentContractError(
                f"Subagent '{definition.name}' cannot use tools: {', '.join(sorted(denied))}"
            )

    def build_prompt(
        self,
        name: str,
        payload: dict[str, Any],
        skill_packages: list[dict[str, Any]] | None = None,
    ) -> tuple[str, str]:
        definition = self.load(name)
        system_prompt = "\n\n".join([
            definition.instructions,
            "Return only strict JSON matching the structured output contract.",
            f"Structured output contract:\n{definition.output_contract}",
        ]).strip()
        user_prompt = json.dumps({
            "agent": definition.name,
            "input": payload,
            "available_skill_packages": skill_packages or [],
            "runtime_policy": {
                "allowed_tools": sorted(definition.allowed_tools),
                "allowed_skills": definition.allowed_skills,
                "forbidden_actions": definition.forbidden_actions,
                "no_qoder_skills": True,
            },
        }, ensure_ascii=False)
        return system_prompt, user_prompt

    async def invoke(
        self,
        name: str,
        payload: dict[str, Any],
        engine: Any,
        requested_tools: set[str] | list[str] | tuple[str, ...] | None = None,
        skill_packages: list[dict[str, Any]] | None = None,
    ) -> SubAgentResult:
        definition = self.load(name)
        self.validate_tool_request(definition.name, requested_tools or [])
        if engine is None:
            return SubAgentResult(
                success=False,
                agent=definition.name,
                status="blocked",
                reason="LLM engine is not configured for subagent invocation",
            )

        system_prompt, user_prompt = self.build_prompt(definition.name, payload, skill_packages)
        response = await engine.complete_with_system(system_prompt, user_prompt, temperature=0.1)
        try:
            output = self._parse_json(response.content)
        except SubAgentContractError as exc:
            return SubAgentResult(
                success=False,
                agent=definition.name,
                status="failure",
                reason=str(exc),
                prompt_tokens=response.prompt_tokens,
                completion_tokens=response.completion_tokens,
            )

        status = str(output.get("status") or "success")
        return SubAgentResult(
            success=status not in {"failure", "failed", "blocked"},
            agent=definition.name,
            status=status,
            output=output,
            reason=str(output.get("reason") or output.get("blocked_reason") or ""),
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
        )

    def _definition_path(self, name: str) -> Path:
        normalized = name[:-3] if name.endswith(".md") else name
        return self.root / f"{normalized}.md"

    @staticmethod
    def _split_front_matter(text: str) -> tuple[str, str]:
        if not text.startswith("---"):
            return "", text
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.DOTALL)
        if not match:
            return "", text
        return match.group(1), match.group(2)

    @staticmethod
    def _scalar(meta_text: str, key: str) -> str:
        match = re.search(rf"^{re.escape(key)}:\s*(.*)$", meta_text, re.MULTILINE)
        if not match:
            return ""
        value = match.group(1).strip().strip("\"'")
        if value in {">", "|"}:
            block = SubAgentRuntime._block(meta_text, key)
            return " ".join(line.strip() for line in block.splitlines() if line.strip())
        return value

    @staticmethod
    def _list(meta_text: str, key: str) -> list[str]:
        block = SubAgentRuntime._section(meta_text, key)
        values = []
        for line in block.splitlines():
            stripped = line.strip()
            if stripped.startswith("- "):
                values.append(stripped[2:].strip())
        return values

    @staticmethod
    def _block(meta_text: str, key: str) -> str:
        return SubAgentRuntime._section(meta_text, key).strip()

    @staticmethod
    def _section(meta_text: str, key: str) -> str:
        pattern = rf"^{re.escape(key)}:\s*(?:[>|])?\s*$\n(.*?)(?=^[A-Za-z_][\w-]*:\s*|\Z)"
        match = re.search(pattern, meta_text, re.MULTILINE | re.DOTALL)
        return match.group(1) if match else ""

    @staticmethod
    def _first_paragraph(text: str) -> str:
        for line in text.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                return stripped
        return "Unit-test subagent"

    @staticmethod
    def _parse_json(content: str) -> dict:
        raw = content.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        if not raw.startswith("{"):
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if not match:
                raise SubAgentContractError("subagent output is not JSON")
            raw = match.group(0)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SubAgentContractError(f"invalid subagent JSON output: {exc}") from exc
        if not isinstance(data, dict):
            raise SubAgentContractError("subagent output must be a JSON object")
        return data


subagent_runtime = SubAgentRuntime()
