"""L3 Orchestration — State: immutable snapshot of a run."""

from __future__ import annotations

import sys
import types
import typing
from dataclasses import dataclass, field, fields, is_dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Any

from ascendc_devkit.domain.operator import OperatorIdentity, OperatorSpec
from ascendc_devkit.domain.requirement import Requirement, TestCase, UnclearItem
from ascendc_devkit.domain.repository import RepositoryProfile
from ascendc_devkit.domain.verification import BuildResult, PrecisionDebugResult, PerformanceResult, DeployResult, EvalResult, AdaptResult
from ascendc_devkit.orchestration.run_context import RunContext


@dataclass(frozen=True)
class ErrorFeedback:
    stage_name: str
    # Failure class. The authoritative taxonomy + the two halt channels
    # (fail_strategy="halt" → _stage_failed/is_terminal, vs PreconditionError →
    # dispatcher clean-halt) live in
    # docs/plan/chip-gate-precondition/halt-feedback-global-policy.md.
    #   halt-class (don't retry): "infra", "framework", "chip_mismatch",
    #     "env_probe_timeout"
    #   selffix-class (retryable): "schema_violation", "incomplete_output",
    #     "deploy_failed", "missing_artifact", "integration_incomplete"
    #   gray-zone (loops back, bounded by the stage's exhausted→__halt__
    #     stop-loss): "unclassified"
    #   ("design_needs_human" is a TRANSITION_TABLE routing key, NOT an
    #   error_type.)
    error_type: str
    message: str
    details: dict = field(default_factory=dict)


@dataclass(frozen=True)
class State:
    """Immutable snapshot of a run. Each transition returns a new instance."""

    # —— Run metadata ——
    run_id: str = ""
    workflow_name: str = ""
    mode: str = "new"                # "new" | "incremental"
    current_stage: str = ""
    non_interactive: bool = False
    # User-supplied per-stage iteration budget. None = not specified (the runner
    # then applies mode-based defaults: interactive safety net, or each stage's
    # own default_max_iterations). An explicit value is honored verbatim as a
    # hard cap in BOTH interactive and non-interactive modes.
    user_max_iterations: int | None = None
    on_decision: str = "default"     # "default" | "abort"

    # —— Repository & environment ——
    target_repo: Path | None = None
    repo_profile_name: str = ""
    profile: RepositoryProfile | None = None
    adapter: Any = field(default=None, repr=False, compare=False)
    # Resolved from the absolute --op-dir (L1→L2). L3 stages read these only.
    op_dir: Path | None = None          # absolute operator directory
    repo_root: Path | None = None       # absolute repo root (== op_dir's repo)
    rel_op_dir: str = ""                # op_dir relative to repo_root
    full_op_name: str = ""              # op_dir's last segment (prefixed name)
    variant_name: str = ""              # selected build variant
    reference_roots: list[str] = field(default_factory=list)  # default + --reference
    # P13 (step-116)：op 级权威卡号。dispatch 在 op 边界经 resolve_op_card 解析
    # （批=整段租约的卡；单 op CLI/内层 CLI=pin env/npu_id/legacy env 链）后写回
    # 本字段——此后 op 内一切 spawn（serve/harness/deploy/eval/命令前缀）都读它
    # 经 card_pin_env 双变量 pin。None 仅存在于 dispatch 解析之前。
    npu_id: int | None = None
    # step-34: dual chip fields, disjoint authority (they replace the former
    # single chip field that conflated design intent with on-box hardware
    # truth).
    #   design_target_chip — design/compile intent. Authority: CLI
    #     (--design_target_chip) > requirement doc constraint > profile default_chip
    #     > probe-if-known. Drives build (soc_version = to_soc_version(design_target)).
    #   runtime_target_chip — on-box hardware truth. Authority: probe >
    #     --runtime_target_chip (CLI is only a flaky-driver timeout fallback; the
    #     probe wins whenever it can produce a value). The run-gate hardware side;
    #     unrelated to the requirement doc.
    # Both default "" (NOT "A2"): an unresolved chip is honestly empty. The run
    # gate treats empty design as "no constraint" (chip_mismatch_reason → None).
    design_target_chip: str = ""
    runtime_target_chip: str = ""
    # step-34 D3: cross-generation pre-design gate confirmation marker. Set once
    # the user has acknowledged a design≠runtime mismatch this run (either chose
    # cross-generation, or retargeted — both end the need to re-ask). Stops the
    # gate from re-firing on loopback / next iteration within the same run.
    cross_gen_confirmed: bool = False
    # P27: frozen, run-invariant environment context (design-target hw + current
    # hw + runtime sw). Populated once at the context stage; read directly via
    # state.run_context — no per-stage _upstream_inputs declaration (that is the
    # 传递丢失 vector). The hw_params slice is auto-materialized to each design
    # substage's cwd.
    #
    # Single-source relationship (intentional, not transitional):
    # design_target_chip / npu_id are the canonical run-level config (one
    # authoritative value each, reachable everywhere — they never had the
    # 传递丢失 problem). run_context is the DERIVED expansion — built once from
    # design_target_chip (loads hw_params from the chip spec, the single source
    # that cures P24 drift) + probes the env. So: chip truth =
    # design_target_chip; hw_params truth = chip spec via run_context. Mirror
    # fields inside run_context (hardware_target.chip) are derived from
    # design_target_chip at build time, not a second authority.
    run_context: RunContext | None = None
    # Plan-A in-repo safety net: the *target operator repo*'s baseline ref,
    # captured before first repo write so the rollback guard can restore it.
    # Renamed from ``repo_baseline_ref`` to disambiguate from DevKit's OWN git
    # identity (which lives in PROVENANCE.json, not here). git repo → HEAD sha;
    # non-git → "filebackup:<path>"; "" when no repo / skipped.
    target_repo_baseline_ref: str = ""

    # —— Operator identity ——
    op_name: str = ""
    op_spec: OperatorSpec | None = None
    # proto.yaml ``operator.schema`` — plugin 注册 schema + cann-bench eval harness 调用
    # 契约的**共同权威**（54/54 proto.yaml 均声明；codegen m.def 必须服从 type+name+order）。
    # agent 重表达的 op_spec 不可靠（曾畸形：inputs/outputs 全进 attrs），proto.yaml 才是
    # 单一真相源；cannbench_adapt/codegen 自检以 proto_schema 为基准，非 codegen_manifest。
    proto_schema: str | None = None
    # golden 参考计算精度（对齐 cann-bench BenchConfig.golden_precision）：
    #   fp64_cpu（默认）: 升 float64 + CPU 计算（eval 权威标准）
    #   native_cpu       保持原生 dtype + CPU 计算
    # "" = 未指定 → 契约构建处落默认 fp64_cpu（与 eval 一致）。
    golden_precision: str = ""
    # eval seed：与 cann-bench kernel_eval 的 config.eval_seed 对齐（默认 0）。
    # harness 与 eval 必须用同一 eval_seed 生成用例输入，否则两侧输入分裂 →
    # debug 判过而 eval 判挂。0 = 默认（scorer 显式 --eval-seed 0 对齐）。
    eval_seed: int = 0
    op_identity: OperatorIdentity | None = None

    # —— Stage artifacts (per output_contract) ——
    task_request: dict | None = None
    requirement_path: Path | None = None
    # 附加需求材料（--requirement-aux，可重复）：主需求文档之外、随 requirement
    # 分析工作目录一并物化供 agent 阅读的补充需求材料（如同 task 目录的 desc.md）。
    # 不是确定性解析源——schema/精度/tensorlist 仍只读 requirement_path；仅作 agent
    # 的补充阅读输入（§1.13 golden 仍为行为唯一权威）。
    requirement_aux_paths: list[Path] = field(default_factory=list)
    reference_code: dict[str, str] | None = None
    reference_op_path: Path | None = None
    design_doc_path: Path | None = None
    # Precision baseline: golden reference implementation/data (--golden). Flows
    # to verify's precision gate as the authoritative comparison source so the
    # precision check is not left guessing from --reference. Decision-point 9.
    golden_path: Path | None = None
    # golden source moved from profile-preset (P11) to explicit CLI (13 E1/E3):
    # three scalars replace the profile-substituted contract object; verify
    # reads them straight from State. golden_entry = source golden's entry
    # function name (e.g. "exp"); golden_input_type = "torch"|"numpy" ("" =
    # unspecified); cases_path = external cann-bench cases CSV absolute path.
    golden_entry: str = ""
    golden_input_type: str = ""
    cases_path: Path | None = None
    # step-40: upstream test_design marker — the authoritative source of
    # state.test_cases. "cannbench" = a cann-bench cases CSV was loaded (and, in
    # incremental-fusion mode, LLM-designed cases were appended as a supplement);
    # "devkit" = LLM-generated only. Drives EvaluationBackend selection
    # (CannbenchBackend is available only when cases_source == "cannbench").
    # Persisted (a real upstream marker flowing test_design → precision_debug's
    # run_tests → select_backend).
    cases_source: str | None = None
    # Detailed-design short-circuit (--detailed-design): when set, the
    # detailed-design group parses this existing detailed design into the
    # three-piece contract and runs only validate before codegen, skipping
    # template-division → tiling → anchor → integrate → docgen. Decision-point 9.
    detailed_design_path: Path | None = None
    code_source: str | None = None        # "auto" | "manual"

    requirement: Requirement | None = None
    unclear_items: list[UnclearItem] | None = None
    requirement_clarified: bool = False

    # —— Test design (step-4): TDD acceptance cases fixed before codegen ——
    # Authoritative test-case source for verify, produced by the test_design
    # stage's CSV→TestCase adapter. requirement.test_cases is retained only as
    # a fallback (D3). All Optional/default so old snapshots load unchanged.
    test_cases: list[TestCase] | None = None       # normalized TestCase list (authority)
    test_design_report: Path | None = None      # 《算子测试设计方案_设计版.md》 path (trace)
    # test_design substage intermediate products (step-9 L4-a): the test-design
    # group's analyze→casedesign→casegen chain hands these off as files in the
    # shared working dir; mirrored into State for observability + reflow debug.
    test_analysis: dict | None = None           # analyze substage product
    test_casedesign: dict | None = None         # casedesign substage product

    design_spec: dict | None = None
    tiling_strategy: dict | None = None
    kernel_architecture: dict | None = None
    data_flow: dict | None = None

    # —— Design substage intermediate artifacts (step-2b P1) ——
    # Produced by the design subgroups (general-design / detailed-design) and
    # passed between substages via State. All Optional/default so old snapshots
    # load unchanged (R4). See docs/plan/step-2b-design-orchestration-impl.md §2.1
    general_design: dict | None = None            # general-design-generator → division/docgen
    # SIMD/SIMT 编程模型决策（template-select 判定产物，仅 A5 路径产出；
    # A2/A3 平台锁定 SIMD 不产出 → Optional）。general-design-generator 在
    # 模板划分/Tiling 推导前判定，template-division 消费（并入模板条目）。
    template_decision: dict | None = None
    template_division: dict | None = None         # templates list + locked global decisions
    tiling_results: dict | None = None            # {template: {split, buffer_kernel, precision_perf}}
    design_doc: str | None = None                 # P36: path to <op>_详细设计说明书.md (docgen skill output)
    # design_known_issues: carried forward to codegen as known_issues. With the
    # design gates removed it is never populated (stays empty), but codegen's
    # prompt + materialization still read it, so the field is retained as a
    # well-typed, always-empty source.
    design_known_issues: list = field(default_factory=list)

    generated_sources: dict[str, str] | None = None
    change_summary: str | None = None
    codegen_iterations: int = 0
    # Consecutive hard agent failures within codegen (reset on any successful
    # generation). Drives the codegen circuit breaker so a persistently failing
    # coder doesn't spin the stage up to its iteration safety net.
    codegen_consecutive_failures: int = 0
    # F8（2026-08-21）：连续孤儿轮计数（孤儿 = transcript Write 证据在 op_dir 外）。
    # 窗口内（retry_budgets.orphan_exempt_window）豁免熔断；超窗后孤儿轮按空跑同样
    # 消耗熔断（防空烧迭代预算 1000）。任何非孤儿结局（成功/空跑/failure）清零。
    codegen_orphan_streak: int = 0

    # —— Regbase 多步编排状态（仅 A5 Regbase 路径使用；Membase 保持空字符串） ——
    # Phase 状态机: "" | "init" | "s2" | "s4" | "s5" | "done"
    codegen_phase: str = ""
    # RECORD_DIR 绝对路径（staging 子目录下）
    codegen_record_dir: str = ""
    # 当前 s4 子阶段 ID（如 "4.C.3.VT.0"），空字符串表示未开始或已完成
    codegen_s4_sub_stage: str = ""
    # 当前 s4 检查点组
    codegen_s4_checkpoint_group: str = ""
    # 重试计数器（独立于 meta.json，Python 侧管理）
    codegen_retries: dict = field(default_factory=dict)
    # NEEDS_AGENT 暂存：目标 agent 名 + 恢复点
    codegen_pending_agent: str = ""
    codegen_pending_resume_point: str = ""
    # Membase build-retry 循环状态（阶段3：框架驱动 build-retry，方案 Z）。
    # codegen_build_retries: 编译失败重试计数（仅 Membase；编译过但 smoke 失败走 D4 不计数）。
    # codegen_build_feedback: 上轮编译错误反馈（error_class/log_path/error_lines），注入下轮
    # coder prompt。不触发 halt（不是 last_error）；由 runner output_contract 不满足机制驱动重 spawn。
    codegen_build_retries: int = 0
    codegen_build_feedback: dict | None = None
    # 2026-09-10（advisory 废弃收口）：build 侧同签名 stop-loss（镜像 smoke 的
    # codegen_smoke_same_error_streak）。同签名连续重试 ≥K → 机械 D4，不依赖
    # coder 声明——给"build 反复同错无进展"确定性上界。签名变化 → streak 重置。
    codegen_build_same_error_streak: int = 0
    codegen_build_last_error_sig: str = ""
    # smoke-host 机械 stop-loss（Part B）：同错误签名连续重试计数（不依赖 coder 声明"不归我"）。
    # _smoke_error_signature 稳定签名连续 ≥_SMOKE_ERROR_STOP_LOSS_STREAK 次 → 强制 D4 交下游，
    # 给"codegen 误判白耗"一个确定性上界（签名变化 = 根因变了，重置 streak）。
    codegen_smoke_same_error_streak: int = 0
    codegen_smoke_last_error_sig: str = ""
    # Membase artifact-retry 循环状态（manifest/plugin 不完整重试，方案：派生+机械校验+定向 retry）。
    # codegen_artifact_retries: codegen_manifest 非契约（缺 callable_target/inputs/outputs 等，
    #   且 callable_target 无法从 plugin 构造性派生兜底时）的重试计数。
    # codegen_artifact_feedback: 上轮缺失字段反馈（missing_fields/hint），注入下轮 coder prompt。
    # 不触发 halt（不是 last_error）；由 runner output_contract 不满足机制驱动重 spawn。耗尽才 halt。
    codegen_artifact_retries: int = 0
    codegen_artifact_feedback: dict | None = None
    # step-112 (§1.15)：本 stage 最近一次 agent 会话 id——runner 在每次
    # transition 后统一捕获（机械单点，取代 codegen step-100 的 per-stage
    # 回写）。产物不合格反馈重派轮 actions 据此 resume 原会话（保留决策
    # 上下文，修复限于被指认处），不再全新 spawn 重付冷启动；重跑
    # （rerun_reset_fields）清空 = 新会话；空值不清空既有锚点（宁续旧勿丢）。
    last_agent_session_id: str = ""
    # M13（review 整改）：锚点归属——捕获时同记 spawn 所属 stage。锚点是
    # runner 对**所有** stage 统一写的单点字段，消费方（反馈重派 resume）
    # 必须能判定「这是我自己的会话」：stale 反馈 + 期间他 stage spawn 过的
    # 组合下，无归属即 resume 到外来会话注入错位修复提示。
    last_agent_stage: str = ""

    build_result: BuildResult | None = None
    # P54: in-stage precision debug (codegen → precision_debug 直连，无 verify 前置)。
    # agent 闭环迭代产物 + 计数；debug_result 由 agent 写 debug_result.json、
    # transition 解析（文件接力）。halt stage（agent 崩走 P46 _stage_failed）。
    debug_result: PrecisionDebugResult | None = None
    debug_iterations: int = 0

    performance_result: PerformanceResult | None = None
    perf_iterations: int = 0
    perf_needs_redesign: bool = False
    perf_profile_report: dict | None = None

    # —— Deploy & Eval (deploy_result 由 codegen/precision_debug agent 经 Deployer 写；
    #     eval_result 由 CannbenchEvalStage 产。能力下沉后 deploy 不再是 stage) ——
    deploy_result: DeployResult | None = None
    eval_result: EvalResult | None = None

    # —— codegen manifest (step 10): authoritative operator signature adopted by codegen ——
    # Downstream stages (cannbench_adapt, eval) read this instead of design_spec
    # to avoid inconsistencies when codegen adjusts dtypes/defaults.
    codegen_manifest: dict | None = None

    # —— CannbenchAdaptStage (step 11): repo glue-file adaptation result ——
    adapt_result: AdaptResult | None = None

    skip_precision: bool = False
    enable_stubbed: bool = False    # If True, allow stub fallback when CANN/NPU unavailable
    workflow_timeout_sec: int = 0   # 0 = no timeout, seconds for entire workflow
    # step-5b: None = CLI --stage-timeout not given → resolve per-stage from
    # config (timeouts.stages.<name>); explicit int (incl. 0) = CLI override
    # that wins over config. 0 = no timeout.
    stage_timeout_sec: int | None = None
    resume_iteration: int = 0      # 0 = start fresh; >0 = resume from this iteration

    # —— Loop-back / state machine (three-layer routing) ——
    # Level 1 — Corrective loopbacks: same-strategy fixes (verify→codegen, etc.)
    max_corrective: int = 5          # hard cap in non-interactive mode (unlimited in interactive)
    # Level 2 — Strategic escalations: architecture-level rework (→design, →requirement)
    max_escalations: int = 2         # hard cap (both modes)
    # Decision logs: per-stage structured reasoning records for loop-back context
    decision_logs: dict[str, dict] = field(default_factory=dict)  # {"codegen": {...}, "design": {...}}
    # User feedback collected during interactive loop-back, injected into agent prompt
    user_feedback: str = ""

    # —— Scoped routing (graph executor; SOLE loop-back counter/history authority) ——
    routing_scopes: dict = field(default_factory=dict)
    #   {scope_path: {"corrective": int, "escalation": int, "history": list, "last_sig": str}}
    #   History entry: {from, to, type, condition, sig}. Counter/history/quota live
    #   HERE, not in flat corrective_count/escalation_count mirrors (M4: mirrors
    #   deleted — no production reader, write-only 镜像; the graph executor's
    #   ``state.scope(path)`` is the sole authority).
    node_status: dict = field(default_factory=dict)
    #   {node_path: "completed" | "running" | "cancelled"} — graph resume frontier
    _bubble_condition: str = ""   # transient: sub-group escalation bubbled to parent
    _bubble_signature: str = ""   # transient (B1): gate issue signature riding the
                                  # escalation bubble; root-scope stagnation (B2) reads
                                  # it since root's child is the group, not the gate.
    _bubble_origin: str = ""      # transient (P42): node path of the ATOMIC leaf that
                                  # emitted the escalation. The failed-mark is applied
                                  # only where the disposition is known (root __halt__),
                                  # not at the emission point — success/soft-gate
                                  # escalations (passed/exhausted→cannbench_adapt)
                                  # advance linearly and must NOT read as failed.
    _converged_this_pass: bool = False  # transient (P5): set when the substage
                                  # transition's terminal converge (_sync_debug_result)
                                  # already ran this pass. The GE escalation branch
                                  # consumes it to skip a duplicate converge — the
                                  # transition did it (declared semantics, not a
                                  # condition-name proxy); abort/timeout exits that
                                  # skipped the transition converge keep the GE one.
    _stage_failed: Any = None     # transient: (status, stage_name) when fail_strategy=halt triggers
    # design-halt-diagnostics P3: transient — which of the two distinct halt
    # mechanisms fired and why, so the dispatcher's terminal message can name
    # the actual stage/reason instead of a single hardcoded generic text.
    # {"kind": "fail_strategy_halt" | "corrective_exhausted", "stage": str,
    #  "message": str}. Same transient class as _stage_failed — not persisted.
    halt_reason: dict | None = None
    # P6-c: transient loopback feedback dict. Gate stages (anchor-consistency / validate /
    # review) write structured blocking feedback here; the GraphExecutor reads it
    # after resolve_condition and before routing so the target stage sees what
    # specifically failed. Consumed by the target stage on first read (cleared).
    _loopback_feedback: dict | None = None
    # P0 (51-*.md): precision_debug CompositeGroup routing snapshot. transition()
    # extracts the minimal routing field set from checkpoint.json (the sub-agents'
    # file relay) into this transient view; resolve_condition()/loopback_feedback()
    # read it. Same transient class as _loopback_feedback — never persisted: a
    # resume re-derives it from checkpoint.json on the node's next transition.
    _debug_checkpoint: dict | None = None
    # 20260821 F3 全局收口：最近一次 spawn 的 transcript 路径（孤儿产物就地恢复
    # 的证据源——_load_control 用它判定 control.json 是否被写到了
    # debug_artifacts_dir 之外）。transient（resume 后由下一次 transition 重记），
    # 与 _debug_checkpoint 同类：不落盘、不带跨 run 语义。
    _last_agent_transcript: str | None = None
    # P0/D1 (36-*.md §1): forward advisory channel. Non-blocking issues whose
    # owner is a downstream stage (e.g. anchor-consistency AC3 → integrate) are
    # appended here by the graph_executor's advisory branch and consumed by the
    # owner's prompt. One-way forward: no corrective/escalation quota, no
    # invalidate, no backward jump. Persisted (unlike _loopback_feedback) so a
    # resume still delivers an undelivered advisory; cleared by the owner on a
    # successful transition.
    pending_advisories: list = field(default_factory=list)

    integration_result: dict | None = None
    target_files: list[Path] | None = None

    final_build_result: BuildResult | None = None
    dev_record_updated: bool = False

    # —— Error & iteration ——
    last_error: ErrorFeedback | None = None
    stage_iterations: dict[str, int] = field(default_factory=dict)
    is_terminal: bool = False
    # R1 (2026-08-21, 公共 artifact-retry 抽象): agent 型 stage 的"产物契约未满足"
    # （missing_artifact / incomplete_output）独立重试计数——不烧 iteration 预算。
    # runner 在 last_error 命中 stage 且 error_type 属产物契约类别时递增；耗尽后
    # 落回 iteration 语义。与 codegen_artifact_retries 同语义，但后者是 codegen 专属
    # 字段（R1 收敛后 codegen 也应走公共 artifact_retries，§2.5 唯一通路）。
    artifact_retries: int = 0

    # artifact-location-provenance: transcript-harvested evidence that a
    # missing product was actually written outside working_dir. Consumed by
    # _DesignSubstage.actions() (always asks via AskUserQuestion when set —
    # on_decision dispatch, same as any other AskUserQuestion, happens in
    # runner._execute_ask_user_question, not here) and _read_disk_artifacts
    # (decision fallthrough); cleared on every successful parse so it never
    # survives into an unrelated later iteration.

    # P13 (step-116)：原 card_pool（span 级池穿线）与 card_lease（迭代租约号）
    # 字段已随 op 级租约退役（§2.5）——池对象由 batch_runner 直传 dispatch 参数，
    # 不再进 State；卡号权威在 npu_id。
    # —— Workspace (not serialized in JSON snapshot) ——
    _workspace: Any = field(default=None, repr=False, compare=False)

    def with_updates(self, **kwargs) -> State:
        return replace(self, **self._coerce_kwargs(kwargs))

    def with_field(self, field_name: str, value: Any) -> State:
        return replace(self, **self._coerce_kwargs({field_name: value}))

    @classmethod
    def _coerce_kwargs(cls, kwargs: dict) -> dict:
        """Coerce mutation values to their declared field types — the inverse of
        ``to_snapshot``'s ``asdict``. Funneling every mutation
        (``with_field``/``with_updates``) through here is the single chokepoint
        that keeps dict out of State: a JSON/asdict dict is rebuilt to its
        dataclass (profile / requirement / op_identity / build_result / ...)
        before entering, regardless of which caller mutates (§2.9 构造性保证
        优先于检查门 — no per-callsite conversion discipline needed). Already-
        correct values pass through unchanged (``_rebuild_dataclass`` returns
        ``isinstance(v, cls)`` as-is), so this is idempotent and free for the
        common case where callers pass real objects. ``Path``/list[Path] are
        promoted from str the same way ``from_snapshot`` does it.
        """
        hints = _hints_for(cls)
        return {k: _rebuild_value(hints.get(k, Any), v) for k, v in kwargs.items()}

    def with_scope_counters(self, scope_path: str, *, corrective: int,
                            escalation: int, history: list, last_sig: str) -> "State":
        """Write a scope's routing counters (scoped routing is the sole authority)."""
        scopes = dict(self.routing_scopes)
        scopes[scope_path] = {
            "corrective": corrective, "escalation": escalation,
            "history": list(history), "last_sig": last_sig,
        }
        return replace(self, routing_scopes=scopes)

    def scope(self, scope_path: str) -> dict:
        """Return a scope's counters, defaulting to a zeroed dict."""
        return self.routing_scopes.get(
            scope_path,
            {"corrective": 0, "escalation": 0, "history": [], "last_sig": ""})

    def has_all(self, fields: list[str]) -> bool:
        for f in fields:
            if getattr(self, f, None) is None:
                return False
        return True

    def existing_fields(self) -> set[str]:
        """Return names of all non-None fields."""
        result = set()
        for fld in self.__dataclass_fields__:
            if not fld.startswith("_") and getattr(self, fld) is not None:
                result.add(fld)
        return result

    def to_snapshot(self) -> dict:
        """Serialize to plain dict for state_snapshot.json (exclude workspace)."""
        import json
        from dataclasses import asdict, replace
        d = asdict(self)
        d.pop("_workspace", None)
        # Transient per-pass control-flow signals — never persisted. _loopback_feedback
        # is the precedent; is_terminal / _stage_failed / _bubble_condition are the
        # same class (documented transient at L203-204). Letting them leak into the
        # snapshot breaks resume: a halt-terminated run writes is_terminal=True, the
        # next RESUME re-reads it and _execute_sequential breaks before re-running
        # the failed stage (0.0s no-op + re-reported halt). node_status is the sole
        # durable resume authority; these flags only describe the prior pass.
        d.pop("_loopback_feedback", None)
        d.pop("_debug_checkpoint", None)
        d.pop("_last_agent_transcript", None)
        d.pop("is_terminal", None)
        d.pop("_stage_failed", None)
        d.pop("halt_reason", None)
        d.pop("_bubble_condition", None)
        d.pop("_bubble_signature", None)
        d.pop("_bubble_origin", None)
        d.pop("_converged_this_pass", None)
        return d

    @classmethod
    def from_snapshot(cls, data: dict) -> State:
        """Reconstruct from state_snapshot.json."""
        data.pop("_workspace", None)
        # One-shot disk-snapshot rename: repo_baseline_ref → target_repo_baseline_ref
        # (§1.4 — a single field name in code; this migrates the key on load, NOT
        # a long-term compat alias). Old snapshots keep their value under new key.
        if "repo_baseline_ref" in data:
            data.setdefault("target_repo_baseline_ref", data.pop("repo_baseline_ref"))
        # P13 (step-116)：card_pool/card_lease 已退役；盘上旧快照的残余键
        # 直接丢弃（一次性迁移，§1.4 不留别名）。
        data.pop("card_pool", None)
        data.pop("card_lease", None)
        # Transient per-pass control-flow signals — never trusted from disk (see
        # to_snapshot). Strip them so a snapshot written by an older build (which
        # leaked is_terminal=True on halt) loads clean and the resume pass starts
        # fresh. They fall back to their dataclass defaults (False / None / "").
        data.pop("is_terminal", None)
        data.pop("_stage_failed", None)
        data.pop("halt_reason", None)
        data.pop("_bubble_condition", None)
        data.pop("_bubble_signature", None)
        data.pop("_bubble_origin", None)
        data.pop("_converged_this_pass", None)
        # Strip deprecated Slice 9 fields (replaced by corrective/escalation)
        for old in ("loopback_count", "max_loopbacks", "stage_loopbacks"):
            data.pop(old, None)
        # step-34 Step 10: strip retired chip fields from older snapshots (the
        # former single chip field and the declared-chip probe bypass —
        # replaced by the dual design/runtime fields above). Loading-time
        # defense only: an old key is dropped, never resurrected as a field
        # (§1.4 — no compat shim).
        for old in ("target_chip", "assume_chip"):
            data.pop(old, None)
        # Strip retired report-generation flag from older snapshots (the field
        # was removed from State; loading-time defense only — §1.4, no compat
        # shim, an old key is dropped, never resurrected as a field).
        data.pop("report_generated", None)
        # e9ed199e Step 改动2: 删死字段 top-level op_spec(恒 None 的投影,
        # 权威收敛到 requirement.op_spec)。同 chip 字段一样,retired key 必须在
        # 加载期 strip,否则 e9ed199e 之前落盘的快照带 op_spec → cls(**data)
        # TypeError(unexpected kwarg)使 resume 崩。§1.4 只 drop 不 alias。
        data.pop("op_spec", None)
        # 20260821 F3 收口：删字段 pending_relocation（孤儿产物改为就地搬回，
        # 不再跨迭代携带证据）。同 chip/op_spec 语义：retired key 加载期 strip，
        # 旧快照 resume 不崩（§1.4 只 drop 不 alias）。
        data.pop("pending_relocation", None)
        # E(t)/V(t) 机制已移除（重试预算收敛为 per-type 计数器 + 类别升级）：旧快照
        # 带 codegen_et / codegen_vt → 加载期 strip，§1.4 只 drop 不 alias。
        data.pop("codegen_et", None)
        data.pop("codegen_vt", None)
        # M4: 删平面镜像字段 corrective_count/escalation_count/last_error_signature/
        # loopback_history（routing_scopes 是唯一 loop-back 权威，平面只写不读的
        # 镜像；§2.5 不留死通路）。同 retired key 语义：旧快照携带则加载期 drop，
        # 不带则无 —— §1.4 只 drop 不 alias。
        for old in ("corrective_count", "escalation_count",
                    "last_error_signature", "loopback_history"):
            data.pop(old, None)
        # Ensure new fields have defaults
        for new_field, default in [
            ("max_corrective", 5), ("max_escalations", 2),
            ("decision_logs", {}),
            ("routing_scopes", {}),
            ("node_status", {}),
            ("target_repo_baseline_ref", ""),
            ("codegen_consecutive_failures", 0),
            ("codegen_orphan_streak", 0),
            ("op_dir", None),
            ("repo_root", None),
            ("rel_op_dir", ""),
            ("full_op_name", ""),
            ("proto_schema", None),
            ("golden_precision", ""),
            ("eval_seed", 0),
            ("variant_name", ""),
            ("reference_roots", []),
            ("requirement_aux_paths", []),
            # step-2b P1: design substage intermediate fields
            ("general_design", None),
            ("template_decision", None),
            ("template_division", None),
            ("tiling_results", None),
            ("design_doc", None),
            ("golden_path", None),
            ("golden_entry", ""),
            ("golden_input_type", ""),
            ("cases_path", None),
            ("cases_source", None),
            ("detailed_design_path", None),
            # step-4 P1: test_design stage fields
            ("test_cases", None),
            ("test_design_report", None),
            ("test_analysis", None),
            ("test_casedesign", None),
            # self-evolution L4-4: deploy + eval results
            ("deploy_result", None),
            ("eval_result", None),
            # P54: precision debug stage result + iterations
            ("debug_result", None),
            ("debug_iterations", 0),
            # self-evolution step 10/11: codegen_manifest + adapt_result
            ("codegen_manifest", None),
            ("adapt_result", None),
            # step-34 dual chip fields (default empty = unresolved, NOT "A2";
            # redundant with the dataclass defaults but registered here next to
            # the other chip fields so snapshot-compat handling is discoverable)
            ("design_target_chip", ""),
            ("runtime_target_chip", ""),
            ("cross_gen_confirmed", False),
            # P6-c: loopback feedback (transient, not persisted)
            ("_loopback_feedback", None),
            ("pending_advisories", []),
            # P83 (step-58): design-gate escape-hatch known issues
            ("design_known_issues", []),
            # Regbase 多步编排状态（新增字段，旧快照兼容）
            ("codegen_phase", ""),
            ("codegen_record_dir", ""),
            ("codegen_s4_sub_stage", ""),
            ("codegen_s4_checkpoint_group", ""),
            ("codegen_retries", {}),
            ("codegen_pending_agent", ""),
            ("codegen_pending_resume_point", ""),
            ("codegen_build_retries", 0),
            ("codegen_build_feedback", None),
            ("codegen_build_same_error_streak", 0),
            ("codegen_build_last_error_sig", ""),
            ("codegen_smoke_same_error_streak", 0),
            ("codegen_smoke_last_error_sig", ""),
            ("codegen_artifact_retries", 0),
            ("codegen_artifact_feedback", None),
            ("artifact_retries", 0),
        ]:
            if new_field not in data:
                data[new_field] = default
        # Inverse of to_snapshot's asdict: rebuild every field from the dict
        # asdict flattened (and re-promote Path fields demoted to str by the
        # JSON pass). Driven by State's own field annotations, so it covers
        # nested dataclasses (op_identity / requirement / profile / build_result /
        # ...) AND top-level scalar/list Path fields (repo_root / op_dir /
        # target_files / ...) uniformly. An earlier version gated this on
        # ``is_dataclass(annotation)``, which skipped every non-dataclass
        # field — top-level Path fields came back as str (deploy.py's
        # ``repo_root / cwd`` crashed with "unsupported operand type(s) for
        # /: 'str' and 'str'" after resume) and list[Path]/list[dataclass]
        # fields stayed unrebuilt. _rebuild_value already handles scalars,
        # Path, containers, and nested dataclasses uniformly, so no gate is
        # needed — see _rebuild_dataclass for the full rationale.
        for f in fields(cls):
            if f.name not in data:
                continue
            annotation = _hints_for(cls).get(f.name, Any)
            data[f.name] = _rebuild_value(annotation, data[f.name])
        return cls(**data)

    @classmethod
    def empty(cls) -> State:
        return cls()

    @classmethod
    def defaults_for(cls, field_names: list[str]) -> dict:
        """Dataclass defaults for the named State fields (P68 rerun reset).

        Returns a dict suitable for ``with_updates(**...)``. Used by the rerun
        path to reset a re-run stage's outputs/counters to a clean slate. Skips
        unknown names and names without a default (output/counter fields always
        have one); callers may therefore pass ``Stage.rerun_reset_fields()``
        output wholesale without filtering.
        """
        import dataclasses
        flds = {f.name: f for f in dataclasses.fields(cls)}
        out: dict = {}
        for fn in field_names:
            f = flds.get(fn)
            if f is None:
                continue
            if f.default is not dataclasses.MISSING:
                out[fn] = f.default
            elif f.default_factory is not dataclasses.MISSING:  # type: ignore[misc]
                out[fn] = f.default_factory()  # type: ignore[misc]
        return out


# —— Snapshot rebuild: inverse of to_snapshot's dataclasses.asdict ——————————
#
# to_snapshot serializes the whole State tree with asdict, which recursively
# flattens every nested frozen dataclass to a plain dict; the on-disk JSON pass
# (json.dumps(default=str)) additionally demotes Path → str. from_snapshot must
# invert BOTH layers, or the first attribute access after resume raises
# ``'dict' object has no attribute '<field>'`` (historically hit by codegen on
# ``state.op_identity.op_dir``).
#
# The earlier fix rebuilt only run_context by hand — a per-field patch that left
# every other nested dataclass (op_identity / requirement / profile / build_result /
# ...) as a latent resume-only crash. This generic rebuilder walks State's own
# field annotations, so any future dataclass field is covered automatically
# (§1.2 可扩展: 同类新情况自动正确归位, not another special case).


@lru_cache(maxsize=None)
def _hints_for(cls) -> dict:
    """Resolved type hints for a dataclass, cached. ``from __future__ import
    annotations`` makes raw field.type a string; get_type_hints resolves names
    against the class's own module globals."""
    return typing.get_type_hints(cls)


def _strip_optional(annotation):
    """Unwrap ``Optional[X]`` / ``X | None`` → ``X``. A Union with several
    non-None members is returned unchanged (no deterministic single pick)."""
    origin = typing.get_origin(annotation)
    is_union = origin is typing.Union
    if sys.version_info >= (3, 10):
        is_union = is_union or origin is types.UnionType
    if is_union:
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return annotation


def _rebuild_value(annotation, value):
    """Rebuild one value to match its type annotation after an asdict+JSON
    round-trip. Scalars pass through; containers rebuild element-wise; nested
    dataclasses recurse; ``Path`` is promoted back from ``str``. Unknown /
    mismatched shapes pass through unchanged so a malformed snapshot degrades
    to the dict it holds rather than crashing resume."""
    if value is None:
        return None
    annotation = _strip_optional(annotation)
    origin = typing.get_origin(annotation)

    # Sequence containers: asdict turns tuple/set into list; rebuild elements,
    # keep the list shape (frozen dataclasses don't enforce the declared tuple).
    if origin in (list, tuple, set, frozenset):
        args = [a for a in typing.get_args(annotation)
                if a is not Ellipsis and a is not type(None)]
        if not args or not isinstance(value, (list, tuple, set, frozenset)):
            return value
        elem_ann = args[0]
        return [_rebuild_value(elem_ann, v) for v in value]

    # Mapping containers: rebuild values, keep keys as-is.
    if origin is dict:
        args = typing.get_args(annotation)
        if len(args) < 2 or not isinstance(value, dict):
            return value
        val_ann = args[1]
        return {k: _rebuild_value(val_ann, v) for k, v in value.items()}

    # Path field: JSON demoted it to str.
    if annotation is Path:
        return Path(value) if isinstance(value, str) else value

    # Nested dataclass.
    if is_dataclass(annotation):
        return _rebuild_dataclass(annotation, value)

    return value


def _rebuild_dataclass(cls, value):
    """Rebuild a frozen dataclass from the nested dict asdict produced. Pass
    through None / already-correct instances; leave non-dict values untouched
    so an unexpected shape never aborts resume."""
    if value is None or isinstance(value, cls):
        return value
    if not isinstance(value, dict):
        return value
    hints = _hints_for(cls)
    allowed = {f.name for f in fields(cls)}
    kwargs = {}
    for k, v in value.items():
        if k not in allowed:
            continue
        kwargs[k] = _rebuild_value(hints.get(k, Any), v)
    return cls(**kwargs)
