"""Phase 1: GraphExecutor — tree traversal + scoped routing."""

from pathlib import Path
from ascendc_devkit.orchestration.graph_executor import GraphExecutor
from ascendc_devkit.orchestration.node import AtomicStage, SequentialGroup
from ascendc_devkit.orchestration.kernel.runner import Runner
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.base import Stage
from ascendc_devkit.domain.contract import StageIOContract


class _RecordStage(Stage):
    """Records execution order into a shared list via transition."""
    default_max_iterations = 1
    def __init__(self, name, log):
        self._name = name; self._log = log
    @property
    def name(self): return self._name
    def input_contract(self): return StageIOContract()
    def output_contract(self): return StageIOContract()
    def actions(self, state, iteration=1): return []
    def transition(self, state, result):
        self._log.append(self._name)
        return state


def _executor():
    return GraphExecutor(runner=Runner())


class _GateFailStage(Stage):
    """A stage whose gate always fails — simulates a missing upstream artifact."""
    default_max_iterations = 1
    def __init__(self, name, log):
        self._name = name; self._log = log
    @property
    def name(self): return self._name
    def input_contract(self): return StageIOContract()
    def output_contract(self): return StageIOContract()
    def actions(self, state, iteration=1): return []
    def transition(self, state, result):
        self._log.append(self._name)
        return state
    def gate(self):
        from ascendc_devkit.orchestration.kernel.gate import Gate, GateResult
        class _Fail(Gate):
            def evaluate(self, evidence):
                return GateResult(passed=False, reason="No requirement available")
        return _Fail()


class TestFailFastOnPrecondition:
    def test_precondition_failure_halts_and_propagates(self):
        """A gate (precondition) failure must abort the workflow and propagate
        PreconditionError instead of being swallowed and advancing linearly."""
        import pytest
        from ascendc_devkit.domain.exceptions import PreconditionError
        log = []
        root = SequentialGroup(name="pipeline", children=[
            AtomicStage(_GateFailStage("design", log)),
            AtomicStage(_RecordStage("codegen", log))])
        s = State.empty().with_updates(non_interactive=True, user_max_iterations=1)
        with pytest.raises(PreconditionError) as ei:
            _executor().execute(root, s)
        assert ei.value.stage_name == "design"
        # Downstream stage must NOT have run.
        assert "codegen" not in log

class TestSequentialTraversal:
    def test_runs_children_in_order(self):
        log = []
        root = SequentialGroup(name="pipeline", children=[
            AtomicStage(_RecordStage("a", log)),
            AtomicStage(_RecordStage("b", log)),
            AtomicStage(_RecordStage("c", log))])
        s = State.empty().with_updates(non_interactive=True, user_max_iterations=1)
        _executor().execute(root, s)
        assert log == ["a", "b", "c"]

    def test_marks_node_status_completed(self):
        log = []
        root = SequentialGroup(name="pipeline", children=[
            AtomicStage(_RecordStage("a", log))])
        s = State.empty().with_updates(non_interactive=True, user_max_iterations=1)
        out = _executor().execute(root, s)
        assert out.node_status.get("pipeline/a") == "completed"
        assert out.node_status.get("pipeline") == "completed"


class _CondStage(Stage):
    """Returns a fixed condition the first N times, then 'default'."""
    default_max_iterations = 1
    def __init__(self, name, cond, fail_times, log):
        self._name = name; self._cond = cond
        self._fail_times = fail_times; self._calls = 0; self._log = log
    @property
    def name(self): return self._name
    def input_contract(self): return StageIOContract()
    def output_contract(self): return StageIOContract()
    def actions(self, state, iteration=1): return []
    def transition(self, state, result):
        self._calls += 1; self._log.append(self._name)
        return state
    def resolve_condition(self, state):
        if self._calls <= self._fail_times:
            return self._cond
        return "default"


class TestScopedLoopback:
    def test_corrective_loopback_within_scope(self):
        """verify fails twice → loops back to codegen twice → then proceeds."""
        log = []
        codegen = _RecordStage("codegen", log)
        verify = _CondStage("verify", "build_failed", fail_times=2, log=log)
        root = SequentialGroup(
            name="pipeline",
            children=[AtomicStage(codegen), AtomicStage(verify)],
            transition_table={
                "verify": {"build_failed": ("codegen", "corrective")}},
            max_corrective=5)
        s = State.empty().with_updates(non_interactive=True, user_max_iterations=1,
                                       max_corrective=5)
        out = GraphExecutor(runner=Runner()).execute(root, s)
        # codegen ran 3 times (initial + 2 loopbacks), verify 3 times
        assert log.count("codegen") == 3
        assert log.count("verify") == 3
        assert out.routing_scopes["pipeline"]["corrective"] == 2

    def test_corrective_quota_exhausted_stops(self):
        log = []
        codegen = _RecordStage("codegen", log)
        verify = _CondStage("verify", "build_failed", fail_times=99, log=log)
        root = SequentialGroup(
            name="pipeline",
            children=[AtomicStage(codegen), AtomicStage(verify)],
            transition_table={
                "verify": {"build_failed": ("codegen", "corrective")}},
            max_corrective=2)
        s = State.empty().with_updates(non_interactive=True, user_max_iterations=1,
                                       max_corrective=2)
        out = GraphExecutor(runner=Runner()).execute(root, s)
        # 2 loopbacks then quota stops it
        assert out.routing_scopes["pipeline"]["corrective"] == 2

    def test_reverse_validation_edge_is_quota_bounded(self):
        """T2 regression: a 'validation' edge that jumps BACKWARD (e.g.
        perf→verify 'tuned') is a real loop and must be bounded by the
        corrective quota, not loop forever. Mirrors the verify↔perf hang."""
        log = []
        verify = _RecordStage("verify", log)
        # perf always reports 'tuned' → validation edge back to verify.
        perf = _CondStage("perf", "tuned", fail_times=99, log=log)
        root = SequentialGroup(
            name="pipeline",
            children=[AtomicStage(verify), AtomicStage(perf)],
            transition_table={
                "perf": {"tuned": ("verify", "validation")}},
            max_corrective=3)
        s = State.empty().with_updates(non_interactive=True, user_max_iterations=1,
                                       max_corrective=3)
        out = GraphExecutor(runner=Runner()).execute(root, s)
        # Reverse validation metered against corrective quota → stops at 3.
        assert out.routing_scopes["pipeline"]["corrective"] == 3
        # verify ran initial + 3 loopbacks = 4; perf ran 4 times.
        assert log.count("perf") == 4
        assert log.count("verify") == 4

    def test_forward_validation_edge_not_counted(self):
        """A forward 'validation' edge (target after current) is normal
        re-validation and must NOT consume the corrective quota."""
        log = []
        a = _CondStage("a", "revalidate", fail_times=1, log=log)
        b = _RecordStage("b", log)
        root = SequentialGroup(
            name="pipeline",
            children=[AtomicStage(a), AtomicStage(b)],
            transition_table={
                "a": {"revalidate": ("b", "validation")}},
            max_corrective=3)
        s = State.empty().with_updates(non_interactive=True, user_max_iterations=1,
                                       max_corrective=3)
        out = GraphExecutor(runner=Runner()).execute(root, s)
        # Forward validation does not increment corrective.
        assert out.routing_scopes.get("pipeline", {}).get("corrective", 0) == 0


class TestHaltRouting:
    """A `__halt__` route target stops traversal terminally instead of looping
    back or advancing — mirrors verify's exhausted edge, which must not run
    downstream stages on known-broken code nor auto-rewrite the design.
    """

    def test_halt_stops_and_skips_downstream(self):
        log = []
        codegen = _RecordStage("codegen", log)
        # verify always reports exhausted → routed to __halt__.
        verify = _CondStage("verify", "exhausted", fail_times=99, log=log)
        perf = _RecordStage("perf", log)
        root = SequentialGroup(
            name="pipeline",
            children=[AtomicStage(codegen), AtomicStage(verify),
                      AtomicStage(perf)],
            transition_table={
                "verify": {"exhausted": ("__halt__", "escalation")}},
            max_escalations=5)
        s = State.empty().with_updates(non_interactive=True, user_max_iterations=1,
                                       max_escalations=5)
        out = GraphExecutor(runner=Runner()).execute(root, s)
        # verify ran once, then halted: perf (downstream) must NOT run.
        assert log.count("verify") == 1
        assert "perf" not in log
        # The run is flagged terminal so the dispatcher can report a halt.
        assert out.is_terminal is True

    def test_route_halt_marks_leaf_failed_for_resume(self):
        """P40: route-triggered __halt__ (resolve_condition → __halt__, e.g.
        verify's exhausted → halt OR diagnose's upstream → halt) must mark the
        halting LEAF node_status='failed' (not 'completed').

        Why: the stage body completes normally (writes its artifacts, node_status
        marked 'completed' at _execute_atomic L343), THEN resolve_condition routes
        to __halt__ which only sets is_terminal. Without marking the leaf 'failed',
        _group_status propagates 'completed' to the root and the dispatcher's
        resume authority (root node_status=='completed') short-circuits:
        'All stages already completed, regenerating report' — so a halted run can
        never be resumed, and resume-time fixes (e.g. diagnose resume_status
        injection) never get a chance to run.

        Real instance: unique batch 20260823-125944-7d3451 — control.json
        upstream_signal=True (deploy), but snapshot showed ALL nodes completed
        incl. root, and RESUME=1 exited 0.0s with '1/1 workflow-done'.
        """
        log = []
        codegen = _RecordStage("codegen", log)
        verify = _CondStage("verify", "exhausted", fail_times=99, log=log)
        perf = _RecordStage("perf", log)
        root = SequentialGroup(
            name="pipeline",
            children=[AtomicStage(codegen), AtomicStage(verify),
                      AtomicStage(perf)],
            transition_table={
                "verify": {"exhausted": ("__halt__", "escalation")}},
            max_escalations=5)
        s = State.empty().with_updates(non_interactive=True, user_max_iterations=1,
                                       max_escalations=5)
        out = GraphExecutor(runner=Runner()).execute(root, s)

        # The halting leaf must NOT read as "completed" (resume-skipped) — it
        # must be "failed" so a re-run re-enters it.
        assert out.node_status.get("pipeline/verify") == "failed", (
            "route-halt leaf must be 'failed' (P40): otherwise resume 误判 "
            "all_done、静默跳过下游")
        # _group_status propagates failed → root stays non-completed.
        assert out.node_status.get("pipeline") == "failed", (
            "route-halt 必须经 _group_status 传播到根,根保持非 completed")
        assert out.node_status.get("pipeline/codegen") == "completed"

    def test_upstream_route_halt_marks_leaf_failed(self):
        """P40: the upstream → __halt__ route (precision_debug diagnose 上报
        upstream defect) is a DISTINCT path from exhausted — must also mark the
        halting leaf 'failed' for resume."""
        from ascendc_devkit.orchestration.kernel.state import ErrorFeedback

        class _UpstreamStage(Stage):
            name = "precision_debug"
            default_max_iterations = 1
            def input_contract(self): return StageIOContract()
            def output_contract(self): return StageIOContract()
            def actions(self, state, iteration=1): return []
            def transition(self, state, result):
                return state.with_updates(
                    last_error=ErrorFeedback(
                        stage_name=self.name, error_type="upstream",
                        message="upstream defect in [deploy]: stale OPP kernel"))
            def resolve_condition(self, state):
                return "upstream"

        root = SequentialGroup(
            name="pipeline",
            children=[AtomicStage(_UpstreamStage())],
            transition_table={
                "precision_debug": {"upstream": ("__halt__", "escalation")}},
            max_escalations=5)
        s = State.empty().with_updates(non_interactive=True,
                                       user_max_iterations=1, max_escalations=5)
        out = GraphExecutor(runner=Runner()).execute(root, s)

        assert out.is_terminal is True
        assert out.node_status.get("pipeline/precision_debug") == "failed", (
            "upstream route-halt leaf must be 'failed' (P40)")
        assert out.node_status.get("pipeline") == "failed"

    def test_bubbled_upstream_halt_marks_atomic_leaf_failed(self):
        """P40 nested: diagnose (atomic) bubbles 'upstream' via __escalate__ out
        of the precision_debug GROUP, which then reaches __halt__ at the root.
        The ATOMIC diagnose leaf must be marked 'failed' — not just the group —
        so resume re-enters the halt origin, not a silent no-op group."""
        from ascendc_devkit.orchestration.kernel.state import ErrorFeedback

        class _DiagnoseUpstreamStage(Stage):
            name = "diagnose"
            default_max_iterations = 1
            def input_contract(self): return StageIOContract()
            def output_contract(self): return StageIOContract()
            def actions(self, state, iteration=1): return []
            def transition(self, state, result):
                return state.with_updates(
                    last_error=ErrorFeedback(
                        stage_name=self.name, error_type="upstream",
                        message="deploy 旧 OPP kernel"))
            def resolve_condition(self, state):
                return "upstream"

        class _RunTestsStage(Stage):
            name = "run_tests"
            default_max_iterations = 1
            def input_contract(self): return StageIOContract()
            def output_contract(self): return StageIOContract()
            def actions(self, state, iteration=1): return []
            def transition(self, state, result):
                return state

        pdbg = SequentialGroup(
            name="precision_debug",
            children=[AtomicStage(_RunTestsStage()),
                      AtomicStage(_DiagnoseUpstreamStage())],
            transition_table={
                "diagnose": {"upstream": ("__escalate__:upstream", "validation")}})
        root = SequentialGroup(
            name="pipeline",
            children=[pdbg],
            transition_table={
                "precision_debug": {"upstream": ("__halt__", "escalation")}},
            max_escalations=5)
        s = State.empty().with_updates(non_interactive=True,
                                       user_max_iterations=1, max_escalations=5)
        out = GraphExecutor(runner=Runner()).execute(root, s)

        assert out.is_terminal is True
        # The halt ORIGIN — the atomic diagnose leaf — must be "failed" so
        # resume re-enters it (clean-prefix walker: first_bad = diagnose).
        assert out.node_status.get("pipeline/precision_debug/diagnose") == "failed", (
            "bubbled upstream halt origin (atomic leaf) must be 'failed' (P40)")
        # _group_status propagates failed up to root.
        assert out.node_status.get("pipeline/precision_debug") == "failed"
        assert out.node_status.get("pipeline") == "failed"

    def test_halt_reason_names_corrective_exhausted_kind_stage(self):
        """design-halt-diagnostics P3: a __halt__ route (corrective/escalation
        budget exhaustion) must record halt_reason with
        kind='corrective_exhausted' and the exhausted stage's name — distinct
        from the fail_strategy=halt mechanism above, so the dispatcher can
        tell the two apart and give scenario-appropriate guidance."""
        log = []
        codegen = _RecordStage("codegen", log)
        verify = _CondStage("verify", "exhausted", fail_times=99, log=log)
        perf = _RecordStage("perf", log)
        root = SequentialGroup(
            name="pipeline",
            children=[AtomicStage(codegen), AtomicStage(verify),
                      AtomicStage(perf)],
            transition_table={
                "verify": {"exhausted": ("__halt__", "escalation")}},
            max_escalations=5)
        s = State.empty().with_updates(non_interactive=True, user_max_iterations=1,
                                       max_escalations=5)
        out = GraphExecutor(runner=Runner()).execute(root, s)

        assert out.halt_reason is not None
        assert out.halt_reason["kind"] == "corrective_exhausted"
        assert out.halt_reason["stage"] == "verify"
        assert out.halt_reason["message"], "message must not be empty"

    def test_halt_reason_corrective_exhausted_uses_last_error_message(self):
        """When last_error is set at the point of __halt__, halt_reason.message
        must surface it (not the generic 'quota exhausted' fallback text)."""
        from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
        log = []

        class _ExhaustedWithErrorStage(Stage):
            name = "verify"
            default_max_iterations = 1
            def input_contract(self): return StageIOContract()
            def output_contract(self): return StageIOContract()
            def actions(self, state, iteration=1): return []
            def transition(self, state, result):
                log.append(self.name)
                return state.with_updates(
                    last_error=ErrorFeedback(
                        stage_name=self.name,
                        error_type="precision_mismatch",
                        message="rel error 0.05 exceeds threshold 0.01"))
            def resolve_condition(self, state):
                return "exhausted"

        root = SequentialGroup(
            name="pipeline",
            children=[AtomicStage(_ExhaustedWithErrorStage())],
            transition_table={
                "verify": {"exhausted": ("__halt__", "escalation")}},
            max_escalations=5)
        s = State.empty().with_updates(non_interactive=True, user_max_iterations=1,
                                       max_escalations=5)
        out = GraphExecutor(runner=Runner()).execute(root, s)

        assert out.halt_reason["kind"] == "corrective_exhausted"
        assert out.halt_reason["message"] == "rel error 0.05 exceeds threshold 0.01"

    def test_halt_reason_upstream_defect_prefers_debug_result_halt_reason(self):
        """P3 (precision-tensorlist-harness-contract): when a scope_guard
        upstream halt materializes debug_result.halt_reason AND a coincidental
        last_error exists (e.g. a run_tests transition TypeError), the __halt__
        message must surface the SEMANTIC reason (upstream scope_reason) — not
        the last_error — and kind becomes 'upstream_defect'."""
        from ascendc_devkit.domain.verification import PrecisionDebugResult
        from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
        log = []

        class _UpstreamStage(Stage):
            name = "precision_debug"
            default_max_iterations = 1
            def input_contract(self): return StageIOContract()
            def output_contract(self): return StageIOContract()
            def actions(self, state, iteration=1): return []
            def transition(self, state, result):
                log.append(self.name)
                return state.with_updates(
                    last_error=ErrorFeedback(
                        stage_name=self.name, error_type="uncaught",
                        message="'>' not supported between instances of "
                                "'NoneType' and 'NoneType'"),
                    debug_result=PrecisionDebugResult(
                        passed=False, stubbed=True,
                        halt_reason="run-cases aborted at PD-CONTRACT "
                                    "(shape must be list[int])"))
            def resolve_condition(self, state):
                return "upstream"

        root = SequentialGroup(
            name="pipeline",
            children=[AtomicStage(_UpstreamStage())],
            transition_table={
                "precision_debug": {"upstream": ("__halt__", "escalation")}},
            max_escalations=5)
        s = State.empty().with_updates(non_interactive=True,
                                       user_max_iterations=1, max_escalations=5)
        out = GraphExecutor(runner=Runner()).execute(root, s)

        assert out.halt_reason["kind"] == "upstream_defect"
        assert out.halt_reason["stage"] == "precision_debug"
        assert "PD-CONTRACT" in out.halt_reason["message"]
        assert "not supported between" not in out.halt_reason["message"], (
            "upstream halt message must not surface the coincidental last_error")

    def test_halt_reason_upstream_condition_without_debug_result(self):
        """M3 (PR-42): upstream is judged by the routing condition, not by
        debug_result.halt_reason — a halt reached before debug_result
        materializes (e.g. a transition crash) must still classify
        upstream_defect, not fall back to corrective_exhausted."""
        from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
        log = []

        class _UpstreamNoDebugResultStage(Stage):
            name = "precision_debug"
            default_max_iterations = 1
            def input_contract(self): return StageIOContract()
            def output_contract(self): return StageIOContract()
            def actions(self, state, iteration=1): return []
            def transition(self, state, result):
                log.append(self.name)
                return state.with_updates(
                    last_error=ErrorFeedback(
                        stage_name=self.name, error_type="uncaught",
                        message="transition crashed before scope_guard ran"))
                # NOTE: no debug_result set — halt_reason never materialized
            def resolve_condition(self, state):
                return "upstream"

        root = SequentialGroup(
            name="pipeline",
            children=[AtomicStage(_UpstreamNoDebugResultStage())],
            transition_table={
                "precision_debug": {"upstream": ("__halt__", "escalation")}},
            max_escalations=5)
        s = State.empty().with_updates(non_interactive=True,
                                       user_max_iterations=1, max_escalations=5)
        out = GraphExecutor(runner=Runner()).execute(root, s)

        assert out.halt_reason["kind"] == "upstream_defect"
        assert out.halt_reason["stage"] == "precision_debug"


class TestDesignRequirementRouting:
    """Task 3.4/3.5: design routes back to requirement on an incomplete
    requirement (corrective loop-back) instead of halting via a precondition
    gate. Mirrors the real generate_ascendc transition table edge.
    """

    def test_design_loops_back_to_requirement_then_proceeds(self):
        # requirement "clarifies" on the 2nd pass; design reports
        # requirement_incomplete the 1st time it runs, then default.
        log = []
        requirement = _RecordStage("requirement", log)
        design = _CondStage("design", "requirement_incomplete",
                            fail_times=1, log=log)
        root = SequentialGroup(
            name="pipeline",
            children=[AtomicStage(requirement), AtomicStage(design)],
            transition_table={
                "design": {"requirement_incomplete": ("requirement", "corrective")}},
            max_corrective=5)
        s = State.empty().with_updates(non_interactive=True, user_max_iterations=1,
                                       max_corrective=5)
        out = GraphExecutor(runner=Runner()).execute(root, s)
        # design loops back once → requirement runs twice, design runs twice,
        # then proceeds (no halt / PreconditionError).
        assert log.count("requirement") == 2
        assert log.count("design") == 2
        assert out.routing_scopes["pipeline"]["corrective"] == 1
        assert out.node_status.get("pipeline") == "completed"


class TestFailStrategyHalt:
    """P2+P3: fail_strategy=halt → _stage_failed signal breaks sequential pipeline."""

    def test_halt_signal_breaks_pipeline_and_skips_downstream(self):
        """When a stage sets _stage_failed, graph_executor breaks the loop and
        downstream stages are NOT executed."""
        from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
        log = []

        class _HaltTriggerStage(Stage):
            """Writes _stage_failed to state and appends itself to log."""
            name = "fail-step"
            default_max_iterations = 1
            def input_contract(self): return StageIOContract()
            def output_contract(self): return StageIOContract()
            def actions(self, state, iteration=1): return []
            def transition(self, state, result):
                log.append(self.name)
                return state.with_updates(
                    _stage_failed=("failed", self.name))

        # A normal stage that should NOT run after halt
        class _NotRunStage(Stage):
            name = "should-not-run"
            default_max_iterations = 1
            def input_contract(self): return StageIOContract()
            def output_contract(self): return StageIOContract()
            def actions(self, state, iteration=1): return []
            def transition(self, state, result):
                log.append(self.name)
                return state

        root = SequentialGroup(
            name="pipeline",
            children=[
                AtomicStage(_HaltTriggerStage()),
                AtomicStage(_NotRunStage()),
            ])
        s = State.empty().with_updates(non_interactive=True, user_max_iterations=1)
        out = GraphExecutor(runner=Runner()).execute(root, s)

        # fail-step ran but should-not-run was skipped
        assert "fail-step" in log
        assert "should-not-run" not in log
        # Pipeline is terminal
        assert out.is_terminal is True
        # _stage_failed signal consumed (cleared)
        assert getattr(out, "_stage_failed", None) is None

    def test_halt_signal_only_breaks_if_set(self):
        """A stage without _stage_failed does NOT break the pipeline."""
        log = []

        class _CleanStage1(Stage):
            name = "clean-1"
            default_max_iterations = 1
            def input_contract(self): return StageIOContract()
            def output_contract(self): return StageIOContract()
            def actions(self, state, iteration=1): return []
            def transition(self, state, result):
                log.append(self.name)
                return state

        class _CleanStage2(Stage):
            name = "clean-2"
            default_max_iterations = 1
            def input_contract(self): return StageIOContract()
            def output_contract(self): return StageIOContract()
            def actions(self, state, iteration=1): return []
            def transition(self, state, result):
                log.append(self.name)
                return state

        root = SequentialGroup(
            name="pipeline",
            children=[
                AtomicStage(_CleanStage1()),
                AtomicStage(_CleanStage2()),
            ])
        s = State.empty().with_updates(non_interactive=True, user_max_iterations=1)
        out = GraphExecutor(runner=Runner()).execute(root, s)

        # Both stages ran
        assert "clean-1" in log
        assert "clean-2" in log
        # Not terminal
        assert out.is_terminal is False

    def test_hard_crash_on_halt_stage_stops_pipeline(self):
        """A fail_strategy=halt stage that RAISES (hard crash — e.g. actions()
        KeyError before any agent spawns) must still halt the pipeline, not be
        swallowed by _execute_atomic's 'advance linearly' except-branch into
        running downstream stages on broken state until workflow timeout. The
        hard-crash path must set _stage_failed just like the soft-failure path
        (runner halt check) does (P46)."""
        log = []

        class _CrashHaltStage(Stage):
            name = "crash-halt"
            fail_strategy = "halt"
            default_max_iterations = 1
            def input_contract(self): return StageIOContract()
            def output_contract(self): return StageIOContract()
            def actions(self, state, iteration=1):
                raise RuntimeError("boom")
            def transition(self, state, result):
                return state

        class _NotRunStage(Stage):
            name = "should-not-run"
            default_max_iterations = 1
            def input_contract(self): return StageIOContract()
            def output_contract(self): return StageIOContract()
            def actions(self, state, iteration=1): return []
            def transition(self, state, result):
                log.append(self.name)
                return state

        root = SequentialGroup(
            name="pipeline",
            children=[
                AtomicStage(_CrashHaltStage()),
                AtomicStage(_NotRunStage()),
            ])
        s = State.empty().with_updates(non_interactive=True, user_max_iterations=1)
        out = GraphExecutor(runner=Runner()).execute(root, s)

        # downstream must NOT run after a halt-stage hard crash
        assert "should-not-run" not in log
        # pipeline is terminal (halt honoured despite the crash)
        assert out.is_terminal is True

    def test_halt_in_nested_sequential_group_breaks_parent(self):
        """When a child in a nested SequentialGroup sets _stage_failed, the parent
        group's _execute_sequential also breaks, skipping its downstream siblings."""
        log = []

        class _HaltChildStage(Stage):
            name = "halt-child"
            default_max_iterations = 1
            def input_contract(self): return StageIOContract()
            def output_contract(self): return StageIOContract()
            def actions(self, state, iteration=1): return []
            def transition(self, state, result):
                log.append(self.name)
                return state.with_updates(
                    _stage_failed=("failed", self.name))

        class _AfterHaltStage(Stage):
            name = "after-halt"
            default_max_iterations = 1
            def input_contract(self): return StageIOContract()
            def output_contract(self): return StageIOContract()
            def actions(self, state, iteration=1): return []
            def transition(self, state, result):
                log.append(self.name)
                return state

        inner = SequentialGroup(
            name="inner",
            children=[
                AtomicStage(_HaltChildStage()),
                AtomicStage(_AfterHaltStage()),
            ])

        root = SequentialGroup(
            name="outer",
            children=[inner])

        s = State.empty().with_updates(non_interactive=True, user_max_iterations=1)
        out = GraphExecutor(runner=Runner()).execute(root, s)

        assert "halt-child" in log
        assert "after-halt" not in log
        assert out.is_terminal is True

    def test_halt_triggers_is_terminal(self):
        """The halt path must set is_terminal so the dispatcher reports correctly."""
        from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
        log = []

        class _HaltStage(Stage):
            name = "halter"
            default_max_iterations = 1
            def input_contract(self): return StageIOContract()
            def output_contract(self): return StageIOContract()
            def actions(self, state, iteration=1): return []
            def transition(self, state, result):
                log.append(self.name)
                return state.with_updates(
                    _stage_failed=("partial", self.name))

        root = SequentialGroup(
            name="pipeline",
            children=[AtomicStage(_HaltStage())])
        s = State.empty().with_updates(non_interactive=True, user_max_iterations=1)
        out = GraphExecutor(runner=Runner()).execute(root, s)

        assert "halter" in log
        assert out.is_terminal is True

    def test_halt_reason_names_fail_strategy_halt_kind_stage_message(self):
        """design-halt-diagnostics P3: fail_strategy=halt must record
        halt_reason with kind='fail_strategy_halt', the failing stage's name,
        and the last_error message — so the dispatcher can name the real
        cause instead of a single hardcoded generic text."""
        from ascendc_devkit.orchestration.kernel.state import ErrorFeedback

        class _HaltWithErrorStage(Stage):
            name = "fail-step"
            default_max_iterations = 1
            def input_contract(self): return StageIOContract()
            def output_contract(self): return StageIOContract()
            def actions(self, state, iteration=1): return []
            def transition(self, state, result):
                return state.with_updates(
                    _stage_failed=("failed", self.name),
                    last_error=ErrorFeedback(
                        stage_name=self.name,
                        error_type="missing_artifact",
                        message="missing tiling_buffer_kernel.json"))

        root = SequentialGroup(
            name="pipeline",
            children=[AtomicStage(_HaltWithErrorStage())])
        s = State.empty().with_updates(non_interactive=True, user_max_iterations=1)
        out = GraphExecutor(runner=Runner()).execute(root, s)

        assert out.halt_reason == {
            "kind": "fail_strategy_halt",
            "stage": "fail-step",
            "message": "missing tiling_buffer_kernel.json",
        }

    def test_halt_reason_fail_strategy_halt_message_empty_without_last_error(self):
        """When no last_error is present, halt_reason.message is empty (not a
        crash) but kind/stage are still recorded."""
        class _HaltNoErrorStage(Stage):
            name = "fail-step"
            default_max_iterations = 1
            def input_contract(self): return StageIOContract()
            def output_contract(self): return StageIOContract()
            def actions(self, state, iteration=1): return []
            def transition(self, state, result):
                return state.with_updates(
                    _stage_failed=("failed", self.name))

        root = SequentialGroup(
            name="pipeline",
            children=[AtomicStage(_HaltNoErrorStage())])
        s = State.empty().with_updates(non_interactive=True, user_max_iterations=1)
        out = GraphExecutor(runner=Runner()).execute(root, s)

        assert out.halt_reason == {
            "kind": "fail_strategy_halt", "stage": "fail-step", "message": ""}


# —— P6-e: halt surfaces last_error reason ——

class TestHaltSurfacesErrorReason:
    """P6-e fix 1: halt log includes last_error.message so the operator can
    triage without opening events.jsonl."""

    def test_halt_log_includes_last_error_message(self):
        from unittest import mock
        from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
        log_entries = []

        class _HaltWithErrorStage(Stage):
            name = "fail-step"
            default_max_iterations = 1
            def input_contract(self): return StageIOContract()
            def output_contract(self): return StageIOContract()
            def actions(self, state, iteration=1): return []
            def transition(self, state, result):
                return state.with_updates(
                    _stage_failed=("failed", self.name),
                    last_error=ErrorFeedback(
                        stage_name=self.name,
                        error_type="missing_artifact",
                        message="missing tiling_buffer_kernel.json"))

        init = _RecordStage("init", [])
        root = SequentialGroup(
            name="pipeline",
            children=[
                AtomicStage(init),
                AtomicStage(_HaltWithErrorStage()),
            ])
        s = State.empty().with_updates(non_interactive=True, user_max_iterations=1)
        with mock.patch(
            "ascendc_devkit.infra.logger.Logger.warn") as m:
            GraphExecutor(runner=Runner()).execute(root, s)
        # The warn message must include the last_error.message
        halt_msgs = [c.args[0] for c in m.call_args_list
                    if c.args and "fail_strategy=halt" in str(c.args[0])]
        assert len(halt_msgs) >= 1
        assert any("missing tiling_buffer_kernel.json" in msg for msg in halt_msgs), (
            f"halt message must include last_error.message, got: {halt_msgs}")

    def test_halt_without_last_error_still_works(self):
        """P6-e: when no last_error, halt still logs without reason (no crash)."""
        from unittest import mock
        log = []

        class _HaltNoErrorStage(Stage):
            name = "fail-step"
            default_max_iterations = 1
            def input_contract(self): return StageIOContract()
            def output_contract(self): return StageIOContract()
            def actions(self, state, iteration=1): return []
            def transition(self, state, result):
                log.append(self.name)
                return state.with_updates(
                    _stage_failed=("failed", self.name))

        root = SequentialGroup(
            name="pipeline",
            children=[AtomicStage(_HaltNoErrorStage())])
        s = State.empty().with_updates(non_interactive=True, user_max_iterations=1)
        with mock.patch(
            "ascendc_devkit.infra.logger.Logger.warn") as m:
            out = GraphExecutor(runner=Runner()).execute(root, s)
        assert out.is_terminal is True
        halt_msgs = [c.args[0] for c in m.call_args_list
                    if c.args and "fail_strategy=halt" in str(c.args[0])]
        assert len(halt_msgs) >= 1, "halt should still be logged even without last_error"


# —— P6-e fix 3: loopback passed summary ——

class TestLoopbackPassedSummary:
    """P6-e fix 3: when a gate stage finally passes after corrective retries,
    a summary line is logged so the operator sees the rescue chain completed."""

    def test_gate_passed_after_loopbacks_logs_summary(self):
        from unittest import mock
        from ascendc_devkit.orchestration.node import AtomicStage, SequentialGroup
        from ascendc_devkit.orchestration.kernel.runner import Runner

        call_count = 0

        class _Gate(Stage):
            """Fails once (routes corrective), then passes on second execution."""
            name = "gate"
            default_max_iterations = 1
            def input_contract(self): return StageIOContract()
            def output_contract(self): return StageIOContract()
            def actions(self, state, iteration=1): return []
            def resolve_condition(self, state):
                nonlocal call_count
                call_count += 1
                return "bad" if call_count <= 1 else "default"
            def is_satisfied(self, state):
                nonlocal call_count
                return call_count >= 2  # only satisfied after loopback

        class _Producer(Stage):
            name = "producer"
            default_max_iterations = 1
            def input_contract(self): return StageIOContract()
            def output_contract(self): return StageIOContract()
            def actions(self, state, iteration=1): return []

        group = SequentialGroup(
            name="g",
            children=[AtomicStage(_Producer()), AtomicStage(_Gate())],
            transition_table={"gate": {"bad": ("producer", "corrective")}},
            max_corrective=5, max_escalations=0)
        root = SequentialGroup(name="pipeline", children=[group])

        with mock.patch(
            "ascendc_devkit.infra.logger.Logger.action") as m:
            GraphExecutor(runner=Runner()).execute(
                root, State.empty().with_updates(
                    non_interactive=True, user_max_iterations=1,
                    max_corrective=5))

        passed_msgs = [c.args for c in m.call_args_list
                      if c.args and c.args[0] == "loopback"
                      and "passed after" in str(c.args[1])]
        assert len(passed_msgs) >= 1, (
            "gate passing after corrective retries must log a summary, "
            f"got loopback messages: {[c.args for c in m.call_args_list if c.args and c.args[0]=='loopback']}")


# --- P29 / step-16: per-node state-progress flush (hard-kill resume) -------
# GraphExecutor fires on_state_progress after each node completion so the state
# snapshot reflects the latest completed frontier. A hard-killed run then resumes
# from that frontier instead of restarting from the top (node_status is the sole
# resume authority; making it durable per-node is the fix — see L3 19-*.md).
from ascendc_devkit.application.dispatcher import _write_state_snapshot
from ascendc_devkit.infra.workspace import Workspace
from ascendc_devkit.orchestration.node_forkjoin import ForkJoinGroup


class _KillStage(Stage):
    """Raises a control exception on first transition (simulates a hard kill
    mid-stage), one-shot via a mutable flag so a resume re-run proceeds."""
    default_max_iterations = 1
    def __init__(self, name, log, kill):
        self._name = name; self._log = log; self._kill = kill  # [bool] mutable
    @property
    def name(self): return self._name
    def input_contract(self): return StageIOContract()
    def output_contract(self): return StageIOContract()
    def actions(self, state, iteration=1): return []
    def transition(self, state, result):
        if self._kill and self._kill[0]:
            self._kill[0] = False  # one-shot: resume re-run won't raise
            raise KeyboardInterrupt
        self._log.append(self._name)
        return state


class TestStateProgressFlush:
    """on_state_progress fires once per completed node, monotonically growing
    node_status — never for resume-skipped / no-op nodes."""

    def test_on_state_progress_called_per_node(self):
        records = []
        log = []
        root = SequentialGroup(name="pipeline", children=[
            AtomicStage(_RecordStage("a", log)),
            AtomicStage(_RecordStage("b", log)),
            AtomicStage(_RecordStage("c", log))])
        s = State.empty().with_updates(non_interactive=True, user_max_iterations=1)
        ex = GraphExecutor(runner=Runner(),
                           on_state_progress=lambda st: records.append(dict(st.node_status)))
        ex.execute(root, s)
        # 3 leaves + the group node itself = 4 completions → 4 flushes.
        assert len(records) == 4
        assert records[0] == {"pipeline/a": "completed"}
        assert records[1]["pipeline/b"] == "completed"
        assert records[2]["pipeline/c"] == "completed"
        assert records[-1]["pipeline"] == "completed"   # group folded into last flush

    def test_on_state_progress_skipped_for_resume_skip(self):
        records = []
        log = []
        root = SequentialGroup(name="pipeline", children=[
            AtomicStage(_RecordStage("a", log)),
            AtomicStage(_RecordStage("b", log))])
        # a pre-completed → resume-skip must NOT generate a flush for a.
        s = State.empty().with_updates(
            non_interactive=True, user_max_iterations=1,
            node_status={"pipeline/a": "completed"})
        ex = GraphExecutor(runner=Runner(),
                           on_state_progress=lambda st: records.append(dict(st.node_status)))
        ex.execute(root, s)
        # b + group flush only (a skipped); every record carries the preseeded a.
        assert len(records) == 2
        for r in records:
            assert r["pipeline/a"] == "completed"   # preseeded, never re-flushed
        assert records[0] == {"pipeline/a": "completed", "pipeline/b": "completed"}
        assert records[1]["pipeline"] == "completed"

    def test_forkjoin_flushes_only_merged_once(self):
        # Branches run in branch_exec (callback=None); only the main executor
        # flushes after merge → exactly one flush for the whole fork-join.
        records = []
        log = []
        root = ForkJoinGroup(name="suite", children=[
            AtomicStage(_RecordStage("a", log)),
            AtomicStage(_RecordStage("b", log))])
        s = State.empty().with_updates(non_interactive=True, user_max_iterations=1)
        ex = GraphExecutor(runner=Runner(),
                           on_state_progress=lambda st: records.append(dict(st.node_status)))
        ex.execute(root, s)
        assert len(records) == 1
        assert records[0]["suite/a"] == "completed"
        assert records[0]["suite/b"] == "completed"
        assert records[0]["suite"] == "completed"

    def test_persist_failure_is_non_fatal(self, capfd):
        # A persist hiccup must not kill the run (best-effort flush, §1.2).
        log = []
        root = SequentialGroup(name="pipeline", children=[
            AtomicStage(_RecordStage("a", log))])
        s = State.empty().with_updates(non_interactive=True, user_max_iterations=1)

        def boom(_st):
            raise OSError("disk full")
        out = GraphExecutor(runner=Runner(), on_state_progress=boom).execute(root, s)
        assert out.node_status["pipeline/a"] == "completed"   # run still completed
        assert log == ["a"]


class TestResumeAfterKill:
    """The headline invariant: a per-node-flushed snapshot lets a hard-killed
    run resume past completed nodes."""

    def test_kill_then_resume_skips_completed(self, tmp_path):
        # First run: a completes + flushes snapshot; b is "killed" mid-stage.
        kill = [True]
        log1 = []
        root = SequentialGroup(name="pipeline", children=[
            AtomicStage(_RecordStage("a", log1)),
            AtomicStage(_KillStage("b", log1, kill)),
            AtomicStage(_RecordStage("c", log1))])
        ws = Workspace.create(output_root=str(tmp_path))
        s0 = State.empty().with_updates(non_interactive=True, user_max_iterations=1)
        ex = GraphExecutor(
            runner=Runner(),
            on_state_progress=lambda st: _write_state_snapshot(ws, st))
        try:
            ex.execute(root, s0)
            raise AssertionError("expected KeyboardInterrupt from _KillStage")
        except KeyboardInterrupt:
            pass
        assert log1 == ["a"]                       # a ran, b was killed before logging

        # Resume: reload node_status from the on-disk snapshot, re-execute.
        import json
        snap = json.loads(ws.state_snapshot_path.read_text())
        assert snap["node_status"] == {"pipeline/a": "completed"}

        log2 = []
        root2 = SequentialGroup(name="pipeline", children=[
            AtomicStage(_RecordStage("a", log2)),
            AtomicStage(_KillStage("b", log2, kill)),
            AtomicStage(_RecordStage("c", log2))])
        s1 = State.empty().with_updates(
            non_interactive=True, user_max_iterations=1,
            node_status=dict(snap["node_status"]))
        GraphExecutor(runner=Runner()).execute(root2, s1)
        assert log2 == ["b", "c"]                  # a skipped on resume

    def test_latest_state_current_after_interrupt(self):
        # Ctrl+C (KeyboardInterrupt) mid-run: the dispatcher writes
        # executor.latest_state to the snapshot. latest_state must reflect the
        # last COMPLETED node (with its marker) — else the Ctrl+C snapshot
        # overwrites the per-node flush and resume re-runs that node.
        kill = [True]
        log = []
        root = SequentialGroup(name="pipeline", children=[
            AtomicStage(_RecordStage("a", log)),
            AtomicStage(_KillStage("b", log, kill))])
        s = State.empty().with_updates(non_interactive=True, user_max_iterations=1)
        ex = GraphExecutor(runner=Runner(),
                           on_state_progress=lambda st: None)
        try:
            ex.execute(root, s)
            raise AssertionError("expected KeyboardInterrupt from _KillStage")
        except KeyboardInterrupt:
            pass
        # a completed before b was interrupted → latest_state must carry a.
        assert ex.latest_state.node_status.get("pipeline/a") == "completed"

    def test_write_state_snapshot_is_atomic(self, tmp_path):
        # Atomic write (temp + os.replace): no truncated half-JSON, no .tmp
        # leftover. POSIX rename atomicity guarantees crash-safety (old or new,
        # never empty) — asserted here at the observable contract level.
        ws = Workspace.create(output_root=str(tmp_path))
        s = State.empty().with_updates(
            non_interactive=True,
            node_status={"pipeline/a": "completed", "pipeline": "completed"})
        _write_state_snapshot(ws, s)

        import json
        path = ws.state_snapshot_path
        assert path.exists()
        data = json.loads(path.read_text())        # valid, non-truncated JSON
        assert data["node_status"] == {"pipeline/a": "completed", "pipeline": "completed"}
        assert list(path.parent.glob("*.tmp")) == []   # no leftover temp


class _HaltFailStage(Stage):
    """fail_strategy='halt' whose agent goes fatal → runner sets _stage_failed
    without raising (P35 fixture)."""
    name = "halt-stage"
    fail_strategy = "halt"
    default_max_iterations = 1
    def input_contract(self): return StageIOContract(requires=[])
    def output_contract(self): return StageIOContract(provides=[])
    def actions(self, state, iteration=1):
        from ascendc_devkit.orchestration.kernel.action import SpawnAgent
        return [SpawnAgent(agent_name="x", prompt="p", context={})]


class TestHaltMarksNodeFailed:
    """P35: fail_strategy='halt' 的 stage 必须标 node_status='failed'(非
    'completed')。

    halt 不抛异常、只设 _stage_failed 信号(runner.py);原 _execute_atomic
    无脑标 completed → _group_status 看不到 failed 子节点 → 根被标 completed
    → dispatcher resume 误判 all_done、静默跳过未跑的下游 stage。实例:run
    20260705-072625-72f58b 在 design stage halt 后 snapshot 全 completed,resume
    输出 'All stages already completed' 退出,但 codegen/verify 根本没跑。"""

    def _fatal_executor(self):
        from ascendc_devkit.capabilities.agent.backend import (
            AgentBackend, AgentResult)
        class FatalBackend(AgentBackend):
            def spawn(self, agent_name, prompt, context, skills=None,
                      model=None, working_dir=None, repo_baseline=None,
                      repo_root=None, stage_name="", branch_label="", resume_session_id=None, resume_prompt=None, primary_skill=None, deadline_monotonic: float | None = None):
                return AgentResult(agent_name="x", status="fatal")
        return GraphExecutor(runner=Runner(agent_backend=FatalBackend()))

    def test_halt_atomic_node_marked_failed(self):
        root = SequentialGroup(name="pipeline", children=[
            AtomicStage(_HaltFailStage())])
        s = State.empty().with_updates(non_interactive=True, user_max_iterations=1)
        out = self._fatal_executor().execute(root, s)
        assert out.node_status.get("pipeline/halt-stage") == "failed", (
            "halt 的 stage 必须标 'failed'(P35):否则 resume 误判 all_done、"
            "静默跳过未跑的下游 stage")
        assert out.node_status.get("pipeline") == "failed", (
            "halt 必须经 _group_status 传播到根,根保持非 completed")

    def test_halt_in_nested_group_propagates_to_root(self):
        """对应实际场景 self_evolve_op/test_design stage halt:
        嵌套 group 里的 atomic halt → 子 group failed → 根 failed。"""
        root = SequentialGroup(name="self_evolve_op", children=[
            SequentialGroup(name="test_design",
                            children=[AtomicStage(_HaltFailStage())]),
        ])
        s = State.empty().with_updates(non_interactive=True, user_max_iterations=1)
        out = self._fatal_executor().execute(root, s)
        assert out.node_status.get(
            "self_evolve_op/test_design/halt-stage") == "failed"
        assert out.node_status.get("self_evolve_op/test_design") == "failed"
        assert out.node_status.get("self_evolve_op") == "failed", (
            "根必须非 completed,dispatcher resume 才不会误判 all_done")


class TestResumeRetriesAfterHalt:
    """P39: resume after a halt-terminated run must RE-RUN the failed stage,
    not silently exit (0.0s) and re-report the halt.

    Root cause: halt sets is_terminal=True — a TRANSIENT per-pass signal
    (state.py L203-204) — which leaked into state_snapshot.json. On resume,
    ``_execute_sequential`` (graph_executor.py:201) broke immediately on the
    persisted flag, before re-running the failed leaf. The fix strips
    is_terminal / _stage_failed / _bubble_condition at the snapshot boundary, so
    node_status — the durable resume authority — alone drives the re-run: a
    "failed" leaf is not "completed", so ``_execute_node:75`` does not skip it.

    Real instance: run 20260706-153520-e8f653 halted on general-design-generator
    (quota 401), then ``RESUME=...`` logged 'workflow done (0.0s)' + the same
    halt message — the failed stage was never retried.
    """

    def test_resume_after_halt_reruns_failed_leaf(self):
        # Snapshot exactly as the buggy build persisted it: the halt leaf is
        # "failed", the root is "failed" (propagated via _group_status), AND
        # is_terminal=True leaked in. stage_iterations reflects the prior run.
        snap = {
            "run_id": "r1",
            "workflow_name": "pipeline",
            "non_interactive": True,
            "user_max_iterations": 1,
            "is_terminal": True,
            "node_status": {
                "pipeline/fail-step": "failed",
                "pipeline": "failed",
            },
            "stage_iterations": {"pipeline/fail-step": 5},
        }
        s = State.from_snapshot(snap)
        # Transient flag must be gone after load (also asserted by UT A; repeated
        # here so a from_snapshot regression fails this test for the right reason).
        assert s.is_terminal is False

        # Resume tree: same shape, but the previously-halting stage now runs
        # cleanly — the operator resolved whatever caused the halt.
        log = []

        class _NowCleanStage(Stage):
            name = "fail-step"
            default_max_iterations = 1
            def input_contract(self): return StageIOContract()
            def output_contract(self): return StageIOContract()
            def actions(self, state, iteration=1): return []
            def transition(self, state, result):
                log.append(self.name)
                return state

        class _DownstreamStage(Stage):
            name = "after"
            default_max_iterations = 1
            def input_contract(self): return StageIOContract()
            def output_contract(self): return StageIOContract()
            def actions(self, state, iteration=1): return []
            def transition(self, state, result):
                log.append(self.name)
                return state

        root = SequentialGroup(name="pipeline", children=[
            AtomicStage(_NowCleanStage()),
            AtomicStage(_DownstreamStage()),
        ])
        out = GraphExecutor(runner=Runner()).execute(root, s)

        # The previously-failed leaf was RE-RUN (not resume-skipped) + succeeded.
        assert "fail-step" in log, "halted leaf must be retried on resume"
        assert out.node_status.get("pipeline/fail-step") == "completed"
        # Downstream proceeded — proves the pass did not abort at :201.
        assert "after" in log
        assert out.node_status.get("pipeline") == "completed"
        # The resume pass completed normally; no stale terminal flag.
        assert out.is_terminal is False


# —— precision_debug converge 双通道（改动2 escalation + except 通道）——————————


class TestEscalationConverge:
    """改动2: precision_debug 组经 escalation 退出（abort_exhausted / exhausted /
    deploy_broken / passed）→ 接入 ``_converge_to_best_commit``，与 except 通道收敛
    语义一致（cannbench_eval 读 deploy_result 不读源码，故通道①也须 rollback+redeploy）。
    ``upstream`` 排除（无 best_commit 可收敛，与 _sync_debug_result 的 is_upstream 一致）；
    ``passed`` 由 converge 内 status=='passed' 短路（接入安全）。"""

    @staticmethod
    def _pd_group(cond):
        """precision_debug SequentialGroup; child 'rt' resolves ``cond`` once,
        routed to ``__escalate__:<cond>``."""
        child = _CondStage("rt", cond, fail_times=99, log=[])
        return SequentialGroup(
            name="precision_debug",
            children=[AtomicStage(child)],
            transition_table={"rt": {cond: ("__escalate__:" + cond, "escalation")}},
            max_escalations=5)

    @staticmethod
    def _spy(monkeypatch):
        calls = []

        def _spy_fn(state, dc):
            calls.append(dc)
            return state

        monkeypatch.setattr(
            "ascendc_devkit.orchestration.stages.precision_debug_substages"
            "._converge_to_best_commit", _spy_fn)
        return calls

    @staticmethod
    def _state():
        return State.empty().with_updates(
            non_interactive=True, user_max_iterations=1, max_escalations=5)

    def test_abort_exhausted_converges_and_bubbles(self, monkeypatch):
        calls = self._spy(monkeypatch)
        out = GraphExecutor(runner=Runner()).execute(
            self._pd_group("abort_exhausted"), self._state())
        assert len(calls) == 1
        assert out._bubble_condition == "abort_exhausted"

    def test_exhausted_converges(self, monkeypatch):
        calls = self._spy(monkeypatch)
        GraphExecutor(runner=Runner()).execute(
            self._pd_group("exhausted"), self._state())
        assert len(calls) == 1

    def test_deploy_broken_converges(self, monkeypatch):
        calls = self._spy(monkeypatch)
        GraphExecutor(runner=Runner()).execute(
            self._pd_group("deploy_broken"), self._state())
        assert len(calls) == 1

    def test_upstream_skips_converge_but_bubbles(self, monkeypatch):
        calls = self._spy(monkeypatch)
        out = GraphExecutor(runner=Runner()).execute(
            self._pd_group("upstream"), self._state())
        assert calls == []                           # upstream 不收敛
        assert out._bubble_condition == "upstream"   # 但仍 bubble 给父级路由

    def test_passed_converge_is_safe_via_internal_short_circuit(self, monkeypatch):
        """§step-91 P5: GE 升级分支按业务语义标记 _converged_this_pass 跳重复收敛
        （transition 终态已收敛；ccad38 实证背靠背双收敛空烧）。此处 state 未设标记
        （孤立调用场景），GE 兜底收敛发生——标记与旧条件名短路等价。收敛函数对 passed
        的语义由 _converge_to_best_commit 的独立测试守护。"""
        calls = self._spy(monkeypatch)
        out = GraphExecutor(runner=Runner()).execute(
            self._pd_group("passed"), self._state())
        assert len(calls) == 1      # 未声明已收敛 → GE 兜底收敛（语义不变）
        assert out._bubble_condition == "passed"

    def test_a5_exhausted_uses_a5_converge_not_a3(self, monkeypatch):
        a5_calls = []
        a3_calls = []
        monkeypatch.setattr(
            "ascendc_devkit.orchestration.stages.precision_debug_a5"
            "._converge_a5_to_best_commit",
            lambda state: a5_calls.append(1) or state)
        monkeypatch.setattr(
            "ascendc_devkit.orchestration.stages.precision_debug_substages"
            "._converge_to_best_commit",
            lambda state, dc: a3_calls.append(1) or state)

        group = self._pd_group("exhausted")
        group.variant = "a5"
        out = GraphExecutor(runner=Runner()).execute(group, self._state())

        assert a5_calls == [1]
        assert a3_calls == []
        assert out._bubble_condition == "exhausted"


class TestExceptConverge:
    """precision_debug 组内 child 抛 (StageTimeoutError|WorkflowTimeoutError) →
    except 通道 converge 到 best_commit + bubble='exhausted'（既有零覆盖，顺带补）。
    非 precision_debug 组 → raise（硬退出，不收敛）。"""

    @staticmethod
    def _timeout_child():
        from ascendc_devkit.domain.exceptions import WorkflowTimeoutError

        class _TimeoutStage(Stage):
            default_max_iterations = 1
            @property
            def name(self): return "rt"
            def input_contract(self): return StageIOContract()
            def output_contract(self): return StageIOContract()
            def actions(self, state, iteration=1): return []
            def transition(self, state, result):
                raise WorkflowTimeoutError("workflow deadline exceeded")

        return _TimeoutStage()

    def test_pd_timeout_converges_and_bubbles_exhausted(self, monkeypatch):
        calls = []

        def _spy(state, dc):
            calls.append(dc)
            return state

        monkeypatch.setattr(
            "ascendc_devkit.orchestration.stages.precision_debug_substages"
            "._converge_to_best_commit", _spy)
        root = SequentialGroup(
            name="precision_debug", children=[AtomicStage(self._timeout_child())])
        s = State.empty().with_updates(non_interactive=True, user_max_iterations=1)
        out = GraphExecutor(runner=Runner()).execute(root, s)
        assert len(calls) == 1
        assert out._bubble_condition == "exhausted"

    def test_a5_timeout_uses_a5_converge(self, monkeypatch):
        a5_calls = []
        a3_calls = []
        monkeypatch.setattr(
            "ascendc_devkit.orchestration.stages.precision_debug_a5"
            "._converge_a5_to_best_commit",
            lambda state: a5_calls.append(1) or state)
        monkeypatch.setattr(
            "ascendc_devkit.orchestration.stages.precision_debug_substages"
            "._converge_to_best_commit",
            lambda state, dc: a3_calls.append(1) or state)
        root = SequentialGroup(
            name="precision_debug",
            children=[AtomicStage(self._timeout_child())],
        )
        root.variant = "a5"
        state = State.empty().with_updates(
            non_interactive=True, user_max_iterations=1)

        out = GraphExecutor(runner=Runner()).execute(root, state)

        assert a5_calls == [1]
        assert a3_calls == []
        assert out._bubble_condition == "exhausted"

    def test_non_pd_timeout_propagates(self, monkeypatch):
        import pytest
        from ascendc_devkit.domain.exceptions import WorkflowTimeoutError
        calls = []
        monkeypatch.setattr(
            "ascendc_devkit.orchestration.stages.precision_debug_substages"
            "._converge_to_best_commit", lambda state, dc: calls.append(1) or state)
        root = SequentialGroup(
            name="codegen", children=[AtomicStage(self._timeout_child())])
        s = State.empty().with_updates(non_interactive=True, user_max_iterations=1)
        with pytest.raises(WorkflowTimeoutError):
            GraphExecutor(runner=Runner()).execute(root, s)
        assert calls == []
