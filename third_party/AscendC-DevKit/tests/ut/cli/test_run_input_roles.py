"""P7 (step-2b) — CLI input-role params (§八).

--general-design replaces --design-doc (both map to design_doc_path);
--requirement help narrowed to requirement/problem description. Strict TDD.
"""

from unittest import mock
import pytest
from click.testing import CliRunner
from ascendc_devkit.cli.main import main as cli_main


@pytest.fixture
def runner():
    return CliRunner()


class TestGeneralDesignParam:
    @mock.patch("ascendc_devkit.cli.commands.run.dispatch")
    def test_general_design_flows_to_design_doc_path(self, mock_dispatch, runner, tmp_path):
        mock_dispatch.return_value = 0
        doc = tmp_path / "concept.md"
        doc.write_text("# 概要设计")
        result = runner.invoke(cli_main, [
            "run", "--target-repo", str(tmp_path), "--repo-profile", "omni-ops",
            "--op-name", "gelu", "--general-design", str(doc),
            "--output-root", str(tmp_path),
        ])
        assert result.exit_code == 0
        task = mock_dispatch.call_args.args[0]
        assert task["design_doc_path"] == str(doc)

    @mock.patch("ascendc_devkit.cli.commands.run.dispatch")
    def test_general_design_absent_is_none(self, mock_dispatch, runner, tmp_path):
        mock_dispatch.return_value = 0
        result = runner.invoke(cli_main, [
            "run", "--target-repo", str(tmp_path), "--repo-profile", "omni-ops",
            "--output-root", str(tmp_path),
        ])
        assert result.exit_code == 0
        task = mock_dispatch.call_args.args[0]
        assert task["design_doc_path"] is None


class TestDesignDocRemoved:
    def test_design_doc_no_longer_recognized(self, runner, tmp_path):
        doc = tmp_path / "d.md"
        doc.write_text("x")
        result = runner.invoke(cli_main, [
            "run", "--target-repo", str(tmp_path), "--repo-profile", "omni-ops",
            "--design-doc", str(doc),
        ])
        assert result.exit_code != 0
        assert "no such option" in result.output.lower()


class TestRequirementHelpNarrowed:
    def test_requirement_help_mentions_requirement_semantics(self, runner):
        result = runner.invoke(cli_main, ["run", "--help"])
        assert result.exit_code == 0
        # --requirement help narrowed to requirement/problem description; the
        # --general-design option exists for the concept-design role.
        assert "--general-design" in result.output
        assert "需求" in result.output or "requirement" in result.output.lower()
