"""A2 (step-2 follow-up) — --golden CLI input role (decision-point 9 remainder).

--golden carries the precision baseline (golden reference implementation/data).
It flows CLI → task_request → State.golden_path → precision_debug's agent
context (the precision consumer, post-P57 能力下沉). Strict TDD: red first.
"""

from pathlib import Path
from unittest import mock
import pytest
from click.testing import CliRunner
from ascendc_devkit.cli.main import main as cli_main
from ascendc_devkit.orchestration.kernel.state import State


@pytest.fixture
def runner():
    return CliRunner()


class TestGoldenCliParam:
    @mock.patch("ascendc_devkit.cli.commands.run.dispatch")
    def test_golden_flows_to_task_request(self, mock_dispatch, runner, tmp_path):
        mock_dispatch.return_value = 0
        g = tmp_path / "golden.py"
        g.write_text("# golden reference\n")
        result = runner.invoke(cli_main, [
            "run", "--target-repo", str(tmp_path), "--repo-profile", "omni-ops",
            "--op-name", "gelu", "--golden", str(g),
            "--output-root", str(tmp_path),
        ])
        assert result.exit_code == 0
        task = mock_dispatch.call_args.args[0]
        assert task["golden_path"] == str(g)

    @mock.patch("ascendc_devkit.cli.commands.run.dispatch")
    def test_golden_absent_is_none(self, mock_dispatch, runner, tmp_path):
        mock_dispatch.return_value = 0
        result = runner.invoke(cli_main, [
            "run", "--target-repo", str(tmp_path), "--repo-profile", "omni-ops",
            "--output-root", str(tmp_path),
        ])
        assert result.exit_code == 0
        task = mock_dispatch.call_args.args[0]
        assert task["golden_path"] is None

    def test_golden_help_mentions_precision_baseline(self, runner):
        result = runner.invoke(cli_main, ["run", "--help"])
        assert result.exit_code == 0
        assert "--golden" in result.output


class TestGoldenStateField:
    def test_default_none(self):
        assert State.empty().golden_path is None

    def test_roundtrip_via_snapshot(self):
        s = State.empty().with_updates(golden_path=Path("/tmp/g.py"))
        s2 = State.from_snapshot(s.to_snapshot())
        assert s2.golden_path == Path("/tmp/g.py")

    def test_old_snapshot_defaults_none(self):
        s = State.from_snapshot({"run_id": "r1"})
        assert s.golden_path is None


class TestGoldenThreadsToPrecisionDebug:
    """precision_debug's run_tests sub-stage carries the golden contract (resolved
    from user --golden) in its SpawnAgent context, so the precision agent compares
    against the user's reference, not a guess. P0 (51-*.md): precision_debug is now
    a CompositeGroup; the run_tests sub-stage (first child) is the golden consumer
    (it drives run-cases)."""

    def test_precision_debug_context_includes_golden_contract(self, tmp_path):
        from ascendc_devkit.orchestration.stages.precision_debug_substages import (
            DiagnoseSubstage,
        )
        from ascendc_devkit.orchestration.kernel.action import SpawnAgent
        from ascendc_devkit.domain.requirement import Requirement, TestCase
        from ascendc_devkit.domain.operator import OperatorIdentity, OperatorSpec
        from pathlib import Path

        g = tmp_path / "golden.py"
        g.write_text("# golden\n")
        req = Requirement(
            op_spec=OperatorSpec(name="gelu"),
            test_cases=[TestCase(name="c1", inputs=[{"shape": [8]}])],
        )
        identity = OperatorIdentity(
            spec=OperatorSpec(name="gelu"),
            repo_root=tmp_path,
            op_dir=tmp_path,
            files={},
        )
        state = State.empty().with_updates(
            requirement=req, op_identity=identity,
            golden_path=g, golden_entry="gelu",
            golden_input_type="torch", npu_id=0, enable_stubbed=True,
            skip_precision=False,
        )
        # §judgment-ownership (N1): run_tests 纯 Python 化不 spawn agent；diagnose 是
        # 唯一 spawn 的 phase agent，golden 契约 thread 到它的 context。
        actions = DiagnoseSubstage().actions(state)
        spawn = next(a for a in actions if isinstance(a, SpawnAgent))
        # golden contract is read verbatim from the three State scalars
        # (entry/input_type carried verbatim — no profile fallback, no
        # hardcoded reference/numpy convention).
        assert spawn.context["golden"] == {
            "path": str(g), "entry": "gelu", "input_type": "torch"}
