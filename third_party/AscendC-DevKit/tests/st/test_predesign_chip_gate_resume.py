"""ST (step-34 D3) — pre-design cross-generation gate: runner-level resume.

Drives ``GeneralDesignStage`` through the real runner loop to prove the full
AskUserQuestion → DecisionPendingError → ``respond`` → resume chain (path A,
the integration Step 0 wired): a cross-generation run pauses for a human
decision in non-interactive abort mode, consumes
``decision_response.json`` on resume (Step 0 replay — no re-ask), applies the
choice, and advances to the design agent.

No real LLM (``_GenStubBackend``); no probe monkeypatch — the gate is a pure
comparison over the two already-resolved chip fields, so it never probes.
This is the §3.9/§3.10 guard that the resumable gate actually round-trips
(UT covers the trigger/transition logic; this covers the runner plumbing).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ascendc_devkit.capabilities.agent.backend import AgentBackend, AgentResult
from ascendc_devkit.domain.exceptions import DecisionPendingError
from ascendc_devkit.domain.requirement import Requirement
from ascendc_devkit.infra.workspace import Workspace
from ascendc_devkit.orchestration.kernel.runner import Runner
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.registry import _ensure_stages_loaded
from ascendc_devkit.orchestration.stages.design_substages import GeneralDesignStage


class _GenStubBackend(AgentBackend):
    """Returns a valid general_design.json for the design-generator skill.

    P62: design-stage transitions read products from DISK under working_dir
    (the agent-dict fallback is gone, §2.5 single pathway). So this stub
    writes ``general_design.json`` into ``working_dir`` — faithfully modelling
    a real agent's cwd write, exactly as the canonical ``StubBackend`` does.
    """

    def spawn(self, agent_name, prompt, context, skills=None,
              model=None, working_dir=None, repo_baseline=None, repo_root=None,
              stage_name="", branch_label="", resume_session_id=None, resume_prompt=None, primary_skill=None, deadline_monotonic: float | None = None):
        content = json.dumps({
            "op_name": "gelu",
            "split_axis_priority": ["N"],
            "tiling_data": [], "loop_framework": "", "buffer_eval": {},
        })
        if working_dir is not None:
            wd = Path(working_dir)
            (wd / "general_design.json").write_text(content, encoding="utf-8")
        return AgentResult(
            agent_name=agent_name, status="ok",
            artifacts={"general_design.json": content})


@pytest.fixture(autouse=True)
def _stages():
    _ensure_stages_loaded()


def _state(ws, design, runtime):
    s = State.empty().with_updates(
        non_interactive=True,
        on_decision="abort",
        workflow_name="generate_ascendc",
        _workspace=ws,
        requirement=Requirement.from_dict({"op": {"name": "gelu"}}),
        design_target_chip=design,
        runtime_target_chip=runtime,
    )
    # P1/§3.12: general-design consumes requirement from the authoritative disk
    # file — mirror the real flow (requirement stage ran first, writing the full
    # on-disk file) so validate_inputs doesn't reject the fixture.
    req_dir = ws.artifacts / "requirement"
    req_dir.mkdir(parents=True, exist_ok=True)
    (req_dir / "requirement.json").write_text(json.dumps({
        "op_name": "gelu",
        "mutation_mode": "out_of_place",
        "inputs": [{"name": "x", "dtype": "float16"}],
        "outputs": [{"name": "y", "dtype": "float16"}],
        "domain": {"rank": {"min": 0, "max": 8},
                   "inputs": [{"name": "x",
                               "dtypes": ["float16", "float32"]}]},
    }, ensure_ascii=False), encoding="utf-8")
    return s


class TestPreDesignChipGateResume:
    def test_cross_gen_pauses_then_resume_retargets_without_reask(self, tmp_path):
        ws = Workspace.create(output_root=str(tmp_path / "out"), run_id="gate")
        runner = Runner(agent_backend=_GenStubBackend(), workspace=ws)
        stage = GeneralDesignStage()
        state = _state(ws, design="A5", runtime="A2")

        # 1) First pass: gate fires; non-interactive abort pauses for a human.
        with pytest.raises(DecisionPendingError):
            runner.run_stage(state, stage)
        pending = Path(ws.dir) / "pending_decision.json"
        assert pending.exists(), "abort path must write the pause record"

        # 2) Human responds: 改打本机 (option 1, 1-based → index 0 = retarget).
        resp = Path(ws.dir) / "decision_response.json"
        resp.write_text(json.dumps({"choice": 1}))

        # 3) Resume: Step 0 replay consumes the response (NO re-ask / re-pause),
        #    transition retargets design→runtime, gate does not refire, the
        #    design agent runs and produces general_design.
        out = runner.run_stage(state, stage)
        assert out.general_design is not None
        assert out.general_design["op_name"] == "gelu"
        assert out.design_target_chip == "A2"            # retargeted to local
        assert out.runtime_target_chip == "A2"
        assert out.cross_gen_confirmed is True
        assert not resp.exists(), "response file must be consumed on resume"
        # pending_decision.json unchanged from pass 1 (no second pause).
        assert json.loads(pending.read_text())["question"]  # still the first ask

    def test_resume_confirm_proceeds_cross_generation(self, tmp_path):
        ws = Workspace.create(output_root=str(tmp_path / "out"), run_id="gate2")
        runner = Runner(agent_backend=_GenStubBackend(), workspace=ws)
        stage = GeneralDesignStage()
        state = _state(ws, design="A5", runtime="A2")

        with pytest.raises(DecisionPendingError):
            runner.run_stage(state, stage)

        # 跨代设计 (option 2 → index 1 = confirm): keep A5, just mark confirmed.
        resp = Path(ws.dir) / "decision_response.json"
        resp.write_text(json.dumps({"choice": 2}))

        out = runner.run_stage(state, stage)
        assert out.general_design is not None
        assert out.design_target_chip == "A5"            # unchanged — cross-gen
        assert out.runtime_target_chip == "A2"
        assert out.cross_gen_confirmed is True
