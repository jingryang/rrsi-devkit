"""L6 Adapters — SchemaLoader: JSON → ArtifactSpec/ArtifactContract.

Externalized single source of truth for stage spec-artifact schemas. Each
``kind="spec"`` artifact a stage produces is declared in a JSON schema file so
it can be read and audited without opening Python source; the loader reconstructs
the same ``ArtifactSpec`` the stage previously declared inline, preserving the
single-source-of-truth contract (the prompt the agent sees and the parser that
reads its output back are both built from this one object).

First principle (step-10, CLAUDE.md): the schema travels WITH the skill so the
skill is self-contained and runs verbatim in Claude Code TUI. The schema lives in
the skill's own dir in the flat canonical tree:
  - ``.claude/skills/<skill>/schema/`` — the skill that produces the spec artifact
    carries its schema. ``*_from_skill``.

Mirrors adapters/repository/profile_loader.py (the established L6 resource
loader pattern). The legacy ``resources/schemas/`` root was deleted in the
step-10 convergence (discipline #2: one path, no dead route).
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from ascendc_devkit.domain.artifact import ArtifactSpec, ArtifactContract

_SKILLS_ROOT = Path(__file__).resolve().parents[4] / ".claude" / "skills"


class SchemaNotFoundError(FileNotFoundError):
    """Schema file missing or unreadable.

    A hard error rather than a soft default: without the schema the agent
    prompt cannot tell the model what to produce, so silently degrading would
    reproduce the very "missing source of truth" class of bug this design
    exists to prevent.
    """


def _build_spec(data: dict, filename: str) -> ArtifactSpec:
    """Reconstruct an ArtifactSpec from a parsed schema mapping.

    Shared by the resources-root and skill-dir loaders so both produce an
    identical spec object from the same JSON shape (single source of truth).
    """
    return ArtifactSpec(
        name=Path(filename).stem,
        kind="spec",
        filename=filename,
        required=bool(data.get("required", True)),
        required_keys=tuple(data.get("required_keys", [])),
        issue_required_keys=tuple(data.get("issue_required_keys", [])),
        allowed_top_level_keys=tuple(data.get("allowed_top_level_keys", [])),
        description=data.get("description", ""),
        example=data.get("example"),
    )


def _read_schema_json(path: Path, label: str) -> dict:
    """Read+parse a schema JSON file, raising SchemaNotFoundError on any miss."""
    if not path.exists():
        schema_dir = path.parent
        avail = sorted(p.name for p in schema_dir.glob("*.json")) \
            if schema_dir.exists() else []
        raise SchemaNotFoundError(
            f"Schema '{label}' not found at {path}. Available: {avail}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SchemaNotFoundError(f"Schema '{label}' invalid JSON: {e}")


class SchemaLoader:
    """Load externalized stage artifact schemas (schema travels with the skill).

    One root: ``.claude/skills/<skill>/schema/`` — the producing skill carries
    its own schema in the flat canonical tree. ``*_from_skill``.
    """

    @staticmethod
    @lru_cache(maxsize=None)
    def load_spec_from_skill(skill: str, filename: str) -> ArtifactSpec:
        """Load one spec-artifact schema from a skill's own ``schema/`` dir.

        Path: ``.claude/skills/<skill>/schema/<filename>``.
        """
        data = _read_schema_json(
            _SKILLS_ROOT / skill / "schema" / filename,
            f"{skill}/{filename}")
        return _build_spec(data, filename)

    @staticmethod
    def load_contract_from_skill(skill: str,
                                 filenames: list[str]) -> ArtifactContract:
        """Build an ordered ``ArtifactContract`` from a skill's schema dir.

        Order is significant (drives prompt rendering); pass filenames in the
        order the stage wants them rendered.
        """
        return ArtifactContract(
            artifacts=[SchemaLoader.load_spec_from_skill(skill, fn)
                       for fn in filenames])
