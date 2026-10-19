"""L3 Orchestration — Entry Stage: parse TaskRequest, validate inputs."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ascendc_devkit.domain.contract import StageIOContract
from ascendc_devkit.orchestration.base import Stage
from ascendc_devkit.orchestration.registry import register_stage
from ascendc_devkit.orchestration.kernel.action import ValidateInputs, Action, NoOp
from ascendc_devkit.infra.logger import Logger

if TYPE_CHECKING:
    from ascendc_devkit.orchestration.kernel.state import State


@register_stage
class EntryStage(Stage):
    name = "entry"
    description = "Parse TaskRequest, validate inputs, determine mode and workflow"
    default_max_iterations = 1
    needs_iteration_safety_net = False  # deterministic single pass, no agent

    def input_contract(self) -> StageIOContract:
        return StageIOContract(
            requires=["task_request"],
            optional=[],
        )

    def output_contract(self) -> StageIOContract:
        return StageIOContract(
            provides=[
                "mode",
                "workflow_name",
                "op_name",
                "repo_profile_name",
                "non_interactive",
            ],
            # Conditional / runtime-filled outputs: declared but NOT part of the
            # has_all() early-termination check.
            #  - target_repo / requirement_path: only set when the user supplied
            #    them; downstream stages that truly need them enforce it in their
            #    own `requires` (e.g. RequirementStage requires requirement_path).
            #  - npu_id: dispatch-resolved op card (P13/step-116 op-level lease
            #    writes it into State before the executor runs; entry preserves
            #    it, never rebuilds from the task hint). Declared optional only
            #    for schema completeness.
            optional_provides=[
                "target_repo",
                "requirement_path",
                "requirement_aux_paths",
                "npu_id",
            ],
        )

    def actions(self, state: State, iteration: int = 1) -> list[Action]:
        tr = state.task_request or {}
        checks = [
            f"mode in ('new', 'incremental'): got '{tr.get('mode', '')}'",
        ]
        target_repo = tr.get("target_repo", "")
        if target_repo:
            checks.append(
                f"target_repo '{target_repo}' exists: {Path(target_repo).is_dir()}"
            )

        # When --op-dir was given, the L1→L2 resolver already identified the
        # repo and selected a build variant (it errors out otherwise). Assert
        # those products landed in task_request so a silent resolution gap
        # surfaces here rather than failing deep in a later stage. L3 only reads
        # the resolved fields — it never re-imports the L2 resolver (§11.4).
        if tr.get("op_dir"):
            checks.append(
                f"repo identified from --op-dir: '{tr.get('repo_profile', '')}' is truthy"
            )
            checks.append(
                f"build variant matched for --op-dir: '{tr.get('variant_name', '')}' is truthy"
            )

        if tr.get("mode") == "incremental":
            op_name = tr.get("op_name", "")
            checks.append(
                f"op_name is set for incremental mode: '{op_name}' is truthy"
            )

        return [ValidateInputs(checks=checks)]

    def transition(self, state: State, result: dict) -> State:
        tr = state.task_request or {}
        # Prefer the resolved repo_root (from --op-dir) as target_repo so
        # repo-aware stages have a concrete root. Fall back to explicit
        # target_repo, then to the resolved repo_root.
        target_repo_raw = tr.get("target_repo") or tr.get("repo_root")
        target_repo = Path(target_repo_raw) if target_repo_raw else None

        op_dir = tr.get("op_dir")
        repo_root = tr.get("repo_root")

        return state.with_updates(
            mode=tr.get("mode", "new"),
            workflow_name=tr.get("workflow", "generate_ascendc"),
            op_name=tr.get("op_name", ""),
            target_repo=target_repo,
            repo_profile_name=tr.get("repo_profile", ""),
            op_dir=Path(op_dir) if op_dir else None,
            repo_root=Path(repo_root) if repo_root else None,
            rel_op_dir=tr.get("rel_op_dir", ""),
            full_op_name=tr.get("full_op_name", ""),
            variant_name=tr.get("variant_name", ""),
            reference_roots=list(tr.get("references", []) or []),
            # step-34 dual chip fields: rebuild from task_request (CLI) on a
            # resume that re-runs entry, else preserve the dispatch-resolved
            # values (runtime was probe-resolved; must not be blanked on resume).
            design_target_chip=tr.get("design_target_chip") or state.design_target_chip,
            runtime_target_chip=tr.get("runtime_target_chip") or state.runtime_target_chip,
            requirement_path=Path(tr["requirement_path"]) if tr.get("requirement_path") else None,
            # 附加需求材料（--requirement-aux）：从 task_request 透传为 Path 列表。
            requirement_aux_paths=[Path(p) for p in (tr.get("requirement_aux_paths") or [])],
            # P13 (step-116)：npu_id 的权威值 = dispatch 在 op 边界解析的 op 卡
            # （resolve_op_card 后写回 State）。entry 不从 task hint 重建——旧
            # `tr.get("npu_id", 0)` 会把已解析卡打回 hint/0，破坏 op 租约唯一性。
            non_interactive=tr.get("non_interactive", False),
        )
