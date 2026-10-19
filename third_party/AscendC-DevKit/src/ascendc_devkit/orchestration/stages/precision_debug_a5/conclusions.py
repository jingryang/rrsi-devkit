"""Cross-phase conclusion relay for A5 precision_debug.

Each phase agent writes a one-paragraph ``conclusion`` field inside its own
phase result JSON (e.g. ``kernel_debug_round_2_result.json``). The framework
materializes it here into a single shared relay file
(``{debug_dir}/conclusions.json``), keyed by phase and preserving round
history, and tracks ``last`` = the most recently completed agent.

At spawn time the framework injects ONLY ``last`` (the current agent's
"previous agent" conclusion) into the prompt; the full per-phase/round history
stays in the file for the agent to read via ``conclusions_path``. This is the
cross-phase file relay described by §2.3 (I/O 契约 = 文件): every agent
constructively sees its predecessor's conclusion without the prompt carrying
more than that.

Ownership: agents write ONLY their own phase result JSON's ``conclusion``; the
framework is the sole writer of ``conclusions.json`` (mirrors the checkpoint
guard pattern — shared routing/observability state is framework-owned).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ascendc_devkit.orchestration.kernel.state import State

_CONCLUSIONS_FILE = "conclusions.json"


def _conclusions_path(state: "State") -> Path | None:
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _debug_artifacts_dir,
    )
    d = _debug_artifacts_dir(state)
    return None if d is None else d / _CONCLUSIONS_FILE


def _read_conclusions(state: "State") -> dict:
    p = _conclusions_path(state)
    if p is None or not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        from ascendc_devkit.infra.logger import Logger
        Logger.warn(f"[A5-PD-CONCLUSION] 读取 {p} 失败（{exc}），按空处理")
        return {}


def _format_conclusions_block(state: "State") -> str:
    """Render only the most recently completed agent's conclusion into a block.

    Called by ``_common_context`` at spawn time and injected into the agent
    prompt, so every agent *constructively* sees its previous agent's conclusion
    (not just a file path it would have to Read itself — §2.9 构造性保证优先于
    检查门). Deliberately bounded: only the last entry rides the prompt; the full
    per-phase/round history stays in ``conclusions.json`` for the agent to read
    via ``conclusions_path`` — the injection never carries "more" than the
    immediately preceding agent.
    """
    data = _read_conclusions(state)
    last = data.get("last") or {}
    lines = ["## 上一个已完成 agent 的结论（框架注入，无需自行读文件）"]
    conclusion = str(last.get("conclusion", "")).strip()
    if not conclusion:
        lines.append("- （暂无已完成阶段的结论）")
    else:
        lines.append(
            f"- **{last.get('phase')}** (round {last.get('round')}): {conclusion}"
        )
    lines.append("- 完整历史结论请读取上方 `conclusions_path` 指向的 `conclusions.json`。")
    return "\n".join(lines)


def _materialize_conclusion(
    state: "State", phase: str, round_num: int, phase_result: dict,
) -> None:
    """Append this phase round's one-paragraph conclusion to the relay file.

    Reads ``phase_result["conclusion"]`` (string). Skips silently-empty or
    missing conclusions (the field is skill-mandated; a missing one leaves a
    warn so the gap is diagnosable, not swallowed — §1.2). Writes atomically
    (read → merge → write) so a single writer never tears the file.
    """
    from ascendc_devkit.infra.logger import Logger
    conclusion = (phase_result or {}).get("conclusion")
    if conclusion is None:
        Logger.warn(
            f"[A5-PD-CONCLUSION] {phase} round {round_num}: phase result 缺 "
            f"`conclusion` 字段（skill 要求一段话结论），未写入 conclusions.json"
        )
        return
    if not str(conclusion).strip():
        Logger.warn(
            f"[A5-PD-CONCLUSION] {phase} round {round_num}: `conclusion` 为空字符串，"
            f"未写入 conclusions.json"
        )
        return
    p = _conclusions_path(state)
    if p is None:
        return
    data = _read_conclusions(state)
    phases = data.setdefault("phases", {})
    entry = {
        "round": round_num,
        "conclusion": str(conclusion).strip(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    phases.setdefault(phase, []).append(entry)
    # ``last`` = 最近一个完成的 agent（当前 spawn 的"上一个 agent"）。prompt 只注入它，
    # 完整历史由 agent 从 `conclusions_path` 读文件（注入不膨胀、不携带更多）。
    data["last"] = {"phase": phase, **entry}
    data["updated_at"] = entry["updated_at"]
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        Logger.warn(f"[A5-PD-CONCLUSION] write {p} failed: {exc}")
