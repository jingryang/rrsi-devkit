"""Plan-A in-repo codegen — integration regression (Phase 6).

Task 6.1: contract no-spin guard for codegen/verify/perf/integrate (each one
transition fills its output_contract.provides, never spinning to max_iterations).
Task 6.2: end-to-end smoke over a tmp git repo (cwd→op_dir, in-repo build,
integrate validates without materializing) + failure-rollback / abort-preserve.
"""

from __future__ import annotations

import json
import subprocess
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import pytest

from ascendc_devkit.orchestration.kernel.state import State, ErrorFeedback
from ascendc_devkit.domain.operator import OperatorSpec, OperatorIdentity
from ascendc_devkit.domain.requirement import Requirement
from ascendc_devkit.domain.repository import RepositoryProfile
from ascendc_devkit.domain.verification import BuildResult, DeployResult
from ascendc_devkit.adapters.repository.generic import GenericRepositoryAdapter
from ascendc_devkit.infra.workspace import Workspace
from ascendc_devkit.orchestration.stages.codegen import CodegenStage
from ascendc_devkit.orchestration.stages.perf import PerfStage
from ascendc_devkit.orchestration.stages.integrate import IntegrateStage
from ascendc_devkit.capabilities.agent.backend import AgentResult


def _has_git() -> bool:
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True)
        return True
    except Exception:
        return False


def _op_identity(repo_root: Path, op_name: str = "gelu") -> OperatorIdentity:
    return OperatorIdentity(
        spec=OperatorSpec(name=op_name),
        repo_root=repo_root,
        op_dir=repo_root / "custom_ops" / op_name,
    )


def _attach_passing_deploy(state, tmp_path, smoke_passed=True):
    """Attach a run workspace + last_deploy.json (the codegen agent's redeploy
    handoff) so the codegen transition satisfies its build-loop contract
    (P57-B: success requires build_result/deploy_result). Mirrors the same
    helper in test_stages.py."""
    ws = Workspace.create(output_root=str(tmp_path / "out"), run_id="r1")
    op_name = (state.op_name
               or (state.op_identity.spec.name if state.op_identity else "op"))
    debug_dir = ws.dir / "artifacts" / "debug" / op_name
    debug_dir.mkdir(parents=True, exist_ok=True)
    (debug_dir / "last_deploy.json").write_text(json.dumps({
        "run_package": "/pkg/gelu.run", "wheel_package": "/pkg/gelu.whl",
        "ld_library_path_add": "/opp/lib", "smoke_passed": smoke_passed,
        "install_path": "/opp/gelu", "python_path": "/py/gelu",
    }))
    return state.with_updates(_workspace=ws)


@contextmanager
def _patch_deploy(smoke_passed=True, run_package="/pkg/gelu.run",
                  build_fail=False, resolve_fail=False):
    """Mock Deployer.compile + install_and_smoke for codegen transition tests.

    方案 2 (L4 改动 2)：codegen transition 走 compile() → install_and_smoke()（不再走
    deploy 全链）。compile 失败（resolve_fail/build_fail）→ 返回 err；compile 过 →
    install_and_smoke 决定 smoke 结果。deploy mock 保留（其它仍走全链的调用方测试用）。
    Pair with _attach_passing_deploy (attaches the workspace _persist_sources needs).

    Modes: smoke_passed=True (done) / smoke_passed=False (compile OK but smoke
    failed → D4) / build_fail=True (compile failed → build-retry respawn) /
    resolve_fail=True (unfixable → halt)."""
    from ascendc_devkit.orchestration.stages.deploy import Deployer
    # —— compile 结果：resolve/build 失败在 compile 阶段暴露；否则产物成功 ——
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
            DeployResult(run_package=run_package, wheel_package="/pkg/gelu.whl",
                         smoke_passed=False),
            None)
    # —— install_and_smoke 结果：compile 失败时不会走到；否则决定 smoke ——
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
                             install_path="/opp/gelu", python_path="/py/gelu"),
                None)
    with mock.patch.object(Deployer, "compile",
                           side_effect=_compile) as mc, \
         mock.patch.object(Deployer, "install_and_smoke",
                           side_effect=_install_and_smoke) as mis:
        yield (mc, mis)


class TestContractNoSpin:
    """Task 6.1: one transition satisfies each stage's output contract."""

    def test_codegen_no_spin(self, tmp_path):
        op = _op_identity(tmp_path)
        op.op_dir.mkdir(parents=True)
        (op.op_dir / "gelu.cpp").write_text("// k\n", encoding="utf-8")
        stage = CodegenStage()
        state = _attach_passing_deploy(
            State(mode="new", op_identity=op,
                  kernel_architecture={"kernel_code": {"files": ["gelu.cpp"]}}),
            tmp_path)
        result = {"agent_result": AgentResult(
            agent_name="ascendc-coder", status="ok",
            artifacts={"op_kernel/gelu.cpp": "// k\n"})}
        with _patch_deploy(smoke_passed=True):
            new_state = stage.transition(state, result)
        assert new_state.has_all(stage.output_contract().provides)
        assert new_state.codegen_iterations == 1  # advanced, not stuck

    def test_perf_no_spin(self, tmp_path):
        op = _op_identity(tmp_path)
        stage = PerfStage()
        state = State(mode="new", op_identity=op,
                      requirement=Requirement(op_spec=OperatorSpec(name="gelu")))
        new_state = stage.transition(state, {
            "gate_result": {"gate": "performance", "passed": True,
                            "metrics": {"actual_ms": 1.0, "baseline_ms": 2.0}}})
        assert new_state.has_all(stage.output_contract().provides)
        assert new_state.perf_iterations == 1

    def test_integrate_no_spin(self, tmp_path):
        op = _op_identity(tmp_path)
        op.op_dir.mkdir(parents=True)
        (op.op_dir / "gelu.cpp").write_text("// k\n", encoding="utf-8")
        profile = RepositoryProfile(name="omni-ops")
        stage = IntegrateStage()
        state = State(mode="new", op_identity=op, profile=profile,
                      adapter=GenericRepositoryAdapter(profile))
        new_state = stage.transition(state, {})
        assert new_state.has_all(stage.output_contract().provides)
        assert new_state.integration_result["status"] == "ok"


class TestRequiresPinned:
    """Task 6.1 Step 2: requires归位 pinned by assertions."""

    def test_integrate_requires(self):
        c = IntegrateStage().input_contract()
        assert "generated_sources" not in c.requires
        assert "change_set" not in c.optional and "change_set" not in c.requires
        assert "op_identity" in c.requires

# __APPEND_E2E__

from ascendc_devkit.capabilities.agent.backend import AgentBackend


class _WritingStubBackend(AgentBackend):
    """Stub agent that writes files into its working_dir (op_dir) and reports
    them as artifacts — simulates a real agent's in-repo Write under Plan-A.
    """

    def __init__(self, files: dict[str, str]):
        self._files = files
        self.spawn_calls: list[dict] = []

    def spawn(self, agent_name, prompt, context, skills=None,
              model=None, working_dir=None, repo_baseline=None, repo_root=None,
              stage_name="", branch_label="", resume_session_id=None, resume_prompt=None, primary_skill=None, deadline_monotonic: float | None = None):
        self.spawn_calls.append({
            "agent_name": agent_name, "working_dir": working_dir,
            "repo_baseline": repo_baseline, "repo_root": repo_root,
        })
        artifacts = {}
        if working_dir:
            wd = Path(working_dir)
            wd.mkdir(parents=True, exist_ok=True)
            for rel, content in self._files.items():
                fpath = wd / rel
                fpath.parent.mkdir(parents=True, exist_ok=True)
                fpath.write_text(content, encoding="utf-8")
                artifacts[rel] = content
        return AgentResult(agent_name=agent_name, status="ok", artifacts=artifacts)


def _init_git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    def g(*a):
        subprocess.run(["git", "-C", str(repo), *a], capture_output=True, check=True)
    g("init", "-q")
    g("config", "user.email", "t@e.com")
    g("config", "user.name", "T")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    g("add", "-A")
    g("commit", "-q", "-m", "init")
    return repo


@pytest.mark.skipif(not _has_git(), reason="git not installed")
class TestInRepoChainSmoke:
    """Task 6.2: linear chain over a tmp git repo, code lands in op_dir."""

    def _profile(self):
        return RepositoryProfile(name="omni-ops")

    def test_codegen_writes_into_op_dir_with_baseline(self, tmp_path):
        from ascendc_devkit.orchestration.kernel.runner import Runner
        from ascendc_devkit.infra.repo_guard import RepoGuard
        repo = _init_git_repo(tmp_path)
        op = _op_identity(repo)
        baseline = RepoGuard().create_baseline(repo, op.op_dir)
        # P3: writing stub writes files with op_host/op_kernel prefixes
        # to match codegen's _expected_code_files (which reads kernel_architecture
        # and qualifies each file with its canonical directory).
        backend = _WritingStubBackend({"op_kernel/gelu.cpp": "// kernel\n",
                                       "op_host/gelu_tiling.h": "// tiling\n"})
        runner = Runner(agent_backend=backend)
        state = _attach_passing_deploy(State(
            mode="new", op_identity=op, target_repo_baseline_ref=baseline,
            design_spec={"inputs": [{"name": "x"}], "outputs": [{"name": "y"}]},
            kernel_architecture={"host_code": {"files": ["gelu_tiling.h"]},
                                 "kernel_code": {"files": ["gelu.cpp"]}}),
            tmp_path)
        with _patch_deploy(smoke_passed=True):
            new_state = runner.run_stage(state, CodegenStage())
        # cwd was op_dir; baseline + repo_root threaded to the agent.
        call = backend.spawn_calls[0]
        assert Path(call["working_dir"]) == op.op_dir
        assert call["repo_baseline"] == baseline
        assert Path(call["repo_root"]) == repo
        # Files actually landed in the repo's op_dir with canonical prefixes.
        assert (op.op_dir / "op_kernel/gelu.cpp").is_file()
        assert new_state.last_error is None
        assert "op_kernel/gelu.cpp" in (new_state.generated_sources or {})


@pytest.mark.skipif(not _has_git(), reason="git not installed")
class TestFailureRollbackAndAbort:
    """Task 6.2 Steps 2-3: hard-failure rollback vs abort-preserve over git."""

    def test_hard_failure_rollback_cleans_op_dir(self, tmp_path):
        from ascendc_devkit.application import dispatcher as disp
        from ascendc_devkit.infra.repo_guard import RepoGuard
        repo = _init_git_repo(tmp_path)
        op = _op_identity(repo)
        guard = RepoGuard()
        baseline = guard.create_baseline(repo, op.op_dir)
        # Half-baked files written this run.
        op.op_dir.mkdir(parents=True)
        (op.op_dir / "gelu.cpp").write_text("BROKEN\n", encoding="utf-8")
        profile = RepositoryProfile(name="omni-ops")
        state = State(mode="new", op_identity=op, profile=profile,
                      adapter=GenericRepositoryAdapter(profile),
                      target_repo_baseline_ref=baseline)
        disp._rollback_repo_if_needed(state)
        # op_dir restored to clean baseline (untracked half-bake removed).
        assert not (op.op_dir / "gelu.cpp").exists()
        assert guard.is_clean(repo, op.op_dir)

    def test_abort_preserves_changes(self, tmp_path):
        from ascendc_devkit.application import dispatcher as disp
        from ascendc_devkit.infra.repo_guard import RepoGuard
        repo = _init_git_repo(tmp_path)
        op = _op_identity(repo)
        baseline = RepoGuard().create_baseline(repo, op.op_dir)
        op.op_dir.mkdir(parents=True)
        (op.op_dir / "gelu.cpp").write_text("wip\n", encoding="utf-8")
        profile = RepositoryProfile(name="omni-ops")
        state = State(mode="new", op_identity=op, profile=profile,
                      target_repo_baseline_ref=baseline)
        # Abort path must NOT delete changes (git_safety).
        disp._preserve_repo_with_hint(state)
        assert (op.op_dir / "gelu.cpp").exists()
        assert (op.op_dir / "gelu.cpp").read_text(encoding="utf-8") == "wip\n"


class TestCodegenDirectoryOrganization:
    """P3+P4: CodegenStage file placement and staging isolation."""

    @staticmethod
    def _codegen_state_with_arch():
        """State with kernel_architecture that declares section directories (P2 section-level, no files[])."""
        from ascendc_devkit.orchestration.stages.codegen import CodegenStage
        from ascendc_devkit.domain.repository import RepositoryProfile
        profile = RepositoryProfile(name="ops-transformer")
        return State(
            mode="new",
            # P2: kernel_architecture is section-level — only directory, no files[]
            kernel_architecture={
                "host_code": {"directory": "op_host"},
                "kernel_code": {"directory": "op_kernel"},
            },
            design_spec={"op_name": "rotary", "inputs": [{"name": "x"}], "outputs": [{"name": "y"}]},
            tiling_strategy={"approach": "multi_core"},
            profile=profile,
        ), CodegenStage

    def test_expected_files_return_section_directories(self):
        """P2: _expected_code_files returns section directory names, not file paths."""
        state, stage_cls = self._codegen_state_with_arch()
        stage = stage_cls()
        dirs = stage._expected_code_files(state)
        assert "op_host" in dirs, f"Expected op_host section, got: {dirs}"
        assert "op_kernel" in dirs
        # Section-level: directories, not individual file paths
        assert all("/" not in d for d in dirs), f"Should be directories, got: {dirs}"

    def test_expected_files_default_when_no_directory_field(self):
        """P2: without 'directory' field, defaults to op_host/op_kernel."""
        from ascendc_devkit.orchestration.kernel.state import State as S
        state = S(
            mode="new",
            kernel_architecture={"host_code": {}, "kernel_code": {}},
            design_spec={"op_name": "x", "inputs": [{"name": "x"}], "outputs": [{"name": "y"}]},
            tiling_strategy={"approach": "single"},
        )
        stage = CodegenStage()
        dirs = stage._expected_code_files(state)
        assert "op_host" in dirs
        assert "op_kernel" in dirs

    def test_design_inputs_not_materialized_to_op_dir(self, tmp_path):
        """P4: _materialize_inputs writes to staging, not op_dir."""
        import json
        from ascendc_devkit.orchestration.stages.codegen import CodegenStage

        op_dir = tmp_path / "op_dir"
        op_dir.mkdir()
        staging_dir = tmp_path / "staging"
        staging_dir.mkdir(parents=True)

        state = State(
            mode="new",
            kernel_architecture={"host_code": {}, "kernel_code": {}},
            design_spec={"op_name": "rotary", "inputs": [{"name": "x"}], "outputs": [{"name": "y"}]},
            tiling_strategy={"approach": "multi_core"},
        )

        stage = CodegenStage()
        stage._materialize_inputs(state, staging_dir)

        # JSONs should land in staging, not op_dir
        assert (staging_dir / "design_spec.json").exists()
        assert (staging_dir / "tiling_strategy.json").exists()
        assert (staging_dir / "kernel_architecture.json").exists()
        assert not list(op_dir.glob("*.json")), "op_dir must not contain design JSONs"
