"""ST — batch_runner end-to-end via real dispatch + StubBackend (stage 1).

Verifies run_batch orchestration (concurrency / card pool / 1-task degradation)
against the REAL dispatch chain: each task gets an independent Workspace +
events.jsonl. StubBackend (SDKBackend mocked unavailable) + enable_stubbed
means NO real LLM / CANN / NPU — fast, deterministic, so no llm/npu/cann
markers (§3.5: no runtime dependency on them). Mirrors tests/st/test_integration.py's
stub-dispatch pattern.

See docs/plan/self-evolution/42-batch-fusion-impl.md §7 Phase 5-6.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest
import yaml

from ascendc_devkit.capabilities.agent.stub_backend import StubBackend
from ascendc_devkit.application.batch_runner import (
    load_manifest, resolve_card_pool, run_batch,
)
from ascendc_devkit.domain.exit_codes import EX_DATAERR


def _golden(tmp_path: Path, op: str) -> dict:
    """generate_ascendc requires the golden three params (design + verify).
    StubBackend never executes the golden — a trivial stub suffices, as in
    test_integration.py."""
    g = tmp_path / f"golden_{op}.py"
    g.write_text("def reference(*inputs, **attrs):\n    return inputs\n")
    return {"golden_path": str(g), "golden_entry": op, "golden_input_type": "numpy"}


def _write_manifest(tmp_path: Path, tasks: list[dict], cards=None) -> Path:
    data = {
        "cards": cards if cards is not None else [0, 1],
        "enable_stubbed": True,
        "non_interactive": True,
        "max_iterations": 1,
        "output_root": str(tmp_path / "output"),
        "tasks": tasks,
    }
    p = tmp_path / "batch.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


def _task(tmp_path: Path, op: str) -> dict:
    """A stub-dispatch task: target_repo/repo_profile/op_name locator (no op_dir,
    so _dispatch_one skips resolve_op_dir — matches run_cmd's op_dir-optional path)."""
    repo = tmp_path / f"repo_{op}"
    repo.mkdir()
    req = tmp_path / f"req_{op}.yaml"
    req.write_text(f"op: {op}\n")
    return {
        "target_repo": str(repo),
        "repo_profile": "omni-ops",
        "op_name": op,
        "requirement_path": str(req),
        **_golden(tmp_path, op),
    }


class TestBatchE2E:
    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_two_ops_concurrent_independent_workspaces(self, mock_sdk, tmp_path):
        """2 tasks + 2 cards: both dispatch concurrently, each materializes its
        OWN Workspace + events.jsonl (no cross-contamination). The card pool is
        exercised for real (each worker acquires/releases)."""
        mock_sdk.return_value = StubBackend()  # force StubBackend
        manifest = load_manifest(_write_manifest(tmp_path, [
            _task(tmp_path, "gelu"), _task(tmp_path, "relu"),
        ]))
        pool = resolve_card_pool(manifest)
        result = run_batch(manifest, pool)

        # StubBackend produces no real requirement → both halt at the design
        # gate (EX_DATAERR). The point is orchestration, not stage success.
        assert len(result.results) == 2
        assert all(r.exit_code == EX_DATAERR for r in result.results)

        # Layered ids (L4 §54): runs land under output/<batch_id>/<exec_id>/.
        # The exec dir NAME equals RunOutcome.run_id — proving batch_runner's
        # pre-assigned execution_id flowed task_request["run_id"] → dispatch →
        # Workspace.create(run_id=) → the on-disk dir name.
        batch_dir = tmp_path / "output" / result.batch_id
        assert batch_dir.is_dir(), f"no batch dir {batch_dir}"
        run_dirs = sorted(d for d in batch_dir.iterdir() if d.is_dir())
        assert len(run_dirs) == 2
        assert {d.name for d in run_dirs} == {r.run_id for r in result.results}
        for ws in run_dirs:
            events_path = ws / "events.jsonl"
            assert events_path.exists(), f"no events.jsonl in {ws}"
            events = [
                json.loads(line)
                for line in events_path.read_text().strip().split("\n")
                if line.strip()
            ]
            types = {e["type"] for e in events}
            assert "stage_enter" in types, f"missing stage_enter in {ws}"
            assert "stage_complete" in types, f"missing stage_complete in {ws}"

    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_single_task_degrades_to_sync_e2e(self, mock_sdk, tmp_path):
        """1 task → degraded synchronous path (no thread pool, no card queue):
        still dispatches through the real chain, produces exactly one workspace."""
        mock_sdk.return_value = StubBackend()
        manifest = load_manifest(_write_manifest(tmp_path, [
            _task(tmp_path, "gelu"),
        ], cards=[0]))
        pool = resolve_card_pool(manifest)
        result = run_batch(manifest, pool)

        assert len(result.results) == 1
        assert result.results[0].exit_code == EX_DATAERR
        batch_dir = tmp_path / "output" / result.batch_id
        run_dirs = [d for d in batch_dir.iterdir() if d.is_dir()]
        assert len(run_dirs) == 1  # single task → single workspace, nested under batch
        assert run_dirs[0].name == result.results[0].run_id
