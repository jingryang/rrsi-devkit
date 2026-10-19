"""UT for ``tests.st._dual_backend._classify_smoke_result`` — the pure decision
function behind the opencode positive-smoke precondition (§3.7).

No real opencode / LLM: feeds fake ``AgentResult`` variants and asserts the
pass/skip classification. This is the deterministic core that turns a wrong
``opencode.json`` config into a clear §3.7 skip instead of a false-green pass
on the negative hard-wall test (see plan: opencode 正向冒烟前置).
"""

from __future__ import annotations

from ascendc_devkit.capabilities.agent.backend import AgentResult

from tests.st._dual_backend import _classify_smoke_result


def _result(*, status: str = "ok", aborted: str | None = None,
             error_type: str | None = None) -> AgentResult:
    """Build a minimal AgentResult with only the fields the classifier reads."""
    return AgentResult(
        agent_name="smoke", status=status,
        aborted=aborted, error_type=error_type,
    )


class TestClassifySmokeResult:
    def test_clean_ok_passes(self):
        """ok = healthy gateway response — including a trivial "ACK" reply with
        zero artifacts (F5: 干净零产物不再有独立 status；冒烟只关心网关可达，
        `_result` 默认 artifacts={} 恰好覆盖该形态)。"""
        ok, reason = _classify_smoke_result(_result(status="ok"))
        assert ok and reason == ""

    def test_partial_passes(self):
        """partial = gateway was reached (model started replying); for a smoke
        that is enough evidence opencode config/gateway works."""
        ok, _ = _classify_smoke_result(_result(status="partial"))
        assert ok

    def test_aborted_hard_timeout_fails(self):
        """The blind spot: config broken → spawn hangs → hard wall → aborted.
        Smoke MUST fail here so the negative hard-wall test does not false-green
        on a broken config."""
        ok, reason = _classify_smoke_result(_result(aborted="hard_timeout"))
        assert not ok
        assert "aborted" in reason

    def test_infra_error_fails(self):
        """error_type=infra = opencode env misconfigured (gateway/auth/model in
        opencode.json) — the explicit "config broken" signal (AgentResult docs)."""
        ok, reason = _classify_smoke_result(_result(error_type="infra"))
        assert not ok
        assert "infra" in reason

    def test_fatal_status_fails(self):
        ok, reason = _classify_smoke_result(_result(status="fatal"))
        assert not ok
        assert "status" in reason

    def test_aborted_takes_precedence_over_ok_status(self):
        """Even if status looks ok, an aborted spawn means it hung → FAIL."""
        ok, _ = _classify_smoke_result(_result(status="ok", aborted="hard_timeout"))
        assert ok is False
