"""Phase 2/3: graph resume via node_status frontier."""

from ascendc_devkit.orchestration.graph_executor import GraphExecutor
from ascendc_devkit.orchestration.node import AtomicStage, SequentialGroup
from ascendc_devkit.orchestration.node_forkjoin import ForkJoinGroup
from ascendc_devkit.orchestration.kernel.runner import Runner
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.base import Stage
from ascendc_devkit.domain.contract import StageIOContract


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


class TestSequentialResume:
    def test_skips_completed_nodes(self):
        log = []
        root = SequentialGroup(name="pipeline", children=[
            AtomicStage(_Rec("a", log)), AtomicStage(_Rec("b", log)),
            AtomicStage(_Rec("c", log))])
        s = State.empty().with_updates(
            non_interactive=True, user_max_iterations=1,
            node_status={"pipeline/a": "completed", "pipeline/b": "completed"})
        GraphExecutor(runner=Runner()).execute(root, s)
        assert log == ["c"]   # a, b skipped


class TestForkJoinResume:
    def test_reruns_only_incomplete_branches(self):
        log = []
        root = ForkJoinGroup(name="suite", children=[
            AtomicStage(_Rec("a", log)), AtomicStage(_Rec("b", log))])
        s = State.empty().with_updates(
            non_interactive=True, user_max_iterations=1,
            node_status={"suite/a": "completed"})
        GraphExecutor(runner=Runner()).execute(root, s)
        assert log == ["b"]   # a skipped


class TestResumeCausalValidity:
    """P52 end-to-end: resume invalidates downstream 'completed' built on a
    failed sibling, so the executor actually reruns them (not silently skips
    with stale results). See 29-resume-causal-validity-impl.md §4."""

    def test_reruns_downstream_after_failed_sibling(self):
        import types
        from ascendc_devkit.application.dispatcher import _resume_node_status
        log = []
        root = SequentialGroup(name="pipe", children=[
            AtomicStage(_Rec("a", log)), AtomicStage(_Rec("b", log)),
            AtomicStage(_Rec("c", log)), AtomicStage(_Rec("d", log))])
        # b failed previously; c/d completed on b's bad output (stale).
        s = State.empty().with_updates(
            non_interactive=True, user_max_iterations=1,
            node_status={"pipe/a": "completed", "pipe/b": "failed",
                         "pipe/c": "completed", "pipe/d": "completed"})
        wf = types.SimpleNamespace(root=root, name="pipe")
        s = s.with_updates(node_status=_resume_node_status(s, wf))
        GraphExecutor(runner=Runner()).execute(root, s)
        # a skipped (valid prefix); b (failed) + c + d (invalidated) all rerun.
        assert log == ["b", "c", "d"]

    def test_bubbled_upstream_halt_resume_reruns_diagnose(self):
        """P40 end-to-end: a bubbled upstream halt (diagnose → __escalate__:
        upstream → group → root __halt__) marks the atomic diagnose leaf
        "failed". On resume, _resume_node_status re-enters diagnose AND
        invalidates downstream (perf), so the halted run is actually resumable.

        Mirrors unique batch 20260823-125944-7d3451: before P40 the snapshot
        showed ALL nodes completed (incl. root) and RESUME=1 exited 0.0s with
        'All stages already completed' — resume could never re-run diagnose."""
        import types
        from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
        from ascendc_devkit.application.dispatcher import _resume_node_status

        class _DiagnoseStage(Stage):
            name = "diagnose"
            default_max_iterations = 1
            def __init__(self, log): self._log = log
            def input_contract(self): return StageIOContract()
            def output_contract(self): return StageIOContract()
            def actions(self, state, iteration=1): return []
            def transition(self, state, result):
                self._log.append(self.name)
                return state

        class _PerfStage(Stage):
            name = "perf"
            default_max_iterations = 1
            def __init__(self, log): self._log = log
            def input_contract(self): return StageIOContract()
            def output_contract(self): return StageIOContract()
            def actions(self, state, iteration=1): return []
            def transition(self, state, result):
                self._log.append(self.name)
                return state

        pdbg = SequentialGroup(name="precision_debug", children=[
            AtomicStage(_Rec("run_tests", [])),
            AtomicStage(_DiagnoseStage([]))])
        root = SequentialGroup(name="pipeline", children=[
            pdbg, AtomicStage(_PerfStage([]))])

        # Snapshot exactly as P40 now persists it: the atomic diagnose leaf is
        # "failed" (halt origin), run_tests still "completed" (valid prefix),
        # the group + root "failed" (propagated via _group_status), and perf was
        # never reached (halted before it).
        s = State.empty().with_updates(
            non_interactive=True, user_max_iterations=1,
            node_status={
                "pipeline/precision_debug/run_tests": "completed",
                "pipeline/precision_debug/diagnose": "failed",
                "pipeline/precision_debug": "failed",
                "pipeline": "failed",
            })
        wf = types.SimpleNamespace(root=root, name="pipeline")
        s = s.with_updates(node_status=_resume_node_status(s, wf))

        # run_tests (valid prefix) kept; diagnose re-entered; perf (downstream
        # of the failed group) invalidated → also re-runs once diagnose passes.
        assert s.node_status.get("pipeline/precision_debug/run_tests") == "completed"
        assert s.node_status.get("pipeline/precision_debug/diagnose") == "failed"
        assert "pipeline/precision_debug" not in s.node_status or \
            s.node_status.get("pipeline/precision_debug") != "completed", (
            "group must not stay 'completed' (resume would skip it entirely)")
        assert "pipeline" not in s.node_status or \
            s.node_status.get("pipeline") != "completed", (
            "root must not stay 'completed' (dispatcher all_done guard)")

        # The executor actually re-enters diagnose (the halt origin).
        log = []
        root2 = SequentialGroup(name="pipeline", children=[
            SequentialGroup(name="precision_debug", children=[
                AtomicStage(_Rec("run_tests", log)),
                AtomicStage(_DiagnoseStage(log))]),
            AtomicStage(_PerfStage(log))])
        GraphExecutor(runner=Runner()).execute(root2, s)
        assert "diagnose" in log, "bubbled-upstream halt origin must re-run on resume"

