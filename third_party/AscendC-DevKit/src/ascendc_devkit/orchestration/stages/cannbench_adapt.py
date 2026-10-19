"""L3 Orchestration — CannbenchAdaptStage: orchestrate cann-bench glue adaptation.

The cann-bench-specific glue — ``cann_bench/__init__.py`` wrapper generation
and op_plugin ``m.def`` schema alignment/validation — lives in
``adapters/evaluation/cannbench_adapt.py``. This stage resolves state inputs,
calls that adapter, runs the clean rebuild, and writes ``AdaptResult``.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ascendc_devkit.adapters.evaluation.cannbench_adapt import (
    generate_and_inject_wrapper,
    rename_mdef_schema_if_needed,
    validate_plugin_schema,
)
from ascendc_devkit.domain.contract import StageIOContract
from ascendc_devkit.domain.verification import AdaptResult, DeployResult
from ascendc_devkit.orchestration.base import Stage
from ascendc_devkit.orchestration.kernel.action import Action
from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
from ascendc_devkit.orchestration.registry import register_stage

if TYPE_CHECKING:
    from ascendc_devkit.orchestration.kernel.state import State


@register_stage
class CannbenchAdaptStage(Stage):
    """Deterministically adapt cann-bench glue so the operator is discoverable."""

    name = "cannbench_adapt"
    description = (
        "Deterministically write cann_bench wrapper + align m.def schema "
        "so cann-bench discovers the operator"
    )
    default_max_iterations = 2
    fail_strategy = "continue"
    uninterruptible = True

    def input_contract(self) -> StageIOContract:
        return StageIOContract(
            requires=["generated_sources", "codegen_manifest", "repo_root"],
            optional=["deploy_result"],
        )

    def output_contract(self) -> StageIOContract:
        return StageIOContract(provides=["adapt_result"])

    @staticmethod
    def _resolve_repo_root(state: State) -> Path | None:
        if state.repo_root:
            return state.repo_root
        if state.op_identity and state.op_identity.repo_root:
            return state.op_identity.repo_root
        return None

    @staticmethod
    def _resolve_source_dir(state: State, repo_root: Path) -> Path:
        if state.op_dir:
            return state.op_dir
        if state.op_identity and state.op_identity.op_dir:
            return state.op_identity.op_dir
        return repo_root / "examples" / "aclnn_launch_example"

    def actions(self, state: State, iteration: int = 1) -> list[Action]:
        return []

    def skip_reason(self, state: State) -> str | None:
        return "deterministic stage — wrapper gen + P10 m.def rename run in transition()"

    def transition(self, state: State, result: dict) -> State:
        """Run deterministic adaptation and one clean rebuild when files change."""
        repo_root = self._resolve_repo_root(state)
        source_dir = self._resolve_source_dir(state, repo_root) if repo_root else None
        op_spec = state.op_spec
        if op_spec is None and state.requirement is not None:
            op_spec = state.requirement.op_spec
        op_dir = state.op_dir or (
            state.op_identity.op_dir if state.op_identity else None
        )
        op_name = state.op_name or ""

        injected, wrap_errors, files_modified = generate_and_inject_wrapper(
            state.codegen_manifest,
            op_spec,
            op_name,
            repo_root,
            source_dir,
            state.proto_schema,
        )
        schema_renamed, p10_errors = rename_mdef_schema_if_needed(
            op_spec,
            op_dir,
            op_name,
            state.proto_schema,
        )
        errors = wrap_errors + p10_errors

        order_violation = validate_plugin_schema(
            op_dir, op_name, state.proto_schema
        )
        if order_violation:
            errors.append(order_violation)

        need_rebuild = injected or bool(schema_renamed)
        new_deploy: DeployResult | None = None
        rebuild_err: ErrorFeedback | None = None
        rebuilt = False
        if need_rebuild:
            from ascendc_devkit.orchestration.stages.deploy import Deployer

            # 统一 clean rebuild (build_install, 不 smoke)：wrapper 注入 OR schema rename
            # → 无条件一次 clean build+install,让新算子进 _C.abi3.so（P96：清 CMake GLOB
            # cache build_py 强制 reconfigure）+ per-op 包同步（含新 wrapper，P47：per-op 是
            # eval 实际加载目标）。只 build+install 不 smoke——adapt 改的是胶水层,kernel
            # 可调用性归 codegen smoke + precision_debug（§2.9：adapt smoke 无修复渠道）。
            new_deploy, rebuild_err = Deployer().build_install(
                state, clean_build=True)
            # build_install 的 smoke_passed 恒 False（没跑 smoke）；rebuilt 只看 build+install
            # 成功产出包，不看 smoke_passed。
            rebuilt = rebuild_err is None and new_deploy is not None

        updates: dict = {
            "adapt_result": AdaptResult(
                adapted=injected or bool(schema_renamed),
                files_modified=files_modified,
                errors=errors,
                schema_renamed=schema_renamed,
                rebuilt=rebuilt,
            ),
        }
        if new_deploy is not None and rebuild_err is None:
            updates["deploy_result"] = new_deploy
        if rebuild_err is not None or (need_rebuild and not rebuilt):
            updates["last_error"] = ErrorFeedback(
                stage_name="cannbench_adapt",
                error_type="deploy_failed",
                message=(
                    "clean rebuild after adapt failed: "
                    f"{rebuild_err.message if rebuild_err else 'build_install produced no package'}"
                ),
                details={"schema_renamed": schema_renamed},
            )
        elif order_violation:
            updates["last_error"] = ErrorFeedback(
                stage_name="cannbench_adapt",
                error_type="schema_param_order_violation",
                message=order_violation,
                details={"op_name": op_name},
            )
        return state.with_updates(**updates)
