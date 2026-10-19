"""Self-evolution — TrainingState: immutable scheduler-level state.

Follows the same pattern as orchestration/kernel/state.py:
  - frozen=True dataclass
  - with_updates(**kwargs) -> new instance
  - to_snapshot() / from_snapshot() for persistence

This is SEPARATE from per-op State. Per-op State lives in subprocess
workspaces. TrainingState tracks cross-operator progress.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace, asdict
from typing import Any

from ascendc_devkit.domain.evolution import (
    OpEvalResult, TrainingLoss, EpochSnapshot,
    AttributionItem, ImprovementRecord,
)


@dataclass(frozen=True)
class TrainingState:
    """Immutable scheduler-level state for multi-operator training.

    Fields:
        training_run_id: unique ID for this training run
        operator_list: operator names to train on
        training_set_size: number of operators

        current_epoch: which epoch we just completed (0 = not started)
        max_epochs: hard cap

        loss_history: per-epoch aggregated losses
        epochs_without_improvement: consecutive epochs without score gain
        converged: True when convergence criteria are met

        op_baselines: op_name -> baseline overall_score (for regression guard)

        attribution_history: per-epoch attribution records
        improvement_records: all improvement actions taken
        review_queue: high-risk items flagged for human review
    """

    # -- Identity --
    training_run_id: str = ""
    started_at: str = ""

    # -- Operator set --
    operator_list: list[str] = field(default_factory=list)
    training_set_size: int = 0

    # -- Epoch progress --
    current_epoch: int = 0
    max_epochs: int = 20
    convergence_threshold: float = 0.0          # stop when overall_score >= this
    convergence_patience: int = 3               # stop after N epochs without improvement
    epochs_without_improvement: int = 0
    converged: bool = False

    # -- Loss history --
    loss_history: list[dict] = field(default_factory=list)
    # [{epoch, overall_score, compile_score, function_score, performance_score}]

    # -- Per-operator baselines (regression guard) --
    op_baselines: dict[str, float] = field(default_factory=dict)

    # -- Attribution & improvement --
    attribution_history: list[dict] = field(default_factory=list)
    improvement_records: list[dict] = field(default_factory=list)
    review_queue: list[dict] = field(default_factory=list)

    # -- Best epoch (for regression guard rollback) --
    best_epoch: int = 0
    best_overall_score: float = 0.0
    best_model_snapshot: dict = field(default_factory=dict)

    # -- Workspace (not serialized) --
    _workspace: Any = field(default=None, repr=False, compare=False)

    # —— Public API ——

    def with_updates(self, **kwargs) -> "TrainingState":
        """Return a new TrainingState with the given fields replaced."""
        return replace(self, **kwargs)

    def record_epoch(self, snapshot: "EpochSnapshot") -> "TrainingState":
        """Record one epoch's results and return the new TrainingState.

        Updates loss_history, tracks convergence, and records the best epoch
        for regression guard.
        """
        loss_dict = {
            "epoch": snapshot.epoch,
            "overall_score": snapshot.loss.overall_score,
            "compile_score": snapshot.loss.compile_score,
            "function_score": snapshot.loss.function_score,
            "performance_score": snapshot.loss.performance_score,
            "num_ops": snapshot.loss.num_ops,
            "num_passed": snapshot.loss.num_passed,
            "num_failed": snapshot.loss.num_failed,
        }
        history = list(self.loss_history) + [loss_dict]

        # Track best epoch
        best_epoch = self.best_epoch
        best_score = self.best_overall_score
        if snapshot.loss.overall_score > best_score:
            best_epoch = snapshot.epoch
            best_score = snapshot.loss.overall_score

        # Convergence: score >= threshold
        threshold_met = (
            self.convergence_threshold > 0
            and snapshot.loss.overall_score >= self.convergence_threshold
        )

        # Convergence: patience exceeded
        no_improv = self.epochs_without_improvement
        if len(history) >= 2:
            prev_best = max(
                h["overall_score"] for h in self.loss_history
            ) if self.loss_history else 0.0
            if snapshot.loss.overall_score <= prev_best:
                no_improv += 1
            else:
                no_improv = 0

        patience_exceeded = (
            self.convergence_patience > 0
            and no_improv >= self.convergence_patience
        )

        # Attribution history
        attr_records = list(self.attribution_history)
        if snapshot.attributions:
            attr_records.append({
                "epoch": snapshot.epoch,
                "attributions": [
                    {
                        "failure_type": a.failure_type,
                        "target_component": a.target_component,
                        "severity": a.severity,
                        "evidence": a.evidence,
                        "op_count": a.op_count,
                    }
                    for a in snapshot.attributions
                ],
            })

        # Improvement records
        impr_records = list(self.improvement_records)
        for impr in snapshot.improvements:
            impr_records.append({
                "epoch": snapshot.epoch,
                "applied": impr.applied,
                "action": impr.action,
                "detail": impr.detail,
            })

        # Review queue: append high-risk items
        review = list(self.review_queue)
        for a in snapshot.attributions:
            if a.severity == "high":
                review.append({
                    "epoch": snapshot.epoch,
                    "failure_type": a.failure_type,
                    "target_component": a.target_component,
                    "severity": a.severity,
                    "evidence": a.evidence,
                })

        return self.with_updates(
            current_epoch=snapshot.epoch,
            loss_history=history,
            epochs_without_improvement=no_improv,
            converged=(threshold_met or patience_exceeded),
            best_epoch=best_epoch,
            best_overall_score=best_score,
            attribution_history=attr_records,
            improvement_records=impr_records,
            review_queue=review,
        )

    def record_baselines(self, results: list[OpEvalResult]) -> "TrainingState":
        """Capture initial per-op scores as baselines (regression guard)."""
        baselines = dict(self.op_baselines)
        for r in results:
            if r.eval_result is not None and r.eval_result.overall_score > 0:
                baselines[r.op_name] = r.eval_result.overall_score
        return self.with_updates(op_baselines=baselines)

    def check_regression(self, results: list[OpEvalResult]) -> list[str]:
        """Return operator names whose score regressed >50% from baseline."""
        regressed = []
        for r in results:
            if r.op_name not in self.op_baselines:
                continue
            baseline = self.op_baselines[r.op_name]
            current = r.eval_result.overall_score if r.eval_result else 0.0
            if baseline > 0 and current < baseline * 0.5:
                regressed.append(r.op_name)
        return regressed

    # —— Persistence ——

    def to_snapshot(self) -> dict:
        """Serialize to plain dict (excludes _workspace)."""
        d = asdict(self)
        d.pop("_workspace", None)
        return d

    @classmethod
    def from_snapshot(cls, data: dict) -> "TrainingState":
        """Reconstruct from a plain dict."""
        data.pop("_workspace", None)
        # Ensure all fields have defaults for forward-compat
        defaults = {
            "training_run_id": "", "started_at": "",
            "operator_list": [], "training_set_size": 0,
            "current_epoch": 0, "max_epochs": 20,
            "convergence_threshold": 0.0, "convergence_patience": 3,
            "epochs_without_improvement": 0, "converged": False,
            "loss_history": [], "op_baselines": {},
            "attribution_history": [], "improvement_records": [],
            "review_queue": [],
            "best_epoch": 0, "best_overall_score": 0.0,
            "best_model_snapshot": {},
        }
        for key, default in defaults.items():
            if key not in data:
                data[key] = default
        return cls(**data)
