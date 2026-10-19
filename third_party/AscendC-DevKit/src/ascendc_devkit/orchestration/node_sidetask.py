"""L3 Orchestration — SideTask: fire-and-forget side branch."""

from __future__ import annotations

from dataclasses import dataclass

from ascendc_devkit.orchestration.node import StageNode
from ascendc_devkit.domain.contract import StageIOContract


@dataclass
class SideTask(StageNode):
    name: str = ""
    description: str = ""
    task: StageNode | None = None
    timeout_sec: int = 300

    def children(self) -> list[StageNode]:
        # Opaque to parent traversal; executor schedules `task` itself.
        return []

    def input_contract(self) -> StageIOContract:
        return self.task.input_contract() if self.task else StageIOContract()

    def output_contract(self) -> StageIOContract:
        # Side tasks contribute nothing to the main State.
        return StageIOContract()
