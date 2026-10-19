"""baseline stage: dual-tool (run-cases + KernelLaunch) baseline + case queue."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
    A5PrecisionDebugSubstage,
    case_source_composition,
)

if TYPE_CHECKING:
    from ascendc_devkit.orchestration.kernel.state import State


def _tool_full(result: dict) -> bool:
    """Whether a tool summary (``rc_result`` / ``kl_result``) reports full pass.

    Deterministic acceptance helper: ``total > 0`` and ``pass == total``.
    A missing / non-numeric summary is NOT full pass (fail-closed: an absent tool
    result must never become an implicit "all pass").
    """
    if not isinstance(result, dict):
        return False
    try:
        total = int(result.get("total") or 0)
        passed = int(result.get("pass") or 0)
    except (TypeError, ValueError):
        return False
    return total > 0 and passed == total


class BaselineSubstage(A5PrecisionDebugSubstage):
    """A5 precision_debug baseline phase.

    Runs both ``ascendc-devkit run-cases`` and ``KernelLaunch`` on all cases,
    cross-compares results to classify each failure as kernel/tiling vs
    op_plugin/aclnn, and builds ``failed_case_queue``.
    """

    name = "baseline"
    agent_name = "ascendc-precision-baseline"
    _schema_files = ["baseline_result.json"]
    # baseline 是全局双跑分类，不解决精度问题——prompt 不得注入"当前待处理 case"
    # （首轮队列未构建，重跑时注入会误导 agent 去修单个 case 而非跑全量）。
    _inject_current_case = False
    # baseline writes the plain latest path (``baseline_result.json``) — no
    # framework-decided round counter — so exact-round reads are skipped.
    _round_file_convention = False

    def _phase_prompt(self, ctx, iteration) -> str:
        debug_dir = ctx.get("debug_dir") or "<debug_dir>"
        code_dir = ctx.get("code_dir") or "<code_dir>"
        latest_path = ctx.get("phase_json_latest_path") or "<phase_json_latest_path>"
        op_name = ctx.get("op_name") or "<op_name>"
        comp = ctx.get("test_case_source_composition") or {}
        comp_line = (
            f"cannbench={comp.get('cannbench', 0)}, "
            f"devkit(st-design)={comp.get('devkit', 0)}, "
            f"unknown={comp.get('unknown', 0)}"
        )
        return "\n".join([
            f"## Phase: baseline (A5 precision_debug, round {iteration})",
            "",
            f"你是 baseline phase agent。核心方法通过 skill `{self._assigned_skill()}` 加载。",
            "",
            f"- 日志/产物根目录: `{debug_dir}`",
            f"- 算子源码目录: `{code_dir}`",
            f"- 本阶段结果写入: `{latest_path}`",
            f"- 用例来源组成（框架权威，勿自行推断）: {comp_line}",
            "",
            "## 任务",
            f"1. 在 `{debug_dir}/baseline/` 生成 KernelLaunch 全量测试脚本 `{op_name}_kernel_launch_test.py`（若不存在）。",
            "2. 执行 `ascendc-devkit run-cases` 全量。",
            f"3. 在 `{debug_dir}/baseline/` 执行 `python3 {op_name}_kernel_launch_test.py` 全量。",
            "4. rc 与 kl 双工具全过才输出 `baseline_status=passed`（流程结束）；任一工具失败 → failed。",
            "5. 否则逐 case 交叉对比：",
            "   - run-cases 失败 + KernelLaunch 通过 → `error_layer=op_plugin`",
            "   - run-cases 失败 + KernelLaunch 失败 → `error_layer=kernel`",
            "   - run-cases 通过 + KernelLaunch 失败 → `error_layer=kernel`（KL 直测 binary，rc 过也阻断）",
            "   - KernelLaunch crash → `failure_type=vector_error`",
            "6. 在 `baseline_result.json.cross_compare` 输出逐 case 分类；由 framework 构建 queue。",
            "7. 在 `rc_result/kl_result` 输出 pass/total/max_diff/failed_cases；由 framework 刷新 best_snapshot。",
            "8. 把用例来源拆分（st-design 生成用例 vs cann-bench 原有用例）单独统计："
            "rc 跑全量（cann-bench + st-design），kl 按约定只跑 cann-bench cases.csv。"
            "在 `rc_result.by_source` 写结构化副本（`{cannbench:{pass,total}, devkit:{pass,total}}`）。"
            "`## BASELINE_RESULT` 的 `rc_pass` 行取 cann-bench 子集（`by_source.cannbench`，"
            "与 kl_pass 同基、可直接交叉对比，**不是** rc 全量合并总计）；`st-design-case` 行"
            "= `by_source.devkit`（rc 用例中 `source=devkit` 者）。`rc_result.pass/total`（JSON）"
            "保持 run-cases 全量合并总计（cannbench + devkit）供框架双工具验收门。"
            "st-design 总数必须与上方注入的 `devkit(st-design)` 组成一致。",
            "",
            "## 返回协议",
            "输出 RESULT: BASELINE_PASSED / BASELINE_FAILED。",
        ])

    def transition(self, state: "State", result) -> "State":
        from ascendc_devkit.orchestration.stages.precision_debug_a5.checkpoint import (
            _load_a5_checkpoint, _save_a5_checkpoint, _extract_a5_debug_checkpoint,
        )
        from ascendc_devkit.orchestration.stages.precision_debug_a5.best_snapshot import (
            _merge_best_snapshot,
            _commit_modified_numeric_phase,
        )
        from ascendc_devkit.orchestration.stages.precision_debug_a5.vector_evidence import (
            _record_phase_error,
        )
        aborted = self._abort_guard(state)
        if aborted is not None:
            return aborted
        # Relay round-suffixed baseline_result_rRRR_pPPP.json → latest
        # baseline_result.json. The framework only calls _sync_phase_latest
        # on the abort path (_handle_abort), never on the success path, so
        # without this the latest copy never exists — transition's
        # _load_result reads {} (→ empty failed_case_queue → false "all_pass")
        # and downstream kernel_debug/op_plugin_debug agents (whose prompts
        # read {debug_dir}/baseline/baseline_result.json) also see nothing.
        # _sync_phase_latest 已做 mtime 防覆盖：agent 本轮写的 fresh latest 不被
        # 陈旧 round 文件覆盖（2026-08-24 轨迹：双工具全 pass 结果被首轮 failed
        # round 文件覆盖 → 假 status_mismatch → baseline↔baseline 重试循环）。
        self._sync_phase_latest(state)
        cp = _load_a5_checkpoint(state)
        cp = self._restore_framework_routing_fields(state, cp, phase=self.name)
        baseline = self._load_result(state, "baseline_result.json")
        # agent 自报状态校验：RETURN 缺失/非 COMPLETED/phase 不符/状态不一致 → 重试。
        abnormal = self._agent_return_abnormal(state, result, baseline)
        if abnormal is not None:
            return abnormal
        # baseline 用固定 round 0（无 round 计数器），与 best_snapshot 一致。
        self._record_conclusion(state, baseline, 0)
        # —— 双工具验收门槛（框架侧机械判定，不信任 agent 文本）——
        # baseline_status=passed 的合法前提是 rc 与 kl 双双全过（skill Step 5）。
        # 2026-09-02 cumsum_min 轨迹：rc 20/20 + kl 19/20 被 agent 判 passed 直通
        # 结束、KL-only 失败不处理。此处用 rc_result/kl_result 实测计数复核——
        # agent 自报 passed 但任一工具未全过 → 降级走 failed 分支（失败 case 进
        # failed_case_queue 继续分流，绝不假 passed 结束流程）。
        rc_result = baseline.get("rc_result") or {}
        kl_result = baseline.get("kl_result") or {}
        rc_full = _tool_full(rc_result)
        kl_full = _tool_full(kl_result)
        double_pass = bool(rc_full and kl_full)
        agent_passed = baseline.get("baseline_status") == "passed"
        if agent_passed != double_pass:
            from ascendc_devkit.infra.logger import Logger
            Logger.warn(
                f"[A5-PD-BASELINE] baseline_status 文本与双工具实测不一致：agent 自报"
                f" {baseline.get('baseline_status')!r}，rc {rc_result.get('pass', '?')}/"
                f"{rc_result.get('total', '?')}、kl {kl_result.get('pass', '?')}/"
                f"{kl_result.get('total', '?')} ——以双工具实测为准"
                f"（{'passed' if double_pass else 'failed'}）")
        cp["double_tool_passed"] = bool(double_pass)
        cp["rc_full_pass"] = bool(rc_full)
        cp["kl_full_pass"] = bool(kl_full)
        # —— 用例来源拆分复核（st-design vs cann-bench）——
        # 权威组成来自框架的 state.test_cases 来源标记；agent 上报的 st-design 子集
        # 总数必须与之一致。这是一条报告维度的可观测性校验（§1.3），**不**作为验收
        # 闸门、不改路由——不一致只留 WARN，不阻断流程。
        composition = case_source_composition(getattr(state, "test_cases", None))
        cp["case_source_composition"] = composition
        _by_source = rc_result.get("by_source") if isinstance(rc_result, dict) else None
        _devkit = (_by_source or {}).get("devkit") if isinstance(_by_source, dict) else None
        _reported = _devkit.get("total") if isinstance(_devkit, dict) else None
        if _reported is not None:
            try:
                _reported = int(_reported)
            except (TypeError, ValueError):
                _reported = None
        if _reported is not None and _reported != composition.get("devkit", 0):
            from ascendc_devkit.infra.logger import Logger
            Logger.warn(
                f"[A5-PD-BASELINE] st-design 用例总数与框架组成不一致：agent 上报"
                f" rc_result.by_source.devkit.total={_reported}，框架 state.test_cases"
                f" 的 devkit 来源计数={composition.get('devkit', 0)} ——以框架组成为准"
                f"（报告维度校验，不影响路由）")
        if double_pass:
            cp["status"] = "passed"
            # 全 pass 收尾：清空待处理队列并重置索引——「passed = 无失败 case」，
            # checkpoint 不得残留旧 failed_case_queue / current_case_index，否则读
            # checkpoint 的人/诊断会误以为还有失败 case（2026-08-11 模拟暴露）。
            # 历史/best_snapshot 是独立字段，不受影响；resolve_condition 只看 status。
            cp["failed_case_queue"] = []
            cp["current_case_index"] = 0
            cp["classification"] = {}
        else:
            cp["status"] = "in_progress"
            cp["phase"] = "baseline"
            # case 元数据（shape/dtype）权威源是 cases.csv（§1.13 golden 权威、
            # 构造性保证）：agent 的 cross_compare 契约只承载对比结果，不要求回显
            # case 元数据；框架直接读 cases.csv 富集，避免注入块展示 <无> 误导 agent。
            from ascendc_devkit.domain.cann_bench_cases_loader import (
                load_cann_bench_case_meta,
            )
            case_meta = (
                load_cann_bench_case_meta(state.cases_path)
                if state.cases_path else {}
            )
            queue = []
            for cc in baseline.get("cross_compare", []) or []:
                rc_pass = cc.get("rc_pass")
                kl_pass = cc.get("kl_pass")
                # 只剔「rc 失败 + kl 通过」且 agent 显式标 actionable=false 的
                # cann-bench relative-error 误报（within_abs_tolerance / pass_both，
                # KL 证明 kernel 正确）；kl 失败不允许以 actionable 剔除——KL 直测
                # binary，kl 失败即 kernel 层缺陷，必须进 kernel_debug。
                if rc_pass is False and kl_pass is True and cc.get("actionable") is False:
                    continue
                # 双工具门槛（skill Step 4/5）：rc 或 kl 任一失败即阻断入队。
                # rc pass + kl fail 属 kernel 层，不得因 rc 交付通路通过而跳过。
                if rc_pass is not False and kl_pass is not False:
                    continue
                # kl 失败（无论 rc）→ kernel 层；kl 通过、仅 rc 失败 → op_plugin
                # 适配层。kl_pass=false 一律 kernel（与 _apply_kl_failures_to_queue
                # 的 regress 语义一致：KL 绕过适配层直测 kernel）。
                if kl_pass is False:
                    layer = "kernel"
                else:
                    layer = (
                        cc.get("error_layer")
                        if cc.get("error_layer") in ("kernel", "op_plugin")
                        else "op_plugin"
                    )
                meta = case_meta.get(str(cc.get("case_id", "")), {})
                queue.append({
                    "case_id": cc.get("case_id", ""),
                    "shape": cc.get("shape") or meta.get("shape") or "",
                    "dtype": cc.get("dtype") or meta.get("dtype") or "",
                    "max_diff_rc": cc.get("max_diff_rc"),
                    "max_diff_kl": cc.get("max_diff_kl"),
                    "error_layer": layer,
                    "failure_type": cc.get("failure_type", "precision"),
                    "status": "pending",
                    "attempt_count": 0,
                })
            cp["failed_case_queue"] = queue
            cp["current_case_index"] = 0
            # 每次 baseline 都用最新 KL 全量结果调和队列：刷新 max_diff_kl，并把
            # KL 已通过的 kernel 层 case 直接标 resolved，避免本轮双跑已确证通过的
            # case 仍以 pending 进入 per-case 调试（2026-08-10 case_18 轨迹）。
            from ascendc_devkit.orchestration.stages.precision_debug_a5.case_loop import (
                _load_latest_kl_data,
                _per_case_kl_results,
                _reconcile_queue_from_kl,
            )
            kl_data = _load_latest_kl_data(state)
            if kl_data:
                _reconcile_queue_from_kl(cp, _per_case_kl_results(kl_data))
            cp["op_plugin_round"] = cp.get("op_plugin_round", 0)
            # 透传 agent 的 classification 顶层判据（has_op_plugin_failures /
            # has_kernel_failures），供 resolve_condition 在 queue 为空时区分
            # all_pass vs no_case_data；queue 非空时以 queue 为准（kernel 优先）。
            cp["classification"] = baseline.get("classification") or {}
        cp["history"] = cp.get("history", [])
        cp["history"].append({
            "phase": self.name,
            "baseline_status": "passed" if double_pass else "failed",
        })
        _record_phase_error(cp, baseline, self.name)
        has_best = _merge_best_snapshot(cp, baseline, self.name, 0)
        if has_best:
            committed = _commit_modified_numeric_phase(state, cp, self.name, 0)
            if not committed and double_pass:
                cp["status"] = "commit_failed"
        _save_a5_checkpoint(state, cp)
        dc = _extract_a5_debug_checkpoint(cp)
        dc["baseline_status"] = "passed" if double_pass else "failed"
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
            return "has_kernel_failures"
        if dc.get("status") == "commit_failed" or dc.get("commit_error"):
            return "commit_failed"
        # —— 双工具验收（框架机械判定，baseline.py transition 已复核 rc/kl 实测）——
        # passed 的唯一合法条件是 rc 与 kl 双双全过（skill Step 5）。不信任 agent 的
        # baseline_status 文本：agent 自报 passed 但双工具未全过时 transition 已降级
        # 走 failed 分支，这里 double_tool_passed=false，绝不会 all_pass 直通。
        if dc.get("double_tool_passed"):
            return "all_pass"
        # —— 未达双工具全过：按 failed_case_queue 路由（kernel 优先）——
        # 队列由框架从 cross_compare 构建（含 kl-only 失败 = kernel 层），agent 无法
        # 用 classification 抹掉已入队的 kl 失败；resolved（最新 KL 已确证通过）不计。
        # kernel 层失败优先（决策 Q6 修订：出现精度问题时优先调度
        # ascendc-precision-kernel-debug 解 kernel/tiling 层问题；op_plugin 适配层
        # 问题在 kernel 工作收敛后由 baseline 重跑重新分流处理）——混合队列路由
        # kernel_debug 时，per-case 阶段的队列推进会跳过 op_plugin case，不会把
        # 适配层 case 派给 kernel_debug。
        queue = [c for c in (dc.get("failed_case_queue", []) or [])
                 if c.get("status") != "resolved"]
        if any(c.get("error_layer") == "kernel" for c in queue):
            return "has_kernel_failures"
        if any(c.get("error_layer") == "op_plugin" for c in queue):
            return "has_op_plugin_failures"
        # queue 无残留失败 → 用 agent 顶层 classification 兜底（data-faithful，
        # 已剔除 cann-bench relative-error 误报）。
        cls = dc.get("classification") or {}
        if cls.get("has_kernel_failures"):
            return "has_kernel_failures"
        if cls.get("has_op_plugin_failures"):
            return "has_op_plugin_failures"
        # 全非缺陷（仅剩 rc 的 within_abs_tolerance / pass_both 误报被剔）→ 允许
        # all_pass：kl 是 kernel 直测真值必须全过；rc 未全过时必须有 agent 顶层
        # classification 担保 rc 失败已全部判为非缺陷（误报剔除）。两者任一缺失
        # （失败 case 未进 cross_compare / classification 缺省）→ 契约缺失，按
        # no_case_data escalate exhausted，绝不假 passed。
        if dc.get("kl_full_pass") and (dc.get("rc_full_pass") or bool(cls)):
            return "all_pass"
        return "no_case_data"

    def _load_result(self, state: "State", filename: str) -> dict:
        return self._read_phase_result(state, filename)

    def _sync_result(self, state: "State", dc: dict) -> "State":
        from ascendc_devkit.orchestration.stages.precision_debug_a5.converge import (
            _sync_debug_result,
        )
        state = state.with_updates(_debug_checkpoint=dc)
        return _sync_debug_result(state, dc)

    def _assigned_skill(self) -> str | None:
        return self._skill_from_config(self.name)

    def _skill_from_config(self, name: str) -> str | None:
        from ascendc_devkit.orchestration.skill_config import STAGE_SKILL_MAP
        return STAGE_SKILL_MAP.get(name)

    def _validate_phase_json(self, state):
        # A5 baseline uses a custom schema name; skip generic schema validation for now.
        pass
