#!/usr/bin/env python3
"""transition.py — precision_debug 闭环的确定性状态推进器(standalone, 两段闭环)。

这是 TUI 适配器 ``ascendc-precision-adapter`` 的"框架替身":把框架
CompositeGroup 里 driver 必须复刻的路由逻辑(history 物化 / case 推进 /
transition_table 路由)抽成一个无 ``ascendc_devkit`` 依赖的 CLI,供 driver skill
每轮调用。

减法收敛:七 substage → 两段(run_tests ⇄ diagnose)。scope_guard/bounds_check/
printf_location/comment_bisect/diagnose_refine 独立 phase 已删;上游缺陷由
diagnose 入口判据上报(upstream_signal → HALT)。

为什么用脚本而非让 LLM 即兴改 JSON:闭环正确性依赖确定性的状态机不变式
(§1.3 加载期校验优于运行期暴露;§2.7 子 agent 通用协议要求原子化 read→modify→
write)。LLM 维护 JSON 状态机易丢字段,改用确定性脚本是"正确改动落在职责正确的层"。

用法(子命令 ``post-phase``,driver 每轮 phase subagent 返回后调用一次)::

    python3 transition.py post-phase \\
        --control   <debug_artifacts_dir>/control.json \\
        --phase     run_tests \\
        --result    RUN_TESTS_OK \\
        --phase-json <debug_artifacts_dir>/phases/run_tests/precision_run_tests.json \\
        [--max-rounds 30]

stdout 恰好一行 ``NEXT_PHASE=<target>``(target ∈ run_tests / diagnose / DONE /
HALT),后续可附 ``REASON=<...>``。diagnose 诊断+实施一体(无独立 fix 阶段),
RESULT 码与框架 diagnose agent 协议一致。

路由表忠实复刻 precision_debug CompositeGroup 的 transition table 定义(P3 两段)。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

# ── transition_table(复刻 CompositeGroup transition table 定义, 两段)─────────
#   run_tests / diagnose / DONE / HALT
# DONE = 全量通过收工;HALT = 上游缺陷/预算耗尽,停止循环。
# diagnose 诊断+实施一体(fix 阶段已并入 diagnose 实施模式):
#   DIAGNOSED_AND_FIXED → run_tests(全量回归);
#   DIAGNOSE_UPSTREAM → HALT(上游编译/注册/契约错,如实上报);
#   FIX_PARTIAL_OUTPUT → run_tests(部分好转回归);其余 → diagnose 重试。
# 无 scope_guard(上游判据并入 diagnose 入口);无 printf/comment_bisect(二分降为
# diagnose 就地技巧,不产生独立 phase)。

PHASES = ("run_tests", "diagnose")

DEFAULT_MAX_ROUNDS = 30


# ── JSON 原子化读写(§ _shared-protocol.md §1)─────────────────────────────────
def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save(path: str, data: dict) -> None:
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _read_summary(phase_json: str) -> dict:
    """读 phase subagent 写入的 ``_summary``(框架 _read_agent_summary 的等价物)。"""
    if not phase_json or not os.path.exists(phase_json):
        return {}
    try:
        with open(phase_json, encoding="utf-8") as f:
            return json.load(f).get("_summary", {}) or {}
    except (OSError, json.JSONDecodeError):
        return {}


# ── control.json 派生量(复刻 _extract_debug_checkpoint 的路由派生)──────────────
def _current_case(cp: dict) -> dict | None:
    queue = cp.get("failed_case_queue") or []
    idx = cp.get("current_case_index", 0)
    if 0 <= idx < len(queue):
        return queue[idx]
    return None


def _more_cases(cp: dict) -> bool:
    """是否还有未处理的 case(current_case_index 之后还有条目)。"""
    queue = cp.get("failed_case_queue") or []
    return cp.get("current_case_index", 0) < len(queue) - 1


def _advance_current_case(cp: dict) -> None:
    """复刻 _advance_current_case:当前 case 标 skipped,index+1。"""
    queue = cp.get("failed_case_queue") or []
    idx = cp.get("current_case_index", 0)
    if 0 <= idx < len(queue):
        queue[idx]["status"] = "skipped"
    cp["current_case_index"] = idx + 1


def _append_history(cp: dict, phase: str, summary: dict) -> None:
    """复刻 _append_history:从 _summary 追加 history 条目。"""
    cp.setdefault("history", []).append({
        "phase": phase,
        "round": cp.get("rounds", 0),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "content": summary or {},
    })


# ── phase 后处理 + condition 判定 + 路由(复刻各 Substage.transition/resolve_condition)──
def _post_run_tests(cp: dict, summary: dict) -> None:
    """RunTestsSubstage.transition 的框架_owned 部分。

    - run_iter_counter++(下轮 run-cases 写新 iter-N 目录)
    - rounds++(exhausted 判定依据)
    - status==passed:resolved_pending→resolved(全量回归确认)
    """
    cp["run_iter_counter"] = int(cp.get("run_iter_counter", 0)) + 1
    cp["rounds"] = int(cp.get("rounds", 0)) + 1
    if cp.get("status") == "passed":
        for c in cp.get("failed_case_queue") or []:
            if c.get("status") == "resolved_pending":
                c["status"] = "resolved"


def _route_run_tests(cp: dict, result: str, max_rounds: int) -> tuple[str, str]:
    if cp.get("status") == "passed":
        return "DONE", "all_pass"
    if cp.get("rounds", 0) > max_rounds:
        return "HALT", "exhausted(rounds > max_rounds)"
    queue = cp.get("failed_case_queue") or []
    if not queue:
        return "DONE", "no failures"
    return "diagnose", "has_failures"


def _post_diagnose(cp: dict, summary: dict) -> None:
    """DiagnoseSubstage.transition 的框架_owned 部分(简化为两段)。

    - 无 candidate_pool / route_to / corrective_cycles(减法收敛)
    - upstream_signal → 路由 upstream → HALT
    - 弱模型就绪: 成功清错——正常轮清 last_reject_reason(防残留旧拒因误导;
      _route_diagnose 的打回分支随后按需覆盖写入)
    """
    cp["last_reject_reason"] = None


def _route_diagnose(cp: dict, result: str) -> tuple[str, str]:
    """diagnose(诊断+实施一体)路由,忠实复刻框架 resolve_condition(两段闭环 + stalled 自检)。

    减法收敛:无 route_to/printf/comment_bisect——diagnose 就地定位+修,
    printf/注释二分降为就地技巧,不产生独立 phase。上游缺陷 → HALT。
    stalled(假设空间穷尽)必须带 self_check 自检证据,缺失打回 retry 继续调试。
    弱模型就绪: 打回时写 last_reject_reason(round=当前 rounds;driver 组 diagnose
    prompt 时渲染「框架打回」段——与框架 _reject_reason_block 同语义)。
    """
    if cp.get("upstream_signal"):
        return "HALT", f"upstream({cp.get('upstream_stage')}: {cp.get('upstream_reason')})"
    # stalled 必须带 self_check(模型自检证明确实穷尽),
    # 缺失打回 retry——防"累了/想放弃"就声明 stalled(对齐框架 _extract_debug_checkpoint).
    if cp.get("stalled"):
        sd = cp.get("stalled_detail")
        sc = (sd or {}).get("self_check") if isinstance(sd, dict) else None
        if sc:
            return "HALT", "stalled(hypothesis space exhausted, self_check passed)"
        cp["last_reject_reason"] = {
            "cond": "stalled_without_selfcheck",
            "detail": ("声明 stalled 但缺 self_check 自检证据。请按自检项"
                       "(全局理解/多假设已验证/弹药系统排查/确认再试不推进)"
                       "补 self_check 后重新声明,或继续调试产出修复"),
            "round": int(cp.get("rounds", 0) or 0),
        }
        return "diagnose", "stalled_without_selfcheck(retry)"
    if result == "DIAGNOSED_AND_FIXED":
        return "run_tests", "resolved(full regression)"
    if result == "DIAGNOSE_UPSTREAM":
        return "HALT", f"upstream({cp.get('upstream_stage')})"
    if result == "FIX_PARTIAL_OUTPUT":
        return "run_tests", "partial_output(regress)"
    if result == "DIAGNOSED_NO_FIX":
        if _more_cases(cp):
            _advance_current_case(cp)
            return "diagnose", "skip_more(no fix, advance)"
        _advance_current_case(cp)
        return "run_tests", "skip_done(last case, regress)"
    return "diagnose", f"retry(unknown result {result!r}, re-enter diagnose)"


# ── 子命令:post-phase ────────────────────────────────────────────────────────
def cmd_post_phase(args: argparse.Namespace) -> int:
    if args.phase not in PHASES:
        print(f"NEXT_PHASE=HALT  REASON=unknown phase {args.phase!r}", flush=True)
        return 2

    cp = _load(args.control)
    summary = _read_summary(args.phase_json)
    _append_history(cp, args.phase, summary)

    if args.phase == "run_tests":
        _post_run_tests(cp, summary)
        nxt, reason = _route_run_tests(cp, args.result, args.max_rounds)
    else:  # diagnose
        _post_diagnose(cp, summary)
        nxt, reason = _route_diagnose(cp, args.result)

    _save(args.control, cp)
    print(f"NEXT_PHASE={nxt}  REASON={reason}", flush=True)
    return 0


# ── 子命令:init(委托说明,实际初始化由 init-checkpoint.py 完成)──────────────
def cmd_get_start(args: argparse.Namespace) -> int:
    """读 control.json,告诉 driver 起步 phase(始终 run_tests)。"""
    if not os.path.exists(args.control):
        print("NEXT_PHASE=run_tests  REASON=cold_start", flush=True)
        return 0
    cp = _load(args.control)
    if cp.get("status") == "passed":
        print("NEXT_PHASE=DONE  REASON=already_passed", flush=True)
    else:
        print("NEXT_PHASE=run_tests  REASON=resume", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="transition.py",
        description="precision_debug 闭环确定性状态推进器(adapter driver 用, 两段闭环)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("post-phase", help="phase subagent 返回后推进一次")
    p.add_argument("--control", required=True, help="control.json 绝对路径")
    p.add_argument("--phase", required=True, choices=PHASES)
    p.add_argument("--result", required=True,
                   help="subagent 返回的 RESULT 码(如 RUN_TESTS_OK / DIAGNOSED_AND_FIXED)")
    p.add_argument("--phase-json", default="",
                   help="本轮 phase subagent 的 phase 产物 JSON(读 _summary)")
    p.add_argument("--max-rounds", type=int, default=DEFAULT_MAX_ROUNDS,
                   help="run_tests 轮数上限(exhausted 判定)")
    p.set_defaults(func=cmd_post_phase)

    g = sub.add_parser("get-start", help="查询 driver 起步 phase")
    g.add_argument("--control", required=True)
    g.set_defaults(func=cmd_get_start)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        print(f"NEXT_PHASE=HALT  REASON=transition_error({type(exc).__name__}: {exc})",
              flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
