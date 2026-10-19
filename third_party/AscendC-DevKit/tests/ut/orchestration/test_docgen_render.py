"""P36 — DocgenStage spawns the ascendc-op-design-docgen skill to assemble the
《详细设计说明书》 (v2.0 template-faithful). state.design_doc stores the md path
(not content / not a JSON dict). Strict TDD.
"""

import json
import re
from pathlib import Path

import pytest

from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.kernel.action import SpawnAgent
from ascendc_devkit.orchestration.stages.design_substages import (
    DocgenStage, _opdef_missing_canonical_anchors)


def _seed_contract(wd, state):
    (wd / "design_spec.json").write_text(
        json.dumps(state.design_spec, ensure_ascii=False))
    (wd / "tiling_strategy.json").write_text(
        json.dumps(state.tiling_strategy, ensure_ascii=False))


def _state():
    return State.empty().with_updates(
        op_name="add",
        design_spec={"op_name": "add", "mutation_mode": "out_of_place",
                     "inputs": [{"name": "x"}], "outputs": [{"name": "y"}]},
        tiling_strategy={"approach": "single_core"},
        tiling_results={"T1": {"buffer_kernel": {}}},
        general_design={"op_name": "add"})


class TestActionsSpawnSkill:
    """P36: docgen is no longer a deterministic render — it spawns the docgen
    skill (wired via STAGE_SKILL_MAP), using the generator role agent."""

    def test_actions_emits_spawn(self):
        actions = DocgenStage().actions(_state(), iteration=1)
        spawns = [a for a in actions if isinstance(a, SpawnAgent)]
        assert len(spawns) == 1

    def test_spawn_carries_docgen_skill(self):
        actions = DocgenStage().actions(_state(), iteration=1)
        spawn = next(a for a in actions if isinstance(a, SpawnAgent))
        # docgen skill leads the allowlist (no tail-call — docgen is an
        # independent stage; the facade was removed, §2.5).
        assert "ascendc-op-design-docgen" in spawn.skills

    def test_agent_is_generator(self):
        actions = DocgenStage().actions(_state(), iteration=1)
        spawn = next(a for a in actions if isinstance(a, SpawnAgent))
        assert spawn.agent_name == "ascendc-design-generator"


class TestTransitionReadsMdPath:
    """P36: transition locates the <op>_详细设计说明书.md the skill produced in
    its working_dir and stores the PATH in state.design_doc."""

    def test_design_doc_stores_md_path(self, tmp_path):
        wd = tmp_path / "design" / "docgen"
        wd.mkdir(parents=True)
        md = wd / "add_详细设计说明书.md"
        md.write_text("# add 详细设计说明书\n...")
        _seed_contract(wd, _state())
        out = DocgenStage().transition(_state(), {"_working_dir": str(wd)})
        assert out.design_doc == str(md)
        assert out.last_error is None

    def test_missing_md_records_error_for_halt(self, tmp_path):
        # fail_strategy="halt" (inherited): a missing doc → last_error → halt,
        # not a silent empty/bad doc (§1.2 可诊断).
        wd = tmp_path / "design" / "docgen"
        wd.mkdir(parents=True)
        _seed_contract(wd, _state())
        out = DocgenStage().transition(_state(), {"_working_dir": str(wd)})
        assert out.design_doc is None
        assert out.last_error is not None
        # 方案 C：user_feedback 含 skill 提示（「可能某 skill 未能正确调用和执行」），
        # 不武断断言「未调用」——下一轮 prompt 注入让 agent 定向补齐（docs/plan/
        # synthesize-docgen-dilution/）。
        assert out.user_feedback
        assert "可能" in out.user_feedback
        assert "skill" in out.user_feedback


class TestTransitionAcceptsAnyFilename:
    """P6 fix: the design doc is a human-facing deliverable no downstream stage
    reads (validate/codegen ignore it), so the exact filename is NOT a contract.
    transition accepts ANY ``*_详细设计说明书.md`` the skill produced; only the
    total absence of one halts. Cures the PascalCase-vs-snake_name mismatch
    (design_spec.op_name is non-deterministically Pascal; the skill reliably
    writes snake) that halted cross_entropy_loss / dynamic_quant every run."""

    def _state_cel(self):
        # Reproduce the failing op: snake dir name + Pascal design_spec.op_name
        # (exactly the cross_entropy_loss / dynamic_quant condition).
        return State.empty().with_updates(
            op_name="cross_entropy_loss",
            design_spec={"op_name": "CrossEntropyLoss", "mutation_mode": "out_of_place",
                         "inputs": [{"name": "x"}], "outputs": [{"name": "y"}]},
            tiling_strategy={"approach": "single_core"},
            general_design={"op_name": "CrossEntropyLoss"})

    def test_accepts_snake_md_when_design_spec_is_pascal(self, tmp_path):
        # The skill writes snake even though design_spec.op_name is Pascal.
        wd = tmp_path / "design" / "docgen"
        wd.mkdir(parents=True)
        (wd / "cross_entropy_loss_详细设计说明书.md").write_text("# doc\n")
        _seed_contract(wd, self._state_cel())
        out = DocgenStage().transition(self._state_cel(), {"_working_dir": str(wd)})
        assert out.last_error is None
        assert out.design_doc is not None
        assert out.design_doc.endswith("cross_entropy_loss_详细设计说明书.md")

    def test_accepts_pascal_md(self, tmp_path):
        wd = tmp_path / "design" / "docgen"
        wd.mkdir(parents=True)
        (wd / "CrossEntropyLoss_详细设计说明书.md").write_text("# doc\n")
        _seed_contract(wd, self._state_cel())
        out = DocgenStage().transition(self._state_cel(), {"_working_dir": str(wd)})
        assert out.last_error is None
        assert out.design_doc is not None

    def test_accepts_arbitrary_prefix_md(self, tmp_path):
        wd = tmp_path / "design" / "docgen"
        wd.mkdir(parents=True)
        (wd / "foo_详细设计说明书.md").write_text("# doc\n")
        _seed_contract(wd, self._state_cel())
        out = DocgenStage().transition(self._state_cel(), {"_working_dir": str(wd)})
        assert out.last_error is None
        assert out.design_doc is not None

    def test_prefers_op_name_match_when_multiple(self, tmp_path):
        # If the skill (or a prior run) left two docs, prefer the canonical
        # state.op_name one; either way do NOT halt (both are valid docs).
        wd = tmp_path / "design" / "docgen"
        wd.mkdir(parents=True)
        (wd / "CrossEntropyLoss_详细设计说明书.md").write_text("# pascal\n")
        (wd / "cross_entropy_loss_详细设计说明书.md").write_text("# snake\n")
        _seed_contract(wd, self._state_cel())
        out = DocgenStage().transition(self._state_cel(), {"_working_dir": str(wd)})
        assert out.last_error is None
        assert out.design_doc.endswith("cross_entropy_loss_详细设计说明书.md")

    def test_unrelated_md_only_does_not_match(self, tmp_path):
        # A stray .md without the _详细设计说明书 suffix is not the design doc.
        wd = tmp_path / "design" / "docgen"
        wd.mkdir(parents=True)
        (wd / "notes.md").write_text("# notes\n")
        _seed_contract(wd, self._state_cel())
        out = DocgenStage().transition(self._state_cel(), {"_working_dir": str(wd)})
        assert out.last_error is not None
        assert out.design_doc is None


class TestDeterministicRenderRemoved:
    """P36: the deterministic render path is gone — docgen is LLM-driven now.
    Mermaid / section assembly / pseudocode loading all live in the skill."""

    def test_no_render_detailed(self):
        assert not hasattr(DocgenStage, "_render_detailed")

    def test_no_render_concept(self):
        assert not hasattr(DocgenStage, "_render_concept")

    def test_no_persist_markdown(self):
        assert not hasattr(DocgenStage, "_persist_markdown")

    def test_no_skip_reason(self):
        # No longer a deterministic no-op: actions() spawns, so skip_reason
        # must not short-circuit it as "deterministic_render".
        assert DocgenStage().skip_reason(_state()) is None


class TestOpDefCanonicalGate:
    """Hard gate (last-resort, §1.2): docgen 详设文档不编译，无天然硬门（不像 codegen
    def.cpp 有编译兜底）。transition 用**正向锚点**断言渲染出的 OpDef 是 canonical 的
    （builder 链 + 每 IO 按名 Input/Output + 真 soc 字面量），缺任一即 halt 交人，防虚构 OpDef
    静默流到人审（run 20260722-022209-e08f46 的回归）。正向锚点天然覆盖原地（同名 IO 两侧都查）。
    门只作用在**围栏代码块**内——prose-only 文档（路径/命名 UT 用）自然跳过，不误伤。"""

    @staticmethod
    def _write_doc(wd, body):
        md = wd / "add_详细设计说明书.md"
        md.write_text(body, encoding="utf-8")
        return md

    # Canonical add OpDef (matches _state(): inputs=[x], outputs=[y]) in a cpp fence.
    _CANONICAL = (
        "## 2.3 算子信息库\n```cpp\n"
        "namespace ops { class Add : public OpDef { public:\n"
        "explicit Add(const char *name) : OpDef(name) {\n"
        'this->Input("x").ParamType(REQUIRED).DataType({ge::DT_FLOAT16})'
        ".Format({ge::FORMAT_ND}).UnknownShapeFormat({ge::FORMAT_ND}).AutoContiguous();\n"
        'this->Output("y").ParamType(REQUIRED).DataType({ge::DT_FLOAT16})'
        ".Format({ge::FORMAT_ND}).UnknownShapeFormat({ge::FORMAT_ND}).AutoContiguous();\n"
        'this->Attr("mode").Int(0);\n'
        'OpAICoreConfig cfg; this->AICore().AddConfig("ascend910b", cfg);\n'
        "}}; OP_ADD(Add); }\n```\n")

    def test_canonical_opdef_passes(self, tmp_path):
        wd = tmp_path / "design" / "docgen"
        wd.mkdir(parents=True)
        self._write_doc(wd, self._CANONICAL)
        _seed_contract(wd, _state())
        out = DocgenStage().transition(_state(), {"_working_dir": str(wd)})
        assert out.last_error is None
        assert out.design_doc is not None

    def test_hallucinated_opdef_records_known_issue(self, tmp_path):
        # The regression: a fictional OpDef (no real builder chain, placeholder
        # soc) lacks the positive anchors. A (fail-forward): it records a
        # NON-BLOCKING known_issue (surfaces in codegen prompt + human review)
        # instead of halting — the doc is a presentation artifact; codegen's
        # def.cpp compile is the authoritative OpDef backstop. cpp fence (realistic).
        wd = tmp_path / "design" / "docgen"
        wd.mkdir(parents=True)
        self._write_doc(wd, (
            "## 2.3 算子信息库\n```cpp\nclass Exp : public OpDef {\n"
            'auto &x = desc.MutatableInputDesc("x");\n'
            "desc.OutputAttrMapping(&y, {0});\n"
            "desc.Attr(\"base\", ge::DT_FLOAT, ScalarValueType::SINGLE_FLOAT, -1.0f);\n"
            "this->AICore().AddConfig(<SOC_VERSION_FROM_CHIP_TRANSLATION>);\n}\n```"))
        _seed_contract(wd, _state())
        out = DocgenStage().transition(_state(), {"_working_dir": str(wd)})
        assert out.last_error is None  # not halted
        assert out.design_doc is not None  # doc still produced
        assert out.design_known_issues  # recorded as non-blocking
        assert any("缺正向锚点" in i.get("detail", "")
                   for i in out.design_known_issues)

    @pytest.mark.parametrize("drop,needle", [
        ("op_add", "OP_ADD("),
        ("input", 'Input("x")'),
        ("output", 'Output("y")'),
        ("paramtype", ".ParamType("),
        ("soc", "ascend910b"),
    ])
    def test_missing_each_anchor_records_known_issue(self, tmp_path, drop, needle):
        # Positive gate: remove a canonical anchor (ALL occurrences — structural
        # anchors like .ParamType(/.DataType( appear once per IO) → recorded as a
        # non-blocking known_issue (A: fail-forward, NOT halt).
        wd = tmp_path / "design" / "docgen"
        wd.mkdir(parents=True)
        body = self._CANONICAL.replace(needle, "/*anchor-removed*/")
        self._write_doc(wd, body)
        _seed_contract(wd, _state())
        out = DocgenStage().transition(_state(), {"_working_dir": str(wd)})
        assert out.last_error is None, f"移除锚点 {drop!r}({needle!r}) 不应 halt"
        assert out.design_doc is not None  # doc still produced
        assert out.design_known_issues, f"移除锚点 {drop!r}({needle!r}) 应记 known_issue"

    def test_placeholder_soc_records_known_issue(self, tmp_path):
        # The <占位> bug: all other anchors present, but AddConfig has a placeholder
        # instead of a real soc literal → missing the real-soc anchor → non-blocking
        # known_issue (A: fail-forward, NOT halt).
        wd = tmp_path / "design" / "docgen"
        wd.mkdir(parents=True)
        body = self._CANONICAL.replace(
            "ascend910b", "<SOC_VERSION_FROM_CHIP_TRANSLATION>", 1)
        self._write_doc(wd, body)
        _seed_contract(wd, _state())
        out = DocgenStage().transition(_state(), {"_working_dir": str(wd)})
        assert out.last_error is None
        assert out.design_doc is not None
        assert any("<real soc_version literal>" in i.get("detail", "")
                   for i in out.design_known_issues)

    def test_inplace_op_requires_both_declarations(self, tmp_path):
        # In-place: key_cache in BOTH inputs and outputs. The per-name anchors check
        # each side independently, so omitting the Output declaration → halt (the
        # OpDef would lose the write-back alias). Both declared → pass.
        st = State.empty().with_updates(
            op_name="scatter",
            design_spec={"op_name": "scatter", "mutation_mode": "in_place",
                         "inputs": [{"name": "key_cache"}],
                         "outputs": [{"name": "key_cache"}]},  # same name both sides
            tiling_strategy={"approach": "single_core"})
        wd = tmp_path / "design" / "docgen"
        wd.mkdir(parents=True)
        both = (
            "## 2.3\n"
            "```cpp\n"
            'this->Input("key_cache").ParamType(REQUIRED).DataType({ge::DT_FLOAT16});\n'
            'this->Output("key_cache").ParamType(REQUIRED).DataType({ge::DT_FLOAT16});\n'
            'this->AICore().AddConfig("ascend950");\n'
            "OP_ADD(Scatter);\n"
            "```\n")
        self._write_doc(wd, both)
        _seed_contract(wd, st)
        assert DocgenStage().transition(st, {"_working_dir": str(wd)}).last_error is None
        # Drop the Output declaration → the in-place alias is broken → recorded
        # as a non-blocking known_issue (A: fail-forward, not halt).
        wd2 = tmp_path / "design" / "docgen2"
        wd2.mkdir(parents=True)
        output_line = (
            'this->Output("key_cache")'
            ".ParamType(REQUIRED).DataType({ge::DT_FLOAT16});\n")
        self._write_doc(wd2, both.replace(output_line, ""))
        _seed_contract(wd2, st)
        out = DocgenStage().transition(st, {"_working_dir": str(wd2)})
        assert out.last_error is None  # not halted
        assert any('Output("key_cache")' in i.get("detail", "")
                   for i in out.design_known_issues)

    def test_prose_only_doc_skips_gate(self, tmp_path):
        # The gate is scoped to fenced CODE; a prose-only doc (no cpp block) has
        # nothing to validate → skip (no false halt). A wholly missing §2.3 is the
        # agent self-check's concern, not this hallucination backstop's.
        wd = tmp_path / "design" / "docgen"
        wd.mkdir(parents=True)
        self._write_doc(wd, "# add 详细设计说明书\n（纯文字，无代码块）\n")
        _seed_contract(wd, _state())
        out = DocgenStage().transition(_state(), {"_working_dir": str(wd)})
        assert out.last_error is None
        assert out.design_doc is not None

    # —— D: gate input-form coverage (scalar→Attr, attrs section) ——
    def test_scalar_input_expects_attr_not_input(self):
        # 51d915 root: a scalar in inputs (shape:[], SCALAR) must expect
        # Attr("<name>"), not Input("<name>") — a correct Attr render passes; a
        # wrong Input render reports Attr("epsilon") (not Input("epsilon")).
        spec = {"inputs": [{"name": "epsilon", "shape": [], "format": "SCALAR"}],
                "outputs": []}
        ok = 'Attr("epsilon") OP_ADD( AddConfig( .ParamType( .DataType( ascend910b'
        assert _opdef_missing_canonical_anchors(ok, spec) == []
        wrong = ok.replace('Attr("epsilon")', 'Input("epsilon")')
        missing = _opdef_missing_canonical_anchors(wrong, spec)
        assert 'Attr("epsilon")' in missing
        assert 'Input("epsilon")' not in missing

    def test_attrs_list_requires_attr_anchor(self):
        spec = {"inputs": [{"name": "x", "shape": ["N"]}],
                "outputs": [{"name": "y", "shape": ["N"]}],
                "attrs": [{"name": "mode", "type": "int"},
                          {"name": "eps", "type": "float"}]}
        ok = ('Input("x") Output("y") Attr("mode") Attr("eps") '
              'OP_ADD( AddConfig( .ParamType( .DataType( ascend910b')
        assert _opdef_missing_canonical_anchors(ok, spec) == []
        missing = _opdef_missing_canonical_anchors(ok.replace('Attr("eps")', ''), spec)
        assert 'Attr("eps")' in missing

    def test_attrs_dict_form_checked(self):
        # attrs as dict {name: {...}} — gate reads names from both list & dict.
        spec = {"inputs": [], "outputs": [],
                "attrs": {"cache_mode": {"type": "string"}}}
        code = 'OP_ADD( AddConfig( .ParamType( .DataType( ascend910b'
        assert 'Attr("cache_mode")' in _opdef_missing_canonical_anchors(code, spec)

    def test_known_issue_does_not_clobber_other_sources(self, tmp_path):
        # A: design_known_issues partitioned by source — a prior gate's carried
        # issue survives docgen recording its own (mirrors _set_known_issues).
        prior = [{"code": "other", "source": "validate", "detail": "x"}]
        st = _state().with_updates(design_known_issues=prior)
        wd = tmp_path / "design" / "docgen"
        wd.mkdir(parents=True)
        self._write_doc(wd, self._CANONICAL.replace("OP_ADD(", "/*x*/"))
        _seed_contract(wd, st)
        out = DocgenStage().transition(st, {"_working_dir": str(wd)})
        sources = [i.get("source") for i in out.design_known_issues]
        assert "validate" in sources and "docgen" in sources


class TestDocgenTemplateTilingDataStruct:
    """TDR1 回归守护：docgen 模板 `TilingData设计` 章节的代码块占位必须是
    plain C struct，不是 CANN 旧宏（BEGIN_TILING_DATA_DEF ...）占位。

    docgen 是 LLM 驱动（见 TestDeterministicRenderRemoved），渲染内容靠 heavy ST
    验证；此处仅确定性守护"模板静态契约"——占位形态不得回退为将废弃的旧宏
    （旧宏占位是 swi_glu docgen 渲染旧宏的污染源头，详见
    docs/plan/design-tilingdata-struct-render/01-problems.md D）。
    """

    _TPL = (Path(__file__).resolve().parents[3]
            / ".claude" / "skills" / "ascendc-op-design-docgen"
            / "references" / "doc_template_v2.0.md")

    def test_tilingdata_placeholder_is_struct(self):
        text = self._TPL.read_text(encoding="utf-8")
        # 容错定位 TilingData设计 章节（按节标题关键字，不硬绑节号 4.x.2.1）
        m = re.search(r"TilingData设计(.*?)(?:^#### |^### |\Z)",
                      text, re.S | re.M)
        assert m, "docgen 模板未找到 TilingData设计 章节"
        code = re.search(r"```cpp\n(.*?)```", m.group(1), re.S)
        assert code, "TilingData设计 章节无 cpp 代码块占位"
        body = code.group(1)
        assert "struct " in body, "TilingData 占位必须是 plain C struct（POD）"
        # 占位首行不得是旧宏外壳（精确判占位形态，不误伤 struct 内的禁用说明注释）
        first_nonblank = next((ln for ln in body.splitlines() if ln.strip()), "")
        assert not first_nonblank.lstrip().startswith("BEGIN_TILING_DATA_DEF"), (
            "TilingData 占位不得回退为 BEGIN_TILING_DATA_DEF 旧宏（将废弃写法）")
