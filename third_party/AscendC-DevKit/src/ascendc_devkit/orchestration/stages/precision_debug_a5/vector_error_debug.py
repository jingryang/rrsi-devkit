"""vector_error_debug stage: crash location and repair."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
    A5PrecisionDebugSubstage,
)

if TYPE_CHECKING:
    from ascendc_devkit.orchestration.kernel.state import State


class VectorErrorDebugSubstage(A5PrecisionDebugSubstage):
    """A5 precision_debug vector_error_debug phase.

    Triggered when any phase returns error_type=VECTOR_ERROR. Uses P1/P2/P3 guard
    methodology to locate and fix the device vector error. After a fix, routes
    back to kernel_debug (new flow) rather than pipeline_sync (deleted).
    """

    name = "vector_error_debug"
    agent_name = "ascendc-precision-vector-error-debug"
    _schema_files = ["vector_error_result.json"]
    # Per-case：abort 预算耗尽后推进到下一个失败 case。见
    # A5PrecisionDebugSubstage._abort_advances_case。
    _abort_advances_case = True
    # kernel-first baseline 路由可能把 op_plugin case 留在同一队列——
    # vector_error_debug 只解 kernel 层崩溃，队列推进必须跳过 op_plugin case。
    _skip_op_plugin_in_advance = True

    def _phase_prompt(self, ctx, iteration) -> str:
        debug_dir = ctx.get("debug_dir") or "<debug_dir>"
        code_dir = ctx.get("code_dir") or "<code_dir>"
        round_path = ctx.get("phase_round_result_path") or "<phase_round_result_path>"
        return "\n".join([
            f"## Phase: vector_error_debug (A5 precision_debug, round {iteration})",
            "",
            f"你是 vector_error_debug phase agent。核心方法通过 skill `{self._assigned_skill()}` 加载。",
            "",
            f"- 日志/产物根目录: `{debug_dir}`",
            f"- 算子源码目录: `{code_dir}`",
            f"- 本阶段结果写入: `{round_path}`",
            "",
            "## 任务",
            "1. 稳定复现 VECTOR_ERROR。",
            f"2. 对 `{code_dir}` 下源码执行 A5 静态规则扫描（P1 guard）。",
            "3. 受控实验（P2 guard）。",
            "4. 区域二分 + 行级确认。",
            "5. 修复（P3 guard）。",
            "6. 单 case 复现确认。",
            "",
            "## 注意",
            "- 不使用 printf。",
            "- 修复后路由回 kernel_debug。",
            "",
            "## 返回协议",
            "输出 RESULT: VECTOR_ERROR_FIXED / VECTOR_ERROR_RETRY / VECTOR_ERROR_EXHAUSTED。",
        ])

    # ``vector_error_status`` values an agent may legitimately report. Only
    # ``fixed`` / ``not_reproduced`` (with ``verification.vector_error_cleared``)
    # mean "the crash is gone"; both route back to kernel_debug. ``unresolved``
    # (and anything else) is a genuine retry, bounded by ``max_vector_error_rounds``.
    _RESOLVED_STATUSES = frozenset({"fixed", "not_reproduced"})

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
        round_num = cp.get("vector_error_round", 0) + 1
        cp["vector_error_round"] = round_num
        phase_result = self._read_phase_result(state, "vector_error_result.json")
        # agent 自报状态校验：RETURN 缺失/非 COMPLETED/phase 不符/状态不一致 → 重试。
        abnormal = self._agent_return_abnormal(state, result, phase_result)
        if abnormal is not None:
            return abnormal
        self._record_conclusion(state, phase_result, round_num)
        cp["phase"] = self.name
        raw_status = phase_result.get("vector_error_status", "unresolved")
        cleared = bool(phase_result.get("verification", {}).get("vector_error_cleared"))
        # A crash is "resolved" iff the agent reported fixed/not_reproduced AND
        # verified it no longer reproduces. ``not_reproduced`` is the honest
        # signal agents emit when the original fingerprint is gone after a
        # rebuild — treat it identically to ``fixed`` so a resolved crash never
        # self-loops forever (the previous live incident that prompted this).
        resolved = raw_status in self._RESOLVED_STATUSES and cleared
        cp["history"] = cp.get("history", [])
        cp["history"].append({
            "phase": self.name,
            "round": round_num,
            "vector_error_status": raw_status,
        })
        if resolved:
            cp["error_type"] = ""
            cp["active_error_fingerprint"] = ""
            cp["vector_error_status"] = "fixed"
        else:
            cp["vector_error_status"] = "unresolved"
        # Per-case stop-loss: exhausted → skip and advance. This guarantees
        # termination regardless of what status the agent wrote.
        skipped = False
        more_cases = False
        max_rounds = cp.get("max_vector_error_rounds") or 10
        if round_num >= max_rounds and not resolved:
            phase_result["vector_error_status"] = "exhausted"
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
        if resolved and phase_result.get("code_modified"):
            _commit_candidate_phase(state, cp, self.name, round_num)
        _save_a5_checkpoint(state, cp)
        # 框架同步 latest 副本（agent 不复制）
        self._sync_phase_latest(state)
        dc = _extract_a5_debug_checkpoint(cp)
        dc["vector_error_status"] = cp["vector_error_status"]
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
        if dc.get("vector_error_status") == "fixed":
            return "fixed"
        if dc.get("_case_skipped"):
            return "case_exhausted" if dc.get("_more_cases") else "all_exhausted"
        # Genuine retry: crash still reproduces and budget not yet spent.
        return "retry"

    def _read_phase_result(self, state: "State", filename: str) -> dict:
        return super()._read_phase_result(state, filename)

    def _extract_loop_info(self, ctx: dict) -> dict:
        return {}

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
