"""L6 Adapters — evaluation backend shared helpers (step-40 internal, not protocol).

Both concrete backends (``DevkitBackend`` / ``CannbenchBackend``) execute via the
same L6 ``NPURunner`` (the single NPU executor, §2.5) and differ only in the
``PrecisionComparer`` they inject (the rule × backend orthogonality, P79). This
module owns the shared back-translation: NPURunner result dict → standard
``TestReport`` / ``CaseReport``, plus the runner invocation. Keeping it out of the
public ``EvaluationBackend`` protocol avoids duplicating the conversion in each
backend while preserving their self-contained ``run()`` shape.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ascendc_devkit.domain.evaluation import CaseReport, EvalRequest, TestReport


def _apply_case_filter(cases, case_filter):
    """Honour EvalRequest.case_filter (single-case iteration): keep only cases whose
    name/case_id matches one of the wanted tokens (suffix-tolerant, mirrors
    ``DebugService.run_cases``). Direct-backend entry points set case_filter; the
    CLI path (debug_service) pre-filters instead — both are valid callers of the
    neutral request."""
    if not case_filter:
        return list(cases)
    wanted = set(case_filter)

    def _matches(tc):
        name = getattr(tc, "name", "")
        cid = getattr(tc, "case_id", "")
        if name in wanted or cid in wanted:
            return True
        return any(name.endswith(w) or cid.endswith(w) for w in wanted)

    return [tc for tc in cases if _matches(tc)]


def result_dict_to_test_report(raw: dict) -> "TestReport":
    """NPURunner.execute result dict → standard TestReport.

    The runner emits per-case ``case_details`` with an ``accuracy`` block (cann-bench
    path: passed/threshold/mere/mare/max_diff) or bare diff (devkit abs-diff path).
    Either way we map to ``CaseReport``. 3D scores stay ``None`` — the ① local
    precheck has no compile/function/performance breakdown (that's ②'s job).
    Backend-specific fields (bottleneck, golden_used, raw max_diff) ride ``extra``.
    """
    from ascendc_devkit.domain.evaluation import CaseReport, TestReport

    case_details = raw.get("case_details", []) or []
    reports: list[CaseReport] = []
    for cd in case_details:
        acc = cd.get("accuracy") or {}
        outputs = cd.get("output_results") or cd.get("outputs") or []
        # cann-bench path carries per-output `passed`; devkit path uses diff≤threshold.
        # Status: pass only when accuracy.passed is explicitly True; an error or a
        # non-passing diff → fail. (An absent accuracy block with diff≥0 still judged
        # by the runner's top-level `passed`.)
        status = "pass" if acc.get("passed") is True else (
            "fail" if (cd.get("error") or acc.get("error_msg")) else
            ("pass" if raw.get("passed") else "fail"))
        mismatch = 0
        mere = float(acc.get("mere") or 0.0)
        mare = float(acc.get("mare") or 0.0)
        threshold = float(acc.get("threshold") or 0.0)
        if outputs:
            o0 = outputs[0] or {}
            mismatch = int(o0.get("mismatch_count", 0) or 0)
            if not mere:
                mere = float(o0.get("mere") or 0.0)
            if not mare:
                mare = float(o0.get("mare") or 0.0)
            if not threshold:
                threshold = float(o0.get("threshold") or 0.0)
        elapsed_ms = cd.get("elapsed_ms")
        reports.append(CaseReport(
            case_id=str(cd.get("case_id", "") or cd.get("case", "")),
            name=str(cd.get("case", "")),
            status=status,
            max_diff=float(acc.get("max_diff", cd.get("diff", 0.0)) or 0.0),
            mere=mere,
            mare=mare,
            mismatch_count=mismatch,
            threshold=threshold,
            elapsed_us=float(elapsed_ms) * 1000.0 if elapsed_ms is not None else None,
            error_msg=str(cd.get("error") or acc.get("error_msg") or ""),
        ))
    total = len(reports)
    passed = sum(1 for r in reports if r.status == "pass")
    failed = total - passed
    return TestReport(
        cases=reports,
        total=total,
        passed=passed,
        failed=failed,
        pass_rate=(passed / total) if total else 0.0,
        # ① local precheck produces no 3D scores (None) — see module docstring.
        overall_score=None,
        compile_score=None,
        function_score=None,
        performance_score=None,
        extra={
            "bottleneck": raw.get("bottleneck", ""),
            "golden_used": raw.get("golden_used", False),
            "max_diff": float(raw.get("max_diff", 0.0) or 0.0),
            "actual_ms": float(raw.get("actual_ms", 0.0) or 0.0),
            "passed": bool(raw.get("passed", False)),
            "dtype_thresholds": raw.get("dtype_thresholds", {}),
            "raw_error": raw.get("error", ""),
            # Lossless passthrough of the runner's full result dict. The current
            # result.json consumer (build-failed-case-queue) reads the raw
            # case_details/accuracy structure; run_precision_cases returns this
            # verbatim so result.json is byte-identical. A future non-NPURunner
            # backend (ATK/TTK) leaves _raw absent → run_precision_cases synthesizes
            # the legacy dict from CaseReports (_report_to_legacy_dict).
            "_raw": raw,
        },
    )


def run_with_npu_runner(request: "EvalRequest", comparer) -> "TestReport":
    """Shared execution: build the operator spec, run NPURunner.execute with the
    backend's comparer, back-translate to TestReport.

    NPURunner is the single L6 NPU executor; both backends reuse it (§2.5). The
    comparer is the only backend-specific knob (P79 rule × backend). The rule comes
    straight from ``EvalRequest.rule`` (proto truth, single source).
    """
    from ascendc_devkit.adapters.npu.runner import NPURunner
    from ascendc_devkit.domain.operator import OperatorSpec

    # M2 §2.2: use the full op_spec when available so the runner's attrs
    # validation has type declarations to check against. Fall back to a
    # bare OperatorSpec (name only) when op_spec is absent (legacy / devkit
    # path without op_spec wiring).
    operator = request.op_spec or OperatorSpec(name=request.op.op_name)
    cases = _apply_case_filter(request.cases, request.case_filter)
    runner = NPURunner(chip_version=request.op.chip or None)
    raw = runner.execute(
        operator, cases, request.npu_id,
        golden_contract=request.golden_contract,
        deploy_result=request.deploy_result,
        callable_target=request.op.callable_target,
        rule=request.rule, comparer=comparer,
        log_dir=request.log_dir,
        # 测试 harness 看门狗超时：EvalRequest 承载（config 默认 / control.json 放大值），
        # None → runner 默认 120。大 shape 用例的放大超时沿此透传。
        timeout_sec=request.test_timeout_sec or 120,
    )
    return result_dict_to_test_report(raw)
