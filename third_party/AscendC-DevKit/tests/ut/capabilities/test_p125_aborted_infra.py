"""P125 (trial-20260730): watchdog abort 的真因必须翻译进 error_type=infra。

根因：turn-stall / keepalive / hard-cap 三种 watchdog kill 走 clean-finish 或
crash-salvage 路径，crash_reason 文案（"no new turn for 305s > turn_stall 300s"
等）**不含任何** _INFRA_ERROR_MARKERS，故 _classify_error_type 返回 None →
error_type 为空 → 下游 design 归因（只认 error_type=="infra"）落 missing_artifact
「写错目录」误报，掩盖"被外部中断"的真因（trial-4 四算子中招）。

修复（§1.10 业务语义，不靠文案代理）：_build_result 在 crashed 且 ``aborted``
非空时，若 error_type 仍未被分类为 infra，则设 error_type="infra"——``aborted``
非空是"agent 被 watchdog 杀死、当前轮不可重试、须 resume 重跑"的**显式业务语义
信号**，等价于 infra（短路终止迭代 + node_status failed + resume 重跑）。
"""
from __future__ import annotations

from pathlib import Path

from ascendc_devkit.capabilities.agent.base_backend import BaseAgentBackend


class _MiniBackend(BaseAgentBackend):
    """Minimal concrete backend to exercise the shared _build_result factory."""

    def spawn(self, *a, **k):  # abstract in AgentBackend; unused here
        raise NotImplementedError


def _br(**kw):
    """Call _build_result with sensible defaults; override via kwargs."""
    b = _MiniBackend()
    defaults = dict(
        agent_name="x", consumer=None, crashed=True, crash_reason="boom",
        artifacts={}, transcript_path=None, attempt=1, start_ms=0)
    defaults.update(kw)
    return b._build_result(**defaults)


class TestAbortedTranslatesToInfra:
    def test_turn_stall_abort_is_infra(self):
        """turn-stall 文案无 infra marker，但 aborted 置位 → error_type=infra。"""
        r = _br(aborted="turn_stall",
                crash_reason="x: no new turn for 305s > turn_stall 300s — last turn 10")
        assert r.error_type == "infra"

    def test_keepalive_abort_is_infra(self):
        r = _br(aborted="keepalive",
                crash_reason="x: no SSE activity for 640s > idle cap 600s")
        assert r.error_type == "infra"

    def test_hard_timeout_abort_is_infra(self):
        r = _br(aborted="hard_timeout", crash_reason="x: exceeded 3600s hard cap")
        assert r.error_type == "infra"

    # —— regression guards ————————————————————————————————————————————————

    def test_plain_logic_failure_stays_none(self):
        """未 crashed 的普通逻辑失败不受影响 — error_type 保持 None
        (P51/P116 loopback 仍按 logic failure 处理，不被误判成 infra)。"""
        r = _br(crashed=False, aborted=None, crash_reason=None)
        assert r.error_type is None

    def test_unknown_crash_catchall_transient(self):
        """crashed 但无 marker、无 aborted、也非连接异常 → 兜底 infra_transient
        （fail-open：未知 crash 默认有界重试，不再落「中性失败」夹缝）。"""
        r = _br(aborted=None, crash_reason="Remote end closed connection without response")
        assert r.error_type == "infra_transient"

    def test_marker_infra_still_classified_without_aborted(self):
        """文案已含 infra marker 时，即使 aborted=None 仍判 infra（原路径保留）。"""
        r = _br(aborted=None, crash_reason="No available channel for model")
        assert r.error_type == "infra"

    def test_error_type_override_wins_over_aborted(self):
        """显式 override 优先，不被 aborted→infra 覆盖。"""
        r = _br(aborted="hard_timeout", error_type_override="rate_limit",
                crash_reason="x: exceeded cap")
        assert r.error_type == "rate_limit"

    def test_not_crashed_aborted_ignored(self):
        """未 crashed 的 clean finish 即使传了 aborted 也不派生 error_type
        （error_type 只在 crashed 路径派生，语义不变）。"""
        r = _br(crashed=False, aborted="turn_stall", crash_reason=None,
                artifacts={"f.json": "{}"})
        assert r.error_type is None
