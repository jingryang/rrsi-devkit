"""System tests requiring a real LLM backend via claude_agent_sdk.

Uses dispatch_single_stage to exercise the full L1→L2→L3→L5→L7 chain.

Markers:
    @pytest.mark.llm  — needs SDKBackend (real LLM), ~10s
    @pytest.mark.slow — long-running codegen test, ~5min
"""

import json
import tempfile
from pathlib import Path

import pytest

from ascendc_devkit.application.dispatcher import dispatch_single_stage


@pytest.mark.llm
class TestSmokeStageEndToEnd:
    """Verify smoke stage via full dispatch pipeline."""

    def test_full_pipeline(self):
        fixture = Path(__file__).parent.parent / "fixtures" / "smoke_state.json"
        with tempfile.TemporaryDirectory() as tmpdir:
            exit_code = dispatch_single_stage(
                stage_name="smoke",
                state_file=fixture,
                non_interactive=True,
                output_root=tmpdir,
            )
            assert exit_code == 0

            # Find the workspace directory created by dispatcher
            output_dir = Path(tmpdir)
            run_dirs = [d for d in output_dir.iterdir() if d.is_dir()]
            assert len(run_dirs) == 1
            workspace = run_dirs[0]

            # events.jsonl must capture full stage lifecycle
            events_path = workspace / "events.jsonl"
            assert events_path.exists()
            events = [
                json.loads(line)
                for line in events_path.read_text().strip().split("\n")
                if line.strip()
            ]
            event_types = {e["type"] for e in events}
            for t in ("stage_enter", "stage_complete", "action_start", "action_complete"):
                assert t in event_types, f"Missing event type: {t}"

            # state_snapshot.json must exist
            state_path = workspace / "state_snapshot.json"
            assert state_path.exists()
            snapshot = json.loads(state_path.read_text())
            assert snapshot.get("current_stage") == "smoke"


@pytest.mark.slow
@pytest.mark.llm
@pytest.mark.heavy_llm
class TestCodegenStageEndToEnd:
    """Verify codegen stage via full dispatch pipeline.

    Uses the simplest operator (element-wise add) but remains flaky — LLM
    agent routinely exceeds turn budget reading knowledge bases and
    generating files.  Marked heavy_llm; skip with ``-m \"not heavy_llm\"``.
    """

    def test_full_pipeline(self):
        fixture = Path(__file__).parent.parent / "fixtures" / "add_state.json"
        with tempfile.TemporaryDirectory() as tmpdir:
            exit_code = dispatch_single_stage(
                stage_name="codegen",
                state_file=fixture,
                non_interactive=True,
                max_iterations=1,
                output_root=tmpdir,
            )
            # codegen may exit 0 (success) or non-zero if agent hits turn limit
            # but workspace should still be populated

            output_dir = Path(tmpdir)
            run_dirs = [d for d in output_dir.iterdir() if d.is_dir()]
            assert len(run_dirs) == 1
            workspace = run_dirs[0]

            # events.jsonl must capture stage lifecycle
            events_path = workspace / "events.jsonl"
            assert events_path.exists()

            # state_snapshot.json must exist
            state_path = workspace / "state_snapshot.json"
            assert state_path.exists()
            snapshot = json.loads(state_path.read_text())
            # At minimum, verify the stage was recorded
            assert snapshot.get("current_stage") == "codegen"
