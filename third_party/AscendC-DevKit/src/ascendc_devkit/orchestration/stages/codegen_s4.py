"""L3 Orchestration — Codegen Stage 4 sub-stage state machine (deterministic).

This module is the **single authoritative implementation** of the Regbase Stage 4
sub-stage scheduler. It replaced the shell/python scripts that used to live in
the skill directory (``stage4_scheduler.sh``), which were a cross-layer
dependency: the orchestration layer shelled out into ``.claude/skills/...``
scripts. Agents never invoked the scheduler — only ``codegen.py`` did — so the
logic now lives here, importable directly.

State authority = ``orchestration_plan.json`` (machine-readable plan produced by
s2-analysis and schema-validated at the s2 transition). ``progress.md`` is a
*derived mirror* (human/agent readable) and is NOT a state-transition input.

Completion is driven by the agent's returned signal only — ``dispatch`` accepts
only an authorized execution group's full completion or its validated contiguous
prefix, then advances without any on-disk deliverable verification (the plan's
``deliverables`` list is used for schema validation / s2 self-consistency only).

Public API (all operate on ``record_dir`` = staging dir):
- ``resolve_sub_stage(rd, reason) -> str``          next sub_stage id or "DONE"
- ``resolve_execution_group(rd, sid) -> list[str]`` authorized S4 work unit
- ``pending_vf_ids(rd) -> list[str]``               all still-pending VF step ids
- ``all_vf_ids(rd) -> list[str]``                   all VF step ids (any status)
- ``vf_group_base(sid) -> str``                     VF template group base (strip .VT.{M})
- ``check_retry_exceeded(rd, sid, err_type) -> (bool, str)`` per-substage budget exhausted
- ``bump_retry_counter(rd, sid, err_type) -> None`` increment per-substage FAILED counter
- ``get_group(rd, sub_stage) -> str``               checkpoint group
- ``check_gate(rd) -> str``                         "READY" / "NOT_READY: {id}"
- ``dispatch(rd, status, error_type, ...) -> dict`` decision dict (action=...)
- ``regenerate_progress(rd) -> str``                rewrite progress.md mirror
"""

from __future__ import annotations

import datetime
import json
import re
import sys
from pathlib import Path

STATUS_PENDING = "pending"
STATUS_DONE = "done"
STATUS_EXHAUSTED = "exhausted"


# ─────────────────────────────────────────────────────────────────────────
# orchestration_plan.json 读取/写入（状态决策的单一来源）
# ─────────────────────────────────────────────────────────────────────────

def _plan_path(record_dir: str) -> Path:
    return Path(record_dir) / "orchestration_plan.json"


def _read_plan(record_dir: str) -> dict:
    """读取编排计划。缺失/不可解析 → 空计划（调用方据此降级）。"""
    p = _plan_path(record_dir)
    if not p.is_file():
        return {"sub_stages": []}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — non-conforming plan → treat as empty
        return {"sub_stages": []}


def _write_plan(record_dir: str, plan: dict) -> None:
    """写编排计划，并重新生成 progress.md 派生镜像。"""
    with open(_plan_path(record_dir), "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2, ensure_ascii=False)
        f.write("\n")
    regenerate_progress(record_dir)


def _step_by_id(plan: dict, sid: str) -> dict | None:
    for s in plan.get("sub_stages") or []:
        if not isinstance(s, dict):
            continue
        if s.get("id") == sid:
            return s
    return None


def _set_status(record_dir: str, sid: str, st: str) -> None:
    plan = _read_plan(record_dir)
    s = _step_by_id(plan, sid)
    if s is not None:
        s["status"] = st
        if st == STATUS_DONE:
            s["retry_count"] = 0  # 完成即清零失败计数（per-substage 按尝试窗口计）
        _write_plan(record_dir, plan)


def _set_statuses(record_dir: str, sids: list[str], st: str) -> None:
    """Atomically update a validated list of sub-stages and refresh the mirror once."""
    if not sids:
        return
    plan = _read_plan(record_dir)
    for sid in sids:
        step = _step_by_id(plan, sid)
        if step is None:
            raise ValueError(f"unknown sub-stage while committing progress: {sid}")
        step["status"] = st
        if st == STATUS_DONE:
            step["retry_count"] = 0
    _write_plan(record_dir, plan)


def pending_vf_ids(record_dir: str) -> list[str]:
    """Collect all pending VF sub-stage ids, in plan order.

    Used by the parallel VF dispatch: the orchestrator gathers every still-
    pending ``.VT.{M}`` step so a single iteration can spawn one
    ``ascendc-vf-test-agent`` per VF function (capped by the stage's
    ``max_concurrent_vf``) instead of one-at-a-time. VF steps are independent
    singleton work units (``resolve_execution_group`` keeps them singletons),
    so batching them does not broaden any agent's write authority.
    """
    plan = _read_plan(record_dir)
    return [sid for sid in _pending_ids(plan) if _is_vf_step(record_dir, sid)]


def all_vf_ids(record_dir: str) -> list[str]:
    """All VF sub-stage ids in plan order (any status).

    Complements ``pending_vf_ids`` for the first-serial-then-parallel VF
    dispatch: the orchestrator needs the plan's FIRST VF step regardless of its
    current status. While that first step is still pending it is dispatched
    alone (serial bootstrap that establishes the ``vf_verified`` test harness);
    once it settles (done/exhausted) the remaining VF steps are dispatched in
    parallel batches (capped by ``max_concurrent_vf``).
    """
    plan = _read_plan(record_dir)
    out: list[str] = []
    for s in plan.get("sub_stages") or []:
        if not isinstance(s, dict):
            continue
        sid = s.get("id", "")
        if not isinstance(sid, str) or not sid:
            continue
        # 与 _is_vf_step 同源的双信号（kind=vf 或 .VT.{M} 命名回退），避免逐条重读 plan。
        if s.get("kind") == "vf" or re.match(
                r".*\.VT\.[0-9]+$", sid, re.IGNORECASE):
            out.append(sid)
    return out


def vf_group_base(sid: str) -> str:
    """VF 步骤的模板组基名：去掉 ``.VT.{M}`` 后缀（``4.C.3.VT.0 → 4.C.3``）。

    并行 VF 派发按模板组隔离（§P2）：批内只取与当前 frontier 同组的 pending VF，
    避免跨模板混批（T1 的 VT 不提前混入 T2 的 VT、T2 的 VT 不被普通步骤压后）。
    非 VF id（无 ``.VT.{M}`` 后缀）原样返回，天然自成一组。
    """
    marker = ".VT."
    if marker in sid:
        head, _, _ = sid.rpartition(marker)
        if head:
            return head
    return sid


def _pending_ids(plan: dict) -> list[str]:
    """Collect pending sub_stage ids; skip structurally-broken entries.

    ``orchestration_plan.json`` is agent-produced (s2), so entries may be
    non-dict / missing ``id`` / id not str. Skipping (with a warn) instead of
    ``s["id"]`` KeyError keeps the s4 state machine alive on a bad plan —
    completion stays agent-signal-driven (the s2 gate was intentionally removed),
    but a broken plan no longer crashes resolve/dispatch (§1.2 可诊断)。
    """
    ids: list[str] = []
    for s in plan.get("sub_stages") or []:
        if not isinstance(s, dict):
            _warn_plan_entry("sub_stage 非对象，跳过", repr(s))
            continue
        sid = s.get("id")
        if not isinstance(sid, str) or not sid:
            _warn_plan_entry("sub_stage 缺 id/非法 id，跳过", repr(sid))
            continue
        if s.get("status") == STATUS_PENDING:
            ids.append(sid)
    return ids


def _warn_plan_entry(msg: str, detail: str) -> None:
    """Best-effort structured warn for a structurally-broken plan entry."""
    from ascendc_devkit.infra.logger import Logger
    Logger.warn(f"[CODEGEN-PLAN] {msg}: {detail}")


def _canonicalize_reported(reported: list[str],
                           work_unit: list[str]) -> list[str] | None:
    """Map agent-reported sub-stage IDs onto the plan's canonical IDs.

    The plan is the authoritative ID source; agents may echo IDs in a different
    case (e.g. ``4.D.api`` vs ``4.D.API``). Return the plan's spelling for the
    reported prefix so the contiguity check AND the downstream
    ``_set_statuses`` commit both use the canonical ID. Returns ``None`` when
    any reported ID has no case-insensitive match (invalid list).
    """
    if len(reported) > len(work_unit):
        return None
    canonical: list[str] = []
    for item in reported:
        match = next((wu for wu in work_unit
                      if wu.casefold() == item.casefold()), None)
        if match is None:
            return None
        canonical.append(match)
    return canonical


def _sync_current_stage(record_dir: str) -> None:
    """只要 Stage 4 还有待做 sub-stage，就同步 meta.json.current_stage=4。"""
    meta_path = Path(record_dir) / "meta.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        meta = {}
    if str(meta.get("current_stage", "")) != "4":
        meta["current_stage"] = 4
        meta["updated_at"] = datetime.datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S")
        meta_path.write_text(
            json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────
# 公共 API
# ─────────────────────────────────────────────────────────────────────────

def resolve_sub_stage(record_dir: str, reason: str) -> str:
    """解析本次应调度的 sub_stage id；全部完成返回 "DONE"。

    reason: first_enter（首次，取第一个 pending）/ continue（取第一个 pending）/
    retry（取最后一个 pending，回退目标）。
    """
    plan = _read_plan(record_dir)
    pending = _pending_ids(plan)
    if not plan.get("sub_stages"):
        return "DONE"
    if reason == "first_enter":
        result = pending[0] if pending else "DONE"
    elif reason == "retry":
        result = pending[-1] if pending else "DONE"
    else:  # continue
        result = pending[0] if pending else "DONE"
    if result != "DONE":
        _sync_current_stage(record_dir)
    return result


def get_group(record_dir: str, sub_stage: str) -> str:
    """查询 sub_stage 的检查点组。"""
    plan = _read_plan(record_dir)
    s = _step_by_id(plan, sub_stage)
    return s.get("checkpoint_group", "UNKNOWN") if s else "UNKNOWN"


def get_execution_group(record_dir: str, sub_stage: str) -> str:
    """Return the plan-declared Agent work-unit name, or an empty safe fallback."""
    step = _step_by_id(_read_plan(record_dir), sub_stage)
    value = step.get("execution_group") if step else None
    return value if isinstance(value, str) and value.strip() else ""


def _step_is_vf(step: dict, sid: str) -> bool:
    return step.get("kind") == "vf" or bool(
        re.match(r".*\.VT\.[0-9]+$", sid, re.IGNORECASE))


def resolve_execution_group(record_dir: str, sub_stage: str) -> list[str]:
    """Resolve one S4 Agent work unit from the first pending sub-stage.

    ``execution_group`` is a scheduling boundary, while every entry remains an
    independently audited/self-checked sub-stage.  VF entries are always
    singleton units.  A missing/malformed field degrades to one sub-stage so an
    old or damaged plan can never silently broaden an Agent's write authority.
    """
    plan = _read_plan(record_dir)
    steps = plan.get("sub_stages") or []
    start_index = next(
        (i for i, step in enumerate(steps)
         if isinstance(step, dict) and step.get("id") == sub_stage),
        None,
    )
    if start_index is None:
        _warn_plan_entry("execution group 起点不存在，按单步骤降级", repr(sub_stage))
        return [sub_stage] if sub_stage else []

    first = steps[start_index]
    if _step_is_vf(first, sub_stage):
        return [sub_stage]
    group = first.get("execution_group")
    if not isinstance(group, str) or not group.strip():
        _warn_plan_entry(
            f"sub_stage {sub_stage!r} 缺 execution_group，按单步骤降级",
            repr(group),
        )
        return [sub_stage]

    result: list[str] = []
    for step in steps[start_index:]:
        if not isinstance(step, dict):
            break
        sid = step.get("id")
        if not isinstance(sid, str) or not sid:
            break
        if step.get("status") != STATUS_PENDING:
            break
        if _step_is_vf(step, sid) or step.get("execution_group") != group:
            break
        result.append(sid)
    return result or [sub_stage]


def check_gate(record_dir: str) -> str:
    """校验 Stage 4 是否全部完成：全部 done/exhausted → "READY"。"""
    plan = _read_plan(record_dir)
    for s in plan.get("sub_stages") or []:
        if s.get("status") not in (STATUS_DONE, STATUS_EXHAUSTED):
            return "NOT_READY: " + str(s.get("id", "?"))
    return "READY"


def set_status(record_dir: str, sub_stage: str, status: str) -> bool:
    """设置某 sub_stage 的 status（pending/done/exhausted），并重生成 progress.md。

    供编排层在 vf_exhausted 等路径直接推进编排计划状态（plan 是唯一权威）。
    返回是否找到该 sub_stage。
    """
    if status not in (STATUS_PENDING, STATUS_DONE, STATUS_EXHAUSTED):
        return False
    s = _step_by_id(_read_plan(record_dir), sub_stage)
    if s is None:
        return False
    _set_status(record_dir, sub_stage, status)
    return True


def regenerate_progress(record_dir: str) -> str:
    """由 orchestration_plan.json 重新生成 progress.md（派生镜像）。

    状态映射：pending→⏳, done→✅, exhausted→⚠️。progress.md 仅供 human/agent
    可读，**不参与任何状态转移**。
    """
    plan = _read_plan(record_dir)
    steps = plan.get("sub_stages") or []
    sym = {"pending": "⏳", "done": "✅", "exhausted": "⚠️"}
    lines = ["| Stage | 状态 | 完成时间 | 备注 |",
             "|-------|------|---------|------|"]
    for s in steps:
        sid = s.get("id", "?")
        desc = s.get("desc", "")
        st = sym.get(s.get("status", "pending"), "⏳")
        lines.append(f"| {sid} {desc} | {st} | - | - |")
    (Path(record_dir) / "progress.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")
    return f"OK: progress.md 已由 orchestration_plan.json 重新生成（{len(steps)} 行）"


def sync_kernel_steps(record_dir: str) -> None:
    """派生 meta.json.kernel_steps = 编排计划中的 C 系列步骤（供旧工具/审计）。"""
    plan = _read_plan(record_dir)
    meta_path = Path(record_dir) / "meta.json"
    if not meta_path.exists():
        return
    kernel = []
    for s in plan.get("sub_stages") or []:
        sid = s.get("id", "")
        if sid.startswith("4.C."):
            kernel.append(sid[2:])
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if kernel:
            meta["kernel_steps"] = kernel
            meta_path.write_text(
                json.dumps(meta, indent=2, ensure_ascii=False),
                encoding="utf-8")
    except Exception:  # noqa: BLE001 — best-effort mirror
        pass


# —— dispatch 内部辅助 ——

# per-type 重试预算的唯一权威表（§2.5 唯一通路）：编排层所有升级决策
# （check_retry_exceeded / codegen._handle_regbase_failure / meta.json 初始化）
# 一律从此表取 limit；meta.json 里的 retries.<key>.limit 仅作展示镜像，不参与判定。
RETRY_COUNTER_LIMITS: dict[str, int] = {
    "stage5_compile": 24,
    "vf_test": 4,
    "stage4_selfcheck": 8,
    "stage3_ambiguity": 3,
}


def _retry_key_label(err_type: str) -> tuple[str, str] | None:
    """错误类型 → (per-type 计数器键, 展示 label)。无计数器类别返回 None。

    ``check_retry_exceeded``（读）与 ``bump_retry_counter``（写）共用的唯一映射
    （§1.15 单点，防两处漂移）。ENV 恒 pause / DSG 恒回退 / 未注册类型不计数。
    """
    if err_type in ("C-SYM", "C-TYP", "C-DUP", "C-LNK", "C-API", "MEM"):
        return "stage5_compile", "compile"
    if err_type == "CK-VF":
        return "vf_test", "vf_test"
    if err_type in ("CK", "CK-FLD", "CK-ALIGN", "CK-REG", "CHK"):
        return "stage4_selfcheck", "selfcheck"
    if err_type in ("AMB", "CMD", "AM-CMD", "AM-PATH", "USR"):
        return "stage3_ambiguity", "ambiguity"
    return None


def _step_retry_count(plan: dict, sid: str) -> int:
    """读取 sub_stage 的失败重试计数（orchestration_plan.json，per-substage）。"""
    step = _step_by_id(plan, sid)
    if step is None:
        return 0
    try:
        return int(step.get("retry_count", 0) or 0)
    except (TypeError, ValueError):
        return 0


def check_retry_exceeded(record_dir: str, sid: str,
                         err_type: str) -> tuple[bool, str]:
    """某 sub_stage 的 per-type 重试预算是否耗尽（per-substage 计数）。

    计数按 sub_stage 隔离（存于 ``orchestration_plan.json`` 的
    ``sub_stage.retry_count``），一个子阶段的失败不消耗其他子阶段的预算；
    limit 取 ``RETRY_COUNTER_LIMITS`` 按 err_type 的映射。env 恒 pause /
    design 恒回退 / 未注册类型维持 allow retry。
    """
    plan = _read_plan(record_dir)
    if err_type in ("ENV", "ENV-CANN", "ENV-DRV", "ENV-CC"):
        return True, "env error always pauses"
    if err_type in ("DSG", "DS-ALG", "KBD"):
        return True, "design error always rolls back"
    kl = _retry_key_label(err_type)
    if kl is None:
        return False, "unknown type, allow retry"
    used = _step_retry_count(plan, sid)
    limit = RETRY_COUNTER_LIMITS[kl[0]]
    return used >= limit, f"{kl[1]} retries {used}/{limit}"


def bump_retry_counter(record_dir: str, sid: str, err_type: str) -> None:
    """递增某 sub_stage 的失败重试计数（per-substage，error-handling.md §6）。

    s4 失败路径（``dispatch`` FAILED 分支 / 并行 VF transition）在
    ``check_retry_exceeded`` 之前调用：递增后读取的 ``used`` 即含本次失败。
    计数落在 ``orchestration_plan.json`` 的 ``sub_stage.retry_count``，按子阶段
    隔离——一个子阶段的失败不消耗其他子阶段的预算。无计数器的错误类型
    （ENV 恒 pause / DSG 恒回退 / 未注册）不递增。
    """
    if not sid:
        return
    kl = _retry_key_label(err_type)
    if kl is None:
        return
    plan = _read_plan(record_dir)
    step = _step_by_id(plan, sid)
    if step is None:
        return
    step["retry_count"] = _step_retry_count(plan, sid) + 1
    _write_plan(record_dir, plan)


def _is_vf_step(record_dir: str, sid: str) -> bool:
    if not sid:
        return False
    plan = _read_plan(record_dir)
    s = _step_by_id(plan, sid)
    if s is not None:
        if s.get("kind") == "vf":
            return True
        # plan 内该 step kind≠vf：若 id 形如 .VT.{M} 仍是 VF 步骤，回退正则识别，
        # 防止 agent 产出的 plan 漏标 kind=vf 时被静默 dispatch 到普通编码 agent
        # （s2 校验门已删，此处是消费端兜底，§1.2 可诊断）。
        if re.match(r".*\.VT\.[0-9]+$", sid, re.IGNORECASE):
            _warn_plan_entry(
                f"sub_stage {sid!r} 的 kind={s.get('kind')!r} 非 vf，按 .VT. 回退识别",
                "plan kind 漏标 → 仍按 VF 步骤路由")
            return True
        return False
    return bool(re.match(r".*\.VT\.[0-9]+$", sid, re.IGNORECASE))


# ─────────────────────────────────────────────────────────────────────────
# agent 最后一轮回复的 RETURN 信号解析
# ─────────────────────────────────────────────────────────────────────────

# 返回信号块起始标记。英文 `RETURN:` 保持原语义（任意位置匹配）；中文 `返回:`
# 只接受 markdown 标题形式（`## 返回:`），避免误匹配正文 prose 中的普通 "返回:"。
# 与 precision_debug_a5.base.parse_agent_return_block 同源、严格语义一致。
_RETURN_BLOCK_RE = re.compile(r"RETURN\s*:|(?:\#+\s*)返回\s*:", re.IGNORECASE)

# 字段名的中英文别名。英文为主（agent 硬契约）；中文为编排层宽容兜底——语言偏差
# 不应静默导致完成信号缺失/错乱。英文名统一加词边界 \b，避免 `status=` 子串误配
# 其他字段名（与 A5 解析器同源处理；`failed_sub_stage` 不含 status 子串，但统一
# 加边界更稳妥）。
_FIELD_NAME_ALIASES: dict[str, list[str]] = {
    "status": ["status", "状态"],
    "error_type": ["error_type", "错误类型"],
    "next_sub_stage": ["next_sub_stage", "下一子阶段"],
    "failed_sub_stage": ["failed_sub_stage", "失败子阶段"],
}

# 各字段的合法取值（等号右侧值域）。
_RETURN_FIELD_VALUES: dict[str, str] = {
    "status": r"[A-Za-z_]+",
    "error_type": r"[A-Za-z0-9_-]+",
    "next_sub_stage": r"[A-Za-z0-9_.-]+",
    "failed_sub_stage": r"[A-Za-z0-9_.-]+",
}


def _build_return_field_res() -> dict:
    out: dict = {}
    for key, names in _FIELD_NAME_ALIASES.items():
        alts: list[str] = []
        for name in names:
            if name.isascii():
                alts.append(r"\b" + re.escape(name))
            else:
                alts.append(re.escape(name))
        out[key] = re.compile(
            r"(?:" + "|".join(alts) + r")\s*=\s*("
            + _RETURN_FIELD_VALUES[key] + r")",
            re.IGNORECASE,
        )
    return out


_RETURN_FIELD_RES = _build_return_field_res()
_COMPLETED_SUB_STAGES_RE = re.compile(
    r"completed_sub_stages\s*=\s*\[([^\]]*)\]", re.IGNORECASE)
_SUB_STAGE_ID_RE = re.compile(r"^4(?:\.[0-9A-Za-z]+)*$")
# regbase-vf-test skill 的返回块：ascendc-vf-test-agent 可能漏写自己的 RETURN 块，
# 只把 skill 的 ``## VF_TEST_RESULT`` 块原样带到最终回复（2026-08-06 group_norm
# run 4.C.3.VT.0 失败无重试的根因）。字段为冒号分隔（status: FAILED / error_type:
# PREC），与 RETURN 的等号分隔并存。锚定 header 后紧跟 status 行，避免误匹配
# 回复正文里对 "VF_TEST_RESULT" 的普通提及。
_VF_RESULT_BLOCK_RE = re.compile(
    r"VF_TEST_RESULT\b[^\n]*\n\s*status\s*[=:]\s*([A-Za-z_]+)",
    re.IGNORECASE)
_VF_RESULT_ERROR_TYPE_RE = re.compile(
    r"error_type\s*[=:]\s*([A-Za-z0-9_-]+)", re.IGNORECASE)


def _extract_fields(text: str, fields: dict) -> dict:
    out: dict = {}
    for key, pat in fields.items():
        fm = pat.search(text)
        if fm:
            out[key] = fm.group(1).upper()
    return out


def parse_return_signal(final_response: str | None) -> dict:
    """从 agent 最后一轮回复解析 RETURN / VF_TEST_RESULT 完成信号（对应 SKILL.md §RETURN 契约）。

    s4-coding / vf-test 在回复末尾输出：
      ``## RETURN: status=COMPLETED, next_stage=4, next_sub_stage=4.F``
    失败时输出：``## RETURN: status=FAILED, error_type=XXX``
    ascendc-vf-test-agent 实际可能只带 regbase-vf-test skill 的 ``## VF_TEST_RESULT``
    块（冒号分隔的 status/error_type）而漏写 RETURN 块 —— 同样被识别，避免把 skill
    的失败自报（FAILED/PREC）静默吞掉、推迟到下游才暴露。

    返回 dict（可能为空）：包含 status/error_type/next_sub_stage，以及 S4 可选的
    completed_sub_stages（有序列表）/failed_sub_stage；标量值统一大写。
    无 RETURN / VF_TEST_RESULT 块 → {}（调用方据此判「无机器可读完成信号」→ FAILED）。
    不做宽松兜底：宽松扫描会误匹配正文中的无关 ``status=``（与
    precision_debug_a5.base.parse_agent_return_block 同源、严格语义一致）。
    """
    if not final_response:
        return {}

    m = _RETURN_BLOCK_RE.search(final_response)
    if m:
        # 只取 RETURN 块头部，避免吞入块后无关文本
        block = final_response[m.start():m.start() + 600]
        out = _extract_fields(block, _RETURN_FIELD_RES)
        completed = _COMPLETED_SUB_STAGES_RE.search(block)
        if completed:
            raw = [item.strip() for item in completed.group(1).split(",")
                   if item.strip()]
            # An explicitly malformed list must not disappear into the legacy
            # single-step fallback.  Return [] so dispatch rejects COMPLETED.
            # Pass the IDs through verbatim — the plan is the authoritative ID
            # source and dispatch validates case-insensitively against it (the
            # prior unconditional `.upper()` corrupted valid lowercase IDs like
            # `4.D.api` → `4.D.API`, making the exact-match gate reject every
            # report and loop the stage).
            out["completed_sub_stages"] = (
                list(raw)
                if all(_SUB_STAGE_ID_RE.fullmatch(item) for item in raw)
                else []
            )
        return out

    m2 = _VF_RESULT_BLOCK_RE.search(final_response)
    if m2:
        out = {"status": m2.group(1).upper()}
        fm = _VF_RESULT_ERROR_TYPE_RE.search(
            final_response[m2.start():m2.start() + 600])
        if fm:
            out["error_type"] = fm.group(1).upper()
        return out

    return {}


def _route_action(record_dir: str, sid: str, group: str) -> dict:
    if _is_vf_step(record_dir, sid):
        return {"action": "call_vf_test", "next_sub_stage": sid,
                "checkpoint_group": group}
    return {"action": "call_s4", "next_sub_stage": sid,
            "checkpoint_group": group}


def _clear_last_error_md(record_dir: str) -> None:
    """清除待修问题诊断（last_error.md），幂等。

    语义与 probe 时代的 ``_clear_regbase_last_error`` 一致：待修问题在 group
    COMPLETED 提交时即确认解决，不再出现在后续 group 的 prompt 注入里。
    消费端是 s4 prompt 的「上次失败诊断」段（codegen.py:_build_s4_prompt）。
    """
    try:
        (Path(record_dir) / "last_error.md").unlink(missing_ok=True)
    except OSError:
        pass


def dispatch(record_dir: str, status: str, error_type: str = "",
             rollback_target: str = "", agent_name: str = "",
             error_detail: str = "",
             completed_sub_stages: list[str] | None = None,
             failed_sub_stage: str = "") -> dict:
    """收到 s4-coding/vf-test 返回后决定下一步动作，返回 decision dict。

    decision dict 的 action 字段 ∈ {finish, call_s4, call_vf_test, retry_s4,
    rollback_s4, vf_exhausted, paused, call_agent, rollback_stage, error}。
    """
    if error_detail:
        Path(record_dir, "last_error.md").write_text(
            error_detail, encoding="utf-8")

    plan = _read_plan(record_dir)
    group_of = lambda sid: (_step_by_id(plan, sid) or {}).get(  # noqa: E731
        "checkpoint_group", "UNKNOWN")

    pending_before = _pending_ids(plan)
    current = pending_before[0] if pending_before else "DONE"
    work_unit = (resolve_execution_group(record_dir, current)
                 if current != "DONE" else [])

    def validate_reported_prefix(*, require_full: bool = False,
                                 require_failure_point: bool = False
                                 ) -> tuple[list[str], str]:
        if current == "DONE":
            return [], ""
        if completed_sub_stages is None:
            # Legacy/backend-only result has no group proof.  COMPLETED may
            # advance one step; failure/partial advances none.
            reported = [current] if require_full else []
            if require_full and len(work_unit) > 1:
                reported = [current]
                return reported, ""
        else:
            reported = completed_sub_stages
        if not isinstance(reported, list) or not all(
                isinstance(item, str) for item in reported):
            return [], (
                "invalid completed_sub_stages: expected a list of sub-stage IDs, "
                f"got {reported!r}")
        # Canonicalize to the plan's IDs (case-insensitive) so both the
        # contiguity check and the downstream `_set_statuses` commit use the
        # authoritative spelling regardless of the agent's casing.
        canonical = _canonicalize_reported(reported, work_unit)
        if canonical is None:
            return [], (
                "invalid completed_sub_stages: expected a contiguous prefix of "
                f"{work_unit}, got {reported}")
        reported = canonical
        if reported != work_unit[:len(reported)]:
            return [], (
                "invalid completed_sub_stages: expected a contiguous prefix of "
                f"{work_unit}, got {reported}")
        if require_full and completed_sub_stages is not None and reported != work_unit:
            return [], (
                "invalid completed_sub_stages for COMPLETED: expected full work unit "
                f"{work_unit}, got {reported}")
        if require_failure_point:
            if len(reported) >= len(work_unit):
                return [], "FAILED cannot report the entire execution group completed"
            expected_failed = work_unit[len(reported)]
            if not failed_sub_stage:
                return [], (
                    f"failed_sub_stage missing: expected {expected_failed} after "
                    f"completed prefix {reported}")
            if failed_sub_stage.casefold() != expected_failed.casefold():
                return [], (
                    f"failed_sub_stage mismatch: expected {expected_failed}, "
                    f"got {failed_sub_stage}")
        return reported, ""

    def commit_or_pause(reported: list[str], error: str) -> dict | None:
        if error:
            return {"action": "paused", "pause_reason": error}
        _set_statuses(record_dir, reported, STATUS_DONE)
        return None

    # COMPLETED：只信 agent 返回的完成信号，不再做磁盘交付物校验。
    # 背景（2026-08-06 add_rms_norm_dynamic_quant run）：plan 的 deliverables 可能
    # 用 mainline 仓 camelCase 命名（op_plugin/OpXxx.cpp），而 s4-coding 按本仓 flat
    # snake_case 约定（op_plugin/xxx_plugin.cpp）正确产出，磁盘校验按字符串匹配
    # 永远报"缺失"→ 3 个 session 白重试（ses_02cc1722/02cb8a9f/02cb435a 全走 4.E）。
    # 空产出/崩溃已由 agent_result.status 语义兜底（ok=有落盘文件，fatal=失败）。
    if status == "COMPLETED":
        if current == "DONE":
            result = {"action": "finish", "next_sub_stage": "DONE",
                      "reason": "Stage 4 all sub-stages completed"}
        else:
            reported, report_error = validate_reported_prefix(require_full=True)
            rejected = commit_or_pause(reported, report_error)
            if rejected is not None:
                return rejected
            # 本组待修问题已确认解决：清除 last_error.md，防止陈旧诊断注入
            # 后续 group 的 s4 prompt（恢复 probe 时代清除语义，§2.9 自检闭环）。
            _clear_last_error_md(record_dir)
            _sync_current_stage(record_dir)
            plan = _read_plan(record_dir)
            nxt = _pending_ids(plan)
            if not nxt:
                result = {"action": "finish", "next_sub_stage": "DONE",
                          "reason": "Stage 4 all sub-stages completed"}
            else:
                result = _route_action(record_dir, nxt[0], group_of(nxt[0]))

    elif status == "PARTIAL":
        reported, report_error = validate_reported_prefix(
            require_failure_point=completed_sub_stages is not None)
        rejected = commit_or_pause(reported, report_error)
        if rejected is not None:
            return rejected
        plan = _read_plan(record_dir)
        nxt = _pending_ids(plan)
        if not nxt:
            result = {"action": "finish", "next_sub_stage": "DONE",
                      "reason": "Stage 4 all sub-stages completed (post-partial)"}
        else:
            result = _route_action(record_dir, nxt[0], group_of(nxt[0]))

    elif status == "FAILED":
        reported, report_error = validate_reported_prefix(
            require_failure_point=completed_sub_stages is not None)
        rejected = commit_or_pause(reported, report_error)
        if rejected is not None:
            return rejected
        # §6 编排层计数（per-substage）：每次 FAILED 先递增**该失败子阶段**的
        # 重试计数，再判是否耗尽——否则 s4 串行失败路径计数恒 0，升级门永不触发
        # （log_softmax 4.C.6 32× 实证）。契约违规已在上方 pause 返回，不计数。
        failure_sid = failed_sub_stage or current
        bump_retry_counter(record_dir, failure_sid, error_type)
        plan = _read_plan(record_dir)
        exceeded, reason = check_retry_exceeded(record_dir, failure_sid, error_type)
        if exceeded:
            current_sub = _pending_ids(plan)
            if current_sub and _is_vf_step(record_dir, current_sub[0]):
                result = {"action": "vf_exhausted",
                          "exhausted_sub_stage": current_sub[0],
                          "reason": reason}
            elif error_type in ("ENV", "ENV-CANN", "ENV-DRV", "ENV-CC"):
                # 环境错误恒 pause（人工修复环境），不回退
                result = {"action": "paused", "pause_reason": reason,
                          "error_type": error_type}
            else:
                # 计数器耗尽（自检/编译/歧义/设计错误）→ 回退 s2 重做设计
                # （保留原 E(t)>=5 的 rollback 状态跳转，去加权；E(t) 已移除）。
                result = {"action": "rollback_s4", "reason": reason,
                          "error_type": error_type}
        else:
            nxt = _pending_ids(plan)
            nxt_sid = nxt[0] if nxt else "DONE"
            grp = group_of(nxt_sid) if nxt else ""
            if _is_vf_step(record_dir, nxt_sid):
                result = {"action": "call_vf_test", "next_sub_stage": nxt_sid,
                          "checkpoint_group": grp,
                          "error_type": error_type, "is_retry": True,
                          "error_detail": error_detail}
            else:
                result = {"action": "retry_s4", "next_sub_stage": nxt_sid,
                          "checkpoint_group": grp,
                          "error_type": error_type,
                          "error_detail": error_detail}

    elif status == "ROLLBACK":
        target = rollback_target
        if not target:
            pending = _pending_ids(plan)
            target = pending[-1] if pending else "DONE"
        if target.startswith("Stage") or (not target.startswith("4.")):
            result = {"action": "rollback_stage", "rollback_target": target,
                      "reason": "cross-stage rollback"}
        else:
            grp = group_of(target)
            if _is_vf_step(record_dir, target):
                result = {"action": "call_vf_test", "next_sub_stage": target,
                          "checkpoint_group": grp,
                          "reason": "intra-stage rollback to VF test",
                          "error_detail": error_detail}
            else:
                result = {"action": "retry_s4", "next_sub_stage": target,
                          "checkpoint_group": grp,
                          "reason": "intra-stage rollback",
                          "error_detail": error_detail}

    elif status == "NEEDS_AGENT":
        result = {"action": "call_agent", "agent_name": agent_name or "unknown",
                  "reason": "SubAgent requested external agent"}

    elif status == "PAUSED":
        result = {"action": "paused", "pause_reason": "SubAgent returned PAUSED"}

    else:
        result = {"action": "paused", "pause_reason": f"unknown status: {status}"}

    return result


# ─────────────────────────────────────────────────────────────────────────
# CLI 入口（供 skill 侧 stage4_scheduler.sh 薄壳转发 + shell 测试使用）
# ─────────────────────────────────────────────────────────────────────────

def cmd_finish_stage4() -> None:
    """输出 Stage 4→5 收尾动作清单（CLI 命令 finish-stage4）。"""
    print("Stage 4 全部完成，主 SKILL 应执行以下收尾：")
    print("1. update_todo(todo-2, completed)  # s4-coding")
    print("2. update_todo(todo-3, completed)  # VF 精度预验证（如适用）")
    print("3. 进入 SKILL.md Step 3（s5-compile）")


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        sys.stderr.write(__doc__ + "\n")
        return 2
    cmd = argv[0]
    args = argv[1:]
    try:
        if cmd == "resolve-sub-stage":
            if len(args) < 2:
                return 2
            print(resolve_sub_stage(args[0], args[1]))
        elif cmd == "get-group":
            if len(args) < 2:
                return 2
            print(get_group(args[0], args[1]))
        elif cmd == "check-gate":
            if not args:
                return 2
            print(check_gate(args[0]))
        elif cmd == "finish-stage4":
            cmd_finish_stage4()
        elif cmd == "dispatch":
            if len(args) < 2:
                return 2
            print(json.dumps(
                dispatch(args[0], args[1],
                         args[2] if len(args) > 2 else "",
                         args[3] if len(args) > 3 else "",
                         args[4] if len(args) > 4 else "",
                         args[5] if len(args) > 5 else ""),
                ensure_ascii=False))
        else:
            sys.stderr.write(__doc__ + "\n")
            return 2
    except Exception as e:  # noqa: BLE001 — CLI errors go to stderr
        sys.stderr.write(f"错误: {e}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
