"""§per-output sinking — fix verification granularity from case → output.

TDD covers (diagnose 实施模式，docs/plan/fix-diagnose-merge):
- DiagnoseSubstage.transition: partial_outputs in agent _summary → updates per-output
  diffs/status + sets dc["partial_output"] without marking resolved_pending
- DiagnoseSubstage.resolve_condition: partial_output flag → "partial_output" routing
- transition_table: diagnose.partial_output → ("run_tests", "corrective")
- build-failed-case-queue _extract_outputs: multi-output → list, single → None
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ascendc_devkit.domain.operator import OperatorSpec, OperatorIdentity
from ascendc_devkit.domain.requirement import Requirement
from ascendc_devkit.domain.verification import DeployResult
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.stages.precision_debug_substages import (
    DiagnoseSubstage,
    _PHASE_DEFAULTS,
    _phase_path,
)
from ascendc_devkit.orchestration.precision_debug_tree import (
    _PRECISION_DEBUG_TRANSITION_TABLE,
)


# —— helpers (self-contained, mirror test_precision_debug_stage.py) ————

def _op_identity(tmp_path: Path) -> OperatorIdentity:
    return OperatorIdentity(
        spec=OperatorSpec(name="gelu"),
        repo_root=tmp_path,
        op_dir=tmp_path / "custom_ops" / "gelu",
    )


def _state(tmp_path: Path, **overrides) -> State:
    defaults = dict(
        mode="new",
        op_identity=_op_identity(tmp_path),
        requirement=Requirement(op_spec=OperatorSpec(name="gelu")),
        golden_path=Path("/tmp/golden.py"),
        golden_entry="golden",
        golden_input_type="float32",
        deploy_result=DeployResult(smoke_passed=True),
        codegen_manifest={"callable_target": {
            "kind": "torch_op", "symbol": "torch.ops.custom.gelu"}},
        design_target_chip="A2",
    )
    defaults.update(overrides)
    return State(**defaults)


def _ctrl_path(state: State) -> Path:
    op_dir = state.op_dir or (state.op_identity.op_dir if state.op_identity else None)
    p = Path(op_dir) / ".precision-fix" / "control.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _write_control(state: State, cp: dict) -> None:
    _ctrl_path(state).write_text(json.dumps(cp), encoding="utf-8")


def _read_control(state: State) -> dict:
    return json.loads(_ctrl_path(state).read_text(encoding="utf-8"))


def _control(**overrides) -> dict:
    defaults = {
        "status": "running",
        "max_iterations": 30,
        "current_case_index": 0,
        "best_commit": "init",
        "best_failed_count": None,
        "best_crashed_count": None,
        "best_real_max_err": None,
        "failed_case_queue": [],
        "history": [],
        "phase_counter": 0,
        "run_iter_counter": 0,
    }
    defaults.update(overrides)
    return defaults


def _case(overrides=None):
    c = {"case_id": "c1", "shape": "[8]", "dtype": "fp16",
         "failure_type": "precision", "status": "pending", "max_err": 1.0,
         "attempt_count": 0, "max_attempts_per_case": 10,
         "tried_fix_plan_ids": []}
    if overrides:
        c.update(overrides)
    return c


def _seed_phase(state: State, filename: str, summary: dict | None = None) -> Path:
    payload = dict(_PHASE_DEFAULTS.get(filename, {"any": "payload"}))
    if summary is not None:
        payload["_summary"] = summary
    p = _phase_path(state, filename, round_suffix=True)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


# —— DiagnoseSubstage.transition: partial output ——————————————————————————

class TestPartialOutputTransition:
    def test_partial_outputs_updates_case_diffs(self, tmp_path):
        """Fix agent wrote partial_outputs in _summary → framework updates
        per-output diffs/status, sets dc["partial_output"]=True, and does
        NOT mark resolved_pending."""
        state = _state(tmp_path)
        case = _case({
            "case_id": "c1", "failure_type": "precision",
            "outputs": [
                {"index": 0, "diff": 100.0, "status": "failing"},
                {"index": 1, "diff": 200.0, "status": "failing"},
            ],
        })
        _write_control(state, _control(
            failed_case_queue=[case],
        ))
        # Seed phase JSON: agent wrote partial_outputs evidence into _summary
        fix = DiagnoseSubstage()
        _seed_phase(state, fix._phase_filename(), summary={
            "plan_id": "h1",
            "grade": "B",
            "verification_result": "partial_output",
            "fix_applied": True,
            "partial_outputs": [
                {"index": 0, "diff_before": 100.0, "diff_after": 0.5},
            ],
        })
        out = fix.transition(state, {})
        cp = _read_control(state)
        case_after = cp["failed_case_queue"][0]
        # output[0] diff updated, status → improved
        assert case_after["outputs"][0]["diff"] == 0.5
        assert case_after["outputs"][0]["status"] == "improved"
        # output[1] unchanged
        assert case_after["outputs"][1]["diff"] == 200.0
        assert case_after["outputs"][1]["status"] == "failing"
        # dc flag set
        assert out._debug_checkpoint["partial_output"] is True
        # case NOT marked resolved_pending (partial, not full success)
        assert case_after["status"] == "pending"

    def test_no_partial_outputs_no_flag(self, tmp_path):
        """Without partial_outputs in summary, dc["partial_output"] is absent."""
        state = _state(tmp_path)
        _write_control(state, _control(
            failed_case_queue=[_case()],
        ))
        fix = DiagnoseSubstage()
        _seed_phase(state, fix._phase_filename(), summary={
            "plan_id": "h1",
            "grade": "B",
            "verification_result": "refuted",
            "fix_applied": False,
        })
        out = fix.transition(state, {})
        assert "partial_output" not in (out._debug_checkpoint or {})

    def test_partial_output_ignored_without_case_outputs(self, tmp_path):
        """partial_outputs with symptom-based improvement — dc flag set even
        for single-output cases (no outputs field)."""
        state = _state(tmp_path)
        _write_control(state, _control(
            failed_case_queue=[_case()],
        ))
        fix = DiagnoseSubstage()
        _seed_phase(state, fix._phase_filename(), summary={
            "partial_outputs": [{"index": 0, "diff_before": 100, "diff_after": 1,
                                 "symptom_before": "runtime", "symptom_after": "precision"}],
        })
        out = fix.transition(state, {})
        # §improvement: symptom-based partial acknowledged even without
        # case.outputs — the agent's evidence is the signal.
        assert out._debug_checkpoint["partial_output"] is True


# —— DiagnoseSubstage.resolve_condition: partial_output routing ————————————

class TestPartialOutputRouting:
    def test_resolve_condition_returns_partial_output(self, tmp_path):
        state = _state(tmp_path)
        case = _case({"outputs": [
            {"index": 0, "diff": 100.0, "status": "failing"},
        ]})
        _write_control(state, _control(
            failed_case_queue=[case],
        ))
        fix = DiagnoseSubstage()
        _seed_phase(state, fix._phase_filename(), summary={
            "partial_outputs": [{"index": 0, "diff_before": 100, "diff_after": 1}],
        })
        out = fix.transition(state, {})
        assert fix.resolve_condition(out) == "partial_output"

    def test_partial_output_priority(self, tmp_path):
        """partial_output takes priority over pool_exhausted / need_printf."""
        state = _state(tmp_path)
        case = _case({"outputs": [
            {"index": 0, "diff": 100.0, "status": "failing"},
        ]})
        _write_control(state, _control(
            failed_case_queue=[case],
        ))
        fix = DiagnoseSubstage()
        _seed_phase(state, fix._phase_filename(), summary={
            "partial_outputs": [{"index": 0, "diff_before": 100, "diff_after": 1}],
        })
        out = fix.transition(state, {})
        assert fix.resolve_condition(out) == "partial_output"


# —— transition_table ————————————————————————————————————————————————

class TestTransitionTablePartialOutput:
    def test_diagnose_partial_output_routes_to_run_tests(self):
        target, label = _PRECISION_DEBUG_TRANSITION_TABLE["diagnose"]["partial_output"]
        assert target == "run_tests"
        assert label == "corrective"


# —— build-failed-case-queue: _extract_outputs ————————————————————————

class TestExtractOutputs:
    """Tests for _extract_outputs in build-failed-case-queue.py."""

    @staticmethod
    def _load_script():
        import importlib.util
        import sys
        path = Path(__file__).parents[3] / "src" / "ascendc_devkit" / \
               "orchestration" / "stages" / "precision_debug_run_tests" / \
               "scripts" / "build-failed-case-queue.py"
        spec = importlib.util.spec_from_file_location("bfcq", str(path))
        mod = importlib.util.module_from_spec(spec)
        sys.modules["bfcq"] = mod
        spec.loader.exec_module(mod)
        return mod

    def test_multi_output_extracts_list(self):
        mod = self._load_script()
        cd = {"output_results": [
            {"index": 0, "diff": 25.0, "passed": False},
            {"index": 1, "diff": 1296.0, "passed": False},
        ]}
        outs = mod._extract_outputs(cd)
        assert isinstance(outs, list)
        assert len(outs) == 2
        assert outs[0] == {"index": 0, "diff": 25.0, "passed": False, "status": "failing"}
        assert outs[1] == {"index": 1, "diff": 1296.0, "passed": False, "status": "failing"}

    def test_passed_output_marks_passing(self):
        mod = self._load_script()
        cd = {"output_results": [
            {"index": 0, "diff": 0.0, "passed": True},
            {"index": 1, "diff": 999.0, "passed": False},
        ]}
        outs = mod._extract_outputs(cd)
        assert len(outs) == 2
        assert outs[0]["status"] == "passing"
        assert outs[0]["passed"] is True
        assert outs[1]["status"] == "failing"

    def test_single_output_returns_none(self):
        mod = self._load_script()
        cd = {"output_results": [{"index": 0, "diff": 5.0}]}
        assert mod._extract_outputs(cd) is None

    def test_no_output_results_returns_none(self):
        mod = self._load_script()
        assert mod._extract_outputs({}) is None

    def test_outputs_without_diff_handled(self):
        mod = self._load_script()
        cd = {"output_results": [
            {"index": 0, "diff": 10.0, "passed": False},
            {"index": 1},  # no diff field, no passed field
        ]}
        outs = mod._extract_outputs(cd)
        assert len(outs) == 2
        assert outs[0]["diff"] == 10.0
        assert outs[0]["passed"] is False
        assert outs[1]["diff"] is None
        assert outs[1]["passed"] is False  # default when absent


# —— merge_with_existing: per-output preserve ————————————————

class TestMergePerOutput:
    @staticmethod
    def _load_script():
        import importlib.util
        import sys
        # §judgment-ownership (N1): 脚本迁入框架包 src/.../precision_debug_run_tests/scripts/
        path = Path(__file__).parents[3] / "src" / "ascendc_devkit" / \
               "orchestration" / "stages" / "precision_debug_run_tests" / \
               "scripts" / "build-failed-case-queue.py"
        spec = importlib.util.spec_from_file_location("bfcq2", str(path))
        mod = importlib.util.module_from_spec(spec)
        sys.modules["bfcq2"] = mod
        spec.loader.exec_module(mod)
        return mod

    def test_preserves_per_output_status(self):
        mod = self._load_script()
        old = [{
            "case_id": "c1", "shape": "[8]", "dtype": "fp16",
            "failure_type": "precision", "status": "pending",
            "max_err": 100.0,
            "outputs": [
                {"index": 0, "diff": 5.0, "status": "improved"},
                {"index": 1, "diff": 100.0, "status": "failing"},
            ],
        }]
        new = [{
            "case_id": "c1", "shape": "[8]", "dtype": "fp16",
            "max_err": 80.0,  # fresh measurement: output[1] diff dropped
            "outputs": [
                {"index": 0, "diff": 0.01, "status": "failing"},  # new measurement
                {"index": 1, "diff": 80.0,  "status": "failing"},  # new measurement
            ],
        }]
        merged = mod.merge_with_existing(new, old)
        assert len(merged) == 1
        m = merged[0]
        # New diffs win (fresh measurement)
        assert m["outputs"][0]["diff"] == 0.01
        assert m["outputs"][1]["diff"] == 80.0
        # Old status preserved (improved was set by fix framework)
        assert m["outputs"][0]["status"] == "improved"
        assert m["outputs"][1]["status"] == "failing"
        # diff_before recorded from old diff
        assert m["outputs"][0]["diff_before"] == 5.0
        assert m["outputs"][1]["diff_before"] == 100.0

    def test_no_old_outputs_no_crash(self):
        mod = self._load_script()
        old = [{"case_id": "c1", "shape": "[8]", "dtype": "fp16"}]
        new = [{
            "case_id": "c1", "shape": "[8]", "dtype": "fp16",
            "outputs": [{"index": 0, "diff": 10.0, "status": "failing"}],
        }]
        merged = mod.merge_with_existing(new, old)
        assert len(merged) == 1
        # Old has no outputs → new outputs kept as-is
        assert merged[0]["outputs"][0]["status"] == "failing"
