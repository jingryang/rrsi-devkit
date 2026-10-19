"""in-place/out-of-place 交付契约：mutation_mode 加载期自洽校验（§1.3）。

requirement.json 的 mutation_mode 须与 inputs/outputs 同名关系自洽：
  in_place    ⇔ 存在与 input 同名的 output（read_write 状态张量原地更新）；
  out_of_place ⇔ output 与 input 不同名（独立输出）。
不符 → schema_violation 重试（防 codegen 把 out-of-place 返回交付做错、
也防 requirement 把 in-place 语义算子误标 out_of_place）。

背景见 docs/plan/self-evolution/inplace-outplace-delivery-contract/。
"""

import json
import tempfile
from pathlib import Path

from ascendc_devkit.capabilities.agent.backend import AgentResult
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.stages.requirement import RequirementStage

_STAGE = RequirementStage()


def _req(mutation_mode, input_names, output_names):
    return {
        "op_name": "op",
        "mutation_mode": mutation_mode,
        "inputs": [{"name": n, "dtype": "int64", "shape": ["N"]} for n in input_names],
        "outputs": [{"name": n, "dtype": "int64", "shape": ["N"]} for n in output_names],
    }


# —— 单元测试：_validate_mutation_mode_consistency 全分支 ——

def test_in_place_with_alias_consistent():
    errors = _STAGE._validate_mutation_mode_consistency(
        _req("in_place", ["x", "y"], ["x", "y"]))
    assert errors == []


def test_in_place_partial_alias_consistent():
    # advance_step_v2 形态：4 个同名状态张量 + 若干纯输入
    errors = _STAGE._validate_mutation_mode_consistency(
        _req("in_place", ["a", "b", "c", "d", "e"], ["a", "b", "c", "d"]))
    assert errors == []


def test_in_place_without_alias_is_violation():
    errors = _STAGE._validate_mutation_mode_consistency(
        _req("in_place", ["x"], ["y"]))
    assert len(errors) == 1
    assert "in_place" in errors[0]


def test_out_of_place_without_alias_consistent():
    errors = _STAGE._validate_mutation_mode_consistency(
        _req("out_of_place", ["x"], ["y"]))
    assert errors == []


def test_out_of_place_with_alias_is_violation():
    errors = _STAGE._validate_mutation_mode_consistency(
        _req("out_of_place", ["x", "y"], ["x"]))
    assert len(errors) == 1
    assert "out_of_place" in errors[0]


def test_missing_mutation_mode_skipped():
    # 必填由 required_keys 管；自洽校验不重复报
    errors = _STAGE._validate_mutation_mode_consistency(
        {"inputs": [{"name": "x"}], "outputs": [{"name": "y"}]})
    assert errors == []


def test_invalid_mutation_mode_skipped():
    errors = _STAGE._validate_mutation_mode_consistency(
        _req("bogus", ["x"], ["y"]))
    assert errors == []


def test_non_dict_payload_skipped():
    assert _STAGE._validate_mutation_mode_consistency(None) == []
    assert _STAGE._validate_mutation_mode_consistency("str") == []


# —— 集成测试：transition 的 parse 后自洽校验 → schema_violation ——

def _write_req_doc(body: str) -> Path:
    f = tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False)
    f.write(body)
    f.close()
    return Path(f.name)


def test_transition_in_place_without_alias_schema_violation():
    """in_place 但 outputs 与 inputs 无同名 → 加载期自洽校验 → schema_violation 重试。"""
    req_path = _write_req_doc("operator:\n  name: op\n")
    state = State(mode="new", requirement_path=req_path, design_target_chip="A2")
    ar = AgentResult(
        agent_name="requirement-analyst",
        status="ok",
        artifacts={"requirement.json": json.dumps({
            "op_name": "op",
            "mutation_mode": "in_place",
            "inputs": [{"name": "x", "dtype": "int64", "shape": ["N"]}],
            "outputs": [{"name": "y", "dtype": "int64", "shape": ["N"]}],
        })},
    )
    new_state = RequirementStage().transition(state, {"agent_result": ar})
    assert new_state.last_error is not None
    assert new_state.last_error.error_type == "schema_violation"
    assert "in_place" in new_state.last_error.message
