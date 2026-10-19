"""L3 Orchestration — Finalize Stage: build in repo, generate report, cleanup."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ascendc_devkit.domain.contract import StageIOContract
from ascendc_devkit.domain.verification import BuildResult
from ascendc_devkit.orchestration.base import Stage
from ascendc_devkit.orchestration.registry import register_stage
from ascendc_devkit.orchestration.kernel.action import (
    RunGate, UpdateDevRecord, RemoveMemoryPointer, Action, NoOp,
)
from ascendc_devkit.orchestration.kernel.gate import Gate, GateResult
from ascendc_devkit.orchestration.stages.gates import BuildInRepoGate

if TYPE_CHECKING:
    from ascendc_devkit.orchestration.kernel.state import State


class IntegrationCompleteGate(Gate):
    """Verify that integrate stage successfully landed code.

    Gracefully handles the case where no integration stage ran
    (e.g., SE workflow: design-only deliverable).
    """

    def evaluate(self, evidence: dict) -> GateResult:
        integration = evidence.get("integration_result")
        target_files = evidence.get("target_files", [])

        # No integration stage ran — not an error for design-only workflows
        if integration is None or integration == {}:
            return GateResult(
                passed=True,
                reason="No integration stage — skipping integration check",
            )

        if integration.get("status") == "error":
            return GateResult(
                passed=False,
                reason=integration.get("error", "Integration not complete"),
            )
        if not target_files:
            return GateResult(passed=False, reason="No target files produced")
        return GateResult(
            passed=True,
            reason=f"{len(target_files)} files written to target repo",
        )


@register_stage
class FinalizeStage(Stage):
    name = "finalize"
    description = "Build in target repo, generate report, cleanup"
    default_max_iterations = 1
    needs_iteration_safety_net = False  # deterministic single pass, no agent

    def input_contract(self) -> StageIOContract:
        return StageIOContract(
            requires=["mode"],
            optional=["target_files", "integration_result", "adapter", "op_identity",
                       "dev_record_path", "workspace"],
        )

    def output_contract(self) -> StageIOContract:
        return StageIOContract(
            provides=["final_build_result", "dev_record_updated"],
        )

    def gate(self):
        return IntegrationCompleteGate()

    def actions(self, state: State, iteration: int = 1) -> list[Action]:
        actions: list[Action] = []

        # In-repo build: only when integration produced target files
        has_integration = (
            state.integration_result is not None
            and state.target_files
        )
        if has_integration and state.adapter and state.op_identity:
            actions.append(
                RunGate(
                    gate_name="build_in_repo",
                    gate=BuildInRepoGate(),
                    evidence={
                        "adapter": state.adapter,
                        "op_identity": state.op_identity,
                        "design_target_chip": state.design_target_chip,
                    },
                ),
            )

        if state.mode == "incremental" and has_integration:
            dev_record_path = None
            if state.op_identity:
                dev_record_path = state.op_identity.op_dir / ".lingxi" / "dev_record.md"
            actions.append(
                UpdateDevRecord(
                    path=dev_record_path,
                    stage_status="finalize",
                    requirement_path=state.requirement_path,
                    change_summary=state.change_summary or "",
                    target_files=state.target_files or [],
                )
            )

        # D8 (hard-timeout): report generation moved to dispatcher finally-block
        # (covers every terminal exit incl. timeout). The former GenerateReport
        # action here was an inert marker (runner `else:pass`, transition ignored
        # it) — removed (§2.5 single pathway).

        return actions

    def skip_reason(self, state: State) -> str | None:
        """P6-b: nothing to finalize when integration produced no target files
        (no in-repo build, no dev-record update). Mirrors the actions() conditions
        so an intentionally-empty finalize logs ○ skipped, not ⚠ no-actions."""
        has_integration = (
            state.integration_result is not None
            and state.target_files
        )
        build = has_integration and state.adapter and state.op_identity
        dev_record = state.mode == "incremental" and has_integration
        if not (build or dev_record):
            return "nothing to finalize (no integration result / not incremental)"
        return None

    def transition(self, state: State, result: dict) -> State:
        gate_result = result.get("gate_result", {})

        final_build_result = BuildResult(
            passed=gate_result.get("passed", True),
            stderr=gate_result.get("reason", ""),
        )

        dev_record_updated = False
        if state.mode == "incremental":
            dev_record_result = result.get("dev_record", {})
            dev_record_updated = dev_record_result.get("status") == "ok"

        return state.with_updates(
            final_build_result=final_build_result,
            dev_record_updated=dev_record_updated,
        )
