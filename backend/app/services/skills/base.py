"""
Skill base class. All AI skills inherit from SkillBase.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Any


@dataclass
class SkillContext:
    """Execution context passed to each skill."""
    repo_id: int
    repo_url: str
    platform: str                    # gitlab/github/gitea
    branch: str
    commit_sha: str
    author: str
    diff: str = ""                   # git diff content
    changed_files: list[str] = field(default_factory=list)
    mr_title: Optional[str] = None
    mr_description: Optional[str] = None
    extra: dict = field(default_factory=dict)


@dataclass
class SkillResult:
    """Result from skill execution."""
    success: bool
    summary: str
    details: dict = field(default_factory=dict)
    blocked: bool = False            # True = block merge
    notifications: list[dict] = field(default_factory=list)  # messages to send
    prompt_tokens: int = 0
    completion_tokens: int = 0


class SkillBase(ABC):
    """Base class for all AI skills."""

    name: str = "base"
    description: str = ""
    default_config: dict = {}

    def __init__(self, config: dict = None):
        self.config = {**self.default_config, **(config or {})}

    @abstractmethod
    async def execute(self, context: SkillContext, engine) -> SkillResult:
        """Execute the skill. engine is AIEngine instance."""
        pass

    def get_config(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)
