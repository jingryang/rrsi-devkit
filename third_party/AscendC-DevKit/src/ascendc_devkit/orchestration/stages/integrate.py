"""L3 Orchestration — Integrate Stage: validate in-repo code + finalization.

Plan-A: code is written directly into the operator repo from codegen onward,
so integrate no longer materializes from an in-memory source dict. It now
validates that op_dir holds the expected files and records the operator's
on-disk file list (target_files). new/incremental share one path.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ascendc_devkit.domain.contract import StageIOContract
from ascendc_devkit.orchestration.base import Stage
from ascendc_devkit.orchestration.registry import register_stage
from ascendc_devkit.orchestration.kernel.action import Action, NoOp
from ascendc_devkit.orchestration.kernel.gate import Gate, GateResult
from ascendc_devkit.infra.logger import Logger

if TYPE_CHECKING:
    from ascendc_devkit.orchestration.kernel.state import State


_SOURCE_SUFFIXES = (".cpp", ".h", ".hpp", ".py")


class VerifyCompleteGate(Gate):
    """Verify that compilation passed.

    D2: deleted the dead ``precision_result`` read (only build_result gates here).
    """

    def evaluate(self, evidence: dict) -> GateResult:
        build = evidence.get("build_result")
        if build is None:
            return GateResult(passed=False, reason="No build_result available")
        if not build.passed:
            return GateResult(passed=False, reason=f"Build failed: {build.stderr[:200]}")
        return GateResult(passed=True, reason="Verification complete")


@register_stage
class IntegrateStage(Stage):
    name = "integrate"
    description = "Validate in-repo operator code and record finalization"
    default_max_iterations = 1
    needs_iteration_safety_net = False  # deterministic single pass, no agent

    def input_contract(self) -> StageIOContract:
        return StageIOContract(
            # Plan-A: code already in repo; integrate reads/validates op_dir.
            # generated_sources is no longer required (optional for reports).
            requires=["mode", "op_identity", "profile", "adapter"],
            optional=["generated_sources"],
        )

    def output_contract(self) -> StageIOContract:
        return StageIOContract(
            provides=["integration_result", "target_files"],
        )

    def gate(self):
        return VerifyCompleteGate()

    def actions(self, state: State, iteration: int = 1) -> list[Action]:
        # Validation/finalization runs in transition() by reading op_dir.
        # No materialization action — new and incremental share this path.
        return [NoOp(reason="in-repo: integrate validates op_dir, no materialization")]

    def _scan_op_dir(self, op_dir: Path) -> list[Path]:
        """Return the operator's on-disk source files (authoritative view)."""
        if not op_dir.is_dir():
            return []
        return sorted(
            f for f in op_dir.rglob("*")
            if f.is_file() and f.suffix in _SOURCE_SUFFIXES
        )

    def transition(self, state: State, result: dict) -> State:
        op = state.op_identity
        if op is None:
            # No operator identity (e.g. design-only delivery) — nothing to land.
            return state.with_updates(
                integration_result={"status": "skipped", "reason": "no op_identity"},
                target_files=[],
            )

        op_dir = Path(op.op_dir)
        target_files = self._scan_op_dir(op_dir)

        # Completeness check: expected section directories (from kernel_architecture)
        # must each exist and contain at least one source file in op_dir.
        # P2 section-level: _expected_code_files returns directory names, not
        # individual file paths.  Check each section dir for presence + content.
        from ascendc_devkit.orchestration.stages.codegen import CodegenStage
        expected_sections = CodegenStage._expected_code_files(state)
        present = {str(f.relative_to(op_dir)) for f in target_files}
        missing = [
            d for d in expected_sections
            if not any(p.startswith(d + "/") or p == d for p in present)
        ]

        if not op_dir.is_dir():
            return self._fail(state, f"op_dir does not exist: {op_dir}")
        if expected_sections and missing:
            return self._fail(state, f"missing expected files in op_dir: {sorted(missing)}")
        if not target_files:
            return self._fail(state, f"no source files found in op_dir: {op_dir}")

        Logger.action("integrate", f"validated {len(target_files)} files in {op_dir}")
        return state.with_updates(
            integration_result={"status": "ok", "files": len(target_files)},
            target_files=target_files,
        )

    def _fail(self, state: State, reason: str) -> State:
        from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
        Logger.error(f"Integration validation failed: {reason}")
        return state.with_updates(
            integration_result={"status": "error", "error": reason},
            target_files=[],
            last_error=ErrorFeedback(
                stage_name="integrate",
                error_type="integration_incomplete",
                message=reason,
            ),
        )

