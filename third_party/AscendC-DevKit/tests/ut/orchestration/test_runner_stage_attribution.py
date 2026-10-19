"""Q7 layer-1: Runner fills ``action.stage_name`` → ``self._current_stage_name``.

batch log ``agent_stream`` had no op attribution for stages that don't manually
set ``SpawnAgent.stage_name`` (requirement/codegen/smoke/perf/...). The Runner
tracks ``_current_stage_name = stage.name`` (set on stage entry) but didn't pass
it as a fallback — so ``format_attribution`` got an empty ``stage_name`` and
short-circuited (no ``[op/stage]`` prefix in the batch log). This layer-1 fix
makes the Runner fill the fallback at spawn time. Layer-2 (``format_attribution``
no-shortcut for op_name-only) is tested in ``test_shared.py``.
"""
from __future__ import annotations

from ascendc_devkit.orchestration.base import Stage
from ascendc_devkit.orchestration.kernel.runner import Runner
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.kernel.action import SpawnAgent
from ascendc_devkit.domain.contract import StageIOContract
from ascendc_devkit.capabilities.agent.backend import AgentBackend, AgentResult


class _RecordingBackend(AgentBackend):
    """Records the ``stage_name`` each spawn received."""

    def __init__(self):
        self.last_stage_name = "<no spawn>"

    def spawn(self, agent_name, prompt, context, skills=None, model=None,
              working_dir=None, repo_baseline=None, repo_root=None,
              stage_name="", branch_label="", resume_session_id=None,
        resume_prompt=None,
              primary_skill=None, deadline_monotonic: float | None = None):
        self.last_stage_name = stage_name
        return AgentResult(agent_name=agent_name, status="fatal",
                           error_type=None)  # logic failure → halt stops the loop


class _NoActionStageName(Stage):
    """actions() emits SpawnAgent without stage_name (mirrors requirement/codegen)."""
    name = "no-action-stage-name"
    fail_strategy = "halt"
    default_max_iterations = 1

    def input_contract(self):
        return StageIOContract(requires=[])

    def output_contract(self):
        return StageIOContract(provides=[])

    def actions(self, state, iteration=1):
        return [SpawnAgent(agent_name="x", prompt="p", context={})]  # no stage_name


class _ExplicitActionStageName(Stage):
    """actions() explicitly sets SpawnAgent.stage_name (mirrors design_substages)."""
    name = "sets-action-stage-name"
    fail_strategy = "halt"
    default_max_iterations = 1

    def input_contract(self):
        return StageIOContract(requires=[])

    def output_contract(self):
        return StageIOContract(provides=[])

    def actions(self, state, iteration=1):
        return [SpawnAgent(agent_name="x", prompt="p", context={},
                           stage_name="explicit")]


def test_runner_fills_stage_name_fallback():
    """action.stage_name empty → runner fills ``_current_stage_name`` (= stage.name)."""
    backend = _RecordingBackend()
    runner = Runner(agent_backend=backend)
    runner.run_stage(State(mode="new"), _NoActionStageName())
    assert backend.last_stage_name == "no-action-stage-name", (
        "Runner must fall back to its tracked stage name when the action "
        "didn't set one — batch log attribution depends on it")


def test_runner_preserves_explicit_stage_name():
    """action.stage_name set → runner does NOT override (explicit wins)."""
    backend = _RecordingBackend()
    runner = Runner(agent_backend=backend)
    runner.run_stage(State(mode="new"), _ExplicitActionStageName())
    assert backend.last_stage_name == "explicit", (
        "explicit action.stage_name must not be clobbered by the runner fallback")
