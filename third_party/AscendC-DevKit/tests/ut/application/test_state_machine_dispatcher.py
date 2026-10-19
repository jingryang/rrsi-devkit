"""Unit tests for the dispatcher's state-machine flow + terminal routing.

M4 (route_decision 死代码清理)：文件中原测 ``route_decision`` 簇
(``_handle_route_decision`` / ``_apply_route_counters`` / ``_format_error_for_display``)
与 dispatcher 死 helper (``_is_backward`` / ``_is_stagnating`` / ``_linear_next``)
的测试类已随死代码删除（§2.5 不留死通路；活等价覆盖在 test_graph_executor /
test_state_routing / test_composite_loopback）。此处保留守护活行为的测试：
dispatch 全流程、resume 快照、user_feedback 注入、interrupt resume hint。
"""

from __future__ import annotations

import json
import re
from unittest import mock

from ascendc_devkit.application.dispatcher import dispatch
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.domain.exit_codes import EX_DATAERR
from ascendc_devkit.infra.workspace import Workspace
from ascendc_devkit.capabilities.agent.stub_backend import StubBackend


class TestDispatchStateMachineFlow:
    """Verify the dispatcher uses state machine loop with new fields."""

    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_pipeline_completes_with_new_fields(self, mock_sdk, tmp_path):
        """Basic pipeline completes with new corrective/escalation fields."""
        mock_sdk.return_value = StubBackend()

        target_repo = tmp_path / "target-repo"
        target_repo.mkdir()
        output_root = tmp_path / "output"
        output_root.mkdir()
        req_file = tmp_path / "req.yaml"
        req_file.write_text("op: test_op\n")
        golden_file = tmp_path / "golden.py"
        golden_file.write_text("# golden\n")

        task_request = {
            "mode": "new",
            "workflow": "generate_ascendc",
            "target_repo": str(target_repo),
            "repo_profile": "ops-nn",
            "op_name": "test_op",
            "requirement_path": str(req_file),
            "golden_path": str(golden_file),
            "golden_entry": "test_op",
            "golden_input_type": "torch",
            "non_interactive": True,
            "on_decision": "default",
            "max_iterations": 5,
            "max_corrective": 5,
            "max_escalations": 2,
            "enable_stubbed": True,
            "output_root": str(output_root),
            "npu_id": 0,
        }

        exit_code = dispatch(task_request)
        assert exit_code == EX_DATAERR

        snapshots = list(output_root.glob("*/state_snapshot.json"))
        assert len(snapshots) >= 1

    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_dispatch_with_custom_quotas(self, mock_sdk, tmp_path):
        mock_sdk.return_value = StubBackend()

        target_repo = tmp_path / "target-repo"
        target_repo.mkdir()
        output_root = tmp_path / "output"
        output_root.mkdir()
        req_file = tmp_path / "req.yaml"
        req_file.write_text("op: test_op2\n")
        golden_file = tmp_path / "golden.py"
        golden_file.write_text("# golden\n")

        task_request = {
            "mode": "new",
            "workflow": "generate_ascendc",
            "target_repo": str(target_repo),
            "repo_profile": "ops-nn",
            "op_name": "test_op2",
            "requirement_path": str(req_file),
            "golden_path": str(golden_file),
            "golden_entry": "test_op2",
            "golden_input_type": "torch",
            "non_interactive": True,
            "on_decision": "default",
            "max_iterations": 5,
            "max_corrective": 7,
            "max_escalations": 3,
            "enable_stubbed": True,
            "output_root": str(output_root),
            "npu_id": 0,
        }

        exit_code = dispatch(task_request)
        assert exit_code == EX_DATAERR

        snapshots = list(output_root.glob("*/state_snapshot.json"))
        assert len(snapshots) >= 1
        snap = json.loads(snapshots[0].read_text())
        assert snap["max_corrective"] == 7
        assert snap["max_escalations"] == 3

    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_dispatch_binds_run_log_into_run_dir(self, mock_sdk, tmp_path):
        """dispatch wires a thread-local run.log into <run>/ at workspace creation.

        Guards the integration seam the isolated log_capture UTs can't see: that
        bind fires at the right site and the file lands inside output/<run_id>/,
        self-contained with state_snapshot.json. SDKBackend mocked to fail fast
        (no LLM) — deterministic, ms-level. Real Logger/agent text under a live
        LLM run is the heavy_llm e2e gate's job (§3.11), not this UT's.

        (P-BC1: single dispatch() runs synchronously in the calling thread, so
        the thread-local binding captures this run's Logger output — same
        behavior as the retired process-global _Tee, minus the sibling-thread
        race.)"""
        mock_sdk.return_value = StubBackend()

        target_repo = tmp_path / "target-repo"; target_repo.mkdir()
        output_root = tmp_path / "output"; output_root.mkdir()
        req_file = tmp_path / "req.yaml"; req_file.write_text("op: bind_run_log\n")
        golden_file = tmp_path / "golden.py"; golden_file.write_text("# golden\n")

        task_request = {
            "mode": "new", "workflow": "generate_ascendc",
            "target_repo": str(target_repo), "repo_profile": "ops-nn",
            "op_name": "bind_run_log", "requirement_path": str(req_file),
            "golden_path": str(golden_file), "golden_entry": "bind_run_log",
            "golden_input_type": "torch", "non_interactive": True,
            "on_decision": "default", "max_iterations": 5, "max_corrective": 5,
            "max_escalations": 2, "enable_stubbed": True,
            "output_root": str(output_root), "npu_id": 0,
        }

        exit_code = dispatch(task_request)
        # dispatch fails (chip-probe or SDK) but only AFTER workspace + bind fired.
        assert exit_code == EX_DATAERR

        run_logs = list(output_root.glob("*/run.log"))
        assert len(run_logs) == 1, f"expected one run.log in run dir, got {run_logs}"
        # Self-contained run dir: run.log sits beside state_snapshot.json.
        snaps = list(output_root.glob("*/state_snapshot.json"))
        assert len(snaps) >= 1
        assert run_logs[0].parent == snaps[0].parent
        # Thread-local run.log captured real Logger output — timestamped lines
        # landed in the file (proves the wiring end-to-end at orchestration level,
        # not just an empty file touched by open(); also confirms the
        # [YYYY-MM-DD HH:MM:SS] format).
        content = run_logs[0].read_text(encoding="utf-8")
        assert re.search(r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]", content)

    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_dispatch_binds_op_name_for_new_run(self, mock_sdk, tmp_path, monkeypatch):
        """AU-7 wiring: dispatch's new-run branch binds op_name (from
        task_request, same source State(op_name=...) uses below it) so
        opencode's agent_stream attribution can be batch-op-scoped
        (format_attribution reads it back via current_op_name()).

        Asserted via monkeypatching dispatcher.bind_op_name directly (not the
        ambient current_op_name()) — the module-level contextvar persists
        across tests in this same pytest worker thread, so reading it back
        here would be order-dependent; the isolated log_capture UTs already
        cover the contextvar's own set/get semantics."""
        mock_sdk.return_value = StubBackend()
        calls = []
        monkeypatch.setattr(
            "ascendc_devkit.application.dispatcher.bind_op_name",
            lambda name: calls.append(name))

        target_repo = tmp_path / "target-repo"; target_repo.mkdir()
        output_root = tmp_path / "output"; output_root.mkdir()
        req_file = tmp_path / "req.yaml"; req_file.write_text("op: bind_op_name\n")
        golden_file = tmp_path / "golden.py"; golden_file.write_text("# golden\n")

        task_request = {
            "mode": "new", "workflow": "generate_ascendc",
            "target_repo": str(target_repo), "repo_profile": "ops-nn",
            "op_name": "bind_op_name", "requirement_path": str(req_file),
            "golden_path": str(golden_file), "golden_entry": "bind_op_name",
            "golden_input_type": "torch", "non_interactive": True,
            "on_decision": "default", "max_iterations": 5, "max_corrective": 5,
            "max_escalations": 2, "enable_stubbed": True,
            "output_root": str(output_root), "npu_id": 0,
        }

        dispatch(task_request)

        assert calls == ["bind_op_name"]


class TestResumeWithLoopback:
    """Resume preserves the routing state that drives loop-back."""

    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_resume_preserves_routing_state(self, mock_sdk, tmp_path):
        mock_sdk.return_value = StubBackend()

        target_repo = tmp_path / "target-repo"
        target_repo.mkdir()
        output_root = tmp_path / "output"
        output_root.mkdir()
        req_file = tmp_path / "req.yaml"
        req_file.write_text("op: test_resume_lb\n")
        golden_file = tmp_path / "golden.py"
        golden_file.write_text("# golden\n")

        task_request = {
            "mode": "new",
            "workflow": "generate_ascendc",
            "target_repo": str(target_repo),
            "repo_profile": "ops-nn",
            "op_name": "test_resume_lb",
            "requirement_path": str(req_file),
            "golden_path": str(golden_file),
            "golden_entry": "test_resume_lb",
            "golden_input_type": "torch",
            "non_interactive": True,
            "on_decision": "default",
            "max_iterations": 5,
            "max_corrective": 5,
            "max_escalations": 2,
            "enable_stubbed": True,
            "output_root": str(output_root),
            "npu_id": 0,
        }
        exit_code = dispatch(task_request)
        # Stub backend halts at the design precondition (EX_DATAERR); the
        # snapshot is still written and must carry the routing authority.
        assert exit_code == EX_DATAERR

        snapshots = list(output_root.glob("*/state_snapshot.json"))
        snap = json.loads(snapshots[0].read_text())
        # routing_scopes is the SOLE loop-back authority (graph executor); node_status
        # the resume frontier. The quotas that bound them must round-trip.
        assert "routing_scopes" in snap
        assert "node_status" in snap
        assert "max_corrective" in snap
        assert "max_escalations" in snap


class TestUserFeedbackFlow:
    """User feedback is injected into agent prompts during loop-back."""

    def test_codegen_prompt_includes_user_feedback(self):
        from ascendc_devkit.orchestration.stages.codegen import CodegenStage
        stage = CodegenStage()
        state = State(
            mode="new",
            design_spec={"inputs": [{"name": "x"}], "outputs": [{"name": "y"}]},
            tiling_strategy={"tile_size": 256},
            kernel_architecture={"kernel_code": {"files": ["kernel.cpp"]}},
            user_feedback="use double buffer to avoid bank conflicts",
        )
        prompt = stage._build_codegen_prompt(state, 1)
        assert "用户反馈" in prompt
        assert "double buffer" in prompt

    def test_design_prompt_includes_user_feedback(self):
        # step-2b: the concept-design substage injects user_feedback via the
        # shared base prompt builder.
        from ascendc_devkit.orchestration.stages.design_substages import GeneralDesignStage
        stage = GeneralDesignStage()
        state = State(
            mode="new",
            user_feedback="consider multi-core parallel strategy",
        )
        prompt = stage._build_prompt(state, iteration=1)
        assert "用户反馈" in prompt
        assert "multi-core parallel" in prompt

    def test_prompt_without_user_feedback_does_not_include_section(self):
        from ascendc_devkit.orchestration.stages.codegen import CodegenStage
        stage = CodegenStage()
        state = State(mode="new", user_feedback="")
        prompt = stage._build_codegen_prompt(state, 1)
        assert "用户反馈" not in prompt


class TestPrintResumeHint:
    """Interrupt path surfaces the run ID and resume command."""

    def test_plain_interrupt_shows_resume_command(self, tmp_path, capsys):
        from ascendc_devkit.application.dispatcher import _print_resume_hint
        output_root = tmp_path / "output"
        workspace = Workspace.create(output_root=str(output_root))

        _print_resume_hint(workspace, str(output_root))

        err = capsys.readouterr().err
        assert workspace.run_id in err
        assert f"ascendc-devkit run --resume {workspace.run_id}" in err
        # No pending decision → no respond hint.
        assert "respond --run" not in err

    def test_interrupt_on_pending_decision_shows_respond_then_resume(
            self, tmp_path, capsys):
        from ascendc_devkit.application.dispatcher import _print_resume_hint
        output_root = tmp_path / "output"
        workspace = Workspace.create(output_root=str(output_root))
        # Simulate an unanswered decision captured before the interrupt.
        (workspace.dir / "pending_decision.json").write_text(
            json.dumps({"question": "q?", "options": ["a", "b"]})
        )

        _print_resume_hint(workspace, str(output_root))

        err = capsys.readouterr().err
        assert f"respond --run {workspace.run_id}" in err
        assert f"run --resume {workspace.run_id}" in err

    def test_answered_decision_skips_respond_hint(self, tmp_path, capsys):
        from ascendc_devkit.application.dispatcher import _print_resume_hint
        output_root = tmp_path / "output"
        workspace = Workspace.create(output_root=str(output_root))
        (workspace.dir / "pending_decision.json").write_text(
            json.dumps({"question": "q?", "options": ["a", "b"]})
        )
        # A response already exists → treat as a plain resume.
        (workspace.dir / "decision_response.json").write_text(
            json.dumps({"choice": 1})
        )

        _print_resume_hint(workspace, str(output_root))

        err = capsys.readouterr().err
        assert "respond --run" not in err
        assert f"run --resume {workspace.run_id}" in err
