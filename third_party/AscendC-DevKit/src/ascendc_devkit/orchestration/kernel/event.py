"""L3 Orchestration — Event schema for events.jsonl."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def make_event(event_type: str, **kwargs: Any) -> dict:
    event = {"ts": datetime.now(timezone.utc).isoformat(), "type": event_type}
    event.update(kwargs)
    return event


def stage_enter(stage_name: str, stage_index: int, total: int) -> dict:
    return make_event("stage_enter", stage=stage_name, stage_index=stage_index, total=total)


def stage_complete(stage_name: str, elapsed_ms: int, **kwargs) -> dict:
    return make_event("stage_complete", stage=stage_name, elapsed_ms=elapsed_ms, **kwargs)


def stage_aborted(stage_name: str, elapsed_ms: int, error_type: str, **kwargs) -> dict:
    """Emitted when a stage exits via unhandled exception.

    ``error_type`` is the exception class name (e.g. ``"PreconditionError"``)
    so downstream tooling can filter by failure category without adding new
    event types.
    """
    return make_event("stage_aborted", stage=stage_name, elapsed_ms=elapsed_ms,
                      error_type=error_type, **kwargs)


def action_start(action_type: str, **kwargs) -> dict:
    return make_event("action_start", action=action_type, **kwargs)


def action_complete(action_type: str, result: str, **kwargs) -> dict:
    return make_event("action_complete", action=action_type, result=result, **kwargs)


def iteration_start(stage_name: str, iteration: int, **kwargs) -> dict:
    return make_event("iteration_start", stage=stage_name, iteration=iteration, **kwargs)


def iteration_complete(stage_name: str, iteration: int, result: str, **kwargs) -> dict:
    return make_event("iteration_complete", stage=stage_name,
                       iteration=iteration, result=result, **kwargs)


def artifact_missing_retry(stage_name: str, error_type: str, attempt: int,
                           max_retries: int, message: str) -> dict:
    """R2 (2026-08-21): 产物契约未满足触发独立 artifact-retry 的可观测事件。

    Emitted by runner when a stage's last_error is an artifact-retry class
    (missing_artifact / incomplete_output) and the independent budget is not
    exhausted. Lets operators see "重试发生了、第几次、还剩几次、为什么" without
    opening run.log — previously retries were silent (only spawn/iteration
    repeats), indistinguishable from a fresh spawn (§1.2 可诊断).
    """
    return make_event(
        "artifact_missing_retry", stage=stage_name, error_type=error_type,
        attempt=attempt, max=max_retries, message=message)


def workflow_complete(workflow_name: str, total_elapsed_ms: int) -> dict:
    return make_event("workflow_complete", workflow=workflow_name,
                       total_elapsed_ms=total_elapsed_ms)


def decision_pending(stage_name: str, iteration: int, question: str) -> dict:
    return make_event("decision_pending", stage=stage_name,
                       iteration=iteration, question=question)


def chip_decision(design_chip: str, design_source: str,
                  runtime_chip: str, runtime_source: str,
                  mismatch: bool) -> dict:
    """Record how the design/runtime chip targets were resolved (step-34 D8).

    Emitted once per new run, at dispatch, right after the dual-field
    resolution. ``mismatch`` flags a design≠runtime split (the cross-generation
    situation the pre-design gate and codegen build gate guard). Sources:
    design ∈ {"cli", ""} (other authority layers apply downstream in
    context/requirement, after this event); runtime ∈ {"probe",
    "timeout_fallback"}.
    """
    return make_event(
        "chip_decision",
        design_chip=design_chip, design_source=design_source,
        runtime_chip=runtime_chip, runtime_source=runtime_source,
        mismatch=mismatch)


def env_warning(stage_name: str, reason: str, **kwargs) -> dict:
    return make_event("env_warning", stage=stage_name, reason=reason, **kwargs)


def artifact_relocated(stage_name: str, filename: str,
                       from_path: str, to_path: str, outcome: str) -> dict:
    """Emitted when the framework relocates a transcript-evidenced orphan
    product back into its locator root (artifact-location-provenance, in-place
    deterministic repair — same-iteration self-heal; see
    orchestration/artifact_recovery.py). outcome ∈ {"moved", "idempotent_skip",
    "refused_target_exists", "orphan_gone"} so every recovery attempt is
    auditable from events.jsonl alone, without opening run.log."""
    return make_event("artifact_relocated", stage=stage_name,
                      filename=filename, from_path=from_path,
                      to_path=to_path, outcome=outcome)


def stage_skipped(stage_name: str, reason: str) -> dict:
    return make_event("stage_skipped", stage=stage_name, reason=reason)


def workflow_timeout(stage_name: str, deadline: float) -> dict:
    return make_event("workflow_timeout", stage=stage_name, deadline=deadline)


def stage_timeout(stage_name: str, deadline: float) -> dict:
    return make_event("stage_timeout", stage=stage_name, deadline=deadline)


def run_started(run_id: str, provenance: dict, **kwargs) -> dict:
    """Run-level opener emitted ONCE at dispatch, before the first stage_enter.

    Carries the Provenance summary so a foreign events.jsonl is self-describing
    from its first line — a reviewer reads commit / backend / env / runtime
    config / warnings without opening any other file. Mirrors the immutable
    PROVENANCE.json (events.jsonl is the authoritative record; run.log is only
    a best-effort tee). step-67.
    """
    return make_event("run_started", run_id=run_id, provenance=provenance, **kwargs)


def run_resumed(run_id: str, provenance: dict, resumed_from: str,
                changes: dict, **kwargs) -> dict:
    """Run-level opener emitted at dispatch when RESUMING a prior run (bug1,
    step-68). The first run's PROVENANCE.json stays immutable; this event
    records the re-probed-at-resume provenance plus a diff against the first
    (``changes``), so a reviewer sees what moved between the runs — a DevKit
    upgrade, a CANN/torch_npu bump, a config change — without the resume
    silently overwriting the original version identity.

    ``changes`` keys (each present only when that axis drifted):
    ``commit_changed`` / ``backend_changed`` / ``output_limit_changed`` /
    ``skill_fingerprint_changed`` / ``environment_changed``, each carrying an
    ``{old, new}`` payload under its axis name. See
    ``infra.provenance.diff_provenance``.
    """
    return make_event("run_resumed", run_id=run_id, provenance=provenance,
                      resumed_from=resumed_from, changes=changes, **kwargs)


def output_truncated(agent_name: str, turn: int, reason: str,
                     stage: str = "", session_id: str = "") -> dict:
    """Emitted when a backend detects an agent's turn was cut short by a length
    signal (finish_reason/stop_reason == max_tokens or equivalent) — the
    silent-truncation culprit (e.g. opencode.json limit.output=8192). Per-turn so
    the exact agent+round is locatable, not just a run-level aggregate. step-67."""
    return make_event("output_truncated", agent=agent_name, turn=turn,
                      reason=reason, stage=stage, session_id=session_id)


def op_card_leased(op_name: str, card: int, run_id: str) -> dict:
    """Emitted once per op when the op-level NPU card lease is acquired
    (step-116). events.jsonl is the authoritative op→card mapping — a
    post-batch collision audit (two ops on one card / card 0 crowding) reads
    this line, not run.log."""
    return make_event("op_card_leased", op_name=op_name, card=card,
                      run_id=run_id)


def agent_compacted(agent_name: str, count: int, stage: str = "") -> dict:
    """Per-spawn context-compaction record (step-113 observability; review
    remediation M8: into events.jsonl, previously only in the discarded
    AgentResult.metrics). Emitted only when count>0 — the denominator (total
    spawns) is carried by the existing per-spawn events, so a compaction RATE
    is derivable from events alone; absent = zero or unobserved SSE."""
    return make_event("agent_compacted", agent=agent_name, count=count,
                      stage=stage)


def agent_aborted(agent_name: str, reason: str, stage: str = "") -> dict:
    """Emitted when a backend aborts a spawn via a hard kill (D4) — the
    agent was killed mid-run, NOT a logic failure. Per-spawn so the exact
    agent+stage is locatable in events.jsonl. ``reason`` ∈ {"hard_timeout",
    "cancelled", "keepalive", "turn_stall"} (mirrors ``AgentResult.aborted``;
    §P9: the label is the TRUE kill kind — one error never masquerades as
    another). See hard-timeout-and-graceful-shutdown L3 D3/D4."""
    return make_event("agent_aborted", agent=agent_name, reason=reason,
                      stage=stage)


def spawn_context(agent_name: str, prompt: str, context_keys: list[str],
                  skills: list[str], working_dir: str,
                  transcript: str = "", session_id: str = "") -> dict:
    """``transcript`` (rel path ``agents/<agent>-<seq>.jsonl``) and ``session_id``
    tie this spawn's events.jsonl action to its agent transcript file + the
    backend's native session — without them a foreign reviewer cannot map a
    failed action to its session (step-67). Empty when no workspace/transcript."""
    return make_event("spawn_context", agent=agent_name, prompt=prompt[:500],
                      context_keys=context_keys, skills=skills,
                      working_dir=working_dir, transcript=transcript,
                      session_id=session_id)


def node_enter(path: str) -> dict:
    return make_event("node_enter", path=path)


def node_complete(path: str, elapsed_ms: int, **kwargs) -> dict:
    return make_event("node_complete", path=path, elapsed_ms=elapsed_ms, **kwargs)


def loopback(scope: str, from_node: str, to_node: str, route_type: str,
             count: int, max_count: int) -> dict:
    return make_event("loopback", scope=scope, from_node=from_node,
                      to_node=to_node, route_type=route_type,
                      count=count, max=max_count)


def stagnation(scope: str, from_node: str, to_node: str) -> dict:
    return make_event("stagnation", scope=scope, from_node=from_node,
                      to_node=to_node)
