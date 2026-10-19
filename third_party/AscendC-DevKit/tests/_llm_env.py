"""Single-source LLM environment/credential resolution for tests.

Two agent backends need different config, and both are machine-local files that
are gitignored (never tracked, §1.7):

  * claude (Claude Agent SDK) → ``.claude/settings.json`` ``env`` block
    (``ANTHROPIC_BASE_URL`` / ``ANTHROPIC_AUTH_TOKEN``).
  * opencode → the project-root ``opencode.json`` provider + top-level ``model``
    (opencode reads its own provider/credentials natively; no ANTHROPIC_* needed).

Both used to be re-parsed in every ST module with slightly different copies of
``_load_settings_env`` / ``_has_anthropic`` — a scattered multi-path (§1.15). This
module is the single resolution point: callers ask for the env / a credential
gate / the backend-aware pre-check, and never hardcode a config path again.

Not a test module (leading underscore → pytest never collects it).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SETTINGS_PATH = REPO / ".claude" / "settings.json"
OPENCODE_CONFIG_PATH = REPO / "opencode.json"


# ---------------------------------------------------------------------------
# .claude/settings.json (claude backend credentials)
# ---------------------------------------------------------------------------

def load_settings_env() -> None:
    """Fold ``.claude/settings.json`` ``env`` (ANTHROPIC_*) into os.environ.

    ``setdefault`` semantics: an explicit export in the ambient environment wins
    over the file. No-op when the (gitignored) file is absent.
    """
    if not SETTINGS_PATH.exists():
        return
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    for k, v in (data.get("env") or {}).items():
        os.environ.setdefault(k, str(v))


def has_anthropic() -> bool:
    """True when ANTHROPIC_* credentials are present in the environment."""
    return bool(
        os.environ.get("ANTHROPIC_API_KEY", "").strip()
        or os.environ.get("ANTHROPIC_AUTH_TOKEN", "").strip()
    )


# ---------------------------------------------------------------------------
# opencode.json (opencode backend provider + model)
# ---------------------------------------------------------------------------

def _load_opencode_config() -> dict:
    """Parse the project ``opencode.json`` (JSONC tolerated), or ``{}``."""
    if not OPENCODE_CONFIG_PATH.exists():
        return {}
    try:
        text = OPENCODE_CONFIG_PATH.read_text(encoding="utf-8")
        # opencode accepts JSONC; strip full-line // comments and trailing commas.
        text = "\n".join(
            line for line in text.splitlines()
            if not line.strip().startswith("//"))
        text = re.sub(r",(\s*[}\]])", r"\1", text)
        return json.loads(text)
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def opencode_model() -> str | None:
    """The project ``opencode.json`` top-level ``model`` (``provider/id``)."""
    model = _load_opencode_config().get("model")
    return model if isinstance(model, str) and model.strip() else None


def opencode_available() -> tuple[bool, str]:
    """Is the opencode backend usable from its own config (no ANTHROPIC_*)?

    A real spawn needs both a top-level ``model`` and a ``provider`` block with
    credentials — ``_resolve_model`` fail-fasts without the former and opencode
    cannot reach the gateway without the latter. Absence is a machine-local
    precondition (§3.7), reported honestly, never mocked.
    """
    if not OPENCODE_CONFIG_PATH.exists():
        return False, (f"no {OPENCODE_CONFIG_PATH.name} at the project root "
                       "(machine-local, gitignored) — configure it or export "
                       "ASCENDC_AGENT_BACKEND=claude")
    cfg = _load_opencode_config()
    if not opencode_model():
        return False, (f"{OPENCODE_CONFIG_PATH.name} has no top-level \"model\" "
                       "(opencode serve needs it in the message body)")
    providers = cfg.get("provider") or {}
    if not providers:
        return False, (f"{OPENCODE_CONFIG_PATH.name} has no \"provider\" block "
                       "(no gateway credentials)")
    return True, (f"{OPENCODE_CONFIG_PATH.name} OK "
                  f"(model={opencode_model()}, providers={len(providers)})")


# ---------------------------------------------------------------------------
# Backend-aware resolution (single entry point)
# ---------------------------------------------------------------------------

def active_backend_kind() -> str:
    """Resolve the backend the run would use (env > config > default).

    Delegates to the production factory so tests never re-implement the
    selection order (§2.5). Import is deferred so importing this module stays
    dependency-free.
    """
    try:
        from ascendc_devkit.application.agent_backend_factory import (
            resolve_backend_kind,
        )
        return resolve_backend_kind()
    except Exception:  # noqa: BLE001 — resolution is best-effort
        return "opencode"


def llm_precheck(kind: str | None = None) -> tuple[bool, str]:
    """Backend-aware LLM availability for the pytest pre-check.

    claude → ANTHROPIC_* credentials (from env or ``.claude/settings.json``).
    opencode → the project ``opencode.json`` provider + model.
    """
    kind = kind or active_backend_kind()
    load_settings_env()
    if kind == "claude":
        if has_anthropic():
            return True, "ANTHROPIC_* credentials present"
        return False, ("no ANTHROPIC_* credentials (set ANTHROPIC_AUTH_TOKEN or "
                       "configure .claude/settings.json)")
    return opencode_available()


def load_llm_env() -> None:
    """Fold claude credentials into os.environ for any test that may use claude.

    Idempotent. opencode tests do not need this (they drive their own provider
    from ``opencode.json``), but calling it is harmless and keeps a single
    import for both backends.
    """
    load_settings_env()
