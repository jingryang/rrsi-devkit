"""step-88 — diagnose 设计上下文注入 UT。

L3 方案 A（docs/plan/precision-diagnose-design-context/02-analysis.md）：
  - P1：diagnose 认知输入缺「设计」层——`_common_context` 注入 `design_paths`
    （staging 同源单一权威，只含实际存在的文件），`_phase_prompt` 参数区渲染。
  - P2/P3：结构完备性断言（prompt 含断言）+ schema `design_deviation` 字段。
  - 优雅降级：无 workspace / 无 staging（TUI adapter 场景）→ 空 dict、prompt 不渲染设计段。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from ascendc_devkit.domain.operator import OperatorSpec, OperatorIdentity
from ascendc_devkit.domain.requirement import Requirement
from ascendc_devkit.domain.verification import DeployResult
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.stages.precision_debug_substages import (
    DiagnoseSubstage, _design_paths,
)


def _state(tmp_path: Path, workspace=None) -> State:
    return State(
        mode="new",
        op_identity=OperatorIdentity(
            spec=OperatorSpec(name="unique"),
            repo_root=tmp_path,
            op_dir=tmp_path / "op"),
        requirement=Requirement(op_spec=OperatorSpec(name="unique")),
        golden_path=Path("/tmp/golden.py"),
        golden_entry="unique",
        golden_input_type="torch",
        deploy_result=DeployResult(smoke_passed=True),
        design_target_chip="A2",
        _workspace=workspace,
    )


def _ws(tmp_path: Path, with_staging: bool, files: list[str] | None = None):
    artifacts = tmp_path / "artifacts"
    if with_staging:
        staging = artifacts / "staging"
        staging.mkdir(parents=True, exist_ok=True)
        for fn in (files or ["design_spec.json", "tiling_strategy.json",
                             "kernel_architecture.json"]):
            (staging / fn).write_text("{}", encoding="utf-8")
    return SimpleNamespace(dir=tmp_path, artifacts=artifacts)


def _prompt(state: State) -> str:
    s = DiagnoseSubstage()
    ctx = s._common_context(state)
    return s._phase_prompt(ctx, str(ctx.get("operator_dir") or "/tmp"),
                           str(ctx.get("control_path") or "/tmp"),
                           str(ctx.get("phase_json_path") or "/tmp"),
                           str(ctx.get("skill_dir") or "/tmp"), 1)


class TestDesignPaths:
    def test_full_staging_three_files(self, tmp_path):
        ws = _ws(tmp_path, with_staging=True)
        dp = _design_paths(_state(tmp_path, workspace=ws))
        assert dp == {
            "design_spec": str(tmp_path / "artifacts" / "staging" / "design_spec.json"),
            "tiling_strategy": str(tmp_path / "artifacts" / "staging" / "tiling_strategy.json"),
            "kernel_architecture": str(tmp_path / "artifacts" / "staging" / "kernel_architecture.json"),
        }

    def test_partial_staging_only_existing(self, tmp_path):
        ws = _ws(tmp_path, with_staging=True, files=["tiling_strategy.json"])
        dp = _design_paths(_state(tmp_path, workspace=ws))
        assert dp == {"tiling_strategy": str(
            tmp_path / "artifacts" / "staging" / "tiling_strategy.json")}

    def test_no_workspace_empty(self, tmp_path):
        assert _design_paths(_state(tmp_path)) == {}

    def test_no_staging_empty(self, tmp_path):
        ws = _ws(tmp_path, with_staging=False)
        assert _design_paths(_state(tmp_path, workspace=ws)) == {}

    def test_context_carries_design_paths(self, tmp_path):
        ws = _ws(tmp_path, with_staging=True)
        ctx = DiagnoseSubstage()._common_context(_state(tmp_path, workspace=ws))
        assert ctx.get("design_paths") == _design_paths(_state(tmp_path, workspace=ws))


class TestPromptRendering:
    def test_prompt_renders_design_paths(self, tmp_path):
        ws = _ws(tmp_path, with_staging=True)
        prompt = _prompt(_state(tmp_path, workspace=ws))
        staging = tmp_path / "artifacts" / "staging"
        for fn in ("design_spec.json", "tiling_strategy.json",
                   "kernel_architecture.json"):
            assert str(staging / fn) in prompt
        assert "design_paths" in prompt

    def test_prompt_no_design_section_without_staging(self, tmp_path):
        """优雅降级：无 workspace/staging（TUI adapter 场景）不渲染设计参数段。"""
        prompt = _prompt(_state(tmp_path))
        assert "design_paths" not in prompt

    def test_prompt_has_three_layer_cognition(self, tmp_path):
        """三层认知：设计意图 → 实现 → golden，且含「实现与设计偏差」假设方向。"""
        ws = _ws(tmp_path, with_staging=True)
        prompt = _prompt(_state(tmp_path, workspace=ws))
        assert "设计意图" in prompt and "golden" in prompt
        assert "实现与设计偏差" in prompt or "实现 vs 设计偏差" in prompt

    def test_prompt_has_structure_assertion(self, tmp_path):
        """结构完备性断言：与设计一致或记录 design_deviation。"""
        ws = _ws(tmp_path, with_staging=True)
        prompt = _prompt(_state(tmp_path, workspace=ws))
        assert "design_deviation" in prompt
        assert "设计" in prompt and ("一致" in prompt)


class TestSchema:
    def test_design_deviation_field_declared(self):
        skill_schema = (Path(__file__).resolve().parents[3]
                        / ".claude" / "skills" / "ascendc-precision-diagnose"
                        / "schema" / "precision_diagnose.json")
        data = json.loads(skill_schema.read_text(encoding="utf-8"))
        assert "fix_code_log.design_deviation" in data["fields"]
        # 仅 run 外消费（L4 不做清单 1）：描述必须声明 transition 不校验/不路由
        desc = data["fields"]["fix_code_log.design_deviation"]["description"]
        assert "不校验" in desc or "不路由" in desc or "run 外" in desc
