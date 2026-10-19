"""TensorList 入口契约——A 方案：proto 结构信号确定性派生 is_list/param_type=DYNAMIC。

根因（precision-tensorlist-harness-contract）：requirement 把 Tensor[] 输入标
param_type=REQUIRED（应 DYNAMIC）→ runner 的 DYNAMIC 闸门永不触发 → list-of-lists
用例全被 PD-CONTRACT 拒 → upstream halt（foreach 类算子历史根因）。

修复：requirement 阶段从 proto.yaml 结构信号（operator.inputs[].is_list /
operator.schema 签名 Tensor[]）确定性派生 is_list + param_type=DYNAMIC，外加
加载期交叉校验（is_list=true 但 param_type≠DYNAMIC → schema_violation 重试）。
"""

import json
import tempfile
from pathlib import Path

from ascendc_devkit.capabilities.agent.backend import AgentResult
from ascendc_devkit.domain.requirement import read_proto_tensorlist_inputs
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.stages.requirement import RequirementStage

_STAGE = RequirementStage()


def _write(path_text: str, suffix: str = ".yaml") -> Path:
    f = tempfile.NamedTemporaryFile(suffix=suffix, mode="w", delete=False)
    f.write(path_text)
    f.close()
    return Path(f.name)


# —— domain 层：read_proto_tensorlist_inputs 两信号 ——

def test_read_from_explicit_is_list_field():
    p = _write("operator:\n  name: Op\n  inputs:\n  - name: x\n    is_list: true\n  - name: y\n")
    assert read_proto_tensorlist_inputs(p) == ["x"]


def test_read_from_schema_tensorlist_signature():
    p = _write("operator:\n  name: Op\n  schema: foreach_norm(Tensor[] x, float scalar) -> Tensor[] y\n")
    assert read_proto_tensorlist_inputs(p) == ["x"]


def test_read_merges_both_signals_and_dedupes():
    p = _write(
        "operator:\n"
        "  name: Op\n"
        "  inputs:\n"
        "  - name: a\n"
        "    is_list: true\n"
        "  schema: op(Tensor[] a, Tensor[] b) -> Tensor[] y\n")
    assert read_proto_tensorlist_inputs(p) == ["a", "b"]


def test_read_none_or_missing_returns_empty():
    assert read_proto_tensorlist_inputs(None) == []
    assert read_proto_tensorlist_inputs("/nonexistent/proto.yaml") == []
    p = _write("operator:\n  name: Op\n  inputs:\n  - name: x\n")
    assert read_proto_tensorlist_inputs(p) == []


def test_read_markdown_bold_not_yaml_alias():
    # 回归：cann-bench desc.md 的 ``**基本公式**：`` 触发 PyYAML ScannerError
    # （Markdown 粗体被误判为别名锚点），read_proto_tensorlist_inputs 必须
    # graceful 降级 []，不得 raise（否则 requirement 阶段管线中止）。
    p = _write("# RmsNorm\n\n**基本公式**：\n\n$$ y = x $$\n", suffix=".md")
    assert read_proto_tensorlist_inputs(p) == []


def test_read_directory_returns_empty():
    # 回归：read_text 先抛 OSError 时 except 元组里的 yaml.YAMLError 曾引用
    # lazy-import 未绑定局部名 → UnboundLocalError。上提 import 后须优雅返回 []。
    d = Path(tempfile.mkdtemp())
    assert read_proto_tensorlist_inputs(d) == []


# —— stage 层：_derive_tensorlist_param_type 主修复 ——

def test_derive_rewrites_required_to_dynamic():
    req = {
        "op_name": "Op",
        "inputs": [{"name": "x", "dtype": "fp16", "param_type": "REQUIRED"}],
        "outputs": [{"name": "y", "dtype": "fp16", "param_type": "REQUIRED"}],
    }
    p = _write("operator:\n  name: Op\n  schema: op(Tensor[] x) -> Tensor[] y\n")
    RequirementStage._derive_tensorlist_param_type(req, p)
    assert req["inputs"][0]["param_type"] == "DYNAMIC"
    assert req["inputs"][0]["is_list"] is True


def test_derive_keeps_agent_correct_dynamic():
    req = {
        "op_name": "Op",
        "inputs": [{"name": "x", "dtype": "fp16", "param_type": "DYNAMIC", "is_list": True}],
        "outputs": [{"name": "y", "dtype": "fp16", "param_type": "REQUIRED"}],
    }
    p = _write("operator:\n  name: Op\n  schema: op(Tensor[] x) -> Tensor[] y\n")
    RequirementStage._derive_tensorlist_param_type(req, p)
    assert req["inputs"][0]["param_type"] == "DYNAMIC"
    assert req["inputs"][0]["is_list"] is True


def test_derive_does_not_touch_non_list_inputs():
    req = {
        "op_name": "Op",
        "inputs": [{"name": "a", "dtype": "fp16", "param_type": "REQUIRED"}],
        "outputs": [{"name": "y", "dtype": "fp16", "param_type": "REQUIRED"}],
    }
    p = _write("operator:\n  name: Op\n  schema: op(Tensor a) -> Tensor y\n")
    RequirementStage._derive_tensorlist_param_type(req, p)
    assert req["inputs"][0]["param_type"] == "REQUIRED"
    assert req["inputs"][0].get("is_list") is None


def test_derive_no_proto_no_change():
    req = {
        "op_name": "Op",
        "inputs": [{"name": "x", "dtype": "fp16", "param_type": "REQUIRED"}],
        "outputs": [{"name": "y", "dtype": "fp16", "param_type": "REQUIRED"}],
    }
    RequirementStage._derive_tensorlist_param_type(req, None)
    assert req["inputs"][0]["param_type"] == "REQUIRED"


# —— stage 层：_validate_tensorlist_param_type 交叉校验 ——

def test_validate_list_with_required_is_violation():
    req = {
        "op_name": "Op",
        "inputs": [{"name": "x", "dtype": "fp16", "param_type": "REQUIRED", "is_list": True}],
        "outputs": [{"name": "y", "dtype": "fp16", "param_type": "REQUIRED"}],
    }
    errors = RequirementStage._validate_tensorlist_param_type(req)
    assert len(errors) == 1
    assert "DYNAMIC" in errors[0]


def test_validate_list_with_dynamic_consistent():
    req = {
        "op_name": "Op",
        "inputs": [{"name": "x", "dtype": "fp16", "param_type": "DYNAMIC", "is_list": True}],
        "outputs": [{"name": "y", "dtype": "fp16", "param_type": "REQUIRED"}],
    }
    assert RequirementStage._validate_tensorlist_param_type(req) == []


def test_validate_string_true_normalized():
    req = {
        "op_name": "Op",
        "inputs": [{"name": "x", "dtype": "fp16", "param_type": "REQUIRED", "is_list": "true"}],
        "outputs": [{"name": "y", "dtype": "fp16", "param_type": "REQUIRED"}],
    }
    errors = RequirementStage._validate_tensorlist_param_type(req)
    assert len(errors) == 1


def test_validate_non_list_ignored():
    req = {
        "op_name": "Op",
        "inputs": [{"name": "x", "dtype": "fp16", "param_type": "REQUIRED"}],
        "outputs": [{"name": "y", "dtype": "fp16", "param_type": "REQUIRED"}],
    }
    assert RequirementStage._validate_tensorlist_param_type(req) == []
    assert RequirementStage._validate_tensorlist_param_type(None) == []


# —— 集成：transition 全链路（agent 产 REQUIRED + proto 声明 TensorList → DYNAMIC） ——

def test_transition_derives_dynamic_from_proto():
    req_path = _write(
        "operator:\n  name: Op\n  schema: foreach_norm(Tensor[] x, float scalar) -> Tensor[] y\n")
    state = State(mode="new", requirement_path=req_path, design_target_chip="A2")
    ar = AgentResult(
        agent_name="requirement-analyst",
        status="ok",
        artifacts={"requirement.json": json.dumps({
            "op_name": "Op",
            "aclnn_name": "aclnnOp",
            "mutation_mode": "out_of_place",
            "inputs": [{"name": "x", "dtype": "fp16", "shape": ["L"], "param_type": "REQUIRED"}],
            "outputs": [{"name": "y", "dtype": "fp16", "shape": ["L"], "param_type": "REQUIRED"}],
            "attrs": [{"name": "scalar", "type": "float", "default": None}],
            "golden_alignment": {"status": "pass", "differences": [], "notes": ""},
        })},
    )
    new_state = RequirementStage().transition(state, {"agent_result": ar})
    assert new_state.last_error is None
    assert new_state.requirement is not None
    x_spec = new_state.requirement.op_spec.inputs[0]
    assert x_spec.param_type == "DYNAMIC"


def test_transition_agent_still_wrong_is_list_required_schema_violation():
    """agent 手写 is_list=true 却标 param_type=REQUIRED，且 proto 未声明 → 拒绝。"""
    req_path = _write("operator:\n  name: Op\n  schema: op(Tensor x) -> Tensor y\n")
    state = State(mode="new", requirement_path=req_path, design_target_chip="A2")
    ar = AgentResult(
        agent_name="requirement-analyst",
        status="ok",
        artifacts={"requirement.json": json.dumps({
            "op_name": "Op",
            "aclnn_name": "aclnnOp",
            "mutation_mode": "out_of_place",
            "inputs": [{"name": "x", "dtype": "fp16", "shape": ["N"], "param_type": "REQUIRED", "is_list": True}],
            "outputs": [{"name": "y", "dtype": "fp16", "shape": ["N"], "param_type": "REQUIRED"}],
            "golden_alignment": {"status": "pass", "differences": [], "notes": ""},
        })},
    )
    new_state = RequirementStage().transition(state, {"agent_result": ar})
    assert new_state.last_error is not None
    assert new_state.last_error.error_type == "schema_violation"
    assert "DYNAMIC" in new_state.last_error.message
