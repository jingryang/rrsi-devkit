"""op_plugin_debug stage: adapter-layer repair loop."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
    A5PrecisionDebugSubstage,
)

if TYPE_CHECKING:
    from ascendc_devkit.orchestration.kernel.state import State


class OpPluginDebugSubstage(A5PrecisionDebugSubstage):
    """A5 precision_debug op_plugin_debug phase.

    Triggered when baseline finds cases that pass under KernelLaunch but
    fail under run-cases (error_layer=op_plugin). This is a global adapter-layer
    repair loop, not a per-case debug loop.
    """

    name = "op_plugin_debug"
    agent_name = "ascendc-precision-op-plugin-debug"
    _schema_files = ["op_plugin_result.json"]
    # op_plugin_debug 是全局适配层修复循环，不针对单个 case 解精度——prompt 不得注入
    # "当前待处理 case"（current_case_index / case_id / shape / dtype / error_layer /
    # failure_type / attempt_count / max_diff_rc / max_diff_kl）。该阶段以 run-cases +
    # KernelLaunch 双跑对比为准；且 max_diff_* 是动态回写值（kernel_debug 修复后全量
    # 重测、baseline 双跑更新），不是修复前的冻结值，注入只会误导 agent 去修单个 case。
    _inject_current_case = False

    def _phase_prompt(self, ctx, iteration) -> str:
        debug_dir = ctx.get("debug_dir") or "<debug_dir>"
        code_dir = ctx.get("code_dir") or "<code_dir>"
        round_path = ctx.get("phase_round_result_path") or "<phase_round_result_path>"
        op_name = ctx.get("op_name") or "<op_name>"
        return "\n".join([
            f"## Phase: op_plugin_debug (A5 precision_debug, round {iteration})",
            "",
            f"你是 op_plugin_debug phase agent。核心方法通过 skill `{self._assigned_skill()}` 加载。",
            "",
            f"- 日志/产物根目录: `{debug_dir}`",
            f"- 算子源码目录: `{code_dir}`",
            f"- op_plugin 层代码目录: `{code_dir}/op_plugin/`",
            f"- 本阶段结果写入: `{round_path}`",
            "",
            "## 任务",
            f"1. 读取双工具基线 diff（`{debug_dir}/baseline/baseline_result.json` 中 max_diff_rc vs max_diff_kl）+ run-cases 框架错误信息。",
            "2. 按错误码表解码 161xxx/561xxx 错误码。",
            "3. 按 op_plugin-checklist.md 逐项排查：注册宏、aclnn/C++ OpAPI 签名、dtype 转换、shape reshape、attr 传递、tiling 参数映射、op_info.json 字段。",
            f"4. 读取 `{code_dir}/op_plugin/` 下 op_plugin 层代码 + aclnn 接口定义。",
            f"5. 对比 `{debug_dir}/baseline/{op_name}_kernel_launch_test.py` 中传给 kernel 的参数 vs op_plugin/aclnn 传给 kernel 的参数差异。",
            "6. 修改 op_plugin 代码 → redeploy 重编出包。",
            "7. 双跑验证收敛（RC 不报框架错误 + RC/KL 结果一致 → `debug_status=converged`）。",
            "8. 若适配层逐项排查确认非适配层根因（或已修复），且残余失败 case 在 run-cases 与 KernelLaunch 下都失败 → 属 kernel/tiling 层问题，报 `debug_status=need_kernel_debug` 并把对应 case_id 填进 `kernel_cases` 清单，由框架移交 kernel_debug 做 per-case 调试。",
            "",
            "## 收敛判据",
            "- run-cases 不报框架层错误（无 crash/编译错误/注册失败）。",
            "- run-cases 结果与 KernelLaunch 结果基本一致。",
            "",
            "## 返回协议",
            "输出 RESULT: OP_PLUGIN_CONVERGED / OP_PLUGIN_NEED_KERNEL_DEBUG / OP_PLUGIN_RETRY / OP_PLUGIN_EXHAUSTED。",
        ])

    def transition(self, state: "State", result) -> "State":
        from ascendc_devkit.orchestration.stages.precision_debug_a5.checkpoint import (
            _load_a5_checkpoint, _save_a5_checkpoint, _extract_a5_debug_checkpoint,
        )
        from ascendc_devkit.orchestration.stages.precision_debug_a5.best_snapshot import (
            _commit_candidate_phase,
        )
        aborted = self._abort_guard(state)
        if aborted is not None:
            return aborted
        cp = _load_a5_checkpoint(state)
        cp = self._restore_framework_routing_fields(state, cp, phase=self.name)
        round_num = cp.get("op_plugin_round", 0) + 1
        cp["op_plugin_round"] = round_num
        phase_result = self._read_phase_result(state, "op_plugin_result.json")
        # agent 自报状态校验：RETURN 缺失/非 COMPLETED/phase 不符/状态不一致 → 重试。
        abnormal = self._agent_return_abnormal(state, result, phase_result)
        if abnormal is not None:
            return abnormal
        self._record_conclusion(state, phase_result, round_num)
        cp["phase"] = self.name
        cp["history"] = cp.get("history", [])
        status = phase_result.get("debug_status", "retry")
        cp["history"].append({
            "phase": self.name,
            "round": round_num,
            "debug_status": status,
        })
        # 仅 retry 受 max_op_plugin_rounds 钳制：converged / need_kernel_debug 是
        # 正向决策出口（适配层修好/移交 kernel），不得被轮次上限误改成 exhausted。
        if round_num >= (cp.get("max_op_plugin_rounds") or 10) and status == "retry":
            status = "exhausted"
            phase_result["debug_status"] = "exhausted"
        if status == "need_kernel_debug":
            self._apply_kernel_handoff(cp, phase_result)
            # 适配层确有修改 → 作为 candidate commit 落盘，避免移交后丢失；
            # kernel_debug 修完后的全量 KL / baseline 会基于它做高水位推进。
            if phase_result.get("code_modified"):
                _commit_candidate_phase(state, cp, self.name, round_num)
        elif status == "converged" and phase_result.get("code_modified"):
            _commit_candidate_phase(state, cp, self.name, round_num)
        _save_a5_checkpoint(state, cp)
        # 框架同步 latest 副本（agent 不复制）
        self._sync_phase_latest(state)
        dc = _extract_a5_debug_checkpoint(cp)
        dc["debug_status"] = status
        dc["op_plugin_round"] = round_num
        if status == "need_kernel_debug":
            dc["kernel_cases"] = phase_result.get("kernel_cases") or []
            # 移交后 queue 无任何 pending case（agent 声明移交但未指认任何 case）→
            # 退化走 converged 路由回 baseline 重新交叉对比，不硬闯空队列 kernel_debug。
            dc["_handoff_no_pending"] = not any(
                c.get("status") == "pending" for c in (cp.get("failed_case_queue") or []))
        return self._sync_result(state, dc)

    def _apply_kernel_handoff(self, cp: dict, phase_result: dict) -> None:
        """把适配层判定的 kernel/tiling 层 case 移交 kernel_debug。

        op_plugin agent 已确认适配层正确/修复完成，残余失败在 kernel 层：
        - 指认的 ``kernel_cases`` 改标 ``error_layer=kernel`` + ``status=pending``
          （kernel_debug 只消费 pending case）；
        - 未指认的纯适配层 case 标 ``resolved``（适配层工作已收口，后续 baseline
          重跑仍会复验，不会假通过）；
        - 无 ``kernel_cases`` 清单 → 适配层全局判定正确，全部残余失败视为 kernel 层。
        然后把 current_case_index 指向第一个 pending 的 kernel case。
        """
        queue = cp.get("failed_case_queue", []) or []
        kernel_cases = phase_result.get("kernel_cases") or []
        if kernel_cases:
            kernel_set = set(kernel_cases)
            for case in queue:
                if case.get("case_id") in kernel_set:
                    case["error_layer"] = "kernel"
                    case["status"] = "pending"
                    case["attempt_count"] = 0
                elif case.get("error_layer") == "kernel":
                    case["status"] = "pending"
                else:
                    case["status"] = "resolved"
        else:
            for case in queue:
                case["error_layer"] = "kernel"
                case["status"] = "pending"
                case["attempt_count"] = 0
        cp["failed_case_queue"] = queue
        next_idx = 0
        while next_idx < len(queue) and queue[next_idx].get("status") != "pending":
            next_idx += 1
        cp["current_case_index"] = next_idx

    def resolve_condition(self, state: "State") -> str:
        dc = state._debug_checkpoint or {}
        if (c := self._resolve_abort_condition(dc)) is not None:
            return c
        if dc.get("agent_status_abnormal"):
            return "retry"
        if dc.get("agent_hard_failed"):
            # STATUS=FAILED（ENV/OTH 硬失败）→ escalate，不重试
            return "hard_failed"
        status = dc.get("debug_status", "retry")
        if status == "converged":
            return "converged"
        if status == "need_kernel_debug":
            # 移交后无 pending case → 退化回 baseline 重新交叉对比，不硬闯空队列。
            if dc.get("_handoff_no_pending"):
                return "converged"
            return "need_kernel_debug"
        if status == "exhausted":
            return "exhausted"
        return "retry"

    def _read_phase_result(self, state: "State", filename: str) -> dict:
        return super()._read_phase_result(state, filename)

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
