"""L3 Orchestration — Codegen Stage: generate AscendC code from design spec."""

from __future__ import annotations

import json
from ascendc_devkit.orchestration.artifact_recovery import orphan_path_feedback
from ascendc_devkit.capabilities.agent._shared import (
    is_infra_error_type)
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from ascendc_devkit.domain.chip import chip_programming_model
from ascendc_devkit.domain.verification import BuildResult, DeployResult
from ascendc_devkit.orchestration.base import Stage
from ascendc_devkit.orchestration.registry import register_stage
from ascendc_devkit.orchestration.kernel.state import ErrorFeedback

if TYPE_CHECKING:
    from ascendc_devkit.orchestration.kernel.state import State


def classify_smoke_failure_phase(err) -> str | None:
    """smoke 失败阶段分类："kernel" | "host" | None（§1.12 结构信号，不认算子名）。

    §step-96 D3（docs/plan/converge-tail-reverification/）：提升为模块级单点
    （§1.15）——codegen 重试路由与 converge 收尾链共用同一死亡位置判别：
    launch 之后设备侧死亡 = 质量信号（不否决部署）；launch 之前 host 侧 =
    部署/脚手架缺陷（deploy_failed 门保留）。

    Part B（20260810）：把 smoke 失败按「失败阶段（kernel 是否执行过）」分流——业务语义，
    不用文件位置代理（脚手架缺陷与算法缺陷混在同一批 op_api/op_host/op_kernel 文件里，
    位置判不出；阶段判得出：kernel 从未执行 → host 侧脚手架域）。
    - "kernel"：kernel 执行过（507035/507057/AICORE/aivec/越界文本）→ 维持 D4 交 precision。
    - "host"：kernel 未执行（tiling/infershape/attr 接线/注册/launch，EZ1008/561001/561002
      家族 + "Failed to execute tiling/inferShape"）→ 回 codegen（生产者自闭环修自己的
      host 脚手架产物，§2.9）。判据是黑名单结构：只枚举 kernel 执行证据，host 侧是宽信号，
      新错误码自动归位 codegen。
    - None：无证据/未知 → 歧义区，交给 coder 判归属（不静默默认 D4）。
    507057 类（kernel 崩溃但根因 host OpDef）已由 F5 静态门 pre-deploy 拦截，正常到不了
    这里；到了也按 kernel 处理（运行期崩溃，根因追溯走 precision）——已知局限。
    """
    details = getattr(err, "details", {}) or {}
    stderr = details.get("stderr_tail", "") or ""
    log_path = details.get("log", "") or ""
    full = stderr
    if log_path:
        try:
            with open(log_path, encoding="utf-8", errors="replace") as f:
                full = f.read()
        except OSError:
            pass
    # kernel 执行证据（特异性强，优先）
    for mk in ("507035", "507057", "AICORE", "aivec",
               "GM address exceeds", "UB out of bounds"):
        if mk in full:
            return "kernel"
    # host 阶段证据（宽信号：错误码家族 + host 函数/阶段文本）
    for hk in ("EZ1008", "561001", "561002", "EZ1001", "EZ1006", "EZ1007",
               "Failed to execute tiling", "Failed to execute inferShape",
               "GetShapeAttrsInfo", "GetWorkspace", "kernel never executed",
               "TilingFunc", "inferShape"):
        if hk in full:
            return "host"
    return None


from ascendc_devkit.orchestration.stages.codegen_stage_mixin.regbase import RegbaseMixin
from ascendc_devkit.orchestration.stages.codegen_stage_mixin.contract import ContractMixin
from ascendc_devkit.orchestration.stages.codegen_stage_mixin.feedback import (
    FeedbackMixin,
    _BUILD_ERROR_STOP_LOSS_STREAK,
)
from ascendc_devkit.orchestration.stages.codegen_stage_mixin.deploy import DeployMixin
from ascendc_devkit.orchestration.stages.codegen_stage_mixin.prompt import PromptMixin


@register_stage
class CodegenStage(RegbaseMixin, ContractMixin, FeedbackMixin, DeployMixin, PromptMixin, Stage):
    name = "codegen"
    description = "Generate AscendC operator code from design specification"
    # F10（2026-08-21）：A3/A5 统一迭代预算 = 40。A3 Membase 的迭代上限与
    # build-retry 预算均收敛为 40（config iterations.stages.codegen /
    # codegen.build_max_retries 同值，保持 build-retry ≤ 迭代上限约束）；A5
    # Regbase 无配置覆盖时以本字段（40）兜底。编译地狱场景 40 轮后提前 D4
    # 逃生（carry smoke_passed=False 交下游，不 halt）——预算与失败模式匹配，
    # 而非防御性虚高 1000。
    default_max_iterations = 40
    fail_strategy = "halt"  # codegen 失败 → 中断 pipeline
    # Circuit breaker: stop re-spawning the coder after this many *consecutive*
    # hard agent failures (status != "ok"). Without this, a persistently failing
    # agent (e.g. a server-side API error before any file is written) leaves
    # generated_sources unset, so the output_contract is never satisfied and the
    # runner spins up to its 100-iteration safety net doing no useful work.
    # 20260820：熔断只对"空跑"（transcript 无 Write 证据，0 产出）与"超豁免窗口的
    # 连续孤儿"（F8，2026-08-21）计费——重试无意义（模型没进入写阶段 / 无视确定性
    # 路径反馈），阈值后 halt 防空烧 token。窗口内孤儿豁免，走迭代预算（1000，修
    # bug）重试（见 _transition_membase 的 artifact_misplaced 分支）。
    # 阈值收敛进 orchestration-config retry_budgets.consecutive_failures_max
    # （§1.15 方案 B）；不再用类属性 max_consecutive_failures。


    def rerun_reset_fields(self) -> list[str]:
        # P68: also zero the circuit breaker (codegen.py:156) — it is NOT in
        # output_contract.provides but gates re-entry; a stale trip from the prior
        # run would strand a fresh rerun attempt (same reason _resume_breaker_reset
        # zeros it on resume).
        #
        # Regbase state-machine fields MUST also be reset: a completed run leaves
        # codegen_phase="done", which makes actions() return [] (no-op), and the
        # runner immediately hits max_iterations without spawning any agent.
        fields = list(self.output_contract().provides) + ["codegen_consecutive_failures"]
        fields += [
            "codegen_phase", "codegen_s4_sub_stage", "codegen_s4_checkpoint_group",
            "codegen_record_dir", "codegen_pending_agent", "codegen_pending_resume_point",
            "codegen_vt", "codegen_et", "codegen_retries", "codegen_vf_previous_error",
            "codegen_build_retries", "codegen_build_feedback",
            "codegen_build_same_error_streak", "codegen_build_last_error_sig",
            "codegen_artifact_retries", "codegen_artifact_feedback",
            "last_agent_session_id",
            "last_agent_stage",
        ]
        return fields

    def rerun_reset_files(self, workspace) -> None:
        """删除 staging 目录下的 s4 调度器 checkpoint 文件 + VF 验证产物。

        progress.md / coding_index.md 等若保留旧 ✅，``resolve-sub-stage``
        会直接返回 DONE，整个 s4 循环（包括 VT dispatch）被跳过。
        vf_verified/ 保留旧结果会导致 s4-coding 跳过 VF 测试，直接集成
        可能已过期的实现。``_regbase_ensure_init`` 在下次进入 s4 时会
        重新创建这些文件。
        """
        import shutil
        staging = Path(workspace.artifacts) / "staging"
        for fn in ["progress.md", "coding_index.md", "coding_plan.md",
                   "history.log", "meta.json"]:
            fp = staging / fn
            if fp.exists():
                fp.unlink()
        vf_dir = staging / "vf_verified"
        if vf_dir.is_dir():
            shutil.rmtree(vf_dir)


    # =========================================================================
    # Regbase 辅助方法（路径计算 / 脚本调用 / 文件检查）
    # =========================================================================

    @staticmethod
    def _bash(script: str, *args: str) -> str:
        """调用 shell 脚本，返回 stdout（subprocess.run 封装）。"""
        cmd = ["bash", script, *args]
        cp = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if cp.returncode != 0:
            from ascendc_devkit.infra.logger import Logger
            Logger.warn(f"_bash non-zero exit: {' '.join(cmd)} → {cp.stderr.strip()}")
        return cp.stdout


    # =========================================================================
    # Regbase 幂等初始化
    # =========================================================================


    # =========================================================================
    # actions / transition
    # =========================================================================


    # =========================================================================
    # Membase actions（原 actions() 剩余逻辑精确搬运）
    # =========================================================================


    # =========================================================================
    # Regbase actions — 多步编排状态机
    # =========================================================================


    # —— manifest artifact-retry 耗尽的终态识别（窄 keyed，§1.10/§1.15）———
    # 耗尽路径带占位 deploy_result（smoke_passed=False，保 schema 完整）+
    # last_error（halt 意图），与 runner 两条归一化的前提「记错分支与交付
    # 产物互斥」冲突。靠 error_type=exhausted（退出 is_artifact_retry_error
    # 可重试类）+ 下面两个窄覆写（只认 details.reason 同键）把 halt 信号
    # 完整送到调用方（workflow exhausted→__halt__），不波及本 stage 其他
    # own-error 写点（s4/paused 等各自路径语义不变）。


    # ------------------------------------------------------------------
    # 方案 A/B：plugin 返回签名一致性 —— 脚手架问题必须由 codegen 解决。
    #
    # A（静态，pre-build）：m.def 声明返回签名 ↔ C++ 实现返回类型对质，只拦**高置信**
    #   语义必错类（fail-open），命中 → 定向 retry（回 codegen 重修），不 halt、不 defer。
    # B（运行期，smoke）：smoke 失败且 stderr 命中 checkSchema "doesn't match the
    #   expected function schema"（确定性信号，正常 plugin 永不触发）→ 同样定向 retry。
    # 两者共享 codegen_build_retries 预算 + _build_retry_limit（D4 逃生，不硬 halt）。
    # ------------------------------------------------------------------


    # §step-96 D3: 分类器已提升为模块级单点 classify_smoke_failure_phase
    # （§1.15——converge 收尾链与 codegen 重试路由共用）；staticmethod 别名保持
    # 既有 self._classify_smoke_phase 调用点零改动。
    _classify_smoke_phase = staticmethod(classify_smoke_failure_phase)


    # —— codegen manifest 契约：构造性派生 + 机械校验（§2.9 构造性保证 + §3.4 缺陷不放行）——
    # codegen_manifest.json 的 required_keys（权威源 schema/codegen_manifest.json）。
    def transition(self, state: State, result: dict) -> State:
        agent_result = result.get("agent_result")

        # Regbase 路由在 Membase guard 之前（s4 DONE 时 agent_result=None）
        model = chip_programming_model(state.design_target_chip or "")
        if model == "Regbase" and state.mode == "new":
            return self._transition_regbase(state, agent_result)

        # Membase guard
        if agent_result is None:
            return state

        # Membase — existing logic extracted to helper
        return self._transition_membase(state, result, agent_result)

    # =========================================================================
    # Membase transition（原 transition() 剩余逻辑精确搬运）
    # =========================================================================

    def _transition_membase(self, state: State, result: dict,
                            agent_result) -> State:
        """Membase 路径：沿用原 section 校验 + deploy 检查逻辑。

        分发器：按 agent_result.status 路由到三个 gate 方法——
        _membase_ok_transition（ok+artifacts：契契约门 + deploy 门）、
        partial（警告 + 落盘 + 落入 failure gate）、
        _membase_failure_transition（空跑/孤儿/failure 各结局）。
        """
        iterations = state.codegen_iterations + 1

        # step-112 (§2.5)：会话 id 回写已上收 runner 统一捕获
        # （Runner.run_stage transition 后写 last_agent_session_id）——本入口
        # 的 per-stage 回写删除，捕获通路唯一。

        if agent_result.status == "ok" and agent_result.artifacts:
            return self._membase_ok_transition(
                state, agent_result, iterations)

        if agent_result.status == "partial" and agent_result.artifacts:
            self._persist_sources(state, agent_result.artifacts)
            reason = agent_result.metrics.get("failure_reason", "") if agent_result.metrics else ""
            from ascendc_devkit.infra.logger import Logger
            Logger.warn(
                f"codegen agent {agent_result.agent_name} crashed mid-run with "
                f"partial output ({len(agent_result.artifacts)} files snapshotted "
                f"to artifacts/codegen/, not propagated downstream)"
                + (f": {reason}" if reason else "")
            )

        return self._membase_failure_transition(
            state, agent_result, iterations)

    # =====================================================================
    # Membase ok+artifacts gate：契契约门 + deploy 门（_transition_membase 拆出）
    # =====================================================================

    def _membase_ok_transition(self, state: State, agent_result,
                               iterations: int) -> State:
        """ok+artifacts 分支：契契约门序列 → deploy 门。

        契契约前处理（section 覆盖 / decision_logs / manifest 解析）→
        manifest 漂移/scaffolding/一致性校验 → _membase_contract_gates
        （命中任一 retry 即返回转移 State）→ missing_sections 拦截 →
        deploy 门（_membase_deploy_gate）。构自原 _transition_membase 的
        ok 分支（保真拆分，语义零改写）。
        """
        from ascendc_devkit.orchestration.kernel.state import ErrorFeedback

        # Repository invocation requirements augment design-declared
        # sections.  In particular, a torch_op profile always requires
        # op_plugin even if an upstream design accidentally omitted it.
        expected_dirs = self._required_codegen_sections(state)
        produced = set(agent_result.artifacts.keys())

        def _section_covered(section_dir: str) -> bool:
            prefix = section_dir + "/" if not section_dir.endswith("/") else section_dir
            return any(k.startswith(prefix) for k in produced)

        missing_sections = [
            d for d in expected_dirs if not _section_covered(d)
        ]

        if missing_sections and state.mode == "incremental" and state.op_identity:
            op_dir = state.op_identity.op_dir
            missing_sections = [
                d for d in missing_sections
                if not (op_dir / d).is_dir()
                or not any((op_dir / d).iterdir())
            ]

        decision_logs = dict(state.decision_logs)
        dl_content = agent_result.artifacts.get("decision_log.json")
        if dl_content:
            try:
                dl = json.loads(dl_content)
                decision_logs[self.name] = dl
            except json.JSONDecodeError:
                pass

        manifest = None
        cm_content = agent_result.artifacts.get("codegen_manifest.json")
        if cm_content:
            try:
                manifest = json.loads(cm_content)
            except json.JSONDecodeError:
                pass

        if manifest is not None:
            self._warn_manifest_name_drift(state, manifest)
            self._inject_scaffolding_kind(state, manifest)
            self._check_plugin_schema_consistency(
                state, manifest, agent_result.artifacts)

        # Constructively ensure callable_target (derive symbol from the
        # op_plugin TORCH_LIBRARY_FRAGMENT registration the agent already
        # wrote — §2.9 constructive guarantee: the symbol is determined by
        # the plugin, not independent info), then mechanically validate the
        # manifest's required_keys (§3.4 — a non-conforming manifest is a
        # defective product; retry with targeted feedback rather than pass
        # it through or halt on first miss). Replaces the old
        # manifest_ct_missing → halt block (§2.5 single pathway).
        #
        # Gated on a resolved profile: the signature contract is defined by
        # the profile's invocation protocol — without a profile there is no
        # protocol, so the contract is undefined (and profile-less states
        # are how the section/deploy unit tests isolate their logic).
        early = self._membase_contract_gates(
            state, agent_result, iterations, manifest, decision_logs)
        if early is not None:
            return early

        if missing_sections:
            self._persist_sources(state, agent_result.artifacts)
            return state.with_updates(
                last_error=ErrorFeedback(
                    stage_name="codegen",
                    error_type="incomplete_output",
                    message=f"Missing expected sections: {sorted(missing_sections)}",
                    details={
                        "expected_sections": sorted(expected_dirs),
                        "missing_sections": sorted(missing_sections),
                        "produced_keys": sorted(produced)[:20],
                    },
                ),
                generated_sources=agent_result.artifacts,
                codegen_iterations=iterations,
                codegen_consecutive_failures=0,
                codegen_orphan_streak=0,
                decision_logs=decision_logs,
                codegen_manifest=manifest,
            )
        self._persist_sources(state, agent_result.artifacts)
        # W4: 先 relay 本轮 manifest（含 callable_target）进 state 再 compile —— 否则
        # Deployer.compile/install_and_smoke 的 _callable_target 读到旧/空
        # state.codegen_manifest，smoke 因 callable_target 缺失而假失败（foreach_norm
        # 20260807-144939-310314 的 codegen smoke_passed=False 即此因）。后续
        # with_updates(codegen_manifest=...) 幂等。
        if manifest is not None:
            state = state.with_updates(codegen_manifest=manifest)
        return self._membase_deploy_gate(
            state, agent_result, iterations, manifest, decision_logs)

    # =====================================================================
    # Membase 契契约门序列（_membase_ok_transition 拆出）
    # =====================================================================

    def _membase_contract_gates(self, state: State, agent_result,
                                iterations: int, manifest,
                                decision_logs: dict):
        """契契约门序列：命中任一 retry/拦截即返回转移 State；全过 → None。

        顺序保持原 _transition_membase ok 分支：
          profile 门（callable_target 派生 + required 校验 + F5 OpDef）→
          标量契约 → AICore 注册名 → torch_op 签名对质/host offload。
        命中返回（retry 或带 last_error 的 halt），未命中返回 None 继续。
        """
        from ascendc_devkit.orchestration.kernel.state import ErrorFeedback

        if state.profile is not None:
            manifest, _ct_ok = self._ensure_manifest_callable_target(
                state, manifest, agent_result.artifacts)
            _missing_required = self._missing_required_manifest_fields(manifest)
            self._warn_manifest_extra_fields(manifest)
            if _missing_required:
                return self._artifact_retry(
                    state, agent_result, manifest, decision_logs,
                    _missing_required, iterations)

            # F5：OpDef 输出 ParamType(OPTIONAL) → 定向 retry 回 codegen（全 kind：
            # torch_op 与 aclnn 均防 507057；aclnn 的 fail-closed smoke 无 kernel
            # 执行探针拦不住运行期异常，warn 不足以阻止传播，必须 retry 重修——脚手
            # 架问题由 codegen 解决）。与 A+B 共用预算 + D4 逃生（耗尽 → smoke_passed
            # =False 交 scope_guard 兜底）。
            opdef_opt = self._check_opdef_optional_output(
                state, agent_result.artifacts)
            if opdef_opt is not None:
                return self._plugin_schema_retry(
                    state, agent_result, manifest, decision_logs,
                    opdef_opt, iterations)

        # §step-93 腿1：设计标量点契约——coder 的标量数据搬送必须引用设计
        # 声明（tiling_strategy.scalar_access_points[].name）或携带完整
        # deviation 证据；op_kernel/ 有标量访问而清单空 = 簿记违约。
        # 门正当性（§2.9）：跨产物一致性（设计↔代码↔日志，单一 producer 看
        # 不全）+ 定向 retry 即反馈消费渠道；非 discover+regenerate。仅在
        # 设计产物在场时启用（无 tiling_strategy 即无声明集可查，单测/隔离
        # State 不受影响）。
        _sc = self._scalar_contract_violations(
            state, decision_logs, agent_result)
        if _sc:
            return self._plugin_schema_retry(
                state, agent_result, manifest, decision_logs,
                {"reason": "scalar_access_contract", "violations": _sc},
                iterations)

        # AICore 注册名派生源机械校验(全 scaffolding kind,非仅 torch_op——config
        # 反推错位是 driver/runtime 层,与 plugin 协议无关)。注册名抄 proto 数字段大写
        # → runtime 反推找不到 config → 361001。命中 → 定向 retry codegen(与契约门同
        # 预算/逃生),指引从 op_name 派生。位置在 torch_op 专属校验**之外**、deploy 之前
        # (省一轮 build+smoke)。
        reg_mismatch = self._aicore_registration_mismatch_error(
            state, agent_result.artifacts)
        if reg_mismatch is not None:
            return self._plugin_schema_retry(
                state, agent_result, manifest, decision_logs,
                {"reason": "reg_name_mismatch",
                 "message": reg_mismatch.message,
                 "reg_file": reg_mismatch.details.get("reg_file", ""),
                 "registered_name": reg_mismatch.details.get("registered_name", ""),
                 "expected_derived": reg_mismatch.details.get("expected_derived", ""),
                 "runtime_candidates": reg_mismatch.details.get("runtime_candidates", []),
                 "disk_op_name": reg_mismatch.details.get("disk_op_name", "")},
                iterations)

        profile_kind = self._profile_scaffolding_kind(state)

        if profile_kind == "torch_op":
            # 方案 A：静态返回签名对质（fail-open，只拦高置信类）→ 定向 retry 回
            # codegen 重修，不 defer 到 precision_debug（脚手架问题必须由 codegen
            # 解决）。放在 deploy 之前，省一轮 build+smoke。非 torch_op 无解析器
            # （§3.7 诚实，smoke fail-closed 兜底）。
            schema_mismatch = self._plugin_return_schema_mismatch(
                state, agent_result.artifacts)
            if schema_mismatch is not None:
                return self._plugin_schema_retry(
                    state, agent_result, manifest, decision_logs,
                    schema_mismatch, iterations)

            contract_error = self._torch_plugin_contract_error(
                state, agent_result.artifacts)
            registration = self._resolve_torch_registration(
                state, agent_result.artifacts)
            if contract_error is None and registration is not None:
                namespace, registered_name = registration
                expected_symbol = (
                    f"torch.ops.{namespace}.{registered_name}")
                actual_symbol = manifest["callable_target"]["symbol"]
                if actual_symbol != expected_symbol:
                    contract_error = ErrorFeedback(
                        stage_name="codegen",
                        error_type="incomplete_output",
                        message=(
                            f"callable_target.symbol '{actual_symbol}' conflicts "
                            f"with op_plugin registration '{expected_symbol}'"
                        ),
                        details={
                            "reason": "torch_op_symbol_mismatch",
                            "manifest_symbol": actual_symbol,
                            "registered_symbol": expected_symbol,
                        },
                    )
            if contract_error is not None:
                self._persist_sources(state, agent_result.artifacts)
                return state.with_updates(
                    last_error=contract_error,
                    generated_sources=agent_result.artifacts,
                    codegen_iterations=iterations,
                    codegen_consecutive_failures=0,
                    codegen_orphan_streak=0,
                    decision_logs=decision_logs,
                    codegen_manifest=manifest,
                )

            # 维10③ 机械门：plugin host CPU 往返（.cpu()/kCPU）→ 硬门 retry（与
            # regbase s5 同判据）。moe_re_routing 历史实证：host 算值 + copy_ 回
            # 输出 → cann-bench no_npu_kernel_detected。契约门在 deploy 之前，
            # 省一轮 build+smoke（§3.4 脚手架问题由 codegen 解决）。
            host_offload_error = self._plugin_host_offload_error(
                state, agent_result.artifacts)
            if host_offload_error is not None:
                self._persist_sources(state, agent_result.artifacts)
                return state.with_updates(
                    last_error=host_offload_error,
                    generated_sources=agent_result.artifacts,
                    codegen_iterations=iterations,
                    codegen_consecutive_failures=0,
                    codegen_orphan_streak=0,
                    decision_logs=decision_logs,
                    codegen_manifest=manifest,
                )

        return None

    # =====================================================================
    # Membase deploy 门（_membase_ok_transition 拆出）：compile→install_and_smoke
    # =====================================================================

    def _membase_deploy_gate(self, state: State, agent_result,
                             iterations: int, manifest,
                             decision_logs: dict) -> State:
        """方案 2 框架驱动编译-注入循环 + 三分支路由。

        先 compile（纯数据 I/O，不装系统不 smoke），按 err.details["step"] 路由：
          compile 错（build/resolve）→ 不写 deploy_result → resume/build-retry 循环
          install_*/smoke 错 → smoke 分流（host 回 codegen retry / kernel→D4 交 precision）
          None → 全过 → done。
        构自原 _transition_membase 的 deploy 段（保真拆分，语义零改写）。
        """
        from ascendc_devkit.infra.logger import Logger
        from ascendc_devkit.orchestration.stages.deploy import Deployer

        # 方案 2（L4 改动 2）：框架驱动编译-注入循环。transition 先调 Deployer().compile(state)
        # 做编译验证（纯数据 I/O，不装系统不 smoke），按 err.details["step"] 路由：
        #   compile 错（build/resolve）→ 不写 deploy_result → resume/build-retry 循环
        # compile 过 → install_and_smoke(state, compile_result) 复用产物做 install+smoke（不重 build）：
        #   install_*/smoke 错 → smoke 分流（host 回 codegen retry / kernel→D4 交 precision）
        #   None            → 全过 → done
        # 编译错误不经 last_error（会触发 halt），经 codegen_build_feedback State 字段 +
        # Deployer 自动落盘的 subprocess/build_*.log 接力给下轮 coder prompt。
        # 方案 2（D6 / L4 改动 2）：先 compile（只 build 不装系统不 smoke），
        # compile 过才 install+smoke（install_and_smoke 复用 compile 产物，不重 build）。
        # compile_err 只可能是 build（resume 修）或 resolve（不可修 halt）；
        # install_and_smoke_err 可能是 install_*/smoke。统一成 err/deploy_result 后，
        # 下方 build_failed / smoke_failed / unfixable 三分支逻辑沿用现状不动。
        _deployer = Deployer()
        _compile_result, _compile_err = _deployer.compile(state)
        build_result = BuildResult(passed=bool(_compile_result.run_package))
        if _compile_err is None:
            deploy_result, err = _deployer.install_and_smoke(state, _compile_result)
        else:
            deploy_result, err = _compile_result, _compile_err
        step = (err.details.get("step") if err is not None else None)
        build_failed = step in ("build", "install_runtime", "install_python")
        smoke_failed = (err is not None and step == "smoke")

        if err is not None and not build_failed and not smoke_failed:
            # resolve 阶段失败（repo/profile 缺失）等不可修错误 → halt（设 last_error）
            Logger.warn(
                f"codegen deploy returned unfixable error (step={step}); halting: "
                f"{getattr(err, 'message', '')}")
            return state.with_updates(
                last_error=err,
                generated_sources=agent_result.artifacts,
                codegen_iterations=iterations,
                codegen_consecutive_failures=0,
                codegen_orphan_streak=0,
                decision_logs=decision_logs,
                codegen_manifest=manifest,
                build_result=build_result,
                deploy_result=deploy_result,
            )

        if build_failed:
            retries = state.codegen_build_retries + 1
            limit = self._build_retry_limit()
            # 2026-09-10（advisory 废弃收口）：build 侧机械 stop-loss（镜像 smoke）——
            # 同签名连续重试 ≥K 仍无进展 → 强制 D4（不依赖 coder 声明"该换策略"）。
            # 签名从 err.details.log 的完整日志归一化（复用 smoke 的 _smoke_error_signature
            # 逻辑，语义同：全量错误特征归一化，任一错误变化 → 签名变化 → streak 重置）。
            sig = self._build_error_signature(err)
            if sig and sig == state.codegen_build_last_error_sig:
                build_streak = state.codegen_build_same_error_streak + 1
            else:
                build_streak = 1 if sig else 0
            if build_streak >= _BUILD_ERROR_STOP_LOSS_STREAK:
                Logger.warn(
                    f"codegen build 同一错误签名连续 {build_streak} 次（`{sig[:120]}`）"
                    f"仍无进展 → 机械 stop-loss 强制 D4（不依赖 coder 声明；"
                    f"retry {retries}/{limit}，不 halt）。")
                return state.with_updates(
                    last_error=None,
                    generated_sources=agent_result.artifacts,
                    codegen_iterations=iterations,
                    codegen_consecutive_failures=0,
                    codegen_orphan_streak=0,
                    decision_logs=decision_logs,
                    codegen_manifest=manifest,
                    build_result=BuildResult(passed=False),
                    deploy_result=DeployResult(smoke_passed=False),
                    codegen_build_retries=retries,
                    codegen_build_feedback=None,
                    # 离开 build 循环 → streak 重置（防陈旧累计跨上下文）
                    codegen_build_same_error_streak=0,
                    codegen_build_last_error_sig="",
                    codegen_smoke_same_error_streak=0,
                    codegen_smoke_last_error_sig="",
                )
            if retries >= limit:
                # build-retry 达上限 → D4 逃生：带 smoke_passed=False 交下游，不 halt
                Logger.warn(
                    f"codegen build-retry exhausted ({retries}/{limit}); escaping "
                    f"to D4 — carrying deploy_result(smoke_passed=False) downstream "
                    f"(build still failing after framework-driven retries).")
                return state.with_updates(
                    last_error=None,
                    generated_sources=agent_result.artifacts,
                    codegen_iterations=iterations,
                    codegen_consecutive_failures=0,
                    codegen_orphan_streak=0,
                    decision_logs=decision_logs,
                    codegen_manifest=manifest,
                    build_result=BuildResult(passed=False),
                    deploy_result=DeployResult(smoke_passed=False),
                    codegen_build_retries=retries,
                    codegen_build_feedback=None,
                    # build-retry 是另一重试循环 → smoke streak 重置（防陈旧跨循环）
                    codegen_build_same_error_streak=0,
                    codegen_build_last_error_sig="",
                    codegen_smoke_same_error_streak=0,
                    codegen_smoke_last_error_sig="",
                )
            # 未到上限 → 收集编译错误反馈 → 不写 deploy_result（contract 不满足 →
            # runner 重 spawn）、不设 last_error（不触发 halt）
            feedback = self._collect_build_feedback(state, err)
            Logger.warn(
                f"codegen build failed (step={step}, retry {retries}/{limit}); "
                f"NOT writing deploy_result — runner will re-spawn coder with "
                f"build_feedback (error_class={feedback.get('error_class')}).")
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
                # 留在同一 build 循环 → streak 累计（同签名 +1，换签名已在上文重置为 1）
                codegen_build_same_error_streak=build_streak,
                codegen_build_last_error_sig=sig,
                # build-retry 是另一重试循环 → smoke streak 重置（防陈旧跨循环）
                codegen_smoke_same_error_streak=0,
                codegen_smoke_last_error_sig="",
            )

        # smoke 失败（编译过但不可调用）或全过：写 deploy_result（contract 满足）
        if smoke_failed:
            # Part B（20260810）：smoke 失败按「失败阶段（kernel 是否执行过）」分流。
            #   kernel 执行过（507035/AICORE 等）→ 维持原 D4 交 precision（kernel 运行时/数值缺陷）；
            #   host 阶段（kernel 未执行，EZ1008 tiling/infershape 等）或歧义区 →
            #     单一 _smoke_retry 通路回 codegen（生产者自闭环修自己的 host 脚手架产物，§2.9）。
            #   checkSchema 白名单并入 _smoke_retry 内按「具体优先」选反馈（不保留双轨，§2.5）。
            phase = self._classify_smoke_phase(err)
            if phase != "kernel":
                schema_info = self._classify_smoke_schema_mismatch(err)
                return self._smoke_retry(
                    state, agent_result, manifest, decision_logs, err,
                    iterations, phase=phase, schema_info=schema_info,
                    build_result=build_result)
            Logger.warn(
                "codegen build OK but smoke failed (not callable); NOT halting — "
                "carrying deploy_result(smoke_passed=False) for precision_debug "
                "scope_guard to triage.")
        return state.with_updates(
            last_error=None,
            generated_sources=agent_result.artifacts,
            codegen_iterations=iterations,
            codegen_consecutive_failures=0,
            codegen_orphan_streak=0,
            decision_logs=decision_logs,
            codegen_manifest=manifest,
            build_result=build_result,
            deploy_result=deploy_result,
            codegen_build_retries=0,
            codegen_build_feedback=None,
            # P5：成功/D4 清 sticky 反馈——孤儿反馈、user_feedback 不留到后续
            # 成功轮（否则下轮 context 误带旧失败信号）；last_error 上方已清
            user_feedback="",
            # 成功/D4 离开 smoke 循环 → streak 重置（防陈旧累计）
            codegen_smoke_same_error_streak=0,
            codegen_smoke_last_error_sig="",
        )

    # =====================================================================
    # Membase failure gate（_transition_membase 拆出）：空跑/孤儿/failure 结局
    # =====================================================================

    def _membase_failure_transition(self, state: State, agent_result,
                                    iterations: int) -> State:
        """非 ok+artifacts 结局（空跑/孤儿/failure/infra）统一收口。

        空跑（干净完成 + 零产物，无 Write 证据）与孤儿（有 Write 证据但写到
        op_dir 外）语义相反（§1.10）——孤儿窗口内豁免熔断、超窗消耗熔断。
        构自原 _transition_membase 的尾段（保真拆分，语义零改写）。
        """
        from ascendc_devkit.infra.logger import Logger
        from ascendc_devkit.orchestration.runtime_config import retry_budgets

        is_infra = is_infra_error_type(agent_result.error_type)
        reason = (agent_result.metrics.get("failure_reason", "")
                  if agent_result.metrics else "")
        # 20260820：区分"空跑"vs"孤儿"。两者 backend 视角同为干净完成 + 零产物
        # （status="ok", artifacts={}），但业务语义相反（§1.10）：
        #   - 空跑：transcript 无 Write 证据，模型 0 产出 → 重试无意义 → 熔断（+1）。
        #   - 孤儿：transcript 有 Write 证据但写到 op_dir 外 → 反馈路径后能重试解决 →
        #     窗口内不熔断（不 +1），走迭代预算（1000，修 bug），注入路径反馈让下轮重生成。
        # 判据用"有无 Write 证据"（业务语义：是否产出过），不用 status/artifacts 字面量。
        # F5：干净零产物不再有独立 status——失败分支 error_type 落既有 selffix 类目
        # incomplete_output（可重试语义），不让 "ok" 字面量泄入 error_type。
        # F8（2026-08-21）：孤儿豁免有界化——连续孤儿在 retry_budgets.orphan_exempt_window
        # 内豁免熔断（公平机会，模型有机会改）；超窗后按空跑同样消耗熔断（模型无视
        # 确定性路径反馈 = 零信息产出），最坏 窗口+熔断阈值 发而非烧满迭代上限。
        _budgets = retry_budgets()
        _clean_empty = (agent_result.status == "ok"
                        and not agent_result.artifacts)
        if not is_infra:
            # F7 残留闭合（§1.15）：孤儿判定+反馈文本统一走 orphan_path_feedback
            # 单点（与 perf 共用；证据源 = _shared Write 证据）。此处只接 codegen
            # 私有语义：窗口内豁免熔断、超窗消耗熔断。
            working_dir = state.op_dir or (
                state.op_identity.op_dir if state.op_identity else None)
            orphan_paths, feedback = orphan_path_feedback(
                agent_result, working_dir, "codegen", locator_name="op_dir")
            if orphan_paths:
                _streak = state.codegen_orphan_streak + 1
                _exempt = _streak <= _budgets["orphan_exempt_window"]
                if not _exempt:
                    Logger.warn(
                        f"[codegen] 连续孤儿 {_streak} 次已超豁免窗口 "
                        f"({_budgets['orphan_exempt_window']})——模型持续无视确定性"
                        f"路径反馈，消耗熔断 "
                        f"{state.codegen_consecutive_failures + 1}/"
                        f"{_budgets['consecutive_failures_max']}")
                return state.with_updates(
                    last_error=ErrorFeedback(
                        stage_name="codegen",
                        error_type="artifact_misplaced",
                        message=feedback,
                    ),
                    user_feedback=feedback,
                    codegen_consecutive_failures=(
                        state.codegen_consecutive_failures if _exempt
                        else state.codegen_consecutive_failures + 1),
                    codegen_orphan_streak=_streak,
                    codegen_iterations=iterations,
                )
        return state.with_updates(
            last_error=ErrorFeedback(
                stage_name="codegen",
                error_type=(agent_result.error_type if is_infra
                            else "incomplete_output" if _clean_empty
                            else agent_result.status),
                message=(
                    f"Infrastructure error (bounded retry exhausted): "
                    f"{reason}" if is_infra
                    else (f"Agent {agent_result.agent_name} 干净完成但零产物"
                          f"（transcript 无 Write 证据），未交付代码树"
                          if _clean_empty
                          else f"Agent {agent_result.agent_name} returned "
                               f"status: {agent_result.status}")),
            ),
            codegen_iterations=iterations,
            # 非孤儿结局（空跑/failure）清零孤儿 streak（中断连续孤儿计数）
            codegen_orphan_streak=0,
            codegen_consecutive_failures=(
                state.codegen_consecutive_failures if is_infra
                else state.codegen_consecutive_failures + 1
            ),
        )

    # =========================================================================
    # Regbase transition — 多步编排状态机
    # =========================================================================


    # ------------------------------------------------------------------
    # Phase s2 transition
    # ------------------------------------------------------------------


    # ------------------------------------------------------------------
    # Phase s4 transition
    # ------------------------------------------------------------------

    # s4 步骤中应产出源文件的步骤（不产出源文件的步骤跳过 section 检查）
    _CODE_PRODUCING_STEPS: set[str] = {"4.A", "4.B1", "4.B2", "4.E", "4.F"}


    # ------------------------------------------------------------------
    # Phase s5 transition
    # ------------------------------------------------------------------


    # ------------------------------------------------------------------
    # NEEDS_AGENT 处理
    # ------------------------------------------------------------------


    # ------------------------------------------------------------------
    # Regbase 错误处理（双层保护）
    # ------------------------------------------------------------------


    # =========================================================================
    # Regbase Prompt 构造（从 phase-c-prompts.md 模板翻译为 Python f-string）
    # =========================================================================


