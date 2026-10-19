"""UT for IRConsumer + _build_result factory (step-68). The consumer owns all
per-event signal extraction (ported from sdk_backend :456-546); the factory is
the single AgentResult constructor (replaces 8 scattered return sites)."""

from ascendc_devkit.capabilities.agent.base_backend import (
    BaseAgentBackend, IRConsumer, _ir_tool_sig)


def _ir(role="assistant", blocks=None, **kw):
    d = {"ts": 1, "turn": 0, "role": role, "blocks": blocks or []}
    d.update(kw)
    return d


# —— IRConsumer signal extraction ————————————————————————————

def test_consumer_extracts_first_session_id():
    c = IRConsumer("a")
    c.consume(_ir(session_id=""))
    c.consume(_ir(session_id="ses1"))
    c.consume(_ir(session_id="ses2"))
    assert c.session_id == "ses1"   # first non-empty wins


def test_consumer_accumulates_text_and_thinking():
    c = IRConsumer("a")
    c.consume(_ir("assistant", [{"kind": "text", "text": "hello "},
                                 {"kind": "thinking", "text": "(think)"}]))
    assert c.full_response == "hello (think)"
    assert c.turn_count == 1


def test_consumer_last_assistant_text_excludes_thinking():
    c = IRConsumer("a")
    # turn 1: thinking + text
    c.consume(_ir("assistant", [{"kind": "thinking", "text": "考虑中"},
                                 {"kind": "text", "text": "## RETURN: status=COMPLETED"}]))
    assert c.last_assistant_text == "## RETURN: status=COMPLETED"
    # turn 2 (新 turn)：只含文本 → last_assistant_text 反映最后一轮
    c.consume(_ir("assistant", [{"kind": "text", "text": "final reply"}]))
    assert c.last_assistant_text == "final reply"


def test_consumer_truncation_from_stop_reason():
    c = IRConsumer("a")
    c.consume(_ir("assistant", [{"kind": "text", "text": "x"}]))
    c.consume(_ir("result", stop_reason="max_tokens"))
    assert c.truncated_turns == [1]


def test_consumer_no_truncation_for_end_turn():
    c = IRConsumer("a")
    c.consume(_ir("assistant", [{"kind": "text", "text": "x"}]))
    c.consume(_ir("result", stop_reason="end_turn"))
    assert c.truncated_turns == []


def test_consumer_stall_on_repeated_idle_turns():
    # bootstrap grace (turn_count<=8) → BOOTSTRAP_MAX_STALLED=5
    c = IRConsumer("a")
    for _ in range(6):
        c.consume(_ir("assistant", []))   # no text, no tool → no progress
    assert c.stalled_turns == 6
    assert c.should_stop is True          # 6 >= 5


def test_consumer_stall_resets_on_progress():
    c = IRConsumer("a")
    c.consume(_ir("assistant", []))       # idle → stalled=1
    c.consume(_ir("assistant", [{"kind": "text", "text": "progress"}]))
    assert c.stalled_turns == 0
    assert c.should_stop is False


def test_consumer_new_tool_use_is_progress():
    c = IRConsumer("a")
    c.consume(_ir("assistant",
                  [{"kind": "tool_use", "tool_name": "Read", "tool_input": {"f": "a"}}]))
    assert c.stalled_turns == 0           # new tool = progress


def test_consumer_repeated_tool_use_not_progress():
    c = IRConsumer("a")
    sig_block = {"kind": "tool_use", "tool_name": "Read", "tool_input": {"f": "a"}}
    c.consume(_ir("assistant", [sig_block]))          # turn 1 new tool
    c.consume(_ir("assistant", [sig_block]))          # turn 2 same sig, no text
    assert c.stalled_turns == 1


def test_consumer_tool_result_scan_feeds_errored_sigs():
    c = IRConsumer("a")
    c.consume(_ir("assistant",
                  [{"kind": "tool_use", "tool_name": "Bash", "tool_input": {"c": "ls"}}]))
    c.consume(_ir("user",
                  [{"kind": "tool_result", "is_error": True, "content": "err"}]))
    # errored tool_result → prior turn's sigs marked errored
    assert any("Bash" in s for s in c._errored_sigs)


def test_ir_tool_sig_format():
    assert _ir_tool_sig({"tool_name": "Read", "tool_input": {"f": "a"}}) == 'Read:{"f": "a"}'
    assert _ir_tool_sig({"tool_input": {"f": "a"}}) == ':{"f": "a"}'


# —— _build_result factory status machine ————————————————————————

class _B(BaseAgentBackend):
    def spawn(self, *a, **kw):  # abstract stub — tests only exercise _build_result
        raise NotImplementedError


def _consumer_with(session_id="ses", truncated=None, response="hello"):
    c = IRConsumer("a")
    c.session_id = session_id
    c.truncated_turns = truncated or []
    c.full_response = response
    return c


def _build(**kw):
    defaults = dict(agent_name="a", consumer=_consumer_with(),
                    crashed=False, crash_reason=None, artifacts={"f": "c"},
                    transcript_path=None, attempt=1, start_ms=0)
    defaults.update(kw)
    return _B()._build_result(**defaults)


def test_build_result_ok():
    r = _build()
    assert r.status == "ok"
    assert r.session_id == "ses"
    assert r.truncated_turns == []
    assert r.metrics["response_len"] == 5
    assert "failure_reason" not in r.metrics


def test_build_result_clean_no_artifacts_is_ok():
    """F5: 干净完成 + 零产物 → status="ok"。"空产出"不是一个语义类别——有无
    产出由消费方按业务判据查 artifacts 字典，status 只报过程事实。"""
    r = _build(artifacts={})
    assert r.status == "ok"
    assert r.artifacts == {}


def test_build_result_partial_crash_with_artifacts():
    r = _build(crashed=True, crash_reason="API Error: 401 Unauthorized",  # infra
               artifacts={"f": "c"}, attempt=3)
    assert r.status == "partial"
    assert r.metrics["failure_reason"] == "API Error: 401 Unauthorized"
    assert r.metrics["resume_attempts"] == 2
    assert r.error_type == "infra"   # _classify_error_type maps it → infra


def test_build_result_fatal_crash_no_artifacts():
    r = _build(crashed=True, crash_reason="boom", artifacts={})
    assert r.status == "fatal"
    assert r.metrics["failure_reason"] == "boom"


def test_build_result_injects_truncated_turns():
    r = _build(consumer=_consumer_with(truncated=[2, 5]))
    assert r.truncated_turns == [2, 5]


def test_build_result_sets_final_response_from_consumer():
    c = _consumer_with()
    c.last_assistant_text = "## RETURN: status=COMPLETED, next_sub_stage=4.F"
    r = _build(consumer=c)
    assert r.final_response == "## RETURN: status=COMPLETED, next_sub_stage=4.F"


def test_build_result_final_response_defaults_empty():
    # consumer 无最后一轮文本 → final_response 为空串；无 consumer → None
    assert _build().final_response == ""
    assert _build(consumer=None).final_response is None


def test_build_result_no_consumer_early_fatal():
    # SDK import failure — no stream ran, consumer is None
    r = _build(consumer=None, crashed=True, crash_reason="import failed", artifacts={})
    assert r.status == "fatal"
    assert r.session_id == ""
    assert r.truncated_turns == []


# —— Part 1 (20260810 批根因修复) silent-cut 信号 ——

def test_consumer_last_turn_actionable_thinking_only():
    """末条 assistant 消息只有 thinking（无 text、无 tool_use）= 被切信号。"""
    c = IRConsumer("a")
    c.consume(_ir("assistant", [{"kind": "thinking", "text": "(thinking...)"}]))
    assert c._last_turn_actionable is False

    # 后续消息刷新 —— 有 text 则 actionable
    c.consume(_ir("assistant", [{"kind": "thinking", "text": "..."},
                                {"kind": "text", "text": "done"}]))
    assert c._last_turn_actionable is True


def test_consumer_last_turn_actionable_tool_use():
    c = IRConsumer("a")
    c.consume(_ir("assistant", [{"kind": "tool_use",
                                 "tool_name": "bash", "tool_input": {}}]))
    assert c._last_turn_actionable is True   # 工具调用 = 有行动


def test_consumer_last_turn_actionable_default_true():
    """无 assistant 消息（异常流）默认不可判定 → 不误判为 cut。"""
    c = IRConsumer("a")
    assert c._last_turn_actionable is True


# —— P6（step-110）thinking 分型累计（硬切分类证据，sdk 侧流内实时） ——————————

def test_consumer_thinking_accumulated_and_ts_stamped():
    c = IRConsumer("a")
    assert c.thinking_chars == 0 and c.last_thinking_ts is None   # 初始无证据
    c.consume(_ir("assistant", [{"kind": "thinking", "text": "abc"},
                                {"kind": "thinking", "text": "de"}]))
    assert c.thinking_chars == 5, "消息内多 thinking 块累计"
    assert c.last_thinking_ts is not None, "thinking 到达即打点（流内真实时刻）"


def test_consumer_text_not_counted_as_thinking():
    c = IRConsumer("a")
    c.consume(_ir("assistant", [{"kind": "thinking", "text": "abc"},
                                {"kind": "text", "text": "hello"}]))
    assert c.thinking_chars == 3, "text 不计入 thinking"
    # text-only 消息覆写为 0（末条消息无思考）
    c.consume(_ir("assistant", [{"kind": "text", "text": "done"}]))
    assert c.thinking_chars == 0


def test_consumer_thinking_chars_reflects_last_assistant_message():
    """cut 判的是末条消息——thinking 体量逐消息覆写（cut 时 = 被切步体量）。"""
    c = IRConsumer("a")
    c.consume(_ir("assistant", [{"kind": "thinking", "text": "x" * 100}]))
    c.consume(_ir("assistant", [{"kind": "thinking", "text": "y" * 30}]))
    assert c.thinking_chars == 30


# —— P6（step-110）classify_cut 单点（两侧 backend 共用，gap 判据零模型参数）——

def test_classify_cut_hard_when_gap_small():
    from ascendc_devkit.capabilities.agent.base_backend import classify_cut
    import time as _time
    now = _time.time()
    out = classify_cut(95000, now - 0.12, gap_threshold_s=0.6, now=now)
    assert out is not None
    facts, hard = out
    assert hard is True, "思考流活跃至末刻 = 硬切（外部输出墙形态）"
    assert facts["thinking_chars"] == 95000
    assert facts["last_delta_to_end_s"] == 0.12


def test_classify_cut_not_hard_when_gap_large():
    from ascendc_devkit.capabilities.agent.base_backend import classify_cut
    import time as _time
    now = _time.time()
    _, hard = classify_cut(95000, now - 5.0, gap_threshold_s=0.6, now=now)
    assert hard is False, "末次思考距结束远 = 别的失败形态（停滞后断流），不命中"


def test_classify_cut_none_without_thinking_evidence():
    from ascendc_devkit.capabilities.agent.base_backend import classify_cut
    import time as _time
    # 无 thinking 到达（ts=None）→ 判据不成立（走未知中断原路径）
    assert classify_cut(0, None, gap_threshold_s=0.6) is None
    assert classify_cut(95000, None, gap_threshold_s=0.6) is None
    # 零体量（空 delta 病理）同样不成立
    assert classify_cut(0, _time.time(), gap_threshold_s=0.6) is None


def test_classify_cut_threshold_is_the_boundary():
    from ascendc_devkit.capabilities.agent.base_backend import classify_cut
    import time as _time
    now = _time.time()
    _, hard_at = classify_cut(1, now - 0.6, gap_threshold_s=0.6, now=now)
    _, hard_over = classify_cut(1, now - 0.61, gap_threshold_s=0.6, now=now)
    assert hard_at is True and hard_over is False, "gap == 阈值命中（≤），刚超不命中"


def test_consumer_reset_stall_keeps_thinking_evidence():
    """跨 resume 尝试口径：reset_stall 只清 per-attempt 停滞信号，thinking
    证据（chars/ts）与 full_response 同类持久事实，不清零。"""
    c = IRConsumer("a")
    c.consume(_ir("assistant", [{"kind": "thinking", "text": "deep"}]))
    _ts = c.last_thinking_ts
    c.reset_stall()
    assert c.thinking_chars == 4
    assert c.last_thinking_ts is _ts
