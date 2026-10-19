"""UT — evaluation backend shared helpers (_common.py, step-40 L4).

Direct coverage of the two pure helpers shared by DevkitBackend/CannbenchBackend:
  - ``_apply_case_filter``: single-case iteration filtering (suffix-tolerant —
    previously only covered indirectly via the debug CLI).
  - ``result_dict_to_test_report``: NPURunner dict → standard TestReport back-
    translation, across BOTH the cann-bench accuracy path (covered by test_backends)
    AND the devkit bare-diff path + case-level error + output_results backfill
    (the branches test_backends does not reach — it mocks NPURunner end-to-end and
    only feeds the accuracy block).

Pure logic, no NPU (§3.8).
"""

from __future__ import annotations

from types import SimpleNamespace

from ascendc_devkit.adapters.evaluation._common import (
    _apply_case_filter, result_dict_to_test_report,
)


def _case(name, cid=None):
    return SimpleNamespace(name=name, case_id=cid or name)


class TestApplyCaseFilter:
    def test_no_filter_returns_all(self):
        cases = [_case("a"), _case("b")]
        assert _apply_case_filter(cases, None) == cases
        assert _apply_case_filter(cases, []) == cases

    def test_exact_name_match(self):
        cases = [_case("add_16"), _case("add_32")]
        assert _apply_case_filter(cases, ["add_16"]) == [cases[0]]

    def test_exact_case_id_match(self):
        cases = [_case("add_16", cid="c1"), _case("add_32", cid="c2")]
        assert _apply_case_filter(cases, ["c2"]) == [cases[1]]

    def test_suffix_match(self):
        # DebugService.run_cases matches partial suffix (e.g. "DynamicQuant_16").
        cases = [_case("DynamicQuant_16"), _case("DynamicQuant_32")]
        assert _apply_case_filter(cases, ["_16"]) == [cases[0]]

    def test_no_match_returns_empty(self):
        assert _apply_case_filter([_case("add_16")], ["nonexistent"]) == []

    def test_multiple_filters_union(self):
        cases = [_case("a"), _case("b"), _case("c")]
        assert _apply_case_filter(cases, ["a", "c"]) == [cases[0], cases[2]]


class TestResultDictDevkitBareDiffPath:
    """No accuracy block: bare diff, gated by the runner's top-level passed."""

    def test_no_accuracy_passes_when_raw_passed(self):
        r = result_dict_to_test_report({
            "passed": True,
            "case_details": [{"case": "c1:8", "case_id": "c1", "diff": 0.001}],
        })
        assert r.cases[0].status == "pass"
        assert r.cases[0].max_diff == 0.001  # diff → max_diff fallback
        assert r.all_passed is True

    def test_no_accuracy_fails_when_raw_failed(self):
        r = result_dict_to_test_report({
            "passed": False,
            "case_details": [{"case": "c1:8", "case_id": "c1", "diff": 0.9}],
        })
        assert r.cases[0].status == "fail"
        assert r.all_passed is False

    def test_case_level_error_forces_fail_even_if_raw_passed(self):
        r = result_dict_to_test_report({
            "passed": True,
            "case_details": [{"case": "c1:8", "case_id": "c1", "error": "boom"}],
        })
        assert r.cases[0].status == "fail"
        assert r.cases[0].error_msg == "boom"


class TestResultDictOutputResultsBackfill:
    """output_results[0] backfills mere/mare/threshold/mismatch when accuracy omits."""

    def test_output_results_backfills_metrics(self):
        r = result_dict_to_test_report({
            "passed": True,
            "case_details": [{"case": "c1:8", "case_id": "c1",
                              "accuracy": {"passed": True},
                              "output_results": [{"mere": 0.01, "mare": 0.02,
                                                  "threshold": 0.001,
                                                  "mismatch_count": 3}]}],
        })
        c = r.cases[0]
        assert c.mere == 0.01
        assert c.mare == 0.02
        assert c.threshold == 0.001
        assert c.mismatch_count == 3


class TestResultDictExtraAndEmpty:
    def test_empty_case_details_not_all_passed(self):
        r = result_dict_to_test_report({"passed": True, "case_details": []})
        assert r.total == 0
        assert r.all_passed is False  # empty ≠ all passed

    def test_pass_rate_computed(self):
        r = result_dict_to_test_report({
            "passed": False,
            "case_details": [
                {"case": "c1:8", "case_id": "c1", "accuracy": {"passed": True}},
                {"case": "c2:8", "case_id": "c2", "accuracy": {"passed": False}}],
        })
        assert r.total == 2 and r.passed == 1 and r.failed == 1
        assert r.pass_rate == 0.5

    def test_extra_carries_bottleneck_and_raw(self):
        raw = {"passed": True, "case_details": [], "bottleneck": "kernel",
               "golden_used": True}
        r = result_dict_to_test_report(raw)
        assert r.extra["bottleneck"] == "kernel"
        assert r.extra["golden_used"] is True
        assert r.extra["_raw"] is raw
