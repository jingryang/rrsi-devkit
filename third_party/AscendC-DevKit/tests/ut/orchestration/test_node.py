"""Phase 1: StageNode tree — AtomicStage + SequentialGroup."""

from ascendc_devkit.orchestration.node import AtomicStage, SequentialGroup
from ascendc_devkit.orchestration.base import Stage
from ascendc_devkit.domain.contract import StageIOContract


def _stage(name, requires=(), provides=()):
    return type(f"_S_{name}", (Stage,), {
        "name": name,
        "input_contract": lambda self: StageIOContract(requires=list(requires)),
        "output_contract": lambda self: StageIOContract(provides=list(provides)),
        "actions": lambda self, state, iteration=1: [],
    })()


class TestAtomicStage:
    def test_wraps_stage_name(self):
        node = AtomicStage(_stage("entry"))
        assert node.name == "entry"
        assert node.children() == []

    def test_delegates_contracts(self):
        node = AtomicStage(_stage("s", requires=["a"], provides=["b"]))
        assert node.input_contract().requires == ["a"]
        assert node.output_contract().provides == ["b"]

    def test_exposes_underlying_stage(self):
        st = _stage("s")
        node = AtomicStage(st)
        assert node.stage is st


class TestSequentialGroup:
    def test_children_in_order(self):
        g = SequentialGroup(name="pipeline", children=[
            AtomicStage(_stage("a")), AtomicStage(_stage("b"))])
        assert [c.name for c in g.children()] == ["a", "b"]

    def test_input_contract_is_first_child(self):
        g = SequentialGroup(name="p", children=[
            AtomicStage(_stage("a", requires=["x"])),
            AtomicStage(_stage("b"))])
        assert g.input_contract().requires == ["x"]

    def test_output_contract_is_last_child(self):
        g = SequentialGroup(name="p", children=[
            AtomicStage(_stage("a")),
            AtomicStage(_stage("b", provides=["y"]))])
        assert g.output_contract().provides == ["y"]


from ascendc_devkit.orchestration.node import node_paths


class TestNodePaths:
    def test_flat_paths(self):
        g = SequentialGroup(name="pipeline", children=[
            AtomicStage(_stage("entry")), AtomicStage(_stage("context"))])
        paths = node_paths(g)
        assert paths["pipeline"] is g
        assert paths["pipeline/entry"].name == "entry"
        assert paths["pipeline/context"].name == "context"

    def test_nested_paths(self):
        inner = SequentialGroup(name="design", children=[
            AtomicStage(_stage("high")), AtomicStage(_stage("detail"))])
        g = SequentialGroup(name="pipeline", children=[
            AtomicStage(_stage("entry")), inner])
        paths = node_paths(g)
        assert "pipeline/design" in paths
        assert "pipeline/design/high" in paths
        assert "pipeline/design/detail" in paths


from ascendc_devkit.orchestration.kernel import event as evt


class TestGraphEvents:
    def test_node_enter(self):
        e = evt.node_enter("pipeline/entry")
        assert e["type"] == "node_enter" and e["path"] == "pipeline/entry"

    def test_node_complete(self):
        e = evt.node_complete("pipeline/entry", 12)
        assert e["type"] == "node_complete" and e["elapsed_ms"] == 12

    def test_loopback_scoped(self):
        e = evt.loopback("pipeline/design", "detail", "high", "escalation", 1, 1)
        assert e["type"] == "loopback"
        assert e["scope"] == "pipeline/design"
        assert e["route_type"] == "escalation"

    def test_stagnation(self):
        e = evt.stagnation("pipeline", "verify", "codegen")
        assert e["type"] == "stagnation" and e["scope"] == "pipeline"
