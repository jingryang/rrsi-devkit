"""Phase 2: ForkJoinGroup — parallel children + merge."""

import pytest
from ascendc_devkit.orchestration.node import AtomicStage
from ascendc_devkit.orchestration.base import Stage
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.domain.contract import StageIOContract


def _provider_stage(name, field_name, value):
    return type(f"_P_{name}", (Stage,), {
        "name": name,
        "input_contract": lambda self: StageIOContract(),
        "output_contract": lambda self: StageIOContract(provides=[field_name]),
        "actions": lambda self, state, iteration=1: [],
        "transition": lambda self, state, result: state.with_field(field_name, value),
    })()


def _logging_provider(name, field_name, value, log, tag):
    """Provider that records ``tag`` when its transition runs — lets a resume
    test assert which branches actually re-executed vs were skipped."""
    def _t(self, state, result):
        log.append(tag)
        return state.with_field(field_name, value)
    return type(f"_LP_{tag}", (Stage,), {
        "name": name,
        "input_contract": lambda self: StageIOContract(),
        "output_contract": lambda self: StageIOContract(provides=[field_name]),
        "actions": lambda self, state, iteration=1: [],
        "transition": _t,
    })()


class TestForkJoinNode:
    def test_children_listed(self):
        from ascendc_devkit.orchestration.node_forkjoin import ForkJoinGroup
        g = ForkJoinGroup(name="suite", children=[
            AtomicStage(_provider_stage("a", "build_result", 1))])
        assert [c.name for c in g.children()] == ["a"]


class TestMerge:
    def test_merge_disjoint_fields(self):
        from ascendc_devkit.orchestration.node_forkjoin import ForkJoinGroup, merge_forkjoin
        base = State.empty()
        a = base.with_field("build_result", "BR")
        b = base.with_field("debug_result", "PR")
        children = [AtomicStage(_provider_stage("a", "build_result", "BR")),
                    AtomicStage(_provider_stage("b", "debug_result", "PR"))]
        merged = merge_forkjoin(base, children, [a, b])
        assert merged.build_result == "BR"
        assert merged.debug_result == "PR"

    def test_merge_conflict_raises(self):
        from ascendc_devkit.orchestration.node_forkjoin import (
            ForkJoinGroup, StateConflictError, merge_forkjoin)
        base = State.empty()
        a = base.with_field("build_result", "A")
        b = base.with_field("build_result", "B")
        children = [AtomicStage(_provider_stage("a", "build_result", "A")),
                    AtomicStage(_provider_stage("b", "build_result", "B"))]
        with pytest.raises(StateConflictError):
            merge_forkjoin(base, children, [a, b])


import time
from ascendc_devkit.orchestration.graph_executor import GraphExecutor
from ascendc_devkit.orchestration.kernel.runner import Runner


class _SleepProvider(Stage):
    default_max_iterations = 1
    def __init__(self, name, field_name, sleep_s):
        self._name = name; self._field = field_name; self._sleep = sleep_s
    @property
    def name(self): return self._name
    def input_contract(self): return StageIOContract()
    def output_contract(self): return StageIOContract(provides=[self._field])
    def actions(self, state, iteration=1): return []
    def transition(self, state, result):
        time.sleep(self._sleep)
        return state.with_field(self._field, self._name)


class TestForkJoinExecution:
    def test_parallel_faster_than_serial(self):
        from ascendc_devkit.orchestration.node_forkjoin import ForkJoinGroup
        root = ForkJoinGroup(name="suite", children=[
            AtomicStage(_SleepProvider("a", "build_result", 0.3)),
            AtomicStage(_SleepProvider("b", "debug_result", 0.3)),
            AtomicStage(_SleepProvider("c", "performance_result", 0.3))])
        s = State.empty().with_updates(non_interactive=True, user_max_iterations=1)
        start = time.monotonic()
        out = GraphExecutor(runner=Runner()).execute(root, s)
        elapsed = time.monotonic() - start
        # 3 × 0.3s serial = 0.9s; parallel should be well under 0.7s
        assert elapsed < 0.7, f"parallel expected <0.7s, got {elapsed:.2f}s"
        assert out.build_result == "a"
        assert out.debug_result == "b"
        assert out.performance_result == "c"

    def test_forkjoin_marks_completed(self):
        from ascendc_devkit.orchestration.node_forkjoin import ForkJoinGroup
        root = ForkJoinGroup(name="suite", children=[
            AtomicStage(_SleepProvider("a", "build_result", 0.0))])
        s = State.empty().with_updates(non_interactive=True, user_max_iterations=1)
        out = GraphExecutor(runner=Runner()).execute(root, s)
        assert out.node_status.get("suite") == "completed"


class _HaltNoArtifact(Stage):
    """fail_strategy=halt stage that never satisfies its contract → halt
    (models a design substage whose agent never delivered its artifact)."""
    default_max_iterations = 2
    fail_strategy = "halt"
    def __init__(self, name, provide, sleep_s=0.0):
        self._name = name; self._provide = provide
        self._sleep_s = sleep_s
    @property
    def name(self): return self._name
    def input_contract(self): return StageIOContract()
    def output_contract(self): return StageIOContract(provides=[self._provide])
    def actions(self, state, iteration=1):
        # Optional per-iteration delay so a sibling that must COMPLETE before this
        # branch's halt lands can deterministically win the P128 cancel race.
        if self._sleep_s:
            time.sleep(self._sleep_s)
        return []
    def transition(self, state, result): return state  # never writes provide


class _SlowLoopingStage(Stage):
    """A continue-strategy stage that keeps iterating (returns a non-empty
    NoOp action list each iteration so the runner never hits ``not actions`` and
    never satisfies its contract) while recording every iteration into a shared
    counter. Models a healthy sibling branch mid-work: without cross-branch
    cancellation it burns its whole iteration budget even after another branch
    has already halted the join (softmax T3 空烧 28min)."""
    def __init__(self, name, counter, max_iters=12, sleep_s=0.1):
        from ascendc_devkit.orchestration.kernel.action import NoOp
        self._name = name; self._counter = counter
        self.default_max_iterations = max_iters
        self._sleep = sleep_s; self._noop = NoOp(reason="slow branch tick")
    @property
    def name(self): return self._name
    def input_contract(self): return StageIOContract()
    # provides a field it NEVER writes → contract never satisfied → keeps looping.
    def output_contract(self): return StageIOContract(provides=["never_provided"])
    def actions(self, state, iteration=1): return [self._noop]
    def transition(self, state, result):
        import time as _t
        self._counter.append(1)          # record this iteration ran
        _t.sleep(self._sleep)            # give the fast branch time to halt+cancel
        return state                     # never writes never_provided


class TestForkJoinBranchFailure:
    """step-60: a failed fork-join branch must halt the join cleanly (no crash),
    keep succeeded siblings' results, and stop downstream advance."""

    def _tiling_group(self):
        from ascendc_devkit.orchestration.node import SequentialGroup
        from ascendc_devkit.orchestration.node_forkjoin import ForkJoinGroup
        # Branches shaped like tiling_branch_factory: SequentialGroup per template.
        # T1 sleeps per iteration so the instant T2 branch deterministically
        # completes before T1's halt fires the P128 cancel token (otherwise the
        # cancel-vs-complete race can leave T2 pending and break the 'ok sibling
        # preserved' assertions below).
        t1 = SequentialGroup(name="T1", children=[
            AtomicStage(_HaltNoArtifact("split", "tiling_results",
                                        sleep_s=0.2))])
        t2 = SequentialGroup(name="T2", children=[
            AtomicStage(_provider_stage("split", "tiling_results",
                                        {"T2": {"split": {}}}))])
        return ForkJoinGroup(name="tiling", children=[t1, t2])

    def test_failed_branch_halts_join_without_crash(self):
        root = self._tiling_group()
        s = State.empty().with_updates(non_interactive=True, user_max_iterations=2)
        # P1: must NOT raise StateConflictError.
        out = GraphExecutor(runner=Runner()).execute(root, s)
        # A: fork-join halts cleanly with a named reason.
        assert out.is_terminal is True
        assert out.halt_reason is not None
        assert out.halt_reason.get("kind") == "fail_strategy_halt"
        assert "T1" in out.halt_reason.get("stage", "")
        # node_status: failed branch failed, ok branch completed, group failed.
        assert out.node_status.get("tiling/T1") == "failed"
        assert out.node_status.get("tiling/T2") == "completed"
        assert out.node_status.get("tiling") == "failed"
        # B: succeeded sibling's result is preserved (resume skips it); the
        # failed branch contributed nothing (its None was not merged).
        assert out.tiling_results == {"T2": {"split": {}}}

    def test_failed_forkjoin_branch_stops_downstream_sibling(self):
        from ascendc_devkit.orchestration.node import SequentialGroup
        # detailed-design shape: tiling[ForkJoin] → downstream stage. A failed
        # tiling branch must halt so the downstream sibling never runs (P2).
        downstream = AtomicStage(_provider_stage("integrate", "design_spec",
                                                 {"ran": True}))
        seq = SequentialGroup(name="dd", children=[self._tiling_group(), downstream])
        s = State.empty().with_updates(non_interactive=True, user_max_iterations=2)
        out = GraphExecutor(runner=Runner()).execute(seq, s)
        assert out.is_terminal is True
        # downstream integrate stage must NOT have run.
        assert out.design_spec is None
        assert out.node_status.get("dd/integrate") not in ("completed", "failed")

    def test_multiple_failed_branches_all_marked_no_crash(self):
        from ascendc_devkit.orchestration.node_forkjoin import ForkJoinGroup
        # Two branches fail (bare atomics: node_status "failed", is_terminal not
        # set at branch level → detected via node_status; halt_reason built from
        # the default). Must not crash; both marked failed; group halts.
        # Both branches sleep per iteration so each passes its LAST iteration's
        # cancel check before the other's failure is consumed (P128 cancel) —
        # without the sync, the second branch is a coin flip between 'failed'
        # and cancelled-pending.
        root = ForkJoinGroup(name="tiling", children=[
            AtomicStage(_HaltNoArtifact("T1", "tiling_results", sleep_s=0.2)),
            AtomicStage(_HaltNoArtifact("T2", "tiling_results", sleep_s=0.2))])
        s = State.empty().with_updates(non_interactive=True, user_max_iterations=2)
        out = GraphExecutor(runner=Runner()).execute(root, s)
        assert out.node_status.get("tiling/T1") == "failed"
        assert out.node_status.get("tiling/T2") == "failed"
        assert out.node_status.get("tiling") == "failed"
        assert out.is_terminal is True
        assert out.halt_reason and out.halt_reason.get("kind") == "fail_strategy_halt"
        # all-fail → merge saw an empty ok list → base unchanged, no crash.
        assert out.tiling_results is None

    def test_forkjoin_cancels_siblings_on_branch_halt(self):
        from ascendc_devkit.orchestration.node import SequentialGroup
        from ascendc_devkit.orchestration.node_forkjoin import ForkJoinGroup
        # P128: the moment ONE branch halts (fail_strategy=halt), the join is going
        # to halt (any_failed → is_terminal), so a healthy sibling still mid-work is
        # 确定无用的空烧. It must be cancelled cooperatively — stop entering NEW
        # iterations — instead of burning its full iteration budget.
        ticks = []
        fast = SequentialGroup(name="T1", children=[
            AtomicStage(_HaltNoArtifact("boom", "tiling_results"))])   # halts ~instantly
        slow = SequentialGroup(name="T2", children=[
            AtomicStage(_SlowLoopingStage("grind", ticks, max_iters=12, sleep_s=0.1))])
        root = ForkJoinGroup(name="tiling", children=[fast, slow])
        s = State.empty().with_updates(non_interactive=True, user_max_iterations=12)
        out = GraphExecutor(runner=Runner()).execute(root, s)
        # Join halted on the failed branch.
        assert out.is_terminal is True
        assert out.node_status.get("tiling/T1") == "failed"
        assert out.node_status.get("tiling") == "failed"
        # THE fix: the slow sibling was cancelled well before exhausting its 12
        # iterations. Pre-fix it runs all 12 (wait-all, no cancel) → len == 12.
        assert len(ticks) < 12, (
            f"slow sibling should be cancelled early, ran {len(ticks)}/12 iterations")
        # A cancelled sibling is NOT marked completed — it stays pending so a
        # resume reruns it (its inner checkpoints, if any, fold via P127).
        assert out.node_status.get("tiling/T2") != "completed"

    def test_resume_skips_completed_inner_node_of_failed_branch(self):
        from ascendc_devkit.orchestration.node import SequentialGroup
        from ascendc_devkit.orchestration.node_forkjoin import ForkJoinGroup
        # P127: a branch whose FIRST inner node completed but a LATER inner node
        # failed must, on resume, skip the completed inner node and rerun ONLY the
        # failed one — not restart the whole branch. This is the 80-min death loop:
        # "split" completes, a later inner stage keeps failing, so without folding
        # the inner "completed" into the join's node_status every resume reruns
        # "split" from scratch.
        g1 = ForkJoinGroup(name="tiling", children=[
            SequentialGroup(name="T1", children=[
                AtomicStage(_provider_stage("A", "build_result", "A1")),
                AtomicStage(_HaltNoArtifact("B", "tiling_results"))])])
        s = State.empty().with_updates(non_interactive=True, user_max_iterations=2)
        out1 = GraphExecutor(runner=Runner()).execute(g1, s)
        assert out1.node_status["tiling/T1"] == "failed"
        # THE fix: inner A's completion is folded into the join's node_status so a
        # resume can skip it (pre-fix this key is absent → whole branch reruns).
        assert out1.node_status.get("tiling/T1/A") == "completed"

        # Resume: only B must rerun; the already-completed A must be skipped.
        ran = []
        g2 = ForkJoinGroup(name="tiling", children=[
            SequentialGroup(name="T1", children=[
                AtomicStage(_logging_provider("A", "build_result", "A1", ran, "A")),
                AtomicStage(_logging_provider("B", "tiling_results",
                                              {"T1": {"s": 1}}, ran, "B"))])])
        s2 = State.empty().with_updates(
            non_interactive=True, user_max_iterations=2,
            node_status=dict(out1.node_status), is_terminal=False,
            halt_reason=None, build_result="A1")
        out2 = GraphExecutor(runner=Runner()).execute(g2, s2)
        assert "A" not in ran, "completed inner node A must be skipped on resume"
        assert ran == ["B"]
        assert out2.node_status["tiling"] == "completed"

    def test_resume_reruns_failed_branch_skips_ok_sibling(self):
        from ascendc_devkit.orchestration.node import SequentialGroup
        from ascendc_devkit.orchestration.node_forkjoin import ForkJoinGroup
        # Round-trip (the Run-1→Run-2 recovery): a fork-join halt PRODUCES a
        # node_status; feeding it back must rerun ONLY the failed branch and skip
        # the ok sibling — the whole reason step-60 carries failed status explicitly.
        # T1 sleeps before each iteration so the instant T2 branch deterministically
        # completes before T1's halt fires the P128 cancel token (otherwise the
        # cancel-vs-complete race is a coin flip and T2 may stay pending).
        g1 = ForkJoinGroup(name="tiling", children=[
            SequentialGroup(name="T1", children=[
                AtomicStage(_HaltNoArtifact("split", "tiling_results",
                                            sleep_s=0.2))]),
            SequentialGroup(name="T2", children=[
                AtomicStage(_provider_stage("split", "tiling_results",
                                            {"T2": {"s": 1}}))])])
        s = State.empty().with_updates(non_interactive=True, user_max_iterations=2)
        out1 = GraphExecutor(runner=Runner()).execute(g1, s)
        assert out1.node_status["tiling/T1"] == "failed"
        assert out1.node_status["tiling/T2"] == "completed"
        assert out1.tiling_results == {"T2": {"s": 1}}

        # Resume: T1 now succeeds. Snapshot strips is_terminal/halt_reason, so
        # clear them; carry T2's result in base. Only T1 must rerun.
        ran = []
        g2 = ForkJoinGroup(name="tiling", children=[
            SequentialGroup(name="T1", children=[
                AtomicStage(_logging_provider("split", "tiling_results",
                                              {"T1": {"s": 1}}, ran, "T1"))]),
            SequentialGroup(name="T2", children=[
                AtomicStage(_logging_provider("split", "tiling_results",
                                              {"T2": {"s": 1}}, ran, "T2"))])])
        s2 = State.empty().with_updates(
            non_interactive=True, user_max_iterations=2,
            node_status=dict(out1.node_status), is_terminal=False,
            halt_reason=None, tiling_results=out1.tiling_results)
        out2 = GraphExecutor(runner=Runner()).execute(g2, s2)
        assert ran == ["T1"]                       # ok sibling T2 skipped
        assert out2.node_status["tiling"] == "completed"
        assert out2.tiling_results == {"T1": {"s": 1}, "T2": {"s": 1}}
        assert out2.is_terminal is False


def test_forkjoin_branch_logger_reaches_runlog(tmp_path):
    """AU-8: ForkJoin branches run in a ``ThreadPoolExecutor`` pool worker whose
    ``contextvars`` context is empty. Without propagating the dispatch thread's
    run.log binding into the worker, a branch's ``Logger`` output is dropped from
    per-op run.log (the AU-8 defect). The pool submission must wrap each branch so
    it inherits the binding."""
    from ascendc_devkit.infra.log_capture import bind_run_log, unbind_run_log
    from ascendc_devkit.infra.logger import Logger
    from ascendc_devkit.orchestration.base import Stage
    from ascendc_devkit.orchestration.kernel.state import State
    from ascendc_devkit.orchestration.node_forkjoin import ForkJoinGroup
    from ascendc_devkit.domain.contract import StageIOContract

    def _branch_stage(name, field, tag):
        def _transition(self, state, result):
            Logger.action("agent_stream", f"{tag}-branch-line")
            return state.with_field(field, tag)
        return type(f"_S_{tag}", (Stage,), {
            "name": name,
            "input_contract": lambda self: StageIOContract(),
            "output_contract": lambda self: StageIOContract(provides=[field]),
            "actions": lambda self, state, iteration=1: [],
            "transition": _transition,
        })()

    log = tmp_path / "run.log"
    bind_run_log(log)
    try:
        # concurrency default "thread" → pool.map path (the AU-8 code path).
        # build_result / debug_result are declared State fields (dataclasses.replace
        # in with_field rejects undeclared names); disjoint provides → clean merge.
        root = ForkJoinGroup(name="tiling", children=[
            AtomicStage(_branch_stage("T1", "build_result", "T1")),
            AtomicStage(_branch_stage("T2", "debug_result", "T2")),
        ])
        GraphExecutor(runner=Runner()).execute(root, State.empty())
    finally:
        unbind_run_log()

    content = log.read_text(encoding="utf-8")
    assert "T1-branch-line" in content, "ForkJoin T1 Logger dropped from run.log (AU-8)"
    assert "T2-branch-line" in content, "ForkJoin T2 Logger dropped from run.log (AU-8)"


def test_sidetask_branch_logger_reaches_runlog(tmp_path):
    """AU-8 (SideTask): a fire-and-forget SideTask runs in ``_side_pool`` — a
    ``ThreadPoolExecutor`` whose workers start with an empty ``contextvars``
    context, exactly like the ForkJoin pool. Without propagating the dispatch
    thread's run.log binding into that worker (the ``context_callable`` wrap on
    ``_launch_sidetask``'s submit), the side task's ``Logger`` output is dropped
    from per-op run.log.

    This is the symmetric guard to ``test_forkjoin_branch_logger_reaches_runlog``
    (which guards the ForkJoin ``pool.map`` site). It guards the OTHER AU-8 call
    site — ``graph_executor._launch_sidetask`` (``self._side_pool.submit(...)``) —
    so unwrapping that one submit regresses LOUDLY here instead of silently
    dropping side-task logs (the gap that left SideTask uncovered while ForkJoin
    had two guards)."""
    from ascendc_devkit.infra.log_capture import bind_run_log, unbind_run_log
    from ascendc_devkit.infra.logger import Logger
    from ascendc_devkit.orchestration.base import Stage
    from ascendc_devkit.orchestration.kernel.state import State
    from ascendc_devkit.orchestration.node import AtomicStage
    from ascendc_devkit.orchestration.node_sidetask import SideTask
    from ascendc_devkit.domain.contract import StageIOContract

    def _side_stage(name, field, tag):
        def _transition(self, state, result):
            Logger.action("agent_stream", f"{tag}-sidetask-line")
            return state.with_field(field, tag)
        return type(f"_SS_{tag}", (Stage,), {
            "name": name,
            "input_contract": lambda self: StageIOContract(),
            "output_contract": lambda self: StageIOContract(provides=[field]),
            "actions": lambda self, state, iteration=1: [],
            "transition": _transition,
        })()

    log = tmp_path / "run.log"
    bind_run_log(log)
    try:
        # A root SideTask: execute() launches it async into _side_pool, then
        # _join_side_tasks() waits — so the Logger line is emitted before return.
        root = SideTask(
            name="side", timeout_sec=30,
            task=AtomicStage(_side_stage("side1", "build_result", "S1")))
        GraphExecutor(runner=Runner()).execute(root, State.empty())
    finally:
        unbind_run_log()

    content = log.read_text(encoding="utf-8")
    assert "S1-sidetask-line" in content, (
        "SideTask Logger dropped from run.log (AU-8) — check "
        "graph_executor._launch_sidetask still wraps the _side_pool.submit "
        "callable with context_callable (a bare submit runs in a worker with "
        "an empty contextvars context and drops run.log).")
