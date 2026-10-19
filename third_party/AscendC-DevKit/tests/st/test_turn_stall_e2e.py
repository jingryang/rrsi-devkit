"""P137 heavy_llm ST — producer-liveness turn-stall guard (opencode).

Verifies the P137 fix (producer-liveness turn-stall guard) END-TO-END
against the REAL opencode transport: a genuinely long single-turn generation
whose ``chars`` keep growing must NOT be mis-killed by the turn-stall gate. The
gate keys on ``turn_ts`` (bumped only on ``role=user`` / new exchange), so it
previously killed a slow-but-alive long generation as a dead stall (the observed
batch failure: a >600s buffer-kernel design generation tripped ``turn_stall``
600s); the liveness guard treats growing ``chars`` as the alive signal and only
trips on a chars-static stale turn. This is the §3.9 real-link guard for the
P137 liveness logic; the pure UT ``test_p117_turn_stall_watchdog``
covers the chars-static trip path with stubs.

Mechanism: a tight ``turn_stall_s`` (8s) + a long pure-generation prompt (1500
words, no tools). ``turn_ts`` is stamped once on the user-echo
(``message.updated role=user``) and NOT bumped while the assistant streams — so
the OLD gate would trip at 8s; the liveness guard lets the generation complete.
``message_timeout`` (hard cap) is set far larger so a mis-kill would surface as
``aborted='hard_timeout'``, and ``keepalive_idle_s`` stays default — streaming
SSE keeps ``last_event_ts`` fresh, so the idle gate cannot compete. A normal
completion is ``aborted=None``.

§3.11: heavy_llm — NOT auto-run. The user lists + decides before execution.
Dual-marked ``llm`` + ``heavy_llm``; needs a real ``opencode serve``
(``require_live_opencode`` smoke gates it). Generation length is nondeterministic
(§3.10): if the model finishes <8s the elapsed>=gate assertion is vacuous —
re-run.
"""
from __future__ import annotations

import time

import pytest

from tests.st._dual_backend import make_backend, require_live_opencode

# Substantial pure-generation prompt that reliably outlasts an 8s turn-stall gate
# (the model cannot finish 1500 words in 8s). No tool use is requested — a
# generation race keeps ``turn_ts`` pinned at the user-echo, so the assertion is
# about the GATE, not tools. (Same shape as test_hard_timeout_e2e._LONG_PROMPT,
# kept local so this ST is self-contained.)
_LONG_PROMPT = (
    "Write a detailed 1500-word technical essay explaining AscendC operator "
    "development: the programming model, host tiling, cube/vector APIs, and "
    "memory hierarchy. Write the full essay now; do not use any tools."
)

# turn-stall gate well inside a single long generation; hard cap far beyond it
# so turn-stall owns the stop. keepalive_idle stays default (streaming keeps SSE
# fresh) so the idle gate does not compete.
_TURN_STALL_S = 8.0
_HARD_CAP_S = 300.0


@pytest.mark.llm
@pytest.mark.heavy_llm
def test_turn_stall_liveness_does_not_kill_real_long_generation(tmp_path):
    """Real opencode: a long single-turn generation outlasting ``turn_stall_s``
    must NOT be mis-killed by the turn-stall gate — the spawn completes normally
    (``aborted is None``), proving the producer-liveness guard distinguishes a
    slow-but-alive turn from a dead one."""
    require_live_opencode()
    ws = tmp_path / "ws"
    ws.mkdir()
    backend = make_backend(
        "opencode", ws,
        turn_stall_s=_TURN_STALL_S,       # tight gate — a mis-kill would trip here
        message_timeout=_HARD_CAP_S)       # hard cap: far beyond, so a mis-kill
                                           # shows as aborted='hard_timeout'

    start = time.monotonic()
    result = backend.spawn(
        "ascendc-coder", _LONG_PROMPT, {},
        working_dir=str(ws))
    elapsed = time.monotonic() - start

    # A turn-stall mis-kill surfaces as aborted='hard_timeout' (turn-stall is a
    # keepalive gate). A normal long generation completes with aborted=None.
    assert result.aborted is None, (
        f"turn-stall mis-killed an alive long generation on real opencode: "
        f"status={result.status} aborted={result.aborted!r} elapsed={elapsed:.1f}s")
    # Meaningful only if the generation really outlasted the gate — else vacuous
    # (model was fast); re-run per §3.10.
    assert elapsed >= _TURN_STALL_S, (
        f"generation finished in {elapsed:.1f}s < turn_stall_s ({_TURN_STALL_S}s) "
        f"— vacuous (model fast); re-run, §3.10")
