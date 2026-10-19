"""M2 §2.4: HarnessContractError + _validate_case_form / validate_case_attrs UT.

``validate_case_attrs`` 原为 runner 私有 ``_validate_attrs``（G1 F9 上移域层：
runner pre-flight 与 test_design 自检两消费者共用公开名，编排层不再 import
adapter 私有符号）。
"""

from __future__ import annotations

import pytest

from ascendc_devkit.domain.exceptions import HarnessContractError
from ascendc_devkit.domain.operator import (
    OperatorSpec, TensorSpec, validate_case_attrs)
from ascendc_devkit.adapters.npu.runner import _validate_case_form


# —— test cases ———————————————————————————————————————————————


class _FakeTC:
    """Minimal test-case duck-typed to match what _validate_case_form reads."""

    def __init__(self, inputs=None, attrs=None):
        self.inputs = inputs
        self.attrs = attrs


# —— HarnessContractError ————————————————————————————————————


def test_contract_error_auto_prefix():
    err = HarnessContractError("shape must be list[int]")
    assert str(err).startswith("[PD-CONTRACT]")
    assert "shape must be list[int]" in str(err)


def test_contract_error_no_double_prefix():
    err = HarnessContractError("[PD-CONTRACT] already prefixed")
    assert str(err) == "[PD-CONTRACT] already prefixed"


# —— _validate_case_form —————————————————————————————————————


def test_inputs_none_raises():
    tc = _FakeTC(inputs=None)
    with pytest.raises(HarnessContractError, match="inputs is missing or None"):
        _validate_case_form(tc, 0)


def test_inputs_not_list_raises():
    tc = _FakeTC(inputs="not_a_list")
    with pytest.raises(HarnessContractError, match="must be list/tuple"):
        _validate_case_form(tc, 0)


def test_input_element_not_dict_raises():
    tc = _FakeTC(inputs=["not_a_dict"])
    with pytest.raises(HarnessContractError, match="inputs\\[0\\] must be dict"):
        _validate_case_form(tc, 0)


def test_shape_none_raises():
    tc = _FakeTC(inputs=[{"dtype": "fp16"}])  # no shape key → None
    with pytest.raises(HarnessContractError, match="shape must be list\\[int\\]"):
        _validate_case_form(tc, 0)


def test_shape_not_int_list_raises():
    tc = _FakeTC(inputs=[{"shape": ["eight", 1024]}])
    with pytest.raises(HarnessContractError, match="shape must be list\\[int\\]"):
        _validate_case_form(tc, 0)


def test_shape_string_raises():
    tc = _FakeTC(inputs=[{"shape": "1024"}])
    with pytest.raises(HarnessContractError, match="shape must be list\\[int\\]"):
        _validate_case_form(tc, 0)


def test_valid_single_case_passes():
    tc = _FakeTC(inputs=[{"shape": [8, 1024], "dtype": "fp16"}])
    _validate_case_form(tc, 0)  # no exception


def test_valid_multi_input_passes():
    tc = _FakeTC(inputs=[
        {"shape": [8, 1024], "dtype": "fp16"},
        {"shape": [8, 1024], "dtype": "fp32"},
    ])
    _validate_case_form(tc, 0)


def test_empty_shape_list_passes():
    """Empty shape is valid list[int] (scalar edge case)."""
    tc = _FakeTC(inputs=[{"shape": []}])
    _validate_case_form(tc, 0)


# —— DYNAMIC (Tensor[]) nested shape ——————————————————————————


def test_dynamic_input_accepts_nested_shape():
    """Q3-multi_add: ``param_type=DYNAMIC`` (Tensor[]) input takes
    ``list[list[int]]`` (one inner shape per tensor in the variadic list).
    The harness template already normalizes nested shapes (its
    ``input_shapes=...`` has an ``isinstance(i['shape'][0], list)`` branch);
    this validator was the only holdout rejecting what the harness supports."""
    op = OperatorSpec(name="multi_add",
                      inputs=[TensorSpec(name="x1", param_type="DYNAMIC")])
    tc = _FakeTC(inputs=[{"shape": [[152, 7680]]}])
    _validate_case_form(tc, 0, op)  # no exception


def test_dynamic_input_accepts_multiple_tensors():
    """DYNAMIC input may carry several tensors in the variadic list."""
    op = OperatorSpec(name="multi_add",
                      inputs=[TensorSpec(name="x1", param_type="DYNAMIC")])
    tc = _FakeTC(inputs=[{"shape": [[1, 72], [3, 4]]}])
    _validate_case_form(tc, 0, op)


def test_dynamic_input_rejects_non_int_inner():
    """DYNAMIC inner shape must be all int (symbolic 'N' still rejected)."""
    op = OperatorSpec(name="multi_add",
                      inputs=[TensorSpec(name="x1", param_type="DYNAMIC")])
    tc = _FakeTC(inputs=[{"shape": [[152, "N"]]}])
    with pytest.raises(HarnessContractError, match="list\\[list\\[int\\]\\]"):
        _validate_case_form(tc, 0, op)


def test_is_list_derived_op_spec_accepts_nested_shape():
    """P2 (precision-tensorlist-harness-contract): a requirement-style
    ``is_list=true`` TensorList input derives param_type=DYNAMIC in
    OperatorSpec.from_dict — the runner's DYNAMIC gate must then accept the
    list-of-lists case shape (foreach_norm's halt was the REQUIRED mislabel)."""
    op = OperatorSpec.from_dict({
        "name": "foreach_norm",
        "inputs": [{"name": "x", "shape": ["L", "*"], "is_list": True,
                    "param_type": "REQUIRED"}],
    })
    assert op.inputs[0].param_type == "DYNAMIC"
    tc = _FakeTC(inputs=[{"shape": [[1024, 1024], [1024, 1024]]}])
    _validate_case_form(tc, 0, op)  # no exception


def test_required_reject_nested_shape_hints_param_type():
    """P2 observability: a REQUIRED input given list-of-lists stays rejected
    (§1.13 — the contract violation is surfaced, not swallowed), but the error
    now hints at the likely upstream cause (param_type mislabel) for diagnosis."""
    op = OperatorSpec(name="add",
                      inputs=[TensorSpec(name="x", param_type="REQUIRED")])
    tc = _FakeTC(inputs=[{"shape": [[152, 7680]]}])
    with pytest.raises(HarnessContractError, match="DYNAMIC"):
        _validate_case_form(tc, 0, op)


# —— positional coupling guard (test_cases ⇄ op_spec misalignment) ——————————


def test_input_count_exceeds_op_spec_raises():
    """More test-case inputs than op_spec tensors → positional param_type
    mapping is unreliable (extra entries silently is_dynamic=False). Must fail
    deterministically rather than mis-validate (§1.10/§3.7)."""
    op = OperatorSpec(name="add",
                      inputs=[TensorSpec(name="x", param_type="REQUIRED")])
    tc = _FakeTC(inputs=[{"shape": [8]}, {"shape": [8]}])  # 2 > 1
    with pytest.raises(HarnessContractError, match="exceeds"):
        _validate_case_form(tc, 0, op)


def test_fewer_inputs_than_op_spec_passes():
    """Fewer test-case inputs (a tail OPTIONAL input omitted) is legitimate and
    stays safe under the per-index guard — no misalignment error."""
    op = OperatorSpec(name="add", inputs=[
        TensorSpec(name="x", param_type="REQUIRED"),
        TensorSpec(name="opt", param_type="OPTIONAL"),
    ])
    tc = _FakeTC(inputs=[{"shape": [8]}])  # 1 < 2
    _validate_case_form(tc, 0, op)  # no exception


# —— validate_case_attrs ——————————————————————————————————————————


def test_attrs_none_skips():
    """attrs=None is optional — no validation, no error."""
    tc = _FakeTC(inputs=[{"shape": [8], "dtype": "fp16"}], attrs=None)
    _validate_case_form(tc, 0)  # no exception


def test_attrs_not_dict_raises():
    attrs = "not_a_dict"
    with pytest.raises(HarnessContractError, match="attrs must be dict"):
        validate_case_attrs(attrs, 0)


def test_attrs_empty_dict_passes():
    validate_case_attrs({}, 0)


def test_attrs_valid_scalars_passes():
    validate_case_attrs({"axis": 1, "keepdim": True}, 0)


def test_attrs_bool_as_int_marked_by_spec():
    """With spec declaring axis=int, passing a bool → error."""
    from ascendc_devkit.domain.operator import AttrSpec, OperatorSpec
    op = OperatorSpec(name="test", attrs={"axis": AttrSpec(name="axis", type="int")})
    with pytest.raises(HarnessContractError, match="expected int, got bool"):
        validate_case_attrs({"axis": True}, 0, operator=op)


def test_attrs_int_matches_spec_passes():
    from ascendc_devkit.domain.operator import AttrSpec, OperatorSpec
    op = OperatorSpec(name="test", attrs={"axis": AttrSpec(name="axis", type="int")})
    validate_case_attrs({"axis": 3}, 0, operator=op)  # no exception


def test_attrs_float_matches_spec_passes():
    from ascendc_devkit.domain.operator import AttrSpec, OperatorSpec
    op = OperatorSpec(name="test", attrs={"alpha": AttrSpec(name="alpha", type="float")})
    validate_case_attrs({"alpha": 0.5}, 0, operator=op)  # no exception


def test_attrs_float_int_coercion_passes():
    """int is accepted for float spec (Python interop)."""
    from ascendc_devkit.domain.operator import AttrSpec, OperatorSpec
    op = OperatorSpec(name="test", attrs={"alpha": AttrSpec(name="alpha", type="float")})
    validate_case_attrs({"alpha": 2}, 0, operator=op)  # no exception


def test_attrs_numeric_string_coerced_to_float_spec():
    """Q4 regression: cann-bench fixture epsilon '1e-6' (str, from YAML
    safe_load / cases.csv quoted number) must coerce to float against the
    declared spec, not be rejected by the pre-flight before the harness's own
    _cast_attr runs."""
    from ascendc_devkit.domain.operator import AttrSpec, OperatorSpec
    op = OperatorSpec(name="test", attrs={"epsilon": AttrSpec(name="epsilon", type="float")})
    attrs = {"epsilon": "1e-6"}
    validate_case_attrs(attrs, 0, operator=op)  # no exception
    # coerced in place → flows to harness as float
    assert attrs["epsilon"] == 1e-6
    assert isinstance(attrs["epsilon"], float)


def test_attrs_numeric_string_coerced_to_int_spec():
    """Same coercion for int-typed attrs stored as quoted strings."""
    from ascendc_devkit.domain.operator import AttrSpec, OperatorSpec
    op = OperatorSpec(name="test", attrs={"axis": AttrSpec(name="axis", type="int")})
    attrs = {"axis": "2"}
    validate_case_attrs(attrs, 0, operator=op)
    assert attrs["axis"] == 2
    assert isinstance(attrs["axis"], int)


def test_attrs_numeric_string_coerced_to_union_spec():
    """M4：union 声明**任一分支**为 int/float 即参与 coerce（"int|float"——ATen
    Scalar 的 canonical 形）。"1e-6" 逐分支尝试：int 失败、float 通过。"""
    from ascendc_devkit.domain.operator import AttrSpec, OperatorSpec
    op = OperatorSpec(name="test", attrs={
        "alpha": AttrSpec(name="alpha", type="int|float")})
    attrs = {"alpha": "1e-6"}
    validate_case_attrs(attrs, 0, operator=op)  # no exception
    assert attrs["alpha"] == 1e-6
    assert isinstance(attrs["alpha"], float)
    # int 分支在前、可解析时优先取 int
    attrs2 = {"alpha": "5"}
    validate_case_attrs(attrs2, 0, operator=op)
    assert attrs2["alpha"] == 5 and isinstance(attrs2["alpha"], int)


def test_attrs_numeric_string_coerced_via_scalar_alias():
    """经翻译点到达同一结果：ATen ``Scalar`` 标签 canonicalize 为 int|float，
    引用数值字符串照样 coerce（单点语义与拼写无关）。"""
    from ascendc_devkit.domain.operator import AttrSpec, OperatorSpec
    op = OperatorSpec(name="test", attrs={
        "alpha": AttrSpec(name="alpha", type="Scalar")})
    assert op.attrs["alpha"].type == "int|float"
    attrs = {"alpha": "1e-6"}
    validate_case_attrs(attrs, 0, operator=op)
    assert attrs["alpha"] == 1e-6


def test_attrs_non_numeric_string_for_float_still_raises():
    """A genuinely non-numeric string for a float spec must still be rejected
    (coercion only rescues real numeric strings, not garbage)."""
    from ascendc_devkit.domain.operator import AttrSpec, OperatorSpec
    op = OperatorSpec(name="test", attrs={"epsilon": AttrSpec(name="epsilon", type="float")})
    with pytest.raises(HarnessContractError, match="expected float, got str"):
        validate_case_attrs({"epsilon": "not_a_number"}, 0, operator=op)


def test_attrs_string_spec_keeps_numeric_string():
    """A str-typed attr whose value looks numeric must NOT be coerced —
    coercion is gated on the declared spec being int/float."""
    from ascendc_devkit.domain.operator import AttrSpec, OperatorSpec
    op = OperatorSpec(name="test", attrs={"tag": AttrSpec(name="tag", type="str")})
    attrs = {"tag": "1e-6"}
    validate_case_attrs(attrs, 0, operator=op)
    assert attrs["tag"] == "1e-6"  # unchanged, still str


def test_attrs_str_matches_spec_passes():
    from ascendc_devkit.domain.operator import AttrSpec, OperatorSpec
    op = OperatorSpec(name="test", attrs={"mode": AttrSpec(name="mode", type="str")})
    validate_case_attrs({"mode": "NHWC"}, 0, operator=op)  # no exception


def test_attrs_list_int_matches_spec_passes():
    from ascendc_devkit.domain.operator import AttrSpec, OperatorSpec
    op = OperatorSpec(name="test", attrs={"ksize": AttrSpec(name="ksize", type="list[int]")})
    validate_case_attrs({"ksize": [3, 3]}, 0, operator=op)  # no exception


def test_attrs_list_int_bool_element_rejected():
    from ascendc_devkit.domain.operator import AttrSpec, OperatorSpec
    op = OperatorSpec(name="test", attrs={"ksize": AttrSpec(name="ksize", type="list[int]")})
    with pytest.raises(HarnessContractError, match="expected list\\[int\\]"):
        validate_case_attrs({"ksize": [True, 3]}, 0, operator=op)


def test_attrs_bool_matches_spec_passes():
    from ascendc_devkit.domain.operator import AttrSpec, OperatorSpec
    op = OperatorSpec(name="test", attrs={"keepdim": AttrSpec(name="keepdim", type="bool")})
    validate_case_attrs({"keepdim": True}, 0, operator=op)  # no exception


def test_attrs_bool_spec_rejects_int():
    from ascendc_devkit.domain.operator import AttrSpec, OperatorSpec
    op = OperatorSpec(name="test", attrs={"keepdim": AttrSpec(name="keepdim", type="bool")})
    with pytest.raises(HarnessContractError, match="expected bool, got int"):
        validate_case_attrs({"keepdim": 1}, 0, operator=op)


def test_attrs_unsupported_type_raises():
    attrs = {"bad": object()}
    with pytest.raises(HarnessContractError, match="unsupported type"):
        validate_case_attrs(attrs, 0)


# —— validate_case_attrs: Optional / nullable attrs (P1) ——————————————
# Regression: run 20260805-152456-0762df resize_bilinear — harness aborted at
# schema validation with "[PD-CONTRACT] output_size has unsupported type
# NoneType" because output_size=null (scale_factor-path case) was rejected.
# golden declares output_size / scale_factor as Optional[List[...]] = None,
# mutually exclusive; None is the legitimate "use default / not provided".


def test_attrs_none_accepted_when_default_is_none():
    """Optional attr (golden Optional[X]=None → spec default:null): a case value
    of None is the declared default — must be accepted, not rejected."""
    from ascendc_devkit.domain.operator import AttrSpec, OperatorSpec
    op = OperatorSpec(name="t", attrs={
        "output_size": AttrSpec(name="output_size", type="list[int]", default=None)})
    validate_case_attrs({"output_size": None}, 0, operator=op)  # no exception


def test_attrs_none_rejected_when_default_is_non_none():
    """Attr with a concrete default (bool=False): None is not the declared type
    → still rejected (the fix does not blanket-accept None)."""
    from ascendc_devkit.domain.operator import AttrSpec, OperatorSpec
    op = OperatorSpec(name="t", attrs={
        "align_corners": AttrSpec(name="align_corners", type="bool", default=False)})
    with pytest.raises(HarnessContractError):
        validate_case_attrs({"align_corners": None}, 0, operator=op)


def test_attrs_optional_scale_factor_path_case_passes():
    """The full resize_bilinear scale_factor-path case shape (output_size=None +
    scale_factor list + PascalCase types canonicalized) passes validate_case_attrs."""
    from ascendc_devkit.domain.operator import AttrSpec, OperatorSpec
    op = OperatorSpec(name="resize_bilinear", attrs={
        "output_size": AttrSpec(name="output_size", type="ListInt", default=None),
        "align_corners": AttrSpec(name="align_corners", type="bool", default=False),
        "scale_factor": AttrSpec(name="scale_factor", type="ListFloat", default=None),
    })
    validate_case_attrs(
        {"output_size": None, "align_corners": False, "scale_factor": [2.0, 2.0]},
        0, operator=op)  # no exception


# —— Canonical attr-type system (single source: CANON_ATTR_CHECKERS) ———————


def test_canon_attr_checkers_each_type():
    """The dispatch table is the single source of truth for attr-type validity
    (consumed by validate_case_attrs; deploy _SMOKE_ATTR_DEFAULTS keys ⊆ it)."""
    from ascendc_devkit.domain.operator import CANON_ATTR_CHECKERS as C
    assert C["int"](3) and not C["int"](True) and not C["int"](3.0)
    assert C["float"](3) and C["float"](3.5) and not C["float"](True)
    assert C["str"]("a") and not C["str"](3)
    assert C["bool"](True) and not C["bool"](1)
    assert C["list[int]"]([1, 2]) and not C["list[int]"]([1, True]) and not C["list[int]"]([1.0])
    assert C["list[float]"]([1.0, 2]) and not C["list[float]"](["a"])
    assert all(callable(f) for f in C.values())


@pytest.mark.parametrize("raw,canon", [
    # int family (case / bit-width / C++ suffix)
    ("int", "int"), ("int64", "int"), ("int64_t", "int"), ("Int", "int"),
    ("INT", "int"), ("uint8", "int"), ("int32", "int"),
    # list[int] family (PascalCase / camelCase / brackets)
    ("ListInt", "list[int]"), ("listInt", "list[int]"), ("List[int]", "list[int]"),
    ("List[Int]", "list[int]"), ("ListInt64", "list[int]"), ("int[]", "list[int]"),
    ("list[int]", "list[int]"),
    # float / list[float]
    ("float", "float"), ("double", "float"), ("float32", "float"),
    ("ListFloat", "list[float]"), ("float[]", "list[float]"), ("list[float]", "list[float]"),
    # bool / str families
    ("bool", "bool"), ("BOOL", "bool"),
    ("str", "str"), ("string", "str"), ("String", "str"),
])
def test_attrspec_type_translates_to_canonical(raw, canon):
    from ascendc_devkit.domain.operator import AttrSpec
    assert AttrSpec(name="x", type=raw).type == canon


def test_attrspec_type_canonical_is_idempotent():
    from ascendc_devkit.domain.operator import AttrSpec, CANON_ATTR_CHECKERS
    for c in CANON_ATTR_CHECKERS:
        assert AttrSpec(name="x", type=c).type == c


def test_attrspec_type_non_scalar_passthrough_warns(caplog):
    """Non-scalar / unrecognized labels pass through unchanged AND emit a
    load-time WARN (§1.3) — surfaces misclassification (Tensor-as-attr, exotic
    container forms the translator doesn't recognize)."""
    import logging
    from ascendc_devkit.domain.operator import AttrSpec
    with caplog.at_level(logging.WARNING, logger="ascendc_devkit.domain.operator"):
        assert AttrSpec(name="x", type="Tensor").type == "Tensor"
        assert AttrSpec(name="x", type="RoundMode").type == "RoundMode"  # enum
    # step-105: IntList is now a TRANSLATABLE ATen spelling (list[int]) —
    # translation beats passthrough; only truly unknown labels pass through.
    assert AttrSpec(name="x", type="IntList").type == "list[int]"
    assert any("not a recognized type-grammar form" in r.getMessage()
               for r in caplog.records)


def test_attrspec_known_type_does_not_warn(caplog):
    """Canonical types (incl. translated aliases) must NOT trigger the WARN."""
    import logging
    from ascendc_devkit.domain.operator import AttrSpec
    with caplog.at_level(logging.WARNING, logger="ascendc_devkit.domain.operator"):
        AttrSpec(name="x", type="int")
        AttrSpec(name="x", type="list[float]")
        AttrSpec(name="x", type="ListInt")  # translates → list[int], no WARN
    assert not any("not a recognized canonical scalar type" in r.getMessage()
                   for r in caplog.records)


# —— validate_case_attrs: dispatch via CANON_ATTR_CHECKERS (no if/elif chain) —


def test_attrs_dispatch_each_canonical_type_passes():
    from ascendc_devkit.domain.operator import AttrSpec, OperatorSpec
    for t, v in [("int", 3), ("float", 3.5), ("str", "a"), ("bool", True),
                 ("list[int]", [1, 2]), ("list[float]", [1.0, 2.0])]:
        op = OperatorSpec(name="t", attrs={"a": AttrSpec(name="a", type=t)})
        validate_case_attrs({"a": v}, 0, operator=op)  # no exception


def test_attrs_dispatch_rejects_wrong_type():
    from ascendc_devkit.domain.operator import AttrSpec, OperatorSpec
    op = OperatorSpec(name="t", attrs={"a": AttrSpec(name="a", type="int")})
    with pytest.raises(HarnessContractError, match="expected int"):
        validate_case_attrs({"a": "not_int"}, 0, operator=op)


def test_attrs_list_float_matches_spec_passes():
    from ascendc_devkit.domain.operator import AttrSpec, OperatorSpec
    op = OperatorSpec(name="t", attrs={
        "scale_factor": AttrSpec(name="scale_factor", type="list[float]")})
    validate_case_attrs({"scale_factor": [2.0, 2.0]}, 0, operator=op)


def test_attrs_list_float_accepts_int_elements():
    from ascendc_devkit.domain.operator import AttrSpec, OperatorSpec
    op = OperatorSpec(name="t", attrs={
        "scale_factor": AttrSpec(name="scale_factor", type="list[float]")})
    validate_case_attrs({"scale_factor": [2, 2]}, 0, operator=op)  # ints assignable to float


def test_attrs_list_float_rejects_str_element():
    from ascendc_devkit.domain.operator import AttrSpec, OperatorSpec
    op = OperatorSpec(name="t", attrs={
        "scale_factor": AttrSpec(name="scale_factor", type="list[float]")})
    with pytest.raises(HarnessContractError, match="expected list\\[float\\]"):
        validate_case_attrs({"scale_factor": ["a", "b"]}, 0, operator=op)
