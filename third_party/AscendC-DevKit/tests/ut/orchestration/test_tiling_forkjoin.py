"""P5 (step-2b) — tiling fork-join per-template branches (§六).

Drives TilingStage actions/transition + design_tree.tiling_branch_factory:
per-template branch with a single merged TilingStage (split→vf-design(A5)→
buffer-kernel→precision-perf in one session), join aggregation via P2 dict merge.
Strict TDD. mocks AgentResult.
"""

import json

import pytest
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.kernel.action import SpawnAgent
from ascendc_devkit.capabilities.agent.backend import AgentResult
from ascendc_devkit.orchestration.node import AtomicStage, SequentialGroup
from ascendc_devkit.orchestration.node_forkjoin import merge_forkjoin, StateConflictError
from ascendc_devkit.orchestration.design_tree import tiling_branch_factory
from ascendc_devkit.orchestration.stages.design_substages import TilingStage


def _ar(artifacts):
    return AgentResult(agent_name="x", status="ok", artifacts=artifacts)


def _res(wd, files):
    """P62: land ``{filename: content}`` to wd on disk and return the transition
    result. Design-stage transitions read products from disk under working_dir
    only (the agent-dict fallback is gone); ``agent_result`` is intentionally
    empty — disk is the sole source."""
    for fn, content in files.items():
        (wd / fn).write_text(content, encoding="utf-8")
    return {"_working_dir": str(wd), "agent_result": _ar({})}


class TestBranchFactory:
    def test_two_templates_one_tiling_stage(self):
        state = State.empty().with_updates(template_division={
            "templates": [{"name": "T1"}, {"name": "T2"}]})
        branches = tiling_branch_factory(state)
        assert len(branches) == 2
        assert sorted(b.name for b in branches) == ["T1", "T2"]
        for b in branches:
            assert isinstance(b, SequentialGroup)
            assert [c.name for c in b.children()] == ["tiling"]

    def test_stage_bound_to_template(self):
        state = State.empty().with_updates(template_division={
            "templates": [{"name": "T1", "tiling_key": 1}]})
        branch = tiling_branch_factory(state)[0]
        for atomic in branch.children():
            assert atomic.stage.template == {"name": "T1", "tiling_key": 1}


class TestTilingStageTransitions:
    def test_single_transition_writes_three_segments(self, tmp_path):
        wd = tmp_path / "wd"
        wd.mkdir()
        s = State.empty()
        stage = TilingStage(template={"name": "T1"})
        out = stage.transition(s, _res(wd, {
            "tiling_split.json": '{"template": "T1", "split": {"axis": "N"}}',
            "tiling_buffer_kernel.json":
                '{"template": "T1", "buffer_kernel": {"buffer_num": 2}}',
            "tiling_precision_perf.json":
                '{"template": "T1", "precision_perf": {"compute_dtype": "fp32"}}',
        }))
        assert out.tiling_results == {"T1": {
            "split": {"axis": "N"},
            "buffer_kernel": {"buffer_num": 2},
            "precision_perf": {"compute_dtype": "fp32"}}}

    def test_vf_design_optional_written_when_present(self, tmp_path):
        # A5: the facade skill emits tiling_vf_design.json → vf_design slice lands.
        wd = tmp_path / "wd"
        wd.mkdir()
        s = State.empty().with_updates(design_target_chip="A5")
        out = TilingStage(template={"name": "T1"}).transition(s, _res(wd, {
            "tiling_split.json": '{"template": "T1", "split": {"axis": "N"}}',
            "tiling_vf_design.json":
                '{"template": "T1", "vf_design": {"vf_count": 2, "pattern": 3}}',
            "tiling_buffer_kernel.json":
                '{"template": "T1", "buffer_kernel": {"buffer_num": 2}}',
            "tiling_precision_perf.json":
                '{"template": "T1", "precision_perf": {"compute_dtype": "fp32"}}',
        }))
        assert out.tiling_results["T1"]["vf_design"] == {"vf_count": 2, "pattern": 3}

    def test_vf_design_optional_missing_passes_through(self, tmp_path):
        # A3: no tiling_vf_design.json on disk → transition still succeeds and
        # writes no vf_design slice (the A5-only skip lives in the facade skill).
        wd = tmp_path / "wd"
        wd.mkdir()
        s = State.empty().with_updates(design_target_chip="A3")
        out = TilingStage(template={"name": "T1"}).transition(s, _res(wd, {
            "tiling_split.json": '{"template": "T1", "split": {"axis": "N"}}',
            "tiling_buffer_kernel.json":
                '{"template": "T1", "buffer_kernel": {"buffer_num": 2}}',
            "tiling_precision_perf.json":
                '{"template": "T1", "precision_perf": {"compute_dtype": "fp32"}}',
        }))
        assert out.last_error is None
        assert "vf_design" not in out.tiling_results["T1"]
        assert out.tiling_results["T1"]["split"] == {"axis": "N"}

    def test_missing_artifact_records_error(self):
        s = State.empty()
        out = TilingStage(template={"name": "T1"}).transition(
            s, {"agent_result": _ar({})})
        assert out.last_error is not None
        assert out.tiling_results is None

    def test_stage_emits_only_own_template(self, tmp_path):
        # C1 (branch isolation): the stage must contribute ONLY its own template
        # key, dropping any other templates carried in the base state. This is the
        # prerequisite for safe multi-branch rerun (C3/C4): each branch contributes
        # a disjoint key so merge_forkjoin (C2) shallow-merges into base without a
        # sibling key clash. Carrying base's other templates would make two rerun
        # branches both write {T1,T2} → StateConflictError.
        wd = tmp_path / "wd"
        wd.mkdir()
        base = State.empty().with_updates(tiling_results={"T2": {"split": {"axis": "M"}}})
        out = TilingStage(template={"name": "T1"}).transition(
            base, _res(wd, {
                "tiling_split.json": '{"template": "T1", "split": {"axis": "N"}}',
                "tiling_buffer_kernel.json":
                    '{"template": "T1", "buffer_kernel": {"buffer_num": 2}}',
                "tiling_precision_perf.json":
                    '{"template": "T1", "precision_perf": {"compute_dtype": "fp32"}}',
            }))
        assert out.tiling_results == {"T1": {
            "split": {"axis": "N"},
            "buffer_kernel": {"buffer_num": 2},
            "precision_perf": {"compute_dtype": "fp32"}}}
        assert "T2" not in out.tiling_results


class TestJoinAggregation:
    def _branch_state(self, wd_root, base, name):
        # P62: each branch lands its three segment products to its own working
        # dir on disk (disk-only read pathway).
        wd = wd_root / name
        wd.mkdir(parents=True, exist_ok=True)
        return TilingStage(template={"name": name}).transition(base, _res(wd, {
            "tiling_split.json": '{"template": "%s", "split": {"axis": "N"}}' % name,
            "tiling_buffer_kernel.json":
                '{"template": "%s", "buffer_kernel": {"b": 2}}' % name,
            "tiling_precision_perf.json":
                '{"template": "%s", "precision_perf": {"d": "fp32"}}' % name,
        }))

    def test_join_merges_multiple_templates(self, tmp_path):
        base = State.empty()
        # Each branch starts from base (isolated state copy in real fork-join).
        s1 = self._branch_state(tmp_path, base, "T1")
        s2 = self._branch_state(tmp_path, base, "T2")
        c1 = AtomicStage(TilingStage(template={"name": "T1"}))
        c2 = AtomicStage(TilingStage(template={"name": "T2"}))
        merged = merge_forkjoin(base, [c1, c2], [s1, s2])
        assert set(merged.tiling_results) == {"T1", "T2"}
        assert merged.tiling_results["T1"]["split"] == {"axis": "N"}
        assert merged.tiling_results["T2"]["precision_perf"] == {"d": "fp32"}

    def test_duplicate_template_name_raises(self, tmp_path):
        base = State.empty()
        s1 = self._branch_state(tmp_path, base, "T1")
        s2 = self._branch_state(tmp_path, base, "T1")  # duplicate
        c1 = AtomicStage(TilingStage(template={"name": "T1"}))
        c2 = AtomicStage(TilingStage(template={"name": "T1"}))
        with pytest.raises(StateConflictError):
            merge_forkjoin(base, [c1, c2], [s1, s2])


class TestActions:
    def test_stage_spawns_agent_with_template_in_prompt(self):
        stage = TilingStage(template={"name": "T1", "tiling_key": 1})
        state = State.empty().with_updates(template_division={"templates": [{"name": "T1"}]})
        actions = stage.actions(state, iteration=1)
        spawns = [a for a in actions if isinstance(a, SpawnAgent)]
        assert len(spawns) == 1
        assert spawns[0].agent_name == "ascendc-design-generator"
        assert spawns[0].primary_skill == "ascendc-op-tiling"
        assert spawns[0].skills == [
            "ascendc-op-tiling", "ascendc-op-tiling-split",
            "ascendc-op-tiling-vf-design", "ascendc-op-tiling-buffer-kernel",
            "ascendc-op-tiling-precision-perf",
            "ascendc-simt-operator-design-patterns"]
        assert "T1" in spawns[0].prompt


class TestSegmentClosureRoundTrip:
    """UT-B: 方案 S ([[P100]] / 方案73)——段聚合 :2050 的不变式守护。

    :2050 `tmpl_entry[segment_key]=payload.get(segment_key)` 只搬 segment 内层对象。
    方案 S 让 gate-relevant 设计内容（verifiable_claims / key_parameters /
    kernel_structure）进 segment 内层 → 聚合天然带过（构造性保证）；顶层闭合
    （allowed_top_level_keys）拒孤儿顶层字段。这组测试守护「段内字段 round-trip 不丢」
    与「闭合 enforcement 在 transition 生效」，防 :2050 回归 / 闭合被绕过。
    """

    def test_b1_segment_intra_fields_round_trip_undropped(self, tmp_path):
        # B1: claims/key_parameters 放在 segment 内层 → 经段聚合后 deep-equal，
        # 不丢任何段内字段（P100 回归守护：聚合不得再丢段内 claims）。
        wd = tmp_path / "wd"
        wd.mkdir()
        seg_obj = {
            "axis": "N", "tile": 256, "block_dim": 8,
            "verifiable_claims": [
                {"claim_type": "numeric_derivation", "claim": "ubFactor=8",
                 "verification": "derived", "evidence": {"attempt_log": "..."}}],
            "key_parameters": {"ubFactor": 8, "baseRows": 128}}
        s = State.empty()
        out = TilingStage(template={"name": "T1"}).transition(s, _res(wd, {
            "tiling_split.json": json.dumps({"template": "T1", "split": seg_obj}),
            "tiling_buffer_kernel.json":
                '{"template": "T1", "buffer_kernel": {"buffer_num": 2}}',
            "tiling_precision_perf.json":
                '{"template": "T1", "precision_perf": {"compute_dtype": "fp32"}}',
        }))
        assert out.last_error is None
        # deep-equal: 段内全字段（含 claims/key_params）原样进 tiling_results，无一丢失
        assert out.tiling_results["T1"]["split"] == seg_obj

    def test_b2_top_level_bookkeeping_not_in_segment_slice(self, tmp_path):
        # B2: self_check_summary 是过程元数据（对质原则门不读），留顶层白名单；
        # 聚合只搬 segment 内层 → self_check_summary 不进 tiling_results slice。
        # （它不流向门无害——唯一消费者 feedback-selfcheck 从源文件读，详
        # 73-...-analysis.md §8。这里守护"顶层簿记不误入 segment"。）
        wd = tmp_path / "wd"
        wd.mkdir()
        out = TilingStage(template={"name": "T1"}).transition(State.empty(), _res(wd, {
            "tiling_split.json": json.dumps({
                "template": "T1", "split": {"axis": "N"},
                "self_check_summary": {"passed": 5, "failed": 0}}),
            "tiling_buffer_kernel.json":
                '{"template": "T1", "buffer_kernel": {"buffer_num": 2}}',
            "tiling_precision_perf.json":
                '{"template": "T1", "precision_perf": {"compute_dtype": "fp32"}}',
        }))
        assert out.last_error is None
        slice_obj = out.tiling_results["T1"]["split"]
        assert slice_obj == {"axis": "N"}
        assert "self_check_summary" not in slice_obj

    def test_b3_orphan_top_level_field_rejected_at_transition(self, tmp_path):
        # B3: 闭合 enforcement hook——孤儿顶层字段（gate-relevant 设计内容放顶层）
        # 必在 transition 读产物时被拒为 schema_violation，根本到不了段聚合/下游门。
        # 这是方案 S 路径 (b) 的运行期落地（§1.3 在 producer 边界即拒 → 重 spawn）。
        wd = tmp_path / "wd"
        wd.mkdir()
        out = TilingStage(template={"name": "T1"}).transition(State.empty(), _res(wd, {
            "tiling_split.json": json.dumps({
                "template": "T1", "split": {"axis": "N"},
                "verifiable_claims": [{"claim_type": "x"}]}),  # 放顶层=孤儿
            "tiling_buffer_kernel.json":
                '{"template": "T1", "buffer_kernel": {"buffer_num": 2}}',
            "tiling_precision_perf.json":
                '{"template": "T1", "precision_perf": {"compute_dtype": "fp32"}}',
        }))
        assert out.last_error is not None
        assert out.last_error.error_type == "schema_violation"
        assert "verifiable_claims" in out.last_error.message
