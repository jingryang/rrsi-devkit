"""Unit tests for Slice 9 v2 — Three-layer loopback: state, hooks, route types."""

import pytest

from ascendc_devkit.orchestration.kernel.state import State, ErrorFeedback
from ascendc_devkit.orchestration.base import Stage
from ascendc_devkit.orchestration.workflow import Workflow
from ascendc_devkit.domain.contract import StageIOContract
from ascendc_devkit.domain.transition import StageTransition
from ascendc_devkit.domain.verification import BuildResult, PerformanceResult, PrecisionDebugResult


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


class TestStageTransition:
    """StageTransition dataclass."""

    def test_create_transition(self):
        t = StageTransition(target_stage="design", reason="build_failed")
        assert t.target_stage == "design"
        assert t.reason == "build_failed"

    def test_frozen(self):
        t = StageTransition(target_stage="design", reason="perf_exhausted")
        with pytest.raises(Exception):
            t.target_stage = "codegen"


class TestResolveConditionDefault:
    """Stage.resolve_condition() default returns "default"."""

    def test_default_returns_default(self):
        s = _make_stage("test")
        state = State()
        assert s.resolve_condition(state) == "default"

    def test_override_can_return_condition(self):
        class OverrideStage(_make_stage("override").__class__):
            def resolve_condition(self, state):
                return "build_failed"

        st = OverrideStage()
        assert st.resolve_condition(State()) == "build_failed"


class TestErrorSignature:
    """Stage.error_signature() default and override."""

    def test_default_returns_last_error_message(self):
        s = _make_stage("test")
        state = State(last_error=ErrorFeedback(
            stage_name="test", error_type="compile_error",
            message="something went wrong with the build",
        ))
        sig = s.error_signature(state)
        assert "something went wrong" in sig

    def test_default_empty_when_no_error(self):
        s = _make_stage("test")
        assert s.error_signature(State()) == ""


class TestWorkflowResolveNextStage:
    """Workflow.resolve_next_stage() state machine resolution with transition table."""

    def test_linear_successor(self):
        s1 = _make_stage("entry", provides=["a"])
        s2 = _make_stage("codegen", requires=["a"], provides=["b"])
        s3 = _make_stage("verify", requires=["b"], provides=["c"])
        wf = Workflow(stages=[s1, s2, s3])
        state = State()
        assert wf.resolve_next_stage("entry", state) == "codegen"
        assert wf.resolve_next_stage("codegen", state) == "verify"
        assert wf.resolve_next_stage("verify", state) is None

    def test_transition_table_with_tuples(self):
        """Transition table maps (stage, condition) → (target, route_type)."""

        class FailingVerifyStage(_make_stage("verify", provides=["c"]).__class__):
            def resolve_condition(self, state):
                return "build_failed"

        s1 = _make_stage("design", provides=["a"])
        s2 = _make_stage("codegen", requires=["a"], provides=["b"])
        s3 = FailingVerifyStage()

        class TestWF(Workflow):
            pass

        wf = TestWF(stages=[s1, s2, s3])
        wf._get_transition_table = lambda: {
            "verify": {
                "build_failed": ("codegen", "corrective"),
                "exhausted": ("design", "escalation"),
            },
        }

        state = State()
        assert wf.resolve_next_stage("verify", state) == "codegen"

    def test_transition_table_old_format_still_works(self):
        """Plain string values (old format) still resolve correctly."""
        class FailingStage(_make_stage("verify").__class__):
            def resolve_condition(self, state):
                return "build_failed"

        wf = Workflow(stages=[_make_stage("codegen"), FailingStage()])
        wf._get_transition_table = lambda: {
            "verify": {"build_failed": "codegen"},
        }
        assert wf.resolve_next_stage("verify", State()) == "codegen"

    def test_condition_not_found_falls_back_to_linear(self):
        class UnknownCondStage(_make_stage("codegen").__class__):
            def resolve_condition(self, state):
                return "unknown_xyz"

        s1 = _make_stage("codegen")
        s2 = _make_stage("verify")
        wf = Workflow(stages=[s1, s2])
        assert wf.resolve_next_stage("codegen", State()) == "verify"

    def test_resolve_unknown_stage_returns_none(self):
        wf = Workflow(stages=[_make_stage("entry")])
        assert wf.resolve_next_stage("nonexistent", State()) is None

    def test_index_of(self):
        s1 = _make_stage("a")
        s2 = _make_stage("b")
        s3 = _make_stage("c")
        wf = Workflow(stages=[s1, s2, s3])
        assert wf._index_of("a") == 0
        assert wf._index_of("b") == 1
        assert wf._index_of("c") == 2
        assert wf._index_of("z") == -1

    def test_generate_ascendc_transition_table(self):
        """The real pipeline's transition table uses (target, route_type) tuples."""
        from ascendc_devkit.orchestration.registry import get_workflow, _ensure_stages_loaded, _ensure_workflows_loaded
        _ensure_stages_loaded()
        _ensure_workflows_loaded()
        wf = get_workflow("generate_ascendc")
        table = wf._get_transition_table()

        # P57: verify/deploy gone; precision_debug owns precision.
        assert "verify" not in table
        assert "deploy" not in table
        assert "precision_debug" in table
        assert "perf" in table

        # step-2b: the flat `design` key is gone; requirement_incomplete now
        # lives under the general-design group's cross-group route.
        assert table["general-design"]["requirement_incomplete"] == ("requirement", "corrective")

        # precision_debug exhausted halts (精度修复在 agent 会话内闭环，不回 codegen):
        # a precision failure surviving the agent's in-session budget is a
        # human-triage case, not an auto-rewrite of codegen.
        assert table["precision_debug"]["exhausted"] == ("__halt__", "escalation")

        # perf routes — perf is tied to design, so it escalates to the
        # detailed-design group after tactical tuning is exhausted.
        assert table["perf"]["redesign"] == ("detailed-design", "escalation")
        # perf改码后重验精度：perf-tuner 改了代码 → precision_debug 重新 run-cases。
        assert table["perf"]["tuned"] == ("precision_debug", "validation")

        # step-4 (replaced): the old test_design CompositeGroup is now a flat
        # AtomicStage (ascendc-st-design); no group-level transition entry needed.
        # Exhausted → route=None → linear successor (codegen_init).
        assert "test_design" not in table


class TestGetRouteType:
    """Workflow.get_route_type() returns route type for (stage, condition)."""

    def test_corrective_route(self):
        wf = Workflow(stages=[_make_stage("verify")])
        wf._get_transition_table = lambda: {
            "verify": {"build_failed": ("codegen", "corrective")},
        }
        assert wf.get_route_type("verify", "build_failed") == "corrective"

    def test_escalation_route(self):
        wf = Workflow(stages=[_make_stage("verify")])
        wf._get_transition_table = lambda: {
            "verify": {"exhausted": ("design", "escalation")},
        }
        assert wf.get_route_type("verify", "exhausted") == "escalation"

    def test_validation_route(self):
        wf = Workflow(stages=[_make_stage("perf")])
        wf._get_transition_table = lambda: {
            "perf": {"tuned": ("verify", "validation")},
        }
        assert wf.get_route_type("perf", "tuned") == "validation"

    def test_default_for_unknown(self):
        wf = Workflow(stages=[_make_stage("test")])
        assert wf.get_route_type("test", "unknown") == "corrective"

    def test_old_format_string_defaults_to_corrective(self):
        wf = Workflow(stages=[_make_stage("verify")])
        wf._get_transition_table = lambda: {
            "verify": {"build_failed": "codegen"},
        }
        assert wf.get_route_type("verify", "build_failed") == "corrective"


