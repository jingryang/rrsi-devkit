"""Convergence / materialization helpers for A5 precision_debug."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ascendc_devkit.domain.verification import PrecisionDebugResult
from ascendc_devkit.orchestration.stages.precision_debug_a5.base import _operator_dir
from ascendc_devkit.orchestration.stages.precision_debug_a5.checkpoint import (
    _extract_a5_debug_checkpoint,
    _load_a5_checkpoint,
)

if TYPE_CHECKING:
    from ascendc_devkit.orchestration.kernel.state import State


def _sync_debug_result(state: "State", dc: dict) -> "State":
    """Materialize a terminal PrecisionDebugResult when the run reaches a terminal state.

    A5 terminal states: ``status == "passed"`` or ``status == "max_rounds_reached"``.
    """
    if dc.get("status") == "passed":
        snap = dc.get("best_snapshot") or {}
        result = PrecisionDebugResult(
            passed=True,
            max_diff=float(snap.get("max_err") or 0.0),
            best_commit=str(snap.get("commit") or dc.get("best_commit") or ""),
            best_passed_count=int(snap.get("passed") or 0),
            failing_cases=[],
            iterations_used=int(dc.get("rounds", 0) or 0),
        )
        return state.with_updates(debug_result=result, debug_iterations=result.iterations_used)
    if dc.get("status") == "max_rounds_reached":
        snap = dc.get("best_snapshot") or {}
        result = PrecisionDebugResult(
            passed=False,
            max_diff=float(snap.get("max_err") or 0.0),
            best_commit=str(snap.get("commit") or dc.get("best_commit") or ""),
            best_passed_count=int(snap.get("passed") or 0),
            failing_cases=list(snap.get("failed_cases", []) or []),
            iterations_used=int(dc.get("rounds", 0) or 0),
        )
        return state.with_updates(debug_result=result, debug_iterations=result.iterations_used)
    return state


def _converge_a5_to_best_commit(state: "State") -> "State":
    """Exit-time convergence to best_commit for A5 flow.

    Mirrors A3 ``_converge_to_best_commit`` but uses A5 checkpoint helpers.
    """
    cp = _load_a5_checkpoint(state)
    dc = _extract_a5_debug_checkpoint(cp)
    if dc.get("status") == "passed":
        return state
    op = state.op_identity
    op_dir = _operator_dir(state)
    if op is None or not getattr(op, "repo_root", None) or not op_dir:
        return state
    from ascendc_devkit.infra.logger import Logger
    best = dc.get("best_commit")
    if not best:
        Logger.error("A5 converge_best_commit: best_commit empty; refusing destructive HEAD fallback")
        return state
    from ascendc_devkit.infra.repo_guard import RepoGuard
    from ascendc_devkit.orchestration.stages.deploy import Deployer
    guard = RepoGuard()
    if not dc.get("rollback_safe", cp.get("rollback_safe", True)):
        Logger.error("A5 converge_best_commit: rollback_safe=false; preserving operator tree")
        return state
    if not guard.is_clean(op.repo_root, op_dir):
        Logger.error("A5 converge_best_commit: op_dir dirty; refusing checkout+clean")
        return state
    snapshot_commit = str((dc.get("best_snapshot") or {}).get("commit") or "")
    if snapshot_commit and snapshot_commit != best:
        Logger.error("A5 converge_best_commit: best_snapshot.commit disagrees with best_commit; preserving operator tree")
        return state
    rolled = guard.rollback(op.repo_root, op_dir, best)
    if not rolled:
        Logger.warn(f"A5 converge_best_commit: rollback to {best[:12]} failed")
        return state
    try:
        new_deploy, err = Deployer().deploy(state)
    except Exception as e:
        Logger.error(f"A5 converge_best_commit: redeploy raised {e}")
        return state
    if new_deploy and new_deploy.smoke_passed:
        Logger.action("A5 converge_best_commit",
                      f"op_dir -> {best[:12]} + redeployed (smoke ok)")
        return state.with_updates(deploy_result=new_deploy)
    Logger.error(f"A5 converge_best_commit: redeploy of {best[:12]} failed smoke")
    return state
