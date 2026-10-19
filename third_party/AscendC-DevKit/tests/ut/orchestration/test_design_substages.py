"""P4 (step-2b) — design substage implementations (§五).

Drives design_substages.py: actions (SpawnAgent), transition (parse → State
field + decision_log), quality-gate resolve_condition (blocking_issues + target),
validate_inputs. Strict TDD — written before impl. mocks AgentResult.
"""

import json

import pytest
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.kernel.action import AskUserQuestion, SpawnAgent
from ascendc_devkit.capabilities.agent.backend import AgentResult
from ascendc_devkit.orchestration.stages.design_substages import (
    GeneralDesignStage, TemplateDivisionStage, SynthesizeStage, DocgenStage,
    _route_scalar_params,
)
from ascendc_devkit.capabilities.agent._shared import (
    _harvest_relocation_evidence, _harvest_relocation_evidence_detailed,
)


def _ar(artifacts, status="ok", agent="x", transcript=None):
    return AgentResult(agent_name=agent, status=status, artifacts=artifacts,
                        transcript=transcript)


@pytest.fixture
def wd(tmp_path):
    """P62: design substages read products from disk under working_dir — the
    agent-dict fallback is gone. Fresh per-test working dir."""
    d = tmp_path / "wd"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _res(wd, files):
    """Land each ``{filename: content}`` (str or JSON-able) into wd and return
    the transition result. ``agent_result`` is intentionally empty — disk is the
    only source now (P62)."""
    for fn, content in files.items():
        if not isinstance(content, str):
            content = json.dumps(content)
        (wd / fn).write_text(content)
    return {"_working_dir": str(wd), "agent_result": _ar({})}


class TestActions:
    @pytest.mark.parametrize("cls,role,skills", [
        (GeneralDesignStage, "ascendc-design-generator",
         ["ascendc-op-general-design", "ascendc-op-design-template-select",
          "ascendc-simt-operator-design-patterns",
          "ascendc-strategy-card-select"]),
        (TemplateDivisionStage, "ascendc-design-generator",
         ["ascendc-op-design-template-division"]),
        (SynthesizeStage, "ascendc-design-generator",
         ["ascendc-op-design-integrate"]),
        (DocgenStage, "ascendc-design-generator",
         ["ascendc-op-design-docgen"]),
    ])
    def test_actions_spawn_agent(self, cls, role, skills):
        actions = cls().actions(State.empty(), iteration=1)
        spawns = [a for a in actions if isinstance(a, SpawnAgent)]
        assert len(spawns) == 1
        # agent_name is now the reusable ROLE (A/B/C), not the skill name.
        assert spawns[0].agent_name == role
        # The per-step methodology is assigned via skills= (D7 central config);
        # a merged facade skill also carries its tail-call closure (P47), so the
        # allowlist is primary + tail-calls (synthesize → integrate + docgen).
        assert spawns[0].skills == skills
        assert spawns[0].prompt  # non-empty


class TestContextInjection:
    """§3.3 — operator identity + assigned skill must reach the prompt/context,
    so the agent never falls back to 'the specific operator wasn't provided'."""

    def test_operator_identity_in_prompt_and_context(self):
        from pathlib import Path
        s = State.empty().with_updates(op_name="rope", op_dir=Path("/ops/rope"))
        actions = GeneralDesignStage().actions(s, iteration=1)
        spawn = next(a for a in actions if isinstance(a, SpawnAgent))
        assert "rope" in spawn.prompt
        assert "/ops/rope" in spawn.prompt
        assert spawn.context["op_name"] == "rope"
        assert spawn.context["op_dir"] == "/ops/rope"

    def test_assigned_skill_named_in_prompt(self):
        s = State.empty().with_updates(op_name="rope")
        spawn = next(a for a in GeneralDesignStage().actions(s, 1)
                     if isinstance(a, SpawnAgent))
        # The prompt must name the skill so the model invokes it (Pattern 2).
        assert "ascendc-op-general-design" in spawn.prompt


class TestSkillSlashTrigger:
    """D2 (2.1) — skill delivery lives at the backend boundary, not the stage.

    Each design substage resolves its methodology skill and carries it on
    SpawnAgent.primary_skill; the backend renders delivery natively (claude =
    leading /<skill> via render_skill_injection; opencode = first-call +
    permission closure). The stage prompt body itself no longer leads with a
    slash — that coupling (was _with_trigger) is gone.
    """

    @pytest.mark.parametrize("cls,skill", [
        (GeneralDesignStage, "ascendc-op-general-design"),
        (TemplateDivisionStage, "ascendc-op-design-template-division"),
        (SynthesizeStage, "ascendc-op-design-integrate"),
        (DocgenStage, "ascendc-op-design-docgen"),
    ])
    def test_spawn_carries_primary_skill(self, cls, skill):
        spawn = next(a for a in cls().actions(State.empty(), 1)
                     if isinstance(a, SpawnAgent))
        assert spawn.primary_skill == skill, (
            "the spawn must carry its methodology skill on primary_skill so the "
            "backend delivers it natively (D2)")
        # delivery is no longer prepended to the prompt body
        assert not spawn.prompt.lstrip().startswith(f"/{skill}")

    def test_tiling_stage_carries_primary_skill(self):
        from ascendc_devkit.orchestration.stages.design_substages import TilingStage
        s = State.empty().with_updates(
            op_name="rope",
            template_division={"templates": [{"name": "T1"}]})
        spawn = next(a for a in TilingStage(template={"name": "T1"}).actions(s, 1)
                     if isinstance(a, SpawnAgent))
        assert spawn.primary_skill == "ascendc-op-tiling"
        assert not spawn.prompt.lstrip().startswith("/ascendc-op-tiling")

    def test_general_design_doc_path_branch_carries_primary_skill(self, tmp_path):
        # The --general-design pass-through branch overrides _build_prompt; it
        # must still carry the primary_skill for backend delivery.
        doc = tmp_path / "gd.md"
        doc.write_text("# concept design", encoding="utf-8")
        s = State.empty().with_updates(op_name="rope", design_doc_path=str(doc))
        spawn = next(a for a in GeneralDesignStage().actions(s, 1)
                     if isinstance(a, SpawnAgent))
        assert spawn.primary_skill == "ascendc-op-general-design"


class TestUpstreamInputMaterialization:
    """Step-10 F2: upstream products are materialized as FILES in the working dir
    (not JSON injected into the prompt). Each consuming substage writes its
    declared _upstream_inputs to the working dir before spawn, so the skill reads
    them from CWD exactly as a TUI user would. This guards the same gap as the old
    TestUpstreamInputInjection (anchor-consistency/integrate context-free bug) but
    asserted against the new file-materialization mechanism."""

    def _state(self):
        return State.empty().with_updates(
            op_name="rope",
            general_design={"parallel_decomp": "S-AXIS-MARK"},
            template_division={"templates": [{"name": "T1"}],
                               "locked": {"BUFFER_NUM": 2}},
            tiling_results={"T1": {"split": {"axis": "SPLIT-MARK"},
                                   "buffer_kernel": {"buf": "BUF-MARK"},
                                   "precision_perf": {}}},
            design_doc={"markdown": "DOC-MARK"})

    def _prompt(self, stage):
        spawn = next(a for a in stage.actions(self._state(), 1)
                     if isinstance(a, SpawnAgent))
        return spawn.prompt

    def _files(self, stage, tmp_path):
        """Return the materialized input files for a stage run under tmp_path."""
        class WS:
            def __init__(self, r): self._root = r
            @property
            def artifacts(self): return self._root
        # Force the _working_dir to a controlled tmp path
        s = stage
        wd = tmp_path
        wd.mkdir(parents=True, exist_ok=True)
        # We can't easily inject a workspace — test via actions() and check the
        # prompt suppression + artifacts
        return wd

    def test_prompt_has_no_upstream_input_section(self):
        # F2: the old '## 上游输入' prompt-injection block must be GONE.
        for stage_factory in (TemplateDivisionStage, SynthesizeStage):
            p = self._prompt(stage_factory())
            assert "## 上游输入" not in p, f"{stage_factory.__name__} still injects upstream inputs"

    def test_tiling_prompt_no_inputs(self):
        from ascendc_devkit.orchestration.stages.design_substages import TilingStage
        p = self._prompt(TilingStage(template={"name": "T1"}))
        assert "## 上游输入" not in p

    def test_integrate_prompt_no_inputs(self):
        assert "## 上游输入" not in self._prompt(SynthesizeStage())

    def test_requirement_summary_still_in_prompt(self):
        # operator_section (lightweight identity) is NOT suppressed — only the
        # heavy upstream product injection (_inputs_section) is. The requirement
        # summary (op_name etc.) stays in the prompt as lightweight context.
        from ascendc_devkit.domain.requirement import Requirement
        from ascendc_devkit.domain.operator import OperatorSpec
        req = Requirement(op_spec=OperatorSpec(name="rope"))
        s = State.empty().with_updates(op_name="rope", requirement=req)
        spawn = next(a for a in GeneralDesignStage().actions(s, 1)
                     if isinstance(a, SpawnAgent))
        assert "需求摘要" in spawn.prompt

    def test_tiling_stage_injects_operator(self):
        from ascendc_devkit.orchestration.stages.design_substages import TilingStage
        s = State.empty().with_updates(
            op_name="rope",
            template_division={"templates": [{"name": "T1"}]})
        stage = TilingStage(template={"name": "T1"})
        spawn = next(a for a in stage.actions(s, 1) if isinstance(a, SpawnAgent))
        assert "rope" in spawn.prompt


class TestAttribution:
    """§P2/D8 — stage_name + branch_label reach the SpawnAgent for log/transcript
    attribution (role agent reused across stages; N parallel tiling branches)."""

    def test_non_tiling_substage_has_stage_name_empty_branch(self):
        spawn = next(a for a in GeneralDesignStage().actions(State.empty(), 1)
                     if isinstance(a, SpawnAgent))
        assert spawn.stage_name == "general-design-generator"
        assert spawn.branch_label == ""

    def test_tiling_stage_branch_label_is_template(self):
        from ascendc_devkit.orchestration.stages.design_substages import TilingStage
        s = State.empty().with_updates(
            template_division={"templates": [{"name": "T3_QuarterFull"}]})
        spawn = next(a for a in TilingStage(
            template={"name": "T3_QuarterFull"}).actions(s, 1)
            if isinstance(a, SpawnAgent))
        assert spawn.stage_name == "tiling"
        assert spawn.branch_label == "T3_QuarterFull"

    def test_parallel_branches_get_distinct_labels(self):
        from ascendc_devkit.orchestration.stages.design_substages import TilingStage
        s = State.empty().with_updates(
            template_division={"templates": [{"name": "T1"}, {"name": "T2"}]})
        a1 = next(a for a in TilingStage(template={"name": "T1"}).actions(s, 1)
                  if isinstance(a, SpawnAgent))
        a2 = next(a for a in TilingStage(template={"name": "T2"}).actions(s, 1)
                  if isinstance(a, SpawnAgent))
        assert a1.branch_label == "T1"
        assert a2.branch_label == "T2"
        assert a1.branch_label != a2.branch_label


class TestTransitions:
    def test_gd_generate_writes_general_design(self, wd):
        s = State.empty()
        out = GeneralDesignStage().transition(
            s, _res(wd, {"general_design.json":
                         '{"op_name": "add", "sections": {}}'}))
        assert out.general_design == {"op_name": "add", "sections": {}}

    def test_template_division_writes_field(self, wd):
        s = State.empty()
        out = TemplateDivisionStage().transition(
            s, _res(wd, {"template_division.json":
                         '{"templates": [{"name": "T1"}], "locked_decisions": {}}'}))
        assert out.template_division["templates"] == [{"name": "T1"}]

    def test_template_division_rejects_duplicate_tiling_key(self, wd):
        """§2.9 上游自检：tiling_key 唯一——重复则 codegen 路由歧义，transition 报错。"""
        s = State.empty()
        out = TemplateDivisionStage().transition(
            s, _res(wd, {"template_division.json":
                         '{"templates": [{"name": "T1", "tiling_key": 1},'
                         ' {"name": "T2", "tiling_key": 1}],'
                         ' "locked_decisions": {}}'}))
        assert out.last_error is not None
        assert "tiling_key 不唯一" in str(out.last_error)

    def test_integrate_writes_two_piece(self, wd):
        """Step 9: kernel_architecture removed from integrate output —
        section declaration is now codegen_init's responsibility."""
        s = State.empty()
        out = SynthesizeStage().transition(s, _res(wd, {
            "design_spec.json": '{"inputs": [], "outputs": []}',
            "tiling_strategy.json": '{"approach": "x"}',
        }))
        assert out.design_spec == {"inputs": [], "outputs": []}
        assert out.tiling_strategy == {"approach": "x"}
        assert out.kernel_architecture is None  # not produced by integrate

    # —— C: integrate deterministic scalar-param routing (inputs → attrs) ——
    def test_integrate_routes_scalar_from_inputs_to_attrs(self, wd):
        """C: LLM 把标量（epsilon, shape:[], SCALAR）误列 inputs → integrate
        确定搬到 attrs。51d915 回归根因。"""
        s = State.empty()
        ds = {"op_name": "rms", "mutation_mode": "out_of_place",
              "inputs": [{"name": "x", "dtype": "fp16", "shape": ["N"]},
                         {"name": "epsilon", "dtype": "fp32", "shape": [],
                          "format": "SCALAR", "default": 1e-06}],
              "outputs": [{"name": "y", "dtype": "fp16", "shape": ["N"]}]}
        out = SynthesizeStage().transition(s, _res(wd, {
            "design_spec.json": ds, "tiling_strategy.json": '{"approach": "x"}'}))
        in_names = [i["name"] for i in out.design_spec["inputs"]]
        attr_names = [a["name"] for a in out.design_spec["attrs"]]
        assert "epsilon" not in in_names
        assert "epsilon" in attr_names
        assert "x" in in_names
        assert [o["name"] for o in out.design_spec["outputs"]] == ["y"]
        eps = next(a for a in out.design_spec["attrs"] if a["name"] == "epsilon")
        assert eps["type"] == "fp32" and eps["default"] == 1e-06

    def test_integrate_elementwise_shape_empty_not_routed(self, wd):
        """§1.10 / Maximum RCA: ``shape:[]`` WITHOUT an explicit scalar declaration
        (role=attr / format=SCALAR) is a broadcasting tensor, NOT a scalar — must
        stay in inputs. The old ``shape==[]`` proxy mis-routed exactly this case
        (emptied inputs/outputs → codegen halt). A true scalar must declare itself."""
        s = State.empty()
        ds = {"op_name": "o", "mutation_mode": "out_of_place",
              "inputs": [{"name": "mode", "shape": [], "default": 0},
                         {"name": "x", "shape": ["N"]}],
              "outputs": []}
        out = SynthesizeStage().transition(s, _res(wd, {
            "design_spec.json": ds, "tiling_strategy.json": '{}'}))
        # mode (shape:[] no explicit scalar decl) stays a tensor in inputs
        assert [i["name"] for i in out.design_spec["inputs"]] == ["mode", "x"]
        assert all(a.get("name") != "mode" for a in out.design_spec.get("attrs", []))

    def test_integrate_attrs_dict_normalized_to_list(self, wd):
        """C: attrs 已有 dict 形态 → 归一为 list，并 append 新标量（不覆盖）。"""
        s = State.empty()
        ds = {"op_name": "o", "mutation_mode": "out_of_place",
              "inputs": [{"name": "epsilon", "shape": [], "format": "SCALAR"}],
              "outputs": [],
              "attrs": {"cache_mode": {"type": "string", "default": "PA_NZ"}}}
        out = SynthesizeStage().transition(s, _res(wd, {
            "design_spec.json": ds, "tiling_strategy.json": '{}'}))
        attrs = out.design_spec["attrs"]
        assert isinstance(attrs, list)
        names = [a["name"] for a in attrs]
        assert "cache_mode" in names and "epsilon" in names

    def test_integrate_tensor_not_routed(self, wd):
        """C 回归：真张量（含 shape:["1"] 标量张量、无 shape 的项）不动，attrs 不
        被凭空创建。"""
        s = State.empty()
        ds = {"op_name": "o", "mutation_mode": "out_of_place",
              "inputs": [{"name": "spec_token", "shape": ["1"]},
                         {"name": "x", "shape": ["N", "M"]}],
              "outputs": []}
        out = SynthesizeStage().transition(s, _res(wd, {
            "design_spec.json": ds, "tiling_strategy.json": '{}'}))
        assert [i["name"] for i in out.design_spec["inputs"]] == ["spec_token", "x"]
        # no scalar moved → attrs key not created
        assert "attrs" not in out.design_spec or out.design_spec["attrs"] == []

    def test_integrate_preserves_other_toplevel_keys(self, wd):
        """C: surgical in-place —— 其他顶层键（platform/data_flow/templates）不丢
        （不做 OperatorSpec 全量 round-trip）。"""
        s = State.empty()
        ds = {"op_name": "o", "mutation_mode": "out_of_place",
              "inputs": [{"name": "epsilon", "shape": [], "format": "SCALAR"},
                         {"name": "x", "shape": ["N"]}],
              "outputs": [],
              "platform": {"chip": "A2"},
              "data_flow": {"pipeline": ["CopyIn", "Compute"]},
              "templates": [{"key": "T1"}]}
        out = SynthesizeStage().transition(s, _res(wd, {
            "design_spec.json": ds, "tiling_strategy.json": '{}'}))
        assert out.design_spec["platform"] == {"chip": "A2"}
        assert out.design_spec["data_flow"] == {"pipeline": ["CopyIn", "Compute"]}
        assert out.design_spec["templates"] == [{"key": "T1"}]

    # —— P121 S2: integrate producer shape-rank 保留性自检（§2.9）——

    def test_integrate_reconciles_drifted_shape_rank(self, wd):
        """S2: design_spec input rank 与 requirement（Golden 派生）不符 → 确定性修正
        到 requirement 权威。advance_step_v2 真根因（input_tokens 猜 2D、实际 1D）。"""
        from ascendc_devkit.domain.requirement import Requirement
        from ascendc_devkit.domain.operator import OperatorSpec, TensorSpec
        req = Requirement(op_spec=OperatorSpec(
            name="advance_step_v2",
            inputs=[TensorSpec(name="input_tokens", dtype="int64", shape=["num_seqs"])],
            outputs=[]))
        s = State.empty().with_updates(requirement=req)
        ds = {"op_name": "advance_step_v2", "mutation_mode": "out_of_place",
              "inputs": [{"name": "input_tokens", "dtype": "int64",
                          "shape": ["num_seqs", "col"]}],  # 2D — mid-chain drift
              "outputs": []}
        out = SynthesizeStage().transition(s, _res(wd, {
            "design_spec.json": ds, "tiling_strategy.json": '{}'}))
        fixed = out.design_spec["inputs"][0]
        assert fixed["name"] == "input_tokens"
        assert len(fixed["shape"]) == 1  # reconciled to requirement's 1D rank

    def test_integrate_preserves_matching_shape_rank(self, wd):
        """S2 回归：design_spec rank 与 requirement 一致 → 不动（无误修正）。"""
        from ascendc_devkit.domain.requirement import Requirement
        from ascendc_devkit.domain.operator import OperatorSpec, TensorSpec
        req = Requirement(op_spec=OperatorSpec(
            name="op",
            inputs=[TensorSpec(name="x", dtype="fp16", shape=["N", "M"])],
            outputs=[]))
        s = State.empty().with_updates(requirement=req)
        ds = {"op_name": "op", "mutation_mode": "out_of_place",
              "inputs": [{"name": "x", "dtype": "fp16", "shape": ["N", "M"]}],
              "outputs": []}
        out = SynthesizeStage().transition(s, _res(wd, {
            "design_spec.json": ds, "tiling_strategy.json": '{}'}))
        assert out.design_spec["inputs"][0]["shape"] == ["N", "M"]  # untouched

    def test_integrate_reconcile_skips_when_no_requirement(self, wd):
        """S2: requirement 缺失（State.empty）→ 不修正（无权威源，不崩）。"""
        s = State.empty()  # no requirement
        ds = {"op_name": "op", "mutation_mode": "out_of_place",
              "inputs": [{"name": "x", "shape": ["N", "M"]}], "outputs": []}
        out = SynthesizeStage().transition(s, _res(wd, {
            "design_spec.json": ds, "tiling_strategy.json": '{}'}))
        assert out.design_spec["inputs"][0]["shape"] == ["N", "M"]  # untouched

    def test_decision_log_captured(self, wd):
        s = State.empty()
        out = GeneralDesignStage().transition(s, _res(wd, {
            "general_design.json": '{"op_name": "a", "sections": {}}',
            "decision_log.json": '{"stage": "general-design-generator", "key_decisions": []}'}))
        assert "general-design-generator" in out.decision_logs

    def test_missing_artifact_records_error(self):
        s = State.empty()
        out = TemplateDivisionStage().transition(s, {"agent_result": _ar({})})
        assert out.last_error is not None
        assert out.template_division is None

    # —— P4: transition reads from working_dir (disk) first ——

    def test_transition_reads_from_disk_via_working_dir(self, tmp_path):
        """P4: transition() → _parse_single reads artifact from working_dir on
        disk (deterministic path), not from agent_result.artifacts scan."""
        wd = tmp_path / "design" / "template-division"
        wd.mkdir(parents=True)
        (wd / "template_division.json").write_text(
            '{"templates": [{"name": "T1"}], "locked_decisions": {}}')

        s = State.empty()
        # Even though agent_result is empty, disk file is read first
        result = {"agent_result": _ar({}),
                  "_working_dir": str(wd)}
        out = TemplateDivisionStage().transition(s, result)
        assert out.template_division is not None
        assert out.template_division["templates"] == [{"name": "T1"}]
        # P5: success clears any prior error
        assert out.last_error is None

    def test_transition_disk_file_wins_over_agent_result(self, tmp_path):
        """P4: when both disk file and agent_result exist, disk wins
        (deterministic path priority)."""
        wd = tmp_path / "design" / "general-design-generator"
        wd.mkdir(parents=True)
        (wd / "general_design.json").write_text(
            '{"op_name": "from_disk", "sections": {}}')

        s = State.empty()
        result = {
            "_working_dir": str(wd),
            "agent_result": _ar({
                "general_design.json": '{"op_name": "from_agent", "sections": {}}'})
        }
        out = GeneralDesignStage().transition(s, result)
        # Disk path wins
        assert out.general_design["op_name"] == "from_disk"

    def test_transition_clears_sticky_last_error_on_success(self, tmp_path):
        """P5: transition success MUST clear a sticky last_error from a prior
        iteration, preventing false 'failed' reporting."""
        from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
        wd = tmp_path / "design" / "template-division"
        wd.mkdir(parents=True)
        (wd / "template_division.json").write_text(
            '{"templates": [{"name": "T1"}], "locked_decisions": {}}')

        s = State.empty().with_updates(
            last_error=ErrorFeedback(
                stage_name="template-division",
                error_type="missing_artifact",
                message="iteration 1 failed"))

        result = {"_working_dir": str(wd)}
        out = TemplateDivisionStage().transition(s, result)
        assert out.template_division is not None
        assert out.last_error is None, (
            "sticky last_error must be cleared on successful parse")

    # —— design-halt-diagnostics P1: custom transition() overrides must also
    # clear a stale same-stage last_error on their success path (they bypass
    # _parse_single, so they don't inherit its P5 clear for free). ——

    def test_integrate_clears_sticky_last_error_on_success(self, wd):
        from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
        s = State.empty().with_updates(
            last_error=ErrorFeedback(
                stage_name="synthesize",
                error_type="missing_artifact",
                message="iteration 1 failed"))
        out = SynthesizeStage().transition(s, _res(wd, {
            "design_spec.json": '{"op_name": "add", "mutation_mode": "out_of_place", "inputs": [], "outputs": []}',
            "tiling_strategy.json": '{"approach": "x"}',
        }))
        assert out.design_spec == {"op_name": "add", "mutation_mode": "out_of_place", "inputs": [], "outputs": []}
        assert out.last_error is None, (
            "sticky last_error must be cleared on successful integrate")

    def test_integrate_keeps_schema_violation_error(self, wd):
        """The schema-error branch must NOT be swept by the P1 fix — a design
        product missing required fields is a real, current-iteration error."""
        s = State.empty()
        out = SynthesizeStage().transition(s, _res(wd, {
            "design_spec.json": '{}',  # missing required inputs/outputs
            "tiling_strategy.json": '{"approach": "x"}',
        }))
        assert out.last_error is not None
        assert out.last_error.error_type == "schema_violation"

    def test_integrate_rejects_design_spec_missing_mutation_mode(self, wd):
        """design_spec 缺 mutation_mode（现 required_key）→ schema_violation.
        守护 in-place/out-of-place 交付契约的 design 层必填：mutation_mode 须由
        integrate 从 requirement 继承进 design_spec（供 codegen 消费）。与 requirement
        层 _validate_mutation_mode_consistency 自洽校验互补——design 层靠 schema
        required_keys 保证继承不丢。背景见 inplace-outplace-delivery-contract/。"""
        s = State.empty()
        out = SynthesizeStage().transition(s, _res(wd, {
            "design_spec.json": json.dumps({
                "op_name": "add",
                "inputs": [{"name": "x"}],
                "outputs": [{"name": "y"}],
                # mutation_mode 缺失 → 违反 required_keys
            }),
            "tiling_strategy.json": '{"approach": "x"}',
        }))
        assert out.last_error is not None
        assert out.last_error.error_type == "schema_violation"
        assert "mutation_mode" in out.last_error.message

class TestIntegrateReconcilesFieldDrift:
    """P123: design_spec IO 字段漂移（param_type / in-place outputs）在 integrate
    producer 自检对齐到权威 requirement.json（§2.9）。op_spec.from_dict 把无 shape 张量
    路由进 attrs → in-memory op_spec 有损；权威是 agent 产出的 requirement.json（保留
    mutation_mode + 完整 IO）。两类漂移见 batch 20260729-141750（multi_add / advance_step_v2）。"""

    def _state_with_ws(self, tmp_path, requirement_json):
        s = State.empty()
        root = tmp_path / "ws"
        (root / "requirement").mkdir(parents=True)
        (root / "requirement" / "requirement.json").write_text(
            json.dumps({"requirement": requirement_json}), encoding="utf-8")
        object.__setattr__(
            s, "_workspace", type("WS", (), {"artifacts": root})())
        return s

    def test_reconciles_dynamic_param_type_drift(self, tmp_path, wd):
        """P3 (multi_add): x1 REQUIRED 但 requirement DYNAMIC → 回写 DYNAMIC。
        DYNAMIC 具结构语义（Tensor[] shape + codegen 签名）；降级使 harness 拒绝正确
        的嵌套 shape。对齐到 requirement 权威（同 P121 shape-rank 范式，不同字段）。"""
        req = {"mutation_mode": "out_of_place",
               "inputs": [{"name": "x1", "param_type": "DYNAMIC", "dtype": ["float16"]},
                          {"name": "x2", "param_type": "REQUIRED", "dtype": ["float16"]}],
               "outputs": [{"name": "y", "param_type": "REQUIRED"}]}
        s = self._state_with_ws(tmp_path, req)
        ds = {"op_name": "multi_add_rms_norm_dynamic_quant",
              "mutation_mode": "out_of_place",
              "inputs": [{"name": "x1", "param_type": "REQUIRED",  # DOWNGRADED drift
                          "shape": [152, 7680]},
                         {"name": "x2", "param_type": "REQUIRED", "shape": [152, 7680]}],
              "outputs": [{"name": "y", "param_type": "REQUIRED"}]}
        out = SynthesizeStage().transition(s, _res(wd, {
            "design_spec.json": ds, "tiling_strategy.json": '{}'}))
        ins = {i["name"]: i for i in out.design_spec["inputs"]}
        assert ins["x1"]["param_type"] == "DYNAMIC"   # restored to requirement authority
        assert ins["x2"]["param_type"] == "REQUIRED"  # unchanged (already matched)

    def test_reconciles_renamed_dynamic_by_position(self, tmp_path, wd):
        """#2: agent RENAMED the DYNAMIC input (x1→x) instead of dropping it →
        name match misses. Same arity → positionally restore DYNAMIC onto the
        renamed item (docgen/cannbench signature stays variadic)."""
        req = {"mutation_mode": "out_of_place",
               "inputs": [{"name": "x1", "param_type": "DYNAMIC", "dtype": ["float16"]},
                          {"name": "x2", "param_type": "REQUIRED", "dtype": ["float16"]}],
               "outputs": [{"name": "y", "param_type": "REQUIRED"}]}
        s = self._state_with_ws(tmp_path, req)
        ds = {"op_name": "multi_add", "mutation_mode": "out_of_place",
              "inputs": [{"name": "x", "param_type": "REQUIRED",  # RENAMED x1→x
                          "shape": [152, 7680]},
                         {"name": "x2", "param_type": "REQUIRED", "shape": [152, 7680]}],
              "outputs": [{"name": "y", "param_type": "REQUIRED"}]}
        out = SynthesizeStage().transition(s, _res(wd, {
            "design_spec.json": ds, "tiling_strategy.json": '{}'}))
        # position 0 restored to DYNAMIC despite the rename
        assert out.design_spec["inputs"][0]["param_type"] == "DYNAMIC"
        assert out.design_spec["inputs"][1]["param_type"] == "REQUIRED"

    def test_renamed_dynamic_arity_mismatch_warns_not_clobbers(self, tmp_path, wd):
        """#2: renamed DYNAMIC but arity differs → can't safely align by position;
        must NOT guess/clobber (only warn). design_spec left as-is."""
        req = {"mutation_mode": "out_of_place",
               "inputs": [{"name": "x1", "param_type": "DYNAMIC", "dtype": ["float16"]},
                          {"name": "x2", "param_type": "REQUIRED", "dtype": ["float16"]}],
               "outputs": [{"name": "y", "param_type": "REQUIRED"}]}
        s = self._state_with_ws(tmp_path, req)
        ds = {"op_name": "multi_add", "mutation_mode": "out_of_place",
              "inputs": [{"name": "x", "param_type": "REQUIRED",  # renamed
                          "shape": [152, 7680]}],  # arity 1 vs requirement 2
              "outputs": [{"name": "y", "param_type": "REQUIRED"}]}
        out = SynthesizeStage().transition(s, _res(wd, {
            "design_spec.json": ds, "tiling_strategy.json": '{}'}))
        # no unsafe positional guess — left REQUIRED (warning emitted, not clobber)
        assert out.design_spec["inputs"][0]["param_type"] == "REQUIRED"

    def test_reconciles_inplace_empty_outputs(self, tmp_path, wd):
        """P2 (advance_step_v2/scatter_pa_kv_cache): in-place alias outputs 被 agent
        清空进非契约字段 → 从 requirement 回填，并用同名 input 的 shape/dtype 补全
        （alias output 即该 input，shape 同源）。codegen.validate_inputs 要求 outputs 非空。"""
        req = {"mutation_mode": "in_place",
               "inputs": [{"name": "input_tokens", "param_type": "REQUIRED",
                           "dtype": ["int64"], "shape": ["num_seqs"]},
                          {"name": "other", "param_type": "REQUIRED", "shape": ["k"]}],
               "outputs": [{"name": "input_tokens", "param_type": "REQUIRED",
                            "shape_formula": "same as input"}]}  # alias, no shape list
        s = self._state_with_ws(tmp_path, req)
        ds = {"op_name": "advance_step_v2", "mutation_mode": "in_place",
              "inputs": [{"name": "input_tokens", "param_type": "REQUIRED",
                          "dtype": ["int64"], "shape": ["num_seqs"]},
                         {"name": "other", "param_type": "REQUIRED", "shape": ["k"]}],
              "outputs": []}  # EMPTIED by the agent (aliases moved to in_place_outputs)
        out = SynthesizeStage().transition(s, _res(wd, {
            "design_spec.json": ds, "tiling_strategy.json": '{}'}))
        outs = out.design_spec["outputs"]
        assert len(outs) == 1
        assert outs[0]["name"] == "input_tokens"   # alias restored
        assert outs[0]["shape"] == ["num_seqs"]    # enriched from same-named input
        assert outs[0]["dtype"] == ["int64"]

    def test_no_clobber_when_outputs_already_populated(self, tmp_path, wd):
        """已有正确 outputs（in-place 且非空）→ 不覆盖（不破坏正确产物）。"""
        req = {"mutation_mode": "in_place",
               "inputs": [{"name": "x", "param_type": "REQUIRED", "shape": ["n"]}],
               "outputs": [{"name": "x", "param_type": "REQUIRED"}]}
        s = self._state_with_ws(tmp_path, req)
        ds = {"op_name": "op", "mutation_mode": "in_place",
              "inputs": [{"name": "x", "param_type": "REQUIRED", "shape": ["n"]}],
              "outputs": [{"name": "x", "param_type": "REQUIRED", "shape": ["n"]}]}
        out = SynthesizeStage().transition(s, _res(wd, {
            "design_spec.json": ds, "tiling_strategy.json": '{}'}))
        assert out.design_spec["outputs"] == [
            {"name": "x", "param_type": "REQUIRED", "shape": ["n"]}]

    def test_skip_when_authoritative_requirement_missing(self, wd):
        """无权威 requirement.json（_workspace 未设）→ best-effort 跳过，不崩、不改。"""
        s = State.empty()  # no _workspace → _load_authoritative_requirement → None
        ds = {"op_name": "op", "mutation_mode": "in_place",
              "inputs": [{"name": "x", "param_type": "REQUIRED", "shape": ["n"]}],
              "outputs": []}
        out = SynthesizeStage().transition(s, _res(wd, {
            "design_spec.json": ds, "tiling_strategy.json": '{}'}))
        assert out.design_spec["outputs"] == []  # untouched — no authority to fix from


class TestValidateInputs:
    def test_gd_generate_requires_requirement(self):
        errors = GeneralDesignStage().validate_inputs(State.empty())
        assert errors  # missing requirement → non-empty

class TestGeneralDesignPassThrough:
    def test_design_doc_materialized_to_file(self, tmp_path):
        # The user's concept-design doc is NO LONGER injected verbatim into the
        # prompt (F2). Instead, _materialize_extra copies it to the working dir as
        # existing_general_design.md, and the prompt only references the file.
        doc = tmp_path / "concept.md"
        doc.write_text("# 概要设计\n切分轴优先级 N>C")
        s = State.empty().with_updates(design_doc_path=str(doc))
        actions = GeneralDesignStage().actions(s, iteration=1)
        spawn = [a for a in actions if isinstance(a, SpawnAgent)][0]
        # prompt references the materialized file
        assert "existing_general_design.md" in spawn.prompt
        assert "pass-through" in spawn.prompt
        # doc text is NOT in the prompt (it's in the file now)
        assert "切分轴优先级 N>C" not in spawn.prompt

    def test_no_design_doc_generates_from_scratch(self):
        s = State.empty()
        actions = GeneralDesignStage().actions(s, iteration=1)
        spawn = [a for a in actions if isinstance(a, SpawnAgent)][0]
        assert "pass-through" not in spawn.prompt


class TestParseSingle:
    """P4 + P5: _parse_single reads from disk directly (deterministic path)
    and clears sticky last_error on success."""

    def _make_state(self, last_error=None):
        s = State.empty()
        if last_error is not None:
            s = s.with_updates(last_error=last_error)
        return s

    def test_reads_from_working_dir(self, tmp_path):
        """P4: _parse_single reads the artifact from working_dir/{{filename}} on disk."""
        from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
        wd = tmp_path / "design" / "stage"
        wd.mkdir(parents=True)
        (wd / "general_design.json").write_text(
            '{"op_name": "gelu", "sections": {}}')

        stage = GeneralDesignStage()
        result = {"_working_dir": str(wd)}
        state = self._make_state(
            last_error=ErrorFeedback(stage_name="general-design-generator",
                                     error_type="missing_artifact",
                                     message="prior failure"))
        new_state, ok = stage._parse_single(
            state, result, "general_design", "general_design.json")
        assert ok is True
        assert new_state.general_design == {"op_name": "gelu", "sections": {}}
        # P5: sticky last_error from prior iteration MUST be cleared
        assert new_state.last_error is None

    def test_reads_from_working_dir_with_contract_validation(self, tmp_path):
        """P4: _parse_single validates against artifact_contract before accepting."""
        wd = tmp_path / "design" / "stage"
        wd.mkdir(parents=True)
        # Valid general_design.json per contract
        (wd / "general_design.json").write_text(
            '{"op_name": "add", "sections": {}, "features": []}')

        stage = GeneralDesignStage()
        result = {"_working_dir": str(wd)}
        state = self._make_state()
        new_state, ok = stage._parse_single(
            state, result, "general_design", "general_design.json")
        assert ok is True
        assert new_state.general_design is not None

    def test_missing_file_records_missing_artifact_error(self, tmp_path):
        """P62: the agent-dict fallback is gone. When the product isn't on disk
        under working_dir, transition records missing_artifact (last_error +
        user_feedback with the location requirement) and ok=False — never reads
        agent_result.artifacts. A product leaked to the repo root must NOT sail
        through on the agent's returned dict."""
        wd = tmp_path / "design" / "stage"
        wd.mkdir(parents=True)
        stage = GeneralDesignStage()
        # agent_result carries the artifact, but disk doesn't → must fail.
        result = {"_working_dir": str(wd),
                  "agent_result": _ar({
                      "general_design.json": '{"op_name": "gelu", "sections": {}}'})}
        new_state, ok = stage._parse_single(
            self._make_state(), result, "general_design", "general_design.json")
        assert ok is False
        assert new_state.last_error is not None
        assert new_state.last_error.error_type == "missing_artifact"
        # P62: user_feedback carries the location hint for the re-spawn.
        assert new_state.user_feedback
        assert str(wd) in new_state.user_feedback

    def test_unparseable_disk_file_records_schema_violation(self, tmp_path):
        """P62: a corrupt product on disk is a schema violation (no dict fallback
        to "rescue" it). The disk file is the only source."""
        wd = tmp_path / "design" / "stage"
        wd.mkdir(parents=True)
        (wd / "general_design.json").write_text("not valid json")

        stage = GeneralDesignStage()
        result = {"_working_dir": str(wd),
                  "agent_result": _ar({
                      "general_design.json": '{"op_name": "gelu", "sections": {}}'})}
        new_state, ok = stage._parse_single(
            self._make_state(), result, "general_design", "general_design.json")
        assert ok is False
        assert new_state.last_error is not None

    def test_missing_artifact_records_error_with_feedback(self, tmp_path):
        """P62: no working_dir / no product → missing_artifact with a location
        hint, so the iteration loop re-spawns the agent (not halt on first miss)."""
        from ascendc_devkit.orchestration.kernel.state import ErrorFeedback

        stage = GeneralDesignStage()
        state = self._make_state(
            last_error=ErrorFeedback(stage_name="general-design-generator",
                                     error_type="old_error",
                                     message="old"))
        result = {"_working_dir": str(tmp_path / "nonexistent"),
                  "agent_result": _ar({})}
        new_state, ok = stage._parse_single(
            state, result, "general_design", "general_design.json")
        assert ok is False
        assert new_state.last_error is not None
        assert new_state.last_error.error_type == "missing_artifact"
        assert new_state.user_feedback  # location hint for the re-spawn

    def test_no_working_dir_records_missing_artifact_error(self):
        """P62: no _working_dir at all → the product has nowhere correct to land.
        Record missing_artifact (don't fall back to agent_result.artifacts)."""
        stage = GeneralDesignStage()
        result = {"agent_result": _ar({
            "general_design.json": '{"op_name": "gelu", "sections": {}}'})}
        new_state, ok = stage._parse_single(
            self._make_state(), result, "general_design", "general_design.json")
        assert ok is False
        assert new_state.last_error is not None
        assert new_state.last_error.error_type == "missing_artifact"

    def test_sticky_last_error_cleared_on_disk_path_success(self, tmp_path):
        """P5 regression: _parse_single success MUST clear last_error so the
        runner doesn't false-report failure based on a prior iteration's error."""
        from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
        wd = tmp_path / "design" / "stage"
        wd.mkdir(parents=True)
        (wd / "template_division.json").write_text(
            '{"templates": [{"name": "T1"}], "locked_decisions": {}}')

        stage = TemplateDivisionStage()
        result = {"_working_dir": str(wd)}
        state = self._make_state(
            last_error=ErrorFeedback(
                stage_name="template-division",
                error_type="missing_artifact",
                message="iteration 1 failed"))
        new_state, ok = stage._parse_single(
            state, result, "template_division", "template_division.json")
        assert ok is True
        # P5: last_error must be None after successful parse
        assert new_state.last_error is None, (
            "last_error must be cleared on success to prevent false failure reporting")


class TestEntryKind:
    """P1-a (D2, 36-*.md §2): the incremental-modify prompt section is gated on
    entry-kind — whether the stage's OWN product file already exists in its
    working dir — NOT on iteration count.

    A corrective loopback re-enters the node at iteration=1 yet the prior
    product is still on disk, so entry_kind=modify carries the incremental
    section and the agent builds on prior work instead of re-scanning from
    scratch (the P61 stall root cause). Judging by iteration>1 alone misses
    this — the loopback re-entry sees iteration=1 and silently drops the section.
    """

    def _ws_state(self, tmp_path):
        from pathlib import Path
        s = State.empty()
        object.__setattr__(s, '_workspace',
                          type('WS', (), {'artifacts': Path(tmp_path)})())
        return s

    def test_base_entry_kind_generate_then_modify(self, tmp_path):
        # Base path (via TemplateDivisionStage): no product → generate, product
        # present → modify. Existence, not iteration, drives the kind.
        s = self._ws_state(tmp_path)
        stage = TemplateDivisionStage()
        assert stage.entry_kind(s) == "generate"
        wd = stage._working_dir(s)
        wd.mkdir(parents=True)
        (wd / "template_division.json").write_text("{}")
        assert stage.entry_kind(s) == "modify"

    def test_base_modify_prompt_carries_incremental_section(self, tmp_path):
        s = self._ws_state(tmp_path)
        stage = TemplateDivisionStage()
        wd = stage._working_dir(s)
        wd.mkdir(parents=True)
        (wd / "template_division.json").write_text("{}")
        prompt = stage._build_prompt(s, iteration=1)
        assert "增量修改上下文" in prompt
        assert "勿从零重复扫描" in prompt

    def test_base_generate_prompt_omits_incremental_section(self, tmp_path):
        s = self._ws_state(tmp_path)
        prompt = TemplateDivisionStage()._build_prompt(s, iteration=1)
        assert "增量修改上下文" not in prompt

    def test_general_design_modify_on_loopback_reentry(self, tmp_path):
        # P61 regression: GeneralDesignStage overrides _build_prompt; a loopback
        # re-entry (iteration=1) with a prior product on disk must still carry
        # the incremental section — iteration>1 alone would drop it.
        s = self._ws_state(tmp_path)
        stage = GeneralDesignStage()
        wd = stage._working_dir(s)
        wd.mkdir(parents=True)
        (wd / "general_design.json").write_text("{}")
        prompt = stage._build_prompt(s, iteration=1)
        assert "增量修改上下文" in prompt

    def test_tiling_stage_modify_uses_schema_file(self, tmp_path):
        # TilingStage judges by its own _entry_kind_filename (tiling_split.json,
        # the first required segment), not the group-level tiling_results field.
        # Per-template working dir.
        from ascendc_devkit.orchestration.stages.design_substages import TilingStage
        s = self._ws_state(tmp_path)
        stage = TilingStage(template={"name": "T1"})
        wd = stage._working_dir(s)
        wd.mkdir(parents=True)
        assert stage.entry_kind(s) == "generate"
        (wd / "tiling_split.json").write_text("{}")
        assert stage.entry_kind(s) == "modify"
        prompt = stage._build_prompt(s, iteration=1)
        assert "增量修改上下文" in prompt

    def test_tiling_stage_generate_omits_section(self, tmp_path):
        from ascendc_devkit.orchestration.stages.design_substages import TilingStage
        s = self._ws_state(tmp_path)
        prompt = TilingStage(template={"name": "T1"})._build_prompt(s, iteration=1)
        assert "增量修改上下文" not in prompt

    def test_integrate_modify_prompt_on_reentry(self, tmp_path):
        # SynthesizeStage provides design_spec → product file design_spec.json.
        s = self._ws_state(tmp_path)
        stage = SynthesizeStage()
        wd = stage._working_dir(s)
        wd.mkdir(parents=True)
        (wd / "design_spec.json").write_text("{}")
        prompt = stage._build_prompt(s, iteration=1)
        assert "增量修改上下文" in prompt


# —— P6-d: output boundary constraint in _build_prompt ——

class TestOutputBoundary:
    """P6-d: agent prompt includes boundary hint to prevent upstream product copying."""

    def test_base_build_prompt_includes_boundary(self):
        """The shared _build_prompt appends the output boundary directive."""
        stage = GeneralDesignStage()
        prompt = stage._build_prompt(State.empty(), iteration=1)
        assert "只产出上列文件" in prompt
        assert "不要将上游产物" in prompt

    def test_tiling_stage_prompt_includes_boundary(self):
        """Tiling stage inherits the boundary via base _build_prompt."""
        from ascendc_devkit.orchestration.stages.design_substages import TilingStage
        s = State.empty().with_updates(
            template_division={"templates": [{"name": "T1"}]})
        stage = TilingStage(template={"name": "T1"})
        prompt = stage._build_prompt(s, iteration=1)
        assert "只产出上列文件" in prompt
        assert "不要将上游产物" in prompt

    def test_dd_intake_prompt_also_includes_boundary(self):
        """dd-intake's custom _build_prompt also includes the boundary."""
        from ascendc_devkit.orchestration.stages.design_substages import (
            DetailedDesignIntakeStage)
        from pathlib import Path
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            dd = Path(td) / "detailed.md"
            dd.write_text("# design")
            s = State.empty().with_updates(detailed_design_path=dd)
            stage = DetailedDesignIntakeStage()
            prompt = stage._build_prompt(s, iteration=1)
            assert "只产出上列文件" in prompt or "不要将上游产物" in prompt


class TestOpDirDisambiguation:
    """design-halt-diagnostics P4: op_dir (external reference operator dir) must
    be explicitly marked read-only where it first appears, and the output
    boundary must restate that cwd — not op_dir — is the sole output target.
    Prevents an agent from writing/copying design products into op_dir."""

    def test_operator_section_marks_op_dir_read_only(self):
        s = State.empty().with_updates(op_name="add", op_dir="/repo/ops/add")
        stage = GeneralDesignStage()
        section = stage._operator_section(s)
        assert "/repo/ops/add" in section
        assert "只读参考" in section

    def test_operator_section_empty_without_op_dir(self):
        """No op_dir → no disambiguation noise (keeps synthetic-test prompts clean)."""
        s = State.empty()
        stage = GeneralDesignStage()
        section = stage._operator_section(s)
        assert "只读参考" not in section

    def test_output_boundary_restates_cwd_is_sole_output(self):
        # _output_boundary 现在需要 state（20260820 方案 B 注入 cwd 路径）。
        # 无 workspace 时走原 boundary（不含 cwd 注入），op_dir 只读提示保留。
        stage = GeneralDesignStage()
        boundary = stage._output_boundary(State.empty())
        assert "op_dir" in boundary
        assert "只读参考" in boundary
        assert "当前工作目录" in boundary


class TestFeedbackSection:
    """P45 第一刀: loopback feedback must be consumed by the retrying agent.
    The base ``_feedback_section`` helper is shared by the base ``_build_prompt``
    and the ``TilingStage`` override (which previously dropped it →
    run 20260706-192227's 3-round zero-consumption). P44-C: it renders the
    judgment face (verdict/detail) as fact and remediation as non-binding advice.
    """

    def test_tiling_stage_prompt_consumes_loopback_feedback(self):
        # run 20260706-192227 regression: the tiling stage override dropped the
        # feedback section, so corrective rounds consumed zero feedback.
        from ascendc_devkit.orchestration.stages.design_substages import TilingStage
        s = State.empty().with_updates(
            op_name="rope", template_division={"templates": [{"name": "T1"}]},
            _loopback_feedback={"blocking_issues": [
                {"code": "AC2", "detail": "split 轴与 anchor 冲突",
                 "target": "tiling", "target_template": "T1"}]})
        spawn = next(a for a in TilingStage(template={"name": "T1"}).actions(s, 1)
                     if isinstance(a, SpawnAgent))
        assert "## 上次反馈" in spawn.prompt
        assert "split 轴与 anchor 冲突" in spawn.prompt


def _transcript(tmp_path, turns, name="agent-1.jsonl"):
    """Write a transcript jsonl file: ``turns`` is a list of block-lists, one
    per AssistantMessage (mirrors sdk_backend.py's _serialize_event/_serialize_block
    shape). Returns the Path."""
    path = tmp_path / name
    lines = [json.dumps({"ts": "t", "type": "AssistantMessage",
                         "turn": i, "blocks": blocks})
             for i, blocks in enumerate(turns, start=1)]
    path.write_text("\n".join(lines) + "\n")
    return path


def _write_block(file_path, content="{}"):
    return {"kind": "tool_use", "tool_name": "Write",
            "tool_input": {"file_path": str(file_path), "content": content}}


class TestHarvestRelocationEvidence:
    """P3 (artifact-location-provenance): scan a transcript jsonl for
    Write/Edit calls that landed outside the stage's working_dir, tolerant
    filename match via _normalize_stem. Pure function — no State involved."""

    def test_finds_write_outside_wd(self, tmp_path):
        wd = tmp_path / "wd"
        wd.mkdir()
        op_dir = tmp_path / "op"
        op_dir.mkdir()
        misplaced = op_dir / "general_design.json"
        transcript = _transcript(tmp_path, [[_write_block(misplaced)]])
        found = _harvest_relocation_evidence(transcript, "general_design.json", wd)
        assert found == misplaced

    def test_tolerant_filename_match(self, tmp_path):
        wd = tmp_path / "wd"
        wd.mkdir()
        op_dir = tmp_path / "op"
        op_dir.mkdir()
        # Different case / no separators, same stem when normalized.
        misplaced = op_dir / "GeneralDesign.json"
        transcript = _transcript(tmp_path, [[_write_block(misplaced)]])
        found = _harvest_relocation_evidence(transcript, "general_design.json", wd)
        assert found == misplaced

    def test_extension_mismatch_is_not_evidence(self, tmp_path):
        wd = tmp_path / "wd"
        wd.mkdir()
        op_dir = tmp_path / "op"
        op_dir.mkdir()
        misplaced = op_dir / "general_design.md"
        transcript = _transcript(tmp_path, [[_write_block(misplaced)]])
        found = _harvest_relocation_evidence(transcript, "general_design.json", wd)
        assert found is None

    def test_unrelated_filename_no_match(self, tmp_path):
        wd = tmp_path / "wd"
        wd.mkdir()
        op_dir = tmp_path / "op"
        op_dir.mkdir()
        misplaced = op_dir / "tiling_split.json"
        transcript = _transcript(tmp_path, [[_write_block(misplaced)]])
        found = _harvest_relocation_evidence(transcript, "general_design.json", wd)
        assert found is None

    def test_write_inside_wd_is_not_evidence(self, tmp_path):
        # Already in the correct place — _locate_artifact would have found it;
        # harvest only surfaces MISplaced writes (outside wd).
        wd = tmp_path / "wd"
        wd.mkdir()
        inside = wd / "general_design.json"
        transcript = _transcript(tmp_path, [[_write_block(inside)]])
        found = _harvest_relocation_evidence(transcript, "general_design.json", wd)
        assert found is None

    def test_no_transcript_returns_none(self, tmp_path):
        wd = tmp_path / "wd"
        wd.mkdir()
        assert _harvest_relocation_evidence(None, "general_design.json", wd) is None

    def test_missing_transcript_file_returns_none(self, tmp_path):
        wd = tmp_path / "wd"
        wd.mkdir()
        missing = tmp_path / "does_not_exist.jsonl"
        assert _harvest_relocation_evidence(missing, "general_design.json", wd) is None

    def test_bash_tool_calls_are_skipped(self, tmp_path):
        # P4: Bash cp/mv has no structured file_path — best-effort skip, not a
        # crash and not a false match.
        wd = tmp_path / "wd"
        wd.mkdir()
        op_dir = tmp_path / "op"
        op_dir.mkdir()
        transcript = _transcript(tmp_path, [[{
            "kind": "tool_use", "tool_name": "Bash",
            "tool_input": {"command": f"cp x.json {op_dir / 'general_design.json'}"},
        }]])
        found = _harvest_relocation_evidence(transcript, "general_design.json", wd)
        assert found is None

    def test_multiple_writes_takes_last_chronologically(self, tmp_path):
        wd = tmp_path / "wd"
        wd.mkdir()
        op_dir = tmp_path / "op"
        op_dir.mkdir()
        first = op_dir / "general_design_v1.json"
        second = op_dir / "general_design_v2.json"
        # Both match tolerantly against "general_design" only if stems align —
        # use the exact target name for the later write so the "last wins" is
        # unambiguous, and a differently-stemmed earlier write that also matches.
        first_exact = op_dir / "general_design.json"
        transcript = _transcript(tmp_path, [
            [_write_block(first_exact, content='{"v": 1}')],
            [_write_block(first_exact, content='{"v": 2}')],
        ])
        found = _harvest_relocation_evidence(transcript, "general_design.json", wd)
        assert found == first_exact

    def test_malformed_line_is_skipped_best_effort(self, tmp_path):
        wd = tmp_path / "wd"
        wd.mkdir()
        op_dir = tmp_path / "op"
        op_dir.mkdir()
        misplaced = op_dir / "general_design.json"
        transcript = tmp_path / "agent-1.jsonl"
        transcript.write_text(
            "not valid json\n" +
            json.dumps({"ts": "t", "type": "AssistantMessage", "turn": 1,
                       "blocks": [_write_block(misplaced)]}) + "\n")
        found = _harvest_relocation_evidence(transcript, "general_design.json", wd)
        assert found == misplaced

    def test_harvest_works_on_opencode_produced_transcript(self, tmp_path):
        # step 61 (b) end-to-end: a transcript produced by OpenCodeBackend's
        # normalized _parts_to_records must be readable by harvest — proving the
        # SDK-schema alignment closes the opencode取证空转 gap. Build the records
        # via the real producer (opencode-native parts) and confirm harvest finds
        # the misplaced Write.
        from ascendc_devkit.capabilities.agent.opencode_backend import (
            OpenCodeBackend)
        wd = tmp_path / "wd"
        wd.mkdir()
        op_dir = tmp_path / "op"
        op_dir.mkdir()
        misplaced = op_dir / "tiling_split.json"
        recs = OpenCodeBackend()._parts_to_records({"parts": [
            {"type": "tool", "tool": "Write",
             "input": {"file_path": str(misplaced), "content": "{}"}},
        ]}, turn=2)
        transcript = tmp_path / "agent-1.jsonl"
        transcript.write_text(
            "\n".join(json.dumps(r) for r in recs) + "\n")
        found = _harvest_relocation_evidence(transcript, "tiling_split.json", wd)
        assert found == misplaced

    def test_harvest_real_opencode_schema_lowercase_nested(self, tmp_path):
        """(b) 根治 — 真实 opencode transcript schema：``tool_name`` 小写
        ``write``，路径嵌在 ``tool_input.input.filePath``（camelCase，多套一层
        opencode tool-state）。修前 harvester 只认 SDK schema（大写 ``Write`` +
        ``tool_input.file_path``），对真实 opencode 写**静默失明**——正是 batch
        20260729-* d67f55 越界 blocking_status 无检测的根因。此 fixture 用真实
        opencode block 形状（非理想化），修前必 None、修后必命中。"""
        wd = tmp_path / "wd"
        wd.mkdir()
        misplaced = tmp_path / "batch" / "batch_id" / "op" / "blocking_status.json"
        misplaced.parent.mkdir(parents=True)
        # 真实 opencode block：tool_name 小写，tool_input = opencode tool-state
        # object，真实参数嵌在 .input.filePath（camelCase）
        block = {"kind": "tool_use", "tool_name": "write",
                 "tool_input": {"status": "completed",
                                "input": {"filePath": str(misplaced),
                                          "content": "{}"}}}
        transcript = _transcript(tmp_path, [[block]])
        found = _harvest_relocation_evidence(transcript, "blocking_status.json", wd)
        assert found == misplaced

    def test_sweep_removes_stray_when_product_also_in_wd(self, tmp_path):
        """(b) 根治 success-path sweep：agent 同时写了正确 wd 副本 AND wd 外副本
        （d67f55 就是这样）→ relocation 门只在产物 MISSING 时触发，故正确+越界并存
        时越界副本会永久遗留。_read_disk_artifacts 成功路径应清掉越界副本。"""
        wd = tmp_path / "wd"
        wd.mkdir()
        # correct copy in wd
        (wd / "general_design.json").write_text(
            '{"op_name":"gelu","sections":{}}', encoding="utf-8")
        # stray copy outside wd, proven by transcript (real opencode schema)
        stray = tmp_path / "elsewhere" / "general_design.json"
        stray.parent.mkdir(parents=True)
        stray.write_text('{"op_name":"stray"}', encoding="utf-8")
        block = {"kind": "tool_use", "tool_name": "write",
                 "tool_input": {"input": {"filePath": str(stray), "content": "{}"}}}
        transcript = _transcript(tmp_path, [[block]])
        ar = type("AR", (), {"transcript": transcript})()
        stage = GeneralDesignStage()
        raw, err = stage._read_disk_artifacts(
            State.empty(),
            {"_working_dir": str(wd), "agent_result": ar},
            ["general_design.json"])
        assert err is None
        assert raw is not None                       # correct copy still read
        assert (wd / "general_design.json").is_file()  # correct copy untouched
        assert not stray.exists()                    # stray swept away


class TestMissingArtifactErrorEvidence:
    """_missing_artifact_error's evidence branch (artifact-location-provenance,
    20260821 收口后语义): reached only AFTER in-place recovery was refused by
    the caller. When a transcript proves the missing product landed outside wd,
    the correction message cites the real path instead of the generic
    'not found' text."""

    def test_evidence_found_cites_real_path(self, tmp_path):
        wd = tmp_path / "wd"
        wd.mkdir()
        op_dir = tmp_path / "op"
        op_dir.mkdir()
        misplaced = op_dir / "general_design.json"
        misplaced.write_text("{}")
        transcript = _transcript(tmp_path, [[_write_block(misplaced)]])

        stage = GeneralDesignStage()
        out = stage._missing_artifact_error(
            State.empty(), "general_design.json", wd, transcript=transcript)
        assert str(misplaced) in out.user_feedback
        assert out.last_error is not None
        assert out.last_error.error_type == "missing_artifact"

    def test_no_transcript_no_evidence(self, tmp_path):
        wd = tmp_path / "wd"
        wd.mkdir()
        stage = GeneralDesignStage()
        out = stage._missing_artifact_error(State.empty(), "general_design.json", wd)
        assert out.last_error is not None

    def test_no_working_dir_no_evidence_lookup(self, tmp_path):
        # wd=None (P62 no-working-dir path) — nothing to compare transcript
        # paths against, must not raise.
        transcript = _transcript(tmp_path, [[_write_block(tmp_path / "x.json")]])
        stage = GeneralDesignStage()
        out = stage._missing_artifact_error(
            State.empty(), "general_design.json", None, transcript=transcript)
        assert out.last_error is not None


class TestInfraShortCircuit:
    """P93 (step-69): 设计子阶段 infra 感知——agent 因 infra 错误（网关/配置/鉴权/
    spawn 超时）未产出时，不再误报 missing_artifact（写错目录），改报 infra + 不写
    误导 user_feedback；actions() infra 短路终止迭代（step-27 DEFER 收窄）。"""

    @staticmethod
    def _infra_ar(reason="Model GLM-5.2 price not configured"):
        return AgentResult(agent_name="x", status="fatal", error_type="infra",
                           metrics={"failure_reason": reason})

    def test_transition_infra_marks_error_not_missing_artifact(self, tmp_path):
        # agent 因 infra 未产出 → last_error.error_type="infra"（非 missing_artifact）
        wd = tmp_path / "design" / "template-division"
        wd.mkdir(parents=True)
        out = TemplateDivisionStage().transition(
            State.empty(),
            {"_working_dir": str(wd), "agent_result": self._infra_ar()})
        assert out.last_error is not None
        assert out.last_error.error_type == "infra"
        assert out.template_division is None

    def test_transition_infra_message_cites_cause_not_path(self, tmp_path):
        wd = tmp_path / "design" / "template-division"
        wd.mkdir(parents=True)
        out = TemplateDivisionStage().transition(
            State.empty(),
            {"_working_dir": str(wd),
             "agent_result": self._infra_ar("opencode spawn timed out")})
        assert "基础设施" in out.last_error.message
        assert "timed out" in out.last_error.message
        # 不是"写错目录"误导文案
        assert "未在正确目录" not in out.last_error.message

    def test_actions_infra_short_circuits(self):
        from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
        s = State.empty().with_updates(
            last_error=ErrorFeedback(stage_name="template-division",
                                     error_type="infra", message="infra halt"))
        actions = TemplateDivisionStage().actions(s, iteration=2)
        assert actions == []  # 不再 spawn，终止迭代

    def test_actions_missing_artifact_still_retries(self):
        # 回归守护：missing_artifact 仍正常 spawn 重试，不被 infra 短路误伤
        from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
        s = State.empty().with_updates(
            last_error=ErrorFeedback(stage_name="template-division",
                                     error_type="missing_artifact", message="..."))
        actions = TemplateDivisionStage().actions(s, iteration=2)
        assert any(isinstance(a, SpawnAgent) for a in actions)

    def test_logic_failure_keeps_missing_artifact(self, tmp_path):
        # 回归守护：普通逻辑失败（error_type=None）+ 产物缺失 → 仍 missing_artifact
        wd = tmp_path / "design" / "template-division"
        wd.mkdir(parents=True)
        out = TemplateDivisionStage().transition(
            State.empty(),
            {"_working_dir": str(wd), "agent_result": _ar({})})
        assert out.last_error.error_type == "missing_artifact"


class TestHwParamsChipIdentity:
    """hw_params.json 携带 canonical chip_code + soc_version，让设计 skill（尤其
    docgen §2.3 OpDef AddConfig）有确定性的文件级 chip 源——design JSON 契约保持
    chip-agnostic，chip 走这条 sanctioned 通道（治 <SOC_VERSION> 占位幻觉）。"""

    def _state(self, chip):
        from ascendc_devkit.orchestration.run_context import (
            RunContext, build_hardware_target)
        rc = RunContext(hardware_target=build_hardware_target(chip))
        return State.empty().with_updates(run_context=rc, design_target_chip=chip)

    @pytest.mark.parametrize("chip,soc", [
        ("A2", "ascend910b"), ("A3", "ascend910_93"), ("A5", "ascend950")])
    def test_hw_params_carries_chip_code_and_soc_version(self, tmp_path, chip, soc):
        SynthesizeStage()._materialize_run_context(self._state(chip), tmp_path)
        params = json.loads((tmp_path / "hw_params.json").read_text(encoding="utf-8"))
        assert params["chip_code"] == chip
        assert params["soc_version"] == soc
        # 硬件真值仍在（chip 字段是加性的，不替代 hw 参数）
        assert "ub_size_bytes" in params

    def test_no_known_chip_writes_hw_params_without_chip_fields(self, tmp_path):
        # design_target_chip 未声明/未知 → hw 真值照写，但不伪造 chip_code/soc_version
        # （§3.7 honest error：不静默回落，让消费方明确感知 chip 不可用）。
        from ascendc_devkit.orchestration.run_context import (
            RunContext, build_hardware_target)
        rc = RunContext(hardware_target=build_hardware_target("A5"))
        s = State.empty().with_updates(run_context=rc)  # 不设 design_target_chip
        SynthesizeStage()._materialize_run_context(s, tmp_path)
        params = json.loads((tmp_path / "hw_params.json").read_text(encoding="utf-8"))
        assert "chip_code" not in params
        assert "soc_version" not in params
        assert "ub_size_bytes" in params

    def test_hw_params_dict_not_mutated(self, tmp_path):
        # 实现细节守护：hw_params 是缓存共享对象，物化不得原地改它。
        s = self._state("A5")
        original = dict(s.run_context.hardware_target.hw_params)
        SynthesizeStage()._materialize_run_context(s, tmp_path)
        assert s.run_context.hardware_target.hw_params == original
        assert "chip_code" not in s.run_context.hardware_target.hw_params


class TestIntegrateMaterializesRequirement:
    """A': integrate 的 _upstream_inputs 含 requirement（携带 param_type），使其能
    按 name 对齐 tiling 轨丢弃的 IO 契约事实。这是有界契约对齐，非跨读设计步产物。"""

    def _req(self):
        from ascendc_devkit.domain.requirement import Requirement
        from ascendc_devkit.domain.operator import OperatorSpec, TensorSpec
        return Requirement(op_spec=OperatorSpec(
            name="add",
            inputs=[TensorSpec(name="x", dtype="fp16", param_type="REQUIRED"),
                    TensorSpec(name="bias", dtype="fp16", param_type="OPTIONAL")],
            outputs=[TensorSpec(name="y", dtype="fp16")]))

    def test_requirement_in_upstream_inputs(self):
        s = State.empty().with_updates(requirement=self._req())
        inputs = SynthesizeStage()._upstream_inputs(s)
        assert "requirement" in inputs
        assert inputs["requirement"] is not None

    def test_param_type_survives_proto_materialization(self, tmp_path):
        # requirement 经 proto asdict 物化成 requirement.json 时，param_type 必须保留
        # （TensorSpec.param_type 字段）——否则 integrate 读到的 requirement.json 丢失
        # 可选性，OPTIONAL 无法对齐。
        import dataclasses
        s = State.empty().with_updates(requirement=self._req())
        # 模拟 _materialize_inputs 的 asdict 序列化路径
        payload = dataclasses.asdict(s.requirement)
        bias = next(i for i in payload["op_spec"]["inputs"] if i["name"] == "bias")
        assert bias["param_type"] == "OPTIONAL"
        x = next(i for i in payload["op_spec"]["inputs"] if i["name"] == "x")
        assert x["param_type"] == "REQUIRED"

    def test_design_spec_param_type_preserved_through_transition(self, wd):
        # integrate transition 不得剥离 design_spec 每项的 param_type（codegen/docgen
        # 据此渲染 OpDef .ParamType）。回归守护：loose schema 须透传该字段。
        s = State.empty()
        out = SynthesizeStage().transition(s, _res(wd, {
            "design_spec.json": json.dumps({
                "op_name": "add",
                "mutation_mode": "out_of_place",
                "inputs": [{"name": "x", "param_type": "REQUIRED"},
                           {"name": "bias", "param_type": "OPTIONAL"}],
                "outputs": [{"name": "y", "param_type": "REQUIRED"}]}),
            "tiling_strategy.json": '{"approach": "x"}',
        }))
        assert out.last_error is None
        inputs = {i["name"]: i for i in out.design_spec["inputs"]}
        assert inputs["x"]["param_type"] == "REQUIRED"
        assert inputs["bias"]["param_type"] == "OPTIONAL"


# —— golden fixtures for _route_scalar_params D-reconcile tests (mirror
#    test_golden_binding.py: real torch.Tensor if available, else "Tensor" string;
#    classify_golden_params keys off "Tensor" in the annotation text either way) ——
try:
    import torch as _torch
    _T = _torch.Tensor
except Exception:
    _T = "Tensor"


def _golden_maximum(x1: _T, x2: _T):
    return x1


def _golden_scalar_only(eps: float):
    return eps


class TestRouteScalarParams:
    """_route_scalar_params: is_scalar_entry routing (§2.5) + D-reconcile to
    golden-signature authority (§1.13 — 能修绝不 halt/不空转).

    Guards the 20260805-152456 Maximum RCA: shape:[] tensors must NOT be routed
    into attrs (empties inputs/outputs → codegen halt)."""

    def test_r1_elementwise_shape_empty_not_routed(self):
        # Maximum: shape:[] (broadcast) tensors stay in inputs/outputs, not attrs.
        ds = {
            "inputs": [{"name": "x1", "shape": [], "dtype": ["float16"], "format": "ND"},
                       {"name": "x2", "shape": [], "dtype": ["float16"], "format": "ND"}],
            "outputs": [{"name": "y", "shape": [], "dtype": ["float16"], "format": "ND"}],
            "attrs": [],
        }
        moved = _route_scalar_params(ds)
        assert moved == []
        assert [i["name"] for i in ds["inputs"]] == ["x1", "x2"]
        assert [o["name"] for o in ds["outputs"]] == ["y"]
        assert ds["attrs"] == []

    def test_r2_role_attr_scalar_routed_to_attrs(self):
        ds = {
            "inputs": [{"name": "x", "shape": [128], "dtype": "fp16"},
                       {"name": "eps", "role": "attr", "type": "float"}],
            "outputs": [{"name": "y", "shape": [128], "dtype": "fp16"}],
            "attrs": [],
        }
        moved = _route_scalar_params(ds)
        assert moved == ["inputs/eps"]
        assert [i["name"] for i in ds["inputs"]] == ["x"]
        assert any(a["name"] == "eps" for a in ds["attrs"])

    def test_r3_d_reconcile_restores_misrouted_tensor_from_golden(self):
        # x1 mis-routed into attrs (e.g. by the old shape==[] bug); golden signature
        # names x1/x2 as tensors → D restores them into inputs (no halt, no loopback).
        ds = {"inputs": [], "outputs": [], "attrs": [{"name": "x1", "type": ["float16"]}]}
        moved = _route_scalar_params(ds, golden_fn=_golden_maximum)
        assert [i["name"] for i in ds["inputs"]] == ["x1", "x2"]
        assert ds["attrs"] == []                          # x1 restored out of attrs
        assert moved == []

    def test_r4_d_reconcile_fills_missing_inputs_from_golden(self):
        # inputs entirely empty; golden signature has tensors → D fills inputs.
        ds = {"inputs": [], "outputs": [], "attrs": []}
        _route_scalar_params(ds, golden_fn=_golden_maximum, requirement=None)
        assert {i["name"] for i in ds["inputs"]} == {"x1", "x2"}

    def test_r5_no_io_authority_leaves_ds_for_codegen_halt(self):
        # golden has no Tensor annotations AND requirement is IO-empty → no
        # authority → D does not fire (the only unrecoverable case: op truly has
        # no IO; left to codegen.validate_inputs halt).
        ds = {"inputs": [], "outputs": [], "attrs": []}
        moved = _route_scalar_params(ds, golden_fn=_golden_scalar_only,
                                     requirement={"inputs": [], "outputs": []})
        assert moved == []
        assert ds["inputs"] == []
        assert ds["attrs"] == []


class TestRequirementAuthoritativeMaterialization:
    """P1/§3.12: 设计链 agent-facing requirement 一律物化磁盘权威全量（含 domain），
    非 reduced {op_spec 单 dtype} wrap；权威不可达 → 不落 reduced。"""

    def _stage(self):
        return GeneralDesignStage()

    def _state_with_ws(self, tmp_path, requirement_json):
        from ascendc_devkit.domain.requirement import Requirement
        from ascendc_devkit.domain.operator import OperatorSpec
        s = State.empty().with_updates(
            op_name="exp",
            requirement=Requirement(op_spec=OperatorSpec(name="exp")))
        root = tmp_path / "ws"
        (root / "requirement").mkdir(parents=True)
        (root / "requirement" / "requirement.json").write_text(
            json.dumps(requirement_json, ensure_ascii=False), encoding="utf-8")
        object.__setattr__(
            s, "_workspace", type("WS", (), {"artifacts": root})())
        return s

    def test_materializes_full_authority_with_domain(self, tmp_path):
        # UT-1（§3.12 不变式）: 物化落盘是权威全量（含 domain.dtypes 三值 + 公式），
        # 非 {op_spec: 单 dtype} wrap——设计 agent 必须看到完整需求域。
        req = {
            "op_name": "exp",
            "mutation_mode": "out_of_place",
            "inputs": [{"name": "x", "dtype": "float16"}],
            "outputs": [{"name": "y", "dtype": "float16"}],
            "math_formula": "y = exp(x)",
            "domain": {"rank": {"min": 0, "max": 8},
                       "inputs": [{"name": "x", "dtypes": [
                           "float16", "float32", "bfloat16"]}]},
        }
        s = self._state_with_ws(tmp_path, req)
        wd = tmp_path / "cwd"
        wd.mkdir()
        self._stage()._materialize_inputs(s, wd)
        got = json.loads((wd / "requirement.json").read_text(encoding="utf-8"))
        assert "domain" in got, "权威物化必须含 domain 字段"
        assert got["domain"]["inputs"][0]["dtypes"] == [
            "float16", "float32", "bfloat16"]
        assert got["mutation_mode"] == "out_of_place"
        assert got["math_formula"] == "y = exp(x)"
        assert "op_spec" not in got, "不得落 reduced {op_spec: ...} wrap（§3.12）"

    def test_authority_missing_does_not_materialize_reduced(self, tmp_path):
        # §3.12: requirement 在 State 但权威磁盘文件不可达 → 不落 reduced，
        # 不拿有损数据冒充权威输入。
        from ascendc_devkit.domain.requirement import Requirement
        from ascendc_devkit.domain.operator import OperatorSpec
        s = State.empty().with_updates(
            op_name="exp",
            requirement=Requirement(op_spec=OperatorSpec(name="exp")))
        wd = tmp_path / "cwd"
        wd.mkdir()
        self._stage()._materialize_inputs(s, wd)
        assert not (wd / "requirement.json").exists(), \
            "权威不可达时不应物化 reduced requirement.json（§3.12）"


# —— 20260820 batch fallback: 非交互自动搬回孤儿产物（方案 A）+ prompt 注入 cwd（方案 B） ——

class TestInplaceRelocation:
    """20260821 F3 全局收口：孤儿产物就地搬回（同轮自愈）。locate 失败 → transcript
    证据 → recover_orphan_artifact（防御性搬回）→ 重新 locate → 本轮直接消费。

    驱动方式是真实的失败路径：构造孤儿文件 + transcript（agent_result.transcript），
    走 `_read_disk_artifacts`，断言 raw 同轮读回 + 文件落位。非交互/交互无差别
    （决策点已删，行为统一）。"""

    @staticmethod
    def _layout(tmp_path, non_interactive=True):
        """Real batch layout: run_dir artifacts wd + orphan under a
        missing-prefix run_dir of the SAME batch."""
        batch = tmp_path / "run"
        wd = (batch / "20260820-103324-164bbc" / "artifacts" / "design"
              / "general-design-generator")
        wd.mkdir(parents=True)
        orphan_dir = (batch / "20260820-164bbc" / "artifacts" / "design"
                      / "general-design-generator")
        orphan_dir.mkdir(parents=True)
        return batch, wd, orphan_dir

    def _drive(self, tmp_path, orphan, wd, filename="general_design.json"):
        transcript = _transcript(tmp_path, [[_write_block(orphan)]])
        ar = AgentResult(agent_name="x", status="ok", artifacts={},
                         transcript=transcript)
        s = State.empty()
        stage = GeneralDesignStage()
        return stage._read_disk_artifacts(
            s, {"_working_dir": str(wd), "agent_result": ar},
            [filename])

    def test_orphan_recovered_same_round(self, tmp_path):
        """孤儿 + 证据 → 搬回 + 同轮 raw 读回（零额外迭代）。"""
        batch, wd, orphan_dir = self._layout(tmp_path)
        orphan = orphan_dir / "general_design.json"
        orphan.write_text('{"op_name": "rms_norm", "split_axis_priority": ["N"], "sections": {}}')

        raw, err = self._drive(tmp_path, orphan, wd)

        assert err is None, f"同轮自愈应成功，got error: {err}"
        assert (wd / "general_design.json").exists(), "产物应被搬回 wd"
        assert not orphan.exists(), "孤儿副本应被移除"
        assert "general_design.json" in raw

    def test_orphan_recovered_in_interactive_mode_too(self, tmp_path):
        """交互模式（non_interactive=False）同样就地自愈——决策点已删，行为统一。"""
        batch, wd, orphan_dir = self._layout(tmp_path)
        orphan = orphan_dir / "general_design.json"
        orphan.write_text('{"op_name": "x"}')

        raw, err = self._drive(tmp_path, orphan, wd)

        assert err is None, "交互模式孤儿也应同轮自愈"

    def test_missing_orphan_falls_back_to_missing(self, tmp_path):
        """证据指向的文件已不存在 → 恢复返回 False，走 missing 路径。"""
        batch, wd, orphan_dir = self._layout(tmp_path)
        orphan = orphan_dir / "general_design.json"
        # 不写文件：证据在 transcript 里但磁盘上没有

        raw, err = self._drive(tmp_path, orphan, wd)

        assert raw is None
        assert err is not None, "missing 路径应返回 err_state"
        assert err.last_error is not None

    def test_target_exists_different_file_refuses_overwrite(self, tmp_path):
        """防御（单元级）：wd 已存在同名但不同的产物 → recover_orphan_artifact
        拒绝覆盖、返回 False。注：required 路径正常不可达此分支（wd 有同名文件时
        locate-exact 已成功，不会进恢复）——该防御守护的是并发/竞态下 locate 与
        move 之间窗口，故直接对恢复函数断言。"""
        from ascendc_devkit.orchestration.artifact_recovery import (
            recover_orphan_artifact)
        batch, wd, orphan_dir = self._layout(tmp_path)
        orphan = orphan_dir / "general_design.json"
        orphan.write_text('{"op_name": "rms_norm"}')
        (wd / "general_design.json").write_text('{"op_name": "OTHER_OP"}')
        transcript = _transcript(tmp_path, [[_write_block(orphan)]])

        ok = recover_orphan_artifact(
            transcript, "general_design.json", wd, State.empty(),
            "general-design-generator")

        assert ok is False, "target 已存在不同文件时应拒绝覆盖"
        # wd 原有产物应保持原样，孤儿文件应保留（未被删除/覆盖）
        assert (wd / "general_design.json").read_text() == '{"op_name": "OTHER_OP"}'
        assert orphan.exists(), "孤儿文件不应被删除"

    def test_target_same_file_idempotent_skip(self, tmp_path):
        """防御：wd 已有产物与孤儿是同一文件（hardlink）→ 幂等跳过，落回解析路径。"""
        import os as _os
        batch, wd, orphan_dir = self._layout(tmp_path)
        orphan = orphan_dir / "general_design.json"
        orphan.write_text('{"op_name": "rms_norm"}')
        _os.link(str(orphan), str(wd / "general_design.json"))

        raw, err = self._drive(tmp_path, orphan, wd)

        assert err is None, f"samefile 应幂等跳过并解析成功，got {err}"
        assert raw is not None, "应能读到产物"
        assert (wd / "general_design.json").exists()

    def test_cross_batch_orphan_not_recovered(self, tmp_path):
        """跨 batch 孤儿（wd 有锚点 + 孤儿锚点不同）→ 检测层拒搬，走 missing。"""
        wd = tmp_path / "run" / "artifacts" / "design" / "general-design-generator"
        wd.mkdir(parents=True)
        other = (tmp_path / "other-batch" / "20260820-deadbeef" / "artifacts"
                 / "design" / "general-design-generator" / "general_design.json")
        other.parent.mkdir(parents=True)
        other.write_text('{"op_name": "x"}')

        raw, err = self._drive(tmp_path, other, wd)

        assert raw is None, "跨 batch 孤儿不应被搬回"
        assert err is not None
        assert other.exists(), "跨 batch 文件不应被动"


class TestOutputBoundaryCwdInjection:
    """F8 兜底（方案 B）：_output_boundary 注入 working_dir 绝对路径 + pwd 验证提示。"""

    def test_prompt_injects_cwd_absolute_path(self, tmp_path):
        # Workspace(base_dir, run_id) → dir = base_dir/run_id；_working_dir =
        # dir/artifacts/design/<name>，无中间 run/ 层。
        wd = tmp_path / "20260820-103324-164bbc" / "artifacts" / "design" / "general-design-generator"
        wd.mkdir(parents=True)
        s = State.empty()
        # _working_dir 需要 state._workspace
        from ascendc_devkit.infra.workspace import Workspace
        ws = Workspace(base_dir=tmp_path, run_id="20260820-103324-164bbc")
        s = s.with_updates(_workspace=ws)
        boundary = GeneralDesignStage()._output_boundary(s)
        assert str(wd) in boundary, f"应注入 cwd 绝对路径，got: {boundary}"
        assert "pwd" in boundary, "应要求 pwd 验证"
        assert "禁止拼写绝对路径" in boundary, "应禁止绝对路径写盘"

    def test_prompt_no_workspace_keeps_original(self):
        s = State.empty()  # 无 _workspace → _working_dir 返回 None
        boundary = GeneralDesignStage()._output_boundary(s)
        assert "只产出上列文件" in boundary, "无 workspace 时保持原输出边界"
        assert "当前工作目录（cwd）的完整路径为" not in boundary


class TestRelocationEvidenceDetailed:
    """_harvest_relocation_evidence_detailed 返回 (path, reason) 以支持可诊断日志。"""

    def test_cross_batch_returns_reason(self, tmp_path):
        """跨 batch 拒搬 → detailed 返回 (None, 'cross_batch')，供 WARN。"""
        wd = tmp_path / "run" / "artifacts" / "design" / "general-design-generator"
        wd.mkdir(parents=True)
        other = tmp_path / "other-batch" / "20260820-deadbeef" / "artifacts" / "design" / "general-design-generator" / "general_design.json"
        other.parent.mkdir(parents=True)
        other.write_text('{"op_name": "x"}')
        trans = tmp_path / "t.jsonl"
        trans.write_text(json.dumps({
            "blocks": [{
                "kind": "tool_use",
                "tool_name": "write",
                "tool_input": {"input": {"filePath": str(other)}},
            }],
        }) + "\n")

        path, reason = _harvest_relocation_evidence_detailed(
            str(trans), "general_design.json", wd)
        assert path is None
        assert reason == "cross_batch", f"应标记跨 batch 拒搬，got {reason}"

    def test_same_batch_returns_path_no_reason(self, tmp_path):
        """同 batch 孤儿 → detailed 返回 (path, None)，可搬回。"""
        batch = tmp_path / "run"
        wd = batch / "20260820-103324-164bbc" / "artifacts" / "design" / "general-design-generator"
        wd.mkdir(parents=True)
        orphan = batch / "20260820-164bbc" / "artifacts" / "design" / "general-design-generator" / "general_design.json"
        orphan.parent.mkdir(parents=True)
        orphan.write_text('{"op_name": "x"}')
        trans = tmp_path / "t.jsonl"
        trans.write_text(json.dumps({
            "blocks": [{
                "kind": "tool_use",
                "tool_name": "write",
                "tool_input": {"input": {"filePath": str(orphan)}},
            }],
        }) + "\n")

        path, reason = _harvest_relocation_evidence_detailed(
            str(trans), "general_design.json", wd)
        assert path == orphan
        assert reason is None, f"同 batch 不应有拒搬 reason，got {reason}"


class TestOutputsDeliveredGranularity:
    """M14（review 整改）：聚合字段「已交付」降粒度。

    provides=['tiling_results'] 按模板聚合——批 RESUME 部分交付时（base 已有
    兄弟模板）dict 非 None，裸 has_all 恒真会让 runner 的错误归一化 /
    artifact-retry 预算 / 终态分类静默失效。交付语义=本模板必需段在位。"""

    _SEG = {"split": {"axis": "N"},
            "buffer_kernel": {"buffer_num": 2},
            "precision_perf": {"compute_dtype": "fp32"}}

    def test_sibling_present_but_own_missing_not_delivered(self):
        from ascendc_devkit.orchestration.stages.design_substages import (
            TilingStage)
        t2 = TilingStage(template={"name": "T2"})
        state = State.empty().with_updates(tiling_results={"T1": dict(self._SEG)})
        assert not t2.outputs_delivered(state), (
            "RESUME 部分交付：兄弟模板在场不得算本模板已交付")

    def test_own_template_complete_delivered(self):
        from ascendc_devkit.orchestration.stages.design_substages import (
            TilingStage)
        t2 = TilingStage(template={"name": "T2"})
        state = State.empty().with_updates(
            tiling_results={"T1": dict(self._SEG), "T2": dict(self._SEG)})
        assert t2.outputs_delivered(state)

    def test_aggregated_dict_nonempty_but_own_missing_not_delivered(self):
        # 正是旧 has_all 误判的形态：字段非 None 即「已交付」
        from ascendc_devkit.orchestration.stages.design_substages import (
            TilingStage)
        t2 = TilingStage(template={"name": "T2"})
        state = State.empty().with_updates(tiling_results={"T1": {}})
        assert state.has_all(["tiling_results"])  # 旧判据在此形态下恒真
        assert not t2.outputs_delivered(state)
