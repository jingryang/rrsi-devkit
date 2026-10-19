"""step-105 — 防线 2/3（requirement / test_design 产出期自检）UT。

钉住 docs/plan/op-attr-type-system/（L3 决策②四层防线）：
- 防线 2（requirement 自检）：a) 类型标签文法可表达性——不可翻译标签 →
  schema_violation（响亮，带三选一处置指引）；b) 与 golden 用例值结构
  cross-check——只拦矛盾不拦细化（红线 2）。
- 防线 3（test_design 自检）：用例 attrs 对 op_spec 契约过递归检查器；
  失败 = 自身产物验收不过，报"用例↔契约不一致"（不自修，冲突以 golden
  为准上报）。

回归锚（20260829 interpolate 事故）：分歧暴露点从 codegen 尾段（3h 后）
前移到两个产出当下（分钟级）。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from types import SimpleNamespace

from ascendc_devkit.domain.operator import AttrSpec, OperatorSpec


# ── 防线 2：requirement._validate_attr_type_grammar ────────────────────────


def _stage():
    from ascendc_devkit.orchestration.stages.requirement import RequirementStage
    return RequirementStage()


class TestRequirementAttrTypeGrammar:
    def _call(self, req_data, proto_path=None):
        return _stage()._validate_attr_type_grammar(req_data, proto_path)

    def test_grammar_types_pass(self):
        errs = self._call({"attrs": [
            {"name": "pools", "type": "int[][]"},      # 事故算子的正确声明
            {"name": "mode", "type": "str"},
            {"name": "k", "type": "int[2]"},
            {"name": "s", "type": "Scalar"},
        ]})
        assert errs == []

    def test_untranslatable_label_is_loud(self):
        """不可翻译标签 → 响亮报错 + 三选一处置指引（红线：禁静默改写）。"""
        errs = self._call({"attrs": [{"name": "x", "type": "WeirdType"}]})
        assert len(errs) == 1
        assert "无法解析为类型文法" in errs[0]
        assert "禁止为迁就类型系统发明编码变换" in errs[0]

    def test_incident_form_flat_vs_nested_sample(self):
        """事故正向锚：声明压平 list[int] vs golden 样例嵌套 [[1,1]] → 矛盾被拦。"""
        errs = self._call({"attrs": [{"name": "pools", "type": "list[int]"}]})
        assert errs == []  # 无样例时只查文法（a 项）——样例缺失不算错
        # 有样例（cases.yaml 在 proto 同目录）→ 矛盾拦截
        errs = self._call({"attrs": [{"name": "pools", "type": "list[int]"}]},
                          proto_path="tests/fixtures/attrtype/proto.yaml")
        assert any("与 golden 用例值结构矛盾" in e for e in errs)

    def test_refinement_not_conflict(self):
        """红线 2：细化通过——声明 list[list[int]]，样例嵌套值兼容。"""
        errs = self._call({"attrs": [{"name": "pools", "type": "int[][]"}]},
                          proto_path="tests/fixtures/attrtype/proto.yaml")
        assert errs == []

    def test_no_attrs_no_op(self):
        assert self._call({"attrs": []}) == []
        assert self._call({}) == []
        assert self._call({"attrs": "not-a-list"}) == []


# ── 防线 3：test_design casegen._validate_cases_against_spec ───────────────


def _tc(attrs):
    from types import SimpleNamespace
    return SimpleNamespace(name="c", inputs=[{"shape": [4], "dtype": "fp16"}],
                           attrs=attrs, expected={})


class TestCasegenContractCheck:
    def _call(self, state, cases):
        from ascendc_devkit.orchestration.stages.test_design_substages import (
            _TestDesignSubstage)
        return _TestDesignSubstage._validate_cases_against_spec(state, cases)

    def _state_with_spec(self, spec):
        return SimpleNamespace(
            op_identity=SimpleNamespace(spec=spec), requirement=None)

    def test_nested_contract_and_value_pass(self):
        spec = OperatorSpec(name="t", attrs={
            "pools": AttrSpec(name="pools", type="int[][]")})
        state = self._state_with_spec(spec)
        assert self._call(state, [_tc({"pools": [[1, 1], [2, 2]]})]) is None

    def test_incident_form_halted_at_test_design(self):
        """事故回归锚：契约压平 list[int] + 用例嵌套 [[1,1]] → **test_design
        产出当下**即拦（原系统 3 小时后才在 smoke 联合点爆）。"""
        spec = OperatorSpec(name="t", attrs={
            "pools": AttrSpec(name="pools", type="list[int]")})
        state = self._state_with_spec(spec)
        err = self._call(state, [_tc({"pools": [[1, 1]]})])
        assert err is not None
        assert "用例↔契约不一致" in err
        assert "以 golden 为准" in err

    def test_fixed_length_enforced(self):
        spec = OperatorSpec(name="t", attrs={
            "k": AttrSpec(name="k", type="int[2]")})
        state = self._state_with_spec(spec)
        assert self._call(state, [_tc({"k": [1, 2]})]) is None
        err = self._call(state, [_tc({"k": [1, 2, 3]})])
        assert err is not None and "fixed length" in err

    def test_no_spec_or_no_attrs_no_op(self):
        assert self._call(SimpleNamespace(op_identity=None, requirement=None),
                          [_tc({"a": 1})]) is None
        spec = OperatorSpec(name="t")  # 无 attrs 声明
        assert self._call(self._state_with_spec(spec), [_tc({"a": 1})]) is None

    def test_passthrough_label_falls_back_generic(self):
        """契约透传标签（Tensor）→ 泛化 fallback（遗留行为），标量值不误拦。"""
        spec = OperatorSpec(name="t", attrs={
            "z": AttrSpec(name="z", type="Tensor")})
        state = self._state_with_spec(spec)
        assert self._call(state, [_tc({"z": 5})]) is None
