"""F7 残留闭合：perf（代码树生产者）接入统一孤儿路径反馈 helper。

code-tree 生产者类（codegen/perf）的孤儿处置 = transcript Write 证据 → 路径
反馈 + 下轮重生成（不搬回，F2 用户决策）；单点实现见
orchestration/artifact_recovery.py::orphan_path_feedback（§1.15）。本文件守护
perf 侧接线：孤儿轮注入 user_feedback（进下轮 tuning prompt）+ last_error 可观
测；空跑轮（无 Write 证据）不注入反馈。
"""

from __future__ import annotations

import json

from ascendc_devkit.capabilities.agent.backend import AgentResult
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.stages.perf import PerfStage


def _transcript_with_write(tmp_path, target_paths: list[str]):
    records = [{"blocks": [{
        "kind": "tool_use", "tool_name": "write",
        "tool_input": {"input": {"filePath": p}},
    }]} for p in target_paths]
    tp = tmp_path / "t.jsonl"
    tp.write_text("\n".join(json.dumps(r) for r in records) + "\n",
                  encoding="utf-8")
    return tp


def _perf_state(tmp_path) -> State:
    op_dir = tmp_path / "op_dir"
    op_dir.mkdir(parents=True, exist_ok=True)
    return State(mode="new", op_dir=op_dir)


def _gate_result(passed=False):
    return {"gate_result": {"passed": passed, "metrics": {
        "baseline_ms": 1.0, "actual_ms": 2.0}}}


class TestPerfOrphanPathFeedback:
    def test_orphan_round_injects_feedback_and_error(self, tmp_path):
        """perf-tuner 写到 op_dir 外（transcript 证据）→ 注入路径反馈
        （user_feedback）+ last_error=artifact_misplaced，下轮重生成。"""
        state = _perf_state(tmp_path)
        orphan = tmp_path / "run" / "batch-1" / "op_dir" / "kernel.cpp"
        tp = _transcript_with_write(tmp_path, [str(orphan)])
        ar = AgentResult(agent_name="perf-tuner", status="ok",
                         artifacts={}, transcript=tp)
        out = PerfStage().transition(state, {**_gate_result(), "agent_result": ar})
        assert out.user_feedback and "op_dir" in out.user_feedback
        assert out.last_error is not None
        assert out.last_error.error_type == "artifact_misplaced"
        assert out.last_error.stage_name == "perf"
        # 迭代预算照常消耗（无熔断可豁免；反馈换下轮重生成）
        assert out.perf_iterations == state.perf_iterations + 1

    def test_clean_empty_round_gets_no_feedback(self, tmp_path):
        """空跑（无 Write 证据）→ 不注入孤儿反馈（不误导模型查路径）。"""
        state = _perf_state(tmp_path)
        ar = AgentResult(agent_name="perf-tuner", status="ok",
                         artifacts={}, transcript=None)
        out = PerfStage().transition(state, {**_gate_result(), "agent_result": ar})
        assert out.user_feedback == ""
        assert out.last_error is None

    def test_feedback_reaches_next_tuning_prompt(self, tmp_path):
        """孤儿反馈经 user_feedback 进入下轮 tuning prompt（消费端验证）。"""
        state = _perf_state(tmp_path).with_updates(
            user_feedback="你上次把文件写到了 /x/orphan（op_dir 之外），"
                          "请重新生成到正确位置")
        prompt = PerfStage()._build_tuning_prompt(state, iteration=2)
        assert "你上次把文件写到了" in prompt

    def test_successful_round_clears_stale_feedback(self, tmp_path):
        """成功轮清掉上一轮孤儿反馈（P5 语义：成功清 sticky 反馈）——不把
        过期路径反馈带进后续无关注轮。"""
        state = _perf_state(tmp_path).with_updates(
            user_feedback="你上次把文件写到了 /x/orphan（op_dir 之外）")
        ar = AgentResult(agent_name="perf-tuner", status="ok",
                         artifacts={"op_kernel/kernel.cpp": "// tuned"})
        out = PerfStage().transition(state, {**_gate_result(), "agent_result": ar})
        assert out.user_feedback == ""
        assert "op_kernel/kernel.cpp" in out.generated_sources
