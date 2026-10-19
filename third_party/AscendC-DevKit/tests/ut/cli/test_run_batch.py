"""UT for L1 run_cmd --batch branch (batch fusion, stage 1).

See docs/plan/self-evolution/42-batch-fusion-impl.md §7 Phase 3 (CLI part).
Covers: --batch routes to run_batch; without --batch the original single-op
dispatch path is untouched; --design-concurrency overrides manifest.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from click.testing import CliRunner

from ascendc_devkit.cli.commands.run import run_cmd
from ascendc_devkit.application.batch_runner import BatchResult, RunOutcome
from ascendc_devkit.cli.exit_codes import EX_USAGE


@pytest.fixture(autouse=True)
def _noop_card_health_filter(monkeypatch):
    """Card-pool health filtering probes real NPU cards (open-device subprocess)
    — UT must not depend on NPU hardware (§3.5 运行时真实依赖才标记 npu；本文件
    测 CLI 路由逻辑，不是卡健康探针). Identity filter keeps resolve_card_pool
    deterministic, same convention as tests/ut/application/test_batch_runner.py.
    """
    monkeypatch.setattr(
        "ascendc_devkit.application.batch_runner._filter_healthy_cards",
        lambda pool, timeout_sec: pool,
    )


def _write_manifest(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "batch.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


def _fake_resolve_op_dir(op_dir, **kwargs):
    return SimpleNamespace(
        confidence="high", profile_name="profile", repo_root="/repo",
        rel_op_dir="opX", full_op_name="opX", op_name="opX", variant_name="",
    )


class TestRunCmdBatch:
    def test_batch_invokes_run_batch_not_dispatch(self, tmp_path, monkeypatch):
        """--batch → run_batch called, single-op dispatch NOT called."""
        manifest = _write_manifest(tmp_path, {
            "cards": [0, 1],
            "tasks": [{"op_dir": "/a/opA"}, {"op_dir": "/a/opB"}],
        })
        captured: dict = {}

        def fake_run_batch(m, pool, progress_callback=None):
            captured["pool"] = pool
            captured["n_tasks"] = len(m.tasks)
            return BatchResult(batch_id="test-bid", results=[
                RunOutcome("opA", 0, None), RunOutcome("opB", 0, None)])

        dispatch_called: list = []
        monkeypatch.setattr("ascendc_devkit.cli.commands.run.run_batch", fake_run_batch)
        monkeypatch.setattr(
            "ascendc_devkit.cli.commands.run.dispatch",
            lambda tr: dispatch_called.append(tr) or 0)

        result = CliRunner().invoke(run_cmd, ["--batch", str(manifest)])
        assert result.exit_code == 0
        assert captured["pool"] == [0, 1]  # manifest.cards authoritative
        assert captured["n_tasks"] == 2
        assert dispatch_called == []  # single-op path skipped

    def test_cards_fallback_when_manifest_has_none(self, tmp_path, monkeypatch):
        """manifest without cards → --cards supplies the pool (tier 2 fallback)."""
        manifest = _write_manifest(tmp_path, {
            "tasks": [{"op_dir": "/a/opA"}, {"op_dir": "/a/opB"}],
        })
        captured: dict = {}

        def fake_run_batch(m, pool, progress_callback=None):
            captured["pool"] = pool
            return BatchResult(batch_id="test-bid", results=[RunOutcome("opA", 0, None), RunOutcome("opB", 0, None)])

        monkeypatch.setattr("ascendc_devkit.cli.commands.run.run_batch", fake_run_batch)
        monkeypatch.setattr(
            "ascendc_devkit.cli.commands.run.resolve_op_dir", _fake_resolve_op_dir)

        result = CliRunner().invoke(run_cmd, ["--batch", str(manifest), "--cards", "3,4"])
        assert result.exit_code == 0
        assert captured["pool"] == [3, 4]  # cli --cards, probe NOT consulted

    def test_design_concurrency_overrides_manifest(self, tmp_path, monkeypatch):
        """--design-concurrency overrides manifest's design_concurrency."""
        manifest = _write_manifest(tmp_path, {
            "cards": [0],
            "design_concurrency": 2,  # manifest says 2
            "tasks": [{"op_dir": "/a/opA"}],
        })
        captured: dict = {}

        def fake_run_batch(m, pool, progress_callback=None):
            captured["dc"] = m.design_concurrency
            return BatchResult(batch_id="test-bid", results=[RunOutcome("opA", 0, None)])

        monkeypatch.setattr("ascendc_devkit.cli.commands.run.run_batch", fake_run_batch)
        result = CliRunner().invoke(
            run_cmd, ["--batch", str(manifest), "--design-concurrency", "5"])
        assert result.exit_code == 0
        assert captured["dc"] == 5  # cli override wins over manifest's 2

    def test_nonzero_exit_when_any_task_fails(self, tmp_path, monkeypatch):
        manifest = _write_manifest(tmp_path, {
            "cards": [0, 1],
            "tasks": [{"op_dir": "/a/opA"}, {"op_dir": "/a/opB"}],
        })

        def fake_run_batch(m, pool, progress_callback=None):
            return BatchResult(batch_id="test-bid", results=[
                RunOutcome("opA", 0, None), RunOutcome("opB", 2, None)])  # opB failed

        monkeypatch.setattr("ascendc_devkit.cli.commands.run.run_batch", fake_run_batch)
        result = CliRunner().invoke(run_cmd, ["--batch", str(manifest)])
        assert result.exit_code == 1  # any failure → exit 1

    def test_no_batch_uses_original_dispatch(self, tmp_path, monkeypatch):
        """Without --batch, the original single-op path (resolve_op_dir + dispatch)
        is untouched; run_batch is NOT called."""
        run_batch_called: list = []
        dispatch_called: list = []

        monkeypatch.setattr(
            "ascendc_devkit.cli.commands.run.run_batch",
            lambda *a, **k: run_batch_called.append(1))
        monkeypatch.setattr(
            "ascendc_devkit.cli.commands.run.resolve_op_dir", _fake_resolve_op_dir)
        monkeypatch.setattr(
            "ascendc_devkit.cli.commands.run.dispatch",
            lambda tr: dispatch_called.append(tr) or 0)

        result = CliRunner().invoke(
            run_cmd, ["--op-dir", "/a/opA", "--non-interactive"])
        assert result.exit_code == 0
        assert run_batch_called == []
        assert len(dispatch_called) == 1


class TestRunCmdResumeUnified:
    """--resume <id> unifies single-run / batch resume by id LOCATION (L4 §54)."""

    def test_batch_and_resume_mutually_exclusive(self, tmp_path):
        manifest = _write_manifest(tmp_path, {
            "cards": [0], "tasks": [{"op_dir": "/a/opA"}]})
        result = CliRunner().invoke(
            run_cmd, ["--batch", str(manifest), "--resume", "20260717-120000-x"])
        assert result.exit_code == EX_USAGE

    def test_resume_batch_id_routes_to_resume_batch(self, tmp_path, monkeypatch):
        bid = "20260717-120000-batch1"
        eid = "20260717-120000-exec1"
        out = tmp_path / "output"
        (out / bid / eid).mkdir(parents=True)
        (out / bid / eid / "state_snapshot.json").write_text("{}", encoding="utf-8")
        called: dict = {}

        def fake_resume_batch(b, output_root=None, cli_cards=None,
                              progress_callback=None):
            called["bid"] = b
            called["output_root"] = output_root
            return BatchResult(batch_id=b, results=[RunOutcome("op", 0, eid)])

        monkeypatch.setattr("ascendc_devkit.cli.commands.run.resume_batch",
                            fake_resume_batch)
        monkeypatch.chdir(tmp_path)  # default output_root "output" → tmp_path/output
        result = CliRunner().invoke(run_cmd, ["--resume", bid, "--cards", "0"])
        assert result.exit_code == 0
        assert called["bid"] == bid
        assert called["output_root"] == "output"

    def test_resume_single_run_id_routes_to_dispatch(self, tmp_path, monkeypatch):
        rid = "20260717-120000-run1"
        out = tmp_path / "output"
        (out / rid).mkdir(parents=True)
        (out / rid / "state_snapshot.json").write_text("{}", encoding="utf-8")
        dispatched: list = []

        def fake_dispatch(tr, progress_callback=None, card_pool=None):
            dispatched.append(tr)
            return 0

        monkeypatch.setattr("ascendc_devkit.cli.commands.run.dispatch", fake_dispatch)
        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(run_cmd, ["--resume", rid])
        assert result.exit_code == 0
        assert len(dispatched) == 1
        assert dispatched[0]["resume_from"] == rid
        # flat single run → output_root unchanged (not scoped to a batch)
        assert dispatched[0]["output_root"] == "output"

    def test_resume_nested_exec_routes_to_dispatch_scoped(self, tmp_path, monkeypatch):
        """Resuming a single execution nested under a batch scopes output_root
        to output/<batch_id> so dispatch loads it from the right place."""
        bid, eid = "20260717-120000-batch1", "20260717-120000-exec1"
        out = tmp_path / "output"
        (out / bid / eid).mkdir(parents=True)
        (out / bid / eid / "state_snapshot.json").write_text("{}", encoding="utf-8")
        dispatched: list = []
        monkeypatch.setattr(
            "ascendc_devkit.cli.commands.run.dispatch",
            lambda tr, progress_callback=None, card_pool=None: dispatched.append(tr) or 0)
        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(run_cmd, ["--resume", eid])
        assert result.exit_code == 0
        assert dispatched[0]["resume_from"] == eid
        assert dispatched[0]["output_root"] == f"output/{bid}"  # scoped to batch dir
