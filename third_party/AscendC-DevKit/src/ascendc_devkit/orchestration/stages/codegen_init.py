"""L3 Orchestration — CodegenInitStage: deterministic section declaration for codegen.

Self-evolution step 9: determines kernel_architecture section declarations
(host_code/kernel_code/api_code/plugin_code), NOT from operator design.
This replaces the design stage's section-declaration responsibility.

Rules (deterministic, no LLM agent):
  - host_code + kernel_code + api_code + plugin_code: always declared. The
    ACLNN registration layer (op_api/op_plugin) is generic code virtually every
    operator needs; the rare operator that doesn't is an operator-level (not
    repo-level) exception, and generating it anyway is harmless (extra work, not
    an error). So there is no repo/scaffolding gate here — the old
    per-repo-name switch was a wrong abstraction (the need is neither repo-level
    nor cleanly on/off) and is removed. Revisit only if a real
    "must-not-generate-aclnn" case appears.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ascendc_devkit.domain.contract import StageIOContract
from ascendc_devkit.orchestration.base import Stage
from ascendc_devkit.orchestration.registry import register_stage
from ascendc_devkit.orchestration.kernel.action import Action

if TYPE_CHECKING:
    from ascendc_devkit.orchestration.kernel.state import State


@register_stage
class CodegenInitStage(Stage):
    """Deterministic section declaration for codegen.

    Replaces the design-stage integrator's kernel_architecture section
    declaration (P3 fix).  Declares the four standard sections
    (host_code/kernel_code/api_code/plugin_code) that virtually every AscendC
    operator needs — including the ACLNN registration layer (op_api/op_plugin),
    which is generic code, not a per-repo choice (see module docstring).

    This is a deterministic single-pass stage (no agent, no iteration).
    """

    name = "codegen_init"
    description = "Deterministic section declaration for codegen (four standard sections)"
    default_max_iterations = 1
    needs_iteration_safety_net = False
    fail_strategy = "continue"  # if unable to determine, codegen uses safe defaults

    def input_contract(self) -> StageIOContract:
        # No hard requires: section declaration is now unconditional (no longer
        # reads profile to gate api/plugin), so nothing upstream is mandatory.
        return StageIOContract(
            requires=[],
            optional=["profile", "design_spec", "tiling_strategy"],
        )

    def output_contract(self) -> StageIOContract:
        return StageIOContract(
            provides=["kernel_architecture"],
        )

    def actions(self, state: State, iteration: int = 1) -> list[Action]:
        return []  # deterministic — no agent

    def skip_reason(self, state: State) -> str | None:
        """P6-b: deterministic no-agent stage — work runs in transition(), not actions()."""
        return "deterministic stage — section declaration runs in transition()"

    def transition(self, state: State, result: dict) -> State:
        arch = self._build_sections()
        return state.with_updates(kernel_architecture=arch)

    # —— internal helpers ——

    @staticmethod
    def _build_sections() -> dict:
        """Build kernel_architecture section declarations.

        All four standard sections are always declared. host_code + kernel_code
        are the AscendC core; api_code + plugin_code are the ACLNN registration
        layer — generic code virtually every operator needs, and harmless when
        an occasional operator doesn't (extra work, not an error). There is no
        repo/scaffolding gate: the need is not a repo-level property, so a
        per-repo switch would be the wrong abstraction (§1.2). ``state`` is
        unused; kept in the signature for a uniform stage-helper shape.
        """
        return {
            "host_code": {"directory": "op_host"},
            "kernel_code": {"directory": "op_kernel"},
            "api_code": {"directory": "op_api"},
            "plugin_code": {"directory": "op_plugin"},
        }
