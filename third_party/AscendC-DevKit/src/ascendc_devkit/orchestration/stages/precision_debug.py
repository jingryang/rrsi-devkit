"""L3 Orchestration — precision_debug capability module (P0 + step-40).

The precision_debug capability is a framework ``CompositeGroup``
(``precision_debug_tree.build_precision_debug_group``) driven by four sub-stages
(``precision_debug_substages``). This module is the **pure capability module** the
group's run_tests sub-agent reaches via the debug CLI ``run-cases``.

``run_precision_cases`` is the ① local-precheck judgement: it builds a neutral
``EvalRequest`` and routes it through ``select_backend`` (step-40). Backend
selection is driven by ``cases_source`` — the upstream ``test_design`` marker
("cannbench" | "devkit" | None): CannbenchBackend (cann-bench ``compare_tensors``
authority) is preferred when a cann-bench op ships a golden, else DevkitBackend
(abs-diff). Each backend is self-contained (own data-gen/comparison/thresholds);
the runner's raw result dict is returned verbatim (lossless ``extra["_raw"]``) so
result.json stays byte-identical for ``build-failed-case-queue``.

``DEBUG_RESULT_CONTRACT`` documents the ``PrecisionDebugResult`` shape the
sub-stage transitions materialise into State (P0 stopped writing a separate
debug_result.json file; the group transition owns the materialisation).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ascendc_devkit.domain.precision import CompareRule

if TYPE_CHECKING:
    from ascendc_devkit.orchestration.kernel.state import State


def run_precision_cases(
    op_spec, test_cases, npu_id, golden_contract,
    deploy_result, callable_target, chip_version="A2",
    log_dir=None,
    cases_source: str | None = None,
    op_dir: str | None = None,
    test_timeout_sec: float | None = None,
) -> dict:
    """Run precision cases on NPU via the selected EvaluationBackend (step-40).

    Backs the debug CLI ``run-cases`` (``DebugService.run_cases`` → here). Builds
    a neutral ``EvalRequest`` and lets ``select_backend`` pick the backend
    (CannbenchBackend when ``cases_source == "cannbench"`` + golden; else
    DevkitBackend). Each backend is self-contained; the framework never mixes
    parts (L3 §2.3).

    The return dict shape is the NPURunner result contract — unchanged because
    ``build-failed-case-queue`` consumes it. The backend's ``TestReport`` carries
    the runner's raw result dict losslessly in ``extra["_raw"]``; it is returned
    verbatim so result.json is byte-identical (P0's run_tests sub-stage reaches
    this through the CLI — the swap is transparent, 51-*.md §13.2).

    Args:
        cases_source: upstream ``test_design`` marker ("cannbench" | "devkit" |
            None). Drives ``select_backend``; None defaults to DevkitBackend.
        op_dir: operator source dir (the agent cwd; carried on ``OpRef.op_dir`` for
            backends that compile from source — the NPURunner path uses
            ``callable_target`` + ``deploy_result``).

    Raises on NPU/environment failure — callers own the policy: the debug CLI
    surfaces the failure honestly (§3.4/§3.7).
    """
    from ascendc_devkit.adapters.evaluation import select_backend
    from ascendc_devkit.domain.precision import merge_thresholds
    from ascendc_devkit.domain.evaluation import EvalRequest, OpRef, RunMode

    rule = CompareRule(dtype_thresholds=merge_thresholds(
        getattr(op_spec, "precision_thresholds", None)))
    request = EvalRequest(
        op=OpRef(callable_target=callable_target or {},
                 op_name=getattr(op_spec, "name", ""),
                 op_dir=op_dir or "",
                 chip=chip_version),
        cases=test_cases,
        rule=rule,
        deploy_result=deploy_result,
        golden_contract=golden_contract,
        mode=RunMode.SINGLE_CASE,
        cases_source=cases_source or "devkit",
        npu_id=npu_id,
        log_dir=str(log_dir) if log_dir is not None else None,
        op_spec=op_spec,
        test_timeout_sec=test_timeout_sec,
    )
    report = select_backend(request).run(request)
    # The NPURunner-based backends (Devkit/Cannbench) preserve the runner's raw
    # result dict losslessly in extra["_raw"] — return it verbatim so result.json
    # is byte-identical for build-failed-case-queue. A future non-NPURunner backend
    # (ATK/TTK — the backend abstraction's stated motivation) builds a TestReport
    # without _raw; then synthesize the legacy result-dict shape from CaseReports
    # so the result.json consumer stays fed.
    raw = report.extra.get("_raw")
    if raw is not None:
        return raw
    return _report_to_legacy_dict(report)


def _report_to_legacy_dict(report) -> dict:
    """Synthesize the NPURunner-style result dict from a TestReport (for backends
    that do not produce a compatible raw dict — future ATK/TTK)."""
    case_details = []
    for c in report.cases:
        case_details.append({
            "case": c.name,
            "case_id": c.case_id,
            "diff": c.max_diff,
            "elapsed_ms": (c.elapsed_us / 1000.0) if c.elapsed_us is not None else -1.0,
            "accuracy": {
                "passed": c.status == "pass",
                "threshold": c.threshold,
                "mere": c.mere,
                "mare": c.mare,
                "max_diff": c.max_diff,
                "error_msg": c.error_msg,
            },
        })
    return {
        "passed": report.all_passed,
        "max_diff": float(report.extra.get("max_diff", 0.0) or 0.0),
        "actual_ms": float(report.extra.get("actual_ms", 0.0) or 0.0),
        "case_details": case_details,
        "dtype_thresholds": report.extra.get("dtype_thresholds", {}),
        "bottleneck": report.extra.get("bottleneck", ""),
        "golden_used": report.extra.get("golden_used", False),
    }


# PrecisionDebugResult 契约（子 stage transition 物化到 State 时参照此形状）。暴露为
# 常量便于 sub-stage prompt + 测试引用（run_tests/diagnose/printf_locate 子 agent
# 经 checkpoint 把这些字段回传，框架 transition 物化为 PrecisionDebugResult）。
DEBUG_RESULT_CONTRACT = {
    "passed": "bool — 全部用例精度是否通过",
    "max_diff": "float — 最佳 commit 的最大 diff（轮数耗尽时为最小 max_diff）",
    "best_commit": "str — 最佳 commit sha（轮数耗尽回退目标）",
    "failing_cases": "list[str] — 仍失败的用例名",
    "iterations_used": "int — 实际迭代轮数",
    "stubbed": "bool — True 若 NPU 不可用降级 stub",
}
