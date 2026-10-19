"""UT for run_precision_cases L3 assembly via select_backend (step-40 / P79).

step-40 externalised test execution: ``run_precision_cases`` builds an
``EvalRequest`` and routes through ``select_backend`` (CannbenchBackend /
DevkitBackend), each calling the L6 ``NPURunner`` with its own comparer. This
guards the two assembly invariants that survived the refactor:
  1. proto truth (``op_spec.precision_thresholds``) → ``merge_thresholds`` →
     ``CompareRule`` → reaches the runner (DQ 冤杀 root-cause chain).
  2. ``cases_source`` + golden drive backend/comparer selection (cann-bench →
     CannbenchComparer; otherwise DevkitComparer) — replacing the old
     ``use_cancbench_checker`` flag + task_loader sniff.

mock ``NPURunner`` (no real NPU — §3.8 UT = pure orchestration). proto bridge
uses the real ``merge_thresholds`` (imports torch → autoload=0, memory
torch-npu-autoload-conflict). Real NPU e2e is npu ST (§3.11).
"""

from __future__ import annotations

import os

# precision_compare imports torch at top level; pure-CPU compare doesn't need the
# torch_npu device-backend autoload. Set autoload=0 so plain torch works (test-local).
os.environ.setdefault("TORCH_DEVICE_BACKEND_AUTOLOAD", "0")

from types import SimpleNamespace
from unittest.mock import patch

from ascendc_devkit.adapters.npu.precision_comparer import (
    CannbenchComparer, DevkitComparer,
)
from ascendc_devkit.domain.operator import OperatorSpec, TensorSpec
from ascendc_devkit.domain.precision import CompareRule

_EMPTY_RULE = CompareRule(dtype_thresholds={})
# run_with_npu_runner imports NPURunner here — patch target for the assembly tests.
_RUNNER_TARGET = "ascendc_devkit.adapters.npu.runner.NPURunner"


def _op(proto_thresholds=None):
    return OperatorSpec(
        name="DynamicQuant",
        precision_thresholds=proto_thresholds,
        inputs=[TensorSpec(name="x", dtype="fp16", shape=["N"])],
        outputs=[TensorSpec(name="y", dtype="int8", shape=["N"])],
    )


def _deploy():
    return SimpleNamespace(python_path="/p", install_path="/i",
                           ld_library_path_add="")


def _golden():
    return {"path": "/task/golden.py", "entry": "DynamicQuant", "input_type": "torch"}


class TestRunPrecisionCasesProtoBridge:
    """proto truth (op_spec.precision_thresholds) → CompareRule → runner."""

    def test_proto_threshold_reaches_rule(self):
        """DQ proto {int8: 1.0} → merge_thresholds → rule.dtype_thresholds['int8']==1.0."""
        op = _op({"int8": 1.0})
        with patch(_RUNNER_TARGET) as mock_cls:
            mock_cls.return_value.execute.return_value = {"passed": True, "case_details": []}
            from ascendc_devkit.orchestration.stages.precision_debug import (
                run_precision_cases,
            )
            run_precision_cases(
                op, [], 0, golden_contract=None, deploy_result=_deploy(),
                callable_target={"kind": "torch_op", "symbol": "s"},
            )
        kwargs = mock_cls.return_value.execute.call_args.kwargs
        assert kwargs["rule"].dtype_thresholds["int8"] == 1.0
        # uncovered dtype keeps the default (float32 = 2^-13, cann-bench aligned)
        assert kwargs["rule"].dtype_thresholds["float32"] == 2 ** -13

    def test_no_proto_uses_default_table(self):
        op = _op(None)
        with patch(_RUNNER_TARGET) as mock_cls:
            mock_cls.return_value.execute.return_value = {"passed": True, "case_details": []}
            from ascendc_devkit.orchestration.stages.precision_debug import (
                run_precision_cases,
            )
            run_precision_cases(
                op, [], 0, golden_contract=None, deploy_result=_deploy(),
                callable_target={"kind": "torch_op", "symbol": "s"},
            )
        rule = mock_cls.return_value.execute.call_args.kwargs["rule"]
        # default table int=0 (exact), not the old fallback int8=1.0 — single canonical table (§2.5)
        assert rule.dtype_thresholds["int8"] == 0
        assert rule.dtype_thresholds["float16"] == 2 ** -10


class TestRunPrecisionCasesBackendSelection:
    """cases_source + golden drive backend/comparer selection (step-40)."""

    def test_cannbench_source_with_golden_selects_cannbench_comparer(self):
        """cases_source='cannbench' + golden → CannbenchBackend → CannbenchComparer
        (cann-bench compare_tensors 权威路径)."""
        op = _op({"int8": 1.0})
        with patch(_RUNNER_TARGET) as mock_cls:
            mock_cls.return_value.execute.return_value = {"passed": True, "case_details": []}
            from ascendc_devkit.orchestration.stages.precision_debug import (
                run_precision_cases,
            )
            run_precision_cases(
                op, [], 0, golden_contract=_golden(), deploy_result=_deploy(),
                callable_target={"kind": "torch_op", "symbol": "s"},
                cases_source="cannbench",
            )
        comparer = mock_cls.return_value.execute.call_args.kwargs["comparer"]
        assert isinstance(comparer, CannbenchComparer)
        setup = "\n".join(comparer.harness_setup_lines(_EMPTY_RULE))
        assert "kernel_eval.utils.compare" in setup

    def test_devkit_source_selects_devkit_comparer(self):
        """cases_source='devkit' (or None) → DevkitBackend → DevkitComparer (abs-diff)."""
        op = _op({"int8": 1.0})
        with patch(_RUNNER_TARGET) as mock_cls:
            mock_cls.return_value.execute.return_value = {"passed": True, "case_details": []}
            from ascendc_devkit.orchestration.stages.precision_debug import (
                run_precision_cases,
            )
            run_precision_cases(
                op, [], 0, golden_contract=None, deploy_result=_deploy(),
                callable_target={"kind": "torch_op", "symbol": "s"},
                cases_source="devkit",
            )
        comparer = mock_cls.return_value.execute.call_args.kwargs["comparer"]
        assert isinstance(comparer, DevkitComparer)
        # DevkitComparer has zero cann-bench import (§1.7)
        assert comparer.harness_setup_lines(_EMPTY_RULE) == []

    def test_cannbench_source_without_golden_falls_back_to_devkit(self):
        """CannbenchBackend.available requires a golden; without it the selector
        falls back to DevkitBackend (honest — no cann-bench standard comparison
        without a golden baseline)."""
        op = _op({"int8": 1.0})
        with patch(_RUNNER_TARGET) as mock_cls:
            mock_cls.return_value.execute.return_value = {"passed": True, "case_details": []}
            from ascendc_devkit.orchestration.stages.precision_debug import (
                run_precision_cases,
            )
            run_precision_cases(
                op, [], 0, golden_contract=None, deploy_result=_deploy(),
                callable_target={"kind": "torch_op", "symbol": "s"},
                cases_source="cannbench",
            )
        comparer = mock_cls.return_value.execute.call_args.kwargs["comparer"]
        assert isinstance(comparer, DevkitComparer)

    def test_result_dict_passthrough_preserves_raw(self):
        """The backend returns the runner's raw result dict verbatim (via
        TestReport.extra['_raw']) so result.json stays byte-identical for
        build-failed-case-queue — the step-40 swap is transparent to P0."""
        op = _op(None)
        raw = {"passed": False, "max_diff": 0.5, "case_details": [
            {"case": "c1:8", "case_id": "c1", "diff": 0.5,
             "accuracy": {"passed": False, "max_diff": 0.5}}]}
        with patch(_RUNNER_TARGET) as mock_cls:
            mock_cls.return_value.execute.return_value = raw
            from ascendc_devkit.orchestration.stages.precision_debug import (
                run_precision_cases,
            )
            result = run_precision_cases(
                op, [], 0, golden_contract=None, deploy_result=_deploy(),
                callable_target={"kind": "torch_op", "symbol": "s"},
            )
        assert result is raw  # verbatim passthrough
