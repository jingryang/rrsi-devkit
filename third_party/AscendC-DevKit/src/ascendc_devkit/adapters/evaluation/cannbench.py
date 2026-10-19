"""L6 Adapters — CannbenchBackend: cann-bench standard-alignment backend (step-40).

Module form (L3 §9 decision 2): reuses ``NPURunner`` (single L6 executor) with the
``CannbenchComparer`` (P79), which makes the harness import cann-bench's
``compare_tensors`` and run the cann-bench ``DataGenerator`` data-generation path —
both internalised via the comparer + harness, not scattered into runner/task_loader.
This is the ① local precheck's cann-bench path: single-case fast iteration with no
CLI cold-start, returning cann-bench-standard comparison (the same cases + golden
formula as ②, so the local pre-judgement agrees with the authoritative score).

The per-input value_range bug (scatter) — task_loader's directory-sniff path that
fed int32 indices a [-100,100] range — disappears here: cases come from upstream
``test_design`` (``cann_bench_cases_loader``, which already handles nested per-input
ranges correctly), surfaced to this backend via ``request.cases``; there is no
task_loader directory sniff (L3 §0.2/§6).

``available`` keys off the upstream ``cases_source == "cannbench"`` marker + a golden
contract (cann-bench ops always ship a golden). It does NOT scan the repo. The
selector tries CannbenchBackend before DevkitBackend (standard-alignment priority).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ascendc_devkit.adapters.evaluation._common import run_with_npu_runner
from ascendc_devkit.adapters.npu.precision_comparer import CannbenchComparer

if TYPE_CHECKING:
    from ascendc_devkit.domain.evaluation import EvalRequest, TestReport


class CannbenchBackend:
    """cann-bench standard-alignment backend (module form)."""

    name = "cannbench"

    def available(self, request: "EvalRequest") -> bool:
        """Applies when the op's cases came from a cann-bench task (upstream marker)
        AND a golden contract is present. No directory sniff (step-40 L4 §5)."""
        return (request.cases_source == "cannbench"
                and request.golden_contract is not None)

    def run(self, request: "EvalRequest") -> "TestReport":
        return run_with_npu_runner(request, CannbenchComparer())
