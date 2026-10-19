"""step-2b B (resume) — node_status is the sole resume-completion authority.

These pin the integrate name-collision bug and the node_status-only contract for
_resume_node_status. The detailed-design group has an `integrate` substage whose
name collides with the top-level `integrate` stage; both write
stage_iterations["integrate"]. The old bridge synthesized
f"{workflow.name}/integrate" from stage_iterations → it falsely marked the
top-level integrate completed and resume skipped it. B2 deletes the synthesis so
only the persisted multi-level node_status drives resume.
"""

import types

from ascendc_devkit.application.dispatcher import _resume_node_status
from ascendc_devkit.orchestration.base import Stage
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.node import AtomicStage, SequentialGroup
from ascendc_devkit.orchestration.node_forkjoin import ForkJoinGroup
from ascendc_devkit.orchestration.registry import get_workflow
from ascendc_devkit.domain.contract import StageIOContract


class _Stub(Stage):
    """Minimal Stage for resume tree construction (not executed in resume tests)."""
    default_max_iterations = 1

    def __init__(self, name):
        self._name = name

    @property
    def name(self):
        return self._name

    def input_contract(self):
        return StageIOContract()

    def output_contract(self):
        return StageIOContract()

    def actions(self, state, iteration=1):
        return []

    def transition(self, state, result):
        return state


class TestResumeNodeStatusAuthority:
    def test_synthesize_substage_not_mark_top_level_integrate(self):
        # detailed-design's synthesize substage ran; its multi-level path is
        # completed, but the TOP-LEVEL integrate has NOT. The frontier must not
        # mark the top-level integrate completed (else resume skips real work).
        wf = get_workflow("generate_ascendc")
        state = State(
            workflow_name="generate_ascendc",
            stage_iterations={"synthesize": 1},  # group substage, not top-level
            node_status={
                "generate_ascendc/detailed-design/synthesize": "completed"},
        )
        frontier = _resume_node_status(state, wf)
        assert "generate_ascendc/integrate" not in frontier

    def test_node_status_sole_authority_no_phantoms(self):
        # node_status is the SOLE resume authority (step-2b B): the frontier is
        # built from multi-level node_status only — NO single-level phantom keys
        # are synthesized from stage_iterations (the deleted bridge did that).
        # P52 layers clean-prefix filtering on top: a valid-prefix completed node
        # (entry, the first root child) survives; phantoms are still never injected.
        wf = get_workflow("generate_ascendc")
        state = State(
            workflow_name="generate_ascendc",
            # old bridge synthesized phantoms from these stage_iterations:
            stage_iterations={"split": 1, "template-division": 1},
            node_status={"generate_ascendc/entry": "completed"},   # first root child
        )
        frontier = _resume_node_status(state, wf)
        assert frontier.get("generate_ascendc/entry") == "completed"  # valid prefix kept
        assert "generate_ascendc/split" not in frontier               # no phantom
        assert "generate_ascendc/template-division" not in frontier   # no phantom


class TestResumeBreakerReset:
    """P50: a manual resume is a fresh attempt — the codegen circuit breaker
    must reset (a stale trip from a prior process must not strand the run), and
    an infra-typed last_error must be cleared (else codegen.actions()'s infra
    guard halts instantly and the resume can't re-probe after the env fix)."""

    def test_resets_breaker_and_clears_infra_last_error(self):
        from ascendc_devkit.application.dispatcher import _resume_breaker_reset
        from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
        state = State(
            codegen_consecutive_failures=3,
            last_error=ErrorFeedback(
                stage_name="codegen",
                error_type="infra",
                message="Infrastructure error: 503 No available channel",
            ),
        )
        out = _resume_breaker_reset(state)
        assert out["codegen_consecutive_failures"] == 0
        assert out["last_error"] is None  # infra trap cleared → resume can re-probe

    def test_resets_breaker_but_keeps_logic_last_error(self):
        # A logic failure's last_error is useful retry context — reset the
        # breaker counter but leave the error untouched for the retried agent.
        from ascendc_devkit.application.dispatcher import _resume_breaker_reset
        from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
        le = ErrorFeedback(
            stage_name="verify",
            error_type="compile_error",
            message="undefined symbol: GeluCustom",
        )
        state = State(codegen_consecutive_failures=3, last_error=le)
        out = _resume_breaker_reset(state)
        assert out["codegen_consecutive_failures"] == 0
        assert "last_error" not in out  # logic error preserved (not in override dict)

    def test_resets_breaker_when_no_last_error(self):
        from ascendc_devkit.application.dispatcher import _resume_breaker_reset
        state = State(codegen_consecutive_failures=2)
        out = _resume_breaker_reset(state)
        assert out["codegen_consecutive_failures"] == 0
        assert "last_error" not in out


class TestResumeCausalValidity:
    """P52: within a SequentialGroup scope, resume enforces clean-prefix causal
    validity — a "completed" node is valid only if all preceding siblings are
    also completed. The first non-completed (failed/missing) node breaks the
    prefix; every "completed" sibling after it is invalidated (→ rerun).

    ForkJoinGroup branches are parallel-independent: a failed branch does NOT
    invalidate a completed branch. But a fork-join node that ended up "failed"
    still breaks its parent SequentialGroup's prefix (downstream siblings
    invalidated). See 29-resume-causal-validity-impl.md §1.
    """

    @staticmethod
    def _wf(root):
        return types.SimpleNamespace(root=root, name=root.name)

    @staticmethod
    def _seq(*names):
        return SequentialGroup(
            name="pipe",
            children=[AtomicStage(_Stub(n)) for n in names])

    def test_failed_invalidates_downstream_completed(self):
        # The实证 shape: verify=failed, adapt/eval/finalize=completed on verify's
        # bad state. Resume must invalidate the stale downstream.
        root = self._seq("a", "b", "c", "d")
        state = State.empty().with_updates(node_status={
            "pipe/a": "completed", "pipe/b": "failed",
            "pipe/c": "completed", "pipe/d": "completed"})
        ns = _resume_node_status(state, self._wf(root))
        assert ns.get("pipe/a") == "completed"   # valid prefix kept
        assert "pipe/c" not in ns                 # downstream invalidated
        assert "pipe/d" not in ns

    def test_preserves_valid_completed_prefix(self):
        root = self._seq("a", "b", "c", "d")
        state = State.empty().with_updates(node_status={
            "pipe/a": "completed", "pipe/b": "completed",
            "pipe/c": "failed", "pipe/d": "completed"})
        ns = _resume_node_status(state, self._wf(root))
        assert ns.get("pipe/a") == "completed"
        assert ns.get("pipe/b") == "completed"   # before first-failure: kept
        assert "pipe/d" not in ns                 # after first-failure: invalidated

    def test_missing_breaks_prefix(self):
        # b absent from node_status (never ran / snapshot gap) → breaks prefix
        # → downstream completed invalidated.
        root = self._seq("a", "b", "c")
        state = State.empty().with_updates(node_status={
            "pipe/a": "completed", "pipe/c": "completed"})
        ns = _resume_node_status(state, self._wf(root))
        assert ns.get("pipe/a") == "completed"
        assert "pipe/c" not in ns

    def test_all_completed_unchanged(self):
        root = self._seq("a", "b")
        ns_in = {"pipe/a": "completed", "pipe/b": "completed"}
        state = State.empty().with_updates(node_status=dict(ns_in))
        ns = _resume_node_status(state, self._wf(root))
        assert ns == ns_in

    def test_forkjoin_branches_independent(self):
        # fork-join branches are parallel: A failed must NOT invalidate B.
        root = ForkJoinGroup(
            name="suite",
            children=[AtomicStage(_Stub("a")), AtomicStage(_Stub("b"))])
        state = State.empty().with_updates(node_status={
            "suite/a": "failed", "suite/b": "completed"})
        ns = _resume_node_status(state, self._wf(root))
        assert ns.get("suite/b") == "completed"   # NOT invalidated

    def test_nested_sequential_scope(self):
        # clean-prefix applies at every SequentialGroup scope, including nested.
        inner = SequentialGroup(
            name="G",
            children=[AtomicStage(_Stub("g1")), AtomicStage(_Stub("g2")),
                      AtomicStage(_Stub("g3"))])
        root = SequentialGroup(name="pipe", children=[inner])
        state = State.empty().with_updates(node_status={
            "pipe/G/g1": "completed", "pipe/G/g2": "failed",
            "pipe/G/g3": "completed", "pipe/G": "failed"})
        ns = _resume_node_status(state, self._wf(root))
        assert ns.get("pipe/G/g1") == "completed"
        assert "pipe/G/g3" not in ns              # nested scope clean-prefix

    def test_forkjoin_failed_breaks_parent_prefix(self):
        # fork-join node is "failed" in parent sequential scope → downstream
        # sibling invalidated (fork-join participates in parent clean-prefix;
        # only its INTERNAL branches are independent).
        fj = ForkJoinGroup(
            name="suite",
            children=[AtomicStage(_Stub("a")), AtomicStage(_Stub("b"))])
        root = SequentialGroup(
            name="pipe",
            children=[AtomicStage(_Stub("pre")), fj, AtomicStage(_Stub("post"))])
        state = State.empty().with_updates(node_status={
            "pipe/pre": "completed", "pipe/suite": "failed",
            "pipe/post": "completed"})
        ns = _resume_node_status(state, self._wf(root))
        assert ns.get("pipe/pre") == "completed"
        assert "pipe/post" not in ns
