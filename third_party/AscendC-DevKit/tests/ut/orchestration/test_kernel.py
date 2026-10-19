"""Unit tests for L3 Kernel — pure functions (state, transition, actions)."""

import copy
from unittest import mock

import pytest

from ascendc_devkit.orchestration.kernel.state import State, ErrorFeedback
from ascendc_devkit.orchestration.kernel.action import (
    SpawnAgent, RunGate, Integrate, AskUserQuestion, Option, NoOp, Action,
    UpdateDevRecord,
)
from ascendc_devkit.orchestration.kernel.event import (
    make_event, stage_enter, stage_complete, action_start, action_complete,
    iteration_start, iteration_complete,
)
from ascendc_devkit.orchestration.kernel.runner import (
    Runner, RunnerCancelledError,
)
from ascendc_devkit.domain.exceptions import (
    DecisionPendingError, WorkflowTimeoutError, StageTimeoutError,
)
from ascendc_devkit.orchestration.base import Stage, Gate, GateResult
from ascendc_devkit.domain.contract import StageIOContract
from ascendc_devkit.capabilities.agent.stub_backend import StubBackend
from ascendc_devkit.capabilities.agent.backend import AgentResult
from ascendc_devkit.infra.logger import Logger


class TestState:
    def test_empty_state(self):
        s = State.empty()
        assert s.mode == "new"
        assert s.run_id == ""

    def test_with_updates_immutable(self):
        s = State(mode="new", op_name="gelu")
        s2 = s.with_updates(mode="incremental")
        assert s.mode == "new"
        assert s2.mode == "incremental"
        assert s2.op_name == "gelu"

    def test_with_field(self):
        s = State.empty()
        s2 = s.with_field("mode", "incremental")
        assert s2.mode == "incremental"

    def test_has_all(self):
        s = State(mode="new", op_name="gelu")
        assert s.has_all(["mode", "op_name"])
        assert not s.has_all(["mode", "nonexistent"])
        assert not s.has_all(["op_spec"])

    def test_existing_fields(self):
        s = State(mode="new", run_id="abc", npu_id=0)
        fields = s.existing_fields()
        assert "mode" in fields
        assert "run_id" in fields
        assert "npu_id" in fields
        assert "op_spec" not in fields

    def test_snapshot_roundtrip(self):
        s = State(mode="new", op_name="gelu", run_id="test-1")
        snapshot = s.to_snapshot()
        assert snapshot["mode"] == "new"
        s2 = State.from_snapshot(snapshot)
        assert s2.mode == s.mode
        assert s2.op_name == s.op_name
        assert s2.run_id == s.run_id

    def test_stage_iterations(self):
        s = State(stage_iterations={"codegen": 3})
        assert s.stage_iterations["codegen"] == 3

    def test_error_feedback(self):
        err = ErrorFeedback(
            stage_name="codegen",
            error_type="compile_error",
            message="undefined symbol",
        )
        s = State(last_error=err)
        assert s.last_error.stage_name == "codegen"
        assert s.last_error.error_type == "compile_error"


class TestActions:
    def test_spawn_agent_defaults(self):
        a = SpawnAgent(agent_name="test", prompt="hello")
        assert a.agent_name == "test"
        assert a.context == {}
        assert a.max_retries == 3

    def test_spawn_agent_with_context(self):
        a = SpawnAgent(
            agent_name="coder",
            prompt="write code",
            context={"mode": "new"},
            skills=["debug"],
        )
        assert a.context["mode"] == "new"
        assert a.skills == ["debug"]

    def test_spawn_agent_model_defaults_to_none(self):
        """SpawnAgent.model defaults to None — SDK uses its own default."""
        a = SpawnAgent(agent_name="test", prompt="hello")
        assert a.model is None

    def test_spawn_agent_model_explicit(self):
        """SpawnAgent.model can be set to override the stage default."""
        a = SpawnAgent(agent_name="test", prompt="hello",
                       model="claude-opus-4-8")
        assert a.model == "claude-opus-4-8"

    def test_run_gate(self):
        a = RunGate(gate_name="build", evidence={"sources": {}})
        assert a.gate_name == "build"

    def test_ask_user_question(self):
        a = AskUserQuestion(
            question="what to do?",
            options=[Option(label="A"), Option(label="B")],
            default_index=0,
        )
        assert len(a.options) == 2
        assert a.default_index == 0

    def test_noop(self):
        a = NoOp()
        assert isinstance(a, Action)


class TestEvents:
    def test_make_event_has_ts(self):
        e = make_event("test", key="value")
        assert e["type"] == "test"
        assert e["key"] == "value"
        assert "ts" in e

    def test_stage_enter(self):
        e = stage_enter("codegen", 5, 9)
        assert e["type"] == "stage_enter"
        assert e["stage"] == "codegen"
        assert e["stage_index"] == 5

    def test_stage_complete(self):
        e = stage_complete("codegen", 3200, total_iterations=2)
        assert e["type"] == "stage_complete"
        assert e["elapsed_ms"] == 3200
        assert e["total_iterations"] == 2

    def test_action_events(self):
        e = action_start("spawn_agent", agent="coder")
        assert e["type"] == "action_start"
        assert e["action"] == "spawn_agent"

        e2 = action_complete("spawn_agent", result="ok", agent="coder")
        assert e2["result"] == "ok"


class TestGate:
    def test_gate_result(self):
        r = GateResult(passed=True, reason="all good", metrics={"diff": 0.001})
        assert r.passed
        assert "all good" in r.reason

        r2 = GateResult(passed=False, reason="failed")
        assert not r2.passed


class TestStageContract:
    class _DummyStage(Stage):
        name = "dummy"
        description = "test"

        def input_contract(self):
            return StageIOContract(requires=["x"], provides=["y"])

        def output_contract(self):
            return StageIOContract(provides=["y"])

        def actions(self, state, iteration=1):
            return []

    def test_stage_contract(self):
        s = self._DummyStage()
        assert s.name == "dummy"
        assert s.input_contract().requires == ["x"]
        assert s.output_contract().provides == ["y"]
        assert s.gate() is None

    def test_stage_max_iterations(self):
        s = self._DummyStage()
        assert s.default_max_iterations == 3


class TestIterationSafetyNet:
    """Task 2.1: interactive iteration_ceiling respects needs_iteration_safety_net.

    The runner surfaces iteration_ceiling via the progress callback's 'max' field;
    we capture it to assert what the status bar would display.
    """

    class _DeterministicStage(Stage):
        name = "det_stage"
        description = "single-pass, no agent"
        default_max_iterations = 1
        needs_iteration_safety_net = False

        def input_contract(self):
            return StageIOContract(requires=[], optional=[])

        def output_contract(self):
            return StageIOContract(provides=[])

        def actions(self, state, iteration=1):
            return [NoOp()]

    class _AgentStage(Stage):
        name = "agent_stage"
        description = "may need many rounds"
        default_max_iterations = 3
        # needs_iteration_safety_net defaults True

        def input_contract(self):
            return StageIOContract(requires=[], optional=[])

        def output_contract(self):
            return StageIOContract(provides=[])

        def actions(self, state, iteration=1):
            return [NoOp()]

    def _capture_max(self, stage):
        captured = {}

        def cb(event, stage_name, data):
            if event == "iteration_start":
                captured["max"] = data["max"]

        # Interactive mode (non_interactive=False) is where the safety net applies.
        state = State(mode="new")
        runner = Runner(agent_backend=StubBackend(), progress_callback=cb)
        runner.run_stage(state, stage)
        return captured.get("max")

    def test_deterministic_stage_shows_real_ceiling(self):
        assert self._capture_max(self._DeterministicStage()) == 1

    def test_agent_stage_keeps_safety_net(self):
        # The ceiling is the config-driven interactive safety net, not a
        # hardcoded literal (see test_safety_net_is_config_driven).
        from ascendc_devkit.orchestration import runtime_config
        assert (self._capture_max(self._AgentStage())
                == runtime_config.INTERACTIVE_ITERATION_SAFETY_NET)

    def _capture_max_with_state(self, stage, state):
        captured = {}

        def cb(event, stage_name, data):
            if event == "iteration_start":
                captured["max"] = data["max"]

        runner = Runner(agent_backend=StubBackend(), progress_callback=cb)
        runner.run_stage(state, stage)
        return captured.get("max")

    def test_explicit_user_cap_honored_in_interactive(self):
        """Regression: an explicit --max-iterations must be a hard cap even in
        interactive mode, not swallowed by the max(default, 100) safety net."""
        state = State(mode="new", user_max_iterations=5)  # interactive
        assert self._capture_max_with_state(self._AgentStage(), state) == 5

    def test_explicit_user_cap_honored_in_noninteractive(self):
        state = State(mode="new", user_max_iterations=5, non_interactive=True)
        assert self._capture_max_with_state(self._AgentStage(), state) == 5

    def test_unset_noninteractive_uses_stage_default(self):
        """Unset budget in non-interactive mode → each stage's own default
        (no magic global 5, no 100 safety net)."""
        state = State(mode="new", non_interactive=True)
        assert self._capture_max_with_state(self._AgentStage(), state) == 3

    def test_safety_net_is_config_driven(self):
        """The interactive safety net comes from resources/orchestration-config.json
        (runtime_config), not a hardcoded literal — overriding it changes the
        ceiling the runner applies."""
        with mock.patch(
            "ascendc_devkit.orchestration.runtime_config."
            "INTERACTIVE_ITERATION_SAFETY_NET", 42
        ):
            state = State(mode="new")  # interactive, unset budget
            assert self._capture_max_with_state(self._AgentStage(), state) == 42


class TestRunnerCancellation:
    """Verify Runner cancellation and graceful interrupt."""

    class _LongStage(Stage):
        name = "long_stage"
        description = "multi-iteration stage for cancellation test"
        default_max_iterations = 5

        def input_contract(self):
            return StageIOContract(requires=[], optional=[])

        def output_contract(self):
            return StageIOContract(provides=[])

        def actions(self, state, iteration=1):
            return [NoOp()]

    def test_cancel_raises_runner_cancelled_error(self):
        stage = self._LongStage()
        state = State(mode="new", user_max_iterations=5)
        runner = Runner(agent_backend=StubBackend())

        # Cancel before running
        runner.cancel()
        assert runner.is_cancelled is True

        with pytest.raises(RunnerCancelledError, match="Cancelled"):
            runner.run_stage(state, stage)

    def test_cancel_mid_iteration_loop(self):
        """Cancel after first iteration — should stop at iteration boundary."""
        stage = self._LongStage()
        state = State(mode="new", user_max_iterations=5)

        class CancelAfterOneRunner(Runner):
            def _execute_actions(self, actions, state=None):
                result = super()._execute_actions(actions, state)
                self.cancel()  # cancel after first action execution
                return result

        runner = CancelAfterOneRunner(agent_backend=StubBackend())
        with pytest.raises(RunnerCancelledError, match="Cancelled"):
            runner.run_stage(state, stage)
        # State was updated once before cancellation
        assert stage.default_max_iterations == 5  # stage not modified

    def test_cancel_not_set_by_default(self):
        runner = Runner()
        assert runner.is_cancelled is False


class TestDecisionPending:
    """Verify DecisionPendingError and decision_pending event."""

    def test_decision_pending_error_attributes(self):
        err = DecisionPendingError(
            question="Which tiling?",
            options=["tile_32", "tile_64"],
            workspace_dir="/tmp/ws",
        )
        assert err.question == "Which tiling?"
        assert err.options == ["tile_32", "tile_64"]
        assert err.workspace_dir == "/tmp/ws"
        assert "Which tiling?" in str(err)

    def test_decision_pending_event_helper(self):
        from ascendc_devkit.orchestration.kernel.event import decision_pending
        e = decision_pending("design", 2, "Pick strategy")
        assert e["type"] == "decision_pending"
        assert e["stage"] == "design"
        assert e["iteration"] == 2
        assert e["question"] == "Pick strategy"
        assert "ts" in e

    def test_decision_pending_written_to_event_log(self, tmp_path):
        """When DecisionPendingError is raised, event is written to events.jsonl."""
        from ascendc_devkit.infra.workspace import Workspace
        from ascendc_devkit.infra.event_log import EventLog

        ws = Workspace.create(output_root=str(tmp_path))
        event_log = EventLog(ws.events_path)

        # A backend that raises DecisionPendingError
        class _DecisionBackend(StubBackend):
            def spawn(self, agent_name, prompt, context, skills=None, model=None, working_dir=None, repo_baseline=None, repo_root=None, stage_name="", branch_label="", resume_session_id=None, resume_prompt=None, primary_skill=None, deadline_monotonic: float | None = None):
                raise DecisionPendingError(
                    question="Which one?",
                    options=["A", "B"],
                    workspace_dir=str(tmp_path),
                )

        # A stage that spawns an agent
        class _DecisionStage(Stage):
            name = "test_decision"
            description = "stage that hits a decision"
            default_max_iterations = 1

            def input_contract(self):
                return StageIOContract(requires=[], optional=[])

            def output_contract(self):
                return StageIOContract(provides=["decision_result"])

            def actions(self, state, iteration=1):
                return [SpawnAgent(agent_name="test", prompt="test")]

            def transition(self, state, result):
                return state

        stage = _DecisionStage()
        state = State(mode="new", user_max_iterations=1)
        runner = Runner(agent_backend=_DecisionBackend(), workspace=ws)

        with pytest.raises(DecisionPendingError):
            runner.run_stage(state, stage)

        # Verify decision_pending event is in events.jsonl
        events = EventLog.read(ws.events_path)
        decision_events = [e for e in events if e["type"] == "decision_pending"]
        assert len(decision_events) == 1
        assert decision_events[0]["stage"] == "test_decision"
        assert decision_events[0]["question"] == "Which one?"


class TestMaxIterations:
    """Verify max_iterations enforcement and stage fallback."""

    class _OutputNeededStage(Stage):
        name = "test_stage"
        description = "stage that never produces output"
        default_max_iterations = 3

        def input_contract(self):
            return StageIOContract(requires=[], optional=[])

        def output_contract(self):
            return StageIOContract(provides=["generated_sources"])

        def actions(self, state, iteration=1):
            return [NoOp()]

        def transition(self, state, result):
            return state  # never sets generated_sources

    def test_max_iterations_capped_by_state(self):
        stage = self._OutputNeededStage()
        state = State(mode="new", user_max_iterations=2, non_interactive=True)
        runner = Runner(agent_backend=StubBackend())
        final = runner.run_stage(state, stage)
        # Stage has user_max_iterations=3, but state caps at 2
        assert final.stage_iterations.get("test_stage", 0) == 2

    def test_missing_output_after_max_iterations(self):
        stage = self._OutputNeededStage()
        state = State(mode="new", user_max_iterations=2, non_interactive=True)
        runner = Runner(agent_backend=StubBackend())
        final = runner.run_stage(state, stage)
        # Output contract not satisfied — generated_sources stays None
        assert final.generated_sources is None

    def test_fallback_warning_emitted_when_output_unsatisfied(self):
        """Logger.warn is called when max_iterations reached without output_contract."""
        stage = self._OutputNeededStage()
        state = State(mode="new", user_max_iterations=2, non_interactive=True)
        runner = Runner(agent_backend=StubBackend())

        with mock.patch("ascendc_devkit.orchestration.kernel.runner.Logger.warn") as mock_warn:
            runner.run_stage(state, stage)
            # At least one warning about unsatisfied output_contract
            unsatisfied_calls = [
                c for c in mock_warn.call_args_list
                if "without satisfying output_contract" in str(c)
            ]
            assert len(unsatisfied_calls) == 1


class TestExecuteActionsRunGate:
    """Verify RunGate action execution (Slice 5)."""

    def test_run_gate_with_real_gate_evaluates(self):
        """RunGate with a gate instance actually calls gate.evaluate()."""

        class AlwaysFailGate(Gate):
            def evaluate(self, evidence):
                return GateResult(passed=False, reason="intentional failure",
                                  metrics={"count": 1})

        runner = Runner()
        action = RunGate(gate_name="test_gate", gate=AlwaysFailGate(),
                         evidence={"key": "value"})
        result = runner._execute_actions([action])
        gate_result = result["gate_result"]
        assert gate_result["gate"] == "test_gate"
        assert gate_result["passed"] is False
        assert gate_result["reason"] == "intentional failure"
        assert gate_result["metrics"] == {"count": 1}

    def test_run_gate_missing_gate_falls_back(self):
        """RunGate with no gate and no registry defaults to passed."""
        runner = Runner()
        action = RunGate(gate_name="nonexistent", evidence={})
        result = runner._execute_actions([action])
        assert result["gate_result"]["gate"] == "nonexistent"
        assert result["gate_result"]["passed"] is True

    def test_run_gate_from_registry(self):
        """RunGate resolved via gate_registry dict."""

        class CustomGate(Gate):
            def evaluate(self, evidence):
                return GateResult(passed=True, reason="from registry",
                                  metrics={"v": 42})

        runner = Runner(gate_registry={"custom": CustomGate()})
        action = RunGate(gate_name="custom", evidence={})
        result = runner._execute_actions([action])
        assert result["gate_result"]["gate"] == "custom"
        assert result["gate_result"]["passed"] is True
        assert result["gate_result"]["reason"] == "from registry"
        assert result["gate_result"]["metrics"] == {"v": 42}


class TestExecuteActionsIntegrate:
    """Verify Integrate action execution (Slice 5)."""

    def test_integrate_materialize_calls_adapter(self):
        """Integrate materialize_new_operator calls adapter and stores result."""
        from pathlib import Path
        import tempfile

        class FakeAdapter:
            def materialize_new_operator(self, op, sources, dest_root, category=None):
                return [Path("/fake/target/file.cpp")]

        runner = Runner(adapters={"repository": FakeAdapter()})
        action = Integrate(
            adapter_name="test",
            action="materialize_new_operator",
            operator="fake_op",
            sources={"k.cpp": "// code"},
            dest_root=Path(tempfile.gettempdir()),
        )
        result = runner._execute_actions([action])
        assert result["integration_result"]["status"] == "ok"
        assert result["integration_result"]["files"] == 1
        assert len(result["target_files"]) == 1

    def test_integrate_materialize_error(self):
        """Integration error is captured in result."""

        class FailingAdapter:
            def materialize_new_operator(self, op, sources, dest_root, category=None):
                raise RuntimeError("disk full")

        runner = Runner(adapters={"repository": FailingAdapter()})
        action = Integrate(
            adapter_name="test",
            action="materialize_new_operator",
            operator="fake_op",
            sources={"k.cpp": "// code"},
        )
        result = runner._execute_actions([action])
        assert result["integration_result"]["status"] == "error"
        assert "disk full" in result["integration_result"]["error"]

    def test_integrate_no_adapter_available(self):
        """Integration with no adapter produces error result."""
        runner = Runner()  # no adapters
        action = Integrate(adapter_name="test", action="materialize_new_operator")
        result = runner._execute_actions([action])
        assert result["integration_result"]["status"] == "error"
        assert "No repository adapter" in result["integration_result"]["error"]


class TestExecuteActionsAskUserQuestion:
    """Verify AskUserQuestion action execution (Slice 5)."""

    def test_non_interactive_default_returns_first_option(self):
        """non_interactive + default → auto-select option 0."""
        state = State(mode="new", non_interactive=True, on_decision="default")
        runner = Runner()
        action = AskUserQuestion(
            question="Which?",
            options=[Option(label="A"), Option(label="B"), Option(label="C")],
        )
        result = runner._execute_actions([action], state)
        assert result["decision"] == "A"

    def test_non_interactive_default_with_index(self):
        """default_index honoured in non-interactive default mode."""
        state = State(mode="new", non_interactive=True, on_decision="default")
        runner = Runner()
        action = AskUserQuestion(
            question="Which?",
            options=[Option(label="X"), Option(label="Y"), Option(label="Z")],
            default_index=1,
        )
        result = runner._execute_actions([action], state)
        assert result["decision"] == "Y"

    def test_non_interactive_abort_raises_decision_pending(self):
        """non_interactive + abort → raises DecisionPendingError."""
        import tempfile
        from pathlib import Path as P
        from ascendc_devkit.infra.workspace import Workspace

        with tempfile.TemporaryDirectory() as tmpd:
            ws = Workspace.create(output_root=tmpd)
            state = State(mode="new", non_interactive=True, on_decision="abort",
                          _workspace=ws)
            runner = Runner(workspace=ws)
            action = AskUserQuestion(
                question="Tiling strategy?",
                options=[Option(label="tile_32"), Option(label="tile_64")],
            )
            with pytest.raises(DecisionPendingError, match="Tiling strategy"):
                runner._execute_actions([action], state)
            # Verify pending_decision.json was written
            pending = P(ws.dir) / "pending_decision.json"
            assert pending.exists()

    def test_empty_options_returns_empty(self):
        """Empty options list → empty decision string."""
        state = State(mode="new", non_interactive=True, on_decision="default")
        runner = Runner()
        action = AskUserQuestion(question="Nothing?", options=[])
        result = runner._execute_actions([action], state)
        assert result["decision"] == ""

    def test_decision_handler_callback(self):
        """Injected decision_handler is called with question/options/default_index."""
        calls = []

        def handler(question, options, default_index=None):
            calls.append((question, options, default_index))
            return "handler_choice"

        runner = Runner(decision_handler=handler)
        action = AskUserQuestion(
            question="Test?",
            options=[Option(label="Opt1"), Option(label="Opt2")],
            default_index=1,
        )
        result = runner._execute_actions([action])
        assert result["decision"] == "handler_choice"
        assert len(calls) == 1
        assert calls[0][0] == "Test?"
        assert calls[0][1] == ["Opt1", "Opt2"]
        assert calls[0][2] == 1


class TestExecuteActionsSpawnAgent:
    """Verify SpawnAgent execution edge cases (Slice 5)."""

    def test_spawn_agent_no_backend_no_crash(self):
        """SpawnAgent without agent_backend does not raise UnboundLocalError."""
        runner = Runner()  # no agent_backend
        action = SpawnAgent(agent_name="test", prompt="hello", context={})
        result = runner._execute_actions([action])
        # Should not crash; result may have no agent_result key
        assert "agent_result" not in result or result["agent_result"] is None


class TestExecuteActionsUpdateDevRecord:
    """Verify UpdateDevRecord action execution (Slice 7)."""

    def test_update_dev_record_calls_adapter(self, tmp_path):
        """UpdateDevRecord with valid adapter writes dev_record."""
        from pathlib import Path

        op_dir = tmp_path / "ops" / "test_op"
        op_dir.mkdir(parents=True)

        class FakeAdapter:
            def write_dev_record(self, op_dir, entry):
                record_dir = op_dir / ".lingxi"
                record_dir.mkdir(parents=True, exist_ok=True)
                record_path = record_dir / "dev_record.md"
                record_path.write_text(f"## {entry['change_summary']}\n")
                return record_path

        runner = Runner(adapters={"repository": FakeAdapter()})
        action = UpdateDevRecord(
            path=op_dir,
            change_summary="Test change",
            target_files=["a.cpp", "b.h"],
            requirement_path="/tmp/req.md",
        )
        result = runner._execute_actions([action])
        assert result["dev_record"]["status"] == "ok"
        assert "dev_record.md" in result["dev_record"]["path"]
        dev_record = op_dir / ".lingxi" / "dev_record.md"
        assert dev_record.exists()

    def test_update_dev_record_no_adapter(self):
        """UpdateDevRecord without adapter logs error but doesn't crash."""
        runner = Runner()  # no adapters
        action = UpdateDevRecord(path="/tmp/ops/test_op")
        result = runner._execute_actions([action])
        assert result["dev_record"]["status"] == "error"
        assert "No repository adapter" in result["dev_record"]["error"]

    def test_update_dev_record_no_path(self):
        """UpdateDevRecord with None path skips gracefully."""
        runner = Runner(adapters={"repository": mock.MagicMock()})
        action = UpdateDevRecord(path=None)
        result = runner._execute_actions([action])
        assert result["dev_record"]["status"] == "skipped"
        assert "No op_dir path" in result["dev_record"]["reason"]


class TestProgressCallback:
    """Verify Runner calls progress_callback with correct events."""

    def _make_minimal_stage(self, stage_name="test_stage"):
        cls = type(f"_MinimalStage_{stage_name}", (Stage,), {
            "name": stage_name,
            "max_iterations": 2,
            "input_contract": lambda self: StageIOContract(requires=[]),
            "output_contract": lambda self: StageIOContract(provides=[]),
            "actions": lambda self, state, iteration=1: [NoOp()],
        })
        return cls()

    def test_callback_called_on_stage_start(self):
        calls = []
        def cb(event_type, stage_name, metadata):
            calls.append((event_type, stage_name))

        stage = self._make_minimal_stage()
        runner = Runner(progress_callback=cb)
        state = State(mode="new", op_name="test")
        runner.run_stage(state, stage)

        assert ("stage_start", "test_stage") in calls

    def test_callback_called_on_iteration_boundaries(self):
        calls = []
        def cb(event_type, stage_name, metadata):
            calls.append(event_type)

        stage = self._make_minimal_stage()
        runner = Runner(progress_callback=cb)
        state = State(mode="new", op_name="test")
        runner.run_stage(state, stage)

        assert "iteration_start" in calls
        assert "iteration_end" in calls

    def test_callback_called_on_stage_complete(self):
        calls = []
        def cb(event_type, stage_name, metadata):
            calls.append((event_type, stage_name, metadata))

        stage = self._make_minimal_stage()
        runner = Runner(progress_callback=cb)
        state = State(mode="new", op_name="test")
        runner.run_stage(state, stage)

        complete_calls = [c for c in calls if c[0] == "stage_complete"]
        assert len(complete_calls) == 1
        assert complete_calls[0][2]["status"] == "ok"

    def test_callback_not_called_when_none(self):
        stage = self._make_minimal_stage()
        runner = Runner(progress_callback=None)
        state = State(mode="new", op_name="test")
        # Should not raise
        result = runner.run_stage(state, stage)
        assert result is not None

    def test_callback_called_on_cancellation(self):
        calls = []
        def cb(event_type, stage_name, metadata):
            calls.append((event_type, stage_name))

        class _LongStage(Stage):
            name = "long_stage"
            default_max_iterations = 10
            def input_contract(self):
                return StageIOContract(requires=[])
            def output_contract(self):
                return StageIOContract(provides=[])
            def actions(self, state, iteration=1):
                return [NoOp()]

        stage = _LongStage()
        runner = Runner(progress_callback=cb)
        state = State(mode="new", op_name="test")
        runner.cancel()

        try:
            runner.run_stage(state, stage)
        except RunnerCancelledError:
            pass

        error_calls = [c for c in calls if c[0] == "stage_error"]
        assert len(error_calls) == 1
        assert error_calls[0][1] == "long_stage"

    def test_metadata_includes_iteration_info(self):
        metas = []
        def cb(event_type, stage_name, metadata):
            if event_type == "iteration_start":
                metas.append(metadata)

        stage = self._make_minimal_stage()
        runner = Runner(progress_callback=cb)
        state = State(mode="new", op_name="test")
        runner.run_stage(state, stage)

        assert len(metas) >= 1
        assert "iteration" in metas[0]
        assert "max" in metas[0]


class TestWorkflowTimeout:
    """Verify workflow-level timeout checking."""

    def _make_long_stage(self):
        cls = type("_LongStage", (Stage,), {
            "name": "long_stage",
            "max_iterations": 10,
            "input_contract": lambda self: StageIOContract(requires=[]),
            "output_contract": lambda self: StageIOContract(provides=[]),
            "actions": lambda self, state, iteration=1: [NoOp()],
        })
        return cls()

    def test_timeout_raised_after_deadline(self):
        import time as _time
        stage = self._make_long_stage()
        runner = Runner()

        # Set deadline in the past
        runner._workflow_deadline = _time.monotonic() - 1.0
        state = State(mode="new", op_name="test", workflow_timeout_sec=10)

        with pytest.raises(WorkflowTimeoutError):
            runner.run_stage(state, stage)

    def test_timeout_not_raised_when_disabled(self):
        stage = self._make_long_stage()
        runner = Runner()
        state = State(mode="new", op_name="test", workflow_timeout_sec=0)

        # Should complete without timeout error
        result = runner.run_stage(state, stage)
        assert result is not None

    def test_stage_timeout_raises_for_past_deadline(self):
        import time as _time
        stage = self._make_long_stage()
        runner = Runner()
        # Set stage_timeout_sec=0 so run_stage doesn't recompute, then
        # manually set stage deadline to past to trigger timeout.
        runner._stage_deadline = _time.monotonic() - 1.0
        state = State(mode="new", op_name="test", stage_timeout_sec=0)

        # stage_timeout_sec=0 → run_stage sets _stage_deadline=None, but
        # we set it before calling, so need to verify _check_timeout directly.
        with pytest.raises(StageTimeoutError):
            runner._check_timeout("long_stage")


class TestStageTimeout:
    """Verify stage-level timeout via _check_timeout."""

    def test_stage_timeout_raised(self):
        import time as _time
        runner = Runner()
        runner._stage_deadline = _time.monotonic() - 1.0

        with pytest.raises(StageTimeoutError) as exc_info:
            runner._check_timeout("test_stage")
        assert exc_info.value.stage_name == "test_stage"

    def test_workflow_timeout_priority(self):
        """Workflow timeout also raises for past deadline."""
        import time as _time
        runner = Runner()
        runner._workflow_deadline = _time.monotonic() - 1.0

        with pytest.raises(WorkflowTimeoutError) as exc_info:
            runner._check_timeout("test_stage")

    def test_timeout_message_shows_budget_and_elapsed(self):
        """T4 regression: the message must report the configured budget and
        actual elapsed time, not the raw monotonic deadline (a huge number)."""
        import time as _time
        runner = Runner()
        runner._workflow_deadline = _time.monotonic() - 1.0
        runner._workflow_started = _time.monotonic() - 1801.0
        runner._workflow_budget_sec = 1800

        with pytest.raises(WorkflowTimeoutError) as exc_info:
            runner._check_timeout("perf")
        msg = str(exc_info.value)
        assert "1800s budget" in msg
        assert "ran 1801" in msg
        # The raw monotonic deadline must NOT leak into the message.
        assert f"{runner._workflow_deadline:.1f}" not in msg

    def test_stage_timeout_message_shows_budget_and_elapsed(self):
        import time as _time
        runner = Runner()
        runner._stage_deadline = _time.monotonic() - 1.0
        runner._stage_started = _time.monotonic() - 601.0
        runner._stage_budget_sec = 600

        with pytest.raises(StageTimeoutError) as exc_info:
            runner._check_timeout("verify")
        msg = str(exc_info.value)
        assert "verify" in msg
        assert "600s budget" in msg
        assert "ran 601" in msg

    def test_stage_timeout_disabled_when_zero(self):
        cls = type("_TimedStage", (Stage,), {
            "name": "timed_stage",
            "max_iterations": 2,
            "input_contract": lambda self: StageIOContract(requires=[]),
            "output_contract": lambda self: StageIOContract(provides=[]),
            "actions": lambda self, state, iteration=1: [NoOp()],
        })
        stage = cls()
        runner = Runner()
        state = State(mode="new", op_name="test", stage_timeout_sec=0)
        result = runner.run_stage(state, stage)
        assert result is not None

    def test_workflow_timeout_state_field_default(self):
        s = State()
        assert s.workflow_timeout_sec == 0
        # step-5b: stage_timeout_sec defaults to None (= CLI did not pass
        # --stage-timeout), so the runner resolves it from config per stage.
        assert s.stage_timeout_sec is None

    def test_timeout_fields_persist_in_snapshot(self):
        s = State(workflow_timeout_sec=300, stage_timeout_sec=60)
        snapshot = s.to_snapshot()
        assert snapshot["workflow_timeout_sec"] == 300
        assert snapshot["stage_timeout_sec"] == 60
        s2 = State.from_snapshot(snapshot)
        assert s2.workflow_timeout_sec == 300
        assert s2.stage_timeout_sec == 60

    def test_per_stage_timeout_from_config_when_cli_unset(self):
        """step-5b: with no CLI --stage-timeout (stage_timeout_sec=None),
        run_stage resolves the per-stage budget from config and sets a deadline.
        """
        import time as _time
        import ascendc_devkit.orchestration.runtime_config as rc
        cls = type("_CfgTimedStage", (Stage,), {
            "name": "cfg_timed_stage",
            "max_iterations": 100,
            "input_contract": lambda self: StageIOContract(requires=[]),
            "output_contract": lambda self: StageIOContract(provides=[]),
            "actions": lambda self, state, iteration=1: [NoOp()],
        })
        stage = cls()
        state = State(mode="new", op_name="test", stage_timeout_sec=None,
                      user_max_iterations=100)
        runner = Runner()
        orig = dict(rc.STAGE_TIMEOUTS)
        rc.STAGE_TIMEOUTS = {"cfg_timed_stage": 1}
        call_count = [0]

        def fake_monotonic():
            call_count[0] += 1
            return 0.0 if call_count[0] == 1 else 100.0
        try:
            with mock.patch(
                    "ascendc_devkit.orchestration.kernel.runner.time.monotonic",
                    fake_monotonic):
                with pytest.raises(StageTimeoutError) as ei:
                    runner.run_stage(state, stage)
                assert ei.value.stage_name == "cfg_timed_stage"
        finally:
            rc.STAGE_TIMEOUTS = orig

    def test_cli_stage_timeout_overrides_config(self):
        """step-5b: an explicit CLI --stage-timeout wins over config. We give
        config a huge budget and CLI a tiny one; the tiny CLI value must apply
        (deadline gets exceeded)."""
        import ascendc_devkit.orchestration.runtime_config as rc
        cls = type("_OverrideStage", (Stage,), {
            "name": "override_stage",
            "max_iterations": 100,
            "input_contract": lambda self: StageIOContract(requires=[]),
            "output_contract": lambda self: StageIOContract(provides=[]),
            "actions": lambda self, state, iteration=1: [NoOp()],
        })
        stage = cls()
        # CLI explicit 1s; config would give 9999s — CLI must win.
        state = State(mode="new", op_name="test", stage_timeout_sec=1,
                      user_max_iterations=100)
        runner = Runner()
        orig = dict(rc.STAGE_TIMEOUTS)
        rc.STAGE_TIMEOUTS = {"override_stage": 9999}
        call_count = [0]

        def fake_monotonic():
            call_count[0] += 1
            return 0.0 if call_count[0] == 1 else 100.0
        try:
            with mock.patch(
                    "ascendc_devkit.orchestration.kernel.runner.time.monotonic",
                    fake_monotonic):
                with pytest.raises(StageTimeoutError):
                    runner.run_stage(state, stage)
        finally:
            rc.STAGE_TIMEOUTS = orig

    def test_cli_explicit_zero_disables_config_timeout(self):
        """step-5b: --stage-timeout 0 disables timeout even when config sets a
        per-stage budget (CLI explicit beats config)."""
        import ascendc_devkit.orchestration.runtime_config as rc
        cls = type("_ZeroStage", (Stage,), {
            "name": "zero_stage",
            "max_iterations": 2,
            "input_contract": lambda self: StageIOContract(requires=[]),
            "output_contract": lambda self: StageIOContract(provides=[]),
            "actions": lambda self, state, iteration=1: [NoOp()],
        })
        stage = cls()
        state = State(mode="new", op_name="test", stage_timeout_sec=0)
        runner = Runner()
        orig = dict(rc.STAGE_TIMEOUTS)
        rc.STAGE_TIMEOUTS = {"zero_stage": 1}
        try:
            result = runner.run_stage(state, stage)
            assert result is not None
            assert runner._stage_deadline is None
        finally:
            rc.STAGE_TIMEOUTS = orig


class TestSoftStageTimeout:
    """Option A: stage timeout is soft when the last agent iteration was ok.

    Background: ``_check_timeout`` is a post-hoc iteration-boundary check — the
    agent runs past the deadline uninterrupted, and the raise fires at the next
    check point. A slow-but-successful run (agent status=ok, usable artifacts)
    was being discarded by StageTimeoutError even though the product was fine.
    Option A: when the previous iteration's agent returned ok, a stage-deadline
    overrun becomes a soft warn (continue iterating / reach max_iterations),
    NOT a raise. The workflow deadline stays a hard wall either way.
    """

    def _agent_stage(self, *, empty_after_first=False):
        def _actions(self, state, iteration=1):
            if empty_after_first and iteration > 1:
                return []
            return [SpawnAgent(agent_name="test", prompt="hi")]
        return type("_SoftTimeoutStage", (Stage,), {
            "name": "soft_stage",
            "max_iterations": 5,
            "input_contract": lambda self: StageIOContract(requires=[]),
            "output_contract": lambda self: StageIOContract(provides=[]),
            "actions": _actions,
        })()

    def test_stage_timeout_soft_when_last_iter_ok(self):
        """Past stage deadline + last iter ok → NO raise (soft)."""
        import time as _time
        runner = Runner()
        runner._stage_deadline = _time.monotonic() - 1.0
        runner._last_iter_ok = True
        # Must not raise.
        runner._check_timeout("soft_stage")

    def test_stage_timeout_raises_when_last_iter_not_ok(self):
        """Past stage deadline + last iter NOT ok → raises (preserve old behavior)."""
        import time as _time
        runner = Runner()
        runner._stage_deadline = _time.monotonic() - 1.0
        runner._last_iter_ok = False
        with pytest.raises(StageTimeoutError):
            runner._check_timeout("soft_stage")

    def test_workflow_timeout_hard_even_when_last_iter_ok(self):
        """Workflow deadline is a hard wall regardless of _last_iter_ok."""
        import time as _time
        runner = Runner()
        runner._workflow_deadline = _time.monotonic() - 1.0
        runner._last_iter_ok = True
        with pytest.raises(WorkflowTimeoutError):
            runner._check_timeout("soft_stage")

    def test_last_iter_ok_true_after_ok_agent(self):
        """run_stage sets _last_iter_ok=True when the agent returns a productive
        ok (F5: bare ok + 零产物不点亮——那是一轮空跑，无可抢救产物)."""
        runner = Runner(agent_backend=StubBackend(canned_responses=[
            AgentResult(agent_name="test", status="ok", artifacts={"f": "x"})]))
        state = State(mode="new", op_name="test", user_max_iterations=1,
                      stage_timeout_sec=0, workflow_timeout_sec=0)
        runner.run_stage(state, self._agent_stage())
        assert runner._last_iter_ok is True

    def test_last_iter_ok_false_after_non_ok_agent(self):
        """run_stage sets _last_iter_ok=False when the agent returns non-ok."""
        runner = Runner(agent_backend=StubBackend(canned_responses=[
            AgentResult(agent_name="test", status="partial")]))
        state = State(mode="new", op_name="test", user_max_iterations=1,
                      stage_timeout_sec=0, workflow_timeout_sec=0)
        runner.run_stage(state, self._agent_stage())
        assert runner._last_iter_ok is False

    def test_last_iter_ok_not_overwritten_by_empty_actions_iter(self):
        """An empty-actions iteration (no agent_result) must NOT reset
        _last_iter_ok to False — the flag tracks the last *agent-bearing* iter,
        so a trailing empty-actions iter doesn't lose the prior ok signal."""
        runner = Runner(agent_backend=StubBackend(canned_responses=[
            AgentResult(agent_name="test", status="ok", artifacts={"f": "x"})]))  # iter-1 productive ok
        state = State(mode="new", op_name="test", user_max_iterations=2,
                      stage_timeout_sec=0, workflow_timeout_sec=0)
        runner.run_stage(state, self._agent_stage(empty_after_first=True))
        assert runner._last_iter_ok is True

    def test_last_iter_ok_preserved_after_hard_aborted_spawn(self):
        """S2 (D7 Option A 收紧): 硬墙杀（aborted≠None）的 spawn 不携带 agent 证据
        （deadline 杀前没真跑），不该盖掉 prior ok 的 salvageable 信号。否则硬墙回归
        Option A：abort 翻 _last_iter_ok=False → 下轮边界 raise → 丢弃 salvageable 产物
        （硬墙前 spawn 跑过 deadline、Option A 持续软放过保产物）。

        iter1 ok+产物（salvageable）→ iter2 hard-abort 且不再回退重试（_infra_backoff_retry
        直接耗尽）→ run_stage 以 aborted 轮收尾 → _last_iter_ok 应维持 True。断言是
        诊断性的：末轮 agent 证据就是 aborted，True 只可能来自 iter1 的豁免保留。"""
        runner = Runner(agent_backend=StubBackend(canned_responses=[
            AgentResult(agent_name="test", status="ok",
                        artifacts={"f": "x"}),                                      # iter 1
            AgentResult(agent_name="test", status="fatal", aborted="hard_timeout")]))  # iter 2（末轮）
        # 回退预算视为耗尽：aborted 轮直接落 is_terminal 收尾（不引入重试轮的
        # 新 agent 证据，保证末轮证据 = aborted 本身）
        runner._infra_backoff_retry = lambda stage: False
        state = State(mode="new", op_name="test", user_max_iterations=2,
                      stage_timeout_sec=0, workflow_timeout_sec=0)
        runner.run_stage(state, self._agent_stage())
        assert runner._last_iter_ok is True  # iter-2 abort did NOT clobber iter-1 ok

    def test_non_aborted_fatal_still_clears_last_iter_ok(self):
        """S2: 豁免只给 aborted≠None；普通 fatal（aborted=None，真跑了但失败）仍清
        _last_iter_ok —— 它是真 agent 证据（genuinely stuck），下轮边界该 raise。

        iter1 ok → iter2 普通 fatal（aborted=None）→ _last_iter_ok 应为 False。"""
        runner = Runner(agent_backend=StubBackend(canned_responses=[
            AgentResult(agent_name="test", status="ok"),        # iter 1
            AgentResult(agent_name="test", status="fatal")]))   # iter 2, aborted=None
        state = State(mode="new", op_name="test", user_max_iterations=2,
                      stage_timeout_sec=0, workflow_timeout_sec=0)
        runner.run_stage(state, self._agent_stage())
        assert runner._last_iter_ok is False

    def test_last_iter_ok_preserved_after_cut_spawn(self):
        """M1 (review 坐实，runner 级): silent-cut（Part 1，thinking-only 终止）与
        aborted 同属"被外部中断、不携带 agent 证据"——S2 守卫同样豁免它不清
        _last_iter_ok。否则 cut 翻 False → 下轮撞 stage deadline 时 Option A 软超时
        失效、硬 raise 丢弃可抢救产物（复现 S2 注释防的 aborted 回归）。

        iter1 ok+产物（salvageable）→ 之后连续 cut 直到撞 MAX_CUT_STREAK 退出 →
        _last_iter_ok 应维持 True（信号只可能来自 iter1——cut 轮全被豁免，
        任何 clobber 都会翻 False，断言因此是诊断性的）。"""
        _cut = AgentResult(agent_name="test", status="ok",
                           artifacts={}, cut=True)
        runner = Runner(agent_backend=StubBackend(canned_responses=[
            AgentResult(agent_name="test", status="ok",
                        artifacts={"f": "x"}),      # iter 1：唯一证据轮
            *([_cut] * 5)]))  # 连续 cut ×5 → MAX_CUT_STREAK 有界退出
        state = State(mode="new", op_name="test", user_max_iterations=2,
                      stage_timeout_sec=0, workflow_timeout_sec=0)
        runner.run_stage(state, self._agent_stage())
        assert runner._last_iter_ok is True  # iter-2 cut did NOT clobber iter-1 ok


class TestStageTeardown:
    """S3 D5: stage 被 spawn 硬墙杀（中断）时，runner 调 stage.teardown() 收尾
    （finally 语义）。best-effort：teardown 异常不阻塞退出。"""

    @staticmethod
    def _teardown_stage(*, boom=False):
        calls: list[str] = []

        class _TdStage(Stage):
            name = "td_stage"
            default_max_iterations = 3
            input_contract = lambda self: StageIOContract(requires=[])
            output_contract = lambda self: StageIOContract(provides=[])

            def actions(self, state, iteration=1):
                return [SpawnAgent(agent_name="test", prompt="hi")]

            def transition(self, state, result):
                return state

            def teardown(self, state, *, interrupt_reason):
                calls.append(interrupt_reason)
                if boom:
                    raise RuntimeError("teardown boom")
                return state

        stage = _TdStage()
        stage.calls = calls  # type: ignore[attr-defined]
        return stage

    def test_teardown_called_with_aborted_reason(self, monkeypatch):
        """§step-98-B：aborted 且循环真退出（退避预算耗尽）→ runner 调
        teardown(interrupt_reason='hard_timeout')——teardown 是循环退出的
        finally 钩子，不再在「将 resume 的 abort」上触发。"""
        import ascendc_devkit.orchestration.runtime_config as rc
        monkeypatch.setattr(
            rc, "infra_backoff",
            lambda: {"max_retries": 0, "backoff_base_s": 0.0,
                     "backoff_factor": 1.0, "backoff_max_total_s": 0.0})
        backend = StubBackend(canned_responses=[
            AgentResult(agent_name="test", status="fatal", aborted="hard_timeout")])
        runner = Runner(agent_backend=backend)
        stage = self._teardown_stage()
        state = State(mode="new", op_name="test", user_max_iterations=3,
                      stage_timeout_sec=0, workflow_timeout_sec=0)
        runner.run_stage(state, stage)
        assert stage.calls == ["hard_timeout"]

    def test_teardown_not_called_on_normal_completion(self):
        """正常 spawn（aborted=None）→ 不调 teardown（teardown 是中断收尾，非正常路径）。"""
        backend = StubBackend()  # default status=ok
        runner = Runner(agent_backend=backend)
        stage = self._teardown_stage()
        state = State(mode="new", op_name="test", user_max_iterations=1,
                      stage_timeout_sec=0, workflow_timeout_sec=0)
        runner.run_stage(state, stage)
        assert stage.calls == []

    def test_teardown_exception_does_not_block_exit(self, monkeypatch):
        """best-effort：teardown 抛异常 → runner 吞掉+log，stage 仍正常返回（不阻塞退出）。"""
        import ascendc_devkit.orchestration.runtime_config as rc
        monkeypatch.setattr(
            rc, "infra_backoff",
            lambda: {"max_retries": 0, "backoff_base_s": 0.0,
                     "backoff_factor": 1.0, "backoff_max_total_s": 0.0})
        backend = StubBackend(canned_responses=[
            AgentResult(agent_name="test", status="fatal", aborted="hard_timeout")])
        runner = Runner(agent_backend=backend)
        stage = self._teardown_stage(boom=True)
        state = State(mode="new", op_name="test", user_max_iterations=3,
                      stage_timeout_sec=0, workflow_timeout_sec=0)
        # Must NOT raise — teardown failure is best-effort.
        runner.run_stage(state, stage)
        assert stage.calls == ["hard_timeout"]  # teardown invoked despite raising


class TestUninterruptibleStage:
    """S3 D6: uninterruptible stage 进行中不被 deadline 抢占（cann-bench 硬超时也走完）。

    边界检查对 uninterruptible stage 不 raise（记 pending），让 transition 跑完；
    stage 结束后才 raise（deferred）——产物已在 state、dispatcher snapshot 保留。"""

    @staticmethod
    def _stage(*, uninterruptible, name="unint_stage"):
        ran: list[bool] = []

        class _Stage(Stage):
            name = "unint_stage"
            default_max_iterations = 1
            input_contract = lambda self: StageIOContract(requires=[])
            output_contract = lambda self: StageIOContract(provides=[])

            def actions(self, state, iteration=1):
                return []  # 确定性 stage：活儿在 transition（cann-bench 模型）

            def transition(self, state, result):
                ran.append(True)
                return state

        _Stage.uninterruptible = uninterruptible  # set after class body (closure)
        stage = _Stage()
        stage.name = name  # per-call name（串行链里每个 stage 不同名）
        stage.ran = ran  # type: ignore[attr-defined]
        return stage

    def test_uninterruptible_runs_transition_past_workflow_deadline(self):
        """workflow deadline 已过 + uninterruptible → 边界不 raise（warn 留痕），
        transition 跑完，run_stage 正常返回（软放行链路贯通，L3 冻结方案）。

        不再 per-node 兑现 deferred raise —— 连续 uninterruptible 链全部跑完后，
        链路后非 uninterruptible stage 入口才 raise（见 chain 回归用例）。"""
        import time as _time
        runner = Runner()
        runner._workflow_deadline = _time.monotonic() - 1.0  # already passed
        stage = self._stage(uninterruptible=True)
        state = State(mode="new", op_name="test", user_max_iterations=1,
                      stage_timeout_sec=0, workflow_timeout_sec=0)
        runner.run_stage(state, stage)  # 不 raise（软放行）
        assert stage.ran == [True]  # transition ran despite passed deadline

    def test_normal_stage_skipped_past_workflow_deadline(self):
        """对照：普通 stage + workflow deadline 已过 → 边界即 raise，transition 不跑。"""
        import time as _time
        runner = Runner()
        runner._workflow_deadline = _time.monotonic() - 1.0
        stage = self._stage(uninterruptible=False)
        state = State(mode="new", op_name="test", user_max_iterations=1,
                      stage_timeout_sec=0, workflow_timeout_sec=0)
        with pytest.raises(WorkflowTimeoutError):
            runner.run_stage(state, stage)
        assert stage.ran == []  # transition did NOT run (skipped at boundary)

    def test_uninterruptible_past_deadline_keeps_product_no_raise(self):
        """graph_executor 级：uninterruptible stage 跑过 deadline → transition 产物
        进 latest_state、execute() 正常返回（不 raise）。软放行链路贯通（L3 冻结方案）。

        历史守卫：cab06045 曾把 deferred raise 放在 latest_state 更新之前 → 产物丢失；
        c2b807e6 改为 persist 后 raise（保留产物）。L3 冻结方案退役 per-node raise ——
        uninterruptible 链根本不 raise，产物天然保留（B1 整类 bug 表面消失）。"""
        import time as _time
        from ascendc_devkit.orchestration.graph_executor import GraphExecutor
        from ascendc_devkit.orchestration.node import AtomicStage
        runner = Runner()
        runner._workflow_deadline = _time.monotonic() - 1.0
        stage = self._stage(uninterruptible=True)
        ge = GraphExecutor(runner=runner)
        state = State(mode="new", op_name="BEFORE", user_max_iterations=1,
                      stage_timeout_sec=0, workflow_timeout_sec=0)
        ge.execute(AtomicStage(stage), state)  # 不 raise，正常返回
        # transition 跑了（ran 非空）+ latest_state 是 transition 后的 state（产物保留）。
        assert stage.ran == [True]
        assert ge.latest_state is not None
        assert ge.latest_state is not state  # 经历了 transition（with_updates 新实例）

    def test_uninterruptible_chain_runs_full_then_normal_stage_raises(self):
        """L3 冻结方案核心回归（P1 修复点）：连续 uninterruptible 链（软放行收尾
        adapt→eval）+ workflow deadline 已过 → 链上所有 stage 的 transition 都跑完
        （不 per-node raise），链路贯通；链路后第一个非 uninterruptible stage 入口
        _check_timeout 真实检查 → raise 终止。

        替代旧 deferred-raise-per-node 实证陷阱：旧机制下两个 uninterruptible 串行，
        第一个跑完即 raise（raise_deferred_timeout per-node 兑现），第二个到不了。"""
        import time as _time
        from ascendc_devkit.orchestration.graph_executor import GraphExecutor
        from ascendc_devkit.orchestration.node import AtomicStage, SequentialGroup
        runner = Runner()
        runner._workflow_deadline = _time.monotonic() - 1.0  # 已过期
        adapt = self._stage(uninterruptible=True, name="adapt")
        eval_ = self._stage(uninterruptible=True, name="eval")
        after = self._stage(uninterruptible=False, name="after")  # 链后普通 stage
        ge = GraphExecutor(runner=runner)
        state = State(mode="new", op_name="test", user_max_iterations=1,
                      stage_timeout_sec=0, workflow_timeout_sec=0)
        group = SequentialGroup(
            name="root",
            children=[AtomicStage(adapt), AtomicStage(eval_), AtomicStage(after)])
        with pytest.raises(WorkflowTimeoutError):
            ge.execute(group, state)
        # 链上两个 uninterruptible stage 的 transition 都跑了（贯通 —— P1 修复点）
        assert adapt.ran == [True]
        assert eval_.ran == [True]
        # 链后普通 stage 的 transition 没跑（入口 _check_timeout 真实检查 → raise 拦）
        assert after.ran == []


class TestRunnerStartIteration:
    """Verify run_stage start_iteration parameter."""

    def _make_tracking_stage(self, stage_name="track_stage"):
        """Stage that records which iterations were executed."""
        cls = type(f"_TrackStage_{stage_name}", (Stage,), {
            "name": stage_name,
            "max_iterations": 3,
            "input_contract": lambda self: StageIOContract(requires=[]),
            "output_contract": lambda self: StageIOContract(provides=[]),
            "actions": lambda self, state, iteration=1: [NoOp()],
        })
        return cls()

    def test_start_iteration_default_is_one(self):
        """Default start_iteration=1 runs all iterations."""
        stage = self._make_tracking_stage()
        runner = Runner()
        state = State(mode="new", op_name="test", non_interactive=True)
        result = runner.run_stage(state, stage)
        # With user_max_iterations=3, should have 3 iterations
        assert result.stage_iterations.get("track_stage") == 3

    def test_start_iteration_skips_earlier(self):
        """start_iteration=3 skips iterations 1 and 2."""
        stage = self._make_tracking_stage()
        runner = Runner()
        state = State(mode="new", op_name="test", non_interactive=True)
        result = runner.run_stage(state, stage, start_iteration=3)
        # Starts at 3, user_max_iterations=3, runs iteration 3 only
        assert result.stage_iterations.get("track_stage") == 3

    def test_start_iteration_greater_than_max(self):
        """start_iteration > max_iterations runs zero iterations."""
        stage = self._make_tracking_stage()
        runner = Runner()
        state = State(mode="new", op_name="test", non_interactive=True)
        result = runner.run_stage(state, stage, start_iteration=5)
        # start_iteration=5 > iteration_ceiling=3, loop body never executes
        assert "track_stage" not in result.stage_iterations

    def test_start_iteration_preserves_events(self):
        """Events are still logged when starting from non-1 iteration."""
        stage = self._make_tracking_stage()
        runner = Runner()
        state = State(mode="new", op_name="test", non_interactive=True)
        result = runner.run_stage(state, stage, start_iteration=2)

        # Should have completed with iterations recorded
        assert result.stage_iterations.get("track_stage", 0) >= 2


class TestSpawnContextEvent:
    """Verify spawn_context event is written during SpawnAgent execution."""

    def test_spawn_context_event_written(self, tmp_path):
        """_execute_spawn_agent writes spawn_context event to EventLog."""
        from ascendc_devkit.infra.workspace import Workspace
        from ascendc_devkit.capabilities.agent.stub_backend import StubBackend

        workspace = Workspace.create(output_root=str(tmp_path / "output"))
        runner = Runner(agent_backend=StubBackend(), workspace=workspace)
        action = SpawnAgent(
            agent_name="ascendc-coder",
            prompt="Generate kernel for gelu",
            context={"op_name": "gelu"},
            skills=["ascendc-op-general-design"],
        )

        runner._execute_spawn_agent(action, {})

        # Verify spawn_context event in events.jsonl
        from ascendc_devkit.infra.event_log import EventLog
        events = EventLog.read(workspace.events_path)
        spawn_events = [e for e in events if e.get("type") == "spawn_context"]
        assert len(spawn_events) >= 1
        ctx = spawn_events[0]
        assert ctx["agent"] == "ascendc-coder"
        assert "gelu" in ctx.get("prompt", "")


class TestSpawnAgentModelResolution:
    """Verify model resolution: action > stage config map > None."""

    def test_model_from_map_when_stage_in_config(self):
        """Runner injects a concrete model id named in the stage map."""
        from ascendc_devkit.orchestration import model_config
        expected = "deepseek-v4-pro"
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(model_config, "STAGE_MODEL_MAP", {"codegen": expected})

            calls = []

            class RecordingBackend(StubBackend):
                def spawn(self, agent_name, prompt, context, skills=None, model=None, working_dir=None, repo_baseline=None, repo_root=None, stage_name="", branch_label="", resume_session_id=None, resume_prompt=None, primary_skill=None, deadline_monotonic: float | None = None):
                    calls.append(model)
                    return super().spawn(agent_name, prompt, context, skills, model)

            runner = Runner(agent_backend=RecordingBackend())
            runner._current_stage_name = "codegen"
            action = SpawnAgent(agent_name="test", prompt="hello")
            runner._execute_actions([action])

        assert len(calls) == 1
        assert calls[0] == expected

    def test_default_token_in_map_yields_sdk_default(self):
        """A stage set to 'default' makes the runner pass model=None (SDK default).

        Regression guard for the codegen 503: 'default' must NOT be passed
        through as a literal model id (the gateway has no such channel)."""
        from ascendc_devkit.orchestration import model_config
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(model_config, "STAGE_MODEL_MAP", {"codegen": "default"})

            calls = []

            class RecordingBackend(StubBackend):
                def spawn(self, agent_name, prompt, context, skills=None, model=None, working_dir=None, repo_baseline=None, repo_root=None, stage_name="", branch_label="", resume_session_id=None, resume_prompt=None, primary_skill=None, deadline_monotonic: float | None = None):
                    calls.append(model)
                    return super().spawn(agent_name, prompt, context, skills, model)

            runner = Runner(agent_backend=RecordingBackend())
            runner._current_stage_name = "codegen"
            action = SpawnAgent(agent_name="test", prompt="hello")
            runner._execute_actions([action])

        assert len(calls) == 1
        assert calls[0] is None

    def test_model_none_when_stage_not_in_config(self):
        """Runner passes model=None when stage is not in STAGE_MODEL_MAP."""
        from ascendc_devkit.orchestration.model_config import STAGE_MODEL_MAP

        assert "entry" not in STAGE_MODEL_MAP

        calls = []

        class RecordingBackend(StubBackend):
            def spawn(self, agent_name, prompt, context, skills=None, model=None, working_dir=None, repo_baseline=None, repo_root=None, stage_name="", branch_label="", resume_session_id=None, resume_prompt=None, primary_skill=None, deadline_monotonic: float | None = None):
                calls.append(model)
                return super().spawn(agent_name, prompt, context, skills, model)

        runner = Runner(agent_backend=RecordingBackend())
        runner._current_stage_name = "entry"
        action = SpawnAgent(agent_name="test", prompt="hello")
        runner._execute_actions([action])

        assert len(calls) == 1
        assert calls[0] is None

    def test_action_model_overrides_stage_map(self):
        """Action-level model takes priority over STAGE_MODEL_MAP."""
        from ascendc_devkit.orchestration.model_config import STAGE_MODEL_MAP

        assert "codegen" in STAGE_MODEL_MAP

        calls = []

        class RecordingBackend(StubBackend):
            def spawn(self, agent_name, prompt, context, skills=None, model=None, working_dir=None, repo_baseline=None, repo_root=None, stage_name="", branch_label="", resume_session_id=None, resume_prompt=None, primary_skill=None, deadline_monotonic: float | None = None):
                calls.append(model)
                return super().spawn(agent_name, prompt, context, skills, model)

        runner = Runner(agent_backend=RecordingBackend())
        runner._current_stage_name = "codegen"
        action = SpawnAgent(agent_name="test", prompt="hello",
                            model="custom-model")
        runner._execute_actions([action])

        assert len(calls) == 1
        assert calls[0] == "custom-model"

    def test_no_model_when_map_empty_and_no_action_override(self):
        """model=None when neither config map nor action specifies one."""
        calls = []

        class RecordingBackend(StubBackend):
            def spawn(self, agent_name, prompt, context, skills=None, model=None, working_dir=None, repo_baseline=None, repo_root=None, stage_name="", branch_label="", resume_session_id=None, resume_prompt=None, primary_skill=None, deadline_monotonic: float | None = None):
                calls.append(model)
                return super().spawn(agent_name, prompt, context, skills, model)

        runner = Runner(agent_backend=RecordingBackend())
        runner._current_stage_name = ""  # no stage set
        action = SpawnAgent(agent_name="test", prompt="hello")
        runner._execute_actions([action])

        assert len(calls) == 1
        assert calls[0] is None


class TestSpawnAgentSkillsPassthrough:
    """Verify SpawnAgent.skills reaches the backend spawn call (P1 task 1)."""

    def test_skills_passed_through_to_backend(self):
        """A stage-assigned skill list reaches backend.spawn's skills arg."""
        calls = []

        class RecordingBackend(StubBackend):
            def spawn(self, agent_name, prompt, context, skills=None, model=None, working_dir=None, repo_baseline=None, repo_root=None, stage_name="", branch_label="", resume_session_id=None, resume_prompt=None, primary_skill=None, deadline_monotonic: float | None = None):
                calls.append(skills)
                return super().spawn(agent_name, prompt, context, skills, model)

        runner = Runner(agent_backend=RecordingBackend())
        action = SpawnAgent(
            agent_name="test", prompt="hello",
            skills=["ascendc-op-tiling-split"])
        runner._execute_actions([action])

        assert len(calls) == 1
        assert calls[0] == ["ascendc-op-tiling-split"]

    def test_skills_none_passed_through_as_none(self):
        """Unassigned skills (None) stay None — inherit CLI default, not []."""
        calls = []

        class RecordingBackend(StubBackend):
            def spawn(self, agent_name, prompt, context, skills=None, model=None, working_dir=None, repo_baseline=None, repo_root=None, stage_name="", branch_label="", resume_session_id=None, resume_prompt=None, primary_skill=None, deadline_monotonic: float | None = None):
                calls.append(skills)
                return super().spawn(agent_name, prompt, context, skills, model)

        runner = Runner(agent_backend=RecordingBackend())
        action = SpawnAgent(agent_name="test", prompt="hello")
        runner._execute_actions([action])

        assert len(calls) == 1
        assert calls[0] is None


class TestSpawnAgentAttributionPassthrough:
    """§P2/D8 — stage_name + branch_label reach backend.spawn for log attribution."""

    def test_attribution_forwarded_to_backend(self):
        calls = []

        class RecordingBackend(StubBackend):
            def spawn(self, agent_name, prompt, context, skills=None, model=None, working_dir=None, repo_baseline=None, repo_root=None, stage_name="", branch_label="", resume_session_id=None, resume_prompt=None, primary_skill=None, deadline_monotonic: float | None = None):
                calls.append((stage_name, branch_label))
                return super().spawn(agent_name, prompt, context, skills,
                                     stage_name=stage_name, branch_label=branch_label)

        runner = Runner(agent_backend=RecordingBackend())
        action = SpawnAgent(agent_name="role", prompt="hi",
                            stage_name="split", branch_label="T3")
        runner._execute_actions([action])

        assert calls == [("split", "T3")]

    def test_attribution_defaults_empty(self):
        calls = []

        class RecordingBackend(StubBackend):
            def spawn(self, agent_name, prompt, context, skills=None, model=None, working_dir=None, repo_baseline=None, repo_root=None, stage_name="", branch_label="", resume_session_id=None, resume_prompt=None, primary_skill=None, deadline_monotonic: float | None = None):
                calls.append((stage_name, branch_label))
                return super().spawn(agent_name, prompt, context, skills,
                                     stage_name=stage_name, branch_label=branch_label)

        runner = Runner(agent_backend=RecordingBackend())
        runner._execute_actions([SpawnAgent(agent_name="x", prompt="hi")])

        assert calls == [("", "")]


class TestParallelSpawnAgents:
    """P9 — multiple SpawnAgents in one iteration run concurrently."""

    def test_parallel_spawn_populates_agent_results(self):
        """2 SpawnAgents → ``agent_results`` list, first also in ``agent_result``."""
        import threading
        import time
        lock = threading.Lock()
        peak = {"cur": 0, "max": 0}

        class _ConcBackend(StubBackend):
            def spawn(self, *args, **kwargs):
                with lock:
                    peak["cur"] += 1
                    peak["max"] = max(peak["max"], peak["cur"])
                time.sleep(0.05)  # widen the window so overlap is observable
                with lock:
                    peak["cur"] -= 1
                return AgentResult(agent_name="x", status="ok")

        runner = Runner(agent_backend=_ConcBackend())
        result = runner._execute_actions([
            SpawnAgent(agent_name="x", prompt="p1"),
            SpawnAgent(agent_name="x", prompt="p2"),
        ])

        assert len(result["agent_results"]) == 2
        # first result is also mirrored into agent_result for backward compat
        assert result["agent_result"] is result["agent_results"][0]["agent_result"]
        assert peak["max"] >= 2  # proven concurrent (serial would peak at 1)

    def test_single_spawn_no_agent_results_key(self):
        """Single SpawnAgent keeps the legacy single-result contract."""
        runner = Runner(agent_backend=StubBackend())
        result = runner._execute_actions([SpawnAgent(agent_name="x", prompt="hi")])

        assert "agent_results" not in result
        assert result["agent_result"] is not None

    def test_parallel_spawn_no_backend_does_not_crash(self):
        """No agent_backend + parallel batch → agent_results of Nones, no crash.

        Regression guard: the _last_iter_ok / infra merge must tolerate None
        agent_results (Runner() with no backend leaves agent_result unset).
        """
        from ascendc_devkit.orchestration.kernel.runner import Runner as R
        runner = R()  # no backend → each spawn yields agent_result=None
        result = runner._execute_actions([
            SpawnAgent(agent_name="x", prompt="p1"),
            SpawnAgent(agent_name="x", prompt="p2"),
        ])

        assert len(result["agent_results"]) == 2
        assert result["agent_results"][0]["agent_result"] is None
        # no exception raised is the point; _last_iter_ok untouched (None guard)
        assert runner._last_iter_ok is False or hasattr(runner, "_last_iter_ok")


class TestStageDoneArtifactListing:
    """§P6 — run_stage forwards the last agent_result's artifacts to stage_done."""

    def _spawn_stage(self, stage_name="s"):
        cls = type(f"_SpawnStage_{stage_name}", (Stage,), {
            "name": stage_name,
            "default_max_iterations": 1,
            "input_contract": lambda self: StageIOContract(requires=[]),
            "output_contract": lambda self: StageIOContract(provides=["op_name"]),
            "actions": lambda self, state, iteration=1: [
                SpawnAgent(agent_name="role", prompt="p")],
            # Terminate after the spawning iteration so the retained `result`
            # carries that iteration's agent_result (op_name already satisfies
            # provides → early-termination fires on iteration 1).
            "transition": lambda self, state, result: state,
        })
        return cls()

    def test_artifacts_forwarded_to_stage_done(self):
        from unittest import mock
        backend = StubBackend(canned_responses=[
            AgentResult(agent_name="role", status="ok",
                        artifacts={"out.json": '{"a":1}'})])
        runner = Runner(agent_backend=backend)
        with mock.patch.object(Logger, "stage_done") as m:
            runner.run_stage(State(mode="new", op_name="x"), self._spawn_stage())
        # stage_done called with the artifacts dict as 3rd positional/keyword arg.
        args, kwargs = m.call_args
        passed = args[2] if len(args) > 2 else kwargs.get("artifacts")
        assert passed == {"out.json": '{"a":1}'}

    def test_no_agent_result_passes_none(self):
        from unittest import mock
        stage = self._make_noop_stage()
        runner = Runner()
        with mock.patch.object(Logger, "stage_done") as m:
            runner.run_stage(State(mode="new", op_name="x"), stage)
        args, kwargs = m.call_args
        passed = args[2] if len(args) > 2 else kwargs.get("artifacts")
        assert passed is None

    def _make_noop_stage(self):
        cls = type("_NoopStage", (Stage,), {
            "name": "noop",
            "default_max_iterations": 1,
            "input_contract": lambda self: StageIOContract(requires=[]),
            "output_contract": lambda self: StageIOContract(provides=[]),
            "actions": lambda self, state, iteration=1: [NoOp()],
        })
        return cls()


class TestIsSatisfiedHook:
    """is_satisfied gates early-termination on top of has_all(provides)."""

    class _QualityGatedStage(Stage):
        """Provides are met from iteration 1, but is_satisfied only flips True
        on iteration 3 — exercising the quality self-check."""
        name = "quality_stage"
        description = "produces output immediately but is not 'satisfied' yet"
        default_max_iterations = 5

        def input_contract(self):
            return StageIOContract(requires=[], optional=[])

        def output_contract(self):
            return StageIOContract(provides=["generated_sources"])

        def actions(self, state, iteration=1):
            return [NoOp()]

        def transition(self, state, result):
            # Always sets provides; tracks iterations via codegen_iterations.
            n = state.codegen_iterations + 1
            return state.with_updates(
                generated_sources={"f.cpp": "x"},
                codegen_iterations=n,
            )

        def is_satisfied(self, state):
            # Not acceptable until the 3rd iteration completes.
            return state.codegen_iterations >= 3

    def test_not_satisfied_keeps_iterating(self):
        stage = self._QualityGatedStage()
        state = State(mode="new", user_max_iterations=5, non_interactive=True)
        runner = Runner(agent_backend=StubBackend())
        final = runner.run_stage(state, stage)
        # has_all(provides) is True from iter 1, but is_satisfied blocks early
        # exit until codegen_iterations >= 3 → stops exactly at 3.
        assert final.codegen_iterations == 3
        assert final.stage_iterations.get("quality_stage", 0) == 3

    def test_default_is_satisfied_allows_immediate_exit(self):
        """A stage that doesn't override is_satisfied early-exits as before."""
        class _PlainStage(Stage):
            name = "plain_stage"
            default_max_iterations = 5

            def input_contract(self):
                return StageIOContract()

            def output_contract(self):
                return StageIOContract(provides=["generated_sources"])

            def actions(self, state, iteration=1):
                return [NoOp()]

            def transition(self, state, result):
                return state.with_updates(generated_sources={"f.cpp": "x"})

        stage = _PlainStage()
        state = State(mode="new", user_max_iterations=5, non_interactive=True)
        runner = Runner(agent_backend=StubBackend())
        final = runner.run_stage(state, stage)
        # Default is_satisfied=True → exits on iteration 1.
        assert final.stage_iterations.get("plain_stage", 0) == 1


class TestNoOpContractSatisfied:
    """P33: NoOp(contract_satisfied=True) = stage 显式声明"确定性跳过"。

    典型场景:test_design 三 substage 在外部 cases 短路时 actions=[NoOp]、transition
    纯 passthrough(不产出 test_analysis/test_casedesign),但 output_contract 仍硬
    provides。修复前 runner 把它当"未满足契约"死循环到 max_iter → partial+halt(误退出
    65)。修复后:NoOp(contract_satisfied=True) 视契约已满足 → 早终止、不 warn、不 partial。

    反例(裸 NoOp() 默认 False)见 TestMaxIterations —— 本该产出却 NoOp 的真 bug 仍 warn/partial。
    """

    class _ShortCircuitStage(Stage):
        name = "sc_stage"
        description = "external-cases-style deterministic skip"
        default_max_iterations = 3

        def input_contract(self):
            return StageIOContract(requires=[], optional=[])

        def output_contract(self):
            return StageIOContract(provides=["test_analysis"])

        def actions(self, state, iteration=1):
            return [NoOp(reason="external cases supplied (13 E1)",
                         contract_satisfied=True)]

        def transition(self, state, result):
            return state  # passthrough — deliberately does NOT set test_analysis

    def _run(self, progress_callback=None):
        stage = self._ShortCircuitStage()
        state = State(mode="new", non_interactive=True)
        runner = Runner(agent_backend=StubBackend(),
                        progress_callback=progress_callback)
        return runner.run_stage(state, stage)

    def test_terminates_on_first_iteration_not_loops_to_ceiling(self):
        final = self._run()
        # contract_satisfied NoOp → terminal at iter 1, NOT a 3-iteration death loop.
        assert final.stage_iterations.get("sc_stage") == 1

    def test_no_unsatisfied_contract_warning(self):
        with mock.patch(
                "ascendc_devkit.orchestration.kernel.runner.Logger.warn") as mw:
            self._run()
            assert not any("without satisfying output_contract" in str(c)
                           for c in mw.call_args_list)

    def test_stage_status_ok_not_partial(self):
        captured = {}

        def cb(event, name, data):
            if event == "stage_complete":
                captured["status"] = data["status"]

        self._run(progress_callback=cb)
        assert captured.get("status") == "ok"

    def test_provides_field_unproduced_but_stage_not_failed(self):
        final = self._run()
        # test_analysis deliberately not produced (passthrough), but the stage
        # must NOT be marked failed / trigger halt.
        assert final.test_analysis is None
        assert getattr(final, "_stage_failed", None) is None
