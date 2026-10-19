"""Step 1 (chip-target-selection): State dual chip fields + UNKNOWN sentinel.

Splits the former single chip semantics into:
  - design_target_chip: design/compile intent (CLI > req > probe)
  - runtime_target_chip: on-box hardware truth (probe > CLI fallback)
Both default to "" (NOT "A2"): an unresolved chip is honestly empty, not silently
A2. UNKNOWN is the probe's missing-hardware sentinel — deliberately outside
CHIP_GENERATIONS so is_known_generation(UNKNOWN) is False (Step 2).
"""
from __future__ import annotations

from ascendc_devkit.domain import chip
from ascendc_devkit.orchestration.kernel.state import State


class TestStateChipFields:
    def test_state_defaults_empty(self):
        s = State.empty()
        assert s.design_target_chip == ""
        assert s.runtime_target_chip == ""

    def test_with_updates_design_target_only(self):
        s = State.empty().with_updates(design_target_chip="A5", runtime_target_chip="A2")
        assert s.design_target_chip == "A5"
        assert s.runtime_target_chip == "A2"
        # with_updates touches only the named fields
        s2 = s.with_updates(design_target_chip="A3")
        assert s2.design_target_chip == "A3"
        assert s2.runtime_target_chip == "A2"  # unchanged

    def test_from_snapshot_missing_fields_defaults_empty(self):
        snap = State.empty().to_snapshot()
        snap.pop("design_target_chip", None)
        snap.pop("runtime_target_chip", None)
        loaded = State.from_snapshot(snap)
        assert loaded.design_target_chip == ""
        assert loaded.runtime_target_chip == ""

    def test_unknown_sentinel_not_a_known_generation(self):
        assert chip.UNKNOWN == "unknown"
        assert chip.UNKNOWN not in chip.CHIP_GENERATIONS
        assert chip.is_known_generation(chip.UNKNOWN) is False
        assert chip.is_known_generation(chip.A5) is True
