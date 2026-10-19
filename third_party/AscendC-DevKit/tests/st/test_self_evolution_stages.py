"""ST — self-evolution stages (steps 9-11) via GraphExecutor + stub backend.

Exercises the three new stages:
  - CodegenInitStage: deterministic section declaration from repo_profile
  - codegen_manifest: CodegenStage produces manifest in transition
  - CannbenchAdaptStage: LLM glue-file adaptation with stub agent

No real agent / LLM — uses _StubBackend with canned artifacts.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from ascendc_devkit.capabilities.agent.backend import AgentBackend, AgentResult
from ascendc_devkit.orchestration.kernel.runner import Runner
from ascendc_devkit.orchestration.graph_executor import GraphExecutor
from ascendc_devkit.orchestration.kernel.state import State, ErrorFeedback
from ascendc_devkit.orchestration.registry import _ensure_stages_loaded, get_stage, get_workflow
from ascendc_devkit.orchestration.stages.deploy import Deployer
from ascendc_devkit.domain.repository import RepositoryProfile, Scaffolding
from ascendc_devkit.domain.verification import DeployResult
from ascendc_devkit.infra.workspace import Workspace


def _attach_passing_deploy(state, tmp_path, smoke_passed=True):
    """Attach a run workspace + last_deploy.json (the codegen agent's redeploy
    handoff) so codegen's transition satisfies its build-loop contract (P57-B:
    success requires build_result/deploy_result). op_name mirrors the path
    codegen._read_deploy_result derives."""
    ws = Workspace.create(output_root=str(tmp_path / "out"), run_id="r1")
    op_name = (state.op_name
               or (state.op_identity.spec.name if state.op_identity else "op"))
    debug_dir = ws.dir / "artifacts" / "debug" / op_name
    debug_dir.mkdir(parents=True, exist_ok=True)
    (debug_dir / "last_deploy.json").write_text(json.dumps({
        "run_package": "/pkg/op.run", "wheel_package": "/pkg/op.whl",
        "ld_library_path_add": "/opp/lib", "smoke_passed": smoke_passed,
        "install_path": "/opp/op", "python_path": "/py/op",
    }))
    return state.with_updates(_workspace=ws)


@contextmanager
def _patch_deploy(smoke_passed=True, run_package="/pkg/exp.run",
                  build_fail=False, resolve_fail=False):
    """Mock Deployer.compile + install_and_smoke for codegen transition tests.

    方案 2 (L4 改动 2)：codegen transition 走 compile() → install_and_smoke()（不再走
    deploy 全链）。compile 失败（resolve_fail/build_fail）→ 返回 err；compile 过 →
    install_and_smoke 决定 smoke 结果。Pair with _attach_passing_deploy (attaches the
    workspace _persist_sources needs).
    """
    if resolve_fail:
        c_result, c_err = DeployResult(smoke_passed=False), ErrorFeedback(
            stage_name="deploy", error_type="deploy_failed",
            message="resolve failed (repo/profile missing)",
            details={"step": "resolve", "log": "", "stderr_tail": ""})
    elif build_fail:
        c_result, c_err = DeployResult(smoke_passed=False), ErrorFeedback(
            stage_name="deploy", error_type="deploy_failed",
            message="build failed",
            details={"step": "build", "log": "/fake/build_ascendc.log",
                     "stderr_tail": "error: no matching function for call to 'Cast'"})
    else:
        c_result, c_err = (
            DeployResult(run_package=run_package, wheel_package="/pkg/exp.whl",
                         smoke_passed=False),
            None)
    if resolve_fail or build_fail:
        def _compile(state):
            return c_result, c_err
        def _install_and_smoke(state, compile_result):
            raise AssertionError("compile 失败时不应调用 install_and_smoke")
    elif not smoke_passed:
        def _compile(state):
            return c_result, c_err
        def _install_and_smoke(state, compile_result):
            return (
                DeployResult(run_package=run_package, smoke_passed=False),
                ErrorFeedback(stage_name="deploy", error_type="deploy_failed",
                              message="smoke failed",
                              details={"step": "smoke", "log": "/fake/smoke.log",
                                       "stderr_tail": "not callable"}))
    else:
        def _compile(state):
            return c_result, c_err
        def _install_and_smoke(state, compile_result):
            return (
                DeployResult(run_package=run_package,
                             wheel_package=compile_result.wheel_package,
                             smoke_passed=True,
                             install_path="/opp/exp", python_path="/py/exp"),
                None)
    with patch.object(Deployer, "compile", side_effect=_compile), \
         patch.object(Deployer, "install_and_smoke",
                      side_effect=_install_and_smoke):
        yield


@pytest.fixture(autouse=True)
def _stages():
    _ensure_stages_loaded()


# —— CodegenInitStage tests ——

class TestCodegenInitStage:
    """Deterministic section declaration (step 9): all four sections, always."""

    _FOUR = {
        "host_code": {"directory": "op_host"},
        "kernel_code": {"directory": "op_kernel"},
        "api_code": {"directory": "op_api"},
        "plugin_code": {"directory": "op_plugin"},
    }

    def test_produces_all_four_without_profile(self):
        """No profile → still all four sections (no per-repo gate)."""
        stage = get_stage("codegen_init")()
        state = State.empty().with_updates(non_interactive=True)
        runner = Runner(agent_backend=_StubBackend())
        out = runner.run_stage(state, stage)
        assert out.kernel_architecture == self._FOUR

    def test_produces_all_four_sections_with_profile(self):
        """Any repo profile → the same four sections (unconditional)."""
        stage = get_stage("codegen_init")()
        state = State.empty().with_updates(
            non_interactive=True,
            profile=RepositoryProfile(name="cann-bench"),
        )
        runner = Runner(agent_backend=_StubBackend())
        out = runner.run_stage(state, stage)
        assert out.kernel_architecture == self._FOUR

    def test_profile_name_does_not_change_sections(self):
        """An arbitrary repo name yields the same four sections — the old
        repo-name switch is gone (regression guard)."""
        stage = get_stage("codegen_init")()
        out_names = []
        for name in ("unknown-custom-repo", "omni-ops", "whatever"):
            state = State.empty().with_updates(
                non_interactive=True, profile=RepositoryProfile(name=name))
            runner = Runner(agent_backend=_StubBackend())
            out = runner.run_stage(state, stage)
            out_names.append(out.kernel_architecture)
        assert all(a == self._FOUR for a in out_names)



# —— codegen_manifest tests (step 10) ——

class _ManifestStubBackend(AgentBackend):
    """Stub that returns codegen_manifest.json in addition to source files."""

    def spawn(self, agent_name, prompt, context, skills=None,
              model=None, working_dir=None, repo_baseline=None, repo_root=None,
              stage_name="", branch_label="", resume_session_id=None, resume_prompt=None, primary_skill=None, deadline_monotonic: float | None = None):
        return AgentResult(
            agent_name=agent_name, status="ok",
            artifacts={
                "op_host/exp_tiling.h": "// tiling data",
                "op_kernel/exp_kernel.cpp": "// kernel impl",
                # torch_op profile（47da3b50 契约门）要求 op_plugin 注册存在且可解析——
                # 否则 _torch_plugin_contract_error 判 incomplete_output。m.def/实现返回
                # 形态与 manifest 一致（单 Tensor），方案 A 返回签名对质也零误报。
                "op_plugin/exp_plugin.cpp": (
                    "TORCH_LIBRARY_FRAGMENT(cann_bench, m) {\n"
                    '    m.def("exp(Tensor x, float base=-1, float scale=1, '
                    'float shift=0) -> Tensor");\n'
                    "}\n"
                    "static torch::Tensor exp_meta(torch::Tensor x) { return x; }\n"
                    "static torch::Tensor exp_npu(torch::Tensor x) { return x; }\n"
                    "TORCH_LIBRARY_IMPL(cann_bench, Meta, m) {\n"
                    '    m.impl("exp", exp_meta);\n'
                    "}\n"
                    "TORCH_LIBRARY_IMPL(cann_bench, PrivateUse1, m) {\n"
                    '    m.impl("exp", exp_npu);\n'
                    "}\n"
                ),
                "decision_log.json": json.dumps({"key_decisions": [], "known_issues": [], "assumptions": []}),
                "codegen_manifest.json": json.dumps({
                    "op_name": "exp",
                    "op_pascal": "Exp",
                    "inputs": [{"name": "x", "type": "Tensor"}],
                    "outputs": [{"name": "y", "type": "Tensor"}],
                    "attrs": [
                        {"name": "base", "type": "float", "default": -1.0},
                        {"name": "scale", "type": "float", "default": 1.0},
                        {"name": "shift", "type": "float", "default": 0.0},
                    ],
                    "supported_dtypes": ["float32", "float16"],
                    "callable_target": {"kind": "torch_op", "symbol": "torch.ops.cann_bench.exp"},
                }),
            },
        )


class TestCodegenManifest:
    """CodegenStage parses + stores codegen_manifest (step 10)."""

    def test_transition_populates_codegen_manifest(self, tmp_path):
        from ascendc_devkit.orchestration.stages.codegen import CodegenStage
        stage = CodegenStage()
        state = _attach_passing_deploy(State(
            mode="new",
            non_interactive=True,
            profile=RepositoryProfile(name="cann-bench",
                                      scaffolding=Scaffolding(selected="torch_op")),
            kernel_architecture={
                "host_code": {"directory": "op_host"},
                "kernel_code": {"directory": "op_kernel"},
            },
            design_spec={"inputs": [{"name": "x"}], "outputs": [{"name": "y"}]},
            tiling_strategy={"approach": "single"},
        ), tmp_path)
        runner = Runner(agent_backend=_ManifestStubBackend())
        with _patch_deploy(smoke_passed=True):
            out = runner.run_stage(state, stage)
        assert out.codegen_manifest is not None
        assert out.codegen_manifest["op_name"] == "exp"
        assert out.codegen_manifest["op_pascal"] == "Exp"
        assert len(out.codegen_manifest["inputs"]) == 1
        assert out.codegen_manifest["supported_dtypes"] == ["float32", "float16"]
        # G1/D7: manifest carries callable_target{kind, symbol}
        assert out.codegen_manifest["callable_target"]["kind"] == "torch_op"
        assert out.codegen_manifest["callable_target"]["symbol"] == "torch.ops.cann_bench.exp"
        assert out.last_error is None

    def test_manifest_omits_io_proceeds_no_retry(self, tmp_path):
        """P1 收敛（2026-08-20）：manifest 省略 inputs/outputs（可选）→ 不再触发
        artifact-retry，直接进 deploy。IO 不被下游消费，agent 合法选择不回声。"""
        from ascendc_devkit.orchestration.stages.codegen import CodegenStage
        stage = CodegenStage()
        state = _attach_passing_deploy(State(
            mode="new",
            non_interactive=True,
            profile=RepositoryProfile(name="cann-bench",
                                      scaffolding=Scaffolding(selected="torch_op")),
            kernel_architecture={
                "host_code": {"directory": "op_host"},
                "kernel_code": {"directory": "op_kernel"},
            },
            design_spec={"inputs": [{"name": "x"}], "outputs": [{"name": "y"}]},
            tiling_strategy={"approach": "single"},
        ), tmp_path)

        class _OmitIOBackend(_ManifestStubBackend):
            """同 _ManifestStubBackend 但 manifest 不含 inputs/outputs/attrs。"""

            def spawn(self, agent_name, prompt, context, skills=None,
                      model=None, working_dir=None, repo_baseline=None,
                      repo_root=None, stage_name="", branch_label="",
                      resume_session_id=None, resume_prompt=None,
                      primary_skill=None, deadline_monotonic: float | None = None):
                # 复用父类产物，仅替换 manifest 为无 IO 版
                res = _ManifestStubBackend.spawn(
                    self, agent_name, prompt, context, skills, model,
                    working_dir, repo_baseline, repo_root, stage_name,
                    branch_label, resume_session_id, resume_prompt,
                    primary_skill, deadline_monotonic)
                m = json.loads(res.artifacts["codegen_manifest.json"])
                m.pop("inputs", None)
                m.pop("outputs", None)
                m.pop("attrs", None)
                res.artifacts["codegen_manifest.json"] = json.dumps(m)
                return res

        runner = Runner(agent_backend=_OmitIOBackend())
        with _patch_deploy(smoke_passed=True):
            out = runner.run_stage(state, stage)
        # 无 retry：进 deploy（deploy_result 有值），last_error 空
        assert out.last_error is None
        assert out.deploy_result is not None
        assert out.codegen_artifact_retries == 0
        assert out.codegen_manifest is not None
        assert "inputs" not in out.codegen_manifest   # IO 未被要求回声
        assert out.codegen_manifest["callable_target"]["symbol"] == "torch.ops.cann_bench.exp"

    def test_manifest_missing_callable_target_routes_back(self):
        """G1/D7: a manifest without callable_target is incomplete output —
        codegen (the symbol's author) must declare it, else loop back."""
        from ascendc_devkit.orchestration.stages.codegen import CodegenStage
        stage = CodegenStage()

        class _NoCallableTargetBackend(AgentBackend):
            def spawn(self, *args, **kwargs):
                return AgentResult(agent_name="test", status="ok", artifacts={
                    "op_host/t.h": "// x",
                    "op_kernel/k.cpp": "// y",
                    "decision_log.json": json.dumps({"key_decisions": [], "known_issues": [], "assumptions": []}),
                    # manifest present but omits callable_target
                    "codegen_manifest.json": json.dumps({
                        "op_name": "exp", "inputs": [{"name": "x"}], "outputs": [{"name": "y"}],
                    }),
                })

        state = State(
            mode="new",
            non_interactive=True,
            profile=RepositoryProfile(name="cann-bench",
                                      scaffolding=Scaffolding(selected="torch_op")),
            kernel_architecture={
                "host_code": {"directory": "op_host"},
                "kernel_code": {"directory": "op_kernel"},
            },
            design_spec={"inputs": [{"name": "x"}], "outputs": [{"name": "y"}]},
            tiling_strategy={"approach": "single"},
        )
        runner = Runner(agent_backend=_NoCallableTargetBackend())
        out = runner.run_stage(state, stage)
        # incomplete output → 定向 artifact-retry（5 次）耗尽 → exhausted 终态类
        # halt：last_error 必须活着走到调用方（workflow exhausted→__halt__ 路由），
        # 不得被 runner R1 归一化/F6"成功清错"抹掉（耗尽冒充成功交付=错误冒充）。
        assert out.last_error is not None
        assert out.last_error.error_type == "exhausted"
        assert "callable_target" in out.last_error.message
        # 耗尽轮不再空烧：5 次耗尽即停（stop_in_stage_retry），不迭代到 40
        assert out.stage_iterations["codegen"] == 5
        assert out.codegen_artifact_retries == 5

    def test_empty_stub_does_not_set_manifest(self):
        """When agent produces no manifest, field stays None."""
        from ascendc_devkit.orchestration.stages.codegen import CodegenStage
        stage = CodegenStage()

        class _NoManifestBackend(AgentBackend):
            def spawn(self, *args, **kwargs):
                return AgentResult(agent_name="test", status="ok", artifacts={
                    "op_host/t.h": "// x",
                    "op_kernel/k.cpp": "// y",
                })

        state = State(
            mode="new",
            non_interactive=True,
            kernel_architecture={
                "host_code": {"directory": "op_host"},
                "kernel_code": {"directory": "op_kernel"},
            },
            design_spec={"inputs": [{"name": "x"}], "outputs": [{"name": "y"}]},
            tiling_strategy={"approach": "single"},
        )
        runner = Runner(agent_backend=_NoManifestBackend())
        out = runner.run_stage(state, stage)
        # No manifest in artifacts → stays None
        assert out.codegen_manifest is None
        assert out.generated_sources is not None  # sources still produced

    def test_codegen_manifest_in_self_evolve_pipeline(self):
        """Full self_evolve pipeline: codegen_init → codegen produces manifest.
        precision_debug and later stages are pre-seeded as completed since they
        require real build/NPU environments (run-cases / shell commands)."""
        wf = get_workflow("self_evolve_op")

        class _SelfEvolveBackend(AgentBackend):
            def spawn(self, agent_name, prompt, context, skills=None,
                      model=None, working_dir=None, repo_baseline=None, repo_root=None,
                      stage_name="", branch_label="", resume_session_id=None, resume_prompt=None, primary_skill=None, deadline_monotonic: float | None = None):
                return AgentResult(agent_name=agent_name, status="ok", artifacts={
                    "design_spec.json": json.dumps({"inputs": [{"name": "x"}], "outputs": [{"name": "y"}]}),
                    "tiling_strategy.json": json.dumps({"approach": "multi_template"}),
                    "op_host/t.h": "// host",
                    "op_kernel/k.cpp": "// kernel",
                    "codegen_manifest.json": json.dumps({"op_name": "test", "inputs": [], "outputs": [],
                        "callable_target": {"kind": "torch_op", "symbol": "torch.ops.cann_bench.test"}}),
                })

        from ascendc_devkit.domain.verification import (
            DeployResult, EvalResult, AdaptResult, PrecisionDebugResult,
        )
        from ascendc_devkit.domain.requirement import Requirement
        state = State.empty().with_updates(
            non_interactive=True,
            op_name="test",
            profile=RepositoryProfile(name="cann-bench",
                                      scaffolding=Scaffolding(selected="torch_op")),
            requirement=Requirement.from_dict({"op": {"name": "test"}}),
            requirement_clarified=True,
            general_design={"op_name": "test", "split_axis_priority": [],
                            "tiling_data": [], "loop_framework": "", "buffer_eval": {}},
            template_division={"templates": [{"name": "T1"}]},
            tiling_results={"T1": {"split": {}}},
            # Pre-seed downstream results to skip shell-dependent stages
            generated_sources={"op_host/t.h": "// host", "op_kernel/k.cpp": "// kernel"},
            debug_result=PrecisionDebugResult(passed=True),
            deploy_result=DeployResult(smoke_passed=True, install_path="/tmp/x"),
            adapt_result=AdaptResult(adapted=True, files_modified=["__init__.py"]),
            eval_result=EvalResult(overall_score=31.4),
            node_status={
                "self_evolve_op/requirement": "completed",
                "self_evolve_op/general-design": "completed",
                "self_evolve_op/detailed-design/dd-intake": "completed",
                "self_evolve_op/detailed-design/template-division": "completed",
                "self_evolve_op/detailed-design/tiling": "completed",
                "self_evolve_op/detailed-design/anchor-forkjoin": "completed",
                "self_evolve_op/detailed-design/anchor-consistency": "completed",
                "self_evolve_op/detailed-design/synthesize": "completed",
                "self_evolve_op/detailed-design/docgen": "completed",
                "self_evolve_op/detailed-design/validate": "completed",
                "self_evolve_op/ascendc-st-design": "completed",
                "self_evolve_op/detailed-design/validate": "completed",
                "self_evolve_op/precision_debug": "completed",
                "self_evolve_op/cannbench_adapt": "completed",
                "self_evolve_op/cannbench_eval": "completed",
            },
            design_spec={"inputs": [{"name": "x"}], "outputs": [{"name": "y"}]},
            tiling_strategy={"approach": "multi_template"},
        )
        runner = Runner(agent_backend=_SelfEvolveBackend())
        out = GraphExecutor(runner=runner).execute(wf.root(), state)
        # codegen_init should have produced kernel_architecture
        assert out.kernel_architecture is not None
        assert "host_code" in out.kernel_architecture
        # codegen should have produced codegen_manifest
        assert out.codegen_manifest is not None
        assert out.codegen_manifest["op_name"] == "test"


# —— CannbenchAdaptStage tests (step 11) ——

class TestCannbenchAdaptStage:
    """CannbenchAdaptStage — deterministic cann-bench glue adapter (方案 G, agent 已退役)。

    transition 确定性生成 cann_bench/__init__.py wrapper（manifest 派生）+ P10 m.def
    rename + clean rebuild；不再 spawn cannbench-adapt LLM agent。
    """

    def test_skips_when_no_codegen_manifest(self, tmp_path):
        """Adapt is a no-op when no manifest is available (adapted=False)."""
        stage = get_stage("cannbench_adapt")()
        repo_root = tmp_path / "cann-bench"
        repo_root.mkdir()
        state = State.empty().with_updates(
            non_interactive=True,
            repo_root=repo_root,
            codegen_manifest=None,  # missing
            generated_sources={"op_host/t.h": "//"},
        )
        runner = Runner(agent_backend=_StubBackend())
        out = runner.run_stage(state, stage)
        # 确定性 pass-through：无 manifest → 无 wrapper、无 rebuild
        assert out.adapt_result is not None
        assert out.adapt_result.adapted is False

    def test_transition_no_op_when_manifest_lacks_signature(self):
        """manifest 无 callable_target.symbol → 派生不出 wrapper，adapted=False。"""
        from ascendc_devkit.orchestration.stages.cannbench_adapt import CannbenchAdaptStage
        stage = CannbenchAdaptStage()
        state = State.empty().with_updates(codegen_manifest={"op_name": "x"})
        out = stage.transition(state, {})
        assert out.adapt_result is not None
        assert out.adapt_result.adapted is False
        assert out.adapt_result.files_modified == []

    def test_derivation_failure_collects_errors(self, tmp_path):
        """manifest 缺 callable_target.symbol → 确定性收集 error（§3.7 honest signal）。"""
        from ascendc_devkit.orchestration.stages.cannbench_adapt import CannbenchAdaptStage
        repo_root = tmp_path / "cann-bench"
        repo_root.mkdir()
        state = State.empty().with_updates(
            op_name="exp",
            repo_root=repo_root,
            codegen_manifest={"op_name": "exp"},  # 无 callable_target
        )
        out = CannbenchAdaptStage().transition(state, {})
        assert out.adapt_result.adapted is False
        assert len(out.adapt_result.errors) > 0
        assert any("callable_target.symbol" in e for e in out.adapt_result.errors)

    def test_fail_strategy_is_continue(self):
        """Adapt failure must not block downstream eval."""
        stage = get_stage("cannbench_adapt")()
        assert stage.fail_strategy == "continue"

    def test_input_contract_requires_manifest(self):
        """codegen_manifest is a required input for cannbench_adapt."""
        stage = get_stage("cannbench_adapt")()
        ic = stage.input_contract()
        assert "codegen_manifest" in ic.requires
        assert "generated_sources" in ic.requires
        assert "repo_root" in ic.requires


# —— Pipeline integration tests ——

class TestSelfEvolvePipelineContracts:
    """Stage IO chain validation for self_evolve_op workflow."""

    def test_stage_names_include_new_stages(self):
        wf = get_workflow("self_evolve_op")
        names = [s.name for s in wf.flat_stages()]
        # P57 能力下沉: Full pipeline: entry → context → requirement → [design
        #   groups] → [test_design group] → codegen_init → codegen →
        #   precision_debug → cannbench_adapt → cannbench_eval → finalize.
        #   deploy/verify are gone — build owned in-session by codegen (redeploy),
        #   precision owned by precision_debug (run-cases).
        # test_design AND precision_debug are CompositeGroups; their substages
        # appear as: ascendc-st-design and
        # run_tests/diagnose/fix/printf_location.
        assert "requirement" in names
        assert "codegen_init" in names
        assert "cannbench_adapt" in names
        assert "ascendc-st-design" in names      # single test-design stage
        assert "run_tests" in names             # precision_debug group substage (P0)
        # Order (use precision_debug's first sub-stage run_tests as its position)
        rq = names.index("requirement")
        ci = names.index("codegen_init")
        cg = names.index("codegen")
        pd = names.index("run_tests")           # precision_debug group's first child
        ca = names.index("cannbench_adapt")
        ce = names.index("cannbench_eval")
        assert rq < ci < cg < pd < ca < ce

    def test_transition_table_no_cannbench_eval_loopback(self):
        """Step D: cann-bench eval is the one-shot LOSS — never routes back.

        Removing the `cannbench_eval: eval_failed → codegen` edge keeps the
        loss signal (②) from feeding codegen (①), per the three-tier model.
        """
        wf = get_workflow("self_evolve_op")
        table = wf._get_transition_table()
        assert "cannbench_eval" not in table


    def test_codegen_init_provides_kernel_architecture(self):
        stage = get_stage("codegen_init")()
        assert "kernel_architecture" in stage.output_contract().provides

    def test_codegen_accepts_kernel_architecture_as_optional(self):
        stage = get_stage("codegen")()
        ic = stage.input_contract()
        assert "kernel_architecture" in ic.optional
        assert "kernel_architecture" not in ic.requires

    def test_flow_from_codegen_init_to_codegen(self):
        """codegen_init provides kernel_architecture → codegen reads it."""
        stage_init = get_stage("codegen_init")()
        stage_codegen = get_stage("codegen")()
        # codegen_init output: kernel_architecture
        assert "kernel_architecture" in stage_init.output_contract().provides
        # codegen accepts kernel_architecture (optional, consumed from State)
        codegen_opt = stage_codegen.input_contract().optional
        assert "kernel_architecture" in codegen_opt


class TestDeployerHelpers:
    """Deployer internal helpers — resolution + path logic (P54 D3: moved from DeployStage)."""

    def test_resolve_repo_root_from_state(self, tmp_path):
        state = State.empty().with_updates(repo_root=tmp_path)
        assert Deployer._resolve_repo_root(state) == tmp_path

    def test_resolve_repo_root_from_op_identity(self, tmp_path):
        from ascendc_devkit.domain.operator import OperatorSpec, OperatorIdentity
        op_id = OperatorIdentity(
            spec=OperatorSpec(name="gelu"),
            repo_root=tmp_path, op_dir=tmp_path / "ops" / "gelu",
        )
        state = State.empty().with_updates(
            repo_root=None, op_identity=op_id,
        )
        assert Deployer._resolve_repo_root(state) == tmp_path

    def test_smoke_harness_uses_callable_target_symbol(self):
        """G4/D7: smoke harness is driven by callable_target, NOT hardcoded cann_bench.
        torch_op smoke now does a REAL fn() call via the shared precision_debug
        harness (not the old getattr-only probe), so this checks the harness
        bakes in the target symbol."""
        ct = {"kind": "torch_op", "symbol": "torch.ops.cann_bench.add"}
        state = State.empty().with_updates(
            codegen_manifest={"callable_target": ct},
            design_target_chip="A2", runtime_target_chip="A2")
        script = Deployer()._build_smoke_harness(
            state, ct, "/tmp/py", "/tmp/opp", "/tmp/ld")
        assert "cann_bench" in script  # from the symbol, not hardcoded
        assert "add" in script
        assert "kernel_fn(" in script  # real call, not just getattr resolution

    def test_smoke_harness_custom_namespace(self):
        """A non-cann_bench symbol yields a namespace-agnostic harness."""
        ct = {"kind": "torch_op", "symbol": "torch.ops.custom.npu_rope"}
        state = State.empty().with_updates(
            codegen_manifest={"callable_target": ct},
            design_target_chip="A2", runtime_target_chip="A2")
        script = Deployer()._build_smoke_harness(
            state, ct, "/tmp/py", "/tmp/opp", "/tmp/ld")
        assert "custom" in script
        assert "npu_rope" in script

    def test_callable_target_missing_returns_none(self):
        state = State.empty().with_updates(codegen_manifest={"op_name": "x"})
        assert Deployer._callable_target(state) is None

    def test_find_file_locates_glob(self, tmp_path):
        dist = tmp_path / "dist"
        dist.mkdir()
        (dist / "custom_ops-1.0.run").write_text("pkg", encoding="utf-8")
        result = Deployer._find_file(dist, "*.run")
        assert "custom_ops-1.0.run" in result

    def test_per_op_path_isolation(self, tmp_path):
        """Per-op path includes op_name in the directory (workspace-backed; ~/.cache
        fallback 已删 §1.7/§1.4, dispatcher 全入口 attach _workspace)。"""
        from ascendc_devkit.infra.workspace import Workspace
        ws = Workspace(tmp_path, "r1")
        ws.dir.mkdir(parents=True, exist_ok=True)
        p = Deployer._per_op_path(ws, "opp", "gelu")
        assert "gelu" in p
        assert "opp" in p


# —— CannbenchEvalStage tests (self-evolution L4-3) ——

class TestCannbenchEvalStageContracts:
    """CannbenchEvalStage I/O contracts and deterministic transition."""

    def test_input_contract(self):
        stage = get_stage("cannbench_eval")()
        ic = stage.input_contract()
        assert "deploy_result" in ic.requires
        assert "generated_sources" in ic.requires
        assert "op_name" in ic.requires
        # P13 (step-116)：device_id 死链已拆（State 从未携带该字段），
        # optional 契约条目随之退役。
        assert "repo_root" in ic.optional

    def test_output_contract(self):
        stage = get_stage("cannbench_eval")()
        oc = stage.output_contract()
        assert "eval_result" in oc.provides

    def test_fail_strategy_is_continue(self):
        """Eval failure must not block other ops."""
        stage = get_stage("cannbench_eval")()
        assert stage.fail_strategy == "continue"

    def test_transition_missing_deploy_skips(self):
        """No deploy_result → skip with score=0, no last_error (step A: only出分)."""
        stage = get_stage("cannbench_eval")()
        state = State.empty().with_updates(
            non_interactive=True,
            op_name="exp",
            deploy_result=None,
        )
        out = stage.transition(state, {})
        assert out.eval_result is not None
        assert out.eval_result.overall_score == 0.0
        # Step A (D4/07): evaluator is single-responsibility — never injects
        # last_error / never routes back to codegen. Score==0 is the loss signal.
        assert out.last_error is None

    def test_transition_deploy_not_smoked_skips(self):
        """Deploy smoke not passed → skip with score=0, no last_error."""
        from ascendc_devkit.domain.verification import DeployResult
        stage = get_stage("cannbench_eval")()
        state = State.empty().with_updates(
            non_interactive=True,
            op_name="exp",
            deploy_result=DeployResult(smoke_passed=False),
        )
        out = stage.transition(state, {})
        assert out.eval_result is not None
        assert out.eval_result.overall_score == 0.0
        assert out.last_error is None

    def test_transition_missing_repo_root(self):
        """No repo_root → skip with score=0, no last_error."""
        from ascendc_devkit.domain.verification import DeployResult
        stage = get_stage("cannbench_eval")()
        state = State.empty().with_updates(
            non_interactive=True,
            op_name="exp",
            deploy_result=DeployResult(smoke_passed=True),
            repo_root=None,
        )
        out = stage.transition(state, {})
        assert out.eval_result.overall_score == 0.0
        assert out.last_error is None

    def test_resolve_condition_never_routes_back(self):
        """Step A: evaluator has no resolve_condition override — always default.

        cann-bench is the one-shot LOSS signal (② in the three-tier model); it
        must NOT feed a corrective loopback to codegen. A zero score is the loss,
        not a trigger to re-generate.
        """
        from ascendc_devkit.domain.verification import EvalResult
        stage = get_stage("cannbench_eval")()
        state = State.empty().with_updates(
            eval_result=EvalResult(overall_score=0.0),
        )
        assert stage.resolve_condition(state) == "default"


class TestCannbenchEvalStageHelpers:
    """CannbenchEvalStage internal helpers."""

    def test_snake_to_pascal(self):
        # step-82 (42d7c3c3): 收敛到 adapter 边界 —— snake_to_pascal 现为
        # CannbenchScorer 静态方法(stage.transition 经 CannbenchScorer.snake_to_pascal 调)。
        from ascendc_devkit.adapters.evaluation.cannbench_scorer import CannbenchScorer
        assert CannbenchScorer.snake_to_pascal("exp") == "Exp"
        assert CannbenchScorer.snake_to_pascal("swi_glu") == "SwiGlu"
        assert CannbenchScorer.snake_to_pascal("add") == "Add"

    def test_resolve_source_dir_from_op_dir(self, tmp_path):
        stage = get_stage("cannbench_eval")()
        repo_root = tmp_path / "repo"
        op_dir = repo_root / "ops" / "gelu"
        op_dir.mkdir(parents=True)
        state = State.empty().with_updates(op_dir=op_dir)
        resolved = stage._resolve_source_dir(state, repo_root, "gelu")
        assert resolved == op_dir

    def test_find_latest_report_none_when_missing(self, tmp_path):
        # step-82 (42d7c3c3): _find_latest_report 现为 CannbenchScorer 静态方法。
        from ascendc_devkit.adapters.evaluation.cannbench_scorer import CannbenchScorer
        result = CannbenchScorer._find_latest_report(tmp_path)
        assert result == ""

    def test_eval_failure_dumps_full_stderr_to_subprocess_log(self, tmp_path):
        """kernel_eval failure must persist FULL stderr (the Python traceback
        lives at the END), not truncate to a head window — which hid the
        Evaluator crash in the 20260707-091803 resume run. The meaningful line
        sits beyond any head window, so head-truncation loses it.

        step-82 (42d7c3c3): eval subprocess + failure logging收敛到 adapter 边界 ——
        全 stderr 落盘由 CannbenchScorer._log_eval_failure 承担(stage.transition
        经 CannbenchScorer.run_eval 调它)。故本测直接守护该单元:构造失败 proc →
        断言全量落盘、尾部异常行完整(不被 head 截断丢失)。
        """
        from ascendc_devkit.adapters.evaluation.cannbench_scorer import CannbenchScorer
        from ascendc_devkit.infra.workspace import Workspace

        marker = "ValueError: Evaluator boom (no channel)"
        long_stderr = "[INFO] --skip-install\n" + ("x" * 2000) + "\n" + marker + "\n"

        class _FakeProc:
            returncode = 1
            stdout = ""
            stderr = long_stderr

        ws = Workspace.create(output_root=str(tmp_path), run_id="r1")
        CannbenchScorer()._log_eval_failure("exp", _FakeProc(), ws)

        # Full stderr persisted to the run's subprocess log, tail exception intact
        log_path = ws.subprocess_log / "cannbench_eval_exp.stderr.log"
        assert log_path.is_file()
        dumped = log_path.read_text(encoding="utf-8")
        assert marker in dumped              # the line head-truncation would have lost
        assert len(dumped) == len(long_stderr)


# —— adapter helpers ——

class _StubBackend(AgentBackend):
    """Doesn't need per-skill artifacts for these tests — returns empty."""

    def spawn(self, agent_name, prompt, context, skills=None,
              model=None, working_dir=None, repo_baseline=None, repo_root=None,
              stage_name="", branch_label="", resume_session_id=None, resume_prompt=None, primary_skill=None, deadline_monotonic: float | None = None):
        return AgentResult(agent_name=agent_name, status="ok", artifacts={})
