"""ST — TrainingRunner epoch loop via stub OpScheduler."""

import pytest

from ascendc_devkit.domain.evolution import OpEvalResult, TrainingLoss, EpochSnapshot
from ascendc_devkit.domain.verification import EvalResult
from ascendc_devkit.self_evolution.training_state import TrainingState
from ascendc_devkit.self_evolution.training_runner import TrainingRunner
from ascendc_devkit.self_evolution.scheduling import OpScheduler


class _StubScheduler(OpScheduler):
    """Returns pre-canned per-op EvalResults — no subprocess, no NPU."""

    def __init__(self, canned_results: list[OpEvalResult]):
        super().__init__()
        self._canned = {r.op_name: r for r in canned_results}

    def eval_all(self, operators, op_dir_root=None, output_root=None,
                 slot_manager=None):
        return [self._canned.get(name, OpEvalResult(
            op_name=name, status="crashed")) for name in operators]


def _make_result(op_name: str, overall_score: float) -> OpEvalResult:
    return OpEvalResult(
        op_name=op_name, status="ok",
        eval_result=EvalResult(
            overall_score=overall_score,
            compile_score=overall_score * 0.2,
            function_score=overall_score * 0.3,
            performance_score=overall_score * 0.5,
        ),
    )


class TestTrainingRunnerSingleEpoch:
    def test_single_epoch_with_all_passing(self):
        ops = ["add", "exp", "sqrt"]
        canned = [_make_result(n, 80.0) for n in ops]
        scheduler = _StubScheduler(canned)

        ts = TrainingState(operator_list=ops, training_set_size=3, max_epochs=1)
        runner = TrainingRunner(
            operators=ops,
            training_state=ts,
            max_epochs=1,
        )
        runner._scheduler = scheduler  # inject stub

        state, snapshots = runner.run()
        assert len(snapshots) == 1
        snap = snapshots[0]
        assert snap.epoch == 1
        assert snap.loss.overall_score == 80.0
        assert snap.loss.num_ops == 3
        assert snap.loss.num_passed == 3
        assert snap.loss.num_failed == 0
        # All passing → no attributions
        assert snap.attributions == []
        assert state.current_epoch == 1

    def test_single_epoch_with_mixed_results(self):
        ops = ["add", "exp"]
        canned = [
            _make_result("add", 85.0),
            OpEvalResult(op_name="exp", status="compile_failed"),
        ]
        scheduler = _StubScheduler(canned)

        ts = TrainingState(operator_list=ops, training_set_size=2, max_epochs=1)
        runner = TrainingRunner(operators=ops, training_state=ts, max_epochs=1)
        runner._scheduler = scheduler

        state, snapshots = runner.run()
        snap = snapshots[0]
        assert snap.loss.overall_score == 42.5  # (85 + 0) / 2
        assert snap.loss.num_passed == 1
        assert snap.loss.num_failed == 1
        # Failed → attribution
        assert len(snap.attributions) == 1
        assert snap.attributions[0].failure_type == "compile_failed"
        assert snap.attributions[0].severity == "low"

    def test_baselines_captured_before_epoch_1(self):
        """Epoch 0 captures baseline scores for regression guard."""
        ops = ["add"]
        canned = [_make_result("add", 75.0)]
        scheduler = _StubScheduler(canned)

        ts = TrainingState(operator_list=ops, training_set_size=1, max_epochs=1)
        runner = TrainingRunner(operators=ops, training_state=ts, max_epochs=1)
        runner._scheduler = scheduler

        state, _ = runner.run()
        assert "add" in state.op_baselines
        assert state.op_baselines["add"] == 75.0


class TestConvergence:
    def test_convergence_on_score_threshold(self):
        ops = ["add"]
        canned = [_make_result("add", 90.0)]
        scheduler = _StubScheduler(canned)

        ts = TrainingState(
            operator_list=ops, training_set_size=1,
            max_epochs=10, convergence_threshold=80.0,
        )
        runner = TrainingRunner(
            operators=ops, training_state=ts,
            max_epochs=10, convergence_threshold=80.0,
        )
        runner._scheduler = scheduler

        state, snapshots = runner.run()
        # Should converge on first epoch since 90 >= 80
        assert len(snapshots) == 1
        assert snapshots[0].converged is True
        assert state.converged is True

    def test_no_convergence_with_single_failure(self):
        ops = ["add"]
        canned = [OpEvalResult(op_name="add", status="compile_failed")]
        scheduler = _StubScheduler(canned)

        ts = TrainingState(
            operator_list=ops, training_set_size=1,
            max_epochs=3, convergence_threshold=80.0,
        )
        runner = TrainingRunner(
            operators=ops, training_state=ts,
            max_epochs=3, convergence_threshold=80.0,
        )
        runner._scheduler = scheduler

        state, snapshots = runner.run()
        # All epochs with score 0 → no convergence after max_epochs
        assert len(snapshots) == 3
        assert all(s.converged is False for s in snapshots)
        assert state.converged is False
