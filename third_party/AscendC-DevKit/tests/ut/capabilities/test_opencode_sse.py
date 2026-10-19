"""UT for opencode SSE parsing (streaming transport slice 1).

Pure, deterministic, millisecond-scale — no real ``opencode serve`` (§3.8).
Spike-observed payloads (2026-07-20, opencode 1.18.3) drive every fixture; see
docs/plan/opencode-streaming-transport/02-analysis.md §9 for the raw frames.

**协议形态注意**：``message.part.delta`` 的 ``field`` 恒为 ``"text"``（指 part
属性名，text/reasoning part 同名），不区分内容类型；事件不携带 part 类型，
内容类型只能取自 ``message.part.updated`` 先行的 ``part.type``。故本文件不含
「按 field 分型」的用例——那条通路按 §2.5 已删除（见
docs/plan/opencode-cut-classification/）。协议守护见
``test_opencode_backend.py::test_sse_part_kinds_tracked_from_real_wire_frames``。
"""

from __future__ import annotations

import json

from ascendc_devkit.capabilities.agent.opencode_sse import (
    _part_to_block,
    event_session_id,
    event_tokens,
    is_session_compacted,
    parse_sse_frames,
)


def _frame(t: str, props: dict) -> str:
    """One SSE frame as the server emits it: `data: <json>\\n\\n`."""
    return "data: " + json.dumps({"id": "evt_x", "type": t, "properties": props}) + "\n\n"


# —————————————————————————————————————————————————————————————————————————
# parse_sse_frames
# —————————————————————————————————————————————————————————————————————————
def test_parse_single_data_frame():
    out = list(parse_sse_frames([_frame("server.connected", {})]))
    assert out == [{"id": "evt_x", "type": "server.connected", "properties": {}}]


def test_parse_multiline_data_joined():
    # multi-line data: must be joined with \n before JSON parse
    payload = '{"type": "x",\n"properties": {"a": 1}}'
    lines = ["data: " + payload.split("\n")[0] + "\n",
             "data: " + payload.split("\n")[1] + "\n",
             "\n"]
    out = list(parse_sse_frames(lines))
    assert out == [{"type": "x", "properties": {"a": 1}}]


def test_parse_heartbeat_and_comment_skipped():
    lines = [": keepalive\n", _frame("server.heartbeat", {})]
    out = list(parse_sse_frames(lines))
    assert len(out) == 1 and out[0]["type"] == "server.heartbeat"


def test_parse_non_json_yields_raw_not_dropped():
    out = list(parse_sse_frames(["data: not-json\n", "\n"]))
    assert out == [{"_raw": "not-json"}]


def test_parse_trailing_frame_without_blank_flushed():
    out = list(parse_sse_frames(["data: " + json.dumps({"type": "tail"}) + "\n"]))
    assert out == [{"type": "tail"}]


def test_parse_event_id_prefixes_tolerated():
    # opencode puts type inside data (spike-confirmed); spec event:/id: ignored.
    out = list(parse_sse_frames([
        "event: ignored\n",
        "id: 42\n",
        "data: " + json.dumps({"type": "real"}) + "\n",
        "\n",
    ]))
    assert out == [{"type": "real"}]


# —————————————————————————————————————————————————————————————————————————
# _part_to_block
# —————————————————————————————————————————————————————————
def test_part_to_block_text():
    assert _part_to_block({"type": "text", "text": "hi"}) == {"kind": "text", "text": "hi"}


def test_part_to_block_reasoning_is_thinking():
    assert _part_to_block({"type": "reasoning", "text": "ponder"}) == {"kind": "thinking", "text": "ponder"}


def test_part_to_block_tool():
    b = _part_to_block({"type": "tool", "tool": "Read", "state": {"path": "/a"}})
    assert b == {"kind": "tool_use", "tool_name": "Read", "tool_input": {"path": "/a"}}


def test_part_to_block_step_marker_kept():
    assert _part_to_block({"type": "step-start"}) == {"kind": "step-start", "text": ""}


# —————————————————————————————————————————————————————————————————————————
# signal accessors
# —————————————————————————————————————————————————————————————————————————
def test_event_session_id_from_properties():
    assert event_session_id({"type": "x", "properties": {"sessionID": "ses_9"}}) == "ses_9"


def test_event_session_id_from_info():
    assert event_session_id({"type": "session.created",
                             "properties": {"info": {"id": "ses_info"}}}) == "ses_info"


def test_event_tokens_from_message_updated():
    ev = {"type": "message.updated",
          "properties": {"info": {"tokens": {"input": 10, "output": 2}}}}
    assert event_tokens(ev) == {"input": 10, "output": 2}


def test_event_tokens_none_for_other_types():
    assert event_tokens({"type": "message.part.delta", "properties": {}}) is None


def test_is_session_compacted_only_for_compacted_event():
    assert is_session_compacted({"type": "session.compacted", "properties": {}}) is True
    for t in ("session.idle", "session.status", "message.updated",
              "message.part.delta"):
        assert is_session_compacted({"type": t, "properties": {}}) is False


# —————————————————————————————————————————————————————————————————————————
# wire 解析端到端：一段真实形态的帧序列经 parser 后逐帧可识别
# —————————————————————————————————————————————————————————————————————————
def test_wire_frames_parse_end_to_end():
    """一段真实形态的帧序列（connected → part.updated → part.delta → idle）
    经 ``parse_sse_frames`` 后逐帧识别正确。

    帧形态取自 spike 捕获（2026-07-20）。重点守护 delta 的**真实形态**：
    ``field`` 恒为 ``"text"``（不区分内容类型），类型标记只出现在先行的
    ``part.updated`` 的 ``part.type`` 上——这正是 backend 分型所依赖的协议事实。
    """
    sse = (
        _frame("server.connected", {}) +
        _frame("message.part.updated",
               {"sessionID": "ses_1",
                "part": {"id": "p1", "type": "reasoning", "text": "",
                         "messageID": "m_a"}}) +
        _frame("message.part.delta",
               {"sessionID": "ses_1", "messageID": "m_a", "partID": "p1",
                "field": "text", "delta": "OK"}) +
        _frame("session.idle", {"sessionID": "ses_1"})
    )
    events = list(parse_sse_frames(sse.splitlines(keepends=True)))
    assert [e["type"] for e in events] == [
        "server.connected", "message.part.updated", "message.part.delta",
        "session.idle"]
    # 每帧 sessionID 一致（无跨会话泄漏的前提）
    for ev in events[1:]:
        assert event_session_id(ev) == "ses_1"
    # 类型标记只在 part.updated；delta 的 field 恒 "text"（不含类型信息）
    marker = events[1]["properties"]["part"]
    assert marker["type"] == "reasoning" and marker["id"] == "p1"
    delta = events[2]["properties"]
    assert delta["field"] == "text" and delta["partID"] == "p1"
    assert _part_to_block(marker)["kind"] == "thinking"
