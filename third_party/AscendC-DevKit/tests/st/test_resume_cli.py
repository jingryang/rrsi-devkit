"""ST — resume 的真实 CLI 链路(非 mock):click 解析 --workflow → dispatcher workflow 一致性检查。

这条缝既有的测试都没焊上:
  - tests/ut/cli/test_cli.py 的 CLI 测试全部 mock 掉 dispatch,只测 click 解析;
  - tests/ut/application/test_application.py 的 resume 测试直接构造 task_request dict
    (不经 click),且 mock SDKBackend。
两者都没把「click 给 --workflow 填的默认值」与「dispatcher 的 workflow 冲突校验」
串起来。P30 主修复就栽在这条缝上:click 曾给 --workflow 设 default='generate_ascendc',
导致 resume 不传该参数时也被注入默认值、触发 dispatcher 新加的冲突校验 → resume
不可用。本 ST 用真实 click(CliRunner,不 mock)+ 真实 dispatch(all_done fixture
在 backend 初始化前 return,不跑 LLM/NPU)端到端焊上这条缝。

fixture: tests/fixtures/resume_all_done_state.json —— 合成的 self_evolve_op
all_done 快照(workflow_name=self_evolve_op, node_status={"self_evolve_op":"completed"})。
由 ``State(run_id='fake-resume-all-done', workflow_name='self_evolve_op',
node_status={'self_evolve_op':'completed'}).to_snapshot()`` 合成;若 State schema
变更导致 from_snapshot 读不回,用同样方式重新生成(勿手改)。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from ascendc_devkit.cli.main import main as cli_main

_FIXTURE = (
    Path(__file__).parent.parent / "fixtures" / "resume_all_done_state.json"
)
_RUN_ID = "fake-resume-all-done"


def _materialize_run(tmp_path: Path) -> Path:
    """把归档 fixture 铺成 dispatcher resume 期望的目录布局:
    <output_root>/<run_id>/state_snapshot.json"""
    out_root = tmp_path / "output"
    run_dir = out_root / _RUN_ID
    run_dir.mkdir(parents=True)
    (run_dir / "state_snapshot.json").write_text(_FIXTURE.read_text())
    return out_root


class TestResumeRealCLIWorkflowContract:
    """端到端真实 CLI:resume 的 workflow 选择契约。"""

    def test_resume_without_workflow_succeeds(self, tmp_path):
        """回归:resume 不传 --workflow → click default=None → dispatcher 沿用
        state.workflow_name,走 all_done report 重生成,exit 0。

        P30 bug 下(click default='generate_ascendc')此处会是 EX_USAGE(64) +
        「--workflow 'generate_ascendc' 与 ... 不一致」。
        """
        out_root = _materialize_run(tmp_path)
        result = CliRunner().invoke(cli_main, [
            "run", "--resume", _RUN_ID,
            "--output-root", str(out_root), "--non-interactive",
        ])
        assert result.exit_code == 0, result.output
        assert "不一致" not in result.output
        # 走的是 all_done report 重生成路径(证明确实 resume 进了 state,而非
        # 因为别的什么原因 return 0)
        assert "All stages already completed" in result.output

    def test_resume_conflicting_workflow_returns_usage(self, tmp_path):
        """对称契约:显式 --workflow 与 state.workflow_name 冲突 → 加载期
        EX_USAGE(§1.3),而非静默用错图。"""
        out_root = _materialize_run(tmp_path)
        result = CliRunner().invoke(cli_main, [
            "run", "--resume", _RUN_ID,
            "--workflow", "generate_ascendc",  # 与 state 的 self_evolve_op 冲突
            "--output-root", str(out_root), "--non-interactive",
        ])
        assert result.exit_code == 64, result.output
        assert "不一致" in result.output
