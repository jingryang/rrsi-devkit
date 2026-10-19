"""Phase 4: SideTask — fire-and-forget side branch."""

from ascendc_devkit.orchestration.node import AtomicStage
from ascendc_devkit.orchestration.base import Stage
from ascendc_devkit.domain.contract import StageIOContract


def _stage(name):
    return type(f"_S_{name}", (Stage,), {
        "name": name,
        "input_contract": lambda self: StageIOContract(),
        "output_contract": lambda self: StageIOContract(),
        "actions": lambda self, state, iteration=1: [],
    })()


class TestSideTaskNode:
    def test_wraps_task(self):
        from ascendc_devkit.orchestration.node_sidetask import SideTask
        st = SideTask(name="render", task=AtomicStage(_stage("md")),
                      timeout_sec=60)
        assert st.name == "render"
        assert st.timeout_sec == 60
        assert st.children() == []

    def test_default_timeout(self):
        from ascendc_devkit.orchestration.node_sidetask import SideTask
        st = SideTask(name="render", task=AtomicStage(_stage("md")))
        assert st.timeout_sec == 300


import time
from ascendc_devkit.orchestration.graph_executor import GraphExecutor
from ascendc_devkit.orchestration.node import SequentialGroup, AtomicStage
from ascendc_devkit.orchestration.node_sidetask import SideTask
from ascendc_devkit.orchestration.kernel.runner import Runner
from ascendc_devkit.orchestration.kernel.state import State


class _Marker(Stage):
    """Records that it ran into a shared list (proves side task executed)."""
    default_max_iterations = 1
    def __init__(self, name, log, sleep_s=0.0):
        self._name = name; self._log = log; self._sleep = sleep_s
    @property
    def name(self): return self._name
    def input_contract(self): return StageIOContract()
    def output_contract(self): return StageIOContract()
    def actions(self, state, iteration=1): return []
    def transition(self, state, result):
        time.sleep(self._sleep); self._log.append(self._name); return state


class TestSideTaskExecution:
    def test_main_flow_does_not_wait_but_join_before_return(self):
        log = []
        root = SequentialGroup(name="pipeline", children=[
            AtomicStage(_Marker("design", log)),
            SideTask(name="render",
                     task=AtomicStage(_Marker("md", log, sleep_s=0.2)),
                     timeout_sec=5),
            AtomicStage(_Marker("codegen", log))])
        s = State.empty().with_updates(non_interactive=True, user_max_iterations=1)
        GraphExecutor(runner=Runner()).execute(root, s)
        # codegen (main) runs before the slow side task completes...
        assert log.index("codegen") < log.index("md")
        # ...but the side task IS joined before execute() returns
        assert "md" in log

    def test_side_task_does_not_write_state(self):
        log = []
        # side task tries to set a field; it must NOT appear in returned state
        side = type("_Setter", (Stage,), {
            "name": "setter",
            "input_contract": lambda self: StageIOContract(),
            "output_contract": lambda self: StageIOContract(provides=["build_result"]),
            "actions": lambda self, state, iteration=1: [],
            "transition": lambda self, state, result: state.with_field("build_result", "SIDE"),
        })()
        root = SequentialGroup(name="pipeline", children=[
            SideTask(name="s", task=AtomicStage(side), timeout_sec=5),
            AtomicStage(_Marker("main", log))])
        s = State.empty().with_updates(non_interactive=True, user_max_iterations=1)
        out = GraphExecutor(runner=Runner()).execute(root, s)
        assert out.build_result is None   # side task result discarded
