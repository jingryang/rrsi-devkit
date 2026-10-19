"""opencode SSE event parsing + event→IR mapping (streaming transport).

Spike-verified 2026-07-20 (opencode 1.18.3, see docs/plan/opencode-streaming-
transport/02-analysis.md §9): the ``GET /event`` stream emits ``text/event-
stream`` frames of shape ``data: {"id":"evt_...","type":"<event>","properties":
{...}}`` — **no** SSE ``event:`` prefix; the type lives inside the JSON (matches
the JS SDK's ``event.type``/``event.properties`` model in docs/opencode-sdk-ref/
sdk.mdx). Every event carries ``properties.sessionID`` so per-session filtering
is trivial.

This module is **pure + I/O-free** (unit-testable in isolation):

  * ``parse_sse_frames``        — raw SSE text lines → parsed event dicts.
  * ``_part_to_block``          — opencode part dict → one IR block (symmetric
                                  with ``opencode_backend._parts_to_records``;
                                  slice 2 refactors that caller to reuse this).
  * ``event_session_id`` / ``event_tokens`` / ``is_session_compacted`` —
    non-record signals the transport layer inspects.

The transport wiring (``GET /event`` bg-thread + ``POST prompt_async`` +
``IRConsumer`` feed + completion on ``session.idle`` + final ``GET`` for
finishReason) lives in ``OpenCodeBackend.spawn`` (slice 2/3), NOT here.

**协议形态注意（field 恒 "text"）**：``message.part.delta`` 的 ``field`` 恒为
``"text"``——它指 part 上被流的属性名（text part 与 reasoning part 的属性同名
``"text"``），**不区分内容类型**（opencode 二进制内嵌发射源码实证）。事件同样
不携带 part 类型；内容类型唯一的来源是 ``message.part.updated`` 先行携带的
``part.type``（→ ``_part_to_block`` 的 kind）。故 delta 的分型必须经
partID → 该类型标记关联（实现见 ``opencode_backend._handle_sse_event`` 的
``part_kinds``），**不得按 field 判别**。
"""

from __future__ import annotations

import json
from typing import Iterable, Iterator

# opencode SSE event types we route (spike-observed). Anything else is noise
# (plugin.added / catalog.updated / reference.updated / integration.updated /
# server.connected / server.heartbeat) — the caller drops it after filtering.
_EVT_MESSAGE_PART_DELTA = "message.part.delta"
_EVT_MESSAGE_PART_UPDATED = "message.part.updated"
_EVT_MESSAGE_UPDATED = "message.updated"
# Context compaction (server collapses history into a summary). Not routed into
# blocks — counted by the backend as a `compactions` metric.
_EVT_SESSION_COMPACTED = "session.compacted"


# —————————————————————————————————————————————————————————————————————————
# SSE frame parser
# —————————————————————————————————————————————————————————————————————————
def parse_sse_frames(lines: Iterable[str]) -> Iterator[dict]:
    """Yield parsed event dicts from raw SSE text lines.

    Each yielded dict is the JSON object the server placed after ``data:``
    (opencode frame ``{id?, type, properties}``). Handling:

      * blank line            → dispatch the buffered frame.
      * line starting with ``:`` → comment / heartbeat → skipped.
      * ``data:`` line        → append (multi-line data joined with ``\\n``).
      * ``event:`` / ``id:``  → tolerated per SSE spec, ignored (opencode puts
                                the type inside the data JSON, spike-confirmed).
      * non-JSON data payload → yield ``{"_raw": <str>}`` so a frame is never
                                silently dropped ( diagnosable, §1.2).

    A trailing frame whose stream ended without a blank line is still yielded.
    """
    data_parts: list[str] = []
    for line in lines:
        line = line.rstrip("\r\n")
        if not line:
            if data_parts:
                yield _parse_data("\n".join(data_parts))
                data_parts = []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            data_parts.append(line[5:].lstrip(" "))
        # event:/id:/retry: and any other field — ignored (type is in data).
    if data_parts:
        yield _parse_data("\n".join(data_parts))


def _parse_data(joined: str) -> dict:
    try:
        parsed = json.loads(joined)
    except json.JSONDecodeError:
        return {"_raw": joined}
    return parsed if isinstance(parsed, dict) else {"_raw": joined}


# —————————————————————————————————————————————————————————————————————————
# opencode part → IR block (shared with _parts_to_records in slice 2)
# —————————————————————————————————————————————————————————————————————————
def _part_to_block(part: dict) -> dict:
    """Map an opencode message part dict to one IR block.

    Symmetric with ``opencode_backend._parts_to_records``' block extraction
    (text/reasoning/tool/step-*). Extracted as a shared helper so the streaming
    mapper and the post-hoc assembler produce identical block schemas; slice 2
    refactors ``_parts_to_records`` to call this (eliminating duplication).
    """
    if not isinstance(part, dict):
        return {"kind": "text", "text": ""}
    ptype = part.get("type")
    if ptype == "text":
        return {"kind": "text", "text": part.get("text", "")}
    if ptype == "reasoning":
        return {"kind": "thinking", "text": part.get("text", "")}
    if ptype == "tool":
        return {"kind": "tool_use",
                "tool_name": part.get("tool") or part.get("name"),
                "tool_input": part.get("state") or part.get("input") or {}}
    # step-start / step-finish / unknown — keep the marker (parity with
    # _parts_to_records: replay can see step boundaries).
    return {"kind": str(ptype), "text": part.get("text", "")}


# —————————————————————————————————————————————————————————————————————————
# Signal accessors (events the transport inspects without producing a record)
# —————————————————————————————————————————————————————————————————————————
def event_session_id(event: dict) -> str | None:
    """session_id from any opencode event (every event carries it somewhere)."""
    if not isinstance(event, dict):
        return None
    props = event.get("properties") or {}
    sid = props.get("sessionID")
    if sid:
        return sid
    info = props.get("info") or {}
    return info.get("sessionID") or info.get("id")


def event_tokens(event: dict) -> dict | None:
    """Token usage from message.updated / session.updated (None otherwise).

    Spike-confirmed at completion: ``info.tokens = {total, input, output,
    reasoning, cache:{read,write}}``. Opportunistic metrics fill (dimension-3).
    """
    if not isinstance(event, dict):
        return None
    if event.get("type") not in (_EVT_MESSAGE_UPDATED, "session.updated"):
        return None
    props = event.get("properties") or {}
    info = props.get("info") or {}
    tokens = info.get("tokens")
    return tokens if isinstance(tokens, dict) else None


def is_session_compacted(event: dict) -> bool:
    """True if the event signals the session context was compacted."""
    if not isinstance(event, dict):
        return False
    return event.get("type") == _EVT_SESSION_COMPACTED
