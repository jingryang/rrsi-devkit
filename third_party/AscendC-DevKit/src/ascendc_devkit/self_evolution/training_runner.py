"""Self-evolution — TrainingRunner: outer epoch loop for multi-operator training.

Two-layer architecture (05-multi-op-scheduler.md §1):
  - Upper: TrainingRunner — multi-operator scheduling, epoch loop, loss aggregation
  - Lower: SelfEvolveOpWorkflow — per-operator codegen→deploy→eval (subprocess)

TrainingRunner is NOT a Stage or Workflow. It is a standalone runner at the
scheduler level, analogous to application/dispatcher.py for single-operator runs.

Core loop (04-training-time-iteration.md §1):
  for epoch:
    1. OpScheduler.eval_all(operators)  → per-op EvalResults (subprocess)
    2. LossAggregator.aggregate(results) → TrainingLoss
    3. Convergence check
    4. AttributionEngine.attribute(results) → improvement targets
    5. Apply low-risk improvements, flag high-risk for review
    6. Re-eval next epoch with updated model
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from ascendc_devkit.domain.evolution import (
    OpEvalResult, TrainingLoss, EpochSnapshot,
    AttributionItem, ImprovementRecord,
)
from ascendc_devkit.self_evolution.training_state import TrainingState
from ascendc_devkit.self_evolution.loss_aggregator import LossAggregator
from ascendc_devkit.self_evolution.attribution import AttributionEngine
from ascendc_devkit.self_evolution.scheduling import OpScheduler
from ascendc_devkit.infra.logger import Logger


class TrainingRunner:
    """Outer training loop for self-evolution.

    Parameters:
        operators: operator names (snake_case) in the training set
        training_state: initial TrainingState (pre-seeded or fresh)
        op_dir_root: root directory containing per-op dirs
        output_root: root directory for per-op subprocess outputs
        slot_manager: NPUSlotManager for device allocation (None = no NPU)
        max_concurrent_ops: max simultaneous operator evals
        max_epochs: hard epoch cap
        convergence_threshold: stop when overall_score >= this
        convergence_patience: stop after N epochs without improvement
        progress_callback: optional (event_type, metadata) → None
    """

    def __init__(
        self,
        operators: list[str],
        training_state: TrainingState,
        op_dir_root: Path | None = None,
        output_root: str = "output",
        slot_manager: "NPUSlotManager | None" = None,   # noqa: F821
        max_concurrent_ops: int = 2,
        max_epochs: int = 20,
        convergence_threshold: float = 0.0,
        convergence_patience: int = 3,
        progress_callback: Callable | None = None,
    ):
        self._operator_list = list(operators)
        self._state = training_state.with_updates(
            operator_list=list(operators),
            training_set_size=len(operators),
            max_epochs=max_epochs,
            convergence_threshold=convergence_threshold,
            convergence_patience=convergence_patience,
        )
        self._op_dir_root = op_dir_root
        self._output_root = output_root
        self._slot_manager = slot_manager
        self._progress_callback = progress_callback

        self._scheduler = OpScheduler(max_concurrent=max_concurrent_ops)
        self._snapshots: list[EpochSnapshot] = []
        self._loss_history: list[TrainingLoss] = []

    # —— Public API ——

    def run(self) -> tuple[TrainingState, list[EpochSnapshot]]:
        """Run the full training loop.

        Returns:
            (final TrainingState, list of per-epoch snapshots)
        """
        Logger.stage_header("TrainingRunner", self._state.max_epochs, 1)

        # Epoch 0: capture baselines for regression guard
        if not self._state.op_baselines:
            self._capture_baselines()

        for epoch in range(1, self._state.max_epochs + 1):
            self._notify("epoch_start", {"epoch": epoch})

            snapshot = self._run_epoch(epoch)
            self._snapshots.append(snapshot)
            self._loss_history.append(snapshot.loss)
            self._state = self._state.record_epoch(snapshot)

            Logger.stage_header(
                "TrainingRunner",
                self._state.max_epochs,
                epoch,
            )
            Logger.action(
                "epoch_summary",
                f"epoch={epoch} overall={snapshot.loss.overall_score:.1f} "
                f"compile={snapshot.loss.compile_score:.1f} "
                f"func={snapshot.loss.function_score:.1f} "
                f"perf={snapshot.loss.performance_score:.1f} "
                f"passed={snapshot.loss.num_passed}/{snapshot.loss.num_ops}"
                + (" CONVERGED" if snapshot.converged else ""),
            )

            self._notify("epoch_end", {
                "epoch": epoch,
                "overall_score": snapshot.loss.overall_score,
                "converged": snapshot.converged,
            })

            if snapshot.converged:
                Logger.info(
                    f"TrainingRunner: converged at epoch {epoch} "
                    f"(score={snapshot.loss.overall_score:.1f})"
                )
                break

        return self._state, self._snapshots

    @property
    def state(self) -> TrainingState:
        return self._state

    # —— Internal: epoch loop ——

    def _run_epoch(self, epoch: int) -> EpochSnapshot:
        """Execute one full epoch."""

        # Step 1: eval all operators
        results = self._scheduler.eval_all(
            operators=self._operator_list,
            op_dir_root=self._op_dir_root,
            output_root=self._output_root,
            slot_manager=self._slot_manager,
        )

        # Step 2: aggregate loss
        loss = LossAggregator.aggregate(results)

        # Step 3: check convergence
        converged = self._check_convergence(loss)

        # Step 4: attribute (skip if converged — nothing to improve)
        attributions: list[AttributionItem] = []
        if not converged:
            attributions = AttributionEngine.attribute(results)

        # Step 5: regression guard
        self._check_regression(results)

        # Step 6: apply low-risk improvements
        improvements: list[ImprovementRecord] = []
        if not converged:
            improvements = self._apply_improvements(attributions)

        return EpochSnapshot(
            epoch=epoch,
            loss=loss,
            op_results=results,
            attributions=attributions,
            improvements=improvements,
            converged=converged,
        )

    def _capture_baselines(self) -> None:
        """Run pre-training eval to capture per-op baseline scores."""
        Logger.info("TrainingRunner: capturing epoch-0 baselines...")
        results = self._scheduler.eval_all(
            operators=self._operator_list,
            op_dir_root=self._op_dir_root,
            output_root=self._output_root,
            slot_manager=self._slot_manager,
        )
        self._state = self._state.record_baselines(results)
        Logger.info(
            f"TrainingRunner: baselines captured for "
            f"{len(self._state.op_baselines)} operators"
        )

    def _check_convergence(self, loss: TrainingLoss) -> bool:
        """Convergence: score >= threshold OR patience exceeded."""
        if self._state.convergence_threshold > 0:
            if loss.overall_score >= self._state.convergence_threshold:
                return True

        if self._state.convergence_patience > 0 and len(self._loss_history) >= 1:
            prev_best = max(
                (h.overall_score for h in self._loss_history),
                default=0.0,
            )
            if loss.overall_score <= prev_best:
                no_improv = self._state.epochs_without_improvement + 1
                if no_improv >= self._state.convergence_patience:
                    return True

        return False

    def _check_regression(self, results: list[OpEvalResult]) -> None:
        """Check for regression: any operator score dropped >50% from baseline."""
        regressed = self._state.check_regression(results)
        if regressed:
            Logger.warn(
                f"TrainingRunner: REGRESSION detected on: {', '.join(regressed)}. "
                f"Consider rolling back last improvement."
            )

    def _apply_improvements(
        self, attributions: list[AttributionItem]
    ) -> list[ImprovementRecord]:
        """Apply low-risk improvements. High-risk are flagged for review only.

        Risk policy (04-training-time-iteration.md §2):
          - low/medium risk: record as applied (actual modification deferred)
          - high risk (framework): flag for human review, never auto-modify
        """
        records: list[ImprovementRecord] = []
        for attr in attributions:
            if attr.severity == "high" or "framework" in attr.target_component:
                records.append(ImprovementRecord(
                    attribution=attr,
                    applied=False,
                    action="flag_for_review",
                    detail=f"High-risk: {attr.target_component} — requires human review",
                ))
            else:
                records.append(ImprovementRecord(
                    attribution=attr,
                    applied=False,   # deferred: actual modification is future work
                    action="recorded",
                    detail=f"Low-risk: {attr.target_component} ({attr.failure_type})",
                ))
        return records

    def _notify(self, event_type: str, metadata: dict) -> None:
        """Fire progress callback if configured."""
        if self._progress_callback is not None:
            try:
                self._progress_callback(event_type, metadata)
            except Exception:
                pass  # best-effort
