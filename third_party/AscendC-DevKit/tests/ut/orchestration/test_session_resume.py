"""UT for codegen.actions resume wiring.

Resume was unified to the backend layer (5afe699d): the stage no longer reads the
resume sidecar — sdk_backend owns resume_fails accumulation + degrade-to-fresh
(§2.5 single path). The backend side (sidecar write/clear, resume init,
session-gone degrade) is covered in tests/ut/capabilities/test_session_resume.py.
Here we guard the orchestration wiring that REMAINS at the stage/runner layer:

  ① Even with a sidecar present, codegen.actions fresh-spawns (resume_session_id
     is None) — the stage does NOT read the sidecar (regression guard for the
     backend unification).
  ② With no sidecar, codegen.actions fresh-spawns as before (slash lead, no
     resume_session_id).
  ③ runner._execute_spawn_agent threads action.resume_session_id into
     backend.spawn — the wire a resumed backend session still needs.
"""
from __future__ import annotations

import json


def _workspace(tmp_path):
    from ascendc_devkit.infra.workspace import Workspace
    return Workspace.create(output_root=str(tmp_path), run_id="t")


def test_codegen_actions_ignores_sidecar_after_backend_unification(tmp_path):
    """5afe699d 后 stage 不再读 sidecar：即便 sidecar 存在，codegen.actions 仍 fresh
    spawn（resume_session_id None）——resume 决策归 backend 层。"""
    from ascendc_devkit.orchestration.stages.codegen import CodegenStage
    from ascendc_devkit.orchestration.kernel.state import State
    from ascendc_devkit.infra.workspace import session_sidecar_path
    from ascendc_devkit.domain.chip import chip_programming_model

    # The sidecar is keyed by the agent codegen will actually spawn, so derive
    # it from the same chip→programming-model routing codegen uses (A5→Regbase
    # → ascendc-coder-regbase; A2/A3 → ascendc-coder). Hardcoding "ascendc-coder"
    # drifted when regbase routing landed — deriving keeps this test honest as
    # routing evolves.
    chip = "A5"
    agent_name = ("ascendc-coder-regbase"
                  if chip_programming_model(chip) == "Regbase"
                  else "ascendc-coder")

    ws = _workspace(tmp_path)
    # Sidecar as the backend would leave it after a crashed mid-spawn.
    sc = session_sidecar_path(ws.dir, agent_name, stage_name="codegen")
    sc.parent.mkdir(parents=True, exist_ok=True)
    sc.write_text(json.dumps(
        {"agent_name": agent_name, "session_id": "S-RES-1"}))

    state = State(mode="new", design_target_chip=chip).with_updates(_workspace=ws)
    actions = CodegenStage().actions(state, 1)

    assert len(actions) == 1
    # stage 不再读 sidecar → 恒 fresh spawn（resume 归 backend）
    assert actions[0].resume_session_id is None


def test_codegen_actions_fresh_when_no_sidecar(tmp_path):
    from ascendc_devkit.orchestration.stages.codegen import CodegenStage
    from ascendc_devkit.orchestration.kernel.state import State

    ws = _workspace(tmp_path)
    state = State(mode="new", design_target_chip="A3").with_updates(_workspace=ws)
    actions = CodegenStage().actions(state, 1)

    assert len(actions) == 1
    assert actions[0].resume_session_id is None
    # Fresh spawn carries the methodology skill on primary_skill (D2); the
    # backend delivers it. A3 Membase → default ascendc-op-dev-coding skill.
    assert actions[0].primary_skill == "ascendc-op-dev-coding"


def test_codegen_actions_fresh_a5_regbase_routing(tmp_path):
    """A5 Regbase → regbase orchestration skill, not the default Membase skill."""
    from ascendc_devkit.orchestration.stages.codegen import CodegenStage
    from ascendc_devkit.orchestration.kernel.state import State

    ws = _workspace(tmp_path)
    state = State(mode="new", design_target_chip="A5").with_updates(_workspace=ws)
    actions = CodegenStage().actions(state, 1)

    assert len(actions) == 1
    assert actions[0].primary_skill == "ascendc-op-dev-coding-regbase"


def test_runner_passes_resume_session_id_to_backend(tmp_path):
    """runner._execute_spawn_agent must thread SpawnAgent.resume_session_id into
    backend.spawn — the single wire between the stage's resume decision and the
    backend's resume execution."""
    from ascendc_devkit.orchestration.kernel.runner import Runner
    from ascendc_devkit.capabilities.agent.stub_backend import StubBackend
    from ascendc_devkit.orchestration.kernel.action import SpawnAgent

    ws = _workspace(tmp_path)
    stub = StubBackend()
    runner = Runner(agent_backend=stub, workspace=ws)
    action = SpawnAgent(agent_name="test-resume-agent", prompt="x",
                        resume_session_id="S-PASS-1")
    runner._execute_spawn_agent(action, {})

    assert stub.spawn_calls, "backend.spawn was not invoked"
    assert stub.spawn_calls[-1]["resume_session_id"] == "S-PASS-1"
