"""20260820 — codegen 孤儿逃生：熔断/孤儿区分（F2 剩余缺口 + circuit breaker 修正）。

覆盖 _transition_membase 失败分支：
- 孤儿（transcript 有 Write 证据写到 op_dir 外）→ 不消耗熔断，注入路径反馈重试。
- 空跑（transcript 无 Write 证据）→ 消耗熔断（+1）。
- max_consecutive_failures = 5（用户决策：空跑可做 5 次重试）。
"""

import json
from pathlib import Path

import pytest
from ascendc_devkit.capabilities.agent.backend import AgentResult
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.stages.codegen import CodegenStage
from ascendc_devkit.capabilities.agent._shared import _transcript_orphan_paths


def _transcript_with_write(tmp_path, target_paths: list[str]) -> Path:
    """Build a transcript jsonl with one write block per target path."""
    records = []
    for p in target_paths:
        records.append({"blocks": [{
            "kind": "tool_use",
            "tool_name": "write",
            "tool_input": {"input": {"filePath": p}},
        }]})
    tp = tmp_path / "t.jsonl"
    tp.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return tp


def _state_with_opdir(tmp_path) -> tuple[State, Path]:
    """State with a cann-bench-like op_dir under tmp_path (no artifacts tree —
    op_dir is the codegen working_dir; orphan detection uses batch anchor only
    when both sides resolve one; op_dir has none → orphans with none also pass)."""
    op_dir = tmp_path / "op_dir"
    op_dir.mkdir(parents=True, exist_ok=True)
    return State(mode="new", op_dir=op_dir, codegen_iterations=0), op_dir


class TestTranscriptionOrphanPaths:
    """_transcript_orphan_paths 纯函数行为。"""

    def test_finds_write_outside_wd_same_batch(self, tmp_path):
        batch = tmp_path / "run"
        wd = batch / "20260820-103324-164bbc" / "artifacts" / "design" / "general-design-generator"
        wd.mkdir(parents=True)
        orphan_dir = batch / "20260820-164bbc" / "artifacts" / "design" / "general-design-generator"
        orphan_dir.mkdir(parents=True)
        orphan = orphan_dir / "tiling.h"
        tp = _transcript_with_write(tmp_path, [str(orphan), str(wd / "ok.h")])
        got = _transcript_orphan_paths(str(tp), wd)
        assert len(got) == 1, f"应只有孤儿，got {got}"
        assert "164bbc" in got[0] and "103324" not in got[0]

    def test_no_transcript_returns_empty(self, tmp_path):
        _, op_dir = _state_with_opdir(tmp_path)
        assert _transcript_orphan_paths(None, op_dir) == []

    def test_empty_transcript_returns_empty(self, tmp_path):
        _, op_dir = _state_with_opdir(tmp_path)
        tp = tmp_path / "empty.jsonl"
        tp.write_text("", encoding="utf-8")
        assert _transcript_orphan_paths(str(tp), op_dir) == []

    def test_write_inside_wd_not_orphan(self, tmp_path):
        batch = tmp_path / "run"
        wd = batch / "20260820-103324-164bbc" / "artifacts" / "design" / "general-design-generator"
        wd.mkdir(parents=True)
        inside = wd / "kernel.h"
        tp = _transcript_with_write(tmp_path, [str(inside)])
        assert _transcript_orphan_paths(str(tp), wd) == []

    def test_cross_batch_write_not_orphan_when_wd_has_anchor(self, tmp_path):
        """wd 有 batch 锚点（design 场景）时，跨 batch 的 Write 不算孤儿（防跨 run 误判）。"""
        batch = tmp_path / "run"
        wd = batch / "20260820-103324-164bbc" / "artifacts" / "design" / "general-design-generator"
        wd.mkdir(parents=True)
        other_batch = tmp_path / "other-batch" / "x" / "artifacts" / "design" / "gd"
        other_batch.mkdir(parents=True)
        other = other_batch / "kernel.h"
        tp = _transcript_with_write(tmp_path, [str(other)])
        # wd 有 batch 锚点（run），other 有（other-batch）→ 不同 → 不算孤儿
        assert _transcript_orphan_paths(str(tp), wd) == []

    def test_codegen_wd_no_anchor_orphan_recognized(self, tmp_path):
        """codegen 场景（op_dir 无 artifacts 树）→ wd 外 Write 即孤儿（反馈重试安全）。"""
        batch = tmp_path / "run"
        op_dir = tmp_path / "op_dir"  # 无 artifacts 树 → batch 锚点 None
        op_dir.mkdir(parents=True)
        orphan_dir = batch / "20260820-164bbc" / "op_dir"
        orphan_dir.mkdir(parents=True)
        orphan = orphan_dir / "kernel.h"
        tp = _transcript_with_write(tmp_path, [str(orphan)])
        got = _transcript_orphan_paths(str(tp), op_dir)
        assert len(got) == 1, f"codegen 场景孤儿应被识别，got {got}"


class TestCodegenBreakerSemantics:
    """孤儿 vs 空跑：熔断/反馈区分。"""

    def test_consecutive_failures_threshold_from_config(self):
        from ascendc_devkit.orchestration.runtime_config import retry_budgets
        assert retry_budgets()["consecutive_failures_max"] == 5, (
            "用户决策：空跑可做 5 次重试")

    def test_orphan_does_not_consume_breaker(self, tmp_path):
        """孤儿 → 不 +1，注入 user_feedback 路径反馈，走迭代预算重试。

        F5: 孤儿从 backend 视角就是干净完成 + 零产物（status="ok"，
        artifacts={}，文件写在 op_dir 外收集不到）——判据是 transcript 的
        Write 证据，不是 status 字面量。"""
        state, op_dir = _state_with_opdir(tmp_path)
        # 构造孤儿：transcript 有 Write 写到 op_dir 外（同 batch 结构）
        batch = tmp_path / "run"
        orphan_dir = batch / "20260820-164bbc" / "op_dir"
        orphan_dir.mkdir(parents=True)
        orphan = orphan_dir / "kernel.h"
        tp = _transcript_with_write(tmp_path, [str(orphan)])
        agent_result = AgentResult(
            agent_name="ascendc-coder", status="ok",
            artifacts={}, transcript=tp)
        stage = CodegenStage()
        out = stage.transition(state, {"agent_result": agent_result})
        assert out.codegen_consecutive_failures == 0, "孤儿不应消耗熔断"
        assert "op_dir" in out.user_feedback, "应注入路径反馈"
        assert "orphan" in str(out.last_error.error_type).lower() \
            or "artifact_misplaced" == out.last_error.error_type

    def test_empty_run_consumes_breaker(self, tmp_path):
        """空跑（干净完成 + 零产物 + transcript 无 Write 证据）→ +1，
        error_type=incomplete_output（对齐 state taxonomy，selffix 类可重试；
        不再让 status 字面量泄入 error_type）。"""
        state, _ = _state_with_opdir(tmp_path)
        agent_result = AgentResult(
            agent_name="ascendc-coder", status="ok",
            artifacts={}, transcript=None)
        stage = CodegenStage()
        out = stage.transition(state, {"agent_result": agent_result})
        assert out.codegen_consecutive_failures == 1, "空跑应消耗熔断 +1"
        assert out.user_feedback == "", "空跑不应有路径反馈"
        assert out.last_error.error_type == "incomplete_output"
        assert "零产物" in out.last_error.message

    def test_orphan_feedback_rendered_in_next_prompt(self, tmp_path):
        """孤儿反馈通过 user_feedback 注入下轮 coder prompt（消费端验证）。"""
        state, _ = _state_with_opdir(tmp_path)
        state = state.with_updates(
            user_feedback="你上次把文件写到了 /x/orphan（op_dir 之外），请重新生成",
            design_spec={"inputs": []},
            codegen_iterations=1,
        )
        stage = CodegenStage()
        from ascendc_devkit.orchestration.kernel.action import SpawnAgent
        actions = stage.actions(state, iteration=2)
        spawns = [a for a in actions if isinstance(a, SpawnAgent)]
        assert spawns, "codegen actions 应产生 SpawnAgent"
        assert "你上次把文件写到了" in spawns[0].prompt, \
            "孤儿反馈应注入下轮 coder prompt"


class TestF8OrphanExemptWindow:
    """F8（2026-08-21）：孤儿豁免有界化——连续孤儿在 retry_budgets.orphan_exempt_window
    （=2）内豁免熔断（公平机会）；超窗后按空跑同样消耗熔断，最坏 窗口+熔断阈值 发
    halt，而非烧满迭代预算（1000）。"""

    def _orphan(self, tmp_path, name="ascendc-coder"):
        state, op_dir = _state_with_opdir(tmp_path)
        batch = tmp_path / "run"
        orphan_dir = batch / "20260820-164bbc" / "op_dir"
        orphan_dir.mkdir(parents=True)
        orphan = orphan_dir / "kernel.h"
        tp = _transcript_with_write(tmp_path, [str(orphan)])
        return state, AgentResult(agent_name=name, status="ok",
                                  artifacts={}, transcript=tp)

    def test_within_window_exempts_breaker(self, tmp_path):
        """第 1、2 次连续孤儿：不消耗熔断，streak 递增。"""
        from ascendc_devkit.orchestration.runtime_config import retry_budgets
        window = retry_budgets()["orphan_exempt_window"]
        state, ar = self._orphan(tmp_path)
        for i in range(1, window + 1):
            out = CodegenStage().transition(state, {"agent_result": ar})
            assert out.codegen_consecutive_failures == 0, \
                f"第 {i} 次孤儿窗口内应豁免熔断"
            assert out.codegen_orphan_streak == i
            assert out.last_error.error_type == "artifact_misplaced"
            state = out

    def test_beyond_window_consumes_breaker(self, tmp_path, capsys):
        """第 3 次连续孤儿（超窗）：消耗熔断 +1，WARN 明示超窗。"""
        from ascendc_devkit.orchestration.runtime_config import retry_budgets
        window = retry_budgets()["orphan_exempt_window"]
        state, ar = self._orphan(tmp_path)
        for _ in range(window):
            state = CodegenStage().transition(state, {"agent_result": ar})
        out = CodegenStage().transition(state, {"agent_result": ar})
        assert out.codegen_consecutive_failures == 1, "超窗孤儿应消耗熔断 +1"
        assert out.codegen_orphan_streak == window + 1
        err = capsys.readouterr().err
        assert "超豁免窗口" in err and f"{window + 1}" in err

    def test_empty_round_resets_streak(self, tmp_path):
        """孤儿 → 空跑（无 Write 证据）：尾分支清 streak（孤儿计数中断）+ 空跑熔断 +1。"""
        state, ar = self._orphan(tmp_path)
        state = CodegenStage().transition(state, {"agent_result": ar})   # 孤儿 streak=1
        empty = AgentResult(agent_name="ascendc-coder", status="ok",
                            artifacts={}, transcript=None)
        out = CodegenStage().transition(state, {"agent_result": empty})
        assert out.codegen_orphan_streak == 0, "空跑应清孤儿 streak"
        assert out.codegen_consecutive_failures == 1, "空跑熔断 +1"

    def test_success_resets_streak(self, tmp_path):
        """孤儿 → 成功：成功路径清 streak（孤儿计数中断）+ 熔断清零。"""
        state, ar = self._orphan(tmp_path)
        state = CodegenStage().transition(state, {"agent_result": ar})   # 孤儿 streak=1
        ok = AgentResult(agent_name="ascendc-coder", status="ok",
                         artifacts={"op_host/op_tiling.cpp": "// x"})
        out = CodegenStage().transition(state, {"agent_result": ok})
        assert out.codegen_orphan_streak == 0, "成功应清孤儿 streak"
        assert out.codegen_consecutive_failures == 0

    def test_seven_consecutive_orphans_trip_breaker(self, tmp_path):
        """2 豁免 + 5 消耗 = 7 连孤儿 → 熔断阈值触发（actions 返回 []）。"""
        from ascendc_devkit.orchestration.runtime_config import retry_budgets
        window = retry_budgets()["orphan_exempt_window"]
        breaker = retry_budgets()["consecutive_failures_max"]
        state, ar = self._orphan(tmp_path)
        for _ in range(window + breaker):
            state = CodegenStage().transition(state, {"agent_result": ar})
        stage = CodegenStage()
        assert state.codegen_consecutive_failures >= breaker
        assert stage.actions(state) == [], "熔断触发应停止 spawn"
