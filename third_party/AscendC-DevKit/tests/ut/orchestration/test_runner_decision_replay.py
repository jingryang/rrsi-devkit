"""Step 0 (chip-target-selection): runner path-A decision_response replay.

AskUserQuestion action (path A) historically never read decision_response.json
on resume — only the resolve_ambiguity MCP tool (path B) did. So a non-interactive
abort run that paused for a decision would loop on resume (rewrite pending,
re-raise) and never consume the user's `respond` answer. This file verifies the
replay branch added to Runner._execute_ask_user_question (mirrors mcp_tools.py
resolve_ambiguity "Resume case").
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ascendc_devkit.domain.exceptions import DecisionPendingError
from ascendc_devkit.infra.workspace import Workspace
from ascendc_devkit.orchestration.kernel.action import AskUserQuestion, Option
from ascendc_devkit.orchestration.kernel.runner import Runner
from ascendc_devkit.orchestration.kernel.state import State


def _write_response(ws: Workspace, payload: dict) -> Path:
    p = Path(ws.dir) / "decision_response.json"
    p.write_text(json.dumps(payload))
    return p


def _gate_action() -> AskUserQuestion:
    return AskUserQuestion(
        question="chip gate?",
        options=[Option(label="cross-gen"), Option(label="local")],
    )


class TestDecisionResponseReplay:
    """Resume replay: a prior `respond` answer is consumed, not re-asked."""

    def test_resume_replays_choice_from_decision_response(self, tmp_path):
        ws = Workspace.create(output_root=str(tmp_path))
        _write_response(ws, {"choice": 2})  # 1-based → option index 1
        state = State(mode="new", non_interactive=True, on_decision="abort",
                      _workspace=ws)
        runner = Runner(workspace=ws)
        result = runner._execute_actions([_gate_action()], state)
        assert result["decision"] == "local"
        assert not (Path(ws.dir) / "decision_response.json").exists()

    def test_resume_replays_text_override(self, tmp_path):
        ws = Workspace.create(output_root=str(tmp_path))
        _write_response(ws, {"text": "custom-answer"})
        state = State(mode="new", non_interactive=True, on_decision="abort",
                      _workspace=ws)
        runner = Runner(workspace=ws)
        result = runner._execute_actions([_gate_action()], state)
        assert result["decision"] == "custom-answer"
        assert not (Path(ws.dir) / "decision_response.json").exists()

    def test_no_response_file_falls_through_to_on_decision(self, tmp_path):
        ws = Workspace.create(output_root=str(tmp_path))
        state = State(mode="new", non_interactive=True, on_decision="abort",
                      _workspace=ws)
        runner = Runner(workspace=ws)
        with pytest.raises(DecisionPendingError, match="chip gate"):
            runner._execute_actions([_gate_action()], state)

    def test_response_choice_out_of_range_falls_through(self, tmp_path):
        ws = Workspace.create(output_root=str(tmp_path))
        _write_response(ws, {"choice": 99})
        state = State(mode="new", non_interactive=True, on_decision="abort",
                      _workspace=ws)
        runner = Runner(workspace=ws)
        with pytest.raises(DecisionPendingError, match="chip gate"):
            runner._execute_actions([_gate_action()], state)
        # Out-of-range choice must NOT consume the response file (so the user
        # can re-respond with a valid choice).
        assert (Path(ws.dir) / "decision_response.json").exists()
