"""Self-evolution — LossAggregator: pure-function per-op → epoch loss aggregation.

Weight scheme mirrors cann-bench scoring:
  w_c = 0.2 (compilation), w_f = 0.3 (function), w_p = 0.5 (performance)
  overall_score = compile_score + function_score + performance_score [0, 100]

All methods are static — zero side effects, fully deterministic.
"""

from __future__ import annotations

from ascendc_devkit.domain.evolution import OpEvalResult, TrainingLoss


class LossAggregator:
    """Aggregate per-operator EvalResults into a single TrainingLoss.

    Operators are weighted equally (simple mean). Failed operators
    (eval_result is None or overall_score == 0) contribute 0.
    """

    @staticmethod
    def aggregate(results: list[OpEvalResult]) -> TrainingLoss:
        """Compute epoch-level TrainingLoss from per-op results.

        Args:
            results: per-operator evaluation outcomes

        Returns:
            TrainingLoss with equal-weight mean across operators
        """
        ops_with_eval = [r for r in results if r.eval_result is not None]
        total = len(results)

        if not ops_with_eval:
            return TrainingLoss(
                num_ops=total,
                num_failed=total,
            )

        # Failed operators (no eval_result) contribute 0 to every dimension.
        # Mean is across ALL operators, not just those that reached eval.
        overall = sum(r.eval_result.overall_score for r in ops_with_eval) / total
        compile_s = sum(r.eval_result.compile_score for r in ops_with_eval) / total
        function_s = sum(r.eval_result.function_score for r in ops_with_eval) / total
        perf_s = sum(r.eval_result.performance_score for r in ops_with_eval) / total
        pass_rate = sum(r.eval_result.pass_rate for r in ops_with_eval) / total
        passed = sum(1 for r in ops_with_eval if r.eval_result.overall_score > 0)
        failed = total - passed

        per_op = {
            r.op_name: r.eval_result.overall_score
            for r in ops_with_eval
        }

        return TrainingLoss(
            overall_score=overall,
            compile_score=compile_s,
            function_score=function_s,
            performance_score=perf_s,
            pass_rate_mean=pass_rate,
            num_ops=total,
            num_passed=passed,
            num_failed=failed,
            per_op=per_op,
        )
