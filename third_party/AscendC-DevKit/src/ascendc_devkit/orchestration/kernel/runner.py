"""L3 Orchestration — Runner: main loop with side-effect isolation."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from ascendc_devkit.infra.event_log import EventLog
from ascendc_devkit.infra.logger import Logger
from ascendc_devkit.orchestration.issue_render import render_issues
from ascendc_devkit.domain.exceptions import (
    DecisionPendingError, WorkflowTimeoutError, StageTimeoutError,
    PreconditionError,
)
from .state import State, ErrorFeedback
from .action import SpawnAgent, RunGate, Integrate, AskUserQuestion, NoOp, Action, UpdateDevRecord, RunMeasure
from . import event as evt
from ascendc_devkit.capabilities.agent._shared import is_infra_failure

if TYPE_CHECKING:
    from ascendc_devkit.capabilities.agent.backend import AgentBackend
    from ascendc_devkit.orchestration.base import Stage, StageProtocol


class ContractViolationError(Exception):
    """Stage wrote a field not declared in its output_contract."""
    pass


# 20260810 批根因修复 Part 3 — cut 计数阈值：连续 silent-cut（Part 1 检测的
# thinking-only 终止）且 resume（Part 2 自动续跑）仍失败的次数上限。cut 不烧正常
# 迭代预算（可恢复的中断不是逻辑失败），但连续到阈值即放弃 cut-recovery（网关过
# 不稳，无法推进）→ 循环退出，stage 以契约未满足收尾。成功（产出产物）或真失败
# （自然结束）都会打断 streak 清零——计数器只表示"连续 resume 仍失败"。
# 阈值收敛进 orchestration-config retry_budgets.cut_streak_threshold（§1.15 方案 B，
# 2026-08-21）；模块常量 MAX_CUT_STREAK 删除（§1.4 不留兼容别名）。


def cut_streak_threshold() -> int:
    """连续 silent-cut 放弃 cut-recovery 的阈值（retry_budgets 统一组）。"""
    from ascendc_devkit.orchestration.runtime_config import retry_budgets
    return retry_budgets()["cut_streak_threshold"]


class RunnerCancelledError(Exception):
    """Runner was cancelled mid-execution."""
    pass


# §step-95 (docs/plan/npu-card-lease-lifecycle/): 迭代级租约的防未知最后防线。
# 对称化后 in-process「死等」（租约持有者非活跃）已结构性不可能，剩余等待必然
# 是真忙（用户语义：活跃占用 = 正常等待，不 abort）；有界超时仅兜未知的非对称
# 路径——触发时 CardAcquireTimeout 消息自带 holders 诊断，诚实失败而非静默挂死。
def _unsatisfied_contract_fields(state: State, provides: list[str]) -> list[str]:
    """Subset of ``provides`` that ``State.has_all`` counts as unsatisfied —
    fields absent from the state or whose value is ``None``.

    Single source for both the per-iteration "why we loop again" reason and the
    final "reached max iterations" WARN, so the two never drift apart. Mirrors
    ``State.has_all`` (``is None`` check) by design — a falsy-but-non-None value
    (0, "", False) counts as satisfied, since a stage may legitimately produce it.
    """
    return [f for f in provides
            if not hasattr(state, f) or getattr(state, f) is None]


class Runner:
    """Main execution loop. Only entry point with side effects.

    Accepts optional adapters and handlers via dependency injection:
      - adapters: dict of named adapter instances (e.g. {"npu": NPURunner(), "cann": CANNToolchain()})
      - decision_handler: callback for AskUserQuestion resolution
      - gate_registry: dict of gate_name → Gate instances for RunGate resolution
    """

    def __init__(self, workflow: StageProtocol | None = None,
                 agent_backend: AgentBackend | None = None,
                 workspace=None,
                 adapters: dict[str, Any] | None = None,
                 decision_handler: Callable | None = None,
                 gate_registry: dict[str, Any] | None = None,
                 progress_callback: Callable | None = None):
        self._workflow = workflow
        self._agent_backend = agent_backend
        self._workspace = workspace
        self._adapters = adapters or {}
        self._decision_handler = decision_handler
        self._gate_registry = gate_registry or {}
        self._progress_callback = progress_callback
        self._event_log: EventLog | None = None
        if workspace:
            # for_path：进程级共享实例——runner 与 artifact_recovery（以及任何
            # 同路径写者）串行化在显式锁上（20260821 F3 加固），不依赖
            # O_APPEND 原子性。
            self._event_log = EventLog.for_path(workspace.events_path)
        self._cancelled = False
        self._workflow_deadline: float | None = None
        self._stage_deadline: float | None = None
        # Monotonic start times + configured budgets, used to render
        # human-meaningful timeout messages (elapsed vs budget) instead of the
        # raw monotonic deadline.
        self._workflow_started: float | None = None
        self._workflow_budget_sec: float | None = None
        # P7: reason for the current (re-)iteration, set by the early-termination
        # block after each round so the NEXT iteration_start can log it.
        self._iteration_reason: str = ""
        # P3: scope path (e.g. "detailed-design/tiling/InterleaveBased") set by
        # GraphExecutor before run_stage, so stage_iteration/stage_done can
        # disambiguate fork-join branches with the same stage.name.
        self._scope_prefix: str = ""
        self._stage_started: float | None = None
        self._stage_budget_sec: float | None = None
        # Option A: was the last agent-bearing iteration's result status=ok?
        # When True, a stage-deadline overrun is soft (warn + continue) rather
        # than a hard StageTimeoutError — a slow-but-successful run (e.g. swi_glu
        # codegen 4484s vs 3600s budget, artifacts still salvageable) shouldn't
        # be discarded. Reset per-stage; only updated when an agent actually ran.
        self._last_iter_ok: bool = False
        self._current_stage_name: str = ""
        # P131c: cross-run backoff-resume budget counters for transient infra
        # aborts (watchdog killed a live-but-stalled spawn). Reset per-stage in
        # _run_stage_body. Separate from the productive iteration budget so an
        # infra storm never eats a stage's real retries (the P116 anti-waste
        # concern) — it re-spawns THIS iteration and is bounded by config.
        self._infra_retry_count: int = 0
        self._infra_backoff_elapsed_s: float = 0.0
        # The Stage object currently running, so _check_timeout can read its
        # `uninterruptible` flag (soft let-through for stages that must run past
        # a deadline, e.g. cann-bench eval / cannbench_adapt 收尾链路). Set
        # per-stage in _run_stage_body.
        self._current_stage = None
        self.Logger = Logger

    def cancel(self) -> None:
        """Signal the runner to stop at the next iteration boundary."""
        self._cancelled = True

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    def run_stage(self, state: State, stage: StageProtocol,
                  start_iteration: int = 1, ctx=None) -> State:
        """Run a single Stage. Returns updated State.

        Args:
            state: Current pipeline state.
            stage: Stage to execute.
            start_iteration: Initial iteration number (1-based). Use >1
                to resume from a specific iteration within the stage.
            ctx: Optional ExecContext. When provided, its cancel_flag and
                deadlines take precedence over the Runner's instance fields,
                enabling parallel-safe execution.
        """
        start_ms = int(time.time() * 1000)
        try:
            return self._run_stage_body(state, stage, start_iteration,
                                       ctx, start_ms)
        except Exception as e:
            elapsed_ms = int(time.time() * 1000) - start_ms
            stage_label = (f"{self._scope_prefix}/{stage.name}"
                          if self._scope_prefix else stage.name)
            if self._event_log:
                self._event_log.append(
                    evt.stage_aborted(stage_label, elapsed_ms,
                                     error_type=type(e).__name__))
            self.Logger.stage_done(stage_label, elapsed_ms,
                                  status="aborted")
            raise

    def _run_stage_body(self, state: State, stage: StageProtocol,
                        start_iteration: int, ctx,
                        start_ms: int) -> State:
        """Internal: full stage execution loop. Called by run_stage wrapper."""

        def _is_cancelled() -> bool:
            if ctx is not None and ctx.cancel_flag.is_cancelled():
                return True
            return self._cancelled

        # Single monotonic read reused for both started-marks and deadlines, so
        # start time and deadline are consistent (deadline == started + budget).
        now_mono = time.monotonic()
        # Set workflow/stage deadlines. ExecContext overrides when provided.
        if ctx is not None and ctx.workflow_deadline is not None:
            self._workflow_deadline = ctx.workflow_deadline
            if self._workflow_started is None:
                self._workflow_started = now_mono
                self._workflow_budget_sec = state.workflow_timeout_sec or None
        elif self._workflow_deadline is None and state.workflow_timeout_sec > 0:
            self._workflow_deadline = now_mono + state.workflow_timeout_sec
            self._workflow_started = now_mono
            self._workflow_budget_sec = state.workflow_timeout_sec
        self._stage_started = now_mono
        # Option A: reset per-stage — a fresh stage has no prior ok iteration.
        self._last_iter_ok = False
        # P131c: reset the cross-run backoff-resume budget per stage.
        self._infra_retry_count = 0
        self._infra_backoff_elapsed_s = 0.0
        # Track the running stage so _check_timeout can read `uninterruptible`.
        self._current_stage = stage
        # Resolve the per-stage timeout: CLI --stage-timeout (state.
        # stage_timeout_sec, None when not given) > config timeouts.stages.
        # <stage> > config default > 0 (no timeout). Mirrors the iteration
        # budget override semantics. See runtime_config.resolve_stage_timeout.
        from ascendc_devkit.orchestration.runtime_config import (
            resolve_stage_timeout,
        )
        effective_stage_timeout = resolve_stage_timeout(
            stage.name, state.stage_timeout_sec)
        if ctx is not None and ctx.stage_deadline is not None:
            self._stage_deadline = ctx.stage_deadline
            self._stage_budget_sec = effective_stage_timeout or None
        elif effective_stage_timeout > 0:
            self._stage_deadline = now_mono + effective_stage_timeout
            self._stage_budget_sec = effective_stage_timeout
        else:
            self._stage_deadline = None
            self._stage_budget_sec = None

        # design-halt-diagnostics P2: use the same scope-prefixed label as
        # stage_aborted/iteration_start/stage_complete, so Report._from_events'
        # dict lookup by stage name actually hits (else every stage shows
        # status "unknown" in report.md/report.json).
        enter_label = (f"{self._scope_prefix}/{stage.name}"
                      if self._scope_prefix else stage.name)
        if self._event_log:
            self._event_log.append(
                evt.stage_enter(enter_label, -1, -1))

        if self._progress_callback:
            self._progress_callback("stage_start", stage.name, None)

        gate = stage.gate()
        if gate:
            gate_evidence = {
                "generated_sources": state.generated_sources,
                "build_result": state.build_result,
                "debug_result": state.debug_result,
                "integration_result": state.integration_result,
                "target_files": state.target_files,
                "requirement": state.requirement,
                "op_identity": state.op_identity,
                "design_target_chip": state.design_target_chip,
            }
            if not gate.evaluate(gate_evidence).passed:
                raise PreconditionError(
                    stage.name,
                    f"gate check failed: {gate.evaluate(gate_evidence).reason}")

        # Content-level input validation (beyond presence check)
        input_errors = stage.validate_inputs(state)
        if input_errors:
            raise PreconditionError(
                stage.name,
                "input validation failed:\n" +
                "\n".join(f"  - {e}" for e in input_errors))

        result_state = state.with_updates(current_stage=stage.name)
        self._current_stage_name = stage.name

        # Iteration ceiling resolution.
        #   user_max_iterations set  → user gave an explicit business limit;
        #                              honor it verbatim as a hard cap in BOTH
        #                              modes (e.g. `--max-iterations 5` means 5,
        #                              not swallowed by the interactive safety net).
        #   unset + interactive      → user drives termination via decisions, so
        #                              the ceiling is only a safety net: a high
        #                              net for agent stages that may need many
        #                              rounds, the stage's own ceiling for
        #                              deterministic single-pass stages.
        #   unset + non-interactive  → each stage runs up to its own default.
        if state.user_max_iterations is not None:
            iteration_ceiling = state.user_max_iterations
        else:
            from ascendc_devkit.orchestration.runtime_config import (
                stage_max_iterations,
            )
            # Per-stage budget: config-file override (resources/
            # orchestration-config.json → iterations.stages) or the stage's
            # class default. This is the single knob for tuning intra-stage
            # retries globally without touching code.
            stage_budget = stage_max_iterations(
                stage.name, stage.default_max_iterations)
            if not state.non_interactive and getattr(
                    stage, "needs_iteration_safety_net", True):
                from ascendc_devkit.orchestration.runtime_config import (
                    INTERACTIVE_ITERATION_SAFETY_NET,
                )
                iteration_ceiling = max(
                    stage_budget, INTERACTIVE_ITERATION_SAFETY_NET)
            else:
                iteration_ceiling = stage_budget
        result: dict = {}
        had_any_actions = False  # P6-b: detect pass-through / intentionally-empty stages
        # Part 3 — cut allowance: consecutive silent cuts (Part 1: agent_result.cut
        # = thinking-only terminal) don't burn the normal iteration budget — they're
        # recoverable interruptions, not logic failures. Bounded by retry_budgets cut_streak_threshold;
        # any non-cut outcome (success OR genuine failure) breaks the streak and
        # advances the productive-iteration count. _iteration mirrors the old for
        # loop var (never exceeds iteration_ceiling for productive work); a cut
        # leaves _iteration unchanged, so the next pass logs the same number — the
        # cut-warn line at the loop tail explains the repeat.
        _cut_streak = 0
        # P6（step-110）硬切观测（纯观测不进控制流——上限归 cut_streak/迭代
        # 天花板）：硬切累计数进 WARN 呈现；各次 cut 的 thinking 体量清单供
        # streak 耗尽路径的退出原因（P7 诚实化）。
        _hard_cut_total = 0
        _cut_chars: list[int] = []
        _iteration = start_iteration
        # F6：收尾归一化用的末轮质量门值（循环内每轮刷新；零轮路径保持 True——
        # 无产物可判质量时以默认满足论）。
        _final_quality_ok = True
        # `_first_pass` 取代原 `iteration > start_iteration`（为 for 循环设计，每次
        # 迭代号必增）：cut-resume 回合迭代号不变（cut 不烧预算），原判定恒 False 使
        # `_iteration_reason` 晚一拍显示/不消费。用"非首回合"判定，对正常 run 与跨
        # run resume（start_iteration>1）行为完全一致，且 cut-resume 正确显示上轮原因。
        _first_pass = True
        while _iteration <= iteration_ceiling and _cut_streak < cut_streak_threshold():
            iteration = _iteration
            if _is_cancelled():
                if self._event_log:
                    self._event_log.append(
                        evt.stage_complete(stage.name,
                            int(time.time() * 1000) - start_ms,
                            total_iterations=iteration - 1,
                            status="cancelled"))
                if self._progress_callback:
                    self._progress_callback("stage_error", stage.name,
                                            {"error": "cancelled"})
                raise RunnerCancelledError(
                    f"Cancelled during stage '{stage.name}' at iteration {iteration}")

            self._check_timeout(stage.name)

            # P3: scope prefix disambiguates fork-join branches (same stage.name
            # for ContiguousSplit/InterleaveBased); P7: reason field explains why
            # this is not the first iteration (early-termination unmet).
            stage_label = (f"{self._scope_prefix}/{stage.name}"
                          if self._scope_prefix else stage.name)
            iter_reason = (self._iteration_reason
                          if not _first_pass else "")
            details = f"{stage_label} iteration {iteration}/{iteration_ceiling}"
            if iter_reason:
                details += f" ({iter_reason})"
                self._iteration_reason = ""  # consumed

            self.Logger.action("stage_iteration", details)
            if self._event_log:
                self._event_log.append(
                    evt.iteration_start(stage_label, iteration, reason=iter_reason))
            if self._progress_callback:
                self._progress_callback("iteration_start", stage.name,
                                        {"iteration": iteration, "max": iteration_ceiling})

            actions = stage.actions(result_state, iteration)
            if actions:
                had_any_actions = True
            # P131c (revised, fail-open): cross-run backoff-resume inner loop. 凡
            # 「agent 没干净跑完一轮」的失败（is_infra_failure：crash=partial/fatal、
            # 被杀=aborted、环境故障=error_type 非空，含 infra_transient 连接重置与
            # 永久 infra）都值得重采样一个 FRESH 网关窗口：睡有界退避后重 spawn 本
            # iteration（新 serve + 新 session = 新上游窗口）。§1.10：重试判据用业务
            # 语义 is_infra_failure（「没干成活」），不用机制特征（aborted / 文案 marker）。
            # 有界于重试数 + 累计退避 cap（_infra_backoff_retry）+ stage/workflow
            # deadline（_check_timeout 每次重试重查）——真死网关耗尽后落到干净、可诊断
            # 的 halt（下方 P116 revised 补 reason）。teardown 仅在循环真退出
            # （terminal 分支）对 aborted 触发（§step-98-B：resume ⇒ 不动树）。
            # P2 (parallel-batch partial retry): 并行批（agent_results）可能
            # 部分成员干净、部分 infra 失败。整批重跑会把干净成员的已完成
            # 工作（transition 未提交的 plan 子段）丢掉重做（RowShiftExp
            # COMPLETED 却整批重跑实证）。分区：干净成员结果保留（并入最终
            # result 供 transition 提交）、只重 spawn infra 失败成员的
            # actions。§1.10：重试触发仍是业务语义 is_infra_failure，
            # 「重跑哪些成员」按 per-member 结果派生，不认机制。
            _preserved_results: list[dict] = []  # clean {agent_result, action}
            _replay_actions: list[Action] | None = None  # subset being re-run
            while True:
                try:
                    result = self._execute_actions(actions, result_state)
                except DecisionPendingError as e:
                    if self._event_log:
                        self._event_log.append(
                            evt.decision_pending(stage.name, iteration, e.question))
                    raise
                _ares = result.get("agent_result")
                # P2 + P9: scan the whole batch (order-independent) — ANY
                # infra-failed member poisons the batch: promote it to
                # _ares (retry trigger, matching serial single-spawn
                # semantics). Simultaneously partition: clean members →
                # _preserved (never re-run), failed members → their
                # actions to re-spawn.
                _failed_actions: list[Action] = []
                _clean_entries: list[dict] = []
                _infra_promoted = False
                for _ar_it in result.get("agent_results") or []:
                    _ar_m = _ar_it.get("agent_result")
                    if _ar_m is None:
                        continue
                    if is_infra_failure(_ar_m):
                        if not _infra_promoted:
                            _ares = _ar_m
                            _infra_promoted = True
                        _act = _ar_it.get("action")
                        if _act is not None:
                            _failed_actions.append(_act)
                    else:
                        _clean_entries.append(_ar_it)
                if not is_infra_failure(_ares):
                    break  # clean success → no teardown, iterate normally
                # D5 (hard-timeout): teardown 仅对 aborted（被杀活 spawn）触发——连接重置
                # (infra_transient) 或永久 infra 时 spawn 没写 op_dir，无需回滚。teardown
                # 是 finally 语义（precision-debug 回滚 op_dir 到 best_commit；base 是
                # no-op），best-effort + 幂等，每次 kill 前触发一次，保证重采样从
                # known-good baseline 起步。§1.10 业务语义：回滚判据用 aborted（「杀掉活
                # spawn」），不用 is_infra_failure（机制代理）。
                _abort = getattr(_ares, "aborted", None)
                if _is_cancelled() or not self._infra_backoff_retry(stage):
                    # cancelled, or backoff budget exhausted → the stage
                    # loop is EXITING (aborted result falls through to
                    # transition + P116 halt). §step-98-B: teardown is a
                    # loop-exit finally hook — it fires ONLY here, after
                    # the retry decision. The old fire-on-every-abort
                    # position rolled the tree back before a re-spawn
                    # that auto-resumes the SAME session —「记忆 vs 代码」
                    # divergence, agent work systematically evaporated
                    # (99c4c0: w1 rework destroyed / w3 redone / w4
                    # root-cause fix stripped; docs/plan/
                    # precision-teardown-turnstall-mismatch/). The rule
                    # is「循环还继不继续」, not the abort kind: the retry
                    # branch below never reaches teardown — resume ⇒
                    # never touch the tree is guaranteed by CALL
                    # POSITION, not by stage-side convention. Exception
                    # exits (the _check_timeout raise below) also skip
                    # teardown — the tree stays consistent with the
                    # resumable session's memory; exit cleanliness on a
                    #真 halt is owned by converge's own checkout-to-best.
                    if _abort:
                        result_state = self._run_stage_teardown(
                            stage, result_state, _abort)
                    result["is_terminal"] = True
                    break
                self._check_timeout(stage.name)   # enforce deadline across retries
                if _clean_entries:
                    _preserved_results.extend(_clean_entries)
                if _failed_actions:
                    # P2: re-spawn ONLY the infra-failed members (fresh
                    # gateway window per member, same as serial re-spawn
                    # semantics). The clean members' results are preserved
                    # above and merged into the final result after the
                    # loop → their sub-stages commit.
                    _replay_actions = _failed_actions
                    actions = _failed_actions
                elif _replay_actions is not None and len(actions) == 1:
                    # single-member subset kept failing → keep re-running
                    # it (not the whole batch), matching serial retry.
                    actions = _replay_actions
                else:
                    _replay_actions = None
                    actions = stage.actions(result_state, iteration)  # fresh spawn

            # P2: merge preserved clean members into the final result so
            # the transition commits them done — their work was never
            # re-run, so it is not otherwise present in the last
            # _execute_actions output. The last round may be a
            # single-spawn replay (agent_results unset) or a fresh batch;
            # both merge under the preserved entries. No-op when no
            # parallel partial retry happened (_preserved_results empty).
            if _preserved_results:
                _cur = result.get("agent_results")
                if not _cur and result.get("agent_result") is not None:
                    _cur = [{"agent_result": result.get("agent_result"),
                             "action": (actions[0] if actions and len(actions) == 1
                                        else None)}]
                if _cur:
                    result["agent_results"] = _preserved_results + _cur

            # Emit stage_skipped event if stage returned only NoOp (environment unavailable)
            if result.get("noop") and self._event_log:
                self._event_log.append(
                    evt.stage_skipped(stage.name, result.get("noop_reason", "")))

            result_state = stage.transition(result_state, result)
            # step-112 (§1.15)：会话锚点统一捕获——产物反馈重派
            # resume 的机械单点。session_id 在 spawn 返回时首次出现于
            # 本层；stage 层无公共 transition 入口（8+ 子类覆写），
            # 放 stage 侧 = 逐点回写纪律（漏写一处即丢锚点）。空值
            # 不清空既有锚点（backend 异常时宁续旧勿丢）。消费与否
            # 是各 stage actions 的语义决策（设计子阶段反馈重派轮
            # resume，见 _DesignSubstage.actions；codegen 同义）。
            _cap_ar = result.get("agent_result")
            _cap_sid = ((getattr(_cap_ar, "session_id", "") or "")
                        if _cap_ar is not None else "")
            if _cap_sid:
                # M13：锚点随捕获记归属 stage——消费方判「自己的会话」用。
                result_state = result_state.with_updates(
                    last_agent_session_id=_cap_sid,
                    last_agent_stage=stage.name)
            result_state = result_state.with_updates(
                stage_iterations={**result_state.stage_iterations,
                                  stage.name: iteration}
            )

            # Option A: track whether this iteration's agent succeeded, so the
            # next _check_timeout can soft-skip a stage-deadline overrun when
            # the run is slow-but-successful. Only update when an agent actually
            # ran this iteration — an empty-actions iteration must not clobber
            # the prior ok signal (it carries no new agent evidence).
            _agent_res = result.get("agent_result")
            if _agent_res is not None:
                # S2 (D7 Option A 收紧): a hard-aborted spawn (aborted != None)
                # carries no agent evidence — the deadline killed it before it
                # ran. Don't clobber the prior salvageable signal (_last_iter_ok);
                # otherwise the hard wall regresses Option A: the abort would flip
                # _last_iter_ok=False → next boundary raise → discard the
                # salvageable product (pre-hard-wall the spawn ran past deadline
                # and Option A soft-passed until natural completion, preserving it).
                # 2026-08-11 review M1: silent-cut (Part 1) 与 aborted 同属"被外部
                # 中断、不携带 agent 证据"——同样不得 clobber 先前可抢救信号（否则 cut
                # 后撞 deadline 也会硬 raise 丢产物，复现 S2 防的回归）。一并豁免 cut。
                # P9: parallel batch = all results must be clean ok to record
                # a success (any aborted/cut result withholds the signal).
                # Filter None (no agent_backend / failed spawn) so `.status`
                # below never dereferences None.
                _all_res = [
                    r.get("agent_result")
                    for r in (result.get("agent_results") or [])
                    if r.get("agent_result") is not None
                ]
                if not _all_res:
                    _all_res = [_agent_res]
                _clean = all(
                    not getattr(ar, "aborted", None) and not getattr(ar, "cut", False)
                    for ar in _all_res)
                if _clean:
                    # F5: bare "ok" is no longer enough — a clean finish with
                    # zero products must not light the salvage signal (the
                    # deadline soft-skip would then preserve an empty-handed
                    # round). "有可信完整产出" = clean finish AND products,
                    # for every member of the batch (P9 all-clean).
                    self._last_iter_ok = all(
                        ar.status == "ok" and bool(ar.artifacts)
                        for ar in _all_res)

            if self._event_log:
                self._event_log.append(
                    evt.iteration_complete(stage.name, iteration, "ok"))
            if self._progress_callback:
                self._progress_callback("iteration_end", stage.name,
                                        {"iteration": iteration})

            # P116（revised，fail-open）：infra 类失败（含永久 infra / infra_transient /
            # 连接重置）已由上方 P131c 循环做**有界**退避重试——不再「首见即 halt」，而是
            # 预算耗尽才落此。is_terminal 已由循环耗尽分支置位，这里只补诚实诊断 reason
            # （供 stage_done / 下一 iteration 日志）。默认 fail-open，halt 仅预算耗尽。
            # P9: 并行批次扫描用 is_infra_failure 对齐串行谓词——批内任何 infra 成员
            # （aborted / "infra" / "infra_transient"）都算，不再只认 error_type=="infra"
            # 字面量（否则 infra_transient 成员耗尽预算后落不到诊断与 is_terminal）。
            _all_res = [
                r.get("agent_result")
                for r in (result.get("agent_results") or [])
                if r.get("agent_result") is not None
            ]
            if _agent_res is not None and not _all_res:
                _all_res = [_agent_res]
            _infra_res = next(
                (ar for ar in _all_res if is_infra_failure(ar)), None)
            if _infra_res is not None:
                _fr = ""
                _m = getattr(_infra_res, "metrics", None) or {}
                if isinstance(_m, dict):
                    _fr = str(_m.get("failure_reason", ""))
                self._iteration_reason = (
                    "infrastructure error (bounded retry exhausted)"
                    + (f": {_fr}" if _fr else ""))
                result["is_terminal"] = True

            # Early termination: output contract satisfied AND the stage's own
            # quality self-check passes → stop iterating. is_satisfied defaults
            # to True (presence of provides is enough); stages override it to
            # keep iterating until their output is actually acceptable.
            output_contract = stage.output_contract()
            # R1 (2026-08-21, 公共 artifact-retry 抽象) 循环内归一化：产物契约已满足
            # （has_all）时，**artifact-retry 类的** sticky last_error 必是过时的（本
            # stage 已交付，缺产物错误不可能与产物满足并存）——当场清掉，否则
            # is_satisfied 因 last_error 返回 False → quality_ok False → 成功轮不
            # break、多烧 1 次 iteration。与收尾 F6（_delivered → 清 own error）同界
            # 对称；stage 成功路径不清错（TilingStage 注释"收尾清错统一归 runner"）由
            # 此兜住。**只清 artifact-retry 类**（missing_artifact / incomplete_output）
            # ——质量门不过（schema_violation 等）的错误必须保留（还没交付），否则会
            # 误清未解决的质量问题（test_quality_gate_not_passed_keeps_error）。
            _art_own_err = getattr(result_state, "last_error", None)
            if (_art_own_err is not None
                    and getattr(_art_own_err, "stage_name", None) == stage.name
                    and output_contract.provides
                    and stage.outputs_delivered(result_state)
                    and callable(getattr(stage, "is_artifact_retry_error", None))
                    and stage.is_artifact_retry_error(
                        getattr(_art_own_err, "error_type", ""))):
                # 已交付 → 清过时 artifact 错误 + 重置 artifact-retry 计数（成功清零）
                result_state = result_state.with_updates(
                    last_error=None, artifact_retries=0)
            satisfied = getattr(stage, "is_satisfied", None)
            quality_ok = satisfied(result_state) if callable(satisfied) else True
            _final_quality_ok = quality_ok
            # P33: NoOp(contract_satisfied=True) = 显式确定性跳过 —— output_contract
            # 在此场景不适用(如 external cases 替代了 test_design 的 LLM 产物)。视为
            # terminal,避免"NoOp → 契约未满足 → 重试 NoOp"死循环耗尽 budget 误 halt。
            if result.get("noop") and result.get("noop_contract_satisfied"):
                result["is_terminal"] = True
            elif (output_contract.provides
                    and stage.outputs_delivered(result_state)
                    and quality_ok):
                result["is_terminal"] = True

            # step-84 B3: a quality gate whose outstanding issues ALL route to a
            # loopback target (nothing it can self-fix in-stage) must stop
            # in-stage retry immediately — re-iterating over the frozen upstream
            # product it cannot touch only re-reports the same issue (aggregate/
            # manifold burned 3 iters each, "与 iteration N-1 一致"). Break now;
            # resolve_condition then fires the loopback the very next step. Only
            # gates that declare stop_in_stage_retry opt in; other stages unaffected.
            elif not quality_ok:
                _stop = getattr(stage, "stop_in_stage_retry", None)
                if callable(_stop) and _stop(result_state):
                    result["is_terminal"] = True
                    self._iteration_reason = (
                        "all outstanding issues require loopback (non-self-fixable) "
                        "— routing immediately, skipping futile in-stage retry")

            # Terminal condition: no more actions or explicit terminal
            if result.get("is_terminal") or not actions:
                break

            # P7: capture the reason WHY we're iterating again, for the next
            # stage_iteration log line. Check in priority order so the most
            # actionable reason wins. (P93's infra reason moved up to the
            # is_terminal break above — P116; infra breaks before reaching here,
            # so only non-infra reasons remain: contract / quality / continuing.)
            if not stage.outputs_delivered(result_state):
                missing = _unsatisfied_contract_fields(result_state, output_contract.provides)
                # P1: 区分「stage 主动判契约失败」（last_error 已记录根因，如
                # codegen CMakeLists/manifest/plugin 检查）与「agent 真没产出」。
                # 前者透出 error_type+message 让日志可诊断，不再笼统报 unsatisfied。
                _le = getattr(result_state, "last_error", None)
                if (_le is not None
                        and getattr(_le, "stage_name", None) == stage.name):
                    self._iteration_reason = (
                        f"contract broken: {_le.error_type} — "
                        f"{(_le.message or '')[:160]}")
                else:
                    self._iteration_reason = f"contract unsatisfied: {', '.join(missing)}"
            elif not quality_ok:
                # P25: surface WHY quality failed — render the stage's blocking
                # issues (code/target/template/detail) into the reason so the log
                # is human+LLM readable, not a bare "quality check not satisfied".
                # detail_limit keeps the line compact; the full detail still rides
                # the loopback payload (render_issues(detail_limit=None)).
                bi = getattr(stage, "blocking_issues", None)
                issues = bi(result_state) if callable(bi) else []
                rendered = render_issues(issues, detail_limit=240)
                self._iteration_reason = (
                    "quality check not satisfied: " + " | ".join(rendered)
                    if rendered else "quality check not satisfied")
            elif actions:
                self._iteration_reason = "agent continuing (is_terminal not set)"

            # Part 3 — cut accounting (20260810 批根因修复). A cut result (Part 1
            # detection: thinking-only terminal, no artifact) is a recoverable
            # interruption: it does NOT consume the normal iteration budget, and
            # the streak increments. Any non-cut outcome (success OR genuine
            # failure) breaks the streak and advances the productive-iteration
            # count. The while guard exits once cut_streak_threshold() consecutive cuts
            # couldn't be recovered (gateway too unstable) — the stage then ends
            # on the unsatisfied contract. User-specified semantics: success
            # resets to 0; the counter reflects only "consecutive
            # resume-still-failed". break (terminal) never reaches here.
            _acut = False
            _ares = result.get("agent_result")
            if _ares is not None:
                _acut = bool(getattr(_ares, "cut", False))
            # M8（review 整改）：上下文冲刷计数进 events.jsonl 权威记录——
            # 此前只落 AgentResult.metrics（无持久消费者，下批复盘无法汇总）。
            # 仅 N>0 发射；分母（总 spawn 数）由既有 per-spawn 事件承载。
            if _ares is not None and self._event_log:
                _m_ = getattr(_ares, "metrics", None)
                _n_ = (_m_.get("compactions")
                       if isinstance(_m_, dict) else None)
                if _n_:
                    self._event_log.append(evt.agent_compacted(
                        agent_name=_ares.agent_name, count=int(_n_),
                        stage=stage.name))
            # R1 (2026-08-21, 公共 artifact-retry 抽象): 产物契约未满足
            # （missing_artifact / incomplete_output）→ 独立定向重试，不烧 iteration。
            # 对齐 cut 语义——这类失败是"跑完但产物没按契约就位"（可纠正：喂位置/字段
            # 提示即可修），非"模型产出质量不达标"（那才是 iteration 预算本意）。
            # 预算独立计数（state.artifact_retries），耗尽后落回 iteration 语义。
            _art_err = getattr(result_state, "last_error", None)
            _art_active = False
            # 守卫：产物契约已满足（has_all）时，last_error 必已在上方循环内归一化
            # 清掉；此处仅兜底不触发 artifact-retry（产物就位 → 走正常收尾）。真实
            # stage 成功路径可能不清 sticky last_error，前置归一化 + 此处守卫双保险。
            _art_delivered = bool(
                output_contract.provides
                and stage.outputs_delivered(result_state))
            if (_art_err is not None
                    and not _art_delivered
                    and getattr(_art_err, "stage_name", None) == stage.name
                    and callable(getattr(stage, "is_artifact_retry_error", None))
                    and stage.is_artifact_retry_error(
                        getattr(_art_err, "error_type", ""))):
                _art_retries = getattr(result_state, "artifact_retries", 0) + 1
                _art_max = stage.effective_artifact_retry_max()
                if _art_retries <= _art_max:
                    # 独立计数递增（第 retries 次重试），不烧 iteration，自动重 spawn。
                    # 边界：retries <= max → 都在预算内；retries > max（第 max+1 次）
                    # 才耗尽落回 iteration。artifact_retry_max=3 = 可重试 3 次。
                    result_state = result_state.with_updates(
                        artifact_retries=_art_retries)
                    _art_active = True
                    self.Logger.warn(
                        f"Stage '{stage.name}' artifact-retry "
                        f"({_art_err.error_type}: {_art_err.message[:120]}) "
                        f"retry {_art_retries}/{_art_max}; NOT consuming "
                        f"iteration budget")
                    if self._event_log:
                        self._event_log.append(
                            evt.artifact_missing_retry(
                                stage.name, _art_err.error_type,
                                _art_retries, _art_max,
                                getattr(_art_err, "message", "")[:200]))
                else:
                    # 耗尽 → 落回 iteration 语义（消耗 1 次迭代预算）
                    self.Logger.warn(
                        f"Stage '{stage.name}' artifact-retry exhausted "
                        f"({_art_retries}/{_art_max}); falling back to "
                        f"iteration budget")
            if _acut:
                _cut_streak += 1
                # P6：backend 判切点携带的分类 facts（缺键 = 无思考流证据——
                # 旧 backend/无 thinking，降级现文案不假设）。
                _m = (_ares.metrics if isinstance(
                    getattr(_ares, "metrics", None), dict) else None)
                _facts = _m.get("cut_facts") if _m else None
                _hard = bool(_m.get("cut_hard")) if _m else False
                if _hard:
                    _hard_cut_total += 1
                if isinstance(_facts, dict):
                    _cut_chars.append(int(_facts.get("thinking_chars") or 0))
                    _form = ("思考流活跃至末刻——外部截断形态" if _hard else
                             "末次思考距结束较远（非活跃流截断形态）")
                    _hard_note = (f"，硬切累计 {_hard_cut_total}"
                                  if _hard_cut_total else "")
                    self.Logger.warn(
                        f"Stage '{stage.name}' agent 终止：thinking-only 终态"
                        f"（thinking {_facts.get('thinking_chars', 0)} chars / "
                        f"末增量距结束 {_facts.get('last_delta_to_end_s')}s / "
                        f"尝试时长 {_facts.get('attempt_duration_s')}s；无模型"
                        f"结束原因；{_form}）；auto-resume next iteration "
                        f"(cut_streak={_cut_streak}/{cut_streak_threshold()}"
                        f"{_hard_note}，"
                        f"iteration 保持 {iteration}/{iteration_ceiling}——cut 是"
                        f"可恢复中断，不烧生产迭代预算；生产迭代仍在当前轮，预算"
                        f"按真实成功/失败轮消耗。放弃 cut-recovery 于 cut_streak 达 "
                        f"{cut_streak_threshold()} 或 iteration 达 {iteration_ceiling})")
                else:
                    self.Logger.warn(
                        f"Stage '{stage.name}' agent silent-cut (no artifact, "
                        f"thinking-only terminal); auto-resume next iteration "
                        f"(cut_streak={_cut_streak}/{cut_streak_threshold()}, "
                        f"iteration 保持 {iteration}/{iteration_ceiling}——cut 是可恢复"
                        f"中断，不烧生产迭代预算；生产迭代仍在当前轮，预算按真实成功/"
                        f"失败轮消耗。放弃 cut-recovery 于 cut_streak 达 "
                        f"{cut_streak_threshold()} 或 iteration 达 {iteration_ceiling})")
            elif _art_active:
                _cut_streak = 0   # artifact-retry 分支：不烧 iteration
            else:
                _cut_streak = 0
                _iteration += 1
            _first_pass = False   # 本回合已过，下回合显示/消费 _iteration_reason

        output_contract = stage.output_contract()
        # P33: 确定性跳过的 NoOp 不参与"契约未满足"判定(warn / partial)。result 是
        # 最后一次迭代的产物,NoOp stage 每轮都 NoOp,故最后一轮的标志即代表整个 stage。
        noop_satisfied = bool(result.get("noop")
                              and result.get("noop_contract_satisfied"))
        if (not noop_satisfied and output_contract.provides
                and not stage.outputs_delivered(result_state)):
            # Name the ACTUALLY missing fields, not the whole provides list —
            # the old "{provides}" text read as "every declared output is
            # missing" and sent users hunting for config that was never required
            # (e.g. entry's runtime-filled npu_id, which is legitimately None).
            missing = _unsatisfied_contract_fields(result_state, output_contract.provides)
            if _cut_streak >= cut_streak_threshold():
                # P7（step-110）：循环因 streak 耗尽退出（守卫第 2 条件）而非
                # 迭代耗尽——「reached max iterations」在此路径偏离事实。前置
                # 真实原因 + 各次 thinking 体量清单；真迭代耗尽路径保留原文案。
                self.Logger.warn(
                    f"Stage '{stage.name}' cut-recovery 放弃：连续 {_cut_streak} 次 "
                    f"thinking 截断未恢复（cut_streak 达 "
                    f"{cut_streak_threshold()}，各次 thinking chars：{_cut_chars}"
                    f"{'，其中硬切 ' + str(_hard_cut_total) + ' 次' if _hard_cut_total else ''}）；"
                    f"输出契约未满足; missing: {missing}"
                )
            else:
                self.Logger.warn(
                    f"Stage '{stage.name}' reached max iterations ({iteration_ceiling}) "
                    f"without satisfying output_contract; missing: {missing}"
                )

        elapsed_ms = int(time.time() * 1000) - start_ms
        # P3: use scope prefix for fork-join branch disambiguation
        stage_label = (f"{self._scope_prefix}/{stage.name}"
                      if self._scope_prefix else stage.name)
        # P1: stage_complete emit moved below — after stage_status is final, so
        # the event carries the real outcome (run 20260730 codegen-halt-but-ok).

        # §P6: surface this stage's products (from the last iteration's agent
        # result) so the console lists what was produced/changed. Deterministic
        # or no-op stages (no agent_result) simply list nothing.
        stage_artifacts = None
        last_agent = result.get("agent_result") if isinstance(result, dict) else None
        if last_agent is not None:
            stage_artifacts = getattr(last_agent, "artifacts", None)
        # §P7.1: do not report a failed stage as a clean success. Derive the
        # stage's real status so stage_done shows ✓ / ⚠ / ✗ instead of always ✓:
        #   - a non-ok agent_result ("partial"/"fatal"/... — a crashed-but-salvaged
        #     or failed spawn) → failure, NOT "ok";
        #   - last_error THIS stage recorded (missing/invalid artifact, schema
        #     violation) → failure. last_error is sticky in State, so we only
        #     count it when it names THIS stage — an inherited error from a failed
        #     upstream stage must not mis-mark a clean (e.g. no-op) downstream one.
        #   - the output_contract left unsatisfied after max iterations →
        #     partial when SOME provides landed (slow-but-salvageable), failed
        #     when NONE did (该产出却空跑 — the old constant "partial" blurred
        #     "delivered nothing" into "delivered something incomplete", F5).
        # A clean-finish-zero-products agent is "ok" here (process fact); the
        # contract branch above is what decides whether that empty-handed run
        # fails the stage.
        stage_status = "ok"
        # P9: 并行批次 → stage 状态由整批 agent 的**最差**结果推导（与串行单 agent
        # 语义对齐）。只取 last_agent（批内最先完成者）会漏掉批内非最先完成者的失败
        # ——infra 成员未先完成时，会把本应 halt 的失败静默吞成 ok（P9 review）。
        _batch_agents = [
            r.get("agent_result")
            for r in (result.get("agent_results") or [])
            if r.get("agent_result") is not None
        ]
        if last_agent is not None and not _batch_agents:
            _batch_agents = [last_agent]
        agent_status = None
        for _ar_x in _batch_agents:
            _st = getattr(_ar_x, "status", None)
            if _st in ("failed", "fatal"):
                agent_status = "failed"
            elif _st == "partial" and agent_status != "failed":
                agent_status = "partial"
            elif _st not in ("ok",) and agent_status is None:
                agent_status = _st
        if agent_status is None and _batch_agents:
            agent_status = "ok"  # all batch members clean ok
        own_error = getattr(result_state, "last_error", None)
        own_error = (own_error if own_error is not None
                     and getattr(own_error, "stage_name", None) == stage.name
                     else None)
        # F6（§1.15 统一抽象）：stage 收尾错误归一化——"成功清 own last_error"的
        # 单点实现，取代散落在各 stage 成功 return 里的手工纪律（requirement 漏写
        # 即 d8d4d9 "成功记 failed" 的根因）。判定"已交付"所需的全部信号都在
        # runner 手里：末轮 agent 过程状态（排除 infra——P116 infra 不可恢复，错误
        # 必须保留）、契约满足（含 P33 noop 确定性跳过）、质量门通过。已交付 ⇒
        # 本 stage 之前记的失败错误必然过时（全仓约定：记错分支与交付产物互斥），
        # 清除后再推导 status——状态归一，而非让判定无视错误（那会状态与结论分裂）。
        # 只清署名本 stage 的错误；上游遗留错误保留真实溯源。与 P129（runner 为
        # 失败 stage 反向补写 last_error）同界对称。中途流转语义的清错（design
        # _commit / codegen 重试路径）仍归 stage 自身——那是 stage 未结束时的状态机
        # 逻辑，runner 边界不可达。
        # P9: 并行批次任一 infra 成员即整批 infra（批内任何 aborted / "infra" /
        # "infra_transient" 都算）——单 agent 时退化为 is_infra_failure(last_agent)。
        _last_infra = any(ar is not None and is_infra_failure(ar)
                          for ar in _batch_agents)
        _delivered = (
            noop_satisfied
            or (agent_status in ("ok", "partial")
                and not _last_infra
                and stage.outputs_delivered(result_state)
                and _final_quality_ok))
        if _delivered and own_error is not None:
            self.Logger.warn(
                f"Stage '{stage.name}' delivered successfully — cleared stale "
                f"own-stage error ({own_error.error_type}: "
                f"{own_error.message})")
            result_state = result_state.with_updates(last_error=None)
            own_error = None
        if agent_status is not None and agent_status != "ok":
            stage_status = "partial" if agent_status == "partial" else "failed"
        elif own_error is not None:
            stage_status = "failed"
        elif (not noop_satisfied and output_contract.provides
                and not stage.outputs_delivered(result_state)):
            _missing = _unsatisfied_contract_fields(
                result_state, output_contract.provides)
            stage_status = "partial" if len(_missing) < len(
                output_contract.provides) else "failed"
        # P6-b: intentionally empty stages log ○ skipped; unintentionally empty
        # stages get ⚠ no actions so the operator can spot a misconfiguration.
        if not had_any_actions:
            reason = getattr(stage, "skip_reason", lambda s: None)(result_state)
            if reason:
                self.Logger.stage_skipped(stage_label, reason)
            else:
                self.Logger.warn(
                    f"Stage '{stage_label}' produced no actions with no skip_reason "
                    f"(possible bug or misconfigured stage)")
                self.Logger.stage_done(stage_label, elapsed_ms, stage_artifacts, status=stage_status)
        else:
            self.Logger.stage_done(stage_label, elapsed_ms, stage_artifacts, status=stage_status)

        # P2+P3+P116: fail_strategy halt — propagate failure signal to graph_executor.
        # P116: infra-class failure halts REGARDLESS of fail_strategy. A continue
        # stage (e.g. requirement) hitting an unrecoverable infra fault (gateway/
        # auth/config) must propagate _stage_failed so graph_executor marks
        # node_status="failed" (not "completed"), dispatcher resume re-runs it,
        # and the operator gets a clean halt instead of a silent skip + downstream
        # abort (run 20260725-152037 root cause). Mirrors the crash-path infra
        # halt in graph_executor._execute_atomic (_is_non_fixable). Logic failures
        # (schema/compile/missing_artifact) still respect fail_strategy (continue →
        # retry/loopback). error_type is the authoritative unrecoverable signal
        # (structurally never coexists with status="ok" — base_backend sets it
        # only on crashed=True); status alone (fatal/partial) doesn't distinguish
        # infra from logic failure.
        fail_strategy = getattr(stage, "fail_strategy", "continue")
        # _last_infra 已在上方 F6 归一化段计算（P9 批内任一定义），同值复用。
        if stage_status != "ok" and (fail_strategy == "halt" or _last_infra):
            result_state = result_state.with_updates(
                _stage_failed=(stage_status, stage.name))

        # P8: partial agent 但 contract 已满足 → 不标失败（slow-but-successful salvage）。
        # P116: infra partial 例外——infra 不可恢复、半崩溃产物不可信，保持 failed/
        # partial + 已触发的 halt，不被 P8 吸收成 ok（否则 stage_complete event 误报
        # status=ok；虽 _stage_failed 已在上方 halt 前设、node_status 仍 failed，但
        # stage_status 须诚实 + defense-in-depth）。
        if (agent_status == "partial" and not _last_infra
                and output_contract.provides
                and stage.outputs_delivered(result_state)):
            stage_status = "ok"

        if (stage_status in ("partial", "failed") and own_error is None
                and _batch_agents):
            # P129 (trial-20260730): partial/failed halt with no OWN last_error →
            # the real cause lives only in the agent_result (aborted /
            # failure_reason / error_type) and is never backfilled, so the
            # downstream halt reason (graph_executor reads state.last_error)
            # comes out empty ("halt" with no "why"). When THIS stage ended
            # non-ok but recorded no own_error, synthesize one from the agent's
            # authoritative failure signal — same "translate the agent's real
            # reason into the downstream-consumed channel" fix as P125 (which
            # targets error_type; this targets last_error). name-scoped to
            # stage.name so it is not mistaken for an inherited upstream error.
            # P9: 并行批次取批内最差 agent（stage_status 的判定者）作失败权威——
            # last_agent 是批内最先完成者，可能是干净的成员，用它合成会漏掉真因。
            _worst_agent = next(
                (ar for ar in _batch_agents
                 if (getattr(ar, "status", None) or "") not in ("ok",)),
                _batch_agents[0])
            _aborted = getattr(_worst_agent, "aborted", None)
            _freason = ""
            _metrics = getattr(_worst_agent, "metrics", None)
            if isinstance(_metrics, dict):
                _freason = _metrics.get("failure_reason", "") or ""
            if _aborted or _freason:
                _cls = getattr(_worst_agent, "error_type", None) or "unclassified"
                _msg = (f"agent 被中断（{_aborted}）：{_freason or '无进一步信息'}"
                        if _aborted
                        else f"agent {agent_status}：{_freason or '无进一步信息'}")
                own_error = ErrorFeedback(
                    stage_name=stage.name, error_type=_cls, message=_msg)
                result_state = result_state.with_updates(last_error=own_error)

        # When a stage recorded its own error (schema validation, missing
        # artifact, collision etc.), surface the concrete error type + message
        # on the console so the operator can triage without opening events.jsonl.
        # Follows §P3's precedent: the error is already a structured field
        # ({error_type, message}), so this is a deterministic format — no LLM.
        if own_error is not None:
            self.Logger.warn(
                f"→ {own_error.error_type}: {own_error.message}")
        # P134: emit stage_complete NOW, carrying the derived stage_status, so
        # Report._from_events reflects the真实 status (ok/partial/failed) instead
        # of unconditionally绿. The cancelled path (loop top) emits its own
        # stage_complete with status="cancelled"; this is the normal-finish one.
        # stage_status 在此处已是最终值（post P8-salvage + halt decision），
        # 且本函数只有这一处 emit——事件在 events.jsonl 中唯一，report 据此
        # 求和 stage 时长不双计（曾因早期另加一处 emit 双份写入）。
        if self._event_log:
            self._event_log.append(
                evt.stage_complete(
                    stage_label, elapsed_ms, status=stage_status,
                    total_iterations=result_state.stage_iterations.get(stage.name, 0)))
        if self._progress_callback:
            iterations = result_state.stage_iterations.get(stage.name, 0)
            self._progress_callback("stage_complete", stage.name,
                                    {"status": stage_status, "elapsed_ms": elapsed_ms,
                                     "iterations": iterations})
        return result_state

    def _run_stage_teardown(self, stage, state, interrupt_reason: str):
        """D5: invoke ``stage.teardown()`` (finally-semantics cleanup) after a
        spawn was hard-killed. Best-effort — wraps the call in try/except and a
        duration log so a buggy/slow teardown never blocks the graceful exit.
        Returns the (possibly cleanup-updated) state, or the original state on
        any failure. teardown MUST stay seconds-scale (<60s) and idempotent by
        stage contract; long work belongs to an uninterruptible stage (D6)."""
        if not hasattr(stage, "teardown"):
            return state
        t0 = time.monotonic()
        try:
            return stage.teardown(state, interrupt_reason=interrupt_reason)
        except Exception as te:  # noqa: BLE001 — best-effort, never block exit
            self.Logger.warn(
                f"stage '{stage.name}' teardown raised during hard-timeout "
                f"cleanup ({type(te).__name__}: {te}); continuing with "
                f"pre-teardown state")
            return state
        finally:
            elapsed = time.monotonic() - t0
            if elapsed > 60.0:
                self.Logger.warn(
                    f"stage '{stage.name}' teardown took {elapsed:.0f}s (>60s "
                    f"budget) — teardown must stay seconds-scale; move long "
                    f"work to an uninterruptible stage")

    def _infra_backoff_retry(self, stage) -> bool:
        """P131c: on a transient infra abort, sleep a bounded backoff and signal
        the caller to re-spawn the current iteration (a fresh gateway window).

        Returns False when the cross-run budget is exhausted — either the retry
        count hit ``max_retries`` or cumulative backoff hit the total-time cap
        (``compute_backoff_seconds`` returns None); the caller then lets the
        aborted result fall through to the P116 halt with an actionable reason.
        Reuses ``compute_backoff_seconds`` (§2.5 single source) so the cadence
        matches the in-session 429 backoff. Config is read fresh each call
        (``infra_backoff``), same late-bind pattern as the iteration budgets."""
        from ascendc_devkit.orchestration.runtime_config import infra_backoff
        from ascendc_devkit.capabilities.agent._shared import (
            compute_backoff_seconds,
        )
        cfg = infra_backoff()
        if self._infra_retry_count >= cfg["max_retries"]:
            return False
        sleep_s = compute_backoff_seconds(
            self._infra_retry_count, cfg["backoff_base_s"],
            cfg["backoff_factor"], self._infra_backoff_elapsed_s,
            cfg["backoff_max_total_s"])
        if sleep_s is None:
            return False
        self._infra_retry_count += 1
        stage_label = (f"{self._scope_prefix}/{stage.name}"
                      if self._scope_prefix else stage.name)
        self.Logger.action(
            "infra_backoff",
            f"{stage_label} transient infra abort; sleeping {sleep_s:.0f}s then "
            f"re-spawning to sample a fresh gateway window "
            f"(infra-retry {self._infra_retry_count}/{cfg['max_retries']}, "
            f"cumulative {self._infra_backoff_elapsed_s + sleep_s:.0f}s / "
            f"{cfg['backoff_max_total_s']:.0f}s)")
        if self._event_log:
            self._event_log.append(evt.make_event(
                "infra_backoff", stage=stage_label,
                attempt=self._infra_retry_count, sleep_s=round(sleep_s, 1)))
        self._interruptible_sleep(sleep_s)
        self._infra_backoff_elapsed_s += sleep_s
        return True

    def _interruptible_sleep(self, seconds: float) -> None:
        """Sleep ``seconds`` in ≤1s chunks, waking early on cancel so a Ctrl+C /
        cancel during a long backoff is honored promptly. Decrements by the
        intended chunk (not wall-clock) so it terminates deterministically."""
        remaining = seconds
        while remaining > 0 and not self._cancelled:
            chunk = min(1.0, remaining)
            time.sleep(chunk)
            remaining -= chunk

    def _check_timeout(self, stage_name: str) -> None:
        """Check workflow and stage deadlines. Raises on timeout."""
        now = time.monotonic()
        # uninterruptible stage 跑过 deadline 不 raise（软放行链路贯通，L3 冻结方案）。
        # 仅 warn 留痕（§1.2 可诊断）。连续 uninterruptible 链全部跑完后，链路后第一个
        # 非 uninterruptible stage 入口本函数会真实检查 deadline → 自然 raise 终止，
        # 无需 per-node 兑现、无需 lookahead 图结构。
        if getattr(self._current_stage, "uninterruptible", False):
            if (self._workflow_deadline is not None
                    and now > self._workflow_deadline):
                self.Logger.warn(
                    f"stage '{stage_name}' uninterruptible — ran past "
                    f"workflow deadline (soft let-through)")
            elif (self._stage_deadline is not None
                    and now > self._stage_deadline):
                self.Logger.warn(
                    f"stage '{stage_name}' uninterruptible — ran past "
                    f"stage deadline (soft let-through)")
            return
        if self._workflow_deadline is not None and now > self._workflow_deadline:
            if self._event_log:
                self._event_log.append(
                    evt.workflow_timeout(stage_name, self._workflow_deadline))
            elapsed = (now - self._workflow_started
                       if self._workflow_started is not None else None)
            raise WorkflowTimeoutError(
                self._workflow_deadline,
                budget_sec=self._workflow_budget_sec,
                elapsed_sec=elapsed)
        if self._stage_deadline is not None and now > self._stage_deadline:
            # Option A: a stage-deadline overrun is soft when the last agent
            # iteration succeeded — the run is slow but producing usable output
            # (e.g. swi_glu codegen ran 4484s against a 3600s budget yet emitted
            # a complete, salvageable operator). Hard-raising would discard it.
            # Only raise when the last iteration was NOT ok (partial/infra/fatal
            # — a genuinely stuck or failing run). max_iterations + the workflow
            # deadline still bound the soft path.
            if self._last_iter_ok:
                self.Logger.warn(
                    f"stage '{stage_name}' overran its stage deadline but the "
                    f"last agent iteration succeeded — continuing "
                    f"(soft timeout, Option A)")
                return
            if self._event_log:
                self._event_log.append(
                    evt.stage_timeout(stage_name, self._stage_deadline))
            elapsed = (now - self._stage_started
                       if self._stage_started is not None else None)
            raise StageTimeoutError(
                stage_name, self._stage_deadline,
                budget_sec=self._stage_budget_sec,
                elapsed_sec=elapsed)

    def _execute_actions(self, actions: list[Action], state: State | None = None) -> dict:
        """Execute action list. Route to backend/adapter based on action type.

        Args:
            actions: List of actions to execute.
            state: Current State, needed for non_interactive/on_decision context
                   when handling AskUserQuestion.
        """
        result: dict = {}
        spawn_actions: list[SpawnAgent] = []
        for action in actions:
            if isinstance(action, NoOp):
                result["noop"] = True
                result["noop_reason"] = action.reason
                # P33: stage 可显式声明 NoOp 为"确定性跳过"(契约已满足)—— 见
                # NoOp.contract_satisfied。runner 据此豁免 output_contract 未满足判定。
                if action.contract_satisfied:
                    result["noop_contract_satisfied"] = True
                continue
            elif isinstance(action, SpawnAgent):
                spawn_actions.append(action)
            elif isinstance(action, RunGate):
                self._execute_run_gate(action, result)
            elif isinstance(action, Integrate):
                self._execute_integrate(action, result)
            elif isinstance(action, AskUserQuestion):
                self._execute_ask_user_question(action, result, state)
            elif isinstance(action, UpdateDevRecord):
                self._execute_update_dev_record(action, result)
            elif isinstance(action, RunMeasure):
                self._execute_run_measure(action, result)
            else:
                # Other action types (LoadProfile, InitAdapter, etc.) are
                # consumed by their respective stage.transition() methods.
                pass

        # P9: multiple SpawnAgents in one iteration = a parallel work batch
        # (A5 codegen VF pre-verification). Run them concurrently in a thread
        # pool (each spawn is backend-isolated), and surface every result as
        # ``result["agent_results"]`` so the stage's transition can merge the
        # per-step outcomes. ``result["agent_result"]`` stays the FIRST ACTION's
        # result (deterministic action order, not as_completed completion order)
        # for backward compatibility with single-spawn consumers.
        if len(spawn_actions) == 1:
            self._execute_spawn_agent(spawn_actions[0], result)
        elif len(spawn_actions) > 1:
            self._execute_spawn_agents_parallel(spawn_actions, result)
        return result

    def _execute_spawn_agents_parallel(self, actions: list[SpawnAgent],
                                       result: dict) -> None:
        """Run multiple SpawnAgents concurrently via ThreadPoolExecutor.

        Each worker gets its own context copy (``context_callable``) so
        per-branch run.log/op_name bindings are not clobbered across threads
        (AU-8), matching the ForkJoin pattern in graph_executor. Concurrency
        cap = ``max_workers`` resolved the same way as fork-join: bounded by
        the number of actions and the CPU count. The stage controls how many
        actions it returns (its ``max_concurrent_vf``), so the pool here just
        executes whatever batch it is handed.
        """
        import os
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from ascendc_devkit.infra.log_capture import context_callable

        max_workers = min(len(actions) or 1, os.cpu_count() or 1)
        # m7: deterministic action order — ``agent_results`` and the fallback
        # ``agent_result`` are keyed to the action list order, not the thread
        # completion order (as_completed is racy and would make ``agent_result``
        # an arbitrary member for single-spawn consumers).
        order = {id(a): i for i, a in enumerate(actions)}

        def _run_one(action: SpawnAgent):
            inner: dict = {}
            self._execute_spawn_agent(action, inner)
            return action, inner.get("agent_result")

        completed: list[tuple[int, dict]] = []
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futs = {pool.submit(context_callable(_run_one), a): a
                    for a in actions}
            for fut in as_completed(futs):
                action, ar = fut.result()
                completed.append((order[id(action)],
                                  {"agent_result": ar, "action": action}))
        agent_results = [entry for _, entry in sorted(completed, key=lambda p: p[0])]
        result["agent_results"] = agent_results
        if agent_results:
            result["agent_result"] = agent_results[0]["agent_result"]
        if actions[0].working_dir:
            result["_working_dir"] = actions[0].working_dir

    # —— Action execution helpers ——

    def _execute_spawn_agent(self, action: SpawnAgent, result: dict) -> None:
        """Execute SpawnAgent: delegate to agent_backend."""
        if self._workspace and self._event_log:
            self._event_log.append(
                evt.action_start("spawn_agent", agent=action.agent_name))

        # The agent's skill allowlist rides on action.skills (built by the stage
        # via skill_config.skill_allowlist, bare flat names). Skills are
        # DISCOVERED natively from the flat .claude/skills tree — both backends
        # walk it (claude via the workspace skills anchor, opencode via cwd→git
        # worktree). No plugin resolution here; agent.md frontmatter lists the
        # bare skill names it may use, validated at manifest load time.
        from ascendc_devkit.capabilities.skill.loader import load_agent_manifest
        manifest = load_agent_manifest(action.agent_name)

        # Resolve model: action-level override > stage config map > SDK default.
        # stage_model() returns None for absent / "" / "default", which makes
        # the spawn pass model=None to the backend → SDK default (.claude/
        # settings.json model). See model_config.stage_model.
        model = action.model
        if model is None:
            from ascendc_devkit.orchestration.model_config import stage_model
            model = stage_model(self._current_stage_name)

        agent_result = None
        if self._agent_backend:
            # P5: check timeout before spawn, not just at iteration boundaries.
            # An agent spawn can last 100+ seconds; if the deadline falls during
            # one, the next check is only at the top of the next iteration.
            self._check_timeout(self._current_stage_name)
            # D3: 算剩余 deadline 传给 backend 做硬墙（min of workflow/stage deadline；
            # 两者都是 monotonic 绝对值，_run_stage_body 设置）。None = 不设硬墙。
            _dl_vals = [d for d in (self._workflow_deadline, self._stage_deadline)
                        if d is not None]
            _deadline = min(_dl_vals) if _dl_vals else None
            agent_result = self._agent_backend.spawn(
                action.agent_name, action.prompt, action.context,
                skills=action.skills,
                model=model,
                working_dir=action.working_dir,
                repo_baseline=action.repo_baseline,
                repo_root=action.repo_root,
                # Q7: fall back to the runner's tracked stage name when the
                # action didn't set one — gives batch-log attribution
                # (``[op/stage]``) for stages that don't manually set stage_name
                # (requirement/codegen/smoke/perf/...). Already-set names win.
                stage_name=action.stage_name or self._current_stage_name,
                branch_label=action.branch_label,
                resume_session_id=action.resume_session_id,
                resume_prompt=action.resume_prompt,
                primary_skill=action.primary_skill,
                deadline_monotonic=_deadline)
            result["agent_result"] = agent_result
            # D4: 硬终止留痕（backend 硬墙触发时填 aborted 字段；emit 一条 event 让
            # events.jsonl 能定位是哪个 agent+stage 被硬终止，§1.2 可诊断）。
            if (self._workspace and self._event_log
                    and agent_result is not None
                    and getattr(agent_result, "aborted", None)):
                self._event_log.append(evt.agent_aborted(
                    agent_name=action.agent_name,
                    reason=agent_result.aborted,
                    stage=self._current_stage_name or ""))

        # P4: 传 working_dir 给 transition 使用（设计阶段确定性磁盘读取）
        if action.working_dir:
            result["_working_dir"] = action.working_dir

        if self._workspace and self._event_log:
            status = "ok"
            if agent_result is not None:
                status = agent_result.status if agent_result.status == "ok" else agent_result.status
            elif self._agent_backend is None:
                status = "no_backend"
            # step-67: spawn_context emitted POST-spawn so it carries the actual
            # transcript path + session_id (action↔session localization, P2 — a
            # foreign reviewer maps a failed action to its session file directly).
            _transcript = ""
            if agent_result is not None and getattr(agent_result, "transcript", None) is not None:
                try:
                    _transcript = str(agent_result.transcript.relative_to(self._workspace.dir))
                except Exception:
                    _transcript = str(agent_result.transcript)
            _sid = (getattr(agent_result, "session_id", "") or "") if agent_result is not None else ""
            self._event_log.append(evt.spawn_context(
                agent_name=action.agent_name,
                prompt=action.prompt[:500],
                context_keys=list(action.context.keys()) if action.context else [],
                skills=list(action.skills) if action.skills else list(manifest.skills),
                working_dir=(str(action.working_dir) if action.working_dir
                             else str(self._workspace.artifacts)),
                transcript=_transcript, session_id=_sid))
            # step-67: emit one output_truncated event per turn the backend
            # flagged as length-cut (silent-truncation visibility, P3).
            # M2 (step-68 review): reason is the neutral "output_limit" — the
            # backend's truncated_turns carries only turn NUMBERS (the consumer
            # drops the per-turn stop_reason), so the literal ceiling reason
            # varies by backend (claude max_tokens/max_output_tokens, opencode
            # length) and hardcoding one would misdiagnose the other. Generic
            # label + the turn number is the honest signal; per-backend wording
            # would require threading stop_reason through AgentResult (deferred).
            if agent_result is not None and getattr(agent_result, "truncated_turns", None):
                for _t in agent_result.truncated_turns:
                    self._event_log.append(evt.output_truncated(
                        agent_name=action.agent_name, turn=_t,
                        reason="output_limit",
                        stage=self._current_stage_name or ""))
            self._event_log.append(
                evt.action_complete("spawn_agent", result=status))

    def _execute_run_measure(self, action: RunMeasure, result: dict) -> None:
        """Execute RunMeasure: run the shell command, record rc + tail of stdout/stderr.

        Precision_debug run_tests 纯 Python 测量（§judgment-ownership N1）。确定性执行
        run-cases + build-queue 脚本，无 LLM。结果写 result["measure_result"]（rc + tail），
        RunTestsSubstage.transition 据此判定测量失败（rc != 0 → abort 路径）。
        OSError / TimeoutExpired → rc=-1（观测可诊断，§3.7 不静默）。
        """
        if self._workspace and self._event_log:
            self._event_log.append(
                evt.action_start("run_measure", command=str(action.command)[:240]))
        try:
            proc = subprocess.run(
                action.command, shell=True, capture_output=True, text=True,
                cwd=action.working_dir, timeout=action.timeout)
            result["measure_result"] = {
                "returncode": proc.returncode,
                "stdout": (proc.stdout or "")[-4000:],
                "stderr": (proc.stderr or "")[-2000:],
            }
        except (OSError, subprocess.TimeoutExpired) as exc:
            result["measure_result"] = {
                "returncode": -1, "error": str(exc), "stdout": "", "stderr": ""}
            Logger.warn(f"[RUN-MEASURE] subprocess failed: {exc}")
        if self._workspace and self._event_log:
            status = "ok" if result["measure_result"]["returncode"] == 0 else "fail"
            self._event_log.append(
                evt.action_complete("run_measure", result=status))

    def _execute_run_gate(self, action: RunGate, result: dict) -> None:
        """Execute RunGate: evaluate gate with evidence, write real GateResult."""
        if self._workspace and self._event_log:
            self._event_log.append(
                evt.action_start("run_gate", gate=action.gate_name))

        gate = action.gate or self._gate_registry.get(action.gate_name)
        if gate is not None:
            gate_result = gate.evaluate(action.evidence)
            result["gate_result"] = {
                "gate": action.gate_name,
                "passed": gate_result.passed,
                "reason": gate_result.reason,
                "metrics": gate_result.metrics,
            }
        else:
            # No gate found — fall back to pass for backward compatibility
            self.Logger.warn(f"Gate '{action.gate_name}' not found, defaulting to passed")
            result["gate_result"] = {"gate": action.gate_name, "passed": True}

        if self._workspace and self._event_log:
            passed = result["gate_result"]["passed"]
            self._event_log.append(
                evt.action_complete("run_gate",
                    result="pass" if passed else "fail",
                    gate=action.gate_name))

    def _execute_integrate(self, action: Integrate, result: dict) -> None:
        """Execute Integrate: call repository adapter to materialize or apply changes."""
        adapter = self._adapters.get("repository")
        if adapter is None:
            self.Logger.warn("No repository adapter available for Integrate action")
            result["integration_result"] = {"status": "error", "error": "No repository adapter"}
            return

        if action.action == "materialize_new_operator":
            try:
                target_files = adapter.materialize_new_operator(
                    op=action.operator,
                    sources=action.sources or {},
                    dest_root=action.dest_root or Path("."),
                )
                result["integration_result"] = {"status": "ok", "files": len(target_files)}
                result["target_files"] = target_files
            except Exception as e:
                self.Logger.error(f"materialize_new_operator failed: {e}")
                result["integration_result"] = {"status": "error", "error": str(e)}
                result["target_files"] = []

    def _execute_ask_user_question(self, action: AskUserQuestion, result: dict,
                                    state: State | None) -> None:
        """Execute AskUserQuestion: resolve via handler, terminal UI, or auto-decide."""
        options_text = [opt.label for opt in action.options]
        if not options_text:
            result["decision"] = ""
            return

        # 1) Use injected decision_handler if available
        if self._decision_handler:
            try:
                answer = self._decision_handler(
                    action.question, options_text,
                    default_index=action.default_index,
                )
                result["decision"] = answer
                return
            except DecisionPendingError:
                raise
            except Exception as e:
                self.Logger.warn(f"Decision handler failed: {e}, falling back")

        # 2) Try interactive terminal UI first when not explicitly non-interactive.
        #    _render_ask_user_ui raises EOFError when stdin is non-TTY (CI /
        #    backgrounded / piped); we then fall through to the on_decision
        #    strategy below instead of hanging or silently defaulting.
        interactive = state is None or not state.non_interactive
        if interactive:
            from ascendc_devkit.capabilities.mcp_tools import _render_ask_user_ui
            default_idx = action.default_index if action.default_index is not None else 0
            try:
                result["decision"] = _render_ask_user_ui(
                    action.question, options_text, default_idx)
                return
            except EOFError:
                self.Logger.warn(
                    "Interactive prompt requested but stdin is non-TTY; "
                    f"applying on_decision="
                    f"{getattr(state, 'on_decision', 'default')}")

        # 3) Resume replay: a prior `respond` wrote the answer for this paused
        #    question. Consume it so a non-interactive abort run doesn't loop on
        #    resume (rewrite pending + re-raise forever). Mirrors resolve_ambiguity's
        #    "Resume case" (mcp_tools.py) — path B (MCP tool) already replayed;
        #    path A (this AskUserQuestion action) did not, which made any
        #    stage-emitted AskUserQuestion un-resumable in non-interactive abort
        #    mode (e.g. the chip cross-generation pre-design gate, step-34 D3).
        if self._workspace:
            response_path = Path(self._workspace.dir) / "decision_response.json"
            if response_path.exists():
                try:
                    data = json.loads(response_path.read_text())
                except (json.JSONDecodeError, OSError):
                    data = {}
                # A free-text override (respond --text) takes precedence over a
                # numeric choice, mirroring the interactive custom-input slot.
                custom = data.get("text")
                if isinstance(custom, str) and custom.strip():
                    response_path.unlink(missing_ok=True)
                    result["decision"] = custom
                    return
                try:
                    choice_idx = int(data.get("choice", 1)) - 1
                except (TypeError, ValueError):
                    choice_idx = -1
                if 0 <= choice_idx < len(options_text):
                    selected = options_text[choice_idx]
                    response_path.unlink(missing_ok=True)
                    result["decision"] = selected
                    return
                # Invalid / out-of-range response: leave the file in place (the
                # user can re-respond with a valid choice) and fall through.

        # 4) Non-interactive strategy (also the fallback for a non-TTY interactive
        #    run): abort → pause for human respond; default → auto-pick default.
        on_decision = getattr(state, "on_decision", "default") if state else "default"
        if on_decision == "abort":
            if self._workspace:
                pending = {
                    "question": action.question,
                    "options": options_text,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                ws_dir = Path(self._workspace.dir)
                ws_dir.mkdir(parents=True, exist_ok=True)
                (ws_dir / "pending_decision.json").write_text(
                    json.dumps(pending, ensure_ascii=False, indent=2))
            result["decision"] = "__DECISION_PENDING__"
            raise DecisionPendingError(
                question=action.question,
                options=options_text,
                workspace_dir=str(self._workspace.dir) if self._workspace else "",
            )

        idx = action.default_index if action.default_index is not None else 0
        result["decision"] = (
            options_text[idx] if 0 <= idx < len(options_text) else options_text[0])

    def _execute_update_dev_record(self, action: UpdateDevRecord, result: dict) -> None:
        """Execute UpdateDevRecord: write dev_record via repository adapter."""
        adapter = self._adapters.get("repository")
        if adapter is None:
            self.Logger.warn("No repository adapter available for UpdateDevRecord action")
            result["dev_record"] = {"status": "error", "error": "No repository adapter"}
            return

        op_dir = action.path
        if op_dir is None:
            self.Logger.warn("UpdateDevRecord has no path, skipping")
            result["dev_record"] = {"status": "skipped", "reason": "No op_dir path"}
            return

        from datetime import datetime, timezone
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "change_summary": action.change_summary or "N/A",
            "target_files": action.target_files,
            "requirement_path": str(action.requirement_path) if action.requirement_path else "N/A",
        }

        try:
            record_path = adapter.write_dev_record(Path(op_dir) if not isinstance(op_dir, Path) else op_dir, entry)
            result["dev_record"] = {"status": "ok", "path": str(record_path)}
        except Exception as e:
            self.Logger.error(f"write_dev_record failed: {e}")
            result["dev_record"] = {"status": "error", "error": str(e)}
