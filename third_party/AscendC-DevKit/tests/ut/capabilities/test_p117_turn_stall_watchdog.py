"""P117 route C: turn-stall watchdog (the framework's honest stop for a hung
opencode spawn).

opencode can't be modified — its session-layer SessionRetry.policy has no retry
cap (unbounded backoff on gateway errors like ``[1313] Fair Usage Policy``) and
it silent-swallows the error so the POST never returns, while the SSE bus keeps
emitting session/loop noise that fools the existing ``last_event_ts`` keepalive.
The framework therefore stops a hung spawn via a **turn-stall gate**: if no new
turn starts for ``turn_stall_s`` seconds → trip. The trip reason carries the
stalled turn's number + its active block types (e.g. ``tool:read``) so an
operator knows what the agent was doing when it stalled — opencode emits no SSE
progress during a tool call, so this is the honest signal that a long-looking
stall is a tool, not a hang.

The framework does NOT read opencode.log (external path, §1.7). All thresholds
come from ``runtime_config.opencode_timeouts()`` (config-driven); these tests
pass them via the constructor (the dispatcher's kwargs path).
"""

import threading
import time
import types

import pytest

from ascendc_devkit.capabilities.agent.opencode_backend import (
    OpenCodeBackend, _KeepaliveAbort)


# ———————————————————————— turn-stall gate trips ————————————————————————

def test_post_message_watched_aborts_on_turn_stall(monkeypatch):
    """P117 route C: turn_ts not bumped for turn_stall_s → trip. Catches a hang
    that the SSE bus can't reveal (it still carries loop/permission noise, so
    the last_event_ts keepalive is fooled — this gate keys on real turn
    progress). The reason names the stalled turn + its activity. §P9: the
    stalled turn here carries NO tool block — pure model silence (thinking
    generation went dead), the population the model-silence bound owns."""
    b = OpenCodeBackend(keepalive_idle_s=100.0, keepalive_poll_s=0.05,
                        message_timeout=30.0, turn_stall_s=0.2)
    hang = threading.Event()
    monkeypatch.setattr(b, "_http_json",
                        lambda *a, **k: hang.wait(30.0) or {})
    sse = types.SimpleNamespace(state=b._new_sse_log_state())
    sse.state["turn"] = 12                       # the stalled turn number
    sse.state["block_types"] = {"thinking"}     # non-tool: model-silence gate
    sse.state["turn_ts"] = time.time() - 100      # stale → turn-stall trip
    stopped: list = []
    monkeypatch.setattr(b, "_stop_serve", lambda proc: stopped.append(proc))
    try:
        with pytest.raises(_KeepaliveAbort) as ei:
            b._post_message_watched("http://x", "s1", {}, sse, "PROC", "ag", "")
        assert "no new turn" in str(ei.value)
        # diagnostic: the stalled turn + its activity surface in the reason
        assert "last turn 12" in str(ei.value)
        assert "thinking" in str(ei.value)
        assert stopped == ["PROC"]               # serve killed to unblock POST
    finally:
        hang.set()


def test_turn_stall_reason_carries_sorted_blocks(monkeypatch):
    """The reason joins the block types sorted (deterministic), so a stalled
    turn mid-flight across several blocks names all of them — an operator sees
    the tool + a text fragment, not a hang. §P9: tool-active turns defer to
    the keepalive tolerance — this trip fires past that bound."""
    b = OpenCodeBackend(keepalive_idle_s=1.0, keepalive_poll_s=0.05,
                        message_timeout=30.0, turn_stall_s=0.2)
    hang = threading.Event()
    monkeypatch.setattr(b, "_http_json",
                        lambda *a, **k: hang.wait(30.0) or {})
    sse = types.SimpleNamespace(state=b._new_sse_log_state())
    sse.state["turn"] = 7
    sse.state["block_types"] = {"text", "thinking"}
    sse.state["turn_ts"] = time.time() - 100
    monkeypatch.setattr(b, "_stop_serve", lambda proc: None)
    try:
        with pytest.raises(_KeepaliveAbort) as ei:
            b._post_message_watched("http://x", "s1", {}, sse, "PROC", "ag", "")
        # sorted join over non-tool blocks → "text,thinking"
        assert "last turn 7: text,thinking" in str(ei.value)
        assert "tool:read" not in str(ei.value)
    finally:
        hang.set()


# ———————————————————————— P3: in-flight tool defers turn-stall ————————

def test_turn_stall_tool_in_flight_defers_trip(monkeypatch):
    """P3 原始场景（长工具 ≠ 误杀）：合法长编译/测试呈现 stale-turn + static-chars
    形态，turn-stall 门不得杀。step-97 后该保护由**证据**承接——判死前 probe 查
    本 spawn opencode db 的最新 tool part，status=running（工具在飞，SSE 静默是
    预期）→ 存活复位（block-type 机制代理已删，§1.10）。本用例 mock probe 返回
    running，断言不 trip；证据判的等价守护见 tests/ut/capabilities/
    test_step97_pretrip_evidence.py。"""
    b = OpenCodeBackend(keepalive_idle_s=100.0, keepalive_poll_s=0.05,
                        message_timeout=30.0, turn_stall_s=0.2)
    out = {"parts": [{"type": "text", "text": "done"}]}

    def delayed(*a, **k):
        time.sleep(1.0)          # worker outlives turn_stall_s several times over
        return out
    monkeypatch.setattr(b, "_http_json", delayed)
    monkeypatch.setattr(b, "_probe_running_tool", lambda sid: {
        "status": "running", "command": "bash build.sh", "output_tail": "",
        "started_ms": int(time.time() * 1000) - 100_000})
    sse = types.SimpleNamespace(state=b._new_sse_log_state())
    sse.state["turn"] = 9
    sse.state["block_types"] = {"tool:bash"}     # tool in flight, no result yet
    sse.state["chars"] = 300                     # static during the tool call
    sse.state["turn_ts"] = time.time() - 100     # stale turn = tool still running
    monkeypatch.setattr(b, "_stop_serve", lambda proc: None)

    msg = b._post_message_watched("http://x", "s1", {}, sse, "PROC", "ag", "")

    assert msg == out                            # worker result, NOT _KeepaliveAbort


def test_turn_stall_tool_in_flight_still_bounded_by_keepalive(monkeypatch):
    """P3: the in-flight-tool deferral is NOT a hang exemption — a genuinely hung
    tool (no SSE for keepalive_idle_s) is still killed by the keepalive gate, so
    a stuck tool can't run forever. turn-stall defers, keepalive owns the bound."""
    b = OpenCodeBackend(keepalive_idle_s=0.2, keepalive_poll_s=0.02,
                        message_timeout=30.0, turn_stall_s=100.0)
    hang = threading.Event()
    monkeypatch.setattr(b, "_http_json",
                        lambda *a, **k: hang.wait(30.0) or {})
    sse = types.SimpleNamespace(state=b._new_sse_log_state())
    sse.state["turn"] = 3
    sse.state["block_types"] = {"tool:bash"}     # tool in flight...
    sse.state["last_event_ts"] = time.time() - 10  # ...but no SSE for idle_s
    sse.state["turn_ts"] = time.time() - 100
    monkeypatch.setattr(b, "_stop_serve", lambda proc: None)
    try:
        with pytest.raises(_KeepaliveAbort) as ei:
            b._post_message_watched("http://x", "s1", {}, sse, "PROC", "ag", "")
        assert "no SSE activity" in str(ei.value)   # keepalive is the backstop
    finally:
        hang.set()


def test_turn_stall_reason_with_no_activity(monkeypatch):
    """A stalled turn with no recorded blocks (e.g. the very first turn stalled
    before any block streamed, or turn=0 never started) → the reason still
    names the turn number but doesn't append an empty ':' — it degrades
    gracefully rather than printing 'last turn 0: '."""
    b = OpenCodeBackend(keepalive_idle_s=100.0, keepalive_poll_s=0.05,
                        message_timeout=10.0, turn_stall_s=0.2)
    hang = threading.Event()
    monkeypatch.setattr(b, "_http_json",
                        lambda *a, **k: hang.wait(30.0) or {})
    sse = types.SimpleNamespace(state=b._new_sse_log_state())
    sse.state["turn"] = 0                        # never started a turn
    sse.state["block_types"] = set()             # nothing streamed
    sse.state["turn_ts"] = time.time() - 100
    monkeypatch.setattr(b, "_stop_serve", lambda proc: None)
    try:
        with pytest.raises(_KeepaliveAbort) as ei:
            b._post_message_watched("http://x", "s1", {}, sse, "PROC", "ag", "")
        assert "no new turn" in str(ei.value)
        # no spurious 'last turn 0:' suffix; just the bare turn-stall reason
        assert "last turn 0:" not in str(ei.value)
    finally:
        hang.set()


def test_turn_stall_reason_turn_without_blocks(monkeypatch):
    """A turn that started (turn>0) but streamed no blocks yet (stalled right
    after the user prompt, before any part) → the reason names the turn number
    without an empty ':' suffix. Covers the middle branch of the activity
    ternary (blocks empty, turn>0)."""
    b = OpenCodeBackend(keepalive_idle_s=100.0, keepalive_poll_s=0.05,
                        message_timeout=10.0, turn_stall_s=0.2)
    hang = threading.Event()
    monkeypatch.setattr(b, "_http_json",
                        lambda *a, **k: hang.wait(30.0) or {})
    sse = types.SimpleNamespace(state=b._new_sse_log_state())
    sse.state["turn"] = 5                        # a turn started
    sse.state["block_types"] = set()             # but nothing streamed yet
    sse.state["turn_ts"] = time.time() - 100
    monkeypatch.setattr(b, "_stop_serve", lambda proc: None)
    try:
        with pytest.raises(_KeepaliveAbort) as ei:
            b._post_message_watched("http://x", "s1", {}, sse, "PROC", "ag", "")
        assert "last turn 5" in str(ei.value)        # turn number surfaces
        assert "last turn 5:" not in str(ei.value)   # no empty ':' (no blocks)
    finally:
        hang.set()


def test_post_message_watched_turn_stall_disabled_when_zero(monkeypatch):
    """turn_stall_s=0 → the gate is disabled (rely on keepalive / hard cap),
    matching the '0 = no timeout' semantic of stage timeouts."""
    b = OpenCodeBackend(keepalive_idle_s=100.0, keepalive_poll_s=0.05,
                        message_timeout=0.2, turn_stall_s=0)
    hang = threading.Event()
    monkeypatch.setattr(b, "_http_json",
                        lambda *a, **k: hang.wait(30.0) or {})
    sse = types.SimpleNamespace(state=b._new_sse_log_state())
    sse.state["turn"] = 5
    sse.state["block_types"] = {"tool:read"}
    sse.state["turn_ts"] = time.time() - 1000      # would trip if enabled
    monkeypatch.setattr(b, "_stop_serve", lambda proc: None)
    try:
        with pytest.raises(_KeepaliveAbort) as ei:
            b._post_message_watched("http://x", "s1", {}, sse, "PROC", "ag", "")
        assert "no new turn" not in str(ei.value)   # hard cap owns it instead
    finally:
        hang.set()


# ———————————————————————— SSE handler stamps turn_ts ————————————————

def test_turn_ts_stamped_on_new_turn(monkeypatch):
    """_handle_sse_event bumps turn_ts on message.updated(role=user) and resets
    block_types, so a working agent (turns flowing) keeps the turn-stall gate
    reset while each new turn starts with a fresh block set."""
    b = OpenCodeBackend()
    state = b._new_sse_log_state()
    before = state["turn_ts"]
    time.sleep(0.01)
    # opencode fires message.updated(role=user) BEFORE the assistant parts stream
    b._handle_sse_event(
        {"type": "message.updated",
         "properties": {"info": {"role": "user"}}},
        state, session_id="s1", agent_name="ag", attribution="", start_ms=0)
    assert state["turn"] == 1
    assert state["turn_ts"] > before        # stamped → gate reset
    assert state["block_types"] == set()    # fresh per turn


def test_block_types_accumulate_within_turn(monkeypatch):
    """Within one turn, each streamed block is added to block_types (the set the
    turn-stall reason reports). A tool part records tool:<name> via the shared
    _part_to_block mapper (part.type=tool → tool_use)."""
    b = OpenCodeBackend()
    state = b._new_sse_log_state()
    b._handle_sse_event(
        {"type": "message.updated",
         "properties": {"info": {"role": "user"}}},
        state, session_id="s1", agent_name="ag", attribution="", start_ms=0)
    # a tool part mid-turn (opencode part schema: type=tool, tool=<name>)
    b._handle_sse_event(
        {"type": "message.part.updated",
         "properties": {"part": {"type": "tool", "tool": "read"}}},
        state, session_id="s1", agent_name="ag", attribution="", start_ms=0)
    assert state["block_types"] == {"tool:read"}


# ———————————————————————— Regression: normal agent not mis-killed ———————

def test_post_message_watched_normal_completion_returns_message(monkeypatch):
    """P117 regression: a normal agent (worker returns fast, turn progressing)
    must still return its message — the turn-stall gate doesn't misfire."""
    b = OpenCodeBackend(keepalive_idle_s=1.0, keepalive_poll_s=0.05,
                        turn_stall_s=300.0)
    out = {"parts": [{"type": "text", "text": "done"}]}
    monkeypatch.setattr(b, "_http_json", lambda *a, **k: out)
    sse = types.SimpleNamespace(state=b._new_sse_log_state())

    msg = b._post_message_watched("http://x", "s1", {}, sse, None, "ag", "")

    assert msg == out


# ———————————————————————— message_timeout=0 (disabled hard cap) ———————

def test_post_message_watched_message_timeout_zero_disables_hard_cap(monkeypatch):
    """P117: message_timeout=0 = disabled hard cap (rely on turn-stall/keepalive
    only), matching the '0 = no timeout' semantic of stage timeouts. With all
    gates fresh (turn_ts fresh, last_event_ts fresh) and a slow worker, the
    watchdog must NOT trip hard_timeout — a naive ``deadline = now + 0`` would
    set deadline=now and fire on the first poll. The worker returns normally."""
    b = OpenCodeBackend(keepalive_idle_s=100.0, keepalive_poll_s=0.05,
                        message_timeout=0, turn_stall_s=100.0)
    hang = threading.Event()
    monkeypatch.setattr(b, "_http_json",
                        lambda *a, **k: hang.wait(0.5) or {})
    sse = types.SimpleNamespace(state=b._new_sse_log_state())   # all gates fresh
    monkeypatch.setattr(b, "_stop_serve", lambda proc: None)

    msg = b._post_message_watched("http://x", "s1", {}, sse, "PROC", "ag", "")

    # Worker returned after 0.5s; with hard cap disabled + all gates fresh, no
    # watchdog tripped → empty message (not _KeepaliveAbort).
    assert msg == {}


# ———————————————————————— P137: producer-liveness guard ———————

def test_turn_stall_liveness_chars_growing_not_miskilled(monkeypatch):
    """P137: a stale ``turn_ts`` (no new exchange for turn_stall_s)
    whose ``chars`` keep growing — a genuinely long single-turn generation
    streaming delta text — must NOT be killed as dead. The worker returns its
    message normally instead (a >turn_stall_s slow-but-alive turn survives)."""
    b = OpenCodeBackend(keepalive_idle_s=100.0, keepalive_poll_s=0.02,
                        message_timeout=30.0, turn_stall_s=0.2)
    out = {"parts": [{"type": "text", "text": "done"}]}

    def delayed(*a, **k):
        time.sleep(1.0)          # worker outlives turn_stall_s several times over
        return out
    monkeypatch.setattr(b, "_http_json", delayed)
    sse = types.SimpleNamespace(state=b._new_sse_log_state())
    sse.state["turn"] = 3
    sse.state["block_types"] = {"text"}
    sse.state["turn_ts"] = time.time() - 100      # stale: no new exchange
    stop = threading.Event()

    def _grow():
        while not stop.is_set():
            sse.state["chars"] += 1                # real delta keeps flowing
            time.sleep(0.02)
    grower = threading.Thread(target=_grow, daemon=True)
    grower.start()
    try:
        msg = b._post_message_watched("http://x", "s1", {}, sse, "PROC", "ag", "")
        assert msg == out                        # worker result, NOT _KeepaliveAbort
    finally:
        stop.set()
        grower.join()


def test_turn_stall_liveness_chars_static_trips(monkeypatch):
    """P137: a stale ``turn_ts`` whose ``chars`` have ALSO been static
    for turn_stall_s (streamed earlier, then went silent) IS a real hang — the
    gate still trips, carrying the chars-static window in the reason so the trip
    is distinguishable from a slow-but-alive turn. §P9: non-tool blocks — the
    model-silence population (tool-active turns defer to the keepalive bound,
    see the P9 tests below)."""
    b = OpenCodeBackend(keepalive_idle_s=100.0, keepalive_poll_s=0.02,
                        message_timeout=30.0, turn_stall_s=0.2)
    hang = threading.Event()
    monkeypatch.setattr(b, "_http_json",
                        lambda *a, **k: hang.wait(30.0) or {})
    sse = types.SimpleNamespace(state=b._new_sse_log_state())
    sse.state["turn"] = 4
    sse.state["block_types"] = {"text"}
    sse.state["chars"] = 500                     # streamed earlier...
    sse.state["turn_ts"] = time.time() - 100     # ...then turn stale + silent
    monkeypatch.setattr(b, "_stop_serve", lambda proc: None)
    try:
        with pytest.raises(_KeepaliveAbort) as ei:
            b._post_message_watched("http://x", "s1", {}, sse, "PROC", "ag", "")
        assert "no new turn" in str(ei.value)
        assert "chars static" in str(ei.value)   # diagnostic window surfaced
    finally:
        hang.set()


# ———————————————————————— §step-97: tool 期静默 = 证据判 ————————————————————————
# 旧 §P9 静态让位公式（max(turn_stall, keepalive)）已删：两旋钮收敛 600 后数值
# 清零，且静态界区分不了「挂死工具」与「慢而合法的工具」——该判别移交 pre-trip
# 取证（见 test_step97_pretrip_evidence.py）。这里守护两端边界：

def test_turn_stall_tool_active_no_evidence_trips(monkeypatch):
    """§step-97 反向界：tool 活跃 turn 的静默若**无 running 证据**（真静默——
    工具已完、模型死），model-silence 界直接判死（不再有静态让位）。"""
    b = OpenCodeBackend(keepalive_idle_s=100.0, keepalive_poll_s=0.05,
                        message_timeout=30.0, turn_stall_s=0.2)
    monkeypatch.setattr(b, "_probe_running_tool", lambda sid: None)
    hang = threading.Event()
    monkeypatch.setattr(b, "_http_json",
                        lambda *a, **k: hang.wait(30.0) or {})
    sse = types.SimpleNamespace(state=b._new_sse_log_state())
    sse.state["turn"] = 50
    sse.state["block_types"] = {"thinking", "tool:bash"}
    sse.state["chars"] = 9000
    sse.state["turn_ts"] = time.time() - 100
    monkeypatch.setattr(b, "_stop_serve", lambda proc: None)
    try:
        with pytest.raises(_KeepaliveAbort) as ei:
            b._post_message_watched("http://x", "s1", {}, sse, "PROC", "ag", "")
        assert "no new turn" in str(ei.value)
        assert "tool:bash" in str(ei.value)      # what it was doing surfaced
    finally:
        hang.set()


def test_keepalive_abort_carries_true_kind():
    """P9 去冒充：_KeepaliveAbort 携带真实 kind（turn_stall / keepalive /
    hard_timeout），供 crash-salvage 打真实 aborted 标签——不再把看门狗
    中断一律冒充 hard_timeout（§1.10：一种错误不冒充另一种）。"""
    from ascendc_devkit.capabilities.agent.opencode_backend import _abort_kind
    a = _KeepaliveAbort("no new turn for 128s", kind="turn_stall")
    k = _KeepaliveAbort("no SSE activity", kind="keepalive")
    h = _KeepaliveAbort("exceeded 14400s hard cap", kind="hard_timeout")
    assert _abort_kind(a) == "turn_stall"
    assert _abort_kind(k) == "keepalive"
    assert _abort_kind(h) == "hard_timeout"
    # POST socket timeout（无 kind 的路径）→ hard_timeout（belt-and-suspenders 语义）
    import urllib.error
    import socket
    sock_to = urllib.error.URLError(socket.timeout("timed out"))
    assert _abort_kind(sock_to) == "hard_timeout"
    assert _abort_kind(RuntimeError("logic failure")) is None
