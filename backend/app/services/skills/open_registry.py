"""Curated registry for project and approved external SKILL.md capability packs.

The registry indexes project-local and explicitly configured skill roots. It
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


@dataclass
class SkillPackage:
    name: str
    description: str
    path: str
    source: str
    content: str
    allowed_agents: list[str] = field(default_factory=list)
    token_budget: int = 800
    references: dict[str, str] = field(default_factory=dict)

    def to_prompt_package(self, max_chars: int | None = None) -> dict:
        content = self.content if max_chars is None else self.content[:max_chars]
        return {
            "name": self.name,
            "description": self.description,
            "source": self.source,
            "allowed_agents": self.allowed_agents,
            "token_budget": self.token_budget,
            "content": content,
            "references": self.references,
        }


class OpenSkillRegistry:
    """Indexes local curated SKILL.md files.

    Project-level `skills/` is always the primary source. Operators can extend
    it via `AI_DEVOPS_SKILLS_ROOTS`, separated by the OS path separator.
    `.qoder/skills` is intentionally excluded from product runtime discovery.
    """

    def __init__(self, roots: Iterable[str | Path] | None = None):
        self.roots = self._normalize_roots(roots or self._default_roots())

    @staticmethod
    def _project_root() -> Path:
        env_root = os.getenv("AI_DEVOPS_PROJECT_ROOT")
        if env_root:
            return Path(env_root)

        current = Path(__file__).resolve()
        for parent in current.parents:
            if (parent / "docker-compose.yml").exists():
                return parent
        for parent in current.parents:
            if (parent / "app").exists() and (parent / "alembic").exists():
                return parent
        return current.parents[3]

    @classmethod
    def _default_roots(cls) -> list[Path]:
        project_root = cls._project_root()
        roots = [project_root / "skills"]
        env_roots = os.getenv("AI_DEVOPS_SKILLS_ROOTS")
        if env_roots:
            roots.extend(Path(p) for p in env_roots.split(os.pathsep) if p.strip())
        return roots

    @classmethod
    def _normalize_roots(cls, roots: Iterable[str | Path]) -> list[Path]:
        normalized: list[Path] = []
        seen: set[str] = set()
        for raw_root in roots:
            root = Path(raw_root)
            if cls._is_qoder_path(root):
                continue
            key = str(root).casefold()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(root)
        return normalized

    @staticmethod
    def _is_qoder_path(path: Path) -> bool:
        return any(part.casefold() == ".qoder" for part in path.parts)

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
        package = self.get_package(name, max_chars=max_chars)
        return package.content if package else None

    def get_package(
        self,
        name: str,
        allowed_agent: str | None = None,
        max_chars: int | None = None,
        include_references: bool = True,
    ) -> SkillPackage | None:
        for skill_file in self._iter_skill_files():
            card = self._read_card(skill_file)
            if card.name != name:
                continue
            if allowed_agent and card.allowed_agents and allowed_agent not in card.allowed_agents:
                return None
            text = skill_file.read_text(encoding="utf-8", errors="replace")
            if max_chars is not None:
                text = text[:max_chars]
            return SkillPackage(
                name=card.name,
                description=card.description,
                path=card.path,
                source=card.source,
                content=text,
                allowed_agents=card.allowed_agents,
                token_budget=card.token_budget,
                references=self._read_references(skill_file) if include_references else {},
            )
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
        source = meta.get("source") or self._source_for_path(skill_file)
        token_budget = self._int(meta.get("token_budget"), 800)
        return SkillCard(
            name=name.strip(),
            description=description.strip(),
            path=str(skill_file),
            source=source.strip(),
            allowed_agents=allowed_agents,
            token_budget=token_budget,
        )

    def _read_references(self, skill_file: Path, max_files: int = 8, max_chars: int = 2000) -> dict[str, str]:
        references_dir = skill_file.parent / "references"
        if not references_dir.exists() or self._is_qoder_path(references_dir):
            return {}
        references: dict[str, str] = {}
        for path in sorted(references_dir.glob("*")):
            if len(references) >= max_files:
                break
            if not path.is_file() or self._is_qoder_path(path):
                continue
            references[path.name] = path.read_text(encoding="utf-8", errors="replace")[:max_chars]
        return references

    def _source_for_path(self, skill_file: Path) -> str:
        project_skills = self._project_root() / "skills"
        try:
            skill_file.resolve().relative_to(project_skills.resolve())
            return "project"
        except ValueError:
            return "external"

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
