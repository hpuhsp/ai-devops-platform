"""Curated registry for external SKILL.md capability packs.

The registry indexes local mirrors of approved GitHub/open-source skills. It
never clones repositories or executes bundled scripts at runtime; callers only
receive compact skill cards for routing and optional summaries for prompts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os
import re
from typing import Iterable


@dataclass
class SkillCard:
    name: str
    description: str
    path: str
    source: str = "local"
    allowed_agents: list[str] = field(default_factory=list)
    token_budget: int = 800

    def to_prompt_card(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "source": self.source,
            "allowed_agents": self.allowed_agents,
            "token_budget": self.token_budget,
        }


class OpenSkillRegistry:
    """Indexes local curated SKILL.md files.

    Default roots include `.qoder/skills` so checked-in or locally mirrored
    skills can be reused immediately. Operators can override or extend this via
    `AI_DEVOPS_SKILLS_ROOTS`, separated by the OS path separator.
    """

    def __init__(self, roots: Iterable[str | Path] | None = None):
        self.roots = [Path(p) for p in (roots or self._default_roots())]

    @staticmethod
    def _project_root() -> Path:
        return Path(__file__).resolve().parents[4]

    @classmethod
    def _default_roots(cls) -> list[Path]:
        env_roots = os.getenv("AI_DEVOPS_SKILLS_ROOTS")
        if env_roots:
            return [Path(p) for p in env_roots.split(os.pathsep) if p.strip()]
        project_root = cls._project_root()
        return [
            project_root / ".qoder" / "skills",
            project_root / "skills",
        ]

    def list_cards(self, allowed_agent: str | None = None, limit: int = 12) -> list[SkillCard]:
        cards: list[SkillCard] = []
        for skill_file in self._iter_skill_files():
            card = self._read_card(skill_file)
            if allowed_agent and card.allowed_agents and allowed_agent not in card.allowed_agents:
                continue
            cards.append(card)
            if len(cards) >= limit:
                break
        return cards

    def get_summary(self, name: str, max_chars: int = 2400) -> str | None:
        for skill_file in self._iter_skill_files():
            card = self._read_card(skill_file)
            if card.name == name:
                text = skill_file.read_text(encoding="utf-8", errors="replace")
                return text[:max_chars]
        return None

    def _iter_skill_files(self):
        for root in self.roots:
            if not root.exists():
                continue
            yield from root.glob("*/SKILL.md")

    def _read_card(self, skill_file: Path) -> SkillCard:
        text = skill_file.read_text(encoding="utf-8", errors="replace")
        meta = self._front_matter(text)
        name = meta.get("name") or skill_file.parent.name
        description = meta.get("description") or self._first_heading_or_paragraph(text)
        allowed_agents = self._csv(meta.get("allowed_agents", ""))
        source = meta.get("source") or ("github" if meta.get("repo_url") else "local")
        token_budget = self._int(meta.get("token_budget"), 800)
        return SkillCard(
            name=name.strip(),
            description=description.strip(),
            path=str(skill_file),
            source=source.strip(),
            allowed_agents=allowed_agents,
            token_budget=token_budget,
        )

    @staticmethod
    def _front_matter(text: str) -> dict[str, str]:
        if not text.startswith("---"):
            return {}
        match = re.match(r"^---\s*\n(.*?)\n---\s*", text, re.DOTALL)
        if not match:
            return {}
        meta: dict[str, str] = {}
        current_key: str | None = None
        for raw_line in match.group(1).splitlines():
            line = raw_line.rstrip()
            if not line.strip():
                continue
            if ":" in line and not line.startswith((" ", "\t")):
                key, value = line.split(":", 1)
                current_key = key.strip()
                meta[current_key] = value.strip().strip('"').strip("'").strip(">")
            elif current_key:
                meta[current_key] = f"{meta[current_key]} {line.strip()}".strip()
        return meta

    @staticmethod
    def _first_heading_or_paragraph(text: str) -> str:
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped == "---" or ":" in stripped[:40]:
                continue
            return stripped.lstrip("#").strip()
        return "Curated SKILL.md capability pack"

    @staticmethod
    def _csv(value: str) -> list[str]:
        if not value:
            return []
        return [item.strip() for item in re.split(r"[,;\s]+", value) if item.strip()]

    @staticmethod
    def _int(value: str | None, default: int) -> int:
        try:
            return int(value) if value is not None and value != "" else default
        except ValueError:
            return default


open_skill_registry = OpenSkillRegistry()
