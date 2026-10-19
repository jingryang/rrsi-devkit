"""UT — LossAggregator pure-function tests."""

from ascendc_devkit.domain.evolution import OpEvalResult, TrainingLoss
from ascendc_devkit.domain.verification import EvalResult
from ascendc_devkit.self_evolution.loss_aggregator import LossAggregator


class TestLossAggregator:
    def test_empty_results(self):
        loss = LossAggregator.aggregate([])
        assert loss.num_ops == 0
        assert loss.overall_score == 0.0

    def test_single_passed_operator(self):
        results = [
            OpEvalResult(
                op_name="add",
                status="ok",
                eval_result=EvalResult(
                    overall_score=85.0, compile_score=20.0,
                    function_score=30.0, performance_score=35.0,
                    pass_rate=0.9, num_cases=10, num_passed=9,
                ),
            ),
        ]
        loss = LossAggregator.aggregate(results)
        assert loss.num_ops == 1
        assert loss.num_passed == 1
        assert loss.num_failed == 0
        assert loss.overall_score == 85.0
        assert loss.compile_score == 20.0
        assert loss.function_score == 30.0
        assert loss.performance_score == 35.0
        assert loss.pass_rate_mean == 0.9
        assert loss.per_op == {"add": 85.0}

    def test_single_failed_operator(self):
        results = [
            OpEvalResult(op_name="exp", status="compile_failed", eval_result=None),
        ]
        loss = LossAggregator.aggregate(results)
        assert loss.num_ops == 1
        assert loss.num_passed == 0
        assert loss.num_failed == 1
        assert loss.overall_score == 0.0

    def test_mixed_pass_fail(self):
        results = [
            OpEvalResult(
                op_name="add", status="ok",
                eval_result=EvalResult(overall_score=80.0),
            ),
            OpEvalResult(
                op_name="exp", status="ok",
                eval_result=EvalResult(overall_score=40.0),
            ),
            OpEvalResult(
                op_name="sqrt", status="compile_failed", eval_result=None,
            ),
        ]
        loss = LossAggregator.aggregate(results)
        assert loss.num_ops == 3
        assert loss.num_passed == 2
        assert loss.num_failed == 1
        # (80 + 40 + 0) / 3 = 40.0 (failed operator contributes 0)
        assert loss.overall_score == 40.0
        assert loss.per_op == {"add": 80.0, "exp": 40.0}

    def test_all_failed(self):
        results = [
            OpEvalResult(op_name="a", status="compile_failed", eval_result=None),
            OpEvalResult(op_name="b", status="deploy_failed", eval_result=None),
        ]
        loss = LossAggregator.aggregate(results)
        assert loss.num_ops == 2
        assert loss.num_passed == 0
        assert loss.num_failed == 2
        assert loss.overall_score == 0.0
        assert loss.per_op == {}

    def test_epoch_loss_property(self):
        results = [
            OpEvalResult(
                op_name="add", status="ok",
                eval_result=EvalResult(overall_score=31.4),
            ),
        ]
        loss = LossAggregator.aggregate(results)
        assert loss.epoch_loss == 68.6
