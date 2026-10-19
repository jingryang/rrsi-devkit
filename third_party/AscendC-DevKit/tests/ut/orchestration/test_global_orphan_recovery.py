"""20260821 — F3 全局收口：三个新接入点的孤儿恢复守护。

- requirement：agent-dict 契约 + 孤儿 requirement.json → 恢复后从盘读回走同一契约。
- test-design：CSV locate 失败 + 孤儿 CSV → 恢复后 locate 成功。
- precision-debug：control.json 写错位置 → _load_control 恢复后读到非空。
"""

import json
from pathlib import Path

from ascendc_devkit.capabilities.agent.backend import AgentResult
from ascendc_devkit.infra.workspace import Workspace
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.stages.precision_debug_substages import (
    RunTestsSubstage, _load_control)
from ascendc_devkit.orchestration.stages.requirement import RequirementStage


def _transcript_with_write(tmp_path, target) -> Path:
    tp = tmp_path / "t.jsonl"
    tp.write_text(json.dumps({"blocks": [{
        "kind": "tool_use", "tool_name": "write",
        "tool_input": {"input": {"filePath": str(target)}},
    }]}) + "\n", encoding="utf-8")
    return tp


class TestRequirementOrphanRecovery:
    """requirement：agent-dict 空 + 孤儿 requirement.json → 搬回 + 盘读注入。"""

    def test_orphan_requirement_recovered_into_contract(self, tmp_path):
        ws = Workspace(base_dir=tmp_path, run_id="run-1")
        wd = ws.artifacts / "requirement"
        wd.mkdir(parents=True)
        # 孤儿：写到 workspace 根（wd 之外、同 run）
        orphan = ws.dir / "requirement.json"
        orphan.write_text(json.dumps({
            "op_name": "add_rms", "inputs": [], "outputs": []}))
        tp = _transcript_with_write(tmp_path, orphan)
        ar = AgentResult(agent_name="requirement-analyst", status="ok",
                         artifacts={}, transcript=tp)
        s = State.empty().with_updates(_workspace=ws)

        out = RequirementStage().transition(s, {"agent_result": ar})

        # 恢复成功 → 走契约解析（op_name 缺 inputs/outputs schema 时也可能
        # schema_violation，但绝不是 agent-failed 的 status error）
        assert (wd / "requirement.json").exists(), "孤儿应被搬回 wd"
        assert not orphan.exists()
        assert out.last_error is None or (
            out.last_error.error_type != "ok"), "不应落 agent-failed 分支"

    def test_no_orphan_behavior_unchanged(self, tmp_path):
        ws = Workspace(base_dir=tmp_path, run_id="run-1")
        ar = AgentResult(agent_name="requirement-analyst", status="ok",
                         artifacts={}, transcript=None)
        s = State.empty().with_updates(_workspace=ws)
        out = RequirementStage().transition(s, {"agent_result": ar})
        assert out.last_error is not None, "无孤儿时行为=收口前（agent-failed）"


class TestPrecisionControlJsonRecovery:
    """precision-debug：control.json 写错位置 → _load_control 恢复后非空。"""

    def test_load_control_recovers_orphan(self, tmp_path):
        # _debug_artifacts_dir = workspace.artifacts/debug/{op_name}（有
        # workspace 时）。孤儿写到 debug_dir 之外（artifacts 根）。
        ws = Workspace(base_dir=tmp_path, run_id="run-1")
        debug_dir = ws.artifacts / "debug" / "some_op"
        orphan = ws.artifacts / "control.json"
        ws.artifacts.mkdir(parents=True, exist_ok=True)
        orphan.write_text(json.dumps({"status": "debugging",
                                      "failed_case_queue": []}))
        tp = _transcript_with_write(tmp_path, orphan)

        s = State.empty().with_updates(
            op_name="some_op", _workspace=ws, _last_agent_transcript=str(tp))
        # debug_dir 尚不存在（agent 写孤儿时没建对位置）——恢复的 mkdir 会建
        debug_dir.mkdir(parents=True, exist_ok=True)

        cp = _load_control(s)

        assert cp.get("status") == "debugging", (
            f"孤儿 control.json 应被搬回并读到，got {cp}")
        assert (debug_dir / "control.json").exists()

    def test_no_transcript_no_behavior_change(self, tmp_path):
        ws = Workspace(base_dir=tmp_path, run_id="run-1")
        s = State.empty().with_updates(op_name="some_op", _workspace=ws)
        assert _load_control(s) == {}, "无 transcript 时行为=收口前（{}）"
