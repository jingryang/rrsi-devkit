"""S5 heavy_llm ST — hard-timeout real-link verification (dual-backend).

Verifies the hard-timeout feature END-TO-END against the REAL SDK transports:
  - claude  → spawn-layer ``anyio.fail_after`` hard wall → SDK ``transport.close()``
              SIGTERM/SIGKILL escalation kills the CLI subprocess (S1/S1b).
  - opencode → external ``deadline_monotonic`` tightens ``message_timeout`` →
              keepalive aborts the blocking POST → ``_stop_serve`` ``killpg`` kills
              the serve + engine-MCP group (S1a/S4).

A tight ``deadline_monotonic`` on a task that outlasts it MUST return
``aborted='hard_timeout'`` within seconds (not run the full task), proving the
second-level hard wall + graceful kill. This is the §3.9 real-link guard for the
hard-timeout feature; UTs (``test_hard_timeout.py``) cover the logic with stubs.

§3.11: heavy_llm — NOT auto-run. The user lists + decides before execution.
Dual-marked ``llm`` + ``heavy_llm``; opencode also needs a real ``rg`` on PATH.
"""
from __future__ import annotations

import time

import pytest

from tests.st._dual_backend import (
    load_settings_env, has_anthropic, make_backend,
    require_live_opencode)

# Substantial pure-generation prompt that reliably outlasts a few-second hard
# wall (the model cannot finish it before the deadline fires). No tool use is
# requested — a generation race keeps the assertion about the WALL, not tools.
_LONG_PROMPT = (
    "Write a detailed 1500-word technical essay explaining AscendC operator "
    "development: the programming model, host tiling, cube/vector APIs, and "
    "memory hierarchy. Write the full essay now; do not use any tools."
)

# elapsed ceiling per backend (seconds). claude: deadline + SDK close escalation
# (~≤20s worst case). opencode: serve startup (startup_timeout=90s) precedes the
# tightened message window, so allow startup + abort.
_ELAPSED_CEILING = {"claude": 30.0, "opencode": 120.0}


def _require_live(kind: str) -> None:
    """Honest skip when the real link is unavailable (§3.7) — never a test failure.

    opencode: the positive smoke (require_live_opencode) IS the live check — it
    proves the local opencode.json works, so this negative hard-wall test runs
    against a KNOWN-HEALTHY opencode (closes the false-green blind spot where a
    broken config hangs the spawn and the hard wall dutifully kills it)."""
    if kind == "opencode":
        require_live_opencode()
        return
    load_settings_env()
    if not has_anthropic():
        pytest.skip("no ANTHROPIC creds — real LLM link unavailable (§3.7)")


@pytest.mark.llm
@pytest.mark.heavy_llm
@pytest.mark.parametrize("kind", ["claude", "opencode"])
def test_hard_wall_kills_real_spawn(kind, tmp_path):
    """Real SDK: a tight ``deadline_monotonic`` kills the in-flight spawn and
    returns ``aborted='hard_timeout'`` well before the long task would finish."""
    _require_live(kind)
    ws = tmp_path / "ws"
    ws.mkdir()
    backend = make_backend(kind, ws)

    deadline = time.monotonic() + 4.0   # 4s hard wall
    start = time.monotonic()
    result = backend.spawn(
        "ascendc-coder", _LONG_PROMPT, {},
        working_dir=str(ws),
        deadline_monotonic=deadline,
    )
    elapsed = time.monotonic() - start

    assert result.aborted == "hard_timeout", (
        f"hard wall did not fire on real {kind}: status={result.status} "
        f"aborted={result.aborted!r} elapsed={elapsed:.1f}s "
        f"(model may have finished <4s — re-run, §3.10)")
    # Killed within the wall + graceful-close budget — NOT the full task time.
    assert elapsed < _ELAPSED_CEILING[kind], (
        f"{kind}: hard wall fired but spawn took {elapsed:.1f}s "
        f"(>{_ELAPSED_CEILING[kind]}s) — close/kill escalation too slow")


@pytest.mark.llm
@pytest.mark.heavy_llm
def test_claude_hard_timeout_keeps_session_sidecar(tmp_path):
    """Real claude: after the hard wall kills the spawn, the session sidecar
    must remain on disk (flushed at session_id capture, not cleared on crash) —
    the constructive resume guarantee for a hard-killed spawn (S1b)."""
    _require_live("claude")
    ws = tmp_path / "ws"
    ws.mkdir()
    backend = make_backend("claude", ws)

    deadline = time.monotonic() + 4.0
    result = backend.spawn(
        "ascendc-coder", _LONG_PROMPT, {},
        working_dir=str(ws), deadline_monotonic=deadline)

    assert result.aborted == "hard_timeout"
    # The sidecar lives under the workspace's run dir: <run>/agents/<agent>.session.json
    # (agent_name ascendc-coder). A hard-killed spawn must leave it for resume.
    sidecars = list(ws.parent.glob("**/agents/*.session.json"))
    assert sidecars, (
        "no session sidecar after hard kill — resume handle lost (S1b regression)")
