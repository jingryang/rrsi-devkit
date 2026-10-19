"""UT — TrainingState immutability + convergence + regression guard."""

from ascendc_devkit.domain.evolution import (
    OpEvalResult, TrainingLoss, EpochSnapshot, AttributionItem, ImprovementRecord,
)
from ascendc_devkit.domain.verification import EvalResult
from ascendc_devkit.self_evolution.training_state import TrainingState


class TestTrainingStateImmutability:
    def test_default_construction(self):
        ts = TrainingState()
        assert ts.current_epoch == 0
        assert ts.converged is False
        assert ts.operator_list == []
        assert ts.loss_history == []

    def test_with_updates_returns_new_instance(self):
        ts = TrainingState()
        ts2 = ts.with_updates(current_epoch=5)
        assert ts.current_epoch == 0
        assert ts2.current_epoch == 5
        assert ts is not ts2

    def test_record_epoch_updates_loss_history(self):
        ts = TrainingState(max_epochs=10)
        snapshot = EpochSnapshot(
            epoch=1,
            loss=TrainingLoss(overall_score=50.0, num_ops=3, num_passed=2),
        )
        ts2 = ts.record_epoch(snapshot)
        assert ts2.current_epoch == 1
        assert len(ts2.loss_history) == 1
        assert ts2.loss_history[0]["overall_score"] == 50.0

    def test_record_epoch_tracks_best(self):
        ts = TrainingState()
        snap1 = EpochSnapshot(epoch=1, loss=TrainingLoss(overall_score=30.0))
        ts = ts.record_epoch(snap1)
        assert ts.best_overall_score == 30.0
        assert ts.best_epoch == 1

        snap2 = EpochSnapshot(epoch=2, loss=TrainingLoss(overall_score=50.0))
        ts = ts.record_epoch(snap2)
        assert ts.best_overall_score == 50.0
        assert ts.best_epoch == 2

        # Worse epoch doesn't replace best
        snap3 = EpochSnapshot(epoch=3, loss=TrainingLoss(overall_score=40.0))
        ts = ts.record_epoch(snap3)
        assert ts.best_overall_score == 50.0
        assert ts.best_epoch == 2

    def test_attribution_history_accumulates(self):
        ts = TrainingState()
        attr = AttributionItem(failure_type="compile_failed", op_count=2)
        snap = EpochSnapshot(epoch=1, loss=TrainingLoss(), attributions=[attr])
        ts = ts.record_epoch(snap)
        assert len(ts.attribution_history) == 1
        assert ts.attribution_history[0]["epoch"] == 1

    def test_review_queue_high_risk_only(self):
        ts = TrainingState()
        low = AttributionItem(failure_type="compile_failed", severity="low")
        high = AttributionItem(failure_type="deploy_failed", severity="high")
        snap = EpochSnapshot(epoch=1, loss=TrainingLoss(), attributions=[low, high])
        ts = ts.record_epoch(snap)
        assert len(ts.review_queue) == 1
        assert ts.review_queue[0]["severity"] == "high"


class TestConvergence:
    def test_converges_on_threshold(self):
        ts = TrainingState(convergence_threshold=80.0)
        snap = EpochSnapshot(epoch=1, loss=TrainingLoss(overall_score=85.0))
        ts = ts.record_epoch(snap)
        assert ts.converged is True

    def test_not_converged_below_threshold(self):
        ts = TrainingState(convergence_threshold=80.0)
        snap = EpochSnapshot(epoch=1, loss=TrainingLoss(overall_score=70.0))
        ts = ts.record_epoch(snap)
        assert ts.converged is False

    def test_converges_on_patience(self):
        ts = TrainingState(convergence_patience=3)
        # 4 epochs without improvement
        for e in range(1, 5):
            snap = EpochSnapshot(epoch=e, loss=TrainingLoss(overall_score=50.0))
            ts = ts.record_epoch(snap)
        assert ts.converged is True
        assert ts.epochs_without_improvement >= 3

    def test_improvement_resets_patience_counter(self):
        ts = TrainingState(convergence_patience=3)
        snap1 = EpochSnapshot(epoch=1, loss=TrainingLoss(overall_score=50.0))
        ts = ts.record_epoch(snap1)
        assert ts.epochs_without_improvement == 0

        snap2 = EpochSnapshot(epoch=2, loss=TrainingLoss(overall_score=60.0))
        ts = ts.record_epoch(snap2)
        # Improvement → counter should reset or stay 0
        assert ts.epochs_without_improvement == 0


class TestRegressionGuard:
    def test_no_baseline_no_regression(self):
        ts = TrainingState()
        results = [OpEvalResult(op_name="add", eval_result=EvalResult(overall_score=10.0))]
        assert ts.check_regression(results) == []

    def test_regression_detected(self):
        ts = TrainingState(op_baselines={"add": 80.0})
        # Score dropped from 80 → 10 (< 80*0.5=40) → regression
        results = [OpEvalResult(op_name="add", eval_result=EvalResult(overall_score=10.0))]
        regressed = ts.check_regression(results)
        assert "add" in regressed

    def test_no_regression_when_above_half_baseline(self):
        ts = TrainingState(op_baselines={"add": 80.0})
        # Score 50.0 > 80*0.5=40 → no regression
        results = [OpEvalResult(op_name="add", eval_result=EvalResult(overall_score=50.0))]
        assert ts.check_regression(results) == []

    def test_record_baselines(self):
        ts = TrainingState()
        results = [
            OpEvalResult(op_name="add", eval_result=EvalResult(overall_score=80.0)),
            OpEvalResult(op_name="exp", eval_result=EvalResult(overall_score=31.4)),
            OpEvalResult(op_name="sqrt", eval_result=None),    # failed → skipped
        ]
        ts = ts.record_baselines(results)
        assert ts.op_baselines == {"add": 80.0, "exp": 31.4}
        # sqrt not included (no eval_result)


class TestSerialization:
    def test_to_from_snapshot_roundtrip(self):
        ts = TrainingState(
            training_run_id="run-001",
            operator_list=["add", "exp"],
            training_set_size=2,
            current_epoch=3,
            loss_history=[{"epoch": 1, "overall_score": 50.0}],
            op_baselines={"add": 80.0},
            best_epoch=2,
            best_overall_score=60.0,
        )
        data = ts.to_snapshot()
        restored = TrainingState.from_snapshot(data)
        assert restored.training_run_id == "run-001"
        assert restored.operator_list == ["add", "exp"]
        assert restored.current_epoch == 3
        assert restored.loss_history == [{"epoch": 1, "overall_score": 50.0}]
        assert restored.op_baselines == {"add": 80.0}
        assert restored.best_epoch == 2

    def test_from_snapshot_fills_missing_defaults(self):
        restored = TrainingState.from_snapshot({})
        assert restored.current_epoch == 0
        assert restored.operator_list == []
        assert restored.loss_history == []
        assert restored.converged is False
