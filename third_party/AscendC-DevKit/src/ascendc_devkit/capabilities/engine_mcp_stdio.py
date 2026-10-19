"""L5 Capabilities — resolve_ambiguity as a stdio MCP server (D4).

The claude backend exposes ``resolve_ambiguity`` in-process
(``mcp_tools.build_engine_mcp_server`` → ``create_sdk_mcp_server``). The
opencode backend runs the model in a separate ``opencode serve`` process that
cannot import our Python handler in-process; opencode's native way to reach an
external tool is a ``type: "local"`` MCP entry that spawns a subprocess and
speaks JSON-RPC 2.0 over stdio. This module IS that subprocess:

    python -m ascendc_devkit.capabilities.engine_mcp_stdio

It wraps the SAME SDK-agnostic ``create_resolve_ambiguity_handler`` the claude
path uses (single source, §2.5) and exposes the SAME tool name / description /
input schema (imported constants from ``mcp_tools``). Per-spawn parameters —
which are constructor args on the claude path — arrive here via the process
environment (the only channel opencode's ``mcp.<name>.environment`` gives us):

    ASCENDC_DECISION_WORKSPACE   → workspace_dir  (pending/response decision I/O)
    ASCENDC_ON_DECISION          → on_decision    (default | abort | notify-webhook)
    ASCENDC_WEBHOOK_URL          → webhook_url
    ASCENDC_INTERACTIVE          → interactive    ("1"/"true" → True; default False)

Transport: newline-delimited JSON-RPC 2.0 on stdin/stdout (the MCP stdio
framing — one JSON object per line, no embedded newlines, logs go to stderr so
they never corrupt the protocol stream). Implemented methods: ``initialize``,
``notifications/initialized`` (no reply), ``tools/list``, ``tools/call``,
``ping``. The dispatch is factored into ``handle_message`` (pure, async) so a UT
can drive the protocol with plain dicts and no real subprocess.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Awaitable, Callable

from ascendc_devkit.capabilities.mcp_tools import (
    create_resolve_ambiguity_handler,
    RESOLVE_AMBIGUITY_TOOL_NAME,
    RESOLVE_AMBIGUITY_DESCRIPTION,
    RESOLVE_AMBIGUITY_INPUT_SCHEMA,
)

# MCP protocol version we advertise when the client sends none. When the client
# DOES send one (opencode will), we echo it back — the spec says the server
# should agree to the client's requested version if it can support it, and our
# single trivial tool is version-agnostic.
_DEFAULT_PROTOCOL_VERSION = "2025-06-18"
_SERVER_INFO = {"name": "engine", "version": "1.0.0"}

# A (P115): handshake watchdog ceiling (seconds). The FIRST stdin line must be
# the MCP client's ``initialize``; if it never arrives the server would block
# silently on readline (no diagnostic signal, §1.2) until the framework's
# ``message_timeout`` (1h). A bounded wait surfaces the failure fast: log to
# stderr + non-zero exit → opencode's MCP client sees stdio EOF → the framework
# gets an actionable error instead of a silent 1h. Override via env for tuning.
HANDSHAKE_TIMEOUT = float(os.environ.get("ASCENDC_MCP_HANDSHAKE_TIMEOUT", "30"))


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def build_handler_from_env() -> Callable[[dict], Awaitable[dict]]:
    """Construct the resolve_ambiguity handler from the process environment.

    Mirrors the constructor-arg wiring on the claude path (build_engine_mcp_server
    args) but sources every parameter from env, because opencode can only pass
    per-spawn config to a local MCP subprocess via ``environment``.
    """
    return create_resolve_ambiguity_handler(
        interactive=_bool_env("ASCENDC_INTERACTIVE", False),
        on_decision=os.environ.get("ASCENDC_ON_DECISION", "default"),
        workspace_dir=os.environ.get("ASCENDC_DECISION_WORKSPACE") or None,
        webhook_url=os.environ.get("ASCENDC_WEBHOOK_URL") or None,
    )


def _result(msg_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _error(msg_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


async def handle_message(
    msg: dict, handler: Callable[[dict], Awaitable[dict]]
) -> dict | None:
    """Dispatch one JSON-RPC 2.0 message. Returns the response dict, or None for
    notifications (messages with no ``id``, e.g. ``notifications/initialized``)
    which must not be answered.

    Pure w.r.t. I/O: takes a parsed message + the tool handler, returns the
    response object. The stdin/stdout loop lives in ``main``; this split is what
    makes the protocol unit-testable without a real subprocess.
    """
    method = msg.get("method")
    msg_id = msg.get("id")
    # A message with no id is a notification — never answered (JSON-RPC 2.0).
    is_notification = "id" not in msg

    if method == "initialize":
        params = msg.get("params") or {}
        # Agree to the client's protocol version when given; else advertise ours.
        version = params.get("protocolVersion") or _DEFAULT_PROTOCOL_VERSION
        return _result(msg_id, {
            "protocolVersion": version,
            "capabilities": {"tools": {}},
            "serverInfo": _SERVER_INFO,
        })

    if method == "notifications/initialized":
        return None  # notification — no response

    if method == "ping":
        return _result(msg_id, {})

    if method == "tools/list":
        return _result(msg_id, {"tools": [{
            "name": RESOLVE_AMBIGUITY_TOOL_NAME,
            "description": RESOLVE_AMBIGUITY_DESCRIPTION,
            "inputSchema": RESOLVE_AMBIGUITY_INPUT_SCHEMA,
        }]})

    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if name != RESOLVE_AMBIGUITY_TOOL_NAME:
            # Unknown tool: MCP convention surfaces execution-level failures as
            # an isError result (not a protocol error) so the model sees it.
            return _result(msg_id, {
                "content": [{"type": "text",
                             "text": f"unknown tool: {name}"}],
                "isError": True,
            })
        try:
            # The shared handler already returns MCP tool-result shape
            # ({"content": [{"type": "text", "text": ...}]}).
            out = await handler(arguments)
            return _result(msg_id, out)
        except Exception as e:  # noqa: BLE001 — surface as tool error, don't crash the server
            return _result(msg_id, {
                "content": [{"type": "text", "text": f"resolve_ambiguity failed: {e}"}],
                "isError": True,
            })

    # Unknown method with an id → JSON-RPC "method not found". Notifications are
    # silently ignored (a notification we don't recognise needs no reply).
    if is_notification:
        return None
    return _error(msg_id, -32601, f"method not found: {method}")


def _write_message(out, response: dict) -> None:
    out.write(json.dumps(response, ensure_ascii=False) + "\n")
    out.flush()


async def _serve(stdin, stdout, handler,
                 handshake_timeout: float = HANDSHAKE_TIMEOUT) -> None:
    """Read newline-delimited JSON-RPC from *stdin*, dispatch, write responses to
    *stdout*. Runs until stdin closes (opencode terminates the subprocess by
    closing the pipe when the serve session ends).

    A (P115): the FIRST line is bounded by *handshake_timeout* — it must be the
    MCP client's ``initialize``. If it never arrives (e.g. the opencode serve
    stalled on the shared SQLite DB lock under batch concurrency, so it never
    opened the MCP session) the server logs to stderr and exits non-zero
    instead of blocking silently until ``message_timeout`` (§1.2 可诊断).
    Subsequent reads are unbounded — a ``tools/call`` may legitimately block
    (resolve_ambiguity waits on a decision)."""
    loop = asyncio.get_event_loop()

    async def _readline_with_timeout(timeout):
        return await asyncio.wait_for(
            loop.run_in_executor(None, stdin.readline), timeout=timeout)

    try:
        line = await _readline_with_timeout(handshake_timeout)
    except asyncio.TimeoutError:
        print(
            f"engine_mcp_stdio: handshake timeout — no initialize received in "
            f"{handshake_timeout:.0f}s (client never opened the MCP stdio "
            f"session; likely the opencode serve stalled before handshake).",
            file=sys.stderr)
        sys.exit(1)

    while line:  # EOF ("") ends the session
        line = line.strip()
        if line:
            try:
                msg = json.loads(line)
            except json.JSONDecodeError as e:
                # Cannot recover an id from an unparseable line; log to stderr
                # (never stdout — that would corrupt the protocol stream).
                print(f"engine_mcp_stdio: bad JSON-RPC line: {e}", file=sys.stderr)
            else:
                response = await handle_message(msg, handler)
                if response is not None:
                    _write_message(stdout, response)
        line = await loop.run_in_executor(None, stdin.readline)  # unbounded


def main() -> None:
    handler = build_handler_from_env()
    try:
        asyncio.run(_serve(sys.stdin, sys.stdout, handler))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
