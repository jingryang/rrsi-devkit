"""Per-case loop helpers (queue / advance / stop-loss)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ascendc_devkit.orchestration.kernel.state import State


def _case_diffs_from_kl_result(kl_data: dict) -> dict:
    """Build ``{case_id(str): max_diff}`` from a KernelLaunch ``kl_result.json``.

    Prefers the full-list keys (``all_results`` / ``per_case`` — every case the
    script ran) over ``failed_cases`` (failing subset only), so a full KL re-run
    refreshes all queue cases. Entries with no numeric ``max_diff`` (crash) are
    skipped.
    """
    out: dict[str, float] = {}
    entries = (kl_data.get("all_results") or kl_data.get("per_case")
               or kl_data.get("failed_cases") or [])
    for e in entries:
        md = e.get("max_diff")
        if md is not None:
            out[str(e.get("case_id", ""))] = md
    return out


def _refresh_queue_kl_diffs(cp: dict, case_diffs: dict) -> None:
    """Refresh ``failed_case_queue[i].max_diff_kl`` from the latest KernelLaunch
    measurement (data-faithful write-back, §1.13 — the framework only relays the
    value the KL script actually measured, never fabricates).

    In-place mutation of ``cp`` (returns ``None``; callers must not assume a
    rebind — the caller's ``cp`` is the same dict object). ``case_diffs`` maps
    case_id(str) → latest max_diff. Queue cases absent from the map are left
    untouched. This is what keeps the injected "当前待处理 CASE" block honest
    across iterations: kernel_debug 修复后批跑全量 KL re-measures the kernel and
    the queue's ``max_diff_kl`` follows, instead of staying frozen at the baseline
    value (which misled agents after a fix).
    """
    if not case_diffs:
        return
    for case in cp.get("failed_case_queue", []) or []:
        key = str(case.get("case_id", ""))
        if key in case_diffs:
            case["max_diff_kl"] = case_diffs[key]


def _all_kl_passed(kl_data: dict) -> bool:
    """Whether the full KernelLaunch run passed for every case it measured.

    Only full-list shapes carry pass evidence for *all* cases:
    - ``per_case`` — what ``{op_name}_kernel_launch_test.py`` actually writes
      (every case, incl. passing ones, each with ``passed``);
    - ``all_results`` — legacy harness/test layout (full list).

    ``failed_cases`` alone (failing subset) has no pass evidence, so it returns
    ``False`` conservatively (route back to kernel_debug; spawn reconcile then
    skips whatever the real per-case data marks passed).
    """
    entries = kl_data.get("per_case") or kl_data.get("all_results") or []
    if not entries:
        return False
    return all(bool(e.get("passed")) for e in entries)


def _per_case_kl_results(kl_data: dict) -> dict:
    """Extract per-case KernelLaunch results as ``{case_id(str): {passed, max_diff}}``.

    Only the full-list shapes carry pass/fail evidence for *all* cases (and thus
    the authority to mark a case resolved):
    - ``per_case`` — what ``{op_name}_kernel_launch_test.py`` actually writes
      (every case, incl. passing ones, each with ``passed``);
    - ``all_results`` — legacy harness/test layout (full list).

    ``failed_cases`` alone (failing subset) has no pass evidence, so it returns
    ``{}`` (diffs still refresh via ``_case_diffs_from_kl_result``; statuses are
    left untouched rather than guessed). ``passed`` defaults to ``False`` when an
    entry omits it, so a case is only ever marked resolved on explicit evidence.
    """
    entries = kl_data.get("per_case") or kl_data.get("all_results") or []
    out: dict[str, dict] = {}
    for e in entries:
        cid = e.get("case_id")
        if cid is None or cid == "":
            continue
        out[str(cid)] = {
            "passed": bool(e.get("passed", False)),
            "max_diff": e.get("max_diff"),
        }
    return out


def _reconcile_queue_from_kl(cp: dict, per_case: dict) -> int:
    """Reconcile ``failed_case_queue`` against the latest full KernelLaunch run.

    Two effects (data-faithful, §1.13 — the framework relays only what the KL
    script actually measured, never fabricates):
    - Refreshes ``max_diff_kl`` for every case present in ``per_case``.
    - Marks **kernel-layer** cases (``error_layer != "op_plugin"``) that KL now
      passes as ``resolved`` (when currently ``pending``/``debugging``), so a
      precision-correct case is never re-scheduled for kernel_debug. op_plugin
      cases are left untouched: a KL pass is necessary but not sufficient there
      (RC is the acceptance tool), and baseline's authoritative dual-run covers
      them.

    Returns the number of cases newly marked resolved.
    """
    if not per_case:
        return 0
    marked = 0
    for case in cp.get("failed_case_queue", []) or []:
        key = str(case.get("case_id", ""))
        entry = per_case.get(key)
        if entry is None:
            continue
        if entry.get("max_diff") is not None:
            case["max_diff_kl"] = entry["max_diff"]
        if entry.get("passed") and case.get("error_layer") != "op_plugin":
            if case.get("status") in ("pending", "debugging"):
                case["status"] = "resolved"
                marked += 1
    return marked


def _apply_kl_failures_to_queue(cp: dict, kl_data: dict,
                                case_meta: dict | None = None) -> tuple[int, int]:
    """Maintain the *failing* side of ``failed_case_queue`` from the KL run.

    Framework-authoritative (data-faithful, §1.13): the queue is maintained from
    what the KL script actually measured — not from the agent's transcribed
    ``new_failed_cases`` list. Mirrors how baseline builds its queue from the
    real run outcome, but for the failure side of an existing queue.

    ``kl_data`` must be the parsed ``result_{op_name}_summary.json`` (the
    ``per_case`` key, whose every entry carries an explicit ``passed``). Legacy
    ``all_results`` entries without ``passed`` are NOT authoritative for
    fail-side decisions — callers should only invoke this when
    ``kl_data.get("per_case")`` is present.

    ``case_meta`` is the ``{case_id(str): {shape, dtype}}`` map from cases.csv
    (authoritative case metadata, §1.13); appended entries are enriched with it,
    matching baseline's queue construction.

    For every case the KL run marks failed (``passed=False``):
    - already in queue with ``status=resolved`` → relabel ``debugging``
      (regressed; mutate the original entry, never append a duplicate). If the
      entry was ``error_layer=op_plugin``, flip it to ``kernel``: KL runs the
      kernel binary directly (bypassing the adapter), so a KL failure is
      evidence the problem is kernel-side — keeping ``op_plugin`` would hand a
      mislabeled case to kernel_debug.
    - already in queue with status ``pending``/``debugging``/``skipped`` →
      leave untouched (pending work / in-flight / stop-loss already taken);
    - not in queue → append at tail as ``pending`` (``error_layer=kernel``,
      ``attempt_count=0``, ``max_diff_kl`` from the measured value). The
      appended ``case_id`` keeps the KL script's original type.

    Returns ``(regressed, added)``.
    """
    entries = kl_data.get("per_case") or []
    queue = cp.get("failed_case_queue", []) or []
    by_id = {str(c.get("case_id", "")): c for c in queue}
    case_meta = case_meta or {}
    regressed = 0
    added = 0
    for e in entries:
        cid = e.get("case_id")
        if cid is None or cid == "" or e.get("passed", False):
            continue
        key = str(cid)
        existing = by_id.get(key)
        if existing is not None:
            if existing.get("status") == "resolved":
                existing["status"] = "debugging"
                if existing.get("error_layer") == "op_plugin":
                    existing["error_layer"] = "kernel"
                regressed += 1
            continue
        meta = case_meta.get(key, {})
        queue.append({
            "case_id": cid,
            "shape": meta.get("shape", ""),
            "dtype": meta.get("dtype", ""),
            "max_diff_rc": None,
            "max_diff_kl": e.get("max_diff"),
            "error_layer": "kernel",
            "failure_type": "precision",
            "status": "pending",
            "attempt_count": 0,
        })
        by_id[key] = queue[-1]
        added += 1
    cp["failed_case_queue"] = queue
    return regressed, added


def _case_skip_for_debug(case: dict, *, skip_op_plugin: bool = False) -> bool:
    """Whether a queue entry is *not* consumable work for the current per-case stage.

    ``resolved``/``skipped`` entries (reconciled away or exhausted) are skipped
    transparently. With ``skip_op_plugin=True``, ``error_layer=op_plugin`` entries
    are skipped too: per-case debug stages (kernel_debug / vf_test /
    vector_error_debug) debug the kernel/tiling layer only, and a kernel-first
    routing decision (baseline ``has_kernel_failures`` priority) can leave
    adapter-layer cases in the same queue — spawning a per-case debug agent on
    one (whose kernel is provably correct under KernelLaunch) would be wasted
    work. op_plugin cases stay ``pending`` for op_plugin_debug after the kernel
    work converges (baseline re-runs and re-routes them).
    """
    if case.get("status") in ("skipped", "resolved"):
        return True
    if skip_op_plugin and case.get("error_layer") == "op_plugin":
        return True
    return False


def _has_pending_debuggable(cp: dict, *, skip_op_plugin: bool = False) -> bool:
    """Whether any pending/debugging queue entry remains for the current stage.

    Used for the per-case stop-loss "more cases?" decision: with
    ``skip_op_plugin=True`` only kernel-layer cases count, so an exhausted
    kernel_debug never loops on a queue whose only remaining failures are
    op_plugin-layer (those belong to op_plugin_debug after baseline re-runs).
    """
    queue = cp.get("failed_case_queue", []) or []
    return any(
        c.get("status") in ("pending", "debugging")
        and not _case_skip_for_debug(c, skip_op_plugin=skip_op_plugin)
        for c in queue
    )


def _advance_past_resolved(cp: dict, *, skip_op_plugin: bool = False) -> dict:
    """Advance ``current_case_index`` to the next pending/debugging case.

    ``resolved``/``skipped`` entries (reconciled away or exhausted) are skipped
    transparently so a per-case agent is never spawned for a case whose precision
    already passes. With ``skip_op_plugin=True``, ``error_layer=op_plugin``
    entries are also skipped (see ``_case_skip_for_debug``). Idempotent; sets the
    index to ``len(queue)`` when none remain.
    """
    queue = cp.get("failed_case_queue", []) or []
    idx = int(cp.get("current_case_index", 0) or 0)
    while idx < len(queue) and _case_skip_for_debug(
            queue[idx], skip_op_plugin=skip_op_plugin):
        idx += 1
    cp["current_case_index"] = idx
    return cp


def _load_latest_kl_data(state) -> dict:
    """Load the latest full KernelLaunch results for queue reconciliation.

    Precedence:
    1. ``{debug_dir}/baseline/result_{op_name}_summary.json`` — the file the
       KernelLaunch script actually writes (``per_case`` full list);
    2. ``{debug_dir}/baseline/kl_result.json`` — legacy harness/test layout
       (``all_results`` / ``failed_cases``).

    Returns ``{}`` when neither exists or neither parses.
    """
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _debug_artifacts_dir, _op_name,
    )
    d = _debug_artifacts_dir(state)
    if d is None:
        return {}
    candidates = [f"result_{_op_name(state)}_summary.json", "kl_result.json"]
    import json
    for name in candidates:
        p = d / "baseline" / name
        if not p.exists():
            continue
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
    return {}
