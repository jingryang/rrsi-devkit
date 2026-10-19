"""A1 (step-2 follow-up) — --detailed-design short-circuit (decision-point 9).

When a detailed design doc is supplied, the detailed-design group skips
generation (template-division → tiling → anchor → integrate → docgen) and runs
only an intake (parse the existing detailed design into the three-piece
contract + design_doc) → validate → codegen. When absent, intake is a pure
no-op routing linearly into the normal full flow. Strict TDD: red first.
"""

from pathlib import Path
from unittest import mock
import pytest
from click.testing import CliRunner
from ascendc_devkit.cli.main import main as cli_main
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.kernel.action import SpawnAgent
from ascendc_devkit.capabilities.agent.backend import AgentResult
from ascendc_devkit.orchestration.stages.design_substages import (
    DetailedDesignIntakeStage,
)
from ascendc_devkit.orchestration.design_tree import build_detailed_design_group


@pytest.fixture
def runner():
    return CliRunner()


def _ar(artifacts, status="ok", agent="x"):
    return AgentResult(agent_name=agent, status=status, artifacts=artifacts)


_THREE_PIECE = {
    "design_spec.json": '{"inputs": [], "outputs": []}',
    "tiling_strategy.json": '{"approach": "provided"}',
    "kernel_architecture.json": '{"host_code": {}, "kernel_code": {}}',
}


def _intake_res(tmp_path):
    """P62: land the intake products to a working dir on disk and return the
    transition result. DetailedDesignIntakeStage reads design_spec.json
    (required) + tiling_strategy.json/data_flow.json (optional) from disk only."""
    wd = tmp_path / "wd"
    wd.mkdir(exist_ok=True)
    for fn, content in _THREE_PIECE.items():
        (wd / fn).write_text(content, encoding="utf-8")
    return {"_working_dir": str(wd)}


class TestStateField:
    def test_default_none(self):
        assert State.empty().detailed_design_path is None

    def test_roundtrip_via_snapshot(self):
        s = State.empty().with_updates(detailed_design_path=Path("/tmp/dd.md"))
        s2 = State.from_snapshot(s.to_snapshot())
        assert s2.detailed_design_path == Path("/tmp/dd.md")

    def test_old_snapshot_defaults_none(self):
        assert State.from_snapshot({"run_id": "r1"}).detailed_design_path is None


class TestCliParam:
    @mock.patch("ascendc_devkit.cli.commands.run.dispatch")
    def test_detailed_design_flows_to_task_request(self, mock_dispatch, runner, tmp_path):
        mock_dispatch.return_value = 0
        dd = tmp_path / "detailed.md"
        dd.write_text("# 详细设计")
        result = runner.invoke(cli_main, [
            "run", "--target-repo", str(tmp_path), "--repo-profile", "omni-ops",
            "--op-name", "gelu", "--detailed-design", str(dd),
            "--output-root", str(tmp_path),
        ])
        assert result.exit_code == 0
        task = mock_dispatch.call_args.args[0]
        assert task["detailed_design_path"] == str(dd)

    @mock.patch("ascendc_devkit.cli.commands.run.dispatch")
    def test_absent_is_none(self, mock_dispatch, runner, tmp_path):
        mock_dispatch.return_value = 0
        runner.invoke(cli_main, [
            "run", "--target-repo", str(tmp_path), "--repo-profile", "omni-ops",
            "--output-root", str(tmp_path)])
        assert mock_dispatch.call_args.args[0]["detailed_design_path"] is None

    def test_help_mentions_detailed_design(self, runner):
        result = runner.invoke(cli_main, ["run", "--help"])
        assert "--detailed-design" in result.output


class TestIntakeNoOp:
    def test_actions_empty_without_path(self):
        assert DetailedDesignIntakeStage().actions(State.empty()) == []

    def test_transition_noop_without_path(self):
        s = State.empty()
        out = DetailedDesignIntakeStage().transition(s, {})
        assert out.design_spec is None
        assert out.design_doc is None

    def test_condition_default_without_path(self):
        assert DetailedDesignIntakeStage().resolve_condition(State.empty()) == "default"

    def test_skip_reason_when_no_doc(self):
        """P6-b: dd-intake returns a reason when no --detailed-design supplied."""
        assert (DetailedDesignIntakeStage().skip_reason(State.empty())
                == "no --detailed-design supplied")

    def test_skip_reason_none_when_doc_present(self, tmp_path):
        """P6-b: dd-intake returns None when a detailed design IS supplied."""
        dd = tmp_path / "detailed.md"
        dd.write_text("# design")
        s = State.empty().with_updates(detailed_design_path=dd)
        assert DetailedDesignIntakeStage().skip_reason(s) is None


class TestIntakeShortCircuit:
    def _state(self, tmp_path):
        dd = tmp_path / "detailed.md"
        dd.write_text("# 详细设计说明书\n内容")
        return State.empty().with_updates(detailed_design_path=dd), dd

    def test_actions_spawn_parse_agent(self, tmp_path):
        s, _ = self._state(tmp_path)
        spawns = [a for a in DetailedDesignIntakeStage().actions(s)
                  if isinstance(a, SpawnAgent)]
        assert len(spawns) == 1 and spawns[0].prompt

    def test_transition_parses_two_piece_and_doc(self, tmp_path):
        """Step 9: kernel_architecture removed from design intake output.
        P36: dd-intake no longer renders design_doc (DocgenStage._render_detailed
        removed); the external doc already IS the detailed design, so design_doc
        points at its path (state.design_doc stores an md path, see P36)."""
        s, dd = self._state(tmp_path)
        out = DetailedDesignIntakeStage().transition(s, _intake_res(tmp_path))
        assert out.design_spec == {"inputs": [], "outputs": []}
        assert out.tiling_strategy == {"approach": "provided"}
        assert out.kernel_architecture is None  # not produced by intake
        assert out.design_doc == str(dd)  # points at the external detailed-design doc

    def test_condition_short_circuit_after_parse(self, tmp_path):
        s, _ = self._state(tmp_path)
        out = DetailedDesignIntakeStage().transition(s, _intake_res(tmp_path))
        assert DetailedDesignIntakeStage().resolve_condition(out) == "short_circuit"

    def test_transition_clears_sticky_last_error_on_success(self, tmp_path):
        """design-halt-diagnostics P1: dd-intake's custom transition() bypasses
        _parse_single, so it must clear a stale same-stage last_error on its
        success path itself (via _success_updates) — otherwise a prior
        iteration's missing_artifact error survives into a successful parse
        and falsely halts the pipeline."""
        from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
        s, dd = self._state(tmp_path)
        s = s.with_updates(last_error=ErrorFeedback(
            stage_name="dd-intake", error_type="missing_artifact",
            message="iteration 1 failed"))
        out = DetailedDesignIntakeStage().transition(s, _intake_res(tmp_path))
        assert out.design_spec == {"inputs": [], "outputs": []}
        assert out.last_error is None, (
            "sticky last_error must be cleared on successful intake")


class TestGroupWiring:
    def test_intake_is_first_child(self):
        g = build_detailed_design_group()
        assert g.children()[0].name == "dd-intake"
