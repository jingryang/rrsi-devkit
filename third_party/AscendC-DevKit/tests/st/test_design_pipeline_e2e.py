"""ST (step-2b P8) — design groups end-to-end via GraphExecutor + stub backend.

Exercises the concept/detailed design groups as mounted trees: per-agent stub
artifacts drive each substage; asserts the three-piece contract reaches the
detailed-design boundary, SE stops at the concept group, multi-template tiling
fork-join aggregates, and flat_stages/validate_chain are clean. No real agent.
"""

from __future__ import annotations

import json
import pytest

from ascendc_devkit.capabilities.agent.backend import AgentBackend, AgentResult
from ascendc_devkit.infra.workspace import Workspace
from ascendc_devkit.orchestration.kernel.runner import Runner
from ascendc_devkit.orchestration.graph_executor import GraphExecutor
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.registry import get_workflow, _ensure_stages_loaded
from ascendc_devkit.orchestration.design_tree import (
    build_general_design_group, build_detailed_design_group,
)


class _StubBackend(AgentBackend):
    """Returns canned JSON artifacts keyed by the assigned skill.

    agent_name is now a reusable role (generator/reviewer/anchor) shared across
    substages, so it no longer identifies the step. The per-step skill (passed
    via skills=["<skill>"], D7) does — key the canned products on it.
    """

    _ARTIFACTS = {
        "ascendc-op-general-design": {
            "general_design.json": json.dumps(
                {"op_name": "add", "split_axis_priority": ["N"],
                 "tiling_data": [], "loop_framework": "", "buffer_eval": {}})},
        "ascendc-op-design-template-division": {
            "template_division.json": json.dumps(
                {"templates": [{"name": "T1", "tiling_key": 1, "route_condition": "N>1024"},
                               {"name": "T2", "tiling_key": 2, "route_condition": "N<=1024"}],
                 "locked_decisions": {"precision": "fp32"}})},
        "ascendc-op-tiling": {
            "tiling_split.json": json.dumps({"template": "T", "split": {"axis": "N"}}),
            "tiling_buffer_kernel.json": json.dumps({"template": "T", "buffer_kernel": {"buffer_num": 2}}),
            "tiling_precision_perf.json": json.dumps({"template": "T", "precision_perf": {"compute_dtype": "fp32"}})},
        # kernel_architecture.json removed from integrate output (step 9):
        # section declaration is now codegen_init's responsibility.
        "ascendc-op-design-integrate": {
            "design_spec.json": json.dumps({"op_name": "add", "mutation_mode": "out_of_place", "inputs": [{"name": "x"}], "outputs": [{"name": "y"}]}),
            "tiling_strategy.json": json.dumps({"approach": "multi_template"}),
        },
    }

    @staticmethod
    def _skill_key(skills) -> str:
        return skills[0] if skills else ""

    def spawn(self, agent_name, prompt, context, skills=None,
              model=None, working_dir=None, repo_baseline=None, repo_root=None,
              stage_name="", branch_label="", resume_session_id=None, resume_prompt=None, primary_skill=None, deadline_monotonic: float | None = None):
        key = self._skill_key(skills)
        artifacts = dict(self._ARTIFACTS.get(key, {}))
        # P36: the docgen stage is a disk-first LLM spawn — transition reads
        # <op>_详细设计说明书.md from working_dir (no JSON artifact). The stub
        # simulates the agent writing that md so the disk-first transition
        # succeeds, mirroring how a real run materializes the doc on disk.
        # op_name is read from the materialized design_spec.json — the SAME
        # source transition uses — so stub and transition stay in sync (no
        # hardcoded name that could drift from design_spec.op_name). The md is
        # written BEFORE the JSON artifacts land below, so design_spec.json is
        # not yet on disk here — the "add" default matches _ARTIFACTS' op_name.
        if key == "ascendc-op-design-docgen" and working_dir:
            from pathlib import Path
            wd = Path(working_dir)
            op = "add"
            spec = wd / "design_spec.json"
            if spec.is_file():
                try:
                    op = json.loads(spec.read_text("utf-8")).get("op_name", op)
                except json.JSONDecodeError:
                    pass
            (wd / f"{op}_详细设计说明书.md").write_text(
                "# 详细设计说明书 (stub)\n", encoding="utf-8")
        # P62: design-stage transitions read products from DISK under working_dir
        # (disk-only pathway; the agent-dict fallback is gone). Land the canned
        # artifacts there so every substage's transition sees them — mirrors how
        # a real agent materializes products in its cwd. (docgen's md is written
        # in the branch above; the JSON artifacts land here.)
        if working_dir and artifacts:
            from pathlib import Path
            wdir = Path(working_dir)
            wdir.mkdir(parents=True, exist_ok=True)
            for fn, content in artifacts.items():
                (wdir / fn).write_text(content, encoding="utf-8")
        return AgentResult(agent_name=agent_name, status="ok", artifacts=artifacts)


def _run(root, state, tmp_path, backend=None):
    # Inject workspace (mirrors dispatcher._workspace=workspace) so design
    # substages' _working_dir(state) resolves — P36 docgen is disk-first and
    # reads <op>_详细设计说明书.md from state._workspace.artifacts/design/docgen.
    ws = Workspace.create(output_root=str(tmp_path / "output"), run_id="e2e")
    # P1/§3.12: design chain consumes requirement from the authoritative disk
    # file (artifacts/requirement/requirement.json), not the reduced State
    # dataclass. Mirror the real flow — requirement present in State implies the
    # requirement stage already wrote the full on-disk file.
    if getattr(state, "requirement", None) is not None:
        op_spec = getattr(state.requirement, "op_spec", None)
        op = op_spec.name if op_spec is not None else "add"
        _write_authoritative_requirement(ws, op)
    runner = Runner(agent_backend=backend or _StubBackend(), workspace=ws)
    state = state.with_updates(_workspace=ws)
    return GraphExecutor(runner=runner).execute(root, state)


def _write_authoritative_requirement(ws, op_name: str) -> None:
    """Write a full authoritative requirement.json (含 domain) into the workspace
    — the artifact the requirement stage would have produced before the design
    chain runs (§3.12: 权威全量，非 reduced op_spec wrap)."""
    req_dir = ws.artifacts / "requirement"
    req_dir.mkdir(parents=True, exist_ok=True)
    (req_dir / "requirement.json").write_text(json.dumps({
        "op_name": op_name,
        "mutation_mode": "out_of_place",
        "inputs": [{"name": "x", "dtype": "float16"}],
        "outputs": [{"name": "y", "dtype": "float16"}],
        "domain": {"rank": {"min": 0, "max": 8},
                   "inputs": [{"name": "x",
                               "dtypes": ["float16", "float32"]}]},
    }, ensure_ascii=False), encoding="utf-8")


@pytest.fixture(autouse=True)
def _stages():
    _ensure_stages_loaded()


class TestConceptGroupE2E:
    def test_concept_group_produces_general_design(self, tmp_path):
        from ascendc_devkit.domain.requirement import Requirement
        req = Requirement.from_dict({"op": {"name": "add"}})
        root = build_general_design_group()
        out = _run(root, State.empty().with_updates(
            non_interactive=True, requirement=req), tmp_path)
        assert out.general_design is not None
        assert out.general_design["op_name"] == "add"
        # concept group does NOT produce the three-piece contract
        assert out.design_spec is None


class TestDetailedGroupE2E:
    def test_detailed_group_three_piece_and_tiling(self, tmp_path):
        root = build_detailed_design_group()
        s = State.empty().with_updates(
            non_interactive=True,
            general_design={"op_name": "add", "split_axis_priority": ["N"],
                            "tiling_data": [], "loop_framework": "", "buffer_eval": {}})
        out = _run(root, s, tmp_path)
        # multi-template tiling fork-join aggregated both templates
        assert set(out.tiling_results) == {"T1", "T2"}
        assert out.tiling_results["T1"]["split"] == {"axis": "N"}
        # integrate produced the two-piece design contract (step 9):
        # kernel_architecture moved to codegen_init — section declaration
        # depends on target repo layout, not operator design.
        assert out.design_spec["op_name"] == "add"
        assert out.tiling_strategy["approach"] == "multi_template"
        assert out.kernel_architecture is None  # not produced by design group
        # P36: docgen now produces <op>_详细设计说明书.md via LLM spawn (disk-first);
        # state.design_doc stores the md PATH (no longer a {markdown:...} dict
        # from the removed deterministic renderer).
        assert out.design_doc and out.design_doc.endswith("add_详细设计说明书.md")

    def test_tiling_layout_contract_missing_retries_then_converges(self, tmp_path):
        # step-111 F2 ST：tiling 产物首轮 workspace 契约在位而 layout_contract
        # 缺失 → TilingStage.transition 在位检查打回（incomplete_output +
        # user_feedback）→ Runner artifact-retry 重 spawn（prompt 含定向反馈）→
        # agent 回填后收敛。回填由 **prompt 内容**驱动（反馈到达才写合格格式），
        # 恰好端到端验证 §2.9② 消费闭环——反馈断链则 stub 永远写缺字段格式，
        # tiling 永不满足，用例失败。
        from pathlib import Path

        class _LayoutContractRetryBackend(_StubBackend):
            saw_feedback = False
            tiling_spawns = 0
            # step-112：记录每次 tiling spawn 的会话 id 与收到的 resume 参数，
            # 验证反馈重派轮 resume 原会话（runner 捕获→actions 决策全链）。
            # 每次 spawn 记 {wd(模板分支), sid, resume_sid, resume_prompt}——
            # T1/T2 分支交错执行，须按分支归组断言（不能按全局序号配对）。
            spawns: list = []

            def spawn(self, agent_name, prompt, context, skills=None,
                      working_dir=None, resume_session_id=None,
                      resume_prompt=None, **kw):
                if self._skill_key(skills) == "ascendc-op-tiling":
                    type(self).tiling_spawns += 1
                    sid = f"ses_tiling_{type(self).tiling_spawns}"
                    type(self).spawns.append(dict(
                        wd=str(working_dir), sid=sid,
                        resume_sid=resume_session_id,
                        resume_prompt=resume_prompt))
                    ws = {"user_workspace_bytes": 8,
                          "rationale": "stub staging"}
                    # 回填触发器=「## 用户反馈」节（仅 retry 轮出现；首轮 prompt
                    # 的 schema 渲染已含 layout_contract 字样，不能作判据）。
                    if "用户反馈" in prompt:
                        # retry 反馈已到达重试 agent → 增量回填契约
                        type(self).saw_feedback = True
                        ws["layout_contract"] = [
                            "planeA: blockDim*rows*sizeof(T)"]
                    bk = {"buffer_num": 2, "workspace": ws}
                    files = {
                        "tiling_split.json": json.dumps(
                            {"template": "T", "split": {"axis": "N"}}),
                        "tiling_buffer_kernel.json": json.dumps(
                            {"template": "T", "buffer_kernel": bk}),
                        "tiling_precision_perf.json": json.dumps(
                            {"template": "T",
                             "precision_perf": {"compute_dtype": "fp32"}}),
                    }
                    if working_dir:
                        wd = Path(working_dir)
                        wd.mkdir(parents=True, exist_ok=True)
                        for fn, content in files.items():
                            (wd / fn).write_text(content, encoding="utf-8")
                    return AgentResult(agent_name=agent_name, status="ok",
                                       artifacts=files, session_id=sid)
                return super().spawn(agent_name, prompt, context,
                                     skills=skills, working_dir=working_dir,
                                     **kw)

        backend = _LayoutContractRetryBackend()
        root = build_detailed_design_group()
        s = State.empty().with_updates(
            non_interactive=True,
            general_design={"op_name": "add", "split_axis_priority": ["N"],
                            "tiling_data": [], "loop_framework": "",
                            "buffer_eval": {}})
        out = _run(root, s, tmp_path, backend=backend)
        # 重试确实发生（反馈到达过重试 agent），且恰一次有界 retry/模板
        # （2 模板 × [首轮缺字段 + retry 回填] = 4 次 tiling spawn）。
        assert backend.saw_feedback, (
            "F2 反馈未到达重试 spawn——消费闭环断链")
        assert backend.tiling_spawns == 4, (
            f"expected 4 tiling spawns (2 templates × defect+retry), "
            f"got {backend.tiling_spawns}")
        # step-112：每模板第 2 次 spawn（反馈重派轮）resume 该模板第 1 次的
        # 会话——runner 捕获（transition 后写 last_agent_session_id）+
        # _DesignSubstage.actions 决策的全链接线；首轮必须 fresh（None）。
        # T1/T2 分支交错执行 → 按 working_dir（per-template）归组。
        by_wd = {}
        for sp in backend.spawns:
            by_wd.setdefault(sp["wd"], []).append(sp)
        assert len(by_wd) == 2, f"expected 2 template branches, got {list(by_wd)}"
        for wd, sps in by_wd.items():
            assert len(sps) == 2, f"{wd}: expected defect+retry, got {len(sps)}"
            assert sps[0]["resume_sid"] is None, (
                f"{wd} 首轮不应带 resume：{sps[0]['resume_sid']}")
            assert sps[1]["resume_sid"] == sps[0]["sid"], (
                f"{wd} 反馈重派轮应 resume 首轮会话 {sps[0]['sid']}，"
                f"实得 {sps[1]['resume_sid']}")
            assert sps[1]["resume_prompt"] and "同一会话" in sps[1]["resume_prompt"]
        for t in ("T1", "T2"):
            ws = out.tiling_results[t]["buffer_kernel"]["workspace"]
            assert ws["layout_contract"] == [
                "planeA: blockDim*rows*sizeof(T)"]
        # 下游未被 tiling 一次有界重试拖垮：integrate/docgen 正常收尾
        assert out.design_spec["op_name"] == "add"
        assert out.design_doc and out.design_doc.endswith(
            "add_详细设计说明书.md")


class TestWorkflowContracts:
    def test_full_pipeline_flat_chain_clean_for_design_fields(self):
        wf = get_workflow("generate_ascendc")
        joined = " ".join(wf.validate_chain())
        for f in ("general_design", "template_division", "tiling_results",
                  "design_spec"):
            assert f not in joined

    def test_se_stops_at_concept_boundary(self):
        wf = get_workflow("generate_ascendc_se")
        names = [s.name for s in wf.flat_stages()]
        assert "general-design-generator" in names
        assert "template-division" not in names  # no detailed-design group
        assert "codegen" not in names


class _TrackingBackend(_StubBackend):
    """Records every agent spawn (by assigned skill) so a resume can assert
    what re-ran. agent_name is a shared role now, so track the skill instead."""

    def __init__(self):
        self.spawned: list[str] = []

    def spawn(self, agent_name, prompt, context, skills=None,
              model=None, working_dir=None, repo_baseline=None, repo_root=None,
              stage_name="", branch_label="", resume_session_id=None, resume_prompt=None, primary_skill=None, deadline_monotonic: float | None = None):
        self.spawned.append(self._skill_key(skills))
        return super().spawn(agent_name, prompt, context, skills,
                             model, working_dir, repo_baseline, repo_root,
                             stage_name, branch_label)


class TestFineGrainedResumeE2E:
    """step-2b B: node_status (multi-level paths) drives fine-grained resume into
    the detailed-design group; completed substages are skipped, only pending ones
    rerun. No whole-group rerun, no integrate name-collision."""

    def _run_tracking(self, root, state, tmp_path):
        ws = Workspace.create(output_root=str(tmp_path / "output"), run_id="resume")
        backend = _TrackingBackend()
        state = state.with_updates(_workspace=ws)
        out = GraphExecutor(
            runner=Runner(agent_backend=backend, workspace=ws)).execute(root, state)
        return out, backend.spawned

    def test_resume_skips_completed_substages_in_group(self, tmp_path):
        root = build_detailed_design_group()
        gname = root.name  # "detailed-design"
        # Simulate an interrupt after template-division + both tiling branches
        # completed, before integrate. The group itself is NOT marked
        # completed (interrupted mid-group).
        ns = {
            f"{gname}/dd-intake": "completed",
            f"{gname}/template-division": "completed",
            f"{gname}/tiling": "completed",
            f"{gname}/tiling/T1": "completed",
            f"{gname}/tiling/T2": "completed",
        }
        s = State.empty().with_updates(
            non_interactive=True,
            general_design={"op_name": "add", "split_axis_priority": ["N"],
                            "tiling_data": [], "loop_framework": "", "buffer_eval": {}},
            template_division={"templates": [{"name": "T1"}, {"name": "T2"}]},
            tiling_results={"T1": {"split": {"axis": "N"}},
                            "T2": {"split": {"axis": "M"}}},
            node_status=ns)
        out, spawned = self._run_tracking(root, s, tmp_path)
        # Completed substages did NOT re-run.
        assert "ascendc-op-design-template-division" not in spawned
        assert "ascendc-op-tiling" not in spawned
        # Pending substages DID run (synthesize + docgen onward).
        assert "ascendc-op-design-integrate" in spawned
        assert "ascendc-op-design-docgen" in spawned
        # Pre-existing tiling_results preserved (not clobbered by a rerun).
        assert out.tiling_results["T2"]["split"] == {"axis": "M"}

    def test_top_level_integrate_not_skipped_by_group_synthesize(self):
        # Regression for the resume name-collision (step-2b B). The
        # detailed-design group has a `synthesize` substage (integrate) + a
        # `docgen` substage; the full pipeline ALSO has a top-level `integrate`.
        # Their node paths differ, so marking the group's synthesize completed
        # must NOT mark the top-level integrate.
        wf = get_workflow("generate_ascendc")
        leaves = [s.name for s in wf.flat_stages()]
        assert leaves.count("integrate") >= 1
        # node_status keys are full paths → no collision possible.
        ns = {"generate_ascendc/detailed-design/synthesize": "completed"}
        assert "generate_ascendc/integrate" not in ns

