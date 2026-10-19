"""UT for OpenCodeBackend (D1–D4) — no real ``opencode serve``.

Two layers of guard:
  A. Pure config assembly (``_assemble_config`` / ``_project_agents`` /
     ``_resolve_model`` / ``_decision_env`` /
     ``_build_serve_env`` / ``_parts_to_records``) — the D1/D2/D3/D4 projections
     asserted directly, no I/O.
  B. Full ``spawn`` lifecycle driven against a FAKE HTTP/serve by overriding the
     five transport seams (``_pick_free_port`` / ``_start_serve`` /
     ``_wait_healthy`` / ``_http_json`` / ``_stop_serve``). Guards session
     create → sidecar write → blocking message → transcript persist →
     artifact collect → result classification, plus the crash-salvage path.

Everything here is deterministic and millisecond-scale — a real ``opencode``
binary is exercised in the 2.4 live-LLM spikes, not here (§3.8 UT = pure logic).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from unittest import mock

from ascendc_devkit.capabilities.agent.opencode_backend import (
    OpenCodeBackend, _KeepaliveAbort)


# —————————————————————————————————————————————————————————————————————————
# A fake serve: routes the two POSTs OpenCodeBackend makes and records config.
# —————————————————————————————————————————————————————————————————————————
class _FakeServe(OpenCodeBackend):
    """OpenCodeBackend with the transport seams stubbed to a scripted server.

    ``message_parts`` / ``message_info`` script what the blocking message POST
    returns; ``on_start`` fires when serve "starts" (used to plant artifacts).
    """

    def __init__(self, *, message_parts=None, message_info=None,
                 on_start=None, session_id="sess-1", message_history=None, **kw):
        super().__init__(**kw)
        self._script_parts = message_parts or [{"type": "text", "text": "done"}]
        self._script_info = message_info
        self._on_start = on_start
        self._script_session_id = session_id
        # step 61 P2: scripted GET /session/:id/message history. None → a single
        # message mirroring the blocking POST (parity with pre-history behavior).
        self._script_history = message_history
        self.calls = []          # ordered (method, url) log
        self.started = False
        self.stopped = False
        self.serve_env = None

    def _pick_free_port(self):
        return 45999

    def _start_serve(self, env, cwd, port):
        self.started = True
        self.serve_env = env
        if self._on_start:
            self._on_start(cwd)
        return object()  # opaque "process"

    def _wait_healthy(self, base_url):
        self.calls.append(("GET", f"{base_url}/global/health"))

    def _http_json(self, method, url, body=None, timeout=30.0):
        self.calls.append((method, url))
        if url.endswith("/session"):
            return {"id": self._script_session_id}
        if url.endswith("/message"):
            if method == "GET":
                # step 61 P2: session history walk.
                if self._script_history is not None:
                    return self._script_history
                return [{"parts": self._script_parts}]
            out = {"parts": self._script_parts}
            if self._script_info is not None:
                out["info"] = self._script_info
            return out
        return {}

    def _stop_serve(self, proc):
        self.stopped = True

    def _subscribe_sse(self, base_url, session_id, agent_name, attribution, start_ms):
        # No-op for the POST-path UTs (no real serve / no SSE). Streaming-
        # observability logic is covered directly via _handle_sse_event below.
        import types as _types
        return _types.SimpleNamespace(
            state=self._new_sse_log_state(),
            stop_and_join=lambda *a, **k: None)


_PROJECT_CFG = {
    "provider": {"anthropic": {"options": {"apiKey": "sk-live-abc123"}}},
    "model": "anthropic/GLM-5.2",
}


# ———————————————————————— A. pure config assembly ————————————————————————

def test_assemble_config_projects_all_four_decisions():
    b = OpenCodeBackend()
    cfg = b._assemble_config("lingxi-dsl", "ascendc-op-dev-coding",
                             ["ascendc-op-dev-coding", "ascendc-tips"],
                             None, 8123, _PROJECT_CFG)
    # D1 transport
    assert cfg["server"] == {"port": 8123, "hostname": "127.0.0.1"}
    # provider creds are placeholdered out of the config file (D1 secret path);
    # the real apiKey must NOT appear in the on-disk config.
    apikey_in_cfg = cfg["provider"]["anthropic"]["options"]["apiKey"]
    assert apikey_in_cfg == "{env:OPENCODE_SECRET_ANTHROPIC_APIKEY}"
    assert "sk-live-abc123" not in json.dumps(cfg["provider"])
    # D2 skill: allow-all (a closed glob would DROP the tool — Gate 2.0)
    assert cfg["permission"]["skill"] == "allow"
    assert cfg["permission"]["question"] == "deny"
    # P-BC4: external_directory must be allow — agents operate on the worktree
    # (external to the per-stage artifacts cwd); opencode's default "ask" blocks
    # indefinitely in headless non-interactive batch (no permission resolver).
    assert cfg["permission"]["external_directory"] == "allow"
    # D3 agent projection: leaf is primary
    assert cfg["agent"]["lingxi-dsl"]["mode"] == "primary"
    assert cfg["default_agent"] == "lingxi-dsl"
    # subagent_depth is intentionally NOT written: opencode ≤1.17.x rejects it
    # (ConfigInvalidError) despite the online schema listing it; the runtime's
    # built-in default is already 1 (= single-level dispatch, claude parity).
    assert "subagent_depth" not in cfg
    # D4 engine MCP: local stdio, per-spawn params via environment
    eng = cfg["mcp"]["engine"]
    assert eng["type"] == "local"
    assert eng["command"][1:] == ["-m",
                                  "ascendc_devkit.capabilities.engine_mcp_stdio"]
    assert eng["environment"]["ASCENDC_ON_DECISION"] == "default"


def test_project_agents_marks_leaf_primary_rest_subagent():
    b = OpenCodeBackend()
    agents = b._project_agents("ascendc-testing")
    assert agents["ascendc-testing"]["mode"] == "primary"
    # some other real agent must be projected as a subagent
    others = [n for n, a in agents.items() if a["mode"] == "subagent"]
    assert others, "expected sibling .claude/agents/*.md projected as subagents"
    # every projected agent carries a prompt body
    assert all(a.get("prompt") is not None for a in agents.values())


def test_project_agents_denies_manifest_disallowed_tools():
    """A leaf whose manifest disallows Task/AskUserQuestion → permission deny."""
    b = OpenCodeBackend(disallowed_tools=["Task", "AskUserQuestion"])
    perm = b._leaf_permission("lingxi-dsl")
    assert perm.get("task") == "deny"
    assert perm.get("question") == "deny"


def test_project_agents_missing_dir_falls_back_to_leaf(tmp_path, monkeypatch):
    b = OpenCodeBackend()
    monkeypatch.setattr(b, "_agents_dir", lambda: tmp_path / "nope")
    agents = b._project_agents("solo-agent")
    assert list(agents) == ["solo-agent"]
    assert agents["solo-agent"]["mode"] == "primary"


def test_resolve_model_slash_and_bare():
    b = OpenCodeBackend()
    assert b._resolve_model("anthropic/claude-x", {}) == {
        "providerID": "anthropic", "modelID": "claude-x"}
    # bare id takes provider from the single configured provider key
    assert b._resolve_model(None, {"provider": {"anthropic": {}},
                                   "model": "GLM-5.2"}) == {
        "providerID": "anthropic", "modelID": "GLM-5.2"}
    # no model anywhere → fail-fast ConfigError (never a fabricated fallback —
    # that shipped the wrong provider → HTTP 500 on single-provider configs)
    from ascendc_devkit.domain.exceptions import ConfigError
    with pytest.raises(ConfigError) as ei:
        b._resolve_model(None, {"provider": {"anthropic": {}}})
    assert "top-level \"model\"" in str(ei.value)


def test_resolve_model_priority():
    """Model comes from the SDK's canonical top-level field (or an explicit
    override); never a fabricated default."""
    b = OpenCodeBackend(model="anthropic/backend-default")
    # spawn arg wins
    assert b._resolve_model("anthropic/spawn", _PROJECT_CFG) == {
        "providerID": "anthropic", "modelID": "spawn"}
    # then backend default
    assert b._resolve_model(None, _PROJECT_CFG) == {
        "providerID": "anthropic", "modelID": "backend-default"}
    # then project config's canonical top-level model (SDK's own field)
    b2 = OpenCodeBackend()
    assert b2._resolve_model(None, _PROJECT_CFG) == {
        "providerID": "anthropic", "modelID": "GLM-5.2"}
    # provider/id string splits on the first slash
    assert b2._resolve_model(None, {"provider": {"92bpangu": {}},
                                    "model": "92bpangu/pangu_ultra_moe"}) == {
        "providerID": "92bpangu", "modelID": "pangu_ultra_moe"}


def test_assemble_config_overlay_carries_no_model():
    """The per-spawn overlay config must NOT carry a model field: the model
    lives only in the project opencode.json's canonical top-level field, which
    opencode reads natively (reuse the SDK's config capability). The framework
    only sends the model in the message body via ``_resolve_model``."""
    b = OpenCodeBackend()
    cfg = b._assemble_config("lingxi-dsl", "ascendc-op-dev-coding",
                             ["ascendc-op-dev-coding"], None, 8123, _PROJECT_CFG)
    assert "model" not in cfg  # even though _PROJECT_CFG HAS a top-level model
    assert cfg["provider"]["anthropic"]["options"]["apiKey"].startswith("{env:")


def test_decision_env_carries_per_spawn_params(tmp_path):
    b = OpenCodeBackend(interactive=True, on_decision="abort",
                        decision_workspace=tmp_path, webhook_url="http://cb")
    env = b._decision_env()
    assert env["ASCENDC_INTERACTIVE"] == "1"
    assert env["ASCENDC_ON_DECISION"] == "abort"
    assert env["ASCENDC_DECISION_WORKSPACE"] == str(tmp_path)
    assert env["ASCENDC_WEBHOOK_URL"] == "http://cb"


def test_build_serve_env_keeps_real_home_and_writes_config_to_scratch(tmp_path, monkeypatch):
    monkeypatch.setenv("http_proxy", "http://proxy:8080")
    monkeypatch.setenv("HOME", "/real/home")  # operator's real HOME
    b = OpenCodeBackend()
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    env = b._build_serve_env({"model": "x"}, str(scratch), _PROJECT_CFG)
    # Real HOME is kept so opencode natively discovers the user's global
    # config/auth (global-configuration support); NOT overridden to scratch.
    assert env["HOME"] == "/real/home"
    assert env["http_proxy"] == "http://proxy:8080"  # proxy passthrough
    # No skill-disable env: it would also drop the repo's own .claude/skills
    # (discovered via the anchor), so global skills load and the in-repo skill
    # wins same-name collisions natively (see docs/plan .../05-analysis).
    assert "OPENCODE_DISABLE_CLAUDE_CODE_SKILLS" not in env
    assert "OPENCODE_DISABLE_EXTERNAL_SKILLS" not in env
    # bulk config goes to a scratch FILE (OPENCODE_CONFIG path), NOT the real
    # HOME and NOT the 128KB-capped inline OPENCODE_CONFIG_CONTENT env.
    assert "OPENCODE_CONFIG_CONTENT" not in env
    cfg_path = Path(env["OPENCODE_CONFIG"])
    assert cfg_path.parent == scratch
    assert json.loads(cfg_path.read_text()) == {"model": "x"}
    # provider secret travels via ephemeral env, never written to the file.
    assert env["OPENCODE_SECRET_ANTHROPIC_APIKEY"] == "sk-live-abc123"
    # G (P115): XDG pointed at per-spawn scratch subdirs → each opencode serve
    # gets its own SQLite DB (no shared global ~/.local/share/opencode lock
    # contention under batch/ForkJoin concurrency).
    assert env["XDG_DATA_HOME"] == str(scratch / "data")
    assert env["XDG_CONFIG_HOME"] == str(scratch / "config")
    # File-watcher guard (opencode issue #26981): opencode's inotify watcher
    # hangs on a git worktree cwd (.git is a FILE), stalling the serve before
    # the LLM call → turn_stall miskill. Framework serve is headless (agents do
    # their own file I/O), so the watcher is dead weight — disable unconditionally
    # on every spawn.
    assert env["OPENCODE_EXPERIMENTAL_DISABLE_FILEWATCHER"] == "1"


def test_build_serve_env_xdg_isolated_per_spawn(tmp_path, monkeypatch):
    # G (P115): two concurrent spawns get DISTINCT XDG dirs → distinct opencode
    # SQLite DBs → no shared-lock contention (the batch + ForkJoin concurrency
    # root cause). And the framework's own os.environ is NOT polluted (XDG is
    # local to the serve subprocess env dict, never exported to the shell).
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    b = OpenCodeBackend()
    s1 = tmp_path / "s1"; s1.mkdir()
    s2 = tmp_path / "s2"; s2.mkdir()
    env1 = b._build_serve_env({"model": "a"}, str(s1), _PROJECT_CFG)
    env2 = b._build_serve_env({"model": "b"}, str(s2), _PROJECT_CFG)
    # distinct per-spawn XDG → distinct SQLite DBs → no shared-lock contention
    assert env1["XDG_DATA_HOME"] == str(s1 / "data")
    assert env2["XDG_DATA_HOME"] == str(s2 / "data")
    assert env1["XDG_DATA_HOME"] != env2["XDG_DATA_HOME"]
    assert env1["XDG_CONFIG_HOME"] != env2["XDG_CONFIG_HOME"]
    # framework's own os.environ is NOT polluted (XDG only on the subprocess dict)
    import os
    assert "XDG_DATA_HOME" not in os.environ
    assert "XDG_CONFIG_HOME" not in os.environ


def test_split_provider_secrets_keeps_credential_off_disk():
    b = OpenCodeBackend()
    provider = {"anthropic": {
        "options": {"apiKey": "TOPSECRET", "baseURL": "http://gw:3000"},
        "models": {"GLM-5.2": {}}}}
    sanitized, secret_env = b._split_provider_secrets(provider)
    # credential replaced by an {env:VAR} placeholder
    assert (sanitized["anthropic"]["options"]["apiKey"]
            == "{env:OPENCODE_SECRET_ANTHROPIC_APIKEY}")
    assert secret_env == {"OPENCODE_SECRET_ANTHROPIC_APIKEY": "TOPSECRET"}
    # non-secret fields stay literal; real secret nowhere in the sanitized dict
    assert sanitized["anthropic"]["options"]["baseURL"] == "http://gw:3000"
    assert "TOPSECRET" not in json.dumps(sanitized)
    # source not mutated
    assert provider["anthropic"]["options"]["apiKey"] == "TOPSECRET"


def test_parts_to_records_maps_block_types():
    # step 61 P1 (b): blocks follow the SDK schema (kind/tool_name/tool_input)
    # so the single consumer (harvest) reads one schema across both backends.
    b = OpenCodeBackend()
    recs = b._parts_to_records({"parts": [
        {"type": "text", "text": "hi"},
        {"type": "reasoning", "text": "think"},
        {"type": "tool", "tool": "Bash", "state": {"cmd": "ls"}},
        {"type": "step-finish"},
    ]})
    blocks = recs[0]["blocks"]
    assert blocks[0] == {"kind": "text", "text": "hi"}
    assert blocks[1] == {"kind": "thinking", "text": "think"}
    assert blocks[2]["kind"] == "tool_use" and blocks[2]["tool_name"] == "Bash"
    assert blocks[2]["tool_input"] == {"cmd": "ls"}
    assert blocks[3]["kind"] == "step-finish"
    # no legacy type/name/input keys leak on tool blocks
    assert "type" not in blocks[2] and "name" not in blocks[2]


def test_parts_to_records_tool_input_carries_file_path():
    # The provenance-critical field: a Write's file_path must reach tool_input,
    # so harvest can read block["tool_input"]["file_path"] (step 61 P1 → 51).
    b = OpenCodeBackend()
    recs = b._parts_to_records({"parts": [
        {"type": "tool", "tool": "Write",
         "input": {"file_path": "/abs/elsewhere/tiling_split.json"}},
    ]})
    blk = recs[0]["blocks"][0]
    assert blk["kind"] == "tool_use" and blk["tool_name"] == "Write"
    assert blk["tool_input"]["file_path"] == "/abs/elsewhere/tiling_split.json"


def test_parts_to_records_turn_is_passed_through():
    b = OpenCodeBackend()
    recs = b._parts_to_records({"parts": [{"type": "text", "text": "x"}]}, turn=3)
    assert recs[0]["turn"] == 3


def test_extract_history_messages_tolerates_shapes():
    b = OpenCodeBackend()
    assert b._extract_history_messages([{"parts": []}, {"parts": []}]) == \
        [{"parts": []}, {"parts": []}]
    assert b._extract_history_messages({"messages": [{"parts": []}]}) == \
        [{"parts": []}]
    assert b._extract_history_messages(None) == []
    assert b._extract_history_messages("nope") == []


def test_session_transcript_records_walks_history_with_real_turns():
    # step 61 P2: GET history yields per-message records with real turn indices,
    # capturing intermediate tool calls the final message alone would miss.
    b = _FakeServe(message_history=[
        {"parts": [{"type": "tool", "tool": "Write",
                    "input": {"file_path": "/op/tiling_split.json"}}]},
        {"parts": [{"type": "text", "text": "summary"}]},
    ])
    recs = b._session_transcript_records("http://x", "sess-1",
                                         {"parts": [{"type": "text", "text": "fb"}]})
    assert [r["turn"] for r in recs] == [1, 2]
    assert recs[0]["blocks"][0]["kind"] == "tool_use"
    assert recs[0]["blocks"][0]["tool_input"]["file_path"] == "/op/tiling_split.json"
    assert recs[1]["blocks"][0] == {"kind": "text", "text": "summary"}


def test_session_transcript_records_falls_back_on_get_failure():
    # A GET hiccup must not lose the reply nor abort: fall back to the final
    # message at turn 1 (§1.2 best-effort, non-blocking).
    class _Boom(_FakeServe):
        def _http_json(self, method, url, body=None, timeout=30.0):
            if method == "GET" and url.endswith("/message"):
                raise RuntimeError("history GET down")
            return super()._http_json(method, url, body, timeout)
    b = _Boom()
    recs = b._session_transcript_records(
        "http://x", "sess-1", {"parts": [{"type": "text", "text": "final"}]})
    assert len(recs) == 1 and recs[0]["turn"] == 1
    assert recs[0]["blocks"][0] == {"kind": "text", "text": "final"}


def test_session_transcript_records_empty_history_falls_back():
    # GET succeeds but returns an empty/unrecognized history → fall back to the
    # final message (not an empty transcript).
    b = _FakeServe(message_history=[])
    recs = b._session_transcript_records(
        "http://x", "sess-1", {"parts": [{"type": "text", "text": "final"}]})
    assert len(recs) == 1 and recs[0]["turn"] == 1
    assert recs[0]["blocks"][0] == {"kind": "text", "text": "final"}


def test_spawn_transcript_captures_tool_use_from_history(tmp_path):
    # step 61 end-to-end wiring: spawn walks the session history and persists the
    # intermediate Write tool_use (with file_path) the final message alone lacks.
    ws = tmp_path / "ws"
    cwd = tmp_path / "op"

    def plant(_cwd):
        (cwd / "art.json").write_text("{}", encoding="utf-8")

    b = _FakeServe(
        decision_workspace=ws, on_start=plant,
        message_parts=[{"type": "text", "text": "all done"}],  # final message
        message_history=[
            {"parts": [{"type": "tool", "tool": "Write",
                        "input": {"file_path": "/op/art.json"}}]},
            {"parts": [{"type": "text", "text": "all done"}]},
        ],
        project_config_path=_write_project_cfg(tmp_path))
    b.spawn("lingxi-dsl", "go", {}, working_dir=cwd, stage_name="codegen",
            branch_label="A3", primary_skill="ascendc-op-dev-coding")

    # GET session history was issued during spawn.
    assert ("GET", "http://127.0.0.1:45999/session/sess-1/message") in b.calls
    tpaths = list((ws / "agents").glob("*.jsonl"))
    assert tpaths, "expected a transcript jsonl"
    text = tpaths[0].read_text(encoding="utf-8")
    assert '"kind": "tool_use"' in text
    assert '"tool_name": "Write"' in text
    assert "/op/art.json" in text


def test_spawn_crash_writes_crash_record_to_transcript(tmp_path):
    """P94 (step-69): a spawn that crashes before _open_transcript (e.g. message
    POST timed out — run 20260720-095303-413565 buffer-kernel round-1) must still
    produce a transcript carrying a crash record, not vanish silently (which is
    what left that run's round-1 with no transcript file at all)."""
    ws = tmp_path / "ws"
    cwd = tmp_path / "op"
    cwd.mkdir()

    class _CrashPostServe(_FakeServe):
        # Crash the blocking message POST (the timed-out scenario) — propagates
        # to spawn's crash-salvage except (it is not a session-gone signal).
        def _post_message_watched(self, *a, **kw):
            raise TimeoutError("opencode spawn timed out")

    b = _CrashPostServe(decision_workspace=ws,
                        message_parts=[{"type": "text", "text": "x"}],
                        project_config_path=_write_project_cfg(tmp_path))
    res = b.spawn("lingxi-dsl", "go", {}, working_dir=cwd, stage_name="codegen",
                  branch_label="A3", primary_skill="ascendc-op-dev-coding")
    assert res.status == "fatal"  # crashed, no artifacts salvaged
    tpaths = list((ws / "agents").glob("*.jsonl"))
    assert tpaths, "crash must still produce a transcript (P94)"
    text = tpaths[0].read_text(encoding="utf-8")
    assert '"type": "crash"' in text
    assert "timed out" in text


# ———————————————————————— B. full spawn lifecycle ————————————————————————

def test_spawn_happy_path_collects_artifacts_and_clears_sidecar(tmp_path):
    ws = tmp_path / "ws"
    cwd = tmp_path / "op"

    def plant(_cwd):
        (cwd / "kernel.cpp").write_text("// generated", encoding="utf-8")

    b = _FakeServe(decision_workspace=ws, on_start=plant,
                   message_parts=[{"type": "text", "text": "all done"}],
                   project_config_path=_write_project_cfg(tmp_path))
    res = b.spawn("lingxi-dsl", "build me an op", {},
                  working_dir=cwd, stage_name="codegen", branch_label="A3",
                  primary_skill="ascendc-op-dev-coding")

    assert res.status == "ok"
    assert "kernel.cpp" in res.artifacts
    assert b.started and b.stopped                       # serve lifecycle closed
    # session created before message; health polled first
    methods = [u for _, u in b.calls]
    assert any(u.endswith("/session") for u in methods)
    assert any(u.endswith("/message") for u in methods)
    # clean finish → sidecar removed (review M2: 键含 stage_name="codegen")
    assert not b._session_sidecar_path("lingxi-dsl", "A3", "codegen").exists()
    # transcript written
    tpaths = list((ws / "agents").glob("*.jsonl")) if (ws / "agents").exists() else []
    assert tpaths, "expected a transcript jsonl"


def test_spawn_no_artifacts_is_ok_zero_products(tmp_path):
    """F5: 干净完成 + 零产物 → status="ok" + artifacts={}——"空产出"不是
    status 类别，消费方按业务判据查 artifacts。"""
    cwd = tmp_path / "op"
    cwd.mkdir()
    b = _FakeServe(decision_workspace=tmp_path / "ws",
                   project_config_path=_write_project_cfg(tmp_path))
    res = b.spawn("lingxi-dsl", "noop", {}, working_dir=cwd,
                  primary_skill="ascendc-op-dev-coding")
    assert res.status == "ok"
    assert res.artifacts == {}
    assert b.stopped


def test_spawn_message_error_with_artifacts_is_partial(tmp_path, monkeypatch):
    # "model overloaded" 是非 infra 服务端错误 → 走有限次 in-session backoff resume；
    # mock sleep 避免真实退避（否则 6 次 backoff 睡到 max_total=900s 超时）。
    monkeypatch.setattr(
        "ascendc_devkit.capabilities.agent.opencode_backend.time.sleep",
        lambda s: None)
    cwd = tmp_path / "op"

    def plant(_cwd):
        (cwd / "half.cpp").write_text("partial", encoding="utf-8")

    b = _FakeServe(decision_workspace=tmp_path / "ws", on_start=plant,
                   message_info={"error": "model overloaded"},
                   project_config_path=_write_project_cfg(tmp_path))
    res = b.spawn("lingxi-dsl", "x", {}, working_dir=cwd,
                  primary_skill="ascendc-op-dev-coding")
    assert res.status == "partial"
    assert "half.cpp" in res.artifacts
    assert res.metrics.get("failure_reason") == "model overloaded"


def test_spawn_crash_before_session_is_fatal_and_stops_serve(tmp_path):
    cwd = tmp_path / "op"
    cwd.mkdir()

    class _Boom(_FakeServe):
        def _http_json(self, method, url, body=None, timeout=30.0):
            if url.endswith("/session"):
                raise RuntimeError("connection refused")
            return {}

    b = _Boom(decision_workspace=tmp_path / "ws",
              project_config_path=_write_project_cfg(tmp_path))
    res = b.spawn("lingxi-dsl", "x", {}, working_dir=cwd,
                  primary_skill="ascendc-op-dev-coding")
    assert res.status == "fatal"
    assert b.stopped                       # serve always torn down (finally)
    assert res.metrics.get("failure_reason")


# ————————————————————— P-BC5: serve-startup bounded retry ————————————————

class _FlakyHealth(_FakeServe):
    """_wait_healthy raises 'database is locked' for the first N calls (mimics
    the SQLite DB-lock crash under parallel spawn), then succeeds. Counts
    _start_serve calls so retry behavior is assertable."""
    def __init__(self, *, fail_health_times, **kw):
        super().__init__(**kw)
        self._fail_n = fail_health_times
        self.health_calls = 0
        self.start_calls = 0

    def _start_serve(self, env, cwd, port):
        self.start_calls += 1
        return super()._start_serve(env, cwd, port)

    def _wait_healthy(self, base_url):
        self.health_calls += 1
        if self.health_calls <= self._fail_n:
            raise RuntimeError("database is locked")
        super()._wait_healthy(base_url)


def test_spawn_retries_serve_startup_then_succeeds(tmp_path):
    """P-BC5: transient DB-lock crash on attempt 1 → respawn → healthy on
    attempt 2 → spawn completes (not crashed). _start_serve called twice."""
    cwd = tmp_path / "op"
    cwd.mkdir()
    b = _FlakyHealth(fail_health_times=1, spawn_attempts=3,
                     spawn_retry_backoff_s=0,
                     decision_workspace=tmp_path / "ws",
                     project_config_path=_write_project_cfg(tmp_path))
    res = b.spawn("lingxi-dsl", "x", {}, working_dir=cwd,
                  primary_skill="ascendc-op-dev-coding")
    assert b.start_calls == 2          # 1 failed + 1 healthy
    assert b.health_calls == 2
    assert res.status != "fatal"       # retry recovered → spawn succeeded


def test_spawn_exhausts_serve_startup_retries(tmp_path):
    """P-BC5: _wait_healthy fails every attempt → spawn degrades (crashed) only
    AFTER exhausting all spawn_attempts; crash_reason carries the DB-lock cause."""
    cwd = tmp_path / "op"
    cwd.mkdir()
    b = _FlakyHealth(fail_health_times=99, spawn_attempts=3,
                     spawn_retry_backoff_s=0,
                     decision_workspace=tmp_path / "ws",
                     project_config_path=_write_project_cfg(tmp_path))
    res = b.spawn("lingxi-dsl", "x", {}, working_dir=cwd,
                  primary_skill="ascendc-op-dev-coding")
    assert b.start_calls == 3          # exhausted all attempts (no early break)
    assert res.status == "fatal"
    assert "database is locked" in (res.metrics.get("failure_reason") or "")


def test_spawn_writes_sidecar_before_message(tmp_path):
    """The resume handle must be durable before the (long) message call."""
    cwd = tmp_path / "op"
    cwd.mkdir()
    ws = tmp_path / "ws"
    seen = {}

    class _Probe(_FakeServe):
        def _http_json(self, method, url, body=None, timeout=30.0):
            if url.endswith("/message"):
                # sidecar must already exist when the message is sent
                seen["sidecar_at_message"] = self._session_sidecar_path(
                    "lingxi-dsl", "").exists()
            return super()._http_json(method, url, body, timeout)

    b = _Probe(decision_workspace=ws,
               project_config_path=_write_project_cfg(tmp_path))
    b.spawn("lingxi-dsl", "x", {}, working_dir=cwd,
            primary_skill="ascendc-op-dev-coding")
    assert seen.get("sidecar_at_message") is True


def test_spawn_resume_reuses_prior_session(tmp_path):
    """断链② (step-68): resume_session_id reuses the prior opencode session
    (probe-confirmed task 7 — sessions survive a serve restart) instead of
    POSTing a fresh /session. The first message is the bare continue nudge
    (not the stage prompt), the skill steer is skipped (session already loaded
    it), and the sidecar carries the resumed id. Parity with claude's
    resume_session_id path."""
    cwd = tmp_path / "op"
    cwd.mkdir()
    ws = tmp_path / "ws"
    captured = {}

    class _ResumeProbe(_FakeServe):
        def _http_json(self, method, url, body=None, timeout=30.0):
            if url.endswith("/session") and method == "POST":
                captured["fresh_session_posted"] = True
            if (url.endswith("/message") and method == "POST"
                    and "first_body" not in captured):
                captured["first_body"] = body
                # review M2：sidecar 键含 stage_name（spawn 传 stage_name="codegen"）
                captured["sidecar_at_message"] = self._session_sidecar_path(
                    "lingxi-dsl", "A3", "codegen").read_text()
            return super()._http_json(method, url, body, timeout)

    b = _ResumeProbe(decision_workspace=ws,
                     project_config_path=_write_project_cfg(tmp_path))
    res = b.spawn("lingxi-dsl", "build me an op", {},
                  working_dir=cwd, stage_name="codegen", branch_label="A3",
                  resume_session_id="PRIOR-SESSION-7",
                  primary_skill="ascendc-op-dev-coding")

    from ascendc_devkit.capabilities.agent.opencode_backend import _RESUME_PROMPT
    # No fresh POST /session — the prior session_id is reused verbatim.
    assert not captured.get("fresh_session_posted"), \
        "resume must NOT POST a fresh /session (reuse the prior session_id)"
    # First message is the continue nudge, not the stage prompt.
    assert captured["first_body"]["parts"][0]["text"] == _RESUME_PROMPT
    # Skill steer skipped on resume (the session already loaded the skill).
    assert "system" not in captured["first_body"]
    # Sidecar (durable at message time) carries the resumed id.
    assert json.loads(captured["sidecar_at_message"])["session_id"] == "PRIOR-SESSION-7"
    # The message POST targeted the resumed session.
    assert ("POST", "http://127.0.0.1:45999/session/PRIOR-SESSION-7/message") in b.calls
    assert res.status == "ok"


def test_spawn_resume_uses_resume_prompt(tmp_path):
    """Part 3: resume_session_id + resume_prompt → first message carries the
    feedback prompt (not the default ``_RESUME_PROMPT``). 深修场景把上一轮失败
    反馈作为 resume 首条消息送达，agent 无需重读设计/代码。"""
    cwd = tmp_path / "op"
    cwd.mkdir()
    ws = tmp_path / "ws"
    captured = {}

    class _ResumeProbe(_FakeServe):
        def _http_json(self, method, url, body=None, timeout=30.0):
            if (url.endswith("/message") and method == "POST"
                    and "first_body" not in captured):
                captured["first_body"] = body
            return super()._http_json(method, url, body, timeout)

    b = _ResumeProbe(decision_workspace=ws,
                     project_config_path=_write_project_cfg(tmp_path))
    b.spawn("lingxi-dsl", "build me an op", {},
            working_dir=cwd, stage_name="codegen", branch_label="A3",
            resume_session_id="PRIOR-SESSION-7",
            resume_prompt="上一轮 smoke 失败：aclnnInterpolate 缺失，"
                          "请修正 CMake 注册并回验",
            primary_skill="ascendc-op-dev-coding")

    # First message is the resume_prompt feedback, not the default continue nudge.
    assert captured["first_body"]["parts"][0]["text"] == (
        "上一轮 smoke 失败：aclnnInterpolate 缺失，请修正 CMake 注册并回验")
    # Skill steer still skipped on resume (session already loaded the skill).
    assert "system" not in captured["first_body"]


# —————————————————————— M1 (step-68 review): opencode resume session-gone degrade ———
# A stale sidecar may point at a session opencode purged/TTL'd; the resume POST
# then raises HTTP 404 NotFoundError (probe-confirmed — see
# _OPENCODE_SESSION_GONE_MARKERS). The spawn must degrade to a fresh session on
# the SAME serve (clear sidecar + new /session + full stage prompt + skill steer)
# instead of fataling — parity with claude's _SESSION_GONE_MARKERS degrade.

import io  # noqa: E402
import urllib.error  # noqa: E402

from ascendc_devkit.capabilities.agent._shared import _is_opencode_session_gone  # noqa: E402


def _http_404_session_gone(sid: str) -> urllib.error.HTTPError:
    """A faithful opencode session-gone error (probe-confirmed shape): HTTP 404
    with body ``{"name":"NotFoundError","data":{"message":"Session not found: …"}}``."""
    body = json.dumps({
        "name": "NotFoundError",
        "data": {"message": f"Session not found: {sid}"},
    }).encode("utf-8")
    return urllib.error.HTTPError(
        url=f"http://127.0.0.1:45999/session/{sid}/message",
        code=404, msg="Not Found", hdrs=None,
        fp=io.BytesIO(body),
    )


def test_is_opencode_session_gone_detection():
    # Canonical probe shape: 404 NotFoundError → gone.
    assert _is_opencode_session_gone(_http_404_session_gone("ses_x")) is True
    # Body-only belt: a non-HTTPError carrying the wording still matches.
    class _Wordy(Exception):
        pass
    assert _is_opencode_session_gone(
        _Wordy("Session not found: ses_y")) is True
    # Generic 500 (malformed id, NOT the resume scenario) → NOT gone.
    err500 = urllib.error.HTTPError(
        url="http://x", code=500, msg="Internal Server Error", hdrs=None,
        fp=io.BytesIO(b'{"name":"UnknownError","data":{"message":"Unexpected"}}'))
    assert _is_opencode_session_gone(err500) is False
    # A plain non-HTTP exception with no gone signal → NOT gone.
    assert _is_opencode_session_gone(ValueError("boom")) is False


def test_spawn_resume_gone_degrades_to_fresh(tmp_path):
    """M1: resume_session_id whose POST raises HTTP 404 NotFoundError degrades
    to a fresh session on the same serve — clear sidecar, POST a fresh /session,
    re-send the FULL stage prompt + skill steer (not the continue nudge), and
    complete normally. The stage never sees the failed resume."""
    cwd = tmp_path / "op"
    cwd.mkdir()
    ws = tmp_path / "ws"
    captured: dict = {}

    class _GoneThenFresh(_FakeServe):
        def __init__(self, **kw):
            super().__init__(**kw)
            self._message_posts = 0

        def _http_json(self, method, url, body=None, timeout=30.0):
            # The FIRST resume message POST raises the gone signal.
            if url.endswith("/message") and method == "POST":
                self._message_posts += 1
                if self._message_posts == 1:
                    raise _http_404_session_gone("PRIOR-GONE-SESSION")
                # 2nd message POST = the fresh (post-degrade) session: snapshot
                # the sidecar NOW (clean finish clears it on return) and the body.
                captured["fresh_body"] = body
                # review M2：sidecar 键含 stage_name（spawn 传 stage_name="codegen"）
                captured["sidecar_at_fresh_message"] = self._session_sidecar_path(
                    "lingxi-dsl", "A3", "codegen").read_text()
            # The degrade path POSTs a fresh /session — record it + its id.
            if url.endswith("/session") and method == "POST":
                captured.setdefault("fresh_session_posts", 0)
                captured["fresh_session_posts"] += 1
                # Return a distinct id so we can assert the sidecar was rewritten.
                return {"id": "ses-FRESH-1"}
            return super()._http_json(method, url, body, timeout)

    b = _GoneThenFresh(decision_workspace=ws,
                      project_config_path=_write_project_cfg(tmp_path))
    res = b.spawn("lingxi-dsl", "build me an op", {},
                  working_dir=cwd, stage_name="codegen", branch_label="A3",
                  resume_session_id="PRIOR-GONE-SESSION",
                  primary_skill="ascendc-op-dev-coding")

    # Degrade fired: a fresh /session was POSTed (exactly once).
    assert captured.get("fresh_session_posts") == 1, (
        "resume session-gone must degrade to a fresh /session POST")
    # Fresh session's first message carries the FULL stage prompt + skill steer
    # (not the bare continue nudge — the fresh session has no prior context).
    assert captured["fresh_body"]["parts"][0]["text"] == "build me an op"
    assert captured["fresh_body"].get("system"), (
        "degrade must re-apply the skill steer on the fresh session")
    # Sidecar rewritten to the fresh id (the stale one was cleared first); read
    # at message time because clean finish clears it on return.
    sidecar = json.loads(captured["sidecar_at_fresh_message"])
    assert sidecar["session_id"] == "ses-FRESH-1"
    # The spawn completed cleanly — the stage never sees the failed resume.
    assert res.status == "ok", (
        f"degrade must complete the spawn, got status={res.status}")


def test_spawn_resume_non_gone_error_does_not_degrade(tmp_path):
    """M1 belt: a NON-gone error on the resume POST (e.g. generic 500) must NOT
    degrade — it falls through to crash-salvage like any other spawn failure.
    Degradation is exclusively for the session-gone signal."""
    cwd = tmp_path / "op"
    cwd.mkdir()
    ws = tmp_path / "ws"
    posted_fresh = []

    class _Generic500(_FakeServe):
        def __init__(self, **kw):
            super().__init__(**kw)
            self._first_message_tried = False

        def _http_json(self, method, url, body=None, timeout=30.0):
            if (url.endswith("/message") and method == "POST"
                    and not self._first_message_tried):
                self._first_message_tried = True
                raise urllib.error.HTTPError(
                    url="http://x", code=500, msg="Internal Server Error",
                    hdrs=None,
                    fp=io.BytesIO(b'{"name":"UnknownError","data":{}}'))
            if url.endswith("/session") and method == "POST":
                posted_fresh.append(1)
            return super()._http_json(method, url, body, timeout)

    b = _Generic500(decision_workspace=ws,
                    project_config_path=_write_project_cfg(tmp_path))
    res = b.spawn("lingxi-dsl", "build me an op", {},
                  working_dir=cwd, stage_name="codegen", branch_label="A3",
                  resume_session_id="PRIOR-SESSION")
    # No degrade: the generic 500 must not trigger a fresh /session POST.
    assert not posted_fresh, (
        "a non-gone error must NOT degrade — it should crash-salvage")
    # Crash-salvage path: no artifacts → fatal (the spawn failed).
    assert res.status == "fatal"


# —————————————————————————— helpers ——————————————————————————

def _write_project_cfg(tmp_path: Path) -> Path:
    p = tmp_path / "opencode.json"
    p.write_text(json.dumps(_PROJECT_CFG), encoding="utf-8")
    return p


# ——————————— load-time guard: baseURL must carry /v1 (§1.3) ———————————
# Regression fence for the silent empty-reply gotcha (opencode ai-sdk posts
# ${baseURL}/messages; a baseURL without /v1 hits the gateway dashboard → empty
# stream, status ok, 0 tokens). See docs/plan/opencode-sdk-backend/
# 03-headless-env-gotchas.md §一.A.

def test_validate_rejects_anthropic_baseurl_without_v1():
    from ascendc_devkit.domain.exceptions import ConfigError
    cfg = {"provider": {"anthropic": {"options": {
        "baseURL": "http://gw:3000", "apiKey": "x"}}}}
    with pytest.raises(ConfigError, match="/v1"):
        OpenCodeBackend._validate_project_config(cfg, Path("opencode.json"))


def test_validate_accepts_baseurl_with_v1_and_absent_baseurl():
    # trailing-slash tolerant + absent baseURL (creds via env) both pass
    OpenCodeBackend._validate_project_config(
        {"provider": {"anthropic": {"options": {"baseURL": "http://gw:3000/v1/"}}}},
        Path("opencode.json"))
    OpenCodeBackend._validate_project_config(
        {"provider": {"anthropic": {"options": {"apiKey": "x"}}}},
        Path("opencode.json"))
    OpenCodeBackend._validate_project_config({}, Path("opencode.json"))


def test_load_project_config_raises_on_bad_baseurl(tmp_path):
    from ascendc_devkit.domain.exceptions import ConfigError
    p = tmp_path / "opencode.json"
    p.write_text(json.dumps({"provider": {"anthropic": {"options": {
        "baseURL": "http://gw:3000"}}}}), encoding="utf-8")
    b = OpenCodeBackend(project_config_path=p)
    with pytest.raises(ConfigError):
        b._load_project_config(tmp_path, tmp_path)


# ———————————————————— step-57 (P80): 429 backoff-resume ————————————————————

class _Rate429Serve(_FakeServe):
    """Returns a 429 error on the first ``fail_times`` message POSTs, then a
    clean success. Records how many /message POSTs were issued."""

    def __init__(self, *, fail_times=1, **kw):
        super().__init__(**kw)
        self._fail_times = fail_times
        self.message_posts = 0

    def _http_json(self, method, url, body=None, timeout=30.0):
        self.calls.append((method, url))
        if url.endswith("/session"):
            return {"id": self._script_session_id}
        if url.endswith("/message"):
            if method == "GET":                       # step 61 P2: history walk
                return [{"parts": self._script_parts}]
            self.message_posts += 1
            if self.message_posts <= self._fail_times:
                return {"parts": self._script_parts,
                        "info": {"error": "Request rejected (429) · "
                                          "Weekly/Monthly Limit Exhausted"}}
            return {"parts": self._script_parts}
        return {}


def test_opencode_429_backoff_then_resume_succeeds(tmp_path, monkeypatch):
    slept = []
    monkeypatch.setattr(
        "ascendc_devkit.capabilities.agent.opencode_backend.time.sleep",
        lambda s: slept.append(s))
    cwd = tmp_path / "op"

    def plant(_cwd):
        (cwd / "kernel.cpp").write_text("// generated", encoding="utf-8")

    b = _Rate429Serve(
        fail_times=2, decision_workspace=tmp_path / "ws", on_start=plant,
        project_config_path=_write_project_cfg(tmp_path),
        rate_limit_max_retries=5, rate_limit_backoff_base_s=1.0,
        rate_limit_backoff_factor=2.0, rate_limit_backoff_max_total_s=1000.0)
    res = b.spawn("lingxi-dsl", "build", {}, working_dir=cwd,
                  branch_label="A3", primary_skill="ascendc-op-dev-coding")

    assert res.status == "ok"
    assert b.message_posts == 3, "2 rejected + 1 success"
    assert slept == [1.0, 2.0], "exponential backoff between the 3 posts"
    # A completed spawn clears the sidecar.
    assert not b._session_sidecar_path("lingxi-dsl", "A3").exists()


def test_opencode_429_backoff_exhausted_halts(tmp_path, monkeypatch):
    slept = []
    monkeypatch.setattr(
        "ascendc_devkit.capabilities.agent.opencode_backend.time.sleep",
        lambda s: slept.append(s))
    cwd = tmp_path / "op"
    cwd.mkdir()

    # Never clears (fail_times huge) → backoff budget exhausted → halt.
    b = _Rate429Serve(
        fail_times=999, decision_workspace=tmp_path / "ws",
        project_config_path=_write_project_cfg(tmp_path),
        rate_limit_max_retries=2, rate_limit_backoff_base_s=1.0,
        rate_limit_backoff_factor=2.0, rate_limit_backoff_max_total_s=1000.0)
    res = b.spawn("lingxi-dsl", "build", {}, working_dir=cwd,
                  primary_skill="ascendc-op-dev-coding")

    # 1 initial + 2 retries = 3 posts, then give up (bounded, no infinite loop).
    assert b.message_posts == 3
    assert slept == [1.0, 2.0]
    assert res.status in ("fatal", "partial")
    # The 429 cause rides into failure_reason (build_result reads info.error).
    assert "429" in (res.metrics or {}).get("failure_reason", "")


def test_server_error_thinking_retryable_resume(tmp_path, monkeypatch):
    """黑名单排除语义（20260812 策略分离）：非 infra 服务端错误（APIError thinking
    回传，本批实证）→ 不再 fall-through 到 halt，走有限次立即 resume（策略 'resume'，
    不 sleep——避免误判空等）。耗尽后仍由 build_result 判 partial/fatal（错误原文进
    failure_reason）。"""
    slept = []
    monkeypatch.setattr(
        "ascendc_devkit.capabilities.agent.opencode_backend.time.sleep",
        lambda s: slept.append(s))
    cwd = tmp_path / "op"
    cwd.mkdir()
    err = ("The `content[].thinking` in the thinking mode must be passed back to "
           "the API. (request id: 202608111917167400285358268d9d6q1w6fKM3)")
    b = _FakeServe(decision_workspace=tmp_path / "ws",
                   message_info={"error": err},
                   project_config_path=_write_project_cfg(tmp_path),
                   rate_limit_max_retries=2, rate_limit_backoff_base_s=1.0,
                   rate_limit_backoff_factor=2.0, rate_limit_backoff_max_total_s=1000.0)
    res = b.spawn("lingxi-dsl", "x", {}, working_dir=cwd,
                  primary_skill="ascendc-op-dev-coding")

    # 1 initial + 1 resume = 2 POSTs（立即 resume，不 sleep）
    posts = sum(1 for m, u in b.calls if u.endswith("/message") and m == "POST")
    assert posts == 2
    assert slept == [], "策略 'resume' 立即续跑，不 sleep（不空等）"
    # 耗尽仍 error → 错误原文进 failure_reason（可观测，主日志可见）
    assert res.status in ("fatal", "partial")
    assert "thinking" in (res.metrics or {}).get("failure_reason", "")


def test_infra_message_error_no_backoff(tmp_path, monkeypatch):
    """黑名单语义：infra（不可重试，401）→ 立即 break，不 in-session backoff
    （P116 infra halt 不变），错误原文进主日志。"""
    slept = []
    monkeypatch.setattr(
        "ascendc_devkit.capabilities.agent.opencode_backend.time.sleep",
        lambda s: slept.append(s))
    cwd = tmp_path / "op"
    cwd.mkdir()
    b = _FakeServe(decision_workspace=tmp_path / "ws",
                   message_info={"error": "API Error: 401 Unauthorized"},
                   project_config_path=_write_project_cfg(tmp_path),
                   rate_limit_max_retries=5, rate_limit_backoff_base_s=1.0,
                   rate_limit_backoff_factor=2.0, rate_limit_backoff_max_total_s=1000.0)
    res = b.spawn("lingxi-dsl", "x", {}, working_dir=cwd,
                  primary_skill="ascendc-op-dev-coding")

    posts = sum(1 for m, u in b.calls if u.endswith("/message") and m == "POST")
    assert posts == 1, "infra 不 backoff，只 POST 一次"
    assert slept == []
    assert res.status in ("fatal", "partial")


# ———————————————————————— streaming observability (design B) ———————————————
# _handle_sse_event is the real-time agent_stream logic; tested directly
# (monkeypatching Logger.action) — no thread, no I/O.
def _sse_ctx(**over):
    ctx = dict(session_id="", agent_name="coder", attribution="[s] ", start_ms=0)
    ctx.update(over)
    return ctx


def test_sse_emits_agent_stream_on_assistant_text_part(monkeypatch):
    logs = []
    monkeypatch.setattr(
        "ascendc_devkit.capabilities.agent.opencode_backend.Logger.action",
        lambda t, d: logs.append((t, d)))
    b = OpenCodeBackend()
    state = b._new_sse_log_state()
    # turn bumps on the user-message boundary (fires before the response parts)
    b._handle_sse_event({"type": "message.updated",
                         "properties": {"info": {"role": "user"}}},
                        state, **_sse_ctx())
    b._handle_sse_event({"type": "message.part.updated",
                         "properties": {"part": {"type": "text", "text": "hi"}}},
                        state, **_sse_ctx())
    streams = [d for t, d in logs if t == "agent_stream"]
    assert len(streams) == 1
    assert streams[0].startswith("[s] coder turn 1 (text)")


def test_sse_skips_step_markers_but_logs_text_and_tool(monkeypatch):
    logs = []
    monkeypatch.setattr(
        "ascendc_devkit.capabilities.agent.opencode_backend.Logger.action",
        lambda t, d: logs.append((t, d)))
    b = OpenCodeBackend()
    state = b._new_sse_log_state()
    b._handle_sse_event({"type": "message.updated",
                         "properties": {"info": {"role": "user"}}},
                        state, **_sse_ctx())
    # step markers are filtered as noise (no agent_stream) …
    b._handle_sse_event({"type": "message.part.updated",
                         "properties": {"part": {"type": "step-start"}}},
                        state, **_sse_ctx())
    b._handle_sse_event({"type": "message.part.updated",
                         "properties": {"part": {"type": "step-finish"}}},
                        state, **_sse_ctx())
    # … but text + tool parts DO log (real-time signal)
    b._handle_sse_event({"type": "message.part.updated",
                         "properties": {"part": {"type": "text", "text": "x"}}},
                        state, **_sse_ctx())
    b._handle_sse_event({"type": "message.part.updated",
                         "properties": {"part": {"type": "tool", "tool": "Read"}}},
                        state, **_sse_ctx())
    streams = [d for t, d in logs if t == "agent_stream"]
    assert len(streams) == 2  # text + tool only; step markers skipped
    assert "(text)" in streams[0] and "tool:Read" in streams[1]


def test_sse_tags_tool_use(monkeypatch):
    logs = []
    monkeypatch.setattr(
        "ascendc_devkit.capabilities.agent.opencode_backend.Logger.action",
        lambda t, d: logs.append((t, d)))
    b = OpenCodeBackend()
    state = b._new_sse_log_state()
    b._handle_sse_event({"type": "message.updated",
                         "properties": {"info": {"role": "assistant"}}},
                        state, **_sse_ctx())
    b._handle_sse_event({"type": "message.part.updated",
                         "properties": {"part": {"type": "tool", "tool": "Read"}}},
                        state, **_sse_ctx())
    assert "(tool:Read)" in logs[-1][1]


def test_sse_delta_accumulates_chars(monkeypatch):
    logs = []
    monkeypatch.setattr(
        "ascendc_devkit.capabilities.agent.opencode_backend.Logger.action",
        lambda t, d: logs.append((t, d)))
    b = OpenCodeBackend()
    state = b._new_sse_log_state()
    b._handle_sse_event({"type": "message.updated",
                         "properties": {"info": {"role": "assistant"}}},
                        state, **_sse_ctx())
    for chunk in ("Hel", "lo ", "world"):
        b._handle_sse_event({"type": "message.part.delta",
                             "properties": {"field": "text", "delta": chunk}},
                            state, **_sse_ctx())
    b._handle_sse_event({"type": "message.part.updated",
                         "properties": {"part": {"type": "text", "text": "Hello world"}}},
                        state, **_sse_ctx())
    # 11 chars accumulated from deltas surface in the agent_stream line
    assert "11 chars" in logs[-1][1]


def test_sse_captures_tokens_from_message_updated():
    b = OpenCodeBackend()
    state = b._new_sse_log_state()
    b._handle_sse_event({"type": "message.updated", "properties": {
        "info": {"role": "assistant",
                 "tokens": {"input": 32033, "output": 2}}}},
        state, **_sse_ctx())
    assert state["tokens"] == {"input": 32033, "output": 2}


def test_sse_filters_other_session():
    b = OpenCodeBackend()
    state = b._new_sse_log_state()
    ctx = _sse_ctx(session_id="ses_MINE")
    # event from a different session → ignored (no role/token capture)
    b._handle_sse_event({"type": "message.updated",
                         "properties": {"sessionID": "ses_OTHER",
                                        "info": {"role": "assistant",
                                                 "tokens": {"input": 1}}}},
                        state, **ctx)
    assert state["current_role"] is None and state["tokens"] is None


# ——————————— step-113 (P11-C): session.compacted → metrics["compactions"] ———

class _FakeSSE:
    """Minimal stand-in: only ``state`` is consumed by _compaction_metrics."""

    def __init__(self, state):
        self.state = state


def test_sse_compacted_events_counted_and_logged(monkeypatch):
    logs = []
    monkeypatch.setattr(
        "ascendc_devkit.capabilities.agent.opencode_backend.Logger.action",
        lambda t, d: logs.append((t, d)))
    b = OpenCodeBackend()
    state = b._new_sse_log_state()
    for _ in range(2):
        b._handle_sse_event({"type": "session.compacted", "properties": {"sessionID": "ses_1"}},
                            state, **_sse_ctx())
    assert b._compaction_metrics(_FakeSSE(state), "coder", "[s] ") == {
        "compactions": 2}
    # 事实性日志一行：实测数字，无判断词
    compacts = [d for t, d in logs if t == "agent_compacted"]
    assert len(compacts) == 1 and "x2" in compacts[0]


def test_sse_no_compaction_zero_written_no_log(monkeypatch):
    logs = []
    monkeypatch.setattr(
        "ascendc_devkit.capabilities.agent.opencode_backend.Logger.action",
        lambda t, d: logs.append((t, d)))
    b = OpenCodeBackend()
    state = b._new_sse_log_state()
    b._handle_sse_event({"type": "message.updated",
                         "properties": {"info": {"role": "user"}}},
                        state, **_sse_ctx())
    # 0 也写——键在即「本 spawn 有观测、零冲刷」
    assert b._compaction_metrics(_FakeSSE(state), "coder", "[s] ") == {
        "compactions": 0}
    assert not [d for t, d in logs if t == "agent_compacted"]


def test_sse_compaction_not_reset_by_turn_bump():
    # spawn 级累计：compaction 后新 turn（message.updated role=user）不清零
    b = OpenCodeBackend()
    state = b._new_sse_log_state()
    b._handle_sse_event({"type": "session.compacted", "properties": {"sessionID": "ses_1"}},
                        state, **_sse_ctx())
    b._handle_sse_event({"type": "message.updated",
                         "properties": {"info": {"role": "user"}}},
                        state, **_sse_ctx())
    assert state["compactions"] == 1


def test_sse_compaction_per_spawn_state_isolated():
    # 两次 spawn 各自 _new_sse_log_state → 独立计数（无跨 spawn 泄漏）
    b = OpenCodeBackend()
    s1, s2 = b._new_sse_log_state(), b._new_sse_log_state()
    b._handle_sse_event({"type": "session.compacted", "properties": {"sessionID": "ses_1"}},
                        s1, **_sse_ctx())
    assert s1["compactions"] == 1 and s2["compactions"] == 0


def test_sse_compaction_other_session_filtered():
    b = OpenCodeBackend()
    state = b._new_sse_log_state()
    b._handle_sse_event({"type": "session.compacted",
                         "properties": {"sessionID": "ses_OTHER"}},
                        state, **_sse_ctx(session_id="ses_MINE"))
    assert state["compactions"] == 0


def test_compaction_metrics_absent_key_when_sse_never_ran():
    # SSE 未启动（早夭/预 spawn 超时）→ 键缺失，缺失 ≠ 零冲刷
    b = OpenCodeBackend()
    assert b._compaction_metrics(None, "coder", "[s] ") == {}


# ———————————————————————— AU-6: SSE daemon thread run.log inheritance ————————

def test_subscribe_sse_thread_writes_agent_stream_into_bound_run_log(tmp_path, monkeypatch):
    """AU-6 regression: real ``_subscribe_sse`` starts its daemon reader via
    ``spawn_context_thread`` (not a plain ``threading.Thread``), so it inherits
    the CALLER thread's bound run.log — the ``agent_stream`` line must land in
    the per-op run.log, not just console/batch log."""
    from ascendc_devkit.infra.log_capture import bind_run_log, unbind_run_log
    import ascendc_devkit.capabilities.agent.opencode_backend as ocb_mod

    log = tmp_path / "run.log"
    bind_run_log(log)
    try:
        frame = (b'data: {"type": "message.part.updated", "properties": '
                 b'{"part": {"type": "text", "text": "hi"}}}\n\n')

        class _FakeResp:
            def __init__(self, payload):
                self._buf = payload

            def readline(self):
                if not self._buf:
                    return b""
                nl = self._buf.find(b"\n") + 1
                line, self._buf = self._buf[:nl], self._buf[nl:]
                return line

            def close(self):
                pass

        monkeypatch.setattr(
            ocb_mod.urllib.request, "urlopen",
            lambda *a, **k: _FakeResp(frame))

        b = ocb_mod.OpenCodeBackend()
        handle = b._subscribe_sse("http://fake", "", "coder", "[s] ", 0)
        handle.stop_and_join(timeout=5.0)

        assert "agent_stream" in log.read_text(encoding="utf-8")
    finally:
        unbind_run_log()


def test_concurrent_ops_same_stage_produce_distinguishable_attribution(tmp_path):
    """AU-7 regression: two concurrent execs sharing the same stage_name/
    branch_label (the batch-concurrency scenario the audit called out — e.g.
    5 ops all in ``precision-perf/T2``) must produce attribution distinguishable
    by op_name, not identical ``[stage/branch]`` lines an operator can't
    attribute back to a specific op."""
    import threading
    from ascendc_devkit.infra.log_capture import bind_op_name, bind_run_log, unbind_run_log

    results: dict[str, str] = {}
    errors: list[BaseException] = []

    def _run(op_name: str):
        try:
            bind_op_name(op_name)
            log = tmp_path / f"{op_name}.run.log"
            bind_run_log(log)
            # _resolve_model fail-fast: opencode serve needs the model in the
            # message body (no auto-resolve from a config with no top-level
            # model); the fixture project has no opencode.json, so pin the model
            # explicitly on the backend.
            b = _FakeServe(message_parts=[{"type": "text", "text": "done"}],
                           model="anthropic/test-model")
            b.spawn("coder", "go", {}, working_dir=tmp_path / op_name,
                    stage_name="precision-perf", branch_label="T2")
            results[op_name] = log.read_text(encoding="utf-8")
        except BaseException as e:  # noqa: BLE001
            errors.append(e)
        finally:
            unbind_run_log()

    threads = [threading.Thread(target=_run, args=(name,))
               for name in ("OpA", "OpB")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"concurrent spawn raised: {errors}"
    assert "[OpA/precision-perf/T2]" in results["OpA"]
    assert "[OpB/precision-perf/T2]" in results["OpB"]
    # No cross-talk: each op's run.log only carries its own attribution.
    assert "[OpB/precision-perf/T2]" not in results["OpA"]
    assert "[OpA/precision-perf/T2]" not in results["OpB"]


# ———————————————————————— P-BC2: serve stderr 落盘（非 DEVNULL） ————————————

def test_start_serve_writes_log_not_devnull_and_closes_on_stop(tmp_path, monkeypatch):
    """P-BC2: opencode serve stdout/stderr must NOT be DEVNULL — a stalled
    design needs the daemon's own output to locate the hang (§1.3 expose-don't-
    hide; external-infra "leave a diagnostic signal"). The serve log lands in
    scratch_dir (co-located with OPENCODE_CONFIG, NOT the agent's artifacts
    cwd), stderr merges into stdout (one stream), and _stop_serve closes the
    handle (no fd leak). Popen is stubbed so no real opencode is launched."""
    import subprocess

    b = OpenCodeBackend()
    scratch = tmp_path / "ws" / ".opencode_home"
    scratch.mkdir(parents=True)
    env = {"OPENCODE_CONFIG": str(scratch / "opencode-config.json"),
           "PATH": "/usr/bin"}
    captured: dict = {}

    class _FakeProc:
        def terminate(self): pass
        def wait(self, timeout=None): pass

    def _fake_popen(argv, **kw):
        captured["stdout"] = kw["stdout"]
        captured["stderr"] = kw["stderr"]
        return _FakeProc()

    monkeypatch.setattr(
        "ascendc_devkit.capabilities.agent.opencode_backend.subprocess.Popen",
        _fake_popen)

    proc = b._start_serve(env, str(tmp_path / "cwd"), 48123)

    # NOT DEVNULL — a real file handle so serve output survives a hang.
    assert captured["stdout"] is not subprocess.DEVNULL
    assert captured["stderr"] == subprocess.STDOUT  # stderr merged in
    # Co-located with OPENCODE_CONFIG (scratch_dir), port-named — not in cwd.
    assert proc.serve_log_path == str(scratch / ".opencode-serve-48123.log")
    handle = proc.serve_log_handle
    assert not handle.closed
    # _stop_serve closes the handle (fd hygiene).
    b._stop_serve(proc)
    assert handle.closed


def test_start_serve_starts_new_session(tmp_path, monkeypatch):
    """S4: _start_serve uses start_new_session so the serve + its engine MCP
    child form a process group _stop_serve can kill wholesale (no orphans)."""
    b = OpenCodeBackend()
    scratch = tmp_path / "ws" / ".opencode_home"
    scratch.mkdir(parents=True)
    env = {"OPENCODE_CONFIG": str(scratch / "c.json"), "PATH": "/usr/bin"}
    captured: dict = {}

    class _FakeProc:
        pid = 99999
        def wait(self, timeout=None): pass
        def terminate(self): pass

    def _fake_popen(argv, **kw):
        captured.update(kw)
        return _FakeProc()

    monkeypatch.setattr(
        "ascendc_devkit.capabilities.agent.opencode_backend.subprocess.Popen",
        _fake_popen)
    b._start_serve(env, str(tmp_path / "cwd"), 48123)
    assert captured.get("start_new_session") is True


def test_stop_serve_kills_whole_process_group(tmp_path, monkeypatch):
    """S4: _stop_serve kills the serve's whole process group (serve + engine MCP
    child) via os.killpg with SIGTERM→SIGKILL escalation — proc.terminate alone
    only hits the serve and orphans the child."""
    import signal as _signal
    import subprocess
    b = OpenCodeBackend()
    killed: list = []

    class _FakeProc:
        pid = 4242
        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired(cmd="serve", timeout=timeout)

    monkeypatch.setattr(
        "ascendc_devkit.capabilities.agent.opencode_backend.os.getpgid",
        lambda pid: 4242)
    monkeypatch.setattr(
        "ascendc_devkit.capabilities.agent.opencode_backend.os.killpg",
        lambda pgid, sig: killed.append(sig))
    proc = _FakeProc()
    proc.serve_log_handle = None
    b._stop_serve(proc)
    assert _signal.SIGTERM in killed
    assert _signal.SIGKILL in killed  # wait timed out → SIGKILL escalation


def test_serve_proc_tracked_and_removed_on_stop(tmp_path, monkeypatch):
    """S4b: _start_serve registers the proc for the atexit backstop; _stop_serve
    removes it. A spawn interrupted mid-flight (no _stop_serve) leaves it tracked
    so atexit can clean up."""
    from ascendc_devkit.capabilities.agent.opencode_backend import (
        _ACTIVE_SERVE_PROCS)
    _ACTIVE_SERVE_PROCS.clear()  # defensive isolation
    b = OpenCodeBackend()
    scratch = tmp_path / "ws" / ".opencode_home"
    scratch.mkdir(parents=True)
    env = {"OPENCODE_CONFIG": str(scratch / "c.json"), "PATH": "/usr/bin"}

    class _FakeProc:
        pid = 7777
        def wait(self, timeout=None): pass
        def terminate(self): pass

    monkeypatch.setattr(
        "ascendc_devkit.capabilities.agent.opencode_backend.subprocess.Popen",
        lambda *a, **kw: _FakeProc())
    proc = b._start_serve(env, str(tmp_path / "cwd"), 48123)
    try:
        assert proc in _ACTIVE_SERVE_PROCS
        b._stop_serve(proc)
        assert proc not in _ACTIVE_SERVE_PROCS
    finally:
        _ACTIVE_SERVE_PROCS.discard(proc)


def test_atexit_cleanup_stops_remaining_procs(monkeypatch):
    """S4b: _atexit_cleanup_serve_procs stops any serve proc still alive on
    interpreter exit (spawn interrupted mid-flight → _stop_serve never ran)."""
    import signal as _signal
    from ascendc_devkit.capabilities.agent.opencode_backend import (
        _ACTIVE_SERVE_PROCS, _atexit_cleanup_serve_procs)
    _ACTIVE_SERVE_PROCS.clear()
    killed: list = []

    class _FakeProc:
        pid = 8888
        def wait(self, timeout=None): pass
        def terminate(self): pass

    proc = _FakeProc()
    proc.serve_log_handle = None
    _ACTIVE_SERVE_PROCS.add(proc)
    monkeypatch.setattr(
        "ascendc_devkit.capabilities.agent.opencode_backend.os.getpgid",
        lambda pid: 8888)
    monkeypatch.setattr(
        "ascendc_devkit.capabilities.agent.opencode_backend.os.killpg",
        lambda pgid, sig: killed.append(sig))
    _atexit_cleanup_serve_procs()
    assert _signal.SIGTERM in killed
    assert proc not in _ACTIVE_SERVE_PROCS  # cleared after cleanup


def test_serve_log_path_falls_back_to_tmpdir_without_config():
    """Defensive: no OPENCODE_CONFIG → temp dir base (never raises, never
    DEVNULL). _build_serve_env always sets OPENCODE_CONFIG, so this is the
    belt-and-suspenders path."""
    b = OpenCodeBackend()
    p = b._serve_log_path({}, 9999)
    assert p.name == ".opencode-serve-9999.log"
    assert p.parent.exists()


# ———————————————————————— P-BC3: keepalive + hard-timeout watchdog ———————————

def test_is_hard_timeout_exc_classifies_timeouts():
    """S5 fix guard (§P9 重写为 _abort_kind): a watchdog kill carries its TRUE
    kind (turn_stall / keepalive / hard_timeout — no masquerade), and a urllib
    POST socket timeout (URLError wrapping socket.timeout) still classifies as
    "hard_timeout" → aborted set. Without this, a tightened-deadline POST whose
    byte-idle socket timed out before the watchdog raised a plain URLError →
    aborted=None (the hard-wall regression the heavy_llm ST caught)."""
    import socket
    import urllib.error
    from ascendc_devkit.capabilities.agent.opencode_backend import _abort_kind

    assert _abort_kind(_KeepaliveAbort("x")) == "hard_timeout"  # default kind
    assert _abort_kind(
        _KeepaliveAbort("stall", kind="turn_stall")) == "turn_stall"
    assert _abort_kind(
        _KeepaliveAbort("idle", kind="keepalive")) == "keepalive"
    assert _abort_kind(TimeoutError("timed out")) == "hard_timeout"
    # urllib POST socket timeout: URLError.reason = socket.timeout (== TimeoutError)
    assert _abort_kind(
        urllib.error.URLError(socket.timeout("timed out"))) == "hard_timeout"
    # Non-timeout errors are NOT hard terminations (e.g. 404 session-gone).
    assert _abort_kind(
        urllib.error.URLError(ConnectionRefusedError("no"))) is None
    assert _abort_kind(RuntimeError("boom")) is None


def test_post_message_watched_returns_message_on_normal_completion(monkeypatch):
    """P-BC3: when the POST completes normally the watchdog returns its result
    (no abort). Worker finishes fast → first join returns immediately."""
    import types

    b = OpenCodeBackend(keepalive_idle_s=1.0, keepalive_poll_s=0.05)
    out = {"parts": [{"type": "text", "text": "done"}]}
    monkeypatch.setattr(b, "_http_json", lambda *a, **k: out)
    sse = types.SimpleNamespace(state=b._new_sse_log_state())

    msg = b._post_message_watched("http://x", "s1", {}, sse, None, "ag", "")

    assert msg == out


def test_post_message_watched_aborts_on_sse_idle(monkeypatch):
    """P-BC3: if SSE goes idle beyond keepalive_idle_s the agent is deemed hung
    → _KeepaliveAbort raised + serve killed to unblock the POST (no 1h空烧)."""
    import threading
    import time
    import types

    b = OpenCodeBackend(keepalive_idle_s=0.2, keepalive_poll_s=0.05,
                        message_timeout=30.0)
    hang = threading.Event()

    def _hang_post(*a, **k):
        hang.wait(30.0)  # simulates a POST that never returns (hung agent)
        return {}

    monkeypatch.setattr(b, "_http_json", _hang_post)
    sse = types.SimpleNamespace(state=b._new_sse_log_state())
    sse.state["last_event_ts"] = time.time() - 100  # stale → idle trip
    stopped: list = []
    monkeypatch.setattr(b, "_stop_serve", lambda proc: stopped.append(proc))

    try:
        with pytest.raises(_KeepaliveAbort) as ei:
            b._post_message_watched("http://x", "s1", {}, sse, "PROC", "ag", "")
        assert "no SSE activity" in str(ei.value)
        assert stopped == ["PROC"]  # serve killed to break the connection
    finally:
        hang.set()  # release the hung worker so the test can exit


def test_post_message_watched_aborts_on_hard_timeout(monkeypatch):
    """P-BC3: if SSE stays active but the hard wall-clock cap (message_timeout)
    is exceeded, the watchdog trips the backstop — covers SSE-daemon-death /
    no-SSE-at-all."""
    import threading
    import types

    b = OpenCodeBackend(keepalive_idle_s=100.0, keepalive_poll_s=0.05,
                        message_timeout=0.2)
    hang = threading.Event()
    monkeypatch.setattr(b, "_http_json",
                        lambda *a, **k: hang.wait(30.0) or {})
    sse = types.SimpleNamespace(state=b._new_sse_log_state())  # fresh → no idle
    stopped: list = []
    monkeypatch.setattr(b, "_stop_serve", lambda proc: stopped.append(proc))

    try:
        with pytest.raises(_KeepaliveAbort) as ei:
            b._post_message_watched("http://x", "s1", {}, sse, "PROC", "ag", "")
        assert "hard cap" in str(ei.value)
        assert stopped == ["PROC"]
    finally:
        hang.set()


# —————————————————————————————————————————————————————————————————————————
# P114: silent failure 检测（opencode 吞网关错误 → 0 chars 无 error）
# —————————————————————————————————————————————————————————————————————————
from types import SimpleNamespace


class TestSilentFailureDetection:
    """P114: gateway 200 但 agent 0 文本产出 → silent 卡死。

    ``_maybe_warn_silent_failure`` 仅留可诊断信号（不改 crashed/status，
    保留重试行为——用户意愿）。直接测 staticmethod，无需 transport stub。
    """

    def test_warns_on_gateway_ok_but_empty_response(self, capsys):
        """err=None + full_response 空 → 打 silent 诊断（含 curl 网关提示）。"""
        consumer = SimpleNamespace(full_response="", stalled_turns=1, turn_count=1)
        OpenCodeBackend._maybe_warn_silent_failure(
            "requirement-analyst", None, consumer, {}, None)
        err = capsys.readouterr().err
        assert "silent failure" in err
        assert "requirement-analyst" in err
        assert "curl 网关" in err
        assert "model 不可用" in err

    def test_skips_when_explicit_error_present(self, capsys):
        """有显式 err → 走正常 crash 路径，非 silent（不重复报）。"""
        consumer = SimpleNamespace(full_response="", stalled_turns=1, turn_count=1)
        OpenCodeBackend._maybe_warn_silent_failure(
            "a", "500 Internal Server Error", consumer, {}, None)
        assert "silent failure" not in capsys.readouterr().err

    def test_skips_when_text_produced(self, capsys):
        """有文本产出 → 非 silent（正常完成）。"""
        consumer = SimpleNamespace(full_response="real output here",
                                   stalled_turns=0, turn_count=1)
        OpenCodeBackend._maybe_warn_silent_failure("a", None, consumer, {}, None)
        assert "silent failure" not in capsys.readouterr().err

    def test_skips_when_none_consumer(self, capsys):
        """consumer=None（crash salvage 路径）→ 不报 silent（无 IR 可判）。"""
        OpenCodeBackend._maybe_warn_silent_failure("a", None, None, {}, None)
        assert "silent failure" not in capsys.readouterr().err

    def test_warns_readonly_spin_with_zero_writes(self, tmp_path, capsys):
        """F9: 有 tool_use progress 但零写盘 → read-only 空转（思考泥潭）报警。

        m1 原豁免把"读了很久却没动手写"当合法 read-only 放掉；F9 用 transcript
        写盘证据重判（§1.10：判据用业务事实"有无写盘"，不用 turn_count 代理）——
        零写盘 = 思考泥潭，最该干预，报警。
        """
        tp = tmp_path / "t.jsonl"
        tp.write_text(json.dumps({"blocks": [{
            "kind": "tool_use", "tool_name": "read",
            "tool_input": {"input": {"filePath": "/x/a.cpp"}}}]}) + "\n")
        consumer = SimpleNamespace(full_response="", stalled_turns=0, turn_count=2)
        OpenCodeBackend._maybe_warn_silent_failure(
            "a", None, consumer, {}, None, transcript_path=str(tp))
        err = capsys.readouterr().err
        assert "read-only 空转" in err
        assert "零 Write/Edit" in err

    def test_skips_readonly_when_transcript_has_writes(self, tmp_path, capsys):
        """F9: 有 tool_use 且 transcript 有写盘尝试（含错位孤儿）→ 不在此层报
        警（归孤儿/空跑体系处理，此层只管"读了不写"）。"""
        tp = tmp_path / "t.jsonl"
        tp.write_text(json.dumps({"blocks": [{
            "kind": "tool_use", "tool_name": "write",
            "tool_input": {"input": {"filePath": "/x/orphan/kernel.cpp"}}}]}) + "\n")
        consumer = SimpleNamespace(full_response="", stalled_turns=0, turn_count=2)
        OpenCodeBackend._maybe_warn_silent_failure(
            "a", None, consumer, {}, None, transcript_path=str(tp))
        assert "read-only 空转" not in capsys.readouterr().err

    def test_warns_when_no_assistant_turn(self, capsys):
        """m1：典型 silent（gateway 吞错 → consumer 无 assistant 记录，turn_count=0）→ 报。

        turn_count==0 = opencode 返回了空 stream，consumer 没消费到任何 assistant
        turn —— 真 silent，报警。
        """
        consumer = SimpleNamespace(full_response="", stalled_turns=0, turn_count=0)
        OpenCodeBackend._maybe_warn_silent_failure("a", None, consumer, {}, None)
        assert "silent failure" in capsys.readouterr().err

    def test_warns_with_serve_log_tail(self, capsys, tmp_path):
        """proc 有 serve_log_path → 诊断附 serve log 末 n 行。"""
        log = tmp_path / ".opencode-serve-9999.log"
        log.write_text("line-a\nline-b\nlistening\n", encoding="utf-8")
        proc = SimpleNamespace(serve_log_path=str(log))
        consumer = SimpleNamespace(full_response="", stalled_turns=1, turn_count=1)
        OpenCodeBackend._maybe_warn_silent_failure(
            "design-generator", None, consumer, {}, proc)
        err = capsys.readouterr().err
        assert "silent failure" in err
        assert "serve log tail" in err
        assert "listening" in err

    def test_tail_serve_log_returns_last_n_lines(self, tmp_path):
        log = tmp_path / "serve.log"
        log.write_text("l1\nl2\nl3\n", encoding="utf-8")
        proc = SimpleNamespace(serve_log_path=str(log))
        assert OpenCodeBackend._tail_serve_log(proc, n=2) == "l2\nl3"

    def test_tail_serve_log_handles_missing_proc(self):
        assert OpenCodeBackend._tail_serve_log(None) == ""

    def test_tail_serve_log_handles_no_path_attr(self):
        # proc 无 serve_log_path（未走 _start_serve 设置）→ 空串，不崩。
        assert OpenCodeBackend._tail_serve_log(SimpleNamespace()) == ""

    def test_tail_serve_log_handles_unreadable_file(self, tmp_path):
        # 文件不存在 → 空串，不抛（best-effort）。
        proc = SimpleNamespace(serve_log_path=str(tmp_path / "nope.log"))
        assert OpenCodeBackend._tail_serve_log(proc) == ""


# —————————————————————————————————————————————————————————————————————————
# P114 集成：spawn 调用点守护（_FakeServe 驱动，验证 spawn:707 真的触发 silent 检测）
# —————————————————————————————————————————————————————————————————————————

def test_spawn_invokes_silent_failure_check(tmp_path):
    """P114 集成：spawn 必调 _maybe_warn_silent_failure（调用点守护）。

    守护 spawn:707 的调用点不被删——silent **判据**由 TestSilentFailureDetection
    （9 staticmethod case）覆盖；此处只验证『spawn 流程确实调了 silent 检测』。
    不依赖 _FakeServe 的 silent 场景构造（其 `parts or [default]` fallback +
    _session_transcript_records 的 history fallback 使空响应难稳定构造）。
    """
    cwd = tmp_path / "op"
    cwd.mkdir()
    b = _FakeServe(decision_workspace=tmp_path / "ws",
                   project_config_path=_write_project_cfg(tmp_path))
    with mock.patch.object(OpenCodeBackend, "_maybe_warn_silent_failure") as m:
        b.spawn("a", "go", {}, working_dir=cwd, primary_skill="ascendc-op-dev-coding")
    m.assert_called_once()



# ———————— 退化 spawn 设计（docs/plan/turn-stall-resume-escalation/）————————
# resume 连续失败计数 → 退化 spawn（Phase 1 原地 resume / Phase 2 计数退化）。
# 设计意图：turn-stall → 先原地 resume（续同一 session）→ 数次不成功 → 退化 spawn（fresh）。

def test_spawn_degrades_to_fresh_after_n_resume_fails(tmp_path):
    """退化 spawn（Phase 2）: sidecar resume_fails >= resume_attempts → 退化 spawn（新
    /session + 全量 prompt + skill steer），清 sidecar、新 sidecar 写 resume_fails=0。"""
    cwd = tmp_path / "op"
    cwd.mkdir()
    ws = tmp_path / "ws"
    captured = {}

    class _Probe(_FakeServe):
        def _http_json(self, method, url, body=None, timeout=30.0):
            if (url.endswith("/message") and method == "POST"
                    and "first_body" not in captured):
                captured["first_body"] = body
                captured["sidecar_at_message"] = self._session_sidecar_path(
                    "lingxi-dsl", "A3", "codegen").read_text()
            return super()._http_json(method, url, body, timeout)

    b = _Probe(decision_workspace=ws, session_id="S-FRESH",
               project_config_path=_write_project_cfg(tmp_path))
    sc = b._session_sidecar_path("lingxi-dsl", "A3", "codegen")
    sc.parent.mkdir(parents=True, exist_ok=True)
    sc.write_text(json.dumps({"agent_name": "lingxi-dsl", "session_id": "S-DEAD",
                              "stage_name": "codegen", "resume_fails": 3}))

    res = b.spawn("lingxi-dsl", "build me an op", {},
                  working_dir=cwd, stage_name="codegen", branch_label="A3",
                  primary_skill="ascendc-op-dev-coding")

    from ascendc_devkit.capabilities.agent.opencode_backend import _RESUME_PROMPT
    # 退化：消息是全量 stage prompt（非 "继续"），skill steer 重新注入
    assert captured["first_body"]["parts"][0]["text"] == "build me an op"
    assert captured["first_body"]["parts"][0]["text"] != _RESUME_PROMPT
    assert "system" in captured["first_body"], "fresh 必须重新注入 skill steer"
    # 消息 POST 到新 session S-FRESH，不碰死 session S-DEAD
    assert ("POST", "http://127.0.0.1:45999/session/S-FRESH/message") in b.calls
    assert not any("S-DEAD" in u for _, u in b.calls)
    # 新 sidecar 写 resume_fails=0（新 session 全新预算）
    assert json.loads(captured["sidecar_at_message"])["resume_fails"] == 0
    assert res.status == "ok"


def test_spawn_resume_preserves_counter_below_threshold(tmp_path):
    """原地 resume（Phase 1）: resume_fails < resume_attempts → 照常 resume（续同一 session、
    无 fresh /session），sidecar 续写保留计数（不清零）。"""
    cwd = tmp_path / "op"
    cwd.mkdir()
    ws = tmp_path / "ws"
    captured = {}

    class _Probe(_FakeServe):
        def _http_json(self, method, url, body=None, timeout=30.0):
            if (url.endswith("/message") and method == "POST"
                    and "sidecar_at_message" not in captured):
                captured["sidecar_at_message"] = self._session_sidecar_path(
                    "lingxi-dsl", "A3", "codegen").read_text()
            return super()._http_json(method, url, body, timeout)

    b = _Probe(decision_workspace=ws, session_id="S-DEAD",
               project_config_path=_write_project_cfg(tmp_path))
    sc = b._session_sidecar_path("lingxi-dsl", "A3", "codegen")
    sc.parent.mkdir(parents=True, exist_ok=True)
    sc.write_text(json.dumps({"agent_name": "lingxi-dsl", "session_id": "S-DEAD",
                              "stage_name": "codegen", "resume_fails": 1}))

    res = b.spawn("lingxi-dsl", "build me an op", {},
                  working_dir=cwd, stage_name="codegen", branch_label="A3",
                  primary_skill="ascendc-op-dev-coding")

    from ascendc_devkit.capabilities.agent.opencode_backend import _RESUME_PROMPT
    # resume：消息 POST 到同一 session S-DEAD（无 fresh /session）
    assert ("POST", "http://127.0.0.1:45999/session/S-DEAD/message") in b.calls
    assert not any("/session/S-FRESH" in u for _, u in b.calls)
    # sidecar 续写保留计数 1（不清零，继续累积失败次数）
    assert json.loads(captured["sidecar_at_message"])["resume_fails"] == 1
    assert res.status == "ok"


def test_resume_stall_abort_bumps_sidecar(tmp_path):
    """resume 会话被 stall-kill（aborted）→ sidecar
    resume_fails +1（Phase 1 失败计数；下轮读到达阈即退化 spawn）。"""
    cwd = tmp_path / "op"
    cwd.mkdir()
    ws = tmp_path / "ws"
    from ascendc_devkit.capabilities.agent.opencode_backend import _KeepaliveAbort

    class _KillResume(_FakeServe):
        def _post_message_watched(self, *a, **k):
            raise _KeepaliveAbort("no new turn for 600s > turn_stall 600s")

    b = _KillResume(decision_workspace=ws, session_id="S-DEAD",
                    project_config_path=_write_project_cfg(tmp_path))
    sc = b._session_sidecar_path("lingxi-dsl", "A3", "codegen")
    sc.parent.mkdir(parents=True, exist_ok=True)
    sc.write_text(json.dumps({"agent_name": "lingxi-dsl", "session_id": "S-DEAD",
                              "stage_name": "codegen", "resume_fails": 1}))

    res = b.spawn("lingxi-dsl", "build me an op", {},
                  working_dir=cwd, stage_name="codegen", branch_label="A3")

    assert res.aborted == "hard_timeout"
    data = json.loads(sc.read_text())
    assert data["resume_fails"] == 2, "resume-stall abort 必须 bump 连续失败计数"
    assert data["session_id"] == "S-DEAD"


def test_fresh_stall_abort_does_not_bump(tmp_path):
    """fresh 首跑被 stall-kill → 不 bump（下轮先 resume——turn-stall 先
    原地 resume，不是首跑即计数）。"""
    cwd = tmp_path / "op"
    cwd.mkdir()
    ws = tmp_path / "ws"
    from ascendc_devkit.capabilities.agent.opencode_backend import _KeepaliveAbort

    class _KillFresh(_FakeServe):
        def _post_message_watched(self, *a, **k):
            raise _KeepaliveAbort("no new turn for 600s > turn_stall 600s")

    b = _KillFresh(decision_workspace=ws, session_id="S-FRESH",
                   project_config_path=_write_project_cfg(tmp_path))

    res = b.spawn("lingxi-dsl", "build me an op", {},
                  working_dir=cwd, stage_name="codegen", branch_label="A3")

    assert res.aborted == "hard_timeout"
    sc = b._session_sidecar_path("lingxi-dsl", "A3", "codegen")
    data = json.loads(sc.read_text())
    assert data["resume_fails"] == 0, "fresh 首跑 abort 不 bump（下轮先 resume）"
    assert data["session_id"] == "S-FRESH"


def test_full_resume_degrade_converge_sequence(tmp_path):
    """完整收敛序列（模拟 runner P131c 循环连续 spawn）：fresh-stall → resume×3
    （各 bump）→ 第 5 发读计数达阈 → 退化 fresh → 成功。守护 sidecar 计数 0→1→2→3
    推进 + 首跑/退化用全量 prompt、resume 用 "继续"。"""
    cwd = tmp_path / "op"
    cwd.mkdir()
    ws = tmp_path / "ws"
    from ascendc_devkit.capabilities.agent.opencode_backend import (
        _KeepaliveAbort, _RESUME_PROMPT)
    full_prompt = "build me an op"

    class _Seq(_FakeServe):
        def __init__(self, kill_count, **kw):
            super().__init__(**kw)
            self._kill_remaining = kill_count
            self.bodies = []

        def _post_message_watched(self, *a, **k):
            # 入口采 body（第 3 位置参）——abort 与成功都经过这里，_http_json 只被成功发走到。
            self.bodies.append(a[2])
            if self._kill_remaining > 0:
                self._kill_remaining -= 1
                raise _KeepaliveAbort("no new turn for 600s > turn_stall 600s")
            return super()._post_message_watched(*a, **k)

    b = _Seq(kill_count=4, decision_workspace=ws,
             project_config_path=_write_project_cfg(tmp_path))
    sc = b._session_sidecar_path("lingxi-dsl", "A3", "codegen")
    results = []
    for i in range(5):
        results.append(b.spawn("lingxi-dsl", full_prompt, {},
                               working_dir=cwd, stage_name="codegen",
                               branch_label="A3"))
        if i < 4:
            # fresh 首跑不计数(0)；resume 各 +1(1,2,3) —— 每发 abort 后落盘可读
            data = json.loads(sc.read_text())
            assert data["resume_fails"] == i, f"spawn {i + 1} 后计数应为 {i}"

    assert all(r.aborted == "hard_timeout" for r in results[:4])
    assert results[4].status == "ok", \
        "第 5 发退化 fresh 应成功完成"
    # body 序列：首跑 fresh(全量) → resume×3("继续") → 退化 fresh(全量)
    assert len(b.bodies) == 5
    assert b.bodies[0]["parts"][0]["text"] == full_prompt
    assert all(x["parts"][0]["text"] == _RESUME_PROMPT for x in b.bodies[1:4])
    assert b.bodies[4]["parts"][0]["text"] == full_prompt
    assert not sc.exists(), "退化 fresh 成功 → clean finish 清 sidecar"


def test_session_gone_degrade_resets_resume_fails(tmp_path):
    """within-spawn session-gone(404) 降级 → 新 sidecar resume_fails=0（新 session 全新预算，
    不继承旧会话的失败计数）。"""
    cwd = tmp_path / "op"
    cwd.mkdir()
    ws = tmp_path / "ws"
    captured: dict = {}

    class _Gone(_FakeServe):
        def __init__(self, **kw):
            super().__init__(**kw)
            self._posts = 0

        def _http_json(self, method, url, body=None, timeout=30.0):
            if url.endswith("/message") and method == "POST":
                self._posts += 1
                if self._posts == 1:
                    raise _http_404_session_gone("S-DEAD")
                # 第 2 发 = 降级后的 fresh 消息：此刻 sidecar 已被降级路径重写
                captured["sidecar_at_fresh"] = self._session_sidecar_path(
                    "lingxi-dsl", "A3", "codegen").read_text()
            if url.endswith("/session") and method == "POST":
                return {"id": "ses-FRESH-1"}
            return super()._http_json(method, url, body, timeout)

    b = _Gone(decision_workspace=ws,
              project_config_path=_write_project_cfg(tmp_path))
    sc = b._session_sidecar_path("lingxi-dsl", "A3", "codegen")
    sc.parent.mkdir(parents=True, exist_ok=True)
    sc.write_text(json.dumps({"agent_name": "lingxi-dsl", "session_id": "S-DEAD",
                              "stage_name": "codegen", "resume_fails": 2}))

    res = b.spawn("lingxi-dsl", "build me an op", {},
                  working_dir=cwd, stage_name="codegen", branch_label="A3",
                  primary_skill="ascendc-op-dev-coding")

    assert res.status == "ok"
    data = json.loads(captured["sidecar_at_fresh"])
    assert data["session_id"] == "ses-FRESH-1"
    assert data["resume_fails"] == 0, "session-gone 降级的新 session 必须全新预算"


# ---------------------------------------------------------------------------
# F4 (20260821)：无效 resume 计数（opencode 对称）——resume 后仍 silent-cut
# → resume_fails +1；fresh 首跑 cut 不计数。
# ---------------------------------------------------------------------------

def test_opencode_resume_then_cut_bumps_resume_fails(tmp_path):
    """F4（opencode）：sidecar resume 的会话再次 cut（reasoning-only 终止）→
    sidecar resume_fails +1。"""
    ws = tmp_path / "ws"
    (ws / "agents").mkdir(parents=True)
    sc = ws / "agents" / "coder.session.json"
    sc.write_text(json.dumps({"agent_name": "coder", "session_id": "S-MIRE",
                              "resume_fails": 0}))

    b = _FakeServe(decision_workspace=ws,
                   message_parts=[{"type": "reasoning", "text": "(thinking...)"}],
                   session_id="S-MIRE",
                   project_config_path=_write_project_cfg(tmp_path))
    res = b.spawn("coder", "code it", {}, working_dir=tmp_path / "op",
                  primary_skill="ascendc-op-dev-coding")

    assert res.cut is True, "reasoning-only 终止 = silent-cut"
    data = json.loads(sc.read_text())
    assert data["resume_fails"] == 1, "resume 后仍 cut 必须 bump"


def test_opencode_fresh_cut_does_not_bump_resume_fails(tmp_path):
    """F4（opencode）：fresh 首跑 cut → sidecar 保留但 resume_fails=0。"""
    ws = tmp_path / "ws"
    (ws / "agents").mkdir(parents=True)

    b = _FakeServe(decision_workspace=ws,
                   message_parts=[{"type": "reasoning", "text": "(thinking...)"}],
                   session_id="S-FRESH",
                   project_config_path=_write_project_cfg(tmp_path))
    res = b.spawn("coder", "code it", {}, working_dir=tmp_path / "op",
                  primary_skill="ascendc-op-dev-coding")

    assert res.cut is True
    sc = ws / "agents" / "coder.session.json"
    assert sc.exists(), "fresh cut 保留 sidecar（下次 resume 句柄）"
    assert json.loads(sc.read_text())["resume_fails"] == 0, "fresh cut 不 bump"


# ---------------------------------------------------------------------------
# P6（step-110）硬切分类：SSE reasoning 打点（opencode 侧唯一真实时刻源——
# transcript 是 POST 后回读、时刻失真）+ 判切点分类 + sidecar 键 + 路由三态
# + 硬切不 bump（唯一控制流变化，与 sdk 对称）。
# ---------------------------------------------------------------------------

def test_sse_reasoning_delta_stamps_classification_evidence():
    """reasoning 增量：按步累计体量 + 末次到达时刻打点（gap 判据时间源）。

    真实协议形态（opencode-cut-classification/01-problems.md F3，binary 实证）：
    part-start 标记（message.part.updated 携带 part.type）先行，delta 的 field 恒
    "text"（指 part 属性名，text/reasoning part 同名）——分型只能按 partID 关联
    part 类型，不能按 field。
    """
    b = OpenCodeBackend()
    state = b._new_sse_log_state()
    assert state["step_reasoning_chars"] == 0
    assert state["last_reasoning_delta_ts"] is None
    b._handle_sse_event({"type": "message.part.updated",
                         "properties": {"part": {"id": "p-r", "type": "reasoning",
                                                 "text": ""}}},
                        state, **_sse_ctx())
    for chunk in ("deep ", "reasoning"):
        b._handle_sse_event({"type": "message.part.delta",
                             "properties": {"partID": "p-r", "field": "text",
                                            "delta": chunk}},
                            state, **_sse_ctx())
    assert state["step_reasoning_chars"] == 14
    assert state["last_reasoning_delta_ts"] is not None
    # text part 同形态 delta 不打 thinking 证据（分型按 part 类型，非 field）
    _ts_before = state["last_reasoning_delta_ts"]
    b._handle_sse_event({"type": "message.part.updated",
                         "properties": {"part": {"id": "p-t", "type": "text",
                                                 "text": ""}}},
                        state, **_sse_ctx())
    b._handle_sse_event({"type": "message.part.delta",
                         "properties": {"partID": "p-t", "field": "text",
                                        "delta": "answer"}},
                        state, **_sse_ctx())
    assert state["step_reasoning_chars"] == 14
    assert state["last_reasoning_delta_ts"] == _ts_before


def test_sse_step_start_resets_step_reasoning_chars():
    """输出墙按步计（写文件/调工具=切步=重置单步预算）——step-start 重置按步
    计数；换轮（message.updated role=user）同样重置。part 类型表随同清空：跨步/
    跨轮的同名 partID 未经标记不累计。"""
    b = OpenCodeBackend()
    state = b._new_sse_log_state()
    b._handle_sse_event({"type": "message.part.updated",
                         "properties": {"part": {"id": "p1", "type": "reasoning",
                                                 "text": ""}}},
                        state, **_sse_ctx())
    b._handle_sse_event({"type": "message.part.delta",
                         "properties": {"partID": "p1", "field": "text",
                                        "delta": "x" * 50}},
                        state, **_sse_ctx())
    b._handle_sse_event({"type": "message.part.updated",
                         "properties": {"part": {"type": "step-start"}}},
                        state, **_sse_ctx())
    assert state["step_reasoning_chars"] == 0
    # 时刻不重置（跨步证据持续——判据看末次思考到达）
    assert state["last_reasoning_delta_ts"] is not None
    # 新步的同名 partID（表已清）未经标记 → 不累计
    b._handle_sse_event({"type": "message.part.delta",
                         "properties": {"partID": "p1", "field": "text",
                                        "delta": "y" * 7}},
                        state, **_sse_ctx())
    assert state["step_reasoning_chars"] == 0
    # 新步经标记 → 正常累计
    b._handle_sse_event({"type": "message.part.updated",
                         "properties": {"part": {"id": "p2", "type": "reasoning",
                                                 "text": ""}}},
                        state, **_sse_ctx())
    b._handle_sse_event({"type": "message.part.delta",
                         "properties": {"partID": "p2", "field": "text",
                                        "delta": "y" * 7}},
                        state, **_sse_ctx())
    assert state["step_reasoning_chars"] == 7
    b._handle_sse_event({"type": "message.updated",
                         "properties": {"info": {"role": "user"}}},
                        state, **_sse_ctx())
    assert state["step_reasoning_chars"] == 0
    # 换轮清表后同名 partID 未经标记 → 不累计
    b._handle_sse_event({"type": "message.part.delta",
                         "properties": {"partID": "p2", "field": "text",
                                        "delta": "z" * 3}},
                        state, **_sse_ctx())
    assert state["step_reasoning_chars"] == 0


def test_sse_delta_without_part_marker_not_counted():
    """无 part.updated 先行标记的 delta（订阅中途启动等）不累计思考证据——
    诚实无证据，classify_cut 维持 None 语义。"""
    b = OpenCodeBackend()
    state = b._new_sse_log_state()
    b._handle_sse_event({"type": "message.part.delta",
                         "properties": {"partID": "p-unknown", "field": "text",
                                        "delta": "x" * 99}},
                        state, **_sse_ctx())
    assert state["step_reasoning_chars"] == 0
    assert state["last_reasoning_delta_ts"] is None


def test_sse_part_kinds_tracked_from_real_wire_frames():
    """协议守护（§3.9）：真实 wire 帧序列（``parse_sse_frames`` 解析）经
    ``_handle_sse_event`` 后，delta 能按 partID 关联到 part 类型。

    这是本问题（docs/plan/opencode-cut-classification/）的协议不变式守护——
    fixture 取自 opencode 真实发射形态（delta 的 ``field`` 恒 ``"text"``，
    类型只在先行 ``part.updated`` 的 ``part.type``），**不按实现假设构造**，
    防止「fixture 与实现同错、绿灯掩盖死分支」再次发生。
    """
    import json as _json

    from ascendc_devkit.capabilities.agent.opencode_sse import parse_sse_frames

    def _frame(t, props):
        return ("data: " + _json.dumps(
            {"id": "evt_x", "type": t, "properties": props}) + "\n\n")

    wire = (
        _frame("message.part.updated",
               {"sessionID": "s", "part": {"id": "p-r", "type": "reasoning",
                                           "text": ""}}) +
        _frame("message.part.delta",
               {"sessionID": "s", "partID": "p-r", "field": "text",
                "delta": "think"}) +
        _frame("message.part.updated",
               {"sessionID": "s", "part": {"id": "p-t", "type": "text",
                                           "text": ""}}) +
        _frame("message.part.delta",
               {"sessionID": "s", "partID": "p-t", "field": "text",
                "delta": "answer"})
    )
    b = OpenCodeBackend()
    state = b._new_sse_log_state()
    for ev in parse_sse_frames(wire.splitlines(keepends=True)):
        b._handle_sse_event(ev, state, **_sse_ctx())

    # reasoning part 的 delta 计入思考证据；text part 的 delta 不计
    assert state["step_reasoning_chars"] == len("think")
    assert state["last_reasoning_delta_ts"] is not None
    # 两条 delta 都计入合计字符数（呈现用）
    assert state["chars"] == len("think") + len("answer")
    # 类型表如实反映两个 part
    assert state["part_kinds"] == {"p-r": "thinking", "p-t": "text"}


def test_opencode_hard_cut_classified_from_sse_state(tmp_path):
    """判切点用 SSE 状态分类（fresh 硬切）：metrics 携带 + sidecar 分类键 +
    fresh 首跑本就不 bump。"""
    import time as _time
    ws = tmp_path / "ws"

    class _HardCutServe(_FakeServe):
        def _subscribe_sse(self, base_url, session_id, agent_name, attribution,
                           start_ms):
            import types as _types
            st = self._new_sse_log_state()
            st["step_reasoning_chars"] = 98801        # 深推理按步体量
            st["last_reasoning_delta_ts"] = _time.time()   # 流活跃至末刻
            return _types.SimpleNamespace(
                state=st, stop_and_join=lambda *a, **k: None)

    b = _HardCutServe(decision_workspace=ws,
                      message_parts=[{"type": "reasoning",
                                      "text": "(deep...)"}],
                      session_id="S-HARD",
                      project_config_path=_write_project_cfg(tmp_path))
    res = b.spawn("coder", "code it", {}, working_dir=tmp_path / "op",
                  primary_skill="ascendc-op-dev-coding")

    assert res.cut is True
    assert res.metrics["cut_hard"] is True
    facts = res.metrics["cut_facts"]
    assert facts["thinking_chars"] == 98801
    assert facts["last_delta_to_end_s"] <= 0.6
    sc = ws / "agents" / "coder.session.json"
    data = json.loads(sc.read_text())
    assert data["cut_hard"] is True
    assert data["cut_facts"]["thinking_chars"] == 98801


def test_opencode_hard_cut_on_resume_does_not_bump(tmp_path):
    """P6 唯一控制流变化（opencode 对称）：resume 后硬切 → 不 bump resume_fails
    （不走 fresh 退化——丢上下文重放同一深推理再撞墙）。"""
    import time as _time
    ws = tmp_path / "ws"
    (ws / "agents").mkdir(parents=True)
    sc = ws / "agents" / "coder.session.json"
    sc.write_text(json.dumps({"agent_name": "coder", "session_id": "S-MIRE",
                              "resume_fails": 0}))

    class _HardCutServe(_FakeServe):
        def _subscribe_sse(self, base_url, session_id, agent_name, attribution,
                           start_ms):
            import types as _types
            st = self._new_sse_log_state()
            st["step_reasoning_chars"] = 5000
            st["last_reasoning_delta_ts"] = _time.time()
            return _types.SimpleNamespace(
                state=st, stop_and_join=lambda *a, **k: None)

    b = _HardCutServe(decision_workspace=ws,
                      message_parts=[{"type": "reasoning",
                                      "text": "(deep...)"}],
                      session_id="S-MIRE",
                      project_config_path=_write_project_cfg(tmp_path))
    res = b.spawn("coder", "code it", {}, working_dir=tmp_path / "op",
                  primary_skill="ascendc-op-dev-coding")

    assert res.cut is True and res.metrics["cut_hard"] is True
    data = json.loads(sc.read_text())
    assert data["resume_fails"] == 0, "硬切不进未知中断计数"
    assert data["cut_hard"] is True


def test_opencode_cut_without_sse_evidence_is_soft_and_bumps(tmp_path):
    """SSE 无 reasoning 证据（真实场景：订阅失败/无思考流）→ 分类不成立 →
    走未知中断原路径（bump 语义不变，F4 回归）。"""
    ws = tmp_path / "ws"
    (ws / "agents").mkdir(parents=True)
    sc = ws / "agents" / "coder.session.json"
    sc.write_text(json.dumps({"agent_name": "coder", "session_id": "S-MIRE",
                              "resume_fails": 0}))

    b = _FakeServe(decision_workspace=ws,
                   message_parts=[{"type": "reasoning", "text": "(...)"}],
                   session_id="S-MIRE",
                   project_config_path=_write_project_cfg(tmp_path))
    res = b.spawn("coder", "code it", {}, working_dir=tmp_path / "op",
                  primary_skill="ascendc-op-dev-coding")

    assert res.cut is True
    assert "cut_hard" not in res.metrics, "无证据 → 不携带分类（runner 降级现文案）"
    data = json.loads(sc.read_text())
    assert data["resume_fails"] == 1, "未知中断路径照常 bump（F4 行为不变）"
    assert data["cut_hard"] is False


def test_opencode_resume_routes_hard_cut_facts_prompt(tmp_path):
    """路由三态（opencode）：sidecar cut_hard=True → resume 首条消息 = 兜底
    提示；显式 resume_prompt 恒优先；缺键 → 裸「继续」。"""
    from ascendc_devkit.capabilities.agent._shared import _HARD_CUT_RESUME_PROMPT
    from ascendc_devkit.capabilities.agent.opencode_backend import _RESUME_PROMPT
    ws = tmp_path / "ws"
    (ws / "agents").mkdir(parents=True)

    def _probe(tmp_path, sidecar_body, **spawn_kw):
        captured = {}

        class _Probe(_FakeServe):
            def _http_json(self, method, url, body=None, timeout=30.0):
                if (url.endswith("/message") and method == "POST"
                        and "first_body" not in captured):
                    captured["first_body"] = body
                return super()._http_json(method, url, body, timeout)

        (ws / "agents" / "coder-codegen.session.json").write_text(
            json.dumps(sidecar_body))
        b = _Probe(decision_workspace=ws,
                   project_config_path=_write_project_cfg(tmp_path))
        b.spawn("coder", "code it", {}, working_dir=tmp_path / "op",
                stage_name="codegen", branch_label="",
                primary_skill="ascendc-op-dev-coding", **spawn_kw)
        return captured["first_body"]["parts"][0]["text"]

    # 硬切分类 → 兜底提示（sidecar 自动 resume 路径）
    assert _probe(tmp_path, {"agent_name": "coder", "session_id": "S-HC",
                             "cut_hard": True}) == _HARD_CUT_RESUME_PROMPT
    # 缺键（旧 sidecar）→ 裸「继续」
    assert _probe(tmp_path, {"agent_name": "coder", "session_id": "S-LEGACY"}
                  ) == _RESUME_PROMPT
    # 显式 resume_prompt 恒优先
    assert _probe(tmp_path, {"agent_name": "coder", "session_id": "S-HC",
                             "cut_hard": True},
                  resume_prompt="修 CMake 注册并回验") == "修 CMake 注册并回验"


def test_opencode_resume_rewrite_consumes_classification(tmp_path):
    """stale 防护核心：resume 期的 sidecar 重写不含分类键（=消费）——本 spawn
    若 crash（不写新分类），下一次 resume 回到裸「继续」，与 crash 性质一致。"""
    ws = tmp_path / "ws"
    (ws / "agents").mkdir(parents=True)
    sc = ws / "agents" / "coder.session.json"
    sc.write_text(json.dumps({"agent_name": "coder", "session_id": "S-HC",
                              "cut_hard": True}))

    class _CrashOnMessage(_FakeServe):
        def _http_json(self, method, url, body=None, timeout=30.0):
            if url.endswith("/message") and method == "POST":
                raise RuntimeError("gateway blew up mid-spawn")
            return super()._http_json(method, url, body, timeout)

    b = _CrashOnMessage(decision_workspace=ws, session_id="S-HC",
                        project_config_path=_write_project_cfg(tmp_path))
    res = b.spawn("coder", "code it", {}, working_dir=tmp_path / "op",
                  primary_skill="ascendc-op-dev-coding")

    assert res.status in ("fatal", "partial"), \
        "message POST 崩溃 → crash 路径（保留 sidecar 句柄）"
    data = json.loads(sc.read_text())
    assert data["session_id"] == "S-HC", "crash 保留 resume 句柄"
    assert "cut_hard" not in data, "resume 期重写已消费分类（crash 不复活旧分类）"
    assert b._read_sidecar_cut_hard("coder", "", "") is False, \
        "下一次 resume 路由回到裸「继续」（crash = 未知中断）"


# ————— step-115 (P16): 阳性网关错误证据 → gateway_stream_error 速杀 ——————

import time as _time


def _write_app_log(path, entries):
    """entries: list[(iso_ts, level, message)] → opencode app-log 行。"""
    lines = []
    for ts, lvl, msg in entries:
        lines.append(
            f'timestamp={ts}Z level={lvl} run=r1 message="{msg}" '
            f'providerID=deepseek-gw session.id=ses_X')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class _FakeSSE2:
    def __init__(self, chars=0):
        self.state = {"chars": chars}


def test_gateway_evidence_helper_fresh_and_stale(tmp_path):
    from datetime import datetime, timezone
    b = OpenCodeBackend()
    log = tmp_path / "data" / "opencode" / "log" / "opencode.log"
    now = datetime.now(timezone.utc)
    fresh = (now.timestamp() - 10)
    stale = (now.timestamp() - 500)
    iso = lambda e: datetime.fromtimestamp(
        e, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "")
    _write_app_log(log, [
        (iso(stale), "ERROR", "stream error"),       # 早于静默起点：陈旧
        (iso(fresh), "ERROR", "stream error"),       # 晚于静默起点：新鲜
        (iso(fresh), "ERROR", "permission denied"),  # 非 stream error：不认
        (iso(fresh), "INFO", "stream"),              # 非ERROR：不认
    ])
    got = b._gateway_error_evidence(log, since_epoch=now.timestamp() - 60)
    # 只有 1 条新鲜 stream error（stale 那条不算 / 非标记行不算）
    assert len(got) == 1 and abs(got[0] - fresh) < 1.0
    # 静默起点晚于全部错误行 → 无新鲜证据
    assert b._gateway_error_evidence(log, since_epoch=now.timestamp() - 5) == []
    # 日志不存在 → 空表（无证据不 fail，时长界兜底）
    assert b._gateway_error_evidence(tmp_path / "nope.log", since_epoch=0) == []


def _patch_thread(monkeypatch, on_join):
    """替身 worker 线程：is_alive 恒真、join 打点回调（模拟黑洞 POST）。"""
    class _FakeThread:
        def __init__(self, *a, **k):
            pass

        def start(self):
            pass

        def is_alive(self):
            return True

        def join(self, timeout=None):
            _time.sleep(0.02)
            on_join()

    import ascendc_devkit.capabilities.agent.opencode_backend as ob
    monkeypatch.setattr(ob.threading, "Thread", _FakeThread)


def test_gateway_evidence_trip_in_watchdog(tmp_path, monkeypatch):
    """新鲜错误 + chars 静止 → 证据速杀（早于时长界）。"""
    from datetime import datetime, timezone
    logs = []
    monkeypatch.setattr(
        "ascendc_devkit.capabilities.agent.opencode_backend.Logger.error",
        lambda m, **k: logs.append(m))
    b = OpenCodeBackend(turn_stall_s=300.0, gateway_error_probe_s=0.05,
                        keepalive_poll_s=0.05, keepalive_idle_s=300.0)
    log = tmp_path / "log" / "opencode.log"
    fresh = datetime.now(timezone.utc).timestamp() - 1
    iso = datetime.fromtimestamp(
        fresh, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "")
    _write_app_log(log, [(iso, "ERROR", "stream error")])
    sse = _FakeSSE2(chars=0)

    # 错误行须晚于静默起点（循环启动）才构成「新鲜」证据——在 join 回调里
    # 落盘（模拟坏窗口：POST 挂起后网关开始返回 Gateway Time-out）。
    def _emit_error_during_silence():
        from datetime import datetime, timezone
        iso = datetime.now(timezone.utc).isoformat(
            timespec="milliseconds").replace("+00:00", "")
        with open(log, "a", encoding="utf-8") as f:
            f.write(f'timestamp={iso}Z level=ERROR run=r1 '
                    f'message="stream error" providerID=deepseek-gw\n')

    _patch_thread(monkeypatch, _emit_error_during_silence)

    import pytest
    from ascendc_devkit.capabilities.agent.opencode_backend import _KeepaliveAbort
    with pytest.raises(_KeepaliveAbort) as ei:
        b._post_message_watched(
            "http://127.0.0.1:1", "ses_X", {}, sse, None, "coder", "[s] ",
            message_timeout=0, app_log=log)
    assert ei.value.kind == "gateway_stream_error"
    assert "stream error" in str(ei.value)


def test_gateway_evidence_no_trip_when_chars_flowing(tmp_path, monkeypatch):
    """chars 在流动（活会话）→ 探针静默前提不成立，不 trip（时长界兜底）。"""
    from datetime import datetime, timezone
    b = OpenCodeBackend(turn_stall_s=300.0, gateway_error_probe_s=0.05,
                        keepalive_poll_s=0.05, keepalive_idle_s=300.0)
    log = tmp_path / "log" / "opencode.log"
    fresh = datetime.now(timezone.utc).timestamp() - 1
    iso = datetime.fromtimestamp(
        fresh, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "")
    _write_app_log(log, [(iso, "ERROR", "stream error")])
    sse = _FakeSSE2(chars=0)
    _patch_thread(monkeypatch, lambda: sse.state.__setitem__("chars", 10))

    import pytest
    from ascendc_devkit.capabilities.agent.opencode_backend import _KeepaliveAbort
    with pytest.raises(_KeepaliveAbort) as ei:  # 由硬超时收尾，非证据速杀
        b._post_message_watched(
            "http://127.0.0.1:1", "ses_X", {}, sse, None, "coder", "[s] ",
            message_timeout=0.3, app_log=log)
    assert ei.value.kind == "hard_timeout"


def test_gateway_evidence_disabled_by_zero(tmp_path, monkeypatch):
    """probe_s=0 → 证据路径禁用，只剩时长界（kind=turn_stall 兜底）。"""
    from datetime import datetime, timezone
    b = OpenCodeBackend(turn_stall_s=0.2, gateway_error_probe_s=0,
                        keepalive_poll_s=0.05, keepalive_idle_s=300.0)
    log = tmp_path / "log" / "opencode.log"
    fresh = datetime.now(timezone.utc).timestamp() - 1
    iso = datetime.fromtimestamp(
        fresh, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "")
    _write_app_log(log, [(iso, "ERROR", "stream error")])
    sse = _FakeSSE2(chars=0)
    # 时长界需要 turn_ts（静默轮判定用）；注入一个早已过期的 turn 基线
    sse.state["turn_ts"] = _time.time() - 5
    sse.state["turn"] = 1
    _patch_thread(monkeypatch, lambda: None)

    import pytest
    from ascendc_devkit.capabilities.agent.opencode_backend import _KeepaliveAbort
    with pytest.raises(_KeepaliveAbort) as ei:
        b._post_message_watched(
            "http://127.0.0.1:1", "ses_X", {}, sse, None, "coder", "[s] ",
            message_timeout=0, app_log=log)
    assert ei.value.kind == "turn_stall"  # 证据禁用 → 时长界接管


def test_gateway_evidence_single_transient_error_no_trip(tmp_path, monkeypatch):
    """step-115 收紧：单发瞬态错误（无复发）+ chars 静止 → **不**证据速杀——
    「复发 ≥2」是判据，防误杀「瞬态错误被内部重试自愈 + 首 token 迟到」
    的活会话。最终由硬超时收尾（本用例不构造时长界条件）。"""
    from datetime import datetime, timezone
    b = OpenCodeBackend(turn_stall_s=300.0, gateway_error_probe_s=0.05,
                        keepalive_poll_s=0.05, keepalive_idle_s=300.0)
    log = tmp_path / "log" / "opencode.log"
    _write_app_log(log, [])  # 预建空日志（append 不建目录）

    emitted = {"n": 0}

    def _emit_one_error_only():
        # 每次 join 只在前 2 次各写一条、此后**不再复发**（单发瞬态语义：
        # 用重复写但总量锁 1 条来对齐节流窗口——严格单发）
        if emitted["n"] >= 1:
            return
        emitted["n"] += 1
        iso = datetime.now(timezone.utc).isoformat(
            timespec="milliseconds").replace("+00:00", "")
        with open(log, "a", encoding="utf-8") as f:
            f.write(f'timestamp={iso}Z level=ERROR run=r1 '
                    f'message="stream error" providerID=deepseek-gw\n')

    sse = _FakeSSE2(chars=0)
    _patch_thread(monkeypatch, _emit_one_error_only)

    import pytest
    from ascendc_devkit.capabilities.agent.opencode_backend import _KeepaliveAbort
    with pytest.raises(_KeepaliveAbort) as ei:
        b._post_message_watched(
            "http://127.0.0.1:1", "ses_X", {}, sse, None, "coder", "[s] ",
            message_timeout=0.4, app_log=log)
    assert ei.value.kind == "hard_timeout"  # 不是 gateway_stream_error
    assert emitted["n"] == 1


def test_sse_compaction_without_sid_not_counted(monkeypatch):
    """R8（review 整改）：session.* 是总线级广播事件——载荷无 sid 即无法归属
    本会话，不计入冲刷计数（防串会话污染），留事实行线索。"""
    logs = []
    monkeypatch.setattr(
        "ascendc_devkit.capabilities.agent.opencode_backend.Logger.action",
        lambda t, d: logs.append((t, d)))
    b = OpenCodeBackend()
    state = b._new_sse_log_state()
    b._handle_sse_event({"type": "session.compacted", "properties": {}},
                        state, **_sse_ctx(session_id="ses_1"))
    assert b._compaction_metrics(_FakeSSE(state), "coder", "[s] ") == {
        "compactions": 0}
    assert any(t == "agent_compact_unattributed" for t, _ in logs)
