"""Tests for NPURunner and ops-nn repository integration.

Markers:
    @pytest.mark.npu  — requires real NPU hardware (torch_npu + device)
"""

from pathlib import Path
import tempfile

import pytest

from ascendc_devkit.domain.operator import OperatorSpec
from ascendc_devkit.domain.requirement import TestCase
from ascendc_devkit.adapters.npu.runner import NPURunner
from ascendc_devkit.adapters.npu.detect import detect_chip_version

from tests._testrepos import resolve_test_repo, repo_skip_reason


def _has_npu() -> bool:
    """Return True when torch_npu is importable AND a device is present."""
    try:
        import torch_npu  # noqa: F401
        return bool(torch_npu.npu.device_count())
    except Exception:
        return False


class TestNPURunnerStubMode:
    """P1: NPURunner is a pure executor — no stub fallback. NPU unavailable
    raises EnvironmentNotAvailableError (honest error, never a stubbed
    max_diff=0). PrecisionGate was deleted (P57); precision now runs via
    run-cases in the precision_debug agent, calling NPURunner.execute."""

    def test_runner_is_pure_executor_no_stub(self):
        """P1: NPURunner no longer accepts enable_stubbed or has stub fallback."""
        runner = NPURunner(chip_version="A2")
        assert not hasattr(runner, "_enable_stubbed"), "enable_stubbed removed from runner"
        assert not hasattr(runner, "_stub_execute"), "_stub_execute removed from runner"
        assert "_torch_npu_available" in dir(runner), "environment detection still present"

    def test_raises_when_npu_unavailable(self):
        """P1: NPURunner.execute() always raises when NPU unavailable, no fallback."""
        from ascendc_devkit.domain.exceptions import EnvironmentNotAvailableError

        runner = NPURunner(chip_version="A2")
        runner._torch_npu_available = False

        with pytest.raises(EnvironmentNotAvailableError, match="torch_npu"):
            runner.execute(OperatorSpec(name="test"), [], npu_id=0)


@pytest.mark.external_repo("cann-bench")
class TestNPURunnerRealExecution:
    """Real-kernel precision guard (@pytest.mark.npu). P7/G7.

    These evolve from the old gelu-based tests that only exercised a CPU
    golden-self-compare stub (max_diff always 0). They now deploy the real
    `add` operator and run the REAL kernel on NPU, comparing against a golden:
      - correct golden (a+b) → max_diff ≈ 0 → passed
      - wrong golden   (a-b) → large max_diff → NOT passed
    proving the precision check is real, not a stub.
    """

    CANN_BENCH = resolve_test_repo("ASCENDC_TEST_CANN_BENCH", "cann-bench")
    _ADD_GOLDEN = str(Path(__file__).parent.parent / "fixtures" / "add_golden.py")
    _ADD_GOLDEN_WRONG = str(Path(__file__).parent.parent / "fixtures" / "add_golden_wrong.py")
    _ADD_GOLDEN_TORCH = str(Path(__file__).parent.parent / "fixtures" / "add_golden_torch.py")
    _ADD_GOLDEN_GETINPUT_SCALAR = str(
        Path(__file__).parent.parent / "fixtures" / "add_golden_getinput_scalar.py")
    _CALLABLE = {"kind": "torch_op", "symbol": "torch.ops.cann_bench.add"}

    @pytest.fixture(scope="class")
    @classmethod
    def deployed_add(cls, request):
        """Deploy the real `add` operator via the profile-driven Deployer.

        Returns the DeployResult so precision tests can call the real kernel.
        Skips (not fails) when the cann-bench repo is absent — the deploy path
        itself is exercised by test_self_evolution_stages; this fixture is only
        the vehicle for the NPU precision guard. (P57: deploy is no longer a
        stage; the codegen agent calls Deployer.deploy in-session — here we call
        it directly to stage a real kernel for the precision guard.)

        Chip target is detect_chip_version(), not a hardcoded literal: a real-
        kernel guard must build+run on whatever hardware it actually executes
        on. Hardcoding "A5" builds an ascend950 binary that won't run on A2
        hardware (and vice-versa) — exactly the mismatch this guard exists to
        keep honest.
        """
        if not _has_npu():
            pytest.skip("torch_npu not available (no NPU hardware)")
        if cls.CANN_BENCH is None:
            pytest.skip(repo_skip_reason("cann-bench", "ASCENDC_TEST_CANN_BENCH"))
        from ascendc_devkit.orchestration.stages.deploy import Deployer
        from ascendc_devkit.orchestration.kernel.state import State
        from ascendc_devkit.adapters.repository.profile_loader import ProfileLoader

        op_dir = cls.CANN_BENCH / "examples/aclnn_launch_example/csrc/ops/add"
        # add is binary (x1+x2). The real-call smoke drives fn() from
        # state.test_cases[0] (the same hand-off test_design uses to feed codegen
        # in the real pipeline — no synthetic fallback). Stage a legal 2-tensor
        # case so the probe calls add(x1, x2), not add(x1) (which would raise
        # "missing x2" and skip every precision test for a non-defect reason).
        from ascendc_devkit.domain.requirement import TestCase
        from ascendc_devkit.infra.workspace import Workspace
        # _workspace is non-serialized and attached by dispatcher/CLI in real
        # entry points. This fixture bypasses those and stages State directly,
        # so it must attach a workspace itself — otherwise Deployer._resolve
        # fails with a resolve error (direct-caller contract, see deploy.py).
        # The workspace root must be an EXECUTABLE path: deploy's smoke dlopens
        # the built .so's, so a noexec mount (e.g. /tmp) fails every lib with
        # "failed to map segment from shared object". output/ is the real run
        # root (gitignored, executable) — mirror real runs; Workspace.create
        # mkdirs it when absent, so a fresh checkout (no output/ yet) still works.
        output_root = Path(__file__).resolve().parent.parent.parent / "output"
        deploy_ws = Workspace.create(
            output_root=str(output_root),
            run_id=f"st-npu-{Path(tempfile.mkdtemp()).name}",
        )
        state = State.empty().with_updates(
            non_interactive=True, op_name="add", repo_root=cls.CANN_BENCH,
            op_dir=op_dir,
            rel_op_dir="examples/aclnn_launch_example/csrc/ops/add",
            full_op_name="add", design_target_chip=detect_chip_version(),
            # runtime_target_chip mirrors what dispatch (Step 3 probe authority)
            # threads into state in the real pipeline. This fixture bypasses
            # dispatch and constructs State directly, so it must set the runtime
            # chip itself — otherwise the deploy chip-gate (chip_mismatch_reason,
            # a PURE gate since step-34: no probe here) sees runtime="" → "未解析"
            # → smoke fails → every real-NPU kernel-vs-golden test silently skips.
            runtime_target_chip=detect_chip_version(),
            profile=ProfileLoader.load("cann-bench"),
            test_cases=[TestCase(name="add_smoke", inputs=[
                {"shape": [1024], "dtype": "fp16"},
                {"shape": [1024], "dtype": "fp16"}])],
            codegen_manifest={
                "op_name": "add", "inputs": [], "outputs": [],
                "callable_target": cls._CALLABLE,
            },
            # per-op isolation (02 D plan) lands in deploy_ws.artifacts/per-op/
            # (see deploy.py _per_op_path).
            _workspace=deploy_ws,
        )
        dr, err = Deployer().deploy(state)
        if not dr.smoke_passed:
            # Surface the REAL failure at the skip boundary (§3.4/§3.7): the
            # actual stderr (compile error, missing pkg, etc.) lives in
            # err.details["stderr_tail"], while .message is only a generic
            # "deploy step '<step>' failed". Dropping the stderr once cost a
            # long manual re-run of build.sh to discover a stale ASCEND_TOOLKIT_HOME
            # (see docs/plan/chip-version-generation/01-problems.md P6). Include
            # the stderr tail so the next reader sees the cause without re-running.
            msg = err.message if err else "unknown"
            stderr = (err.details.get("stderr_tail", "") if err and err.details else "").strip()
            tail = f"\n--- deploy stderr (tail) ---\n{stderr}" if stderr else ""
            pytest.skip(f"add deploy did not smoke-pass: {msg}{tail}")
        return dr

    @pytest.mark.npu
    @pytest.mark.slow
    def test_real_kernel_correct_golden_passes(self, deployed_add):
        """add kernel vs correct (a+b) golden → max_diff ≈ 0, passed."""
        runner = NPURunner(chip_version=detect_chip_version())
        op = OperatorSpec(name="add")
        test_cases = [TestCase(
            name="basic",
            inputs=[{"name": "a", "shape": [8], "dtype": "fp16"},
                    {"name": "b", "shape": [8], "dtype": "fp16"}],
        )]
        result = runner.execute(
            op, test_cases, npu_id=0,
            golden_contract={"path": self._ADD_GOLDEN, "entry": "reference", "input_type": "numpy"},
            deploy_result=deployed_add, callable_target=self._CALLABLE,
        )
        assert result["passed"] is True, f"max_diff={result['max_diff']}"
        assert result["max_diff"] < 1e-2
        assert result["bottleneck"] == "real_kernel_vs_golden"
        assert "stubbed" not in result

    @pytest.mark.npu
    @pytest.mark.slow
    def test_real_kernel_wrong_golden_fails(self, deployed_add):
        """add kernel vs wrong (a-b) golden → large max_diff, NOT passed.

        This is the core P7 guard: it proves precision is real, not a stub that
        always reports max_diff=0.
        """
        runner = NPURunner(chip_version=detect_chip_version())
        op = OperatorSpec(name="add")
        test_cases = [TestCase(
            name="basic",
            inputs=[{"name": "a", "shape": [8], "dtype": "fp16"},
                    {"name": "b", "shape": [8], "dtype": "fp16"}],
        )]
        result = runner.execute(
            op, test_cases, npu_id=0,
            golden_contract={"path": self._ADD_GOLDEN_WRONG, "entry": "reference", "input_type": "numpy"},
            deploy_result=deployed_add, callable_target=self._CALLABLE,
        )
        assert result["passed"] is False
        assert result["max_diff"] > 1e-2, "wrong golden must produce a real diff"

    @pytest.mark.npu
    @pytest.mark.slow
    def test_real_kernel_golden_contract_torch(self, deployed_add):
        """A4 golden-adapter on real NPU: a torch golden (cann-bench-style
        contract — entry=add by name, input_type=torch) loads, the harness
        converts numpy→torch, and the real kernel is diffed against it.

        No cann-bench op except add/sqrt is pre-built, and neither has a
        cann-bench task/golden; this torch add golden mirrors the cann-bench
        contract so the adapter's torch path + entry-by-name resolution is
        exercised on real hardware (the run/compute fallback is gone — the entry
        is declared, not guessed).
        """
        runner = NPURunner(chip_version=detect_chip_version())
        op = OperatorSpec(name="add")
        test_cases = [TestCase(
            name="basic",
            inputs=[{"name": "a", "shape": [8], "dtype": "fp16"},
                    {"name": "b", "shape": [8], "dtype": "fp16"}],
        )]
        result = runner.execute(
            op, test_cases, npu_id=0,
            golden_contract={
                "path": self._ADD_GOLDEN_TORCH, "entry": "add", "input_type": "torch"},
            deploy_result=deployed_add, callable_target=self._CALLABLE,
        )
        assert result["passed"] is True, f"max_diff={result['max_diff']}"
        assert result["max_diff"] < 1e-2
        assert result["bottleneck"] == "real_kernel_vs_golden"

    @pytest.mark.npu
    @pytest.mark.slow
    def test_real_kernel_golden_contract_torch_native_cpu(self, deployed_add):
        """M3 (review 坐实，真实链路 ST): golden_precision=native_cpu 时权威 golden
        必须是 native（cann-bench 语义：保持原始精度、直接复用 Golden 输出，不升
        fp64）。渲染断言只验结构门控，本条真实跑 harness 证明 native_cpu 分支在
        真机上判定仍正确（fp16 add：native 参考与 kernel 同精度，diff 应极小）。"""
        runner = NPURunner(chip_version=detect_chip_version())
        op = OperatorSpec(name="add")
        test_cases = [TestCase(
            name="basic",
            inputs=[{"name": "a", "shape": [8], "dtype": "fp16"},
                    {"name": "b", "shape": [8], "dtype": "fp16"}],
        )]
        result = runner.execute(
            op, test_cases, npu_id=0,
            golden_contract={
                "path": self._ADD_GOLDEN_TORCH, "entry": "add", "input_type": "torch",
                "precision": "native_cpu",
            },
            deploy_result=deployed_add, callable_target=self._CALLABLE,
        )
        assert result["passed"] is True, f"max_diff={result['max_diff']}"
        assert result["max_diff"] < 1e-2
        assert result["bottleneck"] == "real_kernel_vs_golden"

    @pytest.mark.npu
    @pytest.mark.slow
    def test_harness_imports_per_op_cann_bench_not_site_packages(self, deployed_add, tmp_path):
        """Q8: the harness bakes ``sys.path.insert(0, per_op_python_dir)`` so the
        ``__import__('cann_bench')`` resolves to the per-op DEPLOYED package, NOT
        a stale global site-packages install. site-packages cann_bench (a
        cann-bench repo standard-op build — add/sqrt/moe_re_routing only) lacks
        target ops like scatter/advance_step_v2; landing there was the root cause
        of batch ``20260727_225324`` scatter "not registered" misjudgment.

        Why a real-NPU ST (§3.9): the snapshot UT pins the harness *source*
        contains ``sys.path.insert``, but only a real run proves *which package
        actually won the import*. The harness probe prints
        ``[harness] cann_bench.__file__ = <path>`` to stdout, which execute()
        dumps to ``<log_dir>/run.log``. With ``add`` (present in both per-op and
        site-packages), only this probe distinguishes the winner — so this is the
        unique regression signal for the Q8 fix. Not heavy_llm (no LLM in the
        path — deploy + subprocess run, §3.5 marker = runtime dependency).
        """
        runner = NPURunner(chip_version=detect_chip_version())
        op = OperatorSpec(name="add")
        test_cases = [TestCase(
            name="basic",
            inputs=[{"name": "a", "shape": [8], "dtype": "fp16"},
                    {"name": "b", "shape": [8], "dtype": "fp16"}],
        )]
        runner.execute(
            op, test_cases, npu_id=0,
            golden_contract={"path": self._ADD_GOLDEN, "entry": "reference",
                             "input_type": "numpy"},
            deploy_result=deployed_add, callable_target=self._CALLABLE,
            log_dir=str(tmp_path),
        )
        run_log = (tmp_path / "run.log").read_text(encoding="utf-8")
        assert "[harness] cann_bench.__file__" in run_log, (
            "harness import-path probe missing from run.log — the Q8 probe did "
            "not fire / was not captured. run.log:\n" + run_log)
        probe_line = next(l for l in run_log.splitlines()
                          if "[harness] cann_bench.__file__" in l)
        per_op_dir = deployed_add.python_path
        assert per_op_dir and per_op_dir in probe_line, (
            f"harness imported cann_bench from OUTSIDE the per-op deploy dir — "
            f"sys.path.insert(0, per_op_python_dir) did NOT win (Q8 regression). "
            f"probe={probe_line!r}, expected per-op dir={per_op_dir!r}")
        assert "site-packages" not in probe_line, (
            f"harness fell back to a global site-packages cann_bench — {probe_line!r}")

    @pytest.mark.npu
    @pytest.mark.slow
    def test_real_kernel_get_input_returning_scalar_does_not_crash(self, deployed_add):
        """Regression (scatter_pa_kv_cache, run 20260801-231442-99db86): a golden's
        get_input that appends a scalar to its return tuple (cache_mode str) must
        NOT crash the harness. Pre-fix, _run_kernel's blind npu-move raised
        ``'str' object has no attribute 'npu'`` on every case → scope_guard
        mis-halted it as upstream(golden). _apply_get_input must drop the scalar
        so the kernel receives only tensors.

        Why a real-NPU ST (§3.9): the UT pins _apply_get_input's filter with a
        sentinel torch, but only a real harness run proves the rendered harness
        + real kernel survive the scalar and produce a numerical diff. ``add``
        is the vehicle (cann-bench pre-built); scatter_pa_kv_cache is the
        real-world origin of the get_input shape, not the classification anchor
        (§1.12). The scalar is dropped (kernel gets 2 tensors) and the golden is
        correct (a+b) → passed.
        """
        runner = NPURunner(chip_version=detect_chip_version())
        op = OperatorSpec(name="add")
        test_cases = [TestCase(
            name="basic",
            inputs=[{"name": "a", "shape": [8], "dtype": "fp16"},
                    {"name": "b", "shape": [8], "dtype": "fp16"}],
        )]
        result = runner.execute(
            op, test_cases, npu_id=0,
            golden_contract={"path": self._ADD_GOLDEN_GETINPUT_SCALAR,
                             "entry": "reference", "input_type": "numpy"},
            deploy_result=deployed_add, callable_target=self._CALLABLE,
        )
        assert result["passed"] is True, (
            f"get_input returning a trailing scalar must not crash the harness — "
            f"passed={result['passed']}, max_diff={result.get('max_diff')!r}. "
            f"scatter_pa_kv_cache regression: _apply_get_input must drop the "
            f"scalar so _run_kernel never npu-moves it (pre-fix: "
            f"'str' object has no attribute 'npu').")
        assert result["max_diff"] < 1e-2


class TestOpsNNRepositoryIntegration:
    """Integration tests using the real ops-nn repository structure."""

    OPS_NN_ROOT = resolve_test_repo("ASCENDC_TEST_OPS_NN", "ops-nn")

    def test_profile_matches_real_repo_structure(self):
        """ops-nn profile: no prefix, single default variant matching any op_dir."""
        from ascendc_devkit.adapters.repository.profile_loader import ProfileLoader

        profile = ProfileLoader.load("ops-nn")
        assert profile.name == "ops-nn"
        assert profile.op_naming.prefix == ""
        v = profile.select_variant("activation/fast_gelu")
        assert v is not None and v.name == "default"

    @pytest.mark.external_repo("ops-nn")
    def test_scan_real_operator_in_ops_nn(self):
        """Scan fast_gelu from ops-nn repo via GenericRepositoryAdapter."""
        from ascendc_devkit.adapters.repository.generic import GenericRepositoryAdapter
        from ascendc_devkit.adapters.repository.profile_loader import ProfileLoader

        if self.OPS_NN_ROOT is None:
            pytest.skip(repo_skip_reason("ops-nn", "ASCENDC_TEST_OPS_NN"))

        profile = ProfileLoader.load("ops-nn")
        adapter = GenericRepositoryAdapter(profile)

        repo_root = self.OPS_NN_ROOT
        op_dir = repo_root / "activation" / "fast_gelu"
        assert op_dir.is_dir(), f"fast_gelu not found at {op_dir}"

        result = adapter.scan_existing_operator(
            repo_root, "fast_gelu", op_dir=op_dir,
        )
        assert result.spec.name == "fast_gelu"
        assert result.op_dir == op_dir
        assert len(result.files) >= 4, f"Expected 4+ files, got: {result.files}"

        # Files should be keyed by relative path from op_dir
        file_names = [str(f) for f in result.files]
        assert any("op_host" in fn for fn in file_names), f"No op_host files in {file_names}"
        assert any("op_kernel" in fn for fn in file_names), f"No op_kernel files in {file_names}"

    @pytest.mark.external_repo("ops-nn")
    def test_list_real_operators_in_activation_category(self):
        """Activation/ directory contains 5+ operators with op_kernel/op_host."""
        if self.OPS_NN_ROOT is None:
            pytest.skip(repo_skip_reason("ops-nn", "ASCENDC_TEST_OPS_NN"))

        repo_root = self.OPS_NN_ROOT
        activation_dir = repo_root / "activation"
        assert activation_dir.is_dir(), f"activation/ not found at {repo_root}"

        ops = []
        for entry in sorted(activation_dir.iterdir()):
            if entry.is_dir():
                has_kernel = (entry / "op_kernel").is_dir()
                has_host = (entry / "op_host").is_dir()
                if has_kernel or has_host:
                    ops.append(entry.name)

        assert len(ops) >= 5, f"Expected 5+ operators, got {len(ops)}"
        assert "fast_gelu" in ops


@pytest.mark.npu
class TestOpCardPinRealChain:
    """P13/step-116 — op 卡 pin 的真实链路守护（@npu，秒级探针非全流程）。

    两个方向都守护，防探针「常绿」：
      - 正向：真实机器/驱动/CANN 上 verify_pin(非 0 卡) 通过——pin env 组装
        确实让子进程只见一张卡（remap 语义的持续回归锚）；
      - 负向：故意破坏 pin 组装（env 不注入）→ 探针必须报
        EnvironmentNotAvailableError——证明探针在真实运行时上真的会检测，
        而非对任何环境都返回通过。
    """

    def test_verify_pin_passes_on_nonzero_card(self):
        from ascendc_devkit.adapters.npu.card_pin import verify_pin
        # 非零卡：pin 失效（env 未传播/被忽略）时 device_count==8 → 必炸。
        # device_count 探测不分配设备内存，卡被他人占用亦可安全执行。
        verify_pin(3)

    def test_verify_pin_catches_broken_pin_on_real_runtime(self, monkeypatch):
        from ascendc_devkit.adapters.npu import card_pin as cp
        from ascendc_devkit.domain.exceptions import EnvironmentNotAvailableError
        # 破坏注入：pin env 为空 → 子进程看到全部 8 卡 → 断言 n==1 失败。
        monkeypatch.setattr(cp, "card_pin_env", lambda card: {})
        with pytest.raises(EnvironmentNotAvailableError):
            cp.verify_pin(3)
