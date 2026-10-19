"""kernel_debug stage: per-case kernel/tiling layer debugging."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
    A5PrecisionDebugSubstage,
    A5PrecisionDebugContractError,
)

if TYPE_CHECKING:
    from ascendc_devkit.orchestration.kernel.state import State


class KernelDebugSubstage(A5PrecisionDebugSubstage):
    """A5 precision_debug kernel_debug phase.

    Reads the current case's KernelLaunch baseline result, runs sync-static-check
    and tiling_bounds_check, then inserts DumpTensor probes to bisect the first
    numerical divergence, fixes the kernel, and re-verifies the intermediate state.
    """

    name = "kernel_debug"
    agent_name = "ascendc-precision-kernel-debug"
    _schema_files = ["kernel_debug_result.json"]
    # 调度前调和：跳过已被最新 KL 全量确认通过的 case（精度正确不再调试）。
    _reconcile_queue_at_spawn = True
    # Per-case：abort 预算耗尽后推进到下一个失败 case（而非自旋进 stagnation →
    # 线性后继）。见 A5PrecisionDebugSubstage._abort_advances_case。
    _abort_advances_case = True
    # kernel-first baseline 路由可能把 op_plugin case 留在同一队列——kernel_debug
    # 只解 kernel/tiling 层，队列推进必须跳过 op_plugin case（其 kernel 在
    # KernelLaunch 下已被证明正确，属 op_plugin_debug 的工作）。
    _skip_op_plugin_in_advance = True

    def _phase_prompt(self, ctx, iteration) -> str:
        debug_dir = ctx.get("debug_dir") or "<debug_dir>"
        code_dir = ctx.get("code_dir") or "<code_dir>"
        dev_record_dir = ctx.get("dev_record_dir") or "<dev_record_dir>"
        round_path = ctx.get("phase_round_result_path") or "<phase_round_result_path>"
        op_name = ctx.get("op_name") or "<op_name>"
        return "\n".join([
            f"## Phase: kernel_debug (A5 precision_debug, round {iteration})",
            "",
            f"你是 kernel_debug phase agent。核心方法通过 skill `{self._assigned_skill()}` 加载。",
            "",
            f"- 日志/产物根目录: `{debug_dir}`",
            f"- 算子源码目录: `{code_dir}`",
            f"- 开发记录目录: `{dev_record_dir}`",
            f"- 本阶段结果写入: `{round_path}`",
            "",
            "## 任务",
            f"1. 读取当前 case 的 baseline KernelLaunch 结果（`{debug_dir}/baseline/baseline_result.json`）+ run-cases 结果，分析失败模式。",
            f"2. 调用 `ascendc-sync-static-check` 扫描 `{code_dir}` 下 kernel 代码的同步缺陷。",
            f"3. 调用 `{debug_dir}/scripts/tiling_bounds_check.py` 检查当前 case 的 tiling 边界/对齐/尾块。",
            f"4. 在 `{code_dir}` 下 kernel 中插 DumpTensor（desc 100-199 CopyIn / 200-299 非 VF 计算 / 300-399 CopyOut）。",
            f"5. 在 `{debug_dir}/baseline/` 用 KernelLaunch 脚本重跑当前 case，捕获 DumpTensor 输出。",
            "6. 二分定位错误阶段。",
            f"7. 定位根因 → 修改 `{code_dir}` 下 kernel 源码 → KernelLaunch 回验当前 case → `debug_status=fixed`。",
            "8. 若 VF 输入正确但输出错误 → `debug_status=need_vf`。",
            "9. 若 VECTOR_ERROR → 设置 `error_type=VECTOR_ERROR` 并返回。",
            "",
            "## 修复后全量 KernelLaunch 验证（debug_status=fixed 时必做）",
            f"10. 重新执行 build 命令编译安装后，在 `{debug_dir}/baseline/` 批跑全量 KernelLaunch：",
            f"    `python3 {op_name}_kernel_launch_test.py`（复用 baseline 生成的脚本，跑全部 case，不跑 run-cases）。",
            "11. 该脚本会自动把 per_case 全量结果写入 `{debug_dir}/baseline/result_{op_name}_summary.json`；",
            "    框架 transition 会读取该 JSON 调和 failed_case_queue（resolved / regressed / 追加 / index 推进）",
            "    并推导路由：KL 全过 → 回 baseline 权威双跑验收；有失败 → 修下一个失败 case；VECTOR_ERROR → vector_error_debug。",
            "12. 在 result JSON 的 `kl_result` 输出完整 KL 汇总（pass/total/max_diff/failed_cases），并写一段话",
            "    `conclusion` 说明修复与全量 KL 结果；`new_failed_cases` 仅佐证（框架以 KL 实测为准）。",
            "",
            "## VF 黑盒约束",
            "- 禁止在 `__simd_vf__` 函数体内插 DumpTensor/printf。",
            "- 禁止修改 `__simd_vf__` 代码。",
            "",
            "## 返回协议",
            "输出 RESULT: KERNEL_DEBUG_FIXED / KERNEL_DEBUG_NEED_VF / KERNEL_DEBUG_RETRY / KERNEL_DEBUG_VECTOR_ERROR / KERNEL_DEBUG_EXHAUSTED。",
        ])

    def transition(self, state: "State", result) -> "State":
        from ascendc_devkit.orchestration.stages.precision_debug_a5.checkpoint import (
            _load_a5_checkpoint, _save_a5_checkpoint, _extract_a5_debug_checkpoint,
        )
        from ascendc_devkit.orchestration.stages.precision_debug_a5.best_snapshot import (
            _commit_candidate_phase,
            _merge_best_snapshot,
            _commit_modified_numeric_phase,
        )
        from ascendc_devkit.orchestration.stages.precision_debug_a5.vector_evidence import (
            _record_phase_error,
        )
        aborted = self._abort_guard(state)
        if aborted is not None:
            return aborted
        cp, round_num, phase_result = self._load_expected_result(state)
        # agent 自报状态校验：RETURN 缺失/非 COMPLETED/phase 不符/状态不一致 → 重试。
        abnormal = self._agent_return_abnormal(state, result, phase_result)
        if abnormal is not None:
            return abnormal
        self._record_conclusion(state, phase_result, round_num)
        case_idx = cp.get("current_case_index", 0)
        queue = cp.get("failed_case_queue", []) or []
        if 0 <= case_idx < len(queue):
            queue[case_idx]["attempt_count"] = queue[case_idx].get("attempt_count", 0) + 1
            queue[case_idx]["status"] = "debugging"
        # 回写最新 KL 测量：kernel_debug 本轮重测当前 case 的 after_max_diff_kl 才是
        # "当前 kernel 代码的真实差异"，写回 queue 让注入的 current_case 块不再显示
        # baseline 冻结值（该值在修复后已成误导信号，见 regression 轨迹）。
        ver = phase_result.get("verification") or {}
        if ver.get("after_max_diff_kl") is not None and 0 <= case_idx < len(queue):
            queue[case_idx]["max_diff_kl"] = ver["after_max_diff_kl"]
        cp["phase"] = self.name
        cp["history"] = cp.get("history", [])
        cp["history"].append({
            "phase": self.name,
            "round": round_num,
            "debug_status": phase_result.get("debug_status", "retry"),
        })
        error_type = _record_phase_error(cp, phase_result, self.name)
        if error_type != "VECTOR_ERROR" and \
           phase_result.get("debug_status") == "fixed" and \
           phase_result.get("code_modified"):
            _commit_candidate_phase(state, cp, self.name, round_num)
        # Per-case stop-loss. Two triggers both skip the current case:
        #  (a) attempt_count reached max_attempts_per_case (framework budget);
        #  (b) the agent explicitly reported ``debug_status=exhausted``
        #      (skill-declared: "I can't fix this case, advance"). Without (b)
        #      the agent's "give up" signal was clamped to retry → infinite loop.
        skipped = False
        more_cases = False
        agent_exhausted = phase_result.get("debug_status") == "exhausted"
        if 0 <= case_idx < len(queue):
            max_attempts = cp.get("max_attempts_per_case") or 10
            if queue[case_idx].get("attempt_count", 0) >= max_attempts or agent_exhausted:
                queue[case_idx]["status"] = "skipped"
                from ascendc_devkit.orchestration.stages.precision_debug_a5.case_loop import (
                    _advance_past_resolved,
                    _has_pending_debuggable,
                )
                # Advance to next non-skipped/non-resolved/non-op_plugin case
                _advance_past_resolved(
                    cp, skip_op_plugin=self._skip_op_plugin_in_advance)
                skipped = True
                # Check if there are more pending kernel-layer cases
                more_cases = _has_pending_debuggable(
                    cp, skip_op_plugin=self._skip_op_plugin_in_advance)
        # —— 修复后全量 KernelLaunch 验证 + 队列调和（原 regression 阶段职责，已合入）——
        # debug_status=fixed 且未止损跳过时，agent 已批跑全量 KernelLaunch，KL 脚本把
        # 结果写入 ``{debug_dir}/baseline/result_{op_name}_summary.json``（per_case 全量）。
        # 框架读该 JSON（§1.13 权威，非 agent 转述）调和 failed_case_queue：刷新
        # max_diff_kl、把 KL 已通过的 kernel 层 case 标 resolved、KL 失败的 resolved
        # case 标回 debugging（regressed，error_layer 翻转 kernel）、不在队列的失败
        # case 追加 pending——全部由 KL 实测推导。同时推导路由条件：
        #   kl_all_pass（→ baseline 权威双跑验收）/
        #   case_kl_fails（→ kernel_debug 修下一个失败 case）/
        #   vector_error（KL 脚本崩溃，summary 不可信，交 vector_error_debug）。
        # 队列的 resolved / regressed / 追加 / advance 不再由独立 regression 阶段负责。
        kl_status = None
        if not skipped and phase_result.get("debug_status") == "fixed":
            kl_status = self._reconcile_queue_from_full_kl(state, cp, phase_result)
            # 全量 KL 高水位推进（原 regression 职责）：仅当 agent 提供全量 KL 汇总
            # （``kl_result``，非 per-case 的 ``precision_result``——单 case 验证不能
            # 代表全量高水位）时，才把当前 operator-tree commit（kernel_debug 的
            # candidate 修复）晋升为 best_commit / 刷新 best_snapshot。失败留痕，
            # 绝不把上一次 HEAD 隐式当 best anchor。
            if phase_result.get("kl_result"):
                improved = _merge_best_snapshot(cp, phase_result, self.name, round_num)
                if improved:
                    _commit_modified_numeric_phase(state, cp, self.name, round_num)
        _save_a5_checkpoint(state, cp)
        # 框架同步 latest 副本（agent 不复制）：round 结果 → {phase_dir}/{stem}_result.json
        self._sync_phase_latest(state)
        dc = _extract_a5_debug_checkpoint(cp)
        dc["debug_status"] = phase_result.get("debug_status", "retry")
        dc["_case_skipped"] = skipped
        dc["_more_cases"] = more_cases
        dc["_kl_status"] = kl_status
        return self._sync_result(state, dc)

    # ``debug_status`` values the kernel_debug skill declares as legal
    # (SKILL.md §RETURN): fixed / need_vf / retry / exhausted. Each maps to a
    # transition-table key; an unknown (misspelled) value is clamped to ``retry``
    # so it never escapes as a condition the transition table doesn't recognize
    # (which would silently fall through to "stage done" and exit the debug loop).
    # ``fixed`` 之后的路由条件（kl_all_pass / case_kl_fails / vector_error）由框架
    # 从全量 KL 实测推导（_reconcile_queue_from_full_kl），不再需要独立 regression 阶段。
    # 单一事实来源：base._KNOWN_STATUS_VALUES_BY_PHASE（§2.5 唯一通路，避免漂移）。
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _KNOWN_STATUS_VALUES_BY_PHASE,
    )
    _KNOWN_DEBUG_STATUSES = frozenset(_KNOWN_STATUS_VALUES_BY_PHASE.get("kernel_debug", set()))

    def _reconcile_queue_from_full_kl(
        self, state: "State", cp: dict, phase_result: dict,
    ) -> str:
        """Fixed 后的全量 KernelLaunch 验证：读 KL summary JSON 调和队列并推导路由。

        Returns the routing condition: ``kl_all_pass`` / ``case_kl_fails`` /
        ``vector_error``. VECTOR_ERROR 时 KL 脚本可能没跑完就崩（dump summary 之前），
        summary.json 可能是旧代码的过期产物——此时不用它调和队列（交给
        vector_error_debug 处理崩溃）。
        """
        from ascendc_devkit.infra.logger import Logger
        from ascendc_devkit.orchestration.stages.precision_debug_a5.case_loop import (
            _load_latest_kl_data,
            _per_case_kl_results,
            _case_diffs_from_kl_result,
            _refresh_queue_kl_diffs,
            _reconcile_queue_from_kl,
            _apply_kl_failures_to_queue,
            _all_kl_passed,
        )
        from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
            _op_name,
        )
        if cp.get("error_type") == "VECTOR_ERROR":
            return "vector_error"
        kl_data = _load_latest_kl_data(state)
        if not kl_data:
            Logger.warn(
                f"[A5-PD-KERNEL-DEBUG] debug_status=fixed 但未找到 KL summary"
                f"（result_{_op_name(state)}_summary.json / kl_result.json）——"
                f"无法从 KL 实测推导队列，路由回 kernel_debug 重跑全量")
            return "case_kl_fails"
        per_case = _per_case_kl_results(kl_data)
        _refresh_queue_kl_diffs(cp, _case_diffs_from_kl_result(kl_data))
        _reconcile_queue_from_kl(cp, per_case)
        # fail 侧只对带显式 passed 的 summary.json（per_case 键）作用；legacy
        # kl_result.json（all_results 缺 passed 证据）只做数值刷新，不判状态。
        if kl_data.get("per_case"):
            from ascendc_devkit.domain.cann_bench_cases_loader import (
                load_cann_bench_case_meta,
            )
            case_meta = (
                load_cann_bench_case_meta(state.cases_path)
                if state.cases_path else {}
            )
            regressed, added = _apply_kl_failures_to_queue(cp, kl_data, case_meta)
            if regressed or added:
                Logger.warn(
                    f"[A5-PD-KERNEL-DEBUG] 队列由 KL 实测推导：{added} 个 KL 失败"
                    f" case 追加 pending、{regressed} 个已 resolved case 标回 debugging"
                    f"（regressed）")
        # 交叉校验 agent 报告的 new_failed_cases（佐证）与 KL 真值：agent 报的 case
        # 若 KL 实测通过 → 误报，留痕；队列以 KL 实测为准，不因此入队。
        reported = [
            str(c.get("case_id")) if isinstance(c, dict) else str(c)
            for c in (phase_result.get("new_failed_cases") or [])
        ]
        if reported:
            false_pos = [cid for cid in reported
                         if cid in per_case and per_case[cid].get("passed")]
            if false_pos:
                Logger.warn(
                    f"[A5-PD-KERNEL-DEBUG] agent 报告的 new_failed_cases 含 KL 已通过"
                    f" case {false_pos}；以 KL 实测为准（未入队）")
        return "kl_all_pass" if _all_kl_passed(kl_data) else "case_kl_fails"

    def resolve_condition(self, state: "State") -> str:
        dc = state._debug_checkpoint or {}
        if (c := self._resolve_abort_condition(dc)) is not None:
            return c
        if dc.get("agent_status_abnormal"):
            return "retry"
        if dc.get("agent_hard_failed"):
            # STATUS=FAILED（ENV/OTH 硬失败）→ escalate，不重试
            return "hard_failed"
        if dc.get("error_type") == "VECTOR_ERROR":
            return "vector_error"
        if dc.get("_case_skipped"):
            if dc.get("_more_cases"):
                return "case_exhausted"
            return "all_exhausted"
        status = dc.get("debug_status", "retry")
        if status == "exhausted":
            # Agent declared "can't fix this case" but the framework budget
            # hadn't forced a skip yet (e.g. queue edge) — honour the contract:
            # advance rather than retry a case the agent already gave up on.
            # kernel-only 计数（与 transition 的 _more_cases 同源）：只数 kernel 层
            # pending case，op_plugin case 不算可解工作（否则仅剩 op_plugin 时误判
            # case_exhausted → 硬闯空队列 kernel_debug）。
            from ascendc_devkit.orchestration.stages.precision_debug_a5.case_loop import (
                _has_pending_debuggable,
            )
            more = _has_pending_debuggable(
                dc, skip_op_plugin=self._skip_op_plugin_in_advance)
            return "case_exhausted" if more else "all_exhausted"
        if status == "fixed":
            # 修复后全量 KL 路由（框架从 KL summary 推导，见 _reconcile_queue_from_full_kl）。
            # 缺省回 case_kl_fails：KL 实测未知时不直通 baseline（避免未经验收的修复
            # 被当 full-pass 处理），由 kernel_debug spawn 的 reconcile 按实测推进。
            return dc.get("_kl_status", "case_kl_fails")
        if status not in self._KNOWN_DEBUG_STATUSES:
            # Unknown / misspelled status → bounded retry (max_attempts_per_case
            # guarantees termination), never an escape hatch.
            return "retry"
        return status

    def _load_expected_result(self, state: "State"):
        from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
            _phase_path, _expected_round_result_path,
        )
        cp = self._load_checkpoint(state)
        cp = self._restore_framework_routing_fields(state, cp, phase=self.name)
        round_num = cp.get("kernel_debug_round", 0) + 1
        cp["kernel_debug_round"] = round_num
        filename = "kernel_debug_result.json"
        import json
        phase_result = None
        # Framework round-suffixed relay (``_rNNN_pNNN.json``) first, then the
        # deterministic skill-convention round file for the CURRENT round
        # (``kernel_debug_round_{round}_result.json``). Both paths are derived
        # solely from framework counters (phase_counter / kernel_debug_round), so
        # leftover files from a previous run can never be misread.
        p = _phase_path(state, filename, round_suffix=True)
        if p is not None and p.exists():
            try:
                phase_result = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                phase_result = None
        if phase_result is None:
            exact = _expected_round_result_path(state, filename)
            if exact is not None and exact.exists():
                try:
                    phase_result = json.loads(exact.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    phase_result = None
        if phase_result is None:
            raise A5PrecisionDebugContractError(
                f"[A5-PD-CONTRACT] {self.name} round {round_num} result is missing"
            )
        return cp, round_num, phase_result

    def _load_checkpoint(self, state: "State") -> dict:
        from ascendc_devkit.orchestration.stages.precision_debug_a5.checkpoint import (
            _load_a5_checkpoint,
        )
        return _load_a5_checkpoint(state)

    def _sync_result(self, state: "State", dc: dict) -> "State":
        from ascendc_devkit.orchestration.stages.precision_debug_a5.converge import (
            _sync_debug_result,
        )
        state = state.with_updates(_debug_checkpoint=dc)
        return _sync_debug_result(state, dc)

    def _assigned_skill(self) -> str | None:
        from ascendc_devkit.orchestration.skill_config import STAGE_SKILL_MAP
        return STAGE_SKILL_MAP.get(self.name)

    def _validate_phase_json(self, state):
        pass
