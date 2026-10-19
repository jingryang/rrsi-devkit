"""P42: escalation exit-status ownership.

An escalation's failed-mark must land only where the disposition is decided
(root ``__halt__``), never at the emission point — success escalations
(``__escalate__:passed``) and soft-gate forwards (``exhausted`` → successor)
advance linearly by design and must NOT read as "Workflow completed with
failed stages" (incident 20260825-153847-ccad38: run_tests 20/20 ok yet
node_status failed → EX_DATAERR).
"""

from ascendc_devkit.orchestration.graph_executor import GraphExecutor
from ascendc_devkit.orchestration.node import (
    AtomicStage, SequentialGroup, CompositeGroup,
)
from ascendc_devkit.orchestration.kernel.runner import Runner
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.base import Stage
from ascendc_devkit.domain.contract import StageIOContract


class _Cond(Stage):
    """Stage whose resolve_condition returns a fixed condition forever."""
    default_max_iterations = 1

    def __init__(self, name, cond, log):
        self._name = name
        self._cond = cond
        self._log = log

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
        self._log.append(self._name)
        return state

    def resolve_condition(self, state):
        return self._cond


class _Rec(_Cond):
    def __init__(self, name, log):
        super().__init__(name, "default", log)

    def resolve_condition(self, state):
        return "default"


def _state():
    return State.empty().with_updates(non_interactive=True,
                                      user_max_iterations=1,
                                      max_corrective=5, max_escalations=3)


def _failed_nodes(out):
    return sorted(k for k, v in (out.node_status or {}).items()
                  if v == "failed")


class TestCleanExitNotMarkedFailed:
    def test_all_pass_escalation_exits_clean(self):
        """precision all_pass → __escalate__:passed; root has no entry → linear
        advance. No node may read "failed" (pre-P42: run_tests was marked)."""
        log = []
        precision = CompositeGroup(
            name="precision_debug",
            children=[AtomicStage(_Rec("run_tests", log)),
                      AtomicStage(_Rec("diagnose", log))],
            transition_table={
                "run_tests": {"all_pass": ("__escalate__:passed", "validation")},
            })
        root = SequentialGroup(
            name="self_evolve_op",
            children=[AtomicStage(_Rec("entry", log)),
                      precision,
                      AtomicStage(_Rec("cannbench_adapt", log))])
        out = GraphExecutor(runner=Runner()).execute(root, _state())
        # linear successor ran; everything completed; nothing failed
        assert "cannbench_adapt" in log
        assert _failed_nodes(out) == []
        assert out.node_status.get("self_evolve_op") == "completed"

    def test_soft_gate_exhausted_forward_route_not_failed(self):
        """precision exhausted → root routes forward (soft gate) — same shape as
        ("cannbench_adapt", "validation") in the self_evolve table."""
        log = []
        precision = CompositeGroup(
            name="precision_debug",
            children=[AtomicStage(_Cond("run_tests", "exhausted", log))],
            transition_table={
                "run_tests": {"exhausted":
                              ("__escalate__:exhausted", "validation")}})
        root = SequentialGroup(
            name="self_evolve_op",
            children=[precision, AtomicStage(_Rec("cannbench_adapt", log))],
            transition_table={
                "precision_debug": {"exhausted":
                                    ("cannbench_adapt", "validation")}})
        out = GraphExecutor(runner=Runner()).execute(root, _state())
        assert "cannbench_adapt" in log
        assert _failed_nodes(out) == []


class TestHaltStillMarksOrigin:
    def test_halt_escalation_marks_group_and_origin(self):
        """upstream/stalled → root __halt__: the halting GROUP and the atomic
        ORIGIN both read "failed" (P40 resume contract preserved via P42)."""
        log = []
        precision = CompositeGroup(
            name="precision_debug",
            children=[AtomicStage(_Cond("diagnose", "upstream", log))],
            transition_table={
                "diagnose": {"upstream":
                             ("__escalate__:upstream", "validation")}})
        root = SequentialGroup(
            name="self_evolve_op",
            children=[precision],
            transition_table={
                "precision_debug": {"upstream": ("__halt__", "escalation")}})
        out = GraphExecutor(runner=Runner()).execute(root, _state())
        assert out.is_terminal is True
        failed = _failed_nodes(out)
        assert "self_evolve_op/precision_debug" in failed
        assert "self_evolve_op/precision_debug/diagnose" in failed

    def test_direct_atomic_halt_marks_itself_only(self):
        """An atomic whose OWN route is __halt__ (no bubble) marks itself —
        no origin exists; behavior identical to pre-P42."""
        log = []
        root = SequentialGroup(
            name="pipeline",
            children=[AtomicStage(_Cond("codegen", "no_last_deploy", log))],
            transition_table={
                "codegen": {"no_last_deploy": ("__halt__", "escalation")}})
        out = GraphExecutor(runner=Runner()).execute(root, _state())
        assert out.is_terminal is True
        # the halting atomic + root propagation; nothing else
        assert _failed_nodes(out) == ["pipeline", "pipeline/codegen"]


class TestGroupReEscalationKeepsDeepOrigin:
    def test_re_escalating_group_preserves_inner_origin(self):
        """A group re-emitting a consumed bubble must keep the DEEP atomic
        origin (not blank it) so a root halt re-enters the origin leaf."""
        log = []
        inner = CompositeGroup(
            name="inner",
            children=[AtomicStage(_Cond("leaf", "bad", log))],
            transition_table={
                "leaf": {"bad": ("__escalate__:bad", "escalation")}})
        outer = CompositeGroup(
            name="outer",
            children=[inner],
            transition_table={
                "inner": {"bad": ("__escalate__:worse", "escalation")}})
        root = SequentialGroup(
            name="pipeline",
            children=[outer],
            transition_table={
                "outer": {"worse": ("__halt__", "escalation")}})
        out = GraphExecutor(runner=Runner()).execute(root, _state())
        assert out.is_terminal is True
        failed = _failed_nodes(out)
        assert "pipeline/outer" in failed
        assert "pipeline/outer/inner/leaf" in failed


class TestSnapshotStripsOrigin:
    def test_bubble_origin_transient_not_persisted(self):
        s = _state().with_updates(_bubble_condition="upstream",
                                  _bubble_origin="pipeline/precision/diagnose")
        snap = s.to_snapshot()
        assert "_bubble_origin" not in snap
        assert "_bubble_condition" not in snap
        r = State.from_snapshot(dict(snap, **{"_bubble_origin": "stale"}))
        assert r._bubble_origin == ""


class TestNoDoubleConvergeOnPassed:
    def test_no_ge_converge_when_transition_declared_converged(self, monkeypatch):
        """§step-91 P5: transition 已声明收敛（_converged_this_pass=True）时，GE 升级
        分支不得重复收敛——判据是业务语义标记（§1.10），uniform 覆盖
        passed/exhausted/stalled（ccad38 实证背靠背双 converge）。abort/timeout
        早退未设标记 → GE 兜底收敛保留。"""
        import ascendc_devkit.orchestration.graph_executor as ge
        calls = []
        monkeypatch.setattr(ge, "_converge_precision_debug",
                            lambda s, n: calls.append(1) or s)
        log = []
        precision = CompositeGroup(
            name="precision_debug",
            children=[AtomicStage(_Cond("run_tests", "all_pass", log))],
            transition_table={
                "run_tests": {"all_pass": ("__escalate__:passed", "validation")}})
        root = SequentialGroup(
            name="self_evolve_op",
            children=[precision, AtomicStage(_Rec("cannbench_adapt", log))],
            transition_table={
                "precision_debug": {"passed":
                                    ("cannbench_adapt", "validation")}})
        out = GraphExecutor(runner=Runner()).execute(
            root, _state().with_updates(_converged_this_pass=True))
        assert calls == []          # GE 不重复收敛（transition 已声明）
        assert "cannbench_adapt" in log

    def test_ge_converges_when_transition_did_not(self, monkeypatch):
        """早退/中途升级（transition 未设 _converged_this_pass）→ GE 兜底收敛仍发生
        （保持 P40 前的覆盖）。"""
        import ascendc_devkit.orchestration.graph_executor as ge
        calls = []
        monkeypatch.setattr(ge, "_converge_precision_debug",
                            lambda s, n: calls.append(1) or s)
        log = []
        precision = CompositeGroup(
            name="precision_debug",
            children=[AtomicStage(_Cond("run_tests", "all_pass", log))],
            transition_table={
                "run_tests": {"all_pass": ("__escalate__:passed", "validation")}})
        root = SequentialGroup(
            name="self_evolve_op",
            children=[precision],
            transition_table={
                "precision_debug": {"passed": ("__halt__", "escalation")}})
        out = GraphExecutor(runner=Runner()).execute(root, _state())
        assert calls == [1]          # 未声明 → GE 兜底收敛（且 __halt__ 标 origin）
        assert out.is_terminal is True
        assert "self_evolve_op/precision_debug" in _failed_nodes(out)
