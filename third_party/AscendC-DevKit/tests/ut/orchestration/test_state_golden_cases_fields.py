"""B1 (14 L4) — State golden/cases scalar fields (golden_entry /
golden_input_type / cases_path) + snapshot back-compat.

golden source moved from profile-preset (P11) to explicit CLI (13 E1/E3):
the three scalars replace the profile-substituted contract object so
verify's golden contract is read straight from State."""

from pathlib import Path

from ascendc_devkit.orchestration.kernel.state import State


class TestDefaults:
    def test_golden_entry_defaults_empty(self):
        assert State.empty().golden_entry == ""

    def test_golden_input_type_defaults_empty(self):
        assert State.empty().golden_input_type == ""

    def test_golden_precision_defaults_empty(self):
        # 空 = 未指定 → 契约构建处落默认 fp64_cpu（对齐 cann-bench eval）。
        assert State.empty().golden_precision == ""

    def test_cases_path_defaults_none(self):
        assert State.empty().cases_path is None


class TestSnapshot:
    def test_to_snapshot_includes_new_fields(self):
        snap = State.empty().to_snapshot()
        assert "golden_entry" in snap
        assert "golden_input_type" in snap
        assert "golden_precision" in snap
        assert "cases_path" in snap

    def test_from_empty_old_snapshot_defaults(self):
        # An old snapshot lacking the new keys must load with defaults.
        s = State.from_snapshot({"run_id": "r1"})
        assert s.run_id == "r1"
        assert s.golden_entry == ""
        assert s.golden_input_type == ""
        assert s.golden_precision == ""
        assert s.cases_path is None

    def test_roundtrip_preserves_new_fields(self):
        s = State.empty().with_updates(
            golden_entry="exp",
            golden_input_type="torch",
            golden_precision="native_cpu",
            cases_path=Path("/abs/cann-bench/tasks/level1/exp/cases.csv"),
        )
        s2 = State.from_snapshot(s.to_snapshot())
        assert s2.golden_entry == "exp"
        assert s2.golden_input_type == "torch"
        assert s2.golden_precision == "native_cpu"
        assert s2.cases_path == Path("/abs/cann-bench/tasks/level1/exp/cases.csv")
