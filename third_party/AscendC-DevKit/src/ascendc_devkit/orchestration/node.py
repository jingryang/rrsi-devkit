"""L3 Orchestration — StageNode tree: graph nodes for hierarchical workflows."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ascendc_devkit.domain.contract import StageIOContract


class StageNode(ABC):
    """A node in the workflow directed graph. GraphExecutor traversal unit."""

    name: str = ""
    description: str = ""

    @abstractmethod
    def children(self) -> list["StageNode"]:
        ...

    @abstractmethod
    def input_contract(self) -> StageIOContract:
        ...

    @abstractmethod
    def output_contract(self) -> StageIOContract:
        ...


class AtomicStage(StageNode):
    """Leaf node wrapping an existing Stage. Delegates all behavior."""

    def __init__(self, stage):
        self.stage = stage
        self.name = stage.name
        self.description = getattr(stage, "description", "")

    def children(self) -> list[StageNode]:
        return []

    def input_contract(self) -> StageIOContract:
        return self.stage.input_contract()

    def output_contract(self) -> StageIOContract:
        return self.stage.output_contract()

    def gate(self):
        return self.stage.gate()

    def validate_inputs(self, state) -> list[str]:
        return self.stage.validate_inputs(state)

    def resolve_condition(self, state) -> str:
        return self.stage.resolve_condition(state)

    def error_signature(self, state) -> str:
        return self.stage.error_signature(state)


@dataclass
class SequentialGroup(StageNode):
    """Ordered children + optional scoped transition table.

    Serves as both the top-level pipeline root and an embedded CompositeGroup.
    CompositeGroup is an alias of this class (see node aliases)."""

    name: str = ""
    description: str = ""
    children_list: list[StageNode] = field(default_factory=list)
    transition_table: dict = field(default_factory=dict)
    max_corrective: int = 3
    max_escalations: int = 1

    # Allow `children=[...]` kwarg at construction for readability.
    def __init__(self, name: str = "", description: str = "",
                 children: list[StageNode] | None = None,
                 transition_table: dict | None = None,
                 max_corrective: int = 3, max_escalations: int = 1,
                 output_contract_override: StageIOContract | None = None):
        self.name = name
        self.description = description
        self.children_list = list(children or [])
        self.transition_table = dict(transition_table or {})
        self.max_corrective = max_corrective
        self.max_escalations = max_escalations
        # When set, output_contract() returns this verbatim instead of deriving
        # from the last child. Needed where a group's outward contract must be
        # declared explicitly (e.g. the detailed-design group exposes the
        # three-piece design contract regardless of which child writes it, and
        # the tiling fork-join child has empty static children → no derivable
        # contract). See step-2b §4.3 (R2).
        self._output_override = output_contract_override

    def children(self) -> list[StageNode]:
        return self.children_list

    def input_contract(self) -> StageIOContract:
        if not self.children_list:
            return StageIOContract()
        return self.children_list[0].input_contract()

    def output_contract(self) -> StageIOContract:
        if self._output_override is not None:
            return self._output_override
        if not self.children_list:
            return StageIOContract()
        return self.children_list[-1].output_contract()


# CompositeGroup is a semantic alias of SequentialGroup (same execution/routing).
CompositeGroup = SequentialGroup


def node_paths(root: StageNode, prefix: str = "") -> dict[str, StageNode]:
    """Map every node to its '/'-joined path. Root path == root.name."""
    path = root.name if not prefix else f"{prefix}/{root.name}"
    result: dict[str, StageNode] = {path: root}
    for child in root.children():
        result.update(node_paths(child, prefix=path))
    return result
