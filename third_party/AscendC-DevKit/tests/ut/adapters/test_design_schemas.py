"""P1 (step-2b / step-10) — design substage schemas load + self-validate.

相1: schemas load from each producing skill's flat schema/ subdirectory
(.claude/skills/<skill>/schema/), keyed by bare skill name (first principle #3).
"""

import pytest
from pathlib import Path
from ascendc_devkit.adapters.schema.loader import SchemaLoader, SchemaNotFoundError
from ascendc_devkit.orchestration.stages.design_substages import _TILING_SEGMENTS

# schema filename → producing skill (1:1; intake reads integrate's schemas)
_SCHEMA_SKILL_MAP = {
    "general_design.json":            "ascendc-op-general-design",
    "template_division.json":         "ascendc-op-design-template-division",
    "tiling_split.json":              "ascendc-op-tiling-split",
    "tiling_buffer_kernel.json":      "ascendc-op-tiling-buffer-kernel",
    "tiling_precision_perf.json":     "ascendc-op-tiling-precision-perf",
    # P36: design_doc.json schema removed — docgen emits <op>_详细设计说明书.md
    # (a markdown doc, no JSON schema); state.design_doc stores its path.
    # multi-schema (integrate produces, intake reads via same path)
    "design_spec.json":               "ascendc-op-design-integrate",
    "tiling_strategy.json":           "ascendc-op-design-integrate",
    "kernel_architecture.json":       "ascendc-op-design-integrate",
    "data_flow.json":                 "ascendc-op-design-integrate",
}

_DESIGN_SCHEMAS = list(_SCHEMA_SKILL_MAP.keys())

def _load_spec(fn):
    """Load design schema from its producing skill directory."""
    return SchemaLoader.load_spec_from_skill(_SCHEMA_SKILL_MAP[fn], fn)


class TestLoadDesignSchemas:
    @pytest.mark.parametrize("fn", _DESIGN_SCHEMAS)
    def test_loads(self, fn):
        spec = _load_spec(fn)
        assert spec.kind == "spec"
        assert spec.filename == fn

    @pytest.mark.parametrize("fn", _DESIGN_SCHEMAS)
    def test_example_satisfies_own_schema(self, fn):
        spec = _load_spec(fn)
        assert spec.validate_payload(spec.example) == []


class TestRequiredKeysEnforced:
    def test_general_design_missing_key_fails(self):
        spec = _load_spec("general_design.json")
        errors = spec.validate_payload({"op_name": "x"})  # missing flattened CR1 fields
        assert any("split_axis_priority" in e for e in errors)

    def test_template_division_missing_key_fails(self):
        spec = _load_spec("template_division.json")
        errors = spec.validate_payload({"templates": []})  # missing locked_decisions
        assert any("locked_decisions" in e for e in errors)


class TestContractOrder:
    def test_tiling_contract_order_preserved(self):
        # Each tiling schema lives in its own producing skill directory.
        specs = [_load_spec(fn) for fn in (
            "tiling_split.json", "tiling_buffer_kernel.json", "tiling_precision_perf.json")]
        assert [s.name for s in specs] == [
            "tiling_split", "tiling_buffer_kernel", "tiling_precision_perf"]


# —— 方案 S ([[P100]] / 方案73): tiling 段 schema 闭合 + 内容重构 ——
#
# design_substages.py:2050 的段聚合 `tmpl_entry[segment_key]=payload.get(segment_key)`
# 只搬 segment 内层对象，丢顶层兄弟。历史 bug：producer 按 schema 把 gate-relevant
# 设计内容（verifiable_claims 等）产成顶层兄弟 → 聚合丢弃 → 消费门（anchor AC0/
# validate GV9-a）永远看不到 → AC0 死循环（run 20260724-045259-898837）。
#
# 方案 S 双路径结构性消除复发：
#   (a) 内容重构——gate-relevant 设计内容（verifiable_claims / key_parameters /
#       kernel_structure）进 segment 内层 → 聚合天然带过（构造性保证，§2.9）。
#   (b) schema 闭合——ArtifactSpec.allowed_top_level_keys 拒未知顶层键 → 未来
#       任何新孤儿字段在 producer 边界（transition 读产物时）即被拒（§1.3），
#       根本到不了 :2050/下游门。顶层只剩纯簿记/过程元数据（非 gate-visible）。
#
# 下列 UT-A 是"类"守护：遍历 TilingStage 的全部 4 个 tiling 段 schema（不硬编码
# 逻辑，schema 声明驱动）。段清单以 design_substages._TILING_SEGMENTS 为唯一权威
# （(sub_skill, schema_file, segment_key, required)），未来加新段/新字段只要走该
# 声明即自动覆盖；agent 私加顶层字段则被 A3 在 validate_payload 拒。

# (producing_skill, schema_file, segment_key) derived from _TILING_SEGMENTS.
_SEGMENT_SCHEMAS = [
    (skill, fn, seg) for skill, fn, seg, _req in _TILING_SEGMENTS
]

# 顶层允许的"非 gate-visible"字段：纯簿记（template 标识 / step / status /
# decisions 另有 decision_logs 通路 / external_verification）+ 过程元数据
# （self_check_summary，对质原则门不读，详 73-...-analysis.md §8）。gate-relevant
# 设计内容（verifiable_claims / key_parameters / kernel_structure）不得在此——
# 它们必须进 segment 内层才能随 :2050 流向门。
_BOOKKEEPING = {"template", "step", "status", "decisions",
                "external_verification", "self_check_summary"}


class TestTilingSegmentSchemaClosure:
    """UT-A: 4 个 tiling 段 schema 的闭合 + 白名单不变式（方案 S）。"""

    @pytest.mark.parametrize("skill,fn,seg", _SEGMENT_SCHEMAS)
    def test_a1_segment_schema_is_closed(self, skill, fn, seg):
        # A1 闭合性：每段 schema 必声明 allowed_top_level_keys（非空=已闭合）。
        spec = SchemaLoader.load_spec_from_skill(skill, fn)
        assert spec.allowed_top_level_keys, (
            f"{fn}: must declare allowed_top_level_keys (方案 S 闭合)；"
            "开放 schema 下顶层兄弟会被 :2050 聚合丢弃（[[P100]] 死循环根因）")

    @pytest.mark.parametrize("skill,fn,seg", _SEGMENT_SCHEMAS)
    def test_a2_allowed_set_is_segment_plus_bookkeeping_only(self, skill, fn, seg):
        # A2 白名单纯洁性：allowed = {segment} ∪ 纯簿记/过程元数据。任一 gate-relevant
        # 设计字段（verifiable_claims / key_parameters / kernel_structure）若被准入顶层 →
        # 聚合丢弃 → 同型复发。这条直接守住院 P100 类 bug 的复发面。
        spec = SchemaLoader.load_spec_from_skill(skill, fn)
        allowed = set(spec.allowed_top_level_keys)
        assert seg in allowed, f"{fn}: segment key '{seg}' must be in allowed set"
        gate_relevant = {"verifiable_claims", "key_parameters", "kernel_structure"}
        leaked = allowed & gate_relevant
        assert not leaked, (
            f"{fn}: gate-relevant 设计字段 {leaked} 不得在顶层白名单——"
            "它们必须进 segment 内层才能流向消费门（:2050 只搬 segment）")
        extras = allowed - {seg} - _BOOKKEEPING
        assert not extras, (
            f"{fn}: 顶层白名单含未声明的非簿记键 {extras}；"
            "新增顶层字段须先判定其非 gate-visible 并登记进 BOOKKEEPING")

    @pytest.mark.parametrize("skill,fn,seg", _SEGMENT_SCHEMAS)
    def test_a3_validate_rejects_orphan_top_level_design_field(self, skill, fn, seg):
        # A3 闭合机制本身：构造一个带非法顶层键（gate-relevant 设计字段放顶层）的
        # 产物 → validate_payload 必报 unexpected key。守护"agent 私加顶层字段被拒"。
        spec = SchemaLoader.load_spec_from_skill(skill, fn)
        payload = {"template": "T1", seg: {},
                   "verifiable_claims": [{"claim_type": "x"}]}  # 放顶层=孤儿
        errors = spec.validate_payload(payload)
        assert any("unexpected" in e and "verifiable_claims" in e for e in errors), (
            f"{fn}: 孤儿顶层 verifiable_claims 必被拒（方案 S 路径 b 闭合机制）")


# —— sort-implementability-gate 阶段 A：template-division 加可实施性自检（LD4）——
# 源头治理：设计在"锁定计算模板 + 精度策略"时就自检算法可实施性（排序/去重/逆映射/
# 跨 dtype 转换），而不是等 codegen 硬扛（[[batch-20260810]] P2 同根）。判据全用
# 结构信号，禁止耦合算子名（§1.12）。本例只守护 schema 层 + skill 判据存在性。
class TestTemplateDivisionImplementability:
    """守护 template_division schema 的 implementability 字段 + skill 判据。"""

    _SKILL = "ascendc-op-design-template-division"
    _FN = "template_division.json"

    def test_schema_loads_with_implementability(self):
        spec = SchemaLoader.load_spec_from_skill(self._SKILL, self._FN)
        assert spec.kind == "spec"
        # example.locked_decisions 须含 implementability（LD4 可实施性）
        assert "implementability" in spec.example["locked_decisions"]
        impl = spec.example["locked_decisions"]["implementability"]
        # 字段结构：risk ∈ {low, high} + reason + mitigation（结构信号）
        assert impl["risk"] in ("low", "high")
        assert impl["reason"]
        assert "mitigation" in impl

    def test_example_still_satisfies_own_schema(self):
        # 加 implementability 后 example 仍须通过 validate_payload（不破坏现有契约）
        spec = SchemaLoader.load_spec_from_skill(self._SKILL, self._FN)
        assert spec.validate_payload(spec.example) == []

    def test_required_keys_unchanged(self):
        # required_keys 不因加嵌套字段而变（implementability 是 locked_decisions 内嵌）
        spec = SchemaLoader.load_spec_from_skill(self._SKILL, self._FN)
        assert spec.required_keys == ("templates", "locked_decisions")

    def test_skill_md_has_implementability_check(self):
        # skill 自检清单含 implementability（防回退：删了判据会被此测试拦）
        skill_dir = (
            Path(__file__).resolve().parents[3]
            / ".claude" / "skills" / self._SKILL / "SKILL.md"
        )
        content = skill_dir.read_text(encoding="utf-8")
        assert "implementability" in content
        # 判据用结构信号（排序/去重/跨 dtype），禁算子名耦合
        assert "排序/去重/逆映射" in content or "排序" in content
