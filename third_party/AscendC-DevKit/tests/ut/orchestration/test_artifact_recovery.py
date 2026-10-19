"""20260821 — F3 全局收口：孤儿产物就地搬回的可观测性与生命周期。

覆盖：
- artifact_relocated 事件落 events.jsonl（用户核心要求：搬回必须在日志上有呈现）。
- workspace 不可达时的事件降级（WARN 有、事件无、不炸主流程）。
- from_snapshot 对含 retired pending_relocation key 的旧快照 strip（§1.4）。
- recover_orphan_artifact 的 outcome 语义（moved / idempotent_skip / refused /
  orphan_gone）。
"""

import json
from pathlib import Path

from ascendc_devkit.capabilities.agent.backend import AgentResult
from ascendc_devkit.infra.workspace import Workspace
from ascendc_devkit.orchestration.artifact_recovery import recover_orphan_artifact
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.stages.design_substages import GeneralDesignStage


def _transcript_with_write(tmp_path, target) -> Path:
    tp = tmp_path / "t.jsonl"
    tp.write_text(json.dumps({"blocks": [{
        "kind": "tool_use", "tool_name": "write",
        "tool_input": {"input": {"filePath": str(target)}},
    }]}) + "\n", encoding="utf-8")
    return tp


def _batch_layout(tmp_path):
    """Real batch layout: workspace run_dir + wd + orphan under a
    missing-prefix run_dir of the SAME batch dir."""
    batch = tmp_path / "batch-root"
    run_dir = batch / "20260820-103324-164bbc"
    wd = run_dir / "artifacts" / "design" / "general-design-generator"
    wd.mkdir(parents=True)
    orphan_dir = batch / "20260820-164bbc" / "artifacts" / "design" / "general-design-generator"
    orphan_dir.mkdir(parents=True)
    return batch, run_dir, wd, orphan_dir


class TestRelocatedEvent:
    """搬回的日志呈现：run.log WARN + events.jsonl artifact_relocated 事件。"""

    def test_recovery_emits_artifact_relocated_event(self, tmp_path):
        batch, run_dir, wd, orphan_dir = _batch_layout(tmp_path)
        orphan = orphan_dir / "general_design.json"
        orphan.write_text('{"op_name": "rms_norm"}')
        # workspace 锚在 run_dir 级（events.jsonl 写到 run_dir/events.jsonl——与
        # 生产一致：Workspace(base_dir, run_id).events_path）
        ws = Workspace(base_dir=batch, run_id="20260820-103324-164bbc")
        s = State.empty().with_updates(_workspace=ws)
        tp = _transcript_with_write(tmp_path, orphan)

        ok = recover_orphan_artifact(
            tp, "general_design.json", wd, s, "general-design-generator")

        assert ok is True
        events = [json.loads(l) for l in
                  (run_dir / "events.jsonl").read_text().splitlines() if l.strip()]
        hits = [e for e in events if e.get("type") == "artifact_relocated"]
        assert hits, f"events.jsonl 应含 artifact_relocated 事件，got {events}"
        ev = hits[-1]
        assert ev["stage"] == "general-design-generator"
        assert ev["filename"] == "general_design.json"
        assert ev["outcome"] == "moved"
        assert ev["from_path"] == str(orphan)
        assert ev["to_path"] == str(wd / "general_design.json")
        assert (wd / "general_design.json").exists()

    def test_refusal_emits_event_with_outcome(self, tmp_path):
        """拒搬（target 冲突）同样落事件，outcome 区分——审计不需要开 run.log。"""
        batch, run_dir, wd, orphan_dir = _batch_layout(tmp_path)
        orphan = orphan_dir / "general_design.json"
        orphan.write_text('{"op_name": "rms_norm"}')
        (wd / "general_design.json").write_text('{"op_name": "OTHER"}')
        ws = Workspace(base_dir=batch, run_id="20260820-103324-164bbc")
        s = State.empty().with_updates(_workspace=ws)
        tp = _transcript_with_write(tmp_path, orphan)

        ok = recover_orphan_artifact(
            tp, "general_design.json", wd, s, "general-design-generator")

        assert ok is False
        events = [json.loads(l) for l in
                  (run_dir / "events.jsonl").read_text().splitlines() if l.strip()]
        hits = [e for e in events if e.get("type") == "artifact_relocated"]
        assert hits and hits[-1]["outcome"] == "refused_target_exists"

    def test_no_workspace_degrades_to_warn_only(self, tmp_path):
        """workspace 不可达（State.empty/UT）→ 不炸，事件无（WARN 即信号）。"""
        batch, run_dir, wd, orphan_dir = _batch_layout(tmp_path)
        orphan = orphan_dir / "general_design.json"
        orphan.write_text('{"op_name": "x"}')
        tp = _transcript_with_write(tmp_path, orphan)

        ok = recover_orphan_artifact(
            tp, "general_design.json", wd, State.empty(),
            "general-design-generator")

        assert ok is True, "无 workspace 不影响搬回本身"
        assert not (run_dir / "events.jsonl").exists(), "无 workspace 无事件"


class TestRecoverOrphanOutcomes:
    """recover_orphan_artifact 四种 outcome 的返回值语义。"""

    def test_orphan_gone_returns_false(self, tmp_path):
        batch, run_dir, wd, orphan_dir = _batch_layout(tmp_path)
        orphan = orphan_dir / "general_design.json"  # 不写文件
        tp = _transcript_with_write(tmp_path, orphan)
        assert recover_orphan_artifact(
            tp, "general_design.json", wd, State.empty(), "s") is False

    def test_no_evidence_returns_false(self, tmp_path):
        batch, run_dir, wd, orphan_dir = _batch_layout(tmp_path)
        tp = tmp_path / "empty-transcript.jsonl"
        tp.write_text("", encoding="utf-8")
        assert recover_orphan_artifact(
            tp, "general_design.json", wd, State.empty(), "s") is False

    def test_idempotent_samefile_returns_true(self, tmp_path):
        import os
        batch, run_dir, wd, orphan_dir = _batch_layout(tmp_path)
        orphan = orphan_dir / "general_design.json"
        orphan.write_text('{"op_name": "x"}')
        os.link(str(orphan), str(wd / "general_design.json"))
        tp = _transcript_with_write(tmp_path, orphan)
        assert recover_orphan_artifact(
            tp, "general_design.json", wd, State.empty(), "s") is True

    def test_wd_none_returns_false(self, tmp_path):
        tp = _transcript_with_write(tmp_path, tmp_path / "x.json")
        assert recover_orphan_artifact(tp, "x.json", None, State.empty(), "s") is False


class TestSameRoundRecoveryWithEvent:
    """端到端：_read_disk_artifacts 同轮自愈 + 事件落盘（真实 workspace 布局）。"""

    def test_read_disk_artifacts_recovers_and_emits(self, tmp_path):
        batch, run_dir, wd, orphan_dir = _batch_layout(tmp_path)
        orphan = orphan_dir / "general_design.json"
        orphan.write_text('{"op_name": "rms_norm", "split_axis_priority": ["N"], '
                          '"sections": {}}')
        ws = Workspace(base_dir=batch, run_id="20260820-103324-164bbc")
        s = State.empty().with_updates(_workspace=ws)
        tp = _transcript_with_write(tmp_path, orphan)
        ar = AgentResult(agent_name="x", status="ok", artifacts={}, transcript=tp)

        raw, err = GeneralDesignStage()._read_disk_artifacts(
            s, {"_working_dir": str(wd), "agent_result": ar},
            ["general_design.json"])

        assert err is None, f"同轮自愈应成功，got {err}"
        assert raw is not None and "general_design.json" in raw
        events = [json.loads(l) for l in
                  (run_dir / "events.jsonl").read_text().splitlines() if l.strip()]
        assert any(e.get("type") == "artifact_relocated"
                   and e.get("outcome") == "moved" for e in events)


class TestSnapshotStripsRetiredKey:
    """from_snapshot 对旧快照的 retired pending_relocation strip（§1.4：加载期
    drop，防 e9ed199e 同款 resume 崩）。"""

    def test_from_snapshot_strips_pending_relocation(self, tmp_path):
        snap = {"mode": "new", "pending_relocation": {
            "stage_name": "s", "filename": "f.json", "wd": "/w",
            "actual_path": "/w/../f.json"}}
        st = State.from_snapshot(snap)
        assert st.mode == "new"
        assert not hasattr(st, "pending_relocation")

    def test_from_snapshot_clean_dict_unchanged(self):
        st = State.from_snapshot({"mode": "incremental"})
        assert st.mode == "incremental"
