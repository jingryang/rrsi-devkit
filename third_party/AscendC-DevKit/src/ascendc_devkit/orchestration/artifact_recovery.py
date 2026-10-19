"""L3 Orchestration — orphan-artifact disposal layer (single authority).

处置层唯一通路（§2.5）：transcript 证据 → 孤儿产物要么「防御性搬回」（小产物，
locate 失败同轮自愈），要么「路径反馈 + 重生成」（代码树）。检测层在
capabilities/agent/_shared.py（单一权威源：transcript → 孤儿证据）；本模块只做
处置，不重复解析，也不持有本地检测拷贝（F1/F2 时期 design_substages 与此处并存
双份 "Mirrors" 拷贝已收编）。

- ``recover_orphan_artifact``：locate 失败时把证据指向的孤儿搬回 wd（四重约束 +
  防御性 move + WARN + events.jsonl artifact_relocated 事件）。
- ``orphan_path_feedback``：给代码树生产者（codegen/perf）生成标准孤儿路径反馈，
  供下轮重生成（判定与文案单点；熔断豁免/迭代计数等 stage 私有语义留消费方）。

分层归属：处置属编排职责（搬回决策要 stage 语境），放 orchestration；检测留
capabilities/agent（transcript 解析属 agent 层）。依赖方向 orchestration →
capabilities，合法。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from ascendc_devkit.capabilities.agent._shared import (
    _harvest_relocation_evidence_detailed,
    _transcript_orphan_paths,
)
from ascendc_devkit.infra.event_log import EventLog
from ascendc_devkit.infra.logger import Logger
from ascendc_devkit.orchestration.kernel import event as evt


def _emit_relocated_event(state, stage_name: str, filename: str,
                          from_path: str, to_path: str, outcome: str) -> None:
    """Append an ``artifact_relocated`` event to events.jsonl.

    Emits via the process-shared ``EventLog.for_path`` instance (runner 与
    artifact_recovery 同路径写者串行化在显式锁上，不依赖 O_APPEND 原子性，
    20260821 F3 加固)。workspace 不可达（State.empty()/UT）→ 跳过事件不炸主流程
    ——可诊断降级，非静默（WARN 由调用方另行发出，本身就是信号）。
    """
    ws = getattr(state, "_workspace", None)
    if ws is None:
        return
    try:
        events_path = ws.events_path
        EventLog.for_path(events_path).append(
            evt.artifact_relocated(stage_name, filename, from_path, to_path,
                                   outcome))
    except Exception:  # noqa: BLE001 — event emission is best-effort, never breaks recovery
        Logger.warn(
            f"[{stage_name}] artifact_relocated 事件写 events.jsonl 失败"
            f"（忽略，WARN 通道已保留）")


def recover_orphan_artifact(transcript, filename, wd, state, stage_name) -> bool:
    """Defensive in-place recovery of a transcript-evidenced orphan product.

    前置约束全部沿用检测层（``_harvest_relocation_evidence_detailed``）：
      1. 文件名容忍匹配产物契约（同 ext + 归一化 stem）；
      2. transcript 证明本次 agent 所写（Write/Edit tool_use）；
      3. 路径解析在 wd 之外；
      4. 同 batch（双侧可解析且相同；任一 None 放行，跨 batch 明确拒绝）。

    move 防御（从方案 A 分支原样移植，不重写）：
    - target 不存在 → ``shutil.move``，WARN + events.jsonl 事件（outcome=moved）
    - target 存在且 samefile → 幂等跳过（落回解析，不发事件）
    - target 存在且不同文件 → 拒绝覆盖（outcome=refused_target_exists），WARN
    - 证据文件已不存在 → WARN + 走 missing（outcome=orphan_gone）

    Returns True = 恢复成功（调用方可重新 locate 成功，同轮自愈）；False = 拒搬/
    无证据（落回既有 missing/重试路径，行为=收口前）。
    """
    if wd is None:
        return False
    wd = Path(wd)
    evidence_path, refuse_reason = _harvest_relocation_evidence_detailed(
        transcript, filename, wd)
    if evidence_path is None:
        if refuse_reason == "cross_batch":
            Logger.warn(
                f"[{stage_name}] 孤儿产物 {filename} 证据指向跨 batch 路径，"
                f"拒绝搬回（防跨 run 误搬），走 missing 重试")
        return False
    if not evidence_path.is_file():
        _emit_relocated_event(state, stage_name, filename,
                              str(evidence_path), str(wd / filename),
                              "orphan_gone")
        Logger.warn(
            f"[{stage_name}] 孤儿产物 {filename} 证据文件已不存在"
            f"（{evidence_path}）——走 missing 重试")
        return False
    target = wd / filename
    if target.exists():
        try:
            same = target.samefile(evidence_path)
        except OSError:
            same = False
        if same:
            Logger.warn(
                f"[{stage_name}] 孤儿产物 {filename} 与 wd 产物是同一文件"
                f"（samefile），幂等跳过")
            return True
        _emit_relocated_event(state, stage_name, filename,
                              str(evidence_path), str(target),
                              "refused_target_exists")
        Logger.warn(
            f"[{stage_name}] 孤儿产物 {filename} 目标已存在且为不同文件，"
            f"拒绝覆盖（{evidence_path} → {target}），走 missing 重试")
        return False
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(evidence_path), str(target))
    except OSError as e:
        Logger.warn(f"[{stage_name}] 孤儿产物 {filename} 搬回失败：{e}")
        return False
    _emit_relocated_event(state, stage_name, filename,
                          str(evidence_path), str(target), "moved")
    Logger.warn(
        f"[{stage_name}] 搬回孤儿产物 {filename}: {evidence_path} → {target}")
    return True


def orphan_path_feedback(agent_result, working_dir, stage_name,
                         locator_name: str = "working_dir"):
    """Code-tree producers' unified orphan path feedback (F7, §1.15).

    证据（``_shared._transcript_orphan_paths``，与小产物搬回同一证据源）→ 判定 +
    标准路径反馈文本 + WARN。返回 ``(orphan_paths, feedback)``；无证据返回
    ``([], "")``。判定与文案单点；熔断豁免/迭代计数等 stage 私有语义留消费方接线
    （codegen 窗口内豁免熔断、perf 照常消耗迭代预算）。
    """
    transcript = getattr(agent_result, "transcript", None)
    orphan_paths = _transcript_orphan_paths(transcript, working_dir)
    if not orphan_paths:
        return [], ""
    path_list = "; ".join(orphan_paths)
    feedback = (
        f"你上次把文件写到了 {locator_name}（{working_dir}）之外的路径，未就位："
        f"{path_list}。这些是孤儿产物，本轮未计入代码树。请把代码重新生成到 "
        f"{locator_name} 下的正确位置（{working_dir}）；禁止拼写绝对路径，"
        f"用相对路径。"
    )
    Logger.warn(
        f"[{stage_name}] 孤儿产物（写于 {locator_name} 之外，共 "
        f"{len(orphan_paths)} 个）：{path_list}")
    return orphan_paths, feedback
