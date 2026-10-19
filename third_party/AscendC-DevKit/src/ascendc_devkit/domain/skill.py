"""L4 Domain — Skill and Agent manifest types."""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class SkillSpec:
    name: str
    path: Path
    description: str = ""

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, SkillSpec):
            return NotImplemented
        return self.name < other.name


@dataclass(frozen=True)
class AgentManifest:
    name: str
    skills: list[str] = field(default_factory=list)
    description: str = ""
    # Tool/permission contract (manifest-driven, D3). None/empty means
    # "inherit the backend default".
    allowed_tools: list[str] = field(default_factory=list)
    disallowed_tools: list[str] = field(default_factory=list)
    max_turns: int | None = None
