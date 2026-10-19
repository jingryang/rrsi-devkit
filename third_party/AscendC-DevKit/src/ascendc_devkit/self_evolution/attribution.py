"""Self-evolution — AttributionEngine: rule-based failure → model component mapping.

Rule mapping (from 04-training-time-iteration.md §3):
  - compile failures    → skill/codegen prompt / resources API knowledge
  - precision failures  → kernel logic guidance / tiling knowledge
  - performance issues  → tiling strategy / performance optimisation knowledge
  - deploy/eval failures → framework stage (HIGH risk, flag for human review)

Initial version is rule-based (no LLM). LLM-based attribution will be
added in a later iteration.
"""

from __future__ import annotations

from ascendc_devkit.domain.evolution import OpEvalResult, AttributionItem


# Failure status values that OpScheduler sets on OpEvalResult.status
_STATUS_COMPILE_FAILED = "compile_failed"
_STATUS_DEPLOY_FAILED = "deploy_failed"
_STATUS_EVAL_TIMEOUT = "eval_timeout"
_STATUS_CRASHED = "crashed"


class AttributionEngine:
    """Rule-based attribution: maps per-op failure patterns to model components.

    Groups operators by failure type, deduplicates, and assigns risk-graded
    improvement targets. All methods are static — zero side effects.
    """

    @staticmethod
    def attribute(results: list[OpEvalResult]) -> list[AttributionItem]:
        """Analyse per-op results and produce deduplicated attribution items.

        Only attributes FAILED operators.  Operators that passed (status=="ok"
        AND eval_result.overall_score > 0) produce no attributions.

        Grouping: operators with the same failure type are grouped into one
        AttributionItem with op_count, rather than one per operator.
        """
        if not results:
            return []

        # Classify each failed operator
        compile_ops: list[str] = []
        precision_ops: list[str] = []
        perf_ops: list[str] = []
        deploy_ops: list[str] = []
        eval_zero_ops: list[str] = []
        unknown_ops: list[str] = []

        for r in results:
            # Passed → skip
            if r.status == "ok" and r.eval_result is not None and r.eval_result.overall_score > 0:
                continue

            # Classify by status
            if r.status == _STATUS_COMPILE_FAILED:
                compile_ops.append(r.op_name)
            elif r.status == _STATUS_DEPLOY_FAILED:
                deploy_ops.append(r.op_name)
            elif r.status in (_STATUS_EVAL_TIMEOUT, _STATUS_CRASHED):
                deploy_ops.append(r.op_name)   # infra failures → framework
            elif r.eval_result is not None and r.eval_result.overall_score == 0:
                # Eval ran but score is zero — check dimensions for hints
                if r.eval_result.compile_score == 0 and r.eval_result.function_score == 0:
                    eval_zero_ops.append(r.op_name)
                elif r.eval_result.compile_score == 0:
                    compile_ops.append(r.op_name)
                elif r.eval_result.function_score == 0:
                    # Function zero w/ non-zero compile → likely precision issue
                    precision_ops.append(r.op_name)
                elif r.eval_result.performance_score == 0:
                    perf_ops.append(r.op_name)
                else:
                    eval_zero_ops.append(r.op_name)
            else:
                unknown_ops.append(r.op_name)

        attributions: list[AttributionItem] = []

        # Compile failures → skill/codegen (low risk)
        if compile_ops:
            attributions.append(AttributionItem(
                failure_type="compile_failed",
                target_component="skill/codegen",
                severity="low",
                evidence=f"{len(compile_ops)} operator(s) failed compilation: {', '.join(compile_ops[:5])}",
                op_count=len(compile_ops),
            ))

        # Precision failures → skill/codegen (kernel logic, low risk)
        if precision_ops:
            attributions.append(AttributionItem(
                failure_type="precision_failed",
                target_component="skill/codegen",
                severity="low",
                evidence=f"{len(precision_ops)} operator(s) precision/function failure: {', '.join(precision_ops[:5])}",
                op_count=len(precision_ops),
            ))

        # Performance issues → skill/tiling (low risk)
        if perf_ops:
            attributions.append(AttributionItem(
                failure_type="perf_insufficient",
                target_component="skill/tiling",
                severity="low",
                evidence=f"{len(perf_ops)} operator(s) performance insufficient: {', '.join(perf_ops[:5])}",
                op_count=len(perf_ops),
            ))

        # Deploy/eval infrastructure failures → framework (HIGH risk)
        if deploy_ops:
            attributions.append(AttributionItem(
                failure_type="deploy_failed",
                target_component="framework/deploy",
                severity="high",
                evidence=f"{len(deploy_ops)} operator(s) deploy/eval infra failure: {', '.join(deploy_ops[:5])}",
                op_count=len(deploy_ops),
            ))

        # Eval-zero (unclear cause) → medium risk
        if eval_zero_ops:
            attributions.append(AttributionItem(
                failure_type="eval_zero",
                target_component="skill/codegen",
                severity="medium",
                evidence=f"{len(eval_zero_ops)} operator(s) eval score zero (unclear cause): {', '.join(eval_zero_ops[:5])}",
                op_count=len(eval_zero_ops),
            ))

        # Unknown failures → medium risk
        if unknown_ops:
            attributions.append(AttributionItem(
                failure_type="unknown_failure",
                target_component="framework/deploy",
                severity="medium",
                evidence=f"{len(unknown_ops)} operator(s) unknown failure: {', '.join(unknown_ops[:5])}",
                op_count=len(unknown_ops),
            ))

        return attributions
