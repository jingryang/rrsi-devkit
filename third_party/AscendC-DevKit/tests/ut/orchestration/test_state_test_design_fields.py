"""P1 (step-4) — State test_design fields (test_cases / test_design_report)
+ snapshot back-compat. Authoritative source for verify's test cases is now
state.test_cases (requirement.test_cases retained as fallback)."""

from pathlib import Path

from ascendc_devkit.domain.requirement import TestCase
from ascendc_devkit.orchestration.kernel.state import State


class TestDefaults:
    def test_test_cases_defaults_none(self):
        s = State.empty()
        assert s.test_cases is None

    def test_test_design_report_defaults_none(self):
        s = State.empty()
        assert s.test_design_report is None


class TestSnapshot:
    def test_to_snapshot_includes_new_fields(self):
        snap = State.empty().to_snapshot()
        assert "test_cases" in snap
        assert "test_design_report" in snap

    def test_from_empty_old_snapshot_defaults(self):
        # An old snapshot lacking the new keys must load with defaults (R4).
        s = State.from_snapshot({"run_id": "r1"})
        assert s.run_id == "r1"
        assert s.test_cases is None
        assert s.test_design_report is None

    def test_roundtrip_preserves_new_fields(self):
        # test_cases is list[TestCase]; a round-trip must rebuild each element
        # as a TestCase (not leave it a plain dict), or verify's runner.py
        # `for inp in tc.inputs` crashes after resume.
        s = State.empty().with_updates(
            test_cases=[TestCase(name="tc1", inputs=[{"name": "x", "shape": [4]}])],
            test_design_report=Path("/tmp/design.md"),
        )
        s2 = State.from_snapshot(s.to_snapshot())
        assert s2.test_cases == [
            TestCase(name="tc1", inputs=[{"name": "x", "shape": [4]}])
        ]
        assert isinstance(s2.test_cases[0], TestCase)
        assert s2.test_design_report == Path("/tmp/design.md")
