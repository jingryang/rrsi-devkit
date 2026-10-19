"""L4 Domain — evaluation neutral formats (step-40 / 03-impl-evaluation-backend.md).

Backend-agnostic request + result types for the ① local-precheck evaluation
(``precision_debug`` run_tests). Each ``EvaluationBackend`` adapter (L6) translates
these to/from its native format (cann-bench cases/compare_tensors, devkit abs-diff).
The framework core only knows these neutral shapes — never any backend's native
format (L3 §4.3 双向 adapter).

Design (L3 §4 frozen, v3): the abstraction is built at the "execute tests + return
a standardized report" level (整箱服务型), NOT at a parts-injection level (零件注入型
would have excluded black-box CLI backends). Standard consistency comes from
"select one self-contained backend" (cann-bench op → CannbenchBackend uses the full
cann-bench stack internally), not from the framework assembling matching parts.

3D scores (compile/function/performance) are ``Optional``: the ② authoritative eval
(``CannbenchEvalStage`` → ``kernel_eval.cli``) produces them; the ① local precheck
does not (single-case judgement has no 3D score) → ``None``. ``extra`` carries
backend-specific data the framework does not interpret.

Some fields carry forward-extensible shapes (``RunMode.BATCH`` for ②; ``case_filter``
for direct-backend single-case iteration; ``OpRef.op_dir`` for source-compiling
backends). These are intentional contract surface, not dead weight — kept per §1.2
(sound, extensible contract) even when the ① local precheck does not populate them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from ascendc_devkit.domain.precision import CompareRule
from ascendc_devkit.domain.verification import DeployResult


class RunMode(Enum):
    """SINGLE_CASE = ① local precheck (fast single-case iteration, precision_debug).
    BATCH = ② full-set scoring (CannbenchEvalStage); reserved on EvalRequest for the
    backend-neutral contract — ① always uses SINGLE_CASE."""
    SINGLE_CASE = "single_case"
    BATCH = "batch"


@dataclass(frozen=True)
class OpRef:
    """Operator location — what a backend needs to run the kernel.

    ``callable_target`` is ``{kind, symbol}`` from ``codegen_manifest`` (how to call
    the deployed op); ``op_name`` is the operator name (the harness labels output
    with it); ``op_dir`` is the operator source dir (= the agent cwd — a source-
    compiling backend would need it; the NPURunner path uses callable_target +
    deploy_result); ``chip`` is the design-target chip (A2/A3/A5).
    """
    callable_target: dict
    op_name: str
    op_dir: str
    chip: str


@dataclass(frozen=True)
class EvalRequest:
    """Standard evaluation request. Backend adapters translate this to native."""
    op: OpRef
    cases: list                     # list[domain.requirement.TestCase]
    rule: CompareRule               # proto-truth precision spec (domain.precision)
    deploy_result: DeployResult     # deploy artifact paths (domain.verification)
    golden_contract: dict | None    # {path, entry, input_type}
    mode: RunMode
    case_filter: list[str] | None = None    # single-case iteration: case_ids/names
    # Upstream test_design marker — drives backend selection (CannbenchBackend is
    # available only when cases came from a cann-bench task). None = unknown → the
    # selector falls back to DevkitBackend (universal). step-40 L4 §7.1.
    cases_source: str | None = None        # "cannbench" | "devkit" | None
    npu_id: int | None = None
    # Where the backend dumps its raw artifacts (harness.py / run.log with
    # DumpTensor output). precision_debug's agent reads run.log off-disk for
    # root-cause, so the backend must persist it (P54 D7).
    log_dir: str | None = None
    # Complete OperatorSpec — carries attrs type declarations for per-attr
    # validation in the NPU runner (M2 §2.2). When None, attrs validation
    # enforces dict-structure only (no type check).
    op_spec: "OperatorSpec | None" = None
    # NPU test harness subprocess watchdog (seconds). None → backend default
    # (NPURunner.execute's timeout_sec=120). Callers set this to the resolved
    # timeout — config default, or control.json.harness_timeout_sec (the
    # large-shape amplification persisted by build-failed-case-queue.py).
    test_timeout_sec: float | None = None


@dataclass(frozen=True)
class CaseReport:
    """Per-case standard result."""
    case_id: str
    name: str
    status: str                     # pass | fail | skip | cascade
    max_diff: float = 0.0
    mere: float = 0.0
    mare: float = 0.0
    mismatch_count: int = 0
    threshold: float = 0.0
    elapsed_us: float | None = None     # performance (optional)
    error_msg: str = ""


@dataclass(frozen=True)
class TestReport:
    """Aggregated standard result. 3D scores Optional (② has / ① does not)."""
    cases: list[CaseReport] = field(default_factory=list)
    total: int = 0
    passed: int = 0
    failed: int = 0
    pass_rate: float = 0.0
    overall_score: float | None = None       # Optional: 3D weighted
    compile_score: float | None = None
    function_score: float | None = None
    performance_score: float | None = None
    extra: dict = field(default_factory=dict)  # backend-specific passthrough

    def case_by_id(self, case_id: str) -> CaseReport | None:
        return next((c for c in self.cases if c.case_id == case_id), None)

    @property
    def all_passed(self) -> bool:
        return self.failed == 0 and self.total > 0
