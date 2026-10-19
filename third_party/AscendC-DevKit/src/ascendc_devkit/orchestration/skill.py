"""L3 Orchestration — Skill resolution facade.

Delegates to L5 skill discovery/validation/manifest parsing.
L2 application layer imports from here to respect architecture rules.
"""

from __future__ import annotations

from pathlib import Path

from ascendc_devkit.capabilities.skill.loader import (
    SkillLoader,
    load_agent_manifest,
    resolve_skills as _resolve_skills,
)
from ascendc_devkit.domain.skill import AgentManifest, SkillSpec


def list_available_skills(extra_paths: list[Path] | None = None) -> list[SkillSpec]:
    return SkillLoader.list_available(extra_paths=extra_paths)


def validate_skills(names: list[str], extra_paths: list[Path] | None = None) -> list[str]:
    return SkillLoader.validate(names, extra_paths=extra_paths)


def get_agent_manifest(name: str) -> AgentManifest:
    return load_agent_manifest(name)


def resolve_agent_skills(agent_name: str, requested: list[str],
                         extra_paths: list[Path] | None = None) -> list[SkillSpec]:
    return _resolve_skills(agent_name, requested, extra_paths=extra_paths)


def load_skill_spec(name: str, extra_paths: list[Path] | None = None) -> SkillSpec | None:
    """Look up a single skill by name. Returns None if not found."""
    all_skills = SkillLoader.discover(extra_paths=extra_paths)
    for s in all_skills:
        if s.name == name:
            return s
    return None
