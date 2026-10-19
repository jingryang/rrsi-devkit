"""P54 D11 — CLI ``redeploy`` / ``run-cases`` (L4 绿-C 用例 4-5).

守护 D11：debug agent 经 CLI 调 deploy/case-run，CLI 是 L1 薄壳，逻辑全在 L2
``DebugService``（§1.1 分层：L1 → L2 → L3；L1 不直接 import 编排/adapter 内部）。
mock ``Deployer`` / ``run_precision_cases``（不真跑 build/NPU——真实链路属
heavy_llm §3.11，由 e2e ST 守护）。

- 用例 4：``redeploy`` 经 ``DebugService`` 调 ``Deployer.deploy``，per-op 安装，
  输出 DeployResult 摘要 + 落盘 ``last_deploy.json``（供 run-cases 文件接力 §2.3）。
- 用例 5：``run-cases`` 经 ``DebugService`` 调 ``run_precision_cases``（L3 共享
  单一 runner 装配路径，§2.5），输出 max_diff + per-case diff + dumptensor 日志
  路径（落盘 D7）。
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from unittest import mock

import pytest
from click.testing import CliRunner

from ascendc_devkit.cli.main import main as cli_main
from ascendc_devkit.domain.operator import OperatorIdentity, OperatorSpec
from ascendc_devkit.domain.requirement import Requirement, TestCase
from ascendc_devkit.domain.verification import DeployResult


def _make_run_dir(tmp_path: Path, op_name: str = "gelu") -> Path:
    """Create a run dir with a minimal state_snapshot.json (read by the CLI)."""
    run_dir = tmp_path / "output" / "run-001"
    (run_dir / "artifacts").mkdir(parents=True)
    op_dir = tmp_path / "ops" / op_name
    op_dir.mkdir(parents=True)
    from ascendc_devkit.orchestration.kernel.state import State
    state = State.empty().with_updates(
        op_name=op_name,
        op_identity=OperatorIdentity(
            spec=OperatorSpec(name=op_name),
            repo_root=tmp_path, op_dir=op_dir,
        ),
        requirement=Requirement(op_spec=OperatorSpec(name=op_name)),
        design_target_chip="A2",
        npu_id=0,
        golden_path=Path("/tmp/golden.py"),
        golden_entry="golden",
        golden_input_type="torch",
        codegen_manifest={"callable_target": {
            "kind": "torch_op", "symbol": f"torch.ops.custom.{op_name}"}},
        test_cases=[
            TestCase(name="t0"),
            TestCase(name="t1"),
        ],
    )
    (run_dir / "state_snapshot.json").write_text(
        json.dumps(state.to_snapshot(), default=str), encoding="utf-8")
    return run_dir


@pytest.fixture
def runner():
    return CliRunner()


class TestRedeployCli:
    """用例 4: redeploy → Deployer.deploy + 摘要 + last_deploy.json 落盘。"""

    @mock.patch("ascendc_devkit.application.debug_service.Deployer")
    def test_redeploy_calls_deployer_and_outputs_summary(
        self, mock_deployer_cls, runner, tmp_path,
    ):
        deploy_result = DeployResult(
            smoke_passed=True, install_path="/opp/gelu",
            python_path="/py/gelu", run_package="/dist/x.run",
            wheel_package="/dist/x.whl",
        )
        mock_deployer_cls.return_value.deploy.return_value = (deploy_result, None)

        run_dir = _make_run_dir(tmp_path)
        result = runner.invoke(cli_main, ["redeploy", "--workspace", str(run_dir)])

        assert result.exit_code == 0, result.output
        # routed to Deployer.deploy with the snapshot's op context
        mock_deployer_cls.return_value.deploy.assert_called_once()
        state_arg = mock_deployer_cls.return_value.deploy.call_args.args[0]
        assert state_arg.op_name == "gelu"
        # output contract: DeployResult summary
        assert "smoke_passed: True" in result.output
        assert "install_path: /opp/gelu" in result.output
        assert "python_path: /py/gelu" in result.output
        # file handoff (§2.3): last_deploy.json written for run-cases
        last_deploy = run_dir / "artifacts" / "debug" / "gelu" / "last_deploy.json"
        assert last_deploy.exists()
        assert json.loads(last_deploy.read_text())["install_path"] == "/opp/gelu"

    @mock.patch("ascendc_devkit.application.debug_service.Deployer")
    def test_redeploy_surfaces_deploy_error_and_exits_nonzero(
        self, mock_deployer_cls, runner, tmp_path,
    ):
        from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
        err = ErrorFeedback(
            stage_name="deploy", error_type="deploy_failed",
            message="deploy step 'build' failed: boom",
            details={"step": "build", "stderr": "boom"},
        )
        mock_deployer_cls.return_value.deploy.return_value = (
            DeployResult(smoke_passed=False), err)

        run_dir = _make_run_dir(tmp_path)
        result = runner.invoke(cli_main, ["redeploy", "--workspace", str(run_dir)])

        assert result.exit_code == 1
        assert "boom" in result.output


class TestRunCasesCli:
    """用例 5: run-cases → NPURunner.execute + max_diff/per-case/logpath 输出。"""

    def _seed_last_deploy(self, run_dir: Path, op_name: str = "gelu") -> Path:
        debug_dir = run_dir / "artifacts" / "debug" / op_name
        debug_dir.mkdir(parents=True, exist_ok=True)
        last = DeployResult(
            smoke_passed=True, install_path="/opp/gelu",
            python_path="/py/gelu", ld_library_path_add="/opp/gelu/lib",
        )
        (debug_dir / "last_deploy.json").write_text(
            json.dumps(dataclasses.asdict(last)), encoding="utf-8")
        return debug_dir

    @mock.patch("ascendc_devkit.application.debug_service.run_precision_cases")
    def test_run_cases_outputs_diff_and_logpath(
        self, mock_run, runner, tmp_path,
    ):
        mock_run.return_value = {
            "passed": False,
            "max_diff": 0.5,
            "per_shape": {"t0": 0.5, "t1": 0.1},
            "actual_ms": 1.2,
            "bottleneck": "real_kernel_vs_golden",
        }

        run_dir = _make_run_dir(tmp_path)
        self._seed_last_deploy(run_dir)
        result = runner.invoke(cli_main, [
            "run-cases", "--workspace", str(run_dir), "--iter", "1"])

        assert result.exit_code == 0, result.output
        # routed to run_precision_cases (shared L3 path, §2.5) with the fresh
        # deploy_result + callable_target + log_dir
        mock_run.assert_called_once()
        kwargs = mock_run.call_args.kwargs
        assert kwargs["deploy_result"].install_path == "/opp/gelu"
        assert kwargs["callable_target"]["symbol"] == "torch.ops.custom.gelu"
        # D7: log_dir lands in <run>/artifacts/debug/<op>/iter-N/
        assert str(kwargs["log_dir"]).endswith(
            f"artifacts/debug/gelu/iter-1")
        # output contract: max_diff + per-case + log path
        assert "max_diff: 0.5" in result.output
        assert "t0: 0.5" in result.output
        assert "t1: 0.1" in result.output
        assert "log:" in result.output
        assert "iter-1/run.log" in result.output

    @mock.patch("ascendc_devkit.application.debug_service.run_precision_cases")
    def test_run_cases_case_filter_restricts_cases(
        self, mock_run, runner, tmp_path,
    ):
        mock_run.return_value = {
            "passed": True, "max_diff": 0.0, "per_shape": {"t0": 0.0},
        }
        run_dir = _make_run_dir(tmp_path)
        self._seed_last_deploy(run_dir)
        result = runner.invoke(cli_main, [
            "run-cases", "--workspace", str(run_dir), "--case", "t0"])

        assert result.exit_code == 0, result.output
        cases = mock_run.call_args.args[1]
        assert [tc.name for tc in cases] == ["t0"]

    def test_run_cases_without_redeploy_errors_honestly(self, runner, tmp_path):
        """No last_deploy.json → honest error (not a silent stub). §3.4/§3.7."""
        run_dir = _make_run_dir(tmp_path)
        result = runner.invoke(cli_main, [
            "run-cases", "--workspace", str(run_dir)])
        assert result.exit_code != 0
        assert "last_deploy" in result.output or "redeploy" in result.output
