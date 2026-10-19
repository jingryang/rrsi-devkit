"""B2 (14 L4) — --golden-entry / --golden-input-type / --cann-bench-cases
CLI params (13 E1/E2). golden source is explicit CLI, not profile-preset.

--golden-entry:        source golden's entry function name (e.g. "exp").
--golden-input-type:   "torch" | "numpy" — CLI enum check (13 E3/E5).
--cann-bench-cases:    external cann-bench cases CSV path (param name encodes
                       format; 13 E2 — no in-loader format dispatch).
"""

from pathlib import Path
from unittest import mock
import pytest
from click.testing import CliRunner
from ascendc_devkit.cli.main import main as cli_main


@pytest.fixture
def runner():
    return CliRunner()


class TestGoldenEntryCliParam:
    @mock.patch("ascendc_devkit.cli.commands.run.dispatch")
    def test_golden_entry_flows_to_task_request(self, mock_dispatch, runner, tmp_path):
        mock_dispatch.return_value = 0
        result = runner.invoke(cli_main, [
            "run", "--target-repo", str(tmp_path), "--repo-profile", "omni-ops",
            "--op-name", "exp", "--golden-entry", "exp",
            "--output-root", str(tmp_path),
        ])
        assert result.exit_code == 0
        task = mock_dispatch.call_args.args[0]
        assert task["golden_entry"] == "exp"

    @mock.patch("ascendc_devkit.cli.commands.run.dispatch")
    def test_golden_entry_absent_is_none(self, mock_dispatch, runner, tmp_path):
        mock_dispatch.return_value = 0
        result = runner.invoke(cli_main, [
            "run", "--target-repo", str(tmp_path), "--repo-profile", "omni-ops",
            "--output-root", str(tmp_path),
        ])
        assert result.exit_code == 0
        task = mock_dispatch.call_args.args[0]
        assert task["golden_entry"] is None


class TestGoldenInputTypeCliParam:
    @mock.patch("ascendc_devkit.cli.commands.run.dispatch")
    def test_golden_input_type_torch_flows(self, mock_dispatch, runner, tmp_path):
        mock_dispatch.return_value = 0
        result = runner.invoke(cli_main, [
            "run", "--target-repo", str(tmp_path), "--repo-profile", "omni-ops",
            "--golden-input-type", "torch",
            "--output-root", str(tmp_path),
        ])
        assert result.exit_code == 0
        task = mock_dispatch.call_args.args[0]
        assert task["golden_input_type"] == "torch"

    @mock.patch("ascendc_devkit.cli.commands.run.dispatch")
    def test_golden_input_type_numpy_flows(self, mock_dispatch, runner, tmp_path):
        mock_dispatch.return_value = 0
        result = runner.invoke(cli_main, [
            "run", "--target-repo", str(tmp_path), "--repo-profile", "omni-ops",
            "--golden-input-type", "numpy",
            "--output-root", str(tmp_path),
        ])
        assert result.exit_code == 0
        task = mock_dispatch.call_args.args[0]
        assert task["golden_input_type"] == "numpy"

    def test_golden_input_type_rejects_invalid(self, runner, tmp_path):
        # click.Choice rejects values outside {torch, numpy} at parse time.
        result = runner.invoke(cli_main, [
            "run", "--target-repo", str(tmp_path), "--repo-profile", "omni-ops",
            "--golden-input-type", "cuda",
            "--output-root", str(tmp_path),
        ])
        assert result.exit_code != 0
        assert "cuda" in result.output or "golden-input-type" in result.output

    @mock.patch("ascendc_devkit.cli.commands.run.dispatch")
    def test_golden_input_type_absent_is_none(self, mock_dispatch, runner, tmp_path):
        mock_dispatch.return_value = 0
        result = runner.invoke(cli_main, [
            "run", "--target-repo", str(tmp_path), "--repo-profile", "omni-ops",
            "--output-root", str(tmp_path),
        ])
        assert result.exit_code == 0
        task = mock_dispatch.call_args.args[0]
        assert task["golden_input_type"] is None


class TestCannBenchCasesCliParam:
    @mock.patch("ascendc_devkit.cli.commands.run.dispatch")
    def test_cann_bench_cases_flows_to_task_request(self, mock_dispatch, runner, tmp_path):
        mock_dispatch.return_value = 0
        cases = tmp_path / "cases.csv"
        cases.write_text("shape,dtype\n[8],float32\n")
        result = runner.invoke(cli_main, [
            "run", "--target-repo", str(tmp_path), "--repo-profile", "omni-ops",
            "--cann-bench-cases", str(cases),
            "--output-root", str(tmp_path),
        ])
        assert result.exit_code == 0
        task = mock_dispatch.call_args.args[0]
        assert task["cases_path"] == str(cases)

    def test_cann_bench_cases_rejects_missing_path(self, runner, tmp_path):
        # click.Path(exists=True) rejects a non-existent path at parse time.
        result = runner.invoke(cli_main, [
            "run", "--target-repo", str(tmp_path), "--repo-profile", "omni-ops",
            "--cann-bench-cases", str(tmp_path / "nope.csv"),
            "--output-root", str(tmp_path),
        ])
        assert result.exit_code != 0

    @mock.patch("ascendc_devkit.cli.commands.run.dispatch")
    def test_cann_bench_cases_absent_is_none(self, mock_dispatch, runner, tmp_path):
        mock_dispatch.return_value = 0
        result = runner.invoke(cli_main, [
            "run", "--target-repo", str(tmp_path), "--repo-profile", "omni-ops",
            "--output-root", str(tmp_path),
        ])
        assert result.exit_code == 0
        task = mock_dispatch.call_args.args[0]
        assert task["cases_path"] is None
