"""UT for output-truncation detection (step-67, P3): AgentResult carries
truncated_turns; Runner emits one output_truncated event per flagged turn."""

from ascendc_devkit.capabilities.agent.backend import AgentBackend, AgentResult
from ascendc_devkit.infra.event_log import EventLog
from ascendc_devkit.infra.workspace import Workspace
from ascendc_devkit.orchestration.kernel.action import SpawnAgent
from ascendc_devkit.orchestration.kernel.runner import Runner


def test_agent_result_default_truncated_turns_empty():
    r = AgentResult(agent_name="x", status="ok")
    assert r.truncated_turns == []


class _TruncatingBackend(AgentBackend):
    """Returns a fixed truncated_turns list so the runner's event emission is
    exercised without depending on a real SDK stop_reason field."""

    def spawn(self, agent_name, prompt, context, **kw):
        return AgentResult(agent_name=agent_name, status="ok",
                           truncated_turns=[2, 5])


class _FakeManifest:
    skills: list = []


def test_runner_emits_output_truncated_per_flagged_turn(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "ascendc_devkit.capabilities.skill.loader.load_agent_manifest",
        lambda name: _FakeManifest())

    ws = Workspace.create(str(tmp_path), run_id="r1")
    rb = Runner(agent_backend=_TruncatingBackend(), workspace=ws)
    rb._current_stage_name = "codegen"

    rb._execute_spawn_agent(
        SpawnAgent(agent_name="coder", prompt="p", stage_name="codegen"), {})

    evs = EventLog.read(ws.events_path)
    trunc = [e for e in evs if e["type"] == "output_truncated"]
    assert len(trunc) == 2
    assert {e["turn"] for e in trunc} == {2, 5}
    assert all(e["agent"] == "coder" for e in trunc)
    assert all(e["stage"] == "codegen" for e in trunc)
    assert all(e["reason"] == "output_limit" for e in trunc)


def test_runner_no_truncation_events_when_clean(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "ascendc_devkit.capabilities.skill.loader.load_agent_manifest",
        lambda name: _FakeManifest())

    class _CleanBackend(AgentBackend):
        def spawn(self, agent_name, prompt, context, **kw):
            return AgentResult(agent_name=agent_name, status="ok")  # no truncation

    ws = Workspace.create(str(tmp_path), run_id="r2")
    rb = Runner(agent_backend=_CleanBackend(), workspace=ws)
    rb._current_stage_name = "codegen"
    rb._execute_spawn_agent(
        SpawnAgent(agent_name="coder", prompt="p", stage_name="codegen"), {})

    evs = EventLog.read(ws.events_path)
    assert not [e for e in evs if e["type"] == "output_truncated"]
