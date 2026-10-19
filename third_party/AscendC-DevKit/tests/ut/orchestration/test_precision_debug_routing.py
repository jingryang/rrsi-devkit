"""P0 (51-*.md) — precision_debug routing + mounting, post-CompositeGroup.

precision_debug is now a CompositeGroup (5 children including §12.1 scope_guard),
not a flat @register_stage Stage. This file guards:
  - the root TRANSITION_TABLE invariants the group relies on: exhausted soft-gates
    to cannbench_adapt (self_evolve_op) / hard-halts (generate_ascendc); upstream
    always halts (§12.1); passed is absent (linear successor). The group escalates
    passed/exhausted/upstream via ``__escalate__`` and the root table routes it
    (runlog 冲突1).
  - the group is mounted in the root tree between codegen and cannbench_adapt
    (position invariant), and is NOT a flat registered stage.

verify is gone (P57 能力下沉); precision_debug owns precision in-session.
"""

from __future__ import annotations

from ascendc_devkit.orchestration.node import node_paths
from ascendc_devkit.orchestration.workflow import (
    GenerateAscendCWorkflow, SelfEvolveOpWorkflow, _SELF_EVOLVE_STAGE_NAMES,
)


class TestPrecisionDebugRouting:
    """Root TRANSITION_TABLE invariants the precision_debug group escalates into."""

    @property
    def table(self):
        return SelfEvolveOpWorkflow.TRANSITION_TABLE

    def test_route_debug_exhausted_soft_gate(self):
        """self_evolve_op 软门：group escalates exhausted → cannbench_adapt（① 本地预检
        不阻断 ② 权威评分；止损降级为 score）。group 不 loopback 到 codegen。"""
        assert self.table["precision_debug"]["exhausted"] == ("cannbench_adapt", "validation")

    def test_debug_default_not_listed_uses_linear_successor(self):
        """passed → escalate 'passed' → root has no 'passed' entry → linear successor
        cannbench_adapt (self_evolve_op) / perf (generate_ascendc)."""
        assert "default" not in self.table.get("precision_debug", {})
        assert "passed" not in self.table.get("precision_debug", {})

    def test_generate_ascendc_exhausted_hard_halt(self):
        """generate_ascendc 无 ② 评分器：precision_debug exhausted → __halt__（保留旧硬止损）。
        runlog 冲突1：若组内用 __halt__ 则 precision 通过即 halt 整条流水线——错；改为 escalate
        + root 按各 workflow 自身策略路由。"""
        assert GenerateAscendCWorkflow.TRANSITION_TABLE["precision_debug"]["exhausted"] == (
            "__halt__", "escalation")

    def test_no_verify_in_table(self):
        """P57: verify 删除后 TRANSITION_TABLE 无 verify 分支（§1.4/§2.5 无死路）。"""
        assert "verify" not in self.table


class TestPrecisionDebugGroupMounting:
    """precision_debug is a CompositeGroup mounted in the root tree, not a flat stage."""

    def test_not_in_flat_stage_names(self):
        """precision_debug is a group (like test_design), so it is NOT in the flat
        instantiable stage-name list — it is mounted via the root override."""
        assert "precision_debug" not in _SELF_EVOLVE_STAGE_NAMES

    def test_codegen_before_group_before_cannbench_adapt_in_root(self):
        """Position invariant: the group sits in the root tree between codegen and
        cannbench_adapt (codegen 产码 → 会话内 precision_debug run-cases 即首量门 → ②)."""
        w = SelfEvolveOpWorkflow()
        paths = list(node_paths(w.root()))
        full = "/".join(p for p in paths)  # not used; index by name below
        names_in_order = []
        for p in paths:
            short = p.split("/")[-1]
            if short in ("codegen", "precision_debug", "cannbench_adapt"):
                names_in_order.append(short)
        i_codegen = names_in_order.index("codegen")
        i_debug = names_in_order.index("precision_debug")
        i_adapt = names_in_order.index("cannbench_adapt")
        assert i_codegen < i_debug < i_adapt

    def test_group_has_two_substages_in_root_tree(self):
        """P3 减法: precision_debug group has 2 top-level substages (run_tests ⇄ diagnose)。
        scope_guard/bounds_check/printf/comment_bisect/diagnose_refine 已删。"""
        w = SelfEvolveOpWorkflow()
        paths = node_paths(w.root())
        sub = [p for p in paths if p.startswith("self_evolve_op/precision_debug/")]
        assert sorted(p.split("/")[-1] for p in sub) == [
            "diagnose", "run_tests"]

    def test_no_deploy_verify_in_stage_names(self):
        """P57: deploy/verify 不在 _SELF_EVOLVE_STAGE_NAMES（能力下沉，类已删）。"""
        assert "deploy" not in _SELF_EVOLVE_STAGE_NAMES
        assert "verify" not in _SELF_EVOLVE_STAGE_NAMES

    def test_upstream_halts_in_all_workflows(self):
        """§12.1: upstream defect escalates to __halt__ in every workflow."""
        from ascendc_devkit.orchestration.workflow import GenerateAscendCDevWorkflow
        for wf_cls in [SelfEvolveOpWorkflow, GenerateAscendCWorkflow,
                       GenerateAscendCDevWorkflow]:
            pd_entry = wf_cls.TRANSITION_TABLE["precision_debug"]
            assert "upstream" in pd_entry, f"{wf_cls.__name__} missing upstream"
            assert pd_entry["upstream"][0] == "__halt__", (
                f"{wf_cls.__name__} upstream must halt to __halt__")

    def test_stalled_halts_in_all_workflows(self):
        """§judgment-ownership (P5): stalled（diagnose 尽力后假设空间穷尽）→ __halt__
        交人，在 every workflow。与 upstream 同路径——模型尽力但修不动，需人工/上游
        接续，不该静默走 eval 评分或继续 retry。"""
        from ascendc_devkit.orchestration.workflow import GenerateAscendCDevWorkflow
        for wf_cls in [SelfEvolveOpWorkflow, GenerateAscendCWorkflow,
                       GenerateAscendCDevWorkflow]:
            pd_entry = wf_cls.TRANSITION_TABLE["precision_debug"]
            assert "stalled" in pd_entry, f"{wf_cls.__name__} missing stalled"
            assert pd_entry["stalled"][0] == "__halt__", (
                f"{wf_cls.__name__} stalled must halt to __halt__")

    def test_stalled_not_soft_gate_in_self_evolve(self):
        """SelfEvolve 的 exhausted 走 cannbench_adapt 软门（预算耗尽止损评分），但
        stalled 必须 __halt__——模型判断「修不动需人工」，不该静默走 eval 评分。"""
        pd_entry = SelfEvolveOpWorkflow.TRANSITION_TABLE["precision_debug"]
        assert pd_entry["exhausted"][0] == "cannbench_adapt"  # 软门保留
        assert pd_entry["stalled"][0] == "__halt__"  # stalled 硬 halt
