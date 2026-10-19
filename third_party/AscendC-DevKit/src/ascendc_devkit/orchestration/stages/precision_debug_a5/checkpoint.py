"""A5 checkpoint I/O and validation."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING

from ascendc_devkit.orchestration.runtime_config import (
    precision_debug_a5_max_attempts_per_case,
    precision_debug_a5_max_iterations,
    precision_debug_a5_max_op_plugin_rounds,
    precision_debug_a5_max_vector_error_rounds,
    precision_debug_a5_max_vf_rounds,
)

if TYPE_CHECKING:
    from ascendc_devkit.orchestration.kernel.state import State


_A5_CONTROL_REQUIRED_KEYS = frozenset({
    "status", "phase", "failed_case_queue", "current_case_index",
    "max_attempts_per_case", "history", "best_snapshot", "best_commit",
    "initial_commit", "rollback_safe", "anchor_error", "op_plugin_round",
    "max_op_plugin_rounds", "error_type", "active_error_fingerprint",
    "candidate_commit", "commit_error",
})

_A5_CONTROL_DEFAULTS = {
    "status": "in_progress",
    "phase": "baseline",
    "failed_case_queue": [],
    "current_case_index": 0,
    "max_attempts_per_case": precision_debug_a5_max_attempts_per_case(),
    "max_op_plugin_rounds": precision_debug_a5_max_op_plugin_rounds(),
    "op_plugin_round": 0,
    "history": [],
    "best_snapshot": {},
    "best_commit": "",
    "initial_commit": "",
    "rollback_safe": True,
    "anchor_error": "",
    "error_type": "",
    "active_error_fingerprint": "",
    "phase_counter": 0,
    "run_iter_counter": 0,
    "vector_error_round": 0,
    "max_vector_error_rounds": precision_debug_a5_max_vector_error_rounds(),
    "max_vf_rounds": precision_debug_a5_max_vf_rounds(),
    "vector_error_status": "",
    "vector_error_source_phase": "",
    "candidate_commit": "",
    "commit_error": "",
}

_FRAMEWORK_OWNED_KEYS = frozenset(_A5_CONTROL_DEFAULTS) | frozenset({
    "classification", "kernel_debug_round", "vf_round",
    "double_tool_passed", "rc_full_pass", "kl_full_pass",
})


def _load_a5_checkpoint(state: "State") -> dict:
    """Load checkpoint.json; auto-repair missing required fields."""
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _control_path, _debug_artifacts_dir, A5PrecisionDebugContractError,
    )
    p = _control_path(state)
    if p is None or not p.exists():
        cp = {}
    else:
        try:
            cp = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cp = {}
    if cp:
        missing = _A5_CONTROL_REQUIRED_KEYS - set(cp.keys())
        if missing:
            from ascendc_devkit.infra.logger import Logger
            Logger.warn(f"[A5-PD-CONTRACT] checkpoint missing {sorted(missing)}; auto-filling")
            for k in sorted(missing):
                cp[k] = _A5_CONTROL_DEFAULTS.get(k)
            if p is not None:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps(cp, indent=2, ensure_ascii=False), encoding="utf-8")
    return cp or {}


def _save_a5_checkpoint(state: "State", cp: dict) -> None:
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _control_path,
    )
    p = _control_path(state)
    if p is None:
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cp, indent=2, ensure_ascii=False), encoding="utf-8")


def _save_framework_checkpoint_guard(state: "State") -> None:
    """Freeze framework-owned fields immediately before an agent spawn."""
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import _control_path
    p = _control_path(state)
    if p is None:
        return
    cp = _load_a5_checkpoint(state)
    guard = {key: deepcopy(cp[key]) for key in _FRAMEWORK_OWNED_KEYS if key in cp}
    guard_path = p.parent / ".framework_checkpoint_guard.json"
    guard_path.parent.mkdir(parents=True, exist_ok=True)
    guard_path.write_text(json.dumps(guard, indent=2, ensure_ascii=False), encoding="utf-8")


def _restore_framework_checkpoint_guard(state: "State", cp: dict, *, phase: str) -> dict:
    """Discard direct agent writes to framework-owned checkpoint fields."""
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import _control_path
    p = _control_path(state)
    guard_path = p.parent / ".framework_checkpoint_guard.json" if p is not None else None
    if guard_path is not None and guard_path.exists():
        try:
            guard = json.loads(guard_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            guard = {}
        for key in _FRAMEWORK_OWNED_KEYS:
            if key in guard:
                cp[key] = deepcopy(guard[key])
            else:
                cp.pop(key, None)
    cp["phase"] = phase
    return cp


def _validate_a5_checkpoint(cp: dict, control_path: str) -> dict:
    """Validate and auto-repair A5 checkpoint.json."""
    if not cp:
        return cp
    repaired = False
    missing = _A5_CONTROL_REQUIRED_KEYS - set(cp.keys())
    if missing:
        from ascendc_devkit.infra.logger import Logger
        Logger.warn(f"[A5-PD-CONTRACT] checkpoint missing {sorted(missing)}; auto-filling")
        for k in sorted(missing):
            cp[k] = _A5_CONTROL_DEFAULTS.get(k)
        repaired = True
    if not isinstance(cp.get("failed_case_queue"), list):
        cp["failed_case_queue"] = []
        repaired = True
    if not isinstance(cp.get("current_case_index"), int):
        try:
            cp["current_case_index"] = int(cp["current_case_index"])
        except (TypeError, ValueError):
            cp["current_case_index"] = 0
        repaired = True
    if not isinstance(cp.get("history"), list):
        cp["history"] = []
        repaired = True
    if repaired:
        Path(control_path).parent.mkdir(parents=True, exist_ok=True)
        Path(control_path).write_text(json.dumps(cp, indent=2, ensure_ascii=False), encoding="utf-8")
    return cp


def _restore_framework_routing_fields(state: "State", cp: dict, *, phase: str) -> dict:
    """Compatibility wrapper for the pre-spawn checkpoint guard."""
    return _restore_framework_checkpoint_guard(state, cp, phase=phase)


def _extract_a5_debug_checkpoint(cp: dict) -> dict:
    """Minimal routing field set derived from checkpoint.json."""
    queue = cp.get("failed_case_queue", []) or []
    case = None
    idx = cp.get("current_case_index", 0)
    if 0 <= idx < len(queue):
        case = queue[idx]
    return {
        "status": cp.get("status", "in_progress"),
        "phase": cp.get("phase", "baseline"),
        "max_iterations": cp.get("max_iterations", precision_debug_a5_max_iterations()),
        # Baseline/kernel_debug resolve_condition route on per-case error_layer,
        # so the full queue (not just the count) must ride the routing snapshot
        # (2026-08-01: missing here made baseline's 20 kernel failures resolve to
        # "all_pass" → group wrongly escalated passed → cannbench_adapt ran).
        "failed_case_queue": queue,
        "failed_case_count": len(queue),
        # agent 的顶层分类判据（baseline 提供）：data-faithful，已剔除 cann-bench
        # relative-error 误报。resolve_condition 据此路由，避免 rc_pass/kl_pass 覆盖。
        "classification": cp.get("classification") or {},
        # 双工具验收机械判据（baseline transition 由 rc_result/kl_result 实测复核）：
        # double_tool_passed = rc 与 kl 双双全过（all_pass 的唯一合法条件）；
        # rc_full_pass/kl_full_pass 供 queue 为空时区分「误报已剔可 all_pass」vs
        # 「契约缺失 escalate exhausted」。
        "double_tool_passed": bool(cp.get("double_tool_passed", False)),
        "rc_full_pass": bool(cp.get("rc_full_pass", False)),
        "kl_full_pass": bool(cp.get("kl_full_pass", False)),
        "consecutive_aborts": cp.get("consecutive_aborts", 0),
        "current_case_status": case.get("status") if case else None,
        "current_case_attempt": case.get("attempt_count", 0) if case else 0,
        "current_case_max_attempts": cp.get("max_attempts_per_case", 3),
        "case_resolved": case.get("status") in ("resolved", "resolved_pending") if case else False,
        "failing_cases": [c.get("case_id", "") for c in queue
                          if c.get("status") in ("pending", "skipped")],
        "best_commit": cp.get("best_commit", ""),
        "candidate_commit": cp.get("candidate_commit", ""),
        "commit_error": cp.get("commit_error", ""),
        "rollback_safe": cp.get("rollback_safe", True),
        "best_snapshot": cp.get("best_snapshot", {}) or {},
        "error_type": cp.get("error_type", ""),
        "active_error_fingerprint": cp.get("active_error_fingerprint", ""),
        "op_plugin_round": cp.get("op_plugin_round", 0),
        "max_op_plugin_rounds": cp.get(
            "max_op_plugin_rounds", precision_debug_a5_max_op_plugin_rounds()),
        "vector_error_round": cp.get("vector_error_round", 0),
        "vector_error_status": cp.get("vector_error_status", ""),
        "vector_error_source_phase": cp.get("vector_error_source_phase", ""),
    }
