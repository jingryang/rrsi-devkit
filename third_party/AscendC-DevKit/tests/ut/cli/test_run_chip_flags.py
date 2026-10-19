"""Step 4 (chip-target-selection): CLI dual-flag replacement.

Retires ``--chip-version`` / ``--assume-chip`` (whose conflation leaked
``--assume-chip`` into the target side and made the run gate a tautology) in
favor of two flags with disjoint authority, matching the dispatcher's dual
fields (Step 3):

  - ``--design-target-chip`` — design/compile intent (CLI > req > profile >
    probe-if-known; downstream layers applied in context/requirement stage).
  - ``--runtime-target-chip`` — on-box hardware, ONLY a flaky-driver timeout
    fallback (the bounded probe is authoritative whenever it can answer).

Both flags are optional ``Choice(["A2","A3","A5"])``; the old flags are gone
(§1.4: no backward-compat shims — a user passing the retired flag gets a clear
UsageError, not a silent ignore).
"""
from __future__ import annotations

from click.testing import CliRunner

from ascendc_devkit.cli.commands.run import run_cmd


def _capture_dispatch(monkeypatch, captured: dict):
    """Stub dispatch so the CLI is exercised without running a workflow."""
    def _fake(task_request, progress_callback=None, card_pool=None):
        captured.update(task_request)
        captured["_card_pool"] = card_pool
        return 0
    monkeypatch.setattr("ascendc_devkit.cli.commands.run.dispatch", _fake)


class TestRunChipFlags:
    def test_design_target_chip_flag_flows_into_task_request(self, monkeypatch):
        captured: dict = {}
        _capture_dispatch(monkeypatch, captured)
        result = CliRunner().invoke(run_cmd, ["--design-target-chip", "A5"])
        assert result.exit_code == 0, result.output
        assert captured["design_target_chip"] == "A5"

    def test_runtime_target_chip_flag_flows_into_task_request(self, monkeypatch):
        captured: dict = {}
        _capture_dispatch(monkeypatch, captured)
        result = CliRunner().invoke(run_cmd, ["--runtime-target-chip", "A2"])
        assert result.exit_code == 0, result.output
        assert captured["runtime_target_chip"] == "A2"

    def test_default_leaves_both_chip_fields_none(self, monkeypatch):
        captured: dict = {}
        _capture_dispatch(monkeypatch, captured)
        result = CliRunner().invoke(run_cmd, [])
        assert result.exit_code == 0, result.output
        assert captured["design_target_chip"] is None
        assert captured["runtime_target_chip"] is None

    def test_retired_chip_version_flag_rejected(self, monkeypatch):
        captured: dict = {}
        _capture_dispatch(monkeypatch, captured)
        result = CliRunner().invoke(run_cmd, ["--chip-version", "A5"])
        assert result.exit_code != 0
        assert not captured  # dispatch never reached

    def test_retired_assume_chip_flag_rejected(self, monkeypatch):
        captured: dict = {}
        _capture_dispatch(monkeypatch, captured)
        result = CliRunner().invoke(run_cmd, ["--assume-chip", "A5"])
        assert result.exit_code != 0
        assert not captured

    def test_invalid_choice_rejected(self, monkeypatch):
        captured: dict = {}
        _capture_dispatch(monkeypatch, captured)
        result = CliRunner().invoke(run_cmd, ["--design-target-chip", "A9"])
        assert result.exit_code != 0


class TestRunNpuIdFlag:
    """--npu-id semantics for op-level card pinning.

    Unset must resolve to None (not 0) so the op-level lease at the dispatch
    boundary auto-picks from the shared card pool; a literal 0 would hard-pin
    card 0 for every task and break batch pooling for tasks that did not opt
    into a specific card.
    """

    def test_npu_id_unset_defaults_to_none(self, monkeypatch):
        captured: dict = {}
        _capture_dispatch(monkeypatch, captured)
        result = CliRunner().invoke(run_cmd, [])
        assert result.exit_code == 0, result.output
        assert captured["npu_id"] is None

    def test_npu_id_flag_flows_into_task_request(self, monkeypatch):
        captured: dict = {}
        _capture_dispatch(monkeypatch, captured)
        result = CliRunner().invoke(run_cmd, ["--npu-id", "2"])
        assert result.exit_code == 0, result.output
        assert captured["npu_id"] == 2

    def test_single_op_passes_no_card_pool(self, monkeypatch):
        # 单算子路径不传 card_pool（None）；batch 才由 batch_runner 传共享池。
        captured: dict = {}
        _capture_dispatch(monkeypatch, captured)
        result = CliRunner().invoke(run_cmd, [])
        assert result.exit_code == 0, result.output
        assert captured["_card_pool"] is None
