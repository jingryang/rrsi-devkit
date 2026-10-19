"""L3 Orchestration — Gate: pure decision function for stage gating."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True)
class GateResult:
    passed: bool
    reason: str = ""
    metrics: dict = field(default_factory=dict)


class Gate(ABC):
    """Pure decision function: given evidence, return pass/fail + reason."""

    @abstractmethod
    def evaluate(self, evidence: dict) -> GateResult:
        ...
