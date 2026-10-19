"""Step 3 (chip-target-selection): dispatcher dual-field chip resolution.

Splits the single ``resolved_chip`` (which conflated CLI design intent and probed
hardware truth, and let ``--assume-chip`` leak into the target side making the
run gate a tautology) into two fields with disjoint authority:

  - ``design_target_chip`` — CLI ``--design_target_chip`` only, here. The
    requirement-doc / profile-default layers of its authority chain are applied
    downstream in context/requirement stage (Step 6); dispatch carries the CLI
    value (may be empty → resolved downstream).
  - ``runtime_target_chip`` — probe authority; ``--runtime_target_chip`` is ONLY
    a flaky-driver timeout fallback (the probe wins whenever it can answer).

A probe timeout no longer hard-halts: if the user declared
``--runtime_target_chip``, the run continues with that fallback (+ warning);
only a timeout with no fallback returns ``None`` → dispatch halts ``EX_DATAERR``.
"""
from __future__ import annotations

import pytest

from ascendc_devkit.adapters.npu.detect import EnvironmentProbeTimeout
from ascendc_devkit.orchestration.runtime_probe import _resolve_chip_fields
from ascendc_devkit.domain import chip


def _req(**kw) -> dict:
    base: dict = {}
    base.update(kw)
    return base


def _probe_timeout(**_kw):
    raise EnvironmentProbeTimeout(1.0)


class TestResolveChipFields:
    def test_design_from_cli_runtime_from_probe(self, monkeypatch):
        monkeypatch.setattr(
            "ascendc_devkit.orchestration.runtime_probe.detect_chip_version",
            lambda **kw: "A2")
        design, runtime, dsrc, rsrc = _resolve_chip_fields(
            _req(design_target_chip="A5"), probe_timeout_sec=1.0)
        assert design == "A5"   # CLI design intent
        assert runtime == "A2"  # probe hardware truth
        assert dsrc == "cli"    # design came from --design_target_chip
        assert rsrc == "probe"  # runtime came from the bounded probe

    def test_no_cli_design_leaves_design_empty(self, monkeypatch):
        # design's downstream layers (req/profile) are NOT resolved here — an
        # empty CLI design stays empty for context/requirement stage to fill.
        monkeypatch.setattr(
            "ascendc_devkit.orchestration.runtime_probe.detect_chip_version",
            lambda **kw: "A3")
        design, runtime, dsrc, rsrc = _resolve_chip_fields(_req(), probe_timeout_sec=1.0)
        assert design == ""
        assert runtime == "A3"
        assert dsrc == ""        # no CLI design → empty source (filled downstream)
        assert rsrc == "probe"

    def test_probe_unknown_propagates_as_runtime(self, monkeypatch):
        monkeypatch.setattr(
            "ascendc_devkit.orchestration.runtime_probe.detect_chip_version",
            lambda **kw: chip.UNKNOWN)
        design, runtime, dsrc, rsrc = _resolve_chip_fields(_req(), probe_timeout_sec=1.0)
        assert runtime == chip.UNKNOWN
        assert design == ""
        assert rsrc == "probe"   # the probe ran and honestly returned UNKNOWN

    def test_probe_timeout_with_cli_fallback(self, monkeypatch):
        monkeypatch.setattr(
            "ascendc_devkit.orchestration.runtime_probe.detect_chip_version",
            _probe_timeout)
        design, runtime, dsrc, rsrc = _resolve_chip_fields(
            _req(runtime_target_chip="A3"), probe_timeout_sec=1.0)
        assert runtime == "A3"  # CLI fallback wins on timeout
        assert design == ""
        assert rsrc == "timeout_fallback"  # probe timed out → CLI stood in
        assert dsrc == ""

    def test_probe_timeout_no_fallback_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            "ascendc_devkit.orchestration.runtime_probe.detect_chip_version",
            _probe_timeout)
        assert _resolve_chip_fields(_req(), probe_timeout_sec=1.0) is None


class TestEntryTransitionChipRebuild:
    """EntryStage.transition rebuilds the dual fields from task_request so a
    resume (which re-runs entry) doesn't lose them."""

    def test_rebuilds_dual_fields_from_task_request(self):
        from ascendc_devkit.orchestration.kernel.state import State
        from ascendc_devkit.orchestration.stages.entry import EntryStage

        tr = {"design_target_chip": "A5", "runtime_target_chip": "A2"}
        state = State(mode="new", task_request=tr,
                      design_target_chip="", runtime_target_chip="")
        result = EntryStage().transition(state, result={})
        assert result.design_target_chip == "A5"
        assert result.runtime_target_chip == "A2"

    def test_preserves_existing_when_task_request_silent(self):
        from ascendc_devkit.orchestration.kernel.state import State
        from ascendc_devkit.orchestration.stages.entry import EntryStage

        # task_request carries no chip keys (e.g. resume of an older run) → keep
        # whatever the snapshot already resolved (runtime was probe-resolved at
        # dispatch; must not be blanked on resume).
        state = State(mode="new", task_request={},
                      design_target_chip="A3", runtime_target_chip="A5")
        result = EntryStage().transition(state, result={})
        assert result.design_target_chip == "A3"
        assert result.runtime_target_chip == "A5"
