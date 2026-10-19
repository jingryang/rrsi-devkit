"""UT — self-evolution domain types."""

from ascendc_devkit.domain.evolution import (
    OpEvalResult, TrainingLoss, AttributionItem, ImprovementRecord, EpochSnapshot,
)
from ascendc_devkit.domain.verification import EvalResult


class TestOpEvalResult:
    def test_defaults(self):
        r = OpEvalResult()
        assert r.op_name == ""
        assert r.eval_result is None
        assert r.status == "ok"
        assert r.elapsed_ms == 0.0

    def test_immutable_with_eval(self):
        ev = EvalResult(overall_score=85.0, pass_rate=0.9)
        r = OpEvalResult(op_name="add", eval_result=ev, status="ok", elapsed_ms=123.0)
        assert r.op_name == "add"
        assert r.eval_result.overall_score == 85.0
        assert r.status == "ok"

    def test_failed_operator(self):
        r = OpEvalResult(op_name="exp", status="compile_failed", eval_result=None)
        assert r.eval_result is None
        assert r.status == "compile_failed"


class TestTrainingLoss:
    def test_defaults(self):
        loss = TrainingLoss()
        assert loss.overall_score == 0.0
        assert loss.num_ops == 0
        assert loss.per_op == {}

    def test_epoch_loss_property(self):
        loss = TrainingLoss(overall_score=31.4)
        assert loss.epoch_loss == 68.6

    def test_epoch_loss_zero_when_perfect(self):
        loss = TrainingLoss(overall_score=100.0)
        assert loss.epoch_loss == 0.0

    def test_with_per_op_scores(self):
        loss = TrainingLoss(
            overall_score=50.0, num_ops=3, num_passed=2, num_failed=1,
            per_op={"add": 85.0, "exp": 31.4, "sqrt": 33.6},
        )
        assert loss.per_op["add"] == 85.0
        assert loss.num_passed == 2


class TestAttributionItem:
    def test_defaults(self):
        a = AttributionItem()
        assert a.failure_type == ""
        assert a.severity == "low"
        assert a.op_count == 0

    def test_high_severity_deploy_failure(self):
        a = AttributionItem(
            failure_type="deploy_failed",
            target_component="framework/deploy",
            severity="high",
            evidence="2 ops deploy-failed",
            op_count=2,
        )
        assert a.severity == "high"
        assert a.target_component == "framework/deploy"
        assert a.op_count == 2


class TestImprovementRecord:
    def test_defaults(self):
        r = ImprovementRecord()
        assert r.applied is False
        assert r.action == ""

    def test_flagged_for_review(self):
        attr = AttributionItem(severity="high", target_component="framework/deploy")
        r = ImprovementRecord(attribution=attr, applied=False, action="flag_for_review")
        assert r.applied is False
        assert r.action == "flag_for_review"


class TestEpochSnapshot:
    def test_defaults(self):
        s = EpochSnapshot()
        assert s.epoch == 0
        assert s.converged is False
        assert s.op_results == []
        assert s.attributions == []

    def test_full_snapshot(self):
        loss = TrainingLoss(overall_score=60.0, num_ops=2, num_passed=1)
        results = [OpEvalResult(op_name="add")]
        attrs = [AttributionItem(failure_type="compile_failed")]
        imprs = [ImprovementRecord(action="recorded")]
        s = EpochSnapshot(epoch=3, loss=loss, op_results=results,
                          attributions=attrs, improvements=imprs, converged=False)
        assert s.epoch == 3
        assert len(s.op_results) == 1
        assert len(s.attributions) == 1
        assert len(s.improvements) == 1
        assert s.converged is False
