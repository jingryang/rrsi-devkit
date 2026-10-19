"""L3 Orchestration — Smoke stage for quick end-to-end verification."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ascendc_devkit.domain.contract import StageIOContract
from ascendc_devkit.orchestration.base import Stage
from ascendc_devkit.orchestration.registry import register_stage
from ascendc_devkit.orchestration.kernel.action import SpawnAgent, Action

if TYPE_CHECKING:
    from ascendc_devkit.orchestration.kernel.state import State


@register_stage
class SmokeStage(Stage):
    name = "smoke"
    description = "Quick verification: agent responds with COMPLETION_MARKER"
    default_max_iterations = 1

    def input_contract(self) -> StageIOContract:
        return StageIOContract(requires=[], optional=["design_spec"])

    def output_contract(self) -> StageIOContract:
        return StageIOContract(provides=["generated_sources"])

    def actions(self, state: State, iteration: int = 1) -> list[Action]:
        prompt = (
            "简单验证任务。请使用 Bash 或 Edit 工具在当前工作目录下创建一个文件 hello.cpp，"
            "内容是 '// hello from agent'。完成后不需要额外输出。"
        )
        return [SpawnAgent(agent_name="ascendc-coder", prompt=prompt, context={})]

    def transition(self, state: State, result: dict) -> State:
        agent_result = result.get("agent_result")
        if agent_result and agent_result.artifacts:
            return state.with_updates(generated_sources=agent_result.artifacts)
        return state
