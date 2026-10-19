"""L4 Domain — StageTransition: loop-back target descriptor."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StageTransition:
    """Describes a pipeline loop-back from one stage to another."""

    target_stage: str
    reason: str  # "build_failed" | "precision_failed" | "perf_exhausted" | "user_decision"
