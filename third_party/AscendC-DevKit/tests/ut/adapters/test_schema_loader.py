"""L6 SchemaLoader — externalized schemas travel with the flat skill (相1).

The legacy resources/schemas root + load_spec/load_contract were deleted in the
step-10 convergence (discipline #2). After the 相1 flat-skill switch, schemas load
from a single flat tree keyed by bare skill name:
  - .claude/skills/<skill>/schema/<file>.json — single producer, bare-name API
The old .claude/plugins/<plugin>/... layout and the *_from_plugin helpers were
deleted (§1.4/§2.5): there is exactly one loading path now.
"""

import pytest
from ascendc_devkit.adapters.schema.loader import SchemaLoader, SchemaNotFoundError

_INTEGRATE = "ascendc-op-design-integrate"
_REQ_SKILL = "ascendc-op-req-analysis"

def _dspec(fn, skill=_INTEGRATE):
    """Load a design schema from its producing skill's schema/ directory."""
    return SchemaLoader.load_spec_from_skill(skill, fn)


class TestLoadSpecFromSkill:
    def test_design_spec_fields(self):
        spec = _dspec("design_spec.json")
        assert spec.name == "design_spec"
        assert spec.filename == "design_spec.json"
        assert spec.kind == "spec"
        assert spec.required is True
        assert spec.required_keys == ("op_name", "mutation_mode", "inputs", "outputs")

    def test_data_flow_optional_no_keys(self):
        spec = _dspec("data_flow.json")
        assert spec.required is False
        assert spec.required_keys == ()

    def test_example_satisfies_own_schema(self):
        for fn in ("design_spec.json", "kernel_architecture.json"):
            spec = _dspec(fn)
            assert spec.validate_payload(spec.example) == []

    def test_requirement_spec_fields(self):
        spec = SchemaLoader.load_spec_from_skill(_REQ_SKILL, "requirement.json")
        assert spec.name == "requirement"
        assert spec.required_keys == ("op_name", "aclnn_name", "mutation_mode", "inputs", "outputs", "golden_alignment")
        assert spec.validate_payload(spec.example) == []

    def test_decision_log_optional_scalar_access_points_accepted(self):
        # L4 D-A5：decision_log 新增 optional scalar_access_points。
        # 守护：带该字段的合法产物必须通过 required_keys 校验（不因新增字段误拒）。
        spec = SchemaLoader.load_spec_from_skill("ascendc-op-dev-coding", "decision_log.json")
        assert spec.name == "decision_log"
        assert spec.required_keys == ("key_decisions", "known_issues", "assumptions")
        payload = {
            "key_decisions": [{"decision": "选择双缓冲", "reason": "UB 有限", "constraints": []}],
            "known_issues": [],
            "assumptions": [],
            "scalar_access_points": [
                {
                    "location": "op_kernel/unique.h:291 (Stage1LocalSort)",
                    "usage": "主循环 GM GetValue 搬送",
                    "reason": "有 DataCopy 等价物 → 理由不成立，应触发 AR-1 fail 判定（LLM 执行层）",
                    "reference": "tiling_results.json buffer_kernel.kernel_structure",
                }
            ],
        }
        assert spec.validate_payload(payload) == []

    def test_diagnose_fix_code_log_optional_fallback_masked_accepted(self):
        # fix-diagnose-merge: fix_code_log 现归 precision_diagnose.json（diagnose 自实施）。
        # P3 减法: arch_gaps 已删, required_keys 只剩 diagnose_done。
        # 守护：带 fix_code_log.fallback_masked 的合法产物必须通过 required_keys 校验
        # （不因新增子字段误拒）。
        spec = SchemaLoader.load_spec_from_skill("ascendc-precision-diagnose", "precision_diagnose.json")
        assert spec.name == "precision_diagnose"
        assert spec.required_keys == ("diagnose_done",)
        payload = {
            "diagnose_done": True,
            "fix_code_log": {
                "verification_result": "confirmed",
                "tried_fixes": [{"fix_desc": "host fallback at::_unique2", "result": "succeeded"}],
                "applied_fix": "host fallback for N>65536",
                "side_effect_cases": [],
                "fallback_masked": True,
            }
        }
        assert spec.validate_payload(payload) == []


class TestLoadContract:
    def test_design_contract_order_preserved(self):
        c = SchemaLoader.load_contract_from_skill(_INTEGRATE, [
            "design_spec.json", "tiling_strategy.json",
            "kernel_architecture.json", "data_flow.json"])
        assert [s.name for s in c.specs()] == [
            "design_spec", "tiling_strategy", "kernel_architecture", "data_flow"]


class TestFailFast:
    def test_missing_file_raises(self):
        with pytest.raises(SchemaNotFoundError):
            _dspec("does_not_exist.json")

    def test_missing_skill_raises(self):
        with pytest.raises(SchemaNotFoundError):
            SchemaLoader.load_spec_from_skill("nope", "x.json")

    def test_cache_returns_same_object(self):
        a = _dspec("design_spec.json")
        b = _dspec("design_spec.json")
        assert a is b


class TestPromptRenderingStable:
    def test_design_spec_block_pins_example(self):
        from ascendc_devkit.orchestration.stages.design_substages import SynthesizeStage
        spec = SynthesizeStage().artifact_contract().by_name("design_spec")
        block = spec.to_prompt_block()
        assert "design_spec.json" in block
        assert '"op_name": "算子名"' in block
        assert '"format": "ND"' in block
