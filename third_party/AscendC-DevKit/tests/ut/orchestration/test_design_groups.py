"""P3 (step-2b) — general-design / detailed-design group skeletons (§四).

Drives: design_tree.py builders, ForkJoinGroup.branch_factory/resolved_children
(B'), CompositeGroup.output_contract_override. Strict TDD — written before impl.
"""

import pytest
from ascendc_devkit.orchestration.node import (
    AtomicStage, SequentialGroup, CompositeGroup, node_paths,
)
from ascendc_devkit.orchestration.node_forkjoin import ForkJoinGroup
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.design_tree import (
    build_general_design_group, build_detailed_design_group,
    _DETAILED_DESIGN_TRANSITION_TABLE,
)


def _find(node, name):
    """Depth-first search for a child node by name."""
    if getattr(node, "name", None) == name:
        return node
    for c in node.children():
        hit = _find(c, name)
        if hit is not None:
            return hit
    return None


class TestGeneralDesignGroup:
    def test_returns_composite_group(self):
        g = build_general_design_group()
        assert isinstance(g, SequentialGroup)  # CompositeGroup is its alias
        assert g.name == "general-design"

    def test_requires_requirement(self):
        g = build_general_design_group()
        assert "requirement" in g.input_contract().requires

    def test_provides_general_design_only(self):
        g = build_general_design_group()
        assert g.output_contract().provides == ["general_design"]

    def test_single_substage_no_forkjoin(self):
        g = build_general_design_group()
        children = g.children()
        assert len(children) == 1
        names = [c.name for c in children]
        assert names == ["general-design-generator"]
        # No tiling / ForkJoin inside the concept-design group.
        for c in children:
            assert not isinstance(c, ForkJoinGroup)


class TestDetailedDesignGroup:
    def test_output_contract_two_piece(self):
        """Step 9: kernel_architecture removed from design output — section
        declaration is now codegen_init's responsibility. The merged synthesize
        owner also provides design_doc (详细设计说明书 path)."""
        g = build_detailed_design_group()
        oc = g.output_contract()
        assert oc.provides == [
            "design_spec", "tiling_strategy", "design_doc",
        ]
        assert oc.optional_provides == ["data_flow"]

    def test_requires_general_design(self):
        g = build_detailed_design_group()
        assert "general_design" in g.input_contract().requires

    def test_contains_tiling_forkjoin(self):
        g = build_detailed_design_group()
        tiling = _find(g, "tiling")
        assert isinstance(tiling, ForkJoinGroup)

    def test_children_order_no_gates(self):
        """删门后详细设计组仅剩 producer 阶段：dd-intake → template-division →
        tiling → synthesize → docgen。anchor-consistency / validate 门节点彻底移除，
        docgen 独立成段（docs/plan/synthesize-docgen-dilution/，§1.14 最小结构）。"""
        g = build_detailed_design_group()
        names = [c.name for c in g.children()]
        assert names == ["dd-intake", "template-division", "tiling",
                         "synthesize", "docgen"]
        assert "anchor-consistency" not in names
        assert "validate" not in names
        assert "integrate" not in names

    def test_no_anchor_forkjoin_node(self):
        """anchor-forkjoin 节点随门删除（§1.14），不再出现在详细设计组树中。"""
        g = build_detailed_design_group()
        assert _find(g, "anchor-forkjoin") is None
        assert _find(g, "anchor-consistency") is None
        assert _find(g, "validate") is None


class TestTransitionTableNoGates:
    def test_detailed_table_only_dd_intake_short_circuit(self):
        """删门后 transition table 无 corrective 边：唯一剩余转移是 dd-intake
        短路 → integrate（合成 owner）。anchor→tiling / validate→redo_tiling
        等门相关 corrective 边已删（§1.14；对应 §4 Step 1「transition table 无
        corrective 边」）。"""
        t = _DETAILED_DESIGN_TRANSITION_TABLE
        assert t["dd-intake"]["short_circuit"] == ("synthesize", "validation")
        assert "anchor-consistency" not in t
        assert "validate" not in t
        assert len(t) == 1  # 仅 dd-intake 一个键

    def test_general_group_has_no_transition_table(self):
        """概设组只有一个 producer 阶段，无 review 门 → 无转移表（无 corrective /
        escalation 边）。"""
        g = build_general_design_group()
        assert g.transition_table == {}


class TestDynamicBranches:
    def test_branch_factory_expands_per_template(self):
        g = build_detailed_design_group()
        tiling = _find(g, "tiling")
        state = State.empty().with_updates(
            template_division={"templates": [{"name": "T1"}, {"name": "T2"}]})
        branches = tiling.resolved_children(state)
        assert len(branches) == 2
        names = sorted(b.name for b in branches)
        assert names == ["T1", "T2"]
        # Each branch is a single-merged-tiling sequential group: one child,
        # name "tiling" (split → vf-design → buffer-kernel → precision-perf run
        # in one agent session; vf-design's A5-only skip lives in the facade
        # skill, so the graph is uniform across arches). See tiling_branch_factory.
        for b in branches:
            child_names = [c.name for c in b.children()]
            assert child_names == ["tiling"]

    def test_resolved_children_falls_back_to_static(self):
        # A ForkJoinGroup without branch_factory (e.g. full_test) keeps static
        # children — zero regression for existing fork-join nodes.
        fj = ForkJoinGroup(name="fj", children=[])
        state = State.empty()
        assert fj.resolved_children(state) == fj.children()


class TestOutputContractOverride:
    def test_override_applied(self):
        from ascendc_devkit.domain.contract import StageIOContract
        ov = StageIOContract(provides=["x"], optional_provides=["y"])
        g = CompositeGroup(name="g", children=[], output_contract_override=ov)
        assert g.output_contract().provides == ["x"]
        assert g.output_contract().optional_provides == ["y"]

    def test_no_override_uses_last_child(self):
        g = CompositeGroup(name="g", children=[])
        # Empty group, no override → empty contract (existing behavior).
        assert g.output_contract().provides == []


class TestNodePaths:
    def test_groups_in_pipeline_paths(self):
        gd = build_general_design_group()
        dd = build_detailed_design_group()
        pipe = SequentialGroup(name="pipeline", children=[gd, dd])
        paths = node_paths(pipe)
        assert "pipeline/general-design/general-design-generator" in paths
        assert "pipeline/detailed-design/tiling" in paths
