"""L2 Application — Task dispatch: route requests to workflows/stages."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, TYPE_CHECKING

from ascendc_devkit.domain.error import is_infra_error_type
from ascendc_devkit.domain.contract import StageIOContract
from ascendc_devkit.domain.requirement import Requirement
from ascendc_devkit.domain.repository import RepositoryProfile
from ascendc_devkit.infra.workspace import Workspace
from ascendc_devkit.infra.event_log import EventLog
from ascendc_devkit.infra.logger import Logger
from ascendc_devkit.infra.log_capture import bind_run_log, bind_op_name
from ascendc_devkit.orchestration.kernel.state import State
# (op 卡借还原语上移 L3 orchestration/op_card——KNOWN 清零 step-2，dispatcher 不再直连 L6 card_pin)
from ascendc_devkit.orchestration.kernel import event as evt
from ascendc_devkit.orchestration.kernel.runner import Runner, RunnerCancelledError
from ascendc_devkit.domain.exceptions import (
    DecisionPendingError, EnvironmentNotAvailableError,
    WorkflowTimeoutError, StageTimeoutError, PreconditionError,
)
from ascendc_devkit.domain.exit_codes import (
    EX_SIGINT, EX_DECISION_PENDING, EX_CONFIG, EX_TIMEOUT, EX_USAGE,
    EX_DATAERR, EX_TEMPFAIL,
)
from ascendc_devkit.orchestration.skill import list_available_skills
from ascendc_devkit.orchestration.runtime_config import (
    CONFIG_MAX_CORRECTIVE as _CONFIG_MAX_CORRECTIVE,
    CONFIG_MAX_ESCALATIONS as _CONFIG_MAX_ESCALATIONS,
    resume_limits as _resume_limits,
    hw_probe_timeout_sec,
    opencode_timeouts as _opencode_timeouts,
    infra_backoff as _infra_backoff,
    retry_budgets as _retry_budgets,
)

from ascendc_devkit.orchestration.runtime_probe import (
    _resolve_chip_fields, _preflight_runtime)
from ascendc_devkit.orchestration.registry import (
    STAGE_REGISTRY, get_stage, get_workflow,
)
from ascendc_devkit.orchestration.agent_backend_factory import build_agent_backend
from ascendc_devkit.application.report import Report

if TYPE_CHECKING:
    from ascendc_devkit.orchestration.base import StageProtocol


# 9-Stage pipeline stage names (used as fallback, primary source is Workflow registry)
_NEW_PIPELINE = [
    "entry", "context", "requirement", "design", "codegen",
    "verify", "perf", "integrate", "finalize",
]

# —— Preflight: user-provided inputs ——
#
# EntryStage forwards these fields verbatim from task_request into State, so
# Workflow.validate_chain() treats them as "provided by entry" and cannot tell
# whether the user actually supplied them. The runtime preflight below closes
# that gap: it inspects each stage's declared `requires`, intersects with the
# set of user inputs, and enforces presence before any stage runs.
#
# Hard-enforced (block / prompt): requirement_path (when a stage requires it),
#   op_name (incremental mode only — cannot locate existing code without it).
# Soft (warn only): target_repo, repo_profile_name — ContextStage degrades
#   gracefully and design-only workflows may legitimately omit a target repo.
#
# op_dir is the preferred single input (resolves profile/repo_root/op_name):
# when present it satisfies target_repo + repo_profile_name + op_name, so they
# are no longer separately hard-required.
_USER_INPUT_FIELDS = {"requirement_path", "target_repo", "op_name",
                      "repo_profile_name", "op_dir",
                      # golden three params (13 E1/E3): source moved from
                      # profile-preset to explicit CLI. Declared-required via
                      # the consuming stage's `requires` (verify + general-
                      # design, D-1); the bundle (all-or-none) is enforced
                      # separately in _preflight_user_inputs.
                      "golden_path", "golden_entry", "golden_input_type"}
_SOFT_INPUT_FIELDS = {"target_repo", "repo_profile_name", "op_dir"}

_FIELD_HELP = {
    "requirement_path": (
        "需求文档路径（--requirement /path/to/req.md）。"
        "这是新建算子的必填输入：缺少它时，需求分析阶段只能凭算子名臆测，"
        "无法产出可信的需求规格。"
    ),
    "op_name": "算子名称（--op-name YourOperator）。增量模式下用于定位已有代码，必填。",
    "target_repo": "目标仓库路径（--target-repo /path/to/repo）。",
    "repo_profile_name": "仓库 profile 名称（--repo-profile name）。",
    "op_dir": (
        "算子目录的绝对路径（--op-dir /abs/repo/.../op_name）。"
        "一条路径自动解析出仓 profile、仓根、编译变体与算子名。"
    ),
    "golden_path": (
        "golden 参考实现路径（--golden /path/to/golden.py）。golden 是全链路"
        "参考实现（design 依据 + verify 基准），凡做 design 或 verify 的 "
        "workflow 必选；须与 --golden-entry / --golden-input-type 配套提供（13 E3/E4）。"
    ),
    "golden_entry": (
        "golden 入口函数名（--golden-entry exp）。须与 --golden / "
        "--golden-input-type 配套提供。"
    ),
    "golden_input_type": (
        "golden 入口张量类型（--golden-input-type torch|numpy）。须与 --golden / "
        "--golden-entry 配套提供。"
    ),
}


def _input_present(state: State, field_name: str) -> bool:
    """True when a user-input field is meaningfully set.

    State.existing_fields() treats empty strings as present (they are not
    None), so string inputs like op_name/repo_profile_name need a truthiness
    check rather than a None check.
    """
    val = getattr(state, field_name, None)
    if val is None:
        return False
    if isinstance(val, str) and not val.strip():
        return False
    return True


def _prompt_for_missing_inputs(state: State, fields: list[str]) -> tuple[State, list[str]]:
    """Interactively prompt for missing hard-required inputs.

    Returns (updated_state, resolved_field_names). A field is resolved only
    when the user supplies a usable value (and, for paths, the path exists).
    """
    # State field name → task_request key. EntryStage.transition re-reads these
    # from task_request and overwrites State, so values prompted here must also
    # be written back to task_request or entry will clobber them with None.
    _TASK_REQUEST_KEY = {
        "requirement_path": "requirement_path",
        "target_repo": "target_repo",
        "op_name": "op_name",
        "repo_profile_name": "repo_profile",
    }

    resolved: list[str] = []
    updates: dict = {}
    tr_updates: dict = {}
    for field_name in fields:
        Logger.info(f"需要输入 {field_name}：{_FIELD_HELP.get(field_name, '')}")
        try:
            val = input(f"[preflight] 请输入 {field_name}（留空跳过）: ").strip()
        except (EOFError, KeyboardInterrupt):
            val = ""
        if not val:
            continue
        if field_name in ("requirement_path", "target_repo"):
            p = Path(val)
            if not p.exists():
                Logger.warn(f"路径不存在: {p}")
                continue
            updates[field_name] = p
            # task_request stores raw strings (EntryStage wraps them in Path()).
            tr_updates[_TASK_REQUEST_KEY[field_name]] = str(p)
        else:
            updates[field_name] = val
            tr_updates[_TASK_REQUEST_KEY[field_name]] = val
        resolved.append(field_name)
    if updates:
        # Mirror into task_request so EntryStage.transition reads the same value
        # instead of overwriting State with the original (empty) task_request.
        if tr_updates:
            task_request = dict(state.task_request or {})
            task_request.update(tr_updates)
            updates["task_request"] = task_request
        state = state.with_updates(**updates)
    return state, resolved


# —— State 完整性埋点（20260827 临时诊断）——
# 已知概率性缺陷：dispatch 期 State 实例出现「声明字段缺失」（to_snapshot→replace
# AttributeError 'reference_roots'），且 task_request 出现「已证传入的字段读空」
# （0810 gelu / 0827 unique 两例，docs/issue-analysis/
# 20260810-state-to-snapshot-reference-roots-startup-crash.md）。静态穷举证明完整
# __init__ 构造的 frozen dataclass 不可能缺字段——埋点判别三假设：构造即坏 /
# 构造后变异 / 对象被换（比对各点位 id()）。健康时除 always=True 外零输出；
# 机制定位后整段删除。
_STATE_PROBE_FIELDS = (
    "run_id", "non_interactive", "target_repo", "reference_roots",
    "design_target_chip", "op_name", "golden_path", "task_request",
)


def _log_state_integrity(tag: str, state: State, *, always: bool = False) -> None:
    d = getattr(state, "__dict__", None)
    if d is None:
        Logger.error(
            f"[state-integrity] {tag}: id=0x{id(state):x} "
            f"thread={threading.current_thread().name} NO-__dict__ "
            f"type={type(state).__module__}.{type(state).__qualname__}")
        return
    missing = [f for f in _STATE_PROBE_FIELDS if f not in d]
    if missing:
        # step 104 keys 升级：塌缩后字典的键集直接点名「换成了谁的字典」——
        # 若修复后仍复发，此一行即定位弹药（历史病例 fields=2/20 的归属）。
        Logger.error(
            f"[state-integrity] {tag}: id=0x{id(state):x} "
            f"thread={threading.current_thread().name} fields={len(d)} "
            f"missing={missing} keys={sorted(d.keys())} "
            f"type={type(state).__module__}.{type(state).__qualname__}")
    elif always:
        Logger.info(
            f"[state-integrity] {tag}: id=0x{id(state):x} "
            f"thread={threading.current_thread().name} fields={len(d)} ok")


def _preflight_user_inputs(state: State, workflow) -> tuple[State, int | None]:
    """Validate user-provided inputs that static chain validation cannot catch.

    Inspects the `requires` of every stage in *workflow*, intersects with the
    set of user-supplied fields, and enforces presence before any stage runs.

    Returns (state, exit_code). exit_code is None to proceed; otherwise an
    EX_* code the caller should return immediately. Interactive mode prompts
    inline for hard-missing inputs before giving up.
    """
    _log_state_integrity("preflight-enter", state)
    required_by_stages: set[str] = set()
    # Use the flattened leaf view so design-group substages' requires are seen
    # (step-2b §9.2.2); for flat workflows flat_stages() == stages.
    _stages = (workflow.flat_stages(
        design_target_chip=state.design_target_chip)
               if hasattr(workflow, "flat_stages") else workflow.stages)
    for stage in _stages:
        try:
            required_by_stages |= set(stage.input_contract().requires)
        except Exception:
            continue

    candidates = required_by_stages & _USER_INPUT_FIELDS

    hard_missing: list[str] = []
    soft_missing: list[str] = []
    for field_name in sorted(candidates):
        if _input_present(state, field_name):
            continue
        if field_name == "op_name":
            # Locating existing code is impossible without op_name in
            # incremental mode; new mode degrades gracefully.
            target = hard_missing if state.mode == "incremental" else soft_missing
            target.append(field_name)
        elif field_name in _SOFT_INPUT_FIELDS:
            soft_missing.append(field_name)
        else:
            hard_missing.append(field_name)

    for field_name in soft_missing:
        Logger.warn(f"未提供可选输入 {field_name}：{_FIELD_HELP.get(field_name, '')}")

    # 13 E3: golden 三参配套 — 凡消费 golden 的 workflow（某 stage require
    # golden_path），三标量须齐全；部分提供（只 path 缺 entry/input_type，
    # 或反之）→ 缺项并入 hard_missing，不猜测默认值。
    if "golden_path" in candidates:
        for gf in ("golden_path", "golden_entry", "golden_input_type"):
            if not _input_present(state, gf) and gf not in hard_missing:
                hard_missing.append(gf)

    if not hard_missing:
        return state, None

    # Interactive: let the user supply the missing inputs inline.
    if not state.non_interactive:
        state, resolved = _prompt_for_missing_inputs(state, hard_missing)
        hard_missing = [f for f in hard_missing if f not in resolved]
        if not hard_missing:
            return state, None

    Logger.error(
        f"缺少必需的用户输入，无法启动工作流 '{workflow.name}'（mode={state.mode}）：")
    for field_name in hard_missing:
        Logger.error(f"  - {field_name}: {_FIELD_HELP.get(field_name, '')}")
    Logger.error("请通过对应的命令行参数提供后重试。")
    return state, EX_USAGE


def _preflight_input_topology(state: State, workflow) -> int | None:
    """Reject user inputs whose intent contradicts the workflow topology (§9.2.1).

    Some inputs only make sense for workflows containing a specific stage:
      - --detailed-design short-circuits the design groups straight into codegen,
        so a workflow with no codegen stage (e.g. generate_ascendc_se) cannot
        honor it.

    Note (13 E4): golden is no longer verify-exclusive — it is a full-chain
    reference (design 依据 + verify 基准), required declaratively via the
    consuming stage's `requires` (_preflight_user_inputs). The old 'golden
    needs verify' rule is gone; golden flows wherever a stage requires it.

    Returns None to proceed; EX_USAGE when an input is incompatible. Uses the
    flattened leaf view so design-group substages are visible, mirroring
    _preflight_user_inputs.
    """
    _stages = (workflow.flat_stages(
        design_target_chip=state.design_target_chip)
               if hasattr(workflow, "flat_stages") else workflow.stages)
    stage_names = {getattr(s, "name", "") for s in _stages}

    # (input field, required stage, CLI flag, human reason)
    _RULES = [
        ("detailed_design_path", "codegen", "--detailed-design",
         "详设短路需要 codegen 阶段消费解析出的三件套，但该工作流无 codegen"),
    ]

    incompatible: list[str] = []
    for field_name, required_stage, flag, reason in _RULES:
        if _input_present(state, field_name) and required_stage not in stage_names:
            incompatible.append(
                f"  - {flag}：{reason}（workflow='{workflow.name}'）")

    if not incompatible:
        return None

    Logger.error(f"输入与工作流拓扑不兼容，无法启动 '{workflow.name}'：")
    for line in incompatible:
        Logger.error(line)
    Logger.error("请改用包含相应阶段的工作流，或移除该参数后重试。")
    return EX_USAGE


# Stages marking a "from-scratch design" workflow (design generated from
# requirement). detailed_design_path (reuse an existing detailed design) is
# mutually exclusive with these — see _preflight_mode_exclusivity + L1 P1/R1
# (docs/plan/input-mode-exclusivity/).
_FROM_SCRATCH_MARKERS = {"requirement", "general-design-generator"}


def _preflight_mode_exclusivity(state: State, workflow) -> int | None:
    """Reject --detailed-design (reuse) on a from-scratch design workflow (§1.3).

    detailed_design_path 复用一份已存在详设，与"从零设计"（requirement →
    general-design → detailed-design generation）是互斥模式——"先做本算子
    需求/概设、再接一份详设去生成代码"没有合理场景（详设是本算子的 → 重跑
    冗余且可能与旧详设假设矛盾；是别算子的 → 纯语义错配）。二者须分属不同
    workflow（L1 P1/R1）。含"从零设计"标志 stage 的 workflow 带
    --detailed-design 即模式混搭，加载期拒绝，零 agent token 浪费。

    self_evolve_op / generate_ascendc / generate_ascendc_dev 共用 from-scratch
    前置，均命中；纯 codegen 复用入口（无 from-scratch stage）放行（合法 reuse）。

    Returns None to proceed; EX_USAGE when the two modes are mutually exclusive.
    """
    if not _input_present(state, "detailed_design_path"):
        return None
    _stages = (workflow.flat_stages(
        design_target_chip=state.design_target_chip)
               if hasattr(workflow, "flat_stages") else workflow.stages)
    stage_names = {getattr(s, "name", "") for s in _stages}
    hit = _FROM_SCRATCH_MARKERS & stage_names
    if not hit:
        return None  # 无从零设计前置（纯 codegen 复用入口），合法 reuse
    Logger.error(f"输入模式与工作流互斥，无法启动 '{workflow.name}'：")
    Logger.error(
        f"  - --detailed-design（复用详设）与从零设计阶段 {sorted(hit)} 互斥："
        f"先做需求分析/概设、再接一份详设去生成代码没有合理场景。")
    Logger.error(
        "  去掉 --detailed-design 走从需求生成，或改用不含从零设计阶段的复用入口。")
    return EX_USAGE


def _preflight_deploy_capability(state: State, workflow) -> int | None:
    """Fail fast when a deploy-bearing workflow targets a repo whose profile
    declares no deploy roles (D8: deploy is mandatory; no stub, no skip).

    P57 能力下沉: deploy is no longer a dedicated stage — it runs in-session via
    codegen's Deployer redeploy (build → install → smoke). So a workflow is
    deploy-bearing iff it has a ``codegen`` stage (codegen owns the redeploy,
    which needs install_runtime + smoke role stages on the target profile).
    When the profile is resolvable at dispatch (via --repo-profile) and
    rel_op_dir is known, an incapable repo is rejected now with actionable
    guidance rather than letting codegen's redeploy fail at runtime. When the
    profile cannot yet be resolved (it is resolved later in ContextStage), this
    defers to codegen's in-session Deployer redeploy, which re-checks capability
    at runtime (fails → codegen self-fixes in-session).

    Returns None to proceed; EX_USAGE when the target repo cannot deploy.
    """
    _stages = (workflow.flat_stages(
        design_target_chip=state.design_target_chip)
               if hasattr(workflow, "flat_stages") else workflow.stages)
    stage_names = {getattr(s, "name", "") for s in _stages}
    if "codegen" not in stage_names:
        return None

    profile = None
    if state.repo_profile_name:
        try:
            from ascendc_devkit.orchestration.profile_loader import load_profile
            profile = load_profile(state.repo_profile_name)
        except Exception:
            profile = None
    rel_op_dir = state.rel_op_dir or ""
    # Defer to the runtime deploy-capability check (codegen's in-session
    # Deployer redeploy) when we cannot resolve the profile or the variant at
    # dispatch (both are finalized in ContextStage).
    if profile is None or not rel_op_dir:
        return None

    if profile.has_deploy_capability(rel_op_dir):
        return None

    Logger.error(
        f"目标仓 profile '{profile.name}' 未声明 deploy 能力"
        f"（缺 install_runtime + smoke role stage），无法运行需要 deploy 能力的 "
        f"workflow '{workflow.name}'（codegen 在会话内经 Deployer redeploy）。")
    Logger.error(
        "deploy 是必备步骤（不跳过、不打桩）。请在该仓 profile 的 build_variant.stages "
        "中补齐 install_runtime / install_python / smoke role，再重试。")
    return EX_USAGE


# P113: runtime 预检进程内缓存 + Lock 串行化。batch resume 用 ThreadPoolExecutor
# (runtime preflight 迁至 orchestration/runtime_probe.py，2026-09-03 KNOWN 清零 step-1)


def dispatch(task_request: dict, progress_callback: Callable | None = None,
             card_pool=None) -> int:
    """Run a full workflow. Returns exit code.

    Args:
        task_request: Pipeline configuration dict.
        progress_callback: Optional callback(event_type, stage_name, metadata)
            for real-time progress reporting. Called synchronously at stage
            lifecycle transitions.
        card_pool: Optional shared ``NPUSlotManager`` (batch mode). ``None``
            (single-op CLI / inner CLI subprocess) → the op card resolves from
            the inherited pin env / ``npu_id`` / legacy env with no lease.
            Batch callers pass the shared pool: the op takes ONE exclusive
            lease for its whole lifetime (op-level pinning, P13/step-116 —
            the former per-span leases left the agent subtree invisibly
            outside the ledger) and every op subprocess (serve/CLI agent
            subtrees, harness, deploy, eval) carries the two-variable pin
            ``ASCEND_RT_VISIBLE_DEVICES=<card>`` + ``ASCEND_NPU_ID=0``.
    """
    # step 104：主进程纯 Python 守卫——dispatch 是 batch/resume/单算子三条
    # 编排路径的漏斗之一（另两个：dispatch_single_stage / dispatch_single_skill
    # ——stage/skill 回放 CLI 同为主进程编排入口，M4 整改后三处齐装；CLI L1
    # 不得 import L7，分层检查界定守卫归属编排层）。违反不变式（进程内
    # import torch/torch_npu → 原生堆损坏，F1/F3）在此刻响亮失败而非概率性
    # 崩溃（§1.3）。幂等；批内 N 个 dispatch 线程重复安装为 no-op；子进程
    # （探测/smoke/run-cases）是全新解释器，不受影响。
    from ascendc_devkit.infra.import_guard import install_purity_guard
    install_purity_guard()
    Logger.info(
        f"[state-integrity] dispatch-enter: tr id=0x{id(task_request):x} "
        f"keys={sorted(task_request, key=str)} "
        f"thread={threading.current_thread().name}")
    mode = task_request.get("mode", "new")
    output_root = task_request.get("output_root", "output")
    # step-34 D8: chip_decision event payload, captured on a new run and
    # emitted once the runner (which owns _event_log) is built. None on resume.
    chip_resolution: tuple | None = None
    resume_from = task_request.get("resume_from")
    resume_iter = task_request.get("resume_iteration", 0)
    workflow_name = task_request.get("workflow") or "generate_ascendc"

    # P68: --rerun-from re-runs a completed stage (and its downstream) FRESH.
    # It targets an existing run, so it requires --resume. (rerun ≠ resume: a
    # rerun discards the prior agent session and spawns fresh — for iterative
    # stage optimization validation. See _apply_rerun.)
    rerun_from = task_request.get("rerun_from")
    if rerun_from and not resume_from:
        Logger.error("--rerun-from 需要 --resume <run_id>（rerun 针对一个已存在的 run）")
        return EX_USAGE

    if resume_from:
        # Resume from a previous run
        state = _load_state_from_run(resume_from, output_root)
        workspace = Workspace.from_existing(resume_from, output_root)
        # 控制台日志 tee 到 <run>/run.log(append):resume 与首次 run 共用同一文件,
        # run 目录自包含;auto 按 run_id 命名,用户零操作(详见 infra/log_capture)。
        bind_run_log(workspace.dir / "run.log")
        # AU-7: op_name 归属绑定,供 opencode 后端的 agent_stream 行 attribution
        # 用(batch 并发下多个 op 共享同一 stage_name 时区分来源)。state 已在上面
        # _load_state_from_run 加载,op_name 取 state(resume 权威源)。
        bind_op_name(state.op_name)
        # workflow_name 是 run 身份的一部分,resume 须以 state 为唯一权威(与
        # node_status 同源——state 是 resume sole authority)。CLI --workflow 无
        # 默认值(default=None),故 task_request["workflow"] 为 None 即「用户未传」
        # → 跳过一致性检查,沿用 state.workflow_name;仅当 resume 时显式传入且与
        # state 不符,加载期报错(§1.3)而非静默跑错图——否则 workflow 图节点名前缀
        # (如 self_evolve_op/* vs generate_ascendc/*)会与 state.node_status 错配,
        # 全部被判未完成、从头重跑。
        cli_workflow = task_request.get("workflow")
        if cli_workflow and cli_workflow != state.workflow_name:
            Logger.error(
                f"--workflow '{cli_workflow}' 与 run '{resume_from}' 的 workflow "
                f"'{state.workflow_name}' 不一致。resume 必须沿用原 run 的 workflow,"
                f"请去掉 --workflow 参数后重试。")
            return EX_USAGE
        workflow_name = state.workflow_name or workflow_name
        # Bug A(P30 推广到 non_interactive/on_decision/enable_stubbed):三键 CLI
        # default=None 后,None=未传 → 沿用 state;非 None=CLI 显式覆盖。布尔必须用
        # is not None(不能用 or——False 是合法显式值,`False or state` 会错用 state)。
        state = state.with_updates(
            run_id=resume_from,
            non_interactive=(task_request.get("non_interactive")
                             if task_request.get("non_interactive") is not None
                             else state.non_interactive),
            user_max_iterations=task_request.get("max_iterations", state.user_max_iterations),
            max_corrective=(task_request.get("max_corrective")
                            if task_request.get("max_corrective") is not None
                            else state.max_corrective),
            max_escalations=(task_request.get("max_escalations")
                             if task_request.get("max_escalations") is not None
                             else state.max_escalations),
            # P23: resume 允许覆盖 timeout(第一次预算给小、第二次放宽)。workflow CLI
            # 默认 0(=disabled)→ or(0 视为未传、沿用旧 state);stage CLI 默认 None →
            # is not None(None=未传、沿用),显式 0(=disabled)也能覆盖。
            workflow_timeout_sec=(task_request.get("workflow_timeout_sec")
                                  or state.workflow_timeout_sec),
            stage_timeout_sec=(task_request.get("stage_timeout_sec")
                               if task_request.get("stage_timeout_sec") is not None
                               else state.stage_timeout_sec),
            on_decision=(task_request.get("on_decision")
                         if task_request.get("on_decision") is not None
                         else state.on_decision),
            enable_stubbed=(task_request.get("enable_stubbed")
                            if task_request.get("enable_stubbed") is not None
                            else state.enable_stubbed),
            # npu_id: None=未传 → 沿用 state；int=CLI 显式覆盖（硬 pin 到该卡）。
            # 之前 resume 缺此覆盖，--npu-id 被静默忽略，原 device 不可用（如
            # 上下文池耗尽）时无法换卡续跑。
            npu_id=(task_request.get("npu_id")
                    if task_request.get("npu_id") is not None
                    else state.npu_id),
            # P40: workspace 是 transient(to/from_snapshot 都 pop),resume 须挂回,
            # 否则 _DesignSubstage._working_dir(state) 返 None → agent cwd 退化到
            # artifacts 根、产物写错位置、_parse_single 读不到 → 契约死循环。
            # new-run 分支构造 State 时已传 _workspace,resume 分支对齐(同 P31 模式)。
            # P50: resume = fresh attempt — reset the codegen circuit breaker
            # (a stale trip from a prior process must not strand the run) and
            # clear any infra-typed last_error (else codegen.actions()'s infra
            # guard halts instantly, defeating the resume). See _resume_breaker_reset.
            **_resume_breaker_reset(state),
            _workspace=workspace,
            task_request=task_request,
        )
        # Determine remaining work from node_status, the sole resume authority
        # (step-2b B). The executor marks the root path (== workflow.name)
        # completed only when the whole tree finishes; a completed leaf set that
        # still leaves the root unmarked means there is pending work. Using
        # node_status (not stage_iterations) avoids the integrate name-collision
        # and sees group-internal fine-grained completion.
        workflow = get_workflow(workflow_name)
        # P68: apply user-triggered rerun BEFORE the all_done / pending
        # computation so it can un-complete a previously-finished run. Resolves
        # the target (bare name or full path), then invalidates it + downstream,
        # deletes session sidecars (fresh spawn), and resets gate counters.
        if rerun_from:
            target = _resolve_rerun_target(workflow, rerun_from,
                                           state.design_target_chip or "")
            if target is None:
                Logger.error(
                    f"--rerun-from '{rerun_from}' 无法在 workflow "
                    f"'{workflow_name}' 中唯一定位节点（重名或不存在）。"
                    f"可用的 node 路径见 state_snapshot.json 的 node_status 键。")
                return EX_USAGE
            state = _apply_rerun(state, workflow, target, workspace)
        ns = state.node_status or {}
        # node_status is the sole resume authority. A halt-terminated run has its
        # halt leaf (and via _group_status, the root) marked "failed", never
        # "completed", so this guard correctly falls through to the re-run branch.
        # is_terminal is a transient per-pass signal and is stripped at the snapshot
        # boundary (state.py to/from_snapshot) — it never reaches here, so it is NOT
        # a resume authority and is intentionally absent from this check.
        all_done = ns.get(workflow.name) == "completed"
        if all_done:
            Logger.info("All stages already completed, regenerating report")
            try:
                report = Report.generate(workspace)
                report.write_markdown(workspace.report_path)
                report.write_json(workspace.report_json_path)
            except Exception as e:
                Logger.error(f"Report regeneration failed: {e}")
            return 0
        completed_nodes = sorted(k for k, v in ns.items() if v == "completed")
        _next = _first_pending_leaf(workflow, ns)
        Logger.info(f"Resuming run '{resume_from}'"
                     + (f" from '{_next}'" if _next else "")
                     + f" (completed nodes: {completed_nodes})")
    else:
        # New run. run_id: caller may pre-assign (batch_runner pre-generates an
        # execution_id so output/<batch_id>/<exec>/ lands in one step — see
        # batch_runner); absent → Workspace.create generates via new_run_id().
        # Single-op run.py never sets it → behavior unchanged.
        workspace = Workspace.create(
            output_root=output_root, run_id=task_request.get("run_id"))
        # 控制台日志 tee 到 <run>/run.log:run 目录自包含,auto 按 run_id 命名,
        # 用户零操作、shell 无需 temp 名+grep+mv(详见 infra/log_capture)。
        bind_run_log(workspace.dir / "run.log")
        # AU-7: op_name 归属绑定,与下面 L~672 State(op_name=...) 同源
        # task_request.get("op_name", "")——state 此时尚未构造。
        bind_op_name(task_request.get("op_name", ""))
        def _cli_path(v):
            # 用户 CLI 路径字段在入口边界锚定为绝对路径：state 把它们序列化进
            # snapshot，下游（resume、独立 CLI 子进程 run-cases/redeploy、harness
            # 子进程）各自 cwd 不同——相对路径只在初始进程可解析，跨进程即断
            # （实证：golden 相对路径在 run-cases cwd=operator_dir 下 FileNotFoundError，
            # harness 加载 golden 前死亡）。入口 resolve 一次，下游 cwd 无关。
            # 覆盖全部 CLI 路径字段（含 op_dir/repo_root）——新增路径字段一并走这里，
            # 不留裸 Path() 构造的例外（§1.15 单点抽象）。
            return Path(v).resolve() if v else None

        target_repo = _cli_path(task_request.get("target_repo"))
        req_path = _cli_path(task_request.get("requirement_path"))
        design_doc = _cli_path(task_request.get("design_doc_path"))
        golden = _cli_path(task_request.get("golden_path"))
        golden_entry = task_request.get("golden_entry") or ""
        golden_input_type = task_request.get("golden_input_type") or ""
        cases_path = _cli_path(task_request.get("cases_path"))
        detailed_dd = _cli_path(task_request.get("detailed_design_path"))
        op_dir = _cli_path(task_request.get("op_dir"))
        repo_root = _cli_path(task_request.get("repo_root"))

        # Resolve the dual chip fields (step-34): runtime_target_chip from the
        # bounded probe (CLI --runtime_target_chip only as a timeout fallback),
        # design_target_chip from CLI (req/profile layers applied downstream).
        # A probe timeout with no CLI fallback → None → clean dispatch-time halt
        # (EX_DATAERR). --assume-chip no longer feeds the target (the leakage
        # that made the gate a tautology); it is retired in Step 4/10.
        resolved = _resolve_chip_fields(task_request, hw_probe_timeout_sec())
        if resolved is None:
            Logger.error(
                "无法确定本机硬件代际：NPU 探机超时（疑似 hdcdrv 死等）且未声明 "
                "--runtime_target_chip。请重启/修复驱动后重试，或用 "
                "--runtime_target_chip 显式声明硬件代际后放行。")
            return EX_DATAERR
        design_chip, runtime_chip, design_source, runtime_source = resolved
        # P81 (step-58): runtime 兜底 when CLI didn't pass --design_target_chip.
        # Agent-produced constraint is NOT a chip source; without this fallback
        # the requirement stage had no default and agent 照搬 schema example A5
        # 污染 (run 20260717-070202-53f685). Authority: CLI > doc field > runtime.
        if not design_chip:
            design_chip = runtime_chip
            design_source = "runtime_default"
        # step-34 D8: capture for the chip_decision event, emitted after the
        # runner (which owns _event_log) is built below. Resume runs skip this —
        # their chip fields are already recorded from the original new run.
        chip_resolution = (design_chip, runtime_chip,
                           design_source, runtime_source)

        state = State(
            run_id=workspace.run_id,
            mode=mode,
            workflow_name=workflow_name,
            op_name=task_request.get("op_name", ""),
            target_repo=target_repo,
            repo_profile_name=task_request.get("repo_profile", ""),
            op_dir=op_dir,
            repo_root=repo_root,
            rel_op_dir=task_request.get("rel_op_dir", ""),
            full_op_name=task_request.get("full_op_name", ""),
            variant_name=task_request.get("variant_name", ""),
            reference_roots=list(task_request.get("references", []) or []),
            design_target_chip=design_chip,
            runtime_target_chip=runtime_chip,
            requirement_path=req_path,
            design_doc_path=design_doc,
            golden_path=golden,
            golden_entry=golden_entry,
            golden_input_type=golden_input_type,
            cases_path=cases_path,
            detailed_design_path=detailed_dd,
            npu_id=task_request.get("npu_id"),
            non_interactive=(task_request.get("non_interactive") or False),
            user_max_iterations=task_request.get("max_iterations", None),
            max_corrective=(task_request.get("max_corrective")
                            if task_request.get("max_corrective") is not None
                            else _CONFIG_MAX_CORRECTIVE),
            max_escalations=(task_request.get("max_escalations")
                             if task_request.get("max_escalations") is not None
                             else _CONFIG_MAX_ESCALATIONS),
            on_decision=(task_request.get("on_decision") or "default"),
            enable_stubbed=(task_request.get("enable_stubbed") or False),
            workflow_timeout_sec=task_request.get("workflow_timeout_sec", 0),
            stage_timeout_sec=task_request.get("stage_timeout_sec", None),
            resume_iteration=task_request.get("resume_iteration", 0),
            task_request=task_request,
            _workspace=workspace,
        )
        _log_state_integrity("constructed", state, always=True)

        # Load workflow for static IO chain validation
        workflow = get_workflow(workflow_name)
        chain_errors = workflow.validate_chain()
        if chain_errors:
            for err in chain_errors:
                Logger.info(f"Workflow IO chain: {err}")
        # Load-time fail-fast: a spawn stage whose agent_name has no agent.md
        # would silently run on a placeholder prompt (P1). Abort startup rather
        # than burn agent time on a context-free spawn.
        agent_errors = workflow.validate_agents()
        # §P4 consistency guard: every design substage's assigned skill must
        # resolve to a real skill on disk, else its /<skill> slash trigger
        # expands to nothing and the agent runs skill-dead again.
        from ascendc_devkit.orchestration.skill_config import (
            validate_skill_map,
        )
        skill_errors = validate_skill_map()
        startup_errors = agent_errors + skill_errors
        if startup_errors:
            for err in startup_errors:
                Logger.error(f"Workflow agent issue: {err}")
            _write_state_snapshot(workspace, state)
            return EX_CONFIG
        pending_stages = list(workflow.stages)

        # Preflight: validate user-provided inputs that static chain validation
        # cannot catch. EntryStage forwards these from task_request, so
        # validate_chain() sees them as "provided" even when the user supplied
        # nothing. Only fresh runs need this — resumed runs already carry them.
        state, preflight_code = _preflight_user_inputs(state, workflow)
        if preflight_code is not None:
            _write_state_snapshot(workspace, state)
            return preflight_code

        # Preflight: reject inputs whose intent contradicts the topology
        # (--detailed-design without codegen / --golden without verify, §9.2.1).
        topology_code = _preflight_input_topology(state, workflow)
        if topology_code is not None:
            _write_state_snapshot(workspace, state)
            return topology_code

        # Preflight: --detailed-design (reuse) is mutually exclusive with a
        # from-scratch design workflow (L1 P1/R1) — reject at load time.
        mode_code = _preflight_mode_exclusivity(state, workflow)
        if mode_code is not None:
            _write_state_snapshot(workspace, state)
            return mode_code

        # Preflight: a deploy-bearing workflow needs a deploy-capable target
        # repo profile (D8 — deploy is mandatory; no stub/skip). Resolvable at
        # dispatch → fail now; otherwise the codegen/precision_debug agents'
        # in-session Deployer redeploy enforces it at runtime.
        deploy_cap_code = _preflight_deploy_capability(state, workflow)
        if deploy_cap_code is not None:
            _write_state_snapshot(workspace, state)
            return deploy_cap_code

    # Write initial state snapshot
    _write_state_snapshot(workspace, state)

    # Preflight: verify CANN toolchain AND NPU runtime are present before
    # spawning any agent.  A verify-bearing workflow without either is
    # guaranteed to fail at verify, so bail out now rather than after ~7000s.
    runtime_code = _preflight_runtime(state, workflow)
    if runtime_code is not None:
        return runtime_code

    # step-108 撞名 WARN（信息级，不拦跑）：本任务算子名撞系统 OPP vendors 内
    # 实体时开跑即留痕——批 20260829 的兄弟覆盖事后 2h 取证变日志一行。
    from ascendc_devkit.infra.env_contract import warn_system_vendor_collisions
    warn_system_vendor_collisions([state.op_name])

    # Validate skill availability at pipeline startup
    available_skills = list_available_skills()
    Logger.info(f"Skill service: {len(available_skills)} skills available")

    webhook_url = task_request.get("webhook_url")

    # Resolve build-artifact ignore globs from the profile so in-repo product
    # collection (sdk_backend) excludes .o/.so/build/ from the change set (R3).
    artifacts_ignore: list[str] = []
    if state.repo_profile_name:
        try:
            from ascendc_devkit.orchestration.profile_loader import load_profile
            _prof = load_profile(state.repo_profile_name)
            artifacts_ignore = list(getattr(_prof, "artifacts_ignore", []) or [])
        except Exception:
            artifacts_ignore = []

    # P13 (step-116)：op 级租约——借/还紧邻（§step-95 对称性：acquire 之后
    # 的一切封装进 _dispatch_leased，本 try/finally 是唯一释放点，函数体内
    # 任何 return/异常路径都必然穿过它——未来修改不可能在借还之间插入
    # 逃逸路径）。借/还原语上移 L3 orchestration/op_card（KNOWN 清零 step-2），
    # dispatcher 不再直连 L6 card_pin。
    from ascendc_devkit.orchestration.op_card import (
        acquire_op_card, release_op_card, OpCardLeaseError)
    try:
        _card, state, _op_release = acquire_op_card(
            state.npu_id, card_pool, state,
            owner=f"op:{state.op_name}/{workspace.run_id}")
    except OpCardLeaseError as e:
        # preferred card held by a sibling op — task config reserved one card
        # twice; out-of-range / not-in-allowed-set is the same task-config
        # error class (slot raises ValueError there). Both fail the op loudly
        # as EX_CONFIG. Nothing is held yet (resolve raised before
        # assignment), no release needed.
        Logger.error(f"NPU op card lease failed: {e}")
        return EX_CONFIG
    Logger.info(
        f"NPU op card lease: card={_card} op={state.op_name} "
        f"run={workspace.run_id}")
    try:
        return _dispatch_leased(
            state, workspace, workflow, card_pool, _card, chip_resolution,
            resume_from, output_root, progress_callback, webhook_url,
            artifacts_ignore)
    finally:
        release_op_card(_op_release)

def _dispatch_leased(state, workspace, workflow, card_pool, op_card,
                     chip_resolution, resume_from, output_root,
                     progress_callback, webhook_url, artifacts_ignore) -> int:
    """P13 (step-116)：op 租约持期内的一切——探针→backend→executor→主循环。

    借/还在调用方 ``dispatch`` 紧邻成对（§step-95 对称性）：本函数体内任何
    return/异常路径都必然穿过调用方唯一的 finally 释放；探针失败在本函数
    入口转为干净的 EX_CONFIG。其余语义与原 dispatch 内联实现逐行一致。
    """
    if card_pool is not None:
        # verify_lease (batch mode only: a pool means a real run) fails the
        # op fast when the pin plumbing is broken, before hours of
        # silently-wrong-card work. 迁 L3 op_card（KNOWN 清零 step-2）。
        from ascendc_devkit.orchestration.op_card import verify_lease
        try:
            verify_lease(op_card)
        except EnvironmentNotAvailableError as e:
            Logger.error(f"NPU card pin verify failed: {e}")
            return EX_CONFIG


    # Initialize backend via the factory (opencode|claude per env/config),
    # fallback to stub on construction failure.
    backend = build_agent_backend(
        interactive=not state.non_interactive,
        working_dir=workspace.artifacts,
        on_decision=state.on_decision,
        decision_workspace=workspace.dir,
        webhook_url=webhook_url,
        enable_stubbed=state.enable_stubbed,
        artifacts_ignore=artifacts_ignore,
        card_pin=state.npu_id,
        resume_max_retries=_resume_limits()["max_retries"],
        resume_max_no_progress=_resume_limits()["max_no_progress"],
        rate_limit_max_retries=_resume_limits()["rate_limit_max_retries"],
        rate_limit_backoff_base_s=_resume_limits()["rate_limit_backoff_base_s"],
        rate_limit_backoff_factor=_resume_limits()["rate_limit_backoff_factor"],
        rate_limit_backoff_max_total_s=_resume_limits()["rate_limit_backoff_max_total_s"],
        turn_stall_s=_opencode_timeouts()["turn_stall_s"],
        gateway_error_probe_s=_opencode_timeouts()["gateway_error_probe_s"],
        tool_grace_s=_opencode_timeouts()["tool_grace_s"],
        message_timeout=_opencode_timeouts()["message_timeout_s"],
        resume_attempts=_infra_backoff()["resume_attempts"],
        thinking_active_gap_s=_retry_budgets()["thinking_active_gap_s"],
        fallback_to_stub=True,
    )

    runner = Runner(agent_backend=backend, workspace=workspace,
                    progress_callback=progress_callback)

    # step-67: write immutable PROVENANCE.json + emit run_started as the FIRST
    # run-level event (before stage_enter). Makes a foreign run self-describing
    # — commit / dirty / backend / env / runtime config / danger warnings — so a
    # reviewer stops guessing whether the reporter ran an old or dirty version,
    # or hit a silent truncation. events.jsonl is authoritative; PROVENANCE.json
    # mirrors. Best-effort: never blocks a run.
    try:
        from pathlib import Path as _Path
        from ascendc_devkit.orchestration.agent_backend_factory import resolve_backend_kind as _rbk
        from ascendc_devkit.infra import provenance as _prov
        _devkit_root = _Path(__file__).resolve().parents[3]
        if resume_from:
            # bug1 (step-68): a resume must NOT overwrite the first run's
            # immutable PROVENANCE.json — it is the authoritative version
            # identity of THIS run_id. Instead re-probe FRESH (run_context=None,
            # so a CANN/torch_npu upgrade or a swapped baseline is captured
            # rather than re-recording the first run's stale snapshot), diff
            # against the first PROVENANCE, and emit run_resumed so the change
            # is visible in events.jsonl. The first run's run_started stays the
            # single opener; the resume appends run_resumed (EventLog is
            # append-only).
            _resume_prov = _prov.build_provenance(
                run_id=workspace.run_id, repo_root=_devkit_root,
                agent_backend=_rbk(),
                target_repo_baseline_ref=getattr(state, "target_repo_baseline_ref", ""),
                run_context=None)
            _first_path = workspace.dir / "PROVENANCE.json"
            _first_dict = None
            try:
                if _first_path.is_file():
                    import json as _json
                    _first_dict = _json.loads(_first_path.read_text(encoding="utf-8"))
            except Exception as _fe:  # noqa: BLE001
                Logger.warn(f"could not read first PROVENANCE for resume diff: {_fe}")
            _changes = (_prov.diff_provenance(_first_dict, _resume_prov.to_dict())
                        if _first_dict else {})
            if runner._event_log is not None:
                runner._event_log.append(evt.run_resumed(
                    run_id=workspace.run_id, provenance=_resume_prov.to_dict(),
                    resumed_from=resume_from, changes=_changes))
                for _w in _resume_prov.warnings:
                    runner._event_log.append(
                        evt.env_warning(stage_name="dispatch", reason=_w))
        else:
            # First run: write the immutable PROVENANCE.json + emit run_started
            # as the FIRST run-level event (self-describing foreign runs).
            _prov_obj = _prov.build_provenance(
                run_id=workspace.run_id, repo_root=_devkit_root,
                agent_backend=_rbk(),
                target_repo_baseline_ref=getattr(state, "target_repo_baseline_ref", ""),
                run_context=getattr(state, "run_context", None))
            _prov.write_provenance(workspace.dir, _prov_obj)
            if runner._event_log is not None:
                runner._event_log.append(
                    evt.run_started(workspace.run_id, _prov_obj.to_dict()))
                for _w in _prov_obj.warnings:
                    runner._event_log.append(
                        evt.env_warning(stage_name="dispatch", reason=_w))
    except Exception as _e:  # noqa: BLE001
        Logger.warn(f"provenance capture failed: {_e}")

    # P13 (step-116): the op→card mapping as a run-level event (after
    # run_started, the opener). events.jsonl is the authoritative record for
    # post-batch collision audits — op_card_leased is its single write point.
    if runner._event_log is not None:
        runner._event_log.append(evt.op_card_leased(
            op_name=state.op_name, card=op_card, run_id=workspace.run_id))

    # step-34 D8: record how the chip targets were resolved for this new run
    # (sources + design/runtime mismatch) into events.jsonl. Stages can't emit
    # this — they hold no _event_log; dispatch is the single write point. The
    # pre-design gate's pause already rides the existing decision_pending event;
    # a design≠runtime mismatch here is the earliest observable signal of the
    # cross-generation situation the gate will surface.
    if chip_resolution is not None and runner._event_log is not None:
        _d, _r, _ds, _rs = chip_resolution
        runner._event_log.append(evt.chip_decision(
            design_chip=_d, design_source=_ds,
            runtime_chip=_r, runtime_source=_rs,
            mismatch=bool(_d) and _d != _r))

    from ascendc_devkit.orchestration.graph_executor import GraphExecutor

    # Inject current adapter into runner for Integrate actions.
    if state.adapter is not None:
        runner._adapters["repository"] = state.adapter

    # Resume bridge: mark already-completed top-level stages so the executor
    # skips them. Old snapshots track completion via stage_iterations.
    if resume_from:
        state = state.with_updates(
            node_status=_resume_node_status(state, workflow))

    executor = GraphExecutor(
        runner=runner,
        event_log=runner._event_log,
        progress_callback=progress_callback,
        on_state_progress=lambda s: _write_state_snapshot(workspace, s),
    )

    run_start = time.monotonic()
    # S4 (hard-timeout): SIGTERM → KeyboardInterrupt so it reuses the SIGINT
    # graceful-exit path (runner.cancel + save state + EX_SIGINT) instead of the
    # default hard-terminate. Registered only on the main thread; restored after.
    _sigterm_prev = None
    _sigterm_registered = False
    try:
        _sigterm_prev = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGTERM, _sigterm_to_keyboard_interrupt)
        _sigterm_registered = True
    except (ValueError, OSError):
        pass  # not main thread / signals unsupported in this context
    # D8 (hard-timeout): report on every terminal exit (finally-block below).
    # A paused run (DecisionPendingError) regenerates the report on resume, so
    # it's excluded — and _generate_report sweeps skills anchors at its tail,
    # which must not run mid-pause (the run continues).
    _report_on_exit = True

    try:
        root = workflow.root(
            design_target_chip=state.design_target_chip)
        state = executor.execute(root, state)
        _write_state_snapshot(workspace, state)
    except RunnerCancelledError as e:
        Logger.warn(f"Cancelled: {e}")
        state = _terminate_preserving(executor, workspace, state)
        return EX_SIGINT
    except DecisionPendingError as e:
        Logger.warn(f"Decision pending: {e.question}")
        Logger.info(f"Run 'ascendc-devkit respond --run {workspace.run_id}"
                    f" --choice <N>' to provide an answer,"
                    f" then 'ascendc-devkit run --resume {workspace.run_id}' to continue.")
        _report_on_exit = False  # pause, not terminal — resume regenerates report
        state = _terminate_preserving(executor, workspace, state)
        return EX_DECISION_PENDING
    except (WorkflowTimeoutError, StageTimeoutError) as e:
        # step-107 (P1): timeout = budget exhausted = "not finished", not a
        # code defect — same pause family as cancel/env/card (which already
        # preserve with exactly that rationale). This branch persists the
        # state snapshot FOR resume; destroying the tree here handed resume a
        # coder session whose memory diverged from an empty op_dir (batch
        # 20260829-142941-49134b: conforming manifests + full sources on disk
        # at kill time, lost to checkout+clean). Whether to continue is the
        # operator's call — resume decides; the preserve hint keeps the manual
        # rollback command available.
        Logger.error(f"Timeout: {e}")
        state = _terminate_preserving(executor, workspace, state)
        _print_resume_hint(workspace, output_root)
        return EX_TIMEOUT
    except PreconditionError as e:
        Logger.error(
            f"Stage '{e.stage_name}' aborted: {e.reason}")
        Logger.error(
            "Halting workflow — a required upstream artifact is missing, so "
            "downstream stages cannot run. Fix the root-cause stage above and re-run.")
        state = executor.latest_state or state
        _rollback_repo_if_needed(state)
        _write_state_snapshot(workspace, state)
        return EX_DATAERR
    except EnvironmentNotAvailableError as e:
        Logger.error(f"Environment not available: {e}")
        # A missing external prerequisite (CANN/NPU) is not a code defect, so the
        # generated operator code should be kept for inspection/reuse rather than
        # discarded. _preserve_repo_with_hint also prints the manual rollback
        # command (git_safety-friendly). With F2's preflight this rarely triggers
        # for verify, but perf.py can still raise it later in the run.
        state = _terminate_preserving(executor, workspace, state)
        return EX_CONFIG
    except KeyboardInterrupt:
        runner.cancel()
        Logger.warn("KeyboardInterrupt received, saving workspace state...")
        state = _terminate_preserving(executor, workspace, state)
        _print_resume_hint(workspace, output_root)
        return EX_SIGINT
    finally:
        # S4: restore the prior SIGTERM handler.
        if _sigterm_registered:
            try:
                signal.signal(signal.SIGTERM, _sigterm_prev)
            except (ValueError, OSError):
                pass
        # D8 (hard-timeout): single report-generation site covering EVERY
        # terminal exit — normal completion, timeout, precondition/env/card
        # failures, cancel, SIGINT/SIGTERM. Previously only PreconditionError +
        # normal completion reported; the timeout path (the hard-timeout
        # scenario) had NO report. _generate_report is best-effort (swallows its
        # own errors), so this never masks the workflow's exit code. Skipped on a
        # DecisionPendingError pause (run resumes and regenerates).
        if _report_on_exit:
            _generate_report(
                workspace,
                run_elapsed_ms=int((time.monotonic() - run_start) * 1000))

    # Terminal halt: the workflow stopped without completing. Two distinct
    # GraphExecutor mechanisms set is_terminal=True — a hard fail_strategy=halt
    # stop, or a corrective/escalation-budget exhaustion (__halt__) — and they
    # call for different operator guidance. halt_reason (design-halt-diagnostics
    # P3) disambiguates; the generic text below is a defensive fallback only
    # (both trigger points are expected to always set it).
    if getattr(state, "is_terminal", False):
        for line in _terminal_message_for(state):
            Logger.error(line)
        return EX_DATAERR
    # §P7.1: a stage that failed with a swallowed exception marks its node (and,
    # by propagation, the workflow root) "failed". Do not return success in that
    # case — the run did not deliver, even though execution advanced linearly.
    failed_nodes = [k for k, v in (state.node_status or {}).items() if v == "failed"]
    if failed_nodes:
        Logger.error(
            "Workflow completed with failed stages: "
            f"{sorted(failed_nodes)}. Review the agent transcripts / logs for "
            "the cause; the output is incomplete or unreliable.")
        return EX_DATAERR
    return 0


def _terminal_message_for(state: State) -> list[str]:
    """Assemble the terminal-halt operator guidance lines (one per Logger.error).

    Extracted from dispatch() so the halt text is a testable pure function
    (§2.5 single point). halt_reason (design-halt-diagnostics P3) names which
    of the two GraphExecutor halt mechanisms fired; the generic fallback text
    is defensive only (both trigger points are expected to always set it).
    step-96 D1: corrective-exhausted halts append the precision quality state
    (``_debug_quality_line``) so "why it failed" is visible at the terminal.
    """
    halt_reason = getattr(state, "halt_reason", None) or {}
    kind = halt_reason.get("kind")
    stage = halt_reason.get("stage", "?")
    if kind == "fail_strategy_halt":
        msg = halt_reason.get("message", "")
        return [(
            f"Workflow halted: stage '{stage}' failed with fail_strategy=halt"
            + (f": {msg}" if msg else ".") +
            " Review the stage's error above, fix the root cause, and "
            "re-run.")]
    if kind == "corrective_exhausted":
        msg = halt_reason.get("message", "")
        detail = f" ({msg})" if msg else ""
        # The quality facts otherwise die in debug_result.json.
        q = _debug_quality_line(state)
        return [(
            f"Workflow halted: stage '{stage}' "
            "exhausted its correction budget on an unresolved "
            f"build/precision failure{detail}. This is most likely an "
            "implementation bug the coder could not fix automatically — "
            "review the latest verify output and agent transcripts, then "
            "re-run (adjust the design manually only if the root cause "
            "is the design)."
            + (f"\n{q}" if q else ""))]
    if kind == "upstream_defect":
        # P3 (precision-tensorlist-harness-contract): an upstream halt must
        # NOT be framed as "coder implementation bug" — the failure is owned
        # by an upstream stage (test_design/requirement/golden/deploy). Covers
        # both __escalate__:upstream and __halt__ upstream halts.
        msg = halt_reason.get("message", "")
        return [(
            f"Workflow halted: stage '{stage}' "
            f"refused to proceed on an upstream defect{(': ' + msg) if msg else '.'} "
            "The failure is owned by an upstream stage (test_design/"
            "requirement/golden/deploy), not the coder — fix the upstream "
            "product, then re-run.")]
    _q = _debug_quality_line(state)
    return [(
        "Workflow halted: a stage exhausted its correction budget on an "
        "unresolved build/precision failure. This is most likely an "
        "implementation bug the coder could not fix automatically — review "
        "the latest verify output and agent transcripts, then re-run "
        "(adjust the design manually only if the root cause is the design)."
        + (f"\n{_q}" if _q else ""))]


def _debug_quality_line(state: State) -> str:
    """Render ``debug_result``'s quality state for the terminal halt message.

    step-96 D1: ``best_quality`` lets "why it failed" be visible (bad 0/20 =
    no usable kernel produced ≠ partial 12/20); ``max_diff`` is always 0 for
    crash-class failures and carries no information. The quality state flows
    with the product (debug_result.json); this is its terminal consumer —
    a corrective_exhausted halt appends it so the field is never write-only
    (§2.10). Empty string when debug_result is absent or passed.
    """
    dr = state.debug_result
    if dr is None or dr.passed:
        return ""
    quality = getattr(dr, "best_quality", "") or ""
    if quality in ("bad", "partial"):
        best = getattr(dr, "best_passed_count", -1)
        failed_n = len(getattr(dr, "failing_cases", []) or [])
        label = ("precision 未产出可用 kernel（零正证据）" if quality == "bad"
                 else "precision 部分通过（有正证据）")
        return (f"Precision best={best} passed, failing={failed_n} "
                f"(quality={quality} — {label}); "
                f"max_diff={getattr(dr, 'max_diff', 'N/A')}")
    return f"Precision max_diff={getattr(dr, 'max_diff', 'N/A')}"


def _sigterm_to_keyboard_interrupt(signum, frame):
    """S4 (hard-timeout): SIGTERM handler that makes a SIGTERM behave exactly
    like Ctrl+C (SIGINT) — raise KeyboardInterrupt. dispatch() registers this
    around the run so SIGTERM hits the existing ``except KeyboardInterrupt``
    path (runner.cancel + save state + EX_SIGINT) instead of the default
    hard-terminate (no state save, no child cleanup)."""
    raise KeyboardInterrupt


def _generate_report(workspace, run_elapsed_ms: int = 0) -> None:
    """Render the run report (markdown + json) from the event log.

    ``run_elapsed_ms`` is the dispatcher wall-clock covering the entire run,
    including aborted stages whose stage_complete events were never emitted.
    When >0 it overrides the events.jsonl accumulation.

    Best-effort: a reporting failure must not mask the workflow's own exit
    code, so any error here is logged and swallowed.
    """
    try:
        report = Report.generate(workspace, run_elapsed_ms=run_elapsed_ms)
        report.write_markdown(workspace.report_path)
        report.write_json(Path(str(workspace.report_path).replace(".md", ".json")))
        # step-67: write MANIFEST.json (per-file sha256) for pack-run/verify-run
        # integrity checks. Best-effort: never masks the workflow exit code.
        try:
            from ascendc_devkit.infra import run_manifest as _rm
            _rm.build_manifest(
                workspace.dir,
                provenance_summary=report.provenance_summary,
                provenance_warnings=list(report.provenance_warnings))
        except Exception as _me:  # noqa: BLE001
            Logger.warn(f"manifest build failed: {_me}")
        # Sweep framework-planted .claude/skills anchors (see
        # Workspace.remove_skills_anchors) so a caller archiving this run dir
        # with a symlink-dereferencing tool (e.g. `zip -r`) doesn't inflate the
        # archive by re-expanding the repo's skill tree once per stage cwd.
        try:
            removed = workspace.remove_skills_anchors()
            if removed:
                Logger.info(f"removed {removed} skills anchor symlink(s) "
                            "from run dir")
        except Exception as _ae:  # noqa: BLE001
            Logger.warn(f"skills anchor cleanup failed: {_ae}")
        Logger.stage_done("workflow", report.total_elapsed_ms)
    except Exception as e:
        Logger.error(f"Report generation failed: {e}")


def _repo_guard_for(state) -> "object | None":
    """Build a RepoGuard matching how ContextStage created the baseline.

    Returns None when there is nothing to guard (no baseline / no op_identity).
    """
    if not getattr(state, "target_repo_baseline_ref", "") or state.op_identity is None:
        return None
    from ascendc_devkit.infra.repo_guard import RepoGuard
    backup_root = None
    if state._workspace is not None:
        backup_root = state._workspace.dir / "repo_backup"
    ignore_globs = []
    if state.profile is not None:
        ignore_globs = list(getattr(state.profile, "artifacts_ignore", []) or [])
    return RepoGuard(backup_root=backup_root, ignore_globs=ignore_globs)


def _rollback_repo_if_needed(state) -> None:
    """Hard-failure path (D4): restore op_dir to the pre-run baseline.

    No-op when no baseline was captured. Blast radius == op_dir (RepoGuard
    enforces checkout+clean scoped to op_dir, never reset --hard on the repo).
    """
    guard = _repo_guard_for(state)
    if guard is None:
        return
    op = state.op_identity
    ok = guard.rollback(op.repo_root, op.op_dir, state.target_repo_baseline_ref)
    if ok:
        Logger.info(f"已恢复算子目录到运行前状态: {op.op_dir}")
    else:
        Logger.warn(
            f"算子目录回滚未完成，请手动检查: "
            f"git checkout {state.target_repo_baseline_ref[:12]} -- {op.op_dir}"
        )


def _preserve_repo_with_hint(state) -> None:
    """Abort path (D4): keep in-repo changes, print how to roll back manually.

    Active user interruption (Ctrl-C / cancel / decision-pending) must NOT
    trigger a destructive auto-restore (git_safety). We only surface the
    baseline ref so the user can roll back themselves or --resume.
    """
    ref = getattr(state, "target_repo_baseline_ref", "")
    if not ref or state.op_identity is None:
        return
    op = state.op_identity
    if ref.startswith("filebackup:"):
        Logger.info(
            f"算子目录改动已保留 ({op.op_dir})。如需回滚，从备份恢复: "
            f"{ref[len('filebackup:'):]}"
        )
    else:
        Logger.info(
            f"算子目录改动已保留 ({op.op_dir})。如需手动回滚: "
            f"git checkout {ref[:12]} -- {op.op_dir} "
            f"&& git clean -fd {op.op_dir}"
        )


def _terminate_preserving(executor, workspace, state) -> State:
    """§1.15 pause-family single point (step-107): shared closing steps for
    every not-a-code-defect termination — latest-state fallback, keep the
    in-repo changes (with manual-rollback hint), atomically persist the resume
    snapshot. Each except branch keeps only its own deltas (log / flag /
    exit code); this triple must not be re-scattered per branch.
    ``executor=None`` for the single-stage rerun path (no GraphExecutor — the
    entry state is the latest persisted truth there; M4-era convergence)."""
    latest = (getattr(executor, "latest_state", None)
              if executor is not None else None)
    state = latest or state
    _preserve_repo_with_hint(state)
    _write_state_snapshot(workspace, state)
    return state


def _print_resume_hint(workspace, output_root: str = "output") -> None:
    """Surface the run_id and the exact command to resume after an interrupt.

    Called from the KeyboardInterrupt path so the user is never left guessing
    how to pick the run back up. When the interrupt landed on an unanswered
    decision prompt, we first point them at `respond` (the resume cannot
    proceed past a pending question without an answer).
    """
    run_id = workspace.run_id
    pending_path = Path(output_root) / run_id / "pending_decision.json"
    response_path = Path(output_root) / run_id / "decision_response.json"
    has_unanswered_decision = (
        pending_path.exists() and not response_path.exists()
    )

    Logger.info(f"已保存运行状态，Session ID（run ID）: {run_id}")
    if has_unanswered_decision:
        Logger.info(
            "运行在一个未作答的决策点被中断。请先作答，再恢复运行:"
        )
        Logger.info(
            f"  1) ascendc-devkit respond --run {run_id} --choice <N>"
            f"  (或 --text <自由文本>)"
        )
        Logger.info(
            f"  2) ascendc-devkit run --resume {run_id}"
        )
    else:
        Logger.info(
            f"如需从中断处继续，执行: ascendc-devkit run --resume {run_id}"
        )


def dispatch_single_stage(stage_name: str, state_file: Path | None = None,
                          from_run_id: str | None = None,
                          sources_dir: Path | None = None,
                          requirement_file: Path | None = None,
                          npu_id: int | None = None,
                          non_interactive: bool = False,
                          max_iterations: int | None = None,
                          enable_stubbed: bool = False,
                          output_root: str = "output") -> int:
    """Run a single Stage independently. Returns exit code."""
    # M4: same main-process purity funnel as dispatch() — the stage-rerun CLI
    # is an orchestration entry too (idempotent install).
    from ascendc_devkit.infra.import_guard import install_purity_guard
    install_purity_guard()

    stage_cls = get_stage(stage_name)
    stage = stage_cls()

    # Workspace 先于 state 构建。--from-run 复用原 run（与主 dispatch resume 分支
    # 同构——单 stage + from-run 即「从某 run 恢复、只跑一个 stage」），且
    # from_existing 自带存在性校验：run 不存在时前置报错（EX_USAGE），不让
    # _load_state_from_run 的 warn+empty 把「run 不存在」掩盖成下游「缺字段」
    # （§3.7 诚实报错、可诊断）。否则新建。这步必须早于 _build_state_for_stage，
    # 否则 run 不存在时 _load 会先打误导性 warn。
    if from_run_id:
        try:
            workspace = Workspace.from_existing(from_run_id, output_root)
            bind_run_log(workspace.dir / "run.log")
        except FileNotFoundError as e:
            Logger.error(f"--from-run 指定的 run 不存在: {e}")
            Logger.info(f"可用 run 见 {Path(output_root).resolve()} 目录，"
                        f"--from-run 传 run_id（output/ 下的目录名）。")
            return EX_USAGE
    else:
        workspace = Workspace.create(output_root=output_root)
        bind_run_log(workspace.dir / "run.log")

    # Build state from available sources（from-run 时 run 已被 from_existing 确认存在，
    # _load_state_from_run 不会 warn）。
    state = _build_state_for_stage(
        stage_name=stage_name,
        state_file=state_file,
        from_run_id=from_run_id,
        sources_dir=sources_dir,
        requirement_file=requirement_file,
        npu_id=npu_id,
        non_interactive=non_interactive,
        max_iterations=max_iterations,
        enable_stubbed=enable_stubbed,
        output_root=output_root,
    )

    # Validate IO contract
    contract = stage.input_contract()
    missing = contract.validate(state.existing_fields())
    if missing:
        Logger.error(f"Stage '{stage_name}' requires these fields but they are missing:")
        for field in missing:
            Logger.error(f"  - {field}")
        Logger.error(f"Available fields: {sorted(state.existing_fields())}")
        Logger.error("Set these fields via --state FILE, --from-run ID, or other CLI flags.")
        return 64

    # 注入 _workspace（stage 不变式）：requirement/context/precision_debug 等 stage
    # 经 state._workspace 取 run 目录（写 prompt、定位 artifacts、context stage 建
    # repo_backup 等）。workspace 是 transient（to/from_snapshot 都 pop），单 stage
    # 路径此前只挂 run_id 未挂 _workspace → 依赖它的 stage 单跑即崩（如
    # precision_debug 子 stage 的 _common_context 取 run 目录写进 prompt 给 agent 调
    # redeploy/run-cases --workspace，取到 None 时 prompt 写死字面量 <run_dir>）。
    # 与主 dispatch new-run/resume 两分支一致（均挂回 _workspace，P40/P31 同模式）。
    state = state.with_updates(run_id=workspace.run_id, _workspace=workspace)

    # Write initial state snapshot
    _write_state_snapshot(workspace, state)

    # P13 (step-116): single-stage rerun runs outside the batch pool — resolve
    # the op card from the inherited pin env / npu_id (no lease; developer-
    # driven, single op at a time by convention) and pin the backend subtree.
    # 统一走 L3 op_card.acquire_op_card（KNOWN 清零 step-2）。
    from ascendc_devkit.orchestration.op_card import acquire_op_card
    _stage_card, state, _ = acquire_op_card(
        state.npu_id, None, state, owner=f"stage:{stage_name}")

    # Run with the configured agent backend, agent writes to workspace artifacts dir
    backend = build_agent_backend(
        interactive=not non_interactive,
        working_dir=workspace.artifacts,
        on_decision="default",
        decision_workspace=workspace.dir,
        enable_stubbed=enable_stubbed,
        card_pin=state.npu_id,
        resume_max_retries=_resume_limits()["max_retries"],
        resume_max_no_progress=_resume_limits()["max_no_progress"],
        rate_limit_max_retries=_resume_limits()["rate_limit_max_retries"],
        rate_limit_backoff_base_s=_resume_limits()["rate_limit_backoff_base_s"],
        rate_limit_backoff_factor=_resume_limits()["rate_limit_backoff_factor"],
        rate_limit_backoff_max_total_s=_resume_limits()["rate_limit_backoff_max_total_s"],
        turn_stall_s=_opencode_timeouts()["turn_stall_s"],
        gateway_error_probe_s=_opencode_timeouts()["gateway_error_probe_s"],
        tool_grace_s=_opencode_timeouts()["tool_grace_s"],
        message_timeout=_opencode_timeouts()["message_timeout_s"],
        resume_attempts=_infra_backoff()["resume_attempts"],
        thinking_active_gap_s=_retry_budgets()["thinking_active_gap_s"],
        fallback_to_stub=True,
    )
    runner = Runner(agent_backend=backend, workspace=workspace)
    Logger.stage_header(stage_name, 1, 1)

    try:
        final_state = runner.run_stage(state, stage)
        _write_state_snapshot(workspace, final_state)
        return 0
    except RunnerCancelledError as e:
        Logger.warn(f"Stage '{stage_name}' cancelled: {e}")
        state = _terminate_preserving(None, workspace, state)
        return EX_SIGINT
    except DecisionPendingError as e:
        Logger.warn(f"Decision pending: {e.question}")
        Logger.info(f"Run 'ascendc-devkit respond --run {workspace.run_id}"
                     f" --choice <N>' to provide an answer.")
        state = _terminate_preserving(None, workspace, state)
        return EX_DECISION_PENDING
    except KeyboardInterrupt:
        runner.cancel()
        Logger.warn("KeyboardInterrupt received, saving workspace state...")
        state = _terminate_preserving(None, workspace, state)
        _print_resume_hint(workspace, output_root)
        return EX_SIGINT
    except EnvironmentNotAvailableError as e:
        Logger.error(f"Environment not available: {e}")
        # same pause family as dispatch(): keep the repo for inspection,
        # persist the resume snapshot (previously this branch wrote neither).
        state = _terminate_preserving(None, workspace, state)
        return EX_CONFIG
    except Exception as e:
        Logger.error(f"Stage '{stage_name}' failed: {e}")
        return 1


def _build_state_for_stage(stage_name: str, state_file: Path | None,
                           from_run_id: str | None,
                           sources_dir: Path | None,
                           requirement_file: Path | None,
                           npu_id: int | None,
                           non_interactive: bool,
                           max_iterations: int,
                           enable_stubbed: bool,
                           output_root: str) -> State:
    """Three-layer merge: from_run → state_file → CLI flags."""

    # Layer 1: from_run_id
    if from_run_id:
        state = _load_state_from_run(from_run_id, output_root)
    else:
        state = State.empty()

    # Layer 1.5: design-artifact re-injection (data-flow (c), §P1 task 5.3).
    # When --sources points at a run's artifacts dir containing design/, rebuild
    # the design State fields from the materialized products so a single design
    # stage can be debugged by editing a product file on disk. Sits above
    # state_file (an explicit state snapshot still wins) and below CLI flags.
    if sources_dir and (Path(sources_dir) / "design").is_dir():
        from ascendc_devkit.orchestration.design_artifacts import (
            design_artifacts_to_state,
        )
        for k, v in design_artifacts_to_state(sources_dir).items():
            if v is not None and hasattr(state, k):
                state = state.with_field(k, v)

    # Layer 2: state_file
    if state_file:
        data = json.loads(state_file.read_text())
        for k, v in data.items():
            if v is not None and hasattr(state, k):
                state = state.with_field(k, v)

    # Layer 3: CLI flags (highest priority)
    if sources_dir:
        sources = _read_sources_dir(sources_dir)
        state = state.with_field("generated_sources", sources)
    if requirement_file:
        req = Requirement.from_file(requirement_file)
        state = state.with_field("requirement", req)
    if npu_id is not None:
        state = state.with_field("npu_id", npu_id)

    state = state.with_updates(
        current_stage=stage_name,
        non_interactive=non_interactive,
        user_max_iterations=max_iterations,
        enable_stubbed=enable_stubbed,
    )

    return state


def _read_sources_dir(dir_path: Path) -> dict[str, str]:
    sources = {}
    for f in dir_path.rglob("*"):
        if f.suffix in (".cpp", ".h", ".hpp", ".py"):
            sources[str(f.relative_to(dir_path))] = f.read_text()
    return sources


def _load_state_from_run(run_id: str, output_root: str) -> State:
    path = Path(output_root) / run_id / "state_snapshot.json"
    if not path.exists():
        Logger.warn(f"No state snapshot found at {path}, starting with empty state")
        return State.empty()
    data = json.loads(path.read_text())
    return State.from_snapshot(data)


def _resume_breaker_reset(state: State) -> dict:
    """P50: state.with_updates overrides applied on every resume so a manual
    resume can re-enter the codegen stage.

    Resume is no longer a blind fresh attempt: codegen.actions() first looks for
    a session sidecar left by an interrupted spawn (graceful crash OR hard kill
    — the backend flushes it at session_id capture) and, if present, issues a
    resume spawn that reuses the crashed session's reasoning memory. The backend
    degrades to a fresh spawn internally if that session expired. The overrides
    below are what make that resume attempt reachable:

    - ``codegen_consecutive_failures=0``: the circuit breaker's job is to stop
      within-run spinning on a coder that genuinely can't fix the bug. A manual
      resume (env/config/design may have changed since — e.g. the gateway
      channel was just provisioned) must not inherit a stale trip from a prior
      process. Within a run the breaker still trips normally.
    - clear ``last_error`` when it is infra-typed: codegen.actions() halts
      pre-spawn on an infra last_error, so leaving it would make the resume
      trip instantly and defeat the reset above (the sidecar read runs AFTER
      this guard). A logic-typed last_error is kept — it is useful retry context
      for the next agent run.

    The resume sidecar itself is NOT State — it lives at
    ``<run>/agents/<agent>.session.json`` and is managed entirely by the backend
    (written at capture, deleted on clean finish), so this reset never touches
    it. Returns a dict suitable for ``state.with_updates(**...)``; keys are
    omitted when no override is needed (so unrelated fields are untouched).
    """
    out: dict = {"codegen_consecutive_failures": 0}
    le = state.last_error
    if le is not None and is_infra_error_type(le.error_type):
        out["last_error"] = None
    return out


def dispatch_single_skill(skill_name: str, prompt: str = "",
                          output_root: str = "output",
                          non_interactive: bool = False) -> int:
    """Run a single skill independently. Returns exit code.

    Creates a workspace, spawns the configured agent backend with the specified
    skill, and collects results. The skill's methodology is delivered via
    ``primary_skill`` (D2 — backend-boundary injection, single path for both
    SDKs: claude prepends ``/<skill>`` to the first message via
    ``render_skill_injection``, opencode adds a system steer to call the
    ``skill`` tool via ``render_opencode_skill_steer`` — opencode does NOT expand
    ``/<skill>``). The assigned ``skill_name`` therefore drives both the
    injection (``primary_skill``) and the session allowlist (``skills``); the
    ``prompt`` argument is the task description.
    """
    # M4: same main-process purity funnel as dispatch() — the skill CLI is an
    # orchestration entry too (idempotent install).
    from ascendc_devkit.infra.import_guard import install_purity_guard
    install_purity_guard()

    from ascendc_devkit.orchestration.skill import load_skill_spec

    spec = load_skill_spec(skill_name)
    if spec is None:
        Logger.error(f"Skill not found: {skill_name}")
        Logger.info("Run 'ascendc-devkit skill list' to see available skills")
        return 1

    workspace = Workspace.create(output_root=output_root)
    bind_run_log(workspace.dir / "run.log")
    if not prompt:
        prompt = f"Execute the {skill_name} skill."

    backend = build_agent_backend(
        interactive=not non_interactive,
        working_dir=workspace.artifacts,
        on_decision="default",
        decision_workspace=workspace.dir,
        enable_stubbed=False,
        resume_max_retries=_resume_limits()["max_retries"],
        resume_max_no_progress=_resume_limits()["max_no_progress"],
        rate_limit_max_retries=_resume_limits()["rate_limit_max_retries"],
        rate_limit_backoff_base_s=_resume_limits()["rate_limit_backoff_base_s"],
        rate_limit_backoff_factor=_resume_limits()["rate_limit_backoff_factor"],
        rate_limit_backoff_max_total_s=_resume_limits()["rate_limit_backoff_max_total_s"],
        turn_stall_s=_opencode_timeouts()["turn_stall_s"],
        gateway_error_probe_s=_opencode_timeouts()["gateway_error_probe_s"],
        tool_grace_s=_opencode_timeouts()["tool_grace_s"],
        message_timeout=_opencode_timeouts()["message_timeout_s"],
        resume_attempts=_infra_backoff()["resume_attempts"],
        thinking_active_gap_s=_retry_budgets()["thinking_active_gap_s"],
        fallback_to_stub=True,
    )

    try:
        # Route the allowlist through the one helper so a standalone skill run
        # gets the same tail-call closure the orchestrated substage does (P47):
        # a no-op for skills with no tail-call, correct for those that have one.
        from ascendc_devkit.orchestration.skill_config import skill_allowlist
        result = backend.spawn(
            agent_name=f"skill:{skill_name}",
            prompt=prompt,
            context={"skill_name": skill_name},
            skills=skill_allowlist(skill_name),
            primary_skill=skill_name,
        )
        if result.status == "ok":
            # F5: 干净完成即 ok（零产物时 artifacts 为空，下方自会不打印产物行；
            # "空产出"不再是一个 status 类别——skill 允许无产出）。
            Logger.info(f"Skill '{skill_name}' completed (status={result.status})")
            if result.artifacts:
                Logger.info(f"Generated {len(result.artifacts)} artifacts")
            return 0
        else:
            Logger.error(f"Skill '{skill_name}' failed (status={result.status})")
            return 1
    except Exception as e:
        Logger.error(f"Skill execution failed: {e}")
        return 1


# —— State machine helpers ——


def _resume_node_status(state: State, workflow) -> dict:
    """Build the resume completion frontier (node_status), enforcing clean-prefix
    causal validity (P52).

    node_status (multi-level node paths) is the SOLE authority for resume
    completion (step-2b B). The GraphExecutor persists it for every node it
    touches and it round-trips through the snapshot intact, so a resumed run
    skips exactly the completed nodes — including mid-group fine-grained resume.

    P52 — clean-prefix causal validity: within each SequentialGroup scope, a
    "completed" node is valid only if all preceding siblings are also completed.
    The first non-completed (failed / missing) node breaks the prefix; every
    "completed" sibling *after* it is built on a bad upstream and is invalidated
    (→ rerun) instead of trusted as stale. The first-bad node itself is left
    untouched (a failed/missing marker already reruns; keep it for diagnostics).
    ForkJoinGroup branches are parallel-independent — no clean-prefix between
    them — but a "failed" fork-join node still breaks its parent SequentialGroup
    prefix, and we recurse into branches for nested sequential scopes.
    See 29-resume-causal-validity-impl.md.

    The former stage_iterations→node_status bridge was GraphExecutor-migration
    debt and is deleted (it synthesized phantom keys that never matched group
    paths). The former passthrough trusted stale "completed"; P52 closes that.
    """
    from ascendc_devkit.orchestration.graph_executor import _invalidate_subtree
    from ascendc_devkit.orchestration.node import SequentialGroup
    from ascendc_devkit.orchestration.node_forkjoin import ForkJoinGroup

    ns = dict(state.node_status)

    def _node_path(node, scope_prefix):
        return node.name if not scope_prefix else f"{scope_prefix}/{node.name}"

    def _walk(node, scope_prefix):
        node_path = _node_path(node, scope_prefix)
        if isinstance(node, SequentialGroup):
            children = node.children()
            first_bad = None
            for idx, c in enumerate(children):
                if ns.get(_node_path(c, node_path)) != "completed":
                    first_bad = idx
                    break
            if first_bad is not None:
                # Invalidate stale "completed" downstream of the first break.
                # first_bad itself is kept (failed/missing already reruns).
                for c in children[first_bad + 1:]:
                    cp = _node_path(c, node_path)
                    if ns.get(cp) == "completed":
                        _invalidate_subtree(ns, cp, c)
            # Recurse into every child: a failed/invalidated group may still hold
            # a valid prefix inside (nested scope), and a fork-join child of a
            # sequential scope must be walked too.
            for c in children:
                _walk(c, node_path)
            return
        if isinstance(node, ForkJoinGroup):
            # Parallel-independent branches: no clean-prefix across siblings.
            for c in node.children():
                _walk(c, node_path)

    root = getattr(workflow, "root", None)
    if root is not None:
        chip = state.design_target_chip or ""
        _walk(root(chip) if callable(root) else root, "")
    return ns


def _resolve_rerun_target(workflow, target: str,
                          design_target_chip: str = "") -> str | None:
    """Resolve a user-typed rerun target (P68) to a full node path.

    Accepts a full path (``<workflow>/.../node``), a bare stage name
    (``codegen``), or a suffix. Returns the full path on a unique match; None on
    no match or ambiguity (a bare name shared by two nodes — the user must give
    the full path). node_status keys are workflow-prefixed paths, so this lets
    the user type the friendly bare name in the common case.
    """
    candidates: list[str] = []

    def _walk(node, prefix):
        p = node.name if not prefix else f"{prefix}/{node.name}"
        if p == target or node.name == target or (target and p.endswith("/" + target)):
            candidates.append(p)
        for c in node.children():
            _walk(c, p)

    root = getattr(workflow, "root", None)
    if root is not None:
        _walk(root(design_target_chip) if callable(root) else root, "")
    if not candidates:
        return None
    exact = [c for c in candidates if c == target]
    if len(exact) == 1:
        return exact[0]
    if len(candidates) == 1:
        return candidates[0]
    return None  # ambiguous bare/suffix name → require the full path


def _rerun_invalidate(node_status: dict, workflow, target_path: str,
                      design_target_chip: str = ""):
    """Drop ``target_path`` + its causal downstream from ``node_status`` (P68).

    Mirrors ``_resume_node_status``'s P52 clean-prefix invalidation, but the
    break point is a user-chosen node (INCLUSIVE) instead of the first
    non-completed sibling. The target's whole subtree is invalidated (a group
    target reruns all its children), and in every enclosing SequentialGroup
    every sibling AFTER the branch leading to the target is invalidated too
    (causal downstream — they may consume the target's outputs).
    ForkJoinGroup siblings are parallel-independent and are NOT invalidated.

    Returns ``(new_ns, found, invalidated_stages)``: ``invalidated_stages`` are
    the Stage objects of the atomic nodes dropped (the caller resets their
    ``rerun_reset_fields``). ``found`` is False (ns unchanged, stages empty) when
    the target is not in the tree. node_status is the sole resume/rerun
    authority — dropping a key makes the executor re-execute that node.
    """
    from ascendc_devkit.orchestration.node import AtomicStage, SequentialGroup
    from ascendc_devkit.orchestration.node_forkjoin import ForkJoinGroup
    from ascendc_devkit.orchestration.graph_executor import _invalidate_subtree

    ns = dict(node_status)
    invalidated: list = []

    def _path(node, prefix):
        return node.name if not prefix else f"{prefix}/{node.name}"

    def _collect_atomic(node):
        if isinstance(node, AtomicStage):
            invalidated.append(node.stage)
            return
        for c in node.children():
            _collect_atomic(c)

    def _walk(node, prefix, ancestors: list[str]) -> bool:
        node_path = _path(node, prefix)
        if node_path == target_path:
            _invalidate_subtree(ns, node_path, node)
            _collect_atomic(node)
            # Drop every enclosing group's key: a descendant is being re-run, so
            # each ancestor group's "completed" is stale — leaving it would make
            # the executor skip the whole group (graph_executor.py:174 skip guard
            # keys on the group path, not just leaves).
            for ap in ancestors:
                ns.pop(ap, None)
            return True
        if isinstance(node, SequentialGroup):
            children = node.children()
            for idx, c in enumerate(children):
                if _walk(c, node_path, ancestors + [node_path]):
                    # Target is inside this child → every LATER sibling in this
                    # scope is causal downstream (invalidate + reset its stages).
                    for later in children[idx + 1:]:
                        _invalidate_subtree(ns, _path(later, node_path), later)
                        _collect_atomic(later)
                    return True
            return False
        if isinstance(node, ForkJoinGroup):
            # Parallel branches: only the branch containing the target is
            # affected; sibling branches are independent (not downstream).
            for c in node.children():
                if _walk(c, node_path, ancestors + [node_path]):
                    return True
            return False
        return False

    root = getattr(workflow, "root", None)
    found = _walk(root(design_target_chip) if callable(root) else root, "", []) if root is not None else False
    return ns, found, invalidated


def _delete_session_sidecars(workspace) -> int:
    """Delete every ``<run>/agents/*.session.json`` resume sidecar (P68).

    The fresh-not-resume invariant: a rerun must spawn FRESH agents, NOT resume
    the prior session's reasoning memory (rerun ≠ resume — that is the whole
    point of rerun). ``codegen.actions`` reads a sidecar to issue a resume
    spawn; deleting the sidecars forces a fresh spawn through the existing
    single read pathway (§2.5).

    Safe to delete ALL sidecars: a sidecar exists only for a spawn that did NOT
    finish cleanly (``SDKBackend`` deletes it on a clean finish). A node marked
    ``completed`` therefore has no sidecar (its agent finished clean). So the
    only sidecars present are for interrupted/failed spawns — and on a rerun,
    every such node is either the re-run target or downstream of it (both want a
    fresh spawn). An upstream completed node has no sidecar to delete. Returns
    the count deleted (best-effort; a missing dir → 0).
    """
    base = getattr(workspace, "dir", None)
    if base is None:
        return 0
    agents = Path(base) / "agents"
    if not agents.exists():
        return 0
    n = 0
    for sc in agents.glob("*.session.json"):
        try:
            sc.unlink()
            n += 1
        except OSError:
            pass
    return n


def _apply_rerun(state: State, workflow, target_path: str, workspace) -> State:
    """Apply user-triggered rerun invalidation (P68). Returns the new State.

    Composition of three effects, all going through existing single pathways:
      1. node_status — invalidate target subtree + causal downstream (the P52
         primitive loopback/resume already share).
      2. session sidecars — delete them so re-run stages spawn FRESH (rerun ≠
         resume); the read site (codegen.actions) then sees no sidecar.
      3. reset fields — zero every invalidated stage's ``rerun_reset_fields`` to
         dataclass defaults so gate-relevant counters (codegen's circuit
         breaker, perf's loop guard) don't strand/misroute the fresh attempt.
    Also clears a ``last_error`` whose stage is being re-run (so the fresh agent
    isn't pre-halted by stale failure context); an upstream last_error is kept.

    Raises ValueError when the target is not in the workflow tree (the caller
    maps this to a usage error).
    """
    new_ns, found, stages = _rerun_invalidate(
        state.node_status, workflow, target_path, state.design_target_chip or "")
    if not found:
        raise ValueError(
            f"--rerun-from 目标 '{target_path}' 不在 workflow 树中")

    field_names: list[str] = []
    for st in stages:
        # rerun_reset_fields lives on the Stage base (default = output provides),
        # so every atomic stage declares what rerun must clear.
        field_names.extend(st.rerun_reset_fields())
    resets = State.defaults_for(field_names)

    rerun_names = {getattr(st, "name", None) for st in stages}
    le = state.last_error
    if le is not None and getattr(le, "stage_name", None) in rerun_names:
        resets["last_error"] = None

    # P68 extension: clear per-stage checkpoint files on disk so a stale
    # progress.md / coding_index.md etc. cannot short-circuit the re-run.
    for st in stages:
        st.rerun_reset_files(workspace)

    deleted = _delete_session_sidecars(workspace)
    Logger.info(
        f"Rerun from '{target_path}': re-run {len(stages)} stage(s) "
        f"[{', '.join(sorted(n for n in rerun_names if n))}]; deleted {deleted} "
        f"session sidecar(s) for fresh spawn (rerun ≠ resume)")
    return state.with_updates(node_status=new_ns, **resets)


def _first_pending_leaf(workflow, node_status: dict) -> str | None:
    """Name of the first root-tree leaf Stage not yet completed (log/display only).

    Resume execution is driven entirely by node_status in the GraphExecutor; this
    only derives a human-readable "resuming from" hint. Returns None when the flat
    leaf view is empty or all leaves are completed.
    """
    try:
        leaves = (workflow.flat_stages()
                  if hasattr(workflow, "flat_stages") else list(workflow.stages))
    except Exception:
        return None
    completed = {k for k, v in (node_status or {}).items() if v == "completed"}
    for leaf in leaves:
        name = getattr(leaf, "name", "")
        # A leaf is completed if any completed node path ends with its name.
        if not any(p == name or p.endswith("/" + name) for p in completed):
            return name
    return None


def _write_state_snapshot(workspace: Workspace, state: State) -> None:
    _log_state_integrity("snapshot-write", state)
    # P29/step-16: atomic write (temp + os.replace) so a SIGKILL mid-write can
    # never truncate/empty the snapshot. Worst case the previous complete
    # snapshot remains — still a valid frontier for resume. POSIX rename
    # atomicity gives old-or-new, never half.
    snapshot = state.to_snapshot()
    final = workspace.state_snapshot_path
    tmp = final.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2, default=str))
    os.replace(tmp, final)
