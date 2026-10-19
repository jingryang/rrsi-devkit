"""L6 Adapters — DevkitBackend: universal default evaluation backend (step-40).

Any operator repo (ops-nn / ops-transformer / omni-ops) runs on this backend with
zero external burden: the operator just needs to be callable + a golden. It reuses
``NPURunner`` (single L6 executor) with the ``DevkitComparer`` (P79 self-contained
abs-diff path — no cann-bench dependency). Data generation is the runner's own
deterministic torch.rand (seed = SHA256(case_id) convention), independent of any
cann-bench ``DataGenerator``.

Result: a standard ``TestReport`` with 3D scores = None (the ① local precheck has
no compile/function/performance breakdown). For cann-bench standard-alignment,
``CannbenchBackend`` is selected instead (its ``available`` wins when the op's cases
came from a cann-bench task).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ascendc_devkit.adapters.evaluation._common import run_with_npu_runner
from ascendc_devkit.adapters.npu.precision_comparer import DevkitComparer

if TYPE_CHECKING:
    from ascendc_devkit.domain.evaluation import EvalRequest, TestReport


class DevkitBackend:
    """Universal default backend — always available, zero external burden."""

    name = "devkit"

    def available(self, request: "EvalRequest") -> bool:
        """Universal fallback — always available (§1.7 self-contained default)."""
        return True

    def run(self, request: "EvalRequest") -> "TestReport":
        return run_with_npu_runner(request, DevkitComparer())
