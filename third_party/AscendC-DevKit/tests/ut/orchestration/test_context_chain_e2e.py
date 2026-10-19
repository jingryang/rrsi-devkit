"""§P7.5 / step-10 F2 — end-to-end cross-stage context chain guard.

The P1 failure mode was a design agent running "context-free" (general-design-generator
hallucinated layernorm because the requirement never reached it; anchor-consistency
ran without tiling_results). Step-10 F2: upstream products are now MATERIALIZED
AS FILES in the working dir (not JSON injected into the prompt). This test still
pins that the old '## 上游输入' prompt-injection block is GONE, and that operator
identity stays in the prompt (lightweight _operator_section, not suppressed).
"""

from __future__ import annotations

import pytest

from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.kernel.action import SpawnAgent
from ascendc_devkit.orchestration.stages import design_substages as ds
from ascendc_devkit.domain.requirement import Requirement
from ascendc_devkit.domain.operator import OperatorSpec, TensorSpec


def _full_state():
    req = Requirement(op_spec=OperatorSpec(
        name="ROPE_REQ_MARK",
        inputs=[TensorSpec(name="x", dtype="fp16", shape=["B", "S", "D"])]))
    return State.empty().with_updates(
        op_name="ROPE_REQ_MARK",
        requirement=req,
        general_design={"k": "GD_MARK"},
        template_division={"templates": [{"name": "T1"}], "k": "TD_MARK"},
        tiling_results={"T1": {"split": {"k": "SPLIT_MARK"},
                               "buffer_kernel": {"k": "BK_MARK"},
                               "precision_perf": {"k": "PP_MARK"}}},
        design_spec={"k": "DS_MARK"},
        tiling_strategy={"k": "TS_MARK"},
        kernel_architecture={"k": "KA_MARK"},
        design_doc={"markdown": "DOC_MARK"})


# Every design substage that spawns an agent.
_SPAWN_SUBSTAGES = [
    ("general-design-generator", lambda: ds.GeneralDesignStage()),
    ("template-division", lambda: ds.TemplateDivisionStage()),
    ("tiling", lambda: ds.TilingStage(template={"name": "T1"})),
    ("synthesize", lambda: ds.SynthesizeStage()),
]


@pytest.mark.parametrize("name,factory", _SPAWN_SUBSTAGES)
def test_no_upstream_injection_in_prompt(name, factory):
    """F2: the old '## 上游输入' prompt-injection block must be GONE from every
    design substage's spawn prompt. Upstream products travel as files (materialized
    by the base _DesignSubstage.actions()). Failure means a prompt is still injecting
    JSON payloads instead of pointing the agent at working-dir files."""
    stage = factory()
    state = _full_state()
    spawn = next((a for a in stage.actions(state, 1)
                  if isinstance(a, SpawnAgent)), None)
    assert spawn is not None, f"{name} did not spawn an agent"
    assert "## 上游输入" not in spawn.prompt, (
        f"{name}: '## 上游输入' still injected — F2 requires file materialization")
    # Operator identity (lightweight) IS still in the prompt
    assert "ROPE_REQ_MARK" in spawn.prompt, (
        f"{name}: operator identity must still be in the prompt")


def test_gd_generate_gets_requirement_not_blank():
    stage = ds.GeneralDesignStage()
    spawn = next(a for a in stage.actions(_full_state(), 1)
                 if isinstance(a, SpawnAgent))
    assert "ROPE_REQ_MARK" in spawn.prompt
