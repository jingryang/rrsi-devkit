"""Unit tests for decision log — loop-back context injection without session resume."""

import json

import pytest

from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.base import Stage
from ascendc_devkit.orchestration.workflow import Workflow
from ascendc_devkit.domain.contract import StageIOContract
from ascendc_devkit.domain.verification import BuildResult


# —— Test helpers ——

def _make_stage(name, requires=(), provides=(), optional=()):
    input_contract_obj = StageIOContract(
        requires=list(requires), optional=list(optional),
    )
    output_contract_obj = StageIOContract(provides=list(provides))

    cls = type(f"_Stage_{name}", (Stage,), {
        "name": name,
        "max_iterations": 3,
        "input_contract": lambda self: input_contract_obj,
        "output_contract": lambda self: output_contract_obj,
        "actions": lambda self, state, iteration=1: [],
    })
    return cls()


class TestDecisionLogState:
    """decision_logs field on State."""

    def test_default_is_empty(self):
        s = State()
        assert s.decision_logs == {}

    def test_can_store_per_stage(self):
        s = State(decision_logs={
            "codegen": {"key_decisions": [{"decision": "test"}]},
            "design": {"key_decisions": []},
        })
        assert "codegen" in s.decision_logs
        assert "design" in s.decision_logs

    def test_snapshot_roundtrip(self):
        s = State(decision_logs={
            "codegen": {
                "key_decisions": [
                    {"decision": "use double buffer", "reason": "UB limit",
                     "constraints": ["UB=192KB"]},
                ],
                "known_issues": ["stride calc"],
                "assumptions": ["N%256==0"],
            },
        })
        snap = s.to_snapshot()
        s2 = State.from_snapshot(snap)
        assert s2.decision_logs == s.decision_logs

    def test_with_updates_preserves_decision_logs(self):
        s = State(decision_logs={"codegen": {"key_decisions": []}})
        s2 = s.with_updates(routing_scopes={"pipeline": {"corrective": 1}})
        assert s2.decision_logs == {"codegen": {"key_decisions": []}}


class TestDecisionLogOutputSection:
    """Stage._decision_log_output_section() generates prompt."""

    def test_includes_stage_name(self):
        s = _make_stage("codegen")
        section = s._decision_log_output_section()
        assert "decision_log.json" in section
        assert "codegen" in section

    def test_includes_required_fields(self):
        s = _make_stage("design")
        section = s._decision_log_output_section()
        assert "key_decisions" in section
        assert "known_issues" in section
        assert "assumptions" in section


class TestPreviousDecisionSection:
    """Stage._previous_decision_section() formats prior decision log."""

    def test_returns_none_when_no_log(self):
        s = _make_stage("codegen")
        state = State()
        assert s._previous_decision_section(state) is None

    def test_returns_none_when_log_empty_for_stage(self):
        s = _make_stage("codegen")
        state = State(decision_logs={"design": {"key_decisions": []}})
        assert s._previous_decision_section(state) is None

    def test_formats_decisions(self):
        s = _make_stage("codegen")
        state = State(decision_logs={
            "codegen": {
                "key_decisions": [
                    {"decision": "choose A", "reason": "faster",
                     "constraints": ["UB=192KB"]},
                    {"decision": "skip B", "reason": "too complex"},
                ],
            },
        })
        section = s._previous_decision_section(state)
        assert "choose A" in section
        assert "faster" in section
        assert "UB=192KB" in section
        assert "skip B" in section

    def test_includes_known_issues(self):
        s = _make_stage("codegen")
        state = State(decision_logs={
            "codegen": {
                "key_decisions": [],
                "known_issues": ["issue 1", "issue 2"],
            },
        })
        section = s._previous_decision_section(state)
        assert "issue 1" in section
        assert "issue 2" in section

    def test_includes_assumptions(self):
        s = _make_stage("design")
        state = State(decision_logs={
            "design": {
                "key_decisions": [],
                "assumptions": ["input is NCHW"],
            },
        })
        section = s._previous_decision_section(state)
        assert "NCHW" in section

    def test_handles_missing_sections(self):
        s = _make_stage("codegen")
        state = State(decision_logs={
            "codegen": {"key_decisions": [{"decision": "ok", "reason": "good"}]},
        })
        section = s._previous_decision_section(state)
        # Should not crash when known_issues/assumptions are missing
        assert "ok" in section
        assert "已知问题" not in section  # No heading when empty
        assert "假设" not in section


class TestCodegenStageDecisionLog:
    """CodegenStage prompt includes decision log sections."""

    def test_prompt_includes_output_requirement(self):
        from ascendc_devkit.orchestration.stages.codegen import CodegenStage
        stage = CodegenStage()
        state = State(mode="new")
        # Set required fields for _build_codegen_prompt
        prompt = stage._build_codegen_prompt(state, 1)
        assert "decision_log.json" in prompt
        assert "key_decisions" in prompt

    def test_prompt_includes_previous_decision_on_loopback(self):
        from ascendc_devkit.orchestration.stages.codegen import CodegenStage
        stage = CodegenStage()
        state = State(
            mode="new",
            build_result=BuildResult(passed=False, stderr="error: foo"),
            decision_logs={
                "codegen": {
                    "key_decisions": [
                        {"decision": "used single buffer", "reason": "simple",
                         "constraints": []},
                    ],
                },
            },
        )
        prompt = stage._build_codegen_prompt(state, 1)
        assert "used single buffer" in prompt
        assert "上一版本的决策记录" in prompt

    def test_transition_parses_decision_log(self):
        from ascendc_devkit.orchestration.stages.codegen import CodegenStage
        stage = CodegenStage()
        state = State(mode="new", decision_logs={})
        dl = {
            "stage": "codegen",
            "key_decisions": [{"decision": "test", "reason": "testing"}],
            "known_issues": [],
            "assumptions": [],
        }
        result = {
            "agent_result": type("R", (), {
                "status": "ok",
                "artifacts": {
                    "kernel.cpp": "// code",
                    "decision_log.json": json.dumps(dl),
                },
                "agent_name": "ascendc-coder",
            })(),
        }
        new_state = stage.transition(state, result)
        assert "codegen" in new_state.decision_logs
        assert new_state.decision_logs["codegen"]["key_decisions"][0]["decision"] == "test"

    def test_transition_handles_corrupt_json(self):
        from ascendc_devkit.orchestration.stages.codegen import CodegenStage
        stage = CodegenStage()
        state = State(mode="new", decision_logs={})
        result = {
            "agent_result": type("R", (), {
                "status": "ok",
                "artifacts": {
                    "kernel.cpp": "// code",
                    "decision_log.json": "not valid json {{{",
                },
                "agent_name": "ascendc-coder",
            })(),
        }
        new_state = stage.transition(state, result)
        # Should not crash; decision_logs unchanged or empty
        assert "codegen" not in new_state.decision_logs or new_state.decision_logs == {}

    def test_transition_preserves_other_stage_logs(self):
        from ascendc_devkit.orchestration.stages.codegen import CodegenStage
        stage = CodegenStage()
        existing = {
            "design": {"key_decisions": [{"decision": "keep this"}]},
        }
        state = State(mode="new", decision_logs=existing)
        dl = {"key_decisions": [{"decision": "new codegen"}]}
        result = {
            "agent_result": type("R", (), {
                "status": "ok",
                "artifacts": {
                    "kernel.cpp": "// code",
                    "decision_log.json": json.dumps(dl),
                },
                "agent_name": "ascendc-coder",
            })(),
        }
        new_state = stage.transition(state, result)
        assert "design" in new_state.decision_logs
        assert new_state.decision_logs["design"]["key_decisions"][0]["decision"] == "keep this"
        assert "codegen" in new_state.decision_logs


class TestDesignStageDecisionLog:
    """Concept-design substage prompt includes decision log sections (step-2b)."""

    def test_prompt_includes_output_requirement(self):
        from ascendc_devkit.orchestration.stages.design_substages import GeneralDesignStage
        stage = GeneralDesignStage()
        state = State(mode="new")
        prompt = stage._build_prompt(state, iteration=1)
        assert "decision_log.json" in prompt
        assert "key_decisions" in prompt

    def test_transition_parses_decision_log(self, tmp_path):
        from ascendc_devkit.orchestration.stages.design_substages import GeneralDesignStage
        stage = GeneralDesignStage()
        state = State(mode="new", decision_logs={})
        dl = {
            "stage": "general-design-generator",
            "key_decisions": [{"decision": "single core", "reason": "small input"}],
            "known_issues": [],
            "assumptions": [],
        }
        # P62: products land on disk under working_dir (disk-only read pathway);
        # decision_log.json is read as an implicit optional companion.
        wd = tmp_path / "wd"
        wd.mkdir()
        (wd / "general_design.json").write_text(
            json.dumps({"op_name": "test", "sections": {}}), encoding="utf-8")
        (wd / "decision_log.json").write_text(json.dumps(dl), encoding="utf-8")
        result = {"_working_dir": str(wd)}
        new_state = stage.transition(state, result)
        assert "general-design-generator" in new_state.decision_logs
        assert new_state.decision_logs["general-design-generator"]["key_decisions"][0]["decision"] == "single core"


class TestDecisionLogUniqueness:
    """Each loop-back accumulates a new decision log, not overwriting."""

    def test_second_codegen_overwrites_previous_codegen_log(self):
        """When codegen runs again (loop-back), new log replaces old one."""
        from ascendc_devkit.orchestration.stages.codegen import CodegenStage
        stage = CodegenStage()
        old_dl = {"key_decisions": [{"decision": "first attempt"}]}
        state = State(mode="new", decision_logs={"codegen": old_dl})

        new_dl = {"key_decisions": [{"decision": "second attempt"}]}
        result = {
            "agent_result": type("R", (), {
                "status": "ok",
                "artifacts": {
                    "kernel.cpp": "// code",
                    "decision_log.json": json.dumps(new_dl),
                },
                "agent_name": "ascendc-coder",
            })(),
        }
        new_state = stage.transition(state, result)
        assert len(new_state.decision_logs["codegen"]["key_decisions"]) == 1
        assert new_state.decision_logs["codegen"]["key_decisions"][0]["decision"] == "second attempt"
