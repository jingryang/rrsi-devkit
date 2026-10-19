"""UT — ascendc-precision-adapter transition.py 路由收口守护（P3 减法两段）。

P3 减法：七 substage → 两段（run_tests ⇄ diagnose）。scope_guard / printf /
comment_bisect / bounds_check / diagnose_refine 独立 phase 已删；上游缺陷由
diagnose 入口判据上报（upstream_signal → HALT）。adapter 的 transition.py 必须
与框架两阶段保持一致——本测试用结构信号（PHASES 集合 / RESULT 码路由目标）
守护两条通路不再分叉。
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_SCRIPT = (_REPO / ".claude/skills/ascendc-precision-adapter/scripts/transition.py").resolve()

spec = importlib.util.spec_from_file_location("adapter_transition", _SCRIPT)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


def _base_control() -> dict:
    """最小可路由 control.json：两个失败 case、无 upstream。"""
    return {
        "status": "failed",
        "rounds": 1,
        "current_case_index": 0,
        "failed_case_queue": [
            {"case_id": "c0", "status": "pending"},
            {"case_id": "c1", "status": "pending"},
        ],
        "upstream_signal": False,
        "upstream_stage": None,
        "upstream_reason": None,
    }


# —— 结构收口：PHASES 收敛为两段 —————————————————————————————————————————————

def test_phases_match_two_stage() -> None:
    """P3 减法: adapter PHASES 收敛为 run_tests/diagnose（scope_guard/printf 已删）。"""
    assert "fix" not in mod.PHASES
    assert set(mod.PHASES) == {"run_tests", "diagnose"}


# —— run_tests 路由：RESULT 码 → 下一 phase ——————————————————————————————————

def test_run_tests_all_pass_done() -> None:
    cp = _base_control()
    cp["status"] = "passed"
    nxt, _ = mod._route_run_tests(cp, "RUN_TESTS_OK", 30)
    assert nxt == "DONE"


def test_run_tests_has_failures_routes_diagnose() -> None:
    nxt, _ = mod._route_run_tests(_base_control(), "RUN_TESTS_OK", 30)
    assert nxt == "diagnose"


# —— diagnose 路由：RESULT 码 → 下一 phase ——————————————————————————————————

def test_diagnose_and_fixed_routes_to_run_tests() -> None:
    nxt, _ = mod._route_diagnose(_base_control(), "DIAGNOSED_AND_FIXED")
    assert nxt == "run_tests"


def test_diagnose_upstream_halts() -> None:
    """diagnose 上报 upstream_signal → HALT（上游编译/注册/契约错，如实上报）。"""
    cp = _base_control()
    cp["upstream_signal"] = True
    cp["upstream_stage"] = "codegen"
    cp["upstream_reason"] = "schema 不匹配"
    nxt, reason = mod._route_diagnose(cp, "DIAGNOSE_UPSTREAM")
    assert nxt == "HALT"
    assert "upstream" in reason


def test_diagnose_no_fix_advances_when_more_cases() -> None:
    """DIAGNOSED_NO_FIX: 有更多 case → advance + 回 diagnose（不退出组）。"""
    cp = _base_control()
    nxt, _ = mod._route_diagnose(cp, "DIAGNOSED_NO_FIX")
    assert nxt == "diagnose"
    assert cp["current_case_index"] == 1  # advance 到下一 case


def test_diagnose_no_fix_regresses_when_last_case() -> None:
    """DIAGNOSED_NO_FIX: 末 case → run_tests 回归（收敛）。"""
    cp = _base_control()
    cp["current_case_index"] = 1  # 末 case
    nxt, _ = mod._route_diagnose(cp, "DIAGNOSED_NO_FIX")
    assert nxt == "run_tests"


def test_diagnose_partial_output_regresses() -> None:
    """FIX_PARTIAL_OUTPUT: 部分好转 → run_tests 回归（重测 per-output diffs）。"""
    cp = _base_control()
    nxt, _ = mod._route_diagnose(cp, "FIX_PARTIAL_OUTPUT")
    assert nxt == "run_tests"


def test_diagnose_unknown_result_retries() -> None:
    """未知 RESULT 码 → 回 diagnose 重试（不静默误路由）。"""
    cp = _base_control()
    nxt, reason = mod._route_diagnose(cp, "GARBAGE_RESULT")
    assert nxt == "diagnose"
    assert "retry" in reason


def test_diagnose_stalled_with_selfcheck_halts() -> None:
    """§judgment-ownership (P5): stalled 带 self_check（模型自检证明确实穷尽）→ HALT。
    对齐框架——尽力后诚实报告，供上游/人工接续。"""
    cp = _base_control()
    cp["stalled"] = True
    cp["stalled_detail"] = {"self_check": [{"item": "read kernel", "passed": True}]}
    nxt, reason = mod._route_diagnose(cp, "DIAGNOSED_STALLED")
    assert nxt == "HALT"
    assert "stalled" in reason


def test_diagnose_stalled_without_selfcheck_retries() -> None:
    """§judgment-ownership (P5) 防偷懒: stalled 缺 self_check（没证明确实穷尽）→
    打回 retry 继续调试（不是静默接受），防"累了/想放弃"就声明 stalled。"""
    cp = _base_control()
    cp["stalled"] = True  # 无 stalled_detail
    nxt, reason = mod._route_diagnose(cp, "DIAGNOSED_STALLED")
    assert nxt == "diagnose"
    assert "selfcheck" in reason or "retry" in reason
    # stalled_detail 无 self_check 也打回
    cp2 = _base_control()
    cp2["stalled"] = True
    cp2["stalled_detail"] = {"exhausted_reason": "很难"}
    nxt2, _ = mod._route_diagnose(cp2, "DIAGNOSED_STALLED")
    assert nxt2 == "diagnose"


# —— CLI 端到端：post-phase 拒绝已删 phase ——————————————————————————————————

def test_post_phase_rejects_scope_guard(tmp_path: Path) -> None:
    """scope_guard 已删 → post-phase 拒绝。"""
    ctrl = tmp_path / "control.json"
    ctrl.write_text(json.dumps(_base_control()), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), "post-phase",
         "--control", str(ctrl), "--phase", "scope_guard", "--result", "SCOPE_UPSTREAM"],
        capture_output=True, text=True, timeout=30)
    assert proc.returncode != 0
    assert "invalid choice" in proc.stderr and "scope_guard" in proc.stderr


def test_post_phase_rejects_printf(tmp_path: Path) -> None:
    """printf 已删 → post-phase 拒绝。"""
    ctrl = tmp_path / "control.json"
    ctrl.write_text(json.dumps(_base_control()), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), "post-phase",
         "--control", str(ctrl), "--phase", "printf", "--result", "PRINTF_FIXED"],
        capture_output=True, text=True, timeout=30)
    assert proc.returncode != 0
    assert "invalid choice" in proc.stderr and "printf" in proc.stderr
