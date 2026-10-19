"""ST — non-LLM integration tests: pipeline, repo materialization, state snapshot.

These tests verify end-to-end behavior without requiring a real LLM or NPU.
They use StubBackend (mock dispatcher.build_agent_backend to return a StubBackend — the fallback now lives inside the factory, so tests feed the stub directly) and temp directories.
"""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from unittest import mock

import pytest

from ascendc_devkit.capabilities.agent.stub_backend import StubBackend
from ascendc_devkit.application.dispatcher import dispatch, dispatch_single_stage
from ascendc_devkit.domain.exit_codes import EX_DATAERR, EX_TIMEOUT, EX_DECISION_PENDING
from ascendc_devkit.adapters.repository.generic import GenericRepositoryAdapter
from ascendc_devkit.adapters.repository.profile_loader import ProfileLoader
from ascendc_devkit.domain.operator import OperatorSpec, OperatorIdentity
from ascendc_devkit.domain.repository import RepositoryProfile
from ascendc_devkit.domain.contract import StageIOContract
from ascendc_devkit.orchestration.kernel.state import State


def _golden_required(op: str, tmp_path) -> dict:
    """generate_ascendc now requires the golden three params (D-1: design +
    verify require golden). These are StubBackend plumbing tests — the golden
    is never executed, only satisfies the dispatch preflight, so a trivial stub
    golden suffices."""
    g = tmp_path / "golden.py"
    if not g.exists():
        g.write_text("def reference(*inputs, **attrs):\n    return inputs\n")
    return {"golden_path": str(g), "golden_entry": op, "golden_input_type": "numpy"}


# ────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────

@pytest.fixture
def omni_ops_profile():
    return ProfileLoader.load("omni-ops")


@pytest.fixture
def sample_operator_spec():
    return OperatorSpec(name="test_gelu")


@pytest.fixture
def sample_operator_identity(sample_operator_spec, tmp_path):
    return OperatorIdentity(
        spec=sample_operator_spec,
        repo_root=tmp_path,
        op_dir=tmp_path / "custom_ops" / "test_gelu",
    )


# ────────────────────────────────────────────────────────────
# Test 1: Pipeline event recording + resilience
# ────────────────────────────────────────────────────────────

class TestNineStagePipeline:
    """Verify dispatch() runs pipeline gracefully with StubBackend fallback."""

    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_pipeline_completes_and_events_recorded(self, mock_sdk, tmp_path):
        mock_sdk.return_value = StubBackend()
        target_repo = tmp_path / "target-repo"
        target_repo.mkdir()
        req_file = tmp_path / "req.yaml"
        req_file.write_text("op: gelu\n")

        exit_code = dispatch({**_golden_required("gelu", tmp_path),
            "mode": "new",
            "target_repo": str(target_repo),
            "repo_profile": "omni-ops",
            "op_name": "gelu",
            "requirement_path": str(req_file),
            "npu_id": 0,
            "non_interactive": True,
            "max_iterations": 1,
            # Stub-mode plumbing test: StubBackend by construction, asserts a
            # halt (EX_DATAERR), never compiles. enable_stubbed is the explicit
            # opt-in that skips the CANN preflight (no real toolchain needed).
            "enable_stubbed": True,
            "output_root": str(tmp_path / "output"),
        })
        # Stub backend produces no real requirement, so design halts at its
        # gate (EX_DATAERR). Events for the stages that ran are still recorded.
        assert exit_code == EX_DATAERR

        # Find workspace
        output = tmp_path / "output"
        run_dirs = [d for d in output.iterdir() if d.is_dir()]
        assert len(run_dirs) == 1
        ws = run_dirs[0]

        # events.jsonl must record stage lifecycle events for stages that ran
        events_path = ws / "events.jsonl"
        assert events_path.exists()
        events = [json.loads(l) for l in events_path.read_text().strip().split("\n") if l.strip()]
        event_types = {e["type"] for e in events}
        for t in ("stage_enter", "stage_complete"):
            assert t in event_types, f"Missing event type: {t}"

        # Entry stage always runs (has inputs from task_request).
        # design-halt-diagnostics P2: stage_enter uses the same scope-prefixed
        # label as stage_complete (e.g. "generate_ascendc/entry/entry"), not
        # the bare stage name.
        stages_seen = {e["stage"] for e in events if e["type"] == "stage_enter"}
        assert any(s.endswith("/entry") for s in stages_seen), stages_seen

    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_state_snapshot_accumulates_fields(self, mock_sdk, tmp_path):
        mock_sdk.return_value = StubBackend()
        target_repo = tmp_path / "target-repo"
        target_repo.mkdir()
        req_file = tmp_path / "req.yaml"
        req_file.write_text("op: gelu\n")

        exit_code = dispatch({**_golden_required("gelu", tmp_path),
            "mode": "new",
            "target_repo": str(target_repo),
            "repo_profile": "omni-ops",
            "op_name": "gelu",
            "requirement_path": str(req_file),
            "npu_id": 0,
            "non_interactive": True,
            "max_iterations": 1,
            # Stub-mode plumbing test: StubBackend by construction, asserts a
            # halt (EX_DATAERR), never compiles. enable_stubbed is the explicit
            # opt-in that skips the CANN preflight (no real toolchain needed).
            "enable_stubbed": True,
            "output_root": str(tmp_path / "output"),
        })
        assert exit_code == EX_DATAERR

        output = tmp_path / "output"
        run_dirs = [d for d in output.iterdir() if d.is_dir()]
        snapshot = json.loads((run_dirs[0] / "state_snapshot.json").read_text())

        # State must carry forward field set from earlier stages
        assert snapshot["mode"] == "new"
        assert snapshot["op_name"] == "gelu"
        assert snapshot["repo_profile_name"] == "omni-ops"

    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_report_generated(self, mock_sdk, tmp_path):
        mock_sdk.return_value = StubBackend()
        target_repo = tmp_path / "target-repo"
        target_repo.mkdir()
        req_file = tmp_path / "req.yaml"
        req_file.write_text("op: gelu\n")

        exit_code = dispatch({**_golden_required("gelu", tmp_path),
            "mode": "new",
            "target_repo": str(target_repo),
            "repo_profile": "omni-ops",
            "op_name": "gelu",
            "requirement_path": str(req_file),
            "non_interactive": True,
            "max_iterations": 1,
            # Stub-mode plumbing test: StubBackend by construction, asserts a
            # halt (EX_DATAERR), never compiles. enable_stubbed is the explicit
            # opt-in that skips the CANN preflight (no real toolchain needed).
            "enable_stubbed": True,
            "output_root": str(tmp_path / "output"),
        })
        assert exit_code == EX_DATAERR

        output = tmp_path / "output"
        run_dirs = [d for d in output.iterdir() if d.is_dir()]
        ws = run_dirs[0]

        # report.md
        report_md = ws / "report.md"
        assert report_md.exists()
        content = report_md.read_text()
        assert "ascendc-devkit" in content.lower() or "Pipeline" in content or "Report" in content

        # report.json
        report_json = ws / "report.json"
        assert report_json.exists()
        data = json.loads(report_json.read_text())
        assert "run_id" in data

    @mock.patch("ascendc_devkit.application.dispatcher._generate_report")
    @mock.patch("ascendc_devkit.orchestration.graph_executor.GraphExecutor")
    def test_report_generated_on_timeout_path(self, mock_exec_cls, mock_report,
                                              tmp_path):
        """D8 re-scope: the timeout exit path generates a report.

        Previously only PreconditionError + normal completion called
        _generate_report; the WorkflowTimeoutError branch (the hard-timeout
        scenario) returned EX_TIMEOUT with NO report. The finally-block now
        covers every terminal exit. Verified by asserting _generate_report is
        called on the timeout path."""
        from ascendc_devkit.domain.exceptions import WorkflowTimeoutError
        from ascendc_devkit.orchestration.kernel.state import State
        fake_exec = mock.MagicMock()
        fake_exec.execute.side_effect = WorkflowTimeoutError(
            0.0, budget_sec=1, elapsed_sec=0)
        fake_exec.latest_state = State(mode="new", op_name="gelu")
        mock_exec_cls.return_value = fake_exec

        target_repo = tmp_path / "target-repo"
        target_repo.mkdir()
        req_file = tmp_path / "req.yaml"
        req_file.write_text("op: gelu\n")
        exit_code = dispatch({**_golden_required("gelu", tmp_path),
            "mode": "new", "target_repo": str(target_repo), "repo_profile": "omni-ops",
            "op_name": "gelu", "requirement_path": str(req_file),
            "non_interactive": True, "max_iterations": 1, "enable_stubbed": True,
            "output_root": str(tmp_path / "output")})
        assert exit_code == EX_TIMEOUT
        mock_report.assert_called_once()  # report generated on timeout path

    @mock.patch("ascendc_devkit.application.dispatcher._generate_report")
    @mock.patch("ascendc_devkit.orchestration.graph_executor.GraphExecutor")
    def test_no_report_on_decision_pause(self, mock_exec_cls, mock_report, tmp_path):
        """D8 re-scope: DecisionPendingError is a PAUSE (run resumes later and
        regenerates the report), not a terminal exit — no report now. Also
        _generate_report sweeps skills anchors at its tail, which must NOT run
        mid-pause (the run continues)."""
        from ascendc_devkit.domain.exceptions import DecisionPendingError
        from ascendc_devkit.orchestration.kernel.state import State
        fake_exec = mock.MagicMock()
        fake_exec.execute.side_effect = DecisionPendingError(
            "which chip?", ["A2", "A5"], str(tmp_path))
        fake_exec.latest_state = State(mode="new", op_name="gelu")
        mock_exec_cls.return_value = fake_exec

        target_repo = tmp_path / "target-repo"
        target_repo.mkdir()
        req_file = tmp_path / "req.yaml"
        req_file.write_text("op: gelu\n")
        exit_code = dispatch({**_golden_required("gelu", tmp_path),
            "mode": "new", "target_repo": str(target_repo), "repo_profile": "omni-ops",
            "op_name": "gelu", "requirement_path": str(req_file),
            "non_interactive": True, "max_iterations": 1, "enable_stubbed": True,
            "output_root": str(tmp_path / "output")})
        assert exit_code == EX_DECISION_PENDING
        mock_report.assert_not_called()  # pause: no report (resume regenerates)


# ────────────────────────────────────────────────────────────
# Test 2: Materialize operator in target repo
# ────────────────────────────────────────────────────────────

class TestOperatorMaterialization:
    """Verify GenericRepositoryAdapter writes operator files into a real temp repo."""

    def test_materialize_creates_directory(self, omni_ops_profile, sample_operator_spec, tmp_path):
        adapter = GenericRepositoryAdapter(omni_ops_profile)
        sources = {
            "gelu_kernel.cpp": "// kernel implementation",
            "gelu_kernel.h": "// kernel header",
            "gelu_tiling.cpp": "// tiling implementation",
        }
        op_dir = tmp_path / "repo" / "inference" / "ascendc" / "src" / "g" / "c" / "ai_infra_test_gelu"

        files = adapter.materialize_new_operator(
            sample_operator_spec, sources, tmp_path / "repo", op_dir=op_dir)

        assert len(files) == 3
        assert op_dir.is_dir()
        assert (op_dir / "gelu_kernel.cpp").read_text() == "// kernel implementation"
        assert (op_dir / "gelu_kernel.h").read_text() == "// kernel header"

    def test_materialize_falls_back_to_dest_root(self, sample_operator_spec, tmp_path):
        profile = RepositoryProfile(name="empty", display_name="Empty")
        adapter = GenericRepositoryAdapter(profile)
        files = adapter.materialize_new_operator(
            sample_operator_spec, {"k.cpp": "// c"}, tmp_path)
        assert len(files) == 1
        assert (tmp_path / "k.cpp").exists()

    def test_materialize_with_nested_sources(self, omni_ops_profile, sample_operator_spec, tmp_path):
        adapter = GenericRepositoryAdapter(omni_ops_profile)
        sources = {
            "src/kernel.cpp": "// kernel",
            "include/kernel.h": "// header",
        }
        op_dir = tmp_path / "custom_ops" / "test_gelu"
        files = adapter.materialize_new_operator(
            sample_operator_spec, sources, tmp_path, op_dir=op_dir)
        assert len(files) == 2
        assert (op_dir / "src" / "kernel.cpp").exists()
        assert (op_dir / "include" / "kernel.h").exists()

    def test_build_no_variant_match_fails(self, sample_operator_identity, tmp_path):
        """omni-ops op_dir outside any match_prefix → failed build with guidance."""
        profile = ProfileLoader.load("omni-ops")
        adapter = GenericRepositoryAdapter(profile)
        result = adapter.build(tmp_path, sample_operator_identity, "A2")
        assert result.passed is False
        assert "match_prefix" in result.stderr

    def test_build_runs_variant_stage(self, sample_operator_spec, tmp_path):
        from ascendc_devkit.domain.repository import (
            RepositoryProfile, BuildVariant, BuildStage,
        )
        marker = tmp_path / "stamp.txt"
        profile = RepositoryProfile(
            name="echo-build",
            build_variants=(BuildVariant(
                name="default", match_prefix="src",
                stages=(BuildStage(
                    name="ascendc", cwd=".",
                    command_template=f"echo built {{full_op_name}} on {{chip_version}} > {marker}"),),
            ),),
        )
        adapter = GenericRepositoryAdapter(profile)
        op_dir = tmp_path / "src" / "ai_infra_test_gelu"
        op_dir.mkdir(parents=True)
        op = OperatorIdentity(spec=sample_operator_spec, repo_root=tmp_path, op_dir=op_dir)
        result = adapter.build(tmp_path, op, "A2")
        assert result.passed is True
        assert "built ai_infra_test_gelu on A2" in marker.read_text()

    def test_scan_existing_operator_finds_files(self, omni_ops_profile, tmp_path):
        op_dir = tmp_path / "custom_ops" / "gelu"
        op_dir.mkdir(parents=True)
        (op_dir / "gelu.h").write_text("// gelu header")
        (op_dir / "gelu.cpp").write_text("// gelu kernel")
        adapter = GenericRepositoryAdapter(omni_ops_profile)
        result = adapter.scan_existing_operator(tmp_path, "gelu", op_dir=op_dir)
        assert result.spec.name == "gelu"
        assert result.op_dir == op_dir
        assert len(result.files) >= 2

    def test_ops_nn_materialize_into_op_dir(self, sample_operator_spec, tmp_path):
        """ops-nn (no prefix, single variant): write into the given op_dir."""
        profile = ProfileLoader.load("ops-nn")
        adapter = GenericRepositoryAdapter(profile)
        sources = {
            "op_kernel/gelu_v3.cpp": "// gelu v3 kernel",
            "op_api/gelu_v3.cpp": "// gelu v3 op_api",
        }
        op_dir = tmp_path / "repo" / "activation" / "gelu_v3"
        files = adapter.materialize_new_operator(
            sample_operator_spec, sources, tmp_path / "repo", op_dir=op_dir,
        )
        assert len(files) == 2
        assert (op_dir / "op_kernel" / "gelu_v3.cpp").read_text() == "// gelu v3 kernel"
        assert (op_dir / "op_api" / "gelu_v3.cpp").read_text() == "// gelu v3 op_api"

    def test_scan_requires_op_dir(self, sample_operator_spec, tmp_path):
        profile = ProfileLoader.load("ops-nn")
        adapter = GenericRepositoryAdapter(profile)
        with pytest.raises(ValueError, match="op_dir"):
            adapter.scan_existing_operator(tmp_path, "gelu_v3")


# ────────────────────────────────────────────────────────────
# Test 3: State snapshot consistency across Stage dispatch
# ────────────────────────────────────────────────────────────

class TestStateSnapshotConsistency:
    """Verify state_snapshot.json accumulates fields as stages run sequentially."""

    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_entry_then_context_state_accumulation(self, mock_sdk, tmp_path):
        mock_sdk.return_value = StubBackend()
        target_repo = tmp_path / "repo"
        target_repo.mkdir()

        # Run entry stage
        state_file = tmp_path / "entry_state.json"
        op_dir = target_repo / "inference" / "ascendc" / "src" / "g" / "c" / "ai_infra_gelu"
        state_file.write_text(json.dumps({
            "mode": "new",
            "task_request": {
                "mode": "new", "op_name": "gelu",
                "target_repo": str(target_repo),
                "repo_root": str(target_repo),
                "op_dir": str(op_dir),
                "rel_op_dir": "inference/ascendc/src/g/c/ai_infra_gelu",
                "full_op_name": "ai_infra_gelu",
                "repo_profile": "omni-ops",
            },
        }))
        exit_code = dispatch_single_stage(
            "entry", state_file=state_file, non_interactive=True,
            output_root=str(tmp_path / "output1"),
        )
        assert exit_code == 0

        # Read entry output state
        output1 = tmp_path / "output1"
        run1 = [d for d in output1.iterdir() if d.is_dir()][0]
        entry_snapshot = json.loads((run1 / "state_snapshot.json").read_text())
        assert entry_snapshot["mode"] == "new"
        assert entry_snapshot["op_name"] == "gelu"
        assert entry_snapshot["repo_profile_name"] == "omni-ops"

        # Feed entry output into context stage
        context_state = tmp_path / "context_state.json"
        context_state.write_text(json.dumps(entry_snapshot))
        exit_code = dispatch_single_stage(
            "context", state_file=context_state, non_interactive=True,
            output_root=str(tmp_path / "output2"),
        )
        assert exit_code == 0

        output2 = tmp_path / "output2"
        run2 = [d for d in output2.iterdir() if d.is_dir()][0]
        context_snapshot = json.loads((run2 / "state_snapshot.json").read_text())
        # Fields from entry should still be present
        assert context_snapshot["op_name"] == "gelu"
        # Context stage should have loaded profile + adapter
        assert context_snapshot.get("profile") is not None

    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_from_run_id_loads_previous_state(self, mock_sdk, tmp_path):
        mock_sdk.return_value = StubBackend()
        target_repo = tmp_path / "repo"
        target_repo.mkdir()

        # Run entry stage
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({
            "mode": "new",
            "task_request": {
                "mode": "new", "op_name": "gelu",
                "target_repo": str(target_repo),
                "repo_profile": "omni-ops",
            },
        }))
        output_root = str(tmp_path / "output")
        exit_code = dispatch_single_stage(
            "entry", state_file=state_file, non_interactive=True,
            output_root=output_root,
        )
        assert exit_code == 0
        output = tmp_path / "output"
        run_dir = [d for d in output.iterdir() if d.is_dir()][0]
        run_id = run_dir.name

        # Now run context using --from-run to pick up entry state
        exit_code = dispatch_single_stage(
            "context", from_run_id=run_id, non_interactive=True,
            output_root=output_root,
        )
        assert exit_code == 0


# ────────────────────────────────────────────────────────────
# Test 4: Decision pending → respond → resume full cycle
# ────────────────────────────────────────────────────────────

class TestDecisionPendingResumeLoop:
    """Verify abort→respond→resume cycle: pipeline pauses on decision,
    user responds via CLI, resume continues from breakpoint."""

    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_abort_writes_pending_decision_and_returns_exit_code(self, mock_sdk, tmp_path):
        """When non_interactive=True, on_decision=abort, a stage with
        AskUserQuestion should write pending_decision.json and return
        EX_DECISION_PENDING (73)."""
        mock_sdk.return_value = StubBackend()

        from ascendc_devkit.domain.exit_codes import EX_DECISION_PENDING

        # Use a stage that produces AskUserQuestion regardless of non_interactive
        # We need to test through the Runner directly since ContextStage
        # skips AskUserQuestion when non_interactive=True
        from ascendc_devkit.orchestration.base import Stage
        from ascendc_devkit.orchestration.kernel.runner import Runner
        from ascendc_devkit.orchestration.kernel.action import AskUserQuestion, Option
        from ascendc_devkit.orchestration.kernel.state import State
        from ascendc_devkit.infra.workspace import Workspace

        # Build a stage that always emits AskUserQuestion
        ask_stage_cls = type("_AskStage", (Stage,), {
            "name": "ask_stage",
            "max_iterations": 2,
            "input_contract": lambda self: StageIOContract(requires=[]),
            "output_contract": lambda self: StageIOContract(provides=["decision"]),
            "actions": lambda self, state, iteration=1: [
                AskUserQuestion(
                    question="Pick one?",
                    options=[Option(label="A"), Option(label="B")],
                ),
            ],
        })
        ask_stage = ask_stage_cls()

        ws = Workspace.create(output_root=str(tmp_path / "output"))
        state = State(
            mode="new", op_name="test",
            non_interactive=True, on_decision="abort",
            run_id=ws.run_id,
            _workspace=ws,
        )

        runner = Runner(workspace=ws)
        from ascendc_devkit.domain.exceptions import DecisionPendingError

        with pytest.raises(DecisionPendingError):
            runner.run_stage(state, ask_stage)

        # pending_decision.json must exist
        pending = ws.dir / "pending_decision.json"
        assert pending.exists()
        data = json.loads(pending.read_text())
        assert data["question"] == "Pick one?"
        assert data["options"] == ["A", "B"]

    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_respond_then_resume_completes_stage(self, mock_sdk, tmp_path):
        """After abort, write decision_response.json, then resume: the
        runner should consume the response and complete the stage."""
        mock_sdk.return_value = StubBackend()

        from ascendc_devkit.orchestration.base import Stage
        from ascendc_devkit.orchestration.kernel.runner import Runner
        from ascendc_devkit.orchestration.kernel.action import AskUserQuestion, Option
        from ascendc_devkit.orchestration.kernel.state import State
        from ascendc_devkit.infra.workspace import Workspace
        from ascendc_devkit.domain.exceptions import DecisionPendingError

        # Use user_max_iterations=1 so only one AskUserQuestion is processed
        ask_stage_cls = type("_AskStageResume", (Stage,), {
            "name": "ask_stage",
            "max_iterations": 1,
            "input_contract": lambda self: StageIOContract(requires=[]),
            "output_contract": lambda self: StageIOContract(provides=[]),
            "actions": lambda self, state, iteration=1: [
                AskUserQuestion(
                    question="Pick one?",
                    options=[Option(label="A"), Option(label="B")],
                ),
            ],
            "transition": lambda self, state, result:
                state.with_updates(code_source=result.get("decision", "")),
        })
        ask_stage = ask_stage_cls()

        # First run: abort
        ws = Workspace.create(output_root=str(tmp_path / "output"))
        state = State(
            mode="new", op_name="test",
            non_interactive=True, on_decision="abort",
            run_id=ws.run_id,
            user_max_iterations=1,
            _workspace=ws,
        )

        runner = Runner(workspace=ws)
        with pytest.raises(DecisionPendingError):
            runner.run_stage(state, ask_stage)

        # Simulate respond CLI: write decision_response.json
        response = {
            "choice": 1,
            "selected": "A",
            "question": "Pick one?",
            "timestamp": "2026-05-28T00:00:00Z",
        }
        resp_path = ws.dir / "decision_response.json"
        resp_path.write_text(json.dumps(response))

        # Resume: create a new runner with decision_handler that reads response
        handler_called = []

        def resume_handler(question, options, default_index=None):
            handler_called.append(True)
            resp_data = json.loads(resp_path.read_text())
            resp_path.unlink()  # consume
            return resp_data["selected"]

        runner2 = Runner(workspace=ws, decision_handler=resume_handler)
        final_state = runner2.run_stage(state, ask_stage)
        # Handler was called and stage completed
        assert len(handler_called) == 1
        assert final_state.code_source == "A"

    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_default_on_decision_auto_selects_first_option(self, mock_sdk, tmp_path):
        """When on_decision=default, the runner auto-selects options[0]."""
        mock_sdk.return_value = StubBackend()

        from ascendc_devkit.orchestration.base import Stage
        from ascendc_devkit.orchestration.kernel.runner import Runner
        from ascendc_devkit.orchestration.kernel.action import AskUserQuestion, Option
        from ascendc_devkit.orchestration.kernel.state import State
        from ascendc_devkit.infra.workspace import Workspace

        ask_stage_cls = type("_AskStageDefault", (Stage,), {
            "name": "ask_stage",
            "max_iterations": 2,
            "input_contract": lambda self: StageIOContract(requires=[]),
            "output_contract": lambda self: StageIOContract(provides=[]),
            "actions": lambda self, state, iteration=1: [
                AskUserQuestion(
                    question="Pick one?",
                    options=[Option(label="A"), Option(label="B")],
                ),
            ],
            "transition": lambda self, state, result:
                state.with_updates(code_source=result.get("decision", "")),
        })
        ask_stage = ask_stage_cls()

        ws = Workspace.create(output_root=str(tmp_path / "output"))
        state = State(
            mode="new", op_name="test",
            non_interactive=True, on_decision="default",
            run_id=ws.run_id,
            _workspace=ws,
        )

        runner = Runner(workspace=ws)
        final_state = runner.run_stage(state, ask_stage)
        # Auto-selected first option "A"
        assert final_state.code_source == "A"


# ────────────────────────────────────────────────────────────
# Test 5: Workflow and Stage timeout
# ────────────────────────────────────────────────────────────

class TestTimeoutEndToEnd:
    """Verify timeout behaviour at the Runner level."""

    def test_stage_timeout_raises_in_runner(self, tmp_path):
        """Runner._check_timeout() raises StageTimeoutError when _stage_deadline is past."""
        from ascendc_devkit.orchestration.kernel.runner import Runner
        from ascendc_devkit.domain.exceptions import StageTimeoutError

        runner = Runner()
        runner._stage_deadline = 0.0  # epoch — always in the past

        with pytest.raises(StageTimeoutError) as exc_info:
            runner._check_timeout("long_stage")
        assert exc_info.value.stage_name == "long_stage"

    def test_workflow_timeout_raises_in_runner(self, tmp_path):
        """Runner with a past workflow deadline should raise WorkflowTimeoutError."""
        from ascendc_devkit.orchestration.base import Stage
        from ascendc_devkit.orchestration.kernel.runner import Runner
        from ascendc_devkit.orchestration.kernel.action import NoOp
        from ascendc_devkit.orchestration.kernel.state import State
        from ascendc_devkit.domain.exceptions import WorkflowTimeoutError

        long_stage_cls = type("_WFTimeoutStage", (Stage,), {
            "name": "wf_timeout_stage",
            "max_iterations": 5,
            "input_contract": lambda self: StageIOContract(requires=[]),
            "output_contract": lambda self: StageIOContract(provides=[]),
            "actions": lambda self, state, iteration=1: [NoOp()],
        })
        long_stage = long_stage_cls()

        state = State(mode="new", op_name="test")
        runner = Runner()
        # Set a past deadline; run_stage won't recompute it since
        # state.workflow_timeout_sec == 0, but _check_timeout checks _workflow_deadline
        runner._workflow_deadline = 0.0

        with pytest.raises(WorkflowTimeoutError):
            runner.run_stage(state, long_stage)

    def test_timeout_does_not_fire_when_deadline_in_future(self, tmp_path):
        """When deadline is far in the future, timeout should not fire."""
        from ascendc_devkit.orchestration.base import Stage
        from ascendc_devkit.orchestration.kernel.runner import Runner
        from ascendc_devkit.orchestration.kernel.action import NoOp
        from ascendc_devkit.orchestration.kernel.state import State

        short_stage_cls = type("_ShortStageNoTimeout", (Stage,), {
            "name": "short_stage",
            "max_iterations": 2,
            "input_contract": lambda self: StageIOContract(requires=[]),
            "output_contract": lambda self: StageIOContract(provides=[]),
            "actions": lambda self, state, iteration=1: [NoOp()],
        })
        short_stage = short_stage_cls()

        state = State(mode="new", op_name="test")
        runner = Runner()
        # Set deadline far in the future — should not fire
        runner._workflow_deadline = time.time() + 3600

        result = runner.run_stage(state, short_stage)
        assert result.stage_iterations.get("short_stage", 0) > 0

    def test_stage_timeout_via_state_timeout_sec(self, tmp_path):
        """When state has stage_timeout_sec > 0, run_stage sets _stage_deadline.
        We mock time.monotonic to ensure the deadline is exceeded."""
        from ascendc_devkit.orchestration.base import Stage
        from ascendc_devkit.orchestration.kernel.runner import Runner
        from ascendc_devkit.orchestration.kernel.action import NoOp
        from ascendc_devkit.orchestration.kernel.state import State
        from ascendc_devkit.domain.exceptions import StageTimeoutError

        long_stage_cls = type("_TimedStage", (Stage,), {
            "name": "timed_stage",
            "max_iterations": 100,
            "input_contract": lambda self: StageIOContract(requires=[]),
            "output_contract": lambda self: StageIOContract(provides=[]),
            "actions": lambda self, state, iteration=1: [NoOp()],
        })
        long_stage = long_stage_cls()

        state = State(
            mode="new", op_name="test",
            stage_timeout_sec=1,
            user_max_iterations=100,
        )

        runner = Runner()
        # Mock monotonic: return 0 on first call (setting deadline to 1),
        # then return 100 on subsequent calls (exceeding deadline)
        call_count = [0]

        def fake_monotonic():
            call_count[0] += 1
            if call_count[0] == 1:
                return 0.0
            return 100.0

        with mock.patch("ascendc_devkit.orchestration.kernel.runner.time.monotonic", fake_monotonic):
            with pytest.raises(StageTimeoutError) as exc_info:
                runner.run_stage(state, long_stage)
            assert exc_info.value.stage_name == "timed_stage"

    def test_workflow_timeout_via_state_timeout_sec(self, tmp_path):
        """When state has workflow_timeout_sec > 0, run_stage sets _workflow_deadline
        and raises WorkflowTimeoutError when exceeded."""
        from ascendc_devkit.orchestration.base import Stage
        from ascendc_devkit.orchestration.kernel.runner import Runner
        from ascendc_devkit.orchestration.kernel.action import NoOp
        from ascendc_devkit.orchestration.kernel.state import State
        from ascendc_devkit.domain.exceptions import WorkflowTimeoutError

        long_stage_cls = type("_WFTimedStage", (Stage,), {
            "name": "wf_timed_stage",
            "max_iterations": 100,
            "input_contract": lambda self: StageIOContract(requires=[]),
            "output_contract": lambda self: StageIOContract(provides=[]),
            "actions": lambda self, state, iteration=1: [NoOp()],
        })
        long_stage = long_stage_cls()

        state = State(
            mode="new", op_name="test",
            workflow_timeout_sec=1,
            user_max_iterations=100,
        )

        runner = Runner()
        call_count = [0]

        def fake_monotonic():
            call_count[0] += 1
            if call_count[0] == 1:
                return 0.0
            return 100.0

        with mock.patch("ascendc_devkit.orchestration.kernel.runner.time.monotonic", fake_monotonic):
            with pytest.raises(WorkflowTimeoutError):
                runner.run_stage(state, long_stage)


# ────────────────────────────────────────────────────────────
# Test 6: Progress callback end-to-end
# ────────────────────────────────────────────────────────────

class TestProgressCallbackEndToEnd:
    """Verify progress_callback flows through dispatch → Runner → stage lifecycle."""

    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_dispatch_passes_callback_to_runner(self, mock_sdk, tmp_path):
        """dispatch() accepts progress_callback and passes it through
        to Runner, which calls it at stage boundaries."""
        mock_sdk.return_value = StubBackend()

        target_repo = tmp_path / "target-repo"
        target_repo.mkdir()
        req_file = tmp_path / "req.yaml"
        req_file.write_text("op: gelu\n")

        events = []
        def track(event_type, stage_name, metadata=None):
            events.append((event_type, stage_name))

        exit_code = dispatch({**_golden_required("gelu", tmp_path),
            "mode": "new",
            "target_repo": str(target_repo),
            "repo_profile": "omni-ops",
            "op_name": "gelu",
            "requirement_path": str(req_file),
            "npu_id": 0,
            "non_interactive": True,
            "max_iterations": 1,
            # Stub-mode plumbing test: StubBackend by construction, asserts a
            # halt (EX_DATAERR), never compiles. enable_stubbed is the explicit
            # opt-in that skips the CANN preflight (no real toolchain needed).
            "enable_stubbed": True,
            "output_root": str(tmp_path / "output"),
        }, progress_callback=track)

        assert exit_code == EX_DATAERR
        # At minimum, stage_start and stage_end events should fire
        event_types = {e[0] for e in events}
        assert "stage_start" in event_types
        assert "stage_end" in event_types or "stage_complete" in event_types

    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_callback_sees_all_pipeline_stages(self, mock_sdk, tmp_path):
        """Progress callback should fire for each stage in the pipeline."""
        mock_sdk.return_value = StubBackend()

        target_repo = tmp_path / "target-repo"
        target_repo.mkdir()
        req_file = tmp_path / "req.yaml"
        req_file.write_text("op: gelu\n")

        stages_seen = []
        def track(event_type, stage_name, metadata=None):
            if event_type == "stage_start":
                stages_seen.append(stage_name)

        exit_code = dispatch({**_golden_required("gelu", tmp_path),
            "mode": "new",
            "target_repo": str(target_repo),
            "repo_profile": "omni-ops",
            "op_name": "gelu",
            "requirement_path": str(req_file),
            "npu_id": 0,
            "non_interactive": True,
            "max_iterations": 1,
            # Stub-mode plumbing test: StubBackend by construction, asserts a
            # halt (EX_DATAERR), never compiles. enable_stubbed is the explicit
            # opt-in that skips the CANN preflight (no real toolchain needed).
            "enable_stubbed": True,
            "output_root": str(tmp_path / "output"),
        }, progress_callback=track)

        assert exit_code == EX_DATAERR
        # entry, context, requirement fire; design then halts at validate_inputs
        # (stub backend produced no requirement, and reference_code/design_spec
        # are empty) — the former precondition gate was replaced by a
        # resolve_condition loop-back, so the halt now comes from validate_inputs.
        assert len(stages_seen) >= 3  # at least entry, context, requirement
        assert "entry" in stages_seen


# ────────────────────────────────────────────────────────────
# Test 7: Incremental mode end-to-end
# ────────────────────────────────────────────────────────────

class TestIncrementalModeEndToEnd:
    """Verify incremental mode pipeline completes with existing operator."""

    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_incremental_mode_pipeline_starts(self, mock_sdk, tmp_path):
        """dispatch with mode='incremental' should start and process
        at least the entry stage (which validates incremental requirements)."""
        mock_sdk.return_value = StubBackend()

        target_repo = tmp_path / "target-repo"
        target_repo.mkdir()
        # Create an existing operator directory for incremental mode
        op_dir = target_repo / "custom_ops" / "gelu"
        op_dir.mkdir(parents=True)
        (op_dir / "gelu.cpp").write_text("// existing kernel")
        req_file = tmp_path / "req.yaml"
        req_file.write_text("op: gelu\n")

        exit_code = dispatch({**_golden_required("gelu", tmp_path),
            "mode": "incremental",
            "target_repo": str(target_repo),
            "repo_profile": "omni-ops",
            "op_name": "gelu",
            "requirement_path": str(req_file),
            "npu_id": 0,
            "non_interactive": True,
            "max_iterations": 1,
            # Stub-mode plumbing test: StubBackend by construction, asserts a
            # halt (EX_DATAERR), never compiles. enable_stubbed is the explicit
            # opt-in that skips the CANN preflight (no real toolchain needed).
            "enable_stubbed": True,
            "output_root": str(tmp_path / "output"),
        })

        # Stub backend produced no requirement, so design halts at
        # validate_inputs (reference_code/design_spec empty). The former
        # precondition gate is gone; the run still advanced through
        # entry/context and recorded its progress.
        assert exit_code == EX_DATAERR

    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_incremental_mode_records_events(self, mock_sdk, tmp_path):
        """Incremental mode should record events and produce a state snapshot."""
        mock_sdk.return_value = StubBackend()

        target_repo = tmp_path / "target-repo"
        target_repo.mkdir()
        op_dir = target_repo / "custom_ops" / "gelu"
        op_dir.mkdir(parents=True)
        (op_dir / "gelu.cpp").write_text("// existing kernel")
        req_file = tmp_path / "req.yaml"
        req_file.write_text("op: gelu\n")

        exit_code = dispatch({**_golden_required("gelu", tmp_path),
            "mode": "incremental",
            "target_repo": str(target_repo),
            "repo_profile": "omni-ops",
            "op_name": "gelu",
            "requirement_path": str(req_file),
            "npu_id": 0,
            "non_interactive": True,
            "max_iterations": 1,
            # Stub-mode plumbing test: StubBackend by construction, asserts a
            # halt (EX_DATAERR), never compiles. enable_stubbed is the explicit
            # opt-in that skips the CANN preflight (no real toolchain needed).
            "enable_stubbed": True,
            "output_root": str(tmp_path / "output"),
        })

        assert exit_code == EX_DATAERR

        output = tmp_path / "output"
        run_dirs = [d for d in output.iterdir() if d.is_dir()]
        assert len(run_dirs) == 1
        ws = run_dirs[0]

        # events.jsonl must exist
        events_path = ws / "events.jsonl"
        assert events_path.exists()
        events = [json.loads(l) for l in events_path.read_text().strip().split("\n") if l.strip()]
        event_types = {e["type"] for e in events}
        assert "stage_enter" in event_types

        # state_snapshot must exist
        snapshot_path = ws / "state_snapshot.json"
        assert snapshot_path.exists()
        snapshot = json.loads(snapshot_path.read_text())
        assert snapshot["mode"] == "incremental"
        assert snapshot["op_name"] == "gelu"


# ────────────────────────────────────────────────────────────
# Test 8: Event log replay (show command backend)
# ────────────────────────────────────────────────────────────

class TestEventLogReplay:
    """Verify EventLog.read() and replay behaviour used by show command."""

    def test_event_log_read_empty_returns_empty_list(self, tmp_path):
        """Reading a non-existent events file returns empty list."""
        from ascendc_devkit.infra.event_log import EventLog

        events = EventLog.read(tmp_path / "nonexistent.jsonl")
        assert events == []

    def test_event_log_read_parses_events(self, tmp_path):
        """EventLog.read() correctly parses events.jsonl."""
        from ascendc_devkit.infra.event_log import EventLog

        events_path = tmp_path / "events.jsonl"
        events_path.write_text(
            '{"type":"stage_enter","stage":"entry","ts":"2026-01-01T00:00:00Z"}\n'
            '{"type":"stage_complete","stage":"entry","ts":"2026-01-01T00:00:01Z"}\n'
        )
        events = EventLog.read(events_path)
        assert len(events) == 2
        assert events[0]["type"] == "stage_enter"
        assert events[1]["type"] == "stage_complete"

    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_full_pipeline_events_replay(self, mock_sdk, tmp_path):
        """A full pipeline run produces replayable events."""
        mock_sdk.return_value = StubBackend()
        from ascendc_devkit.infra.event_log import EventLog

        target_repo = tmp_path / "target-repo"
        target_repo.mkdir()
        req_file = tmp_path / "req.yaml"
        req_file.write_text("op: gelu\n")

        dispatch({**_golden_required("gelu", tmp_path),
            "mode": "new",
            "target_repo": str(target_repo),
            "repo_profile": "omni-ops",
            "op_name": "gelu",
            "requirement_path": str(req_file),
            "npu_id": 0,
            "non_interactive": True,
            "max_iterations": 1,
            # Stub-mode plumbing test: StubBackend by construction, asserts a
            # halt (EX_DATAERR), never compiles. enable_stubbed is the explicit
            # opt-in that skips the CANN preflight (no real toolchain needed).
            "enable_stubbed": True,
            "output_root": str(tmp_path / "output"),
        })

        output = tmp_path / "output"
        run_dirs = [d for d in output.iterdir() if d.is_dir()]
        events = EventLog.read(run_dirs[0] / "events.jsonl")

        # Verify events can be replayed. design-halt-diagnostics P2: stage_enter
        # uses the scope-prefixed label (e.g. "generate_ascendc/entry/entry"),
        # not the bare stage name.
        stage_names = {e["stage"] for e in events if e["type"] == "stage_enter"}
        assert any(s.endswith("/entry") for s in stage_names), stage_names
        event_types = {e["type"] for e in events}
        assert "stage_enter" in event_types
        assert "stage_complete" in event_types
