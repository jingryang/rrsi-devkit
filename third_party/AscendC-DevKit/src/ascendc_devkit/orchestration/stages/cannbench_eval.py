"""L3 orchestration for cann-bench scoring.

The repository-specific subprocess, environment, device handling, and report
parsing live in ``CannbenchScorer``. This stage owns the smoke gate, resolves
state inputs, and writes the one-shot LOSS signal back to state.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ascendc_devkit.adapters.evaluation.cannbench_scorer import CannbenchScorer
from ascendc_devkit.domain.contract import StageIOContract
from ascendc_devkit.domain.verification import EvalResult
from ascendc_devkit.infra.logger import Logger
from ascendc_devkit.orchestration.base import Stage
from ascendc_devkit.orchestration.kernel.action import Action
from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
from ascendc_devkit.orchestration.registry import register_stage

if TYPE_CHECKING:
    from ascendc_devkit.orchestration.kernel.state import State


@register_stage
class CannbenchEvalStage(Stage):
    """Run cann-bench evaluation and write its overall score to state."""

    name = "cannbench_eval"
    description = "cann-bench kernel_eval → overall_score (orchestrates CannbenchScorer)"
    default_max_iterations = 1
    fail_strategy = "continue"
    uninterruptible = True

    def __init__(self, scorer: CannbenchScorer | None = None):
        self._scorer = scorer or CannbenchScorer()

    def input_contract(self) -> StageIOContract:
        return StageIOContract(
            requires=["deploy_result", "generated_sources", "op_name"],
            optional=["repo_root"],
        )

    def output_contract(self) -> StageIOContract:
        return StageIOContract(provides=["eval_result"])

    def actions(self, state: State, iteration: int = 1) -> list[Action]:
        return []

    def skip_reason(self, state: State) -> str | None:
        return "deterministic stage — cann-bench kernel_eval subprocess runs in transition()"

    def transition(self, state: State, result: dict) -> State:
        op_name = state.op_name or ""
        deploy = state.deploy_result
        if deploy is None:
            Logger.warn(
                "CannbenchEvalStage: deploy_result missing (no package produced); "
                "skipping eval"
            )
            return state.with_updates(eval_result=EvalResult(overall_score=0.0))

        repo_root = self._resolve_repo_root(state)
        if not repo_root:
            Logger.error("CannbenchEvalStage: cannot resolve repo_root")
            return state.with_updates(eval_result=EvalResult(overall_score=0.0))

        source_dir = self._resolve_source_dir(state, repo_root, op_name)
        op_pascal = CannbenchScorer.snake_to_pascal(op_name)
        eval_result, reason = self._scorer.run_eval(
            source_dir, repo_root, op_pascal, op_name,
            deploy, state.npu_id,
            ws=getattr(state, "_workspace", None),
        )

        last_error = (
            ErrorFeedback(
                stage_name="cannbench_eval",
                error_type="infra",
                message=reason,
                details={"operator": op_name},
            )
            if reason
            else None
        )
        return state.with_updates(
            eval_result=eval_result,
            **({"last_error": last_error} if last_error is not None else {}),
        )

    @staticmethod
    def _resolve_repo_root(state: State) -> Path | None:
        if state.repo_root:
            return state.repo_root
        if state.op_identity and state.op_identity.repo_root:
            return state.op_identity.repo_root
        return None

    @staticmethod
    def _resolve_source_dir(state: State, repo_root: Path, op_name: str) -> Path:
        if state.op_dir:
            return state.op_dir
        if state.op_identity and state.op_identity.op_dir:
            return state.op_identity.op_dir
        return repo_root / "examples" / "aclnn_launch_example"
