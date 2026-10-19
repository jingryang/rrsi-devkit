"""UT for the resolve_ambiguity stdio MCP server (D4).

Drives ``engine_mcp_stdio.handle_message`` — the pure JSON-RPC dispatch — with
plain dicts, no real subprocess. Guards:
  ① initialize handshake (protocol echo + serverInfo + tools capability)
  ② tools/list advertises the single shared tool contract (name/desc/schema
     come from mcp_tools — proves single-source, no drift)
  ③ tools/call routes to the shared handler and returns MCP tool-result shape
  ④ default on_decision (non-interactive) auto-selects options[0]
  ⑤ abort on_decision persists pending_decision.json + returns the pending marker
  ⑥ notifications get no response; unknown method → -32601; unknown tool → isError
  ⑦ env → handler wiring (build_handler_from_env reads the ASCENDC_* vars)
"""

from __future__ import annotations

import asyncio
import json
import pytest
from pathlib import Path

from ascendc_devkit.capabilities import engine_mcp_stdio as mod
from ascendc_devkit.capabilities.mcp_tools import (
    create_resolve_ambiguity_handler,
    RESOLVE_AMBIGUITY_TOOL_NAME,
    RESOLVE_AMBIGUITY_DESCRIPTION,
    RESOLVE_AMBIGUITY_INPUT_SCHEMA,
    _DECISION_PENDING_MARKER,
)


def _run(coro):
    return asyncio.run(coro)


def _default_handler(workspace_dir=None, on_decision="default"):
    return create_resolve_ambiguity_handler(
        interactive=False, on_decision=on_decision, workspace_dir=workspace_dir)


def test_initialize_echoes_protocol_and_advertises_tools():
    h = _default_handler()
    resp = _run(mod.handle_message(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18"}}, h))
    assert resp["id"] == 1
    r = resp["result"]
    assert r["protocolVersion"] == "2025-06-18"  # echoed
    assert "tools" in r["capabilities"]
    assert r["serverInfo"]["name"] == "engine"


def test_initialize_without_version_advertises_default():
    h = _default_handler()
    resp = _run(mod.handle_message(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, h))
    assert resp["result"]["protocolVersion"] == mod._DEFAULT_PROTOCOL_VERSION


def test_tools_list_is_single_source_contract():
    h = _default_handler()
    resp = _run(mod.handle_message(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, h))
    tools = resp["result"]["tools"]
    assert len(tools) == 1
    t = tools[0]
    # Contract comes verbatim from mcp_tools (single source, §2.5).
    assert t["name"] == RESOLVE_AMBIGUITY_TOOL_NAME
    assert t["description"] == RESOLVE_AMBIGUITY_DESCRIPTION
    assert t["inputSchema"] == RESOLVE_AMBIGUITY_INPUT_SCHEMA
    assert t["inputSchema"]["required"] == ["question", "options"]


def test_tools_call_default_selects_first_option():
    h = _default_handler(on_decision="default")
    resp = _run(mod.handle_message(
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": RESOLVE_AMBIGUITY_TOOL_NAME,
                    "arguments": {"question": "pick", "options": ["A", "B"]}}},
        h))
    content = resp["result"]["content"]
    assert content[0]["text"] == "A"  # options[0]
    assert not resp["result"].get("isError")


def test_tools_call_abort_persists_pending_and_returns_marker(tmp_path):
    ws = tmp_path / "run"
    ws.mkdir()
    h = _default_handler(workspace_dir=str(ws), on_decision="abort")
    resp = _run(mod.handle_message(
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": RESOLVE_AMBIGUITY_TOOL_NAME,
                    "arguments": {"question": "tiling?", "options": ["X", "Y"]}}},
        h))
    assert resp["result"]["content"][0]["text"] == _DECISION_PENDING_MARKER
    pending = json.loads((ws / "pending_decision.json").read_text())
    assert pending["question"] == "tiling?"
    assert pending["options"] == ["X", "Y"]


def test_tools_call_resume_reads_decision_response(tmp_path):
    ws = tmp_path / "run"
    ws.mkdir()
    # A prior `respond` wrote the operator's numeric choice.
    (ws / "decision_response.json").write_text(json.dumps({"choice": 2}))
    h = _default_handler(workspace_dir=str(ws), on_decision="abort")
    resp = _run(mod.handle_message(
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
         "params": {"name": RESOLVE_AMBIGUITY_TOOL_NAME,
                    "arguments": {"question": "q", "options": ["A", "B"]}}},
        h))
    # choice=2 → options[1]; response file consumed.
    assert resp["result"]["content"][0]["text"] == "B"
    assert not (ws / "decision_response.json").exists()


def test_initialized_notification_has_no_response():
    h = _default_handler()
    resp = _run(mod.handle_message(
        {"jsonrpc": "2.0", "method": "notifications/initialized"}, h))
    assert resp is None


def test_unknown_method_returns_method_not_found():
    h = _default_handler()
    resp = _run(mod.handle_message(
        {"jsonrpc": "2.0", "id": 9, "method": "does/not/exist"}, h))
    assert resp["error"]["code"] == -32601


def test_unknown_tool_returns_iserror():
    h = _default_handler()
    resp = _run(mod.handle_message(
        {"jsonrpc": "2.0", "id": 10, "method": "tools/call",
         "params": {"name": "nope", "arguments": {}}}, h))
    assert resp["result"]["isError"] is True


def test_ping_returns_empty_result():
    h = _default_handler()
    resp = _run(mod.handle_message({"jsonrpc": "2.0", "id": 11, "method": "ping"}, h))
    assert resp["result"] == {}


def test_build_handler_from_env(monkeypatch, tmp_path):
    ws = tmp_path / "envws"
    ws.mkdir()
    monkeypatch.setenv("ASCENDC_INTERACTIVE", "0")
    monkeypatch.setenv("ASCENDC_ON_DECISION", "abort")
    monkeypatch.setenv("ASCENDC_DECISION_WORKSPACE", str(ws))
    monkeypatch.delenv("ASCENDC_WEBHOOK_URL", raising=False)
    handler = mod.build_handler_from_env()
    # abort mode from env → writes pending + returns marker.
    resp = _run(mod.handle_message(
        {"jsonrpc": "2.0", "id": 12, "method": "tools/call",
         "params": {"name": RESOLVE_AMBIGUITY_TOOL_NAME,
                    "arguments": {"question": "q", "options": ["A"]}}},
        handler))
    assert resp["result"]["content"][0]["text"] == _DECISION_PENDING_MARKER
    assert (ws / "pending_decision.json").exists()


def test_bool_env_parsing(monkeypatch):
    for truthy in ("1", "true", "YES", "on"):
        monkeypatch.setenv("X_FLAG", truthy)
        assert mod._bool_env("X_FLAG") is True
    for falsy in ("0", "false", "no", ""):
        monkeypatch.setenv("X_FLAG", falsy)
        assert mod._bool_env("X_FLAG") is False
    monkeypatch.delenv("X_FLAG", raising=False)
    assert mod._bool_env("X_FLAG", default=True) is True


def test_serve_handshake_timeout_exits_nonzero(capsys):
    # A (P115): if the client never sends the first line (opencode stalled on
    # the shared SQLite DB lock before opening the MCP session), _serve must
    # exit non-zero + log to stderr within handshake_timeout — NOT block
    # silently until message_timeout (§1.2 可诊断).
    import io
    import time

    class _BlockingStdin:
        def readline(self):
            time.sleep(10)  # never returns within the test's tiny timeout
            return ""

    with pytest.raises(SystemExit) as exc:
        _run(mod._serve(_BlockingStdin(), io.StringIO(), _default_handler(),
                        handshake_timeout=0.1))
    assert exc.value.code == 1
    assert "handshake timeout" in capsys.readouterr().err


def test_serve_handshake_succeeds_then_dispatches_subsequent_lines():
    # A (P115): normal flow — initialize arrives within the deadline, then the
    # loop keeps processing subsequent requests (tools/list). The handshake
    # deadline must NOT bound subsequent reads (a tools/call may legitimately
    # block on a decision).
    import io

    class _Stdin:
        def __init__(self, lines):
            self._lines = list(lines)

        def readline(self):
            return self._lines.pop(0) if self._lines else ""

    stdin = _Stdin([
        '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n',
        '{"jsonrpc":"2.0","id":2,"method":"tools/list"}\n',
    ])
    out = io.StringIO()
    _run(mod._serve(stdin, out, _default_handler(), handshake_timeout=5))
    result = out.getvalue()
    assert '"id": 1' in result and "serverInfo" in result   # initialize replied
    assert '"id": 2' in result and "tools" in result         # tools/list replied
