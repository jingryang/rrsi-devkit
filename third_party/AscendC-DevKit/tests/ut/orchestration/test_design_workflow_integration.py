"""P8 (step-2b) — workflow root override + flat_stages (§9.2/9.2.2).

Three workflows mount the design groups via root override (à la full_test);
flat_stages() recursively flattens groups → leaf Stages for validate_chain /
preflight; resume granularity for design groups is the group boundary. Strict TDD.
"""

from ascendc_devkit.orchestration.registry import get_workflow
from ascendc_devkit.orchestration.node import SequentialGroup, node_paths
from ascendc_devkit.orchestration.node_forkjoin import ForkJoinGroup


def _node_names(root):
    return set(node_paths(root).keys())


class TestRootOverrides:
    def test_full_pipeline_mounts_both_groups(self):
        wf = get_workflow("generate_ascendc")
        paths = _node_names(wf.root())
        assert any(p.endswith("/general-design") for p in paths)
        assert any(p.endswith("/detailed-design") for p in paths)
        # downstream codegen still present
        assert any(p.endswith("/codegen") for p in paths)

    def test_se_mounts_only_concept_group(self):
        wf = get_workflow("generate_ascendc_se")
        paths = _node_names(wf.root())
        assert any(p.endswith("/general-design") for p in paths)
        assert not any(p.endswith("/detailed-design") for p in paths)
        # SE stops before codegen (job boundary)
        assert not any(p.endswith("/codegen") for p in paths)

    def test_dev_mounts_both_groups(self):
        wf = get_workflow("generate_ascendc_dev")
        paths = _node_names(wf.root())
        assert any(p.endswith("/general-design") for p in paths)
        assert any(p.endswith("/detailed-design") for p in paths)


class TestFlatStages:
    def test_flat_stages_recurses_into_groups(self):
        wf = get_workflow("generate_ascendc")
        names = [s.name for s in wf.flat_stages()]
        # group leaves are surfaced
        assert "general-design-generator" in names
        assert "template-division" in names
        assert "integrate" in names
        # group container names are NOT leaves
        assert "general-design" not in names
        assert "detailed-design" not in names

    def test_validate_chain_uses_flat_view_no_missing(self):
        wf = get_workflow("generate_ascendc")
        warnings = wf.validate_chain()
        # design group leaves' requires (general_design, tiling_results...) are
        # produced within the group → not reported as missing.
        joined = " ".join(warnings)
        assert "general_design" not in joined
        assert "tiling_results" not in joined


class TestPipelineCrossGroupRoutes:
    def test_pipeline_table_has_group_routes(self):
        wf = get_workflow("generate_ascendc")
        table = wf._get_transition_table()
        # general-design: design_input_invalid → requirement (escalation).
        # step-79: design_needs_human→halt REMOVED — GD-H* resolved via in-flow
        # resolve_ambiguity or forward-escape as known_issue; design gates don't
        # halt (aligns with step-60 + P83 detailed-design escape hatch). A concept
        # that fails to produce goes via output_contract unsatisfied / stage
        # fail_strategy, not a design halt.
        assert table["general-design"]["design_input_invalid"][0] == "requirement"
        assert "design_needs_human" not in table["general-design"]
        # P83 (step-58): detailed-design escapes forward — validate's redo_doc/
        # human/redo_general now resolve at the group level (group completed →
        # codegen, carrying design_known_issues), so the group never bubbles a
        # condition and intentionally has NO pipeline routes here (§1.4/§2.5:
        # no dead config).
        assert "detailed-design" not in table


class TestAscendCSTDesignForwardEscape:
    """M1 决策守护：ascendc-st-design 是「生成验收用例」而非设计子阶段——耗竭时
    前逃 codegen_init（fail_strategy=continue），不继承 _DesignSubstage 的 halt。

    旧 test_design CompositeGroup 在三步 LLM 链时耗竭 halt（skill 输出不可自愈）。
    新单 AtomicStage 的 6/8 步是确定性脚本，耗竭概率大降；且空 cases 由 codegen
    safe defaults / deploy synthetic probe 兜底，halt 整条链的代价大于收益
    （方案文档「统一前逃到 codegen_init」）。§1.10：判据是业务语义（测试设计可
    重试/兜底），不是机制特征。"""

    def test_stage_fail_strategy_is_continue(self):
        from ascendc_devkit.orchestration.stages.ascendc_st_design import (
            AscendCSTDesignStage,
        )
        assert AscendCSTDesignStage.fail_strategy == "continue", (
            "ascendc-st-design 必须 fail_strategy=continue（耗竭前逃 codegen_init），"
            "不得继承 _DesignSubstage 的 halt（M1 决策）")

    def test_no_pipeline_route_for_ascendc_st_design(self):
        """耗竭 → resolve_condition 返回 exhausted → 顶层无路由 → route=None →
        线性前逃。三条 workflow 均不应有 ascendc-st-design 的 explicit 路由。"""
        for wf_name in ("generate_ascendc", "generate_ascendc_dev",
                        "self_evolve_op"):
            wf = get_workflow(wf_name)
            table = wf._get_transition_table()
            assert "ascendc-st-design" not in table, (
                f"{wf_name} 不应给 ascendc-st-design 配 explicit 路由——"
                "耗竭应走 route=None 线性前逃 codegen_init（M1 决策）")
            assert "test_design" not in table, (
                f"{wf_name} 不应残留旧 test_design 路由（§2.5 唯一通路）")
