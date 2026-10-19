"""A3 (step-2 follow-up) — preflight input/topology compatibility (§9.2.1).

Fail fast when a user input's intent contradicts the workflow topology:
  - --detailed-design (short-circuits into codegen) on a workflow with no
    codegen stage (e.g. the SE workflow) is meaningless → error.

Note (13 E4): the '--golden needs verify' rule is GONE — golden is now a
full-chain reference required declaratively via the consuming stage's
`requires` (_preflight_user_inputs), not a topology concern. The declarative
required/optional behavior lives in test_golden_required_declarative.py.
"""

from pathlib import Path
import pytest
from ascendc_devkit.application.dispatcher import (
    _preflight_input_topology, _preflight_mode_exclusivity)
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.registry import get_workflow
from ascendc_devkit.cli.exit_codes import EX_USAGE


@pytest.fixture
def dd(tmp_path):
    p = tmp_path / "detailed.md"
    p.write_text("# detailed")
    return p


@pytest.fixture
def golden(tmp_path):
    p = tmp_path / "golden.py"
    p.write_text("# golden")
    return p


class TestDetailedDesignTopology:
    def test_detailed_design_on_se_workflow_blocks(self, dd):
        wf = get_workflow("generate_ascendc_se")  # no codegen
        state = State(mode="new", detailed_design_path=dd, non_interactive=True)
        code = _preflight_input_topology(state, wf)
        assert code == EX_USAGE

    def test_detailed_design_on_full_workflow_ok(self, dd):
        wf = get_workflow("generate_ascendc")  # has codegen
        state = State(mode="new", detailed_design_path=dd, non_interactive=True)
        assert _preflight_input_topology(state, wf) is None

    def test_detailed_design_on_dev_workflow_ok(self, dd):
        wf = get_workflow("generate_ascendc_dev")  # has codegen
        state = State(mode="new", detailed_design_path=dd, non_interactive=True)
        assert _preflight_input_topology(state, wf) is None


class TestGoldenTopologyRemoved:
    """13 E4: the golden→verify topology rule is deleted. golden is no longer a
    topology concern (it is required declaratively — see
    test_golden_required_declarative.py), so topology never blocks it."""

    def test_golden_on_se_workflow_not_blocked(self, golden):
        wf = get_workflow("generate_ascendc_se")
        state = State(mode="new", golden_path=golden, non_interactive=True)
        assert _preflight_input_topology(state, wf) is None

    def test_golden_on_full_workflow_not_blocked(self, golden):
        wf = get_workflow("generate_ascendc")
        state = State(mode="new", golden_path=golden, non_interactive=True)
        assert _preflight_input_topology(state, wf) is None


class TestNoInputsNoBlock:
    def test_neither_input_passes_on_se(self):
        wf = get_workflow("generate_ascendc_se")
        state = State(mode="new", non_interactive=True)
        assert _preflight_input_topology(state, wf) is None


class TestDispatchIntegration:
    def test_dispatch_se_with_detailed_design_returns_usage(self, dd, golden, tmp_path):
        from ascendc_devkit.application.dispatcher import dispatch
        code = dispatch({
            "mode": "new", "workflow": "generate_ascendc_se",
            "op_name": "gelu", "repo_profile": "omni-ops",
            "detailed_design_path": str(dd),
            # golden three params supplied so _preflight_user_inputs passes and
            # the topology rule (--detailed-design needs codegen) is the blocker.
            "golden_path": str(golden), "golden_entry": "gelu",
            "golden_input_type": "torch",
            "non_interactive": True, "output_root": str(tmp_path),
        })
        assert code == EX_USAGE


class _StubWorkflow:
    """Minimal workflow stub: only .name + .flat_stages() are read by preflight."""

    def __init__(self, name: str, stage_names: list[str]):
        self.name = name
        self._leaves = [type("_Leaf", (), {"name": n})() for n in stage_names]

    def flat_stages(self, design_target_chip: str = ""):
        return self._leaves


class TestModeExclusivity:
    """--detailed-design (reuse an existing detailed design) is mutually
    exclusive with a from-scratch design workflow (requirement → general-design
    → detailed-design generation). 'design the requirement, then graft on a
    separate detailed design' has no legitimate scenario (L1 P1/R1, step-55).
    Loaded-time reject via _preflight_mode_exclusivity — zero agent token."""

    def test_self_evolve_op_with_detailed_design_blocks(self, dd):
        wf = get_workflow("self_evolve_op")
        state = State(mode="new", detailed_design_path=dd, non_interactive=True)
        assert _preflight_mode_exclusivity(state, wf) == EX_USAGE

    def test_generate_ascendc_with_detailed_design_blocks(self, dd):
        wf = get_workflow("generate_ascendc")
        state = State(mode="new", detailed_design_path=dd, non_interactive=True)
        assert _preflight_mode_exclusivity(state, wf) == EX_USAGE

    def test_generate_ascendc_dev_with_detailed_design_blocks(self, dd):
        wf = get_workflow("generate_ascendc_dev")
        state = State(mode="new", detailed_design_path=dd, non_interactive=True)
        assert _preflight_mode_exclusivity(state, wf) == EX_USAGE

    def test_from_scratch_workflow_without_detailed_design_ok(self):
        # No --detailed-design → normal generation, not reuse → pass.
        wf = get_workflow("generate_ascendc")
        state = State(mode="new", non_interactive=True)
        assert _preflight_mode_exclusivity(state, wf) is None

    def test_reuse_only_workflow_with_detailed_design_ok(self, dd):
        # A workflow with no from-scratch design stage (a pure codegen reuse
        # entry) + --detailed-design is legitimate reuse → pass. This is the
        # future home of the reuse workflow (R1).
        wf = _StubWorkflow(name="reuse_only", stage_names=["codegen"])
        state = State(mode="new", detailed_design_path=dd, non_interactive=True)
        assert _preflight_mode_exclusivity(state, wf) is None
