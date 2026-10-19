"""ST — ascendc-st-design stage end-to-end via GraphExecutor + stub.

Stub mode (no NPU / no real CANN): a stub generator backend drives the single
``ascendc-st-design`` stage, which wraps the ``ascendc-st-design`` skill.
The stub writes the merged CSV (+ design md) into the working dir; the
CSV→TestCase adapter normalizes it into state.test_cases.

Replaces the old 3-substage test_design e2e test (test-analyze →
test-casedesign → test-casegen CompositeGroup).
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest

from ascendc_devkit.capabilities.agent.backend import AgentBackend, AgentResult
from ascendc_devkit.orchestration.kernel.runner import Runner
from ascendc_devkit.orchestration.graph_executor import GraphExecutor
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.node import AtomicStage, SequentialGroup
from ascendc_devkit.orchestration.registry import get_stage, _ensure_stages_loaded
from ascendc_devkit.orchestration.design_tree import build_ascendc_st_design_node
from ascendc_devkit.domain.requirement import Requirement, TestCase
from ascendc_devkit.infra.workspace import Workspace


_COLS = [
    "testcase_name", "op_name", "stc_input_dtypes", "other_compilation_params",
    "stc_inputs", "output_dtypes", "stc_outputs", "stc_input_formats",
    "output_formats", "stc_op_name", "input_data_ranges", "absolute_precision",
    "error_message",
]
_ROW = {
    "testcase_name": "add_8_24576_bf16_L1_boundary_000001",
    "op_name": "add",
    "stc_input_dtypes": "('bfloat16', 'bfloat16')",
    "stc_inputs": "((1, 8, 24576), (1, 8, 24576))",
    "stc_input_formats": "('ND', 'ND')",
    "stc_op_name": "add",
    "absolute_precision": "0.001",
}


def _csv_bytes(*rows) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=_COLS, quoting=csv.QUOTE_ALL)
    w.writeheader()
    for r in rows:
        w.writerow({c: r.get(c, "") for c in _COLS})
    return buf.getvalue()


class _SingleStageStub(AgentBackend):
    """Drives the single ``ascendc-st-design`` stage.

    Writes the merged 13-column CSV + design md into the working dir,
    mirroring what the real agent (running the ascendc-st-design skill)
    would produce at step 9.
    """

    def __init__(self, emit_csv: bool = True):
        self.emit_csv = emit_csv

    def spawn(self, agent_name, prompt, context, skills=None,
              model=None, working_dir=None, repo_baseline=None, repo_root=None,
              stage_name="", branch_label="", resume_session_id=None,
              resume_prompt=None, primary_skill=None,
              deadline_monotonic: float | None = None):
        if stage_name == "ascendc-st-design" and self.emit_csv and working_dir:
            wd = Path(working_dir)
            wd.mkdir(parents=True, exist_ok=True)
            (wd / "add测试用例_合并.csv").write_text(
                _csv_bytes(_ROW), encoding="utf-8-sig")
            (wd / "算子测试设计方案_设计版.md").write_text(
                "# add 测试设计方案\n", encoding="utf-8")
        return AgentResult(agent_name=agent_name, status="ok", artifacts={})


@pytest.fixture(autouse=True)
def _stages():
    _ensure_stages_loaded()


def _seed_state(ws, cases_path=None) -> State:
    # §3.12: 各设计 stage 从磁盘权威 requirement.json 物化（不从 State 序列化
    # reduced dataclass）。State 里放了 requirement → 权威磁盘文件必须可达，
    # 否则 materialize_authoritative_requirement 拿不到全量需求（warn + 不落
    # reduced）→ 输入物化缺失。fixture 同步写权威文件。
    req_dir = ws.artifacts / "requirement"
    req_dir.mkdir(parents=True, exist_ok=True)
    (req_dir / "requirement.json").write_text(json.dumps({
        "op_name": "add",
        "aclnn_name": "aclnnAdd",
        "mutation_mode": "out_of_place",
        "inputs": [{"name": "x", "dtype": "float16", "shape": ["N"]}],
        "outputs": [{"name": "y", "dtype": "float16", "shape": ["N"]}],
        "domain": {"inputs": [{"name": "x",
                               "dtypes": ["float16", "float32"]}]},
    }, ensure_ascii=False), encoding="utf-8")
    return State.empty().with_updates(
        non_interactive=True,
        requirement=Requirement.from_dict({"op": {"name": "add"}}),
        design_spec={"op_name": "add", "inputs": [], "outputs": []},
        tiling_strategy={"approach": "elementwise"},
        kernel_architecture={"host_code": {}, "kernel_code": {}},
        cases_path=cases_path,
    ).with_field("_workspace", ws)


def _run_test_design(tmp_path, emit_csv=True, cases_path=None) -> State:
    ws = Workspace.create(output_root=str(tmp_path / "out"), run_id="r1")
    state = _seed_state(ws, cases_path=cases_path)
    root = build_ascendc_st_design_node()
    runner = Runner(agent_backend=_SingleStageStub(emit_csv=emit_csv),
                    workspace=ws)
    return GraphExecutor(runner=runner).execute(root, state)


class TestAscendCSTDesignProducesCases:
    def test_state_test_cases_populated(self, tmp_path):
        out = _run_test_design(tmp_path, emit_csv=True)
        assert out.test_cases is not None
        assert len(out.test_cases) == 1
        tc = out.test_cases[0]
        assert isinstance(tc, TestCase)
        assert tc.name == "add_8_24576_bf16_L1_boundary_000001"
        assert tc.inputs[0]["shape"] == [1, 8, 24576]
        assert tc.expected == {"max_diff": 0.001}

    def test_report_path_recorded(self, tmp_path):
        out = _run_test_design(tmp_path, emit_csv=True)
        assert out.test_design_report is not None
        assert Path(out.test_design_report).name == "算子测试设计方案_设计版.md"


class TestLocateCsvM5:
    """M5 回归守护：_locate_csv/_locate_report 按确定性优先级选 wd 根产物，
    不靠 mtime 猜，也不扫子目录中间产物（design/testcases）。"""

    def test_prefers_canonical_merged_name(self, tmp_path):
        from ascendc_devkit.orchestration.stages.ascendc_st_design import (
            AscendCSTDesignStage,
        )
        wd = tmp_path / "wd"
        wd.mkdir(parents=True)
        # 多个候选：根目录精确名 + 带迭代后缀的陈旧合并 CSV
        (wd / "合并_测试用例.csv").write_text("a\n", encoding="utf-8")
        (wd / "合并_测试用例_v2.csv").write_text("b\n", encoding="utf-8")
        # 子目录里的中间产物（L0/L1/L2 单级 CSV）不得被选中
        (wd / "testcases").mkdir()
        (wd / "testcases" / "add_l0_test_cases.csv").write_text(
            "c\n", encoding="utf-8")
        picked = AscendCSTDesignStage._locate_csv(wd)
        assert picked is not None and picked.name == "合并_测试用例.csv", (
            "必须选根目录的精确合并文件名，而非带后缀变体或子目录中间产物（M5）")

    def test_ignores_subdir_intermediate_csv(self, tmp_path):
        from ascendc_devkit.orchestration.stages.ascendc_st_design import (
            AscendCSTDesignStage,
        )
        wd = tmp_path / "wd"
        (wd / "design").mkdir(parents=True)
        (wd / "testcases").mkdir(parents=True)
        # 只有子目录里有 CSV（中间产物），根目录没有 → 返回 None，不得选中子目录
        (wd / "design" / "07_因子值.csv").write_text("x\n", encoding="utf-8")
        (wd / "testcases" / "add_l0_test_cases.csv").write_text("x\n",
                                                                encoding="utf-8")
        assert AscendCSTDesignStage._locate_csv(wd) is None, (
            "子目录中间产物不得被当成合并 CSV（M5）")

    def test_fallback_to_merged_substring_in_root(self, tmp_path):
        from ascendc_devkit.orchestration.stages.ascendc_st_design import (
            AscendCSTDesignStage,
        )
        wd = tmp_path / "wd"
        wd.mkdir(parents=True)
        # 变体命名（stub 场景 add测试用例_合并.csv）在根目录 → 按「合并」子串命中
        (wd / "add测试用例_合并.csv").write_text("x\n", encoding="utf-8")
        picked = AscendCSTDesignStage._locate_csv(wd)
        assert picked is not None and picked.name == "add测试用例_合并.csv"

    def test_report_prefers_canonical_name(self, tmp_path):
        from ascendc_devkit.orchestration.stages.ascendc_st_design import (
            AscendCSTDesignStage,
        )
        wd = tmp_path / "wd"
        wd.mkdir(parents=True)
        (wd / "测试设计方案.md").write_text("# t\n", encoding="utf-8")
        (wd / "测试设计方案_旧.md").write_text("# old\n", encoding="utf-8")
        picked = AscendCSTDesignStage._locate_report(wd)
        assert picked is not None and picked.name == "测试设计方案.md", (
            "报告必须选精确文件名，而非陈旧变体（M5）")

    def test_no_error_on_success(self, tmp_path):
        assert _run_test_design(tmp_path, emit_csv=True).last_error is None

    def test_cases_source_is_devkit(self, tmp_path):
        out = _run_test_design(tmp_path, emit_csv=True)
        assert out.cases_source == "devkit"

    def test_input_adapter_generates_param_def_before_spawn(self, tmp_path):
        """B1 回归守护：LLM 路径 spawn 前，convert_to_param_def.py 必须真实跑过并
        在 wd 生成 design/03_参数定义.yaml（skill DESIGN_DIR 约定）。

        曾因 `parents[6]` 定位错仓库根 → 脚本路径恒不存在 → 输入适配静默永不执行，
        agent 被 prompt 告知「03_参数定义.yaml 已生成」实际却没有。本测试断言：
        1) wd 里有 requirement.json / design_spec.json（先物化再跑脚本，顺序对）；
        2) design/03_参数定义.yaml 存在且含 aclnn_name（转换真实发生）。"""
        from ascendc_devkit.orchestration.registry import get_stage

        ws = Workspace.create(output_root=str(tmp_path / "out"), run_id="r1")
        state = _seed_state(ws)
        stage = get_stage("ascendc-st-design")()
        actions = stage.actions(state, 1)
        assert any(a.__class__.__name__ == "SpawnAgent" for a in actions), (
            "LLM 路径必须 spawn agent")
        wd = ws.artifacts / "test_design"
        assert (wd / "requirement.json").exists(), "输入物化必须先于转换脚本（顺序回归）"
        assert (wd / "design_spec.json").exists(), "输入物化必须先于转换脚本（顺序回归）"
        param_def = wd / "design" / "03_参数定义.yaml"
        assert param_def.exists(), (
            "convert_to_param_def.py 未真实执行——仓库根定位、执行顺序或输出位置"
            "（design/ 约定）回归（B1/M2）")
        assert "aclnn_name:" in param_def.read_text(encoding="utf-8")


class TestFailureDoesNotPollute:
    def test_no_csv_records_error_and_no_cases(self, tmp_path):
        out = _run_test_design(tmp_path, emit_csv=False)
        assert out.test_cases is None
        assert out.last_error is not None
        assert out.last_error.stage_name == "ascendc-st-design"

    def test_exhausted_does_not_halt(self, tmp_path):
        """耗竭语义（M1 拍板）：test_design 耗竭（预算内无 CSV）→ fail_strategy=
        continue → 不 halt（is_terminal=False、无 _stage_failed 信号）→
        resolve_condition 返回 exhausted → 顶层无路由 → 线性前逃 codegen_init。
        与方案文档「统一前逃到 codegen_init」一致；区别于旧设计子阶段的 halt
        （设计产物错误不可自愈 vs 空 cases 由 deploy synthetic probe 兜底，
        §1.10 业务语义显式声明）。"""
        from ascendc_devkit.orchestration.kernel.runner import Runner as _R

        ws = Workspace.create(output_root=str(tmp_path / "out"), run_id="r1")
        state = _seed_state(ws).with_updates(
            stage_iterations={"ascendc-st-design": 2})  # at max
        root = SequentialGroup(
            name="t",
            children=[build_ascendc_st_design_node(),
                      AtomicStage(get_stage("codegen_init")())],
            max_corrective=100, max_escalations=100)
        runner = _R(agent_backend=_SingleStageStub(emit_csv=False),
                     workspace=ws)
        out = GraphExecutor(runner=runner).execute(root, state)

        assert out.test_cases is None
        assert out.last_error is not None
        # 前逃：不 halt——is_terminal=False、无 halt 信号（fail_strategy=continue）
        assert out.is_terminal is False, (
            "test_design 耗竭不得 halt（is_terminal 必须 False）——M1 决策："
            "空 cases 由 codegen safe defaults / deploy synthetic probe 兜底，"
            "fail_strategy=continue 前逃 codegen_init")
        assert out._stage_failed is None, (
            "test_design 耗竭不得触发 _stage_failed halt 信号")
        # 前逃生效：codegen_init 被跑到（确定性 stage，无 agent 也记录迭代）
        assert "codegen_init" in out.stage_iterations, (
            "test_design 耗竭后必须线性前逃到 codegen_init（M1 决策）")


# —— external cases_path 增量融合（P34：cann-bench ∪ LLM，非互斥） ——


def _write_cann_bench_cases_csv(tmp_path) -> Path:
    """写一份最小 cann-bench cases.csv 并返回绝对路径（13 E1：cases 是用户
    显式 CLI 路径，非 profile 模板）。"""
    p = tmp_path / "cases.csv"
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["operator", "case_id", "input_shape", "dtype", "attrs",
                "value_range", "note"])
    w.writerow(["Exp", "1", "[[1024, 1024]]", '["float16"]',
                '{"scale": 1.5}', "[-1, 1]", "scale=1.5"])
    w.writerow(["Exp", "2", "[[2048, 2048]]", '["float32"]',
                '{"scale": 2.0}', "[-2, 2]", "scale=2.0"])
    p.write_text(buf.getvalue(), encoding="utf-8")
    return p


class TestExternalCasesIncremental:
    """P34 增量融合（取代旧的互斥短路语义）：外部 cann-bench cases 不再是
    「有则跳过整条 LLM 链」的互斥开关。有 workspace 时 st-design LLM 照常执行，
    其产物作为外部 cases 的**补充**融合（外部在前、生成为补充，``cases_source``
    仍为 ``cannbench`` 以保持 benchmark 标准对齐）；无 workspace 时 LLM 无法跑
    （无 CWD 落产物），退化为确定性加载外部 cases 的 standalone 路径。"""

    def test_spawns_supplement_with_workspace(self, tmp_path):
        ws = Workspace.create(output_root=str(tmp_path / "out"), run_id="r1")
        state = _seed_state(
            ws, cases_path=_write_cann_bench_cases_csv(tmp_path))
        actions = get_stage("ascendc-st-design")().actions(state, iteration=1)
        assert any(a.__class__.__name__ == "SpawnAgent" for a in actions), (
            "有 workspace 且有外部 cases 时必须仍 spawn agent（增量补充，P34）")
        assert not any(a.__class__.__name__ == "NoOp" for a in actions)

    def test_merges_external_and_generated(self, tmp_path):
        """外部 2 条 + LLM 生成 1 条 → 融合为 3 条，外部在前。"""
        out = _run_test_design(
            tmp_path, emit_csv=True,
            cases_path=_write_cann_bench_cases_csv(tmp_path))
        assert out.test_cases is not None and len(out.test_cases) == 3, (
            "外部 cases 与 LLM 生成用例必须融合（P34 cann-bench ∪ LLM）")
        assert out.test_cases[0].name.startswith("Exp_"), (
            "外部 cases 应排在前（主源）")
        assert out.test_cases[-1].name == "add_8_24576_bf16_L1_boundary_000001", (
            "LLM 生成用例作为补充排在外部之后")
        assert out.cases_source == "cannbench", (
            "存在外部 cann-bench cases → 融合集仍按 cann-bench 标准对齐")
        assert out.last_error is None

    def test_prompt_carries_incremental_hint(self, tmp_path):
        ws = Workspace.create(output_root=str(tmp_path / "out"), run_id="r1")
        state = _seed_state(
            ws, cases_path=_write_cann_bench_cases_csv(tmp_path))
        sections = get_stage("ascendc-st-design")()._extra_prompt_sections(state)
        assert sections and "增量补充" in sections[0], (
            "外部 cases 存在时 prompt 须提示 LLM 做增量补充而非另起炉灶")
        assert str(state.cases_path) in sections[0]

    def test_external_cases_survive_llm_failure(self, tmp_path):
        """LLM 补充未产出（emit_csv=False）但有外部 cases → 以外部 cases 交付，
        不阻断，留 user_feedback 可观测信号（§1.2）。"""
        out = _run_test_design(
            tmp_path, emit_csv=False,
            cases_path=_write_cann_bench_cases_csv(tmp_path))
        assert out.test_cases is not None and len(out.test_cases) == 2
        assert out.cases_source == "cannbench"
        assert out.last_error is None
        assert "外部 cann-bench cases 已加载" in (out.user_feedback or ""), (
            "外部主源已交付、LLM 补充缺失须留可观测信号")

    def test_empty_external_with_generated_uses_devkit(self, tmp_path):
        """外部 cases 为空 + LLM 有产物 → 以 LLM 产物交付（cases_source=devkit）。"""
        p = tmp_path / "empty.csv"
        p.write_text(
            "operator,case_id,input_shape,dtype,attrs,value_range,note\n",
            encoding="utf-8")
        out = _run_test_design(tmp_path, emit_csv=True, cases_path=p)
        assert out.test_cases is not None and len(out.test_cases) == 1
        assert out.cases_source == "devkit"
        assert out.last_error is None

    def test_no_workspace_loads_external_deterministically(self, tmp_path):
        """无 workspace + 外部 cases → NoOp(contract_satisfied)（LLM 无法跑），
        transition 确定性加载外部 cases。"""
        from ascendc_devkit.orchestration.kernel.action import NoOp
        s = _seed_state_plain(tmp_path).with_updates(
            cases_path=_write_cann_bench_cases_csv(tmp_path))
        actions = get_stage("ascendc-st-design")().actions(s, iteration=1)
        assert actions and isinstance(actions[0], NoOp), (
            "无 workspace 时无法跑 LLM，外部 cases 走确定性加载（NoOp）")
        assert actions[0].contract_satisfied is True, (
            "NoOp 必须 contract_satisfied=True，否则 runner 在 output_contract "
            "未满足上死循环（P33 语义）")
        out = get_stage("ascendc-st-design")().transition(s, {})
        assert out.test_cases is not None and len(out.test_cases) == 2
        assert [tc.attrs["scale"] for tc in out.test_cases] == [1.5, 2.0], (
            "外部 cases 的 attrs 必须透传（cann-bench 非默认分支对齐）")
        assert out.cases_source == "cannbench"
        assert out.last_error is None

    def test_spawns_when_no_cases_path(self, tmp_path):
        """无 cases_path → 既有 LLM spawn（generate_ascendc 等无 cases 工作流
        保留 LLM 测试设计链）。"""
        s = _seed_state_plain(tmp_path)
        actions = get_stage("ascendc-st-design")().actions(s, iteration=1)
        assert any(a.__class__.__name__ == "SpawnAgent" for a in actions), (
            "无 cases_path 时必须 spawn agent（LLM 路径）")

    def test_empty_external_and_no_generated_records_error(self, tmp_path):
        """外部 cases 空 + 无 LLM 产物 → 合并仍空 → 记 last_error，不静默放行。"""
        p = tmp_path / "empty.csv"
        p.write_text("operator,case_id,input_shape,dtype,attrs,value_range,note\n",
                     encoding="utf-8")
        s = _seed_state_plain(tmp_path).with_updates(cases_path=p)
        out = get_stage("ascendc-st-design")().transition(s, {})
        assert out.test_cases is None
        assert out.last_error is not None
        assert out.last_error.stage_name == "ascendc-st-design"


def _seed_state_plain(tmp_path) -> State:
    """无 workspace 的最小 state（外部 cases 路径不需要 _workspace）。"""
    return State.empty().with_updates(
        non_interactive=True,
        requirement=Requirement.from_dict({"op": {"name": "Exp"}}),
    )
