"""step-58 (P81): design_target_chip authority = CLI > requirement-doc
explicit field > runtime fallback. Agent-produced constraints are NOT a chip
source.

Regresses run 20260717-070202-53f685: requirement-analyst 照搬 schema example
A5 → 凭空产 hardware constraint → _apply_design_target_chip 无条件信它 → 整个
设计按 A5 走（实际运行环境 A2、需求文档无声明）。修复后 chip 来自需求文档
顶层 YAML ``design_target_chip`` 字段（确定性解析），agent constraint 被忽略。

Guarded contract:
  1. requirement-doc top-level ``design_target_chip`` deterministically parsed
     + applied to ``state.design_target_chip`` (build consumers read this field);
  2. agent-produced constraints carrying a chip are IGNORED (防照搬 example);
  3. non-canonical chip in the doc is ignored (keep entry fallback);
  4. no doc chip → entry fallback (runtime canonical, set at dispatch) kept.

The ``Constraint`` dataclass no longer carries ``design_target_chip`` (§2.5:
chip authority 移到需求文档显式字段，旧通路 dead field 删除)。
"""

import json
import tempfile
from pathlib import Path

from ascendc_devkit.capabilities.agent.backend import AgentResult
from ascendc_devkit.domain.requirement import Requirement
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.stages.requirement import RequirementStage


def _write_req_doc(body: str) -> Path:
    f = tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False)
    f.write(body)
    f.close()
    return Path(f.name)


def _agent_result(chip_in_constraint: str | None) -> AgentResult:
    """Agent result whose requirement.json carries a hardware chip constraint —
    which must be IGNORED for chip decisions (防照搬 example)."""
    constraints = ([{"kind": "hardware", "design_target_chip": chip_in_constraint}]
                   if chip_in_constraint else [])
    return AgentResult(
        agent_name="requirement-analyst",
        status="ok",
        artifacts={
            "requirement.json": json.dumps({
                "op_name": "gelu",
                "aclnn_name": "aclnnGelu",
                "mutation_mode": "out_of_place",
                "inputs": [{"name": "x", "dtype": "fp16", "shape": ["N"]}],
                "outputs": [{"name": "y", "dtype": "fp16", "shape": ["N"]}],
                "golden_alignment": {"status": "pass", "differences": [], "notes": ""},
                "constraints": constraints,
            }),
        },
    )


def test_doc_design_target_chip_applied_to_state():
    """requirement-doc top-level design_target_chip=A5 → state.design_target_chip=A5.
    The agent constraint (A3) is IGNORED — proves chip comes from the doc, not the
    agent (run 20260717-070202-53f685 regression guard)."""
    req_path = _write_req_doc("design_target_chip: A5\noperator:\n  name: gelu\n")
    state = State(mode="new", requirement_path=req_path, design_target_chip="A2")
    new_state = RequirementStage().transition(
        state, {"agent_result": _agent_result("A3")})
    assert new_state.design_target_chip == "A5"
    assert new_state.run_context is not None
    assert new_state.run_context.hardware_target.chip == "A5"


def test_agent_constraint_not_chip_source():
    """Agent constraint A5 + doc has no chip → entry fallback (A2) kept. The agent
    constraint does NOT override — the exact 20260717-070202-53f685 failure mode."""
    req_path = _write_req_doc("operator:\n  name: gelu\n")
    state = State(mode="new", requirement_path=req_path, design_target_chip="A2")
    new_state = RequirementStage().transition(
        state, {"agent_result": _agent_result("A5")})
    assert new_state.design_target_chip == "A2"


def test_no_doc_chip_keeps_entry_fallback():
    """No chip anywhere (doc, agent) → entry fallback kept as-is."""
    req_path = _write_req_doc("operator:\n  name: gelu\n")
    state = State(mode="new", requirement_path=req_path, design_target_chip="A2")
    new_state = RequirementStage().transition(
        state, {"agent_result": _agent_result(None)})
    assert new_state.design_target_chip == "A2"


def test_unknown_doc_chip_ignored():
    """Doc design_target_chip=Z9 (non-canonical) → ignored, entry fallback kept
    (canonical 单一源 domain/chip.py；未知代际不污染)."""
    req_path = _write_req_doc("design_target_chip: Z9\noperator:\n  name: gelu\n")
    state = State(mode="new", requirement_path=req_path, design_target_chip="A2")
    new_state = RequirementStage().transition(
        state, {"agent_result": _agent_result(None)})
    assert new_state.design_target_chip == "A2"


def test_from_dict_silently_drops_unknown_constraint_fields():
    # filter_known_fields: an unknown key is dropped, not raised (§1.3 加载期校验,
    # non-fatal for the requirement DSL unknown keys).
    req = Requirement.from_dict({
        "op": {"name": "gelu"},
        "constraints": [
            {"kind": "precision", "threshold": 1e-5, "future_unknown_field": "ignored"},
        ],
    })
    pc = [c for c in req.constraints if c.kind == "precision"][0]
    assert pc.threshold == 1e-5
