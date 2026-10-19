"""Shared helpers for dual-backend (claude / opencode) live-LLM ST spikes.

Single source for the env prerequisites both backends need when driven from a
pytest process (directive: 相2 每步 claude + opencode 双侧真跑，不留单边盲区).
Not a test module (leading underscore → pytest never collects it).
"""

from __future__ import annotations

import glob
import os
import shutil
import tempfile
import time
from pathlib import Path

import pytest

from tests._llm_env import has_anthropic, load_settings_env  # noqa: F401  (re-export)

REPO = Path(__file__).resolve().parent.parent.parent


# —— opencode env prereq: a REAL ``rg`` on PATH ————————————————————————————
# opencode calls Bun.which("rg") at init; if absent it tries to DOWNLOAD
# ripgrep (firewalled here → hang). This dev shell aliases ``rg`` to a Claude
# Code shim (shutil.which → None), so a python test process has no real rg. We
# locate a real binary from known editor-server locations and prepend its dir to
# PATH (env-coupled setup belongs in the test, not in src/ per §1.7). If none is
# found we FAIL honestly (§3.7) rather than let opencode hang.
_RG_GLOBS = (
    "/root/.remotedev-server/bin/*/*/node_modules/@vscode/ripgrep/bin/rg",
    "/root/.vscode-server/bin/*/node_modules/@vscode/ripgrep/bin/rg",
)


def ensure_rg_on_path() -> None:
    if shutil.which("rg"):
        return
    for pat in _RG_GLOBS:
        hits = sorted(glob.glob(pat))
        if hits:
            os.environ["PATH"] = str(Path(hits[-1]).parent) + os.pathsep + os.environ["PATH"]
            return
    if not shutil.which("rg"):
        pytest.fail("opencode requires a real `rg` on PATH but none was found "
                    "(shell shims don't count); install ripgrep or expose its dir")


def make_backend(kind: str, ws: Path, **overrides):
    """Build the backend via the production factory, passing the UNION of both
    constructors' kwargs — the factory filters per backend (§2.3 single path).
    ``overrides`` extend/override the defaults (e.g. ``turn_stall_s`` for the
    turn-stall ST); caller values win over the built-in defaults."""
    from ascendc_devkit.orchestration.agent_backend_factory import build_agent_backend
    kwargs = dict(
        interactive=False,
        working_dir=ws.parent,
        on_decision="default",
        decision_workspace=ws,
        # opencode-only (filtered out for claude):
        project_config_path=str(REPO / "opencode.json"),
        serve_startup_timeout=90.0,
        message_timeout=180.0,
    )
    kwargs.update(overrides)
    return build_agent_backend(kind, **kwargs)


# —— opencode positive smoke precondition (§3.7) ————————————————————————————
# A REAL ``opencode serve`` + a tool-forbidden one-turn prompt → proves the local
# ``opencode.json`` config (gateway / auth / model) actually works BEFORE a real-
# machine opencode test runs. Without this the negative hard-wall test
# (``test_hard_wall_kills_real_spawn[opencode]``) false-greens on a broken config:
# a wrong config makes the spawn hang → the 4s hard wall kills it → ``aborted`` →
# the test's ``aborted=='hard_timeout'`` assertion is satisfied though opencode
# never worked. The smoke turns that into a clear §3.7 skip instead. Cached per
# session (one serve startup amortized across all opencode tests in the run).
#
# ``has_anthropic()`` is NOT the right gate for opencode (opencode drives its own
# provider from ``opencode.json``, not the ANTHROPIC_* env that gate checks) — the
# smoke IS the credential/config check.
_OPENCODE_SMOKE_CACHE: tuple | None = None  # None=未跑; ("ok",)=通过; ("skip", reason)=失败
_SMOKE_AGENT = "ascendc-coder"
_SMOKE_PROMPT = "Do not use any tools. Reply with exactly: ACK"
_SMOKE_DEADLINE_SEC = 30.0  # working config replies in seconds; broken config hangs → wall fires
# opencode "spawn completed, gateway reached the model" statuses — mirrors
# test_session_resume_e2e._COMPLETED. The smoke proves the link; it does not care
# whether the trivial reply carried artifacts.
_SMOKE_COMPLETED = ("ok", "partial")


def _classify_smoke_result(result) -> tuple[bool, str]:
    """Pure decision: did the smoke spawn prove opencode is live?

    Returns ``(ok, skip_reason)``. ``ok=True`` ⟺ opencode reached the gateway and
    the model replied cleanly (config works). Failure reasons target the actual
    wrong-config failure modes: a hung spawn (aborted, gateway/model unreachable)
    and an explicit infra misconfiguration (``error_type=='infra'``).
    """
    aborted = getattr(result, "aborted", None)
    if aborted is not None:
        return False, (f"aborted={aborted!r} (opencode spawn hung — "
                       f"gateway/model unreachable, hard wall fired)")
    if getattr(result, "error_type", None) == "infra":
        return False, ("error_type=infra (opencode env misconfigured — "
                       "gateway/auth/model in opencode.json)")
    if result.status not in _SMOKE_COMPLETED:
        return False, (f"status={result.status!r} (opencode reachable but spawn "
                       f"did not complete cleanly — check opencode.json)")
    return True, ""


def require_live_opencode() -> None:
    """§3.7 positive precondition for every opencode real-machine test.

    Proves the local ``opencode.json`` works (one tool-forbidden spawn through a
    real ``opencode serve``). On a broken config the smoke spawn aborts or errors
    → ``pytest.skip`` with a clear reason (NOT a failure: opencode.json is a
    gitignored local-env precondition, §3.7) → never a false-green pass. Cached
    per session so the serve startup is paid once across all opencode tests.
    """
    global _OPENCODE_SMOKE_CACHE
    if _OPENCODE_SMOKE_CACHE is not None:
        if _OPENCODE_SMOKE_CACHE[0] == "ok":
            return
        # cached failure → re-skip with the original reason
        pytest.skip(_OPENCODE_SMOKE_CACHE[1])

    ensure_rg_on_path()
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td) / "ws"
        ws.mkdir()
        backend = make_backend("opencode", ws)
        deadline = time.monotonic() + _SMOKE_DEADLINE_SEC
        result = backend.spawn(
            _SMOKE_AGENT, _SMOKE_PROMPT, {},
            working_dir=str(ws), deadline_monotonic=deadline,
        )
    ok, reason = _classify_smoke_result(result)
    if ok:
        _OPENCODE_SMOKE_CACHE = ("ok",)
        return
    msg = (f"opencode smoke failed ({reason}) — opencode.json config/gateway/model "
           f"unreachable (§3.7); fix local opencode config before running opencode "
           f"real-machine tests")
    _OPENCODE_SMOKE_CACHE = ("skip", msg)
    pytest.skip(msg)
