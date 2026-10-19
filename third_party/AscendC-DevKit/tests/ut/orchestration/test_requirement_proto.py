"""P69 Flow A: requirement stage re-reads proto.yaml to recover precision_thresholds
that the agent's requirement.json drops (agent schema = op_name/inputs/outputs only).

proto is the single source of precision tolerance (cann-bench artifact). The
requirement agent faithfully extracts inputs/outputs but has no slot for
precision_thresholds, so ``RequirementStage.transition`` deterministically
re-reads the proto (``state.requirement_path``) and patches the recovered
thresholds + per-output compare flags onto the agent-built op_spec.

Guards the DQ (dynamic_quant) 冤杀 root cause: proto declares ``{int8: 1.0}``
(legitimate ±1 quant diff at .5 boundary), but devkit's old hardcoded ``1e-2``
mis-killed it. The patch here makes op_spec carry proto's ``{int8: 1.0}`` so the
runner (P69 改动4) tolerates the ±1 diff.
"""

import json
import tempfile
from pathlib import Path

from ascendc_devkit.capabilities.agent.backend import AgentResult
from ascendc_devkit.domain.operator import OperatorSpec, TensorSpec
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.stages.requirement import RequirementStage


# DQ-flavored proto.yaml (cann-bench artifact shape): precision_thresholds nested
# under top-level ``operator:``, inputs/outputs dtype as lists (multi-dtype).
_PROTO_YAML = """\
operator:
  name: DynamicQuant
  precision_thresholds:
    int8: 1.0
  inputs:
  - name: x
    dtype:
    - float16
    - bfloat16
  outputs:
  - name: y
    dtype:
    - int8
  - name: scale
    dtype:
    - float32
    compare: false
"""


def _write_proto(text=_PROTO_YAML, suffix=".yaml"):
    f = tempfile.NamedTemporaryFile(suffix=suffix, mode="w", delete=False)
    f.write(text)
    f.close()
    return Path(f.name)


def _agent_req():
    """Agent's requirement.json — schema is
    op_name/aclnn_name/mutation_mode/inputs/outputs/golden_alignment;
    precision_thresholds is NOT echoed (the drop P69 fixes). dtype is scalar (agent form)."""
    return json.dumps({
        "op_name": "DynamicQuant",
        "aclnn_name": "aclnnDynamicQuant",
        "mutation_mode": "out_of_place",
        "inputs": [{"name": "x", "dtype": "fp16", "shape": ["N"]}],
        "outputs": [
            {"name": "y", "dtype": "int8", "shape": ["N"]},
            {"name": "scale", "dtype": "fp32", "shape": ["N"]},
        ],
        "golden_alignment": {"status": "pass", "differences": [], "notes": ""},
        "constraints": [],
    })


# --- _attach_proto (static helper) ---

def test_attach_proto_patches_thresholds_from_operator_block():
    spec = OperatorSpec(name="DynamicQuant", outputs=[TensorSpec(name="y", dtype="int8")])
    out = RequirementStage._attach_proto(spec, _write_proto())
    assert out.precision_thresholds == {"int8": 1.0}


def test_attach_proto_preserves_agent_scalar_dtype():
    """Agent op_spec has scalar dtype 'fp16'; proto's dtype is a list. _attach_proto
    patches only thresholds/compare — it must NOT rebuild inputs/outputs from proto
    (which would clobber the richer agent form with proto's list-dtype shape)."""
    spec = OperatorSpec(
        name="DynamicQuant",
        inputs=[TensorSpec(name="x", dtype="fp16", shape=["N"])],
    )
    out = RequirementStage._attach_proto(spec, _write_proto())
    assert out.inputs[0].dtype == "fp16"  # untouched, NOT proto's [float16,bfloat16]


def test_attach_proto_transfers_output_compare_false():
    spec = OperatorSpec(
        name="DynamicQuant",
        outputs=[
            TensorSpec(name="y", dtype="int8"),
            TensorSpec(name="scale", dtype="fp32"),
        ],
    )
    out = RequirementStage._attach_proto(spec, _write_proto())
    assert out.outputs[0].compare is None   # y: not set in proto
    assert out.outputs[1].compare is False  # scale: proto compare:false


# TopK-flavored proto: idx 输出声明 compare:false + index_gather（tie 顺序无关校验）
_TOPK_PROTO_YAML = """\
operator:
  name: TopK
  inputs:
  - name: x
    dtype:
    - float16
  outputs:
  - name: y
    dtype:
    - float16
  - name: idx
    dtype:
    - int64
    compare: false
    index_gather:
      input: x
      dim_attr: dim
      value_output: y
"""


def test_attach_proto_transfers_output_index_gather():
    spec = OperatorSpec(
        name="TopK",
        inputs=[TensorSpec(name="x", dtype="fp16", shape=["N"])],
        outputs=[
            TensorSpec(name="y", dtype="fp16", shape=["K"]),
            TensorSpec(name="idx", dtype="int64", shape=["K"]),
        ],
    )
    out = RequirementStage._attach_proto(spec, _write_proto(_TOPK_PROTO_YAML))
    assert out.outputs[1].compare is False
    assert out.outputs[1].index_gather == {
        "input": "x", "dim_attr": "dim", "value_output": "y",
    }
    assert out.outputs[0].index_gather is None  # y: 未声明


def test_attach_proto_missing_thresholds_returns_unchanged():
    path = _write_proto("operator:\n  name: gelu\n")  # no precision_thresholds
    spec = OperatorSpec(name="gelu")
    out = RequirementStage._attach_proto(spec, path)
    assert out.precision_thresholds is None


def test_attach_proto_none_path_unchanged():
    spec = OperatorSpec(name="gelu")
    assert RequirementStage._attach_proto(spec, None) is spec


def test_attach_proto_nonexistent_path_unchanged():
    spec = OperatorSpec(name="gelu")
    assert RequirementStage._attach_proto(spec, Path("/nonexistent/proto.yaml")) is spec


def test_attach_proto_prose_md_unchanged():
    """prose .md requirement (interpreted by the agent, not machine-parsed) → no
    precision_thresholds to extract; op_spec unchanged, not a crash."""
    path = _write_proto("# free-text requirement\nno yaml here", suffix=".md")
    spec = OperatorSpec(name="gelu")
    out = RequirementStage._attach_proto(spec, path)
    assert out.precision_thresholds is None


# --- transition end-to-end (DQ冤杀 root cause) ---

def test_transition_recovers_proto_thresholds_agent_dropped():
    """End-to-end P69: agent's requirement.json carries no precision_thresholds,
    but proto.yaml (state.requirement_path) declares {int8: 1.0}. transition must
    patch it onto op_spec — exactly the DQ冤杀 path."""
    proto_path = _write_proto()
    state = State(mode="new", requirement_path=proto_path)
    agent_result = AgentResult(
        agent_name="requirement-analyst",
        status="ok",
        artifacts={"requirement.json": _agent_req()},
    )
    new_state = RequirementStage().transition(state, {"agent_result": agent_result})
    op_spec = new_state.requirement.op_spec
    assert op_spec.precision_thresholds == {"int8": 1.0}
    assert op_spec.outputs[1].compare is False  # scale: proto compare:false
    assert op_spec.inputs[0].dtype == "fp16"    # agent form preserved


def test_transition_without_proto_path_still_parses_agent_req():
    """No proto path → _attach_proto no-ops; agent's requirement still parses
    (precision_thresholds=None, downstream uses default table + explicit marker)."""
    state = State(mode="new", requirement_path=None)
    agent_result = AgentResult(
        agent_name="requirement-analyst",
        status="ok",
        artifacts={"requirement.json": _agent_req()},
    )
    new_state = RequirementStage().transition(state, {"agent_result": agent_result})
    assert new_state.requirement.op_spec.precision_thresholds is None
    assert new_state.requirement.op_spec.name == "DynamicQuant"
