"""Unit tests for Stage implementations — all 10 stages.

Uses StubBackend so no real LLM calls are made.
"""

import dataclasses
import json
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from ascendc_devkit.orchestration.kernel.state import State, ErrorFeedback
from ascendc_devkit.orchestration.kernel.action import (
    SpawnAgent, RunGate, Integrate, ValidateInputs,
    LoadProfile, InitAdapter, CollectReferenceCode,
    ScanExistingOperator, ReadOperatorCode, BuildBaseline,
    UpdateDevRecord, AskUserQuestion,
)
from ascendc_devkit.orchestration.kernel.runner import Runner
from ascendc_devkit.orchestration.stages.smoke import SmokeStage
from ascendc_devkit.orchestration.stages.codegen import CodegenStage
from ascendc_devkit.orchestration.stages.entry import EntryStage
from ascendc_devkit.orchestration.stages.context import ContextStage
from ascendc_devkit.orchestration.stages.requirement import RequirementStage
from ascendc_devkit.orchestration.stages.perf import PerfStage, PrecisionPassedGate, PerformanceGate
from ascendc_devkit.orchestration.stages.integrate import IntegrateStage, VerifyCompleteGate
from ascendc_devkit.orchestration.stages.finalize import FinalizeStage, IntegrationCompleteGate
from ascendc_devkit.capabilities.agent.backend import AgentResult
from ascendc_devkit.capabilities.agent.stub_backend import StubBackend
from ascendc_devkit.domain.repository import (
    RepositoryProfile, BuildVariant, BuildStage, OpNaming, Scaffolding,
)
from ascendc_devkit.infra.workspace import Workspace


def _with_golden_alignment(req_dict: dict) -> str:
    """P121 test helper: inject ``golden_alignment`` and ``aclnn_name`` (both
    required_keys) into a requirement dict → json string, so inline fixtures stay
    focused on the field under test. setdefault: a fixture may explicitly
    override (e.g. status=pending)."""
    d = dict(req_dict)
    d.setdefault("aclnn_name", "aclnnOp")
    d.setdefault("golden_alignment",
                 {"status": "pass", "differences": [], "notes": ""})
    return json.dumps(d)


def _omni_profile():
    """omni-ops-like profile for stage tests (single inference variant).

    Selects torch_op to mirror the real omni-ops profile
    (resources/repository-profiles/omni-ops.yaml: scaffolding.selected=torch_op)
    — every real profile selects a protocol (load-time validated, no default),
    so tests must too (an empty selected="" is unrealistic and would make the
    codegen manifest contract un-validatable)."""
    return RepositoryProfile(
        name="omni-ops",
        op_naming=OpNaming(prefix="ai_infra_"),
        scaffolding=Scaffolding(supported=("torch_op",), selected="torch_op"),
        build_variants=(
            BuildVariant(
                name="inference", match_prefix="inference/ascendc/src",
                default_reference_root="inference/ascendc/src",
                stages=(BuildStage(
                    name="ascendc", cwd="inference/ascendc",
                    command_template="bash build.sh -n {full_op_name} -c {chip_version}",
                    default_chip="A3"),),
            ),
        ),
    )


def _torch_op_profile():
    """cann-bench-like profile selecting torch_op (for manifest derivation /
    artifact-retry tests). Generic: any repo whose profile selects torch_op
    hits the same code path (§1.12 — no repo/operator coupling)."""
    return RepositoryProfile(
        name="cann-bench-like",
        op_naming=OpNaming(prefix="ai_infra_"),
        scaffolding=Scaffolding(supported=("torch_op",), selected="torch_op"),
        build_variants=(
            BuildVariant(
                name="inference", match_prefix="inference/ascendc/src",
                default_reference_root="inference/ascendc/src",
                stages=(BuildStage(
                    name="ascendc", cwd="inference/ascendc",
                    command_template="bash build.sh -n {full_op_name} -c {chip_version}",
                    default_chip="A3"),),
            ),
        ),
    )


# A valid torch_op plugin: TORCH_LIBRARY_FRAGMENT(cann_bench, m) +
# m.def("gelu(Tensor x) -> Tensor"). _resolve_torch_registration parses
# namespace=cann_bench, op=gelu → symbol torch.ops.cann_bench.gelu.
_PLUGIN_SRC = """\
#include <torch/library.h>
namespace cann_bench {
torch::Tensor gelu_meta(torch::Tensor x) { return x; }
TORCH_LIBRARY_FRAGMENT(cann_bench, m) {
    m.def("gelu(Tensor x) -> Tensor");
    m.impl("gelu", gelu_meta);
}
}  // namespace cann_bench
"""

# A complete, conforming codegen_manifest (matches _PLUGIN_SRC registration:
# namespace=cann_bench, op=gelu → symbol torch.ops.cann_bench.gelu).
_COMPLETE_MANIFEST = {
    "op_name": "Gelu",
    "inputs": [{"name": "x", "type": "Tensor"}],
    "outputs": [{"name": "y", "type": "Tensor"}],
    "callable_target": {"kind": "torch_op", "symbol": "torch.ops.cann_bench.gelu"},
}


def _gelu_artifacts(code="// kernel", *, manifest=True, plugin=True):
    """Standard gelu artifacts: kernel + (optional) plugin + manifest.

    The codegen manifest contract (schema required_keys) is now mechanically
    enforced — a realistic codegen run always produces a conforming manifest
    + (for torch_op) a plugin registration. Tests that exercise the build/
    deploy/smoke paths opt in via manifest=/plugin= (default both on)."""
    a = {"gelu.cpp": code}
    if plugin:
        a["op_plugin/gelu_plugin.cpp"] = _PLUGIN_SRC
    if manifest:
        a["codegen_manifest.json"] = json.dumps(_COMPLETE_MANIFEST)
    return a


def _attach_passing_deploy(state, tmp_path, smoke_passed=True,
                           run_package="/pkg/gelu.run", run_id="r1"):
    """Attach a run workspace + last_deploy.json (the file handoff the codegen
    agent's `redeploy` loop writes) so the codegen transition can read
    smoke_passed (P57-B build-loop contract). op_name mirrors the path
    codegen._read_deploy_result derives, so any state works. Shared by the
    transition UTs and the Runner-level codegen tests.

    run_id：同一用例内多次调用时传不同 run_id（r2/r3...）规避 workspace 目录冲突
    （Workspace.create 对已存在目录抛 FileExistsError）。"""
    ws = Workspace.create(output_root=str(tmp_path / "out"), run_id=run_id)
    op_name = (state.op_name
               or (state.op_identity.spec.name if state.op_identity else "op"))
    debug_dir = ws.dir / "artifacts" / "debug" / op_name
    debug_dir.mkdir(parents=True, exist_ok=True)
    (debug_dir / "last_deploy.json").write_text(json.dumps({
        "run_package": run_package, "wheel_package": "/pkg/gelu.whl",
        "ld_library_path_add": "/opp/lib", "smoke_passed": smoke_passed,
        "install_path": "/opp/gelu", "python_path": "/py/gelu",
    }))
    return state.with_updates(_workspace=ws)


from contextlib import contextmanager


@contextmanager
def _patch_deploy(smoke_passed=True, run_package="/pkg/gelu.run",
                  build_fail=False, resolve_fail=False, c_err=None):
    """Mock Deployer.compile + install_and_smoke for codegen transition tests.

    方案 2 (L4 改动 2)：codegen transition 走 compile() → install_and_smoke()（不再走
    deploy 全链）。compile 失败（resolve_fail/build_fail）→ 返回 err；compile 过 →
    install_and_smoke 决定 smoke 结果。Pair with _attach_passing_deploy (attaches the
    workspace _persist_sources needs).

    Modes: smoke_passed=True (done) / smoke_passed=False (compile OK but smoke
    failed → D4, kernel-phase 507035——Part B 后 host/歧义类 smoke 失败走 codegen
    retry，只有 kernel 执行过的才 D4) / build_fail=True (compile failed →
    build-retry respawn) / resolve_fail=True (unfixable → halt).
    c_err：build_fail=True 时透传自定义 ErrorFeedback（build 机械 stop-loss UT 用——
    签名取自 err.details.log 的文件内容，需自定义 log 路径）。"""
    from ascendc_devkit.orchestration.stages.deploy import Deployer
    if resolve_fail:
        c_result, c_err = DeployResult(smoke_passed=False), ErrorFeedback(
            stage_name="deploy", error_type="deploy_failed",
            message="resolve failed (repo/profile missing)",
            details={"step": "resolve", "log": "", "stderr_tail": ""})
    elif build_fail:
        c_result, c_err = DeployResult(smoke_passed=False), (
            c_err or ErrorFeedback(
                stage_name="deploy", error_type="deploy_failed",
                message="build failed",
                details={"step": "build", "log": "/fake/build_ascendc.log",
                         "stderr_tail": "error: no matching function for call to 'Cast'"}))
    else:
        c_result, c_err = (
            DeployResult(run_package=run_package, wheel_package="/pkg/gelu.whl",
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
                              message="smoke failed: kernel phase crash",
                              details={"step": "smoke", "log": "/fake/smoke.log",
                                       "stderr_tail": "RuntimeError('call aclnnGelu "
                                       "failed, aivec error, vector core exception "
                                       "507035 ...')"}))
    else:
        def _compile(state):
            return c_result, c_err
        def _install_and_smoke(state, compile_result):
            return (
                DeployResult(run_package=run_package,
                             wheel_package=compile_result.wheel_package,
                             smoke_passed=True,
                             install_path="/opp/gelu", python_path="/py/gelu"),
                None)
    with mock.patch.object(Deployer, "compile",
                           side_effect=_compile), \
         mock.patch.object(Deployer, "install_and_smoke",
                           side_effect=_install_and_smoke):
        yield


def _gelu_torch_plugin():
    return {
        "op_plugin/gelu_plugin.cpp": (
            "TORCH_LIBRARY_FRAGMENT(cann_bench, m) {\n"
            '    m.def("gelu(Tensor x) -> Tensor");\n'
            "}\n"
        )
    }


from ascendc_devkit.domain.operator import OperatorSpec, OperatorIdentity, TensorSpec
from ascendc_devkit.domain.requirement import Requirement, TestCase
from ascendc_devkit.domain.verification import BuildResult, DeployResult, PerformanceResult, PrecisionDebugResult


class TestSmokeStage:
    def test_actions_returns_spawn_agent(self):
        stage = SmokeStage()
        state = State(mode="new", op_name="test")
        actions = stage.actions(state)
        assert len(actions) == 1
        a = actions[0]
        assert isinstance(a, SpawnAgent)
        assert a.agent_name == "ascendc-coder"
        assert "Bash" in a.prompt

    def test_transition_with_artifacts(self):
        stage = SmokeStage()
        state = State(mode="new")
        agent_result = AgentResult(
            agent_name="ascendc-coder",
            status="ok",
            artifacts={"hello.cpp": "// hello"},
        )
        result = state.with_updates()
        new_state = stage.transition(state, {"agent_result": agent_result})
        assert new_state.generated_sources == {"hello.cpp": "// hello"}

    def test_transition_without_artifacts(self):
        stage = SmokeStage()
        state = State(mode="new")
        agent_result = AgentResult(agent_name="ascendc-coder", status="ok")
        new_state = stage.transition(state, {"agent_result": agent_result})
        assert new_state.generated_sources is None

    def test_transition_no_agent_result(self):
        stage = SmokeStage()
        state = State(mode="new", op_name="unchanged")
        new_state = stage.transition(state, {})
        assert new_state is state

    def test_input_contract(self):
        c = SmokeStage().input_contract()
        assert c.requires == []
        assert "design_spec" in c.optional

    def test_output_contract(self):
        c = SmokeStage().output_contract()
        assert "generated_sources" in c.provides


class TestCodegenStage:
    @staticmethod
    def _gelu_state():
        return State(
            mode="new",
            op_name="gelu",
            rel_op_dir="inference/ascendc/src/g/c/ai_infra_gelu",
            full_op_name="ai_infra_gelu",
            design_spec={"op_type": "gelu", "description": "GELU activation"},
            tiling_strategy={"approach": "single_core"},
            kernel_architecture={"pipeline": ["CopyIn", "Compute", "CopyOut"]},
            profile=_omni_profile(),
        )

    def test_actions_new_mode(self):
        stage = CodegenStage()
        state = self._gelu_state()
        actions = stage.actions(state)
        assert len(actions) == 1
        a = actions[0]
        assert isinstance(a, SpawnAgent)
        assert a.agent_name == "ascendc-coder"

    def test_actions_incremental_mode(self):
        stage = CodegenStage()
        state = self._gelu_state().with_updates(mode="incremental")
        actions = stage.actions(state)
        assert actions[0].agent_name == "incremental-developer"

    def test_actions_iteration_with_error(self):
        stage = CodegenStage()
        state = self._gelu_state().with_updates(
            last_error=ErrorFeedback(
                stage_name="verify",
                error_type="compile_error",
                message="undefined symbol: GeluCustom",
            ),
        )
        actions = stage.actions(state, iteration=2)
        a = actions[0]
        assert "undefined symbol" in a.prompt
        # step-103：context 死通道已删——last_error 投递唯一通路是 prompt
        # 的跨 stage 反馈段（上方断言）。

    def test_transition_success(self, tmp_path):
        stage = CodegenStage()
        state = _attach_passing_deploy(self._gelu_state(), tmp_path)
        agent_result = AgentResult(
            agent_name="ascendc-coder",
            status="ok",
            artifacts={"gelu.cpp": "// kernel code"},
        )
        with _patch_deploy(smoke_passed=True):
            new_state = stage.transition(state, {"agent_result": agent_result})
        assert new_state.generated_sources == {"gelu.cpp": "// kernel code"}
        assert new_state.codegen_iterations == 1

    def test_transition_success_clears_residual_own_last_error(self, tmp_path):
        """A successful codegen transition must clear any residual
        last_error(stage_name=codegen). runner.py judges a stage as 'failed'
        when its own last_error is set — checked BEFORE output-contract
        satisfaction — so a stale fatal last_error carried in by resume would
        kill an actually-successful codegen stage. This is the regression that
        ended run 29a24f: codegen produced all 15 files + a complete manifest
        with consecutive_failures reset to 0, yet the run finished 'failed'
        because a residual last_error(stage_name=codegen, fatal) survived the
        success branch."""
        stage = CodegenStage()
        state = _attach_passing_deploy(
            self._gelu_state().with_updates(
                last_error=ErrorFeedback(
                    stage_name="codegen",
                    error_type="fatal",
                    message="Agent ascendc-coder returned status: fatal",
                ),
            ), tmp_path)
        agent_result = AgentResult(
            agent_name="ascendc-coder",
            status="ok",
            artifacts={"gelu.cpp": "// kernel code"},
        )
        with _patch_deploy(smoke_passed=True):
            new_state = stage.transition(state, {"agent_result": agent_result})
        assert new_state.generated_sources == {"gelu.cpp": "// kernel code"}
        assert new_state.last_error is None  # residual cleared on success

    def test_transition_accumulates_iterations(self, tmp_path):
        stage = CodegenStage()
        state = _attach_passing_deploy(
            self._gelu_state().with_updates(codegen_iterations=3), tmp_path)
        agent_result = AgentResult(
            agent_name="ascendc-coder",
            status="ok",
            artifacts={"gelu.cpp": "// v2"},
        )
        with _patch_deploy(smoke_passed=True):
            new_state = stage.transition(state, {"agent_result": agent_result})
        assert new_state.codegen_iterations == 4

    # —— P57-B (step-31 改动点 B): codegen owns the in-session build loop ——
    # Structural success now ALSO reads the agent's last redeploy handoff
    # (last_deploy.json) and asserts smoke_passed. These tests pin the new
    # build-loop contract: success = structural-complete AND smoke-passed.
    # The shared setup lives in the module-level `_attach_passing_deploy`.

    def test_codegen_transition_reads_deploy_result(self, tmp_path):
        """B4: structural success + smoke-passed → set build_result +
        deploy_result, clean success (last_error None)。成功离开 smoke 循环 → streak 重置。"""
        stage = CodegenStage()
        state = _attach_passing_deploy(self._gelu_state(), tmp_path,
                                          smoke_passed=True).with_updates(
            codegen_smoke_same_error_streak=2, codegen_smoke_last_error_sig="OLD_SIG")
        agent_result = AgentResult(
            agent_name="ascendc-coder", status="ok",
            artifacts=_gelu_artifacts(),
        )
        with _patch_deploy(smoke_passed=True):
            new_state = stage.transition(state, {"agent_result": agent_result})
        assert new_state.deploy_result is not None
        assert new_state.deploy_result.smoke_passed is True
        assert new_state.build_result is not None
        assert new_state.build_result.passed is True   # run_package present
        assert new_state.last_error is None
        # 成功 → smoke streak 重置为 0（防陈旧累计进未来上下文）
        assert new_state.codegen_smoke_same_error_streak == 0
        assert new_state.codegen_smoke_last_error_sig == ""

    def test_codegen_transition_compiles_before_install_and_smoke(self, tmp_path):
        """L4 改动 2 编排守护：transition 先调 Deployer.compile()；compile 成功 → 才调
        install_and_smoke() 且传入 compile 产物（复用不重 build）；compile 失败 → 不调
        install_and_smoke（不装系统）。"""
        from ascendc_devkit.orchestration.stages.deploy import Deployer
        stage = CodegenStage()
        state = _attach_passing_deploy(self._gelu_state(), tmp_path)
        agent_result = AgentResult(
            agent_name="ascendc-coder", status="ok",
            artifacts=_gelu_artifacts(),
        )
        calls: list[str] = []

        def _compile(s):
            calls.append("compile")
            return DeployResult(run_package="/pkg/gelu.run",
                                wheel_package="/pkg/gelu.whl",
                                smoke_passed=False), None

        def _install_and_smoke(s, compile_result):
            calls.append("install_and_smoke")
            # 断言 install_and_smoke 收到的是 compile 的产物（复用，不重 build）
            assert compile_result.run_package == "/pkg/gelu.run"
            assert compile_result.wheel_package == "/pkg/gelu.whl"
            return DeployResult(run_package=compile_result.run_package,
                                wheel_package=compile_result.wheel_package,
                                install_path="/opp", python_path="/py",
                                smoke_passed=True), None

        with mock.patch.object(Deployer, "compile", side_effect=_compile), \
             mock.patch.object(Deployer, "install_and_smoke",
                               side_effect=_install_and_smoke):
            new_state = stage.transition(state, {"agent_result": agent_result})

        assert calls == ["compile", "install_and_smoke"]  # 先 compile，成功才 install_and_smoke
        assert new_state.deploy_result is not None
        assert new_state.deploy_result.smoke_passed is True
        assert new_state.last_error is None

    def test_codegen_transition_compile_fail_skips_install(self, tmp_path):
        """L4 改动 2 编排守护：compile 失败（step=build）→ 不调 install_and_smoke（不装系统
        不 smoke），走 build-retry（不写 deploy_result → runner 重 spawn）。"""
        from ascendc_devkit.orchestration.stages.deploy import Deployer
        stage = CodegenStage()
        state = _attach_passing_deploy(self._gelu_state(), tmp_path)
        agent_result = AgentResult(
            agent_name="ascendc-coder", status="ok",
            artifacts=_gelu_artifacts(),
        )
        calls: list[str] = []
        compile_err = ErrorFeedback(
            stage_name="deploy", error_type="deploy_failed",
            message="build failed",
            details={"step": "build", "log": "/fake/build_ascendc.log",
                     "stderr_tail": "error: no matching function for call to 'Cast'"})

        def _compile(s):
            calls.append("compile")
            return DeployResult(smoke_passed=False), compile_err

        def _install_and_smoke(s, compile_result):
            calls.append("install_and_smoke")
            raise AssertionError("compile 失败时不应调用 install_and_smoke")

        with mock.patch.object(Deployer, "compile", side_effect=_compile), \
             mock.patch.object(Deployer, "install_and_smoke",
                               side_effect=_install_and_smoke):
            new_state = stage.transition(state, {"agent_result": agent_result})

        assert calls == ["compile"]               # install_and_smoke 未被调
        assert new_state.deploy_result is None    # contract 不满足 → runner 重 spawn
        assert new_state.codegen_build_feedback is not None  # 注入编译错误反馈
        assert new_state.last_error is None       # 不 halt

    def test_codegen_transition_does_not_halt_on_smoke_fail(self, tmp_path):
        """step-84 D4 (用户订正): 迭代用尽仍 smoke 未过 **不再 halt**——代码问题不是
        硬阻塞。codegen 尽力(会话内 max_rounds 自修)后如实告警 + 带
        deploy_result(smoke_passed=False) 继续往下走,交下游按职责拦截(runtime 崩溃 →
        precision_debug;真编译不过 → 下游 scope_guard 判 upstream)。**不设 codegen
        last_error**(那会经 runner fail_strategy 触发 halt 中断整条 pipeline);硬超时/
        infra 走各自独立通路,不受此分支影响。"""
        stage = CodegenStage()
        state = _attach_passing_deploy(self._gelu_state(), tmp_path,
                                          smoke_passed=False)
        agent_result = AgentResult(
            agent_name="ascendc-coder", status="ok",
            artifacts=_gelu_artifacts(),
        )
        with _patch_deploy(smoke_passed=False):
            new_state = stage.transition(state, {"agent_result": agent_result})
        assert new_state.deploy_result is not None
        assert new_state.deploy_result.smoke_passed is False
        assert new_state.build_result is not None
        # 关键: 不再设 codegen last_error → 不触发 halt, deploy_result 前进给下游
        assert new_state.last_error is None

    def test_codegen_smoke_fail_produces_no_halt_signal(self, tmp_path):
        """step-84 D4 接线端到端: transition 不设 last_error(上一测)→ 经 runner
        stage_status 判定为非 failed → **不设 _stage_failed halt 信号**(否则
        graph_executor 会中断 pipeline)。这是 D4 '不 halt' 的实际因果链,只测
        transition 层不够(还要证 runner 不据此 halt)。对照:结构性失败
        (no_last_deploy)仍应产生 halt 信号(fail_strategy 保留)。"""
        from ascendc_devkit.orchestration.kernel.runner import Runner
        # smoke-fail(迭代用尽): last_deploy.json 存在但 smoke_passed=False
        state = _attach_passing_deploy(self._gelu_state(), tmp_path,
                                       smoke_passed=False).with_updates(
                                           non_interactive=True)
        # 单轮:actions 首轮 spawn coder,transition 读 last_deploy → smoke_passed=False
        # → D4 分支(last_error=None)。run_stage 后不应带 _stage_failed。
        # 注:此处不真跑 agent(backend stub),聚焦 halt 信号因果——直接验 transition
        # 产物经 runner 语义不 halt。
        agent_result = AgentResult(agent_name="ascendc-coder", status="ok",
                                   artifacts=_gelu_artifacts())
        with _patch_deploy(smoke_passed=False):
            out = CodegenStage().transition(state, {"agent_result": agent_result})
        # own_error(本 stage last_error)= None → runner stage_status 不因 own_error
        # 变 failed → 不触发 fail_strategy=halt 的 _stage_failed(runner.py:527)。
        assert out.last_error is None
        assert getattr(out, "_stage_failed", None) is None, \
            "smoke-fail codegen 不应携带 halt 信号(D4:代码问题不 halt)"
        # deploy_result 前进给下游 precision_debug 的 scope_guard 分类
        assert out.deploy_result is not None and out.deploy_result.smoke_passed is False

    # —— 阶段3 方案 Z: 框架驱动 build-retry 新增测试 ——

    def test_codegen_build_failure_triggers_respawn(self, tmp_path):
        """阶段3 方案 Z: 编译失败 → 不写 deploy_result（contract 不满足 → runner 重 spawn）
        + 不设 last_error（不 halt）+ 收集 build_feedback 注入下轮。"""
        stage = CodegenStage()
        state = _attach_passing_deploy(self._gelu_state(), tmp_path)
        agent_result = AgentResult(agent_name="ascendc-coder", status="ok",
                                   artifacts=_gelu_artifacts())
        with _patch_deploy(build_fail=True):
            new_state = stage.transition(state, {"agent_result": agent_result})
        assert new_state.deploy_result is None  # contract 不满足 → runner 重 spawn
        assert new_state.codegen_build_retries == 1
        assert new_state.codegen_build_feedback is not None
        assert new_state.last_error is None  # 不 halt
        assert new_state.build_result is not None and new_state.build_result.passed is False

    def test_codegen_build_retry_exhausted_escapes_to_d4(self, tmp_path):
        """阶段3: build-retry 达上限 → D4 逃生（deploy_result smoke_passed=False 交下游，不 halt）。"""
        stage = CodegenStage()
        state = _attach_passing_deploy(
            self._gelu_state().with_updates(codegen_build_retries=999), tmp_path)
        agent_result = AgentResult(agent_name="ascendc-coder", status="ok",
                                   artifacts=_gelu_artifacts())
        with _patch_deploy(build_fail=True):
            new_state = stage.transition(state, {"agent_result": agent_result})
        assert new_state.deploy_result is not None
        assert new_state.deploy_result.smoke_passed is False
        assert new_state.last_error is None  # D4: 不 halt
        assert getattr(new_state, "_stage_failed", None) is None

    def test_codegen_smoke_passed_resets_build_retry_counters(self, tmp_path):
        """阶段3: build 失败一轮后第二轮 smoke 过 → 计数器归零、feedback 清空。"""
        stage = CodegenStage()
        state = _attach_passing_deploy(
            self._gelu_state().with_updates(
                codegen_build_retries=2,
                codegen_build_feedback={"error_class": "C-API"}), tmp_path)
        agent_result = AgentResult(agent_name="ascendc-coder", status="ok",
                                   artifacts=_gelu_artifacts("// kernel v2"))
        with _patch_deploy(smoke_passed=True):
            new_state = stage.transition(state, {"agent_result": agent_result})
        assert new_state.deploy_result.smoke_passed is True
        assert new_state.codegen_build_retries == 0
        assert new_state.codegen_build_feedback is None
        assert new_state.last_error is None

    def test_codegen_build_feedback_injected_into_prompt(self, tmp_path):
        """阶段3: build_feedback 注入下轮 coder prompt（error_class + 日志路径 + 不自己 build）。"""
        stage = CodegenStage()
        state = _attach_passing_deploy(
            self._gelu_state().with_updates(
                codegen_build_feedback={"error_class": "C-API", "log_path": "/r/build.log",
                                        "stderr_tail": "no matching function", "retry_count": 1}),
            tmp_path)
        actions = stage.actions(state, iteration=2)
        prompt = actions[0].prompt
        assert "C-API" in prompt
        assert "/r/build.log" in prompt
        assert "不要自己运行 build" in prompt
        # step-103：context 死通道已删（backend 零消费）——feedback 投递唯一
        # 通路是 prompt 反馈段（上方断言）与 resume 消息。
        # 2026-09-10：advisory 废弃——「重试策略」行不再渲染（机械 stop-loss 接管）
        assert "重试策略" not in prompt

    # —— Scaffolding authority: callable_target.kind is owned by the profile,
    #    NOT the agent (single truth source; no drift into smoke/deploy). ——

    def _scaffold_profile(self, selected="torch_op"):
        p = self._gelu_state().profile
        from ascendc_devkit.domain.repository import Scaffolding
        return dataclasses.replace(
            p, scaffolding=Scaffolding(
                supported=("torch_op", "aclnn", "pybind"), selected=selected))

    def test_kind_injected_from_profile_when_agent_omits_it(self, tmp_path):
        """Agent writes only `symbol`; codegen injects the profile-selected kind."""
        stage = CodegenStage()
        state = _attach_passing_deploy(
            self._gelu_state().with_updates(
                profile=self._scaffold_profile("torch_op")), tmp_path)
        agent_result = AgentResult(
            agent_name="ascendc-coder", status="ok",
            artifacts={
                "gelu.cpp": "// kernel",
                "codegen_manifest.json": json.dumps({
                    "op_name": "gelu",
                    "callable_target": {"symbol": "torch.ops.cann_bench.gelu"},
                }),
                **_gelu_torch_plugin(),
            },
        )
        with _patch_deploy(smoke_passed=True):
            new_state = stage.transition(state, {"agent_result": agent_result})
        assert new_state.last_error is None
        assert new_state.codegen_manifest["callable_target"]["kind"] == "torch_op"

    def test_agent_divergent_kind_overwritten_by_profile(self, tmp_path):
        """Agent-chosen kind that differs from the profile is overwritten (the
        profile is the authority — closes the drift that let the agent pick a
        weak/wrong protocol)."""
        stage = CodegenStage()
        state = _attach_passing_deploy(
            self._gelu_state().with_updates(
                profile=self._scaffold_profile("pybind")), tmp_path)
        agent_result = AgentResult(
            agent_name="ascendc-coder", status="ok",
            artifacts={
                "gelu.cpp": "// kernel",
                "codegen_manifest.json": json.dumps({
                    "op_name": "gelu",
                    # agent wrongly claims torch_op; profile says pybind
                    "callable_target": {"kind": "torch_op", "symbol": "m.gelu"},
                }),
            },
        )
        with _patch_deploy(smoke_passed=True):
            new_state = stage.transition(state, {"agent_result": agent_result})
        assert new_state.codegen_manifest["callable_target"]["kind"] == "pybind"

    def test_manifest_without_symbol_derives_from_plugin(self, tmp_path):
        """callable_target.symbol missing but op_plugin registration present →
        framework derives the symbol from TORCH_LIBRARY_FRAGMENT (§2.9
        constructive guarantee — the symbol is determined by the plugin, not
        independent info). No halt, no retry; proceeds to deploy. (Supersedes
        the old 'manifest_without_symbol_is_incomplete_output' which encoded the
        dequant bug: halting on a missing symbol despite a correct plugin.)"""
        stage = CodegenStage()
        state = _attach_passing_deploy(
            self._gelu_state().with_updates(
                profile=self._scaffold_profile("torch_op")), tmp_path)
        agent_result = AgentResult(
            agent_name="ascendc-coder", status="ok",
            artifacts={
                **_gelu_torch_plugin(),
                "codegen_manifest.json": json.dumps({
                    "op_name": "gelu",
                    "inputs": [{"name": "x", "type": "Tensor"}],
                    "outputs": [{"name": "y", "type": "Tensor"}],
                    "callable_target": {},   # no symbol → derived from plugin
                }),
            },
        )
        with _patch_deploy(smoke_passed=True):
            new_state = stage.transition(state, {"agent_result": agent_result})
        assert new_state.last_error is None  # derived, not halted/retried
        assert new_state.codegen_manifest["callable_target"]["symbol"] == \
            "torch.ops.cann_bench.gelu"
        assert new_state.deploy_result is not None  # proceeded to deploy

    def test_torch_profile_without_plugin_is_incomplete_output(self, tmp_path):
        stage = CodegenStage()
        state = _attach_passing_deploy(
            self._gelu_state().with_updates(
                profile=self._scaffold_profile("torch_op")), tmp_path)
        agent_result = AgentResult(
            agent_name="ascendc-coder",
            status="ok",
            artifacts={
                "gelu.cpp": "// kernel",
                "codegen_manifest.json": json.dumps({
                    "op_name": "gelu",
                    "inputs": [{"name": "x", "type": "Tensor"}],
                    "outputs": [{"name": "y", "type": "Tensor"}],
                    "callable_target": {
                        "symbol": "torch.ops.cann_bench.gelu",
                    },
                }),
            },
        )

        new_state = stage.transition(state, {"agent_result": agent_result})

        assert new_state.last_error is not None
        assert new_state.last_error.details["reason"] == \
            "torch_op_plugin_missing_or_invalid"

    def test_torch_profile_with_host_offload_plugin(self, tmp_path):
        """维10③ 机械门接线（Membase 路径）：plugin 含 .cpu()/kCPU host 往返 →
        transition 返回 plugin_host_offload（硬门，不 proceed 到 deploy）。"""
        stage = CodegenStage()
        state = _attach_passing_deploy(
            self._gelu_state().with_updates(
                profile=self._scaffold_profile("torch_op")), tmp_path)
        host_offload_plugin = (
            "TORCH_LIBRARY_FRAGMENT(cann_bench, m) {\n"
            '    m.def("gelu(Tensor x) -> Tensor");\n'
            "}\n"
            "static torch::Tensor gelu_npu(const at::Tensor& x) {\n"
            "    auto cx = x.to(torch::kCPU).contiguous();\n"
            "    auto y = torch::empty_like(x);\n"
            "    y.copy_(cx);\n"
            "    return y;\n"
            "}\n"
        )
        agent_result = AgentResult(
            agent_name="ascendc-coder",
            status="ok",
            artifacts={
                "op_plugin/gelu_plugin.cpp": host_offload_plugin,
                "codegen_manifest.json": json.dumps(_COMPLETE_MANIFEST),
            },
        )
        with _patch_deploy(smoke_passed=True):
            new_state = stage.transition(state, {"agent_result": agent_result})
        assert new_state.last_error is not None
        assert new_state.last_error.details["reason"] == "plugin_host_offload"

    def test_prompt_tells_agent_not_to_choose_kind(self):
        """The prompt states the protocol is profile-selected and instructs the
        agent not to emit `kind` (§ single-authority)."""
        stage = CodegenStage()
        state = self._gelu_state().with_updates(
            profile=self._scaffold_profile("torch_op"))
        prompt = stage.actions(state)[0].prompt
        assert "torch_op" in prompt
        assert "callable_target" in prompt
        assert "op_plugin/*.cpp" in prompt
        assert "优先于 Markdown 详设" in prompt

    def test_codegen_transition_halts_on_unfixable_deploy_error(self, tmp_path):
        """阶段3 方案 Z: deploy resolve 阶段失败（repo/profile 缺失）等不可修错误 → halt
        (设 last_error)。不同于 build/smoke 失败（可重试/交下游），resolve 失败意味着
        框架无法继续，必须 halt 并暴露可诊断信号（§1.2）。"""
        stage = CodegenStage()
        state = _attach_passing_deploy(self._gelu_state(), tmp_path)
        agent_result = AgentResult(
            agent_name="ascendc-coder", status="ok",
            artifacts=_gelu_artifacts(),
        )
        with _patch_deploy(resolve_fail=True):
            new_state = stage.transition(state, {"agent_result": agent_result})
        assert new_state.last_error is not None
        assert new_state.last_error.error_type == "deploy_failed"

    def test_codegen_prompt_no_longer_injects_redeploy_loop(self, tmp_path):
        """阶段3 方案 Z: coder 不再自己 build/redeploy，框架在 transition 直调 Deployer.deploy。
        prompt 不含 redeploy/max_rounds in-session 指令。"""
        stage = CodegenStage()
        ws = Workspace.create(output_root=str(tmp_path / "out"), run_id="r3")
        state = self._gelu_state().with_updates(_workspace=ws, user_max_iterations=4)
        actions = stage.actions(state)
        prompt = actions[0].prompt
        assert "ascendc-devkit redeploy" not in prompt
        assert "max_rounds" not in prompt
        assert "最多" not in prompt
        assert actions[0].context.get("max_rounds") is None

    def test_codegen_no_legacy_loopback_feedback(self):
        """B5: a state carrying a FAILING build_result must NOT feed
        build_failure/precision_failure into prompt/context — codegen now
        self-closes build via its in-session redeploy loop (B1), and precision
        routes to precision_debug (P54). No cross-stage build/precision
        loopback into codegen."""
        stage = CodegenStage()
        state = self._gelu_state().with_updates(
            build_result=BuildResult(passed=False, stderr="boom"),
        )
        actions = stage.actions(state)
        prompt = actions[0].prompt
        assert "build_failure" not in actions[0].context
        assert "precision_failure" not in actions[0].context
        assert "编译失败" not in prompt            # build_result-driven section removed
        assert "精度不达标" not in prompt          # precision-driven section removed

    def test_transition_error(self):
        stage = CodegenStage()
        state = self._gelu_state()
        agent_result = AgentResult(agent_name="ascendc-coder", status="fatal")
        new_state = stage.transition(state, {"agent_result": agent_result})
        assert new_state.last_error is not None
        assert new_state.last_error.stage_name == "codegen"
        assert new_state.codegen_iterations == 1

    def test_transition_no_agent_result(self):
        stage = CodegenStage()
        state = self._gelu_state()
        new_state = stage.transition(state, {})
        assert new_state is state

    def test_transition_partial_counts_as_failure(self):
        """F1: a 'partial' result (agent crashed mid-run but wrote files) must
        be treated as a failure — codegen_consecutive_failures increments and
        the half-baked files are NOT propagated as generated_sources."""
        stage = CodegenStage()
        state = self._gelu_state()
        agent_result = AgentResult(
            agent_name="ascendc-coder",
            status="partial",
            artifacts={"gelu.cpp": "// half-written"},
            metrics={"failure_reason": "API Error: Content block not found"},
        )
        new_state = stage.transition(state, {"agent_result": agent_result})
        assert new_state.codegen_consecutive_failures == 1
        assert new_state.generated_sources != {"gelu.cpp": "// half-written"}
        assert new_state.last_error is not None
        assert new_state.last_error.error_type == "partial"

    def test_transition_infra_failure_does_not_increment_breaker(self):
        """P50: an infra failure (503 no channel / 429 quota / auth) is NOT a
        logic failure — the coder never ran. The breaker must stay untouched so
        a transient/fixable env issue can't poison it, and last_error carries
        error_type='infra' + the actionable reason."""
        stage = CodegenStage()
        state = self._gelu_state().with_updates(codegen_consecutive_failures=2)
        agent_result = AgentResult(
            agent_name="ascendc-coder",
            status="fatal",
            error_type="infra",
            metrics={"failure_reason": "503 No available channel for model deepseek-v4-pro"},
        )
        new_state = stage.transition(state, {"agent_result": agent_result})
        # breaker NOT incremented (would have been 3 → trip)
        assert new_state.codegen_consecutive_failures == 2
        assert new_state.last_error is not None
        assert new_state.last_error.error_type == "infra"
        assert "503 No available channel" in new_state.last_error.message

    def test_actions_infra_last_error_halts_without_spawn(self):
        """P50: after an infra failure, the next actions() call must halt the
        stage (return []) WITHOUT spawning — retrying within the run is futile.
        Mirrors the circuit-breaker pattern but leaves the breaker untouched."""
        stage = CodegenStage()
        state = self._gelu_state().with_updates(
            last_error=ErrorFeedback(
                stage_name="codegen",
                error_type="infra",
                message="Infrastructure error: 503 No available channel",
            ),
        )
        actions = stage.actions(state)
        assert actions == []

    def test_actions_logic_last_error_still_spawns(self):
        """P50: only infra-typed last_error halts pre-spawn. A logic error
        (compile_error) must still spawn so the coder can retry."""
        stage = CodegenStage()
        state = self._gelu_state().with_updates(
            last_error=ErrorFeedback(
                stage_name="verify",
                error_type="compile_error",
                message="undefined symbol: GeluCustom",
            ),
        )
        actions = stage.actions(state)
        assert len(actions) == 1
        assert isinstance(actions[0], SpawnAgent)

    def test_transition_partial_snapshots_to_artifacts(self, tmp_path):
        """F1: partial output is snapshotted to artifacts/codegen for inspection."""
        from ascendc_devkit.infra.workspace import Workspace
        ws = Workspace.create(output_root=str(tmp_path / "output"))
        stage = CodegenStage()
        state = self._gelu_state().with_updates(_workspace=ws)
        agent_result = AgentResult(
            agent_name="ascendc-coder",
            status="partial",
            artifacts={"gelu.cpp": "// half-written"},
        )
        stage.transition(state, {"agent_result": agent_result})
        snap = ws.artifacts / "codegen" / "gelu.cpp"
        assert snap.is_file()
        assert snap.read_text() == "// half-written"

    def test_circuit_breaker_trips_after_consecutive_failures(self):
        """F1/F4: three consecutive failures (partial counts) trip the breaker,
        so actions() returns [] instead of re-spawning forever."""
        stage = CodegenStage()
        from ascendc_devkit.orchestration.runtime_config import retry_budgets
        state = self._gelu_state().with_updates(
            codegen_consecutive_failures=retry_budgets()["consecutive_failures_max"],
        )
        assert stage.actions(state) == []

    def test_input_contract(self):
        c = CodegenStage().input_contract()
        assert "design_spec" in c.requires
        assert "tiling_strategy" in c.requires
        # kernel_architecture moved to optional (step 9):
        # now provided by codegen_init, not required from design.
        assert "kernel_architecture" in c.optional
        assert "mode" in c.requires
        assert "profile" in c.requires
        assert "reference_code" in c.optional

    def test_output_contract(self):
        c = CodegenStage().output_contract()
        assert "generated_sources" in c.provides
        assert "codegen_iterations" in c.provides
        # change_set is incremental-mode only, not in base provides

    def test_prompt_references_materialized_design_products(self):
        # F2: design products are CWD files, not prompt-injected JSON.
        stage = CodegenStage()
        prompt = stage._build_codegen_prompt(self._gelu_state(), 1)
        assert "design_spec.json" in prompt
        assert "tiling_strategy.json" in prompt
        assert "kernel_architecture.json" in prompt

    def test_prompt_drops_skill_duplicated_methodology(self):
        """编码方法论（蓝图优先级/编码规则）归 ascendc-op-dev-coding skill 单源承载
        （spawn 经 primary_skill slash 注入 SKILL.md），prompt 不再复写（§2.5 唯一
        通路）；方法论仍在 skill 单源（防误删）。"""
        stage = CodegenStage()
        prompt = stage._build_codegen_prompt(self._gelu_state(), 1)
        assert "## 编码规则" not in prompt
        assert "## 实现蓝图优先级" not in prompt
        skill_md = (Path(__file__).resolve().parents[3]
                    / ".claude" / "skills" / "ascendc-op-dev-coding" / "SKILL.md")
        t = skill_md.read_text(encoding="utf-8")
        assert "ASCENDC_TPL" in t, "TilingKey 模板参数化方法论须留在 skill 单源"
        assert "32 字节对齐" in t, "对齐自检须留在 skill 单源"
        assert "立即 Write/Edit 落盘" in t, "增量落盘纪律须留在 skill 单源"

    def test_prompt_contains_plan_a_repo_instructions(self):
        stage = CodegenStage()
        prompt = stage._build_codegen_prompt(self._gelu_state(), 1)
        # P3+P4: staging dir isolation + op_host/op_kernel placement rules
        assert "op_host" in prompt or "op_kernel" in prompt, "dir placement rules missing"
        assert "op_dir" in prompt
        assert "构建中间物" in prompt
        # P4: changed_files.json moved to staging, not op_dir
        assert "不要" in prompt or "Do not" in prompt

    def test_prompt_contains_target_repo_convention(self):
        stage = CodegenStage()
        prompt = stage._build_codegen_prompt(self._gelu_state(), 1)
        assert "bash build.sh" in prompt

    def test_validate_inputs_valid_design_spec(self):
        stage = CodegenStage()
        state = State(design_spec={"inputs": [{"name": "x"}], "outputs": [{"name": "y"}]})
        assert stage.validate_inputs(state) == []

    def test_validate_inputs_empty_inputs(self):
        stage = CodegenStage()
        state = State(design_spec={"inputs": [], "outputs": [{"name": "y"}]})
        errors = stage.validate_inputs(state)
        assert any("inputs" in e for e in errors)

    def test_validate_inputs_empty_outputs(self):
        stage = CodegenStage()
        state = State(design_spec={"inputs": [{"name": "x"}], "outputs": []})
        errors = stage.validate_inputs(state)
        assert any("outputs" in e for e in errors)

    def test_validate_inputs_non_dict(self):
        stage = CodegenStage()
        state = State(design_spec="not_a_dict")
        errors = stage.validate_inputs(state)
        assert any("must be a dict" in e for e in errors)

    def test_validate_inputs_chip_mismatch_is_precondition(self):
        """§1.9 chip-gate as codegen precondition (step-34): design≠runtime →
        validate_inputs returns a concrete chip error naming BOTH values, so the
        runner raises PreconditionError BEFORE spawning the coder. The gate is a
        PURE comparison against the dispatch-resolved runtime chip — no probe
        here (the runtime chip was resolved once at dispatch, Step 3). The chip
        check is additive — a well-formed design_spec still passes its own shape
        check (the chip error neither masks nor is masked by the shape check)."""
        stage = CodegenStage()
        state = State(
            design_spec={"inputs": [{"name": "x"}],
                         "outputs": [{"name": "y"}]},
            design_target_chip="A5", runtime_target_chip="A2")
        errors = stage.validate_inputs(state)
        chip_errors = [e for e in errors if "'A5'" in e and "'A2'" in e]
        assert len(chip_errors) == 1
        # design_spec shape still passes (chip check is additive, §1.2 可扩展)
        assert not any("inputs" in e or "outputs" in e for e in errors)

    def test_validate_inputs_chip_match_no_error(self):
        """design==runtime → no chip error; a valid design_spec returns []. The
        gate is a pure comparison (no probe) — a match is a plain == check."""
        stage = CodegenStage()
        state = State(
            design_spec={"inputs": [{"name": "x"}],
                         "outputs": [{"name": "y"}]},
            design_target_chip="A2", runtime_target_chip="A2")
        assert stage.validate_inputs(state) == []

    # Retired with their behavior (step-34): the probe-timeout and assume_chip
    # paths in the gate are gone. The gate no longer probes (runtime chip is
    # resolved once at dispatch — Step 3; a probe timeout is handled there via
    # --runtime_target_chip fallback / EX_DATAERR, covered by
    # test_dispatcher_chip_resolution.py), and assume_chip is gone entirely (§1.4).

    def test_transition_missing_expected_section(self):
        """P2 section-level: agent produces only op_kernel files → missing op_host section."""
        stage = CodegenStage()
        state = State(
            mode="new",
            kernel_architecture={
                "host_code": {"directory": "op_host"},
                "kernel_code": {"directory": "op_kernel"},
            },
        )
        agent_result = AgentResult(
            agent_name="ascendc-coder",
            status="ok",
            artifacts={"op_kernel/gelu.cpp": "// only kernel"},
        )
        new_state = stage.transition(state, {"agent_result": agent_result})
        assert new_state.last_error is not None
        assert new_state.last_error.error_type == "incomplete_output"
        # Section-level error: missing op_host (not individual files)
        assert "op_host" in new_state.last_error.message
        # Partial output still saved
        assert new_state.generated_sources == {"op_kernel/gelu.cpp": "// only kernel"}

    def test_transition_all_sections_covered(self, tmp_path):
        """P2 section-level: agent produces at least one file in each expected section → success."""
        stage = CodegenStage()
        state = _attach_passing_deploy(State(
            mode="new",
            kernel_architecture={
                "host_code": {"directory": "op_host"},
                "kernel_code": {"directory": "op_kernel"},
            },
        ), tmp_path)
        agent_result = AgentResult(
            agent_name="ascendc-coder",
            status="ok",
            artifacts={
                "op_host/gelu_tiling.h": "// tiling",
                "op_kernel/gelu.cpp": "// kernel",
            },
        )
        with _patch_deploy(smoke_passed=True):
            new_state = stage.transition(state, {"agent_result": agent_result})
        assert new_state.last_error is None
        assert new_state.generated_sources is not None

    def test_transition_incremental_section_exists_in_op_dir(self, tmp_path):
        """P2 section-level: incremental mode tolerates a missing section when
        the section dir already exists on disk with files from a prior run."""
        from ascendc_devkit.domain.operator import OperatorSpec, OperatorIdentity
        op_dir = tmp_path / "ops" / "gelu"
        (op_dir / "op_host").mkdir(parents=True)
        (op_dir / "op_kernel").mkdir(parents=True)
        (op_dir / "op_host" / "gelu_tiling.h").write_text("// existing tiling\n", encoding="utf-8")
        stage = CodegenStage()
        state = _attach_passing_deploy(State(
            mode="incremental",
            op_identity=OperatorIdentity(
                spec=OperatorSpec(name="gelu"),
                repo_root=tmp_path, op_dir=op_dir,
            ),
            kernel_architecture={
                "host_code": {"directory": "op_host"},
                "kernel_code": {"directory": "op_kernel"},
            },
        ), tmp_path)
        # Agent only changed op_kernel files this run.
        agent_result = AgentResult(
            agent_name="ascendc-coder", status="ok",
            artifacts={"op_kernel/gelu.cpp": "// edited kernel"},
        )
        with _patch_deploy(smoke_passed=True):
            new_state = stage.transition(state, {"agent_result": agent_result})
        # op_host/ dir already exists on disk → not flagged missing.
        assert new_state.last_error is None

    def test_transition_incremental_truly_missing_still_errors(self, tmp_path):
        """P2 section-level: incremental mode reports error when a section
        dir is neither in artifacts nor on disk."""
        from ascendc_devkit.domain.operator import OperatorSpec, OperatorIdentity
        op_dir = tmp_path / "ops" / "gelu"
        (op_dir / "op_kernel").mkdir(parents=True)
        stage = CodegenStage()
        state = State(
            mode="incremental",
            op_identity=OperatorIdentity(
                spec=OperatorSpec(name="gelu"),
                repo_root=tmp_path, op_dir=op_dir,
            ),
            kernel_architecture={
                "host_code": {"directory": "op_host"},
                "kernel_code": {"directory": "op_kernel"},
            },
        )
        agent_result = AgentResult(
            agent_name="ascendc-coder", status="ok",
            artifacts={"op_kernel/gelu.cpp": "// edited kernel"},
        )
        new_state = stage.transition(state, {"agent_result": agent_result})
        assert new_state.last_error is not None
        assert new_state.last_error.error_type == "incomplete_output"
        # Section-level error: missing op_host section
        assert "op_host" in new_state.last_error.message

    # —— manifest 契约：构造性派生 callable_target + 机械校验 + 定向 retry ——
    # dequant RCA (20260804 批): agent 把 codegen_manifest 当报告写（塞调试笔记），
    # 漏 callable_target/inputs/outputs，框架却 halt（尽管 plugin 正确）。修复：
    # 从 plugin 注册派生 callable_target.symbol（§2.9 构造性）+ 机械校验 required_keys
    # 缺则定向 retry（§3.4）+ retry 耗尽 halt（§1.10，无可调用算子交下游）。

    def test_manifest_ct_absent_derives_from_plugin_and_proceeds(self, tmp_path):
        """torch_op + plugin 正确 + manifest 漏 callable_target（inputs/outputs 在）
        → 框架从 plugin 注册派生 symbol，不 halt，进 deploy（dequant-like 但 inputs/outputs 齐）。"""
        stage = CodegenStage()
        state = _attach_passing_deploy(
            self._gelu_state().with_updates(profile=_torch_op_profile()), tmp_path)
        manifest = {"op_name": "Gelu",
                    "inputs": [{"name": "x", "type": "Tensor"}],
                    "outputs": [{"name": "y", "type": "Tensor"}]}
        agent_result = AgentResult(
            agent_name="ascendc-coder", status="ok",
            artifacts={"op_plugin/gelu_plugin.cpp": _PLUGIN_SRC,
                       "codegen_manifest.json": json.dumps(manifest)})
        with _patch_deploy(smoke_passed=True):
            new_state = stage.transition(state, {"agent_result": agent_result})
        # 派生：symbol 从 TORCH_LIBRARY_FRAGMENT(cann_bench)+m.def(gelu) 来
        ct = new_state.codegen_manifest["callable_target"]
        assert ct["symbol"] == "torch.ops.cann_bench.gelu"
        assert ct["kind"] == "torch_op"
        # 无 missing → 不 retry → 进 deploy
        assert new_state.last_error is None
        assert new_state.deploy_result is not None
        assert new_state.codegen_artifact_retries == 0
        assert new_state.codegen_artifact_feedback is None

    def test_manifest_missing_inputs_outputs_no_retry(self, tmp_path):
        """P1 收敛（2026-08-19）：manifest 缺 inputs/outputs 不再触发 retry——IO 不被下游
        消费（下游只读 callable_target+op_name，harness 绑 golden 用 op_spec），降为可选；
        callable_target 从 plugin 派生补上 → 契约满足 → 直接进 deploy。"""
        stage = CodegenStage()
        state = _attach_passing_deploy(
            self._gelu_state().with_updates(profile=_torch_op_profile()), tmp_path)
        # dequant 现场：manifest 有 op_name + 调试笔记，无 inputs/outputs/callable_target
        manifest = {"op_name": "Gelu", "compile_status": "verified_pass",
                    "runtime_status": {"t0": "segfault"}}
        agent_result = AgentResult(
            agent_name="ascendc-coder", status="ok",
            artifacts={"op_plugin/gelu_plugin.cpp": _PLUGIN_SRC,
                       "codegen_manifest.json": json.dumps(manifest)})
        with _patch_deploy(smoke_passed=True):
            new_state = stage.transition(state, {"agent_result": agent_result})
        # 无 retry：不 halt、写 deploy_result（契约满足 → 进 deploy）
        assert new_state.last_error is None
        assert new_state.deploy_result is not None
        assert new_state.codegen_artifact_retries == 0
        assert new_state.codegen_artifact_feedback is None
        # callable_target 由框架从 plugin 派生
        assert new_state.codegen_manifest["callable_target"]["symbol"] == \
            "torch.ops.cann_bench.gelu"

    def test_manifest_plugin_missing_triggers_artifact_retry(self, tmp_path):
        """torch_op + 无 plugin（callable_target 不可派生）→ retry（不 halt）。"""
        stage = CodegenStage()
        state = _attach_passing_deploy(
            self._gelu_state().with_updates(profile=_torch_op_profile()), tmp_path)
        manifest = {"op_name": "Gelu",
                    "inputs": [{"name": "x", "type": "Tensor"}],
                    "outputs": [{"name": "y", "type": "Tensor"}]}  # 无 plugin → 无 callable_target
        agent_result = AgentResult(
            agent_name="ascendc-coder", status="ok",
            artifacts={"op_kernel/gelu.cpp": "// kernel",
                       "codegen_manifest.json": json.dumps(manifest)})
        with _patch_deploy(smoke_passed=True):
            new_state = stage.transition(state, {"agent_result": agent_result})
        assert new_state.last_error is None
        assert new_state.deploy_result is None
        assert new_state.codegen_artifact_retries == 1
        assert "callable_target" in \
            new_state.codegen_artifact_feedback["missing_fields"]

    def test_artifact_retry_exhausted_halts(self, tmp_path):
        """retry 耗尽 → halt（无可调用算子交下游，§1.10；非 build-retry D4）。
        P1 收敛后：无 plugin（callable_target 不可派生）才触发 artifact retry。
        error_type 落 exhausted 终态类（taxonomy：exhausted→__halt__）——不得
        留在 incomplete_output（可重试类），否则 runner R1 归一化/F6 清错会把
        耗尽 halt 信号当过时错误抹掉（耗尽冒充成功交付）。"""
        stage = CodegenStage()
        state = _attach_passing_deploy(
            self._gelu_state().with_updates(
                profile=_torch_op_profile(),
                codegen_artifact_retries=999), tmp_path)
        manifest = {"op_name": "Gelu"}  # 无 plugin → callable_target 不可派生
        agent_result = AgentResult(
            agent_name="ascendc-coder", status="ok",
            artifacts={"op_kernel/gelu.cpp": "// kernel",
                       "codegen_manifest.json": json.dumps(manifest)})
        with _patch_deploy(smoke_passed=True):
            new_state = stage.transition(state, {"agent_result": agent_result})
        assert new_state.last_error is not None
        assert new_state.last_error.error_type == "exhausted"
        assert new_state.last_error.stage_name == "codegen"
        assert (new_state.last_error.details.get("reason")
                == "manifest_non_conforming_exhausted")
        assert "retries" in new_state.last_error.message

    def test_non_torch_op_manifest_ct_missing_triggers_retry(self, tmp_path):
        """非 torch_op（pybind profile）+ manifest 缺 callable_target.symbol
        → 不伪装派生（aclnn/pybind 无注册解析器，§3.7 诚实），走 retry。"""
        stage = CodegenStage()
        state = _attach_passing_deploy(
            self._gelu_state().with_updates(
                profile=self._scaffold_profile("pybind")), tmp_path)
        manifest = {"op_name": "Gelu",
                    "inputs": [{"name": "x", "type": "Tensor"}],
                    "outputs": [{"name": "y", "type": "Tensor"}]}  # 无 callable_target.symbol
        agent_result = AgentResult(
            agent_name="ascendc-coder", status="ok",
            artifacts={"op_kernel/gelu.cpp": "// kernel",
                       "codegen_manifest.json": json.dumps(manifest)})
        with _patch_deploy(smoke_passed=True):
            new_state = stage.transition(state, {"agent_result": agent_result})
        # 非 torch_op：不派生 symbol，callable_target.symbol 缺 → retry
        assert new_state.last_error is None
        assert new_state.deploy_result is None
        assert new_state.codegen_artifact_retries == 1
        assert "callable_target" in \
            new_state.codegen_artifact_feedback["missing_fields"]
        # 没有塞进假 symbol
        ct = (new_state.codegen_manifest or {}).get("callable_target")
        assert not (isinstance(ct, dict) and ct.get("symbol"))

    def test_artifact_feedback_injected_into_prompt(self, tmp_path):
        """artifact_feedback 注入下轮 coder prompt（缺字段清单 + 契约提示）。
        P1 收敛后典型缺字段为 callable_target（inputs/outputs 不再 required）。"""
        stage = CodegenStage()
        state = self._gelu_state().with_updates(
            profile=_torch_op_profile(),
            codegen_artifact_feedback={
                "reason": "manifest_non_conforming",
                "missing_fields": ["callable_target"],
                "retry_count": 1,
                "hint": "fill callable_target per schema"})
        actions = stage.actions(state, iteration=2)
        prompt = actions[0].prompt
        assert "callable_target" in prompt
        assert "签名契约" in prompt  # contract/report 分离提示

    def test_missing_required_manifest_fields_helper(self):
        """机械校验 helper：按 schema required_keys（P1 收敛后 = op_name/callable_target，
        inputs/outputs/attrs 可选）返回缺失字段。"""
        stage = CodegenStage.__new__(CodegenStage)
        assert set(stage._missing_required_manifest_fields(None)) == \
            {"op_name", "callable_target"}
        assert stage._missing_required_manifest_fields({"op_name": "X"}) == \
            ["callable_target"]
        # 缺 inputs/outputs 不再判缺（P1 收敛：IO 不被下游消费）
        assert stage._missing_required_manifest_fields(
            {"op_name": "X", "callable_target": {"kind": "torch_op",
                                                 "symbol": "torch.ops.n.o"}}) == []
        complete = {"op_name": "X",
                    "inputs": [{"name": "x"}], "outputs": [{"name": "y"}],
                    "callable_target": {"kind": "torch_op",
                                        "symbol": "torch.ops.n.o"}}
        assert stage._missing_required_manifest_fields(complete) == []
        # callable_target 深查：有 dict 但缺 symbol → 仍判缺
        partial = dict(complete, callable_target={"kind": "torch_op"})
        assert "callable_target" in stage._missing_required_manifest_fields(partial)

    def test_rerun_reset_includes_artifact_fields(self):
        """rerun_reset_fields 含新字段（rerun 时归零，防 stale trip）。"""
        fields = CodegenStage().rerun_reset_fields()
        assert "codegen_artifact_retries" in fields
        assert "codegen_artifact_feedback" in fields

    def test_state_artifact_fields_default(self):
        """新 State 字段默认值（from_snapshot registry 保证旧快照可加载）。"""
        s = State(mode="new", op_name="gelu")
        assert s.codegen_artifact_retries == 0
        assert s.codegen_artifact_feedback is None


# —— 方案 A/B：plugin 返回签名一致性——脚手架问题由 codegen 解决（不 defer）——————

# unique 20260808 根因形态：m.def 声明 `(Tensor, Tensor?)` 定长元组，但实现返回
# std::vector<Tensor>（PyTorch 推断 Tensor[]，1 个变长返回）→ checkSchema 拒注册。
_UNIQUE_BUG_PLUGIN = (
    "TORCH_LIBRARY_FRAGMENT(cann_bench, m) {\n"
    '    m.def("unique(Tensor x, bool return_inverse=False) -> (Tensor, Tensor?)");\n'
    "}\n"
    "static std::vector<torch::Tensor> unique_npu("
    "const torch::Tensor& x, bool returnInverse) { return {}; }\n"
    "TORCH_LIBRARY_IMPL(cann_bench, PrivateUse1, m) {\n"
    '    m.impl("unique", unique_npu);\n'
    "}\n"
)
# 修复后形态：实现返回 std::tuple<..., optional<...>> 匹配 m.def。
_UNIQUE_FIXED_PLUGIN = (
    "TORCH_LIBRARY_FRAGMENT(cann_bench, m) {\n"
    '    m.def("unique(Tensor x, bool return_inverse=False) -> (Tensor, Tensor?)");\n'
    "}\n"
    "static std::tuple<at::Tensor, std::optional<at::Tensor>> unique_npu("
    "const at::Tensor& x, bool returnInverse) { return {}; }\n"
    "TORCH_LIBRARY_IMPL(cann_bench, PrivateUse1, m) {\n"
    '    m.impl("unique", unique_npu);\n'
    "}\n"
)
# 现存正常算子的真实形态（回归护栏：A 必须零误报）。
_SINGLE_TENSOR_PLUGIN = (
    "TORCH_LIBRARY_FRAGMENT(cann_bench, m) {\n"
    '    m.def("softmax(Tensor x, int dim) -> Tensor");\n'
    "}\n"
    "static torch::Tensor softmax_npu(const torch::Tensor& x, int64_t dim) "
    "{ return x; }\n"
    "TORCH_LIBRARY_IMPL(cann_bench, PrivateUse1, m) {\n"
    '    m.impl("softmax", softmax_npu);\n'
    "}\n"
)
_TUPLE_PLUGIN = (
    "TORCH_LIBRARY_FRAGMENT(cann_bench, m) {\n"
    '    m.def("apply_rotary_pos_emb(Tensor x) -> (Tensor, Tensor)");\n'
    "}\n"
    "static std::tuple<torch::Tensor, torch::Tensor> apply_rotary_pos_emb_npu("
    "const torch::Tensor& x) { return {}; }\n"
    "TORCH_LIBRARY_IMPL(cann_bench, PrivateUse1, m) {\n"
    '    m.impl("apply_rotary_pos_emb", apply_rotary_pos_emb_npu);\n'
    "}\n"
)
_TENSORLIST_PLUGIN = (
    "TORCH_LIBRARY_FRAGMENT(cann_bench, m) {\n"
    '    m.def("foreach_norm(Tensor[] x, float p=2.0) -> Tensor[]");\n'
    "}\n"
    "static std::vector<torch::Tensor> foreach_norm_npu("
    "c10::List<at::Tensor> x, double p) { return {}; }\n"
    "TORCH_LIBRARY_IMPL(cann_bench, PrivateUse1, m) {\n"
    '    m.impl("foreach_norm", foreach_norm_npu);\n'
    "}\n"
)

_UNIQUE_MANIFEST = {
    "op_name": "Unique",
    "inputs": [{"name": "x", "type": "Tensor"}],
    "outputs": [{"name": "y", "type": "Tensor"},
                {"name": "inverse", "type": "Tensor?"}],
    "callable_target": {"kind": "torch_op", "symbol": "torch.ops.cann_bench.unique"},
}

_SOFTMAX_MANIFEST = {
    "op_name": "Softmax",
    "inputs": [{"name": "x", "type": "Tensor"}],
    "outputs": [{"name": "y", "type": "Tensor"}],
    "callable_target": {"kind": "torch_op", "symbol": "torch.ops.cann_bench.softmax"},
}


def _schema_state(tmp_path):
    """torch_op profile + workspace（方案 A/B 测试共用）。"""
    return _attach_passing_deploy(State(
        mode="new", op_name="unique",
        design_spec={"op_type": "unique",
                     "inputs": [{"name": "x", "type": "Tensor"}],
                     "outputs": [{"name": "y", "type": "Tensor"},
                                 {"name": "inverse", "type": "Tensor?"}]},
        tiling_strategy={},
        kernel_architecture={"pipeline": []},
        profile=_torch_op_profile(),
    ), tmp_path)


def _schema_artifacts(plugin_src, manifest=_UNIQUE_MANIFEST):
    return {
        "unique.cpp": "// kernel",
        "op_plugin/unique_plugin.cpp": plugin_src,
        "codegen_manifest.json": json.dumps(manifest),
    }


class TestCodegenPluginReturnSchema:
    """方案 A：静态返回签名对质（fail-open）命中 → 定向 retry 回 codegen，不 defer。"""

    def test_return_verdict_high_confidence_mismatch(self):
        stage = CodegenStage.__new__(CodegenStage)
        v = stage._return_verdict
        # unique bug：元组声明 vs vector 实现
        assert v(["Tensor", "Tensor?"], "vector") == "tuple_vs_vector"
        assert v(["Tensor"], "vector") == "single_vs_vector"
        assert v(["Tensor", "Tensor"], "tensor") == "tuple_vs_single"
        assert v(["Tensor", "Tensor", "Tensor"], "tuple2") == "tuple_arity_mismatch"

    def test_return_verdict_consistent_or_fail_open(self):
        stage = CodegenStage.__new__(CodegenStage)
        v = stage._return_verdict
        # 现存正常形态：全一致 / 合法 / fail-open，不得误报
        assert v(["Tensor"], "tensor") is None                  # softmax
        assert v(["Tensor", "Tensor"], "tuple2") is None        # apply_rotary
        assert v(["Tensor", "Tensor?"], "tuple2") is None       # unique fixed
        assert v(["Tensor[]"], "vector") is None                # foreach_norm 合法
        assert v(["Tensor?"], "optional") is None               # optional 灰区 fail-open
        assert v([], "void") is None
        assert v(["Tensor"], "tuple1") is None                  # 1 元组=单返回

    def test_plugin_return_schema_mismatch_fires_on_unique_bug(self, tmp_path):
        stage = CodegenStage()
        state = _schema_state(tmp_path)
        mm = stage._plugin_return_schema_mismatch(
            state, _schema_artifacts(_UNIQUE_BUG_PLUGIN))
        assert mm is not None
        assert mm["reason"] == "tuple_vs_vector"
        assert mm["declared_returns"] == ["Tensor", "Tensor?"]
        assert mm["impl_return_kind"] == "vector"

    def test_plugin_return_schema_corpus_no_false_positive(self, tmp_path):
        """回归护栏：现存正常算子形态 A 必须零误报（fail-open）。"""
        stage = CodegenStage()
        state = _schema_state(tmp_path)
        for plugin in (_SINGLE_TENSOR_PLUGIN, _TUPLE_PLUGIN,
                       _UNIQUE_FIXED_PLUGIN, _TENSORLIST_PLUGIN):
            assert stage._plugin_return_schema_mismatch(
                state, _schema_artifacts(plugin)) is None

    def test_transition_routes_schema_mismatch_to_retry(self, tmp_path):
        """A 命中 → 定向 retry：不 halt、不写 deploy_result（runner 重 spawn）、
        build_feedback.kind=schema_mismatch。deploy 不应被调用。schema-retry 是另一重试循环
        → smoke streak 必须重置（防陈旧跨循环误 stop-loss）。"""
        stage = CodegenStage()
        state = _schema_state(tmp_path).with_updates(
            codegen_smoke_same_error_streak=2, codegen_smoke_last_error_sig="OLD_SIG")
        agent_result = AgentResult(
            agent_name="ascendc-coder", status="ok",
            artifacts=_schema_artifacts(_UNIQUE_BUG_PLUGIN))
        with mock.patch(
            "ascendc_devkit.orchestration.stages.deploy.Deployer.deploy"
        ) as deploy:
            new_state = stage.transition(state, {"agent_result": agent_result})
        deploy.assert_not_called()  # A 在 deploy 前命中
        assert new_state.last_error is None
        assert new_state.deploy_result is None
        assert new_state.build_result is not None
        assert new_state.build_result.passed is False
        assert new_state.codegen_build_retries == 1
        fb = new_state.codegen_build_feedback
        assert fb is not None and fb.get("kind") == "schema_mismatch"
        assert fb.get("reason") == "tuple_vs_vector"
        # 非 smoke 重试循环 → smoke streak 重置为 0（防陈旧累计）
        assert new_state.codegen_smoke_same_error_streak == 0
        assert new_state.codegen_smoke_last_error_sig == ""

    def test_transition_corpus_proceeds_to_deploy(self, tmp_path):
        """回归护栏：正常形态走完整 transition（deploy 调用 + smoke 通过），不误拦。"""
        stage = CodegenStage()
        state = _schema_state(tmp_path)
        agent_result = AgentResult(
            agent_name="ascendc-coder", status="ok",
            artifacts=_schema_artifacts(_SINGLE_TENSOR_PLUGIN, _SOFTMAX_MANIFEST))
        with _patch_deploy(smoke_passed=True):
            new_state = stage.transition(state, {"agent_result": agent_result})
        assert new_state.deploy_result is not None
        assert new_state.deploy_result.smoke_passed is True
        assert new_state.last_error is None

    def test_schema_feedback_prompt_injected(self, tmp_path):
        """schema feedback 注入下轮 coder prompt（schema 专属段，非编译错误段）。"""
        stage = CodegenStage()
        state = _schema_state(tmp_path).with_updates(
            codegen_build_feedback={
                "kind": "schema_mismatch", "reason": "tuple_vs_vector",
                "declared_returns": ["Tensor", "Tensor?"],
                "impl_return_kind": "vector", "retry_count": 1,
                "hint": "对齐 m.def 返回签名与 C++ 实现返回类型",
            })
        actions = stage.actions(state, iteration=2)
        prompt = actions[0].prompt
        assert "schema retry" in prompt
        assert "tuple_vs_vector" in prompt
        assert "Tensor?" in prompt
        # 不应误入编译错误段（无 clang 错误信息）
        assert "编译失败" not in prompt


class TestCodegenSmokeSchemaBackstop:
    """smoke 失败分流（Part B）：checkSchema schema 不匹配 → 回 codegen 重修（并入 _smoke_retry
    单一通路，kind=schema_mismatch）；kernel 执行过（507035）→ D4 交 precision。"""

    @staticmethod
    def _smoke_schema_err():
        # 真实 c10::Error（unique 20260808 scope_guard 引用的原样形态）
        stderr = (
            "terminate called after throwing an instance of 'c10::Error' "
            "'Inferred operator schema for a C++ kernel function doesn't match "
            "the expected function schema.' operator: cann_bench::unique, "
            "expected='(Tensor, Tensor?)', "
            "inferred='(Tensor _0, bool _1) -> Tensor[] _0', "
            "reason='The number of returns is different. 2 vs 1.' "
            "Exception from checkSchema at OperatorEntry.cpp:98")
        return DeployResult(smoke_passed=False), ErrorFeedback(
            stage_name="deploy", error_type="deploy_failed",
            message="smoke failed: schema mismatch",
            details={"step": "smoke", "log": "/nonexistent/smoke.log",
                     "stderr_tail": stderr})

    def test_classify_smoke_schema_mismatch_hits(self):
        err = self._smoke_schema_err()[1]
        info = CodegenStage._classify_smoke_schema_mismatch(err)
        assert info is not None
        assert info["expected_schema"] == "(Tensor, Tensor?)"
        assert "Tensor[]" in info["inferred_schema"]

    def test_classify_smoke_schema_mismatch_miss(self):
        err = ErrorFeedback(
            stage_name="deploy", error_type="deploy_failed",
            message="smoke failed", details={"step": "smoke",
                                             "log": "", "stderr_tail": "ACL error 507035"})
        assert CodegenStage._classify_smoke_schema_mismatch(err) is None

    def test_smoke_schema_mismatch_routes_to_retry(self, tmp_path):
        """B 命中 → 定向 retry（不写 deploy_result → runner 重 spawn）。"""
        stage = CodegenStage()
        state = _schema_state(tmp_path)
        agent_result = AgentResult(
            agent_name="ascendc-coder", status="ok",
            artifacts=_schema_artifacts(_UNIQUE_FIXED_PLUGIN))
        result, err = self._smoke_schema_err()
        # 方案 2 (L4 改动 2)：compile 成功 → install_and_smoke 暴露 schema mismatch
        def _compile(state):
            return DeployResult(
                run_package="/pkg/unique.run", wheel_package="/pkg/unique.whl",
                smoke_passed=False), None
        def _install_and_smoke(state, compile_result):
            return result, err
        with mock.patch(
            "ascendc_devkit.orchestration.stages.deploy.Deployer.compile",
            side_effect=_compile), \
             mock.patch(
                "ascendc_devkit.orchestration.stages.deploy.Deployer.install_and_smoke",
                side_effect=_install_and_smoke):
            new_state = stage.transition(state, {"agent_result": agent_result})
        assert new_state.last_error is None
        assert new_state.deploy_result is None       # 不 defer（不写 deploy_result）
        assert new_state.codegen_build_retries == 1
        fb = new_state.codegen_build_feedback
        assert fb is not None and fb.get("kind") == "schema_mismatch"
        assert fb.get("reason") == "runtime_checkSchema_mismatch"

    def test_smoke_kernel_phase_stays_d4(self, tmp_path):
        """非 schema 且 kernel 执行过（507035，_patch_deploy smoke_passed=False 现产此串）→
        维持 D4：写 deploy_result(smoke_passed=False) 交 precision（kernel 运行时/数值缺陷）。
        host/歧义类非 schema smoke 失败走 codegen retry（见 TestCodegenSmokeHostBackstop）。"""
        stage = CodegenStage()
        state = _schema_state(tmp_path)
        agent_result = AgentResult(
            agent_name="ascendc-coder", status="ok",
            artifacts=_schema_artifacts(_UNIQUE_FIXED_PLUGIN))
        with _patch_deploy(smoke_passed=False):
            new_state = stage.transition(state, {"agent_result": agent_result})
        assert new_state.deploy_result is not None
        assert new_state.deploy_result.smoke_passed is False
        assert new_state.last_error is None


class TestCodegenSmokeHostBackstop:
    """Part B（20260810）：smoke 失败按失败阶段分流。

    host 阶段（kernel 未执行，EZ1008 等）→ _smoke_retry 单一通路回 codegen（feedback
    kind=smoke_host）；kernel 执行过（507035）→ D4 交 precision；歧义区（无信号）→ 回
    codegen 让 coder 判归属（kind=smoke_owner_judge）。agent 归属判定（1f）：not_codegen /
    upstream_design 只交下游（D4），防逃避 K 守卫，禁止交上游。"""

    @staticmethod
    def _smoke_err(stderr_tail: str, log_path: str = "") -> ErrorFeedback:
        return ErrorFeedback(
            stage_name="deploy", error_type="deploy_failed",
            message="smoke failed",
            details={"step": "smoke", "log": log_path, "stderr_tail": stderr_tail})

    # ---- _classify_smoke_phase 单元 ----
    def test_phase_classifier_host(self):
        err = self._smoke_err(
            "RuntimeError('... EZ1008 Failed to execute operator. Reason: Failed to "
            "execute tiling ... invalid approximate value @gelu_tiling.cpp ...')")
        assert CodegenStage._classify_smoke_phase(err) == "host"

    def test_phase_classifier_kernel(self):
        err = self._smoke_err("RuntimeError('... vector core exception 507035 ...')")
        assert CodegenStage._classify_smoke_phase(err) == "kernel"

    def test_phase_classifier_none(self):
        err = self._smoke_err("RuntimeError('... unknown failure ...')")
        assert CodegenStage._classify_smoke_phase(err) is None

    def test_phase_classifier_kernel_priority(self):
        """同时含 host+kernel 标记（罕见）→ kernel 优先（507xxx 特异性强）。"""
        err = self._smoke_err("RuntimeError('... EZ1008 Failed to execute tiling ... 507035 ...')")
        assert CodegenStage._classify_smoke_phase(err) == "kernel"

    # ---- transition 路由 ----
    def _transition(self, tmp_path, err, retries=0, decision_log_content=None,
                    smoke_streak=0, smoke_last_sig=""):
        stage = CodegenStage()
        state = _schema_state(tmp_path).with_updates(
            codegen_build_retries=retries,
            codegen_smoke_same_error_streak=smoke_streak,
            codegen_smoke_last_error_sig=smoke_last_sig)
        artifacts = dict(_schema_artifacts(_UNIQUE_FIXED_PLUGIN))
        if decision_log_content is not None:
            artifacts["decision_log.json"] = json.dumps(decision_log_content)
        agent_result = AgentResult(
            agent_name="ascendc-coder", status="ok", artifacts=artifacts)
        result = DeployResult(run_package="/pkg/unique.run", smoke_passed=False)
        # 方案 2 (L4 改动 2)：codegen 走 compile → install_and_smoke。这些 smoke-host 用例
        # 语义 = compile 成功、smoke 失败(err 带 step=smoke 由 install_and_smoke 返回)。
        def _compile(state):
            return DeployResult(
                run_package="/pkg/unique.run", wheel_package="/pkg/unique.whl",
                smoke_passed=False), None
        def _install_and_smoke(state, compile_result):
            return result, err
        with mock.patch("ascendc_devkit.orchestration.stages.deploy.Deployer.compile",
                        side_effect=_compile), \
             mock.patch(
                "ascendc_devkit.orchestration.stages.deploy.Deployer.install_and_smoke",
                side_effect=_install_and_smoke):
            return stage.transition(state, {"agent_result": agent_result})

    def test_host_phase_routes_to_codegen_retry(self, tmp_path):
        """EZ1008 host 阶段 → _smoke_retry：不写 deploy_result、feedback kind=smoke_host、不 halt。"""
        err = self._smoke_err("RuntimeError('... EZ1008 Failed to execute tiling ...')")
        new_state = self._transition(tmp_path, err)
        assert new_state.last_error is None
        assert new_state.deploy_result is None          # 回 codegen 重试（不 defer）
        assert new_state.codegen_build_retries == 1
        fb = new_state.codegen_build_feedback
        assert fb is not None and fb.get("kind") == "smoke_host"

    def test_kernel_phase_stays_d4(self, tmp_path):
        """507035 kernel 阶段 → D4 交 precision。"""
        err = self._smoke_err("RuntimeError('... 507035 vector core exception ...')")
        new_state = self._transition(tmp_path, err)
        assert new_state.deploy_result is not None
        assert new_state.deploy_result.smoke_passed is False
        assert new_state.last_error is None

    def test_ambiguous_phase_routes_to_owner_judge(self, tmp_path):
        """无信号歧义区 → 回 codegen，feedback kind=smoke_owner_judge。"""
        err = self._smoke_err("RuntimeError('... unknown failure ...')")
        new_state = self._transition(tmp_path, err)
        assert new_state.last_error is None
        assert new_state.deploy_result is None
        fb = new_state.codegen_build_feedback
        assert fb is not None and fb.get("kind") == "smoke_owner_judge"

    def test_budget_exhausted_d4(self, tmp_path):
        """host 阶段预算耗尽 → D4 逃生（deploy_result smoke_passed=False、不 halt）。"""
        stage = CodegenStage.__new__(CodegenStage)
        limit = stage._build_retry_limit()
        err = self._smoke_err("RuntimeError('... EZ1008 Failed to execute tiling ...')")
        new_state = self._transition(tmp_path, err, retries=limit - 1)
        assert new_state.deploy_result is not None
        assert new_state.deploy_result.smoke_passed is False
        assert new_state.last_error is None

    # ---- agent 归属判定兜底（1f，只交下游）----
    @staticmethod
    def _dl_with_ownership(verdict):
        return {"codegen_smoke_ownership": {
            "verdict": verdict, "reason": "not a codegen artifact defect",
            "evidence": "smoke log points at harness module-load"}}

    def test_not_codegen_ambiguous_immediate_d4(self, tmp_path):
        """歧义区 + not_codegen → 立即 honor → D4。"""
        err = self._smoke_err("RuntimeError('... unknown failure ...')")
        new_state = self._transition(
            tmp_path, err, decision_log_content=self._dl_with_ownership("not_codegen"))
        assert new_state.deploy_result is not None
        assert new_state.deploy_result.smoke_passed is False
        assert new_state.last_error is None

    def test_not_codegen_host_before_k_not_honored(self, tmp_path):
        """host 域 + 同签名重试 <K → not_codegen 不 honor，继续 retry（防逃避）。"""
        err = self._smoke_err("RuntimeError('... EZ1008 Failed to execute tiling ...')")
        new_state = self._transition(
            tmp_path, err, smoke_streak=1,
            decision_log_content=self._dl_with_ownership("not_codegen"))
        assert new_state.deploy_result is None           # 继续 retry
        assert new_state.codegen_build_retries == 1
        fb = new_state.codegen_build_feedback
        assert fb is not None and fb.get("kind") == "smoke_host"  # 反馈仍是修复指引

    def test_not_codegen_host_build_retries_do_not_satisfy_k(self, tmp_path):
        """M2 回归：共享 build_retries 高（=2）但 smoke 同签名 streak 低（=0，从未尝试过
        这个 smoke 错误）→ not_codegen 不 honor（旧实现会 honor，防逃避被稀释）。"""
        err = self._smoke_err("RuntimeError('... EZ1008 Failed to execute tiling ...')")
        new_state = self._transition(
            tmp_path, err, retries=2, smoke_streak=0,
            decision_log_content=self._dl_with_ownership("not_codegen"))
        assert new_state.deploy_result is None           # 不 honor → 继续 retry
        assert new_state.codegen_build_retries == 3
        fb = new_state.codegen_build_feedback
        assert fb is not None and fb.get("kind") == "smoke_host"

    def test_not_codegen_host_after_k_d4(self, tmp_path):
        """host 域 + 同签名重试 ≥K → not_codegen honor → D4。"""
        err = self._smoke_err("RuntimeError('... EZ1008 Failed to execute tiling ...')")
        new_state = self._transition(
            tmp_path, err, smoke_streak=2,
            decision_log_content=self._dl_with_ownership("not_codegen"))
        assert new_state.deploy_result is not None
        assert new_state.deploy_result.smoke_passed is False
        assert new_state.last_error is None

    def test_upstream_design_only_downstream_d4(self, tmp_path):
        """upstream_design → 不路由回 design（禁止交上游），D4 交下游。"""
        err = self._smoke_err("RuntimeError('... EZ1008 Failed to execute tiling ...')")
        new_state = self._transition(
            tmp_path, err, smoke_streak=2,
            decision_log_content=self._dl_with_ownership("upstream_design"))
        assert new_state.deploy_result is not None
        assert new_state.deploy_result.smoke_passed is False
        assert new_state.last_error is None
        # 只交下游：deploy_result 前进即证明未触发 design 上游路由

    def test_missing_ownership_keeps_retry(self, tmp_path):
        """缺失 verdict → 继续 retry。"""
        err = self._smoke_err("RuntimeError('... EZ1008 Failed to execute tiling ...')")
        new_state = self._transition(tmp_path, err, retries=1)
        assert new_state.deploy_result is None
        fb = new_state.codegen_build_feedback
        assert fb is not None and fb.get("kind") == "smoke_host"

    # ---- 机械 stop-loss（用户 20260810 追加）----
    def test_signature_stable_across_pid_noise(self):
        """签名稳定：PID 变化不改变签名（否则每次重试签名变、stop-loss 永不触发）。"""
        g1 = self._smoke_err("RuntimeError('... [PID: 39244] Execution_Error(EZ1008): "
                             "Failed to execute tiling ... [FILE:gelu_tiling.cpp][LINE:89] ...')")
        g2 = self._smoke_err("RuntimeError('... [PID: 99999] Execution_Error(EZ1008): "
                             "Failed to execute tiling ... [FILE:gelu_tiling.cpp][LINE:89] ...')")
        assert CodegenStage._smoke_error_signature(g1) == CodegenStage._smoke_error_signature(g2)
        assert "PID" not in CodegenStage._smoke_error_signature(g1)

    def test_stop_loss_force_d4_same_signature(self, tmp_path):
        """同错误签名连续 streak≥K（不依赖 coder 声明）→ 机械 D4 交下游，不 halt。"""
        err = self._smoke_err("RuntimeError('... EZ1008 Failed to execute tiling "
                              "... [FILE:gelu_tiling.cpp][LINE:89] ...')")
        sig = CodegenStage._smoke_error_signature(err)
        # streak=2（已同错两次）+ 本次同签名 → streak=3 ≥ K=3 → 强制 D4
        new_state = self._transition(tmp_path, err, retries=2,
                                     smoke_streak=2, smoke_last_sig=sig)
        assert new_state.deploy_result is not None
        assert new_state.deploy_result.smoke_passed is False
        assert new_state.last_error is None
        # 离开 smoke 循环 → streak 重置为 0（防陈旧跨上下文）
        assert new_state.codegen_smoke_same_error_streak == 0
        assert new_state.codegen_smoke_last_error_sig == ""

    def test_stop_loss_resets_on_sig_change(self, tmp_path):
        """换错误签名 → streak 重置为 1，继续 retry（不误停）。"""
        err = self._smoke_err("RuntimeError('... EZ1008 Failed to execute tiling "
                              "... [FILE:gelu_tiling.cpp][LINE:89] ...')")
        new_state = self._transition(tmp_path, err, retries=2,
                                     smoke_streak=2, smoke_last_sig="OTHER_SIG")
        assert new_state.deploy_result is None           # 继续 retry（签名不同，不 stop-loss）
        assert new_state.codegen_smoke_same_error_streak == 1  # 重置为 1
        fb = new_state.codegen_build_feedback
        assert fb is not None and fb.get("kind") == "smoke_host"

    def test_smoke_host_feedback_prompt_injected(self, tmp_path):
        """smoke_host feedback 注入 coder prompt（host 脚手架修复指引段 + 归属判定通道）。"""
        stage = CodegenStage()
        state = _schema_state(tmp_path).with_updates(
            codegen_build_feedback={
                "kind": "smoke_host", "reason": "host_phase_launch_failed",
                "error_line": "EZ1008: Failed to execute tiling ... [FILE:gelu_tiling.cpp][LINE:89]",
                "log_path": "/fake/smoke.log", "retry_count": 1,
                "hint": "修复 host 脚手架",
            })
        actions = stage.actions(state, iteration=2)
        prompt = actions[0].prompt
        assert "host 侧启动失败反馈" in prompt
        assert "codegen_smoke_ownership" in prompt   # 归属判定通道
        assert "Failed to execute tiling" in prompt

    def test_smoke_owner_judge_feedback_prompt_injected(self, tmp_path):
        """smoke_owner_judge feedback 注入 coder prompt（歧义区归属判定）。"""
        stage = CodegenStage()
        state = _schema_state(tmp_path).with_updates(
            codegen_build_feedback={
                "kind": "smoke_owner_judge", "reason": "ambiguous_phase",
                "error_line": "RuntimeError('call aclnnFoo failed')",
                "log_path": "/fake/smoke.log", "retry_count": 1,
                "hint": "判断归属并修复或写 codegen_smoke_ownership",
            })
        actions = stage.actions(state, iteration=2)
        prompt = actions[0].prompt
        assert "归属判定" in prompt
        assert "codegen_smoke_ownership" in prompt

    def test_stop_loss_not_triggered_below_k(self, tmp_path):
        """同签名但 streak <K → 继续 retry。"""
        err = self._smoke_err("RuntimeError('... EZ1008 Failed to execute tiling "
                              "... [FILE:gelu_tiling.cpp][LINE:89] ...')")
        sig = CodegenStage._smoke_error_signature(err)
        new_state = self._transition(tmp_path, err, retries=1,
                                     smoke_streak=1, smoke_last_sig=sig)
        assert new_state.deploy_result is None           # streak=2 < 3 → 继续
        assert new_state.codegen_smoke_same_error_streak == 2
        assert new_state.codegen_smoke_last_error_sig == sig

    def test_signature_distinguishes_multi_error_change(self):
        """多错并存：首错相同（EZ1008@89）、后续错误不同 → 签名不同（全量特征，非首条）。"""
        err_a = self._smoke_err("RuntimeError('... Execution_Error(EZ1008): Failed to execute tiling "
                                "... [FILE:gelu_tiling.cpp][LINE:89] ... TraceBack: [FILE:gelu_tiling.cpp][LINE:118]')")
        err_b = self._smoke_err("RuntimeError('... Execution_Error(EZ1008): Failed to execute tiling "
                                "... [FILE:gelu_tiling.cpp][LINE:89] ... TraceBack: [FILE:gelu_tiling.cpp]"
                                "[LINE:118] EZ1006 inferShape failed')")
        assert CodegenStage._smoke_error_signature(err_a) != CodegenStage._smoke_error_signature(err_b)

    def test_signature_captures_all_error_lines_not_first_only(self):
        """M3 回归：多错并存时首条匹配行相同（EZ1008@89），但第二条错误行消息变化
        （同码同位置，inferShape failed for input x→y，非数字部分）→ 签名必须不同
        （旧实现只取首条 → 签名相同 → 误判无进展 → 误 stop-loss）。"""
        g_a = self._smoke_err(
            "RuntimeError('Execution_Error(EZ1008): Failed to execute tiling "
            "[FILE:gelu_tiling.cpp][LINE:89]')\n"
            "[FILE:gelu_tiling.cpp][LINE:118] EZ1006 inferShape failed for input x")
        g_b = self._smoke_err(
            "RuntimeError('Execution_Error(EZ1008): Failed to execute tiling "
            "[FILE:gelu_tiling.cpp][LINE:89]')\n"
            "[FILE:gelu_tiling.cpp][LINE:118] EZ1006 inferShape failed for input y")
        sig_a = CodegenStage._smoke_error_signature(g_a)
        sig_b = CodegenStage._smoke_error_signature(g_b)
        assert sig_a != sig_b, (sig_a, sig_b)

    def test_stop_loss_no_false_positive_on_secondary_error_change(self, tmp_path):
        """首错相同、后续错误变化 → 签名变 → streak 重置 → 不误 stop-loss（coder 可能在进展）。"""
        err_a = self._smoke_err("RuntimeError('... Execution_Error(EZ1008): Failed to execute tiling "
                                "... [FILE:gelu_tiling.cpp][LINE:89] ... TraceBack: [FILE:gelu_tiling.cpp][LINE:118]')")
        err_b = self._smoke_err("RuntimeError('... Execution_Error(EZ1008): Failed to execute tiling "
                                "... [FILE:gelu_tiling.cpp][LINE:89] ... TraceBack: [FILE:gelu_tiling.cpp]"
                                "[LINE:118] EZ1006 inferShape failed')")
        sig_a = CodegenStage._smoke_error_signature(err_a)
        # 上一轮 err_a（streak=2），本轮 err_b（签名不同）→ 重置，不 stop-loss
        new_state = self._transition(tmp_path, err_b, retries=2,
                                     smoke_streak=2, smoke_last_sig=sig_a)
        assert new_state.deploy_result is None           # 不误 stop-loss
        assert new_state.codegen_smoke_same_error_streak == 1  # 重置为 1
        fb = new_state.codegen_build_feedback
        assert fb is not None and fb.get("kind") == "smoke_host"


class TestRunnerWithStages:
    def test_runner_smoke_stage_full_cycle(self):
        backend = StubBackend(canned_responses=[
            AgentResult(agent_name="ascendc-coder", status="ok",
                        artifacts={"hello.cpp": "// hello"}),
        ])
        stage = SmokeStage()
        state = State(mode="new", non_interactive=True)
        runner = Runner(agent_backend=backend)
        final = runner.run_stage(state, stage)
        assert final.generated_sources == {"hello.cpp": "// hello"}
        assert final.stage_iterations.get("smoke") == 1

    def test_runner_codegen_stage_single_iteration(self, tmp_path):
        backend = StubBackend(canned_responses=[
            AgentResult(agent_name="ascendc-coder", status="ok",
                        artifacts=_gelu_artifacts()),
        ])
        stage = CodegenStage()
        state = _attach_passing_deploy(State(
            mode="new",
            op_name="gelu",
            design_spec={"op_type": "gelu", "inputs": [{"name": "x"}], "outputs": [{"name": "y"}]},
            tiling_strategy={"approach": "single_core"},
            kernel_architecture={"pipeline": ["CopyIn", "Compute", "CopyOut"]},
            profile=_omni_profile(),
        ), tmp_path)
        runner = Runner(agent_backend=backend)
        with _patch_deploy(smoke_passed=True):
            final = runner.run_stage(state, stage)
        assert final.generated_sources["gelu.cpp"] == "// kernel"
        assert "codegen_manifest.json" in final.generated_sources  # manifest propagated
        assert final.codegen_iterations == 1

    def test_runner_codegen_schema_mismatch_fixes_via_respawn(self, tmp_path):
        """方案 A runner 层：第一轮 plugin 返回签名不一致 → 定向 retry（不写
        deploy_result → 重 spawn）；第二轮 coder 修复（StubBackend 换回正确
        plugin）→ A 放行 → deploy/smoke 通过 → codegen 完成。"""
        backend = StubBackend(canned_responses=[
            AgentResult(agent_name="ascendc-coder", status="ok",
                        artifacts=_schema_artifacts(_UNIQUE_BUG_PLUGIN)),
            AgentResult(agent_name="ascendc-coder", status="ok",
                        artifacts=_schema_artifacts(_UNIQUE_FIXED_PLUGIN)),
        ])
        stage = CodegenStage()
        state = _schema_state(tmp_path)
        runner = Runner(agent_backend=backend)
        with _patch_deploy(smoke_passed=True):
            final = runner.run_stage(state, stage)
        assert final.deploy_result is not None
        assert final.deploy_result.smoke_passed is True
        # 重 spawn 后修复成功：两轮迭代（首轮 retry 未写 deploy_result → 重 spawn）。
        # codegen_build_retries 成功路径归零（既有 build-retry 语义），用迭代数证明。
        assert final.stage_iterations.get("codegen", 0) >= 2
        assert final.codegen_build_retries == 0
        assert getattr(final, "_stage_failed", None) is None
        assert final.last_error is None or final.last_error.error_type == "ok"

    def test_runner_codegen_corpus_completes(self, tmp_path):
        """回归护栏 runner 层：正常 plugin（单 Tensor 形态）走完整 codegen 不误拦。"""
        backend = StubBackend(canned_responses=[
            AgentResult(agent_name="ascendc-coder", status="ok",
                        artifacts=_schema_artifacts(
                            _SINGLE_TENSOR_PLUGIN, _SOFTMAX_MANIFEST)),
        ])
        stage = CodegenStage()
        state = _schema_state(tmp_path)
        runner = Runner(agent_backend=backend)
        with _patch_deploy(smoke_passed=True):
            final = runner.run_stage(state, stage)
        assert final.deploy_result is not None
        assert final.deploy_result.smoke_passed is True
        assert final.last_error is None

    def test_runner_raises_precondition_on_chip_mismatch(self, tmp_path):
        """Option D end-to-end (step-34): chip mismatch → validate_inputs returns
        the chip error → runner raises PreconditionError BEFORE spawning the coder
        (no agent call). The gate reads the dispatch-resolved dual fields (pure
        comparison, no probe). This is the clean halt channel (dispatcher logs
        stage+reason + report, EX_DATAERR) — vs the old deploy-gate that stranded
        the gate in a service with an empty signal channel and synthesised a
        generic deploy_failed downstream."""
        from ascendc_devkit.domain.exceptions import PreconditionError
        backend = StubBackend(canned_responses=[
            AgentResult(agent_name="ascendc-coder", status="ok",
                        artifacts={"gelu.cpp": "// would-not-be-reached"})])
        stage = CodegenStage()
        state = _attach_passing_deploy(State(
            mode="new",
            op_name="gelu",
            design_spec={"op_type": "gelu",
                         "inputs": [{"name": "x"}], "outputs": [{"name": "y"}]},
            tiling_strategy={"approach": "single_core"},
            kernel_architecture={"pipeline": ["CopyIn", "Compute", "CopyOut"]},
            profile=_omni_profile(),
            design_target_chip="A5", runtime_target_chip="A2",
        ), tmp_path)
        runner = Runner(agent_backend=backend)
        with pytest.raises(PreconditionError, match="A5"):
            runner.run_stage(state, stage)
        # Precondition fired pre-spawn → coder never invoked (proves the halt is
        # at the validate_inputs boundary, not after a wasted agent round).
        assert backend.spawn_calls == []

    # Retired (step-34): the probe-timeout precondition path is gone — the gate
    # no longer probes, and a probe timeout is handled once at dispatch
    # (--runtime_target_chip fallback / EX_DATAERR), covered by
    # test_dispatcher_chip_resolution.py.

    def test_runner_respects_max_iterations_from_state(self):
        """State.user_max_iterations=1 should cap CodegenStage's default 5."""
        backend = StubBackend(canned_responses=[
            AgentResult(agent_name="ascendc-coder", status="ok",
                        artifacts={"gelu.cpp": "// v1"}),
            AgentResult(agent_name="ascendc-coder", status="ok",
                        artifacts={"gelu.cpp": "// v2"}),
        ])
        stage = CodegenStage()
        state = State(
            mode="new",
            op_name="gelu",
            design_spec={"op_type": "gelu", "inputs": [{"name": "x"}], "outputs": [{"name": "y"}]},
            tiling_strategy={"approach": "single_core"},
            kernel_architecture={"pipeline": ["CopyIn", "Compute", "CopyOut"]},
            profile=_omni_profile(),
            user_max_iterations=1,
        )
        runner = Runner(agent_backend=backend)
        with _patch_deploy(smoke_passed=True):
            final = runner.run_stage(state, stage)
        assert final.codegen_iterations == 1
        assert len(backend.spawn_calls) == 1

    def test_runner_early_termination_on_output_satisfied(self):
        """Runner must stop after output contract is satisfied, even with more iterations allowed."""
        stage = SmokeStage()
        state = State(mode="new", user_max_iterations=5)
        runner = Runner(agent_backend=StubBackend(canned_responses=[
            AgentResult(agent_name="ascendc-coder", status="ok",
                        artifacts={"hello.cpp": "// hello"}),
            AgentResult(agent_name="ascendc-coder", status="ok",
                        artifacts={"hello2.cpp": "// should not be called"}),
        ]))
        final = runner.run_stage(state, stage)
        assert final.generated_sources == {"hello.cpp": "// hello"}
        # Second canned response should never be consumed
        assert final.stage_iterations.get("smoke") == 1


# ============================================================
# EntryStage
# ============================================================

class TestEntryStage:
    @staticmethod
    def _entry_state():
        return State(
            task_request={
                "mode": "new",
                "workflow": "generate_ascendc",
                "target_repo": "/tmp/test-repo",
                "repo_profile": "omni-ops",
                "op_name": "gelu",
                "npu_id": 0,
                "non_interactive": True,
            },
        )

    def test_actions_validates_inputs(self):
        stage = EntryStage()
        state = self._entry_state()
        actions = stage.actions(state)
        assert len(actions) == 1
        a = actions[0]
        assert isinstance(a, ValidateInputs)
        assert any("mode in" in c for c in a.checks)

    def test_actions_incremental_mode(self):
        stage = EntryStage()
        state = self._entry_state().with_updates(
            task_request={**self._entry_state().task_request, "mode": "incremental"},
            mode="incremental",
        )
        actions = stage.actions(state)
        assert len(actions) == 1
        assert isinstance(actions[0], ValidateInputs)
        assert any("op_name" in c for c in actions[0].checks)

    def test_transition_extracts_fields(self):
        stage = EntryStage()
        state = self._entry_state().with_updates(
            task_request={
                **self._entry_state().task_request,
                "requirement_path": "/tmp/req.yaml",
            },
        )
        new_state = stage.transition(state, {})
        assert new_state.mode == "new"
        assert new_state.workflow_name == "generate_ascendc"
        assert new_state.op_name == "gelu"
        assert new_state.repo_profile_name == "omni-ops"
        assert new_state.non_interactive is True

    def test_transition_requirement_path(self):
        stage = EntryStage()
        state = self._entry_state().with_updates(
            task_request={
                **self._entry_state().task_request,
                "requirement_path": "/tmp/req.yaml",
            },
        )
        new_state = stage.transition(state, {})
        assert new_state.requirement_path == Path("/tmp/req.yaml")

    def test_input_contract(self):
        c = EntryStage().input_contract()
        assert "task_request" in c.requires

    def test_output_contract(self):
        c = EntryStage().output_contract()
        # Hard provides: fields entry actually derives from task_request.
        for field in ["mode", "workflow_name", "op_name",
                       "repo_profile_name", "non_interactive"]:
            assert field in c.provides, f"Missing {field}"
        # Conditional / runtime-filled outputs: declared but NOT part of the
        # early-termination check. npu_id is runtime-filled — None = use the
        # card pool, int = hard-pin a card (state.py). Declaring it a hard
        # provides would warn on every batch task that leaves it None, which is
        # the legitimate "no hard-pin" state — so it lives in optional_provides
        # alongside target_repo / requirement_path.
        for field in ["target_repo", "requirement_path", "npu_id"]:
            assert field in c.optional_provides, f"Missing optional {field}"
            assert field not in c.provides

    def test_entry_no_spin_when_npu_id_none(self):
        # Regression (batch): task_request carries npu_id=None (no hard-pin;
        # the card pool assigns at runtime — batch_runner.py always sets this
        # key). entry must still satisfy its hard provides so the runner
        # early-terminates instead of spinning to max_iterations=1 and emitting
        # a misleading WARN.
        stage = EntryStage()
        state = State(task_request={"mode": "new", "npu_id": None})
        out = stage.transition(state, {})
        assert out.has_all(stage.output_contract().provides)
        assert out.npu_id is None  # None semantics preserved → pool assigns

    def test_entry_preserves_dispatch_resolved_op_card(self):
        # P13 (step-116)：npu_id 权威值 = dispatch 在 op 边界解析的卡。entry
        # 不得从 task hint 重建——旧 `tr.get("npu_id", 0)` 会把已解析卡打回
        # hint/0，破坏 op 租约唯一性。两个方向都守护：
        #   state 已解析卡 3 + task hint 5 → 仍是 3（不打回 hint）；
        #   state 0（dispatch 解析结果为 0）+ task 无 hint → 仍是 0。
        stage = EntryStage()
        out = stage.transition(State(task_request={"mode": "new", "npu_id": 5},
                                     npu_id=3), {})
        assert out.npu_id == 3
        out2 = stage.transition(State(task_request={"mode": "new"}, npu_id=0), {})
        assert out2.npu_id == 0


# ============================================================
# ContextStage
# ============================================================

class TestContextStage:
    @staticmethod
    def _context_state():
        return State(
            mode="new",
            op_name="gelu",
            target_repo=Path("/tmp/test-repo"),
            repo_root=Path("/tmp/test-repo"),
            op_dir=Path("/tmp/test-repo/inference/ascendc/src/g/c/ai_infra_gelu"),
            rel_op_dir="inference/ascendc/src/g/c/ai_infra_gelu",
            full_op_name="ai_infra_gelu",
            repo_profile_name="omni-ops",
            non_interactive=True,
        )

    def test_actions_new_mode(self):
        stage = ContextStage()
        state = self._context_state()
        actions = stage.actions(state)
        assert len(actions) == 3
        assert isinstance(actions[0], LoadProfile)
        assert actions[0].profile_name == "omni-ops"
        assert isinstance(actions[1], InitAdapter)
        assert isinstance(actions[2], CollectReferenceCode)

    def test_actions_incremental_non_interactive(self):
        stage = ContextStage()
        state = self._context_state().with_updates(mode="incremental", non_interactive=True)
        actions = stage.actions(state)
        assert len(actions) >= 2  # LoadProfile + InitAdapter + scan actions
        assert any(isinstance(a, ScanExistingOperator) for a in actions)
        assert any(isinstance(a, ReadOperatorCode) for a in actions)

    def test_actions_incremental_interactive_iteration_1(self):
        stage = ContextStage()
        state = self._context_state().with_updates(mode="incremental", non_interactive=False)
        actions = stage.actions(state, iteration=1)
        assert len(actions) >= 2
        assert any(isinstance(a, AskUserQuestion) for a in actions)

    def test_transition_loads_profile(self):
        stage = ContextStage()
        state = self._context_state()
        new_state = stage.transition(state, {})
        assert new_state.profile is not None
        assert new_state.profile.name == "omni-ops"
        assert new_state.adapter is not None
        assert new_state.op_identity is not None
        assert new_state.op_identity.spec.name == "gelu"

    def test_transition_missing_profile_graceful(self):
        stage = ContextStage()
        state = self._context_state().with_updates(repo_profile_name="nonexistent")
        new_state = stage.transition(state, {})
        assert new_state.profile is None  # graceful degradation

    def test_context_op_dir_invariant(self):
        # #4: op_identity.op_dir MUST be derived from the top-level state.op_dir
        # (single authority). Fallback readers do
        # ``state.op_dir or op_identity.op_dir`` — safe only while the two can't
        # diverge. This guards that invariant: a future second writer that sets
        # op_identity.op_dir from a different source (without updating
        # state.op_dir) would make this red.
        stage = ContextStage()
        state = self._context_state()
        new_state = stage.transition(state, {})
        assert new_state.op_identity is not None
        assert new_state.op_identity.op_dir == new_state.op_dir

    def test_input_contract(self):
        c = ContextStage().input_contract()
        assert "mode" in c.requires
        assert "op_name" in c.requires
        assert "target_repo" in c.requires
        assert "repo_profile_name" in c.requires

    def test_output_contract(self):
        c = ContextStage().output_contract()
        for field in ["profile", "adapter", "op_identity", "reference_code"]:
            assert field in c.provides, f"Missing {field}"

    def test_transition_sets_target_repo_baseline_ref_via_guard(self):
        class _StubGuard:
            def __init__(self):
                self.created = False
            def is_clean(self, repo_root, op_dir):
                return True
            def create_baseline(self, repo_root, op_dir):
                self.created = True
                return "stub-head-sha"
        guard = _StubGuard()
        stage = ContextStage(repo_guard=guard)
        new_state = stage.transition(self._context_state(), {})
        assert guard.created is True
        assert new_state.target_repo_baseline_ref == "stub-head-sha"

    def test_transition_skips_baseline_without_target_repo(self):
        stage = ContextStage(repo_guard=None)
        state = self._context_state().with_updates(target_repo=None)
        new_state = stage.transition(state, {})
        # No repo → no baseline established.
        assert new_state.target_repo_baseline_ref == ""

    def test_transition_dirty_non_interactive_warns_but_proceeds(self):
        class _DirtyGuard:
            def is_clean(self, repo_root, op_dir):
                return False
            def create_baseline(self, repo_root, op_dir):
                return "head-after-warn"
        stage = ContextStage(repo_guard=_DirtyGuard())
        state = self._context_state().with_updates(non_interactive=True)
        new_state = stage.transition(state, {})
        # Non-interactive: warn + proceed with baseline.
        assert new_state.target_repo_baseline_ref == "head-after-warn"

    def test_transition_resolves_op_identity_from_op_dir(self):
        stage = ContextStage(repo_guard=None)
        new_state = stage.transition(self._context_state(), {})
        assert new_state.op_identity is not None
        # short name derived from full_op_name minus ai_infra_ prefix
        assert new_state.op_identity.spec.name == "gelu"
        assert str(new_state.op_identity.op_dir).endswith("ai_infra_gelu")

    def test_transition_reference_roots_default_plus_extra(self):
        stage = ContextStage(repo_guard=None)
        state = self._context_state().with_updates(reference_roots=["/other/repo/rope"])
        new_state = stage.transition(state, {})
        # Default variant root (repo-relative → resolved against repo_root) first,
        # then the cross-repo absolute --reference value.
        assert any("inference/ascendc/src" in r for r in new_state.reference_roots)
        assert "/other/repo/rope" in new_state.reference_roots

    def test_transition_chip_defaults_to_variant_stage(self):
        stage = ContextStage(repo_guard=None)
        # No CLI design_target_chip → context resolves the design target via the
        # authority chain (step-34 修正 #2): profile default_chip wins when CLI is
        # absent (omni-ops profile, currently A2 to match local 910B3 hardware).
        # The resolved design target writes design_target_chip (the field build
        # consumers read).
        state = self._context_state().with_updates(task_request={})
        new_state = stage.transition(state, {})
        assert new_state.design_target_chip == "A2"

    def test_transition_scans_existing_op_dir_files(self, tmp_path):
        stage = ContextStage(repo_guard=None)
        op_dir = tmp_path / "inference" / "ascendc" / "src" / "g" / "c" / "ai_infra_gelu"
        (op_dir / "op_host").mkdir(parents=True)
        (op_dir / "op_host" / "gelu_tiling.cpp").write_text("// tiling")
        (op_dir / "gelu.cpp").write_text("// kernel")
        state = self._context_state().with_updates(
            mode="incremental",
            target_repo=tmp_path, repo_root=tmp_path, op_dir=op_dir,
        )
        new_state = stage.transition(state, {})
        keys = list(new_state.op_identity.files.keys())
        assert any("op_host" in k for k in keys)
        assert "gelu.cpp" in keys


# ============================================================
# RequirementStage
# ============================================================

class TestRequirementStage:
    @staticmethod
    def _req_state():
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            f.write(json.dumps({"op": {"name": "gelu"}, "constraints": [], "test_cases": []}))
            req_path = Path(f.name)
        return State(
            mode="new",
            requirement_path=req_path,
        )

    def test_actions_spawns_agent(self):
        stage = RequirementStage()
        # non_interactive isolates the SpawnAgent from the interactive review
        # that is now appended every round in interactive mode.
        state = self._req_state().with_updates(non_interactive=True)
        actions = stage.actions(state)
        assert len(actions) == 1
        a = actions[0]
        assert isinstance(a, SpawnAgent)
        assert a.agent_name == "requirement-analyst"
        assert "需求文档" in a.prompt

    def test_actions_incremental_mode(self):
        stage = RequirementStage()
        state = self._req_state().with_updates(mode="incremental",
                                               non_interactive=True)
        actions = stage.actions(state)
        assert len(actions) == 1
        assert isinstance(actions[0], SpawnAgent)
        assert "增量开发" in actions[0].prompt or "已有" in actions[0].prompt

    def test_requirement_artifacts_land_in_stage_subdir(self, tmp_path):
        """Task 2.4: requirement SpawnAgent.working_dir = artifacts/requirement/."""
        from ascendc_devkit.infra.workspace import Workspace
        ws = Workspace.create(output_root=str(tmp_path), run_id="r")
        state = self._req_state().with_updates(non_interactive=True, _workspace=ws)
        spawn = RequirementStage().actions(state)[0]
        assert spawn.working_dir == ws.artifacts / "requirement"

    def test_transition_parses_requirement_json(self):
        stage = RequirementStage()
        state = self._req_state()
        agent_result = AgentResult(
            agent_name="requirement-analyst",
            status="ok",
            artifacts={
                "requirement.json": _with_golden_alignment({
                    "op_name": "gelu",
                    "mutation_mode": "out_of_place",
                    "inputs": [{"name": "x", "dtype": "fp16", "shape": ["N"]}],
                    "outputs": [{"name": "y", "dtype": "fp16", "shape": ["N"]}],
                    "unclear_items": [],
                }),
            },
        )
        new_state = stage.transition(state, {"agent_result": agent_result})
        assert new_state.requirement is not None
        assert new_state.requirement.op_spec.name == "gelu"
        assert new_state.requirement_clarified is True
        assert new_state.unclear_items == []

    def test_design_target_chip_overrides_target_and_run_context(self):
        """需求文档顶层 design_target_chip 显式声明 → override design target +
        rebuild RunContext.hardware_target（P81 step-60：chip 权威 = CLI > 需求文档
        显式字段 > runtime 兜底；agent constraint 不参与）。设计独立于硬件——A2
        机器可做 A5 设计；仅 build/run gate 校验 design==runtime。"""
        stage = RequirementStage()
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write("design_target_chip: A5\noperator:\n  name: gelu\n")
            req_path = Path(f.name)
        state = self._req_state().with_updates(requirement_path=req_path)
        agent_result = AgentResult(
            agent_name="requirement-analyst",
            status="ok",
            artifacts={
                "requirement.json": _with_golden_alignment({
                    "op_name": "gelu",
                    "mutation_mode": "out_of_place",
                    "inputs": [{"name": "x", "dtype": "fp16", "shape": ["N"]}],
                    "outputs": [{"name": "y", "dtype": "fp16", "shape": ["N"]}],
                    # agent constraint 的 chip 被忽略（防照搬 schema example 污染）
                    "constraints": [
                        {"kind": "hardware", "design_target_chip": "A3"},
                    ],
                }),
            },
        )
        new_state = stage.transition(state, {"agent_result": agent_result})
        # design_target_chip (build consumers read) = A5 from the doc, NOT the
        # agent's A3 constraint (run 20260717-070202-53f685 regression guard).
        assert new_state.design_target_chip == "A5"
        # RunContext.hardware_target rebuilt for A5 — hw_params loaded from the
        # A5 chip spec (ub=248KB=253952, distinct from A2's 192KB=196608),
        # proving the override materialized the A5 design facts, not a no-op.
        assert new_state.run_context is not None
        assert new_state.run_context.hardware_target.chip == "A5"
        assert new_state.run_context.hardware_target.hw_params["ub_size_bytes"] == 253952

    def test_design_target_chip_preserves_run_env(self):
        """Override swaps only hardware_target (design-FOR); hardware_env
        (run-ON) and software_env (run-WITH) are preserved — design-target
        change does not re-probe or clobber the runtime environment."""
        from ascendc_devkit.orchestration.run_context import (
            RunContext, HardwareTarget, HardwareEnvironment, SoftwareEnvironment,
        )
        stage = RequirementStage()
        rc = RunContext(
            hardware_target=HardwareTarget(chip="A2"),
            hardware_env=HardwareEnvironment(npu_id=1, detected_chip="A2"),
            software_env=SoftwareEnvironment(cann_version="8.0.0"),
        )
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write("design_target_chip: A5\noperator:\n  name: gelu\n")
            req_path = Path(f.name)
        state = self._req_state().with_updates(
            design_target_chip="A2", run_context=rc, requirement_path=req_path)
        agent_result = AgentResult(
            agent_name="requirement-analyst",
            status="ok",
            artifacts={
                "requirement.json": _with_golden_alignment({
                    "op_name": "gelu",
                    "mutation_mode": "out_of_place",
                    "inputs": [{"name": "x", "dtype": "fp16", "shape": ["N"]}],
                    "outputs": [{"name": "y", "dtype": "fp16", "shape": ["N"]}],
                    "constraints": [
                        {"kind": "hardware", "design_target_chip": "A3"},
                    ],
                }),
            },
        )
        new_state = stage.transition(state, {"agent_result": agent_result})
        assert new_state.design_target_chip == "A5"
        assert new_state.run_context.hardware_target.chip == "A5"
        # run-ON / run-WITH facts untouched by the design-target change
        assert new_state.run_context.hardware_env.detected_chip == "A2"
        assert new_state.run_context.hardware_env.npu_id == 1
        assert new_state.run_context.software_env.cann_version == "8.0.0"

    def test_no_design_target_chip_keeps_context_target(self):
        """No hardware constraint → design_target_chip stays at the context-stage
        value (CLI/profile default); override is a no-op, not a reset."""
        stage = RequirementStage()
        state = self._req_state().with_updates(design_target_chip="A3")
        agent_result = AgentResult(
            agent_name="requirement-analyst",
            status="ok",
            artifacts={
                "requirement.json": _with_golden_alignment({
                    "op_name": "gelu",
                    "mutation_mode": "out_of_place",
                    "inputs": [{"name": "x", "dtype": "fp16", "shape": ["N"]}],
                    "outputs": [{"name": "y", "dtype": "fp16", "shape": ["N"]}],
                    "constraints": [],  # no design_target_chip declared
                }),
            },
        )
        new_state = stage.transition(state, {"agent_result": agent_result})
        assert new_state.design_target_chip == "A3"  # unchanged

    def test_transition_with_unclear_items(self):
        stage = RequirementStage()
        state = self._req_state()
        agent_result = AgentResult(
            agent_name="requirement-analyst",
            status="ok",
            artifacts={
                "requirement.json": _with_golden_alignment({
                    "op_name": "gelu",
                    "mutation_mode": "out_of_place",
                    "inputs": [],
                    "outputs": [],
                    "unclear_items": [
                        {"question": "如何处理 tail block?", "context": "tiling"},
                        {"question": "dtype 支持哪些?", "context": "interface"},
                    ],
                }),
            },
        )
        new_state = stage.transition(state, {"agent_result": agent_result})
        assert new_state.requirement is not None
        assert len(new_state.unclear_items) == 2
        assert new_state.requirement_clarified is False

    def test_transition_no_agent_result(self):
        stage = RequirementStage()
        state = self._req_state()
        new_state = stage.transition(state, {})
        assert new_state.requirement is None
        assert new_state.requirement_clarified is False

    def test_transition_agent_error(self):
        stage = RequirementStage()
        state = self._req_state()
        agent_result = AgentResult(agent_name="requirement-analyst", status="fatal")
        new_state = stage.transition(state, {"agent_result": agent_result})
        assert new_state.last_error is not None
        assert new_state.last_error.stage_name == "requirement"

    def test_transition_agent_clean_empty_sets_incomplete_output(self):
        """F5: 干净完成但零产物 → error_type=incomplete_output（既有 selffix
        类目），message 如实说零产物；不让 status 字面量/含糊措辞泄入。"""
        stage = RequirementStage()
        state = self._req_state()
        agent_result = AgentResult(agent_name="requirement-analyst",
                                   status="ok", artifacts={})
        new_state = stage.transition(state, {"agent_result": agent_result})
        assert new_state.last_error is not None
        assert new_state.last_error.error_type == "incomplete_output"
        assert "零产物" in new_state.last_error.message
        assert new_state.requirement_clarified is False

    def test_transition_rejects_malformed_json_types(self):
        """Agent returns JSON with non-list inputs — should be rejected."""
        stage = RequirementStage()
        state = self._req_state()
        agent_result = AgentResult(
            agent_name="requirement-analyst",
            status="ok",
            artifacts={"requirement.json": _with_golden_alignment({
                "name": "gelu",
                "inputs": "not_a_list",
                "outputs": [{"name": "y", "dtype": "fp16", "shape": ["N"]}],
            })},
        )
        new_state = stage.transition(state, {"agent_result": agent_result})
        assert new_state.requirement is None
        assert new_state.last_error is not None

    def test_input_contract(self):
        c = RequirementStage().input_contract()
        assert "requirement_path" in c.requires
        assert "mode" in c.requires

    def test_output_contract(self):
        c = RequirementStage().output_contract()
        for field in ["requirement", "unclear_items", "requirement_clarified"]:
            assert field in c.provides, f"Missing {field}"

    # —— Interactive AskUserQuestion tests ——

    def test_actions_interactive_includes_ask_user_on_first_run(self):
        """First-round review is no longer skipped: interactive mode appends
        AskUserQuestion every round (review runs after SpawnAgent)."""
        stage = RequirementStage()
        state = self._req_state()  # non_interactive defaults to False
        actions = stage.actions(state, iteration=1)
        assert len(actions) == 2
        assert isinstance(actions[0], SpawnAgent)
        assert isinstance(actions[1], AskUserQuestion)

    def test_actions_non_interactive_excludes_ask_user(self):
        """Non-interactive mode never appends review (severity policy in
        transition governs correctness instead)."""
        stage = RequirementStage()
        state = self._req_state().with_updates(non_interactive=True)
        actions = stage.actions(state, iteration=1)
        assert len(actions) == 1  # only SpawnAgent
        assert isinstance(actions[0], SpawnAgent)

    def test_actions_includes_ask_user_on_iteration_gt_1(self):
        """AskUserQuestion is added on later interactive iterations too."""
        stage = RequirementStage()
        state = self._req_state()
        actions = stage.actions(state, iteration=2)
        assert len(actions) == 2
        assert isinstance(actions[0], SpawnAgent)
        assert isinstance(actions[1], AskUserQuestion)
        assert "approve" in [o.label for o in actions[1].options]
        assert "revise" in [o.label for o in actions[1].options]
        assert "abort" in [o.label for o in actions[1].options]

    def test_actions_includes_ask_user_when_requirement_exists(self):
        """AskUserQuestion is added when requirement already exists (review cycle)."""
        from ascendc_devkit.domain.operator import OperatorSpec
        stage = RequirementStage()
        state = State(
            mode="new",
            requirement=Requirement(op_spec=OperatorSpec(name="gelu")),
        )
        actions = stage.actions(state, iteration=1)
        assert len(actions) == 2
        assert isinstance(actions[1], AskUserQuestion)

    @mock.patch("builtins.input", return_value="needs better inputs")
    def test_transition_revise_reads_feedback(self, mock_input):
        """User chooses 'revise' → feedback read, artifacts NOT committed."""
        from ascendc_devkit.domain.operator import OperatorSpec
        stage = RequirementStage()
        state = State(
            mode="new",
            requirement=Requirement(op_spec=OperatorSpec(name="gelu")),
        )
        new_state = stage.transition(state, {"decision": "revise"})
        assert new_state.requirement is None
        assert new_state.requirement_clarified is False
        assert new_state.user_feedback == "needs better inputs"

    def test_transition_abort_raises_decision_pending(self):
        """User chooses 'abort' → DecisionPendingError raised."""
        from ascendc_devkit.domain.operator import OperatorSpec
        from ascendc_devkit.domain.exceptions import DecisionPendingError
        stage = RequirementStage()
        state = State(
            mode="new",
            requirement=Requirement(op_spec=OperatorSpec(name="gelu")),
        )
        with pytest.raises(DecisionPendingError, match="aborted"):
            stage.transition(state, {"decision": "abort"})

    # —— Self-convergence (is_satisfied) + severity policy ——

    def test_is_satisfied_tracks_requirement_clarified(self):
        """is_satisfied gates early-termination on requirement_clarified, so the
        runner keeps iterating while unclear items remain pending."""
        stage = RequirementStage()
        assert stage.is_satisfied(State(requirement_clarified=False)) is False
        assert stage.is_satisfied(State(requirement_clarified=True)) is True

    def _agent_with_unclear(self, items):
        return AgentResult(
            agent_name="requirement-analyst",
            status="ok",
            artifacts={"requirement.json": _with_golden_alignment({
                "op_name": "gelu",
                "mutation_mode": "out_of_place",
                "inputs": [{"name": "x", "dtype": "fp16", "shape": ["N"]}],
                "outputs": [{"name": "y", "dtype": "fp16", "shape": ["N"]}],
                "unclear_items": items,
            })},
        )

    # —— L2 guard: first-pass returns feedback instead of aborting ——
    def test_non_interactive_blocking_first_pass_returns_feedback(self):
        """L2 guard: first time blocking+unresolved → returns feedback loopback
        instead of aborting, so the runner can iterate and the agent re-evaluates."""
        stage = RequirementStage()
        state = self._req_state().with_updates(non_interactive=True)
        agent = self._agent_with_unclear([
            {"question": "3D or 4D rank?", "severity": "blocking"},
        ])
        out = stage.transition(state, {"agent_result": agent})
        assert out.requirement_clarified is False
        assert out.user_feedback is not None
        assert "L2" in out.user_feedback
        assert "3D or 4D rank?" in out.user_feedback

    def test_non_interactive_blocking_second_pass_raises(self):
        """L2 guard: second pass (user_feedback already set) → agent re-confirmed
        blocking → hard PreconditionError."""
        from ascendc_devkit.domain.exceptions import PreconditionError
        stage = RequirementStage()
        state = self._req_state().with_updates(
            non_interactive=True,
            user_feedback="## 自动反馈（框架层 L2 兜底检查）\n\nprior feedback",
        )
        agent = self._agent_with_unclear([
            {"question": "3D or 4D rank?", "severity": "blocking"},
        ])
        with pytest.raises(PreconditionError, match="underspecified"):
            stage.transition(state, {"agent_result": agent})

    def test_non_interactive_choice_unresolved_auto_filled(self):
        """Non-interactive + only choice pending → auto-resolved, clarified True."""
        stage = RequirementStage()
        state = self._req_state().with_updates(non_interactive=True)
        agent = self._agent_with_unclear([
            {"question": "default mode?", "severity": "choice"},
        ])
        out = stage.transition(state, {"agent_result": agent})
        assert out.requirement_clarified is True
        assert out.unclear_items[0].resolution is not None
        assert "default assumption" in out.unclear_items[0].resolution

    def test_non_interactive_resolved_items_pass_through(self):
        """An already-resolved item is untouched and counts as clarified."""
        stage = RequirementStage()
        state = self._req_state().with_updates(non_interactive=True)
        agent = self._agent_with_unclear([
            {"question": "default mode?", "severity": "choice",
             "resolution": "half"},
        ])
        out = stage.transition(state, {"agent_result": agent})
        assert out.requirement_clarified is True
        assert out.unclear_items[0].resolution == "half"

    def test_interactive_leaves_unclear_items_pending(self):
        """Interactive mode does not auto-resolve — items stay pending so the
        runner keeps iterating (agent re-clarifies via resolve_ambiguity)."""
        stage = RequirementStage()
        state = self._req_state()  # interactive
        agent = self._agent_with_unclear([
            {"question": "default mode?", "severity": "choice"},
        ])
        out = stage.transition(state, {"agent_result": agent})
        assert out.requirement_clarified is False
        assert out.unclear_items[0].resolution is None

    # —— P7 / D2: skill delivery via primary_skill (not a prompt-body slash) ——

    def test_requirement_delivers_skill_via_primary_skill(self):
        """D2: the analysis skill travels on SpawnAgent.primary_skill and is
        rendered natively at the backend boundary — NOT baked into the prompt
        body as a claude-only `/<skill>` slash (opencode doesn't expand it)."""
        stage = RequirementStage()
        state = self._req_state()
        actions = stage.actions(state, 1)
        spawn = actions[0]
        assert spawn.primary_skill == "ascendc-op-req-analysis", (
            f"analysis skill must ride primary_skill, got {spawn.primary_skill!r}")
        # allowlist carries the primary (+ any tail-calls) so the session permits it
        assert spawn.skills and spawn.skills[0] == "ascendc-op-req-analysis"

    def test_requirement_prompt_body_has_no_slash_lead(self):
        """D2: the prompt body itself must not lead with the skill slash —
        delivery is decoupled from the body regardless of mode/iteration."""
        stage = RequirementStage()
        state = self._req_state().with_updates(mode="incremental")
        prompt = stage._build_analysis_prompt(state, 2)
        assert not prompt.lstrip().startswith("/ascendc-op-req-analysis"), (
            "prompt body must not carry the claude-only slash trigger")


class TestPerfStageStubbed:
    """Tests for PerfStage environment pre-check and enable_stubbed behavior."""

    @pytest.fixture(autouse=True)
    def _fresh_perf_probe_cache(self, monkeypatch):
        """perf 可用性探测结果为进程级模块缓存——本类真实探测不得污染他例。"""
        import ascendc_devkit.orchestration.stages.perf as perf_mod
        monkeypatch.setattr(perf_mod, "_NPU_AVAILABLE_CACHE", None)

    def test_no_stubbed_raises_when_npu_unavailable(self):
        """Without --enable-stubbed, unavailable NPU raises EnvironmentNotAvailableError."""
        from ascendc_devkit.domain.exceptions import EnvironmentNotAvailableError
        from ascendc_devkit.domain.requirement import Constraint
        stage = PerfStage()
        state = State(
            build_result=BuildResult(passed=True),
            debug_result=PrecisionDebugResult(passed=True),
            generated_sources={"kernel.cpp": "// code"},
            requirement=Requirement(
                op_spec=OperatorSpec(name="gelu"),
                constraints=[Constraint(kind="performance", baseline_ms=2.0)],
            ),
            npu_id=0,
        )
        npu_available = stage._check_npu_available()
        if not npu_available:
            with pytest.raises(EnvironmentNotAvailableError) as exc_info:
                stage.actions(state)
            assert "NPU" in str(exc_info.value)


# ============================================================
# PerfStage
# ============================================================

class TestPerfStage:
    @pytest.fixture(autouse=True)
    def _fresh_perf_probe_cache(self, monkeypatch):
        """perf 可用性探测结果为进程级模块缓存——actions() 内真实/伪探测每例
        独立，且本类结果不得外泄污染后续用例。"""
        import ascendc_devkit.orchestration.stages.perf as perf_mod
        monkeypatch.setattr(perf_mod, "_NPU_AVAILABLE_CACHE", None)

    @staticmethod
    def _perf_state():
        return State(
            build_result=BuildResult(passed=True),
            debug_result=PrecisionDebugResult(passed=True),
            generated_sources={"kernel.cpp": "// code"},
            requirement=Requirement(op_spec=OperatorSpec(name="gelu")),
            npu_id=0,
            enable_stubbed=True,
        )

    def test_actions_no_perf_target_returns_empty(self):
        """When no performance constraint, actions should be empty (stage skipped)."""
        stage = PerfStage()
        state = self._perf_state()
        actions = stage.actions(state)
        assert len(actions) == 0

    def test_skip_reason_no_perf_constraint(self):
        """P6-b: perf stage returns skip reason when no performance constraint."""
        stage = PerfStage()
        state = self._perf_state()
        assert stage.skip_reason(state) == "no performance constraint in requirement"

    def test_skip_reason_none_with_perf_constraint(self):
        """P6-b: perf stage returns None when a performance constraint exists."""
        from ascendc_devkit.domain.requirement import Constraint
        stage = PerfStage()
        state = self._perf_state().with_updates(
            requirement=Requirement(
                op_spec=OperatorSpec(name="gelu"),
                constraints=[Constraint(kind="performance", baseline_ms=2.0)],
            ),
        )
        assert stage.skip_reason(state) is None

    def test_actions_with_perf_target(self):
        from ascendc_devkit.domain.requirement import Constraint
        stage = PerfStage()
        state = self._perf_state().with_updates(
            requirement=Requirement(
                op_spec=OperatorSpec(name="gelu"),
                constraints=[Constraint(kind="performance", baseline_ms=2.0)],
            ),
        )
        actions = stage.actions(state)
        assert len(actions) == 1
        assert isinstance(actions[0], RunGate)
        assert actions[0].gate_name == "performance"

    def test_perf_tuner_working_dir_falls_back_to_state_op_dir(self, tmp_path):
        """P66：op_identity 是 profile-gated（无 profile 的 run 为 None，即便 op_dir 已设）。
        perf-tuner SpawnAgent.working_dir（及 repo_root）必须兜底到 state.op_dir /
        state.repo_root（漏兜底 → cwd 退化到 workspace.artifacts，agent 在错误目录作业）。"""
        from ascendc_devkit.domain.requirement import Constraint
        stage = PerfStage()
        op_dir = tmp_path / "ops" / "gelu"
        state = self._perf_state().with_updates(
            op_dir=op_dir,
            op_identity=None,
            repo_root=tmp_path,
            requirement=Requirement(
                op_spec=OperatorSpec(name="gelu"),
                constraints=[Constraint(kind="performance", baseline_ms=2.0)],
            ),
            performance_result=PerformanceResult(passed=False),
        )
        actions = stage.actions(state, 1)  # iteration=1 < 3 → 非 strategic，进 perf-tuner
        spawn = next(a for a in actions if isinstance(a, SpawnAgent))
        assert spawn.working_dir == op_dir
        assert spawn.repo_root == tmp_path

    def test_transition_no_perf_target(self):
        stage = PerfStage()
        state = self._perf_state()
        new_state = stage.transition(state, {})
        assert new_state.performance_result is not None
        assert new_state.performance_result.passed is True
        assert new_state.perf_iterations == 1

    def test_transition_needs_redesign_at_iteration_3(self):
        stage = PerfStage()
        state = self._perf_state().with_updates(perf_iterations=2)
        new_state = stage.transition(state, {
            "gate_result": {"gate": "performance", "passed": False},
        })
        assert new_state.perf_needs_redesign is True
        assert new_state.perf_iterations == 3

    # —— T1 regression: no-constraint perf must not emit 'tuned' loop-back ——

    def test_resolve_condition_default_when_no_perf_constraint(self):
        """No performance constraint → never 'tuned' (would loop verify↔perf
        forever). Even with perf_iterations>0 and a passing result, resolve to
        'default' so the pipeline advances to integrate."""
        stage = PerfStage()
        state = self._perf_state().with_updates(
            perf_iterations=3,
            performance_result=PerformanceResult(passed=True),
        )
        assert stage.resolve_condition(state) == "default"

    def test_resolve_condition_tuned_only_with_perf_constraint(self):
        """With a performance constraint, a passing result after >=1 iteration
        still routes 'tuned' (re-validate) — original behavior preserved."""
        from ascendc_devkit.domain.requirement import Constraint
        stage = PerfStage()
        state = self._perf_state().with_updates(
            requirement=Requirement(
                op_spec=OperatorSpec(name="gelu"),
                constraints=[Constraint(kind="performance", baseline_ms=2.0)],
            ),
            perf_iterations=1,
            performance_result=PerformanceResult(passed=True),
        )
        assert stage.resolve_condition(state) == "tuned"

    def test_resolve_condition_redesign_takes_precedence(self):
        """perf_needs_redesign short-circuits to 'redesign' regardless of
        constraint presence."""
        stage = PerfStage()
        state = self._perf_state().with_updates(perf_needs_redesign=True)
        assert stage.resolve_condition(state) == "redesign"

    def test_gate_precision_passed(self):
        # D1: PrecisionPassedGate 读 debug_result（precision_debug 产，非 verify 的 precision_result）
        gate = PrecisionPassedGate()
        result = gate.evaluate({"debug_result": PrecisionDebugResult(passed=True)})
        assert result.passed is True

    def test_gate_precision_failed(self):
        gate = PrecisionPassedGate()
        result = gate.evaluate({"debug_result": PrecisionDebugResult(passed=False)})
        assert result.passed is False

    def test_gate_no_debug_result(self):
        # D1: 缺 debug_result → 不过（精度未验证不测性能）
        gate = PrecisionPassedGate()
        result = gate.evaluate({"debug_result": None})
        assert result.passed is False
        assert "debug_result" in result.reason or "precision" in result.reason.lower()

    def test_perf_input_contract_requires_debug_result(self):
        # D1: perf requires 含 debug_result、不含 precision_result
        c = PerfStage().input_contract()
        assert "debug_result" in c.requires
        assert "precision_result" not in c.requires

    def test_input_contract(self):
        c = PerfStage().input_contract()
        assert "build_result" in c.requires
        assert "generated_sources" in c.requires

    def test_output_contract(self):
        c = PerfStage().output_contract()
        for field in ["performance_result", "perf_iterations", "perf_needs_redesign"]:
            assert field in c.provides, f"Missing {field}"

    def test_actions_spawns_perf_tuner_when_perf_fails(self):
        from ascendc_devkit.domain.requirement import Constraint
        stage = PerfStage()
        state = self._perf_state().with_updates(
            requirement=Requirement(
                op_spec=OperatorSpec(name="gelu"),
                constraints=[Constraint(kind="performance", baseline_ms=2.0)],
            ),
            performance_result=PerformanceResult(passed=False, actual_ms=5.0, baseline_ms=2.0),
        )
        actions = stage.actions(state, iteration=1)
        action_types = [type(a).__name__ for a in actions]
        assert "RunGate" in action_types
        assert any(isinstance(a, SpawnAgent) and a.agent_name == "perf-tuner" for a in actions)

    def test_actions_no_perf_tuner_spawn_when_passed(self):
        from ascendc_devkit.domain.requirement import Constraint
        stage = PerfStage()
        state = self._perf_state().with_updates(
            requirement=Requirement(
                op_spec=OperatorSpec(name="gelu"),
                constraints=[Constraint(kind="performance", baseline_ms=2.0)],
            ),
            performance_result=PerformanceResult(passed=True, actual_ms=1.5, baseline_ms=2.0),
        )
        actions = stage.actions(state, iteration=1)
        assert not any(isinstance(a, SpawnAgent) for a in actions)

    def test_transition_applies_agent_tuning_result(self):
        from ascendc_devkit.domain.requirement import Constraint
        stage = PerfStage()
        state = self._perf_state().with_updates(
            requirement=Requirement(
                op_spec=OperatorSpec(name="gelu"),
                constraints=[Constraint(kind="performance", baseline_ms=2.0)],
            ),
            generated_sources={"gelu.cpp": "// original"},
        )
        agent_result = AgentResult(
            agent_name="perf-tuner",
            status="ok",
            artifacts={"gelu.cpp": "// optimized with loop unrolling"},
        )
        new_state = stage.transition(state, {
            "gate_result": {"gate": "performance", "passed": False, "metrics": {"actual_ms": 3.0, "baseline_ms": 2.0}},
            "agent_result": agent_result,
        })
        assert new_state.generated_sources["gelu.cpp"] == "// optimized with loop unrolling"
        assert new_state.performance_result.actual_ms == 3.0

    def test_performance_gate_pass(self):
        from unittest import mock as umock
        from ascendc_devkit.domain.requirement import Constraint
        from ascendc_devkit.adapters.npu.runner import NPURunner

        gate = PerformanceGate()
        evidence = {
            "generated_sources": {},
            "requirement": Requirement(
                op_spec=OperatorSpec(name="gelu"),
                constraints=[Constraint(kind="performance", baseline_ms=5.0)],
            ),
            "npu_id": 0,
            "design_target_chip": "A2",
            "enable_stubbed": True,
        }
        # Stub NPURunner.execute to return deterministic result regardless of NPU availability
        with umock.patch.object(NPURunner, "execute", return_value={
            "passed": True, "actual_ms": 1.5, "max_diff": 0.0,
            "per_shape": {"1024": 1.5}, "bottleneck": "stubbed",
            "stubbed": True,
        }):
            result = gate.evaluate(evidence)
        assert result.passed is True
        assert result.metrics["actual_ms"] <= 5.0

    def test_performance_gate_no_constraint(self):
        gate = PerformanceGate()
        result = gate.evaluate({
            "generated_sources": {},
            "requirement": Requirement(op_spec=OperatorSpec(name="gelu")),
            "npu_id": 0,
        })
        assert result.passed is True
        assert result.metrics["actual_ms"] == 0.0

    def test_performance_gate_primary_dtype_from_multi_dtype_list(self):
        """When the first input has a multi-dtype list, the gate must extract
        dtype[0] as the scalar primary dtype, not pass the whole list through."""
        from unittest import mock as umock
        from ascendc_devkit.domain.requirement import Constraint
        from ascendc_devkit.adapters.npu.runner import NPURunner

        gate = PerformanceGate()
        op_spec = OperatorSpec(
            name="exp",
            inputs=[TensorSpec(name="x", dtype=["fp16", "fp32", "bf16"],
                               shape=["N"])],
            outputs=[TensorSpec(name="y", dtype=["fp16", "fp32", "bf16"],
                                shape=["N"])],
        )
        evidence = {
            "generated_sources": {},
            "requirement": Requirement(
                op_spec=op_spec,
                constraints=[Constraint(kind="performance", baseline_ms=5.0)],
            ),
            "npu_id": 0,
            "design_target_chip": "A5",
            "enable_stubbed": True,
        }
        with umock.patch.object(NPURunner, "execute") as mock_exec:
            mock_exec.return_value = {
                "passed": True, "actual_ms": 1.5, "max_diff": 0.0,
                "per_shape": {"1024": 1.5}, "bottleneck": "stubbed",
                "stubbed": True,
            }
            gate.evaluate(evidence)
            # Verify the harness received a scalar dtype string, not a list
            call_args = mock_exec.call_args
            test_cases = call_args[0][1]  # second positional arg
            assert len(test_cases) == 1
            assert test_cases[0].inputs[0]["dtype"] == "fp16"


# ============================================================
# IntegrateStage
# ============================================================

class TestIntegrateStage:
    @staticmethod
    def _integrate_state(tmpdir=None):
        from ascendc_devkit.adapters.repository.generic import GenericRepositoryAdapter
        profile = _omni_profile()
        adapter = GenericRepositoryAdapter(profile)
        repo_root = Path(tmpdir) if tmpdir else Path("/tmp")
        return State(
            mode="new",
            generated_sources={"kernel.cpp": "// code"},
            adapter=adapter,
            op_identity=OperatorIdentity(
                spec=OperatorSpec(name="gelu"),
                repo_root=repo_root,
                op_dir=repo_root / "custom_ops" / "gelu",
            ),
            profile=profile,
            target_repo=repo_root,
        )

    def test_actions_is_noop_validation_only(self):
        # Plan-A: integrate no longer materializes — actions is a single NoOp;
        # validation runs in transition() by reading op_dir.
        from ascendc_devkit.orchestration.kernel.action import NoOp
        stage = IntegrateStage()
        actions = stage.actions(self._integrate_state())
        assert len(actions) == 1
        assert isinstance(actions[0], NoOp)

    def test_actions_incremental_same_path_as_new(self):
        # new and incremental collapse to the same (NoOp) path under Plan-A.
        from ascendc_devkit.orchestration.kernel.action import NoOp
        stage = IntegrateStage()
        new_actions = stage.actions(self._integrate_state())
        inc_actions = stage.actions(self._integrate_state().with_updates(mode="incremental"))
        assert len(new_actions) == len(inc_actions) == 1
        assert isinstance(inc_actions[0], NoOp)

    def test_transition_validates_op_dir_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            stage = IntegrateStage()
            state = self._integrate_state(tmpdir)
            op_dir = Path(tmpdir) / "custom_ops" / "gelu"
            op_dir.mkdir(parents=True, exist_ok=True)
            (op_dir / "kernel.cpp").write_text("// code", encoding="utf-8")
            new_state = stage.transition(state, {})
            assert new_state.integration_result["status"] == "ok"
            # target_files read FROM op_dir, not written from memory.
            assert len(new_state.target_files) == 1
            assert new_state.target_files[0].name == "kernel.cpp"

    def test_transition_fails_when_op_dir_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            stage = IntegrateStage()
            state = self._integrate_state(tmpdir)
            op_dir = Path(tmpdir) / "custom_ops" / "gelu"
            op_dir.mkdir(parents=True, exist_ok=True)  # exists but empty
            new_state = stage.transition(state, {})
            assert new_state.integration_result["status"] == "error"
            assert new_state.target_files == []
            assert new_state.last_error is not None
            assert new_state.last_error.error_type == "integration_incomplete"

    def test_transition_fails_when_expected_section_missing(self):
        """P2 section-level: IntegrateStage checks section directories exist with content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            stage = IntegrateStage()
            state = self._integrate_state(tmpdir).with_updates(
                kernel_architecture={
                    "host_code": {"directory": "op_host"},
                    "kernel_code": {"directory": "op_kernel"},
                },
            )
            op_dir = Path(tmpdir) / "custom_ops" / "gelu"
            op_dir.mkdir(parents=True, exist_ok=True)
            (op_dir / "op_kernel").mkdir(parents=True, exist_ok=True)
            (op_dir / "op_kernel" / "gelu.cpp").write_text("// only one", encoding="utf-8")
            new_state = stage.transition(state, {})
            assert new_state.integration_result["status"] == "error"
            # Section-level: missing op_host section
            assert "op_host" in new_state.last_error.message

    def test_transition_skips_without_op_identity(self):
        stage = IntegrateStage()
        state = State(mode="new", op_identity=None)
        new_state = stage.transition(state, {})
        assert new_state.integration_result["status"] == "skipped"
        assert new_state.target_files == []

    def test_gate_verify_complete_passes(self):
        gate = VerifyCompleteGate()
        result = gate.evaluate({
            "build_result": BuildResult(passed=True),
        })
        assert result.passed is True

    def test_gate_verify_complete_build_failed(self):
        gate = VerifyCompleteGate()
        result = gate.evaluate({
            "build_result": BuildResult(passed=False, stderr="linker error"),
        })
        assert result.passed is False

    def test_gate_no_build_result(self):
        gate = VerifyCompleteGate()
        result = gate.evaluate({"build_result": None})
        assert result.passed is False

    def test_input_contract(self):
        c = IntegrateStage().input_contract()
        # Plan-A: code in repo → no generated_sources requirement; reads op_dir.
        assert "mode" in c.requires
        assert "op_identity" in c.requires
        assert "adapter" in c.requires
        assert "generated_sources" not in c.requires
        assert "change_set" not in c.optional

    def test_output_contract(self):
        c = IntegrateStage().output_contract()
        for field in ["integration_result", "target_files"]:
            assert field in c.provides, f"Missing {field}"


# ============================================================
# FinalizeStage
# ============================================================

class TestFinalizeStage:
    @staticmethod
    def _finalize_state():
        from ascendc_devkit.adapters.repository.generic import GenericRepositoryAdapter
        profile = _omni_profile()
        adapter = GenericRepositoryAdapter(profile)
        return State(
            mode="new",
            target_files=[Path("/tmp/custom_ops/gelu/kernel.cpp")],
            integration_result={"status": "ok", "files": 1},
            adapter=adapter,
            op_identity=OperatorIdentity(
                spec=OperatorSpec(name="gelu"),
                repo_root=Path("/tmp"),
                op_dir=Path("/tmp/custom_ops/gelu"),
            ),
        )

    def test_actions_build(self):
        # D8: report generation moved to dispatcher finally-block; FinalizeStage
        # actions are just the in-repo build gate (no GenerateReport marker).
        stage = FinalizeStage()
        state = self._finalize_state()
        actions = stage.actions(state)
        assert len(actions) == 1
        assert isinstance(actions[0], RunGate)
        assert actions[0].gate_name == "build_in_repo"

    def test_actions_incremental_mode(self):
        stage = FinalizeStage()
        state = self._finalize_state().with_updates(mode="incremental")
        actions = stage.actions(state)
        assert any(isinstance(a, UpdateDevRecord) for a in actions)

    def test_transition_sets_final_result(self):
        stage = FinalizeStage()
        state = self._finalize_state()
        new_state = stage.transition(state, {
            "gate_result": {"gate": "build_in_repo", "passed": True, "reason": "ok"},
        })
        assert new_state.final_build_result is not None
        assert new_state.final_build_result.passed is True
        assert new_state.dev_record_updated is False

    def test_gate_integration_complete_passes(self):
        gate = IntegrationCompleteGate()
        result = gate.evaluate({
            "integration_result": {"status": "ok", "files": 3},
            "target_files": [Path("/tmp/a.cpp"), Path("/tmp/b.cpp")],
        })
        assert result.passed is True

    def test_gate_integration_complete_no_files(self):
        gate = IntegrationCompleteGate()
        result = gate.evaluate({
            "integration_result": {"status": "ok"},
            "target_files": [],
        })
        assert result.passed is False

    def test_gate_integration_error(self):
        gate = IntegrationCompleteGate()
        result = gate.evaluate({
            "integration_result": {"status": "error", "error": "disk full"},
            "target_files": [],
        })
        assert result.passed is False

    def test_input_contract(self):
        c = FinalizeStage().input_contract()
        assert "mode" in c.requires
        assert "target_files" in c.optional
        assert "integration_result" in c.optional

    def test_output_contract(self):
        c = FinalizeStage().output_contract()
        for field in ["final_build_result", "dev_record_updated"]:
            assert field in c.provides, f"Missing {field}"


# ============================================================
# Runner Integration Tests for new Stages
# ============================================================

class TestRunnerWithNewStages:
    def test_runner_entry_stage_full_cycle(self):
        stage = EntryStage()
        state = State(
            non_interactive=True,
            task_request={
                "mode": "new",
                "workflow": "generate_ascendc",
                "target_repo": "/tmp/test-repo",
                "repo_profile": "omni-ops",
                "op_name": "gelu",
                "npu_id": 0,
                "non_interactive": True,
            },
        )
        runner = Runner(agent_backend=StubBackend())
        final = runner.run_stage(state, stage)
        assert final.mode == "new"
        assert final.op_name == "gelu"
        assert final.repo_profile_name == "omni-ops"
        assert final.stage_iterations.get("entry") == 1

    def test_runner_context_stage_full_cycle(self):
        stage = ContextStage()
        state = State(
            mode="new",
            op_name="gelu",
            target_repo=Path("/tmp/test-repo"),
            repo_root=Path("/tmp/test-repo"),
            op_dir=Path("/tmp/test-repo/inference/ascendc/src/g/c/ai_infra_gelu"),
            rel_op_dir="inference/ascendc/src/g/c/ai_infra_gelu",
            full_op_name="ai_infra_gelu",
            repo_profile_name="omni-ops",
            non_interactive=True,
        )
        runner = Runner(agent_backend=StubBackend())
        final = runner.run_stage(state, stage)
        assert final.profile is not None
        assert final.adapter is not None
        assert final.op_identity is not None
        assert final.stage_iterations.get("context") == 1

    def test_runner_requirement_stage_full_cycle(self):
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            f.write(json.dumps({"op": {"name": "gelu"}, "constraints": [], "test_cases": []}))
            req_path = Path(f.name)
        backend = StubBackend(canned_responses=[
            AgentResult(
                agent_name="requirement-analyst",
                status="ok",
                artifacts={
                    "requirement.json": _with_golden_alignment({
                        "op_name": "gelu",
                        "mutation_mode": "out_of_place",
                        "inputs": [{"name": "x", "dtype": "fp16", "shape": ["N"]}],
                        "outputs": [{"name": "y", "dtype": "fp16", "shape": ["N"]}],
                        "unclear_items": [],
                    }),
                },
            ),
        ])
        stage = RequirementStage()
        state = State(mode="new", requirement_path=req_path,
                      non_interactive=True)
        runner = Runner(agent_backend=backend)
        final = runner.run_stage(state, stage)
        assert final.requirement is not None
        assert final.requirement.op_spec.name == "gelu"
        assert final.requirement_clarified is True

    def test_runner_design_stage_full_cycle(self, tmp_path):
        # step-2b: the design stage is now the detailed-design group; SynthesizeStage
        # parses the two-piece contract into State (step 9: kernel_architecture moved
        # to codegen_init); docgen is a separate stage (docs/plan/synthesize-docgen-dilution/).
        from ascendc_devkit.infra.workspace import Workspace
        from ascendc_devkit.orchestration.stages.design_substages import SynthesizeStage
        backend = StubBackend(canned_responses=[
            AgentResult(
                agent_name="ascendc-op-design-integrate",
                status="ok",
                artifacts={
                    "design_spec.json": json.dumps({"op_name": "gelu", "inputs": [], "outputs": []}),
                    "tiling_strategy.json": json.dumps({"tile_size": 256}),
                    "data_flow.json": json.dumps({"Init": "none"}),
                },
            ),
        ])
        stage = SynthesizeStage()
        # P62: SynthesizeStage reads its products from disk under the stage's
        # working_dir (state._workspace.artifacts/design/synthesize). The stub
        # lands its canned artifacts there (StubBackend models a real agent's
        # cwd writes), so the state needs a workspace for the path to resolve.
        ws = Workspace.create(output_root=str(tmp_path / "out"), run_id="r1")
        state = State(mode="new",
                      tiling_results={"T1": {"split": {}}},
                      non_interactive=True,
                      _workspace=ws)
        runner = Runner(agent_backend=backend)
        final = runner.run_stage(state, stage)
        assert final.design_spec is not None
        assert final.tiling_strategy is not None
        # kernel_architecture no longer produced by design integrator (step 9)
        assert final.kernel_architecture is None
        assert final.data_flow is not None

    def test_runner_docgen_missing_md_halts_after_bounded_retry(self, tmp_path):
        """有界重试守护（§1.14 反空转）：docgen agent 每轮都不产出 <op>_详细设计
        说明书.md → runner 必须在 ``iterations.stages.docgen``（=3）轮后终止
        （fail_strategy=halt 传播 _stage_failed），而非无限空转。方案 C（docs/plan/
        synthesize-docgen-dilution/）的兜底是「缺产物 → 定向 respawn 反馈」，其
        有界性由 iteration ceiling 确定性守护。"""
        from ascendc_devkit.orchestration.stages.design_substages import DocgenStage
        # 3 轮同一 canned 响应：每轮都不写 md → 每轮都在 docgen glob 处失败 →
        # 有界重试后 halt（user_feedback 注入 skill 提示，stub 不消费它）。
        backend = StubBackend(canned_responses=[
            AgentResult(agent_name="ascendc-op-design-docgen", status="ok",
                        artifacts={}),
        ] * 3)
        ws = Workspace.create(output_root=str(tmp_path / "out"), run_id="r1")
        state = State(mode="new",
                      design_spec={"op_name": "add", "mutation_mode": "out_of_place",
                                   "inputs": [{"name": "x"}], "outputs": [{"name": "y"}]},
                      tiling_strategy={"approach": "single_core"},
                      tiling_results={"T1": {"split": {}}},
                      non_interactive=True, _workspace=ws)
        runner = Runner(agent_backend=backend)
        final = runner.run_stage(state, DocgenStage())
        # 有界：R1 (2026-08-21) 后缺产物走公共 artifact-retry（独立预算 5，不烧
        # iteration）→ 耗尽后落回 iteration（config docgen=3）→ 总 spawn = 5+3 = 8。
        # 有界性仍由 (artifact_retry_max + iterations.docgen) 确定性守护（非无限 spin），
        # fail_strategy=halt 传播 _stage_failed 不变。
        assert len(backend.spawn_calls) == 5 + 3, (
            f"expected 5 artifact-retry + 3 iteration = 8 spawns, "
            f"got {len(backend.spawn_calls)}")
        assert final.design_doc is None  # md 始终未产出
        assert final._stage_failed is not None  # fail_strategy=halt 传播失败信号
        assert final._stage_failed[0] == "failed"

    def test_runner_integrate_stage_full_cycle(self):
        from ascendc_devkit.adapters.repository.generic import GenericRepositoryAdapter
        profile = _omni_profile()
        adapter = GenericRepositoryAdapter(profile)
        with tempfile.TemporaryDirectory() as tmpdir:
            stage = IntegrateStage()
            op_dir = Path(tmpdir) / "custom_ops" / "gelu"
            op_dir.mkdir(parents=True, exist_ok=True)
            # Plan-A: code already lives in op_dir; integrate validates+reads it.
            (op_dir / "kernel.cpp").write_text("// code", encoding="utf-8")
            state = State(
                mode="new",
                generated_sources={"kernel.cpp": "// code"},
                adapter=adapter,
                op_identity=OperatorIdentity(
                    spec=OperatorSpec(name="gelu"),
                    repo_root=Path(tmpdir),
                    op_dir=op_dir,
                ),
                profile=profile,
                target_repo=Path(tmpdir),
                build_result=BuildResult(passed=True),
                debug_result=PrecisionDebugResult(passed=True),
            )
            runner = Runner(
                agent_backend=StubBackend(),
                adapters={"repository": adapter},
            )
            final = runner.run_stage(state, stage)
            assert final.integration_result["status"] == "ok"
            assert len(final.target_files) == 1

    def test_runner_finalize_stage_full_cycle(self):
        from ascendc_devkit.adapters.repository.generic import GenericRepositoryAdapter
        profile = RepositoryProfile(name="omni-ops")
        adapter = GenericRepositoryAdapter(profile)
        stage = FinalizeStage()
        state = State(
            mode="new",
            target_files=[Path("/tmp/custom_ops/gelu/kernel.cpp")],
            integration_result={"status": "ok", "files": 1},
            adapter=adapter,
            op_identity=OperatorIdentity(
                spec=OperatorSpec(name="gelu"),
                repo_root=Path("/tmp"),
                op_dir=Path("/tmp/custom_ops/gelu"),
            ),
        )
        runner = Runner(agent_backend=StubBackend())
        final = runner.run_stage(state, stage)
        assert final.final_build_result is not None

    def test_runner_raises_on_validate_inputs_failure(self):
        """Runner calls validate_inputs and raises PreconditionError on failures."""
        from ascendc_devkit.domain.exceptions import PreconditionError
        stage = CodegenStage()
        state = State(
            mode="new",
            design_spec={},  # empty inputs/outputs triggers validation error
            tiling_strategy={"tile_size": 256},
            kernel_architecture={"classes": ["KernelGelu"]},
            profile=RepositoryProfile(name="test"),
        )
        runner = Runner(agent_backend=StubBackend())
        with pytest.raises(PreconditionError, match="input validation failed"):
            runner.run_stage(state, stage)


# ============================================================
# Contract no-spin audit (orthogonal stages)
# ============================================================

class TestStageContractNoSpin:
    """Regression guard for the contract-spin defect: after a successful
    transition, has_all(output_contract().provides) must be True so the runner
    early-terminates instead of spinning to max_iterations.

    Scope: entry/context/design/requirement (orthogonal to plan A). The
    codegen/verify/perf/integrate no-spin tests are deferred to plan A because
    their artifact-collection model is being rewritten.
    """

    def test_entry_no_spin_without_requirement_path(self):
        # new mode, no requirement_path / target_repo supplied → must still
        # satisfy provides (the conditional outputs live in optional_provides).
        stage = EntryStage()
        state = State(task_request={"mode": "new"})
        out = stage.transition(state, {})
        assert out.has_all(stage.output_contract().provides)

    def test_context_no_spin_new_mode_no_reference(self):
        # new mode without reference_op_path → reference_code is {} (not None).
        stage = ContextStage()
        state = State(mode="new", op_name="Foo", repo_profile_name="",
                      target_repo=None)
        out = stage.transition(state, {})
        assert out.reference_code == {}
        # profile/adapter/op_identity may be None when no profile is loaded;
        # the field that previously caused the spin (reference_code) is fixed.
        assert out.reference_code is not None

    def test_design_no_spin_without_data_flow(self, tmp_path):
        # Agent omits the schema-optional data_flow.json → provides still met.
        # step-2b: SynthesizeStage is the integrate producer (docgen is separate).
        # P62: products land on disk under working_dir (disk-only read pathway);
        # omitting the optional data_flow.json on disk must still satisfy provides.
        from ascendc_devkit.orchestration.stages.design_substages import SynthesizeStage
        stage = SynthesizeStage()
        wd = tmp_path / "design" / "synthesize"
        wd.mkdir(parents=True)
        (wd / "design_spec.json").write_text(json.dumps(
            {"op_name": "gelu", "inputs": [{"name": "x"}],
             "outputs": [{"name": "y"}], "files": ["a.cpp"]}), encoding="utf-8")
        (wd / "tiling_strategy.json").write_text(
            json.dumps({"tile_size": 256}), encoding="utf-8")
        # data_flow.json intentionally omitted (schema-optional)
        state = State(mode="new",
                      tiling_results={"T1": {"split": {}}})
        out = stage.transition(state, {"_working_dir": str(wd)})
        assert out.has_all(stage.output_contract().provides)
        assert out.data_flow is None  # optional output legitimately absent

    def test_requirement_no_spin_on_clarified_output(self):
        # A fully parsed requirement with no unclear items satisfies provides.
        stage = RequirementStage()
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write("requirement doc")
            req_path = Path(f.name)
        state = State(mode="new", requirement_path=req_path)
        agent_result = AgentResult(
            agent_name="requirement-analyst",
            status="ok",
            artifacts={"requirement.json": _with_golden_alignment({
                "op_name": "gelu",
                "mutation_mode": "out_of_place",
                "inputs": [{"name": "x", "dtype": "fp16", "shape": ["N"]}],
                "outputs": [{"name": "y", "dtype": "fp16", "shape": ["N"]}],
                "unclear_items": [],
            })},
        )
        out = stage.transition(state, {"agent_result": agent_result})
        assert out.has_all(stage.output_contract().provides)


# —— P6-b / P6-c: base Stage hooks that every stage inherits ——

class TestStageBaseHooks:
    """Stage base class default hooks (skip_reason, loopback_feedback)."""

    @staticmethod
    def _concrete_stage():
        from ascendc_devkit.orchestration.base import Stage
        from ascendc_devkit.domain.contract import StageIOContract

        class _S(Stage):
            name = "test"
            def input_contract(self): return StageIOContract()
            def output_contract(self): return StageIOContract()
            def actions(self, state, iteration=1): return []
        return _S()

    def test_skip_reason_defaults_to_none(self):
        """P6-b: base Stage.skip_reason returns None."""
        assert self._concrete_stage().skip_reason(State.empty()) is None

    def test_loopback_feedback_defaults_to_none(self):
        """P6-c: base Stage.loopback_feedback returns None."""
        assert self._concrete_stage().loopback_feedback(State.empty()) is None


# ============================================================
# Runner contract WARN precision (entry npu_id regression companion)
# ============================================================

class TestRunnerContractWarn:
    """Guards the 'reached max iterations' WARN names the ACTUALLY missing
    contract fields, not the whole provides list. The old text printed
    ``{output_contract.provides}`` (every declared output), which read as
    'every declared output is missing' and sent users hunting for config that
    was never required — e.g. entry's runtime-filled npu_id, legitimately None
    in batch mode (see TestEntryStage.test_entry_no_spin_when_npu_id_none)."""

    def test_unsatisfied_contract_fields_helper(self):
        from ascendc_devkit.orchestration.kernel.runner import _unsatisfied_contract_fields
        state = State(mode="new")
        # mode is set (non-None) → satisfied; non_existent absent → missing.
        assert _unsatisfied_contract_fields(state, ["mode", "non_existent"]) == ["non_existent"]
        # falsy-but-non-None (0/False/"") counts as satisfied — mirrors has_all,
        # since a stage may legitimately produce these values.
        s2 = State(npu_id=0, non_interactive=False)
        assert _unsatisfied_contract_fields(s2, ["npu_id", "non_interactive"]) == []

    def test_warn_names_missing_not_full_provides(self):
        from ascendc_devkit.orchestration.base import Stage
        from ascendc_devkit.domain.contract import StageIOContract

        class _PartlySatisfiedStage(Stage):
            # Declares two provides, transition sets only one → exactly one
            # missing when the 1-iteration ceiling hits → WARN must name only it.
            name = "fake_partial"
            default_max_iterations = 1
            needs_iteration_safety_net = False

            def input_contract(self):
                return StageIOContract(requires=[], optional=[])

            def output_contract(self):
                return StageIOContract(provides=["mode", "definitely_missing"])

            def actions(self, state, iteration=1):
                return [ValidateInputs(checks=["ok"])]

            def transition(self, state, result):
                return state.with_updates(mode="new")

        runner = Runner()  # no backend needed — stage never spawns an agent
        runner.Logger = mock.Mock()
        runner.run_stage(State(mode="new", non_interactive=True), _PartlySatisfiedStage())
        assert runner.Logger.warn.called, "expected a 'reached max iterations' WARN"
        msg = runner.Logger.warn.call_args[0][0]
        assert "missing:" in msg
        assert "definitely_missing" in msg
        # Satisfied fields must NOT leak into the WARN — that was the old bug
        # (the whole provides list was printed, masquerading as "all missing").
        assert "mode" not in msg


# ---- Part 2 (2026-08-20): 脚手架契约摘要（替代整读参考算子，省 ~90K 探索成本） ----

def _ref_state():
    return State(mode="new").with_updates(reference_code={
        "op_api/aclnn_add.cpp": "// aclnn_add wrapper\n",
        "op_host/add_def.cpp": "// OpDef\n",
        "op_kernel/add.h": "// kernel\n",
        "op_plugin/add_plugin.cpp": (
            'TORCH_LIBRARY_FRAGMENT(cann_bench, m) {\n'
            '    m.def("add(Tensor a, Tensor b) -> Tensor");\n'
            '}\n'),
        "CMakeLists.txt": (
            "# 参考算子 CMakeLists\n"
            "file(GLOB OPS ${SRC_BASE}/*)\n"
            "foreach(d ${OPS})\n"
            "  add_subdirectory(${d})\n"
            "endforeach()\n"),
    })


def test_scaffold_contract_summary_derives_compact_contract():
    """Part 2: reference_code → 紧凑脚手架契约摘要（文件布局/CMake 注册/m.def 签名）。"""
    stage = CodegenStage.__new__(CodegenStage)
    s = stage._scaffold_contract_summary(_ref_state())
    assert s is not None
    assert "参考算子脚手架契约摘要" in s
    assert "add_plugin.cpp" in s              # 文件布局
    assert "cann_bench" in s                  # TORCH_LIBRARY namespace
    assert "m.def 签名" in s and "add(" in s   # 签名
    assert "GLOB" in s                        # CMake 模式
    assert len(s) < 5000                      # 紧凑
    # 空 reference_code → None（不注入空段）
    assert stage._scaffold_contract_summary(
        State(mode="new").with_updates(reference_code={})) is None
    assert stage._scaffold_contract_summary(State(mode="new")) is None


def test_scaffold_contract_summary_no_plugin_no_cmake():
    """只有纯 kernel 文件 → 摘要仍给文件布局，无注册段不报错。"""
    stage = CodegenStage.__new__(CodegenStage)
    s = stage._scaffold_contract_summary(
        State(mode="new").with_updates(reference_code={"op_kernel/x.h": "// k"}))
    assert s is not None and "x.h" in s
    assert "m.def 签名" not in s  # 无 plugin，不编造


def test_codegen_prompt_injects_scaffold_contract_when_reference_present():
    """Part 2: coder prompt 含脚手架契约摘要段（当 reference_code 存在）；无引用时不注入。"""
    stage = CodegenStage()
    # 有 reference_code → 注入摘要段
    state = State(
        mode="new",
        reference_code={"op_plugin/add_plugin.cpp": (
            'TORCH_LIBRARY_FRAGMENT(cann_bench, m) {\n'
            '    m.def("add(Tensor a, Tensor b) -> Tensor");\n}\n'),
                        "CMakeLists.txt": "file(GLOB OPS ${SRC_BASE}/*)"},
    )
    prompt = stage._build_codegen_prompt(state, 1)
    assert "参考算子脚手架契约摘要" in prompt
    assert "cann_bench" in prompt          # namespace
    assert "无需整读全部 ref_*.cpp" in prompt
    # 无 reference_code → 不注入空段
    state2 = State(mode="new")
    prompt2 = stage._build_codegen_prompt(state2, 1)
    assert "参考算子脚手架契约摘要" not in prompt2


class TestBuildMechanicalStopLoss:
    """2026-09-10（advisory 废弃收口）：build 侧机械 stop-loss（镜像 smoke）——
    同签名连续 ≥3 次仍无进展 → 强制 D4（不依赖 coder 声明"该换策略"）。"""

    _SIG_LOG = "/tmp/build_sig_test.log"

    def _gelu_state(self):
        # 复用 TestCodegenStage 的完整 gelu state（带 profile，transition 的
        # _inject_scaffolding_kind 需要）——不另造空 state（无 profile 会报错）。
        return TestCodegenStage._gelu_state()

    def _err(self, msg: str, tag: str = "a") -> ErrorFeedback:
        """构造一个 details.log 指向的 build 错误（文件内容决定签名）。
        tag 区分不同错误实例的文件路径——共用同一文件会相互覆盖
        （transition 从 err.details.log 读当前内容，顺序污染会串签名）。"""
        log_path = f"/tmp/build_sig_{tag}.log"
        with open(log_path, "w") as f:
            f.write(
                "=== rc === exit 1\n=== stderr ===\n"
                "  /home/x/op_host/transpose_infershape.cpp:40:11:\n"
                f"  error: {msg}\n")
        return ErrorFeedback(
            stage_name="deploy", error_type="deploy_failed",
            message="build failed",
            details={"step": "build", "log": log_path, "stderr_tail": msg})

    def _transition_build_fail(self, tmp_path, err, streak=0, last_sig="",
                               retries=0, run_id="r1"):
        stage = CodegenStage()
        state = _attach_passing_deploy(
            self._gelu_state().with_updates(
                codegen_build_retries=retries,
                codegen_build_same_error_streak=streak,
                codegen_build_last_error_sig=last_sig), tmp_path, run_id=run_id)
        agent_result = AgentResult(agent_name="ascendc-coder", status="ok",
                                   artifacts=_gelu_artifacts())
        with _patch_deploy(build_fail=True, c_err=err):
            return stage.transition(state, {"agent_result": agent_result})

    def test_same_signature_streak_reaches_threshold_forced_d4(self, tmp_path):
        """同签名连续 3 次（streak=2 预热 + 本轮=3）→ 机械 stop-loss 强制 D4
        （deploy_result smoke_passed=False 交下游，不 halt、不继续 build-retry）。"""
        err = self._err("'TypedContinuousVector' does not name a type")
        # streak=2 + 同签名 → 本轮 = 3 ≥ 3 → D4
        new_state = self._transition_build_fail(
            tmp_path, err, streak=2, last_sig=CodegenStage._build_error_signature(err))
        assert new_state.deploy_result is not None
        assert new_state.deploy_result.smoke_passed is False
        assert new_state.last_error is None          # D4 不 halt
        assert getattr(new_state, "_stage_failed", None) is None
        # 离开 build 循环 → streak 重置
        assert new_state.codegen_build_same_error_streak == 0
        assert new_state.codegen_build_last_error_sig == ""

    def test_same_signature_streak_accumulates_below_threshold(self, tmp_path):
        """同签名连续 2 次（streak=1 + 本轮=2 < 3）→ 继续 build-retry，streak 累计。"""
        err = self._err("'TypedContinuousVector' does not name a type")
        new_state = self._transition_build_fail(
            tmp_path, err, streak=1, last_sig=CodegenStage._build_error_signature(err))
        assert new_state.deploy_result is None        # 继续重试（不写 deploy_result）
        assert new_state.codegen_build_feedback is not None
        assert new_state.codegen_build_same_error_streak == 2
        assert new_state.codegen_build_last_error_sig != ""

    def test_different_signature_resets_streak(self, tmp_path):
        """签名变化（错误真的变了）→ streak 重置为 1，不误 stop-loss。"""
        # 两个不同错误实例（不同文件路径，签名互不干扰）
        err_a = self._err("'TypedContinuousVector' does not name a type", tag="a")
        sig_a = CodegenStage._build_error_signature(err_a)
        err_b = self._err("conflicting declaration 'uint64_t coreNum'", tag="b")
        # 用上一轮 sig_a 预热 streak，本轮同为 err_a → 同签名，streak=1+1=2
        new_state = self._transition_build_fail(
            tmp_path, err_a, streak=1, last_sig=sig_a)
        assert new_state.codegen_build_same_error_streak == 2
        # 换一个不同错误(err_b) → 签名不同 → streak 重置为 1（不误 stop-loss）
        # 第二次 _attach_passing_deploy 会撞 workspace 目录（同 tmp_path/out），
        # 用不同 run_id 规避（out/r2）
        new_state2 = self._transition_build_fail(
            tmp_path, err_b, streak=2, last_sig=sig_a, run_id="r2")
        assert new_state2.codegen_build_same_error_streak == 1
        assert new_state2.deploy_result is None     # 继续重试（不 D4）
