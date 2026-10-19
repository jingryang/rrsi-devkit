"""A5 RegBase precision_debug orchestration package.

This package restructures the old monolithic ``precision_debug_a5.py`` into
per-phase modules. It exposes both the **new 5-stage flow** (baseline ->
kernel_debug -> vf_test / vector_error_debug / op_plugin_debug; regression 阶段
已合入 kernel_debug——修复当前 case 后由 kernel_debug 批跑全量 KernelLaunch，
框架读取 KL summary JSON 调和 failed_case_queue 并推导路由；baseline 分流
kernel 层失败优先，Q6 修订：精度问题优先调度 ascendc-precision-kernel-debug)
and **legacy compatibility aliases** for existing tests and callers that still
import old names like ``InitBaselineSubstage`` / ``DumpDebugSubstage``.

Public exports (new names):
- BaselineSubstage, KernelDebugSubstage, VfTestSubstage,
  VectorErrorDebugSubstage, OpPluginDebugSubstage
- _A5_TRANSITION_TABLE (new flow), _A5_MAX_CORRECTIVE

Legacy compatibility aliases (old names still importable):
- InitBaselineSubstage -> BaselineSubstage
- PipelineSyncSubstage -> BaselineSubstage (pipeline_sync removed; alias for tests)
- DumpDebugSubstage -> KernelDebugSubstage

All helper functions that old tests import (``_load_a5_checkpoint``,
``_save_a5_checkpoint``, ``_converge_a5_to_best_commit``, etc.) are also
re-exported from the appropriate internal modules.
"""

from __future__ import annotations

from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
    A5PrecisionDebugContractError,
    A5PrecisionDebugSubstage,
    _operator_dir,
    _debug_artifacts_dir,
    _control_path,
    _phase_path,
    _advance_phase_counter,
    _current_round,
    _round_result_stem,
    _skill_round_result_files,
    _expected_round_result_path,
)
from ascendc_devkit.orchestration.stages.precision_debug_a5.checkpoint import (
    _load_a5_checkpoint,
    _save_a5_checkpoint,
    _validate_a5_checkpoint,
    _restore_framework_routing_fields,
    _extract_a5_debug_checkpoint,
    _A5_CONTROL_REQUIRED_KEYS,
    _A5_CONTROL_DEFAULTS,
)
from ascendc_devkit.orchestration.stages.precision_debug_a5.best_snapshot import (
    _snapshot_better,
    _merge_best_snapshot,
    _build_snapshot_from_result,
    _has_valid_numeric_result,
    _commit_candidate_phase,
    _commit_modified_numeric_phase,
)
from ascendc_devkit.orchestration.stages.precision_debug_a5.converge import (
    _sync_debug_result as _a5_sync_debug_result,
    _converge_a5_to_best_commit,
)
from ascendc_devkit.orchestration.stages.precision_debug_a5.git_safety import (
    ensure_entry_snapshot,
    validate_commit_for_operator,
    validated_rollback_anchor,
)
from ascendc_devkit.orchestration.stages.precision_debug_a5.vector_evidence import (
    _extract_error_type,
    _extract_vector_error_evidence,
    _record_phase_error,
)
from ascendc_devkit.orchestration.stages.precision_debug_a5.conclusions import (
    _conclusions_path,
    _read_conclusions,
    _materialize_conclusion,
    _format_conclusions_block,
)
from ascendc_devkit.orchestration.stages.precision_debug_a5.case_loop import (
    _advance_past_resolved,
    _apply_kl_failures_to_queue,
    _case_diffs_from_kl_result,
    _refresh_queue_kl_diffs,
    _per_case_kl_results,
    _reconcile_queue_from_kl,
    _load_latest_kl_data,
    _all_kl_passed,
)
from ascendc_devkit.orchestration.stages.precision_debug_a5.baseline import (
    BaselineSubstage,
)
from ascendc_devkit.orchestration.stages.precision_debug_a5.kernel_debug import (
    KernelDebugSubstage,
)
from ascendc_devkit.orchestration.stages.precision_debug_a5.vf_test import (
    VfTestSubstage,
)
from ascendc_devkit.orchestration.stages.precision_debug_a5.vector_error_debug import (
    VectorErrorDebugSubstage,
)
from ascendc_devkit.orchestration.stages.precision_debug_a5.op_plugin_debug import (
    OpPluginDebugSubstage,
)
from ascendc_devkit.orchestration.stages.precision_debug_a5.transition_table import (
    _A5_TRANSITION_TABLE,
    _A5_MAX_CORRECTIVE,
)


# Legacy aliases for backward compatibility with existing tests.
InitBaselineSubstage = BaselineSubstage
PipelineSyncSubstage = BaselineSubstage
DumpDebugSubstage = KernelDebugSubstage


__all__ = [
    "A5PrecisionDebugContractError",
    "A5PrecisionDebugSubstage",
    "BaselineSubstage",
    "KernelDebugSubstage",
    "VfTestSubstage",
    "VectorErrorDebugSubstage",
    "OpPluginDebugSubstage",
    # Legacy aliases
    "InitBaselineSubstage",
    "PipelineSyncSubstage",
    "DumpDebugSubstage",
    # Transition table
    "_A5_TRANSITION_TABLE",
    "_A5_MAX_CORRECTIVE",
    # Helper re-exports (used by tests and graph_executor)
    "_operator_dir",
    "_debug_artifacts_dir",
    "_control_path",
    "_phase_path",
    "_advance_phase_counter",
    "_current_round",
    "_round_result_stem",
    "_skill_round_result_files",
    "_expected_round_result_path",
    "_load_a5_checkpoint",
    "_save_a5_checkpoint",
    "_validate_a5_checkpoint",
    "_restore_framework_routing_fields",
    "_extract_a5_debug_checkpoint",
    "_snapshot_better",
    "_merge_best_snapshot",
    "_build_snapshot_from_result",
    "_has_valid_numeric_result",
    "_commit_candidate_phase",
    "_commit_modified_numeric_phase",
    "_a5_sync_debug_result",
    "_converge_a5_to_best_commit",
    "ensure_entry_snapshot",
    "validate_commit_for_operator",
    "validated_rollback_anchor",
    "_extract_error_type",
    "_extract_vector_error_evidence",
    "_record_phase_error",
    "_conclusions_path",
    "_read_conclusions",
    "_materialize_conclusion",
    "_format_conclusions_block",
    "_advance_past_resolved",
    "_apply_kl_failures_to_queue",
    "_case_diffs_from_kl_result",
    "_refresh_queue_kl_diffs",
    "_per_case_kl_results",
    "_reconcile_queue_from_kl",
    "_load_latest_kl_data",
    "_all_kl_passed",
]
