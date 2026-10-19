"""UT — DevkitBackend + CannbenchBackend run/available (step-40 L4 Phase B/C).

Mocks the L6 NPURunner (the shared executor) so no real NPU is needed (§3.8 UT =
pure orchestration). Guards: each backend injects its own comparer; both return a
standardized TestReport built from the runner's result dict (with the raw dict
preserved losslessly in extra['_raw']).
"""

from __future__ import annotations

from unittest.mock import patch

from ascendc_devkit.adapters.evaluation._common import result_dict_to_test_report
from ascendc_devkit.adapters.evaluation.cannbench import CannbenchBackend
from ascendc_devkit.adapters.evaluation.devkit import DevkitBackend
from ascendc_devkit.adapters.npu.precision_comparer import (
    CannbenchComparer, DevkitComparer,
)
from ascendc_devkit.domain.evaluation import EvalRequest, OpRef, RunMode
from ascendc_devkit.domain.precision import CompareRule
from ascendc_devkit.domain.verification import DeployResult

_RUNNER_TARGET = "ascendc_devkit.adapters.npu.runner.NPURunner"


def _request(cases_source=None, golden=None):
    return EvalRequest(
        op=OpRef(callable_target={"kind": "torch_op", "symbol": "torch.ops.cann_bench.add"},
                 op_name="add", op_dir="/op", chip="A2"),
        cases=[],
        rule=CompareRule(dtype_thresholds={}),
        deploy_result=DeployResult(python_path="/p", install_path="/i"),
        golden_contract=golden,
        mode=RunMode.SINGLE_CASE,
        cases_source=cases_source,
    )


def _raw_passed():
    return {"passed": True, "max_diff": 0.001, "actual_ms": 1.2,
            "case_details": [
                {"case": "c1:8", "case_id": "c1", "diff": 0.001, "elapsed_ms": 0.5,
                 "accuracy": {"passed": True, "max_diff": 0.001, "threshold": 0.01}}],
            "bottleneck": "real_kernel_vs_golden", "golden_used": True,
            "dtype_thresholds": {"float16": 0.001}}


def _raw_failed():
    return {"passed": False, "max_diff": 0.5, "actual_ms": 1.2,
            "case_details": [
                {"case": "c1:8", "case_id": "c1", "diff": 0.5, "elapsed_ms": 0.5,
                 "accuracy": {"passed": False, "max_diff": 0.5, "error_msg": "boom"}}],
            "bottleneck": "real_kernel_vs_golden", "golden_used": True,
            "dtype_thresholds": {}}


class TestDevkitBackend:
    def test_available_always(self):
        assert DevkitBackend().available(_request()) is True

    def test_run_uses_devkit_comparer_and_returns_test_report(self):
        with patch(_RUNNER_TARGET) as mock_cls:
            mock_cls.return_value.execute.return_value = _raw_passed()
            report = DevkitBackend().run(_request())
        comparer = mock_cls.return_value.execute.call_args.kwargs["comparer"]
        assert isinstance(comparer, DevkitComparer)
        assert report.total == 1
        assert report.passed == 1
        assert report.cases[0].case_id == "c1"
        assert report.cases[0].status == "pass"
        assert report.all_passed is True
        # 3D scores None (① local precheck has no 3D breakdown)
        assert report.overall_score is None

    def test_run_failed_case_marked(self):
        with patch(_RUNNER_TARGET) as mock_cls:
            mock_cls.return_value.execute.return_value = _raw_failed()
            report = DevkitBackend().run(_request())
        assert report.failed == 1
        assert report.cases[0].status == "fail"
        assert report.cases[0].error_msg == "boom"
        assert report.all_passed is False

    def test_raw_dict_preserved_in_extra(self):
        with patch(_RUNNER_TARGET) as mock_cls:
            raw = _raw_passed()
            mock_cls.return_value.execute.return_value = raw
            report = DevkitBackend().run(_request())
        assert report.extra["_raw"] is raw  # lossless passthrough for result.json


class TestCannbenchBackend:
    def test_available_requires_cannbench_source_and_golden(self):
        b = CannbenchBackend()
        assert b.available(_request(cases_source="cannbench",
                                    golden={"path": "/g", "entry": "op", "input_type": "torch"})) is True

    def test_available_false_without_golden(self):
        assert CannbenchBackend().available(_request(cases_source="cannbench", golden=None)) is False

    def test_available_false_for_devkit_source(self):
        assert CannbenchBackend().available(
            _request(cases_source="devkit", golden={"path": "/g"})) is False

    def test_run_uses_cannbench_comparer(self):
        with patch(_RUNNER_TARGET) as mock_cls:
            mock_cls.return_value.execute.return_value = _raw_passed()
            report = CannbenchBackend().run(
                _request(cases_source="cannbench",
                         golden={"path": "/g", "entry": "op", "input_type": "torch"}))
        comparer = mock_cls.return_value.execute.call_args.kwargs["comparer"]
        assert isinstance(comparer, CannbenchComparer)
        assert report.total == 1


class TestResultDictConversion:
    """result_dict_to_test_report: runner dict → TestReport mapping (shared by both
    backends; ATK/TTK without a raw dict would synthesize via run_precision_cases)."""

    def test_pass_rate(self):
        r = result_dict_to_test_report(_raw_passed())
        assert r.pass_rate == 1.0

    def test_extra_carries_bottleneck_and_golden_used(self):
        r = result_dict_to_test_report(_raw_passed())
        assert r.extra["bottleneck"] == "real_kernel_vs_golden"
        assert r.extra["golden_used"] is True

    def test_elapsed_us_from_elapsed_ms(self):
        r = result_dict_to_test_report(_raw_passed())
        assert r.cases[0].elapsed_us == 500.0  # 0.5 ms → 500 us
