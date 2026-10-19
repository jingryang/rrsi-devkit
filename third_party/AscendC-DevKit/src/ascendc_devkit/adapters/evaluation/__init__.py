"""L6 Adapters — evaluation backend protocol + selector (step-40 / L3 §4 frozen).

``EvaluationBackend`` is the service-style abstraction (v3): each backend receives
a standard ``EvalRequest``, executes tests self-contained (its own data generation +
comparison + thresholds — no cross-backend mixing), and returns a standardized
``TestReport``. The framework holds the abstraction; ``select_backend`` injects the
implementation (§1.6 DI).

Default registry order: ``CannbenchBackend`` (cann-bench standard-alignment, when
the op's cases came from a cann-bench task) > ``DevkitBackend`` (universal fallback,
any operator repo, zero external burden). Future ATK/TTK backends slot into the
sequence by repo profile or explicit injection — framework-protocol unchanged (L3 §6).

Why a single ``run()`` and not a parts-factory (v2→v3): ATK/TTK are black-box CLIs
that cannot be decomposed into DataGenerator/comparer/threshold parts. Building the
abstraction at the "整箱服务" level lets every backend (cann-bench module form, ATK/TTK
CLI form, devkit self-built) implement the same ``run()`` (L3 §2.2/§3).
"""

from __future__ import annotations

from typing import Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from ascendc_devkit.domain.evaluation import EvalRequest, TestReport


class EvaluationBackend(Protocol):
    """Evaluation backend: standard request → execute tests → standardized report.

    Implementations guarantee internal self-containment (data generation / comparison
    / thresholds are all same-source within one backend); the framework never mixes
    parts across backends (L3 §2.3 standard-consistency-by-selection).
    """

    name: str

    def run(self, request: "EvalRequest") -> "TestReport":
        ...

    def available(self, request: "EvalRequest") -> bool:
        """Whether this backend applies to the operator (selector probes by priority)."""
        ...


def select_backend(request: "EvalRequest",
                   registry: list["EvaluationBackend"] | None = None) -> "EvaluationBackend":
    """Pick the first available backend by priority.

    Default registry: ``[CannbenchBackend, DevkitBackend]`` — cann-bench standard
    alignment first (when a cann-bench task is the case source), then the universal
    devkit fallback. DevkitBackend is always available, so the "no backend" error is
    unreachable in practice (kept as an honest guard, §3.7).
    """
    if registry is None:
        registry = _default_registry()
    for backend in registry:
        if backend.available(request):
            return backend
    raise RuntimeError(
        "no available evaluation backend (DevkitBackend should always be available)")


def _default_registry() -> list["EvaluationBackend"]:
    # Lazy import: the backends import torch/cann-bench at runtime (inside run()),
    # and keeping this import deferred avoids pulling torch into orchestration startup
    # (memory torch-npu-autoload-conflict).
    from ascendc_devkit.adapters.evaluation.cannbench import CannbenchBackend
    from ascendc_devkit.adapters.evaluation.devkit import DevkitBackend
    return [CannbenchBackend(), DevkitBackend()]
