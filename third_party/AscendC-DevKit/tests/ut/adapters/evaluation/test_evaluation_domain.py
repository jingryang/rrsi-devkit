"""UT — evaluation domain neutral formats (step-40 L4 Phase A)."""

from __future__ import annotations

from ascendc_devkit.domain.evaluation import (
    CaseReport, EvalRequest, OpRef, RunMode, TestReport,
)
from ascendc_devkit.domain.precision import CompareRule
from ascendc_devkit.domain.verification import DeployResult

# TestReport is a production dataclass whose name collides with pytest's "Test*"
# collection pattern; tell pytest not to collect it.
TestReport.__test__ = False  # type: ignore[misc]


def _op_ref():
    return OpRef(callable_target={"kind": "torch_op", "symbol": "s"},
                 op_name="gelu", op_dir="/op", chip="A2")


def _request(**overrides):
    base = dict(
        op=_op_ref(),
        cases=[],
        rule=CompareRule(dtype_thresholds={}),
        deploy_result=DeployResult(),
        golden_contract=None,
        mode=RunMode.SINGLE_CASE,
    )
    base.update(overrides)
    return EvalRequest(**base)


class TestEvalRequest:
    def test_construction(self):
        r = _request()
        assert r.op.op_name == "gelu"
        assert r.mode == RunMode.SINGLE_CASE
        assert r.cases_source is None
        assert r.case_filter is None

    def test_cases_source_field(self):
        r = _request(cases_source="cannbench")
        assert r.cases_source == "cannbench"


class TestCaseReport:
    def test_defaults(self):
        c = CaseReport(case_id="c1", name="c1", status="pass")
        assert c.max_diff == 0.0
        assert c.elapsed_us is None


class TestTestReport:
    def test_all_passed_true(self):
        r = TestReport(cases=[
            CaseReport(case_id="c1", name="c1", status="pass"),
            CaseReport(case_id="c2", name="c2", status="pass")],
            total=2, passed=2, failed=0, pass_rate=1.0)
        assert r.all_passed is True

    def test_all_passed_false_when_failed(self):
        r = TestReport(total=2, passed=1, failed=1)
        assert r.all_passed is False

    def test_all_passed_false_when_empty(self):
        r = TestReport(total=0, passed=0, failed=0)
        assert r.all_passed is False  # empty is not "all passed"

    def test_case_by_id(self):
        c = CaseReport(case_id="c2", name="c2", status="fail")
        r = TestReport(cases=[CaseReport(case_id="c1", name="c1", status="pass"), c])
        assert r.case_by_id("c2") is c
        assert r.case_by_id("nope") is None

    def test_3d_scores_optional(self):
        r = TestReport()
        assert r.overall_score is None
        assert r.compile_score is None
        assert r.function_score is None
        assert r.performance_score is None

    def test_extra_passthrough(self):
        r = TestReport(extra={"bottleneck": "real_kernel_vs_golden"})
        assert r.extra["bottleneck"] == "real_kernel_vs_golden"
