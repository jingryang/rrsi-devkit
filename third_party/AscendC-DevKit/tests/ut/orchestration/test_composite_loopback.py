"""Phase 3: CompositeGroup nested loopback — scoped quotas + bubble-up."""

from ascendc_devkit.orchestration.graph_executor import GraphExecutor
from ascendc_devkit.orchestration.node import (
    AtomicStage, SequentialGroup, CompositeGroup,
)
from ascendc_devkit.orchestration.kernel.runner import Runner
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.base import Stage
from ascendc_devkit.domain.contract import StageIOContract


class _Cond(Stage):
    default_max_iterations = 1
    def __init__(self, name, cond, fail_times, log):
        self._name = name; self._cond = cond
        self._fail = fail_times; self._calls = 0; self._log = log
    @property
    def name(self): return self._name
    def input_contract(self): return StageIOContract()
    def output_contract(self): return StageIOContract()
    def actions(self, state, iteration=1): return []
    def transition(self, state, result):
        self._calls += 1; self._log.append(self._name); return state
    def resolve_condition(self, state):
        return self._cond if self._calls <= self._fail else "default"


class _Rec(Stage):
    default_max_iterations = 1
    def __init__(self, name, log):
        self._name = name; self._log = log
    @property
    def name(self): return self._name
    def input_contract(self): return StageIOContract()
    def output_contract(self): return StageIOContract()
    def actions(self, state, iteration=1): return []
    def transition(self, state, result):
        self._log.append(self._name); return state


class TestSubScopeIsolation:
    def test_sub_corrective_counts_in_own_scope(self):
        log = []
        design = CompositeGroup(
            name="design",
            children=[AtomicStage(_Rec("high", log)),
                      AtomicStage(_Cond("detail", "needs_revision",
                                        fail_times=2, log=log))],
            transition_table={
                "detail": {"needs_revision": ("detail", "corrective")}},
            max_corrective=5)
        root = SequentialGroup(name="pipeline", children=[
            AtomicStage(_Rec("entry", log)), design])
        s = State.empty().with_updates(non_interactive=True, user_max_iterations=1,
                                       max_corrective=5)
        out = GraphExecutor(runner=Runner()).execute(root, s)
        assert log.count("detail") == 3
        assert out.routing_scopes["pipeline/design"]["corrective"] == 2
        assert out.routing_scopes.get("pipeline", {}).get("corrective", 0) == 0


class TestBubbleUp:
    def test_sub_escalate_bubbles_to_parent(self):
        log = []
        design = CompositeGroup(
            name="design",
            children=[AtomicStage(_Rec("high", log)),
                      AtomicStage(_Cond("detail", "infeasible",
                                        fail_times=1, log=log))],
            transition_table={
                "detail": {"infeasible":
                           ("__escalate__:design_infeasible", "escalation")}})
        root = SequentialGroup(
            name="pipeline",
            children=[AtomicStage(_Rec("requirement", log)), design],
            transition_table={
                "design": {"design_infeasible": ("requirement", "escalation")}},
            max_escalations=3)
        s = State.empty().with_updates(non_interactive=True, user_max_iterations=1,
                                       max_escalations=3)
        out = GraphExecutor(runner=Runner()).execute(root, s)
        assert log.count("requirement") == 2


class _SigStage(Stage):
    """Always fails with the SAME error signature → triggers stagnation."""
    default_max_iterations = 1
    def __init__(self, name, log):
        self._name = name; self._log = log
    @property
    def name(self): return self._name
    def input_contract(self): return StageIOContract()
    def output_contract(self): return StageIOContract()
    def actions(self, state, iteration=1): return []
    def transition(self, state, result):
        self._log.append(self._name); return state
    def resolve_condition(self, state): return "build_failed"
    def error_signature(self, state): return "same-error"


class TestStagnation:
    def test_same_error_3x_stops_corrective(self):
        log = []
        codegen = _Rec("codegen", log)
        verify = _SigStage("verify", log)
        root = SequentialGroup(
            name="pipeline",
            children=[AtomicStage(codegen), AtomicStage(verify)],
            transition_table={
                "verify": {"build_failed": ("codegen", "corrective")}},
            max_corrective=10)
        s = State.empty().with_updates(non_interactive=True, user_max_iterations=1,
                                       max_corrective=10, max_escalations=0)
        out = GraphExecutor(runner=Runner()).execute(root, s)
        # After 2 occurrences of "same-error" on verify→codegen, the 3rd is
        # halted by stagnation detection, so we do NOT reach max_corrective (10).
        hist = out.routing_scopes["pipeline"]["history"]
        same_sig_entries = [h for h in hist if h.get("sig") == "same-error"]
        assert len(same_sig_entries) == 2  # stopped after 2, not 10
        assert out.routing_scopes["pipeline"]["corrective"] == 2


class TestLoopbackIntoGroupRerunsSubtree:
    """C3 (R8 follow-up): a loop-back whose target is a GROUP must clear the
    group's whole subtree so its children actually rerun. Before C3 the clearing
    popped only the direct child key (.../tiling), leaving subtree keys
    (.../tiling/T1/...) marked completed → re-entry's pending was empty → the
    rerun was a silent no-op (anchor→tiling reran 0 templates; perf→design reran
    0 design substages)."""

    def test_loopback_into_group_reruns_children(self):
        log = []
        # dd group: division → integrate-dd. Downstream anchor loops back to dd.
        dd = CompositeGroup(
            name="dd",
            children=[AtomicStage(_Rec("division", log)),
                      AtomicStage(_Rec("integrate-dd", log))],
            transition_table={})
        root = SequentialGroup(
            name="pipeline",
            children=[dd, AtomicStage(_Cond("anchor", "infeasible",
                                            fail_times=1, log=log))],
            transition_table={"anchor": {"infeasible": ("dd", "corrective")}},
            max_corrective=5)
        s = State.empty().with_updates(non_interactive=True, user_max_iterations=1,
                                       max_corrective=5)
        GraphExecutor(runner=Runner()).execute(root, s)
        # anchor fires infeasible once → dd must rerun its children (not no-op).
        assert log.count("division") == 2
        assert log.count("integrate-dd") == 2

