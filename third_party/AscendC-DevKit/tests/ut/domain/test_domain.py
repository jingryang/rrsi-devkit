"""Unit tests for L4 Domain types."""

import dataclasses
import json
from pathlib import Path

import pytest

from ascendc_devkit.domain.contract import StageIOContract
from ascendc_devkit.domain.artifact import ArtifactSpec, ArtifactContract
from ascendc_devkit.domain.operator import (
    OperatorSpec, TensorSpec, OperatorIdentity, AttrSpec,
    coerce_precision_thresholds, is_scalar_entry,
)
from ascendc_devkit.domain.requirement import (
    Requirement, Constraint, TestCase, UnclearItem, read_proto_precision,
    read_proto_schema,
)
from ascendc_devkit.domain.repository import (
    RepositoryProfile, BuildVariant, BuildStage, OpNaming, OpDirResolution,
    PrecisionDebugCommitScope,
)
from ascendc_devkit.domain.verification import (
    BuildResult, PerformanceResult,
)


class TestStageIOContract:
    def test_all_required_present(self):
        c = StageIOContract(requires=["a", "b"], provides=["c"])
        assert c.validate({"a", "b", "x"}) == []

    def test_missing_required(self):
        c = StageIOContract(requires=["a", "b"])
        assert c.validate({"a", "x"}) == ["b"]

    def test_empty_contract(self):
        c = StageIOContract()
        assert c.validate(set()) == []
        assert c.validate({"anything"}) == []

    def test_frozen_prevents_reassignment(self):
        """frozen=True prevents field reassignment but not mutation of mutable defaults."""
        c = StageIOContract(requires=["a"])
        try:
            c.requires = ["b"]
            assert False, "Should have raised"
        except Exception:
            pass
        assert c.requires == ["a"]

    def test_optional_provides_defaults_empty(self):
        c = StageIOContract(provides=["a"])
        assert c.optional_provides == []

    def test_all_provides_unions_guaranteed_and_optional(self):
        c = StageIOContract(provides=["a", "b"], optional_provides=["c"])
        assert c.all_provides() == ["a", "b", "c"]

    def test_all_provides_dedups_overlap(self):
        c = StageIOContract(provides=["a", "b"], optional_provides=["b", "c"])
        assert c.all_provides() == ["a", "b", "c"]

    def test_optional_provides_not_in_validate(self):
        """optional_provides is an output declaration; validate only checks requires."""
        c = StageIOContract(requires=["a"], optional_provides=["x"])
        assert c.validate({"a"}) == []


class TestArtifactSpec:
    def test_invalid_kind_rejected(self):
        try:
            ArtifactSpec(name="x", kind="bogus")
            assert False, "Should have raised"
        except ValueError:
            pass

    def test_validate_payload_requires_mapping(self):
        spec = ArtifactSpec(name="design_spec", filename="design_spec.json",
                            required_keys=("op_name",))
        errors = spec.validate_payload(["not", "a", "dict"])
        assert len(errors) == 1
        assert "JSON object" in errors[0]

    def test_validate_payload_missing_keys(self):
        spec = ArtifactSpec(name="d", filename="d.json",
                            required_keys=("op_name", "inputs", "outputs"))
        errors = spec.validate_payload({"op_name": "gelu"})
        assert any("inputs" in e for e in errors)
        assert any("outputs" in e for e in errors)

    def test_validate_payload_valid(self):
        spec = ArtifactSpec(name="d", filename="d.json", required_keys=("a",))
        assert spec.validate_payload({"a": 1}) == []

    def test_validate_payload_issue_required_keys_missing(self):
        # P47 Step 2: issue-level required keys (``acceptance``). A gate's
        # blocking issue without an executable acceptance is an ill-formed issue
        # (§1.3 加载期校验; L3 §3.2: 判据写不出 = issue 不成立), rejected at
        # parse time so the producer fixes the judgment, not the consumer.
        spec = ArtifactSpec(name="blocking_status", filename="blocking_status.json",
                            required_keys=("status",),
                            issue_required_keys=("acceptance",))
        errors = spec.validate_payload({
            "status": "blocked",
            "blocking_issues": [{"code": "AC1", "detail": "x"}]})
        assert any("acceptance" in e for e in errors), errors

    def test_validate_payload_issue_required_keys_present(self):
        spec = ArtifactSpec(name="blocking_status", filename="blocking_status.json",
                            issue_required_keys=("acceptance",))
        assert spec.validate_payload({
            "status": "blocked",
            "blocking_issues": [{"code": "AC1",
                                 "acceptance": "产物中不再出现 bfloat16_t"}]}) == []

    def test_validate_payload_no_issues_no_issue_check(self):
        # status=completed with no blocking_issues → issue-level check dormant.
        spec = ArtifactSpec(name="blocking_status", filename="blocking_status.json",
                            issue_required_keys=("acceptance",))
        assert spec.validate_payload({"status": "completed"}) == []

    def test_code_kind_never_validated(self):
        spec = ArtifactSpec(name="src", kind="code")
        assert spec.validate_payload("anything") == []
        assert spec.to_prompt_block() == ""

    def test_prompt_block_uses_example(self):
        spec = ArtifactSpec(name="d", filename="d.json", description="设计",
                            example={"op_name": "gelu"})
        block = spec.to_prompt_block()
        assert "d.json" in block
        assert "op_name" in block
        assert "```json" in block


class TestArtifactContract:
    def _contract(self):
        return ArtifactContract(artifacts=[
            ArtifactSpec(name="design_spec", filename="design_spec.json",
                        required=True, required_keys=("op_name", "inputs", "outputs")),
            ArtifactSpec(name="data_flow", filename="data_flow.json", required=False),
            ArtifactSpec(name="src", kind="code", required=True),
        ])

    def test_specs_excludes_code(self):
        names = [s.name for s in self._contract().specs()]
        assert names == ["design_spec", "data_flow"]

    def test_required_specs(self):
        names = [s.name for s in self._contract().required_specs()]
        assert names == ["design_spec"]

    def test_by_name(self):
        assert self._contract().by_name("data_flow").required is False
        assert self._contract().by_name("missing") is None

    def test_parse_valid(self):
        arts = {
            "design_spec.json": json.dumps({"op_name": "g", "inputs": [1], "outputs": [1]}),
            "data_flow.json": json.dumps({"step": "x"}),
        }
        parsed, errors = self._contract().parse(arts)
        assert errors == []
        assert set(parsed) == {"design_spec", "data_flow"}

    def test_parse_missing_required(self):
        parsed, errors = self._contract().parse({})
        assert "design_spec" not in parsed
        assert any("required artifact not produced" in e for e in errors)

    def test_parse_invalid_json(self):
        parsed, errors = self._contract().parse({"design_spec.json": "{not json"})
        assert any("invalid JSON" in e for e in errors)

    def test_parse_schema_violation_still_returns_payload(self):
        arts = {"design_spec.json": json.dumps({"op_name": "g"})}
        parsed, errors = self._contract().parse(arts)
        # payload returned despite schema errors, so callers can decide
        assert "design_spec" in parsed
        assert any("inputs" in e for e in errors)

    def test_render_empty_when_no_specs(self):
        c = ArtifactContract(artifacts=[ArtifactSpec(name="src", kind="code")])
        assert c.render_output_requirements() == ""


class TestArtifactCrossStageConsistency:
    """Guard against design↔codegen schema drift recurring.

    Design declares the canonical design_spec/kernel_architecture schema;
    codegen consumes specific keys from those payloads. These tests fail if
    the producer's declared schema stops covering what the consumer reads.
    """

    def test_design_spec_declares_keys_codegen_consumes(self):
        from ascendc_devkit.orchestration.stages.design_substages import SynthesizeStage
        spec = SynthesizeStage().artifact_contract().by_name("design_spec")
        # codegen.validate_inputs reads design_spec["inputs"] and ["outputs"]
        assert "inputs" in spec.required_keys
        assert "outputs" in spec.required_keys

    def test_codegen_init_produces_required_sections(self):
        """codegen_init deterministically produces kernel_architecture with all
        four standard sections (host/kernel + api/plugin), unconditionally.
        The ACLNN registration layer is generic code every operator gets — no
        per-repo gate (the old repo-name switch was a wrong abstraction)."""
        from ascendc_devkit.orchestration.stages.codegen_init import CodegenInitStage
        from ascendc_devkit.orchestration.kernel.state import State
        # Even without a profile → all four sections (no gate).
        arch = CodegenInitStage._build_sections()
        assert "host_code" in arch
        assert "kernel_code" in arch
        assert "api_code" in arch
        assert "plugin_code" in arch

    def test_design_example_satisfies_its_own_schema(self):
        from ascendc_devkit.orchestration.stages.design_substages import SynthesizeStage
        # Every spec's example payload must pass its own required_keys check.
        for spec in SynthesizeStage().artifact_contract().specs():
            if spec.example is not None:
                assert spec.validate_payload(spec.example) == [], \
                    f"{spec.filename} example violates its own schema"

    def test_requirement_example_satisfies_its_own_schema(self):
        from ascendc_devkit.orchestration.stages.requirement import RequirementStage
        for spec in RequirementStage().artifact_contract().specs():
            if spec.example is not None:
                assert spec.validate_payload(spec.example) == []


class TestOperatorSpec:
    def test_basic_creation(self):
        spec = OperatorSpec(
            name="gelu",
            inputs=[TensorSpec(name="x", dtype="fp16", shape=[128, "N"])],
            outputs=[TensorSpec(name="y", dtype="fp16", shape=[128, "N"])],
        )
        assert spec.name == "gelu"
        assert len(spec.inputs) == 1
        assert spec.inputs[0].dtype == "fp16"

    def test_from_dict(self):
        d = {
            "name": "gelu",
            "inputs": [{"name": "x", "dtype": "fp16", "shape": [128]}],
            "outputs": [{"name": "y", "dtype": "fp16", "shape": [128]}],
        }
        spec = OperatorSpec.from_dict(d)
        assert spec.name == "gelu"
        assert spec.inputs[0].name == "x"

    def test_from_dict_ignores_unknown_tensor_keys(self):
        """Agent/file dicts carry extra metadata (role, note, supported_dtypes)
        that TensorSpec does not model; from_dict must drop them, not crash."""
        d = {
            "name": "RotaryPositionEmbedding",
            "inputs": [{
                "name": "x",
                "role": "待执行旋转位置编码的张量",
                "dtype": "bf16",
                "supported_dtypes": ["fp16", "bf16", "fp32"],
                "shape": ["B", "N", "S", "D"],
                "note": "headDim 可不 32B 对齐",
            }],
            "outputs": [{
                "name": "out",
                "role": "计算结果",
                "dtype": "bf16",
                "shape": ["B", "N", "S", "D"],
            }],
        }
        spec = OperatorSpec.from_dict(d)
        assert spec.inputs[0].name == "x"
        assert spec.inputs[0].dtype == "bf16"
        assert spec.inputs[0].shape == ["B", "N", "S", "D"]
        assert spec.outputs[0].name == "out"

    def test_tensorspec_from_dict_filters_extra_keys(self):
        ts = TensorSpec.from_dict(
            {"name": "x", "dtype": "fp16", "shape": [4], "role": "input", "note": "x"}
        )
        assert ts == TensorSpec(name="x", dtype="fp16", shape=[4])

    def test_tensorspec_from_dict_is_list_derives_dynamic(self):
        """P2 (precision-tensorlist-harness-contract): a TensorList entry
        (``is_list=true``) must be param_type=DYNAMIC — REQUIRED on a
        TensorList is a semantic contradiction that made the runner's DYNAMIC
        gate reject list-of-lists case shapes (foreach_norm 20260807 halt)."""
        ts = TensorSpec.from_dict(
            {"name": "x", "dtype": "fp16", "shape": ["L", "*"],
             "is_list": True, "param_type": "REQUIRED"})
        assert ts.param_type == "DYNAMIC"

    def test_tensorspec_from_dict_is_list_already_dynamic_no_rewrite(self, caplog):
        """Already-DYNAMIC TensorList passes through unchanged + silent."""
        import logging
        ts = TensorSpec.from_dict(
            {"name": "x", "dtype": "fp16", "is_list": True,
             "param_type": "DYNAMIC"})
        assert ts.param_type == "DYNAMIC"
        with caplog.at_level(logging.WARNING, logger="ascendc_devkit.domain.operator"):
            TensorSpec.from_dict(
                {"name": "x", "dtype": "fp16", "is_list": True,
                 "param_type": "DYNAMIC"})
        assert not any("派生为 DYNAMIC" in r.getMessage() for r in caplog.records)

    def test_tensorspec_from_dict_is_list_derives_dynamic_warns(self, caplog):
        """The rewrite is surfaced (§1.3 — never silent), so a mis-declared
        producer is observable."""
        import logging
        from ascendc_devkit.domain.operator import TensorSpec as TS
        with caplog.at_level(logging.WARNING, logger="ascendc_devkit.domain.operator"):
            TS.from_dict({"name": "x", "is_list": True, "param_type": "REQUIRED"})
        assert any("派生为 DYNAMIC" in r.getMessage() for r in caplog.records)

    def test_operator_spec_from_dict_is_list_input_dynamic(self):
        """End-to-end: requirement-style TensorList input flows through
        OperatorSpec.from_dict with param_type derived to DYNAMIC (the runner
        reads this op_spec — the DYNAMIC gate then accepts list-of-lists)."""
        spec = OperatorSpec.from_dict({
            "name": "foreach_norm",
            "inputs": [{"name": "x", "dtype": ["fp16", "fp32", "bf16"],
                        "shape": ["L", "*"], "is_list": True,
                        "param_type": "REQUIRED"}],
            "outputs": [{"name": "y", "dtype": ["fp16", "fp32", "bf16"],
                         "shape": ["L"], "is_list": True,
                         "param_type": "REQUIRED"}],
        })
        assert spec.inputs[0].param_type == "DYNAMIC"
        assert spec.outputs[0].param_type == "DYNAMIC"

    def test_tensorspec_from_dict_is_list_string_false_no_derive(self):
        """M1 (PR-42): ``is_list`` as a quoted string ``"false"`` (LLM-written
        YAML/JSON is legal) must NOT be truthy — a non-TensorList input must
        stay REQUIRED, not be wrongly derived to DYNAMIC."""
        ts = TensorSpec.from_dict(
            {"name": "x", "dtype": "fp16", "is_list": "false",
             "param_type": "REQUIRED"})
        assert ts.param_type == "REQUIRED"

    def test_tensorspec_from_dict_is_list_string_true_derives(self):
        """M1 companion: a quoted ``"true"`` string (LLM-written) still derives
        DYNAMIC — normalization accepts the string form of true."""
        ts = TensorSpec.from_dict(
            {"name": "x", "dtype": "fp16", "is_list": "true",
             "param_type": "REQUIRED"})
        assert ts.param_type == "DYNAMIC"

    def test_from_dict_attrs_none_ok(self):
        """proto ``attrs:`` 空键 → YAML 解析为 None（weight_quant_batch_matmul
        真实场景）→ 视为无 attrs，不崩 ``.items()``。"""
        spec = OperatorSpec.from_dict({
            "name": "wq",
            "attrs": None,
            "inputs": [{"name": "x", "dtype": ["fp16"]}],
            "outputs": [{"name": "y", "dtype": ["fp16"]}],
        })
        assert spec.attrs == {}

    def test_from_dict_ignores_unknown_attr_keys(self):
        d = {
            "name": "gelu",
            "attrs": {"approximate": {"type": "str", "default": "none", "extra": "x"}},
        }
        spec = OperatorSpec.from_dict(d)
        assert spec.attrs["approximate"].type == "str"
        assert spec.attrs["approximate"].default == "none"

    def test_from_dict_routes_role_attr_input_to_attrs(self):
        """Agents sometimes list a runtime scalar selector under ``inputs`` and
        tag it ``role: attr`` (no ``shape``). It must land in ``attrs`` and the
        tensor list must stay all-tensors — not crash on the missing shape."""
        d = {
            "name": "RotaryPositionEmbedding",
            "inputs": [
                {"name": "x", "role": "tensor", "dtype": "bf16",
                 "shape": ["B", "N", "S", "D"]},
                {"name": "mode", "role": "attr", "dtype": "int64",
                 "required": True, "note": "0=half,1=interleave"},
            ],
            "outputs": [{"name": "out", "dtype": "bf16",
                         "shape": ["B", "N", "S", "D"]}],
        }
        spec = OperatorSpec.from_dict(d)
        assert [i.name for i in spec.inputs] == ["x"]
        assert "mode" in spec.attrs
        assert spec.attrs["mode"].type == "int"  # "int64" → canonical "int" (AttrSpec.__post_init__)
        assert "0=half" in spec.attrs["mode"].description

    def test_from_dict_routes_shapeless_nontensor_to_attrs(self):
        """A scalar-ish entry listed under ``inputs`` — a scalar ``dtype``
        (int32) with NO shape and no ``param_type`` — is a declared scalar and
        routes to attrs (§1.10 rule 5). Real shapeless tensors are distinguished
        by carrying ``param_type`` / an alias / a shape signal (see the DYNAMIC
        and in-place tests below), so this no longer over-captures them."""
        d = {
            "name": "op",
            "inputs": [
                {"name": "x", "dtype": "fp16", "shape": [128]},
                {"name": "axis", "dtype": "int32"},
            ],
            "outputs": [{"name": "y", "dtype": "fp16", "shape": [128]}],
        }
        spec = OperatorSpec.from_dict(d)
        assert [i.name for i in spec.inputs] == ["x"]
        assert "axis" in spec.attrs

    def test_from_dict_tensor_missing_shape_falls_back_empty(self):
        """A genuine tensor (role=tensor) that omits shape must not crash; it
        degrades to an empty shape as the last-resort safety net."""
        d = {
            "name": "op",
            "inputs": [{"name": "x", "role": "tensor", "dtype": "fp16"}],
            "outputs": [{"name": "y", "dtype": "fp16", "shape": [128]}],
        }
        spec = OperatorSpec.from_dict(d)
        assert spec.inputs[0].name == "x"
        assert spec.inputs[0].shape == []

    def test_dynamic_variadic_input_stays_tensor_without_shape(self):
        """§1.10 根治 (P3 / multi_add): a ``param_type=DYNAMIC`` variadic input
        (``Tensor[]``) has no scalar shape, but ``param_type`` is a tensor-only
        concept — it must stay in ``inputs`` (not sink to attrs). Pre-fix the
        "no shape ⇒ attr" proxy emptied ``op_spec.inputs``, so the precision
        harness read an out-of-range ``inputs[0]`` and rejected the correct
        nested ``[[152,7680]]`` shape."""
        d = {
            "name": "multi_add",
            "inputs": [
                {"name": "x1", "param_type": "DYNAMIC", "dtype": ["fp16"]},
                {"name": "x2", "param_type": "REQUIRED", "dtype": ["fp16"]},
            ],
            "outputs": [{"name": "y", "param_type": "REQUIRED", "dtype": ["fp16"]}],
        }
        spec = OperatorSpec.from_dict(d)
        assert [i.name for i in spec.inputs] == ["x1", "x2"]  # x1 NOT sunk to attrs
        assert spec.inputs[0].param_type == "DYNAMIC"
        assert "x1" not in spec.attrs

    def test_inplace_alias_output_stays_tensor_without_shape(self):
        """§1.10 根治 (P2 / advance_step_v2): an in-place mutation output aliases
        an input by name and carries only ``shape_formula`` (no explicit shape).
        It is a genuine tensor (the aliased input) and must stay in ``outputs``,
        not sink to attrs — otherwise codegen sees empty outputs and aborts."""
        d = {
            "name": "advance_step",
            "mutation_mode": "in_place",
            "inputs": [
                {"name": "input_tokens", "param_type": "REQUIRED",
                 "dtype": ["int64"], "shape": ["n"]},
                {"name": "other", "param_type": "REQUIRED", "shape": ["k"]},
            ],
            "outputs": [
                {"name": "input_tokens", "param_type": "REQUIRED",
                 "shape_formula": "same as input input_tokens"},
            ],
        }
        spec = OperatorSpec.from_dict(d)
        assert [o.name for o in spec.outputs] == ["input_tokens"]  # alias preserved
        assert "input_tokens" not in spec.attrs

    def test_undecidable_entry_kept_as_tensor_not_dropped(self):
        """§1.3 fail-open: an entry with no role / param_type / shape / scalar
        type is undecidable — keep it as a tensor (never silently drop a possible
        tensor) and let the caller see it. (A warning is emitted; not asserted
        here to avoid coupling to log text.)"""
        d = {
            "name": "op",
            "inputs": [{"name": "mystery"}],  # nothing declared
            "outputs": [{"name": "y", "dtype": "fp16", "shape": [8]}],
        }
        spec = OperatorSpec.from_dict(d)
        assert [i.name for i in spec.inputs] == ["mystery"]
        assert "mystery" not in spec.attrs


    def test_preserves_multi_dtype_list(self):
        """from_dict must not truncate a multi-dtype list to the first element."""
        d = {
            "name": "Exp",
            "inputs": [{"name": "x", "dtype": ["fp16", "fp32", "bf16"],
                        "shape": ["N"]}],
            "outputs": [{"name": "y", "dtype": ["fp16", "fp32", "bf16"],
                         "shape": ["N"]}],
        }
        spec = OperatorSpec.from_dict(d)
        assert spec.inputs[0].dtype == ["fp16", "fp32", "bf16"]
        assert spec.outputs[0].dtype == ["fp16", "fp32", "bf16"]

    def test_scalar_dtype_still_works(self):
        """Single-string dtype must remain a plain str (backward compat)."""
        d = {
            "name": "Relu",
            "inputs": [{"name": "x", "dtype": "fp16", "shape": ["N"]}],
            "outputs": [{"name": "y", "dtype": "fp16", "shape": ["N"]}],
        }
        spec = OperatorSpec.from_dict(d)
        assert spec.inputs[0].dtype == "fp16"
        assert spec.outputs[0].dtype == "fp16"

    def test_immutable(self):
        spec = OperatorSpec(name="gelu")
        try:
            spec.name = "relu"
        except Exception:
            pass
        assert spec.name == "gelu"


class TestPrecisionThresholds:
    """P69: OperatorSpec.precision_thresholds 作 proto 精度规格单一载体
    (proto→spec→runner 贯穿)；coerce 纯函数守护加载期健壮性 (§1.3)。"""

    def test_default_is_none_when_absent(self):
        spec = OperatorSpec.from_dict({"name": "gelu"})
        assert spec.precision_thresholds is None

    def test_from_dict_reads_thresholds(self):
        spec = OperatorSpec.from_dict({
            "name": "dynamic_quant",
            "precision_thresholds": {"int8": 1.0, "uint8": 0},
        })
        assert spec.precision_thresholds == {"int8": 1.0, "uint8": 0.0}

    def test_coerce_numeric_strings(self):
        # proto yaml 可能给数值字符串；coerce 成 float
        assert coerce_precision_thresholds({"int8": "1.0", "fp16": 0.001}) == {
            "int8": 1.0, "fp16": 0.001,
        }

    def test_coerce_skips_non_numeric_values(self):
        # 坏值逐项跳过，不整体崩（§1.3）
        assert coerce_precision_thresholds(
            {"int8": 1.0, "fp16": "tight", "x": None}
        ) == {"int8": 1.0}

    def test_coerce_none_for_non_dict(self):
        assert coerce_precision_thresholds(None) is None
        assert coerce_precision_thresholds("int8:1.0") is None
        assert coerce_precision_thresholds([]) is None

    def test_coerce_none_for_empty_dict(self):
        assert coerce_precision_thresholds({}) is None

    def test_from_dict_coerces_bad_thresholds(self):
        spec = OperatorSpec.from_dict({
            "name": "op",
            "precision_thresholds": {"int8": 1.0, "bad": "nope"},
        })
        assert spec.precision_thresholds == {"int8": 1.0}

    def test_spec_is_immutable_thresholds(self):
        spec = OperatorSpec(name="gelu", precision_thresholds={"int8": 1.0})
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            spec.precision_thresholds = {}


class TestTensorSpecCompare:
    """P69: TensorSpec.compare 透传 proto output compare:false (→ cann-bench
    ignore_output_indices，跳过该输出比较)。``None`` = 正常比较 (默认)。"""

    def test_default_compare_is_none(self):
        assert TensorSpec(name="y", dtype="fp16", shape=[4]).compare is None

    def test_from_dict_reads_compare_true(self):
        ts = TensorSpec.from_dict({"name": "y", "dtype": "fp16", "compare": True})
        assert ts.compare is True

    def test_from_dict_reads_compare_false(self):
        ts = TensorSpec.from_dict({"name": "y", "dtype": "fp16", "compare": False})
        assert ts.compare is False

    def test_from_dict_omits_compare_keeps_none(self):
        ts = TensorSpec.from_dict({"name": "y", "dtype": "fp16"})
        assert ts.compare is None

    def test_from_dict_reads_index_gather(self):
        ts = TensorSpec.from_dict({
            "name": "idx", "dtype": "int64",
            "index_gather": {"input": "x", "dim_attr": "dim", "value_output": "y"},
        })
        assert ts.index_gather == {"input": "x", "dim_attr": "dim", "value_output": "y"}

    def test_from_dict_omits_index_gather_keeps_none(self):
        ts = TensorSpec.from_dict({"name": "y", "dtype": "fp16"})
        assert ts.index_gather is None


class TestSpecSerializationRoundTrip:
    """P69: 新增 dict/bool 字段经 State snapshot (asdict + JSON + rebuild) 须
    round-trip 保真——runner 从 resume 后的 spec 取 precision_thresholds 时不能丢。"""

    def test_precision_thresholds_and_compare_round_trip(self):
        spec = OperatorSpec(
            name="dynamic_quant",
            precision_thresholds={"int8": 1.0, "fp16": 2 ** -10},
            outputs=[TensorSpec(name="y", dtype="int8", shape=[16], compare=False)],
        )
        snap = dataclasses.asdict(spec)
        rebuilt = OperatorSpec.from_dict(snap)
        assert rebuilt.precision_thresholds == {"int8": 1.0, "fp16": 2 ** -10}
        assert rebuilt.outputs[0].compare is False

    def test_index_gather_round_trip(self):
        # index_gather dict 经 asdict + from_dict 保真（runner 渲染 harness 时读取）
        spec = OperatorSpec(
            name="top_k",
            inputs=[TensorSpec(name="x", dtype="fp16", shape=["N"])],
            outputs=[
                TensorSpec(name="y", dtype="fp16", shape=["K"]),
                TensorSpec(name="idx", dtype="int64", shape=["K"],
                           compare=False,
                           index_gather={"input": "x", "dim_attr": "dim",
                                         "value_output": "y"}),
            ],
        )
        rebuilt = OperatorSpec.from_dict(dataclasses.asdict(spec))
        assert rebuilt.outputs[1].compare is False
        assert rebuilt.outputs[1].index_gather == {
            "input": "x", "dim_attr": "dim", "value_output": "y",
        }

    def test_none_thresholds_round_trip(self):
        # 默认 None 经 asdict 变 None，round-trip 仍 None（不是 {}）
        spec = OperatorSpec(name="gelu")
        rebuilt = OperatorSpec.from_dict(dataclasses.asdict(spec))
        assert rebuilt.precision_thresholds is None


class TestProtoPrecisionParsing:
    """P69: proto.yaml precision_thresholds 解析（read_proto_precision 纯函数）。
    proto 是 cann-bench 产物，precision 容差单一源；agent 丢，devkit 确定性重读。"""

    def test_read_proto_precision_operator_block(self, tmp_path):
        p = tmp_path / "proto.yaml"
        p.write_text(
            "operator:\n  name: dq\n  precision_thresholds:\n    int8: 1.0\n"
            "  outputs:\n  - name: y\n    dtype:\n    - int8\n"
        )
        pt, compares, _ = read_proto_precision(p)
        assert pt == {"int8": 1.0}
        assert compares == [None]

    def test_read_proto_precision_output_compare_false(self, tmp_path):
        p = tmp_path / "proto.yaml"
        p.write_text("operator:\n  outputs:\n  - name: y\n    compare: false\n")
        _, compares, _ = read_proto_precision(p)
        assert compares == [False]

    def test_read_proto_precision_none_path(self):
        assert read_proto_precision(None) == (None, [], [])

    def test_read_proto_precision_nonexistent(self):
        assert read_proto_precision(Path("/no/such.yaml")) == (None, [], [])

    def test_read_proto_precision_prose_md(self, tmp_path):
        # prose .md（agent 解释，非机器解析）→ 无 precision_thresholds，graceful
        p = tmp_path / "req.md"
        p.write_text("# free text\nnot yaml")
        assert read_proto_precision(p) == (None, [], [])

    def test_read_proto_precision_markdown_bold_not_yaml_alias(self, tmp_path):
        # 回归：cann-bench desc.md 的 ``**基本公式**：`` 被 PyYAML 误判为别名锚点
        # → ScannerError 必须 graceful 降级（None），不得穿透 stage 中止管线。
        p = tmp_path / "desc.md"
        p.write_text(
            "# RmsNorm\n\n## 数学公式\n\n**基本公式**：\n\n$$\ny = x / sqrt(mean(x^2)) \\cdot \\gamma\n$$\n",
            encoding="utf-8",
        )
        assert read_proto_precision(p) == (None, [], [])

    def test_read_proto_precision_directory_returns_none(self, tmp_path):
        # 回归：read_text 先抛 OSError 时，except 元组里的 yaml.YAMLError 曾引用
        # 函数内 lazy-import 未绑定的局部名 → UnboundLocalError 崩溃。import yaml
        # 上提后该读失败路径必须优雅返回 None。
        d = tmp_path / "adir"
        d.mkdir()
        assert read_proto_precision(d) == (None, [], [])

    def test_read_proto_precision_top_level_thresholds(self, tmp_path):
        # devkit requirement.json 风格：顶层 precision_thresholds（无 operator 块）
        p = tmp_path / "req.yaml"
        p.write_text("op:\n  name: gelu\nprecision_thresholds:\n  fp16: 0.001\n")
        pt, _, _ = read_proto_precision(p)
        assert pt == {"fp16": 0.001}

    def test_read_proto_precision_output_index_gather(self, tmp_path):
        # TopK 风格：idx 输出 compare:false + index_gather 声明 → 原样透传
        p = tmp_path / "proto.yaml"
        p.write_text(
            "operator:\n  outputs:\n"
            "  - name: y\n"
            "  - name: idx\n    dtype: [int64]\n    compare: false\n"
            "    index_gather:\n      input: x\n      dim_attr: dim\n"
            "      value_output: y\n"
        )
        _, compares, index_gathers = read_proto_precision(p)
        assert compares == [None, False]
        assert index_gathers == [
            None,
            {"input": "x", "dim_attr": "dim", "value_output": "y"},
        ]

    def test_read_proto_precision_index_gather_wrong_type_warns(self, tmp_path):
        # §1.3：index_gather 类型错误（非 dict）→ warn 留痕（不静默置 None），
        # 校验规格无声消失是配置问题，须可观测。
        p = tmp_path / "proto.yaml"
        p.write_text(
            "operator:\n  outputs:\n"
            "  - name: idx\n    dtype: [int64]\n"
            "    index_gather: 'input: x'  # 误写为字符串\n"
        )
        with pytest.warns(UserWarning, match="index_gather 类型错误"):
            _, _, index_gathers = read_proto_precision(p)
        assert index_gathers == [None]


class TestRequirementFromDictProto:
    """P69 Flow B: Requirement.from_dict 兼容 cann-bench proto.yaml 的
    operator: 块（precision_thresholds 自动经 OperatorSpec.from_dict 进 op_spec）。"""

    def test_from_dict_reads_operator_block_name_and_thresholds(self):
        req = Requirement.from_dict({
            "operator": {"name": "DynamicQuant", "precision_thresholds": {"int8": 1.0}},
        })
        assert req.op_spec.name == "DynamicQuant"
        assert req.op_spec.precision_thresholds == {"int8": 1.0}

    def test_from_dict_prefers_op_over_operator(self):
        # devkit requirement.json 用 op:，proto 用 operator:。两者都在时 op 优先。
        req = Requirement.from_dict({
            "op": {"name": "from_op"},
            "operator": {"name": "from_operator"},
        })
        assert req.op_spec.name == "from_op"

    def test_from_dict_dtype_list_preserved(self):
        # proto dtype 是 list（[float16, bfloat16]）；TensorSpec 原样保留完整列表。
        # （input 带 shape 以免被 _route 当 attr 路由）
        req = Requirement.from_dict({
            "operator": {
                "name": "dq",
                "inputs": [{"name": "x", "dtype": ["float16", "bfloat16"], "shape": ["N"]}],
            },
        })
        assert req.op_spec.inputs[0].dtype == ["float16", "bfloat16"]


class TestOperatorIdentity:
    def test_creation(self):
        spec = OperatorSpec(name="gelu")
        identity = OperatorIdentity(
            spec=spec,
            repo_root=Path("/repo"),
            op_dir=Path("/repo/custom_ops/gelu"),
            files={"tiling_h": Path("gelu_tiling.h")},
        )
        assert identity.spec.name == "gelu"
        assert "tiling_h" in identity.files


class TestTestCase:
    """TestCase.attrs (P8) — carries operator attribute values per case so
    kernels/goldens can be exercised on non-default branches."""

    def test_attrs_default_empty(self):
        """A case with no attrs must default to an empty dict — zero regression
        for attr-less operators whose cases never specify attrs."""
        tc = TestCase(name="basic", inputs=[{"name": "x", "shape": [4]}])
        assert tc.attrs == {}

    def test_attrs_default_is_distinct_instance(self):
        """The mutable default must not be shared across instances (frozen
        dataclass uses field(default_factory=dict) for this)."""
        a = TestCase(name="a")
        b = TestCase(name="b")
        a.attrs["base"] = -1.0
        assert b.attrs == {}

    def test_attrs_carried_in_construction(self):
        tc = TestCase(
            name="scale_branch",
            inputs=[{"name": "x", "shape": [8]}],
            attrs={"base": -1.0, "scale": 1.5, "shift": 0.0},
        )
        assert tc.attrs == {"base": -1.0, "scale": 1.5, "shift": 0.0}

    def test_from_dict_picks_up_attrs(self):
        """Requirement.from_dict → filter_known_fields keeps only declared
        fields, so once attrs is a field it flows through from a test-case dict."""
        d = {
            "op": {"name": "exp"},
            "test_cases": [{
                "name": "scale_branch",
                "inputs": [{"name": "x", "shape": [4]}],
                "attrs": {"base": 2.0, "scale": 1.5, "shift": 1.0},
                "ignored_meta": "dropped",
            }],
        }
        tc = Requirement.from_dict(d).test_cases[0]
        assert tc.attrs == {"base": 2.0, "scale": 1.5, "shift": 1.0}

    def test_from_dict_case_without_attrs_defaults_empty(self):
        d = {
            "op": {"name": "add"},
            "test_cases": [{"name": "basic", "inputs": [{"name": "x", "shape": [4]}]}],
        }
        tc = Requirement.from_dict(d).test_cases[0]
        assert tc.attrs == {}


class TestRequirement:
    def test_from_dict(self):
        d = {
            "op": {
                "name": "gelu",
                "inputs": [{"name": "x", "dtype": "fp16", "shape": [128]}],
                "outputs": [{"name": "y", "dtype": "fp16", "shape": [128]}],
            },
            "constraints": [{"kind": "precision", "threshold": 1e-5}],
            "test_cases": [
                {
                    "name": "basic",
                    "inputs": [{"name": "x", "shape": [4], "data": [1.0, 2.0, 3.0, 4.0]}],
                    "expected": {"max_diff": 1e-5},
                }
            ],
        }
        req = Requirement.from_dict(d)
        assert req.op_spec.name == "gelu"
        assert len(req.test_cases) == 1
        assert req.test_cases[0].name == "basic"
        assert len(req.constraints) == 1

    def test_from_dict_ignores_unknown_constraint_and_item_keys(self):
        """Constraints/unclear_items from the agent carry extra keys (dtype, note);
        from_dict must filter them rather than raise TypeError."""
        d = {
            "op": {
                "name": "rope",
                "inputs": [{"name": "x", "dtype": "bf16", "shape": ["N"], "role": "in"}],
                "outputs": [{"name": "y", "dtype": "bf16", "shape": ["N"]}],
            },
            "constraints": [
                {"kind": "precision", "dtype": "bf16", "threshold": 0.0039, "note": "bf16"},
            ],
            "unclear_items": [
                {"question": "tail behavior?", "context": "partial_rope", "extra": "x"},
            ],
        }
        req = Requirement.from_dict(d)
        assert req.constraints[0].kind == "precision"
        assert req.constraints[0].threshold == 0.0039
        assert req.unclear_items[0].question == "tail behavior?"
        assert req.constraints[0].kind == "precision"

    def test_unclear_item_severity_defaults_choice(self):
        """An unlabeled unclear item is conservatively 'choice' (never blocks)."""
        item = UnclearItem(question="which dtype?")
        assert item.severity == "choice"
        assert item.resolution is None

    def test_unclear_item_parses_severity_and_resolution(self):
        """from_dict carries severity/resolution through filter_known_fields."""
        d = {
            "op": {
                "name": "rope",
                "inputs": [{"name": "x", "dtype": "bf16", "shape": ["N"]}],
                "outputs": [{"name": "y", "dtype": "bf16", "shape": ["N"]}],
            },
            "unclear_items": [
                {"question": "rank 3D or 4D?", "severity": "blocking"},
                {"question": "default mode?", "severity": "choice",
                 "resolution": "half (default assumption)"},
            ],
        }
        req = Requirement.from_dict(d)
        assert req.unclear_items[0].severity == "blocking"
        assert req.unclear_items[0].resolution is None
        assert req.unclear_items[1].severity == "choice"
        assert req.unclear_items[1].resolution == "half (default assumption)"

    def test_defaults(self):
        req = Requirement(op_spec=OperatorSpec(name="test"))
        assert req.test_cases == []
        assert req.constraints == []
        assert req.design_doc_path is None

    def test_frozen_prevents_reassignment(self):
        """frozen=True prevents field reassignment but not mutation of mutable defaults."""
        req = Requirement(op_spec=OperatorSpec(name="test"))
        try:
            req.test_cases = [TestCase(name="new")]
            assert False, "Should have raised"
        except Exception:
            pass
        assert req.test_cases == []

    def test_from_file_json(self, tmp_path):
        p = tmp_path / "req.json"
        p.write_text(json.dumps({
            "op": {"name": "gelu"},
            "constraints": [{"kind": "precision", "threshold": 1e-5}],
        }))
        req = Requirement.from_file(p)
        assert req.op_spec.name == "gelu"
        assert len(req.constraints) == 1

    def test_from_file_yaml(self, tmp_path):
        p = tmp_path / "req.yaml"
        p.write_text(
            "op:\n  name: add\n"
            "test_cases:\n  - name: basic\n"
        )
        req = Requirement.from_file(p)
        assert req.op_spec.name == "add"
        assert req.test_cases[0].name == "basic"

    def test_from_file_yml_extension(self, tmp_path):
        p = tmp_path / "req.yml"
        p.write_text("op:\n  name: relu\n")
        assert Requirement.from_file(p).op_spec.name == "relu"

    def test_from_file_unknown_extension_falls_back_to_yaml(self, tmp_path):
        p = tmp_path / "req.txt"
        p.write_text("op:\n  name: tanh\n")
        assert Requirement.from_file(p).op_spec.name == "tanh"

    def test_from_file_rejects_non_mapping(self, tmp_path):
        p = tmp_path / "req.yaml"
        p.write_text("- a\n- b\n")
        try:
            Requirement.from_file(p)
            assert False, "Should have raised"
        except ValueError:
            pass


class TestRepositoryProfile:
    def _omni(self):
        return RepositoryProfile.from_yaml({
            "name": "omni-ops",
            "display_name": "自定义算子仓 (omni-ops)",
            "op_naming": {"prefix": "ai_infra_"},
            "build_variants": [
                {
                    "name": "inference",
                    "match_prefix": "inference/ascendc/src",
                    "default_reference_root": "inference/ascendc/src",
                    "stages": [
                        {"name": "ascendc", "cwd": "inference/ascendc",
                         "command_template": "bash build.sh -n {full_op_name} -c {soc_version}",
                         "default_chip": "A3", "enabled": True},
                        {"name": "torch_ext", "cwd": "inference/ascendc/torch_ops_extension",
                         "command_template": "bash build_and_install.sh",
                         "default_chip": "A3", "enabled": False},
                    ],
                },
                {
                    "name": "training",
                    "match_prefix": "training/ascendc/src",
                    "default_reference_root": "training/ascendc/src",
                    "stages": [
                        {"name": "ascendc", "cwd": "training/ascendc",
                         "command_template": "bash build.sh -n {full_op_name} -c {soc_version}",
                         "default_chip": "A3", "enabled": True},
                    ],
                },
            ],
            "artifacts_ignore": ["*.o", "*.so"],
            "scaffolding": {"supported": ["torch_op"], "selected": "torch_op"},
        })

    def test_from_yaml_minimal(self):
        data = {
            "name": "ops-nn",
            "build_variants": [
                {"name": "default", "match_prefix": "",
                 "stages": [{"name": "ascendc", "cwd": ".",
                             "command_template": "bash build.sh"}]},
            ],
            "scaffolding": {"supported": ["torch_op"], "selected": "torch_op"},
        }
        profile = RepositoryProfile.from_yaml(data)
        assert profile.name == "ops-nn"
        assert profile.build_variants[0].stages[0].command_template == "bash build.sh"

    def test_precision_debug_commit_scope_from_yaml(self):
        profile = RepositoryProfile.from_yaml({
            "name": "ops-nn",
            "precision_debug_commit": {
                "include": ["op_kernel/**", "CMakeLists.txt"],
                "exclude": ["**/*.bak", "**/*.log"],
            },
            "scaffolding": {"supported": ["torch_op"], "selected": "torch_op"},
        })

        assert profile.precision_debug_commit == PrecisionDebugCommitScope(
            include=("op_kernel/**", "CMakeLists.txt"),
            exclude=("**/*.bak", "**/*.log"),
        )

    def test_full_op_name_prefixes(self):
        p = self._omni()
        assert p.full_op_name("rope") == "ai_infra_rope"
        # idempotent when already prefixed
        assert p.full_op_name("ai_infra_rope") == "ai_infra_rope"

    def test_derive_op_name_strips_prefix(self):
        p = self._omni()
        assert p.derive_op_name("ai_infra_kv_rms_norm_rope_cache") == "kv_rms_norm_rope_cache"
        assert p.derive_op_name("no_prefix") == "no_prefix"

    def test_identity_key_carries_repo(self):
        p = self._omni()
        assert p.identity_key("ai_infra_rope") == "omni-ops/ai_infra_rope"

    def test_select_variant_by_prefix(self):
        p = self._omni()
        v = p.select_variant("inference/ascendc/src/ops-transformer/posembedding/ai_infra_rope")
        assert v is not None and v.name == "inference"
        v2 = p.select_variant("training/ascendc/src/foo/bar")
        assert v2 is not None and v2.name == "training"

    def test_select_variant_no_match_returns_none(self):
        p = self._omni()
        assert p.select_variant("unknown/path") is None

    # —— G2: build_stage role (deploy generalization, D6-2) ——

    def test_stage_role_defaults_to_build(self):
        """A stage without an explicit role is a plain build stage."""
        p = RepositoryProfile.from_yaml({
            "name": "x",
            "build_variants": [
                {"name": "default", "match_prefix": "",
                 "stages": [{"name": "ascendc", "command_template": "bash build.sh"}]},
            ],
            "scaffolding": {"supported": ["torch_op"], "selected": "torch_op"},
        })
        assert p.build_variants[0].stages[0].role == "build"

    def test_stage_role_parsed_from_yaml(self):
        """install_runtime/install_python/smoke roles are read from YAML."""
        p = RepositoryProfile.from_yaml({
            "name": "cann-bench",
            "build_variants": [
                {"name": "default", "match_prefix": "ops",
                 "stages": [
                     {"name": "build", "role": "build", "command_template": "bash build.sh"},
                     {"name": "opp", "role": "install_runtime",
                      "command_template": "bash {run_pkg} --install-path={per_op_opp_dir}"},
                     {"name": "whl", "role": "install_python",
                      "command_template": "pip install --target={per_op_python_dir} {whl_pkg}"},
                     {"name": "smoke", "role": "smoke", "command_template": ""},
                 ]},
            ],
            "scaffolding": {"supported": ["torch_op"], "selected": "torch_op"},
        })
        roles = [s.role for s in p.build_variants[0].stages]
        assert roles == ["build", "install_runtime", "install_python", "smoke"]

    def test_deploy_stages_for_variant(self):
        """deploy_stages(rel_op_dir) returns enabled install/smoke stages in order."""
        p = RepositoryProfile.from_yaml({
            "name": "cann-bench",
            "build_variants": [
                {"name": "default", "match_prefix": "ops",
                 "stages": [
                     {"name": "build", "role": "build", "command_template": "bash build.sh"},
                     {"name": "opp", "role": "install_runtime", "command_template": "install opp"},
                     {"name": "smoke", "role": "smoke", "command_template": ""},
                 ]},
            ],
            "scaffolding": {"supported": ["torch_op"], "selected": "torch_op"},
        })
        deploy = p.deploy_stages("ops/add")
        assert [s.role for s in deploy] == ["install_runtime", "smoke"]

    def test_has_deploy_capability(self):
        """has_deploy_capability = variant has install_runtime + smoke roles."""
        deployable = RepositoryProfile.from_yaml({
            "name": "cann-bench",
            "build_variants": [
                {"name": "default", "match_prefix": "ops",
                 "stages": [
                     {"name": "build", "role": "build", "command_template": "b"},
                     {"name": "opp", "role": "install_runtime", "command_template": "i"},
                     {"name": "smoke", "role": "smoke", "command_template": ""},
                 ]},
            ],
            "scaffolding": {"supported": ["torch_op"], "selected": "torch_op"},
        })
        assert deployable.has_deploy_capability("ops/add") is True

        build_only = RepositoryProfile.from_yaml({
            "name": "legacy",
            "build_variants": [
                {"name": "default", "match_prefix": "ops",
                 "stages": [{"name": "build", "role": "build", "command_template": "b"}]},
            ],
            "scaffolding": {"supported": ["torch_op"], "selected": "torch_op"},
        })
        assert build_only.has_deploy_capability("ops/add") is False

    # —— B7 (13 E1): profile source layer deleted — golden/cases moved to CLI ——

    def test_schema_rejects_golden_source_key(self):
        """B7: the profile schema no longer carries golden_source — the source
        layer moved to CLI (--golden-entry / --golden-input-type). A profile that
        still declares golden_source fails schema validation at load time
        (additionalProperties:false), not silently accepted."""
        from ascendc_devkit.adapters.repository.profile_loader import (
            _validate_profile_data)
        data = {
            "name": "x",
            "build_variants": [{"name": "d", "match_prefix": "", "stages": []}],
            "scaffolding": {"supported": ["torch_op"], "selected": "torch_op"},
            "golden_source": {"path": "g.py"},
        }
        with pytest.raises(ValueError, match="golden_source"):
            _validate_profile_data(data, "x")

    def test_schema_rejects_cases_source_key(self):
        """B7: the profile schema no longer carries cases_source — the source
        layer moved to CLI (--cann-bench-cases). A profile that still declares
        cases_source fails schema validation at load time."""
        from ascendc_devkit.adapters.repository.profile_loader import (
            _validate_profile_data)
        data = {
            "name": "x",
            "build_variants": [{"name": "d", "match_prefix": "", "stages": []}],
            "scaffolding": {"supported": ["torch_op"], "selected": "torch_op"},
            "cases_source": {"format": "cann_bench_csv", "path": "c.csv"},
        }
        with pytest.raises(ValueError, match="cases_source"):
            _validate_profile_data(data, "x")

    def test_profile_has_no_source_fields(self):
        """B7: RepositoryProfile has no golden_source/cases_source attributes
        (the whole source layer is deleted — golden/cases come from CLI/State)."""
        p = RepositoryProfile.from_yaml({
            "name": "x",
            "build_variants": [{"name": "d", "match_prefix": "", "stages": []}],
            "scaffolding": {"supported": ["torch_op"], "selected": "torch_op"},
        })
        assert not hasattr(p, "golden_source")
        assert not hasattr(p, "cases_source")

    def test_schema_rejects_incremental_command_template(self):
        """step-101: incremental_command_template 已整体删除（cann-bench 增量
        构建的 mtime 陷阱：kernel 源变更不进 binary——L1/L3 见
        docs/plan/cannbench-incremental-stale-trap/）。schema 不再接受该键，
        声明即加载期失败（§1.3），防将来误加回。"""
        from ascendc_devkit.adapters.repository.profile_loader import (
            _validate_profile_data)
        data = {
            "name": "x",
            "build_variants": [{
                "name": "d", "match_prefix": "", "stages": [{
                    "name": "ascendc", "cwd": ".", "role": "build",
                    "command_template": "bash build.sh",
                    "incremental_command_template": "cmake --build build",
                }],
            }],
            "scaffolding": {"supported": ["torch_op"], "selected": "torch_op"},
        }
        with pytest.raises(ValueError, match="incremental_command_template"):
            _validate_profile_data(data, "x")

    def test_build_stage_has_no_incremental_field(self):
        """step-101: BuildStage 不再有 incremental_command_template 属性
        （唯一通路=command_template 全量，§2.5 不留双通路）。"""
        s = RepositoryProfile._parse_build_stage({
            "name": "ascendc", "cwd": ".", "role": "build",
            "command_template": "bash build.sh",
            "incremental_command_template": "cmake --build build",
        })
        assert not hasattr(s, "incremental_command_template")

    def test_cann_bench_profile_loads_without_source_blocks(self):
        """B9a/B7 (13 E1): the cann-bench profile no longer declares
        golden_source / cases_source (source moved to CLI). It loads cleanly
        through the real ProfileLoader + JSON Schema gate with just name +
        build_variants; the build/deploy config is intact."""
        from ascendc_devkit.adapters.repository.profile_loader import ProfileLoader
        p = ProfileLoader.load("cann-bench")
        assert p.name == "cann-bench"
        assert p.build_variants  # build config intact

    def test_select_variant_empty_prefix_is_fallback(self):
        p = RepositoryProfile.from_yaml({
            "name": "ops-nn",
            "build_variants": [{"name": "default", "match_prefix": "",
                                "default_reference_root": ".",
                                "stages": []}],
            "scaffolding": {"supported": ["torch_op"], "selected": "torch_op"},
        })
        v = p.select_variant("anything/goes/here")
        assert v is not None and v.name == "default"

    def test_enabled_stages_filters_disabled(self):
        p = self._omni()
        inf = p.select_variant("inference/ascendc/src/x/y")
        assert [s.name for s in inf.enabled_stages()] == ["ascendc"]

    def test_no_prefix_profile_passthrough(self):
        p = RepositoryProfile.from_yaml({"name": "ops-nn", "build_variants": [],
                                          "scaffolding": {"supported": ["torch_op"], "selected": "torch_op"}})
        assert p.full_op_name("rope") == "rope"
        assert p.derive_op_name("rope") == "rope"

    def test_build_commands_render_full_op_name_and_chip(self):
        p = self._omni()
        cmds = p.build_commands(
            "inference/ascendc/src/g/c/ai_infra_rope", "ai_infra_rope", "A2")
        assert cmds == ["bash build.sh -n ai_infra_rope -c ascend910b"]

    def test_build_commands_use_default_chip_when_unset(self):
        p = self._omni()
        cmds = p.build_commands("inference/ascendc/src/x/y", "ai_infra_foo")
        assert cmds == ["bash build.sh -n ai_infra_foo -c ascend910_93"]

    def test_build_commands_empty_when_no_variant(self):
        p = self._omni()
        assert p.build_commands("unknown/tree/foo", "ai_infra_foo") == []

    def test_build_commands_skips_deploy_role_placeholders(self):
        """build_commands is a display/prompt helper that renders only
        build-role commands. Deploy-role templates carry runtime placeholders
        ({run_pkg}/{whl_pkg}/{per_op_opp_dir}) injected by the Deployer at run
        time — rendering them here raises KeyError before codegen can spawn
        its agent (P43). Mirrors deploy.py's own `s.role == "build"` filter."""
        p = RepositoryProfile.from_yaml({
            "name": "cann-bench",
            "build_variants": [
                {"name": "default", "match_prefix": "ops",
                 "stages": [
                     {"name": "ascendc", "role": "build",
                      "command_template": "bash build.sh -c {soc_version}"},
                     {"name": "install_opp", "role": "install_runtime",
                      "command_template": "bash {run_pkg} --install-path={per_op_opp_dir}"},
                     {"name": "install_whl", "role": "install_python",
                      "command_template": "pip install --target {per_op_python_dir} {whl_pkg}"},
                     {"name": "smoke", "role": "smoke", "command_template": ""},
                 ]},
            ],
            "scaffolding": {"supported": ["torch_op", "aclnn", "pybind"],
                            "selected": "torch_op"},
        })
        cmds = p.build_commands("ops/add", "ai_infra_add", "A2")
        # only the build-role command is rendered; deploy-role templates skipped
        assert cmds == ["bash build.sh -c ascend910b"]

    def test_reference_roots_default_only(self):
        p = self._omni()
        roots = p.reference_roots("inference/ascendc/src/x/y")
        assert roots == ["inference/ascendc/src"]

    def test_reference_roots_appends_extras_after_default(self):
        p = self._omni()
        roots = p.reference_roots(
            "inference/ascendc/src/x/y", extra=["/other/repo/rope", "more"])
        assert roots == ["inference/ascendc/src", "/other/repo/rope", "more"]

    def test_reference_roots_dedups_preserving_order(self):
        p = self._omni()
        roots = p.reference_roots(
            "inference/ascendc/src/x/y", extra=["inference/ascendc/src", "x"])
        assert roots == ["inference/ascendc/src", "x"]

    # —— Scaffolding: single-authority invocation protocol ——

    def test_scaffolding_parsed_from_yaml(self):
        p = RepositoryProfile.from_yaml({
            "name": "cann-bench",
            "build_variants": [{"name": "d", "match_prefix": "", "stages": []}],
            "scaffolding": {"supported": ["torch_op", "aclnn", "pybind"],
                            "selected": "torch_op"},
        })
        assert p.scaffolding.supported == ("torch_op", "aclnn", "pybind")
        assert p.scaffolding.selected == "torch_op"
        assert p.scaffolding_kind() == "torch_op"

    def test_scaffolding_absent_raises(self):
        """§1.4: scaffolding is mandatory — absent block raises at load."""
        with pytest.raises(ValueError, match="missing the required.*scaffolding"):
            RepositoryProfile.from_yaml({
                "name": "legacy",
                "build_variants": [{"name": "d", "match_prefix": "", "stages": []}],
            })

    def test_scaffolding_selected_must_be_in_supported(self):
        """§1.3 load-time invariant: selected ∈ supported, else fail fast."""
        with pytest.raises(ValueError, match="not in supported"):
            RepositoryProfile.from_yaml({
                "name": "x",
                "build_variants": [{"name": "d", "match_prefix": "", "stages": []}],
                "scaffolding": {"supported": ["aclnn"], "selected": "torch_op"},
            })

    def test_scaffolding_rejects_unknown_kind(self):
        """Unknown protocol name in supported/selected → load-time error."""
        with pytest.raises(ValueError, match="unknown kind"):
            RepositoryProfile.from_yaml({
                "name": "x",
                "build_variants": [{"name": "d", "match_prefix": "", "stages": []}],
                "scaffolding": {"supported": ["bogus"], "selected": "bogus"},
            })

    def test_scaffolding_selected_can_switch_within_supported(self):
        """Changing only `selected` (the single knob) is legal for any supported
        protocol — the whole-repo switch the design promises."""
        p = RepositoryProfile.from_yaml({
            "name": "cann-bench",
            "build_variants": [{"name": "d", "match_prefix": "", "stages": []}],
            "scaffolding": {"supported": ["torch_op", "aclnn", "pybind"],
                            "selected": "pybind"},
        })
        assert p.scaffolding_kind() == "pybind"

    def test_shipped_cann_bench_profile_selects_torch_op(self):
        """The real cann-bench.yaml declares scaffolding=torch_op (regression:
        catches an accidental drop/typo of the shipped default)."""
        from ascendc_devkit.orchestration.profile_loader import load_profile
        p = load_profile("cann-bench")
        assert "torch_op" in p.scaffolding.supported
        assert p.scaffolding_kind() == "torch_op"


class TestOpDirResolution:
    def test_fields(self):
        r = OpDirResolution(
            profile_name="omni-ops",
            repo_root="/home/x/omni-ops",
            rel_op_dir="inference/ascendc/src/ops-transformer/posembedding/ai_infra_rope",
            full_op_name="ai_infra_rope",
            op_name="rope",
            variant_name="inference",
            confidence="matched",
        )
        assert r.profile_name == "omni-ops"
        assert r.op_name == "rope"
        assert r.confidence == "matched"


class TestBuildResult:
    def test_passed(self):
        r = BuildResult(passed=True, stdout="ok")
        assert r.passed
        assert r.artifacts == []

    def test_failed(self):
        r = BuildResult(passed=False, stderr="error: undefined symbol")
        assert not r.passed
        assert "undefined symbol" in r.stderr


class TestStubbedFields:
    """Verify stubbed defaults to False on all verification result types."""

    def test_build_result_stubbed_defaults_false(self):
        r = BuildResult(passed=True)
        assert r.stubbed is False

    def test_build_result_stubbed_can_be_true(self):
        r = BuildResult(passed=True, stubbed=True)
        assert r.stubbed is True

    def test_performance_result_stubbed_defaults_false(self):
        r = PerformanceResult(passed=True)
        assert r.stubbed is False

    def test_state_enable_stubbed_defaults_false(self):
        from ascendc_devkit.orchestration.kernel.state import State
        s = State()
        assert s.enable_stubbed is False

    def test_state_enable_stubbed_can_be_true(self):
        from ascendc_devkit.orchestration.kernel.state import State
        s = State(enable_stubbed=True)
        assert s.enable_stubbed is True


# —— self-evolution domain types (L4-3 + steps 10-11) ——

class TestSelfEvolutionDomainTypes:
    """DeployResult, EvalResult, AdaptResult — domain defaults + immutability."""

    def test_deploy_result_defaults(self):
        from ascendc_devkit.domain.verification import DeployResult
        r = DeployResult()
        assert r.run_package == ""
        assert r.wheel_package == ""
        assert r.smoke_passed is False
        assert r.install_path == ""
        assert r.python_path == ""

    def test_deploy_result_immutable(self):
        from ascendc_devkit.domain.verification import DeployResult
        r = DeployResult(smoke_passed=True, install_path="/tmp/o")
        assert r.smoke_passed is True
        assert r.install_path == "/tmp/o"

    def test_eval_result_defaults(self):
        from ascendc_devkit.domain.verification import EvalResult
        r = EvalResult()
        assert r.overall_score == 0.0
        assert r.pass_rate == 0.0
        assert r.compile_score == 0.0
        assert r.function_score == 0.0
        assert r.performance_score == 0.0
        assert r.num_cases == 0
        assert r.num_passed == 0
        assert r.baseline_source == ""

    def test_eval_result_immutable(self):
        from ascendc_devkit.domain.verification import EvalResult
        r = EvalResult(overall_score=85.5, num_cases=20, num_passed=18,
                       baseline_source="inherited")
        assert r.overall_score == 85.5
        assert r.num_cases == 20
        assert r.num_passed == 18
        assert r.baseline_source == "inherited"

    def test_adapt_result_defaults(self):
        from ascendc_devkit.domain.verification import AdaptResult
        r = AdaptResult()
        assert r.adapted is False
        assert r.files_modified == []
        assert r.errors == []

    def test_adapt_result_immutable(self):
        from ascendc_devkit.domain.verification import AdaptResult
        r = AdaptResult(adapted=True, files_modified=["__init__.py"],
                        errors=["e1"])
        assert r.adapted is True
        assert "__init__.py" in r.files_modified
        assert len(r.errors) == 1


class TestStateSelfEvolutionFields:
    """State fields for deploy/eval/adapt have correct defaults."""

    def test_deploy_result_default(self):
        from ascendc_devkit.orchestration.kernel.state import State
        s = State()
        assert s.deploy_result is None

    def test_eval_result_default(self):
        from ascendc_devkit.orchestration.kernel.state import State
        s = State()
        assert s.eval_result is None

    def test_codegen_manifest_default(self):
        from ascendc_devkit.orchestration.kernel.state import State
        s = State()
        assert s.codegen_manifest is None

    def test_adapt_result_default(self):
        from ascendc_devkit.orchestration.kernel.state import State
        s = State()
        assert s.adapt_result is None

    def test_from_snapshot_restores_self_evolution_fields(self):
        from ascendc_devkit.orchestration.kernel.state import State
        from ascendc_devkit.domain.verification import DeployResult, EvalResult
        s = State.from_snapshot({})
        assert s.deploy_result is None
        assert s.eval_result is None
        assert s.codegen_manifest is None
        assert s.adapt_result is None


class TestReadProtoSchema:
    """read_proto_schema 读 proto.yaml ``operator.schema``（plugin 接口 + harness 调用契约
    的共同权威）。schema 字符串与 m.def 同构，下游 parse_mdef_params 直接 parse。"""

    def test_read_gather_schema(self, tmp_path):
        proto = tmp_path / "proto.yaml"
        proto.write_text(
            "operator:\n"
            "  name: Gather\n"
            "  schema: gather(Tensor x, Tensor index, int dim=0) -> Tensor y\n"
            "  inputs:\n  - {name: x}\n",
            encoding="utf-8",
        )
        assert read_proto_schema(proto) == \
            "gather(Tensor x, Tensor index, int dim=0) -> Tensor y"

    def test_none_path(self):
        assert read_proto_schema(None) is None

    def test_missing_file(self, tmp_path):
        assert read_proto_schema(tmp_path / "nope.yaml") is None

    def test_no_schema_field(self, tmp_path):
        proto = tmp_path / "proto.yaml"
        proto.write_text("operator:\n  name: Op\n  inputs: []\n", encoding="utf-8")
        assert read_proto_schema(proto) is None

    def test_markdown_bold_not_yaml_alias(self, tmp_path):
        # 回归：Markdown ``**基本公式**：`` 触发 PyYAML ScannerError（别名锚点），
        # read_proto_schema 必须 graceful 降级 None，不得 raise。
        p = tmp_path / "desc.md"
        p.write_text("# RmsNorm\n\n**基本公式**：\n\n$$ y = x $$\n", encoding="utf-8")
        assert read_proto_schema(p) is None

    def test_read_proto_schema_directory_returns_none(self, tmp_path):
        # 回归：同 read_proto_precision_directory_returns_none —— 读失败(OSError)
        # 路径的 except 元组引用 lazy-import 的 yaml → 曾 UnboundLocalError。
        d = tmp_path / "adir"
        d.mkdir()
        assert read_proto_schema(d) is None


class TestIsScalarEntry:
    """Unit tests for the single authoritative scalar/tensor predicate (§2.5).

    Guards the 20260805-152456 Maximum RCA: ``shape: []`` (elementwise broadcast)
    is a real tensor, not a scalar — must classify False (the old
    ``_is_scalar_param`` ``shape == []`` mis-routed it into attrs, emptying
    inputs/outputs). Covers the 7-level business-semantics precedence (§1.10)."""

    def test_u1_elementwise_shape_empty_multidtype_is_tensor(self):
        # Maximum x1: shape=[] (broadcast), dtype is a multi-dtype list → tensor.
        assert is_scalar_entry(
            {"name": "x1", "shape": [], "dtype": ["bfloat16", "float16", "float32"],
             "format": "ND"}) is False

    def test_u2_elementwise_shape_empty_single_dtype_is_tensor(self):
        # Single-dtype elementwise (e.g. fp16-only Add): shape=[] → still tensor.
        # This is the case a "shape==[] + dtype反证" half-fix (option B) would miss.
        assert is_scalar_entry(
            {"name": "x", "shape": [], "dtype": ["float16"], "format": "ND"}) is False

    def test_u3_role_attr_is_scalar(self):
        assert is_scalar_entry(
            {"name": "eps", "role": "attr", "type": "float"}) is True

    def test_u4_role_tensor_is_not_scalar(self):
        assert is_scalar_entry({"name": "x", "role": "tensor"}) is False

    def test_u5_param_type_is_tensor_only(self):
        # DYNAMIC variadic keeps its place even with no shape.
        assert is_scalar_entry({"name": "x", "param_type": "DYNAMIC"}) is False

    def test_u6_output_aliasing_input_is_tensor(self):
        # in-place alias output (name ∈ input_names), no shape → tensor
        assert is_scalar_entry(
            {"name": "x"}, group="outputs", input_names={"x"}) is False

    def test_u7_format_scalar_is_scalar(self):
        # design_spec's explicit scalar format declaration.
        assert is_scalar_entry({"name": "mode", "format": "SCALAR"}) is True

    def test_u8_scalar_type_is_scalar(self):
        assert is_scalar_entry({"name": "eps", "type": "float"}) is True

    def test_u9_undecidable_kept_as_tensor_with_warning(self, caplog):
        import logging
        with caplog.at_level(logging.WARNING):
            assert is_scalar_entry({"name": "mystery"}) is False
        assert any("declares neither a tensor signal" in r.message
                   for r in caplog.records)

    def test_from_dict_elementwise_shape_empty_keeps_tensors(self):
        """Integration: OperatorSpec.from_dict must keep shape:[] tensors in
        inputs/outputs (the Maximum RCA) — not route them into attrs."""
        d = {
            "name": "Maximum",
            "inputs": [
                {"name": "x1", "shape": [], "dtype": ["float16"], "format": "ND"},
                {"name": "x2", "shape": [], "dtype": ["float16"], "format": "ND"},
            ],
            "outputs": [
                {"name": "y", "shape": [], "dtype": ["float16"], "format": "ND"},
            ],
        }
        spec = OperatorSpec.from_dict(d)
        assert [t.name for t in spec.inputs] == ["x1", "x2"]
        assert [t.name for t in spec.outputs] == ["y"]
        assert spec.attrs == {}
