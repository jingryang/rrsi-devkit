"""L3 Orchestration — precision_debug CompositeGroup sub-stages (P3 减法).

Replaces the deleted LLM orchestrator (``ascendc-precision-debugger`` agent) +
external ``stage-transition.py`` script with framework sub-stages driven by
the GraphExecutor's transition_table. P3 减法：七 substage → 两段
（``run_tests`` ⇄ ``diagnose``），删 scope_guard / bounds_check / printf_location /
comment_bisect / diagnose_refine 独立 phase。§judgment-ownership (N1)：run_tests
纯 Python 化——确定性测量（RunMeasure action 执行 run-cases + 脚本），不 spawn
sub-agent；diagnose 是唯一 spawn phase sub-agent（``ascendc-precision-diagnose``）
with its per-phase skill injected via ``primary_skill``（slash ``/<skill>``）。
``transition()`` reads ``control.json``（the file relay, §2.3）into
``state._debug_checkpoint`` and ``resolve_condition()`` routes on it.

Hybrid file relay (54-*.md §4 — "混合切分"): the sub-agents autonomously read/write
two layers under ``{workspace.artifacts}/debug/{op_name}/``:

  - ``control.json`` — the FW routing slice + cross-domain shared state. Holds
    every field the framework routes on (status / failed_case_queue /
    history / current_case_index / best_* / upstream_signal) AND the multi-writer
    cross-domain structures (D2: single file avoids三方写冲突). The FW reads
    ONLY this file.
  - ``precision_<phase>.json`` — each phase's single-owner deep data
    (diagnose's fix_code_log / _summary, run_tests'
    last_result_json/last_run_log). Sub-agent-owned; the FW never reads these for
    routing (Stage 3 load-time validation reads them via SchemaLoader, not for
    routing). Each phase's schema lives in its own skill ``schema/`` dir (§2.2).

Why this shape (51-*.md §1/§2): the SDK ``Agent`` tool dispatches async, but the
old orchestrator prompt assumed a synchronous dispatch→verify LOOP — the mismatch
drove ~210 turn of idle dispatch, context bloat to 251K, and the 600s BG-wait
ceiling that killed batch aggregate sessions. The framework's synchronous
``spawn → wait → transition`` cures all three (§1.1 single authority).

Routing-control vs domain-data split (runlog 冲突4): control.json domain fields
stay 100% sub-agent-owned; the framework owns only *routing-control* —
``current_case_index`` advancement (the per-case stop-loss / skip that
``stage-transition.py`` used to mutate between dispatches) and the framework-side
round counter — writing current_case_index back to control.json and keeping rounds
in transient ``_debug_checkpoint``. ``state.debug_result`` is materialized here too
(runlog 冲突2): ``_sync_debug_result`` builds ``PrecisionDebugResult`` from
control.json when the run reaches a terminal state (passed / rounds exhausted /
upstream signal).

Invariant Layer (framework-owned, §P9 / §2.7)
  These module-level functions are the single authority for precision_debug
  state-machine invariants.  Skills produce raw results + LLM judgments only;
  they do NOT maintain these invariants.

  ============================== ================================================
  Function                        Invariant (source)
  ============================== ================================================
  ``_update_best_metrics``        ``(failed_count, crashed_count)`` comparison;
                                  tied = no claim (§P4 / §O2)
  ``_advance_current_case``       Skip current → index+1 (§P3)
  ============================== ================================================
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING


class PrecisionDebugContractError(RuntimeError):
    """control.json / per-phase artifact violates the mandatory contract (§12.2).

    Raised at load time (first read of control.json or per-phase json in a
    transition). The message always includes ``[PD-CONTRACT]`` so the
    ``_classify_uncaught`` infra/framework detector in ``graph_executor.py``
    classifies it as ``framework`` → non-fixable halt (§1.3 load-time validation
    over runtime surprise). No warn, no migration, no regeneration (§1.4).
    """
    pass

from ascendc_devkit.domain.contract import StageIOContract
from ascendc_devkit.domain.verification import PrecisionDebugResult
from ascendc_devkit.orchestration.kernel.action import SpawnAgent, RunMeasure
from ascendc_devkit.orchestration.runtime_config import (
    harness_timeout_sec,
    precision_debug_abort_exhaust_threshold,
    precision_debug_max_attempts_per_case,
    precision_debug_max_iterations,
    precision_debug_time_budget_sec,
)
from ascendc_devkit.orchestration.skill_config import (
    STAGE_SKILL_MAP, skill_allowlist,
)
from ascendc_devkit.orchestration.stages.design_substages import _DesignSubstage
# 传递 DEBUG_RESULT_CONTRACT 给 sub-agent context（single source，P0）。
from ascendc_devkit.orchestration.stages.precision_debug import (  # noqa: E402
    DEBUG_RESULT_CONTRACT as _DEBUG_RESULT_CONTRACT_REF,
)

if TYPE_CHECKING:
    from ascendc_devkit.orchestration.kernel.state import State


# —— control.json + per-phase file relay (§2.3 / 54-*.md §4) ————————————————

def _operator_dir(state: "State"):
    """op_dir 优先，op_identity.op_dir 兜底（对齐 P66 working_dir 解析）。"""
    if state.op_dir:
        return state.op_dir
    if state.op_identity is not None:
        return state.op_identity.op_dir
    return None


def _precision_fix_dir(state: "State") -> Path | None:
    """Legacy path: ``{operator_dir}/.precision-fix/``.  Still used for
    ``original_backup/`` (source backup, not an artifact) and as a fallback
    when ``state._workspace`` is not available (e.g. tests)."""
    op_dir = _operator_dir(state)
    if op_dir is None:
        return None
    return Path(op_dir) / ".precision-fix"


def _op_name(state: "State") -> str:
    """Operator name for artifact path construction — same logic as
    ``DebugService._op_name`` so precision_debug artifacts land in the same
    ``artifacts/debug/{op_name}/`` directory as the CLI's ``redeploy`` /
    ``run-cases`` outputs."""
    return (state.op_name
            or (state.op_identity.spec.name if state.op_identity else "op"))


def _debug_artifacts_dir(state: "State") -> Path | None:
    """Primary artifact root: ``{workspace.artifacts}/debug/{op_name}/``.

    Uses the same ``Workspace`` as other stages (codegen / deploy / perf / …)
    and the same ``{op_name}`` subdirectory as the ``redeploy`` / ``run-cases``
    CLI (``DebugService.debug_dir``).  Falls back to ``_precision_fix_dir`` when
    the workspace is not available (unit tests with minimal State).
    """
    ws = getattr(state, "_workspace", None)
    if ws is not None:
        return ws.artifacts / "debug" / _op_name(state)
    # Fallback: workspace not available (tests / legacy resume).
    return _precision_fix_dir(state)


def _control_path(state: "State") -> Path | None:
    """control.json — the FW routing slice + cross-domain shared state."""
    d = _debug_artifacts_dir(state)
    return None if d is None else d / "control.json"


# §step-88 (docs/plan/precision-diagnose-design-context/): diagnose 认知输入的
# 「设计」层。单一权威源 = staging 物化文件（与 codegen 输入同源，§2.5），
# 只传路径不传内容（§2.8 按需 Read）；不复制进 debug artifacts。
_DESIGN_STAGING_FILES: list[tuple[str, str]] = [
    ("design_spec", "design_spec.json"),
    ("tiling_strategy", "tiling_strategy.json"),
    ("kernel_architecture", "kernel_architecture.json"),
]


def _design_paths(state: "State") -> dict[str, str]:
    """Map design-artifact name → path for files actually present under
    ``{workspace.artifacts}/staging/`` (codegen's materialized inputs).

    Missing workspace / missing staging dir / missing files → simply absent
    from the result ({} — graceful degradation: TUI adapter runs without
    design artifacts fall back to code+golden understanding, L3 §3).
    """
    ws = getattr(state, "_workspace", None)
    if ws is None:
        return {}
    staging = Path(ws.artifacts) / "staging"
    return {name: str(staging / fn)
            for name, fn in _DESIGN_STAGING_FILES
            if (staging / fn).is_file()}



def _deploy_precondition(dbg, build_cmd: str) -> str:
    """§step-89 (docs/plan/precision-runtests-deploy-precondition/): run_tests
    测量前提——构造性保证 redeploy→run-cases 的文件接力契约（§2.3/§2.9）。

    N1 去 LLM 化后，被删 run_tests agent 的「编译预检 / 首轮 redeploy」隐式前置
    未迁移，fresh entry 必撞 run-cases 的 last_deploy.json 闸门（rc=1 空转熔断）。
    唯一写入者是 ``ascendc-devkit redeploy``（无条件落盘）；codegen 框架循环直调
    ``Deployer.deploy`` 不落盘。

    判据是「记录可用」（install_path AND python_path 非空——结构契约字段，
    §1.10/§1.12），不是「文件存在」：deploy build-failure 分支落盘**无路径**记录
    （diagnose 构建失败回滚后亦会留陈旧记录），空记录必须触发 redeploy 而非
    误导 run-cases。redeploy 的 rc 不是判据（deploy 失败时 CLI exit 1 但已落盘）
    ——只认落盘结果。redeploy 后仍不可用 → FATAL exit 1（真部署 infra 失败，
    measurement abort 熔断此时才正确）。无 dbg / 无 build_cmd（无 workspace
    边缘态）→ 返回空串，行为同旧（run-cases 自身诚实报错）。
    """
    if dbg is None or not build_cmd:
        return ""
    import shlex
    last = shlex.quote(str(Path(dbg) / "last_deploy.json"))
    usable = (
        "python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); "
        "sys.exit(0 if d.get(\"install_path\") and d.get(\"python_path\") else 1)' "
        f"{last} 2>/dev/null"
    )
    return (
        f"{usable} || {{ echo \"[deploy-precondition] last_deploy.json missing/unusable"
        f" — running redeploy\"; {build_cmd} || true; }}\n"
        f"{usable} || {{ echo \"FATAL: redeploy produced no usable last_deploy.json"
        f" (install_path/python_path empty) in {dbg}\" >&2; exit 1; }}\n"
    )


# ── Phase filename → directory stem (explicit mapping, not derived from filename) ──
_PHASE_STEM_MAP: dict[str, str] = {
    "precision_run_tests.json": "run_tests",
    "precision_diagnose.json": "diagnose",
}


# Framework-owned deterministic measurement scripts (§judgment-ownership N1). run_tests
# 从 LLM agent 收敛为纯 Python 测量——脚本迁出 .claude/skills（不再有 run_tests skill），
# 归框架包管理（§1.7 自闭环）。build-failed-case-queue.py / init-checkpoint.py 是队列构建
# 与 control.json 初始化的单一实现（§1.15）。
_RUN_TESTS_SCRIPTS_DIR = (Path(__file__).resolve().parent
                          / "precision_debug_run_tests" / "scripts")


def _phase_path(state: "State", filename: str, round_suffix: bool = False) -> Path | None:
    """A sub-agent's own per-phase json (precision_<phase>.json). **Pure function.**

    When ``round_suffix=True``, appends ``_rNNN_pMMM`` so multiple spawns of the
    same phase within one round (fix retry / printf continue / framework
    re-spawn) archive their deep data instead of the second overwriting the
    first. ``_pMMM`` is the monotonic ``phase_counter``.

    B1 fix: this function must stay side-effect-free. Previously it
    self-incremented ``phase_counter`` on every call, and one spawn called it
    4× (prompt build / context / read-summary / sync-latest) → 4 different
    paths → the agent wrote to one, the FW read another. The single mutation
    point is now ``_advance_phase_counter`` (called once per spawn in
    ``actions()``); this function only reads.
    """
    d = _debug_artifacts_dir(state)
    if d is None:
        return None
    phase_stem = _PHASE_STEM_MAP.get(filename, filename)
    phase_dir = d / "phases" / phase_stem
    if not round_suffix:
        return phase_dir / filename
    r = _current_round(state)
    cp = _load_control(state)
    idx = int(cp.get("phase_counter", 0))
    stem, ext = filename.rsplit(".", 1) if "." in filename else (filename, "json")
    return phase_dir / f"{stem}_r{r:03d}_p{idx:03d}.{ext}"


def _advance_phase_counter(state: "State") -> None:
    """Single mutation point for ``phase_counter`` — called once per spawn by
    ``_PrecisionDebugSubstage.actions()`` (B1 fix).

    Centralizing the increment here (out of ``_phase_path``) makes ``_phase_path``
    pure, so all reads within one spawn return the SAME path; the counter
    advances exactly once per spawn, preserving ``_pMMM`` archive-distinctness
    for same-round re-spawns (fix retry / printf continue / framework retry).

    Does NOT create control.json if absent — init is the agent's job
    (init-checkpoint.py writes the complete file)."""
    p = _control_path(state)
    if p is None or not p.exists():
        return  # 首次进入: control.json 还不存在, 留给 agent 的 init-checkpoint
    cp = _load_control(state)
    if not cp:  # 文件损坏 / 读失败
        return
    cp["phase_counter"] = int(cp.get("phase_counter", 0)) + 1
    _save_control(state, cp)


def _current_round(state: "State") -> int:
    """The framework's round counter (routing-only, transient).

    Each run_tests invocation advances it; diagnose within the same round shares
    the same counter value so its phase artifacts are grouped. Falls back to 0
    when the checkpoint hasn't been populated yet (first-ever run_tests before
    transition).
    """
    dc = state._debug_checkpoint or {}
    return max(int(dc.get("rounds", 0)), 1)


def _load_control(state: "State") -> dict:
    """Read control.json (the sub-agents' file relay). {} when absent/unreadable.

    Auto-repairs missing required keys and type coercions via
    :func:`_ensure_control_contract` on every read — so all callers
    (not just RunTestsSubstage.transition) benefit from contract enforcement.

    Orphan recovery (20260821 全局收口): when the file is absent, first attempt
    an in-place recovery — if the agent's transcript proves it wrote
    control.json OUTSIDE debug_artifacts_dir, ``recover_orphan_artifact`` moves
    it back (defensive, WARN + artifact_relocated event) and this read then
    succeeds normally. ``transcript`` comes from the spawn's agent_result when
    available; without one (fresh entry / no spawn yet) behavior is unchanged.
    """
    p = _control_path(state)
    if p is None or not p.exists():
        _recover_control_json_if_evidenced(state)
        if p is not None:
            p = _control_path(state)  # re-derive (path itself is stable; belt)
        if p is None or not p.exists():
            return {}
    try:
        cp = json.loads(p.read_text(encoding="utf-8"))
        return _ensure_control_contract(cp, str(p))
    except (OSError, json.JSONDecodeError):
        return {}


def _recover_control_json_if_evidenced(state: "State") -> None:
    """Best-effort orphan recovery for control.json (see _load_control).

    Transcript provenance: ``state._last_agent_transcript`` — set by
    RunTestsSubstage.transition from the spawn's agent_result (the only phase
    that owns control.json init). Absent → no-op, behavior identical to
    pre-recovery."""
    transcript = getattr(state, "_last_agent_transcript", None)
    d = _debug_artifacts_dir(state)
    if transcript is None or d is None:
        return
    try:
        from ascendc_devkit.orchestration.artifact_recovery import (
            recover_orphan_artifact)
        recover_orphan_artifact(
            transcript, "control.json", d, state, "precision-debug")
    except Exception:  # noqa: BLE001 — recovery is best-effort, never breaks routing
        from ascendc_devkit.infra.logger import Logger
        Logger.warn("[precision-debug] control.json 孤儿恢复尝试失败（忽略，"
                    "走既有 abort-retry 循环）")


# —— §12.2 load-time contract validation —————————————————————————————

# Required top-level keys every well-formed control.json must have (init-
# checkpoint.py writes them; a resume that reuses a stale checkpoint.json from a
# pre-588e248c build, or a corrupted write, would violate this).
_CONTROL_REQUIRED_KEYS = frozenset({
    "status", "max_iterations", "current_case_index",
    "failed_case_queue", "history",
    # precision_debug loop knobs (init-checkpoint.py writes; substage reads
    # control.json, never the global config — hand-edits win).
    "max_attempts_per_case", "time_budget_sec",
    # run_tests harness watchdog timeout (config default; the queue script
    # amplifies for large-shape cases and persists the amplified value here —
    # debug_service.run_cases reads it as the per-run override).
    "harness_timeout_sec",
    # §P3 upstream: diagnose 入口判据上报上游缺陷
    "upstream_signal", "upstream_stage", "upstream_reason",
    # FW-owned monotonic counters (P9 — init-checkpoint.py writes 0; FW advances)
    "phase_counter", "run_iter_counter",
    # §abort: consecutive agent-abort annealing counter (init-checkpoint writes 0)
    "consecutive_aborts",
})

# D3 (54-*.md §4.3): fields that MUST NOT appear — stale from the old
# checkpoint.json design. Their presence signals a pre-split control.json.
_CONTROL_FORBIDDEN_KEYS = frozenset({
    "current_stage", "trim_retry", "consecutive_failures",
    "current_iteration", "bisect",  # top-level bisect — now in per-phase json
})


# §12.2 safe defaults for control.json fields that the framework can auto-repair
# when the agent (due to model hallucination) writes a partial control.json.
# Must match the initial values written by init-checkpoint.py (§4.2).
_CONTROL_DEFAULTS = {
    "status": "running",
    "max_iterations": precision_debug_max_iterations(),
    "current_case_index": 0,
    "failed_case_queue": [],
    "history": [],
    # precision_debug loop knobs — read from orchestration-config.json via
    # runtime_config accessors (auto-repair fallback when an agent writes a
    # partial control.json; init-checkpoint.py writes the live values).
    # Must be dynamic (not hardcoded): config is the single source of truth.
    "max_attempts_per_case": precision_debug_max_attempts_per_case(),
    "time_budget_sec": precision_debug_time_budget_sec(),
    # run_tests harness watchdog timeout — config default (timeouts.harness_sec);
    # the queue script amplifies and persists the amplified value in
    # control.json (hand-edits / amplifications win). Debug-service reads
    # control.json first, so this default only matters when the field is absent.
    "harness_timeout_sec": harness_timeout_sec(),
    "phase_counter": 0,
    "run_iter_counter": 0,
    # §step-119: best_* 字段已删——最优/计数从 history 测量史现算派生。
    # §time-budget: 已执行秒数, 框架 Python 侧在每个 transition 更新
    "elapsed_sec": 0.0,
    # §abort: consecutive agent-abort annealing counter
    "consecutive_aborts": 0,
    # init-checkpoint 写入（control.json 被框架提前创建时可能缺失）
    "initial_commit": None,
    "is_git_repo": False,
}


# §abort: agent-abort annealing threshold. After this many *consecutive* sub-stage
# aborts (agent produced no output — context limit / infra crash / timeout) the
# sub-stage fires abort_exhausted (→ run_tests via §abort-relay for non-run_tests
# stages) instead of re-spawning forever. Trigger resets the streak (§abort-reset)
# so the next chain counts from 0; run termination is bounded by rounds /
# max_iterations + time budget, not by the abort streak.
# Configurable via ``precision_debug_a3.abort_exhaust_threshold`` (fallback shared
# ``precision_debug.abort_exhaust_threshold``; default 10 — hys run tuning 2).
_ABORT_EXHAUST_THRESHOLD = precision_debug_abort_exhaust_threshold()


# §12.2 safe defaults for per-phase JSON required keys. Each key maps to its
# safe default value (empty list / dict / string / None / False as appropriate).
# Used by _validate_phase_json → _ensure_phase_json_contract for auto-repair
# when an agent (due to model hallucination) writes a partial phase JSON.
_PHASE_DEFAULTS: dict[str, dict[str, object]] = {
    "precision_run_tests.json": {"last_result_json": "", "last_run_log": ""},
    "precision_diagnose.json": {"diagnose_done": False, "fix_code_log": {}},
}


def _ensure_control_contract(cp: dict, control_path: str) -> dict:
    """Validate and auto-repair control.json structure.

    Design principle (§1.2 robustness): missing/malformed fields that can be
    safely re-initialized (agent hallucination / partial write) are auto-repaired
    with a warning.  Only truly unrecoverable violations (D3 stale checkpoint
    format, critical type errors that can't be coerced) raise
    ``PrecisionDebugContractError``.

    Called on every control.json read via :func:`_load_control` — all readers
    (not just RunTestsSubstage.transition) benefit from contract enforcement.
    repaired) control dict; writes back to *control_path* when repair occurred.
    """
    if not cp:
        return cp  # absent control.json → init-checkpoint hasn't run yet, skip

    repaired = False

    # —— Missing required keys: auto-fill with safe defaults ——————————————
    # 框架自有字段（harness_timeout_sec）除外：agent 不对它负责（放大值由确定性脚本
    # 写框架自有 sidecar，§2.9 构造性——机械可派生的事实不靠 LLM 纪律）。agent 重写
    # control.json 丢掉它=正常交接，不是契约违约：缺失时静默跳过（不 WARN、不填默认
    # ——填默认会把放大值 480s 打回 120s；debug_service 读 sidecar 兜底）。20260810
    # 批 6+ 次 PD-CONTRACT WARN 实为把 agent 不该负责的字段归咎于 agent。
    _FRAMEWORK_OWNED_KEYS = frozenset({"harness_timeout_sec"})
    missing = (_CONTROL_REQUIRED_KEYS - set(cp.keys())) - _FRAMEWORK_OWNED_KEYS
    if missing:
        from ascendc_devkit.infra.logger import Logger
        Logger.warn(
            f"[PD-CONTRACT] control.json missing {len(missing)} required key(s): "
            f"{sorted(missing)}. Auto-initializing to safe defaults "
            f"(likely agent hallucination / partial write — see §12.2)."
        )
        for k in sorted(missing):
            cp[k] = _CONTROL_DEFAULTS.get(k)
        repaired = True

    # —— Forbidden D3 keys: truly fatal (stale checkpoint format) ——————————
    resurrected = _CONTROL_FORBIDDEN_KEYS & set(cp.keys())
    if resurrected:
        raise PrecisionDebugContractError(
            f"[PD-CONTRACT] control.json contains stale D3-deleted keys: "
            f"{sorted(resurrected)}. This looks like a pre-split checkpoint."
        )

    # —— Routing scalar type coercion ———————————————————————————————————————
    if not isinstance(cp.get("current_case_index"), int):
        try:
            cp["current_case_index"] = int(cp["current_case_index"])
            repaired = True
        except (TypeError, ValueError):
            cp["current_case_index"] = 0
            repaired = True
    if not isinstance(cp.get("failed_case_queue"), list):
        cp["failed_case_queue"] = []
        repaired = True
    if not isinstance(cp.get("history"), list):
        cp["history"] = []
        repaired = True

    # —— §weak-model: last_reject_reason shape coercion ————————————————————
    # 框架写的打回原因 {cond, detail, round}（可选字段，不进 REQUIRED）。agent 写坏
    # 形状（非 dict）→ 置 None + WARN：拒因丢失可降级（retry 仍进行，只是少了定向
    # 引导），不 raise 不波及 control 其余字段（§3.7 可观测、不过度致命）。
    lrr = cp.get("last_reject_reason")
    if lrr is not None and not isinstance(lrr, dict):
        from ascendc_devkit.infra.logger import Logger
        Logger.warn(
            f"[PD-CONTRACT] last_reject_reason 非 dict（{type(lrr).__name__}）——"
            f"置 None 降级（拒因丢失不影响路由，仅少定向引导）")
        cp["last_reject_reason"] = None
        repaired = True


    # —— failed_case_queue element contract —————————————————————————————————
    queue = cp.get("failed_case_queue") or []
    for i, case in enumerate(queue):
        if not isinstance(case, dict):
            # Non-dict element → drop it (can't recover)
            from ascendc_devkit.infra.logger import Logger
            Logger.warn(
                f"[PD-CONTRACT] control.json.failed_case_queue[{i}] is "
                f"{type(case).__name__}, not dict — dropping element."
            )
            queue[i] = None
            repaired = True
            continue
        for f in ("case_id", "status", "failure_type"):
            if f not in case:
                case[f] = "unknown" if f in ("status", "failure_type") else -1
                repaired = True
    # Remove dropped elements
    if None in queue:
        cp["failed_case_queue"] = [c for c in queue if c is not None]
        repaired = True

    if repaired:
        from pathlib import Path
        p = Path(control_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(cp, indent=2, ensure_ascii=False), encoding="utf-8")

    return cp


def _save_control(state: "State", cp: dict) -> None:
    """Write routing-control fields back to control.json (runlog 冲突4).

    The framework owns ONLY routing-control (current_case_index advancement);
    domain data is sub-agent-owned.
    Called after ``_advance_current_case``.
    """
    p = _control_path(state)
    if p is None:
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cp, indent=2, ensure_ascii=False), encoding="utf-8")


# —— routing predicates + mutations (faithful port of stage-transition.py) ———

def _get_current_case(cp: dict):
    idx = cp.get("current_case_index", 0)
    queue = cp.get("failed_case_queue", []) or []
    if idx < 0 or idx >= len(queue):
        return None
    return queue[idx]


def _get_current_failure_type(cp: dict) -> str | None:
    """failure_type from the most recent run_tests history entry.

    History entries are framework-authored and NESTED: the payload lives under
    ``content`` (``_append_history`` writes ``{"phase","timestamp","round",
    "content":{...}}``). Entries whose content carries no failure_type (e.g.
    upstream halt reports) are naturally skipped. F1 fix: the old top-level read
    (``entry.get("failure_type")``) never matched the nested write."""
    for entry in reversed(cp.get("history", []) or []):
        content = entry.get("content") or {}
        ft = content.get("failure_type")
        if ft:
            return ft
    return None


# §P2: run-level failure_type 聚合优先级（与 run_tests skill 的症状分类优先级一致：
# runtime > compilation > precision）。run-level 从 per-case 值确定性派生，agent
# 只修 per-case（读日志的 LLM 语义），不再单独申报 run-level（§2.5 单通路）。
_FAILURE_TYPE_PRIORITY = ("runtime", "compilation", "schema_contract", "precision")
# §fixability-routing: schema_contract = 契约/注册类（python 契约校验 / plugin
# schema / 注册失败，发生在 kernel launch 前后、非 C++ 编译器输出）。排在
# compilation 之后（编不出 dominates）、precision 之前（契约错挡住精度验证）。

# §fixability-routing: origin_stage 的「上游」集合——verdict=pass 而 origin 落在
# 此集合 = 上游根因但算子工程内可修 → 框架 WARN 后兜底修复（用户指令②）。
# kernel/unknown 不在此列（本阶段职责/未识别，无上游信号可留档）。


def _aggregate_failure_type(queue: list) -> str | None:
    """§P2: run-level failure_type — deterministic aggregation over the
    (agent-corrected) per-case types in failed_case_queue."""
    present = {c.get("failure_type") for c in queue if isinstance(c, dict)}
    for ft in _FAILURE_TYPE_PRIORITY:
        if ft in present:
            return ft
    return next((ft for ft in sorted(present) if ft), None) or None


def _canonical_case_num(raw) -> str:
    """Normalise a case-id representation to its trailing number string.

    Diagnose agents (LLM) produce ``affects_cases`` with inconsistent types and
    formats: ``[7, 12]`` (int), ``['7', '12']`` (str), or ``['level1/op_7',
    'level1/op_12']`` (full case_id_str).  Likewise ``case_id`` in the
    failed_case_queue can be an int or a full path depending on when the
    control.json was created.  This helper extracts the canonical case number
    (last ``_``-delimited segment) so comparisons are type- and format-agnostic.

    >>> _canonical_case_num(7)                          → '7'
    >>> _canonical_case_num('7')                        → '7'
    >>> _canonical_case_num('level1/clipped_swiglu_7')  → '7'
    """
    s = str(raw)
    if '_' in s:
        return s.rsplit('_', 1)[-1]
    return s


def _write_precision_report(cp: dict, debug_dir: Path | None) -> None:
    """Write/update ``precision_report.md`` — human-readable best-version debug status.

    Called in ``RunTestsSubstage.transition`` when ``_update_best_metrics``
    returns True (``best_passed_count`` strictly increased), and in
    ``_sync_debug_result`` at terminal states. The report is self-contained
    and readable by anyone not involved in the debugging session.

    **Fail-safe**: the entire body is wrapped in try/except — a report write
    failure must never crash the transition that called it.
    """
    if debug_dir is None:
        return
    try:
        _write_precision_report_impl(cp, debug_dir)
    except Exception:
        from ascendc_devkit.infra.logger import Logger
        Logger.warn("_write_precision_report failed — continuing without report")


def _report_total(cp: dict, history: list) -> int:
    """报告用「用例总数」（docs/plan/precision-report-rendering P2）。

    §step-119: 不再读已删的 best_total_count——直接取 history run_tests max(total_count)。
    全过态绝不因 best_failed=0 归零（history 有 20/20 记录 → total=20）。
    """
    totals = [int((e.get("content") or {}).get("total_count") or 0)
              for e in history
              if isinstance(e, dict) and e.get("phase") == "run_tests"]
    return max(totals) if totals else 0


def _merge_fix_into_ledger(cp: dict, summary: dict, phase: str) -> None:
    """把 agent 已报告的 commit 合并进 root_cause_ledger（docs/plan/precision-report-rendering P4）。

    追加 resolved 条目，按 fix_commit 短 12 位去重。不增 open 数 → 不扰 diagnose 路由。
    summary 无 commit → no-op。

    P3 减法：bounds_check 分支已删（phase 恒为 "diagnose"，bounds_check phase 不存在）。
    """
    commit = summary.get("git_commit") or ""
    if isinstance(commit, list):
        commit = commit[0] if commit else ""
    if not commit:
        return
    short = str(commit)[:12]
    ledger = cp.setdefault("root_cause_ledger", [])
    for rcl in ledger:
        if isinstance(rcl, dict) and str(rcl.get("fix_commit") or "")[:12] == short:
            return  # 已存在，去重
    plan_id = str(summary.get("applied_plan_id") or summary.get("plan_id") or "")
    ledger.append({
        "id": f"{phase}-{short}",
        "type": "precision",
        "state": "known",
        "status": "resolved",
        "fix_commit": str(commit),
        "evidence": (plan_id or f"{phase} applied commit {short}"),
        "last_result": f"resolved via commit {short}",
    })


def _report_fix_rows(cp: dict, history: list) -> list:
    """修复历史行（docs/plan/precision-report-rendering P4）：commit 单一源 ledger + 纯根因分析行。

    - root_cause_ledger 有 fix_commit → commit 行（commit | root_cause | id+evidence）。
    - history 的 root_cause/finding 文本（无 commit）→ commit 列 '-' 的分析行，保留审计价值。
    - 按 commit 短 12 位去重。
    """
    rows: list[tuple[str, str, str]] = []
    seen: set = set()
    for rcl in cp.get("root_cause_ledger") or []:
        if not isinstance(rcl, dict):
            continue
        fc = rcl.get("fix_commit")
        if not fc:
            continue
        short = str(fc)[:12]
        if short in seen:
            continue
        seen.add(short)
        root = f"{rcl.get('id') or '?'}: {(rcl.get('evidence') or '')[:100]}"
        rows.append((short, "root_cause", root[:120]))
    for entry in history:
        if not isinstance(entry, dict):
            continue
        content = entry.get("content")
        if not isinstance(content, dict):
            content = {}
        # 该 history 条目的 commit（diagnose: git_commit）已在 ledger 出现过 →
        # 跳过，避免同一修复在报告出现两行（ledger 是 commit 单一源，P4）。
        hcommit = content.get("git_commit") or ""
        if isinstance(hcommit, list):
            hcommit = hcommit[0] if hcommit else ""
        if hcommit and str(hcommit)[:12] in seen:
            continue
        root = str(content.get("root_cause") or "")
        if not root:
            finding = content.get("finding")
            if finding:
                root = str(finding)[:200]
        if not root and content.get("aborted"):
            continue
        if not root:
            continue
        plan_id = str(content.get("applied_plan_id") or "")
        if plan_id:
            root = f"{plan_id}: {root}" if root else plan_id
        rows.append(("-", str(entry.get("phase") or "?"), root[:120]))
    return rows


def _write_precision_report_impl(cp: dict, debug_dir: Path) -> None:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    op = str(cp.get("operator") or cp.get("op_name") or "unknown")
    history: list = cp.get("history") or []
    # §step-119: 最优/计数从 history 测量史派生（不再读可写 best_* 字段）——渲染
    # (identity, passed) 对，使「20 全过」与「哪个被测代码」一一对应、可追溯。
    _best_ident = _best_commit_from_history(history) or "unknown"
    _bm = _derive_best_metrics(history)
    best_commit = str(_best_ident)
    best_passed = int(_bm["passed"] or 0)
    best_failed = int(_bm["failed"] or 0)
    best_crashed = int(_bm["crashed"] or 0)
    status = str(cp.get("status") or "unknown")
    best_err = _bm["max_err"]
    err_str = "-" if best_err is None else str(best_err)   # P5
    total = _report_total(cp, history)                     # P2
    rounds = max([int(e.get("round") or 0) for e in history
                  if isinstance(e, dict) and e.get("phase") == "run_tests"] or [1])  # P1

    lines = [
        f"# Precision Debug Report — {op}",
        "",
        f"- **最优 commit**: `{best_commit}`",
        f"- **通过/失败/崩溃**: {best_passed}/{best_failed}/{best_crashed}",
        f"- **最大误差**: {err_str}",
        f"- **状态**: {status}",                          # 目标态 1
        f"- **更新时间**: {now}",
        f"- **迭代轮次**: {rounds}",
        "",
        "## 失败用例状态",                                  # P3 表头诚实化
        "",
        "| # | Case | Shape | Dtype | Status | Max Err | Failure Type | Attempts |",
        "|---|------|-------|-------|--------|---------|-------------|----------|",
    ]
    queue = cp.get("failed_case_queue") or []
    if queue:
        for i, case in enumerate(queue, 1):
            if not isinstance(case, dict):
                continue
            case_id = str(case.get("case_id") or "?")
            shape = str(case.get("shape") or "?")
            dtype = str(case.get("dtype") or "?") or "-"
            cstatus = str(case.get("status") or "pending")
            max_err = case.get("max_err")
            ftype = str(case.get("failure_type") or "?")
            attempts = int(case.get("attempt_count") or 0)
            short_id = case_id.rsplit("/", 1)[-1] if "/" in case_id else case_id
            lines.append(
                f"| {i} | {short_id} | {shape} | {dtype} | {cstatus} "
                f"| {max_err} | {ftype} | {attempts} |"
            )
    else:
        # P3: 全过态显式渲染成功摘要，不留误导性空表
        ok = f"{best_passed}/{total}" if total else str(best_passed)
        lines.append(f"> ✅ **{ok}** 用例全部通过，无待处理失败用例。")

    lines.append("")
    lines.append("## 修复历史")
    lines.append("")
    lines.append("| # | Commit | Phase | 根因 / 发现 |")
    lines.append("|---|--------|-------|-------------|")
    for i, (commit, phase, root) in enumerate(_report_fix_rows(cp, history), 1):  # P4
        lines.append(f"| {i} | {commit} | {phase} | {root} |")

    # P2/P6 收敛趋势：分母用 total；去 fc>0 过滤（最终全过轮可见）；同轮去重（last wins）
    lines.append("")
    lines.append("## 收敛趋势")
    lines.append("")
    by_round: dict[int, tuple[int, int]] = {}
    for entry in history:
        if not isinstance(entry, dict) or entry.get("phase") != "run_tests":
            continue
        c = entry.get("content") or {}
        r = int(entry.get("round") or 0)
        if r <= 0:
            continue
        fc = int(c.get("failed_count") or 0)
        tc = int(c.get("total_count") or 0)
        by_round[r] = (fc, tc)                              # last wins
    for r in sorted(by_round):
        fc, tc = by_round[r]
        total_r = tc or total
        passed_r = total_r - fc if total_r else best_passed
        lines.append(f"- 第 {r} 轮: {passed_r}/{total_r} passed ({fc} failed)")
    lines.append(f"- **当前最优**: {best_passed}/{total} passed")

    report_path = debug_dir / "precision_report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _advance_current_case(cp: dict) -> None:
    """Mark the current case skipped + advance the index.

    Pure mutator — modifies *cp* in place, returns nothing.
    Writes control.json fields: failed_case_queue / current_case_index."""
    queue = cp.get("failed_case_queue") or []
    idx = cp.get("current_case_index", 0)
    if 0 <= idx < len(queue):
        queue[idx]["status"] = "skipped"
    cp["current_case_index"] = idx + 1


def _case_marked_resolved(case: dict | None) -> bool:
    """fix sets ``resolved_pending`` after a single-case pass; the framework
    treats both ``resolved`` and ``resolved_pending`` as 'go regress' (run_tests
    full-suite confirms + checks side-effects)."""
    if case is None:
        return False
    return case.get("status") in ("resolved", "resolved_pending")


def _stalled_reject_reason(dc: dict) -> dict | None:
    """§weak-model A: diagnose「打回」判定的单点（§1.15）——transition 写拒因与
    resolve_condition 路由共用同一判定。

    返回非 None ⇔ stalled 缺 self_check 自检证据（会被打回 retry 继续调试）；
    返回 None = 合法 stalled（诚实报告出口）或非 stalled。detail 遵循 P44-C：
    判定是事实（缺什么），补救是非约束建议。
    """
    if not dc.get("stalled"):
        return None
    sd = dc.get("stalled_detail")
    sc = sd.get("self_check") if isinstance(sd, dict) else None
    if sc:
        return None
    return {
        "cond": "stalled_without_selfcheck",
        "detail": ("声明 stalled（假设空间穷尽）但缺 self_check 自检证据。请按自检项"
                   "（①全局理解 kernel+golden ②多假设已验证 ③弹药系统排查 ④确认再试"
                   "不推进）补 self_check 后重新声明；自检发现未穷尽则继续调试产出修复"),
    }


def _reject_reason_block(cp: dict, current_round: int) -> str:
    """§weak-model A: 渲染 control.json.last_reject_reason 为 prompt 段。

    文件版 consumed-once：拒因的 round 与当前 control rounds 匹配才显示——diagnose
    retry 自环（rounds 不变）持续可见；经 run_tests 全量回归（rounds+1）自动过期，
    不残留旧拒因误导后续轮。非 dict（agent 写坏，契约已矫正为 None）→ 空串。
    """
    lrr = cp.get("last_reject_reason")
    if not isinstance(lrr, dict):
        return ""
    try:
        if int(lrr.get("round", -1)) != int(current_round):
            return ""
    except (TypeError, ValueError):
        return ""
    cond = str(lrr.get("cond") or "")
    detail = str(lrr.get("detail") or "")
    return (f"## 框架打回（上轮 diagnose 产物被拒）\n"
            f"- 判定：{cond}\n"
            f"- 原因：{detail}")


def _extract_debug_checkpoint(cp: dict) -> dict:
    """Minimal routing field set derived from control.json (§7 B-class).

    Domain data (failed_case_queue contents, history, …) stays in control.json
    for the sub-agents; only what routing/loopback needs is lifted into
    ``state._debug_checkpoint``. D3 (54-*.md): current_iteration / diagnose_done
    removed — the FW routes on the transient round counter and
    never read diagnose_done (diagnose-owned, lives in precision_diagnose.json).
    """
    case = _get_current_case(cp)
    queue = cp.get("failed_case_queue", []) or []
    # Per-case failure_type is the precise signal for the fix routing decision
    # (compilation/runtime can't be printf-bisected); fall back to the run-level
    # history type when the case carries none.
    case_failure_type = (case.get("failure_type") if case else None)
    # §step-119: best_* 字段已删——dc 的 best_* 从 history 测量史派生（不再读 cp 顶层）。
    _best_metrics = _derive_best_metrics(cp.get("history") or [])
    _best_ident = _best_commit_from_history(cp.get("history") or [])
    return {
        "status": cp.get("status", "running"),
        "max_iterations": cp.get("max_iterations", 15),
        "best_commit": _best_ident,
        "best_real_max_err": _best_metrics["max_err"],
        "best_failed_count": _best_metrics["failed"],
        "failed_case_count": len(queue),
        "failure_type": case_failure_type or _get_current_failure_type(cp),
        "current_case_status": case.get("status") if case else None,
        "current_case_attempt": case.get("attempt_count", 0) if case else 0,
        "current_case_max_attempts": cp.get("max_attempts_per_case", 8),
        "case_resolved": _case_marked_resolved(case),
        "failing_cases": [c.get("case_id", "") for c in queue
                          if c.get("status") in ("pending", "skipped")],
        # §P3 upstream: diagnose 入口判据上报上游缺陷 → halt（替代 scope_guard upstream）。
        "upstream_signal": cp.get("upstream_signal", False),
        "upstream_stage": cp.get("upstream_stage"),
        "upstream_reason": cp.get("upstream_reason"),
        # §judgment-ownership (P5): diagnose 尽力后假设空间穷尽 → stalled 诚实报告，
        # 不再无限 retry。由 diagnose 写 _summary.stalled=true + RESULT DIAGNOSED_STALLED。
        # stalled_detail 与 stalled 同源（agent 写 control.json），供 halt_reason 展示。
        "stalled": cp.get("stalled", False),
        "stalled_detail": cp.get("stalled_detail", ""),
        # §fixability-routing: 缺陷根因归属（kernel/codegen/test_design/design/
        # golden/deploy/framework/env/unknown）。verdict 管路由；origin 只管
        # 留档与可观测——pass ∧ origin∈上游集 → 框架 WARN 后继续兜底修复。
        # §step-119: best_* 从 history 派生（_derive_best_metrics）。
        "best_crashed_count": _best_metrics["crashed"],
        "best_real_max_err": _best_metrics["max_err"],
        # §passed-count + §time-budget: 透出供 _sync_debug_result / _time_budget_exhausted
        "best_passed_count": _best_metrics["passed"],
        "elapsed_sec": cp.get("elapsed_sec", 0.0),
        "time_budget_sec": cp.get("time_budget_sec", precision_debug_time_budget_sec()),
        # §P8 printf deploy health (extracted from phase JSON _summary)
        "deploy_health": cp.get("deploy_health"),
        # §abort: consecutive agent-abort annealing counter
        "consecutive_aborts": cp.get("consecutive_aborts", 0),
        # §crash-sentinel: harness was killed before printing any case output.
        # build-failed-case-queue.py sets this flag in control.json.
        "crash_sentinel_mode": cp.get("crash_sentinel_mode", False),
        # §3.3 run_tests 如实传递的观察清单（timeout/upstream_signal/test_script/
        # golden/env/other）→ 物化供 diagnose 读（级联隔离 / 精度探针）。
        "observed_issues": cp.get("observed_issues") or [],
    }


# §time-budget: precision_debug 墙钟预算. 首次 run_test 开始计时, 每次 run_test
# 后检查; 超预算则退出该阶段 (与 max_iterations 轮数上限并列的第二退出条件).
# 退出时工作区收敛到 best_commit (通过用例最多). 预算可配置:
# orchestration-config.json precision_debug.time_budget_sec.


def _time_budget_exhausted(dc: dict) -> bool:
    """precision_debug 墙钟预算是否耗尽.

    与 ``resolve_condition`` 的超时→exhausted 路由 + ``_sync_debug_result`` 的
    terminal 判定共用, 保证两处一致.
    ``elapsed_sec`` 由框架 Python 侧在每个 transition 中计算并写入 control.json,
    agent 不参与计时, 避免时间戳被 LLM 序列化为 ISO 字符串导致 corrupt.
    """
    elapsed = float(dc.get("elapsed_sec", 0) or 0)
    budget = float(dc.get("time_budget_sec", precision_debug_time_budget_sec()))
    return elapsed > budget > 0


# —— 框架侧计时 (Python 拥有, 不依赖 control.json 中的原始时间戳) ——

_precision_start_ts: float | None = None  # 模块级, 本次进程内首次 run_test 设定


def _update_elapsed_sec(state: "State", cp: dict) -> None:
    """框架 Python 侧计算已执行时间 (s), 写入 control.json.

    每次 transition 调用, 保证 ``elapsed_sec`` 始终是 Python 计算的权威值,
    agent 读写 control.json 时可能覆盖, 但下一个 transition 会重新修正.
    """
    global _precision_start_ts
    if _precision_start_ts is None:
        # 首次进入: 尝试从 control.json 恢复 (resume 场景)
        prev = cp.get("elapsed_sec")
        if isinstance(prev, (int, float)) and prev > 0:
            # 用上次记录的 elapsed 作为起点, 加上进程启动后已过时间
            _precision_start_ts = time.time() - float(prev)
        else:
            _precision_start_ts = time.time()
    elapsed = time.time() - _precision_start_ts
    cp["elapsed_sec"] = max(elapsed, 0.0)
    _save_control(state, cp)


def _current_head(repo_root) -> str | None:
    """当前 git HEAD commit（best 缺失时的 fallback anchor）。

    非 git / 探测失败 → None。供 ``_converge_to_best_commit`` 在测量史无最优时兜底——
    入口 commit (``_entry_commit_codegen``) 之后 HEAD 含全部 codegen，rollback 安全。
    §review-m1/§1.15：HEAD 探测委托 infra.provenance 单点（probe_source），本模块
    不再自建 rev-parse 子进程——探测超时/语义只改一处。
    """
    from ascendc_devkit.infra.provenance import probe_source
    commit, _ = probe_source(repo_root)
    return commit


def _measured_source(state: "State") -> tuple[str, str]:
    """run_tests 测量时刻的被测树现探 → (完整 commit sha, {sha12}-dirty-N 标签)。

    §step-124 修复：测量行不再抄 ``state.deploy_result`` 的 deploy stamp——精度
    调试期间 agent 自建包（build→单用例验证→commit）不流经框架 Deployer，该缓存
    停留在 codegen 末次部署，导致所有测量行携带同一陈旧标签（20260915 批：两
    worktree 全部测量行同 ``94c716aecb9d-dirty-1``，与真实 HEAD 不符）。
    返回的完整 commit 是合法 git ref，作 converge/teardown 的 best 收敛锚点；
    标签保留 dirty 计数的诚实信号。无 repo_root / 非 git → ("", "")。
    §review-m2：dirty 口径限定 op_dir（一仓多 op 布局下不计兄弟 op/仓根的脏
    改动；锚点 source_commit=HEAD 本就是全仓粒度，不受影响）。op_dir 缺 → 全仓。
    """
    op = getattr(state, "op_identity", None)
    repo_root = getattr(op, "repo_root", None) if op is not None else None
    if not repo_root:
        return "", ""
    from ascendc_devkit.infra.provenance import probe_source
    commit, ident = probe_source(repo_root, scope=_operator_dir(state))
    return commit or "", ident


def _entry_commit_codegen(state: "State") -> None:
    """precision_debug 入口：把允许的 codegen 生产文件 commit 进 git。

    背景：codegen 成功路径不 commit（产物停留 op_dir 工作区 untracked），diagnose 实施模式
    agent 只选择性 ``git add <修改的文件>``，故 best_commit (``= git rev-parse HEAD``) 不含
    未被 diagnose 收编的 codegen 文件（op_plugin/op_api 注册文件等）。这使 converge/teardown
    的 ``git clean -fd -- op_dir`` 误删 codegen → 工作区残缺、redeploy 残缺。

    入口处由框架枚举 op_dir 的实际变更，并按 repository profile 的
    ``precision_debug_commit`` 白名单选择生产文件，以 exact literal pathspec 执行
    add/commit。日志、测试脚本、备份、缓存、编译产物以及算子目录外的 staged change
    都不会被自动提交。

    这样后续 best_commit/HEAD 会包含可回滚的生产 codegen，而调试产物仍停留工作区。
    一石三鸟：通道①(escalation)接入 converge + best_commit 空 HEAD 兜底 + except 通道
    既有 clean -fd 隐患，三者皆依赖此入口 commit。

    仅首轮（control.json 不存在）执行一次；幂等——resume 时 run_tests 已 completed 则
    actions 不重入；首轮中途 hard-kill 重入时没有允许范围内的变化就不创建 commit。
    非 git / commit 失败不阻断，安全 helper 会保留源码并禁用不可信 rollback anchor。

    commit 模型前提（正确性的隐含假设）：
    precision_debug 期间 op_dir 的变更仅来自 codegen（本入口 commit）/ diagnose（实施模式
    各自 commit）/ printf（printf commit）三源，**无用户手动修改**。故入口处
    ``git add -- <op_dir>``（全量 stage op_dir）精确等价于「commit codegen 产物」——入口
    时刻 diagnose/printf 尚未跑、无手动修改，op_dir 变更 = 纯 codegen。违反此前提（如有人在
    precision_debug 期间手动改 tracked 文件）会把手动修改一并 commit，破坏 diagnose/printf 的
    commit 边界。这是全量 add 安全的**唯一**依据。
    """
    # gate: 仅首轮（control.json 不存在 = init-checkpoint 未跑）
    ctrl = _control_path(state)
    if ctrl is not None and ctrl.exists():
        return
    if _operator_dir(state) is None:
        return
    from ascendc_devkit.orchestration.stages.precision_debug_a5.git_safety import (
        ensure_entry_snapshot,
    )
    ensure_entry_snapshot(state)


def _history_run_tests(history: list) -> list:
    """抽取 history 里的 run_tests 测量条目（content 带 failed/total 计数者）。

    §step-119（precision-control-ownership）：最优被测 commit 从框架独占写的 history
    测量史现算——不再依赖可被 agent 写的 best_* 字段。run_tests 条目由 RunTestsSubstage
    transition 确定性 append（含 source_commit / source_identity，测量时刻现探——
    §step-124 `_measured_source`，不抄 deploy stamp）。
    """
    out = []
    for entry in history or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("phase") != "run_tests":
            continue
        content = entry.get("content")
        if not isinstance(content, dict):
            continue
        out.append(content)
    return out


def _derive_best_metrics(history: list) -> dict:
    """从 history 测量史派生 best 计数（passed/failed/crashed/max_err）——单一实现。

    取代被删的 best_* 字段。取「已测 total 最大的一次 run_tests」的计数
    （passed = total - failed；crashed 取该测量记录的 crashed_count）。无测量 → 全 0。
    """
    runs = _history_run_tests(history)
    if not runs:
        return {"passed": 0, "failed": 0, "crashed": 0, "max_err": None}
    # 取 total 最大的一次（信息最全）；平局取最新（更接近当前代码）。
    max_total = max((int(c.get("total_count") or 0) for c in runs), default=0)
    best = next(c for c in reversed(runs)
                if int(c.get("total_count") or 0) == max_total)
    total = int(best.get("total_count") or 0)
    failed = int(best.get("failed_count") or 0)
    crashed = int(best.get("crashed_count") or 0)
    return {
        "passed": max(0, total - failed),
        "failed": failed,
        "crashed": crashed,
        "max_err": best.get("max_err"),
    }


def _best_commit_from_history(history: list) -> str:
    """从 history 测量史派生「最优被测 commit」（合法 git ref）——双路径（step-119 v8
    + step-124 锚点契约）。

    - **路径一（全过退出）**：存在全过测量（content.failed_count==0 且 total_count>0）→
      取**最近一条**全过测量的 source_commit。同一会话不会出现两个都全过的 commit
      （全过即退出），故由退出条件构造性保证，无需 argmax/tie-break。
    - **路径二（非全过退出）**：无全过测量 → 取「passed(=total-failed) 最大」者，
      **平局保留较早**（复现旧 `_update_best_metrics` 的「严格大于才更新」反向保护——
      防 diagnose 改到一半、通过数没变但代码更差时把差代码当 best 交付）。

    只认 ``source_commit``（测量时刻现探的全 sha，合法 git ref）；``{sha}-dirty-N``
    溯源标签不是 ref，不得作锚点（step-124：曾令 RepoGuard.rollback 静默 no-op）。
    缺失/空 → 返回 ""（调用方 fallback HEAD / skip）。
    """
    runs = _history_run_tests(history)
    if not runs:
        return ""
    # 路径一：最近一条全过测量的 commit
    for content in reversed(runs):
        total = int(content.get("total_count") or 0)
        failed = int(content.get("failed_count") or 0)
        if total > 0 and failed == 0:
            commit = (content.get("source_commit") or "").strip()
            if commit:
                return commit
    # 路径二：passed 最大者，平局保留较早。仅 passed>0 才候选——全 0（零正证据，
    # bad 态）返回 ""，与 _classify_best_quality 的「passed==0 = 无正证据」语义对齐，
    # 使 teardown 不会在全 bad 时回滚到无正证据的 commit。
    best_content = None
    best_passed = 0
    for content in runs:
        total = int(content.get("total_count") or 0)
        failed = int(content.get("failed_count") or 0)
        passed = max(0, total - failed)
        # 严格大于才替换 → 平局保留较早（首个命中）
        if passed > best_passed:
            best_passed = passed
            best_content = content
    if best_content is None:
        return ""
    return (best_content.get("source_commit") or "").strip()


def _classify_best_quality(dc: dict) -> str:
    """§step-96 D2: best 的绝对质量态——框架从 control.json 计数客观派生的纯函数
    （非模型判定、非比例魔法数）。

    刻度刻在**证据有无**上：passed==0 ⇔ 没有任何正证据证明 kernel 干过活（质的
    差别，结构可判定）；0<passed 则有正证据。total==0（无任何测量记录）≠ 全过
    ——未测量必须显式区分（否则 0==0 会误判 good）。

    - "good":        total > 0 且 passed == total
    - "partial":     0 < passed < total（eval 带已知失败清单，失败 case 记 0
                     不 cascade——下游经 debug_result.failing_cases 消费）
    - "bad":         total > 0 且 passed == 0（零正证据——烂中之最，不当交付物，
                     D1 直接 fallback + 结构化记录）
    - "unmeasured":  total == 0（无质量信息，不启用 D1/D2 决策，走现行路径）
    """
    passed = int(dc.get("best_passed_count") or 0)
    total = passed + int(dc.get("best_failed_count") or 0)
    if total <= 0:
        return "unmeasured"
    if passed == total:
        return "good"
    if passed == 0:
        return "bad"
    return "partial"


def _converge_check_handoff(state: "State", best_identity: str) -> "State":
    """C1（step-119）：converge 交付前自检「最终 deploy_result 是否指向最优被测代码」。

    这是**收敛动作自身的完整性自检**，不是重验质量（质量已在 run_tests 全量闭合，
    §2.9/step-96 D1/D2）。当 converge 因 rollback/deploy/smoke 失败而 keep 旧 deploy_result
    时，旧包可能指向非最优 source（部署阶段留下的坏包）——若无信号，eval 会用错包而无人察觉
    （§1.2 可诊断缺口）。

    处理：deploy_result 有 source_identity 且 != 最优 commit → WARN + 在 _debug_checkpoint
    标记 `converge_mismatch`，使 eval 报告 / 用户可见。deploy_result 无 source_identity（旧格式）
    → 不标记（诚实：无来源信息可比对）。纯读比对，无耗时。

    §step-124：比对按 **sha 前缀**——deploy stamp 是 ``{sha12}-dirty-N`` 标签（部署
    时刻），best 是测量时刻的全 sha（合法 ref）；同一 commit（纵使 deploy 时带未
    提交改动）视为一致，不同 commit 才是「eval 用错包」信号（形态不同不做精确
    字符串相等，那几乎必误报）。
    """
    if not best_identity:
        return state  # 无最优 commit 可比对 → 无标记（诚实）
    _dr = getattr(state, "deploy_result", None)
    _src = getattr(_dr, "source_identity", "") if _dr is not None else ""
    if not _src:
        return state  # deploy_result 无来源信息（旧格式/非 git）→ 无从比对
    _src_sha = _src.split("-", 1)[0]
    if _src_sha and best_identity.startswith(_src_sha):
        return state  # 同一 commit → 正常
    from ascendc_devkit.infra.logger import Logger
    Logger.warn(
        f"converge_best_commit: 交付的 deploy_result.source_identity={_src!r} ≠ "
        f"最优被测 identity={best_identity!r} — eval 将用非最优 source 的旧包 "
        f"(rollback/deploy/smoke 失败 keep 旧包路径)；debug_result 已标记 converge_mismatch")
    dc = dict(state._debug_checkpoint or {})
    dc["converge_mismatch"] = {"deploy_source": _src, "best": best_identity}
    return state.with_updates(_debug_checkpoint=dc)


def _converge_to_best_commit(state: "State", dc: dict) -> "State":
    """退出时把工作区收敛到 best_commit (通过用例最多的 commit).

    cann-bench 评测读 ``state.deploy_result`` (已编译 opp 包, cannbench_eval),
    不读 op_dir 源码; cannbench_adapt 仅在 schema 偏离时 rebuild opp. 故仅回退
    源码对评测无效 — 必须 rollback 后重新 deploy, 更新 deploy_result.

    Steps (scoped, 不动 HEAD — RepoGuard D4/R1 禁 reset --hard):
      1. ``RepoGuard.rollback(op_dir, best_commit)`` — op_dir 源码回到 best_commit.
      2. ``Deployer.deploy(state)`` — 重新编译 best_commit 源码成 opp 包.
      3. smoke 通过 → 更新 ``state.deploy_result``; 失败 → 保留旧包 + 告警 (不阻断 eval).

    ``passed`` 不收敛 (HEAD 已最优且已 deploy). best_commit 缺失 → fallback 当前 HEAD
    (入口 commit ``_entry_commit_codegen`` 之后 HEAD 含生产 codegen，rollback 安全)；
    非 git 仓库 → 跳过.
    """
    op = state.op_identity
    op_dir = _operator_dir(state)
    if op is None or not getattr(op, "repo_root", None) or not op_dir:
        return state
    # §step-119: 最优被测 commit 从 history 测量史现算（双路径：全过取最近全过 /
    # 非全过 argmax 平局较早）。history 从 control.json 读（dc 不含 history）；control
    # 不可得时 fallback dc.best_commit（transition 已从 history 派生）。
    # best 缺失（首轮超时 / init-checkpoint 未跑）→ fallback 当前 HEAD。
    # 入口 commit（_entry_commit_codegen）后 HEAD 含全部 codegen，rollback 安全。
    _ctrl = _load_control(state) if _debug_artifacts_dir(state) else None
    _hist = (_ctrl or {}).get("history") or []
    _best_from_hist = _best_commit_from_history(_hist)
    best = _best_from_hist or dc.get("best_commit") or _current_head(op.repo_root)
    if not best:
        return state  # best_commit + HEAD 都缺（非 git）→ 无 anchor，跳过收敛
    from ascendc_devkit.infra.logger import Logger
    # §step-96 D1/D2（docs/plan/converge-tail-reverification/）：收尾决策消费
    # control.json 已测质量事实——不再用 redeploy+smoke 崩溃把已知质量「重新
    # 发现」成一次部署失败事件（99c4c0 unique：best 0/20 被重部署 → smoke
    # 507035 → deploy_failed 断链 → 回退更旧产物——三次位点三次重新发现同一事实）。
    quality = _classify_best_quality(dc)
    if quality == "bad":
        # 零正证据：best 是烂中之最（相对 argmax 在全 0 计数上退化为入口
        # commit），不是交付物。对已知坏 kernel 重新 build+smoke 只会复现已知
        # 崩溃。处置：不重部署 best；保留既有 deploy_result（部署阶段已验证的
        # 产物记录）；质量事实经 debug_result（best_quality / best_passed_count
        # / failing_cases / halt_reason）结构化流转给 eval / report。
        passed = int(dc.get("best_passed_count") or 0)
        total = passed + int(dc.get("best_failed_count") or 0)
        Logger.error(
            f"converge_best_commit: best {best[:12]} quality=bad "
            f"(passed={passed}/{total}, status={dc.get('status')!r}) — "
            f"precision 未产出可用 kernel；skip best redeploy (no crash "
            f"re-discovery), keep prior deploy_result; quality facts flow "
            f"via debug_result")
        return state
    # unmeasured / good / partial → 现行重部署路径（unmeasured 时 smoke 即首测；
    # good/partial 时 smoke 崩才是真意外，既有 fallback 语义正确）。
    # 即使 HEAD == best_commit，工作区也可能有未提交残留（printf 探针、
    # 失败的 fix 编辑等）。始终 rollback + redeploy 确保 cannbench_eval
    # 拿到干净的最优 commit 编译包。
    from ascendc_devkit.infra.repo_guard import RepoGuard
    from ascendc_devkit.orchestration.stages.deploy import Deployer
    rolled = RepoGuard().rollback(op.repo_root, op_dir, best)
    if not rolled:
        Logger.warn(f"converge_best_commit: rollback to {best[:12]} failed — "
                    f"keeping current op_dir / deploy_result")
        return _converge_check_handoff(state, best)  # C1: 标记旧包可能非最优 source
    # 重新 deploy best_commit 源码 → cannbench_eval 拿到最优 commit 的包.
    try:
        new_deploy, err = Deployer().deploy(state)
    except Exception as e:  # redeploy 自身崩溃 → 不阻断, eval 用旧包
        Logger.error(f"converge_to_best_commit: redeploy raised {e} — "
                     f"eval will use the prior deploy_result")
        return _converge_check_handoff(state, best)  # C1: 标记旧包可能非最优 source
    if new_deploy and new_deploy.smoke_passed:
        Logger.action("converge_best_commit",
                      f"op_dir → {best[:12]} + redeployed (smoke ok); "
                      f"eval will run the best-passed-count commit")
        return state.with_updates(deploy_result=new_deploy)
    # §step-96 D3: smoke 失败按**死亡位置**二分（codegen.classify_smoke_failure_phase
    # 同款结构判别，§1.15 单点）——「launch 成功后设备侧死亡」（507035 族）是
    # 质量信号而非部署失败：产物装得上、调得动，崩在 kernel 执行期，归
    # precision/eval 的质量预期。eval 本不以 smoke_passed 为门（cannbench_eval
    # 明示 NOT a gate），放行**新鲜的** deploy_result（precision 期间的
    # redeploy 可能已覆盖共享 OPP 目录，旧记录的 install_path 文件已非其原始
    # 产物——新鲜包才是安装一致态）；已知失败预期经 debug_result 流转。
    # host 侧失败（launch 之前，EZ/561xxx 族）= 部署完整性失败，保留现行
    # fallback 语义。
    from ascendc_devkit.orchestration.stages.codegen import (
        classify_smoke_failure_phase,
    )
    phase = (classify_smoke_failure_phase(err)
             if err is not None else None)
    if new_deploy is not None and phase == "kernel":
        Logger.warn(
            f"converge_best_commit: redeploy of {best[:12]} smoke died "
            f"POST-LAUNCH (device-side, phase=kernel) — quality signal, not "
            f"a deployment failure (best_quality={quality}); accepting the "
            f"fresh deploy_result so eval runs a consistent install, with "
            f"known-fail expectations via debug_result")
        return state.with_updates(deploy_result=new_deploy)
    Logger.error(f"converge_best_commit: redeploy of {best[:12]} failed smoke "
                 f"(err={getattr(err, 'error_type', None)}) — eval falls back "
                 f"to prior deploy_result")
    return _converge_check_handoff(state, best)  # C1: 标记旧包可能非最优 source


def _sync_debug_result(state: "State", dc: dict) -> "State":
    """Materialize PrecisionDebugResult into State at a terminal state (runlog 冲突2).

    Replaces the deleted orchestrator's ``write-debug-result.py`` + the old
    ``PrecisionDebugStage.transition`` file parse. Downstream consumers need
    ``state.debug_result``: perf's gate ``requires=["debug_result"]`` and the
    dispatcher's terminal message reads ``debug_result.passed/max_diff``.

    Terminal conditions (any one triggers materialisation):
      - status=='passed' (all cases green)
      - rounds > max_iterations (exhausted)
      - upstream_signal（diagnose 入口判据上报上游缺陷 — codegen/test_design/golden/
        deploy/framework/env 错，非 precision）
    """
    # framework 侧计时：每个 transition 更新 elapsed_sec → control.json
    cp = _load_control(state)
    _update_elapsed_sec(state, cp)
    dc["elapsed_sec"] = cp.get("elapsed_sec", 0.0)  # 回写 dc, resolve_condition 读取

    max_iterations = dc.get("max_iterations", precision_debug_max_iterations())
    rounds = dc.get("rounds", 0)
    # §P3 减法: upstream 由 diagnose 入口判据上报（upstream_signal），替代 scope_guard
    # 的 scope_verdict=='upstream'。
    is_upstream = bool(dc.get("upstream_signal"))
    # §judgment-ownership (P5): stalled = diagnose 尽力后假设空间穷尽。与 upstream 同为
    # 终止态，但语义不同——upstream 是上游缺陷（stubbed，无 best_commit 收敛）；
    # stalled 是模型尽力但未修好（保留已修部分如 ShiftF32，收敛到 best_commit）。
    is_stalled = bool(dc.get("stalled"))
    terminal = (dc.get("status") == "passed") or (
        rounds > 0 and rounds > max_iterations) or is_upstream or is_stalled
    # §time-budget: 墙钟预算耗尽也是终止态 (与 resolve_condition 超时→exhausted 一致).
    if not terminal:
        terminal = _time_budget_exhausted(dc)
    if not terminal:
        return state
    # upstream halt — no best_commit to converge to; expose the defect directly.
    # stalled 尽力 — 保留已修部分，收敛到 best_commit（与 exhausted 同）。
    if not is_upstream:
        state = _converge_to_best_commit(state, dc)
        # §step-91 P5: 声明本 pass 已收敛——GE 升级分支据此跳过重复收敛（业务语义
        # 而非条件名代理，§1.10）。abort/timeout 早退未到此块 → 保持 False →
        # GE 兜底收敛保留。
        state = state.with_updates(_converged_this_pass=True)
        # Write final report at terminal state (ensures report exists even
        # when best_passed_count never improved — captures the last state).
        _write_precision_report(cp, _debug_artifacts_dir(state))
    passed = dc.get("status") == "passed" and not is_upstream
    # §P3 减法 visibility: upstream halt 时 surface upstream_stage + upstream_reason
    # 供 dispatcher 终端消息 + log 说明为何 precision_debug 拒绝继续。
    halt_reason = ""
    if is_upstream:
        upstream_stage = dc.get("upstream_stage", "") or ""
        upstream_reason = dc.get("upstream_reason", "") or ""
        parts = [p for p in [upstream_stage, upstream_reason] if p]
        halt_reason = ": ".join(parts) if parts else "upstream defect (no detail)"
        from ascendc_devkit.infra.logger import Logger
        Logger.error(
            f"precision_debug HALTED — upstream defect in [{upstream_stage or 'unknown'}]: "
            f"{upstream_reason or 'no detail'}"
        )
    elif is_stalled:
        # §judgment-ownership (P5): stalled = diagnose 尽力后假设空间穷尽。surface
        # self_check 自检结论（供人工接续），与 exhausted（预算耗尽）区分。
        sd = dc.get("stalled_detail") or {}
        if isinstance(sd, str):
            sd = {}  # 兼容旧形态（无 self_check 的纯文本）
        sc = sd.get("self_check") or [] if isinstance(sd, dict) else []
        passed_checks = sum(1 for c in sc if isinstance(c, dict) and c.get("passed"))
        total_checks = len(sc) if isinstance(sc, list) else 0
        exhausted_reason = (sd.get("exhausted_reason") if isinstance(sd, dict)
                            else "") or "assumption space exhausted, manual review needed"
        from ascendc_devkit.infra.logger import Logger
        Logger.warn(
            f"precision_debug STOPPED — diagnose exhausted hypothesis space "
            f"(self_check {passed_checks}/{total_checks} passed); {exhausted_reason}")
        halt_reason = (
            f"diagnose hypothesis space exhausted "
            f"(self_check {passed_checks}/{total_checks}): {exhausted_reason}")
    # §step-119: best_* 产物从 history 现算兜底（dc 不含 history；dc.best_* 由
    # transition 派生填充，graph 直调时无派生值 → history 兜底）。
    _hist = (cp.get("history") if cp else None) or []
    _best_metrics = _derive_best_metrics(_hist)
    _best_ident = _best_commit_from_history(_hist) or str(dc.get("best_commit") or "")
    _best_passed = (int(dc["best_passed_count"])
                    if dc.get("best_passed_count") is not None
                    else _best_metrics["passed"])
    _best_max_err = (dc.get("best_real_max_err")
                     if dc.get("best_real_max_err") is not None
                     else _best_metrics["max_err"])
    dr = PrecisionDebugResult(
        passed=passed,
        max_diff=float(_best_max_err) if _best_max_err is not None else 0.0,
        best_commit=_best_ident,
        # §step-96 D2: 0 是合法计数（bad ⇔ passed==0）——`or -1` 会把 0 吞成
        # 「未初始化」，使 bad 态的质量事实失真；仅 None 才是未初始化。
        best_passed_count=(_best_passed if _best_passed is not None else -1),
        failing_cases=list(dc.get("failing_cases", [])),
        iterations_used=int(rounds or 0),
        stubbed=is_upstream,    # upstream halt — not a real precision pass/fail
        halt_reason=halt_reason,
        # §step-96 D2: 绝对质量态随产物结构化流转（§2.10——收尾链消费字段而非
        # 重新测量）。
        best_quality=_classify_best_quality(dc),
    )
    updates: dict = {
        "debug_result": dr,
        "debug_iterations": dr.iterations_used or 1,
        # §P3 减法: upstream_stage / upstream_reason 供 dispatcher 终端消息（从
        # _debug_checkpoint 读取，与 debug_result 一并透出）。
    }
    if passed:
        updates["last_error"] = None
    return state.with_updates(**updates)


# —— shared sub-stage base ————————————————————————————————————————————————

class _PrecisionDebugSubstage(_DesignSubstage):
    """Common: locate the phase sub-agent's working dir + build its param prompt.

    Each phase sub-agent (run_tests/diagnose/fix/printf_location) has its own
    ``.claude/agents/ascendc-precision-<phase>.md`` definition (role + hard rules)
    AND its own per-phase skill (``.claude/skills/ascendc-precision-<phase>/``,
    carrying the core method via SKILL.md + schema, §2.1/§2.2/§2.7). The
    orchestration injects that skill by leading the spawn's first message with
    ``/<skill>`` (``primary_skill`` → backend ``render_skill_injection``); the
    prompt here only passes task parameters (control path, phase-json path,
    operator dir, CLI commands) — mirroring the deleted orchestrator's dispatch
    prompt (§4.3: one spawn, params-only).

    Half-adhere (54-*.md §3): inherits ``_DesignSubstage`` for shared hooks
    (``_assigned_skill`` / ``artifact_contract`` via ``STAGE_SKILL_MAP`` and
    ``SchemaLoader``) but does NOT use the design materialization chain
    (``_materialize_inputs`` / ``_parse_single`` State↔file). precision_debug's
    file relay is sub-agent autonomous read/write of ``{debug_artifacts_dir}/``; the
    FW reads control.json only for routing. ``actions()`` is fully overridden
    here (no relocation gate, no hw_params materialization) so design machinery
    never leaks into a paradigm it doesn't apply to.
    """

    name: str = ""
    agent_name: str = ""
    fail_strategy = "continue"   # routing is driven by resolve_condition, not halt
    default_max_iterations = 1   # each dispatch is single-pass; the GROUP loops
    needs_iteration_safety_net = False

    # P13 (step-116)：迭代持卡机制已拆除——op 级租约（dispatch 边界一借一还）
    # + 双变量 pin 结构性覆盖全部子树；本类原先按 §1.10 声明的
    # iteration_card_lease 会在同一池内与 op 租约互相死锁，随 span 级通路
    # 一并退役（§2.5）。

    # Per-phase schema (loaded from this sub-stage's assigned skill ``schema/``
    # dir via SchemaLoader). The phase-json artifact the sub-agent owns; used by
    # Stage 3 load-time contract validation, not by routing.
    _schema_files: list[str] = []

    # Lazy-init cache for SchemaLoader contract — keyed by
    # (skill, tuple(schema_files)), populated on first _validate_phase_json call.
    _schema_contract_cache: object = None

    def teardown(self, state: "State", *, interrupt_reason: str) -> "State":
        """D5 (hard-timeout): on interruption, roll op_dir back to the last
        fully-verified-good commit (``best_commit``).

        Uses ``RepoGuard.rollback`` (``git checkout <best> -- op_dir`` + ``git clean
        -fd -- op_dir``, scoped op_dir, HEAD untouched) — same semantics as
        ``_converge_to_best_commit``, compliant with RepoGuard D4/R1 (no whole-repo
        ``reset --hard``). Inherited by every phase substage (any phase interrupted
        rolls back). Idempotent + best-effort + seconds-scale (<30s)."""
        from ascendc_devkit.infra.logger import Logger
        from ascendc_devkit.infra.repo_guard import RepoGuard
        cp = _load_control(state)
        # §step-119: best 从 history 测量史现算（不再读可写 best_commit 字段）。
        # 语义不变：只有「全量验证过的最优」才回滚，丢弃未验证半成品。history 无
        # run_tests 测量 → best 空 → 走下方「无 anchor → 跳过」保守路径。
        best = _best_commit_from_history((cp or {}).get("history") or []) if cp else None
        op_dir = _operator_dir(state)
        if not best or not op_dir:
            # no known-good anchor yet / no op_dir → nothing to roll back.
            # Deliberately NOT falling back to HEAD here (unlike
            # _converge_to_best_commit, which falls back to HEAD when best_commit
            # is absent): teardown is a hard-kill path that can fire on the very
            # first run before _entry_commit_codegen has committed the codegen
            # products. At that moment HEAD may not contain codegen, so a HEAD
            # fallback + `clean -fd` would delete them. converge falls back to
            # HEAD safely because it runs only after the entry commit (best_commit
            # / HEAD both contain codegen); teardown must stay conservative.
            return state
        repo_root = (state.op_identity.repo_root
                     if state.op_identity and state.op_identity.repo_root
                     else op_dir)
        # best-effort（与 _converge_to_best_commit 包裹 deploy 一致）：硬超时收尾
        # 路径绝不能因 rollback 二次抛异常而打断 runner 的中断处理。RepoGuard.rollback
        # 自身 best-effort（_git 捕获常见异常返 None），此 try/except 是防御未预期异常
        # 的 last resort（§1.2 可诊断：warn 记录，不静默吞到下游）。
        try:
            rolled = RepoGuard().rollback(repo_root, op_dir, best)
        except Exception as e:  # noqa: BLE001 — 硬超时收尾 last resort
            Logger.warn(
                f"precision-debug teardown: rollback raised {e} — "
                f"keeping current op_dir (interrupt_reason={interrupt_reason})")
            return state
        if rolled:
            Logger.warn(
                f"precision-debug teardown ({interrupt_reason}): rolled back op_dir "
                f"to best_commit {best[:8]} (checkout+clean, HEAD untouched)")
        else:
            Logger.warn(
                f"precision-debug teardown: rollback to {best[:8]} failed — "
                f"keeping current op_dir")
        return state

    def _phase_filename(self) -> str:
        """The on-disk phase-json filename this sub-stage's agent owns."""
        return self._schema_files[0] if self._schema_files else ""

    def _skill_dir(self) -> str:
        """Absolute path to this sub-stage's assigned skill dir (for scripts).

        Repo-self-contained (§1.7): resolved from the package root, never
        ``~/.claude``. Empty when no skill is assigned."""
        assigned = self._assigned_skill()
        if not assigned:
            return ""
        project_root = Path(__file__).resolve().parents[4]
        return str(project_root / ".claude" / "skills" / assigned)

    def _workspace_dir(self, state: "State") -> str:
        ws = getattr(state, "_workspace", None)
        return str(ws.dir) if ws is not None else ""

    def _format_resume_status(self, state: "State") -> str:
        """§方案F: resume 状态感知段（prompt 注入）。基类空（run_tests 无 resume 感知）；
        DiagnoseSubstage 覆盖返回「被杀未写进度」或「续跑 + 上次进度」提示。"""
        return ""

    def _common_context(self, state: "State") -> dict:
        op_dir = _operator_dir(state)
        ws_dir = self._workspace_dir(state)
        ctrl = _control_path(state)
        # Round-suffixed path — the agent writes HERE (never overwrites).
        phase = _phase_path(state, self._phase_filename(), round_suffix=True)
        # Non-suffixed "latest" path — for cross-phase reads.
        phase_latest = _phase_path(state, self._phase_filename(), round_suffix=False)
        ct = (state.codegen_manifest or {}).get("callable_target")
        op_name = (state.op_name
                   or (state.op_identity.spec.name if state.op_identity else ""))
        # P13 (step-116)：命令不带卡前缀——agent shell 经 serve 继承已带双变量
        # pin，内层 CLI 的 resolve_op_card 从 pin env 读回同一张卡；把变量名
        # 写进命令串只会制造卡感知（零卡知识裁定延伸到变量名）。
        # iter_n: auto-incrementing run-cases iteration number, so each
        # invocation writes to iter-0, iter-1, … instead of overwriting.
        cp = _load_control(state)
        iter_n = int(cp.get("run_iter_counter", 0))
        return {
            "control_path": str(ctrl) if ctrl else "",
            "phase_json_path": str(phase) if phase else "",
            "phase_json_latest_path": str(phase_latest) if phase_latest else "",
            "operator_dir": str(op_dir) if op_dir else "",
            "debug_artifacts_dir": str(_debug_artifacts_dir(state)) if _debug_artifacts_dir(state) else "",
            "op_name": op_name,
            "skill_dir": self._skill_dir(),
            "phase_filename": self._phase_filename(),
            # §step-88: 设计产物路径（staging 同源）——diagnose 三层认知的设计层输入。
            # 无 workspace/无 staging → {}（TUI adapter 场景优雅降级）。
            "design_paths": _design_paths(state),
            "iter_n": iter_n,
            "golden": {
                "path": str(state.golden_path) if state.golden_path else "",
                "entry": state.golden_entry or "",
                "input_type": state.golden_input_type or "",
            },
            "build_command": (f"ascendc-devkit redeploy "
                              f"--workspace {ws_dir}") if ws_dir else "",
            "test_command": (f"ascendc-devkit run-cases "
                             f"--workspace {ws_dir}") if ws_dir else "",
            "callable_target": ct,
            "design_target_chip": state.design_target_chip,
            "debug_result_contract": _DEBUG_RESULT_CONTRACT_REF,
            # §方案F (docs/plan/diagnose-upstream-misattribution): resume 状态感知——
            # 只有 diagnose 需要（被杀/resume 后感知自身进度），run_tests 不需要（基类空）。
            "resume_status": self._format_resume_status(state),
            # §weak-model A: 框架打回原因（stalled 缺 self_check 等）——round 匹配
            # 当前轮才渲染（文件版 consumed-once，见 _reject_reason_block）。
            "reject_reason": _reject_reason_block(
                cp, current_round=int(cp.get("rounds", 0) or 0)),
            # §weak-model B: 产物缺失定向提示（design _missing_artifact_error 写入
            # State.user_feedback 的路径指引）——「上次产物问题」段的ctx 通道。
            "product_feedback": getattr(state, "user_feedback", "") or "",
            # precision_debug loop knobs — injected into init-checkpoint CLI so
            # control.json seeds from the GLOBAL config (orchestration-config.json
            # via runtime_config) on first run; hand-editing control.json after
            # overrides (the substage reads control.json, not these).
            "precision_max_iterations": precision_debug_max_iterations(),
            "precision_max_attempts_per_case": precision_debug_max_attempts_per_case(),
            "precision_time_budget_sec": precision_debug_time_budget_sec(),
        }

    def actions(self, state: "State", iteration: int = 1):
        # 入口全量 commit codegen（首轮，幂等）：让 best_commit/HEAD 含全部 codegen，
        # 后续 converge/teardown 的 rollback 才安全（详见 _entry_commit_codegen）。
        self._phase_setup(state)
        # P13 (step-116)：本 op 全程持卡由 dispatch 的 op 级租约承担。
        skill = self._assigned_skill()
        ctx = self._common_context(state)
        return [SpawnAgent(
            agent_name=self.agent_name,
            prompt=self._build_prompt(ctx, iteration),
            context=ctx,
            skills=skill_allowlist(skill),       # primary + tail-calls (§2.1)
            primary_skill=skill,                 # D2: backend delivers /<skill>
            working_dir=_operator_dir(state),
            # P0 重构遗漏：与其他 stage（codegen/perf/cannbench_adapt）对齐，
            # 让 backend 的 _load_project_config walk-up 终点能锚定 repo_root。
            # 即使 op_identity.repo_root 为 None（batch 跑批场景），opencode
            # backend 还有 devkit_root 兜底锚点，不会丢失 provider 配置。
            repo_root=(state.op_identity.repo_root
                       if state.op_identity else None),
            stage_name="precision_debug",        # outer-stage attribution
        )]

    def _phase_setup(self, state: "State") -> None:
        """Sub-stage 公共前置副作用（§judgment-ownership N1：run_tests 纯 Python 化后
        actions() 覆盖版与基类 SpawnAgent 版共用，避免复制漂移）：
        ① _entry_commit_codegen（首轮 git commit codegen 产物，保 rollback 安全）；
        ② _precision_start_ts 起表（§time-budget 首个子阶段 actions 触发）；
        ③ _advance_phase_counter（每 spawn 推进一次 → _phase_path round 后缀稳定）。
        """
        _entry_commit_codegen(state)
        global _precision_start_ts
        if _precision_start_ts is None:
            _precision_start_ts = time.time()
        _advance_phase_counter(state)

    def _build_prompt(self, ctx: dict, iteration: int) -> str:
        op_dir = ctx["operator_dir"] or "<operator_dir>"
        ctrl = ctx["control_path"] or "<control_path>"
        phase_path = ctx["phase_json_path"] or "<phase_json_path>"
        skill_dir = ctx["skill_dir"]
        return self._phase_prompt(ctx, op_dir, ctrl, phase_path, skill_dir, iteration)

    def _phase_prompt(self, ctx, op_dir, ctrl, phase_path, skill_dir, iteration) -> str:
        raise NotImplementedError

    def _append_history(self, state: "State", content: dict) -> dict:
        """Framework-authored history entry — guarantees one entry per spawn,
        UTC timestamp, and correct phase/round attribution.

        The agent writes its summary to ``_summary`` inside its per-phase JSON
        (the round-suffixed file).  Transition calls this method to promote
        that summary into a framework-controlled history record so the
        agent's output quality (missing timestamps, duplicate entries,
        wrong phase) can never corrupt the audit trail.

        Returns the updated control.json dict (also written to disk).
        """
        from datetime import datetime, timezone
        cp = _load_control(state)
        entry = {
            "phase": self.name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "round": _current_round(state),
            "content": content,
        }
        cp.setdefault("history", []).append(entry)
        _save_control(state, cp)
        return cp

    def _read_agent_summary(self, state: "State") -> dict:
        """Read the ``_summary`` dict the agent wrote into its round-suffixed
        phase JSON.  Returns {} when the file is absent or unreadable."""
        p = _phase_path(state, self._phase_filename(), round_suffix=True)
        if p is None or not p.exists():
            return {}
        try:
            phase_data = json.loads(p.read_text(encoding="utf-8"))
            return phase_data.get("_summary", {}) or {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _read_phase_data(self, state: "State") -> dict:
        """Read this spawn's round-suffixed phase JSON — full top-level dict
        (schema-required paths + ``_summary``), not just ``_summary``.
        Returns {} when the file is absent or unreadable."""
        p = _phase_path(state, self._phase_filename(), round_suffix=True)
        if p is None or not p.exists():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _validate_phase_json(self, state):
        """Load-time contract validation with auto-repair (§1.3 / §12.2).

        Phase JSON must conform to its skill schema.  When required keys are
        missing (agent hallucination / partial write), auto-fill safe defaults
        with a warning and write back — mirroring ``_ensure_control_contract``.
        Only truly unrecoverable violations (non-JSON, wrong-type values that
        can't be coerced, forbidden format) raise ``PrecisionDebugContractError``.

        The schema contract is cached on first load — identical across transitions
        for the same substage instance (skill + schema files never change).
        """
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
        # Lazy-init cache: load contract once per substage instance
        if self._schema_contract_cache is None:
            try:
                self._schema_contract_cache = SchemaLoader.load_contract_from_skill(
                    self._assigned_skill(), self._schema_files)
            except Exception as exc:
                Logger.warn(f"[PD-CONTRACT] schema load failed for "
                            f"{self._assigned_skill()}/{self._schema_files}: {exc} "
                            f"— skipping per-phase validation (non-blocking)")
                return
        _, errors = self._schema_contract_cache.parse(
            {self._phase_filename(): raw_text})
        if errors:
            # —— §12.2 auto-repair: try to fill missing keys with safe defaults ——
            phase_fn = self._phase_filename()
            defaults = _PHASE_DEFAULTS.get(phase_fn)
            if defaults:
                try:
                    phase_data = json.loads(raw_text)
                except (json.JSONDecodeError, TypeError):
                    # Unparseable JSON is unrecoverable — raise original errors
                    raise PrecisionDebugContractError(
                        f"[PD-CONTRACT] {phase_fn} failed schema validation "
                        f"(unparseable): " + "; ".join(errors))
                repaired = False
                for key, default_val in defaults.items():
                    if key not in phase_data:
                        phase_data[key] = default_val
                        repaired = True
                if repaired:
                    Logger.warn(
                        f"[PD-CONTRACT] {phase_fn} missing required key(s) "
                        f"— auto-initializing to safe defaults "
                        f"(likely agent hallucination / partial write — see §12.2).")
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(json.dumps(phase_data, indent=2,
                                            ensure_ascii=False), encoding="utf-8")
                    # Re-validate the repaired JSON
                    _, errors = self._schema_contract_cache.parse(
                        {phase_fn: p.read_text(encoding="utf-8")})
            if errors:
                raise PrecisionDebugContractError(
                    f"[PD-CONTRACT] {phase_fn} failed schema validation: "
                    + "; ".join(errors))

    def _write_phase_relay(self, state: "State", relay: dict) -> None:
        """§judgment-ownership (N1): 框架确定性写 phase JSON（round-suffixed）。

        run_tests 纯 Python 后无 agent 写 precision_run_tests.json——框架在 transition
        写 relay（last_result_json / last_run_log）。原子写 round-suffixed 文件（阶段
        产物归档），随后 _sync_phase_latest 同步到 non-suffixed 'latest' 供 diagnose
        跨 phase 读。relay 契约同 _PHASE_DEFAULTS（"precision_run_tests.json"）。
        """
        round_path = _phase_path(state, self._phase_filename(), round_suffix=True)
        if round_path is None:
            return
        round_path.parent.mkdir(parents=True, exist_ok=True)
        existing = {}
        try:
            existing = json.loads(round_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {}
        existing.update(relay)
        round_path.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")

    def _sync_phase_latest(self, state: "State") -> None:
        """Copy the round-suffixed phase JSON → non-suffixed 'latest' path.

        Cross-phase reads (e.g. diagnose reading precision_run_tests.json)
        always use the non-suffixed path.  After the agent writes to the
        round-suffixed file, this call copies it so downstream consumers
        see the latest data.  Idempotent — a missing round file is silently
        skipped (the agent may have failed before writing anything).
        """
        import shutil
        from ascendc_devkit.infra.logger import Logger
        round_path = _phase_path(state, self._phase_filename(), round_suffix=True)
        latest_path = _phase_path(state, self._phase_filename(), round_suffix=False)
        if round_path is None or latest_path is None:
            return
        if not round_path.exists():
            Logger.warn(f"[PD-RELAY] {round_path} round file missing — phase "
                        f"json not synced (agent may have failed before writing)")
            return
        try:
            shutil.copy2(round_path, latest_path)
        except OSError as exc:
            Logger.warn(f"[PD-RELAY] copy {round_path} → {latest_path} failed: {exc}")

    # —— §abort: agent-abort annealing helpers ————————————————————————————

    def _agent_produced_output(self, state: "State") -> bool:
        """True iff this spawn's round-suffixed phase JSON exists, parses, and is
        non-empty — i.e. the agent ran to completion and wrote real output.

        Abort判据 (03-impl S2a): the file is the agent's only durable proof of
        progress. Absent / corrupt / empty-shell ``{}`` all mean the agent died
        before producing usable output (context limit, infra crash, timeout).

        §P6-FIX: if round-suffixed file is missing but the non-suffixed "latest"
        file has content (agent wrote to latest ignoring round-suffix instruction),
        auto-copy latest→round-suffixed and return True with a WARN.  把成功误判
        为失败是最坏情形；last-resort 宽容兜底优于误 abort（§1.2 组合策略）。
        """
        p = _phase_path(state, self._phase_filename(), round_suffix=True)
        if p is not None and p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return False
            return bool(data)
        # §P6-FIX: round-suffixed missing — check latest as fallback.
        latest = _phase_path(state, self._phase_filename(), round_suffix=False)
        if latest is None or not latest.exists():
            return False
        try:
            data = json.loads(latest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if not data:
            return False
        # Latest has real content; agent wrote to wrong path.  Auto-repair:
        # copy latest→round-suffixed so downstream (_validate_phase_json,
        # _read_agent_summary, _sync_phase_latest) all find it normally.
        if p is not None:
            import shutil
            from ascendc_devkit.infra.logger import Logger
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(latest, p)
                Logger.warn(
                    f"[PD-P6-FIX] {self._phase_filename()}: round-suffixed "
                    f"file missing but latest has content — auto-copied "
                    f"latest→round ({latest.name} → {p.name}). "
                    f"Agent wrote to wrong path; see prompt 读写契约.")
            except OSError as exc:
                Logger.warn(f"[PD-P6-FIX] auto-copy latest→round failed: {exc}")
                return False
        return True

    def _bump_consecutive_aborts(self, state: "State") -> int:
        """Increment ``consecutive_aborts`` in control.json; return the new value.

        RunTests (which owns its own richer abort path) calls this directly; the
        other sub-stages go through :meth:`_handle_abort`.
        """
        cp = _load_control(state)
        n = int(cp.get("consecutive_aborts", 0)) + 1
        cp["consecutive_aborts"] = n
        _save_control(state, cp)
        return n

    def _reset_consecutive_aborts(self, state: "State") -> int:
        """Clear ``consecutive_aborts`` to 0 (a normal spawn broke the streak).
        Skips the disk write when already 0. Returns 0."""
        cp = _load_control(state)
        if int(cp.get("consecutive_aborts", 0)) != 0:
            cp["consecutive_aborts"] = 0
            _save_control(state, cp)
        return 0

    def _resolve_abort_condition(self, dc: dict) -> str | None:
        """Route an abort state. Returns a transition-table condition or None.

        Priority: ``consecutive_aborts >= threshold`` → ``abort_exhausted``
        (§abort-relay: 非 run_tests 阶段路由 run_tests 走主循环，不直接退出组；
        dc 保留触发值，cp 已在 _handle_abort 清零）；else when this spawn
        aborted → ``agent_aborted`` (self-loop corrective re-spawn)；else None
        (fall through to the stage's normal routing).
        """
        if int(dc.get("consecutive_aborts", 0)) >= _ABORT_EXHAUST_THRESHOLD:
            return "abort_exhausted"
        if dc.get("agent_aborted"):
            return "agent_aborted"
        return None

    def _handle_abort(self, state: "State", *, bump_counters: bool = False) -> "State":
        """Common agent-abort transition body for the non-RunTests sub-stages.

        Bumps ``consecutive_aborts`` (annealing); optionally bumps ``run_iter_counter``
        so the stage's own stop-loss still bounds re-spawns (redeploy-heavy, so an
        abort still burns a budget slot); appends an audit history entry; sets the
        transient ``agent_aborted`` flag; returns a state whose ``_debug_checkpoint``
        routes via :meth:`_resolve_abort_condition`. ``_sync_debug_result``
        materializes nothing (abort is non-terminal).
        """
        cp = _load_control(state)
        n = int(cp.get("consecutive_aborts", 0)) + 1
        # §abort-reset: 熔断触发即清零（cp）——abort_exhausted 路由 run_tests 走
        # 主循环后从 0 重计，否则单链累计会在后续正常修复路径上误判熔断。
        # dc 保留触发值供 _resolve_abort_condition 判定（见下）。
        cp["consecutive_aborts"] = 0 if n >= _ABORT_EXHAUST_THRESHOLD else n
        if bump_counters:
            cp["run_iter_counter"] = int(cp.get("run_iter_counter", 0)) + 1
        _save_control(state, cp)
        cp = self._append_history(state, {"aborted": True})
        dc = _extract_debug_checkpoint(cp)
        dc["consecutive_aborts"] = n  # dc 覆盖回触发值（cp 已清零）
        dc["agent_aborted"] = True
        dc["rounds"] = (state._debug_checkpoint or {}).get("rounds", 0)
        self._sync_phase_latest(state)
        state = state.with_updates(_debug_checkpoint=dc)
        return _sync_debug_result(state, dc)

    # Each sub-stage always writes _debug_checkpoint in transition() (even
    # non-terminal).  debug_result / debug_iterations are terminal-only and
    # belong to the CompositeGroup's output_contract_override — placing them
    # here causes every intermediate sub-stage to fail the contract check.
    def input_contract(self) -> StageIOContract:
        return StageIOContract(
            requires=["op_identity", "requirement", "golden_path",
                      "deploy_result", "codegen_manifest", "design_target_chip"],
            optional=["repo_root", "npu_id", "golden_entry", "golden_input_type",
                      "test_cases", "cases_path", "profile", "enable_stubbed"])

    def output_contract(self) -> StageIOContract:
        return StageIOContract(provides=["_debug_checkpoint"])


# —— RunTestsSubstage —————————————————————————————————————————————————

class RunTestsSubstage(_PrecisionDebugSubstage):
    """Phase: run the precision suite, parse results, write failed_case_queue.

    First child of the group → owns control.json init (the deleted orchestrator's
    job): when control.json is absent the sub-stage runs ``init-checkpoint.py``
    (via RunMeasure, deterministic — no LLM). Increments the framework-side round
    counter each run (the loop's semantic bound; ``rounds > max_iterations`` → exhausted).

    §judgment-ownership (N1): run_tests 从 LLM agent 收敛为纯 Python 测量——actions()
    返回 RunMeasure（确定性执行 run-cases + 脚本），不再 spawn agent。判断失败性质
    （局部/算法级/上游）归 diagnose Step 0。node 结构保留（graph 构造性"先测量再诊断"，
    §2.9）；`uninterruptible=True` 对齐 CannbenchEvalStage——长 run-cases 不被 runner
    阶段 deadline 抢占。
    """

    name = "run_tests"
    # agent_name 删除（不再 spawn agent）
    _schema_files = ["precision_run_tests.json"]   # 保留：_phase_filename() 依赖
    uninterruptible = True

    def actions(self, state: "State", iteration: int = 1):
        """§judgment-ownership (N1): run_tests 纯 Python 测量——返回 RunMeasure（确定性
        执行 run-cases + 脚本），不再 spawn LLM agent。基类副作用（entry-commit /
        time-budget 起表 / phase_counter）经 _phase_setup 保留。判断失败性质归 diagnose
        Step 0（N2）。"""
        self._phase_setup(state)
        # §step-95: 持卡由 runner card_iteration_lease 声明式持有（基类声明）。
        ctx = self._common_context(state)
        ctrl = _control_path(state)
        dbg = _debug_artifacts_dir(state)
        op_dir = _operator_dir(state)
        iter_n = int((_load_control(state) or {}).get("run_iter_counter", 0))
        cmd = self._build_measure_command(ctx, ctrl, dbg, op_dir, iter_n)
        return [RunMeasure(command=cmd, working_dir=op_dir,
                           timeout=self._measure_timeout(state))]

    def _validate_phase_json(self, state):
        """Phase JSON 由框架写（transition 确定性写）——schema 校验不适用（无 agent）。
        §N1: _assigned_skill() 返回 None（STAGE_SKILL_MAP 已删 run_tests），基类
        _validate_phase_json 会 load_contract_from_skill(None) → TypeError warn，no-op 消除。
        diagnose 仍走基类（map 仍指向 ascendc-precision-diagnose）。"""
        return

    def _build_measure_command(self, ctx: dict, ctrl, dbg, op_dir, iter_n: int) -> str:
        """构造 RunMeasure 的 shell 命令（跑 run-cases + 建队列）。

        首轮（control.json 不存在）前置 init-checkpoint.py；每轮跑 test_command →
        build-failed-case-queue.py 建队列。`set -e` 保证 run-cases 非零退出 → 整条命令
        rc≠0 → measure_result.rc≠0 → transition abort 路径。`for` 循环实现大 shape
        超时放大后的重跑（build-failed-case-queue.py 打印 AMPLIFIED: 时同 iter 重跑）。
        shlex.quote 包路径防注入。
        """
        import shlex
        scripts = _RUN_TESTS_SCRIPTS_DIR
        op_dir_q = shlex.quote(str(op_dir)) if op_dir else ""
        dbg_q = shlex.quote(str(dbg)) if dbg else ""
        ctrl_q = shlex.quote(str(ctrl)) if ctrl else ""
        test_cmd = ctx.get("test_command") or ""
        build_cmd = ctx.get("build_command") or ""
        op_name = ctx.get("op_name") or ""
        max_iter = int(ctx.get("precision_max_iterations") or 0)
        max_attempts = int(ctx.get("precision_max_attempts_per_case") or 0)
        time_budget = int(ctx.get("precision_time_budget_sec") or 0)
        # 首轮 init（control.json 不存在时）
        init_part = ""
        if ctrl is None or not (ctrl.exists() if hasattr(ctrl, 'exists') else False):
            init_part = (
                f"[ -f {ctrl_q} ] || python3 {shlex.quote(str(scripts / 'init-checkpoint.py'))} "
                f"--operator-dir {op_dir_q} --output-dir {dbg_q} "
                f"--test-command {shlex.quote(test_cmd)} --build-command {shlex.quote(build_cmd)} "
                f"--compile-work-dir {op_dir_q} "
                f"--op-name {shlex.quote(op_name)} --max-iterations {max_iter} "
                f"--max-attempts-per-case {max_attempts} --time-budget-sec {time_budget}\n"
            )
        result_json = f"{dbg_q}/run_tests_iter-{iter_n}/result.json"
        # §step-89: deploy-precondition（每轮幂等）——测量前构造性保证 last_deploy.json
        # 可用（P1/P2/P3 根因修复，见 _deploy_precondition docstring）。
        precondition = _deploy_precondition(dbg, build_cmd)
        # 注意转义分层：printf 格式串内的 '%s\\n' 是字面 \n（printf 自己解释成换行，
        # 正确）；行间分隔必须是真换行 \n——写成 \\n 会把三行 shell 粘成一行致
        # 「expecting done」语法错（ST 干跑实证）。
        run_part = (
            "for i in 1 2 3; do\n"
            f"  {test_cmd} --iter {iter_n} --label run_tests\n"
            f"  out=$(python3 {shlex.quote(str(scripts / 'build-failed-case-queue.py'))} "
            f"--result-json {result_json} --control {ctrl_q})\n"
            "  printf '%s\\n' \"$out\"\n"
            "  echo \"$out\" | grep -q AMPLIFIED && continue || break\n"
            "done"
        )
        return "set -e\n" + init_part + precondition + run_part

    def _measure_timeout(self, state: "State"):
        """RunMeasure 墙钟上限：None（不限）——依赖 harness 看门狗（harness_timeout_sec
        每 case 有界）+ runner 阶段 deadline 不抢占（uninterruptible）。run-cases 的
        大 shape 放大重跑需充足时间，设 None 避免误杀。"""
        return None

    def _framework_case_stats(self, state: "State", cp: dict,
                              phase_data: dict) -> dict | None:
        """§P2: framework-owned run statistics.

        Re-runs ``build-failed-case-queue.py`` — the same deterministic
        stdlib-only skill script the agent runs in-session (single
        implementation, §1.15) — and parses its stdout for the failed/total
        counts. total_count semantics (len(case_details) / tested_cases
        fallback / 0 for crash sentinel) live in the script; the framework
        never re-implements them. The script's idempotent queue rewrite also
        deterministically enforces the queue contract (and crash_sentinel_mode)
        even when the agent skipped its in-session script run.

        Returns ``{"failed_count", "total_count", "result_json"}`` or None
        when no result.json can be resolved — hard-error rounds where the
        agent built the queue manually from run.log (no stats exist).
        Failures (missing script / nonzero rc / unparseable stdout) WARN and
        degrade to None: stats stay 0, observable, never fabricated (§3.7).
        """
        from ascendc_devkit.infra.logger import Logger
        script = Path(_RUN_TESTS_SCRIPTS_DIR) / "build-failed-case-queue.py"
        ctrl = _control_path(state)
        if not script.exists() or ctrl is None:
            Logger.warn(f"[PD-P2] build-failed-case-queue.py not found under "
                        f"{_RUN_TESTS_SCRIPTS_DIR} — run stats degrade to 0")
            return None
        # Resolve this round's result.json: the deterministic iter-dir
        # convention FIRST (framework arithmetic — run_iter_counter is still
        # pre-increment here and names this round; same-iter re-runs after
        # timeout amplification overwrite the same dir, so it is always the
        # latest product), then the agent-reported path as fallback (covers
        # agents that deviated from the --iter convention). Same trust
        # direction as §P2 at large: derived over declared.
        candidates: list[Path] = []
        dbg = _debug_artifacts_dir(state)
        iter_n = int(cp.get("run_iter_counter", 0))
        if dbg is not None:
            candidates.append(Path(dbg) / f"run_tests_iter-{iter_n}" / "result.json")
        reported = phase_data.get("last_result_json")
        if isinstance(reported, str) and reported:
            candidates.append(Path(reported))
        result_json = next((c for c in candidates if c.is_file()), None)
        if result_json is None:
            return None
        try:
            proc = subprocess.run(
                [sys.executable, str(script),
                 "--result-json", str(result_json),
                 "--control", str(ctrl)],
                capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as exc:
            Logger.warn(f"[PD-P2] build-failed-case-queue.py failed: {exc} "
                        "— run stats degrade to 0")
            return None
        if proc.returncode != 0:
            Logger.warn(f"[PD-P2] build-failed-case-queue.py rc={proc.returncode}: "
                        f"{(proc.stderr or '').strip()[:200]} — run stats degrade to 0")
            return None
        m = re.search(r"failed_count=(\d+) total_count=(\d+)", proc.stdout or "")
        if not m:
            Logger.warn(f"[PD-P2] unparseable script stdout: "
                        f"{(proc.stdout or '').strip()[:200]} — run stats degrade to 0")
            return None
        return {"failed_count": int(m.group(1)),
                "total_count": int(m.group(2)),
                "result_json": str(result_json)}

    def transition(self, state: "State", result) -> "State":
        # §judgment-ownership (N1): run_tests 纯 Python 测量——无 agent_result（不 spawn
        # agent）。孤儿恢复（_load_control 的 transcript 证据）随之休眠：control.json
        # 由 init-checkpoint.py 确定性写正确位置，无"写错位置"场景。
        # §step-95: 租约释放由 runner with 块统一持有（异常/中止路径结构性覆盖）。
        cp = _load_control(state)  # contract enforced on every read inside _load_control
        # Re-enter after a fix→run_tests corrective loopback: the rebuild may
        # have shrunk the queue below current_case_index. Reset to 0 so the next
        # diagnose/fix targets a real case (framework routing-control write).
        queue = cp.get("failed_case_queue") or []
        if queue and cp.get("current_case_index", 0) >= len(queue):
            cp["current_case_index"] = 0
            _save_control(state, cp)
        dc = _extract_debug_checkpoint(cp)
        self._validate_phase_json(state)
        # —— §judgment-ownership (N1): measure abort detection —————————————
        # run_tests 纯 Python 测量，abort 判据 = RunMeasure 的 measure_result.returncode
        # != 0（run-cases 非零退出 / subprocess 异常 rc=-1）。取代 _agent_produced_output
        #（那是 agent 产物判据，纯 Python 无 agent 产物）。
        # On abort: skip best_metrics update (no trustworthy data); but DO
        # advance rounds/history/run_iter_counter so the graph_executor's retry
        # can re-spawn into a clean iter-N directory.
        mr = result.get("measure_result") if isinstance(result, dict) else None
        measure_failed = mr is not None and mr.get("returncode") != 0
        if measure_failed:
            from ascendc_devkit.infra.logger import Logger
            Logger.warn(f"run_tests measurement failed (rc={mr.get('returncode')}): "
                        f"{(mr.get('stderr') or '')[-200:] or 'no stderr'} — Rounds/history "
                        "still advanced (framework-owned); best_metrics "
                        "skipped (no trustworthy data); letting corrective retry "
                        "re-spawn.")
            # —— Framework-owned invariants always advance ——————————————
            # rounds and history are framework-owned; agent absence doesn't
            # suspend them (otherwise the graph_executor sees stale rounds=0
            # and can never exit via exhausted).
            dc["rounds"] = (state._debug_checkpoint or {}).get("rounds", 0) + 1
            cp = self._append_history(state, {
                "failure_type": "unknown",
                "test_result": "aborted",
                "failed_count": len(cp.get("failed_case_queue") or []),
                "total_count": 0,
                "max_err": None,
                "last_run_log": "",
            })
            iter_n = int(cp.get("run_iter_counter", 0))
            cp["run_iter_counter"] = iter_n + 1
            _save_control(state, cp)
            # §abort: count this abort toward the annealing threshold.
            dc["consecutive_aborts"] = self._bump_consecutive_aborts(state)
            dc["agent_aborted"] = True
            # 写 phase relay（空路径）——避免 _sync_phase_latest 对缺失 round 文件 warn。
            self._write_phase_relay(state, {"last_result_json": "", "last_run_log": ""})
            self._sync_phase_latest(state)
            state = state.with_updates(_debug_checkpoint=dc)
            return _sync_debug_result(state, dc)
        # —— normal path ———————————————————————————————————————————————
        # §abort: a normal (non-aborted) spawn broke the abort streak — clear it.
        dc["consecutive_aborts"] = self._reset_consecutive_aborts(state)
        dc["rounds"] = (state._debug_checkpoint or {}).get("rounds", 0) + 1
        # §N1: phase JSON 由框架确定性写（run_tests 纯 Python，无 agent 写产物）。
        # last_result_json/last_run_log = 本轮 iter 目录的 result.json/run.log（与
        # _framework_case_stats 主候选路径一致，§P2 单一实现）。diagnose 跨 phase 读此
        # relay（last_result_json 回溯误差分布 / last_run_log 回溯日志）。
        dbg = _debug_artifacts_dir(state)
        iter_n = int(cp.get("run_iter_counter", 0))
        _rj = (Path(dbg) / f"run_tests_iter-{iter_n}" / "result.json") if dbg else None
        _rl = (Path(dbg) / f"run_tests_iter-{iter_n}" / "run.log") if dbg else None
        self._write_phase_relay(state, {
            "last_result_json": str(_rj) if _rj and _rj.exists() else "",
            "last_run_log": str(_rl) if _rl and _rl.exists() else "",
        })
        phase_data = self._read_phase_data(state)
        # §N1: no agent _summary — 删除 stale 检测（last_run_log 路径每轮不同，永不触发）
        # 与 agent observed_issues 合并。仅保留 _prev_run_log 回写（向后兼容 resume 读取）。
        dc["_prev_run_log"] = str(phase_data.get("last_run_log") or "")
        # —— §P2: framework-owned case stats (single path, replaces agent
        # _summary counts). Re-runs the deterministic skill script and parses
        # its stdout; the idempotent queue rewrite also enforces the queue
        # contract even when the agent skipped its in-session script run.
        stats = self._framework_case_stats(state, cp, phase_data)
        # Framework-derived all-pass: result.json shows zero failures over a
        # non-empty suite. status=passed no longer relies on the agent; a
        # contradictory agent-written "passed" reverts with a WARN (framework
        # truth wins — result.json is the authority). Held in a local until
        # after the _append_history disk round-trip below.
        derived_status: str | None = None
        if stats is not None:
            # Script rewrote control.json (queue merge / crash_sentinel_mode /
            # timeout sidecar) — re-read before queue-derived arithmetic.
            cp = _load_control(state)
            if stats["failed_count"] == 0 and stats["total_count"] > 0:
                derived_status = "passed"
            elif cp.get("status") == "passed":
                from ascendc_devkit.infra.logger import Logger
                Logger.warn(
                    "control.json status=passed contradicts result.json "
                    f"({stats['failed_count']} failed / {stats['total_count']}) "
                    "— framework truth wins, status reverted to running")
                derived_status = "running"
        # §P4: framework-owned best_* comparison (reclaims _better() from skill).
        # Compute crashed_count / real_max_err from per-case data —
        # 999.0 sentinel means "kernel crashed, no numerical result"; None means
        # the queue entry carries no numerical result (build-failed-case-queue.py
        # crash fallback writes max_err=None). Both count as crashed and must be
        # excluded from real_errs — max([None,...]) raises TypeError.
        queue_for_best = cp.get("failed_case_queue") or []
        # None 计入 crashed：harness 中止（执行前崩）时 build-failed-case-queue.py
        # crash fallback 写 max_err=None（P1 incident 20260807-144939-310314:
        # 全 None 时 max() 抛 TypeError 掩盖真实原因）——None 是「无数值结果」不是
        # diff，计 crashed 可观测（§1.2）、排除出 real_errs 防 TypeError。
        crashed = sum(1 for c in queue_for_best
                      if c.get("max_err") is None
                      or c.get("max_err") == 999.0
                      or c.get("elapsed_ms", 0) < 0)
        real_errs = [c["max_err"] for c in queue_for_best
                     if c.get("max_err") is not None
                     and c.get("max_err") != 999.0
                     and c.get("elapsed_ms", 0) >= 0]
        # §passed-count: 通过用例数 = total - failed (用户诉求: 交付通过用例最多的 commit).
        # §P2: total_count is framework-derived from the script stdout. When no
        # result.json exists (hard-error rounds — the agent built the queue
        # manually from run.log), total stays 0 → passed=0 (safe degradation:
        # never claims improvement on an unknown denominator).
        total_count = int(stats["total_count"]) if stats else 0
        failed_count = len(queue_for_best)
        passed_count = max(0, total_count - failed_count)
        run_result = {
            "passed_count": passed_count,
            "failed_count": failed_count,
            "crashed_count": crashed,
            "real_max_err": max(real_errs) if real_errs else None,
            "total_count": total_count,   # F8: 供 _update_best_metrics 写 best_total_count（报告 P2 优先级链首步）
        }
        # —— §P2: framework-composed history entry ————————————————————
        # Stats/verdict fields are framework-derived (script stdout + queue
        # arithmetic + per-case aggregation); the agent's _summary no longer
        # reports them (§2.5 single path). observed_issues (LLM semantic) is
        # the only agent-authored part, materialized separately below.
        if stats is None:
            test_result = f"{failed_count} failed (total unknown — no result.json)"
        elif cp.get("crash_sentinel_mode"):
            test_result = "crash_sentinel (harness died before any case output)"
        elif total_count == 0:
            test_result = (f"{failed_count} failed (total unknown — "
                           "result.json carries no case data)")
        elif failed_count == 0:
            test_result = f"0/{total_count} failed (all passed)"
        else:
            test_result = f"{failed_count}/{total_count} failed"
        # B2 fix: _append_history re-reads disk → appends → writes → RETURNS the
        # fresh cp. Receive it; otherwise a stale cp erases the entry just
        # appended. Derived values live in locals (survive the round-trip);
        # all cp mutations happen below on the returned dict.
        # step-119/§step-124: history 测量记录带被测来源——**测量时刻现探**
        # （_measured_source），供 converge/teardown/report 从测量史现算「最优被测
        # 代码」。不抄 state.deploy_result 的 deploy stamp：精度调试期间 agent 自建
        # 包不流经框架 Deployer，该缓存停留在 codegen 末次部署 → 全部测量行携带
        # 同一陈旧标签（20260915 批实证）。source_commit = 全 sha（合法 git ref，
        # 收敛锚点）；source_identity = 标签（dirty 计数的诚实信号）。
        _m_commit, _m_ident = _measured_source(state)
        cp = self._append_history(state, {
            "failure_type": _aggregate_failure_type(queue_for_best),
            "test_result": test_result,
            "failed_count": failed_count,
            "total_count": total_count,
            "max_err": run_result["real_max_err"],
            "crashed_count": crashed,
            "last_run_log": str(_rl) if _rl and _rl.exists() else "",
            "source_commit": _m_commit,
            "source_identity": _m_ident,
        })
        # §judgment-ownership (N1): 无 agent 申报 observed_issues（run_tests 纯 Python）。
        # 仅保留框架派生的级联/崩溃探针（纯算术，§1.15 单点）——供 diagnose 读
        # （级联隔离 / 精度探针）。blocking 恒 False：二者是「给 diagnose 的提示」。
        # 仅在分母有意义时派生（stats 缺失/total=0 的 hard-error 轮不派生）。
        _derived = []
        if (stats is not None and total_count > 0 and queue_for_best
                and all(c.get("failure_type") == "runtime" for c in queue_for_best)):
            if failed_count > 0.8 * total_count:
                _derived.append({
                    "category": "cascade_suspected",
                    "evidence": (f"runtime 失败率 >80%"
                                 f"（{failed_count}/{total_count}，框架派生）"),
                    "blocking": False,
                })
            if failed_count == total_count:
                _derived.append({
                    "category": "crash_masking_probe_needed",
                    "evidence": (f"全量 runtime 崩溃（{failed_count}/{total_count}），"
                                 f"精度层结果被掩盖（框架派生）"),
                    "blocking": False,
                })
        if _derived:
            cp["observed_issues"] = _derived
        # Advance run_iter_counter so the next run-cases writes to a new iter-N dir.
        iter_n = int(cp.get("run_iter_counter", 0))
        cp["run_iter_counter"] = iter_n + 1
        # §P2: framework-derived status lands here (after the history disk
        # round-trip above) together with the other cp mutations.
        if derived_status is not None:
            cp["status"] = derived_status
        # §step-119: 不再「严格大于才更新 best_commit」——最优被测 identity 从 history
        # 测量史现算派生（A-4），不存可写字段。此处无条件推进 run_iter_counter 后，
        # dc 的 best_* 从 history 现算填充（下游 converge/teardown/report 读 dc 契约不变）。
        _write_precision_report(cp, _debug_artifacts_dir(state))
        # Mirror status / crash_sentinel_mode + 派生 best_* 到 dc — dc 在 transition
        # 入口提取 (早于以上 cp 变更), 此处同步使返回的 checkpoint 见到新值.
        dc["status"] = cp.get("status", "running")
        dc["crash_sentinel_mode"] = bool(cp.get("crash_sentinel_mode"))
        _hist = cp.get("history") or []
        _best_ident = _best_commit_from_history(_hist)
        _best = _derive_best_metrics(_hist)
        dc["best_commit"] = _best_ident or dc.get("best_commit", "")
        dc["best_passed_count"] = _best["passed"]
        dc["best_failed_count"] = _best["failed"]
        dc["best_crashed_count"] = _best["crashed"]
        dc["best_real_max_err"] = _best["max_err"]
        _save_control(state, cp)
        # Copy round-suffixed phase JSON → latest path for cross-phase reads.
        self._sync_phase_latest(state)
        state = state.with_updates(_debug_checkpoint=dc)
        return _sync_debug_result(state, dc)

    def resolve_condition(self, state: "State") -> str:
        dc = state._debug_checkpoint or {}
        # §abort: anneal before business routing — a persistent abort escalates;
        # a transient one re-spawns run_tests (self-loop) instead of advancing to
        # diagnose with no trustworthy data.
        if (c := self._resolve_abort_condition(dc)) is not None:
            return c
        if dc.get("status") == "passed":
            return "all_pass"
        if dc.get("rounds", 0) > dc.get("max_iterations", 15):
            return "exhausted"
        # §time-budget: 墙钟预算耗尽 → 退出 (复用 exhausted 路由: self_evolve_op
        # → cannbench_adapt 软门 → cannbench_eval; generate_ascendc → __halt__).
        if _time_budget_exhausted(dc):
            return "exhausted"
        # §P3 减法：删 scope_guard 路由——上游缺陷由 diagnose 入口判据上报（upstream_signal），
        # 不再有独立 scope_guard phase。失败 → 直通 diagnose（就地定位+修）。
        # crash_sentinel_mode 保留：harness killed 前无 case 输出时，diagnose 读 crash dump
        # 处理（就地定位），不再转独立 comment_bisect phase。
        return "has_failures"
    # No loopback_feedback override: corrective-loopback context lives in
    # control.json, which the sub-agents read autonomously. Duplicating it via
    # prompt-injected loopback state would violate the file-relay separation
    # (§1.2/§2.7) — base Stage.loopback_feedback returns None.


# —— DiagnoseSubstage ————————————————————————————————————————————————

class DiagnoseSubstage(_PrecisionDebugSubstage):
    """Phase: 就地定位 + 自实施（diagnose-fix 融合，P3 减法）。

    docs/plan/fix-diagnose-merge: diagnose 产出 fix_plan 后就地 apply（Edit→build→
    单用例验证→commit/rollback），不再经独立 fix stage。Owns per-case stop-loss
    （原 FixSubstage 职责全量并入）。

    P3 减法（docs/plan/precision-debug-blindspot）：不枚举错误类型、不生成
    candidate_pool、不 route_to、不回炉重生成——比对 golden 不一致就地修那一处。
    printf/注释二分降级为 skill 的就地技巧（references/techniques/），不是独立 phase。
    scope_guard 降级为入口 upstream 判据：上游编译/注册/契约错 → 如实上报 halt。
    """

    name = "diagnose"
    agent_name = "ascendc-precision-diagnose"
    _schema_files = ["precision_diagnose.json"]

    def _format_resume_status(self, state: "State") -> str:
        """§方案F: diagnose resume 状态感知段（prompt 注入）。

        被杀/resume 后，diagnose 需感知「当前真实状态」（上次写下的进度 + 失败状态），
        而非从 round 1 重头认知 + 过时环境结论（docs/plan/diagnose-upstream-misattribution
        /02-l3-analysis.md 方案 F）。读上次 _summary（增量写）：
          - 无 _summary（被杀太早未写进度）→ 引导先读 result.json 的 error_msg 确认失败状态。
          - 有 _summary（已写进度）→ 续跑提示含 root_cause + 最近尝试。
        """
        summary = self._read_agent_summary(state) or {}
        if not summary:
            # §weak-model D：区分真首轮与「被杀未写进度」——history 无 diagnose
            # 条目 = diagnose 从未跑过（真首轮）→ 返回空（框架事实不能错：首轮
            # 没有「上次被杀」，误导模型自我怀疑）；有条目才注入引导。
            cp = _load_control(state)
            ran_before = any(h.get("phase") == "diagnose"
                             for h in (cp.get("history") or [])
                             if isinstance(h, dict))
            if not ran_before:
                return ""
            return ("## Resume 状态（上次 diagnose 被杀，未写进度）\n"
                    "你上次可能正在定位中途被杀。**先读 result.json 的 error_msg 确认当前失败"
                    "状态**（崩 / 输出空 / 精度错），再决定继续方向；勿凭环境现象（stale OPP、"
                    "NPU Alarm 等）直接归因上游。")
        rc = str(summary.get("root_cause") or "")[:200]
        # fix_code_log 是 phase json 平级字段（不在 _summary 内），单独读。
        phase_data = self._read_phase_data(state) or {}
        fixes = (phase_data.get("fix_code_log") or {}).get("tried_fixes") or []
        tried = "; ".join(
            str((f if isinstance(f, str) else f.get("fix_desc") or f.get("result") or ""))[:80]
            for f in (fixes if isinstance(fixes, list) else [])[-3:])
        return ("## Resume 状态（上次 diagnose 已写进度，续跑）\n"
                f"上次 root_cause: {rc or '(未定)'}\n"
                f"上次尝试: {tried or '(无)'}\n"
                "基于以上进度继续；但**先重新确认当前失败状态**（result.json 的 error_msg），"
                "勿沿用可能过时的结论。")

    def _phase_prompt(self, ctx, op_dir, ctrl, phase_path, skill_dir, iteration) -> str:
        resume_status = str(ctx.get("resume_status") or "")
        resume_block = (resume_status + "\n\n") if resume_status else ""
        # §weak-model A: 框架打回原因（P44-C：判定是事实，补救是非约束建议）——
        # 有值才渲染，round 过期自动消失（consumed-once）。
        reject_reason = str(ctx.get("reject_reason") or "")
        reject_block = (reject_reason + "\n\n") if reject_reason else ""
        # §weak-model B: 产物缺失定向提示（上轮产物没写/写错位置的路径指引）——
        # 有值才渲染；正常产出轮由 transition 清空（成功清错）。
        product_feedback = str(ctx.get("product_feedback") or "")
        product_block = (f"## 上次产物问题\n{product_feedback}\n\n") if product_feedback else ""
        # §step-88 (docs/plan/precision-diagnose-design-context/): 设计产物注入
        # （三层认知：设计意图 → 实现 → golden）。存在才渲染；无（TUI adapter /
        # 无设计场景）整段省略——skill 侧已约定按代码+golden 理解的优雅降级。
        design_paths = ctx.get("design_paths") or {}
        design_param_lines = [f"- design_paths（设计产物，全局理解必读）: {k}={v}"
                              for k, v in sorted(design_paths.items())]
        design_block = ("\n".join([
            "## 设计产物（三层认知：设计意图 → 实现 → golden）",
            "代码是 codegen 参考设计实现的投影，可能存在**实现与设计偏差**——先读上述设计产物建立",
            "设计意图（tiling 切分 / 流水编排 / 搬运路径 / 精度策略），再对照实现形成全局认知。假设",
            "空间显式包含「实现与设计偏差」方向：确认偏差 → 把实现修回设计的样子（原地修，不回炉）。",
            "数值权威仍是 golden（§1.13）：设计与 golden 冲突时以 golden 为准就地修。",
            "**结构完备性断言**：修复引起的 kernel 结构变化，要么与设计产物声明一致，要么必须记录",
            "`fix_code_log.design_deviation`（偏离维度 + 理由）——禁止未记录的结构偏离。",
            ""]) + "\n") if design_paths else ""
        return "\n".join([
            f"## Phase: diagnose（precision_debug loop, round {iteration}）",
            "",
            "你是 diagnose phase agent（**诊断 + 自实施一体**）。核心方法：**先全局理解算子 + golden →",
            "形成假设 → 验证推进**（§1.13/§1.14「比对 golden 一致即对，不一致就地修」）。**判断决策权",
            "在你**——失败是什么性质、用全局推演还是就地查证、验证哪些 case，由你基于完整上下文判断，",
            "框架不框死打法。可用的定位手段（全局推演 / golden 比对 / printf 二分 / 注释降级 / 知识库",
            "查证）都是**可选弹药**，按需取用。**不枚举错误类型、不生成候选池、不 route_to、不回炉重生成**。",
            "核心方法已通过 skill `{self._assigned_skill()}` 加载（见你的 agent instructions + 加载的",
            "SKILL.md/references）。",
            "",
            "## 假设纪律（改动必须有预测）",
            "动手前写 `_summary.hypothesis`（hypothesis 改 X 因认为根因 Y / evidence / predict 改完应看到",
            "什么）。验证结果回填 `_summary.validation`（confirmed/refuted + 新认知）——无论对错都推进认知，",
            "这是「分诊错也能收敛」的兜底。**没有 predict 的改动 = 试错法，禁止**（试错法不产生新信息、",
            "认知不推进）。",
            "",
            resume_block,
            reject_block,
            product_block,
            design_block,
            "## Step 0：上游判据（入口，先于任何定位）",
            "先看当前 failed case 是哪种错：",
            "- **崩了**（SIGSEGV / 507035 vector core exception / 越界）→ 本阶段职责，就地修",
            "- **数值错**（max_diff / 形状 mismatch / NaN）→ 本阶段职责，就地修",
            "- **上游编译/注册/契约错**（编译失败 / op_plugin schema 不匹配 / golden 缺 get_input /",
            "  算子未注册 / devkit 自身抛错）→ **先尝试原地兜底解决，解决不了才上报**：",
            "  · 凡修复目标代码在算子工程内的缺陷一律就地修——含 host 侧 tiling/launch/注册/",
            "    脚手架缺陷，不因根因属上游生成而推诿（plugin/manifest 契约不一致等仅为子集例）",
            "    → 就地修（Edit→build→单用例验证→commit/rollback），修好按已修复处理",
            "  · 确实超出本阶段职责的（golden 语义错 / devkit 框架自身抛错 / 编译依赖缺失无法本地补）",
            "    → 如实上报：写 control.json.upstream_signal=true + upstream_stage（codegen/test_design/",
            "    golden/deploy/framework/env）+ upstream_reason（一句话事实），输出 RESULT: DIAGNOSE_UPSTREAM",
            "混合失败按主导归类；拿不准时**倾向本阶段**（能修就修，别轻易上报——预算兜底）。",
            "",
            "## 尽力后的诚实报告（假设空间穷尽时）",
            "当所有方向试过、认知无法再推进（假设空间系统穷尽）→ **先自检**（对齐 §2.9 "
            "producer 自检——自己保证确实穷尽了，不是框架替你判断）：",
            "  ① 我已对失败做全局理解（读完整 kernel + golden），不是从局部盲试",
            "  ② 我已形成并验证了多个假设（每个有 predict + validation 回填），不只试了一两个方向",
            "  ③ 我已用可选弹药（全局推演/golden 比对/printf/注释降级/知识库）系统排查",
            "  ④ 我确认：再试下去认知不会推进（假设空间已穷尽），不是因为我'累了/想放弃'",
            "自检全过 → 写 control.json.stalled=true + stalled_detail（**必须含 self_check 数组**，",
            "记录上述自检项 + 结论），同时 _summary.stalled 记录详情，输出 RESULT: DIAGNOSED_STALLED。",
            "自检任一不过 → 继续调试（不许 stalled）——自检发现还有方向没试，兜底继续解决。",
            "**框架校验 stalled 必须带 self_check**——缺失打回 retry 继续调试（不是静默接受）。",
            "",
            "## 参数",
            f"- control_path: {ctrl}",
            f"- phase_json_path（你 owner 的 phase 产物）: {phase_path}",
            f"- operator_dir（你的 cwd）: {op_dir}",
            f"- skill_dir（脚本/参考所在）: {skill_dir}",
            *design_param_lines,
            f"- op_name: {ctx['op_name']}",
            f"- build_command（redeploy）: {ctx['build_command']}",
            f"- test_command（单用例验证，必须带 --iter {ctx['iter_n']}）: {ctx['test_command']}",
            f"- current_case_id: 见 control.json.failed_case_queue[current_case_index].case_id",
            f"- 单用例验证命令: {ctx['test_command']} --case \"<CASE_ID>\" --iter {ctx['iter_n']} --label diagnose",
            "",
            "## 验证节奏由你定（判断决策权）",
            "算法级 bug 可「改完整个算法再验证」，不必每改一处就全量回归。run_tests 最终全量判定，",
            "但**中间的验证范围/节奏由你判断**（改一处验证一处，或改完一起验证）。核心目标是把 bug "
            "修对，不是机械地每改必测。",
            "",
            "## 读写契约（混合切分）",
            "- 读 control.json：failed_case_queue[current_case_index]（case_id / failure_type / shape /",
            "  dtype / max_err）/ failure_type / history（避开重复方向）/ upstream_signal",
            "- 跨 phase 只读：{debug_artifacts_dir}/phases/run_tests/precision_run_tests.json 的",
            "  last_result_json / last_run_log（回溯完整误差分布 / max_diff_location / 运行日志上下文）",
            f"- 写 {phase_path}（round 后缀文件，禁止写 non-suffixed latest；框架 _sync_phase_latest 负责同步）：",
            "  diagnose_done / fix_code_log（applied_fix / tried_fixes[] / verification_result / ",
            "  side_effect_cases[] / fallback_masked）/ _summary（symptom / case_id / root_cause / ",
            "  upstream_signal / upstream_stage / upstream_reason；实施时 already_resolved / partial_outputs）",
            "- 写 control.json：case.status（resolved_pending / skipped + reason）/ attempt_count（递增；",
            "  框架据此 + max_attempts_per_case 判 stop-loss）/ upstream_signal + upstream_stage +",
            "  upstream_reason（上游时）。**最优被测代码与计数由框架从 history 测量史派生，",
            "  无 best_* 字段可写、也无需你写**（step-119：字段已删）",
            "- **禁止**写 control.json.history（框架 transition 统一物化）；禁止写 debug_result.json。",
            "",
            "## 返回协议（RESULT 行仅供人读；路由由 _summary 结构化字段 + case.status 驱动，非 RESULT 字符串）",
            "输出恰好一行 RESULT：",
            "- DIAGNOSE_UPSTREAM — 上游编译/注册/契约错（必写 upstream_signal/stage/reason），框架 halt",
            "- DIAGNOSED_AND_FIXED — 实施成功 / already_resolved，case=resolved_pending",
            "- FIX_PARTIAL_OUTPUT — 部分 output/symptom 改善未全 pass（必写 partial_outputs，commit 保留）",
            "- DIAGNOSED_NO_FIX — 本轮无修复（尝试后未果），框架按 stop-loss 处理",
            "**路由契约**：upstream / partial_output / resolved 全靠 _summary 结构化字段 + case.status",
            "判定，RESULT 行仅作可读标签（§2.10 结构化契约）。禁止写 debug_result.json。",
        ])

    def _handle_diagnose_abort(self, state: "State", ar) -> "State" | None:
        """§weak-model B: diagnose abort 分流——infra 熔断 vs 产物缺失走 rounds。

        - **infra**（``is_infra_error_type(ar.error_type)``——网关/鉴权/spawn 超时
          死亡，§1.10 业务语义判据）→ 既有 abort 退火熔断（fail-open 有界，语义
          不变）+ 拒因记 agent_infra。**不写 user_feedback**（P93 教训：infra 下
          重试无意义，不教 agent 修路径——design 侧曾因误导文案带偏 agent）。
        - **非 infra**（模型没写/写垃圾）→ design 哲学「iteration budget 就是为
          产物纠错存在的」+ 用户原则「能解决尽量解决，宁可多花 token」：**不进
          熔断**，rounds+1 正常推进（exhausted 兜底可达）+ 定向提示（transcript
          证据点名真实误写路径）→ resolve 走兜底 retry 自环。
        - **孤儿搬回先行**（零迭代自愈）：transcript 证据指向 wd 外的误写产物 →
          ``recover_orphan_artifact`` 搬回 → 重判通过 → 返回 None 让调用方
          fall-through 走正常 transition。

        Returns None 仅表示「孤儿已搬回，继续正常路径」；其余返回 abort/retry
        终态 state。
        """
        from ascendc_devkit.capabilities.agent._shared import (
            _harvest_relocation_evidence_detailed, is_infra_error_type)
        from ascendc_devkit.infra.logger import Logger
        # ar=None（UT 直调 / backend 缺失）→ 无 error_type/transcript 证据，不
        # 臆测性质（§1.11 实际产出为证）——维持既有 abort 退火（有界重试安全路径）。
        # 生产 runner 总写 result["agent_result"]（含 fatal），分流证据总在。
        if ar is None:
            return self._handle_abort(state, bump_counters=True)
        filename = self._phase_filename()
        phase_p = _phase_path(state, filename, round_suffix=True)
        phase_dir = phase_p.parent if phase_p else None
        transcript = getattr(ar, "transcript", None)

        # §weak-model: 拒因写入单点（纯函数——只改 cp dict 不碰盘，落盘时机与
        # rounds 时序由各调用路径自理；round 缺省 = cp 当前 rounds）。
        def _reject(cp: dict, reason: dict, *, round: int | None = None) -> None:
            cp["last_reject_reason"] = {
                **reason,
                "round": int(round if round is not None
                             else cp.get("rounds", 0) or 0)}

        # —— infra 分流（权威信号 error_type）———————————————————————
        if is_infra_error_type(getattr(ar, "error_type", None)):
            metrics = getattr(ar, "metrics", None) or {}
            state = self._infra_no_product_error(state, filename, ar)
            cp = _load_control(state)
            _reject(cp, {"cond": "agent_infra",
                         "detail": f"agent 因基础设施错误未产出（重试自动进行，"
                                   f"无需修产物路径）。原因：{metrics.get('failure_reason', '')}"})
            _save_control(state, cp)
            return self._handle_abort(state, bump_counters=True)

        # —— 非 infra：先试孤儿搬回（零迭代自愈）———————————————————
        if transcript is not None and phase_dir is not None:
            try:
                from ascendc_devkit.orchestration.artifact_recovery import (
                    recover_orphan_artifact)
                evidence, _refused = _harvest_relocation_evidence_detailed(
                    transcript, filename, phase_dir)
                if evidence is not None:
                    recover_orphan_artifact(
                        transcript, filename, phase_dir, state, "precision-debug")
                    if self._agent_produced_output(state):
                        Logger.warn(
                            f"[{self.name}] {filename} 孤儿搬回成功"
                            f"（{evidence} → {phase_dir}）——零 abort 走正常 transition")
                        return None
                    Logger.warn(
                        f"[{self.name}] {filename} 搬回后产物仍未就位——走定向提示重试")
            except Exception as exc:  # noqa: BLE001 — 恢复是 best-effort，绝不阻断路由
                Logger.warn(f"[precision-debug] 孤儿恢复尝试失败（忽略，"
                            f"走定向提示重试）: {exc}")

        # —— 产物缺失：定向提示 + rounds 预算（不熔断）——————————————
        state = self._missing_artifact_error(state, filename, phase_dir, transcript)
        pre_cp = _load_control(state)
        cp = self._append_history(state, {
            "failure_type": "unknown",
            "test_result": "aborted_no_product",
            "failed_count": len(pre_cp.get("failed_case_queue") or []),
            "total_count": 0,
            "max_err": None,
            "last_run_log": "",
        })
        # rounds+1 必须在 _append_history 的盘往返之后（它内部重读盘，未保存的
        # 改动会被丢弃——B2 同款陷阱）；exhausted 兜底靠它可达。拒因 round =
        # 推进后的 rounds（本轮 retry 的 prompt 按 rounds 匹配可见）。
        cp["rounds"] = int(cp.get("rounds", 0) or 0) + 1
        hint = str(state.user_feedback or "")
        _reject(cp, {"cond": "missing_artifact",
                     "detail": hint[:300] or "产物未在正确路径找到"},
                round=cp["rounds"])
        _save_control(state, cp)
        dc = _extract_debug_checkpoint(cp)
        # 不设 agent_aborted / 不 bump consecutive_aborts（§weak-model B：产物
        # 缺失走 rounds 预算 + retry 自环；只有 infra 死亡才吃熔断计数）。
        state = state.with_updates(_debug_checkpoint=dc)
        return _sync_debug_result(state, dc)

    def transition(self, state: "State", result) -> "State":
        # §merge (docs/plan/fix-diagnose-merge): diagnose 融合 fix 后承担实施职责。
        # P3 减法：diagnose 就地定位+修，不再枚举候选、不回炉；加 upstream 读取
        # （diagnose 入口判据）。
        # §step-95: 租约释放由 runner with 块统一持有（异常/中止路径结构性覆盖）。
        # —— §weak-model B：接住 runner 的 agent_result（error_type / metrics /
        # transcript）——infra 分流、孤儿搬回、产物缺失定向提示的证据源；同时把
        # transcript 挂上 state（复活 control.json 孤儿恢复的证据通道——N1 删
        # run_tests spawn 时 setter 一并被删，9a883cc9 的接线曾静默失效）。
        ar = result.get("agent_result") if isinstance(result, dict) else None
        if ar is not None and getattr(ar, "transcript", None):
            state = state.with_updates(
                _last_agent_transcript=str(ar.transcript))
        if not self._agent_produced_output(state):
            out = self._handle_diagnose_abort(state, ar)
            if out is not None:
                return out
            # 孤儿搬回成功（产物已就位）→ fall through 走正常路径（零 abort）。
        self._reset_consecutive_aborts(state)
        cp = _load_control(state)
        summary = self._read_agent_summary(state) or {}

        # —— 实施模式（原 FixSubstage.transition 就地实施内核保留） ——
        case = _get_current_case(cp)
        skipped = False
        more_cases = False
        # §P3: case stop-loss（attempt 耗尽）。
        if case is not None:
            attempts = case.get("attempt_count", 0)
            max_attempts = cp.get("max_attempts_per_case", 8)
            if attempts >= max_attempts:
                _advance_current_case(cp)
                _save_control(state, cp)
                skipped = True
                more_cases = cp["current_case_index"] < len(cp.get("failed_case_queue", []) or [])
        # §P4: 写侧 ledger 归一化——diagnose 应用的 commit 合并进 root_cause_ledger。
        _merge_fix_into_ledger(cp, summary, "diagnose")
        # §step-119 D1: agent 声明已修复（already_resolved 或 fix_code_log.applied_fix）
        # 但漏填 git_commit → 修复史断链（ledger no-op、报告 commit 列 '-'）。WARN 可观测，
        # 不阻断（§1.2——显式失败优于静默丢信息；教学层 SKILL.md 已列 git_commit 为实施必填）。
        _fix_commit = summary.get("git_commit")
        _phase_d1 = self._read_phase_data(state) or {}
        if (not _fix_commit) and (summary.get("already_resolved")
                                  or (_phase_d1.get("fix_code_log") or {}).get("applied_fix")):
            from ascendc_devkit.infra.logger import Logger
            Logger.warn(
                "diagnose 声明已修复但 _summary 缺 git_commit — 修复史将断链"
                "（root_cause_ledger 空置、报告 commit 列 '-'）。"
                "SKILL.md 契约：实施（DIAGNOSED_AND_FIXED / already_resolved）时必填 git_commit。")
        already = summary.get("already_resolved")
        if already and case:
            # §P4: agent 发现 case 已被先前 commit 修复。标 resolved_pending，run_tests
            # 全量回归升级 resolved。
            case["status"] = "resolved_pending"
            case["last_fix_commit"] = already.get("commit")
            _save_control(state, cp)
        # §per-output: partial output improvement（fix 对部分 output 有效，非全部）。
        _pout = summary.get("partial_outputs")
        _partial = False
        if _pout and case:
            outputs = case.get("outputs")
            if outputs:
                for po in _pout:
                    if not isinstance(po, dict):
                        continue
                    for o in outputs:
                        if o.get("index") == po.get("index"):
                            o["diff"] = po.get("diff_after")
                            o["status"] = "improved"
                _save_control(state, cp)
            _partial = True
        # Increment run_iter_counter so each diagnose↔run_tests cycle writes unique iter-N dir.
        fix_iter = int(cp.get("run_iter_counter", 0))
        cp["run_iter_counter"] = fix_iter + 1
        # —— §weak-model A: 打回原因写入/清空（成功清错）———————————————
        # 判定单点 _stalled_reject_reason：stalled 缺 self_check（会被打回）→ 写
        # last_reject_reason（含 round，_reject_reason_block 按轮 consumed-once）；
        # 正常产出 / 合法 stalled → 清空（防残留旧拒因误导，对齐 design last_error
        # clear-on-success）。在 _save_control 前写入，_append_history 的盘往返不丢。
        _reason = _stalled_reject_reason(cp)
        cp["last_reject_reason"] = (
            {**_reason, "round": int(cp.get("rounds", 0) or 0)}
            if _reason is not None else None)
        _save_control(state, cp)
        dc = _extract_debug_checkpoint(cp)  # re-extract
        dc["rounds"] = (state._debug_checkpoint or {}).get("rounds", 0)
        dc["case_skipped"] = skipped
        dc["more_cases"] = more_cases
        if _partial:
            dc["partial_output"] = True
        # §upstream: diagnose 入口判据上报上游缺陷 → halt（框架展示 upstream_stage/reason）。
        if cp.get("upstream_signal"):
            dc["upstream_signal"] = True
            dc["upstream_stage"] = cp.get("upstream_stage", "")
            dc["upstream_reason"] = cp.get("upstream_reason", "")
        # §judgment-ownership (P5): stalled = diagnose 尽力后假设空间穷尽 → 诚实收敛。
        # agent 写 control.json.stalled=true（与 upstream 同路径），stalled_detail 已在
        # _extract_debug_checkpoint 读取，transition 无需重复透传（§1.15 单点收敛）。
        self._validate_phase_json(state)
        # Framework-authored history — one entry per spawn.
        self._append_history(state, summary)
        self._sync_phase_latest(state)
        # §weak-model B: 成功清错（对齐 design L1065 先例）——正常产出轮清
        # user_feedback（产物问题提示只在缺失轮有效，防残留误导）+ 拒因已在上方
        # 写入/清空。
        state = state.with_updates(_debug_checkpoint=dc, user_feedback="")
        return _sync_debug_result(state, dc)

    def resolve_condition(self, state: "State") -> str:
        dc = state._debug_checkpoint or {}
        # §abort: anneal before business routing.
        if (c := self._resolve_abort_condition(dc)) is not None:
            return c
        # §time-budget: 墙钟预算耗尽 → 退出循环，收敛到 best_commit
        if _time_budget_exhausted(dc):
            return "exhausted"
        # §upstream: diagnose 入口判据上报上游缺陷 → halt（不空转修非本阶段 bug）。
        if dc.get("upstream_signal"):
            return "upstream"
        # §judgment-ownership (P5): diagnose 尽力后假设空间穷尽（stalled）→ 诚实
        # 收敛。这是「模型判断已尽力」（写 _summary.stalled=true + DIAGNOSED_STALLED），
        # 不同于 upstream（上游的错）——stalled 是模型尽力后的诚实声明，框架按
        # 已尽力处理（收敛到 best_commit / 报告需人工），不再无限 retry。
        # **防偷懒门槛**：stalled 必须带 self_check（对齐 §2.9 producer 自检）——
        # 模型自检确认确实穷尽（读全 kernel+golden / 多假设已验证 / 弹药系统排查 /
        # 确认再试不推进），不是"累了/想放弃"。缺 self_check 的 stalled 打回 retry
        # （diagnose resume 继续自检兜底），不静默接受。
        if dc.get("stalled"):
            # §weak-model A：判定单点（_stalled_reject_reason）——transition 写
            # last_reject_reason 与此处路由共用同一判定（§1.15，防两处漂移）。
            if _stalled_reject_reason(dc) is None:
                return "stalled"
            # stalled 缺自检 → 不是合法 stall，回 retry 继续调试（不静默接受）。
            # 拒因已由 transition 写入 control.json.last_reject_reason，下轮
            # diagnose prompt 经 _reject_reason_block 可见（不再盲猜被打回原因）。
            from ascendc_devkit.infra.logger import Logger
            Logger.warn(
                "precision_debug diagnose stalled 缺 self_check 自检证据——打回 retry "
                "继续调试（防偷懒门槛：stalled 必须证明确实穷尽）")
            return "retry"
        # §per-output: partial output 改善 → 回 run_tests 全量回归，重测 per-output diffs。
        if dc.get("partial_output"):
            return "partial_output"
        # §P4: case 已修（resolved_pending）→ run_tests 全量回归确认。
        if dc.get("case_resolved"):
            return "resolved"
        # §P2: case_skipped（attempt 耗尽 advance 触发）。
        if dc.get("case_skipped"):
            return "skip_more" if dc.get("more_cases") else "skip_done"
        return "retry"
