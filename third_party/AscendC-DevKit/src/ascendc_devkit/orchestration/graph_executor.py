"""L3 Orchestration — GraphExecutor: unified tree traversal + scoped routing."""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor

from ascendc_devkit.orchestration.node import (
    StageNode, AtomicStage, SequentialGroup, node_paths,
)
from ascendc_devkit.orchestration.node_forkjoin import ForkJoinGroup, merge_forkjoin
from ascendc_devkit.orchestration.issue_render import render_issue, render_issues
from ascendc_devkit.infra.log_capture import context_callable


# §P3/D6: console loop-back summary is a deterministic field-select + truncate of
# the gate's structured blocking_issues — NOT an LLM/NLP compression, so the log
# faithfully mirrors system state (no hallucination/latency/cost).
_SUMMARY_MAX_DETAIL = 80
_SUMMARY_MAX_ISSUES = 5


def _summarize_issue(issue: dict) -> str:
    """One blocking issue → ``[{code}→{target}{/template}] {truncated detail}``.

    Delegates to the shared render_issue (P25) so the loopback summary and the
    runner's iteration-reason share one deterministic renderer.
    """
    return render_issue(issue, _SUMMARY_MAX_DETAIL)


def _summarize_issues(issues: list[dict]) -> list[str]:
    """First N issue summaries + a ``(+k more, see events.jsonl)`` tail when
    truncated. Full set always stays in events.jsonl (the console never drops it)."""
    return render_issues(issues, detail_limit=_SUMMARY_MAX_DETAIL,
                         max_issues=_SUMMARY_MAX_ISSUES)


def _invalidate_subtree(ns: dict, child_path: str, child_node, targets=None) -> None:
    """Drop ``child_path`` (and, for a group node, its subtree) from ``ns``.

    The single primitive backing the clean-prefix causal-validity invariant
    (P52). Used by both loopback (runtime corrective rollback) and resume
    (stale-completed invalidation) — one mechanism, two trigger points (§1.2/§2.5).

    Mutates ``ns`` in place; the caller passes a fresh copy.
    ``targets``:
      - ``None``: clear the whole subtree (resume: invalidate everything downstream).
      - a collection of branch names: clear only those branches' immediate
        subtrees (loopback's template-precise rollback via ``rerun_selector``).
    AtomicStage has no subtree; only its own key is dropped.
    """
    ns.pop(child_path, None)
    if isinstance(child_node, AtomicStage):
        return
    prefix = child_path + "/"
    if targets is None:
        for k in [k for k in ns if k.startswith(prefix)]:
            ns.pop(k, None)
    else:
        for k in [k for k in ns if k.startswith(prefix)]:
            if k[len(prefix):].split("/", 1)[0] in targets:
                ns.pop(k, None)


def _invalidate_sequential_range(
        ns: dict, scope_path: str, order: list, by_name: dict,
        start_idx: int, end_idx: int, state,
        targets_of=None) -> None:
    """Invalidate ``order[start_idx:end_idx]`` nodes (+ subtrees) from ``ns``.

    Wraps :func:`_invalidate_subtree` over a SequentialGroup's ordered range:
      - loopback passes ``[target_idx, i+1)`` + a ``targets_of`` that honors each
        node's ``rerun_selector`` (equivalent to the former ad-hoc range clear).
      - resume passes ``[first_bad, len(order))`` + ``targets_of=None`` (a failed
        upstream invalidates its whole downstream, not selected branches).
    """
    for j in range(start_idx, end_idx):
        name = order[j]
        child_node = by_name[name]
        child_path = f"{scope_path}/{name}"
        targets = targets_of(child_node, state) if targets_of else None
        _invalidate_subtree(ns, child_path, child_node, targets)


def _rerun_targets_of(child_node, state):
    """Resolve a group node's ``rerun_selector(state)`` → branch-name targets.

    Loopback's template-precise rollback hook: when a group selects only some
    branches to rerun, just those branches' subtrees are invalidated and the
    rest stay completed (skip on re-entry). ``None`` (no selector) clears the
    whole subtree. Resume does NOT use this — it invalidates the whole downstream.
    """
    sel = getattr(child_node, "rerun_selector", None)
    return sel(state) if callable(sel) else None


# P51: classify a continue stage's uncaught crash for halt-vs-loopback routing.
# Binary by design — only *confidently-non-fixable* classes halt; everything
# else (codegen-fixable + genuine gray-zone) loops back (user preference: prefer
# wasting tokens over missing a fix; repeated gray-zone crashes are bounded by
# the stage's own exhausted→__halt__ stop-loss). The infra detection reuses the
# agent-layer text classifier (single source, P50); the framework detection keys
# on the deserialization signature — a Python primitive where a domain object
# was expected (the P48 shape) — which is a state-layer bug codegen cannot fix.
# See 30-verify-continue-crash-impl.md.
_FRAMEWORK_STATE_MARKERS = (
    "'dict' object has no attribute",
    "'list' object has no attribute",
    "'str' object has no attribute",
    "'int' object has no attribute",
    "'float' object has no attribute",
    "'tuple' object has no attribute",
    "'set' object has no attribute",
    "'NoneType' object has no attribute",
    "[PD-CONTRACT]",  # §12.2: precision_debug contract validation failure
)


def _classify_uncaught(exc: Exception) -> str:
    """Classify an uncaught stage exception (P51) → 'infra' | 'framework' |
    'unclassified'. Only confidently-non-fixable classes halt; the rest
    (including gray-zone) loop back. Infra detection reuses the agent-layer
    text classifier (single source)."""
    from ascendc_devkit.capabilities.agent.sdk_backend import _classify_error_type
    text = f"{type(exc).__name__}: {exc}"
    if _classify_error_type(text) == "infra":
        return "infra"
    if any(m in text for m in _FRAMEWORK_STATE_MARKERS):
        return "framework"
    return "unclassified"


def _is_non_fixable(cls: str) -> bool:
    """P51: a non-fixable crash class (infra / framework-state) halts."""
    return cls in ("infra", "framework")


def _capture_loopback_feedback(child, state):
    """If ``child`` is an AtomicStage gate with ``loopback_feedback``, write its
    structured issues into ``state._loopback_feedback`` for the loopback target's
    prompt to render (``## 上次反馈``). Shared by the corrective-jump path AND the
    escalate-bubble path — so a gate's feedback reaches both a same-scope
    corrective target (e.g. review→generator) and a pipeline-scope target reached
    via bubble (e.g. review design_input_invalid→requirement); otherwise the latter
    re-runs blind. P6-c extended from corrective-only to escalation. No-op when
    child is not a gate (group/non-gate substage)."""
    if isinstance(child, AtomicStage) and hasattr(child.stage, "loopback_feedback"):
        fb = child.stage.loopback_feedback(state)
        if fb is not None:
            return state.with_updates(_loopback_feedback=fb)
    return state


def _converge_precision_debug(state, node):
    """Converge a precision_debug group's working tree to best_commit on exit
    (rollback op_dir + redeploy → updated deploy_result). Shared by the except
    channel (architecture timeout) and the escalation channel so cannbench_eval
    reads a deploy_result pointing at best_commit, not the last (possibly-worst)
    fix HEAD. In-function import breaks the graph_executor ↔
    precision_debug_substages cycle. The caller decides *whether* to converge:
    except channel converges on any precision_debug timeout; escalation channel
    excludes ``upstream`` (no best_commit to converge to, matching
    _sync_debug_result's ``if not is_upstream``)."""
    variant = getattr(node, "variant", "") or "a3"
    if variant == "a5":
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            _converge_a5_to_best_commit,
        )
        return _converge_a5_to_best_commit(state)
    from ascendc_devkit.orchestration.stages.precision_debug_substages import (
        _converge_to_best_commit,
    )
    dc = getattr(state, "_debug_checkpoint", None) or {}
    return _converge_to_best_commit(state, dc)


class GraphExecutor:
    """Traverses a StageNode tree, driving Runner for atomic stages and
    applying scoped loop-back routing for groups."""

    def __init__(self, runner, event_log=None,
                 progress_callback=None, on_state_progress=None):
        self._runner = runner
        self._event_log = event_log
        self._progress_callback = progress_callback
        # P29/step-16: per-node callback that persists state_progress so the
        # on-disk snapshot reflects the latest completed frontier — a hard-killed
        # run then resumes from it (node_status is the sole resume authority).
        # Only the MAIN executor gets it; branch_exec (fork-join / side-task)
        # pass None so concurrent/partial branches never race the snapshot file.
        self._on_state_progress = on_state_progress
        self._side_futures: list = []
        self._side_pool: ThreadPoolExecutor | None = None
        # P128: cross-branch cancel token. Only a fork-join branch's executor gets
        # one (set by _execute_forkjoin on each branch_exec); the main executor
        # keeps None → _execute_atomic passes ctx=None → unchanged behavior. When
        # set, an atomic threads it into run_stage so a sibling's halt cancels this
        # branch cooperatively at the next iteration boundary.
        self._cancel_token = None
        # Most recent state seen mid-traversal. Lets the dispatcher read fields
        # set early (e.g. target_repo_baseline_ref from context) even when a later
        # stage raises a control-flow exception that aborts execute().
        self.latest_state = None

    def execute(self, root: StageNode, state):
        """Execute the whole tree starting at root. Returns final State."""
        self.latest_state = state
        state = self._execute_node(root, state, scope_prefix="")
        self._join_side_tasks()
        self.latest_state = state
        return state

    def _path(self, node: StageNode, scope_prefix: str) -> str:
        return node.name if not scope_prefix else f"{scope_prefix}/{node.name}"

    def _execute_node(self, node: StageNode, state, scope_prefix: str):
        path = self._path(node, scope_prefix)
        if state.node_status.get(path) == "completed":
            return state   # resume: already done (no change → no flush)
        # P29/step-16: capture the pre-dispatch frontier so we persist only on
        # actual progress. The post-dispatch flush is what makes a hard-killed
        # run resumable — state_snapshot.json ends up reflecting the last
        # completed node, so --resume skips it.
        prev_ns = dict(state.node_status)
        if isinstance(node, AtomicStage):
            state = self._execute_atomic(node, state, path)
        elif isinstance(node, ForkJoinGroup):
            state = self._execute_forkjoin(node, state, path)
        elif isinstance(node, SequentialGroup):
            state = self._execute_sequential(node, state, path)
        else:
            from ascendc_devkit.orchestration.node_sidetask import SideTask
            if isinstance(node, SideTask):
                self._launch_sidetask(node, state, scope_prefix)
                # SideTask is async; main-flow state is unchanged → the guard
                # below skips the flush (its own branch_exec has callback=None).
            else:
                raise TypeError(f"Unknown StageNode type: {type(node).__name__}")
        if state.node_status != prev_ns:
            # Keep latest_state current with the completion-marked frontier so
            # the dispatcher's control-exception handlers (Ctrl+C / cancel /
            # timeout / decision-pending) snapshot the LAST COMPLETED node, not
            # a stale pre-marker state (which would make resume re-run it).
            self.latest_state = state
            self._persist_progress(state)
        return state

    def _persist_progress(self, state) -> None:
        """Best-effort per-node snapshot flush (P29/step-16).

        Fires after each node completion so state_snapshot.json reflects the
        latest completed frontier — a hard-killed run then resumes from it
        instead of restarting from the top. Best-effort: a persist hiccup warns
        but never breaks the run (§1.2 — diagnosable, non-masking, yet a logging
        failure must not abort the pipeline).
        """
        if not self._on_state_progress:
            return
        try:
            self._on_state_progress(state)
        except Exception as e:  # noqa: BLE001 — observability must not break routing
            from ascendc_devkit.infra.logger import Logger
            Logger.warn(f"state-progress persist failed (non-fatal): {e}")

    def _execute_atomic(self, node: AtomicStage, state, path: str):
        # P3: set scope prefix on runner so stage_iteration/stage_done logs
        # disambiguate fork-join branches with the same stage.name (e.g.
        # "detailed-design/tiling/ContiguousSplit/split" vs.
        # "detailed-design/tiling/InterleaveBased/split").
        self._runner._scope_prefix = path
        try:
            # P128: when this executor is a fork-join branch (has a shared cancel
            # token), thread it into run_stage via a minimal ExecContext so the
            # runner's iteration-boundary _is_cancelled() honors a sibling's halt.
            # _run_stage_body reads only cancel_flag + the two deadlines from ctx
            # (None deadlines fall back to the runner's own logic), so a token-only
            # ctx is side-effect-free. Non-branch executors keep _cancel_token=None
            # → ctx=None → identical to before.
            ctx = None
            if self._cancel_token is not None:
                from ascendc_devkit.orchestration.exec_context import ExecContext
                from pathlib import Path
                ctx = ExecContext(workspace_dir=Path("."), current_node_path=path,
                                  cancel_flag=self._cancel_token)
            state = self._runner.run_stage(state, node.stage, ctx=ctx)
            self.latest_state = state
        except self._control_exceptions() as e:
            raise
        except Exception as e:
            # Tolerate an unexpected per-stage failure (control-flow exceptions
            # are re-raised above) — but do NOT mark the node "completed" as if
            # it succeeded (§P7.1). Mark it "failed" so: (a) it is not silently
            # resume-skipped on re-entry (resume keys on "completed"), and
            # (b) the console shows ✗ instead of ✓.
            from ascendc_devkit.infra.logger import Logger
            from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
            Logger.error(f"Stage '{node.name}' failed: {e}")
            Logger.stage_done(node.name, 0, status="failed")
            # P51: a hard crash short-circuits transition()/resolve_condition
            # (run_stage re-raised before transition ran), so route by the
            # failure's ROOT CAUSE, not by stale state (which would read as
            # "default" and advance downstream on broken state). Persist the
            # classified reason as last_error (diagnosable; name-scoped so a
            # downstream stage is not mis-marked). halt stages halt
            # unconditionally (P46, unchanged); a continue stage halts only on a
            # non-fixable crash (infra/framework-state) and otherwise funnels
            # into loopback via the stage's on_uncaught_failure hook (which
            # marks a crash-failed result + bumps the stage's iteration counter,
            # so its resolve_condition routing + exhausted→__halt__ stop-loss
            # engage). See 30-verify-continue-crash-impl.md.
            cls = _classify_uncaught(e)
            state = state.with_updates(
                node_status={**state.node_status, path: "failed"},
                last_error=ErrorFeedback(
                    stage_name=node.name, error_type=cls,
                    message=f"{type(e).__name__}: {e}"),
            )
            # P46: fail_strategy=halt halts on a hard crash (mirrors the
            # soft-failure halt in runner._run_stage_body, which a raised
            # exception bypasses). Format mirrors runner's
            # (_stage_failed=(stage_status, stage.name)).
            if getattr(node.stage, "fail_strategy", "continue") == "halt":
                state = state.with_updates(_stage_failed=("aborted", node.name))
            elif _is_non_fixable(cls):
                # P51: continue stage + non-fixable crash → halt (handoff).
                state = state.with_updates(_stage_failed=("aborted", node.name))
            else:
                # P51: continue stage + fixable/gray crash → loopback bookkeeping.
                state = node.stage.on_uncaught_failure(state, e)
            return state
        # P35: fail_strategy='halt' does NOT raise — runner only sets the
        # _stage_failed signal (kernel/runner.py). Without this check the halt
        # leaf would fall through to the "completed" mark below; _group_status
        # (which only looks for a "failed" child) would then propagate
        # "completed" to the root, and dispatcher resume — keying solely on
        # root node_status == "completed" — would misjudge all_done and silently
        # exit ("All stages already completed, regenerating report"), skipping
        # unrun downstream stages. Mirror the exception branch: mark "failed"
        # so _group_status propagates the halt up and the root stays
        # non-completed. (_execute_sequential still reads _stage_failed to set
        # is_terminal and stop the in-run traversal; this fix is about the
        # resume-authority marker, which is_terminal does not provide.)
        if getattr(state, "_stage_failed", None) is not None:
            return state.with_updates(
                node_status={**state.node_status, path: "failed"})
        state = state.with_updates(
            node_status={**state.node_status, path: "completed"})
        return state

    @staticmethod
    def _control_exceptions():
        """Exceptions that must propagate to the dispatcher (not swallowed)."""
        from ascendc_devkit.orchestration.kernel.runner import RunnerCancelledError
        from ascendc_devkit.domain.exceptions import (
            DecisionPendingError, EnvironmentNotAvailableError,
            WorkflowTimeoutError, StageTimeoutError, PreconditionError,
        )
        # P13 (step-116)：CardAcquireTimeout 已从传播清单移除——span 级带超时
        # acquire 全部退役，op 级租约 timeout=None（阻塞排队语义，不抛此异常）。
        return (RunnerCancelledError, DecisionPendingError,
                EnvironmentNotAvailableError, WorkflowTimeoutError,
                StageTimeoutError, PreconditionError,
                KeyboardInterrupt)

    def _group_status(self, node, state, path: str) -> str:
        """A group is "completed" only if no direct child ended up "failed".

        §P7.1: a swallowed per-stage failure marks the leaf "failed". Without this
        the enclosing group (and ultimately the workflow root) would still be
        marked "completed", so the run would exit as a clean success despite a
        broken stage. Propagating "failed" up the tree keeps the root non-completed
        (the dispatcher's resume authority) and lets a re-run pick up the failed
        leaf (resume skips only "completed" nodes). Bubbled-up halts use the
        separate is_terminal path and are not affected here.
        """
        ns = state.node_status or {}
        for child in node.children():
            if ns.get(self._path(child, scope_prefix=path)) == "failed":
                return "failed"
        return "completed"

    def _execute_sequential(self, node: SequentialGroup, state, path: str):
        from ascendc_devkit.domain.exceptions import (
            StageTimeoutError, WorkflowTimeoutError,
        )
        children = node.children()
        by_name = {c.name: c for c in children}
        order = [c.name for c in children]
        i = 0
        while i < len(order):
            # A child (possibly in a nested scope) may have signalled a terminal
            # halt; stop advancing this scope too so we don't run downstream
            # stages on known-broken state.
            if getattr(state, "is_terminal", False):
                break
            child = by_name[order[i]]
            child_path = self._path(child, scope_prefix=path)
            was_completed = state.node_status.get(child_path) == "completed"

            try:
                state = self._execute_node(child, state, scope_prefix=path)
            except (StageTimeoutError, WorkflowTimeoutError):
                # precision_debug 组内架构超时 → converge + escalate 而非硬退出
                if node.name == "precision_debug":
                    state = _converge_precision_debug(state, node)
                    state = state.with_updates(_bubble_condition="exhausted")
                    break
                raise

            # P2+P3: read fail_strategy halt signal and break the pipeline
            sf = getattr(state, "_stage_failed", None)
            if sf is not None:
                from ascendc_devkit.infra.logger import Logger
                sname = sf[1] if isinstance(sf, tuple) else "?"
                # P6-e: surface the concrete failure reason from last_error so the
                # operator can triage without opening events.jsonl.
                last_err = getattr(state, "last_error", None)
                reason = (
                    f": {last_err.message}"
                    if last_err is not None and getattr(last_err, "message", "")
                    else ""
                )
                Logger.warn(
                    f"Stage '{sname}' failed with fail_strategy=halt; "
                    f"stopping pipeline.{reason}")
                # design-halt-diagnostics P3: record which halt mechanism fired
                # so the dispatcher's terminal message can name the real
                # stage/reason instead of a single hardcoded generic text
                # written for the OTHER halt mechanism (__halt__ below).
                state = state.with_updates(
                    is_terminal=True, _stage_failed=None,
                    halt_reason={
                        "kind": "fail_strategy_halt", "stage": sname,
                        "message": (last_err.message
                                   if last_err is not None
                                   and getattr(last_err, "message", "") else "")})
                break

            # If the child was already completed (resume skip), do not resolve
            # a stale condition — just proceed linearly.
            if was_completed:
                i += 1
                continue

            # Resolve condition: a nested group may have bubbled one up.
            bubble = getattr(state, "_bubble_condition", "")
            if bubble and not isinstance(child, AtomicStage):
                condition = bubble
                # P42: the bubble's atomic ORIGIN (recorded at emission) is only
                # needed while routing this child — capture it locally, then clear
                # the transient so a stale origin can never leak into later routes.
                bubble_origin = getattr(state, "_bubble_origin", "")
                state = state.with_updates(_bubble_condition="",
                                           _bubble_origin="")  # consume
            else:
                condition = self._resolve_condition(child, state)
                bubble_origin = ""
            route = node.transition_table.get(child.name, {}).get(condition)
            if route is None:
                # P6-e: when a gate stage finally passes after corrective
                # loopbacks (route=None means no further loopback needed),
                # output a summary so the operator sees the rescue completed.
                if (not was_completed and isinstance(child, AtomicStage)):
                    stage_ = getattr(child, "stage", None)
                    if (stage_ is not None
                            and callable(getattr(stage_, "is_satisfied", None))):
                        scope_hist = state.scope(path).get("history", [])
                        past_loops = len([h for h in scope_hist
                                         if h.get("from") == child.name])
                        if past_loops > 0 and stage_.is_satisfied(state):
                            from ascendc_devkit.infra.logger import Logger
                            Logger.action(
                                "loopback",
                                f"{child.name} passed after {past_loops} "
                                f"corrective retries")
                i += 1
                continue

            target_name, route_type = route
            if target_name.startswith("__escalate__:"):
                # Bubble up: stop here, let parent route via returned condition.
                escalation_cond = target_name.split(":", 1)[1]
                # precision_debug 退出（非 upstream）→ 与 except 通道经同一 helper
                # (_converge_precision_debug) 一致 converge 到 best_commit
                # （rollback+redeploy 更新 deploy_result），否则 cannbench_eval 读到的
                # deploy_result 不指向 best_commit（cann-bench 评测读 deploy_result 不读
                # op_dir 源码；cannbench_adapt 仅 schema 偏离时 rebuild）。upstream 不收敛
                # （无 best_commit 可收敛，与 _sync_debug_result `if not is_upstream` 一致）；
                # passed 由 converge 内 status=="passed" 短路。
                if node.name == "precision_debug" and escalation_cond != "upstream":
                    # §step-91 P5: passed/exhausted/stalled 退出已由 transition 终态
                    # 收敛（_sync_debug_result）收敛到 best_commit，此处跳过重复收敛
                    # （ccad38 实证背靠背双收敛：同 commit 秒级间隔两次全量
                    # rollback+redeploy ~46s 空烧）。判据是业务语义标记
                    # _converged_this_pass（transition 声明），非条件名代理
                    # （§1.10）；abort/timeout 早退未设标记 → GE 兜底收敛保留。
                    if not getattr(state, "_converged_this_pass", False):
                        state = _converge_precision_debug(state, node)
                # §scope_guard visibility: when halted on upstream, surface the
                # scope_reason in the dispatcher terminal message so the user sees
                # WHY precision_debug refused to proceed (not just "escalated:upstream").
                if node.name == "precision_debug" and escalation_cond == "upstream":
                    dr = getattr(state, "debug_result", None)
                    hr_msg = (dr.halt_reason
                              if dr is not None and getattr(dr, "halt_reason", "")
                              else "upstream defect (no detail)")
                    state = state.with_updates(
                        halt_reason={"kind": "upstream_defect",
                                    "stage": child.name,
                                    "message": hr_msg})
                    from ascendc_devkit.infra.logger import Logger
                    Logger.error(f"precision_debug HALTED — {hr_msg}")
                # P6-c (escalation): carry the gate's loopback_feedback out too, so
                # the pipeline-scope target (e.g. requirement) sees what the gate
                # rejected — same mechanism as the corrective jump below.
                # B1: relay the gate's issue signature up the bubble so the
                # root-scope stagnation check (B2) can detect a gate re-reporting
                # the identical issue. `child` is still the in-group AtomicStage
                # (the gate) here; at root the child becomes the group and the
                # signature would be lost without this transient relay.
                bubble_sig = ""
                _child_stage = getattr(child, "stage", None)
                if _child_stage is not None and callable(
                        getattr(_child_stage, "error_signature", None)):
                    bubble_sig = _child_stage.error_signature(state) or ""
                state = _capture_loopback_feedback(child, state)
                # Atomic child = emission point (it owns the origin). A group
                # child RE-escalating a consumed bubble keeps the deeper origin
                # (bubble_origin local from the consumption branch above).
                state = state.with_updates(
                    _bubble_condition=escalation_cond,
                    _bubble_signature=bubble_sig,
                    _bubble_origin=(child_path if isinstance(child, AtomicStage)
                                    else bubble_origin))
                # P42 (supersedes the old P40 origin-mark): do NOT mark the
                # bubbling leaf "failed" here. The escalation's disposition is
                # decided by the scope that ROUTES it — a root transition table
                # may advance linearly (precision all_pass → successor), route
                # forward through a soft gate (precision exhausted →
                # cannbench_adapt), loop back (design gate → requirement; the
                # loopback's _invalidate_sequential_range governs re-runs), or
                # halt (__halt__). Marking at emission made every success/soft-
                # gate exit read as "Workflow completed with failed stages" and
                # exit non-zero (20260825-153847-ccad38: run_tests 20/20 ok,
                # events verdict ok, node_status failed). The failed-mark now
                # lands only where a halt is actually decided (the __halt__
                # branch below uses _bubble_origin) — preserving the P40 resume
                # contract (halt ⇒ origin leaf "failed" ⇒ resume re-enters it)
                # without defaming clean exits.
                break

            if target_name == "__halt__":
                # Terminal halt: the stage exhausted its corrective budget and
                # the failure class (compile/precision) is not one we want to
                # auto-escalate into a design rewrite. Stop the traversal
                # cleanly, mark the run terminal, and let the dispatcher report.
                # Remaining downstream stages (perf/integrate/finalize) are
                # intentionally skipped — running them on known-broken code is
                # worse than stopping.
                if self._event_log:
                    from ascendc_devkit.orchestration.kernel import event as evt
                    self._event_log.append(
                        evt.make_event("halt", scope=path,
                                       stage=child.name, condition=condition))
                # design-halt-diagnostics P3: record which halt mechanism fired
                # (distinct from the fail_strategy=halt branch above) so the
                # dispatcher's terminal message names the actual exhausted
                # stage/reason instead of a fixed generic text.
                # P3 (precision-tensorlist-harness-contract): prefer the SEMANTIC
                # halt reason (debug_result.halt_reason — scope_guard's upstream
                # scope_reason, non-empty ⟺ upstream) over a coincidental
                # last_error; otherwise an upstream halt got mis-reported as the
                # last exception (e.g. a run_tests transition TypeError), masking
                # the real cause. last_error stays a fallback for non-precision
                # halts (debug_result is None there → behavior unchanged).
                dr = getattr(state, "debug_result", None)
                semantic = (dr.halt_reason
                            if dr is not None and getattr(dr, "halt_reason", "")
                            else "")
                last_err = getattr(state, "last_error", None)
                last_err_msg = (last_err.message
                                if last_err is not None
                                and getattr(last_err, "message", "")
                                else "")
                halt_msg = semantic or last_err_msg or (
                    f"corrective/escalation quota exhausted at condition '{condition}'")
                # M3 (PR-42 review): judge upstream by the ROUTING condition
                # (resolve_condition's truth), not by debug_result.halt_reason —
                # a halt reached before debug_result materializes (e.g. the
                # pre-P1 transition crash) would otherwise mis-report an upstream
                # halt as corrective_exhausted. halt_reason stays the message.
                kind = ("upstream_defect" if condition == "upstream"
                        else "corrective_exhausted")
                state = state.with_updates(
                    is_terminal=True,
                    halt_reason={"kind": kind,
                                "stage": child.name, "message": halt_msg})
                # P40: mark the halting leaf "failed" in node_status. The stage
                # body completed normally (node_status already "completed" from
                # _execute_atomic), but routing chose to halt — a halted run must
                # NOT read as fully "completed", else the dispatcher's resume
                # authority (root node_status=="completed") short-circuits with
                # "All stages already completed" and the halted leaf is never
                # re-entered on resume. Mirror the P35/_stage_failed contract
                # (L340-342): halt ⇒ leaf "failed" ⇒ _group_status propagates
                # failed to the root ⇒ resume re-runs the halting leaf.
                state = state.with_updates(
                    node_status={**state.node_status, child_path: "failed"})
                # P42: when the halting condition arrived as an escalation
                # bubble, ALSO mark the atomic ORIGIN that emitted it — the
                # direct child here is the group, whose body merely relayed the
                # bubble; resume must re-enter the origin leaf (e.g. diagnose
                # that reported upstream), not just the group wrapper. This is
                # the only place an escalation earns a failed-mark: the halt
                # decision is made here, so ownership is decidable (§1.10 —
                # disposition-declared, not inferred from the condition name).
                if bubble_origin:
                    state = state.with_updates(
                        node_status={**state.node_status, bubble_origin: "failed"})
                break

            if route_type == "advisory":
                # P0/D1 (36-*.md §1): forward advisory — pure information carry,
                # NO control-flow change. This round's outstanding issues whose
                # target == the advisory's owner are appended to
                # pending_advisories for the owner to consume in its own prompt.
                # No corrective/escalation quota, no invalidate, no backward
                # jump. The owner-capability judgment lives in the skill (D8);
                # the router only forwards what the skill already tagged.
                stage_ = getattr(child, "stage", None)
                forwarded = []
                if (stage_ is not None
                        and callable(getattr(stage_, "blocking_issues", None))):
                    forwarded = [i for i in stage_.blocking_issues(state)
                                 if i.get("target") == target_name]
                if forwarded:
                    pa = list(state.pending_advisories or [])
                    for _issue in forwarded:
                        pa.append({
                            "code": _issue.get("code"),
                            "target": _issue.get("target"),
                            "detail": _issue.get("detail"),
                            "remediation": _issue.get("remediation"),
                            "acceptance": _issue.get("acceptance"),
                            "owner_ambiguous": bool(
                                _issue.get("owner_ambiguous", False)),
                            "from_stage": child.name,
                        })
                    state = state.with_updates(pending_advisories=pa)
                if self._event_log:
                    from ascendc_devkit.orchestration.kernel import event as evt
                    self._event_log.append(evt.make_event(
                        "advisory", scope=path, stage=child.name,
                        target=target_name, count=len(forwarded)))
                # D9: a gray-area (owner-ambiguous) advisory defaults forward but
                # is surfaced — never silently swallowed (operator decides).
                from ascendc_devkit.infra.logger import Logger
                ambiguous = any(i.get("owner_ambiguous") for i in forwarded)
                tag = " [owner_ambiguous: 已前投，待人工裁定]" if ambiguous else ""
                Logger.action("advisory", (
                    f"{child.name} → {target_name} "
                    f"({len(forwarded)} issue(s) forward){tag}"))
                i += 1
                continue

            scope = state.scope(path)
            target_idx = order.index(target_name)
            # Reverse validation guard: a "validation" edge is normally a
            # forward re-validation that never counts as a loop-back. But a
            # validation edge that jumps BACKWARD (target before current, e.g.
            # perf→verify "tuned") is a genuine loop and must be quota-bounded,
            # or it can spin forever. We meter such reverse-validation edges
            # against the corrective budget (a re-validation is closer to a
            # corrective retry than a strategic escalation, and we avoid
            # polluting the scarce escalation quota / its reporting).
            effective_type = route_type
            if route_type == "validation" and target_idx < i:
                effective_type = "corrective"

            count = scope["corrective"] if effective_type == "corrective" else scope["escalation"]
            is_root = (path == node.name and "/" not in path)
            if is_root:
                cap = state.max_corrective if effective_type == "corrective" else state.max_escalations
            else:
                cap = node.max_corrective if effective_type == "corrective" else node.max_escalations

            if count >= cap:
                # Quota exhausted in this scope → stop routing, proceed forward.
                i += 1
                continue

            # Stagnation: same (from→to, sig) appearing >= 2 times → stop routing,
            # proceed forward. Symmetric for corrective (in-group loopback) AND
            # escalation (gate bubble to root): a gate re-reporting the identical
            # issue can't spin to max_escalations (B2 — closes the asymmetry where
            # escalation was excluded at 587 and the gate signature never reached
            # root scope because root's child is the group, not an AtomicStage).
            sig = ""
            if isinstance(child, AtomicStage) and hasattr(child.stage, "error_signature"):
                sig = child.stage.error_signature(state) or ""
            elif effective_type == "escalation":
                # Root's child here is the bubbling group (not AtomicStage), so the
                # gate signature can't be read directly — it rode the bubble up as
                # _bubble_signature (B1, captured at the escalate branch above).
                sig = getattr(state, "_bubble_signature", "") or ""
            if sig:
                same = sum(1 for h in scope["history"]
                           if h.get("from") == child.name
                           and h.get("to") == target_name
                           and h.get("sig") == sig)
                if same >= 2:   # this would be the 3rd → stop
                    if self._event_log:
                        from ascendc_devkit.orchestration.kernel import event as evt
                        self._event_log.append(evt.stagnation(path, child.name, target_name))
                    i += 1
                    continue

            # Apply counter + history, write event, jump to target index.
            # P6-c: inject structured loopback feedback from the gate stage into
            # State (the target's _build_prompt renders it as 「## 上次反馈」).
            state = _capture_loopback_feedback(child, state)
            history = list(scope["history"])
            history.append({"from": child.name, "to": target_name,
                            "type": route_type, "condition": condition,
                            "sig": sig})
            new_corr = count + 1 if effective_type == "corrective" else scope["corrective"]
            new_esc = count + 1 if effective_type == "escalation" else scope["escalation"]
            state = state.with_scope_counters(
                path, corrective=new_corr, escalation=new_esc,
                history=history, last_sig=scope["last_sig"])
            if self._event_log:
                from ascendc_devkit.orchestration.kernel import event as evt
                self._event_log.append(evt.loopback(
                    path, child.name, target_name, route_type,
                    new_corr if effective_type == "corrective" else new_esc, cap))
            # §P3/D6: echo the loop-back to the console (the event_log above is
            # jsonl-only). The deterministic blocking_issues summary turns the
            # previously black-box rerun into a visible "why". Full issues stay in
            # events.jsonl; the console shows the first N + a "(+k more)" tail.
            self._log_loopback(child, state, target_name, route_type,
                               new_corr if effective_type == "corrective" else new_esc,
                               cap)
            # Clear node_status for the re-executed range so the resume-skip
            # does not skip nodes we loop back through. For a group child, pop the
            # group key alone is not enough: its subtree keys (.../tiling/T1/...)
            # stay completed → re-entry's pending is empty → the rerun is a silent
            # no-op (C3, R8 follow-up). So also clear the group's whole subtree.
            # A group may expose rerun_selector(state) → set of branch names to
            # rerun; then clear ONLY those branches' subtrees (template-precise
            # rollback, C4) and leave the rest completed so they skip on re-entry.
            #
            # P52: this is the loopback trigger point of the unified clean-prefix
            # primitive (_invalidate_sequential_range). Resume is the other
            # trigger point; both share one mechanism (§1.2/§2.5).
            cleared = dict(state.node_status)
            _invalidate_sequential_range(
                cleared, path, order, by_name, target_idx, i + 1, state,
                targets_of=_rerun_targets_of)
            state = state.with_updates(node_status=cleared)
            i = target_idx

        state = state.with_updates(
            node_status={**state.node_status, path: self._group_status(node, state, path)})
        return state

    def _log_loopback(self, child, state, target_name, route_type, count, cap):
        """Console echo of a loop-back: header line + deterministic issue summary.

        Pulls structured blocking_issues from the gate stage's blocking_issues()
        hook (domain judgment stays in the stage). Best-effort: never blocks
        routing on a logging/summary error.
        """
        from ascendc_devkit.infra.logger import Logger
        from_name = getattr(child, "name", "?")
        Logger.action(
            "loopback",
            f"{from_name} → {target_name} ({route_type} {count}/{cap})")
        try:
            stage = getattr(child, "stage", None)
            issues = stage.blocking_issues(state) if stage is not None else []
            for line in _summarize_issues(issues):
                Logger.action("loopback", f"  {line}")
        except Exception as e:  # noqa: BLE001 — observability never breaks routing
            Logger.warn(f"loopback summary unavailable: {e}")

    def _resolve_condition(self, node, state) -> str:
        if isinstance(node, AtomicStage):
            return node.stage.resolve_condition(state)
        if isinstance(node, SequentialGroup):
            return "default"
        return "default"

    def _execute_forkjoin(self, node: ForkJoinGroup, state, path: str):
        # Dynamic fork-join (step-2b B'): branch_factory(state) expands branches
        # from state at execute time; static nodes return children_list. resume
        # rebuilds the same branches from the same state.template_division →
        # node_status keys match → completed branches still skip.
        main_children = (node.resolved_children(state)
                         if hasattr(node, "resolved_children")
                         else list(node.children()))
        # Resume: skip already-completed branches.
        pending = [(i, c) for i, c in enumerate(main_children)
                   if state.node_status.get(self._path(c, path)) != "completed"]

        if self._event_log:
            from ascendc_devkit.orchestration.kernel import event as evt
            self._event_log.append(evt.make_event(
                "forkjoin_start", scope=path,
                children=[c.name for c in main_children]))

        start = time.monotonic()
        results: list = [None] * len(main_children)

        # P128: one cancel token shared by all sibling branches. The moment ANY
        # branch returns a FAILED/terminal outcome the join is going to halt
        # (any_failed → is_terminal below), so the other branches are 确定无用的
        # 空烧 (softmax T3 空烧 28min). Fire the token then; each still-running
        # branch's runner sees it at its next iteration boundary (cooperative — an
        # in-flight spawn within the current iteration is NOT hard-killed) and a
        # not-yet-started branch skips entirely. §1.10: the trigger is the business
        # semantic "a sibling branch failed", not a mechanism proxy.
        from ascendc_devkit.orchestration.exec_context import CancelToken
        from ascendc_devkit.orchestration.kernel.runner import RunnerCancelledError
        cancel_token = CancelToken()

        def _run(idx_child):
            idx, child = idx_child
            # Already cancelled by a sibling's halt → don't even start (branch
            # stays pending: returns None → not marked completed → resume reruns).
            if cancel_token.is_cancelled():
                return idx, None
            # Each branch gets an isolated Runner so mutable instance fields
            # (_current_stage_name / _cancelled / _stage_deadline) are not
            # clobbered across threads.
            branch_exec = GraphExecutor(
                runner=self._branch_runner(),
                event_log=self._event_log,
                progress_callback=self._progress_callback,
                on_state_progress=None)
            # P128: thread the shared token so this branch's atomics honor it.
            branch_exec._cancel_token = cancel_token
            try:
                return idx, branch_exec._execute_node(child, state, scope_prefix=path)
            except RunnerCancelledError:
                # We (a sibling's halt) cancelled this branch — swallow at the
                # branch boundary (internal cancellation, not a user Ctrl+C) and
                # leave it pending. Guard on the token so a cancel from any OTHER
                # source still propagates (diagnosable, not silently eaten).
                if cancel_token.is_cancelled():
                    return idx, None
                raise

        # A branch's THIS-PASS outcome is "failed" when it returns a failed branch
        # node_status or a terminal state (fail_strategy=halt in an inner stage).
        # A cancelled/not-started branch returns None and is neither ok nor failed.
        def _branch_failed(child, cstate):
            return cstate is not None and (
                cstate.node_status.get(self._path(child, path)) == "failed"
                or getattr(cstate, "is_terminal", False))

        if node.concurrency == "1":
            for ic in pending:
                idx, cstate = _run(ic)
                results[idx] = cstate
                # A failed branch cancels the rest: subsequent _run calls short-
                # circuit to None (pending), so serial siblings stop launching too.
                if _branch_failed(main_children[idx], cstate):
                    cancel_token.cancel()
        else:
            max_workers = min(len(pending) or 1, os.cpu_count() or 1)
            # AU-8: one fresh context copy per branch, captured HERE in the
            # dispatch thread (where the run.log/op_name binding is active). A
            # single shared Context can't be entered by two workers at once
            # (CPython "already entered"), so wrap per-item — each worker enters
            # its own copy and the branch's Logger output (incl. agent_stream)
            # reaches per-op run.log instead of being dropped by the worker's
            # otherwise-empty contextvars context.
            # P128: submit + as_completed (not pool.map wait-all) so a branch's
            # failure fires the cancel token the instant it lands, not after every
            # branch finishes.
            from concurrent.futures import as_completed
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futs = {pool.submit(context_callable(_run), ic): ic for ic in pending}
                for fut in as_completed(futs):
                    idx, cstate = fut.result()
                    results[idx] = cstate
                    if _branch_failed(main_children[idx], cstate):
                        cancel_token.cancel()

        ran_children = [main_children[i] for i, _ in pending]
        ran_states = [results[i] for i, _ in pending]

        # step-60 (A/B): classify each ran branch by its OWN returned outcome.
        # A halted branch (fail_strategy=halt in an inner stage) returns
        # node_status[branch]="failed" and, wrapped in a SequentialGroup,
        # is_terminal + halt_reason. The failed branch's node_status lives in the
        # returned branch state — merge_forkjoin folds only `provides`, not branch
        # node_status — so we carry it explicitly below. A cancelled branch
        # (cstate is None) is neither ok nor failed → it stays pending.
        ok_children, ok_states, failed_branches, cancelled_children = [], [], [], []
        for child, cstate in zip(ran_children, ran_states):
            if cstate is None:
                cancelled_children.append(child)     # P128: cancelled → pending
            elif _branch_failed(child, cstate):
                failed_branches.append((child, cstate))
            else:
                ok_children.append(child)
                ok_states.append(cstate)

        # (B) Merge ONLY succeeded branches. A failed branch never wrote its
        # provides (value stayed None), so letting it reach merge would surface
        # that None as a phantom non-dict write colliding with a succeeded
        # sibling's dict (StateConflictError, step-60 P1). Succeeded siblings'
        # results still fold in and persist → resume skips them.
        merged = merge_forkjoin(state, ok_children, ok_states)

        # Mark each branch path from its THIS-PASS outcome (step-60): failed if it
        # failed now, else completed. A base "failed" branch is always pending
        # (resume reruns any non-"completed" node), so a successful rerun MUST
        # clear it — never preserve a stale base "failed" for a branch that just
        # reran (that would strand it failed forever across resumes).
        ns = dict(merged.node_status)
        # P127: fold each ran branch's INNER node_status sub-keys into the join's
        # node_status. merge_forkjoin folds only `provides`; without carrying the
        # branch-internal keys, a branch whose early inner nodes completed but a
        # later one failed loses those completions at the join → resume can't see
        # ".../T1/split=completed" and reruns the whole branch from scratch (the
        # 80-min death loop). Keys returned by the branch's _execute_node are
        # already fully qualified under the branch path, so a prefix match carries
        # exactly this branch's subtree.
        for child, cstate in zip(ran_children, ran_states):
            if cstate is None:
                continue   # P128: cancelled branch carried no state to fold
            bp = self._path(child, path)
            for k, v in cstate.node_status.items():
                if k.startswith(bp + "/"):
                    ns[k] = v
        failed_paths = {self._path(c, path) for c, _ in failed_branches}
        cancelled_paths = {self._path(c, path) for c in cancelled_children}
        for c in main_children:
            cp = self._path(c, path)
            if cp in cancelled_paths:
                continue   # P128: leave cancelled sibling pending → resume reruns
            ns[cp] = "failed" if cp in failed_paths else "completed"
        merged = merged.with_updates(node_status=ns)

        # The fork-join node is "completed" only if no branch failed.
        any_failed = any(ns.get(self._path(c, path)) == "failed"
                         for c in main_children)

        # (A+C) A failed branch halts the fork-join: lift its terminal signal to
        # the merged state so the parent SequentialGroup stops (is_terminal break)
        # instead of advancing to downstream siblings on a partial merge (step-60
        # P2). Reuse step-50 halt_reason + the dispatcher terminal message. C:
        # name the failed branch(es) so the halt is diagnosable, not a crash.
        if failed_branches:
            from ascendc_devkit.infra.logger import Logger
            fc, fcs = failed_branches[0]
            inner = getattr(fcs, "halt_reason", None) or {}
            seg = inner.get("stage")
            hr = {
                "kind": inner.get("kind", "fail_strategy_halt"),
                # Qualify with the branch (template) name so the terminal message
                # names WHICH branch failed, not just the shared inner segment
                # (every template has a "split"). step-60 C: diagnosable halt.
                "stage": f"{fc.name}/{seg}" if seg else fc.name,
                "message": inner.get("message") or f"fork-join 分支 '{fc.name}' 失败",
            }
            merged = merged.with_updates(is_terminal=True, halt_reason=hr)
            for fc, _ in failed_branches:
                Logger.warn(
                    f"ForkJoin 分支 '{fc.name}' 失败，join 处停止管线："
                    f"{hr.get('message', '')}")

        merged = merged.with_updates(
            node_status={**merged.node_status,
                         path: "failed" if any_failed else "completed"})
        if self._event_log:
            from ascendc_devkit.orchestration.kernel import event as evt
            self._event_log.append(evt.make_event(
                "forkjoin_complete", scope=path,
                total_elapsed_ms=int((time.monotonic() - start) * 1000)))
        return merged

    def _branch_runner(self):
        """Build a fresh Runner sharing the template runner's deps but with its
        own mutable state, so parallel branches don't clobber each other."""
        from ascendc_devkit.orchestration.kernel.runner import Runner
        t = self._runner
        return Runner(
            workflow=getattr(t, "_workflow", None),
            agent_backend=getattr(t, "_agent_backend", None),
            workspace=getattr(t, "_workspace", None),
            adapters=dict(getattr(t, "_adapters", {}) or {}),
            decision_handler=getattr(t, "_decision_handler", None),
            gate_registry=getattr(t, "_gate_registry", None),
            progress_callback=getattr(t, "_progress_callback", None))

    def _launch_sidetask(self, side_task, state, scope_path):
        from ascendc_devkit.orchestration.node_sidetask import SideTask
        if self._side_pool is None:
            self._side_pool = ThreadPoolExecutor(max_workers=4)
        snapshot = state   # frozen → safe read-only snapshot
        if self._event_log:
            from ascendc_devkit.orchestration.kernel import event as evt
            self._event_log.append(evt.make_event(
                "sidetask_start", scope=scope_path, task=side_task.name))

        def _run():
            branch_exec = GraphExecutor(
                runner=self._branch_runner(),
                event_log=self._event_log,
                progress_callback=self._progress_callback,
                on_state_progress=None)
            try:
                branch_exec._execute_node(side_task.task, snapshot,
                                          scope_prefix=f"{scope_path}#side")
                status = "ok"
            except Exception:
                status = "failed"
            if self._event_log:
                from ascendc_devkit.orchestration.kernel import event as evt
                self._event_log.append(evt.make_event(
                    "sidetask_complete", scope=scope_path,
                    task=side_task.name, status=status))

        fut = self._side_pool.submit(context_callable(_run))  # AU-8: inherit run.log/op_name binding into the side-task pool worker
        self._side_futures.append((fut, side_task.timeout_sec,
                                    side_task.name, scope_path))

    def _join_side_tasks(self):
        from concurrent.futures import TimeoutError as FTimeout
        for fut, timeout_sec, name, scope in self._side_futures:
            try:
                fut.result(timeout=timeout_sec)
            except FTimeout:
                if self._event_log:
                    from ascendc_devkit.orchestration.kernel import event as evt
                    self._event_log.append(evt.make_event(
                        "sidetask_complete", scope=scope, task=name,
                        status="timeout"))
        if self._side_pool is not None:
            self._side_pool.shutdown(wait=False)
            self._side_pool = None
        self._side_futures = []
