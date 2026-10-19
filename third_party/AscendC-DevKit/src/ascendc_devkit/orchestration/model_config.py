"""Per-stage model configuration.

Reads the "models.stages" section of resources/orchestration-config.json (the
single source of truth for orchestration tuning). Each entry maps a stage name
to either a concrete model id or the reserved token ``"default"`` — which means
"use the SDK's configured default" (the model in ``.claude/settings.json``). A
missing or empty entry is also ``"default"``.

There is intentionally NO ``models.default`` field: "default" is expressed
per-stage via the token, not as a global that silently never applies (the old
``models.default`` was a dead config — ``DEFAULT_MODEL`` had zero consumers —
removed per §1.4).
"""

from __future__ import annotations

import json
from pathlib import Path


# Reserved stage-map value meaning "use the SDK default" (.claude/settings.json
# model). Lets a stage explicitly opt into the system default instead of naming
# a concrete model id.
DEFAULT_TOKEN = "default"

_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "resources" / "orchestration-config.json"
)


def _load_stage_map() -> dict[str, str]:
    if not _CONFIG_PATH.exists():
        return {}
    data = json.loads(_CONFIG_PATH.read_text())
    return data.get("models", {}).get("stages", {}) or {}


STAGE_MODEL_MAP: dict[str, str] = _load_stage_map()


def stage_model(stage_name: str) -> str | None:
    """Return the model id for a stage, or ``None`` to use the SDK default.

    The runner resolves a stage's model as: action-level override >
    ``stage_model(stage_name)`` > SDK default. ``None`` here means the spawn
    passes ``model=None`` to the backend, which falls back to the configured
    system default. Concretely:

      ``stages.<stage>`` absent / ``""`` / ``"default"``  →  ``None``  (SDK default)
      ``stages.<stage>`` == ``"<concrete id>"``           →  that id
    """
    m = STAGE_MODEL_MAP.get(stage_name)
    if not m or m == DEFAULT_TOKEN:
        return None
    return m
