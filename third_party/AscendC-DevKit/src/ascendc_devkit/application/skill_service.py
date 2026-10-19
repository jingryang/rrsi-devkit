"""L2 Application — Skill service facade.

Delegates to L3 orchestration skill layer.
L1 CLI imports from here to respect architecture rules.
"""

from __future__ import annotations

from pathlib import Path

from ascendc_devkit.orchestration.skill import (
    AgentManifest,
    SkillSpec,
    get_agent_manifest,
    list_available_skills,
    resolve_agent_skills,
    validate_skills,
)
