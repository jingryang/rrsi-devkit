"""UT for CannbenchEvalStage orchestration."""

from unittest import mock

from ascendc_devkit.domain.verification import DeployResult, EvalResult
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.stages.cannbench_eval import CannbenchEvalStage


def _state_with_deploy(tmp_path, smoke_passed=True):
    return State.empty().with_updates(
        op_name="exp",
        repo_root=tmp_path,
        deploy_result=DeployResult(smoke_passed=smoke_passed),
    )


class TestSmokeGate:
    def test_no_deploy_short_circuits_to_zero(self, tmp_path):
        state = State.empty().with_updates(op_name="exp", repo_root=tmp_path)
        new_state = CannbenchEvalStage().transition(state, {})
        assert new_state.eval_result.overall_score == 0.0

    def test_smoke_not_passed_still_runs_eval(self, tmp_path):
        """smoke_passed=False 不再 short-circuit — scorer 照常调用,让 kernel bug
        按 case 记分、胶水 bug 由 scorer discovery/precheck 兜(infra-0)。"""
        state = _state_with_deploy(tmp_path, smoke_passed=False)
        scorer = mock.Mock()
        scorer.run_eval.return_value = (EvalResult(overall_score=99.0), None)
        new_state = CannbenchEvalStage(scorer=scorer).transition(state, {})
        assert scorer.run_eval.call_count == 1
        assert new_state.eval_result.overall_score == 99.0


class TestScorerDelegationAndLoss:
    def test_transition_injects_last_error_on_discovery_broken(self, tmp_path):
        state = _state_with_deploy(tmp_path)
        scorer = mock.Mock()
        scorer.run_eval.return_value = (
            EvalResult(overall_score=0.0),
            "discovery broken",
        )
        new_state = CannbenchEvalStage(scorer=scorer).transition(state, {})
        assert scorer.run_eval.call_count == 1
        assert new_state.last_error is not None
        assert new_state.last_error.error_type == "infra"
        assert "discovery broken" in new_state.last_error.message
        assert new_state.eval_result.overall_score == 0.0

    def test_transition_no_last_error_on_precision_fail(self, tmp_path):
        state = _state_with_deploy(tmp_path)
        scorer = mock.Mock()
        scorer.run_eval.return_value = (
            EvalResult(overall_score=0.0, num_cases=5),
            None,
        )
        new_state = CannbenchEvalStage(scorer=scorer).transition(state, {})
        assert new_state.last_error is None
        assert new_state.eval_result.num_cases == 5

    def test_transition_emits_score_and_stops(self, tmp_path):
        state = _state_with_deploy(tmp_path)
        scorer = mock.Mock()
        scorer.run_eval.return_value = (
            EvalResult(overall_score=42.0, num_cases=10, num_passed=7),
            None,
        )
        new_state = CannbenchEvalStage(scorer=scorer).transition(state, {})
        assert new_state.eval_result.overall_score == 42.0
        assert new_state.eval_result.num_passed == 7
        assert new_state.last_error is None

    def test_transition_no_repo_root_short_circuits(self):
        state = State.empty().with_updates(
            op_name="exp",
            deploy_result=DeployResult(smoke_passed=True),
        )
        scorer = mock.Mock()
        scorer.run_eval.return_value = (EvalResult(overall_score=99.0), None)
        new_state = CannbenchEvalStage(scorer=scorer).transition(state, {})
        assert scorer.run_eval.call_count == 0
        assert new_state.eval_result.overall_score == 0.0
