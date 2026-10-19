"""L4 Domain — Self-evolution training-loop types."""

from __future__ import annotations

from dataclasses import dataclass, field

from ascendc_devkit.domain.verification import EvalResult


@dataclass(frozen=True)
class OpEvalResult:
    """Single-operator evaluation outcome from one self_evolve_op run.

    Fields:
        op_name: operator name (snake_case)
        eval_result: parsed EvalResult (None if the run failed before eval)
        status: "ok" | "compile_failed" | "deploy_failed" | "eval_timeout" | "crashed"
        elapsed_ms: wall-clock time for the full self_evolve_op run
        output_dir: path to the subprocess output directory (for traceability)
    """
    op_name: str = ""
    eval_result: EvalResult | None = None
    status: str = "ok"
    elapsed_ms: float = 0.0
    output_dir: str = ""


@dataclass(frozen=True)
class TrainingLoss:
    """Aggregated loss across the training set for one epoch.

    Weight scheme mirrors cann-bench: compile 0.2 + function 0.3 + perf 0.5.
    epoch_loss = 100 - overall_score (lower is better, for convergence tracking).
    """
    overall_score: float = 0.0
    compile_score: float = 0.0
    function_score: float = 0.0
    performance_score: float = 0.0
    pass_rate_mean: float = 0.0
    num_ops: int = 0
    num_passed: int = 0
    num_failed: int = 0
    per_op: dict[str, float] = field(default_factory=dict)   # op_name → overall_score

    @property
    def epoch_loss(self) -> float:
        """100 - overall_score so convergence minimises loss."""
        return 100.0 - self.overall_score


@dataclass(frozen=True)
class AttributionItem:
    """One attribution: which failure pattern maps to which model component.

    Risk policy (from 04-training-time-iteration.md §2):
      - resources: lowest risk
      - skill prompt: low risk
      - agent manifest: low-medium risk
      - framework Python: HIGH risk (flag for review, never auto-modify)
    """
    failure_type: str = ""        # "compile_failed" | "precision_failed" |
                                  # "perf_insufficient" | "deploy_failed" | "eval_zero"
    target_component: str = ""    # "skill/codegen" | "skill/tiling" |
                                  # "resources/api" | "agent/codegen" | "framework/deploy"
    severity: str = "low"         # "low" | "medium" | "high"
    evidence: str = ""            # human-readable evidence (e.g. "3 ops compile-failed")
    op_count: int = 0             # how many operators exhibit this failure


@dataclass(frozen=True)
class ImprovementRecord:
    """Record of one improvement action taken (or flagged for review).

    Low-risk items (skill/resources) are auto-applied. High-risk items
    (framework) are flagged for human review.
    """
    attribution: AttributionItem = field(default_factory=AttributionItem)
    applied: bool = False         # True if the improvement was auto-applied
    action: str = ""              # "enhance_prompt" | "add_knowledge" |
                                  # "flag_for_review" | "rollback"
    detail: str = ""              # what was changed (human-readable)


@dataclass(frozen=True)
class EpochSnapshot:
    """Complete record of one training epoch."""
    epoch: int = 0
    loss: TrainingLoss = field(default_factory=TrainingLoss)
    op_results: list[OpEvalResult] = field(default_factory=list)
    attributions: list[AttributionItem] = field(default_factory=list)
    improvements: list[ImprovementRecord] = field(default_factory=list)
    converged: bool = False
