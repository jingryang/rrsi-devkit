"""B3 (14 L4) — golden declared-required via stage `requires` +
`_USER_INPUT_FIELDS` (13 E6), golden→verify topology rule removed (13 E4),
three-param bundle check (13 E3). D-1 (定案 a): design (general-design) also
requires golden, so generate_ascendc_se requires golden too.

Uses a fake workflow/stage to isolate the preflight logic from unrelated
required fields, plus real workflows for the topology + SE-requires-golden
behavior.
"""

from pathlib import Path
from unittest import mock

import pytest

from ascendc_devkit.application.dispatcher import (
    _preflight_user_inputs, _preflight_input_topology, _USER_INPUT_FIELDS,
)
from ascendc_devkit.cli.exit_codes import EX_USAGE
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.registry import get_workflow
from ascendc_devkit.domain.contract import StageIOContract


class _FakeStage:
    def __init__(self, requires):
        self.name = "fake"
        self._requires = requires

    def input_contract(self):
        return StageIOContract(requires=list(self._requires))


class _FakeWorkflow:
    def __init__(self, requires, name="fake_wf"):
        self.name = name
        self._stage = _FakeStage(requires)

    def flat_stages(self, design_target_chip: str = ""):
        return [self._stage]


def _state(**kw):
    base = dict(mode="new", non_interactive=True)
    base.update(kw)
    return State.empty().with_updates(**base)


class TestGoldenDeclaredRequired:
    def test_user_input_fields_include_golden_three(self):
        assert "golden_path" in _USER_INPUT_FIELDS
        assert "golden_entry" in _USER_INPUT_FIELDS
        assert "golden_input_type" in _USER_INPUT_FIELDS

    def test_stage_requiring_golden_makes_three_required(self):
        wf = _FakeWorkflow(requires=["golden_path"])
        _, code = _preflight_user_inputs(_state(), wf)
        assert code == EX_USAGE

    def test_golden_three_complete_passes(self, tmp_path):
        wf = _FakeWorkflow(requires=["golden_path"])
        g = tmp_path / "g.py"
        g.write_text("# g")
        state = _state(golden_path=g, golden_entry="exp",
                       golden_input_type="torch")
        _, code = _preflight_user_inputs(state, wf)
        assert code is None

    def test_golden_path_without_entry_blocks(self, tmp_path):
        # golden_path present, entry/input_type absent → bundle incomplete.
        wf = _FakeWorkflow(requires=["golden_path"])
        g = tmp_path / "g.py"
        g.write_text("# g")
        _, code = _preflight_user_inputs(_state(golden_path=g), wf)
        assert code == EX_USAGE

    def test_golden_entry_without_path_blocks(self):
        # Partial (entry present, path absent) → bundle incomplete (13 E3).
        wf = _FakeWorkflow(requires=["golden_path"])
        _, code = _preflight_user_inputs(_state(golden_entry="exp"), wf)
        assert code == EX_USAGE

    def test_declarative_switch_to_optional_not_required(self):
        # Flexibility (E6): move golden out of requires → no longer enforced.
        wf = _FakeWorkflow(requires=[])
        _, code = _preflight_user_inputs(_state(), wf)
        assert code is None


class TestGoldenTopologyRuleRemoved:
    def test_se_workflow_golden_not_topology_rejected(self, tmp_path):
        # golden→verify rule deleted (13 E4): design-only SE with --golden is
        # no longer a topology error (it is now required, not rejected).
        wf = get_workflow("generate_ascendc_se")
        g = tmp_path / "g.py"
        g.write_text("# g")
        code = _preflight_input_topology(_state(golden_path=g), wf)
        assert code is None

    def test_detailed_design_topology_rule_kept(self):
        # --detailed-design still needs a codegen stage (rule retained).
        wf = get_workflow("generate_ascendc_se")  # no codegen
        code = _preflight_input_topology(
            _state(detailed_design_path=Path("/tmp/dd.md")), wf)
        assert code == EX_USAGE


class TestSeWorkflowRequiresGolden:
    """D-1 (定案 a): generate_ascendc_se mounts general-design, which now
    requires golden_path — so the SE workflow requires golden too."""

    def test_se_general_design_requires_golden(self):
        wf = get_workflow("generate_ascendc_se")
        requires_union: set[str] = set()
        for s in wf.flat_stages():
            requires_union |= set(s.input_contract().requires)
        assert "golden_path" in requires_union

    def test_verify_stage_requires_golden(self):
        wf = get_workflow("generate_ascendc")
        requires_union: set[str] = set()
        for s in wf.flat_stages():
            requires_union |= set(s.input_contract().requires)
        assert "golden_path" in requires_union
