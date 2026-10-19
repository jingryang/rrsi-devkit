"""External operator-repo resolution for tests (§1.7 self-closure).

ST/UT that exercise real deploy/precision/scan need a REAL operator repo
(cann-bench / ops-nn) on disk. Those repos are **external** — not vendored in
this project — so their paths must NOT be hardcoded to any developer's home
(no ``Path.home()`` / absolute home literals; §1.7).

``resolve_test_repo`` resolution order:
  1. Explicit env var (authoritative): ``ASCENDC_TEST_CANN_BENCH`` /
     ``ASCENDC_TEST_OPS_NN``. Power-user / CI override.
  2. Persisted local config (``tests/.testrepos.local.json``): written by the
     conftest interactive prompt on first run, so a user can configure a repo
     WITHOUT knowing any env-var name (the env var is no longer a hidden
     contract — discoverability, §3.7).
  3. Convenience default: a sibling of this repo (common workspace layout,
     e.g. ``../cann-bench``) — relative to the repo root, never a home path.

Returns the ``Path`` when resolved AND present on disk, else ``None``.
Callers MUST ``pytest.skip()`` via ``repo_skip_reason()`` when ``None``
(§3.7 honest reporting — the absence of an optional external dep is an
environment precondition, NOT a test or code defect; never fail / mock).
"""

import os
from pathlib import Path

# Workspace = parent of this repo. Sibling repos live one level above the
# project (e.g. ``/code/cann-bench`` beside ``/code/AscendC-DevKit``).
# Derived from this file's location — never from a hardcoded absolute path.
_WORKSPACE = Path(__file__).resolve().parents[2]

# Persisted interactive answers, in-project (gitignored). Written by the
# conftest prompt on first run; lets a user configure a repo without knowing
# any env-var name. Lives under tests/ (not ~/, §1.7).
_LOCAL_CONFIG = Path(__file__).resolve().parent / ".testrepos.local.json"


def _read_local_repo(env_var: str) -> str | None:
    """Read a persisted repo path for *env_var*, or ``None``.

    Returns the path only when it still exists on disk — a stale/moved repo is
    treated as unset so the prompt re-fires honestly (§3.7) instead of silently
    masking a bad path.
    """
    try:
        import json
        data = json.loads(_LOCAL_CONFIG.read_text(encoding="utf-8"))
        path = data.get(env_var)
        return path if path and Path(path).is_dir() else None
    except Exception:
        return None


def write_local_repo(env_var: str, path: str) -> None:
    """Persist *path* for *env_var* so ``resolve_test_repo`` finds it later.

    Public (no underscore) — called from conftest's interactive prompt. Merges
    into the existing JSON (other repos preserved).
    """
    import json
    try:
        data = json.loads(_LOCAL_CONFIG.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}
    data[env_var] = str(path)
    _LOCAL_CONFIG.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve_test_repo(env_var: str, sibling: str) -> Path | None:
    """Resolve an external operator-repo path, or ``None`` if unavailable.

    Resolution order:
      1. env var (authoritative override). A value that is set but missing on
         disk returns ``None`` (so the caller reports "configured but not found"
         honestly — an explicit override is respected, not fallen-through).
      2. persisted local config (``tests/.testrepos.local.json``).
      3. sibling dir beside this repo (convenience default).

    A persisted or sibling path that has since vanished falls through to the
    next source / ``None`` so the prompt can re-fire (§3.7).
    """
    explicit = os.environ.get(env_var)
    if explicit:
        candidate = Path(explicit)
        return candidate if candidate.is_dir() else None
    persisted = _read_local_repo(env_var)
    if persisted:
        return Path(persisted)
    default = _WORKSPACE / sibling
    return default if default.is_dir() else None


def repo_skip_reason(name: str, env_var: str) -> str:
    """Actionable skip message for a missing external operator repo (§3.7)."""
    return (
        f"{name} repo not available — this test needs the external {name} repo, "
        f"which is NOT vendored in this project. Re-run pytest in an interactive "
        f"terminal to be prompted for its path (persisted, one-time), or set "
        f"{env_var}=<path> explicitly, or place {name}/ as a sibling of this repo. "
        f"Honest skip: optional external env precondition (§3.7), not a defect."
    )
