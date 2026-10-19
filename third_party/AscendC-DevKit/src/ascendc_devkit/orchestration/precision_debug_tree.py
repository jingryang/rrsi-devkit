"""L3 Orchestration — precision_debug CompositeGroup builder (P3 减法).

Mounts the two precision_debug sub-stages (run_tests ⇄ diagnose) as a
``CompositeGroup``
(SequentialGroup alias) with a scoped transition_table. The GraphExecutor drives the loop synchronously
(spawn → wait → transition → route), replacing the deleted async LLM orchestrator
(51-*.md §1). P3 减法:七 substage → 两段;scope_guard/bounds_check/printf_location/
comment_bisect/diagnose_refine 独立 phase 已删。上游缺陷由 diagnose 入口判据上报
(upstream_signal → __escalate__:upstream → halt)。

Transition-table correction vs the L4 (runlog 冲突1): the L4 §5 wrote terminal
states as ``("__halt__", "completion")``, but ``graph_executor._execute_sequential``
treats ``__halt__`` as whole-run termination (``is_terminal=True``) — that would
halt the entire pipeline on precision pass/exhaust (never reaching cannbench_eval,
losing the ② loss signal). The framework's "group exits to parent" primitive is
``__escalate__:<cond>`` (proven by the test_design group: ``test-casegen.exhausted
→ __escalate__:exhausted``). So terminal states escalate ``passed``/``exhausted``
to the root TRANSITION_TABLE, which routes per-workflow (generate_ascendc:
exhausted→__halt__; self_evolve_op: exhausted→cannbench_adapt soft-gate;
passed→linear successor). The L4 §5.1 "delete the root precision_debug entry,
group always default→linear" is NOT adopted: it loses generate_ascendc's hard
stop-loss (exhausted would wrongly advance to perf).
"""

from __future__ import annotations

from ascendc_devkit.domain.contract import StageIOContract
from ascendc_devkit.orchestration.node import AtomicStage, CompositeGroup

# High safety backstop: the framework's corrective quota bounds any runaway
# (diagnose 实施模式↔printf spin with no run_tests re-entry). The semantic loop bound is the
# framework-side round counter (RunTestsSubstage.transition increments it; rounds
# > checkpoint.max_iterations → escalate exhausted). Set well above max_rounds so
# the framework quota never silently preempts the sub-stage's exhaustion signal.
_DEFAULT_MAX_ROUNDS = 30


# Scoped transition table. Forward-linear steps (run_tests→diagnose on
# has_failures) are deliberately NOT listed: route=None →
# the executor's linear successor advances them without consuming quota. Only
# loop-backs (backward jumps), self-loops, and group exits are encoded.
#
# Conditions come from each sub-stage's resolve_condition (reading
# state._debug_checkpoint). `__escalate__:<cond>` bubbles out of the group; the
# root TRANSITION_TABLE (keyed on the group name "precision_debug") routes it.
_PRECISION_DEBUG_TRANSITION_TABLE: dict = {
    "run_tests": {
        "all_pass": ("__escalate__:passed", "validation"),
        "exhausted": ("__escalate__:exhausted", "validation"),
        # §abort: agent produced no output — self-loop re-spawn (transient) /
        # escalate (persistent, ≥3 consecutive).
        "agent_aborted": ("run_tests", "corrective"),
        "abort_exhausted": ("__escalate__:exhausted", "validation"),
        # "has_failures" → linear successor (diagnose)
    },
    "diagnose": {
        "exhausted": ("__escalate__:exhausted", "validation"),
        # §P3 upstream: diagnose 入口判据上报上游缺陷 → halt（替代 scope_guard upstream）。
        "upstream": ("__escalate__:upstream", "validation"),
        # §judgment-ownership (P5): diagnose 尽力后假设空间穷尽 → stalled 诚实报告。
        # 与 upstream 同 escalate 到根（根按 __halt__ 交人），但 halt_reason 区分
        # "stalled"（模型尽力）vs "upstream"（上游缺陷）vs "exhausted"（预算耗尽）。
        "stalled": ("__escalate__:stalled", "validation"),
        "agent_aborted": ("diagnose", "corrective"),
        # §abort-relay: 熔断 → run_tests 走主循环（abort 是瞬态 agent 死亡/超时，
        # 熔断 ≠ 调试失败，best_commit 需回归验证）。
        "abort_exhausted": ("run_tests", "linear"),
        # 就地实施产物路由
        "resolved": ("run_tests", "corrective"),         # 自实施成功 → 全量回归
        "partial_output": ("run_tests", "corrective"),    # §per-output: partial progress → regress
        "skip_more": ("diagnose", "corrective"),          # case skipped → 下一 case 再诊断
        "skip_done": ("run_tests", "corrective"),         # last case skipped → regress
        "retry": ("diagnose", "corrective"),              # 未修好 → 再诊断+实施
    },
}

def _is_a5(chip_version: str) -> bool:
    """Chip version starts with 'A5' (case-insensitive)."""
    return (chip_version or "").strip().upper().startswith("A5")

def build_precision_debug_group(
    max_rounds: int = _DEFAULT_MAX_ROUNDS,
    chip_version: str = "A3",
) -> CompositeGroup:
    """precision_debug CompositeGroup, chip-aware.

    A3 (default): run_tests → diagnose → diagnose_refine → printf_location →
    comment_bisect → bounds_check → scope_guard (7-substage Membase loop;
    diagnose 自实施原 fix 职责). A5: baseline → kernel_debug →
    (vf_test, conditional) → (vector_error_debug, conditional) → op_plugin_debug
    (5-substage Regbase loop; regression 已合入 kernel_debug).

    Both variants share the same outward contract (debug_result,
    debug_iterations) and the __escalate__ routing convention.
    """
    if _is_a5(chip_version):
        return _build_precision_debug_group_a5()
    return _build_precision_debug_group_a3(max_rounds)

def _build_precision_debug_group_a3(max_rounds: int = _DEFAULT_MAX_ROUNDS) -> CompositeGroup:
    """precision_debug CompositeGroup: run_tests ⇄ diagnose（P3 减法两段）。

    Two children（P3 减法：七 substage → 两段，删 scope_guard / bounds_check /
    printf_location / comment_bisect / diagnose_refine 独立 phase）。diagnose 承担
    诊断+修复一体（就地定位+修，不再枚举/候选池/回炉）；上游缺陷由 diagnose 入口
    判据上报（upstream_signal → halt）。

    The group's outward contract provides ``debug_result`` / ``debug_iterations``
    (materialized by the sub-stages' transition via ``_sync_debug_result``).
    ``max_corrective`` is a high safety backstop; the semantic round bound lives
    in the run_tests sub-stage (rounds > checkpoint.max_iterations → exhausted).
    """
    from ascendc_devkit.orchestration.runtime_config import (
        precision_debug_max_corrective,
    )
    from ascendc_devkit.orchestration.stages.precision_debug_substages import (
        RunTestsSubstage, DiagnoseSubstage,
    )
    mc = precision_debug_max_corrective()
    return CompositeGroup(
        name="precision_debug",
        children=[
            AtomicStage(RunTestsSubstage()),
            AtomicStage(DiagnoseSubstage()),
        ],
        transition_table=_PRECISION_DEBUG_TRANSITION_TABLE,
        output_contract_override=StageIOContract(
            provides=["debug_result", "debug_iterations"]),
        max_corrective=mc,
        max_escalations=mc,
    )


def _build_precision_debug_group_a5() -> CompositeGroup:
    """A5 Regbase (new 5-stage flow): baseline → kernel_debug →
    vf_test / vector_error_debug / (op_plugin_debug)。regression 阶段已合入
    kernel_debug：修复当前 case 后由 kernel_debug 批跑全量 KernelLaunch 验证。"""
    from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
        BaselineSubstage, KernelDebugSubstage, VfTestSubstage,
        VectorErrorDebugSubstage, OpPluginDebugSubstage,
        _A5_TRANSITION_TABLE, _A5_MAX_CORRECTIVE,
    )
    group = CompositeGroup(
        name="precision_debug",
        children=[
            AtomicStage(BaselineSubstage()),
            AtomicStage(OpPluginDebugSubstage()),
            AtomicStage(KernelDebugSubstage()),
            AtomicStage(VfTestSubstage()),
            AtomicStage(VectorErrorDebugSubstage()),
        ],
        transition_table=_A5_TRANSITION_TABLE,
        output_contract_override=StageIOContract(
            provides=["debug_result", "debug_iterations"]),
        max_corrective=_A5_MAX_CORRECTIVE,
        max_escalations=_A5_MAX_CORRECTIVE,
    )
    group.variant = "a5"
    return group
