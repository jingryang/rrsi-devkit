"""反馈渲染 mixin — CodegenStage 的反馈/retry 职责承载（m1 God module 治理后归属本模块）。

承载 build/artifact/schema/smoke 各 feedback 的收集与渲染、定向 retry（artifact/plugin_schema/smoke）、
``_render_retry_resume_prompt``（fresh 与 resume 共用）、is_satisfied / stop_in_stage_retry 出口。

依赖 ``self._persist_sources``（DeployMixin）与 ``self._classify_smoke_phase``（编排壳别名）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

from ascendc_devkit.domain.verification import BuildResult, DeployResult
from ascendc_devkit.orchestration.kernel.state import ErrorFeedback

if TYPE_CHECKING:
    from ascendc_devkit.orchestration.kernel.state import State

_SMOKE_ERROR_STOP_LOSS_STREAK = 3

# build 失败反馈注入的结构化错误行数上限（首错 + 前几条；§1.15 截断，防刷屏）。
_BUILD_FEEDBACK_ERROR_LIMIT = 5

# 2026-09-10（advisory 废弃收口）：build 侧机械 stop-loss 阈值（镜像 smoke）。
# 同签名连续重试 ≥K 仍无进展 → 强制 D4，不依赖 coder 声明"该换策略"。
_BUILD_ERROR_STOP_LOSS_STREAK = 3


class FeedbackMixin:
    """反馈/retry mixin（职责见模块 docstring，经 MRO 合并回 CodegenStage）。"""

    def _artifact_retry(self, state: State, agent_result, manifest,
                        decision_logs: dict, missing: list[str],
                        iterations: int) -> State:
        """Retry path for a non-conforming manifest (missing required fields).

        Mirrors build-retry: NO ``last_error`` (stays out of the halt/corrective
        channel), NO ``deploy_result`` (output_contract unsatisfied → runner
        auto re-spawns the coder with ``codegen_artifact_feedback``). On budget
        exhaustion → halt (no callable artifact to defer; §1.10 — distinct from
        build-retry's D4 which carries a compiled-but-smoke-failed result).
        """
        from ascendc_devkit.infra.logger import Logger

        self._persist_sources(state, agent_result.artifacts)
        retries = state.codegen_artifact_retries + 1
        limit = self._artifact_retry_limit()
        if retries >= limit:
            Logger.warn(
                f"codegen artifact-retry exhausted ({retries}/{limit}); halting "
                f"— manifest still missing {missing} after targeted retries.")
            # error_type 落 exhausted 终态类（taxonomy：exhausted→__halt__），
            # 不留在 incomplete_output（可重试类）：占位 deploy_result 会让
            # runner R1 归一化/F6"成功清错"把 halt 信号当过时错误抹掉——
            # 预算耗尽冒充成功交付（§1.10 一种错误不得冒充另一种）。
            # is_satisfied/stop_in_stage_retry 按 details.reason 同键窄识别。
            return state.with_updates(
                last_error=ErrorFeedback(
                    stage_name="codegen",
                    error_type="exhausted",
                    message=(
                        f"after {retries} retries codegen_manifest still "
                        f"non-conforming (missing required fields {missing}); "
                        f"cannot derive a callable target — manual triage"),
                    details={
                        "reason": "manifest_non_conforming_exhausted",
                        "missing_fields": list(missing),
                    },
                ),
                generated_sources=agent_result.artifacts,
                codegen_iterations=iterations,
                codegen_consecutive_failures=0,
                codegen_orphan_streak=0,
                decision_logs=decision_logs,
                codegen_manifest=manifest,
                build_result=BuildResult(passed=False),
                deploy_result=DeployResult(smoke_passed=False),
                codegen_artifact_retries=retries,
                codegen_artifact_feedback=None,
                # artifact-retry 是另一重试循环 → smoke streak 重置
                codegen_smoke_same_error_streak=0,
                codegen_smoke_last_error_sig="",
            )
        feedback = self._collect_artifact_feedback(state, missing)
        Logger.warn(
            f"codegen manifest non-conforming (missing {missing}, retry "
            f"{retries}/{limit}); NOT writing deploy_result — runner will "
            f"re-spawn coder with artifact_feedback.")
        return state.with_updates(
            last_error=None,
            generated_sources=agent_result.artifacts,
            codegen_iterations=iterations,
            codegen_consecutive_failures=0,
            codegen_orphan_streak=0,
            decision_logs=decision_logs,
            codegen_manifest=manifest,
            build_result=BuildResult(passed=False),
            # deploy_result 不设 → has_all=False → runner 自动重 spawn
            codegen_artifact_retries=retries,
            codegen_artifact_feedback=feedback,
            # artifact-retry 是另一重试循环 → smoke streak 重置
            codegen_smoke_same_error_streak=0,
            codegen_smoke_last_error_sig="",
        )
    def _artifact_retry_limit(self) -> int:
        """Framework-driven artifact-retry ceiling (mirror ``_build_retry_limit``).

        From ``codegen.artifact_max_retries`` (orchestration-config.json, loaded
        once at import via runtime_config.codegen_artifact_max_retries). On
        exhaustion → halt (no callable artifact to carry downstream, unlike
        build-retry's D4 — deferring to precision_debug scope_guard would only
        postpone an inevitable halt, §1.10). MUST be ≤ iterations.stages.codegen.
        """
        from ascendc_devkit.orchestration.runtime_config import (
            codegen_artifact_max_retries,
        )
        return codegen_artifact_max_retries()
    def _build_retry_limit(self) -> int:
        """Framework-driven build-retry ceiling (阶段3 方案 Z).

        From ``codegen.build_max_retries`` (orchestration-config.json, loaded
        once at import via runtime_config.codegen_build_max_retries). On
        exhaustion → D4 escape (carry smoke_passed=False downstream, no halt).
        MUST be ≤ ``iterations.stages.codegen`` (runner's mechanical ceiling) —
        see orchestration-config.json codegen._comment (both aligned to 1000).

        Caveat: D4 escape is only reached when the runner's iteration ceiling
        (``user_max_iterations`` if set, else config stage_budget — runner.py:254)
        is ≥ build_max_retries. If a user sets a smaller ``--max-iterations`` and
        build keeps failing, iteration truncates first → no deploy_result →
        partial-passed → halt (not D4). Production ``batch_self_evolve`` leaves
        it unset → config stage_budget (1000) wins.
        """
        from ascendc_devkit.orchestration.runtime_config import codegen_build_max_retries
        return codegen_build_max_retries()
    def _collect_artifact_feedback(self, state: State, missing: list[str]) -> dict:
        """Assemble the next-round coder's feedback for a non-conforming manifest.

        Targeted feedback (§2.9 ② — explicit consumption channel, not blind
        re-run): tells the coder exactly which contract fields are missing and
        where debug/report content belongs. No re-classification of build logs
        (this is a manifest defect, not a compile error).
        """
        profile_kind = self._profile_scaffolding_kind(state)
        plugin_missing = (
            "callable_target" in missing and profile_kind == "torch_op"
        )
        if plugin_missing:
            hint = (
                "torch_op profile requires op_plugin/*.cpp containing both "
                "TORCH_LIBRARY_FRAGMENT(namespace, m) and a parseable "
                "m.def(\"op(...)\"); callable_target.symbol is derived from that "
                "registration — write the plugin registration and the manifest "
                "callable_target will be auto-derived."
            )
        elif "callable_target" in missing:
            hint = (
                "fill callable_target{kind, symbol} per schema/codegen_manifest.json "
                "(kind from profile, symbol = torch.ops.<namespace>.<op>)."
            )
        else:
            hint = (
                "fill the missing contract fields (op_name; inputs/outputs/attrs are "
                "OPTIONAL — P1 收敛: only op_name + callable_target are required per "
                "schema/codegen_manifest.json, IO is not consumed downstream). "
                "Debug/report content (compile_status/runtime_status/"
                "suspected_root_causes/next_steps/files/...) belongs in "
                "decision_log.json, NOT codegen_manifest.json — the manifest is a "
                "signature contract only."
            )
        retries = state.codegen_artifact_retries + 1
        return {
            "reason": "manifest_non_conforming",
            "missing_fields": list(missing),
            "scaffolding_kind": profile_kind,
            "retry_count": retries,
            "hint": hint,
        }
    def _collect_build_feedback(self, state: State, err) -> dict:
        """Assemble the next-round coder's build-failure feedback (阶段3 方案 Z).

        ``Deployer._build_failure_footer`` already auto-classified the error
        (``classify_build_error`` → persisted to ``build_retry_state.json``) and
        appended the clang summary + signature hint footer to
        ``subprocess/build_*.log``. This helper reads those back and injects the
        STRUCTURED first-error (scan_kernel_compile_errors over the log) into
        the next coder prompt — so the actionable root error is IN the feedback
        text, not just in the log the agent must read (transpose 2026-09-10:
        silent-cut 轮不读日志 → 首错从未进反馈).
        """
        from ascendc_devkit.orchestration.stages.deploy import Deployer
        from ascendc_devkit.domain.build_log_scanner import (
            scan_kernel_compile_errors,
        )
        ws = getattr(state, "_workspace", None)
        retry_state = Deployer._read_retry_state(ws) if ws is not None else {}
        error_class = retry_state.get("last_class") or "unknown"
        details = getattr(err, "details", {}) or {}
        log_path = details.get("log", "")
        # 结构化首错提取（best-effort）：从完整日志读，命中即注入（首错 + 前 5 条）。
        # 失败（日志缺失/不可读/无 clang 行）→ 空列表，不阻断反馈主链（§1.2）。
        error_lines: list[str] = []
        if log_path:
            try:
                full = Path(log_path).read_text(encoding="utf-8", errors="replace")
                errs = scan_kernel_compile_errors(full)
                error_lines = [
                    f"{e.source}  {e.message}" if e.source else e.message
                    for e in errs[:_BUILD_FEEDBACK_ERROR_LIMIT]
                ]
            except OSError:
                error_lines = []
        return {
            "kind": "compile",  # 区分 schema_mismatch（方案 A/B）反馈
            "error_class": error_class,
            "log_path": log_path,
            "stderr_tail": details.get("stderr_tail", ""),
            "error_lines": error_lines,
            # 2026-09-10：advisory 废弃——gradient_hint/class_count/total_failures
            # 不再注入（机械 stop-loss 用 State 的 codegen_build_*_sig/streak，不走
            # 反馈文本；渲染段已同步删「重试策略」行）。
            "retry_count": state.codegen_build_retries + 1,
        }
    def _collect_schema_feedback(self, state: State, schema_mismatch: dict,
                                 retries: int) -> dict:
        """Assemble schema-mismatch feedback for the next coder round.

        ``kind='schema_mismatch'`` → prompt 渲染 schema 专属反馈段（区别于
        ``_collect_build_feedback`` 的 ``kind='compile'`` 编译错误段）。
        """
        reason = schema_mismatch.get("reason", "unknown")
        if reason == "scalar_access_contract":
            # §step-93 腿1：设计标量点契约违约 → 专属反馈段（kind='scalar_contract'，
            # 区别于返回签名段——错误源在 kernel 数据通路，不在 m.def）。
            return {
                "kind": "scalar_contract",
                "reason": reason,
                "violations": schema_mismatch.get("violations", []),
                "hint": (
                    "每个标量数据搬送点三选一：①向量化（主循环搬送有 "
                    "DataCopy/DataCopyPad 等价物时标量理由不成立，须改）；②补 "
                    "reference（tiling_strategy.scalar_access_points[] 里设计声明的"
                    " name）；③补 deviation_evidence（failure_signature / "
                    "repro_or_log 指向真实存在的产物路径 / why_no_vector_equivalent"
                    " 三键齐备）。metadata/index 类 usage 免 reference 但必须登记。"
                    "遇 MTE/vector 流水竞态先查同步选型表（SetFlag/WaitFlag/"
                    "PipeBarrier），不得以标量化消灭流水。"),
                "retry_count": retries,
            }
        if reason == "opdef_optional_output":
            # F5：OpDef 输出 OPTIONAL（非 plugin 返回签名）→ 专属反馈段（kind='opdef_optional'，
            # 区别于 kind='schema_mismatch' 的返回签名段，避免误导 coder 去查 m.def）。
            return {
                "kind": "opdef_optional",
                "reason": reason,
                "def_file": schema_mismatch.get("def_file", ""),
                "output_name": schema_mismatch.get("output_name", ""),
                "hint": (
                    "OpDef 输出声明 ParamType(OPTIONAL) → AscendC 编译器多发射 8B kernel "
                    "参数槽（__CCE_KernelArgSize 48 vs host 40）→ kernel 入口读垃圾 tiling "
                    "指针 → 507057 向量核异常。OpDef 输出一律改为 ParamType(REQUIRED)；"
                    "可选性只表达在 torch schema `Tensor?` + plugin 返回 None（维5b/维11）。"),
                "retry_count": retries,
            }
        if reason == "reg_name_mismatch":
            # 注册名派生源错:OP_ADD/ADD_TO_LAUNCHER_LIST_AICORE 首参抄了 proto 数字段
            # 大写 → runtime 反推找不到 config → 361001。专属反馈段(kind='reg_name',
            # 错误源在 def.cpp/op_api 注册宏,不在 m.def),指引从 op_name 派生。
            return {
                "kind": "reg_name",
                "reason": reason,
                "reg_file": schema_mismatch.get("reg_file", ""),
                "registered_name": schema_mismatch.get("registered_name", ""),
                "expected_derived": schema_mismatch.get("expected_derived", ""),
                "runtime_candidates": schema_mismatch.get("runtime_candidates", []),
                "disk_op_name": schema_mismatch.get("disk_op_name", ""),
                "message": schema_mismatch.get("message", ""),
                "retry_count": retries,
            }
        declared = schema_mismatch.get("declared_returns") or []
        impl_kind = schema_mismatch.get("impl_return_kind") or "?"
        hints = {
            "tuple_vs_vector": (
                "m.def 声明定长返回元组 (N≥2)，但 C++ 实现返回 std::vector<Tensor> —— "
                "vector 被 PyTorch 推断为 Tensor[]（1 个变长返回），与声明的 N 个定长返回 "
                "矛盾，checkSchema 注册时拒。应改为 std::tuple<...>，可选输出位用 "
                "c10::optional<Tensor>/std::optional<Tensor> 表达（缺席返回 c10::nullopt）。"),
            "single_vs_vector": (
                "m.def 声明单个 -> Tensor，但 C++ 实现返回 std::vector<Tensor>（推断 "
                "Tensor[] 变长）——Tensor 与 Tensor[] 是不同返回类型。单个 Tensor 应返回 "
                "torch::Tensor/at::Tensor。"),
            "tuple_arity_mismatch": (
                "m.def 声明的返回元组元素数与 C++ 实现 std::tuple<...> 元素数不一致，"
                "checkSchema 按返回数拒注册。对齐两者元素数。"),
            "tuple_vs_single": (
                "m.def 声明返回元组 (N≥2)，但 C++ 实现返回单个 Tensor —— 返回数不一致。"
                "应按 m.def 返回全输出元组。"),
            "runtime_checkSchema_mismatch": (
                "smoke 时 PyTorch checkSchema 拒绝注册：m.def 声明与 C++ 实现返回签名 "
                "不一致（expected/inferred 见反馈）。对齐实现返回类型到 m.def 声明。"),
        }
        return {
            "kind": "schema_mismatch",
            "reason": reason,
            "plugin_file": schema_mismatch.get("plugin_file", ""),
            "declared_returns": declared,
            "impl_return_kind": impl_kind,
            "runtime_schema": schema_mismatch.get("runtime_schema"),
            "hint": hints.get(
                reason, "对齐 m.def 返回签名与 C++ 实现返回类型。"),
            "retry_count": retries,
        }
    def _collect_smoke_feedback(self, state: State, err, retries: int,
                                phase: str | None, schema_info: dict | None) -> dict:
        """smoke-retry 反馈按「具体优先」选内容（§2.5 单一通路，checkSchema 白名单并入为最具体档）。"""
        if schema_info is not None:
            return self._collect_schema_feedback(state, {
                "reason": "runtime_checkSchema_mismatch",
                "plugin_file": "",
                "declared_returns": [schema_info.get("expected_schema", "")],
                "impl_return_kind": schema_info.get("inferred_schema", ""),
                "runtime_schema": schema_info,
            }, retries)
        if phase == "host":
            return self._collect_smoke_host_feedback(state, err, retries)
        return self._collect_smoke_owner_judge_feedback(state, err, retries)
    def _collect_smoke_host_feedback(self, state: State, err, retries: int) -> dict:
        """host 阶段 smoke 失败反馈（Part B）：kernel 未执行 → codegen 脚手架产物缺陷。

        ``kind='smoke_host'`` → prompt 渲染 host 脚手架修复指引段（区别于 compile /
        schema_mismatch / opdef_optional 段）。
        """
        details = getattr(err, "details", {}) or {}
        return {
            "kind": "smoke_host",
            "reason": "host_phase_launch_failed",   # 阶段分类（不枚举错误码）
            "error_line": self._first_smoke_error_line(details),
            "log_path": details.get("log", ""),
            "stderr_tail": (details.get("stderr_tail") or "")[:1500],
            "retry_count": retries,
            "facts": self._smoke_facts(state, details),
            # 一句话指引；完整修复/归属判定指引由 prompt 段正文承载（N1：不重复展开）
            "hint": "host 侧 launch 失败（kernel 未执行）根因在 codegen 脚手架产物"
                    "（tiling/infershape/attr 接线/注册宏）——见下方完整修复指引",
        }
    def _collect_smoke_owner_judge_feedback(self, state: State, err, retries: int) -> dict:
        """歧义区（phase=None）smoke 失败反馈：框架无法机械判定阶段 → 交 coder 判归属。"""
        details = getattr(err, "details", {}) or {}
        return {
            "kind": "smoke_owner_judge",
            "reason": "ambiguous_phase",
            "error_line": self._first_smoke_error_line(details),
            "log_path": details.get("log", ""),
            "stderr_tail": (details.get("stderr_tail") or "")[:1500],
            "retry_count": retries,
            "facts": self._smoke_facts(state, details),
            # 一句话指引；完整归属判定指引由 prompt 段正文承载（N1：不重复展开）
            "hint": "框架无法机械判定失败阶段（kernel 是否执行过）——见下方完整归属判定指引",
        }
    @staticmethod
    def _first_smoke_error_line(details: dict) -> str:
        """从 smoke 日志提取首条错误行（RuntimeError / Execution_Error 等），截断 300 字符。"""
        full = details.get("stderr_tail", "") or ""
        log_path = details.get("log", "") or ""
        if log_path:
            try:
                with open(log_path, encoding="utf-8", errors="replace") as f:
                    full = f.read()
            except OSError:
                pass
        for ln in full.splitlines():
            s = ln.strip()
            if not s or s.startswith("==="):
                continue   # 日志结构头（=== rc/stdout/stderr ===）非错误行
            low = s.lower()
            if ("runtimeerror" in low or "execution_error" in low or "ez1008" in low
                    or "failed to execute" in low or "error:" in low):
                return s[:300]
        for ln in full.splitlines():
            s = ln.strip()
            if s and not s.startswith("==="):
                return s[:300]
        return ""
    @staticmethod
    def _is_manifest_exhausted_halt(err) -> bool:
        return (err is not None
                and getattr(err, "stage_name", None) == "codegen"
                and getattr(err, "error_type", "") == "exhausted"
                and (getattr(err, "details", None) or {}).get(
                    "reason") == "manifest_non_conforming_exhausted")
    def _plugin_schema_retry(self, state: State, agent_result, manifest,
                             decision_logs: dict, schema_mismatch: dict,
                             iterations: int,
                             build_result: BuildResult | None = None) -> State:
        """方案 A/B 共用的定向 retry：plugin 返回签名不一致 → 回 codegen 重修。

        镜像 build-retry：不设 ``last_error``（不 halt）、不写 ``deploy_result``
        （output_contract 不满足 → runner 自动重 spawn 带 ``codegen_build_feedback``）。
        预算与 build-retry 共享（``codegen_build_retries`` / ``_build_retry_limit``），
        耗尽 → D4 逃生（带 ``smoke_passed=False`` 交下游，不硬 halt——fixable issues
        not hard-halt 指令；此时 scope_guard 兜底上游判定）。``build_result`` 只在 D4
        逃生时随 ``deploy_result`` 前进：A（pre-build）默认 passed=False；B（smoke 后）
        传入实际值（编译已过，passed=True）。
        """
        from ascendc_devkit.infra.logger import Logger

        self._persist_sources(state, agent_result.artifacts)
        retries = state.codegen_build_retries + 1
        limit = self._build_retry_limit()
        build_result = build_result or BuildResult(passed=False)
        if retries >= limit:
            Logger.warn(
                f"codegen plugin schema retry exhausted ({retries}/{limit}); "
                f"escaping to D4 — carrying deploy_result(smoke_passed=False) "
                f"downstream (scaffolding schema contract still mismatched: "
                f"{schema_mismatch.get('reason')}).")
            return state.with_updates(
                last_error=None,
                generated_sources=agent_result.artifacts,
                codegen_iterations=iterations,
                codegen_consecutive_failures=0,
                codegen_orphan_streak=0,
                decision_logs=decision_logs,
                codegen_manifest=manifest,
                build_result=build_result,
                deploy_result=DeployResult(smoke_passed=False),
                codegen_build_retries=retries,
                codegen_build_feedback=None,
                # schema-retry 是另一重试循环 → smoke streak 重置
                codegen_smoke_same_error_streak=0,
                codegen_smoke_last_error_sig="",
            )
        feedback = self._collect_schema_feedback(state, schema_mismatch, retries)
        Logger.warn(
            f"codegen plugin return-schema mismatch "
            f"({schema_mismatch.get('reason')}, retry {retries}/{limit}); NOT "
            f"writing deploy_result — runner will re-spawn coder with schema "
            f"feedback.")
        return state.with_updates(
            last_error=None,
            generated_sources=agent_result.artifacts,
            codegen_iterations=iterations,
            codegen_consecutive_failures=0,
            codegen_orphan_streak=0,
            decision_logs=decision_logs,
            codegen_manifest=manifest,
            build_result=BuildResult(passed=False),
            # deploy_result 不设 → has_all=False → runner 自动重 spawn
            codegen_build_retries=retries,
            codegen_build_feedback=feedback,
            # schema-retry 是另一重试循环 → smoke streak 重置
            codegen_smoke_same_error_streak=0,
            codegen_smoke_last_error_sig="",
        )
    def _render_artifact_feedback_section(self, afb: dict) -> str:
        """step-103：artifact_feedback 反馈段渲染（§1.15 单点，fresh/resume 共用）。"""
        missing = afb.get("missing_fields") or []
        afeedback_lines = [
            "## 上轮 codegen_manifest 非契约反馈（框架 artifact-retry）",
            f"- 缺失字段: **{missing}**",
            f"- 重试: 第 {afb.get('retry_count', 0)} 次",
            f"- 修复指引: {afb.get('hint', '')}",
            "",
            "codegen_manifest.json 是**算子签名契约**——**必填仅 op_name + "
            "callable_target**（P1 收敛：inputs/outputs/attrs 可选，IO 不被下游"
            "消费；声明了则须与 plugin m.def 一致），不是会话报告。调试/运行时内容"
            "（compile_status/runtime_status/suspected_root_causes/next_steps/"
            "files/...）写进 decision_log.json，**禁止进 manifest**。schema 见 "
            "`schema/codegen_manifest.json`。",
        ]
        return "\n".join(afeedback_lines)
    def _render_build_feedback_section(self, fb: dict, run_dir: str) -> str:
        """step-103：build_feedback 的 kind 专属反馈段渲染（§1.15 单点）——
        fresh prompt 反馈段与 resume 消息共用同一渲染（此前 resume 走通用摘要
        会丢失 kind 专属上下文与修复指引）。块体为阶段3 方案 Z 原文搬运。"""
        default_log = f"{run_dir}/subprocess/build_ascendc.log"
        if fb.get("kind") == "opdef_optional":
            # F5：OpDef 输出 OPTIONAL → 专属反馈段（区别于编译错误段 / schema
            # 返回签名段——错误源在 {op}_def.cpp 的输出 param_type，不是 m.def）。
            return (
                "## 上轮 OpDef 输出 OPTIONAL 契约反馈（框架 opdef retry）\n"
                f"- 文件: **{fb.get('def_file', '')}**\n"
                f"- 输出: **{fb.get('output_name', '')}**\n"
                f"- 重试: 第 {fb.get('retry_count', 0)} 次\n"
                f"- 修复指引: {fb.get('hint', 'OpDef 输出改 ParamType(REQUIRED)')}\n"
                "\n"
                "请在上一版代码基础上把该 OpDef 输出改为 `ParamType(REQUIRED)`——"
                "可选性只表达在 torch schema `Tensor?` + plugin 返回 None（skill 自检表"
                "维5b/维11）；不改 kernel/tiling，**禁止修改 golden/参考实现**"
                "（golden 是权威真值 §1.13，可选输出语义按 golden 在 plugin 返回层"
                "对齐，见维11）。**不要自己运行 build/redeploy**——"
                "改完代码后输出 `git diff --name-only -- op_host/ op_kernel/ op_api/ "
                "op_plugin/` 报告改动文件，框架会自动编译验证。"
            )
        if fb.get("kind") == "scalar_contract":
            # §step-93 腿1：设计标量点契约违约 → 标量通路专属反馈段。
            lines = [
                "## 上轮设计标量点契约违约反馈（框架 scalar-contract retry）",
                f"- 违约条目（{len(fb.get('violations', []))} 条）:",
            ]
            lines += [f"  - {v}" for v in fb.get("violations", [])]
            lines += [
                f"- 重试: 第 {fb.get('retry_count', 0)} 次",
                f"- 修复指引: {fb.get('hint', '三选一：向量化 / 补 reference / 补证据')}",
                "",
                "请在上一版代码基础上逐条处置（向量化 / 补 decision_log 引用 / 补"
                " deviation 证据），**不要整体回退重写**。kernel 阶段错误（vector "
                "core 异常/运行期数据错/同步竞态）不属于会话内吸收范围——记录到"
                " known_issues 交棒，框架会转交 precision 阶段（那里有 golden 与"
                "设计上下文）。**不要自己运行 build/redeploy**——改完代码后输出 "
                "`git diff --name-only -- op_host/ op_kernel/ op_api/ "
                "op_plugin/` 报告改动文件，框架会自动编译验证。",
            ]
            return "\n".join(lines)
        if fb.get("kind") == "schema_mismatch":
            # 方案 A/B：plugin 返回签名契约不匹配 → schema 专属反馈段（区别于
            # 编译错误段，避免误导 coder 去查 clang 错误）。
            schema_lines = [
                "## 上轮 plugin 返回签名契约不匹配反馈（框架 schema retry）",
                f"- 不匹配类别: **{fb.get('reason', 'unknown')}**",
                f"- m.def 声明返回: `{fb.get('declared_returns') or []}`",
                f"- C++ 实现返回分类: `{fb.get('impl_return_kind') or '?'}`",
                f"- 重试: 第 {fb.get('retry_count', 0)} 次",
                f"- 修复指引: {fb.get('hint', '对齐 m.def 返回签名与 C++ 实现返回类型')}",
                "",
                "请在上一版代码基础上修复 op_plugin 的返回签名/实现返回类型一致性"
                "（不改 kernel/tiling）。**不要自己运行 build/redeploy**——改完代码后"
                "输出 `git diff --name-only -- op_host/ op_kernel/ op_api/ "
                "op_plugin/` 报告改动文件，框架会自动编译验证。",
            ]
            return "\n".join(schema_lines)
        if fb.get("kind") == "smoke_host":
            # Part B（20260810）：host 阶段 smoke 失败（kernel 未执行）→ host 脚手架修复指引段。
            host_lines = [
                "## 上轮 host 侧启动失败反馈（框架 smoke host-retry）",
                f"- 错误分类: **{fb.get('reason', 'unknown')}**",
                f"- 首条错误行: `{fb.get('error_line', '')}`",
                f"- 重试: 第 {fb.get('retry_count', 0)} 次",
                f"- 完整 smoke 日志: `{fb.get('log_path') or default_log}`",
                f"- 修复指引: {fb.get('hint', '修复 host 脚手架（tiling/infershape/attr 接线/注册宏）')}",
            ]
            host_lines += self._render_smoke_facts_lines(fb)
            host_lines += ["",
                "请在上一版代码基础上修复 host 侧脚手架缺陷（op_host tiling/infershape / "
                "op_api attr 接线 / op_plugin 注册宏）——参考目标仓/stock 现有算子代码形态，"
                "禁止凭记忆写；禁止改 kernel/golden。**若你判定该错误不归 codegen 产物修**"
                "（harness/框架/设计 tiling 策略/环境），在 decision_log.json 写 "
                "`codegen_smoke_ownership: {verdict: \"not_codegen\"|\"upstream_design\", "
                "reason, evidence}` —— 框架将放行到下游（不交上游）。"
                "**不要自己运行 build/redeploy**——改完输出 `git diff --name-only -- "
                "op_host/ op_kernel/ op_api/ op_plugin/` 报告改动文件，框架会自动编译验证。",
            ]
            if fb.get("stderr_tail"):
                host_lines.append(f"- stderr 摘要:\n```\n{fb.get('stderr_tail')}\n```")
            return "\n".join(host_lines)
        if fb.get("kind") == "smoke_owner_judge":
            # Part B（20260810）：歧义区（机械无法判 kernel 是否执行）→ 交 coder 判归属。
            judge_lines = [
                "## 上轮 smoke 失败归属判定（框架 smoke owner-judge）",
                f"- 首条错误行: `{fb.get('error_line', '')}`",
                f"- 完整 smoke 日志: `{fb.get('log_path') or default_log}`",
                f"- 判定指引: {fb.get('hint', '判断归属并修复或写 codegen_smoke_ownership')}",
            ]
            judge_lines += self._render_smoke_facts_lines(fb)
            judge_lines += ["",
                "请判断该 smoke 失败是否属于你的 codegen 产物可修范围："
                "（a）错误在你的 op_host/op_api/op_plugin 产物 → 修复；"
                "（b）不归 codegen 修（harness/框架/设计 tiling 策略/环境）→ 在 "
                "decision_log.json 写 `codegen_smoke_ownership: {verdict: \"not_codegen\"|"
                "\"upstream_design\", reason, evidence}`，框架将放行到下游（不交上游）。"
                "**不要自己运行 build/redeploy**——改完输出 `git diff --name-only -- "
                "op_host/ op_kernel/ op_api/ op_plugin/` 报告改动文件，框架会自动编译验证。",
            ]
            if fb.get("stderr_tail"):
                judge_lines.append(f"- stderr 摘要:\n```\n{fb.get('stderr_tail')}\n```")
            return "\n".join(judge_lines)
        if fb.get("kind") == "reg_name":
            # 注册名派生源错：OP_ADD/ADD_TO_LAUNCHER_LIST_AICORE 首参抄 proto 数字段大写
            # → runtime 反推找不到 config → 361001。专属反馈段（kind='reg_name'）。
            return (
                "## 上轮 AICore 注册名派生源反馈（框架 reg-name retry）\n"
                f"- 文件: **{fb.get('reg_file', '')}**\n"
                f"- 注册名(现): `{fb.get('registered_name', '')}`\n"
                f"- runtime 反推候选: `{fb.get('runtime_candidates') or []}`\n"
                f"- 落盘目录名(op_name): `{fb.get('disk_op_name', '')}`\n"
                f"- 应派生为: `{fb.get('expected_derived', '')}`\n"
                f"- 重试: 第 {fb.get('retry_count', 0)} 次\n"
                f"- 修复指引: 注册名须从落盘目录名（op_dir 末段；带前缀仓 = 前缀 + golden "
                "snake，勿用 strip 后短名）经 snake_to_pascal 派生"
                "（每 `_` 段 capitalize 后拼接），**勿直接抄 proto/requirement 的 "
                "operator.name**——proto 数字段大写会让 runtime 按注册名反推找不到以落盘"
                "目录名命名的 config → 361001。\n"
                "\n"
                "请在上一版代码基础上修正 op_host/*_def.cpp 的 `OP_ADD` 与 op_api/*.cpp 的 "
                "`ADD_TO_LAUNCHER_LIST_AICORE` 注册名（不改 kernel/tiling，**禁止修改 "
                "golden/参考实现** §1.13）。**不要自己运行 build/redeploy**——改完代码后"
                "输出 `git diff --name-only -- op_host/ op_kernel/ op_api/ op_plugin/` "
                "报告改动文件，框架会自动编译验证。"
            )
        log_path = fb.get("log_path") or default_log
        feedback_lines = [
            "## 上轮编译失败反馈（框架 build-retry）",
            f"- 错误分类: **{fb.get('error_class', 'unknown')}**",
            f"- 重试: 第 {fb.get('retry_count', 0)} 次",
            f"- 完整编译日志: `{log_path}`（读此文件获取 clang error 行 + 框架"
            "错误分析 footer）",
        ]
        # 结构化首错注入（2026-09-10）：scan_kernel_compile_errors 从完整日志提取的
        # 首 N 条错误直接进反馈文本——agent 不读日志也看得到根错误（silent-cut 轮
        # 只 thinking 不读文件的场景下，这是错误进入模型的唯一通道）。stderr 尾部
        # 摘要（截断残影）不再渲染——误导性尾巴（如 "did you mean 'perm'"）会引
        # agent 修错处；完整信息在 log_path 里，agent 需要时 Read。
        error_lines = fb.get("error_lines") or []
        if error_lines:
            feedback_lines.append("- 首错误（框架从编译日志结构化提取）:")
            feedback_lines += [f"  - `{e}`" for e in error_lines]
        # 方案 2 + ccec 知识化收敛：不在 prompt 展开 ccec 方法（避免逐轮指令诱导），
        # 仅在签名类错误时给一句判据指针，方法沉淀在 skill references 知识文件按需查。
        # 判据兼容两种形态：结构化 error_lines（新）或 stderr_tail（旧 snapshot/无
        # 结构化提取时）。不渲染 stderr_tail 全文，只在签名类判断上用。
        _tail = (fb.get("stderr_tail") or "")[:1500]
        _sig_hit = any("no matching function" in e for e in error_lines) \
            or "no matching function" in _tail
        if fb.get("error_class") == "C-API" and _sig_hit:
            feedback_lines.append(
                "- **no matching function = API 签名/用法错**：查正确签名优先"
                "知识库/ascendc-tips；若仍存疑可做最小单文件编译验证，"
                "方法见 ascendc-op-dev-coding skill 的 references（验证 API 用法）。"
            )
        feedback_lines.append(
            "\n请在上一版代码基础上修复编译错误。**不要自己运行 build/redeploy**——"
            "改完代码后输出 `git diff --name-only -- op_host/ op_kernel/ op_api/ "
            "op_plugin/` 报告改动文件，框架会自动编译验证。"
        )
        return "\n".join(feedback_lines)
    def _render_retry_resume_prompt(self, state: State) -> str:
        """反馈重派轮的 resume 消息：resume 场景首句（同会话继续修复）+
        **与 fresh prompt 同源的 kind 专属反馈段**（§1.15 单点渲染——此前通用
        摘要会丢失 kind 专属上下文与修复指引）。build_feedback 优先于
        artifact_feedback（与 actions 的 feedback 取用顺序一致）。"""
        ws = getattr(state, "_workspace", None)
        run_dir = str(ws.dir) if ws is not None else "<run_dir>"
        if state.codegen_build_feedback:
            body = self._render_build_feedback_section(
                state.codegen_build_feedback, run_dir)
        else:
            body = self._render_artifact_feedback_section(
                state.codegen_artifact_feedback)
        return (
            "上一轮交付未通过框架校验，请在同一会话继续修复（勿重做已交付的"
            "正确部分，只改被指认的问题后重新交付）：\n\n" + body
        )
    @staticmethod
    def _render_smoke_facts_lines(fb: dict) -> list[str]:
        """smoke 失败反馈的客观事实块渲染（§0 事实第一性：只陈述观测 + 实证方法）。

        事实：死亡方式（rc）、最后进度打点（流水线段位）、复现现场（脚本 + 框架
        env）、前次会话产物指针（结构化计数，不搬结论文本 §2.10）。判界方法仅在
        「invoking 后死亡」段给出（加日志实证，跨框架验证循环），不要求模型猜。
        """
        facts = fb.get("facts") or {}
        lines: list[str] = []
        rc = facts.get("rc_label") or ""
        marker = facts.get("last_marker") or ""
        script = facts.get("script_path") or ""
        env = facts.get("env_summary") or {}
        prev = facts.get("prev_decision_log") or {}
        if rc:
            lines.append(f"- 进程死亡方式: **{rc}**")
        if marker:
            lines.append(f"- 最后进度打点: `{marker}`（其后打点未出）")
        elif rc:
            lines.append("- 最后进度打点: 无（首个用例未开始——崩在 import/加载/初始化段）")
        if marker or rc:
            lines.append("  - 打点语义（固定流水线段位，非错误分类）: `start`=用例开始"
                         "（输入生成前）/ `invoking`=进入 op 调用链 / `kernel_done`="
                         "kernel 调用返回 / `golden_done`=golden 参考算完")
        if script:
            lines.append(f"- 复现现场: `python -u {script}`（**后续自检一律复用此脚本，"
                         "勿自建副本**——两套脚本会分叉出「自检绿、框架红」的假矛盾）")
            # P13 (step-116)：卡 env（VISIBLE_DEVICES/NPU_ID）不进注入文本——
            # agent 自己的 shell 经 serve 继承已带 pin，复现脚本默认即落本 op
            # 卡；注入变量名只会制造卡感知（零卡知识裁定延伸到变量名）。
            for k in ("PYTHONPATH", "ASCEND_CUSTOM_OPP_PATH"):
                if env.get(k):
                    lines.append(f"  - {k}={env[k]}")
            if env.get("LD_LIBRARY_PATH"):
                lines.append(f"  - LD_LIBRARY_PATH={env['LD_LIBRARY_PATH'][:300]}")
        if prev.get("path"):
            lines.append(f"- 前次会话产物: `{prev['path']}`（known_issues={prev.get('known_issues', 0)}"
                         f"、scalar_access_points={prev.get('scalar_access_points', 0)}"
                         + (f"，标题: {prev['known_issue_titles']}" if prev.get("known_issue_titles") else "")
                         + "）——先读再动手，勿重复推导已知结论")
        if marker.endswith("invoking"):
            lines.append(
                "- 判界方法（实证，非猜测）: 崩点在 op 调用链内（invoking 后、"
                "kernel_done 前），host 胶水/device 从进程外不可分——在 launch 前后"
                "加日志探针（如 aclnn 调用前一行输出），经框架验证循环交付（git diff "
                "报告改动→框架自动重编译重跑），下一轮反馈会携带你的日志输出："
                "日志未出即崩=launch 之前=host 胶水（你的产物，就地修）；日志已出后崩"
                "=launch 之后=device 侧（不归你修——崩点证据记 known_issues 并写 "
                "`codegen_smoke_ownership` verdict 交棒）")
        return lines
    @classmethod
    def _build_error_signature(cls, err) -> str:
        """build 编译错误稳定签名（2026-09-10 advisory 废弃收口，机械 stop-loss 用）。

        与 ``_smoke_error_signature`` 同源思路（build 侧镜像）：从 build 失败日志的
        完整内容提取**稳定错误特征**——所有 ``error:`` 行（去噪后保留消息）+ 所有
        file:line 定位。任何错误变化（消息/文件/行）→ 签名变化 → streak 重置
        （避免"首错相同、后续错误不同"被误判为同错 → 误 stop-loss）；只有全部
        特征逐字不变（真·无进展）才累计。归一化吸收绝对路径前缀（worktree 目录
        每轮可能不同，是纯噪声）与独立数字（形状/行号变化视为无进展的保守权衡）。
        """
        details = getattr(err, "details", {}) or {}
        full = details.get("stderr_tail", "") or ""
        log_path = details.get("log", "") or ""
        if log_path:
            try:
                with open(log_path, encoding="utf-8", errors="replace") as f:
                    full = f.read()
            except OSError:
                pass
        # 所有 error: 行（去噪后保留消息）+ 所有 file:line 定位。worktree 绝对路径
        # 前缀归一（路径段每轮不同是纯噪声，删到相对形态），独立数字归 N。
        err_msgs = []
        locs = []
        for m in re.finditer(r"(?P<loc>[^\s:][^:\n]*):(?P<line>\d+):\d+:\s*(?:\n\s*)?error: (?P<msg>[^\n]+)", full):
            loc = re.sub(r"^(?:/[\w.-]+)+/", "", m["loc"])   # 去绝对路径前缀 → 相对
            locs.append(f"{loc}:{m['line']}")
            msg = re.sub(r"\b\d+\b", "N", m["msg"].strip())  # 独立数字归 N
            err_msgs.append(msg[:160])
        # 错误消息去重排序 + 定位去重排序（多 tiling_key 复现同一错只算一条）
        parts = []
        if locs:
            parts.append("locs=" + "|".join(sorted(set(locs)))[:2000])
        if err_msgs:
            parts.append("msgs=" + "|".join(sorted(set(err_msgs)))[:3000])
        return "@".join(parts)
    @classmethod
    def _smoke_error_signature(cls, err) -> str:
        """smoke 错误稳定签名（机械 stop-loss 用）。

        归一化**全量**错误特征：**所有**错误码 + **所有** FILE:LINE 定位 + 首条错误行内容
        （去 PID/地址/独立数字噪声）。签名 = 全量特征——多错并存时任一错误变化 → 签名变化 →
        streak 重置（避免"首错相同、后续错误不同"被误判为同错 → 误 stop-loss）；只有全部
        特征逐字不变（真·无进展）才累计。码/文件/行来自精确错误标记，不入噪音（PID 删除、
        0x 地址归一、独立数字归一为 N——否则每次重试 PID/形状变、签名变、stop-loss 永不触发）。
        """
        details = getattr(err, "details", {}) or {}
        full = details.get("stderr_tail", "") or ""
        log_path = details.get("log", "") or ""
        if log_path:
            try:
                with open(log_path, encoding="utf-8", errors="replace") as f:
                    full = f.read()
            except OSError:
                pass
        # 所有错误码（set 去重 + 排序，保证多错并存时全量捕获、顺序稳定）
        codes = sorted(set(re.findall(
            r"EZ\d+|507\d{3}|561\d{3}|Failed to execute (?:tiling|inferShape)|invalid \w+ value",
            full)))
        # 所有 FILE:LINE 定位（保留行号——代码编辑移行 → 签名变 → streak 重置，给 coder 更多机会）
        locs = sorted({f + (f":{l}" if l else "") for f, l in re.findall(
            r"\[FILE:([^\]]+)\](?:\[LINE:(\d+)\])?", full)})
        # 全部错误行内容（去噪后保留消息——**不只首条**：多错并存时首条匹配行相同、后续
        # 错误行消息变化（如 "inferShape failed for input x"→"input y"，同码同位置仅文本变）
        # 也必须改变签名，否则误判无进展 → 误 stop-loss；M3 review 坐实）。归一化吸收 PID/
        # 地址/独立数字（形状/行号）噪声——数字变化视为噪声（有意权衡：同码同位置仅数字变
        # 化的错误视为无进展，stop-loss 触发是保守设计）。
        error_lines = []
        for ln in full.splitlines():
            s = re.sub(r"\s+", " ", ln.strip())
            if re.search(r"RuntimeError|Execution_Error|EZ\d+|Failed to execute|invalid \w+ value", s):
                s = re.sub(r"PID:\s*\d+", "", s)          # PID 纯噪声，删
                s = re.sub(r"0x[0-9a-fA-F]+", "0xN", s)   # 地址归一
                s = re.sub(r"\b\d+\b", "N", s)            # 独立数字（形状/行号）归一
                error_lines.append(s[:160])
        # 去重 + 排序 + 截断（顺序稳定、防重复行/海量错误行膨胀签名）
        err_lines = "|".join(sorted(set(error_lines)))[:4000]
        # 前缀：进程死亡方式 + 最后进度打点（通道不变式）——「同码同位置」但崩点
        # 段位/死亡方式变化（如加了判界日志后进度推进）= 有进展，签名变化重置
        # streak；静默失败（rc 稳定 + 打点不推进）才持续累计触发 stop-loss。
        facts_rc = details.get("rc_label", "") or ""
        facts_marker = cls._smoke_last_marker(details)
        prefix = "/".join(x for x in (facts_rc, facts_marker or "nomarker") if x)
        return prefix + "@" + "|".join(codes or ["no_code"]) + "@" + ",".join(locs) + "@" + err_lines
    def _smoke_facts(self, state: State, details: dict) -> dict:
        """smoke 失败反馈的客观事实块（§0 事实第一性：只陈述观测，不猜原因）。

        汇聚：进程死亡方式（rc_label）、最后进度打点、复现现场（脚本 + env）、
        前次会话产物指针（worktree decision_log 的结构化计数摘要——不搬运 agent
        结论文本，§2.10）。缺失项静默省略（best-effort 事实，不阻断反馈主链）。
        """
        ctx = details.get("smoke_context") or {}
        facts: dict = {
            "rc_label": details.get("rc_label", "") or ctx.get("rc_label", ""),
            "last_marker": self._smoke_last_marker(details),
            "script_path": ctx.get("script_path", ""),
            "env_summary": ctx.get("env_summary") or {},
        }
        op_dir = getattr(state, "op_dir", None) or (
            state.op_identity.op_dir if getattr(state, "op_identity", None) else None)
        if op_dir:
            dl = Path(op_dir) / "decision_log.json"
            try:
                data = json.loads(dl.read_text(encoding="utf-8"))
                ki = data.get("known_issues") or []
                sp = data.get("scalar_access_points") or []
                facts["prev_decision_log"] = {
                    "path": str(dl),
                    "known_issues": len(ki),
                    "scalar_access_points": len(sp),
                    "known_issue_titles": [str(i.get("title", i.get("issue", "")))[:60]
                                           for i in ki[:3] if isinstance(i, dict)],
                }
            except (OSError, ValueError, json.JSONDecodeError):
                pass
        return facts
    @classmethod
    def _smoke_last_marker(cls, details: dict) -> str:
        """最后观测到的 harness 进度打点（客观事实，通道不变式消费端）。

        从 smoke 日志（log_path，持久化含 ``=== rc ===`` 头 + stdout 全量）提取
        最后一条 ``[harness] case N start/invoking/kernel_done/golden_done``——
        「死在流水线哪一段」的机械答案：零打点 = 首用例未开始（import/加载/
        初始化）；``invoking`` 后 ``kernel_done`` 前 = op 调用链内。打点由
        harness 模板 flush=True + 子进程 -u 保证 native 死亡不丢。读不到日志
        → 空串（超时/异常形态无 rc，走既有文案，不猜）。
        """
        log_path = details.get("log", "") or ""
        if not log_path:
            return ""
        try:
            with open(log_path, encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError:
            return ""
        last = ""
        for m in cls._SMOKE_MARKER_RE.finditer(content):
            last = f"case {m.group(1)} {m.group(2)}"
        return last
    def _smoke_retry(self, state: State, agent_result, manifest: dict | None,
                     decision_logs: dict, err, iterations: int,
                     phase: str | None, schema_info: dict | None,
                     build_result: BuildResult | None = None) -> State:
        """单一 smoke-retry 通路（Part B）：smoke 失败（kernel 未执行 / 歧义）回 codegen 重试。

        镜像 ``_plugin_schema_retry`` 的机制（共享 ``codegen_build_retries`` 预算 + 设
        ``codegen_build_feedback`` + 省略 ``deploy_result`` → runner 重 spawn + 耗尽 D4 逃生 +
        不设 ``last_error``）。反馈按分类链选内容（schema 专属 → host 通用 → 归属判定）。

        agent 归属判定兜底（§2.9②）：coder 在 decision_log 写 ``codegen_smoke_ownership``，
        只允许交下游（not_codegen / upstream_design → D4 逃生交 scope_guard），
        **禁止交上游**（upstream_design 不路由回 design，设计嫌疑随 WARN + decision_log 证据下行）。
        """
        from ascendc_devkit.infra.logger import Logger

        self._persist_sources(state, agent_result.artifacts)
        retries = state.codegen_build_retries + 1
        limit = self._build_retry_limit()
        build_result = build_result or BuildResult(passed=False)

        # 机械 stop-loss（用户 20260810 追加）：同一 smoke 错误签名连续重试 ≥K → 强制 D4，
        # 不依赖 coder 声明"不归我"——给"codegen 误判白耗"一个确定性上界。
        # streak 只在**同一 smoke 重试循环**内累计：同签名 +1、换签名重置为 1、空签名不累计。
        # 所有离开 smoke 循环的路径（归属 D4 / stop-loss D4 / 预算 D4 / 成功 / build·schema·artifact
        # 其它重试）都必须把 streak 重置为 0——否则陈旧 streak 跨上下文误触发 stop-loss（§1.2 可诊断）。
        sig = self._smoke_error_signature(err)
        if sig and sig == state.codegen_smoke_last_error_sig:
            streak = state.codegen_smoke_same_error_streak + 1
        else:
            streak = 1 if sig else 0

        # 1f：agent 归属判定消费（只交下游，禁止交上游）。
        # decision_logs 是 {stage_name: dl_content} 合并结构；coder 的 verdict 在 [self.name] 里。
        owner_dl = decision_logs.get(self.name) if isinstance(decision_logs, dict) else None
        ownership = self._read_smoke_ownership(owner_dl)
        # K 守卫用 smoke 特定同签名 streak（非共享 build_retries，M2）：coder 已对该错
        # 同签名重试 ≥K 次（上一轮累计）才 honor——build/schema 重试不折算为「已尝试过
        # 这个 smoke 错误」。streak=0 且无签名 → 永不 honor（无签名无法确认同错，最终预算
        # 耗尽 D4 兜底，保守正确）。
        if ownership is not None and self._ownership_honored(
                phase, state.codegen_smoke_same_error_streak, ownership):
            verdict = ownership.get("verdict")
            if verdict == "upstream_design":
                Logger.warn(
                    "[codegen smoke] coder 判定 upstream_design（疑似设计 tiling 策略缺陷）——"
                    "不路由回 design（暂禁止交上游），D4 交下游，证据随 decision_log 下行，"
                    f"由 eval/precision 兜底暴露: {ownership.get('reason', '')}")
            else:
                Logger.warn(
                    "[codegen smoke] coder 判定 not_codegen "
                    f"({ownership.get('reason', '')}) → D4 交下游 scope_guard 裁决")
            return state.with_updates(
                last_error=None,
                generated_sources=agent_result.artifacts,
                codegen_iterations=iterations,
                codegen_consecutive_failures=0,
                codegen_orphan_streak=0,
                decision_logs=decision_logs,
                codegen_manifest=manifest,
                build_result=build_result,
                deploy_result=DeployResult(smoke_passed=False),
                codegen_build_retries=retries,
                codegen_build_feedback=None,
                # 离开 smoke 循环 → streak 重置（防陈旧累计跨上下文）
                codegen_smoke_same_error_streak=0,
                codegen_smoke_last_error_sig="",
            )

        # 机械 stop-loss：同错误签名连续重试 ≥K 仍无进展 → 强制 D4（不依赖 coder 声明）
        if sig and streak >= _SMOKE_ERROR_STOP_LOSS_STREAK:
            Logger.warn(
                f"[codegen smoke] 同一错误签名连续 {streak} 次（`{sig}`）仍无进展 → 机械 "
                f"stop-loss 强制 D4 交下游（不依赖 coder 声明；retry {retries}/{limit}，不 halt）。")
            return state.with_updates(
                last_error=None,
                generated_sources=agent_result.artifacts,
                codegen_iterations=iterations,
                codegen_consecutive_failures=0,
                codegen_orphan_streak=0,
                decision_logs=decision_logs,
                codegen_manifest=manifest,
                build_result=build_result,
                deploy_result=DeployResult(smoke_passed=False),
                codegen_build_retries=retries,
                codegen_build_feedback=None,
                # 离开 smoke 循环 → streak 重置
                codegen_smoke_same_error_streak=0,
                codegen_smoke_last_error_sig="",
            )

        if retries >= limit:
            Logger.warn(
                f"codegen smoke-retry exhausted ({retries}/{limit}); escaping "
                f"to D4 — carrying deploy_result(smoke_passed=False) downstream "
                f"(host-phase launch defect still unfixed after framework retries).")
            return state.with_updates(
                last_error=None,
                generated_sources=agent_result.artifacts,
                codegen_iterations=iterations,
                codegen_consecutive_failures=0,
                codegen_orphan_streak=0,
                decision_logs=decision_logs,
                codegen_manifest=manifest,
                build_result=build_result,
                deploy_result=DeployResult(smoke_passed=False),
                codegen_build_retries=retries,
                codegen_build_feedback=None,
                # 离开 smoke 循环 → streak 重置
                codegen_smoke_same_error_streak=0,
                codegen_smoke_last_error_sig="",
            )

        feedback = self._collect_smoke_feedback(state, err, retries, phase, schema_info)
        Logger.warn(
            f"codegen smoke failed ({feedback.get('kind')}, retry {retries}/{limit}); "
            f"NOT writing deploy_result — runner will re-spawn coder with smoke feedback.")
        return state.with_updates(
            last_error=None,
            generated_sources=agent_result.artifacts,
            codegen_iterations=iterations,
            codegen_consecutive_failures=0,
            codegen_orphan_streak=0,
            decision_logs=decision_logs,
            codegen_manifest=manifest,
            build_result=build_result,
            # deploy_result 不设 → has_all=False → runner 自动重 spawn
            codegen_build_retries=retries,
            codegen_build_feedback=feedback,
            # 留在同一 smoke 重试循环 → streak 累计（同签名 +1，换签名已在上面重置为 1）
            codegen_smoke_same_error_streak=streak,
            codegen_smoke_last_error_sig=sig,
        )
    def is_satisfied(self, state: State) -> bool:
        """耗尽态不满足：占位 deploy_result 不是可接受交付——质量门必须
        失败，否则 runner F6"成功清错"会把 halt 信号当过时错误抹掉。"""
        return not self._is_manifest_exhausted_halt(
            getattr(state, "last_error", None))
    def stop_in_stage_retry(self, state: State) -> bool:
        """耗尽后继续 re-spawn 同一 coder 是空烧——立即停，交 workflow
        exhausted→__halt__ 路由（B3 stop_in_stage_retry 机制）。"""
        return self._is_manifest_exhausted_halt(
            getattr(state, "last_error", None))
    _SMOKE_MARKER_RE = re.compile(
        r"\[harness\] case (\S+) (start|invoking|kernel_done|golden_done)")

