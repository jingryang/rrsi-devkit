"""step-96 D1 审计补 — 终态消息消费质量态（best_quality 的下游消费者，M4 迁移后）。

step-96 反面审查发现：`PrecisionDebugResult.best_quality` 字段落了但零消费者——
D1 承诺「质量事实流转给 eval/report」，缺最后一块会让字段成为 write-only
（§2.10 反例）。`_format_error_for_display` 是终态消息的自然最小消费者：
「为什么没过」必须可见（bad 0/20 = 未产出可用 kernel ≠ partial 12/20），
max_diff 对崩溃类失败恒 0 无信息量。

M4：`_format_error_for_display` 属 route_decision 死簇（无生产接线，§2.5 删）。
渲染契约迁移到活路径 —— ``dispatcher._debug_quality_line``（helper）+ 经
``dispatcher._terminal_message_for``（corrective_exhausted 终态停线消息）消费，
质量态随产物流转的终态消费者不丢。
"""
from __future__ import annotations

from ascendc_devkit.application.dispatcher import _debug_quality_line, _terminal_message_for
from ascendc_devkit.domain.verification import PrecisionDebugResult
from ascendc_devkit.orchestration.kernel.state import State


def _state(dr=None) -> State:
    return State(mode="new", debug_result=dr)


class TestDebugQualityLine:
    """``_debug_quality_line`` 渲染质量态（bad/partial 或 legacy max_diff 行）。"""

    def test_bad_surfaces_counts_and_label(self):
        msg = _debug_quality_line(_state(PrecisionDebugResult(
            passed=False, best_passed_count=0, failing_cases=["c1", "c2"],
            best_quality="bad")))
        assert "quality=bad" in msg
        assert "best=0 passed" in msg
        assert "failing=2" in msg
        assert "零正证据" in msg

    def test_partial_surfaces_counts(self):
        msg = _debug_quality_line(_state(PrecisionDebugResult(
            passed=False, max_diff=0.37, best_passed_count=12,
            failing_cases=["c3"], best_quality="partial")))
        assert "quality=partial" in msg
        assert "best=12 passed" in msg
        assert "部分通过" in msg

    def test_unmeasured_or_absent_keeps_legacy_line(self):
        msg = _debug_quality_line(_state(PrecisionDebugResult(
            passed=False, max_diff=0.5, best_quality="unmeasured")))
        assert "max_diff=0.5" in msg
        assert "quality=" not in msg

    def test_passed_not_mentioned(self):
        assert _debug_quality_line(_state(PrecisionDebugResult(
            passed=True, best_quality="good"))) == ""

    def test_no_debug_result_empty(self):
        assert _debug_quality_line(_state()) == ""


class TestTerminalMessageQuality:
    """corrective_exhausted 停线消息 append 质量行 —— 活路径消费（D1 承诺不丢）。"""

    def test_corrective_exhausted_appends_bad_quality(self):
        state = State(
            mode="new",
            is_terminal=True,
            halt_reason={"kind": "corrective_exhausted",
                         "stage": "codegen", "message": "boom"},
            debug_result=PrecisionDebugResult(
                passed=False, best_passed_count=0, failing_cases=["c1", "c2"],
                best_quality="bad"),
        )
        lines = _terminal_message_for(state)
        # single message: the guidance text, then \n + the quality line
        assert len(lines) == 1
        assert "quality=bad" in lines[0]
        assert "best=0 passed" in lines[0]

    def test_corrective_exhausted_without_quality_keeps_legacy(self):
        state = State(
            mode="new",
            is_terminal=True,
            halt_reason={"kind": "corrective_exhausted",
                         "stage": "codegen", "message": "boom"},
            debug_result=PrecisionDebugResult(
                passed=False, max_diff=0.05),
        )
        lines = _terminal_message_for(state)
        assert len(lines) == 1
        assert "max_diff=0.05" in lines[0]

    def test_fail_strategy_halt_no_quality_line(self):
        state = State(
            mode="new",
            is_terminal=True,
            halt_reason={"kind": "fail_strategy_halt",
                         "stage": "codegen", "message": "boom"},
            debug_result=PrecisionDebugResult(
                passed=False, best_quality="bad"),
        )
        lines = _terminal_message_for(state)
        assert len(lines) == 1
        assert "quality=" not in lines[0]
        assert "fail_strategy=halt" in lines[0]

    def test_upstream_defect_not_framed_as_coder_bug(self):
        state = State(
            mode="new",
            is_terminal=True,
            halt_reason={"kind": "upstream_defect",
                         "stage": "codegen", "message": "golden drift"},
        )
        lines = _terminal_message_for(state)
        assert len(lines) == 1
        assert "upstream" in lines[0]
        assert "not the coder" in lines[0]

    def test_generic_fallback_appends_quality_when_debug_failed(self):
        """halt_reason absent/kind unknown → generic defensive text; M4 new
        behavior appends the quality line there too (a corrective-exhaustion
        terminal reached without a disambiguated kind still surfaces why)."""
        state = State(
            mode="new",
            is_terminal=True,
            halt_reason={},  # defensive fallback: kind missing
            debug_result=PrecisionDebugResult(
                passed=False, best_passed_count=12, failing_cases=["c3"],
                best_quality="partial"),
        )
        lines = _terminal_message_for(state)
        assert len(lines) == 1
        assert "exhausted its correction budget" in lines[0]
        assert "quality=partial" in lines[0]

    def test_generic_fallback_without_debug_no_quality(self):
        """generic fallback with no failing debug_result stays legacy text."""
        lines = _terminal_message_for(State(mode="new", is_terminal=True))
        assert len(lines) == 1
        assert "exhausted its correction budget" in lines[0]
        assert "Precision" not in lines[0]
