"""vf_test stage: VF function isolation unit test."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
    A5PrecisionDebugSubstage,
)

if TYPE_CHECKING:
    from ascendc_devkit.orchestration.kernel.state import State


class VfTestSubstage(A5PrecisionDebugSubstage):
    """A5 precision_debug vf_test phase.

    Triggered when kernel_debug returns is_vf_issue=True. Isolates the offending
    ``__simd_vf__`` function and tests it via SingleOperatorLaunch.
    """

    name = "vf_test"
    agent_name = "ascendc-precision-vf-debug"
    _schema_files = ["vf_result.json"]
    # Per-case：abort 预算耗尽后推进到下一个失败 case。见
    # A5PrecisionDebugSubstage._abort_advances_case。
    _abort_advances_case = True
    # kernel-first baseline 路由可能把 op_plugin case 留在同一队列——vf_test 只解
    # 被指认的 kernel 层 VF，队列推进必须跳过 op_plugin case。
    _skip_op_plugin_in_advance = True

    def _common_context(self, state: "State") -> dict:
        """Enrich the shared context with the VF-under-test contract.

        The vf_test agent must know *which* VF to test and under *what*
        shape/dtype combination — this is the kernel_debug hand-off that used to
        be discoverable only by ad-hoc directory listing. The target VF is the
        actual implementation in the deployed code, so the source location is
        injected too (the skill copies the real ``__simd_vf__`` body verbatim).
        """
        from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
            _latest_kernel_debug_result,
            _normalize_vf_functions,
        )
        from ascendc_devkit.orchestration.stages.precision_debug_a5.checkpoint import (
            _load_a5_checkpoint,
        )
        ctx = super()._common_context(state)
        kd_path, kd_result = _latest_kernel_debug_result(state)
        cp = _load_a5_checkpoint(state)
        queue = cp.get("failed_case_queue", []) or []
        case = None
        idx = cp.get("current_case_index", 0)
        if 0 <= idx < len(queue):
            case = queue[idx]
        ctx["kernel_debug_result_path"] = str(kd_path) if kd_path else ""
        ctx["vf_functions"] = _normalize_vf_functions(kd_result, case)
        ctx["vf_evidence"] = (kd_result or {}).get("dump_evidence", "")
        if case:
            ctx["current_case"] = {
                "case_id": case.get("case_id", ""),
                "shape": case.get("shape", ""),
                "dtype": case.get("dtype", ""),
                "error_layer": case.get("error_layer", ""),
                "failure_type": case.get("failure_type", ""),
                "max_diff_kl": case.get("max_diff_kl"),
            }
        return ctx

    def _phase_prompt(self, ctx, iteration) -> str:
        debug_dir = ctx.get("debug_dir") or "<debug_dir>"
        code_dir = ctx.get("code_dir") or "<code_dir>"
        dev_record_dir = ctx.get("dev_record_dir") or "<dev_record_dir>"
        round_path = ctx.get("phase_round_result_path") or "<phase_round_result_path>"
        kd_path = ctx.get("kernel_debug_result_path") or ""
        vf_funcs = ctx.get("vf_functions") or []
        case = ctx.get("current_case") or {}
        lines = [
            f"## Phase: vf_test (A5 precision_debug, round {iteration})",
            "",
            f"你是 vf_test phase agent。核心方法通过 skill `{self._assigned_skill()}` 加载。",
            "",
            f"- 日志/产物根目录: `{debug_dir}`",
            f"- 算子源码目录: `{code_dir}`",
            f"- 开发记录目录: `{dev_record_dir}`",
            f"- 本阶段结果写入: `{round_path}`",
            f"- kernel_debug 结果文件: `{kd_path}`（被测 VF 的唯一事实来源）",
            "",
            "## 被测 VF（框架从 kernel_debug 结果注入，禁止自行猜测）",
        ]
        if vf_funcs:
            for vf in vf_funcs:
                lines += [
                    f"- `name`: {vf.get('name') or '<缺失>'}",
                    f"  - `function`: {vf.get('function') or '<缺失>'}",
                    f"  - `dtype`: {vf.get('dtype') or '<缺失>'}",
                    f"  - `input_shapes`: {vf.get('input_shapes') or '<缺失>'}",
                    f"  - `failed_case_id`: {vf.get('failed_case_id') or '<缺失>'}",
                    f"  - `evidence`: {vf.get('evidence') or '<缺失>'}",
                ]
        else:
            lines.append(
                f"- 框架未解析到 `vf_functions`。先读 `{kd_path}`（该路径为空则从 "
                f"`{debug_dir}/kernel-debug/` 找最新 `kernel_debug_round_*_result.json`），"
                f"以确定被测 VF 的 `name` / `dtype` / `input_shapes` / `failed_case_id`。"
                f"仍无法确定 → 按 skill FAIL-SAFE 返回 error_type=INP，禁止猜测。"
            )
        if case:
            lines += [
                "",
                "## 当前失败 case（checkpoint 上下文）",
                f"- `case_id`: {case.get('case_id')} | `shape`: {case.get('shape')} | "
                f"`dtype`: {case.get('dtype')} | `error_layer`: {case.get('error_layer')} | "
                f"`failure_type`: {case.get('failure_type')}",
            ]
        lines += [
            "",
            "## 任务",
            f"1. 按被测 VF 的 `name` 从 `{dev_record_dir}/coding_index.md` 读取 VF 函数规格。",
            "2. 预查询 VF 指令参考 + 类别经验库检索（按计算模式定位 vf_experiences 类别条目）。",
            "3. 参考 golden_module 构造 VF 级期望值。",
            f"4. 在 `{debug_dir}/vf-test/` 下用 SingleOperatorLaunch 隔离测试（测试用例必须覆盖上面的 `dtype` + `input_shapes`）。",
            "5. 合规性检查。",
            "6. vf_status=passed 时提炼归约类别级经验到 vf_experiences/{类别}/experience-*.md（不放完整源码答案，留实证来源）。",
            "",
            "## VF 测试源码纪律（硬规则，防假通过）",
            f"- 被测对象必须是 `{code_dir}` 实际 kernel 代码里的 `__simd_vf__` 函数："
            f"按 `name` 在 `{code_dir}/op_kernel/*.{{h,cpp}}`（或 `{code_dir}` 下其它 kernel 源文件）"
            f"中定位，把**实际函数体原样搬运**进测试 kernel（只允许外加 `__aicore__` wrapper 与测试数据搬入/搬出）。",
            "- 禁止把 `vf_verified/`（开发期已测脚本）或 `references/examples/` 模板里的 VF 实现当作被测对象——"
            "它们只能作 harness/wrapper 写法参考，不可作为被测 VF 函数体来源（否则测的是理想重建而非真实实现，缺陷会逃逸）。",
            f"- 生成 `{{vf_func_snake}}_custom.cpp` 后，对搬运的 VF 函数体与真实源码做 diff 核对，差异行写入 `compliance` 报告。",
            "",
            "## 返回协议",
            "输出 RESULT: VF_PASSED / VF_RETRY / VF_VECTOR_ERROR / VF_EXHAUSTED。",
        ]
        return "\n".join(lines)

    def transition(self, state: "State", result) -> "State":
        from ascendc_devkit.orchestration.stages.precision_debug_a5.checkpoint import (
            _load_a5_checkpoint, _save_a5_checkpoint, _extract_a5_debug_checkpoint,
        )
        from ascendc_devkit.orchestration.stages.precision_debug_a5.vector_evidence import (
            _record_phase_error,
        )
        aborted = self._abort_guard(state)
        if aborted is not None:
            return aborted
        cp = _load_a5_checkpoint(state)
        cp = self._restore_framework_routing_fields(state, cp, phase=self.name)
        round_num = cp.get("vf_round", 0) + 1
        cp["vf_round"] = round_num
        phase_result = self._read_phase_result(state, "vf_result.json")
        # agent 自报状态校验：RETURN 缺失/非 COMPLETED/phase 不符/状态不一致 → 重试。
        abnormal = self._agent_return_abnormal(state, result, phase_result)
        if abnormal is not None:
            return abnormal
        self._record_conclusion(state, phase_result, round_num)
        cp["phase"] = self.name
        cp["history"] = cp.get("history", [])
        cp["history"].append({
            "phase": self.name,
            "round": round_num,
            "vf_status": phase_result.get("vf_status", "failed"),
        })
        _record_phase_error(cp, phase_result, self.name)
        # Round budget check for the VF phase itself. Guarantees termination
        # regardless of agent-reported status (unknown values fall to retry,
        # bounded here by max_vf_rounds).
        skipped = False
        more_cases = False
        if round_num >= (cp.get("max_vf_rounds") or 10):
            if phase_result.get("vf_status") != "passed":
                phase_result["vf_status"] = "exhausted"
                from ascendc_devkit.orchestration.stages.precision_debug_a5.case_loop import (
                    _advance_past_resolved,
                    _has_pending_debuggable,
                )
                queue = cp.get("failed_case_queue", []) or []
                case_idx = cp.get("current_case_index", 0)
                if 0 <= case_idx < len(queue):
                    queue[case_idx]["status"] = "skipped"
                    _advance_past_resolved(
                        cp, skip_op_plugin=self._skip_op_plugin_in_advance)
                    skipped = True
                    more_cases = _has_pending_debuggable(
                        cp, skip_op_plugin=self._skip_op_plugin_in_advance)
        _save_a5_checkpoint(state, cp)
        # 框架同步 latest 副本（agent 不复制）
        self._sync_phase_latest(state)
        dc = _extract_a5_debug_checkpoint(cp)
        dc["vf_status"] = phase_result.get("vf_status", "failed")
        dc["_case_skipped"] = skipped
        dc["_more_cases"] = more_cases
        return self._sync_result(state, dc)

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
            return "case_exhausted" if dc.get("_more_cases") else "all_exhausted"
        vf_status = dc.get("vf_status", "failed")
        if vf_status == "passed":
            return "vf_passed"
        if vf_status == "exhausted":
            return "case_exhausted"
        # Unknown / non-passing status → bounded retry (max_vf_rounds guarantees
        # termination), never an escape hatch out of the table.
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
