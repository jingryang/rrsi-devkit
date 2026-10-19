"""Q5: deterministic no-agent stages declare ``skip_reason``.

``cannbench_adapt`` / ``cannbench_eval`` / ``codegen_init`` always return ``[]``
from ``actions()`` (work happens in ``transition()``); ``finalize`` conditionally.
Without ``skip_reason`` the runner WARNs "produced no actions with no skip_reason"
(false alarm — P6-b, ``runner.py`` L487). With it the runner logs ○ skipped, so a
truly broken (unintentionally empty) stage still stands out as ⚠.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from ascendc_devkit.orchestration.stages.cannbench_adapt import CannbenchAdaptStage
from ascendc_devkit.orchestration.stages.cannbench_eval import CannbenchEvalStage
from ascendc_devkit.orchestration.stages.codegen_init import CodegenInitStage
from ascendc_devkit.orchestration.stages.finalize import FinalizeStage
from ascendc_devkit.orchestration.kernel.state import State


def test_cannbench_adapt_has_skip_reason():
    """adapt is deterministic (LLM agent retired) — always self-skips."""
    assert CannbenchAdaptStage().skip_reason(State(mode="new")) is not None


def test_cannbench_eval_has_skip_reason():
    """eval runs kernel_eval in transition() — always self-skips."""
    assert CannbenchEvalStage().skip_reason(State(mode="new")) is not None


def test_codegen_init_has_skip_reason():
    """codegen_init declares sections in transition() — always self-skips."""
    assert CodegenInitStage().skip_reason(State(mode="new")) is not None


def test_finalize_skips_when_no_integration():
    """No integration result → nothing to build / record → self-skip."""
    assert FinalizeStage().skip_reason(State(mode="new")) is not None


def test_finalize_no_skip_when_build_will_run():
    """integration + adapter + op_identity → in-repo build action → no skip."""
    state = State(mode="new").with_updates(
        integration_result={"built": True},
        target_files=[Path("a.cpp")],
        adapter=SimpleNamespace(),
        op_identity=SimpleNamespace(),
    )
    assert FinalizeStage().skip_reason(state) is None


def test_finalize_no_skip_when_incremental_dev_record():
    """mode=incremental + integration → dev-record update action → no skip."""
    state = State(mode="incremental").with_updates(
        integration_result={"built": True},
        target_files=[Path("a.cpp")],
    )
    assert FinalizeStage().skip_reason(state) is None


def test_runner_skip_reason_stage_logs_skipped_not_no_action_warn():
    """Q5 runner integration: ``actions()=[]`` + ``skip_reason`` non-None → runner
    logs ○ ``stage_skipped``, NOT ⚠ 'produced no actions' warn (runner.py L484-494).

    The method-level UTs above prove each stage returns a reason; this proves the
    runner integration actually consumes it (runner.py L485 ``getattr(...,
    'skip_reason', ...)`` → L487 ``stage_skipped`` path) — the WARN is gone
    end-to-end, not just that the method exists.
    """
    from unittest.mock import MagicMock
    from ascendc_devkit.orchestration.base import Stage
    from ascendc_devkit.orchestration.kernel.runner import Runner
    from ascendc_devkit.domain.contract import StageIOContract
    from ascendc_devkit.capabilities.agent.backend import AgentBackend, AgentResult

    class _DetStage(Stage):
        name = "det-stage"
        fail_strategy = "halt"
        default_max_iterations = 1

        def input_contract(self):
            return StageIOContract(requires=[])

        def output_contract(self):
            return StageIOContract(provides=[])

        def actions(self, state, iteration=1):
            return []

        def skip_reason(self, state):
            return "deterministic — runs in transition()"

        def transition(self, state, result):
            return state

    class _Backend(AgentBackend):
        def spawn(self, *a, **kw):
            return AgentResult(agent_name="x", status="ok")

    runner = Runner(agent_backend=_Backend())
    mock_log = MagicMock()
    runner.Logger = mock_log
    runner.run_stage(State(mode="new"), _DetStage())
    assert mock_log.stage_skipped.called, (
        "deterministic stage should log ○ stage_skipped (skip_reason path)")
    no_action_warns = [c for c in mock_log.warn.call_args_list
                       if "produced no actions" in str(c)]
    assert not no_action_warns, (
        "skip_reason stage must NOT WARN 'produced no actions' — that warn is "
        "the Q5 false alarm this fix removes")
