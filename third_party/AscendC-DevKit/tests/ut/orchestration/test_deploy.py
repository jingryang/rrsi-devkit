"""UT for Deployer — guards the command_template render contract.

The NPU real-machine cases (tests/st/test_npu.py) once went 4×skip with
``deploy step 'build' failed``: step-17 changed profile command_template from
``{chip_version}`` to ``{soc_version}``, but the deploy chain's tvars dict was
not updated in lockstep, so ``str.format`` raised ``KeyError`` at render time
and the whole build role aborted. There was no UT covering this path — the only
deploy coverage exercised the display-only ``build_commands`` path, which never
renders against tvars. These tests pin the producer (``Deployer._template_vars``)
and the render boundary (``Deployer._run_command``) so a placeholder/tvars drift
can't slip through ST-only again (§3.1 TDD, §1.2 可扩展尺子).

P54 D3: deploy 链抽到 ``Deployer``（§2.5 单一通路）后，本文件改测 ``Deployer``；
mock 路径 ``deploy.subprocess.run`` 不变（subprocess 仍在 deploy 模块导入）。
"""

from pathlib import Path
from unittest import mock

import pytest

from ascendc_devkit.domain.repository import BuildStage, BuildVariant
from ascendc_devkit.domain.verification import DeployResult
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.stages.deploy import Deployer, _ResolvedInputs


def _state_with_chip(chip: str) -> State:
    # step-34: set both dual fields (design==runtime → match state).
    return State.empty().with_updates(
        design_target_chip=chip, runtime_target_chip=chip)


class TestTemplateVars:
    """Producer contract: every placeholder a template may use has a value."""

    @pytest.mark.parametrize("chip,soc", [
        ("A2", "ascend910b"),
        ("A3", "ascend910_93"),
        ("A5", "ascend950"),
    ])
    def test_soc_version_translated_per_generation(self, chip, soc):
        tvars = Deployer._template_vars(
            _state_with_chip(chip), "add", "/opp/add", "/py/add"
        )
        assert tvars["soc_version"] == soc          # canonical → CANN translation
        assert tvars["chip_version"] == chip        # raw canonical preserved

    def test_passes_through_non_chip_vars(self):
        tvars = Deployer._template_vars(
            _state_with_chip("A5"), "add", "/opp/add", "/py/add"
        )
        assert tvars["full_op_name"] == "add"
        assert tvars["per_op_opp_dir"] == "/opp/add"
        assert tvars["per_op_python_dir"] == "/py/add"
        # run_pkg / whl_pkg are populated later by the chain (dist-artifact scan),
        # not by _template_vars — empty at render entry is the contract.
        assert tvars["run_pkg"] == ""
        assert tvars["whl_pkg"] == ""

    def test_empty_chip_leaves_soc_version_blank(self):
        # Unknown / unset chip → soc_version "" so the repo's build.sh auto-detects
        # (historical behaviour; not every repo mandates --soc).
        tvars = Deployer._template_vars(
            _state_with_chip(""), "add", "/opp/add", "/py/add"
        )
        assert tvars["soc_version"] == ""
        assert tvars["chip_version"] == ""

    def test_unknown_chip_leaves_soc_version_blank(self):
        tvars = Deployer._template_vars(
            _state_with_chip("not-a-generation"), "add", "/opp/add", "/py/add"
        )
        assert tvars["soc_version"] == ""

    def test_forward_compat_compiles_for_runtime_chip(self):
        # P65 dual source: design=A2 (Membase, drives code style), runtime=A5
        # (the box). Deploy compiles for the BOX, so soc_version/chip_version
        # come from runtime — the product builds for A5 even though the design
        # target is A2. This is the forward-compat validation mode.
        state = State.empty().with_updates(
            design_target_chip="A2", runtime_target_chip="A5")
        tvars = Deployer._template_vars(state, "add", "/opp/add", "/py/add")
        assert tvars["soc_version"] == "ascend950"   # runtime-driven
        assert tvars["chip_version"] == "A5"          # runtime-driven


class TestRunCommandRender:
    """Render boundary: template placeholders must resolve against tvars.

    This is exactly where the NPU-skip regression fired — ``{soc_version}`` in
    the template had no matching tvars key.
    """

    def _stage(self, template: str) -> BuildStage:
        return BuildStage(
            name="build", cwd=".", command_template=template, role="build"
        )

    def test_soc_version_flows_into_rendered_command(self, tmp_path):
        stage = self._stage("bash build.sh -c {soc_version}")
        tvars = Deployer._template_vars(
            _state_with_chip("A5"), "add", "/opp/add", "/py/add"
        )
        seen = {}

        def fake_run(cmd, **kwargs):
            seen["cmd"] = cmd
            r = mock.Mock(returncode=0, stderr="", stdout="")
            return r

        with mock.patch(
            "ascendc_devkit.orchestration.stages.deploy.subprocess.run",
            side_effect=fake_run,
        ):
            ok, err, _ = Deployer()._run_command(stage, tmp_path, tvars)

        assert ok is True
        assert seen["cmd"] == "bash build.sh -c ascend950"

    def test_missing_tvar_aborts_cleanly_not_silently(self, tmp_path):
        # Regression fingerprint: template declares {soc_version} but tvars lacks
        # it → _run_command must return False with a diagnostic, NOT raise or
        # silently no-op (§3.4 honest signal at the failure boundary).
        stage = self._stage("bash build.sh -c {soc_version}")
        tvars = {"full_op_name": "add"}  # missing soc_version on purpose
        ok, err, log_path = Deployer()._run_command(stage, tmp_path, tvars)
        assert ok is False
        assert "soc_version" in err
        assert "unknown template var" in err
        assert log_path is None  # render failure — no subprocess ran, nothing to persist


class TestRunCommandPersistsFullOutput:
    """P57-B (step-31 改动点 A): a failing subprocess must persist FULL
    stdout+stderr to ``<run>/subprocess/<role>_<stage>.log`` and surface the log
    path + a tail in the ErrorFeedback — instead of losing everything past the
    old ``stderr[:1500]`` / ``details["stderr"][:2000]`` truncation (the agent
    then had no concrete error to self-fix on)."""

    def _stage(self, template: str = "bash build.sh") -> BuildStage:
        return BuildStage(name="compile", cwd=".", command_template=template, role="build")

    def test_persists_full_stderr_beyond_1500_truncation(self, tmp_path):
        from ascendc_devkit.infra.workspace import Workspace

        ws = Workspace.create(str(tmp_path / "out"), run_id="r1")
        stage = self._stage()
        big_stderr = "ERR-line " + ("x" * 2000)  # >1500 — old [:1500] lost the tail

        def fake_run(cmd, **kwargs):
            return mock.Mock(returncode=1, stdout="build stdout line", stderr=big_stderr)

        with mock.patch(
            "ascendc_devkit.orchestration.stages.deploy.subprocess.run",
            side_effect=fake_run,
        ):
            ok, stderr, log_path = Deployer()._run_command(
                stage, tmp_path, {}, ws=ws)

        assert ok is False
        # full stderr surfaced in the return (no [:1500] loss)
        assert stderr == big_stderr
        # persisted under <run>/subprocess/ with FULL content (stderr + stdout)
        assert log_path is not None
        log = Path(log_path)
        assert log.parent == ws.subprocess_log
        assert log.exists()
        text = log.read_text(encoding="utf-8")
        assert big_stderr in text          # FULL stderr in the file
        assert "build stdout line" in text  # stdout captured too

    def test_no_workspace_returns_none_log_but_keeps_full_stderr(self, tmp_path):
        # best-effort persistence: without a workspace nothing is written, but
        # stderr is still returned in full (not silently truncated to [:1500]).
        stage = self._stage()
        big_stderr = "ERR-" + ("y" * 2000)

        def fake_run(cmd, **kwargs):
            return mock.Mock(returncode=1, stdout="", stderr=big_stderr)

        with mock.patch(
            "ascendc_devkit.orchestration.stages.deploy.subprocess.run",
            side_effect=fake_run,
        ):
            ok, stderr, log_path = Deployer()._run_command(stage, tmp_path, {})

        assert ok is False
        assert stderr == big_stderr
        assert log_path is None

    def test_err_carries_log_path_and_tail_not_truncated_slice(self):
        # _err details: structured {step, log, stderr_tail} — agent reads the log
        # for full output, stderr_tail is a quick peek. No legacy "stderr" key
        # (§1.4 clean rename; only consumer is debug.py which echoes the dict).
        big = "z" * 3000
        ef = Deployer._err("build", big, log_path="/run/subprocess/build_compile.log")
        assert ef.details["step"] == "build"
        assert ef.details["log"] == "/run/subprocess/build_compile.log"
        assert ef.details["stderr_tail"] == big[-2000:]
        assert "stderr" not in ef.details

    def test_err_without_log_keeps_stderr_tail(self):
        ef = Deployer._err("smoke", "short msg", log_path=None)
        assert ef.details["step"] == "smoke"
        assert ef.details["log"] == ""
        assert ef.details["stderr_tail"] == "short msg"


class TestRunCommandDetectsSwallowedKernelCompileFailure:
    """第5类隐患(Plan lovely-painting-aurora):cann-bench build_run.sh 的 ``||`` 把
    kernel 编译失败吞成 RC=0,旧逻辑在 RC=0 分支 ``return True, "", None`` 丢弃整个
    stdout(含 ``error: no matching function for call to 'Cast'``)。现在扫描 build role
    输出,命中 → 视为 build 失败,复用 RC≠0 通路(落盘 + 返回 False),让 codegen
    in-session 自修循环捕获(agent prompt 已指向 subprocess/*.log)。"""

    _KERNEL_FAIL_STDOUT = (
        "Op[CrossEntropyLoss] of index[0] compile failed, kernelName: CrossEntropyLoss_abc.h.\n"
        "/home/x/op_kernel/cross_entropy_loss.h:294:13: error: no matching function for call to 'Cast'\n"
        "WARNING: Kernel binary build may have errors, continuing with package creation...\n"
    )
    _CLEAN_STDOUT = (
        "Opc tool start working now, please wait for a moment.\n"
        "Built target cross_entropy_loss_api\n"
        "WARNING: Kernel binary build may have errors, continuing with package creation...\n"
    )

    def _stage(self, role: str = "build") -> BuildStage:
        return BuildStage(
            name="build", cwd=".", command_template="bash build.sh", role=role)

    def _patch_run(self, returncode: int, stdout: str, stderr: str = ""):
        return mock.patch(
            "ascendc_devkit.orchestration.stages.deploy.subprocess.run",
            return_value=mock.Mock(
                returncode=returncode, stdout=stdout, stderr=stderr),
        )

    def test_rc0_with_kernel_failure_returns_false_and_persists_full_log(
            self, tmp_path):
        from ascendc_devkit.infra.workspace import Workspace
        ws = Workspace.create(str(tmp_path / "out"), run_id="r1")
        stage = self._stage()
        with self._patch_run(0, self._KERNEL_FAIL_STDOUT):
            ok, stderr, log_path = Deployer()._run_command(
                stage, tmp_path, {}, ws=ws)
        # RC=0 被 ``||`` 吞,但扫描命中 → 视为 build 失败(不再是假阳性绿灯)
        assert ok is False
        assert "CrossEntropyLoss" in stderr       # summary 带 op 名
        assert "no matching function" in stderr   # summary 带编译器原文
        # 落盘全文供 agent in-session 自修读
        assert log_path is not None
        text = Path(log_path).read_text(encoding="utf-8")
        assert "no matching function for call to 'Cast'" in text

    def test_rc0_clean_build_still_returns_true(self, tmp_path):
        # 对照:RC=0 + 仅良性信号(WARNING/Opc start/Built target)→ 不误报
        stage = self._stage()
        with self._patch_run(0, self._CLEAN_STDOUT):
            ok, stderr, log_path = Deployer()._run_command(stage, tmp_path, {})
        assert ok is True
        assert stderr == ""
        assert log_path is None

    def test_rc0_kernel_failure_without_workspace_still_returns_false(
            self, tmp_path):
        # 无 ws 不落盘,但仍须返回 False(信号不丢)—— 与 RC≠0 无 ws 行为一致
        stage = self._stage()
        with self._patch_run(0, self._KERNEL_FAIL_STDOUT):
            ok, stderr, log_path = Deployer()._run_command(stage, tmp_path, {})
        assert ok is False
        assert "CrossEntropyLoss" in stderr
        assert log_path is None  # 无 ws,无法落盘

    def test_non_build_role_not_scanned(self, tmp_path):
        # install/smoke role 的输出不扫描(无 kernel 编译信号,避免误报+性能)
        stage = self._stage(role="install_runtime")
        with self._patch_run(0, self._KERNEL_FAIL_STDOUT):
            ok, stderr, log_path = Deployer()._run_command(stage, tmp_path, {})
        assert ok is True  # install role 不扫描,RC=0 → True(现有行为不变)
        assert stderr == ""


class TestCannBenchProfileBuildContract:
    """Resource-level guard: the REAL cann-bench profile must pass soc to
    build.sh via ``--soc=`` — not ``-c``, which build.sh silently ignores.

    The render-boundary tests above use inline-constructed stages, so nothing
    caught it when the profile itself drifted to the ignored ``-c`` form. With
    ``-c`` ignored, build.sh auto-detects the soc and the profile's
    ``default_chip`` is silently bypassed — on a mismatched box (e.g.
    default_chip=A5, hardware A2) that builds a binary that won't run, with no
    error at build time (§1.2 可诊断). Pinning ``--soc={soc_version}`` at the
    resource level makes that regression loud instead of silent.
    """

    def test_cann_bench_build_passes_soc_via_dash_dash_soc(self):
        from ascendc_devkit.adapters.repository.profile_loader import ProfileLoader

        profile = ProfileLoader.load("cann-bench")
        build_stages = [s for v in profile.build_variants
                        for s in v.stages if s.role == "build"]
        assert len(build_stages) == 1, "cann-bench expected exactly one build stage"
        template = build_stages[0].command_template
        # build.sh's arg parser handles only `--soc=*` and silently ignores `-c`;
        # the honored flag is what makes default_chip actually take effect.
        assert "--soc={soc_version}" in template, (
            f"cann-bench build must pass soc via --soc= (not -c, which build.sh "
            f"silently ignores → default_chip bypassed). Got: {template!r}"
        )


class TestChipGate:
    """Build gate (§1.9 三层对齐): the runtime hardware must support the design's
    programming model, else the deploy aborts with a chip-gate error (P65).

    Design may target a generation other than hardware — and that is often
    FINE: a low-gen Membase design (A2/A3) is forward-compatible with an A5 box
    (A5 runs Membase), so design=A2/runtime=A5 PASSES the gate and builds for
    the box. The ONLY hard block is an A5 (Regbase) design on A2/A3 (Membase-
    only) hardware: the compiled binary is hardware-coupled (CANN soc_version /
    VF instructions fixed at compile time) and genuinely cannot run. So
    ``Deployer.deploy()`` returns ``smoke_passed=False`` only for that
    incompatible case, rather than producing an unrunnable binary.
    ``detect_chip_version()`` returns the canonical A2/A3/A5 (fallback A2 on
    no-NPU), the same vocabulary as ``state.design_target_chip``.

    Option D (chip-gate precondition 专题): the PRIMARY gate is now a precondition
    in ``codegen.validate_inputs`` → ``PreconditionError`` (clean halt, codegen
    never spawns). ``Deployer.deploy()`` keeps a SECONDARY deep-defense check
    because deploy is reachable via the ``redeploy`` CLI / direct callers that
    BYPASS the pipeline (no ``codegen.validate_inputs``). Both share the single
    ``chip_mismatch_reason`` helper (§2.5: one compare + one concrete message).
    ``error_type="chip_mismatch"`` is halt-class (env generation mismatch, not
    codegen-fixable) and never conflated with ``deploy_failed`` (compile/smoke —
    fixable). Deployer is a service, not a Stage, so the halt-vs-loopback
    decision is the caller's.
    """

    def test_mismatch_aborts_with_chip_mismatch_error(self):
        """design=A5(Regbase), runtime=A2(Membase-only) → the hard block: deploy()
        returns smoke_passed=False with a halt-class chip_mismatch ErrorFeedback
        (no transition / no loopback), NOT a fixable deploy_failed. The gate is a
        pure matrix check against the dispatch-resolved runtime chip — no probe
        here (step-34)."""
        state = State.empty().with_updates(
            design_target_chip="A5", runtime_target_chip="A2")
        dr, err = Deployer().deploy(state)
        assert dr.smoke_passed is False
        assert err is not None
        # halt-class, distinct from fixable deploy_failed (§1.2 two-failure split)
        assert err.error_type == "chip_mismatch"
        assert err.details["design_target_chip"] == "A5"
        # Diagnosability: both values surface in the message so a reader sees the
        # mismatch without re-running (§1.2 可诊断). Single-sourced by the helper.
        assert "'A5'" in err.message
        assert "'A2'" in err.message

    def test_forward_compat_proceeds_past_gate(self):
        """P65: design=A2(Membase), runtime=A5 → forward-compatible (A5 runs
        Membase). The gate must NOT fire — deploy() advances past the chip gate
        and fails later (here at 'resolve' for the empty state), NOT with a
        chip_mismatch. This is the user's core validation mode (A2/A3 Membase
        codegen on the A5 box)."""
        state = State.empty().with_updates(
            design_target_chip="A2", runtime_target_chip="A5")
        dr, err = Deployer().deploy(state)
        assert err is not None
        assert err.error_type != "chip_mismatch"

    def test_match_proceeds_past_gate(self):
        """design==runtime → gate passes (pure comparison, no probe); deploy()
        advances to later resolution and fails there (here at 'resolve' for the
        empty state), NOT with a chip_mismatch — proving the gate did not fire
        on a match."""
        state = _state_with_chip("A2")
        dr, err = Deployer().deploy(state)
        assert err is not None
        assert err.error_type != "chip_mismatch"

    # Retired with their behavior (step-34): the env_probe_timeout path is gone
    # (deploy no longer probes — the runtime chip is resolved once at dispatch,
    # and a probe timeout is handled there via --runtime_target_chip fallback /
    # EX_DATAERR, covered by test_dispatcher_chip_resolution.py); assume_chip is
    # gone entirely (§1.4).


class _SmokeFakeCompleted:
    """Mirrors subprocess.run's CompletedProcess for _run_smoke judgement tests."""
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


def _smoke_stdout(*, error=None, max_diff=-1.0):
    """Synthesize the JSON line the harness prints (its last stdout line)."""
    import json
    detail = {"case": "smoke"}
    if error is not None:
        detail["error"] = error
    return json.dumps({"case_details": [detail], "max_diff": max_diff,
                       "golden_used": False})


def _smoke_state(kind="torch_op", symbol="torch.ops.cann_bench.add", npu_id=0):
    """Minimal state for smoke: a callable_target + one tiny test case + chip."""
    from ascendc_devkit.domain.requirement import TestCase
    return State.empty().with_updates(
        codegen_manifest={"callable_target": {"kind": kind, "symbol": symbol}},
        design_target_chip="A2", runtime_target_chip="A2", npu_id=npu_id,
        test_cases=[TestCase(name="smoke",
                             inputs=[{"shape": [1024], "dtype": "fp16"}])],
    )


class TestSmokeFailClosedScript:
    """aclnn/unknown kinds have no real callable probe → honest fail-closed
    (regression guard for the print-only no-op false-green hole).

    torch_op/pybind no longer use _smoke_script — they now do a REAL fn() call
    via the shared precision_debug harness (see TestSmokeHarnessRealCall /
    TestRunSmokeJudgement), so smoke_passed=True actually means callable.
    """

    def _script(self, kind: str, symbol: str) -> str:
        return Deployer()._smoke_script(
            {"kind": kind, "symbol": symbol}, per_op_python_dir="/tmp/py")

    def test_aclnn_fails_honestly_not_print_ok(self):
        """No aclnn python probe exists yet → honest hard-fail, NOT a false OK.
        Regression guard for the print-only no-op hole."""
        s = self._script("aclnn", "aclnnAdd")
        assert "smoke FAIL" in s
        assert "raise SystemExit" in s
        # must NOT be the old always-pass print
        assert "smoke OK" not in s

    def test_unknown_kind_fails_closed(self):
        s = self._script("bogus", "whatever")
        assert "smoke FAIL" in s
        assert "smoke OK" not in s


class TestSmokeHarnessRealCall:
    """torch_op/pybind smoke now does a REAL fn() call (not just getattr symbol
    resolution) via the shared precision_debug harness — closes the codegen↔
    precision_debug 断裂点 (smoke_passed=True must mean actually callable, not
    merely registered). step-31 §5 wired smoke as a symbol-resolution-only gate;
    this extends its boundary to 接线+可执行 (precision still owned by run-cases).
    """

    def _harness(self, kind="torch_op", symbol="torch.ops.cann_bench.add",
                 test_cases=None):
        state = _smoke_state(kind=kind, symbol=symbol)
        if test_cases is not None:
            state = state.with_updates(test_cases=test_cases)
        return Deployer()._build_smoke_harness(
            state, {"kind": kind, "symbol": symbol},
            per_op_python_dir="/tmp/py", per_op_opp_dir="/tmp/opp",
            ld_path="/tmp/ld")

    def test_torch_op_harness_actually_calls_kernel_fn(self):
        s = self._harness("torch_op", "torch.ops.cann_bench.add")
        # the harness resolves the symbol AND invokes it with a real tensor —
        # not the old getattr-only probe (the false-green that let registered-
        # but-broken ops pass and only blow up in precision_debug).
        assert "kernel_fn(" in s
        # NPU device pinned (smoke runs the real kernel on a card).
        assert "set_device" in s

    def test_pybind_harness_actually_calls_kernel_fn(self):
        s = self._harness("pybind", "my_ext.add")
        assert "kernel_fn(" in s

    def test_no_golden_required(self):
        """smoke verifies callability, NOT precision — the harness must run
        without a golden reference (golden_contract=None)."""
        s = self._harness("torch_op", "torch.ops.cann_bench.add")
        # the harness unconditionally calls kernel_fn BEFORE any golden branch,
        # so a missing golden cannot gate out the real call.
        assert "kernel_fn(" in s

    def test_uses_first_test_case_when_available(self):
        from ascendc_devkit.domain.requirement import TestCase
        tc = TestCase(name="real_case",
                      inputs=[{"shape": [4, 4], "dtype": "fp32"}])
        s = self._harness(test_cases=[tc])
        # the real case's shape is baked into the harness, not a synthetic [1024].
        assert "[4, 4]" in s

    def test_synthesizes_matching_arity_for_multi_input_op(self):
        """When test_cases is absent, smoke's synthetic case matches the op's
        real input arity (one tensor per op_spec.input) — a unary synthetic case
        would make a multi-input op like add(x1,x2) raise 'missing argument' and
        fail smoke for a non-defect reason (the real-machine ST finding)."""
        from ascendc_devkit.domain.operator import (
            OperatorSpec, TensorSpec, OperatorIdentity)
        state = State.empty().with_updates(
            codegen_manifest={"callable_target": {
                "kind": "torch_op", "symbol": "torch.ops.cann_bench.add"}},
            design_target_chip="A2", runtime_target_chip="A2",
            op_identity=OperatorIdentity(
                spec=OperatorSpec(
                    name="add",
                    inputs=[TensorSpec(name="x1", dtype="fp16", shape=["N"]),
                            TensorSpec(name="x2", dtype="fp16", shape=["N"])],
                    outputs=[TensorSpec(name="y", dtype="fp16", shape=["N"])]),
                repo_root=Path("/tmp"), op_dir=Path("/tmp/add")),
        )
        s = Deployer()._build_smoke_harness(
            state, {"kind": "torch_op", "symbol": "torch.ops.cann_bench.add"},
            "/tmp/py", "/tmp/opp", "/tmp/ld")
        # 2-input op → the synthetic case bakes 2 input tensors (2 shapes),
        # not a single unary one.
        assert s.count("'shape': [1024]") >= 2

    def test_synthetic_op_spec_arity_matches_multi_input_test_case(self):
        """No requirement AND no op_identity, but test_cases carries a multi-input
        case (fixture直调 Deployer.deploy 的边缘路径) → the synthetic op_spec must
        match the CASE's input count, not hardcode 1. A 1-input synthetic spec vs
        a 2-input test_case trips the harness positional-coupling guard
        (test_cases.inputs count > op_spec.inputs count → HarnessContractError),
        which is exactly the real-NPU test_npu.py::TestNPURunnerRealExecution
        setup ERROR this fixes — the guard should NOT fire on a legal multi-input
        smoke case merely because the synthetic spec under-counts."""
        from ascendc_devkit.domain.requirement import TestCase
        # state has neither requirement nor op_identity → forces the synthetic
        # branch; test_cases[0] is a binary (2-input) add case.
        tc = TestCase(name="add_smoke",
                      inputs=[{"shape": [1024], "dtype": "fp16"},
                              {"shape": [1024], "dtype": "fp16"}])
        # _harness's _smoke_state sets no requirement/op_identity by default.
        s = self._harness(test_cases=[tc])
        # Built without raising HarnessContractError, and the real call is wired.
        assert "kernel_fn(" in s
        # Both input shapes baked in (2 tensors fed), proving arity alignment.
        assert s.count("[1024]") >= 2


class TestRunSmokeJudgement:
    """_run_smoke judgement: returncode==0 AND case_details[0] has no `error`.

    The harness swallows per-case kernel exceptions into exit 0 + an `error`
    field (_harness_template.py:443-455), so returncode alone can't certify
    callability — that was the exact gap letting a registered-but-broken op
    earn smoke_passed=True and only fail later in precision_debug. The new
    judgement parses the JSON to confirm fn() ran without raising.
    """

    def _run(self, state, fake):
        with mock.patch(
                "ascendc_devkit.orchestration.stages.deploy.subprocess.run",
                return_value=fake):
            return Deployer()._run_smoke(
                state, "add", "/tmp/opp", "/tmp/py", "/tmp/ld")

    def test_returncode0_no_error_passes(self):
        ok, _err, _log, _ctx = self._run(
            _smoke_state(), _SmokeFakeCompleted(_smoke_stdout(), 0))
        assert ok is True

    def test_returncode0_with_kernel_error_fails(self):
        """fn() raised inside the harness → case_details[0].error set, exit 0.
        smoke MUST fail (not a false green). Core regression guard for the
        codegen↔precision_debug 断裂点."""
        ok, err, _log, _ctx = self._run(
            _smoke_state(),
            _SmokeFakeCompleted(_smoke_stdout(error="RuntimeError: boom"), 0))
        assert ok is False
        assert err  # non-empty reason surfaced (§1.2 可诊断)

    def test_returncode_nonzero_fails(self):
        ok, _err, _log, _ctx = self._run(
            _smoke_state(),
            _SmokeFakeCompleted("", returncode=1, stderr="import failed"))
        assert ok is False

    def test_timeout_fails(self):
        import subprocess
        with mock.patch(
                "ascendc_devkit.orchestration.stages.deploy.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="python", timeout=60)):
            ok, err, _log, _ctx = Deployer()._run_smoke(
                _smoke_state(), "add", "/tmp/opp", "/tmp/py", "/tmp/ld")
        assert ok is False
        assert "timed out" in err

    def test_callable_target_missing_fails(self):
        ok, _err, _log, _ctx = Deployer()._run_smoke(
            State.empty(), "add", "/tmp/opp", "/tmp/py", "/tmp/ld")
        assert ok is False

    def test_env_carries_op_card_pin_pair(self):
        """P13 (step-116)：smoke 子进程 env 双变量 pin——物理卡由
        VISIBLE_DEVICES 携带，ASCEND_NPU_ID 恒 0（remap 后逻辑号）。"""
        captured = {}

        def _fake(cmd, **kw):
            captured["env"] = kw.get("env", {})
            return _SmokeFakeCompleted(_smoke_stdout(), 0)

        with mock.patch(
                "ascendc_devkit.orchestration.stages.deploy.subprocess.run",
                side_effect=_fake):
            Deployer()._run_smoke(
                _smoke_state(npu_id=2), "add", "/tmp/opp", "/tmp/py", "/tmp/ld")
        assert captured["env"]["ASCEND_RT_VISIBLE_DEVICES"] == "2"
        assert captured["env"]["ASCEND_NPU_ID"] == "0"

    def test_aclnn_fail_closed(self):
        """aclnn has no real probe → _run_smoke runs the fail-closed script
        (raise SystemExit → returncode != 0) → smoke fails honestly."""
        ok, _err, _log, _ctx = self._run(
            _smoke_state(kind="aclnn", symbol="aclnnAdd"),
            _SmokeFakeCompleted("", returncode=1, stderr="smoke FAIL: aclnn"))
        assert ok is False


class TestCleanBuild:
    """clean_build=True clears variant.clean_dirs under the build cwd before
    building — forces CMake reconfigure so a new operator enters _C.abi3.so
    (P96: INTERNAL cache + file(GLOB) without CONFIGURE_DEPENDS). Default False
    preserves the incremental behavior for existing callers (codegen/debug).
    """

    def test_clean_build_removes_clean_dirs(self, tmp_path, monkeypatch):
        build_cwd = tmp_path / "example"
        (build_cwd / "build_py" / "cache").mkdir(parents=True)  # CMake GLOB cache
        (build_cwd / "build").mkdir()                            # CMake opp build dir
        variant = BuildVariant(
            name="default", clean_dirs=("build_py", "build", "*.egg-info"),
            stages=(BuildStage(name="b", role="build", cwd="example"),),
        )
        deployer = Deployer()
        # mock _run_command: build ok (不真跑 build.sh); 后续 dist 无产物会 return,
        # 但 clean 已在 build 前发生 —— 本例只锁 clean 行为。
        monkeypatch.setattr(deployer, "_run_command", lambda *a, **k: (True, "", None))
        inputs = _ResolvedInputs(
            profile=None, variant=variant, repo_root=tmp_path, source_dir=build_cwd,
            op_name="op", per_op_opp_dir="/opp", per_op_python_dir="/py", tvars={},
        )
        deployer._run_build_install(State.empty(), inputs, clean_build=True)
        assert not (build_cwd / "build_py").exists()
        assert not (build_cwd / "build").exists()

    def test_no_clean_build_preserves_dirs(self, tmp_path, monkeypatch):
        build_cwd = tmp_path / "example"
        (build_cwd / "build_py").mkdir(parents=True)
        variant = BuildVariant(
            name="default", clean_dirs=("build_py",),
            stages=(BuildStage(name="b", role="build", cwd="example"),),
        )
        deployer = Deployer()
        monkeypatch.setattr(deployer, "_run_command", lambda *a, **k: (True, "", None))
        inputs = _ResolvedInputs(
            profile=None, variant=variant, repo_root=tmp_path, source_dir=build_cwd,
            op_name="op", per_op_opp_dir="/opp", per_op_python_dir="/py", tvars={},
        )
        deployer._run_build_install(State.empty(), inputs, clean_build=False)
        assert (build_cwd / "build_py").exists()  # 默认保留（增量）


class TestBuildInstallSkipsSmoke:
    """build_install() = _resolve + _run_build_install, deliberately NOT chaining
    _run_smoke_phase (§2.9: cannbench_adapt smoke has no repair channel). The
    returned DeployResult.smoke_passed is always False — callers must not treat
    it as a gate (cannbench_eval is decoupled from smoke_paid for this reason)."""

    def test_build_install_does_not_chain_smoke(self, tmp_path, monkeypatch):
        deployer = Deployer()
        inputs = _ResolvedInputs(
            profile=None, variant=mock.Mock(), repo_root=tmp_path,
            source_dir=tmp_path, op_name="op",
            per_op_opp_dir="/opp", per_op_python_dir="/py", tvars={},
        )
        monkeypatch.setattr(deployer, "_resolve", lambda state: (inputs, None))
        built = DeployResult(
            run_package="r", wheel_package="w", install_path="/opp",
            python_path="/py", smoke_passed=False,
        )
        bi = mock.Mock(return_value=(built, None))
        monkeypatch.setattr(deployer, "_run_build_install", bi)
        smoke = mock.Mock(return_value=(built, None))
        monkeypatch.setattr(deployer, "_run_smoke_phase", smoke)

        result, err = deployer.build_install(State.empty())

        assert err is None
        assert bi.call_count == 1            # build+install ran
        assert smoke.call_count == 0         # smoke did NOT run (the whole point)
        assert result.smoke_passed is False  # no smoke → always False

    # —— step-108: deploy 尾 env 契约探针（真实生产值，失配走 pause 家族）——

    def test_env_contract_violation_raises_environment_not_available(
            self, monkeypatch):
        """探针失配 → EnvironmentNotAvailableError（pause 家族：preserve +
        EX_CONFIG，走 dispatcher._terminate_preserving——树不回滚，修复环境后
        resume 续跑；对照批 20260829-142941-49134b P3 的空烧路径）。"""
        from ascendc_devkit.domain.exceptions import EnvironmentNotAvailableError
        from ascendc_devkit.infra import env_contract

        monkeypatch.setattr(
            env_contract, "probe_env_contract",
            lambda env, timeout_sec=10.0: "expected /x/vendors/custom_ops in /x")
        with pytest.raises(EnvironmentNotAvailableError) as ei:
            Deployer()._probe_env_contract_or_raise("/x")
        assert ei.value.stage_name == "deploy"

    def test_smoke_phase_runs_env_contract_probe_first(
            self, tmp_path, monkeypatch):
        """接线守护：_run_smoke_phase 必须先过 env 契约探针再跑 smoke——
        毒环境在烧任何 smoke 子进程前拦截（不空烧）。"""
        from ascendc_devkit.domain.exceptions import EnvironmentNotAvailableError

        deployer = Deployer()
        inputs = _ResolvedInputs(
            profile=None, variant=mock.Mock(), repo_root=tmp_path,
            source_dir=tmp_path, op_name="op",
            per_op_opp_dir="/opp", per_op_python_dir="/py", tvars={},
        )
        built = DeployResult(
            run_package="r", wheel_package="w", install_path="/opp",
            python_path="/py", smoke_passed=False,
        )
        order: list[str] = []

        def probe_then_violate(install_path):
            order.append("probe")
            raise EnvironmentNotAvailableError(
                stage_name="deploy", missing="env contract",
                help_hint="poisoned interpreter startup hook")

        smoke = mock.Mock()
        monkeypatch.setattr(deployer, "_probe_env_contract_or_raise",
                            probe_then_violate)
        monkeypatch.setattr(deployer, "_run_smoke", smoke)

        with pytest.raises(EnvironmentNotAvailableError):
            deployer._run_smoke_phase(State.empty(), built, inputs)
        assert order == ["probe"]
        assert smoke.call_count == 0  # 探针失败 → smoke 零子进程（不空烧）

    def test_build_install_resolve_failure_skips_build(self, tmp_path, monkeypatch):
        """_resolve failure (e.g. chip mismatch) → (smoke_passed=False, err),
        build+install never runs."""
        from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
        deployer = Deployer()
        resolve_err = ErrorFeedback(
            stage_name="deploy", error_type="chip_mismatch",
            message="nope", details={})
        monkeypatch.setattr(deployer, "_resolve", lambda state: (None, resolve_err))
        bi = mock.Mock()
        monkeypatch.setattr(deployer, "_run_build_install", bi)

        result, err = deployer.build_install(State.empty())

        assert bi.call_count == 0
        assert err is resolve_err
        assert result.smoke_passed is False


class TestInstallPythonReinstallOverwrite:
    """P99: pip --target --force-reinstall 不覆盖已存在的包文件（__init__.py 等），
    redeploy 后 per-op 包残留旧版——agent 改的 wrapper 进了 whl 却到不了 per-op，
    scan_interfaces 发现不到新算子（operators=[]）。install_python 步骤须在 pip 前
    清空 per_op_python_dir 内容，让新 whl 干净覆盖。per_op_python_dir 是 per-op 隔离
    的 whl target dir（deploy.py _per_op_path），清空安全。
    """

    def _stage(self, template="pip install --target {per_op_python_dir} whl"):
        return BuildStage(
            name="install_python", role="install_python", cwd=".",
            command_template=template,
        )

    def test_clears_stale_package_before_pip(self, tmp_path):
        py_dir = tmp_path / "py"
        # 旧包残留（上次 install 的旧 __init__.py + dist-info + pycache）
        (py_dir / "cann_bench").mkdir(parents=True)
        (py_dir / "cann_bench" / "__init__.py").write_text(
            "# OLD: only add/sqrt, no exp wrapper\n")
        (py_dir / "cann_bench-1.0.0.dist-info").mkdir()
        (py_dir / "cann_bench" / "__pycache__").mkdir()
        tvars = {"per_op_python_dir": str(py_dir), "full_op_name": "exp"}

        with mock.patch(
            "ascendc_devkit.orchestration.stages.deploy.subprocess.run",
            return_value=mock.Mock(returncode=0, stderr="", stdout=""),
        ):
            ok, err, _ = Deployer()._run_command(self._stage(), tmp_path, tvars)

        assert ok is True
        # 旧包内容被清空 → pip 干净覆盖（不再残留旧 __init__.py）
        assert not (py_dir / "cann_bench").exists()
        assert not (py_dir / "cann_bench-1.0.0.dist-info").exists()

    def test_non_python_role_preserves_dir(self, tmp_path):
        """非 install_python（build/install_runtime）不清 per_op_python。"""
        py_dir = tmp_path / "py"
        (py_dir / "cann_bench").mkdir(parents=True)
        (py_dir / "cann_bench" / "__init__.py").write_text("old")
        stage = BuildStage(
            name="build", role="build", cwd=".", command_template="bash build.sh")
        tvars = {"per_op_python_dir": str(py_dir)}
        with mock.patch(
            "ascendc_devkit.orchestration.stages.deploy.subprocess.run",
            return_value=mock.Mock(returncode=0, stderr="", stdout=""),
        ):
            ok, _, _ = Deployer()._run_command(stage, tmp_path, tvars)
        assert ok is True
        assert (py_dir / "cann_bench" / "__init__.py").exists()  # 保留

    def test_missing_per_op_python_dir_no_crash(self, tmp_path):
        """per_op_python_dir 不存在（首次 install）不崩。"""
        tvars = {"per_op_python_dir": str(tmp_path / "nonexistent")}
        with mock.patch(
            "ascendc_devkit.orchestration.stages.deploy.subprocess.run",
            return_value=mock.Mock(returncode=0, stderr="", stdout=""),
        ):
            ok, _, _ = Deployer()._run_command(self._stage(), tmp_path, tvars)
        assert ok is True


class TestBuildFailureFooterWiring:
    """阶段1 (Plan cozy-wiggling-emerson): build 失败时框架把「错误分析 footer」
    写进 codegen agent 读的 subprocess/*.log —— 结构化 clang 错误 + API 签名权威指路，
    让 in-session 自修循环不再凭记忆猜签名（244 次失败的根因）。
    """

    _SIG_STDERR = (
        "op_kernel/foo.h:540:10: error: no matching function for call to 'ReduceSum'\n"
    )

    def test_footer_for_build_role_has_signature_hint(self):
        from types import SimpleNamespace
        d = Deployer()
        d._programming_model = "Membase"
        stage = SimpleNamespace(role="build")
        # ws=None → 只算阶段1 footer（签名指路），不追加 gradient（无持久状态/消费者）。
        footer = d._build_failure_footer(stage, None, "", self._SIG_STDERR)
        assert "框架错误分析" in footer
        assert "ReduceSum" in footer
        assert "高阶API" in footer  # A3 Membase → 非 SIMD 高阶 API doc 变体

    def test_footer_empty_for_non_build_role(self):
        from types import SimpleNamespace
        d = Deployer()
        d._programming_model = "Membase"
        # install/smoke 角色失败不富化（签名错是 build 期的事）。
        stage = SimpleNamespace(role="install_runtime")
        assert d._build_failure_footer(stage, None, "", self._SIG_STDERR) == ""

    def test_persist_subprocess_output_appends_footer(self, tmp_path):
        from types import SimpleNamespace
        ws = SimpleNamespace(subprocess_log=tmp_path / "subprocess")
        footer = (
            "\n=== 框架错误分析（自动生成，非编译器输出） ===\n"
            "ReduceSum → doc\n=== end 框架错误分析 ==="
        )
        path = Deployer._persist_subprocess_output(
            ws, "build", "ascendc", "stdout-text", "stderr-text",
            analysis_footer=footer)
        assert path is not None
        content = Path(path).read_text(encoding="utf-8")
        assert "=== stdout ===" in content and "stdout-text" in content
        assert "=== stderr ===" in content and "stderr-text" in content
        # footer 追加在原始 stdout/stderr 之后，带清晰标注
        assert "框架错误分析" in content
        assert "=== end 框架错误分析" in content

    def test_build_failure_archives_per_attempt(self, tmp_path):
        """2026-09-10：build 失败日志独立归档——每轮一个 <stem>_retry{N}.log，
        <stem>.log 保留最新一份。多轮 build 失败不再互相覆盖，历史错误可回溯。"""
        import json
        from types import SimpleNamespace
        ws = SimpleNamespace(subprocess_log=tmp_path / "subprocess")
        # 预置 retry-state 为「第 2 次 build」→ 归档应命名 _retry2
        ws.subprocess_log.mkdir(parents=True, exist_ok=True)
        (ws.subprocess_log / "build_retry_state.json").write_text(json.dumps({
            "per_class": {"C-SYM": 2}, "total": 2, "last_class": "C-SYM"}))

        path = Deployer._persist_subprocess_output(
            ws, "build", "ascendc", "out-2", "err-2",
            analysis_footer="footer-2", archive=True)
        assert path is not None
        archive = ws.subprocess_log / "build_ascendc_retry2.log"
        assert archive.exists(), "build 失败应归档到 _retry{N}.log"
        assert "err-2" in archive.read_text(encoding="utf-8")
        # 最新指针文件仍在
        assert Path(path).exists() and "err-2" in Path(path).read_text(encoding="utf-8")

    def test_non_build_role_not_archived(self, tmp_path):
        """install/smoke 失败不归档（retry-state 只记 build 类，写归档制造噪音）。"""
        import json
        from types import SimpleNamespace
        ws = SimpleNamespace(subprocess_log=tmp_path / "subprocess")
        ws.subprocess_log.mkdir(parents=True, exist_ok=True)
        (ws.subprocess_log / "build_retry_state.json").write_text(json.dumps({
            "per_class": {"C-API": 1}, "total": 1, "last_class": "C-API"}))

        Deployer._persist_subprocess_output(
            ws, "install_runtime", "ascendc", "out", "err")
        # install 无归档
        assert not (ws.subprocess_log / "install_runtime_ascendc_retry1.log").exists()
        # smoke 无归档
        Deployer._persist_subprocess_output(ws, "smoke", "", "o", "e")
        assert not (ws.subprocess_log / "smoke_retry1.log").exists()

    def test_build_without_archive_flag_not_archived(self, tmp_path):
        """M2：归档是显式 opt-in（调用方传 archive=True）——通用函数本身
        不内建 role 分支，role=build 但调用方不传 archive 则不归档。"""
        import json
        from types import SimpleNamespace
        ws = SimpleNamespace(subprocess_log=tmp_path / "subprocess")
        ws.subprocess_log.mkdir(parents=True, exist_ok=True)
        (ws.subprocess_log / "build_retry_state.json").write_text(json.dumps({
            "per_class": {"C-SYM": 1}, "total": 1, "last_class": "C-SYM"}))

        Deployer._persist_subprocess_output(
            ws, "build", "ascendc", "out", "err")
        assert not (ws.subprocess_log / "build_ascendc_retry1.log").exists()

    def test_build_archive_best_effort_on_missing_state(self, tmp_path):
        """retry-state 缺失(如直接调 _persist 的场景)→ 归档命名退化为 _retry1,
        best-effort 不崩(§1.2)。"""
        from types import SimpleNamespace
        ws = SimpleNamespace(subprocess_log=tmp_path / "subprocess")
        path = Deployer._persist_subprocess_output(
            ws, "build", "ascendc", "out", "err", archive=True)
        assert path is not None
        assert (ws.subprocess_log / "build_ascendc_retry1.log").exists()

    def test_run_command_build_failure_writes_footer_to_log(self, tmp_path):
        """端到端：build 失败（RC≠0 + 签名错 stderr）→ 持久化 log 含签名指路 footer。"""
        from types import SimpleNamespace
        ws = SimpleNamespace(subprocess_log=tmp_path / "subprocess")
        stage = BuildStage(
            name="ascendc", role="build", cwd=".", command_template="bash build.sh")
        d = Deployer()
        d._programming_model = "Membase"
        with mock.patch(
            "ascendc_devkit.orchestration.stages.deploy.subprocess.run",
            return_value=mock.Mock(
                returncode=1, stdout="", stderr=self._SIG_STDERR),
        ):
            ok, err, log_path = d._run_command(stage, tmp_path, {}, ws=ws)
        assert ok is False
        assert log_path is not None
        content = Path(log_path).read_text(encoding="utf-8")
        # agent 读 log 时能看到权威签名指路（不只原始 stderr）
        assert "框架错误分析" in content
        assert "ReduceSum" in content


class TestBuildRetryState:
    """阶段2 改动3+4: build 失败 retry-state 文件 I/O + gradient 接线。

    codegen in-session redeploy 循环原本对「同类失败第几次」无记忆 → 同策略盲重试 40×。
    retry-state 持久化 per-class 计数，footer 据此给「同策略/换策略/升级」advisory。
    """

    _SIG_STDERR = (
        "op_kernel/foo.h:540:10: error: no matching function for call to 'ReduceSum'\n"
    )

    def _ws(self, tmp_path):
        from types import SimpleNamespace
        return SimpleNamespace(subprocess_log=tmp_path / "subprocess")

    def test_read_retry_state_missing_file_is_empty(self, tmp_path):
        # 文件不存在（首次 run）→ 空状态，不崩。
        st = Deployer._read_retry_state(self._ws(tmp_path))
        assert st == {"per_class": {}, "total": 0, "last_class": ""}

    def test_read_retry_state_no_workspace_is_empty(self):
        assert Deployer._read_retry_state(None) == {
            "per_class": {}, "total": 0, "last_class": ""}

    def test_read_retry_state_corrupt_file_is_empty(self, tmp_path):
        # 损坏 JSON → 空状态（§1.2 宽容兜底，不崩）。
        ws = self._ws(tmp_path)
        ws.subprocess_log.mkdir(parents=True, exist_ok=True)
        (ws.subprocess_log / "build_retry_state.json").write_text("NOT JSON{")
        assert Deployer._read_retry_state(ws) == {
            "per_class": {}, "total": 0, "last_class": ""}

    def test_bump_first_occurrence(self, tmp_path):
        ws = self._ws(tmp_path)
        class_count, total = Deployer._bump_retry_state(ws, "C-API")
        assert (class_count, total) == (1, 1)
        # 持久化可回读：per_class + total + last_class 都对。
        st = Deployer._read_retry_state(ws)
        assert st["per_class"] == {"C-API": 1}
        assert st["total"] == 1
        assert st["last_class"] == "C-API"

    def test_bump_accumulate_same_and_different_class(self, tmp_path):
        ws = self._ws(tmp_path)
        Deployer._bump_retry_state(ws, "C-API")
        Deployer._bump_retry_state(ws, "C-API")   # 同类第 2 次
        cc, total = Deployer._bump_retry_state(ws, "C-TYP")  # 另一类第 1 次
        assert (cc, total) == (1, 3)  # C-TYP 首次=1；累计=3
        st = Deployer._read_retry_state(ws)
        assert st["per_class"] == {"C-API": 2, "C-TYP": 1}
        assert st["total"] == 3
        assert st["last_class"] == "C-TYP"

    def test_read_retry_state_drops_non_int_values(self, tmp_path):
        """M1: per_class 值非 int（外部损坏）→ 丢弃该键保留合法键，不崩、不致
        _bump_retry_state 的 +1 TypeError。下次 bump 用干净值覆盖（自愈）。"""
        import json
        ws = self._ws(tmp_path)
        ws.subprocess_log.mkdir(parents=True, exist_ok=True)
        (ws.subprocess_log / "build_retry_state.json").write_text(json.dumps({
            "per_class": {"C-API": "garbage", "C-TYP": 2},
            "total": 2, "last_class": "C-TYP"}))
        st = Deployer._read_retry_state(ws)
        # C-API 的字符串值被丢弃；C-TYP 的合法 int 保留
        assert st["per_class"] == {"C-TYP": 2}
        assert st["total"] == 2 and st["last_class"] == "C-TYP"

    def test_bump_self_heals_corrupt_value(self, tmp_path):
        """M1 自愈：值损坏的文件 → bump 不崩、返回合理计数、文件被干净状态覆盖。"""
        import json
        ws = self._ws(tmp_path)
        ws.subprocess_log.mkdir(parents=True, exist_ok=True)
        (ws.subprocess_log / "build_retry_state.json").write_text(json.dumps({
            "per_class": {"C-API": "garbage"}, "total": 1, "last_class": "C-API"}))
        cc, total = Deployer._bump_retry_state(ws, "C-API")  # 不崩
        # 损坏值被丢弃 → C-API 视作首计 = 1；total = 1 + 1 = 2
        assert (cc, total) == (1, 2)
        # 文件已被干净状态覆盖（无 "garbage"）
        st = Deployer._read_retry_state(ws)
        assert st["per_class"] == {"C-API": 1}
        assert st["total"] == 2

    def test_footer_first_failure_no_gradient_but_counts(self, tmp_path):
        """2026-09-10（M2/M3 收口）：footer 不再追 gradient advisory——分类只做
        retry-state 计数（供归档 attempt 号 + 签名 stop-loss），文案由 signature
        检测接管。首次失败仍计数落盘。"""
        from types import SimpleNamespace
        d = Deployer()
        d._programming_model = "Membase"
        stage = SimpleNamespace(role="build")
        ws = self._ws(tmp_path)
        footer = d._build_failure_footer(stage, ws, "", self._SIG_STDERR)
        # gradient advisory 已废弃 → 不再出现在日志
        assert "框架重试梯度" not in footer
        # 阶段1 footer 仍在（clang 摘要 + 签名指路）
        assert "框架错误分析" in footer
        # retry-state 仍计数（供归档命名 + stop-loss）
        st = Deployer._read_retry_state(ws)
        assert st["total"] == 1
        assert st["per_class"].get("C-API") == 1

    def test_footer_second_same_class_counts_accumulate(self, tmp_path):
        """预热 retry-state（C-API 已 1 次）→ 第 2 次失败 → total=2（无 gradient 文案）。"""
        from types import SimpleNamespace
        import json
        ws = self._ws(tmp_path)
        ws.subprocess_log.mkdir(parents=True, exist_ok=True)
        (ws.subprocess_log / "build_retry_state.json").write_text(json.dumps(
            {"per_class": {"C-API": 1}, "total": 1, "last_class": "C-API"}))
        d = Deployer()
        d._programming_model = "Membase"
        stage = SimpleNamespace(role="build")
        footer = d._build_failure_footer(stage, ws, "", self._SIG_STDERR)
        assert "框架重试梯度" not in footer
        st = Deployer._read_retry_state(ws)
        assert st["total"] == 2
        assert st["per_class"].get("C-API") == 2

    def test_footer_unknown_class_counts_observable(self, tmp_path):
        """unknown 错误类（纯链接器症状）仍记 unknown 计数（可观测 §1.3）；
        gradient 文案废弃后 footer 仅含阶段1（此处为空，诚实不富化）。"""
        from types import SimpleNamespace
        d = Deployer()
        d._programming_model = "Membase"
        stage = SimpleNamespace(role="build")
        ws = self._ws(tmp_path)
        linker_stderr = "ld.lld: cannot open foo_9.o: No such file\n"
        footer = d._build_failure_footer(stage, ws, "", linker_stderr)
        # Phase 1 对纯链接器症状为 ""（无 clang 可富化）；gradient 已废弃
        assert "框架重试梯度" not in footer
        assert "框架错误分析" not in footer
        st = Deployer._read_retry_state(ws)
        assert st["per_class"].get("unknown") == 1

    def test_run_command_end_to_end_counts_and_archives(self, tmp_path):
        """端到端：build RC≠0 + 签名错 → log 含阶段1 footer（无 gradient）；
        retry-state 落盘 + 归档 _retry1.log。"""
        from types import SimpleNamespace
        ws = SimpleNamespace(subprocess_log=tmp_path / "subprocess")
        stage = BuildStage(
            name="ascendc", role="build", cwd=".", command_template="bash build.sh")
        d = Deployer()
        d._programming_model = "Membase"
        with mock.patch(
            "ascendc_devkit.orchestration.stages.deploy.subprocess.run",
            return_value=mock.Mock(
                returncode=1, stdout="", stderr=self._SIG_STDERR),
        ):
            ok, err, log_path = d._run_command(stage, tmp_path, {}, ws=ws)
        assert ok is False and log_path is not None
        content = Path(log_path).read_text(encoding="utf-8")
        assert "框架重试梯度" not in content
        assert "框架错误分析" in content  # 阶段1 仍在
        # retry-state 已落盘
        st = Deployer._read_retry_state(ws)
        assert st["total"] == 1
        # 归档已写（build 失败分支传 archive=True，M2/M3）
        assert (ws.subprocess_log / "build_ascendc_retry1.log").exists()
        st = Deployer._read_retry_state(ws)
        assert st["per_class"]["C-API"] == 1


class TestSmokeSynthShape:
    """M4 (PR-42): the smoke synth path (no test_cases) must give a DYNAMIC
    (TensorList) input a list-of-lists shape — a flat [1024] would fail the
    harness _validate_case_form (DYNAMIC requires list[list[int]]) and give a
    false smoke failure on the no-test_cases edge path."""

    def test_dynamic_input_gets_list_of_lists_shape(self):
        from ascendc_devkit.domain.operator import OperatorSpec, TensorSpec
        from ascendc_devkit.domain.requirement import Requirement

        state = _state_with_chip("A2").with_updates(
            op_name="foreach_norm",
            requirement=Requirement(op_spec=OperatorSpec(
                name="foreach_norm",
                inputs=[TensorSpec(name="x", dtype="fp16", shape=["L", "*"],
                                   param_type="DYNAMIC")],
                outputs=[TensorSpec(name="y", dtype="fp16", shape=["L"],
                                    param_type="DYNAMIC")],
            )),
            test_cases=[],  # empty → synth path
        )
        script = Deployer()._build_smoke_harness(
            state,
            {"kind": "torch_op",
             "symbol": "torch.ops.cann_bench.foreach_norm"},
            "/p/python", "/p/opp", "/p/opp/op_api/lib",
        )
        # synth case for the DYNAMIC input must carry a list-of-lists shape
        # (a flat [1024] would be rejected by the DYNAMIC contract gate).
        assert "[[1024]]" in script

    def test_required_input_stays_flat_shape(self):
        from ascendc_devkit.domain.operator import OperatorSpec, TensorSpec
        from ascendc_devkit.domain.requirement import Requirement

        state = _state_with_chip("A2").with_updates(
            op_name="add",
            requirement=Requirement(op_spec=OperatorSpec(
                name="add",
                inputs=[TensorSpec(name="x", dtype="fp16", shape=["N"],
                                   param_type="REQUIRED")],
                outputs=[TensorSpec(name="y", dtype="fp16", shape=["N"],
                                    param_type="REQUIRED")],
            )),
            test_cases=[],
        )
        script = Deployer()._build_smoke_harness(
            state,
            {"kind": "torch_op", "symbol": "torch.ops.cann_bench.add"},
            "/p/python", "/p/opp", "/p/opp/op_api/lib",
        )
        assert "[1024]" in script and "[[1024]]" not in script


class TestSourceIdentity:
    """_source_identity 纯函数：git 探测 → {HEAD12}-{clean|dirty-n} 字符串。

    B（step-119）：deploy stamp 的构建源码来源标识。探测逻辑复用 infra 公共
    probe_git_head_and_dirty（已被 infra 契约 UT 覆盖），此处测 deploy 的拼串产出
    + 真实 git 目录的 clean/dirty/非 git 三态。
    """

    def _git_init(self, repo: Path):
        import subprocess
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t"])
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"])

    def test_clean_repo(self, tmp_path):
        import subprocess
        from ascendc_devkit.orchestration.stages.deploy import _source_identity
        self._git_init(tmp_path)
        (tmp_path / "a.txt").write_text("x")
        subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
        subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "init"], check=True)
        ident = _source_identity(tmp_path)
        assert ident.endswith("-clean")
        assert len(ident) == 12 + len("-clean")  # HEAD 短12 + "-clean"

    def test_dirty_repo_counts_files(self, tmp_path):
        import subprocess
        from ascendc_devkit.orchestration.stages.deploy import _source_identity
        self._git_init(tmp_path)
        (tmp_path / "a.txt").write_text("x")
        subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
        subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "init"], check=True)
        (tmp_path / "a.txt").write_text("dirty")
        (tmp_path / "b.txt").write_text("new")
        ident = _source_identity(tmp_path)
        assert ident.endswith("-dirty-2")  # a.txt 修改 + b.txt 新增

    def test_not_a_git_repo_empty(self, tmp_path):
        """非 git / git 不可用 → 空串（下游按「无来源信息」诚实处理，非伪造）。"""
        import tempfile
        from ascendc_devkit.orchestration.stages.deploy import _source_identity
        # 非 git 目录须建在 git 仓外（tmp_path 内会被父 git 认作子目录）
        not_repo = Path(tempfile.mkdtemp(dir=str(tmp_path.parent)))
        assert _source_identity(not_repo) == ""


class TestCompileBuildOnly:
    """L4 改动 1 (方案 2 D6): Deployer.compile() = build only — 不 install、不 smoke。

    codegen transition 用它做「编译验证门」：compile 错 → resume agent 修；compile 过 →
    才 install+smoke（install_and_smoke 复用产物，不重 build）。compile() 返回的
    DeployResult 不得带 install_path/python_path（未 install，防误导下游以为装好）。
    """

    def _inputs(self, tmp_path, variant):
        return _ResolvedInputs(
            profile=None, variant=variant, repo_root=tmp_path,
            source_dir=tmp_path / variant.stages[0].cwd if variant.stages else tmp_path,
            op_name="op", per_op_opp_dir="/opp", per_op_python_dir="/py", tvars={},
        )

    def _variant(self, tmp_path, build_name="b"):
        """build role stage only + install roles (install_opp/install_whl)。"""
        (tmp_path / "dist").mkdir(parents=True)
        (tmp_path / "dist" / "pkg.run").write_text("run")
        (tmp_path / "dist" / "pkg.whl").write_text("whl")
        return BuildVariant(
            name="default",
            stages=(
                BuildStage(name=build_name, role="build", cwd="."),
                BuildStage(name="install_opp", role="install_runtime", cwd=".",
                           command_template="install {run_pkg}"),
                BuildStage(name="install_whl", role="install_python", cwd=".",
                           command_template="pip {whl_pkg}"),
            ),
        )

    def test_compile_build_only_runs_build_not_install(self, tmp_path, monkeypatch):
        """compile() 只跑 build role；install/smoke role 命令未被调用。"""
        deployer = Deployer()
        variant = self._variant(tmp_path)
        inputs = self._inputs(tmp_path, variant)
        monkeypatch.setattr(deployer, "_resolve", lambda state: (inputs, None))
        # _run_command 全 mock 成 ok，但记录被调用的 stage（role）
        called = []
        def fake_run(stage, *a, **k):
            called.append(stage.role)
            return True, "", None
        monkeypatch.setattr(deployer, "_run_command", fake_run)
        smoke = mock.Mock(return_value=(mock.Mock(), None))
        monkeypatch.setattr(deployer, "_run_smoke_phase", smoke)

        result, err = deployer.compile(State.empty())

        assert err is None
        assert called == ["build"]            # 只 build，不 install
        assert smoke.call_count == 0          # 不 smoke
        assert result.run_package             # 有产物
        # 质疑后修正：compile 未 install → install_path/python_path 留空（防误导）
        assert not result.install_path
        assert not result.python_path

    def test_compile_resolve_failure_returns_err(self, tmp_path, monkeypatch):
        deployer = Deployer()
        from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
        resolve_err = ErrorFeedback(
            stage_name="deploy", error_type="deploy_failed",
            message="resolve failed", details={"step": "resolve"})
        monkeypatch.setattr(deployer, "_resolve", lambda state: (None, resolve_err))
        result, err = deployer.compile(State.empty())
        assert result.smoke_passed is False
        assert err is resolve_err

    def test_run_build_install_build_only_skips_install(self, tmp_path, monkeypatch):
        """_run_build_install(build_only=True) 在 build 段后 return，install role 不跑。"""
        deployer = Deployer()
        variant = self._variant(tmp_path)
        inputs = self._inputs(tmp_path, variant)
        called = []
        def fake_run(stage, *a, **k):
            called.append(stage.role)
            return True, "", None
        monkeypatch.setattr(deployer, "_run_command", fake_run)
        result, err = deployer._run_build_install(
            State.empty(), inputs, build_only=True)
        assert err is None
        assert called == ["build"]
        assert not result.install_path
        assert not result.python_path


class TestInstallAndSmoke:
    """L4 改动 1d (质疑后修正): install_and_smoke(state, compile_result) 复用 compile 产物
    做 install+smoke，不重 build（无码改动不做两次 build）。"""

    def _inputs(self, tmp_path, variant):
        return _ResolvedInputs(
            profile=None, variant=variant, repo_root=tmp_path,
            source_dir=tmp_path / variant.stages[0].cwd if variant.stages else tmp_path,
            op_name="op", per_op_opp_dir="/opp", per_op_python_dir="/py", tvars={},
        )

    def test_install_and_smoke_skips_build_reuses_package(self, tmp_path, monkeypatch):
        deployer = Deployer()
        variant = BuildVariant(
            name="default",
            stages=(
                BuildStage(name="b", role="build", cwd="."),
                BuildStage(name="install_opp", role="install_runtime", cwd=".",
                           command_template="install {run_pkg}"),
            ),
        )
        inputs = self._inputs(tmp_path, variant)
        monkeypatch.setattr(deployer, "_resolve", lambda state: (inputs, None))
        run_roles = []
        def fake_run(stage, *a, **k):
            run_roles.append(stage.role)
            return True, "", None
        monkeypatch.setattr(deployer, "_run_command", fake_run)
        compiled = DeployResult(
            run_package="/dist/pkg.run", wheel_package="/dist/pkg.whl",
            smoke_passed=False)
        smoke_ret = DeployResult(
            run_package="/dist/pkg.run", wheel_package="/dist/pkg.whl",
            install_path="/opp", python_path="/py", smoke_passed=True)
        monkeypatch.setattr(
            deployer, "_run_smoke_phase",
            lambda state, build_result, inputs: (smoke_ret, None))

        result, err = deployer.install_and_smoke(State.empty(), compiled)

        assert err is None
        assert "build" not in run_roles       # 不重 build
        assert "install_runtime" in run_roles  # install 跑了
        assert result.smoke_passed is True
        assert result.run_package == "/dist/pkg.run"

    def test_install_and_smoke_no_run_package_errors(self, tmp_path, monkeypatch):
        deployer = Deployer()
        variant = BuildVariant(
            name="default",
            stages=(BuildStage(name="b", role="build", cwd="."),),
        )
        inputs = self._inputs(tmp_path, variant)
        monkeypatch.setattr(deployer, "_resolve", lambda state: (inputs, None))
        compiled = DeployResult(smoke_passed=False)  # 无 run_package
        result, err = deployer.install_and_smoke(State.empty(), compiled)
        assert err is not None
        assert err.details.get("step") == "build"
