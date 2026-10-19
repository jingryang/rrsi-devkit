"""Step 5 (chip-target-selection): chip_mismatch_reason pure comparison + gate.

The gate no longer probes: ``runtime_target_chip`` was resolved once at dispatch
(probe authority, Step 3), so ``chip_mismatch_reason`` is now a pure two-arg
comparison ``(design_target, runtime_target) → reason | None``. This eliminates
the double-probe (dispatch + gate) and makes ``validate_inputs`` a cheap pure
gate (§3.8: no NPU-driver I/O in UT — verified by the explosive-detect stub).

``runtime=UNKNOWN`` (probe couldn't identify hardware) is a DISTINCT non-mismatch
state: surfaced as a "cannot verify" reason, neither silently passed nor reported
as a design≠hardware mismatch.
"""
from __future__ import annotations

import pytest

from ascendc_devkit.adapters.npu.detect import chip_mismatch_reason
from ascendc_devkit.domain import chip


class TestChipMismatchPureComparison:
    def test_match_returns_none(self):
        assert chip_mismatch_reason("A5", "A5") is None

    def test_membase_design_forward_compatible_with_higher_gen(self):
        # P65: compatibility is by programming model, not strict generation.
        # A2/A3 are Membase; A5 hardware runs Membase too (backward compatible),
        # so a low-gen Membase design is FORWARD-compatible with an A5 box. This
        # is the mode the user needs: validating A2/A3 Membase codegen on A5.
        assert chip_mismatch_reason("A2", "A5") is None
        assert chip_mismatch_reason("A3", "A5") is None

    def test_membase_portable_across_a2_a3(self):
        # A2↔A3 are the same Membase generation — source is portable across them;
        # only the compile soc_version differs. Never a mismatch.
        assert chip_mismatch_reason("A2", "A3") is None
        assert chip_mismatch_reason("A3", "A2") is None

    def test_regbase_design_blocked_on_membase_runtime(self):
        # P65: the ONLY hard block — an A5 (Regbase) design cannot run on A2/A3
        # (Membase-only hardware; Regbase VF instructions / soc_version fixed at
        # compile time). Message names BOTH values + the "不兼容" framing.
        reason = chip_mismatch_reason("A5", "A3")
        assert reason is not None
        assert "'A5'" in reason and "'A3'" in reason
        assert "不兼容" in reason

    def test_empty_design_returns_none(self):
        # no design constraint → gate is a no-op (regardless of runtime)
        assert chip_mismatch_reason("", "A5") is None
        assert chip_mismatch_reason("", chip.UNKNOWN) is None
        assert chip_mismatch_reason("", "") is None

    def test_runtime_unknown_is_distinct_cannot_verify(self):
        reason = chip_mismatch_reason("A5", chip.UNKNOWN)
        assert reason is not None
        # distinct from a mismatch: names the unknown hardware, no "不兼容"
        assert "无法校验" in reason or "未知" in reason
        assert "不兼容" not in reason

    def test_runtime_empty_is_also_cannot_verify(self):
        reason = chip_mismatch_reason("A5", "")
        assert reason is not None
        assert "无法校验" in reason or "未知" in reason


class TestValidateInputsGateUsesDualFields:
    """codegen.validate_inputs reads design_target_chip/runtime_target_chip and
    does NOT probe (pure comparison)."""

    def test_match_returns_no_error_without_probing(self, monkeypatch):
        from ascendc_devkit.orchestration.kernel.state import State
        from ascendc_devkit.orchestration.stages.codegen import CodegenStage

        def _boom(**_kw):
            raise AssertionError("gate must not probe (pure comparison)")
        monkeypatch.setattr(
            "ascendc_devkit.adapters.npu.detect.detect_chip_version", _boom)
        state = State(
            design_spec={"inputs": [{"name": "x"}], "outputs": [{"name": "y"}]},
            design_target_chip="A2", runtime_target_chip="A2")
        assert CodegenStage().validate_inputs(state) == []

    def test_mismatch_returns_chip_error_without_probing(self, monkeypatch):
        from ascendc_devkit.orchestration.kernel.state import State
        from ascendc_devkit.orchestration.stages.codegen import CodegenStage

        def _boom(**_kw):
            raise AssertionError("gate must not probe (pure comparison)")
        monkeypatch.setattr(
            "ascendc_devkit.adapters.npu.detect.detect_chip_version", _boom)
        # P65: A5(Regbase) design + A2(Membase-only) runtime = the true hard
        # block. validate_inputs surfaces it without probing.
        state = State(
            design_spec={"inputs": [{"name": "x"}], "outputs": [{"name": "y"}]},
            design_target_chip="A5", runtime_target_chip="A2")
        errors = CodegenStage().validate_inputs(state)
        chip_errors = [e for e in errors if "'A5'" in e and "'A2'" in e]
        assert len(chip_errors) == 1

    def test_forward_compat_passes_gate_without_probing(self, monkeypatch):
        from ascendc_devkit.orchestration.kernel.state import State
        from ascendc_devkit.orchestration.stages.codegen import CodegenStage

        def _boom(**_kw):
            raise AssertionError("gate must not probe (pure comparison)")
        monkeypatch.setattr(
            "ascendc_devkit.adapters.npu.detect.detect_chip_version", _boom)
        # P65: A2(Membase) design + A5 runtime = forward-compatible (A5 runs
        # Membase). Must pass the gate with NO error — this is the user's core
        # use case (validate A2/A3 Membase codegen on an A5 box).
        state = State(
            design_spec={"inputs": [{"name": "x"}], "outputs": [{"name": "y"}]},
            design_target_chip="A2", runtime_target_chip="A5")
        assert CodegenStage().validate_inputs(state) == []

    def test_runtime_unknown_returns_cannot_verify(self, monkeypatch):
        from ascendc_devkit.orchestration.kernel.state import State
        from ascendc_devkit.orchestration.stages.codegen import CodegenStage

        def _boom(**_kw):
            raise AssertionError("gate must not probe (pure comparison)")
        monkeypatch.setattr(
            "ascendc_devkit.adapters.npu.detect.detect_chip_version", _boom)
        state = State(
            design_spec={"inputs": [{"name": "x"}], "outputs": [{"name": "y"}]},
            design_target_chip="A5", runtime_target_chip=chip.UNKNOWN)
        errors = CodegenStage().validate_inputs(state)
        assert any("无法校验" in e or "未知" in e for e in errors)
