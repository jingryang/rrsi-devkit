"""L6 Adapters — Profile loader: YAML → RepositoryProfile."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from ascendc_devkit.domain.repository import RepositoryProfile
from ascendc_devkit.infra.logger import Logger


_RESOURCES_ROOT = Path(__file__).resolve().parents[4] / "resources" / "repository-profiles"
_PROFILE_SCHEMA_PATH = (
    Path(__file__).resolve().parents[4] / "resources" / "schemas" / "repository" / "profile.json"
)


@lru_cache(maxsize=1)
def _load_schema() -> dict | None:
    """Load the profile JSON Schema once. None when unavailable (soft门禁)."""
    if not _PROFILE_SCHEMA_PATH.exists():
        return None
    try:
        import json
        return json.loads(_PROFILE_SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _validate_profile_data(data: dict, profile_name: str) -> None:
    """Validate raw profile YAML against the JSON Schema before construction.

    Best-effort门禁: when ``jsonschema`` is not installed or the schema file is
    missing, validation is skipped (``from_yaml`` is already tolerant of absent
    fields, per the design's "解析健壮 + schema 门禁后置" note). When both are
    present, a structural violation raises ``ValueError`` with the offending
    path so a malformed profile fails fast at load time.
    """
    schema = _load_schema()
    if schema is None:
        return
    try:
        import jsonschema
    except ImportError:
        return
    try:
        jsonschema.validate(instance=data, schema=schema)
    except jsonschema.ValidationError as e:
        loc = "/".join(str(p) for p in e.absolute_path) or "<root>"
        raise ValueError(
            f"Profile '{profile_name}' fails schema validation at '{loc}': {e.message}"
        ) from e


class ProfileLoader:
    """Load RepositoryProfile from YAML files in resources/repository-profiles/."""

    @staticmethod
    @lru_cache(maxsize=8)
    def load(profile_name: str, resources_root: Path | None = None) -> RepositoryProfile:
        root = resources_root or _RESOURCES_ROOT
        profile_path = root / f"{profile_name}.yaml"
        if not profile_path.exists():
            raise FileNotFoundError(
                f"Profile '{profile_name}' not found at {profile_path}. "
                f"Available: {[p.stem for p in root.glob('*.yaml')]}"
            )
        data = yaml.safe_load(profile_path.read_text())
        _validate_profile_data(data, profile_name)
        profile = RepositoryProfile.from_yaml(data)
        Logger.action("load_profile", f"Loaded profile '{profile_name}' from {profile_path}")
        return profile

    @staticmethod
    def list_profiles(resources_root: Path | None = None) -> list[str]:
        root = resources_root or _RESOURCES_ROOT
        if not root.exists():
            return []
        return sorted(p.stem for p in root.glob("*.yaml"))
