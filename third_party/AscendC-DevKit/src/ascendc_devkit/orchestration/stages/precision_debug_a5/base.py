"""Base class and shared helpers for A5 precision_debug sub-stages."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

from ascendc_devkit.domain.contract import StageIOContract
from ascendc_devkit.orchestration.kernel.action import SpawnAgent
from ascendc_devkit.orchestration.skill_config import skill_allowlist
from ascendc_devkit.orchestration.stages.design_substages import _DesignSubstage

if TYPE_CHECKING:
    from ascendc_devkit.orchestration.kernel.state import State


class A5PrecisionDebugContractError(RuntimeError):
    """A5 checkpoint / phase artifact violates the mandatory contract."""
    pass


# 用例来源词汇表（与 ``TestCase.source`` 一一对应）。baseline 报告需把 st-design
# 生成用例（devkit）与 cann-bench 原有用例（cannbench）分开统计；两者在各自 loader
# 构造时即打标（§1.12 结构信号，不靠命名猜测）。
CASE_SOURCE_CANN_BENCH = "cannbench"
CASE_SOURCE_DEVKIT = "devkit"
_CASE_SOURCE_UNKNOWN = "unknown"


def case_source_composition(cases) -> dict[str, int]:
    """按来源统计用例数 → ``{"cannbench": N, "devkit": M, "unknown": K}``。

    baseline「st-design vs cann-bench」拆分的**唯一通路**（§1.15）：框架从这里拿
    权威组成注入 prompt 供 agent 报告，并在 transition 复核 agent 上报的 st-design
    总数。``unknown`` 兜住无来源标记的存量/手写用例（fail-open 计数，绝不静默并入
    任一来源）。
    """
    counts = {
        CASE_SOURCE_CANN_BENCH: 0,
        CASE_SOURCE_DEVKIT: 0,
        _CASE_SOURCE_UNKNOWN: 0,
    }
    for tc in cases or []:
        src = getattr(tc, "source", "") or _CASE_SOURCE_UNKNOWN
        if src not in counts:
            src = _CASE_SOURCE_UNKNOWN
        counts[src] += 1
    return counts


class A5PrecisionDebugSubstage(_DesignSubstage):
    """Base class for A5 precision_debug sub-stages.

    Inherits ``_DesignSubstage`` for the shared skill-assignment hooks
    (``_assigned_skill`` / ``artifact_contract`` via ``STAGE_SKILL_MAP`` and
    ``SchemaLoader``).  The A5 file relay is sub-agent autonomous read/write of
    ``{debug_dir}/``; the framework reads checkpoint.json only for routing.
    """

    name: str = ""
    agent_name: str = ""
    fail_strategy = "continue"
    default_max_iterations = 1
    needs_iteration_safety_net = False

    _schema_files: list[str] = []
    _schema_contract_cache: object = None
    # Whether this stage's output follows the ``{stem}_round_{round}_result.json``
    # convention (framework-decided round). baseline writes the plain latest path
    # only, so exact-round reads are skipped there.
    _round_file_convention: bool = True

    # Per-case stages whose spawn should reconcile the queue against the latest
    # full KernelLaunch run and skip already-resolved cases (so a precision-correct
    # case is never re-scheduled for debugging). baseline / op_plugin_debug are
    # excluded: they must see the queue exactly as the previous stage left it.
    _reconcile_queue_at_spawn: bool = False

    # Per-case stages (kernel_debug / vf_test / vector_error_debug) that advance
    # to the NEXT failed case when consecutive aborts exhaust the anneal budget.
    # Without this, an aborted spawn loops ``agent_aborted`` on the same case;
    # after a few identical loopbacks the graph_executor's generic stagnation
    # guard falls through to the group's *linear successor* (vf_test for
    # kernel_debug) — a semantically wrong sibling with zero VF evidence. The
    # per-case stop-loss (skip + advance, same as the ``exhausted`` path) keeps
    # "can't process this case" on one semantic path (§2.5 唯一通路). Non
    # per-case stages (baseline / op_plugin_debug) keep the original
    # ``abort_exhausted`` → escalate behaviour.
    _abort_advances_case: bool = False

    # Whether the prompt carries the "当前待处理 case" block (the queue entry at
    # ``current_case_index``). Per-case stages that debug a single case
    # (kernel_debug / vf_test / vector_error_debug) need it; global validation
    # stages (baseline 双跑分类 / op_plugin_debug 适配层循环) do NOT solve
    # precision and must not be shown a "case to fix" — it would
    # mislead the agent into attempting repairs instead of running the suite.
    _inject_current_case: bool = True

    # Per-case debug stages (kernel_debug / vf_test / vector_error_debug) debug
    # the kernel/tiling layer only. When kernel-first baseline routing leaves
    # op_plugin-layer cases in the same failed_case_queue, those are foreign work
    # for op_plugin_debug (their kernel is provably correct under KernelLaunch)
    # and must be skipped during queue advancement — a per-case debug agent must
    # never be spawned on an op_plugin case. baseline / op_plugin_debug consume
    # the whole queue and keep this False.
    _skip_op_plugin_in_advance: bool = False

    def teardown(self, state: "State", *, interrupt_reason: str) -> "State":
        """Best-effort rollback to best_commit on interruption."""
        from ascendc_devkit.infra.logger import Logger
        from ascendc_devkit.infra.repo_guard import RepoGuard
        cp = _load_a5_checkpoint(state)
        best = cp.get("best_commit") if cp else None
        op_dir = _operator_dir(state)
        if not best or not op_dir:
            return state
        repo_root = (state.op_identity.repo_root
                     if state.op_identity and state.op_identity.repo_root
                     else op_dir)
        try:
            guard = RepoGuard()
            if not cp.get("rollback_safe", True):
                Logger.warn("A5 precision-debug teardown: rollback_safe=false; preserving op_dir")
                return state
            if not guard.is_clean(repo_root, op_dir):
                Logger.warn("A5 precision-debug teardown: op_dir dirty; refusing checkout+clean")
                return state
            rolled = guard.rollback(repo_root, op_dir, best)
        except Exception as e:  # noqa: BLE001
            Logger.warn(f"A5 precision-debug teardown: rollback raised {e}")
            return state
        if rolled:
            Logger.warn(f"A5 precision-debug teardown ({interrupt_reason}): "
                        f"rolled back op_dir to best_commit {best[:8]}")
        else:
            Logger.warn(f"A5 precision-debug teardown: rollback to {best[:8]} failed")
        return state

    def _phase_filename(self) -> str:
        return self._schema_files[0] if self._schema_files else ""

    def _skill_dir(self) -> str:
        assigned = self._assigned_skill()
        if not assigned:
            return ""
        project_root = Path(__file__).resolve().parents[4]
        return str(project_root / ".claude" / "skills" / assigned)

    def _workspace_dir(self, state: "State") -> str:
        ws = getattr(state, "_workspace", None)
        return str(ws.dir) if ws is not None else ""

    def _common_context(self, state: "State") -> dict:
        op_dir = _operator_dir(state)
        ws_dir = self._workspace_dir(state)
        ctrl = _control_path(state)
        phase = _phase_path(state, self._phase_filename(), round_suffix=True)
        phase_latest = _phase_path(state, self._phase_filename(), round_suffix=False)
        ct = (state.codegen_manifest or {}).get("callable_target") if state.codegen_manifest else None
        op_name = (state.op_name
                   or (state.op_identity.spec.name if state.op_identity else ""))
        cp = _load_a5_checkpoint(state) or {}
        iter_n = int(cp.get("run_iter_counter", 0))
        # 当前待处理 case（框架权威来源）：由 checkpoint 的 failed_case_queue 与
        # current_case_index 唯一决定。注入给所有 per-case 阶段（kernel_debug /
        # vf_test / vector_error_debug），保证各 agent 与框架看到
        # 同一个 current case，避免 agent 自行推断（如取 best_snapshot 首个失败
        # case）导致与框架路由不一致（§2.9 构造性保证优先于检查门）。
        _queue = cp.get("failed_case_queue", []) or []
        _case_idx = int(cp.get("current_case_index", 0) or 0)
        _current_case = (_queue[_case_idx]
                         if 0 <= _case_idx < len(_queue) else None)
        from ascendc_devkit.orchestration.runtime_config import (
            precision_debug_a5_max_attempts_per_case,
            precision_debug_a5_max_iterations,
        )
        from ascendc_devkit.orchestration.runtime_config import (
            precision_debug_max_corrective_cycles,
            precision_debug_time_budget_sec,
        )
        debug_dir = _debug_artifacts_dir(state)
        debug_dir_str = str(debug_dir) if debug_dir else ""
        from ascendc_devkit.orchestration.stages.precision_debug_a5.conclusions import (
            _conclusions_path,
            _format_conclusions_block,
        )
        conclusions_path = _conclusions_path(state)
        prior_conclusions = _format_conclusions_block(state)
        # Current phase directory / latest result path (log relay targets).
        current_stem = _PHASE_STEM_MAP.get(self._phase_filename(), self._phase_filename())
        current_phase_dir = (debug_dir / current_stem) if debug_dir else None
        # Baseline result path is the main cross-phase read target.
        baseline_phase_dir = (debug_dir / "baseline") if debug_dir else None
        baseline_phase_json_path = (baseline_phase_dir / "baseline_result.json") if baseline_phase_dir else None
        # Deploy/runtime paths from prior deploy stage.
        deploy = state.deploy_result
        deploy_install = getattr(deploy, "install_path", "") or "" if deploy else ""
        deploy_python = getattr(deploy, "python_path", "") or "" if deploy else ""
        deploy_ld = getattr(deploy, "ld_library_path_add", "") or "" if deploy else ""
        # Helper paths.
        code_dir = str(op_dir) if op_dir else ""
        dev_record_dir = state.codegen_record_dir or ""
        cases_csv_path = str(state.cases_path) if state.cases_path else ""
        golden_module_path = str(state.golden_path) if state.golden_path else ""
        tiling_bounds_check_script_path = (
            str(debug_dir / "scripts" / "tiling_bounds_check.py") if debug_dir else ""
        )
        klt_script_path = (
            str(debug_dir / "baseline" / f"{op_name}_kernel_launch_test.py")
            if debug_dir and op_name else ""
        )
        # Skill-convention round result path (primary write target for most A5
        # skills: ``{phase_dir}/{stem}_round_{round}_result.json``). The round is
        # decided solely by the framework from the per-stage checkpoint counter
        # (``{stem}_round``, e.g. ``vf_round`` / ``op_plugin_round`` /
        # ``kernel_debug_round``); the prompt tells the agent to write exactly this
        # path and the transition reads exactly this path — no directory scan, so
        # leftover files from a previous run can never be mistaken for this round.
        if self._round_file_convention:
            phase_round_result_path = _expected_round_result_path(
                state, self._phase_filename())
        else:
            # 非 round 约定阶段（baseline）直接写 plain latest 路径，不注入 round
            # 文件路径：注入 ``{stem}_round_{n}_result.json`` 与任务（"本阶段结果
            # 写入 {latest_path}"）冲突，且 transition 的 _sync_phase_latest 兜底
            # 会误用陈旧 round 文件覆盖 agent 新鲜产物 → 假 status_mismatch → 重试
            # 循环（2026-08-24 baseline↔baseline 轨迹）。统一指向 latest 路径。
            phase_round_result_path = _phase_path(
                state, self._phase_filename(), round_suffix=False)
        ctx = {
            "checkpoint_path": str(ctrl) if ctrl else "",
            "phase_json_path": str(phase) if phase else "",
            "phase_json_latest_path": str(phase_latest) if phase_latest else "",
            "phase_round_result_path": str(phase_round_result_path) if phase_round_result_path else "",
            "phase_dir": str(current_phase_dir) if current_phase_dir else "",
            "baseline_phase_json_path": str(baseline_phase_json_path) if baseline_phase_json_path else "",
            "code_dir": code_dir,
            "debug_dir": debug_dir_str,
            "dev_record_dir": dev_record_dir,
            "workspace_dir": ws_dir,
            "conclusions_path": str(conclusions_path) if conclusions_path else "",
            "prior_conclusions": prior_conclusions,
            "op_name": op_name,
            "skill_dir": self._skill_dir(),
            "phase_name": self.name,
            "phase_filename": self._phase_filename(),
            "iter_n": iter_n,
            "golden": {
                "path": str(state.golden_path) if state.golden_path else "",
                "entry": state.golden_entry or "",
                "input_type": state.golden_input_type or "",
            },
            "golden_module_path": golden_module_path,
            "cases_csv_path": cases_csv_path,
            "klt_script_path": klt_script_path,
            "tiling_bounds_check_script_path": tiling_bounds_check_script_path,
            "deploy_install_path": deploy_install,
            "deploy_python_path": deploy_python,
            "deploy_ld_path": deploy_ld,
            "build_command": f"ascendc-devkit redeploy --workspace {ws_dir}" if ws_dir else "",
            "test_command": f"ascendc-devkit run-cases --workspace {ws_dir}" if ws_dir else "",
            "callable_target": ct,
            "design_target_chip": state.design_target_chip,
            "device_id": state.npu_id or 0,
            "current_case": _current_case,
            "current_case_index": _case_idx,
            "failed_case_queue": _queue,
            "test_case_source_composition": case_source_composition(
                getattr(state, "test_cases", None)),
            "precision_max_iterations": precision_debug_a5_max_iterations(),
            "precision_max_corrective_cycles": precision_debug_max_corrective_cycles(),
            "precision_max_attempts_per_case": precision_debug_a5_max_attempts_per_case(),
            "precision_time_budget_sec": precision_debug_time_budget_sec(),
        }
        return ctx

    def actions(self, state: "State", iteration: int = 1):
        from ascendc_devkit.orchestration.stages.precision_debug_a5.git_safety import (
            ensure_entry_snapshot,
        )
        ensure_entry_snapshot(state, record_anchor=True)
        _advance_phase_counter(state)
        self._provision_phase_scripts(state)
        if self._reconcile_queue_at_spawn:
            # 调度前调和：用最新 KL 全量结果把精度已通过的 case 标 resolved，并跳过
            # 已 resolved/skipped 的队列项，避免把通过精度的 case 派给调试 agent
            # （2026-08-10 case_18 轨迹：全量 KL 早已验证其 PASS，仍被位置推进
            # 调度给 kernel_debug）。
            self._reconcile_queue_for_spawn(state)
        # guard 必须在 reconcile 之后保存：guard 是 transition 侧
        # _restore_framework_routing_fields 的恢复源（防 agent 篡改框架字段）。
        # 若在 reconcile 之前保存，transition 恢复时会把调和结果（标 resolved +
        # 推进 current_case_index）一并回滚成预调和状态——agent 被告知处理的是
        # reconcile 后的当前 case（_common_context 读 reconcile 后的 checkpoint），
        # transition 却按预调和索引路由，两者错位（2026-08-11 轨迹：spawn 注入
        # current_case=17、index=1，transition 恢复后 index=0 落到已 pass 的 case 18）。
        from ascendc_devkit.orchestration.stages.precision_debug_a5.checkpoint import (
            _save_framework_checkpoint_guard,
        )
        _save_framework_checkpoint_guard(state)
        skill = self._assigned_skill()
        ctx = self._common_context(state)
        return [SpawnAgent(
            agent_name=self.agent_name,
            prompt=self._build_prompt(ctx, iteration),
            context=ctx,
            skills=skill_allowlist(skill),
            primary_skill=skill,
            working_dir=_operator_dir(state),
            repo_root=(state.op_identity.repo_root
                       if state.op_identity else None),
            stage_name="precision_debug",
        )]

    def _reconcile_queue_for_spawn(self, state: "State") -> None:
        """Reconcile ``failed_case_queue`` from the latest KL run and skip done cases.

        Called at spawn time (before ``_common_context``) for per-case stages that
        consume ``pending`` queue entries. Two steps, both idempotent:
        1. ``_reconcile_queue_from_kl`` — refresh ``max_diff_kl`` and mark
           KL-passing kernel-layer cases ``resolved``;
        2. ``_advance_past_resolved`` — move ``current_case_index`` to the next
           pending/debugging entry so the spawn never targets a resolved case
           (per-case stages additionally skip ``error_layer=op_plugin`` entries
           via ``_skip_op_plugin_in_advance`` — see ``_case_skip_for_debug``).

        Safe when no KL summary exists yet (no-op), and safe when the whole queue
        is resolved (index lands at ``len(queue)``; ``resolve_condition`` will
        route to baseline rather than spawn a debug agent).
        """
        from ascendc_devkit.orchestration.stages.precision_debug_a5.case_loop import (
            _advance_past_resolved,
            _load_latest_kl_data,
            _per_case_kl_results,
            _reconcile_queue_from_kl,
        )
        cp = _load_a5_checkpoint(state)
        kl_data = _load_latest_kl_data(state)
        if kl_data:
            _reconcile_queue_from_kl(cp, _per_case_kl_results(kl_data))
        cp = _advance_past_resolved(
            cp, skip_op_plugin=self._skip_op_plugin_in_advance)
        _save_a5_checkpoint(state, cp)

    def _provision_phase_scripts(self, state: "State") -> None:
        """Copy framework-owned diagnostic scripts into ``{debug_dir}/scripts/``.

        The kernel_debug prompt and skill instruct the agent to run
        ``{debug_dir}/scripts/tiling_bounds_check.py``; without provisioning
        here that path never exists and the P0 tiling check cannot run. The
        source lives beside this package (``stages/precision_debug_a5/scripts/``);
        it is copied at every spawn so a stale/partial previous copy is
        overwritten by the canonical one.
        """
        import shutil
        from ascendc_devkit.infra.logger import Logger
        debug_dir = _debug_artifacts_dir(state)
        if debug_dir is None:
            return
        scripts_dir = Path(__file__).resolve().parent / "scripts"
        target_dir = debug_dir / "scripts"
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            for src in scripts_dir.iterdir():
                if src.is_file():
                    shutil.copy2(src, target_dir / src.name)
        except OSError as exc:
            Logger.warn(f"[A5-PD-PROVISION] script copy failed: {exc}")

    def _build_prompt(self, ctx: dict, iteration: int) -> str:
        paths_block = self._format_paths_block(ctx)
        conclusions_block = ctx.get("prior_conclusions") or ""
        phase_block = self._phase_prompt(ctx, iteration)
        return "\n".join([paths_block, "", conclusions_block, "", phase_block])

    def _format_paths_block(self, ctx: dict) -> str:
        """Minimal path context block injected into every A5 precision-debug prompt.

        Skills/agents should derive subpaths from these storage roots instead
        of reconstructing the layout.
        """
        golden = ctx.get("golden") or {}
        lines = [
            "## 上下文路径（由编排层注入，直接使用以下变量名）",
            f"- `debug_dir`: {ctx.get('debug_dir') or '<未提供>'}  # precision debug 阶段产物/日志根目录",
            f"- `code_dir`: {ctx.get('code_dir') or '<未提供>'}  # 算子源码目录",
            f"- `dev_record_dir`: {ctx.get('dev_record_dir') or '<未提供>'}  # 开发记录目录（coding_index.md 等）",
            f"- `workspace_dir`: {ctx.get('workspace_dir') or '<未提供>'}  # workspace 根目录（用于运行命令）",
            f"- `conclusions_path`: {ctx.get('conclusions_path') or '<未提供>'}  # 跨阶段结论接力文件（所有已完成 agent 的一段话结论；开工前读它，了解流程已得出的结论）",
            f"- `golden_module_path`: {ctx.get('golden_module_path') or '<未提供>'}  # golden.py 绝对路径（直接传给 load_golden）",
            f"- `cases_csv_path`: {ctx.get('cases_csv_path') or '<未提供>'}  # cases.csv 绝对路径（直接传给 load_cases）",
            f"- `golden.entry`: {golden.get('entry') or '<未提供>'}  # golden 函数入口名（cann-bench 用算子名；手写 fixture 用 reference）",
            f"- `golden.input_type`: {golden.get('input_type') or '<未提供>'}  # golden 期望的输入类型：numpy 或 torch（与 run-cases harness 一致）",
            "",
            "子路径约定（已注入实际值）：",
            f"- checkpoint: `{ctx.get('debug_dir') or '<debug_dir>'}/checkpoint.json`",
            f"- baseline 产物: `{ctx.get('debug_dir') or '<debug_dir>'}/baseline/`",
            f"- baseline KernelLaunch 脚本: `{ctx.get('debug_dir') or '<debug_dir>'}/baseline/{ctx.get('op_name') or '<op_name>'}_kernel_launch_test.py`",
            f"- tiling_bounds_check 脚本: `{ctx.get('debug_dir') or '<debug_dir>'}/scripts/tiling_bounds_check.py`",
            f"- 当前阶段产物目录: `{ctx.get('debug_dir') or '<debug_dir>'}/{_PHASE_STEM_MAP.get(ctx.get('phase_filename', ''), ctx.get('phase_filename', ''))}/`",
            f"- 当前阶段结果文件: `{ctx.get('phase_round_result_path') or '<phase_round_result_path>'}`（skill round 约定见 `phase_round_result_path`",
            f"- op_plugin 层代码: `{ctx.get('code_dir') or '<code_dir>'}/op_plugin/`",
        ]
        lines.append("")
        if self._inject_current_case:
            lines.append(self._format_current_case_block(ctx))
        return "\n".join(lines)

    def _format_current_case_block(self, ctx: dict) -> str:
        """框架注入的当前 case（权威来源），供 per-case 阶段（kernel_debug /
        vf_test / vector_error_debug）统一使用。

        当前 case 由框架从 checkpoint 的 `failed_case_queue[current_case_index]`
        唯一决定并注入到 prompt；agent 不得自行推断（如取 best_snapshot 首个失败
        case / kl_result 首个失败项）——那会与框架路由、以及其它阶段实际处理的 case
        产生分歧（§2.9 构造性保证）。若注入缺失（异常场景），才回退读取
        `{debug_dir}/checkpoint.json`。
        """
        cc = ctx.get("current_case") or {}
        idx = ctx.get("current_case_index", 0)
        queue = ctx.get("failed_case_queue") or []
        dbg = ctx.get("debug_dir") or "<debug_dir>"
        if not cc:
            # baseline 首轮队列尚未构建：无当前 case，提示以 checkpoint 为准。
            return "\n".join([
                "## 当前待处理 case（框架注入，权威来源）",
                f"- `current_case_index`: {idx}（queue 长度 {len(queue)}，baseline 首轮可能为空）",
                "- `current_case`: <无>（首轮无失败 case 或队列未构建）",
                f"- 若本阶段需要当前 case，回退读取 `{dbg}/checkpoint.json` 的 `failed_case_queue[current_case_index]`。",
            ])
        return "\n".join([
            "## 当前待处理 case（框架注入，权威来源）",
            f"- `current_case_index`: {idx}",
            f"- `current_case.case_id`: {cc.get('case_id')}",
            f"- `current_case.shape`: {cc.get('shape') or '<无>'}",
            f"- `current_case.dtype`: {cc.get('dtype') or '<无>'}",
            f"- `current_case.error_layer`: {cc.get('error_layer') or '<无>'}",
            f"- `current_case.failure_type`: {cc.get('failure_type') or '<无>'}",
            f"- `current_case.attempt_count`: {cc.get('attempt_count', 0)}",
            f"- `current_case.max_diff_rc`: {cc.get('max_diff_rc') if cc.get('max_diff_rc') is not None else '<无>'}",
            f"- `current_case.max_diff_kl`: {cc.get('max_diff_kl') if cc.get('max_diff_kl') is not None else '<无>'}",
            "（`max_diff_kl` 为最新一次 KernelLaunch 测量，kernel_debug 修复后全量重测、baseline 双跑更新后框架回写；"
            "`max_diff_rc` 为最近一次 run-cases 测量，仅 baseline 双跑更新——两者都不是修复前的冻结值）",
            "",
            "**本阶段只针对这一个 case；禁止自行推断当前 case**（如取 best_snapshot 首个失败",
            f"case 或 kl_result 首个失败项）。完整失败队列见 `{dbg}/checkpoint.json` 的",
            "`failed_case_queue`，框架负责维护 `current_case_index`。",
        ])

    def _phase_prompt(self, ctx, iteration) -> str:
        raise NotImplementedError

    # ———————————————————————————————————————————————————————————————————
    # agent 自报状态（RETURN 行）解析与校验
    # ———————————————————————————————————————————————————————————————————
    # 每个 A5 阶段 SKILL 都要求 agent 最后输出一行：
    #   ``## RETURN: status=COMPLETED, phase={name}, {status_key}={value}, ...``
    # （baseline → baseline_status；kernel_debug → debug_status；vf_test →
    # vf_status；vector_error_debug → vector_error_status；op_plugin_debug →
    # debug_status）。
    #
    # 编排层把该自报状态作为**路由判据之一**：与 result JSON 中读到的状态交叉
    # 校验。自报状态异常（RETURN 块缺失 / status 非 COMPLETED / phase 不符 /
    # 状态值非法）时，不静默用默认值兜底，而是注入 `_agent_status_abnormal`
    # → resolve_condition 走 retry 重试该 agent（§1.3 加载期校验优于运行期暴露，
    # §1.2 可诊断：异常留痕不吞掉）。
    #
    # 兼容性：老 backend / 无 final_response 的 spawn（如测试桩）→ 解析器返回
    # {}，视为"无自报状态"，不做严格校验（避免破坏既有 stub 测试）。

    @staticmethod
    def _parse_agent_return(result) -> dict:
        """从 transition 的 ``result`` 中提取 agent 自报 RETURN 状态。

        返回 dict（可能为空）：``{"status", "phase", "error_type"}`` + 各阶段
        ``{status_key}``（如 ``debug_status``）。值统一大写。解析不到 → {}。
        """
        if not isinstance(result, dict):
            return {}
        agent_result = result.get("agent_result")
        if agent_result is None:
            return {}
        final_response = getattr(agent_result, "final_response", None)
        if not final_response:
            return {}
        return parse_agent_return_block(final_response)

    def _status_key(self) -> str:
        """本阶段 result JSON 中的路由状态字段名。"""
        return _STATUS_KEY_BY_PHASE.get(self.name, "")

    def _validate_agent_return(self, result, phase_result: dict) -> dict:
        """交叉校验 agent 自报状态与 result JSON 状态。

        - 无 self._status_key()（未知阶段）→ 不校验，返回 {}。
        - result 无 agent_result / 无 final_response（stub 测试）→ 不校验。
        - RETURN 块缺失或 status != COMPLETED → 异常。
        - phase 存在但不匹配本阶段 → 异常。
        - 自报 status_key 存在但与 result JSON 不一致 → 异常（留痕）。

        返回异常描述 dict（空 = 正常）；调用方把它并入 dc 并路由 retry。
        """
        key = self._status_key()
        if not key:
            return {}
        if not (isinstance(result, dict) and result.get("agent_result") is not None):
            return {}
        agent_result = result.get("agent_result")
        final_response = getattr(agent_result, "final_response", None)
        if not final_response:
            # 无 final_response（stub backend / 老版本）→ 无法校验，宽容放行，
            # 避免破坏既有 stub 测试与 resume 场景。
            return {}
        ret = self._parse_agent_return(result)
        if not ret:
            # 有 final_response 但无 RETURN 块：agent 未遵守返回协议 → 异常。
            return {"reason": "missing_return_block",
                    "detail": "agent 输出中未找到 `## RETURN:` 完成信号行"}
        if ret.get("status") == "FAILED":
            # 合法完成信号：STATUS=FAILED → 各 SKILL 语义为 "直接 escalate，不重试"。
            # 返回 hard_failed/input_gap 由 _agent_return_abnormal 路由到 escalate；
            # 不得判为 retry，否则硬失败会被错误地反复重试。
            err_type = ret.get("error_type")
            if err_type == "INP":
                # 输入/注入缺漏（框架侧问题，如 prompt 未注入 current_case /
                # vf_functions / golden 等）：重试同 agent 不会修复缺字段（注入来自
                # 框架读上游产物，与 agent 本轮行为无关）→ 同样 escalate，但留独立
                # reason 便于日志/诊断区分（§1.2 可诊断）。skill 文档须同步声明
                # INP→escalate 是刻意的。
                return {"reason": "input_gap",
                        "detail": "agent 自报 STATUS=FAILED, error_type=INP（输入/注入"
                                  "缺漏，框架侧问题）→ escalate（不重试）"}
            return {"reason": "hard_failed",
                    "detail": f"agent 自报 STATUS=FAILED"
                              + (f"，error_type={err_type!r}" if err_type else "")}
        if ret.get("status") != "COMPLETED":
            return {"reason": "non_completed",
                    "detail": f"agent 自报 status={ret.get('status')!r} != COMPLETED"
                              + (f"，error_type={ret.get('error_type')!r}" if ret.get("error_type") else "")}
        phase = ret.get("phase")
        if phase:
            # 归一化（vf-test 与 vf_test 视为一致）：去除非字母数字。
            norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())  # noqa: E731
            if norm(phase) != norm(self.name):
                return {"reason": "phase_mismatch",
                        "detail": f"agent 自报 phase={phase!r} != 本阶段 {self.name!r}"}
        reported = ret.get(key)
        json_status = (phase_result or {}).get(key)
        known = _KNOWN_STATUS_VALUES_BY_PHASE.get(self.name, set())
        # 状态值合法性（§1.3 加载期校验）：agent 上报值不在已知集合内 → 非法留痕。
        for val, src in ((reported, "RETURN"), (json_status, "result JSON")):
            if val is not None and known and str(val).lower() not in known:
                return {"reason": "invalid_status",
                        "detail": f"{src} 中 {key}={val!r} 不在已知集合 {sorted(known)}"}
        if reported is not None and json_status is not None and \
                str(reported).lower() != str(json_status).lower():
            return {"reason": "status_mismatch",
                    "detail": f"agent 自报 {key}={reported!r} != result JSON {key}={json_status!r}"}
        return {}

    def _agent_return_abnormal(self, state: "State", result, phase_result: dict) -> "State | None":
        """校验 agent 自报状态；异常/硬失败时注入路由标记并返回已同步的 state。

        - ``reason=hard_failed``（STATUS=FAILED，ENV/OTH 硬失败）→ 注入
          ``agent_hard_failed``，resolve_condition 路由 escalate（不重试）。
        - ``reason=input_gap``（STATUS=FAILED, error_type=INP——框架输入/注入缺漏，
          非 agent 可自修）→ 同样 escalate（重试不修复缺字段），但日志独立区分。
        - 其他异常（missing/phase_mismatch/invalid_status/status_mismatch/
          non_completed）→ 注入 ``agent_status_abnormal``，路由 retry 重试该 agent。

        Caller 在 transition 业务逻辑前调用；返回非 None 时直接 return 该 state。
        """
        bad = self._validate_agent_return(result, phase_result)
        if not bad:
            return None
        from ascendc_devkit.infra.logger import Logger
        if bad["reason"] in ("hard_failed", "input_gap"):
            label = ("STATUS=FAILED, error_type=INP（输入/注入缺漏）"
                     if bad["reason"] == "input_gap" else "STATUS=FAILED")
            Logger.warn(
                f"[A5-PD-AGENT-STATUS] {self.name}: agent 自报 {label}"
                f"（{bad.get('detail', '')}）→ escalate（不重试）"
            )
            flag = "agent_hard_failed"
        else:
            Logger.warn(
                f"[A5-PD-AGENT-STATUS] {self.name}: agent 自报状态异常"
                f"（{bad['reason']}）：{bad.get('detail', '')} → 重试该 agent"
            )
            flag = "agent_status_abnormal"
        cp = _load_a5_checkpoint(state)
        cp = self._restore_framework_routing_fields(state, cp, phase=self.name)
        cp[flag] = bad
        _save_a5_checkpoint(state, cp)
        dc = _extract_a5_debug_checkpoint(cp)
        dc[flag] = bad
        return self._sync_result(state, dc)

    def _append_history(self, state: "State", content: dict) -> dict:
        from datetime import datetime, timezone
        cp = _load_a5_checkpoint(state)
        entry = {
            "phase": self.name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "round": _current_round(state),
            "content": content,
        }
        cp.setdefault("history", []).append(entry)
        _save_a5_checkpoint(state, cp)
        return cp

    def _read_agent_summary(self, state: "State") -> dict:
        p = _phase_path(state, self._phase_filename(), round_suffix=True)
        if p is None or not p.exists():
            return {}
        try:
            phase_data = json.loads(p.read_text(encoding="utf-8"))
            return phase_data.get("_summary", {}) or {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _validate_phase_json(self, state):
        from ascendc_devkit.adapters.schema.loader import SchemaLoader
        from ascendc_devkit.infra.logger import Logger
        if not self._schema_files:
            return
        p = _phase_path(state, self._phase_filename(), round_suffix=True)
        if p is None or not p.exists():
            return
        try:
            raw_text = p.read_text(encoding="utf-8")
        except OSError:
            return
        if self._schema_contract_cache is None:
            try:
                self._schema_contract_cache = SchemaLoader.load_contract_from_skill(
                    self._assigned_skill(), self._schema_files)
            except Exception as exc:
                Logger.warn(f"[A5-PD-CONTRACT] schema load failed for "
                            f"{self._assigned_skill()}/{self._schema_files}: {exc}")
                return
        _, errors = self._schema_contract_cache.parse(
            {self._phase_filename(): raw_text})
        if errors:
            raise A5PrecisionDebugContractError(
                f"[A5-PD-CONTRACT] {self._phase_filename()} failed schema validation: "
                + "; ".join(errors)
            )

    def _sync_phase_latest(self, state: "State") -> None:
        import shutil
        from ascendc_devkit.infra.logger import Logger
        round_path = _phase_path(state, self._phase_filename(), round_suffix=True)
        latest_path = _phase_path(state, self._phase_filename(), round_suffix=False)
        if round_path is None or latest_path is None:
            return
        # Prefer the framework round-suffixed relay; fall back to the newest
        # skill-convention round file (``{stem}_round_{round}_result.json``).
        src = round_path if round_path.exists() else None
        if src is None:
            round_files = _skill_round_result_files(state, self._phase_filename())
            if round_files:
                src = round_files[-1]
        if src is None:
            Logger.warn(f"[A5-PD-RELAY] {round_path} missing — not synced")
            return
        # 防覆盖：latest 已不旧于候选 src → 保留 latest，跳过 relay。agent 本轮写
        # 的 fresh latest 是权威结果，不能被陈旧 round 文件覆盖——2026-08-24 轨迹：
        # baseline 重入验收全 pass 写 fresh baseline_result.json，transition 的
        # relay 兜底用旧 baseline_round_1_result.json（首轮 failed）覆盖它 →
        # _load_result 读到 failed → 假 status_mismatch → baseline↔baseline 重试
        # 循环，白跑一整轮双工具。round 约定阶段（agent 只写 round 文件）latest
        # 仍比 src 旧，正常 relay 不受影响。
        if latest_path.exists():
            try:
                latest_mtime = latest_path.stat().st_mtime
                src_mtime = src.stat().st_mtime
            except OSError:
                latest_mtime = src_mtime = None
            if latest_mtime is not None and src_mtime is not None and latest_mtime >= src_mtime:
                Logger.info(
                    f"[A5-PD-RELAY] {latest_path} not older than {src} — keep latest"
                    f" (agent's fresh result authoritative), skip relay"
                )
                return
        try:
            shutil.copy2(src, latest_path)
        except OSError as exc:
            Logger.warn(f"[A5-PD-RELAY] copy failed: {exc}")

    def _agent_produced_output(self, state: "State") -> bool:
        """True if this spawn left a non-empty phase artifact for the CURRENT round.

        Round-convention stages (kernel_debug / vf_test / vector_error_debug)
        must prove THIS round's spawn produced output. The only
        valid evidence is the current round's own artifacts: the round-suffixed
        relay path (``*_rNNN_pNNN.json``) or the skill-convention round file
        (``{stem}_round_{round}_result.json``). The round-agnostic ``latest``
        path and any historical round file are NOT evidence — ``_sync_phase_latest``
        copies a *previous* round's result there, so a killed spawn (no output
        this round) would be misread as "produced" → the abort anneal never fires
        → the transition raises a contract error → graph_executor stagnation
        falls through to a linear sibling (e.g. vf_test) with no evidence.

        baseline writes the plain ``latest`` path only (``_round_file_convention``
        False), so it checks that path directly.
        """
        for filename in (self._schema_files or []):
            if self._round_file_convention:
                relay = _phase_path(state, filename, round_suffix=True)
                if relay is not None and relay.exists():
                    try:
                        data = json.loads(relay.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        data = None
                    if data:
                        return True
                exact = _expected_round_result_path(state, filename)
                if exact is not None and exact.exists():
                    try:
                        data = json.loads(exact.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        data = None
                    if data:
                        return True
            else:
                latest = _phase_path(state, filename, round_suffix=False)
                if latest is not None and latest.exists():
                    try:
                        data = json.loads(latest.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        data = None
                    if data:
                        return True
        return False

    def _read_phase_result(self, state: "State", filename: str) -> dict:
        """Read this phase's result JSON — round decided by the framework.

        Precedence:
        1. the deterministic round file for the CURRENT round
           (``{phase_dir}/{stem}_round_{round}_result.json``, ``round`` read from
           the checkpoint counter ``{stem}_round``), the exact path the prompt
           told this spawn's agent to write;
        2. the framework ``latest`` path (``{phase_dir}/{filename}``), used by
           baseline and any relay writes.
        Returns ``{}`` when neither exists (caller applies its default).

        No directory scan: a leftover round file from a previous run/session can
        never be read for a different round, because the path is derived solely
        from the checkpoint counter.
        """
        import json
        if self._round_file_convention:
            exact = _expected_round_result_path(state, filename)
            if exact is not None and exact.exists():
                try:
                    return json.loads(exact.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    pass
        p = _phase_path(state, filename, round_suffix=False)
        if p is not None and p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        return {}

    def _handle_abort(self, state: "State", bump_counters: bool = False) -> "State":
        cp = _load_a5_checkpoint(state)
        cp["consecutive_aborts"] = int(cp.get("consecutive_aborts", 0)) + 1
        if bump_counters:
            cp["corrective_cycles"] = int(cp.get("corrective_cycles", 0)) + 1
            cp["run_iter_counter"] = int(cp.get("run_iter_counter", 0)) + 1
        # Per-case abort stop-loss: once the anneal budget is exhausted on a
        # per-case stage, skip the current case and advance to the next failed
        # case (same semantic as the agent-reported ``exhausted`` path). This
        # prevents an aborted spawn from looping ``agent_aborted`` on the same
        # case until graph_executor's stagnation guard falls through to a linear
        # sibling (e.g. vf_test) with no evidence (§1.2 架构合理 — fix at the
        # stage layer, not by special-casing the generic executor).
        skipped = False
        more_cases = False
        if self._abort_advances_case and \
           int(cp.get("consecutive_aborts", 0)) >= _abort_exhaust_threshold():
            queue = cp.get("failed_case_queue", []) or []
            case_idx = int(cp.get("current_case_index", 0) or 0)
            if 0 <= case_idx < len(queue):
                queue[case_idx]["status"] = "skipped"
                from ascendc_devkit.orchestration.stages.precision_debug_a5.case_loop import (
                    _advance_past_resolved,
                    _has_pending_debuggable,
                )
                _advance_past_resolved(
                    cp, skip_op_plugin=self._skip_op_plugin_in_advance)
                skipped = True
                more_cases = _has_pending_debuggable(
                    cp, skip_op_plugin=self._skip_op_plugin_in_advance)
        _save_a5_checkpoint(state, cp)
        cp = self._append_history(state, {"aborted": True, "case_skipped": skipped})
        dc = _extract_a5_debug_checkpoint(cp)
        dc["agent_aborted"] = True
        dc["_case_skipped"] = skipped
        dc["_more_cases"] = more_cases
        dc["rounds"] = (state._debug_checkpoint or {}).get("rounds", 0)
        self._sync_phase_latest(state)
        state = state.with_updates(_debug_checkpoint=dc)
        return _sync_debug_result(state, dc)

    def _reset_consecutive_aborts(self, state: "State") -> int:
        """Clear the consecutive-abort streak (a normal spawn broke it)."""
        cp = _load_a5_checkpoint(state)
        if int(cp.get("consecutive_aborts", 0)) != 0:
            cp["consecutive_aborts"] = 0
            _save_a5_checkpoint(state, cp)
        return 0

    def _abort_guard(self, state: "State") -> "State | None":
        """Anneal an aborted spawn before business routing.

        Returns the aborted state (whose ``_debug_checkpoint`` carries
        ``agent_aborted`` / ``consecutive_aborts`` so ``resolve_condition`` routes
        via ``_resolve_abort_condition`` → the transition table's
        ``agent_aborted`` / ``abort_exhausted`` entries) when this spawn produced
        no phase output; otherwise clears the abort streak and returns None so the
        stage's normal transition body runs. Call first thing in ``transition()``.
        """
        if not self._agent_produced_output(state):
            return self._handle_abort(state, bump_counters=False)
        self._reset_consecutive_aborts(state)
        return None

    def _resolve_abort_condition(self, dc: dict) -> str | None:
        # A per-case abort that already advanced the queue (skip + move to next
        # case, set in ``_handle_abort``) routes via the per-case stop-loss
        # conditions — the transition table forwards ``case_exhausted`` back to
        # the debug loop for the NEXT failed case and ``all_exhausted`` to
        # baseline. Check BEFORE the generic abort-exhaust escalation so a
        # per-case stage never spins into stagnation / a linear sibling.
        if dc.get("_case_skipped"):
            return "case_exhausted" if dc.get("_more_cases") else "all_exhausted"
        if int(dc.get("consecutive_aborts", 0)) >= _abort_exhaust_threshold():
            return "abort_exhausted"
        if dc.get("agent_aborted"):
            return "agent_aborted"
        return None

    def input_contract(self) -> StageIOContract:
        return StageIOContract(
            requires=["op_identity", "requirement", "golden_path",
                      "deploy_result", "codegen_manifest", "design_target_chip"],
            optional=["repo_root", "npu_id", "golden_entry", "golden_input_type",
                      "test_cases", "cases_path", "profile", "enable_stubbed"]
        )

    def output_contract(self) -> StageIOContract:
        return StageIOContract(provides=["_debug_checkpoint"])

    def _restore_framework_routing_fields(
        self, state: "State", cp: dict, *, phase: str,
    ) -> dict:
        """Restore routing fields from pre-spawn checkpoint to guard against agent corruption."""
        from ascendc_devkit.orchestration.stages.precision_debug_a5.checkpoint import (
            _restore_framework_checkpoint_guard,
        )
        return _restore_framework_checkpoint_guard(state=state, cp=cp, phase=phase)

    def _record_conclusion(self, state: "State", phase_result: dict, round_num: int) -> None:
        """Materialize this phase round's one-paragraph conclusion into the shared
        ``conclusions.json`` relay (other phases read it at spawn time).

        Sole framework-owned write authority; the agent only wrote ``conclusion``
        inside its own phase result JSON (``_materialize_conclusion`` reads it).
        Called once per transition after the agent-return check.
        """
        from ascendc_devkit.orchestration.stages.precision_debug_a5.conclusions import (
            _materialize_conclusion,
        )
        _materialize_conclusion(state, self.name, round_num, phase_result)


def _operator_dir(state: "State"):
    if state.op_dir:
        return state.op_dir
    if state.op_identity is not None:
        return state.op_identity.op_dir
    return None


def _abort_exhaust_threshold() -> int:
    from ascendc_devkit.orchestration.runtime_config import (
        precision_debug_a5_abort_exhaust_threshold,
    )
    return precision_debug_a5_abort_exhaust_threshold()


def _op_name(state: "State") -> str:
    return (state.op_name
            or (state.op_identity.spec.name if state.op_identity else "op"))


def _debug_artifacts_dir(state: "State") -> Path | None:
    ws = getattr(state, "_workspace", None)
    if ws is not None:
        return ws.artifacts / "precision_debug_a5"
    op_dir = _operator_dir(state)
    if op_dir is not None:
        return Path(op_dir) / ".precision-fix"
    return None


def _control_path(state: "State") -> Path | None:
    d = _debug_artifacts_dir(state)
    return None if d is None else d / "checkpoint.json"


_PHASE_STEM_MAP: dict[str, str] = {
    "baseline_result.json": "baseline",
    "kernel_debug_result.json": "kernel-debug",
    "vf_result.json": "vf-test",
    "vector_error_result.json": "vector-error",
    "op_plugin_result.json": "op-plugin-debug",
}


def _phase_path(state: "State", filename: str, round_suffix: bool = False) -> Path | None:
    d = _debug_artifacts_dir(state)
    if d is None:
        return None
    phase_stem = _PHASE_STEM_MAP.get(filename, filename)
    phase_dir = d / phase_stem
    if not round_suffix:
        return phase_dir / filename
    r = _current_round(state)
    cp = _load_a5_checkpoint(state) or {}
    idx = int(cp.get("phase_counter", 0))
    stem, ext = filename.rsplit(".", 1) if "." in filename else (filename, "json")
    return phase_dir / f"{stem}_r{r:03d}_p{idx:03d}.{ext}"


def _round_result_stem(filename: str) -> str:
    """The skill-convention round-file stem for a schema filename.

    ``kernel_debug_result.json`` → ``kernel_debug``; the skills write
    ``{stem}_round_{round}_result.json`` (e.g. ``kernel_debug_round_1_result.json``).
    """
    if filename.endswith("_result.json"):
        return filename[: -len("_result.json")]
    return filename.rsplit(".", 1)[0]


def _expected_round_result_path(state: "State", filename: str) -> Path | None:
    """The deterministic skill-convention round file for the CURRENT round.

    The round is owned by the framework: it is ``cp[{stem}_round] + 1`` — the
    same counter the transition increments after consuming the file. Both the
    prompt's write target (``_common_context``) and the transition's read target
    (``_read_phase_result`` / ``_load_expected_result``) derive from this single
    source, so a leftover file at a higher round number is never read.
    """
    d = _debug_artifacts_dir(state)
    if d is None:
        return None
    stem = _round_result_stem(filename)
    round_key = f"{stem}_round"
    cp = _load_a5_checkpoint(state) or {}
    round_num = int(cp.get(round_key, 0) or 0) + 1
    phase_dir = d / _PHASE_STEM_MAP.get(filename, filename)
    return phase_dir / f"{stem}_round_{round_num}_result.json"


def _skill_round_result_files(state: "State", filename: str) -> list[Path]:
    """Skill-convention round result files in this phase's dir, by ascending round.

    A5 skills instruct the agent to write ``{phase_dir}/{stem}*_round_<n>_result.json``
    (e.g. kernel_debug → ``kernel_debug_round_3_result.json``, op_plugin →
    ``op_plugin_debug_round_2_result.json``). Returns files sorted ascending by the
    numeric round so ``[-1]`` is the newest. Empty when none exist.
    """
    import re
    d = _debug_artifacts_dir(state)
    if d is None:
        return []
    stem = _round_result_stem(filename)
    phase_dir = d / _PHASE_STEM_MAP.get(filename, filename)
    if not phase_dir.is_dir():
        return []
    matched = []
    for p in phase_dir.glob(f"{stem}*_round_*_result.json"):
        m = re.search(r"_round_(\d+)_result\.json$", p.name)
        if m:
            matched.append((int(m.group(1)), p))
    matched.sort(key=lambda t: t[0])
    return [p for _, p in matched]


def _latest_kernel_debug_result(state: "State") -> tuple[Path | None, dict]:
    """The newest kernel_debug round result file (path, parsed dict).

    Primary source is the deterministic skill-convention round file
    (``kernel-debug/kernel_debug_round_{n}_result.json``, newest n); fallback is
    the latest relay path. Returns ``(None, {})`` when neither exists.
    """
    files = _skill_round_result_files(state, "kernel_debug_result.json")
    if not files:
        p = _phase_path(state, "kernel_debug_result.json", round_suffix=False)
        if p is not None and p.exists():
            files = [p]
    if not files:
        return None, {}
    p = files[-1]
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    return p, data


def _normalize_vf_functions(kd_result: dict | None, case: dict | None) -> list[dict]:
    """Normalize a kernel_debug result's ``vf_functions`` to the vf-debug skill
    contract: a list of dicts with ``name`` / ``function`` / ``evidence`` /
    ``dtype`` / ``input_shapes`` / ``failed_case_id``.

    kernel_debug may emit either structured dicts or free-form strings; both are
    accepted and best-effort enriched with the current case's dtype/shape and the
    result's ``dump_evidence`` so the vf_test agent always knows *which* VF failed
    and under *what* shape/dtype combination, without guessing.
    """
    raw = (kd_result or {}).get("vf_functions") or []
    dump_evidence = (kd_result or {}).get("dump_evidence", "")
    case = case or {}
    dtype = case.get("dtype", "")
    shape = case.get("shape", "")
    case_id = case.get("case_id", "")
    out = []
    for item in raw:
        if isinstance(item, dict):
            entry = dict(item)
        else:
            text = str(item)
            name = text.split("(")[0].strip() or text.split(":")[0].strip()
            entry = {"name": name, "function": text}
        entry.setdefault("name", "")
        entry.setdefault("function", entry["name"])
        entry.setdefault("evidence", dump_evidence)
        entry.setdefault("dtype", dtype)
        entry.setdefault("input_shapes", shape)
        entry.setdefault("failed_case_id", case_id)
        if entry["name"]:
            out.append(entry)
    return out


def _advance_phase_counter(state: "State") -> None:
    cp = _load_a5_checkpoint(state) or {}
    cp["phase_counter"] = int(cp.get("phase_counter", 0)) + 1
    _save_a5_checkpoint(state, cp)


def _current_round(state: "State") -> int:
    return (state._debug_checkpoint or {}).get("rounds", 0) or 1


# Late imports to avoid circular dependency at module load time.
def _load_a5_checkpoint(state: "State") -> dict:
    from ascendc_devkit.orchestration.stages.precision_debug_a5.checkpoint import (
        _load_a5_checkpoint as impl,
    )
    return impl(state)


def _save_a5_checkpoint(state: "State", cp: dict) -> None:
    from ascendc_devkit.orchestration.stages.precision_debug_a5.checkpoint import (
        _save_a5_checkpoint as impl,
    )
    return impl(state, cp)


def _extract_a5_debug_checkpoint(cp: dict) -> dict:
    from ascendc_devkit.orchestration.stages.precision_debug_a5.checkpoint import (
        _extract_a5_debug_checkpoint as impl,
    )
    return impl(cp)


def _sync_debug_result(state: "State", dc: dict) -> "State":
    from ascendc_devkit.orchestration.stages.precision_debug_a5.converge import (
        _sync_debug_result as impl,
    )
    return impl(state, dc)


# ———————————————————————————————————————————————————————————————————
# agent 自报 RETURN 状态解析（模块级，供 A5PrecisionDebugSubstage 使用）
# ———————————————————————————————————————————————————————————————————
# 与 codegen_s4.parse_return_signal 同源的解析思路：agent 最后一轮回复以
# ``## RETURN: status=COMPLETED, phase=xxx, {status_key}=value, ...`` 作为完成
# 信号。这里抽取公共正则，避免各阶段各自实现一套。

_STATUS_KEY_BY_PHASE: dict[str, str] = {
    "baseline": "baseline_status",
    "kernel_debug": "debug_status",
    "vf_test": "vf_status",
    "vector_error_debug": "vector_error_status",
    "op_plugin_debug": "debug_status",
}

# 各阶段业务状态值的已知集合（agent 可合法上报的 status_key 取值，小写）。
# 编排层在 _validate_agent_return 校验 agent 上报值是否在此集合内：不在 → 判
# invalid_status（重试该 agent 并留痕），避免非法值静默落入默认值兜底（§1.3 加载期
# 校验优先）。集合与各 SKILL 的返回协议（RESULT/## RETURN: 行）一一对齐：
# - baseline: baseline_status = passed | failed
# - kernel_debug: debug_status = fixed | need_vf | retry | exhausted
#   （fixed 之后的路由条件 kl_all_pass/case_kl_fails/vector_error 由框架从全量
#   KL 实测推导，agent 无需、也不得上报——regression 阶段已合入 kernel_debug）
# - vf_test: vf_status = passed | failed（exhausted 由框架超轮次注入，非 agent 上报）
# - vector_error_debug: vector_error_status = fixed | unresolved | not_reproduced
# - op_plugin_debug: debug_status = converged | retry | exhausted | need_kernel_debug
_KNOWN_STATUS_VALUES_BY_PHASE: dict[str, set[str]] = {
    "baseline": {"passed", "failed"},
    "kernel_debug": {"fixed", "need_vf", "retry", "exhausted"},
    "vf_test": {"passed", "failed"},
    "vector_error_debug": {"fixed", "unresolved", "not_reproduced"},
    "op_plugin_debug": {"converged", "retry", "exhausted", "need_kernel_debug"},
}

# 返回信号块起始标记。英文 `RETURN:` 保持原语义（任意位置匹配）；中文 `返回:`
# 只接受 markdown 标题形式（`## 返回:`），避免误匹配正文 prose 中的普通 "返回:"。
_RETURN_BLOCK_RE = re.compile(r"RETURN\s*:|(?:\#+\s*)返回\s*:", re.IGNORECASE)

# 各字段的合法取值（等号右侧值域）。值永远是 ASCII 枚举（COMPLETED/FAILED/fixed 等），
# 不做中文值兜底——中文值在 _validate_agent_return 的已知集合校验下本就该失败。
_RETURN_FIELD_VALUES: dict[str, str] = {
    "status": r"[A-Za-z_]+",
    "phase": r"[A-Za-z_-]+",
    "error_type": r"[A-Za-z0-9_-]+",
    "baseline_status": r"[A-Za-z_]+",
    "debug_status": r"[A-Za-z_]+",
    "vf_status": r"[A-Za-z_]+",
    "vector_error_status": r"[A-Za-z_]+",
}

# 字段名的中英文别名。英文为主（agent 硬契约，§2.12 结构化断言）；中文为编排层
# 宽容兜底——语言偏差不应静默导致完成信号错乱并重派本 agent（§1.2 兜底 + 可观测）。
# 英文名统一加词边界 \b：避免 `status=` 子串误配 `debug_status=`（历史实证：agent
# 写 `状态=COMPLETED` 时 ASCII status= 缺失，`debug_status=fixed` 里的 status=fixed
# 子串被误读为状态，整轮结果被废弃重派）。
_FIELD_NAME_ALIASES: dict[str, list[str]] = {
    "status": ["status", "状态"],
    "phase": ["phase", "阶段"],
    "error_type": ["error_type", "错误类型"],
    "baseline_status": ["baseline_status", "基线状态"],
    "debug_status": ["debug_status", "调试状态"],
    "vf_status": ["vf_status", "vf状态"],
    "vector_error_status": ["vector_error_status", "向量错误状态"],
}


def _build_return_field_res() -> dict[str, "re.Pattern[str]"]:
    out: dict[str, "re.Pattern[str]"] = {}
    for key, names in _FIELD_NAME_ALIASES.items():
        alts: list[str] = []
        for name in names:
            if name.isascii():
                alts.append(r"\b" + re.escape(name))
            else:
                alts.append(re.escape(name))
        out[key] = re.compile(
            r"(?:" + "|".join(alts) + r")\s*=\s*("
            + _RETURN_FIELD_VALUES[key] + r")",
            re.IGNORECASE,
        )
    return out


_RETURN_FIELD_RES: dict[str, "re.Pattern[str]"] = _build_return_field_res()


def _extract_return_fields(text: str) -> dict:
    """在 RETURN 块头部（前 600 字符）内逐个字段正则提取。"""
    out: dict[str, str] = {}
    for key, pattern in _RETURN_FIELD_RES.items():
        m = pattern.search(text)
        if m:
            out[key] = m.group(1).upper()
    return out


def parse_agent_return_block(final_response: str | None) -> dict:
    """从 agent 最后一轮回复解析 ``## RETURN:`` 完成信号块。

    返回 dict（可能为空）：``{"status", "phase", "error_type"}`` + 阶段状态字段
    （如 ``debug_status``），值统一大写。无 RETURN 块 / 解析不到 → {}。
    """
    if not final_response:
        return {}
    m = _RETURN_BLOCK_RE.search(final_response)
    if m:
        return _extract_return_fields(final_response[m.start():m.start() + 600])
    # 无 RETURN 块 → 返回 {}（调用方据此判 missing_return_block）。不做宽松兜底：
    # 宽松扫描会误匹配正文中的无关 ``status=`` / ``{status_key}=``，导致误判
    # （§1.3 加载期校验优先；A5 SKILL 已强制 RETURN 行，无需兼容旧格式）。
    return {}
