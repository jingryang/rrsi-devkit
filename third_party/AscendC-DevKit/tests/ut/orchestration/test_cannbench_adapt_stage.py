"""UT — CannbenchAdaptStage transition 集成行为（mock Deployer 的确定性用例）。

§3.8 分层：mock 掉 Deployer 的确定性逻辑测试归 UT（原在 tests/st/
test_self_evolution_stages.py，PR-36 review m4 移入）；ST 只保留真实 build_install
链路。本文件覆盖 transition 层行为：wrapper 注入、只碰胶水不碰算子代码、
persist 到 State。wrapper 生成的纯函数逻辑见 test_cannbench_adapt_schema.py。
"""

from __future__ import annotations

from unittest.mock import patch

from ascendc_devkit.capabilities.agent.backend import AgentBackend, AgentResult
from ascendc_devkit.domain.operator import (
    AttrSpec,
    OperatorIdentity,
    OperatorSpec,
    TensorSpec,
)
from ascendc_devkit.domain.requirement import Requirement
from ascendc_devkit.domain.verification import DeployResult
from ascendc_devkit.orchestration.kernel.runner import Runner
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.stages.cannbench_adapt import CannbenchAdaptStage


class _StubBackend(AgentBackend):
    """Doesn't need per-skill artifacts for these tests — returns empty."""

    def spawn(self, agent_name, prompt, context, skills=None,
              model=None, working_dir=None, repo_baseline=None, repo_root=None,
              stage_name="", branch_label="", resume_session_id=None,
        resume_prompt=None,
              primary_skill=None, deadline_monotonic: float | None = None):
        return AgentResult(agent_name=agent_name, status="ok", artifacts={})


def _full_state(tmp_path):
    """带 callable_target.symbol + requirement.op_spec + cann_bench/ 包的完整 State（wrapper 可注入）。"""
    spec = OperatorSpec(
        name="exp",
        inputs=[TensorSpec(name="x")],
        attrs={"base": AttrSpec(name="base", type="float")},
    )
    repo_root = tmp_path / "cann-bench"
    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "cann_bench").mkdir(parents=True, exist_ok=True)
    (repo_root / "cann_bench" / "__init__.py").write_text("", encoding="utf-8")
    ident = OperatorIdentity(spec=spec, repo_root=repo_root,
                             op_dir=repo_root, files={})
    # e9ed199e: top-level op_spec 删除,权威收敛到 requirement.op_spec
    # (cannbench_adapt.py:106 读 state.requirement.op_spec)。
    return State.empty().with_updates(
        non_interactive=True,
        op_name="exp",
        requirement=Requirement(op_spec=spec),
        op_identity=ident,
        repo_root=repo_root,
        codegen_manifest={
            "op_name": "exp",
            "callable_target": {"kind": "torch_op", "symbol": "npu_exp"},
        },
        deploy_result=DeployResult(
            smoke_passed=True,
            install_path=str(tmp_path / "opp"),
            python_path=str(tmp_path / "py"),
        ),
        design_target_chip="A2",
        runtime_target_chip="A2",
    )


class TestCannbenchAdaptStage:
    def test_successful_adapt_injects_wrapper(self, tmp_path):
        """确定性注入 wrapper → AdaptResult.adapted=True, files_modified 含 __init__.py。"""
        state = _full_state(tmp_path)
        with patch("ascendc_devkit.orchestration.stages.deploy.Deployer") as MockDep:
            MockDep.return_value.build_install.return_value = (
                DeployResult(smoke_passed=True), None)
            out = CannbenchAdaptStage().transition(state, {})
        assert out.adapt_result.adapted is True
        assert "cann_bench/__init__.py" in out.adapt_result.files_modified
        content = (state.repo_root / "cann_bench" / "__init__.py").read_text(encoding="utf-8")
        # 三维：对外名 exp、转发目标 npu_exp、参数名 proto(x, base)
        assert "def exp(x, base):" in content
        assert "torch.ops.cann_bench.npu_exp(x, base)" in content

    def test_adapt_only_touches_glue_not_operator_code(self, tmp_path):
        """方案 G scope：只写 cann_bench/__init__.py，永不碰 op_host/op_kernel/op_api/op_plugin。"""
        state = _full_state(tmp_path)
        with patch("ascendc_devkit.orchestration.stages.deploy.Deployer") as MockDep:
            MockDep.return_value.build_install.return_value = (
                DeployResult(smoke_passed=True), None)
            out = CannbenchAdaptStage().transition(state, {})
        assert out.adapt_result.files_modified == ["cann_bench/__init__.py"]
        for f in out.adapt_result.files_modified:
            assert "op_host/" not in f
            assert "op_kernel/" not in f
            assert "op_api/" not in f
            assert "op_plugin/" not in f

    def test_adapt_persists_in_state_full_cycle(self, tmp_path):
        """CannbenchAdaptStage via Runner 注入 wrapper 并写 adapt_result 到 State。"""
        state = _full_state(tmp_path)
        with patch("ascendc_devkit.orchestration.stages.deploy.Deployer") as MockDep:
            MockDep.return_value.build_install.return_value = (
                DeployResult(smoke_passed=True), None)
            runner = Runner(agent_backend=_StubBackend())
            out = runner.run_stage(state, CannbenchAdaptStage())
        assert out.adapt_result is not None
        assert out.adapt_result.adapted is True
        assert "cann_bench/__init__.py" in out.adapt_result.files_modified
