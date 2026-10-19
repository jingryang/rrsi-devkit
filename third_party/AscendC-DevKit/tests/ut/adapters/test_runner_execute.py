"""UT for NPURunner.execute — P79 rule × backend orthogonal precision verdict.

execute 暴露 ``precision_threshold``（无 golden 标量回退）+ ``rule``
（``CompareRule``，逐 dtype 阈值 = proto 真值经 ``merge_thresholds``）+
``comparer``（``PrecisionComparer``，backend 侧——harness setup + 主进程聚合）。
``passed`` 来自 ``comparer.aggregate``（逐输出：cann-bench checker ``passed`` 优先，
否则 ``diff <= rule.dtype_thresholds[dtype]``）；无 golden 时回退
``max_diff <= precision_threshold``。

UT mock subprocess（§3.8 UT = 纯逻辑/编排，不依赖 NPU 运行时）。
真实 NPU 端到端属 heavy_llm/npu ST（§3.11），不默认跑。
"""

import inspect
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from ascendc_devkit.domain.precision import merge_thresholds
from ascendc_devkit.adapters.npu.precision_comparer import CannbenchComparer
from ascendc_devkit.adapters.npu.runner import NPURunner
from ascendc_devkit.domain.operator import OperatorSpec, TensorSpec
from ascendc_devkit.domain.precision import CompareRule
from ascendc_devkit.domain.requirement import TestCase


def _rule_from(op_spec):
    """Mirror run_precision_cases assembly: proto 真值 → CompareRule."""
    return CompareRule(dtype_thresholds=merge_thresholds(
        getattr(op_spec, "precision_thresholds", None)))


def _runner():
    r = NPURunner.__new__(NPURunner)
    r._chip_version = "A2"
    r._torch_npu_available = True
    return r


def _harness_stdout(*, max_diff=0.5, case_details=None, golden_used=True,
                    total_ms=10.0, bottleneck=None):
    return json.dumps({
        "total_ms": total_ms,
        "max_diff": max_diff,
        "case_details": case_details or [],
        "golden_used": golden_used,
        # mirror the real harness, which derives bottleneck from golden_used
        "bottleneck": bottleneck or (
            "real_kernel_vs_golden" if golden_used else "no_golden_reference"),
    })


def _deploy():
    return SimpleNamespace(python_path="/p", install_path="/i",
                           ld_library_path_add="")


def _op_dq():
    return OperatorSpec(
        name="DynamicQuant", precision_thresholds={"int8": 1.0},
        inputs=[TensorSpec(name="x", dtype="fp16", shape=["N"])],
        outputs=[TensorSpec(name="y", dtype="int8", shape=["N"])],
    )


class _FakeCompleted:
    def __init__(self, stdout, returncode=0, stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TestExecutePrecisionVerdict:
    def test_execute_exposes_threshold_params(self):
        """execute 暴露 precision_threshold（标量回退）+ rule + comparer（P79）。"""
        sig = inspect.signature(NPURunner.execute)
        assert "precision_threshold" in sig.parameters
        assert "rule" in sig.parameters
        assert "comparer" in sig.parameters
        # dtype_thresholds 散参数已下线（rule × backend 正交后由 rule 承载）
        assert "dtype_thresholds" not in sig.parameters

    def test_dq_int8_within_threshold_passes(self):
        """DQ 冤杀解除：int8 输出 diff=1.0 / proto threshold=1.0 / passed=True。

        rule 由 op_spec.precision_thresholds 桥接（= run_precision_cases 装配产物），
        ``comparer.aggregate`` 据逐输出 verdict（passed=True）判 passed=True。
        旧 max_diff(1.0)<=1e-2 标量会误杀；现逐输出 verdict 走 proto dtype 阈值。"""
        r = _runner()
        case_details = [{
            "case": "c1",
            "outputs": [{"index": 0, "passed": True, "dtype": "int8",
                         "threshold": 1.0, "diff": 1.0}],
        }]
        with patch("ascendc_devkit.adapters.npu.runner.subprocess.run",
                   return_value=_FakeCompleted(_harness_stdout(
                       max_diff=1.0, case_details=case_details))):
            result = r.execute(
                _op_dq(),
                [TestCase(name="c1",
                          inputs=[{"name": "x", "shape": [4], "dtype": "fp16"}])],
                0, deploy_result=_deploy(),
                callable_target={"kind": "torch_op",
                                 "symbol": "torch.ops.cann_bench.dq"},
                rule=_rule_from(_op_dq()),
            )
        assert result["passed"] is True
        assert result["case_details"][0]["outputs"][0]["passed"] is True
        assert result["case_details"][0]["outputs"][0]["dtype"] == "int8"
        # proto 真值贯穿：result 回显的 dtype_thresholds 含 proto int8=1.0
        assert result["dtype_thresholds"]["int8"] == 1.0

    def test_failed_output_propagates_passed_false(self):
        """任一输出 passed=False → ``comparer.aggregate`` 返回 False。"""
        r = _runner()
        case_details = [{
            "case": "c1",
            "outputs": [{"index": 0, "passed": False, "dtype": "fp16",
                         "threshold": 0.001, "diff": 0.5}],
        }]
        with patch("ascendc_devkit.adapters.npu.runner.subprocess.run",
                   return_value=_FakeCompleted(
                       _harness_stdout(case_details=case_details))):
            result = r.execute(
                _op_dq(), [], 0, deploy_result=_deploy(),
                callable_target={"kind": "torch_op", "symbol": "s"},
            )
        assert result["passed"] is False

    def test_degradation_warning_surfaced_to_main_log(self):
        """F2: harness stderr 含降级 signature（``compare_tensors 不可用`` / ``退
        devkit 默认路径``）→ runner 上浮主 log 的 [WARN]（``Logger.warn``）。原仅
        dump 到 per-iter run.log，对看主 run.log 的顶层观察者不可见（batch
        20260731-132818 首诊漏掉了降级，一度误判 golden 上游缺陷）。"""
        r = _runner()
        degraded = ("UserWarning: CannbenchComparer: cann-bench compare_tensors "
                    "不可用 (ModuleNotFoundError: No module named 'kernel_eval'))，"
                    "退 devkit 默认路径\n")
        with patch("ascendc_devkit.adapters.npu.runner.subprocess.run",
                   return_value=_FakeCompleted(_harness_stdout(), stderr=degraded)), \
             patch("ascendc_devkit.infra.logger.Logger.warn") as mock_warn:
            r.execute(
                _op_dq(), [], 0, deploy_result=_deploy(),
                callable_target={"kind": "torch_op", "symbol": "s"},
                comparer=CannbenchComparer(),
            )
        assert mock_warn.called, "F2: 降级 warning 未上浮主 log"
        assert "降级" in mock_warn.call_args[0][0]

    def test_no_degradation_warning_when_clean_stderr(self):
        """F2 反例：stderr 无降级 signature → 不上浮（避免误报）。"""
        r = _runner()
        with patch("ascendc_devkit.adapters.npu.runner.subprocess.run",
                   return_value=_FakeCompleted(_harness_stdout(), stderr="")), \
             patch("ascendc_devkit.infra.logger.Logger.warn") as mock_warn:
            r.execute(
                _op_dq(), [], 0, deploy_result=_deploy(),
                callable_target={"kind": "torch_op", "symbol": "s"},
            )
        assert not mock_warn.called

    def test_diff_over_dtype_threshold_fails(self):
        """无 ``passed`` 字段时回退 ``diff <= dtype threshold``：fp16 diff 0.5 > 0.001 → 失败。"""
        r = _runner()
        case_details = [{
            "case": "c1",
            "outputs": [{"index": 0, "dtype": "fp16",
                         "threshold": 0.001, "diff": 0.5}],
        }]
        with patch("ascendc_devkit.adapters.npu.runner.subprocess.run",
                   return_value=_FakeCompleted(
                       _harness_stdout(case_details=case_details))):
            result = r.execute(
                _op_dq(), [], 0, deploy_result=_deploy(),
                callable_target={"kind": "torch_op", "symbol": "s"},
            )
        assert result["passed"] is False

    def test_no_golden_scalar_threshold_fallback(self):
        """golden_used=False → passed = max_diff <= precision_threshold（标量回退）。"""
        r = _runner()
        with patch("ascendc_devkit.adapters.npu.runner.subprocess.run",
                   return_value=_FakeCompleted(_harness_stdout(
                       max_diff=0.5, golden_used=False))):
            result = r.execute(
                _op_dq(), [], 0, deploy_result=_deploy(),
                callable_target={"kind": "torch_op", "symbol": "s"},
                precision_threshold=1e-2,
            )
        # 0.5 > 1e-2 → 失败
        assert result["passed"] is False

    def test_no_golden_loose_scalar_threshold_passes(self):
        """同 diff 但放宽标量阈值 precision_threshold=1.0 → passed。"""
        r = _runner()
        with patch("ascendc_devkit.adapters.npu.runner.subprocess.run",
                   return_value=_FakeCompleted(_harness_stdout(
                       max_diff=0.5, golden_used=False))):
            result = r.execute(
                _op_dq(), [], 0, deploy_result=_deploy(),
                callable_target={"kind": "torch_op", "symbol": "s"},
                precision_threshold=1.0,
            )
        assert result["passed"] is True

    def test_execution_failure_returns_passed_false(self):
        r = _runner()
        with patch("ascendc_devkit.adapters.npu.runner.subprocess.run",
                   return_value=_FakeCompleted("", returncode=1, stderr="boom")):
            result = r.execute(
                _op_dq(), [], 0, deploy_result=_deploy(),
                callable_target={"kind": "torch_op", "symbol": "s"},
            )
        assert result["passed"] is False
        assert result["max_diff"] == 999.0
        assert result["error"] == "boom"

    # ------------------------------------------------------------------
    # D2: crash honest reporting (batch 20260801-050054-ab7283 P4-D2)
    # ------------------------------------------------------------------
    # A fatal AICORE abort kills the child subprocess; the old runner collapsed
    # every abnormal exit (signal-kill / timeout) into one opaque sentinel
    # {passed:False, max_diff:999, case_details:[]} with NO failure_type, and
    # truncated stderr to its HEAD 500 chars (keeping CANN's warning preamble,
    # discarding the AICORE/507035 keyword at the tail). golden_used never made
    # it into result.json (harness dies before its print) → scope_guard mistook
    # the crash for a golden defect and HALT'd the wrong stage. These guard the
    # fix: the sentinel now carries failure_type/returncode/timed_out/error_tail
    # (+ crash_dump_path when CANN wrote an exception_info dump), and run.log is
    # written even on timeout (it was skipped before — yet it's the very artifact
    # scope_guard is told to read for crash evidence).

    def test_signal_killed_exit_flagged_runtime_crash(self):
        """returncode<0 (signal kill, e.g. -6 SIGABRT) → failure_type=runtime_crash
        + returncode preserved, so scope_guard routes to diagnose not golden."""
        r = _runner()
        with patch("ascendc_devkit.adapters.npu.runner.subprocess.run",
                   return_value=_FakeCompleted("", returncode=-6,
                                              stderr="fatal AICORE abort")):
            result = r.execute(
                _op_dq(), [], 0, deploy_result=_deploy(),
                callable_target={"kind": "torch_op", "symbol": "s"},
            )
        assert result["passed"] is False
        assert result["failure_type"] == "runtime_crash"
        assert result["returncode"] == -6
        assert result["timed_out"] is False
        # error head kept (compat) AND error_tail carries the crash text
        assert "AICORE" in result["error_tail"]

    def test_error_tail_preserves_keyword_truncated_from_head(self):
        """D2 defect B: real crash keyword sits in stderr's TAIL (after CANN's
        warning preamble). error (head [:500]) loses it; error_tail ([-800:])
        keeps it. This is the signal scope_guard couldn't see before."""
        r = _runner()
        head_padding = "W CANN NPUCachingAllocator padding warning.\n" * 40
        tail_signal = "RuntimeError: AICORE error code 507035 aivec out of bounds"
        stderr = head_padding + tail_signal
        with patch("ascendc_devkit.adapters.npu.runner.subprocess.run",
                   return_value=_FakeCompleted("", returncode=-6, stderr=stderr)):
            result = r.execute(
                _op_dq(), [], 0, deploy_result=_deploy(),
                callable_target={"kind": "torch_op", "symbol": "s"},
            )
        assert "507035" not in result["error"], (
            "head truncation should drop the tail crash keyword (this assertion "
            "documents the OLD defect; the fix is error_tail carrying it)")
        assert "507035" in result["error_tail"]

    def test_timeout_flagged_and_runlog_written(self, tmp_path):
        """D2 defect D: run.log was skipped on timeout (write sat before the
        except) — yet run.log is scope_guard's designated crash-evidence file.
        Timeout must (a) flag failure_type=timeout and (b) still write run.log
        from the partial subprocess output."""
        r = _runner()
        partial_err = "RuntimeError: AclrtSynchronizeDeviceWithTimeout 507035"
        exc = subprocess.TimeoutExpired(
            cmd=["x"], timeout=120,
            output=b"partial stdout", stderr=partial_err.encode())
        with patch("ascendc_devkit.adapters.npu.runner.subprocess.run",
                   side_effect=exc):
            result = r.execute(
                _op_dq(), [], 0, deploy_result=_deploy(),
                callable_target={"kind": "torch_op", "symbol": "s"},
                log_dir=str(tmp_path),
            )
        assert result["failure_type"] == "timeout"
        assert result["timed_out"] is True
        assert result["returncode"] is None
        # run.log recovered from the timeout's partial output (defect D fix)
        run_log = (tmp_path / "run.log").read_text()
        assert "507035" in run_log

    def test_crash_dump_detected_when_written_during_run(self, tmp_path, monkeypatch):
        """D2 defect E: CANN writes exception_info.* on a fatal AICORE abort; its
        mere existence is a 100% crash signal no one checked. The dump is created
        DURING the subprocess (mirrors reality), so its mtime ≥ run_started_at."""
        monkeypatch.chdir(tmp_path)
        dump_dir = tmp_path / "extra-info" / "data-dump" / "0"

        def _spawn(*a, **k):
            dump_dir.mkdir(parents=True, exist_ok=True)
            (dump_dir / "exception_info.41.10.20260801140158042").write_bytes(b"\x00")
            return _FakeCompleted("", returncode=-6, stderr="fatal AICORE abort")

        r = _runner()
        with patch("ascendc_devkit.adapters.npu.runner.subprocess.run",
                   side_effect=_spawn):
            result = r.execute(
                _op_dq(), [], 0, deploy_result=_deploy(),
                callable_target={"kind": "torch_op", "symbol": "s"},
            )
        assert result["failure_type"] == "runtime_crash"
        assert result["crash_dump_path"].endswith(
            "exception_info.41.10.20260801140158042")

    def test_no_crash_dump_key_when_absent(self, tmp_path, monkeypatch):
        """Clean cwd (no exception_info dump) → no crash_dump_path key; the crash
        identity still comes from returncode (non-load-bearing enrichment)."""
        monkeypatch.chdir(tmp_path)
        r = _runner()
        with patch("ascendc_devkit.adapters.npu.runner.subprocess.run",
                   return_value=_FakeCompleted("", returncode=-6, stderr="boom")):
            result = r.execute(
                _op_dq(), [], 0, deploy_result=_deploy(),
                callable_target={"kind": "torch_op", "symbol": "s"},
            )
        assert result["failure_type"] == "runtime_crash"
        assert "crash_dump_path" not in result

    def test_clean_run_does_not_carry_failure_type(self):
        """Regression guard: the success path (returncode 0, parsed) must NOT be
        polluted with failure_type — it's a real precision result, not a crash."""
        r = _runner()
        with patch("ascendc_devkit.adapters.npu.runner.subprocess.run",
                   return_value=_FakeCompleted(_harness_stdout(
                       max_diff=0.0, golden_used=True,
                       case_details=[{"case": "c1", "outputs": [
                           {"index": 0, "passed": True, "dtype": "fp16",
                            "diff": 0.0}]}]))):
            result = r.execute(
                _op_dq(), [], 0, deploy_result=_deploy(),
                callable_target={"kind": "torch_op", "symbol": "s"},
            )
        assert result["passed"] is True
        assert "failure_type" not in result
        assert "returncode" not in result

    def test_result_propagates_bottleneck_and_golden_used(self):
        """execute 的成功路径结果必须回带 harness 报告的 ``bottleneck`` +
        ``golden_used``（ST test_npu.py + CLI UT 都断言 ``bottleneck``；precision_debug
        stage 据此区分真 kernel-vs-golden diff 与无 golden 运行）。

        Regression: 3c250fd 重写 runner 成功路径 return 时丢了 ``bottleneck``
        （harness 算了但 runner 没透传）→ ``result['bottleneck']`` KeyError / None。"""
        r = _runner()
        with patch("ascendc_devkit.adapters.npu.runner.subprocess.run",
                   return_value=_FakeCompleted(_harness_stdout(
                       max_diff=0.0, golden_used=True,
                       case_details=[{"case": "c1",
                                      "outputs": [{"index": 0, "passed": True,
                                                   "dtype": "fp16", "diff": 0.0}]}]))):
            result = r.execute(
                _op_dq(), [TestCase(name="c1",
                                    inputs=[{"name": "x", "shape": [4], "dtype": "fp16"}])],
                0, deploy_result=_deploy(),
                callable_target={"kind": "torch_op", "symbol": "s"},
            )
        assert result["bottleneck"] == "real_kernel_vs_golden"
        assert result["golden_used"] is True

    def test_result_bottleneck_no_golden(self):
        """无 golden → ``bottleneck='no_golden_reference'`` / ``golden_used=False``。"""
        r = _runner()
        with patch("ascendc_devkit.adapters.npu.runner.subprocess.run",
                   return_value=_FakeCompleted(_harness_stdout(
                       max_diff=0.5, golden_used=False))):
            result = r.execute(
                _op_dq(), [], 0, deploy_result=_deploy(),
                callable_target={"kind": "torch_op", "symbol": "s"},
                precision_threshold=1.0,
            )
        assert result["bottleneck"] == "no_golden_reference"
        assert result["golden_used"] is False


def _assigned_names(source: str) -> set[str]:
    """Module-level + nested names assigned anywhere in the harness source.

    Catches the P79 regression: the generated harness unconditionally
    references ``_cann_checker_used`` (final report) and ``_compare_tensors``
    (cann-bench path gate), but ``DevkitComparer`` (the default backend)
    injects no setup lines. If the template doesn't define their defaults,
    a real-NPU run NameError's at the final ``print(json.dumps(output))`` and
    never emits JSON → runner returns the max_diff=999.0 error sentinel.

    The UT mocks subprocess.run (§3.8), so the *generated harness* was never
    executed in UT and the bug only surfaced in ST. This guard inspects the
    harness SOURCE (ast) so the regression is caught without NPU.
    """
    import ast
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


class TestHarnessBackendContractVars:
    """P79 regression guard: the generated harness must DEFINE the backend-
    contract vars it references, for BOTH comparers.

    ``DevkitComparer.harness_setup_lines`` returns ``[]`` by design (UT pins
    this — abs-diff path uses harness-internal numpy, zero cann-bench import).
    So the template — not the comparer — owns the defaults. Without template
    defaults, ``DevkitComparer`` crashes the real harness with NameError
    (root cause of test_real_kernel_* max_diff=999.0 failures before this fix).
    """

    def _harness_for(self, comparer):
        r = _runner()
        op = OperatorSpec(name="add")
        tc = [TestCase(name="basic",
                       inputs=[{"name": "a", "shape": [8], "dtype": "fp16"},
                               {"name": "b", "shape": [8], "dtype": "fp16"}])]
        return r._build_test_harness(
            op, tc,
            golden_contract={"path": "/tmp/golden.py", "entry": "reference",
                             "input_type": "numpy"},
            deploy_result=_deploy(),
            callable_target={"kind": "torch_op", "symbol": "torch.ops.cann_bench.add"},
            rule=CompareRule(dtype_thresholds={"*": 1e-2}),
            comparer=comparer,
        )

    def test_devkit_comparer_harness_defines_contract_vars(self):
        """DevkitComparer injects nothing — template must still define the
        two contract vars or the harness NameError's at the final report."""
        from ascendc_devkit.adapters.npu.precision_comparer import DevkitComparer
        assigned = _assigned_names(self._harness_for(DevkitComparer()))
        assert "_cann_checker_used" in assigned, (
            "harness references _cann_checker_used in the final report but "
            "DevkitComparer injects no definition — template must own the default")
        assert "_compare_tensors" in assigned, (
            "harness references _compare_tensors in the cann-bench path gate "
            "but DevkitComparer injects no definition — template must own the default")

    def test_devkit_comparer_harness_defines_index_gather_vars(self):
        """proto idx 语义：模板无条件定义 ``_IGNORE_INDICES``/``_INDEX_GATHER``
        （两条比较路径都引用；空默认保证 add 类算子不 NameError）。"""
        from ascendc_devkit.adapters.npu.precision_comparer import DevkitComparer
        assigned = _assigned_names(self._harness_for(DevkitComparer()))
        assert "_IGNORE_INDICES" in assigned
        assert "_INDEX_GATHER" in assigned

    def test_cannbench_comparer_harness_flips_checker_used(self):
        """CannbenchComparer specializes: imports compare_tensors and sets
        ``_cann_checker_used = True`` on success (its injected lines own the
        specialization; the template provides the default)."""
        from ascendc_devkit.adapters.npu.precision_comparer import CannbenchComparer
        src = self._harness_for(CannbenchComparer())
        assert "_cann_checker_used = True" in src
        assert "compare_tensors as _compare_tensors" in src

    def test_devkit_harness_passes_native_refs(self):
        """完全对齐（fp64 golden + 同精度参考）：DevkitBackend 的 FALLBACK 比较
        compare_outputs 必须传 ``native_refs=_n_tensors``（fp64 golden 可用时）——
        否则 cpu_diff≡0，小值域/相消零容忍会把同精度 kernel 误判失败（gelu 复盘根因）。
        F1 兜底：fp64 golden 不可用（golden 不支持 fp64 输入）时 native_refs=None
        回退严格语义 + WARN，不把 case 打成 error。"""
        from ascendc_devkit.adapters.npu.precision_comparer import DevkitComparer
        src = self._harness_for(DevkitComparer())
        assert "native_refs=(_n_tensors if _fp64_ok else None)" in src, (
            "FALLBACK compare_outputs 必须传 native_refs（同精度 CPU 参考），"
            "否则零容忍误判（gelu 复盘根因）；fp64 不可用时须回退 None（F1）")
        assert "def _upcast_fp64" in src, "harness 必须定义 _upcast_fp64（fp64 golden）"
        assert "golden_np_list_fp64" in src, "FALLBACK 必须跑 fp64 golden（cann-bench fp64_cpu）"
        assert "fp64 golden 不可用" in src, (
            "F1：fp64 golden 抛异常须 WARN 留痕（可观测），不能静默崩溃成 case error")
        assert "golden_np_list_fp64[_v.index]" in src, (
            "F2/F3：FALLBACK 显示（golden_first10）须与判定同源（fp64 golden），"
            "不能用 native golden 误导调试")

    def test_cannbench_harness_passes_native_output(self):
        """完全对齐：CANN 分支 compare_tensors 必须传 ``native_output=_fp64_native_out``
        （真实评测 golden_precision=fp64_cpu 正是这样调用 cann-bench；fp64 golden 可用
        时即 native 参考）。F1 兜底：fp64 不可用 → native_output=None 回退严格语义。"""
        from ascendc_devkit.adapters.npu.precision_comparer import CannbenchComparer
        src = self._harness_for(CannbenchComparer())
        assert "native_output=_fp64_native_out" in src, (
            "CANN compare_tensors 必须传 native_output（同精度 CPU 参考），"
            "fp64 不可用时回退 None（F1）")
        assert "_upcast_fp64(_torch_inputs)" in src, "CANN 必须用 fp64 输入跑 fp64 golden"
        assert "fp64 golden 不可用" in src, "F1：fp64 golden 抛异常须 WARN 留痕"


class TestHarnessExtractionSnapshot:
    """A1 提取回归门：固定输入下 ``_build_test_harness`` 输出必须与 golden 逐字节相等。

    harness 模板（``_build_test_harness`` 内 ``lines=[...]`` ~490 行）外移到
    ``_harness_template.py``（``string.Template``）前后行为零变更。Q8 的
    ``sys.path.insert`` 注入（A2）会更新此 golden。
    """

    GOLDEN = Path(__file__).parent / "fixtures" / "harness_devkit_golden.txt"

    def _src(self) -> str:
        from ascendc_devkit.adapters.npu.precision_comparer import DevkitComparer
        r = _runner()
        op = OperatorSpec(name="add")
        tc = [TestCase(name="basic",
                inputs=[{"name": "a", "shape": [8], "dtype": "fp16"},
                        {"name": "b", "shape": [8], "dtype": "fp16"}])]
        return r._build_test_harness(
            op, tc,
            golden_contract={"path": "/tmp/g.py", "entry": "reference",
                             "input_type": "numpy"},
            deploy_result=_deploy(),
            callable_target={"kind": "torch_op", "symbol": "torch.ops.cann_bench.add"},
            rule=CompareRule(dtype_thresholds={"*": 1e-2}),
            comparer=DevkitComparer())

    def test_harness_matches_golden(self):
        """提取前后逐字节相等（A1 行为零变更回归门）。

        失败信息指向 golden 文件——若有意改动（如 Q8 注入），更新该 golden。
        """
        golden = self.GOLDEN.read_text()
        assert self._src() == golden, (
            "harness 输出与 golden 不符——若有意改动（如 Q8 注入），"
            "更新 tests/ut/adapters/fixtures/harness_devkit_golden.txt")

    def test_python_path_injected_when_present(self):
        """Q8: ``deploy_result.python_path`` 非空 → harness 烘进 ``sys.path.insert``，
        确定性压过 site-packages（``__import__`` 解析到 per-op deployed cann_bench，
        不落 stale 全局安装）。golden 的 ``_deploy().python_path == "/p"``。"""
        assert "sys.path.insert(0, '/p')  # Q8" in self._src()

    def test_python_path_omitted_when_empty(self):
        """Q8: ``python_path`` 空 → 不注入 ``sys.path.insert``（不留空行/空段）。"""
        from ascendc_devkit.adapters.npu.precision_comparer import DevkitComparer
        r = _runner()
        op = OperatorSpec(name="add")
        tc = [TestCase(name="basic",
                inputs=[{"name": "a", "shape": [8], "dtype": "fp16"}])]
        src = r._build_test_harness(
            op, tc,
            golden_contract={"path": "/tmp/g.py", "entry": "r", "input_type": "numpy"},
            deploy_result=SimpleNamespace(python_path="", install_path="/i",
                                          ld_library_path_add=""),
            callable_target={"kind": "torch_op", "symbol": "torch.ops.cann_bench.add"},
            rule=CompareRule(dtype_thresholds={"*": 1e-2}),
            comparer=DevkitComparer())
        assert "sys.path.insert" not in src

    def test_probe_logs_cann_bench_file_and_not_json_prefixed(self):
        """Q8 probe: harness 打印实际加载的 ``cann_bench.__file__``；探针行**不以
        ``{`` 开头**（runner L378 把 stdout 里 ``{`` 开头行当 JSON 解析）。"""
        src = self._src()
        assert "[harness]" in src and ".__file__" in src
        probe_lines = [l for l in src.split("\n") if "[harness]" in l]
        assert probe_lines, "expected at least one [harness] probe line"
        assert all(not l.lstrip().startswith("{") for l in probe_lines), (
            "probe line must not start with '{' — runner parses such stdout as JSON")

    def test_rendered_harness_apply_get_input_drops_scalars_for_npu_move(self):
        """Two contracts for _apply_get_input (cann-bench evaluator.py:208-227):
        (a) DROP non-tensor scalars — scatter_pa_kv_cache.get_input appends a
        ``cache_mode`` str; _run_kernel's npu-move would crash on it (``'str'
        has no attribute 'npu'``), scalars reach the kernel via ``**_attrs``.
        (b) KEEP None placeholders — conv1d (run 20260803-164157) get_input
        returns a proto-order tuple with None at the optional slot; dropping
        None collapsed the list → bind_golden_args positional consume mis-bound
        cache_indices onto query_start_loc → golden 'a Tensor with 3 elements'.
        cann-bench evaluator:218-222 keeps None (value-passed so golden's
        Optional param self-defaults). Structural signal (isinstance), §1.12;
        scatter_pa_kv_cache / conv1d named only as real-world origins."""
        import ast
        import types
        src = self._src()
        tree = ast.parse(src)
        fn = next((n for n in tree.body if isinstance(n, ast.FunctionDef)
                   and n.name == "_apply_get_input"), None)
        assert fn is not None, "rendered harness has no _apply_get_input"
        # torch.Tensor sentinel so isinstance works without a real torch install
        try:
            import torch as _torch
            _Tensor = _torch.Tensor
        except Exception:
            class _Tensor:
                pass
        import inspect as _inspect
        ns = {"torch": types.SimpleNamespace(Tensor=_Tensor), "inspect": _inspect}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), "<harness>", "exec"), ns)
        apply_get_input = ns["_apply_get_input"]

        t0, t1 = _Tensor(), _Tensor()
        # mimic scatter_pa_kv_cache.get_input's return: tensors + TensorList +
        # a trailing scalar (cache_mode) + a None optional slot (conv1d shape)
        ns["_get_input"] = lambda *a, **k: (t0, [t1], "PA_NZ", None)
        out = apply_get_input(["placeholder"], {"cache_mode": "PA_NZ"})

        # scalar "PA_NZ" dropped (would crash .npu()); Tensor + TensorList +
        # None placeholder KEPT (proto-order positional integrity — conv1d
        # run 20260803-164157: dropping None collapsed the list → bind_golden_args
        # mis-bound cache_indices onto query_start_loc). cann-bench evaluator:218-222.
        assert out == [t0, [t1], None], (
            "_apply_get_input must drop scalars but KEEP None placeholders — got %r" % (out,))

    def test_rendered_harness_apply_get_input_filters_unexpected_attrs(self):
        """F1（review 坐实）：attr 补齐后 _attrs 含全部 op_spec attrs，strict-signature
        的 get_input（无 **kwargs）会拒意外 kwarg——`_apply_get_input` 必须按 get_input
        签名过滤只传接受的 attr。有 **kwargs 的 get_input 不受影响（全传）。"""
        import ast
        import types
        import inspect as _inspect
        src = self._src()
        tree = ast.parse(src)
        fn = next((n for n in tree.body if isinstance(n, ast.FunctionDef)
                   and n.name == "_apply_get_input"), None)
        assert fn is not None
        try:
            import torch as _torch
            _Tensor = _torch.Tensor
        except Exception:
            class _Tensor:
                pass
        ns = {"torch": types.SimpleNamespace(Tensor=_Tensor), "inspect": _inspect}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), "<harness>", "exec"), ns)
        apply_get_input = ns["_apply_get_input"]

        # strict get_input：只接受 x + output_size（无 **kwargs）→ 意外 attr 被过滤
        ns["_get_input"] = lambda x, output_size=None: (x,)
        out = apply_get_input([_Tensor()],
                              {"output_size": [256, 256], "scale_factor": None,
                               "align_corners": False})
        # 只传了 get_input 接受的 attr（scale_factor/align_corners 被过滤，不 TypeError）
        assert len(out) == 1, f"strict get_input must not TypeError on unexpected attrs: {out}"

    def _harness_for_kind(self, kind: str, symbol: str) -> str:
        """substitute a harness for a given callable_kind (M1: probe must be safe
        for BOTH torch_op and pybind, not just the torch_op golden fixture)."""
        from ascendc_devkit.adapters.npu.precision_comparer import DevkitComparer
        r = _runner()
        op = OperatorSpec(name="add")
        tc = [TestCase(name="basic",
                inputs=[{"name": "a", "shape": [8], "dtype": "fp16"}])]
        return r._build_test_harness(
            op, tc,
            golden_contract={"path": "/tmp/g.py", "entry": "r", "input_type": "numpy"},
            deploy_result=_deploy(),
            callable_target={"kind": kind, "symbol": symbol},
            rule=CompareRule(dtype_thresholds={"*": 1e-2}),
            comparer=DevkitComparer())

    def test_pybind_harness_probe_is_nameerror_safe(self):
        """M1 回归守护：Q8 probe 引用 ``_ns``，而 ``_ns`` 只在 ``if callable_kind
        == 'torch_op'`` 分支内赋值；pybind 分支不执行该赋值 → probe ``if _ns``
        NameError，且 except handler 的 ``str(_ns)`` 再次 NameError（不被同 except
        捕获）→ harness 在跑到 cases loop 前崩溃（step-80 M1，已用运行时复现坐实）。

        修复 = 模板顶层预定义 ``_ns = ''``。本守护 ast 断言 ``_ns`` 在 Module 顶层
        赋值（非 If/Try 分支内），防预定义被回退。"""
        import ast
        src = self._harness_for_kind("pybind", symbol="mymod.op")
        tree = ast.parse(src)
        toplevel_assigned = {
            t.id for node in tree.body if isinstance(node, ast.Assign)
            for t in node.targets if isinstance(t, ast.Name)
        }
        assert "_ns" in toplevel_assigned, (
            "M1 regression: _ns not pre-bound at module top level — the pybind "
            "harness's probe (`if _ns`) will NameError. Keep `_ns = ''` before "
            "the kernel-resolve try-block.")

    def test_both_callable_kinds_produce_valid_python(self):
        """torch_op + pybind harness 都必须是合法 Python（py_compile，M1：
        确保新加的 probe 对两种 callable_kind 都不引入语法/编译错）。"""
        import py_compile
        import tempfile
        for kind, sym in [("torch_op", "torch.ops.cann_bench.add"),
                          ("pybind", "mymod.op")]:
            src = self._harness_for_kind(kind, sym)
            with tempfile.NamedTemporaryFile(
                    suffix=".py", mode="w", delete=False) as f:
                f.write(src)
                path = f.name
            py_compile.compile(path, doraise=True)

    def test_golden_call_is_name_keyed_not_positional(self):
        """P135 回归守护：golden 调用必须按签名 name-keyed 绑定（``bind_golden_args``），
        不能用朴素位置 ``golden(*tensors, **attrs)``。

        标量在前的 golden（advance_step_v2(num_seqs, num_queries, block_size,
        input_tokens, ...)）下，位置绑定会让 tensors[0] 落到 num_seqs，再被
        attrs['num_seqs'] 二次绑定 → ``got multiple values for argument 'num_seqs'``。
        kernel 侧（op-plugin 张量在前）不受影响，缺陷单在 golden 调用路径。

        本守护 ast/源断言：bind_golden_args 被内联进生成 harness，且 _golden_wrap
        与 cann-checker 两处 golden 调用都走 bind_golden_args（不再有 ``_golden_raw(*...,
        **_attrs)``）。独立于 byte-exact snapshot，防 P135 被无声回退。"""
        src = self._src()
        # bind_golden_args 源被内联（runner.py getsource 注入 $golden_bind_helper）
        assert "def bind_golden_args(fn, tensors, attrs):" in src, (
            "P135 regression: bind_golden_args not inlined into the harness — "
            "golden calls would fall back to positional binding.")
        # 两处 golden 调用都走 name-keyed 绑定
        assert "_golden_raw(**bind_golden_args(" in src, (
            "P135 regression: a golden call does not use bind_golden_args.")
        # 不残留朴素位置 golden 调用（kernel 的 kernel_fn(*..., **_attrs) 不在此列）
        assert "_golden_raw(*_inputs, **_attrs)" not in src, (
            "P135 regression: naive positional golden call _golden_raw(*_inputs, **_attrs) present.")
        assert "_golden_raw(*_torch_inputs, **_attrs)" not in src, (
            "P135 regression: naive positional golden call _golden_raw(*_torch_inputs, **_attrs) present.")

    def test_golden_wrap_handles_tensorlist_from_numpy(self):
        """F3: ``_golden_wrap`` 的 from_numpy 必须对 TensorList（list-of-ndarray）
        分支处理（``[torch.from_numpy(t) for t in a]``）。原 ``[torch.from_numpy(a)
        for a in _inputs]`` 对 TensorList 必炸——``torch.from_numpy(list)`` 抛
        ``TypeError('expected np.ndarray (got list)')``，batch 20260731-132818
        multi_add 的 x1 TensorList 在 fallback numpy 路径下崩（一度误判 golden
        上游缺陷，实为 harness fallback 自身的 TensorList 盲区）。"""
        src = self._src()
        assert "isinstance(a, list)" in src, (
            "F3 regression: _golden_wrap 缺 TensorList 分支，from_numpy(list) 会炸")
        assert "[torch.from_numpy(t) for t in a]" in src

    def test_harness_restores_proto_order_none_placeholders(self):
        """conv1d 回归(run 20260803-164157): cann-bench CSV loader 删 null shape
        → 压实 inputs（短于 proto）。harness 的 ``_restore_proto_order`` 必须按
        ``proto_idx`` 把压实 tensors 散回 proto 顺序，缺省 optional 位填 None，
        使位置式 get_input / bind / kernel 对齐签名（query_start_loc 缺省 → slot 3
        是 None，而非 cache_indices 错绑）。位置消费 + 占位还原 = 构造性消灭错位，
        对齐 cann-bench evaluator（保留 None 直传 golden 让其兜底）。"""
        import ast
        from ascendc_devkit.adapters.npu.precision_comparer import DevkitComparer
        from ascendc_devkit.domain.operator import TensorSpec
        r = _runner()
        op = OperatorSpec(name="opt_op", inputs=[TensorSpec(name="a"),
                          TensorSpec(name="opt"), TensorSpec(name="b"),
                          TensorSpec(name="c")])
        tc = [TestCase(name="opt_absent", inputs=[
            {"name": "input_0", "shape": [2], "dtype": "fp16"},
            {"name": "input_2", "shape": [2], "dtype": "fp16"},
            {"name": "input_3", "shape": [2], "dtype": "fp16"}])]
        src = r._build_test_harness(
            op, tc,
            golden_contract={"path": "/tmp/g.py", "entry": "r", "input_type": "numpy"},
            deploy_result=_deploy(),
            callable_target={"kind": "torch_op", "symbol": "torch.ops.cann_bench.op"},
            rule=CompareRule(dtype_thresholds={"*": 1e-2}), comparer=DevkitComparer())
        # input_names baked in proto order (incl. optional)
        assert "input_names = ['a', 'opt', 'b', 'c']" in src
        # exec _restore_proto_order, verify None placeholder at the absent slot
        tree = ast.parse(src)
        fn = next((n for n in tree.body if isinstance(n, ast.FunctionDef)
                   and n.name == "_restore_proto_order"), None)
        assert fn is not None, "rendered harness has no _restore_proto_order"
        ns = {"input_names": ["a", "opt", "b", "c"]}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), "<h>", "exec"), ns)
        restore = ns["_restore_proto_order"]
        t0, t1, t2 = object(), object(), object()
        # compact gen (a,b,c) + proto_idx (0,2,3) → opt(1) absent
        out = restore([t0, t1, t2], [{"proto_idx": 0}, {"proto_idx": 2}, {"proto_idx": 3}])
        assert out == [t0, None, t1, t2], (
            "_restore_proto_order must place None at the absent proto slot "
            "(opt=1) — got %r" % (out,))

    def test_harness_serializes_explicit_proto_idx(self):
        """runner 只读 entry 的显式 ``proto_idx``（各生产方统一写入——loader /
        test-design 适配器），序列化进 harness —— ``_restore_proto_order`` 依赖它
        还原占位。位置不再从 ``input_{i}`` name 推断（§1.15 单点；旧猜名字
        逻辑已删，无字段时唯一退化为压实位置）。"""
        from ascendc_devkit.adapters.npu.precision_comparer import DevkitComparer
        from ascendc_devkit.domain.operator import TensorSpec
        r = _runner()
        op = OperatorSpec(name="opt_op", inputs=[TensorSpec(name="a"),
                          TensorSpec(name="opt"), TensorSpec(name="b")])
        # loader dropped opt (idx 1) → case carries input_0/input_2 with the
        # original proto positions as an EXPLICIT field
        tc = [TestCase(name="x", inputs=[
            {"name": "input_0", "shape": [2], "dtype": "fp16", "proto_idx": 0},
            {"name": "input_2", "shape": [2], "dtype": "fp16", "proto_idx": 2}])]
        src = r._build_test_harness(
            op, tc,
            golden_contract={"path": "/tmp/g.py", "entry": "r", "input_type": "numpy"},
            deploy_result=_deploy(),
            callable_target={"kind": "torch_op", "symbol": "torch.ops.cann_bench.op"},
            rule=CompareRule(dtype_thresholds={"*": 1e-2}), comparer=DevkitComparer())
        assert "'proto_idx': 0" in src and "'proto_idx': 2" in src
        assert "'proto_idx': 1" not in src, (
            "absent optional (opt idx 1) must not be serialized as a proto_idx")


class TestHarnessDynamicNestedShape:
    """Q3-multi_add: a ``param_type=DYNAMIC`` (Tensor[]) input with a nested
    ``list[list[int]]`` shape must flow through ``_build_test_harness`` end-to-end.

    The validator (Q3 fix, runner.py L571) accepts nested shapes for DYNAMIC
    inputs, and the harness template inlines them as nested literals its runtime
    ``isinstance(i['shape'][0], list)`` branch normalizes. Pre-fix,
    ``_build_test_harness`` raised ``HarnessContractError`` at ``_validate_case_form``
    — so a Tensor[] op produced NO harness (batch ``20260727_225324`` multi_add:
    ``0/0 cases ran``).

    This is the right level (not a heavy NPU ST): the fix is pure-Python logic
    (validator + template normalization); a real Tensor[] kernel doesn't exist as
    a simple deployable op, so an NPU ST would need enormous scaffolding for
    marginal value over this source-level guard (§3.11 — don't force heavy when a
    lighter test suffices; §3.9 — only SDK/agent-real-behavior links need real ST).
    """

    def _harness(self, op, tc=None):
        from ascendc_devkit.adapters.npu.precision_comparer import DevkitComparer
        r = _runner()
        return r._build_test_harness(
            op, tc,
            golden_contract={"path": "/tmp/g.py", "entry": "r", "input_type": "numpy"},
            deploy_result=_deploy(),
            callable_target={"kind": "torch_op", "symbol": "torch.ops.cann_bench.op"},
            rule=CompareRule(dtype_thresholds={"*": 1e-2}),
            comparer=DevkitComparer())

    def test_nested_shape_accepted_and_inlined(self):
        """DYNAMIC nested shape ``[[152, 7680]]`` builds a harness without raising
        and inlines the nested shape (the template normalizes it at runtime)."""
        op = OperatorSpec(name="multi_add",
                          inputs=[TensorSpec(name="x1", param_type="DYNAMIC")])
        tc = [TestCase(name="c1",
                       inputs=[{"name": "x1", "shape": [[152, 7680]], "dtype": "fp16"}])]
        src = self._harness(op, tc)  # pre-fix: raised HarnessContractError here
        # inner shape inlined (pprint keeps small nested lists contiguous)
        assert "[152, 7680]" in src, (
            "nested Tensor[] shape not inlined into harness — Q3 validator should "
            "accept list[list[int]] for DYNAMIC inputs")
        # the nested-normalization branch is present in the template
        assert "isinstance(i['shape'][0], list)" in src

    def test_multiple_tensors_inlined(self):
        """DYNAMIC variadic list of several tensors (multi_add: N tensors summed):
        ``[[1, 72], [3, 4]]`` inlines both inner shapes."""
        op = OperatorSpec(name="multi_add",
                          inputs=[TensorSpec(name="x1", param_type="DYNAMIC")])
        tc = [TestCase(name="c1",
                       inputs=[{"name": "x1", "shape": [[1, 72], [3, 4]], "dtype": "fp16"}])]
        src = self._harness(op, tc)
        assert "[1, 72]" in src and "[3, 4]" in src

    def test_required_flat_shape_still_inlines_flat(self):
        """Non-regression: a REQUIRED input's flat shape still inlines flatly."""
        op = OperatorSpec(name="add",
                          inputs=[TensorSpec(name="a", param_type="REQUIRED")])
        tc = [TestCase(name="c1",
                       inputs=[{"name": "a", "shape": [8, 16], "dtype": "fp16"}])]
        src = self._harness(op, tc)
        assert "[8, 16]" in src

    def test_tensorlist_nested_shape_accepted_by_structure(self):
        """TensorList 输入经 is_list 结构信号派生 DYNAMIC（上游 P2：
        ``OperatorSpec.from_dict`` 对 ``is_list=true`` 派生 param_type=DYNAMIC）
        → 校验放行嵌套 shape，harness 内联嵌套 shape。REQUIRED 直接声明 + 嵌套
        仍拒绝（§1.13 契约矛盾大声失败，test_runner_contract 锁定）；TensorList
        放行统一走 is_list → DYNAMIC 派生唯一通路。"""
        op = OperatorSpec.from_dict({
            "name": "lstm",
            "inputs": [
                {"name": "x", "dtype": ["fp32"]},
                {"name": "weight_ih", "dtype": ["fp32"], "is_list": True,
                 "param_type": "REQUIRED"},
            ],
        })
        tc = [TestCase(name="c1", inputs=[
            {"name": "x", "shape": [10, 4, 64], "dtype": "fp32"},
            {"name": "weight_ih", "shape": [[128, 64]], "dtype": "fp32"}])]
        src = self._harness(op, tc)
        assert "[10, 4, 64]" in src and "[128, 64]" in src

    def test_malformed_nested_shape_still_rejected(self):
        """TensorList 结构信号只放行「每个元素都是 int list」的嵌套；元素本身不是
        int list（如 [[1, 2], 3] 混入标量）仍拒绝——结构信号不放宽到任意嵌套。"""
        op = OperatorSpec(name="op", inputs=[TensorSpec(name="x")])
        tc = [TestCase(name="c1",
                       inputs=[{"name": "x", "shape": [[1, 2], 3], "dtype": "fp16"}])]
        from ascendc_devkit.domain.exceptions import HarnessContractError
        with pytest.raises(HarnessContractError):
            self._harness(op, tc)

    def test_from_dict_to_harness_accepts_dynamic_nested_shape(self):
        """§1.10 根治端到端 (P3 real halt): build the op_spec the way production
        does — ``OperatorSpec.from_dict(requirement_dict)`` where the DYNAMIC
        input ``x1`` has NO explicit shape (only ``param_type``) — then feed the
        harness a nested ``[[152,7680]]`` case. Pre-fix, ``from_dict`` sank x1
        into attrs so ``op_spec.inputs`` was empty and ``_validate_case_form``
        rejected the correct nested shape (multi_add halted precision_debug).
        This test would fail without the ``_route`` business-semantic judature —
        it is the assertion GLM's design_spec-only fix never made (it reconciled
        design_spec, which the harness never reads)."""
        op = OperatorSpec.from_dict({
            "name": "multi_add_rms_norm_dynamic_quant",
            "inputs": [
                {"name": "x1", "param_type": "DYNAMIC", "dtype": ["fp16"]},
                {"name": "x2", "param_type": "REQUIRED", "dtype": ["fp16"]},
                {"name": "gamma", "param_type": "REQUIRED", "dtype": ["fp16"]},
            ],
            "outputs": [{"name": "y", "param_type": "REQUIRED", "dtype": ["fp16"]}],
        })
        # from_dict must keep x1 in inputs (position 0) with DYNAMIC preserved
        assert op.inputs and op.inputs[0].name == "x1"
        assert op.inputs[0].param_type == "DYNAMIC"
        tc = [TestCase(name="c0", inputs=[
            {"name": "x1", "shape": [[152, 7680]], "dtype": "fp16"},
            {"name": "x2", "shape": [152, 7680], "dtype": "fp16"},
            {"name": "gamma", "shape": [7680], "dtype": "fp16"}])]
        src = self._harness(op, tc)   # pre-fix: raised HarnessContractError
        assert "[152, 7680]" in src



class TestBuildHarnessEmptyDtypeInheritance:
    """改动 B（docs/plan/case-dtype-broadcast/）：空/缺失 dtype 继承用例声明 dtype。

    旧 state_snapshot 空串残值（run 20260805-100200-c00f72 同源）在 runner 烘焙时应
    继承用例首声明 dtype，而非空串穿透（CannbenchBackend ValueError）或静默降级 fp16
    （DevkitBackend）。仅存量防崩，不冒充合法语义（合法广播由 loader 承担）。
    """

    def _cases_dtypes(self, inputs):
        from ascendc_devkit.adapters.npu.precision_comparer import DevkitComparer
        r = _runner()
        op = OperatorSpec(name="add")
        tc = [TestCase(name="basic", inputs=inputs)]
        src = r._build_test_harness(
            op, tc,
            golden_contract={"path": "/tmp/g.py", "entry": "reference",
                             "input_type": "numpy"},
            deploy_result=_deploy(),
            callable_target={"kind": "torch_op", "symbol": "torch.ops.cann_bench.add"},
            rule=CompareRule(dtype_thresholds={"*": 1e-2}),
            comparer=DevkitComparer(),
        )
        import ast
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id == "test_cases":
                        cases = ast.literal_eval(node.value)
                        return [i["dtype"] for i in cases[0]["inputs"]]
        raise AssertionError("test_cases 赋值未在 harness 中找到")

    def test_stale_empty_dtype_inherits_case_declared(self):
        """旧快照空串残值：[fp32, '', ''] → 3 输入全继承 fp32（WARN 触发），
        而非 '' 穿透 / 静默降级 fp16。"""
        dtypes = self._cases_dtypes([
            {"name": "input_0", "shape": [8], "dtype": "fp32"},
            {"name": "input_1", "shape": [8], "dtype": ""},
            {"name": "input_2", "shape": [8], "dtype": ""},
        ])
        assert dtypes == ["fp32", "fp32", "fp32"]

    def test_all_empty_dtype_falls_back_fp16(self):
        """全用例无 dtype 声明 → 既有 fp16 默认不破坏。"""
        dtypes = self._cases_dtypes([
            {"name": "input_0", "shape": [8]},
            {"name": "input_1", "shape": [8]},
        ])
        assert dtypes == ["fp16", "fp16"]

    def test_runner_full_dtype_unchanged(self):
        """全声明 dtype 用例 → 原样，无继承改写。"""
        dtypes = self._cases_dtypes([
            {"name": "input_0", "shape": [8], "dtype": "bf16"},
            {"name": "input_1", "shape": [8], "dtype": "int32"},
        ])
        assert dtypes == ["bf16", "int32"]

    def test_stale_empty_dtype_warns_with_input_idx(self, capsys):
        """WARN 触发且消息带正确 input 序号 + 继承值（§1.3 可观测）。
        回归 runner.py 曾把 case 序号 _idx 误标成 input 序号——input_1/2 空 dtype
        应打 'input 1'/'input 2'，而非旧实现的 'input 0'（case 序号）。"""
        dtypes = self._cases_dtypes([
            {"name": "input_0", "shape": [8], "dtype": "fp32"},
            {"name": "input_1", "shape": [8], "dtype": ""},
            {"name": "input_2", "shape": [8], "dtype": ""},
        ])
        assert dtypes == ["fp32", "fp32", "fp32"]
        err = capsys.readouterr().err
        assert "input 1 dtype 为空/缺失" in err, err
        assert "input 2 dtype 为空/缺失" in err, err
        assert err.count("继承用例声明 dtype='fp32'") >= 2, err

    def test_hetero_dtype_stale_warn_flags_untrusted(self, capsys):
        """异构 dtype 用例（int32 索引 + fp16 数据）的空输入继承首个声明 dtype，
        但 WARN 必须标注『异构 dtype，继承值不可信』（m3：猜测不冒充合法语义）。"""
        dtypes = self._cases_dtypes([
            {"name": "input_0", "shape": [8], "dtype": "fp16"},
            {"name": "input_1", "shape": [8], "dtype": "int32"},
            {"name": "input_2", "shape": [8], "dtype": ""},
        ])
        assert dtypes == ["fp16", "int32", "fp16"]
        err = capsys.readouterr().err
        assert "input 2 dtype 为空/缺失" in err, err
        assert "异构 dtype，继承值仅防崩、不可信" in err, err

    def test_all_empty_warn_says_framework_default(self, capsys):
        """全用例无 dtype 声明 → 回退 fp16 的 WARN 措辞不冒充『用例声明』。"""
        dtypes = self._cases_dtypes([
            {"name": "input_0", "shape": [8]},
            {"name": "input_1", "shape": [8]},
        ])
        assert dtypes == ["fp16", "fp16"]
        err = capsys.readouterr().err
        assert "用例无 dtype 声明，回退框架默认 fp16" in err, err


class TestOptionalOutputAdapter:
    """optional 输出适配：golden union（省略尾部 optional 输出单返回）vs kernel
    proto 双输出（含 None 占位）→ harness 右补 None 对齐后交给比较器。

    比较器（cann-bench compare_tensors / devkit compare_outputs）原生处理双边
    None 跳过、单边 None 判 fail、数量不匹配 fail——harness 只负责右补对齐。
    """

    def _src_for_outputs(self, outputs):
        from ascendc_devkit.adapters.npu.precision_comparer import DevkitComparer
        r = _runner()
        op = OperatorSpec(name="unique", outputs=outputs)
        tc = [TestCase(name="basic",
                       inputs=[{"name": "x", "shape": [8], "dtype": "int32"}],
                       attrs={"return_inverse": False})]
        return r._build_test_harness(
            op, tc,
            golden_contract={"path": "/tmp/g.py", "entry": "reference",
                             "input_type": "numpy"},
            deploy_result=_deploy(),
            callable_target={"kind": "torch_op",
                             "symbol": "torch.ops.cann_bench.unique"},
            rule=CompareRule(dtype_thresholds={"*": 1e-2}),
            comparer=DevkitComparer(),
        )

    def test_injects_output_names_including_optional(self):
        """proto outputs 名（完整顺序含 optional 位）注入 output_names。"""
        src = self._src_for_outputs([
            TensorSpec(name="y", dtype="int32"),
            TensorSpec(name="inverse", dtype="int64", param_type="OPTIONAL"),
        ])
        assert "output_names = ['y', 'inverse']" in src, src[:400]

    def test_kernel_and_golden_outputs_padded_to_proto_len(self):
        """CANN 路径 kernel/golden 输出均右补 None 对齐 proto 输出数后传比较器
        （不再取 [0] 特判）；_run_kernel 对 None 输出透传不 .cpu()。"""
        src = self._src_for_outputs([
            TensorSpec(name="y", dtype="int32"),
            TensorSpec(name="inverse", dtype="int64", param_type="OPTIONAL"),
        ])
        assert "None if _o is None else _o.cpu()" in src
        # kernel/golden 两侧均右补到 proto 输出数（CANN + FALLBACK 两路径）
        assert src.count("_normalize_outputs(_run_kernel(") == 2
        assert src.count("len(output_names)") >= 2
        # compare 调用整体传右补列表，无 [0] 特判
        assert "output=_k_tensors," in src and "golden=_g_tensors," in src

    def test_normalize_outputs_pads_none_and_keeps_extra(self):
        """右补 None 到 proto 输出数；超出 proto 的输出不截断（数量不匹配
        交给比较器诚实判 fail）。"""
        import ast
        src = self._src_for_outputs([
            TensorSpec(name="y", dtype="int32"),
            TensorSpec(name="inverse", dtype="int64", param_type="OPTIONAL"),
        ])
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_normalize_outputs":
                fn_src = ast.get_source_segment(src, node)
                break
        else:
            raise AssertionError("_normalize_outputs 未在 harness 中生成")
        ns: dict = {}
        exec(fn_src, ns)
        f = ns["_normalize_outputs"]
        sentinel = object()
        # 单输出右补 None（golden union 省略尾部 optional 的场景）
        assert f(sentinel, 2) == [sentinel, None]
        # (y, None) kernel 双输出原样保持
        assert f((sentinel, None), 2) == [sentinel, None]
        # 超出 proto 输出数不截断（交给比较器数量不匹配 fail）
        assert f((sentinel, sentinel, sentinel), 2) == [sentinel, sentinel, sentinel]

    def test_display_lists_tolerate_none(self):
        """display（kernel_first10 / golden_first10）对 None 输出透传不崩；
        first_n(None) 返回空列表。"""
        import ast
        src = self._src_for_outputs([
            TensorSpec(name="y", dtype="int32"),
            TensorSpec(name="inverse", dtype="int64", param_type="OPTIONAL"),
        ])
        assert "None if o is None else" in src
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "first_n":
                fn_src = ast.get_source_segment(src, node)
                break
        else:
            raise AssertionError("first_n 未在 harness 中生成")
        ns: dict = {"np": __import__("numpy")}
        exec(fn_src, ns)
        assert ns["first_n"](None, 10) == []


class TestHarnessAttrsInputAlias:
    """cann-bench 约定：optional 输入在 attrs 列以 ``null`` 占位（quant_matmul
    offset/pertoken_scale/bias），官方 ``param_builder.build_params_by_proto_order``
    对与输入同名的 attr key 忽略（params 已含输入键）。runner 序列化时过滤同名
    key，防位置 + 关键字重复传参（kernel ``got multiple values for argument``），
    真 attr 保留——§1.13 忠实消费上游约定，非工程私改。"""

    def _harness(self, op, tc=None):
        from ascendc_devkit.adapters.npu.precision_comparer import DevkitComparer
        r = _runner()
        if tc is None:
            tc = [TestCase(name="basic",
                           inputs=[{"name": "x", "shape": [8], "dtype": "fp16"}],
                           attrs=op)]
            op = OperatorSpec(name="test_op", inputs=[TensorSpec(name="x")])
        return r._build_test_harness(
            op, tc,
            golden_contract={"path": "/tmp/g.py", "entry": "r", "input_type": "numpy"},
            deploy_result=_deploy(),
            callable_target={"kind": "torch_op", "symbol": "torch.ops.cann_bench.op"},
            rule=CompareRule(dtype_thresholds={"*": 1e-2}),
            comparer=DevkitComparer())

    def test_attrs_keys_aliasing_input_names_dropped(self):
        """quant_matmul 场景：attrs 含 offset/pertoken_scale/bias（输入占位，null）
        + output_dtype（真 attr）。过滤后 harness 只含真 attr——防 kernel 收到
        位置 offset + 关键字 offset 的重复传参崩。"""
        op = OperatorSpec(name="quant_matmul", inputs=[
            TensorSpec(name="x1"), TensorSpec(name="x2"), TensorSpec(name="scale"),
            TensorSpec(name="offset"), TensorSpec(name="pertoken_scale"),
            TensorSpec(name="bias"),
        ])
        tc = [TestCase(name="c1", inputs=[
            {"name": "input_0", "shape": [1024, 3584], "dtype": "int8"},
            {"name": "input_1", "shape": [3584, 3584], "dtype": "int8"},
            {"name": "input_2", "shape": [3584], "dtype": "fp32"}],
            attrs={"offset": None, "pertoken_scale": None, "bias": None,
                   "output_dtype": "float16"})]
        src = self._harness(op, tc)  # pre-fix: HarnessContractError (None attr)
        # 注意不能断言裸 "offset"：_input_names 序列化必然含它（proto 输入名）。
        # 必须匹配 attrs 字典的序列化形态（pprint 单引号键 + ": None" 值）。
        assert "'offset': None" not in src, "与输入同名的 attr 占位必须被过滤"
        assert "'output_dtype': 'float16'" in src, "真 attr 必须保留"

    def test_true_attrs_kept_when_no_alias(self):
        """无同名冲突时 attrs 原样透传（回归：常规算子 attrs 不受过滤影响）。"""
        op = OperatorSpec(name="softmax", inputs=[TensorSpec(name="x")],
                          attrs={})
        tc = [TestCase(name="c1",
                       inputs=[{"name": "x", "shape": [8], "dtype": "fp16"}],
                       attrs={"dim": 0})]
        src = self._harness(op, tc)
        assert "dim" in src and "0" in src

    def test_inf_attr_serialized_as_sentinel_not_bare(self):
        """``float('inf')`` attr → ``'__INF__'`` 哨兵串，绝不漏成裸 ``inf``。

        断言带 attrs key（``scalar``），区别于模板 ``_resolve_vr`` 里固有的
        ``'__INF__'`` 字面量——否则模板自带哨兵会让测试假绿。"""
        src = self._harness({"scalar": float("inf")})
        assert "'scalar': '__INF__'" in src, (
            "float('inf') attr must serialize as '__INF__' sentinel — bare inf leaks "
            "into harness attrs and NameError's at import (20260806-034053 deploy smoke)")
        assert "'scalar': inf" not in src, (
            "bare inf token leaked into harness attrs — pprint wrote float('inf') "
            "as the unqualified name `inf` (NameError at harness import)")

    def test_nan_and_ninf_attrs_sentinels(self):
        src = self._harness({"a": float("nan"), "b": float("-inf")})
        assert "'a': '__NAN__'" in src
        assert "'b': '__NINF__'" in src
        # 裸 nan/-inf 不应漏进 attrs（区别于模板 _resolve_vr 固有哨兵）
        assert "'a': nan" not in src
        assert "'b': -inf" not in src

    def test_mixed_attrs_preserve_finite_and_string(self):
        """有限数值 + 非数字串原样保留，仅 inf/nan 走哨兵。"""
        src = self._harness({"scalar": float("inf"), "axis": -1, "mode": "NHWC"})
        assert "'scalar': '__INF__'" in src
        assert "'axis': -1" in src
        assert "'mode': 'NHWC'" in src
        assert "'scalar': inf" not in src

    def test_finite_float_attr_unchanged(self):
        """有限 float 不误转哨兵（回归守护：pre/post-fix 都应通过）。"""
        src = self._harness({"eps": 1e-6})
        assert "'eps': 1e-06" in src
        assert "'eps': '__INF__'" not in src

    def test_cast_attr_round_trips_sentinels(self):
        """harness 侧 ``_cast_attr`` 把哨兵解码回 float（镜像 ranges 的 ``_resolve_vr``）。

        从生成 harness 源码 ast 提取 ``_cast_attr`` exec，验 round-trip + 非回归。"""
        import ast
        import math
        src = self._harness({"scalar": float("inf")})
        tree = ast.parse(src)
        fn = next((n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == "_cast_attr"), None)
        assert fn is not None, "rendered harness has no _cast_attr"
        ns = {}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), "<h>", "exec"), ns)
        cast = ns["_cast_attr"]
        assert math.isinf(cast("__INF__")) and cast("__INF__") > 0
        assert math.isinf(cast("__NINF__")) and cast("__NINF__") < 0
        assert math.isnan(cast("__NAN__"))
        # 非回归：有限数值串仍 float()，非数字串原样返回
        assert cast("3.0") == 3.0
        assert cast("NHWC") == "NHWC"


class TestHarnessAttrFillOptionalPlaceholder:
    """模式1-attrs 喂参缺口（20260810 批 resize_bilinear run_tests 崩根因）：harness
    按 op_spec 声明补齐用例缺的 attrs——optional→None、有默认→默认值，镜像输入侧
    None 占位语义（§2.5）。m.def 把 `float[2]? scale_factor` 声明为可选类型但无默认
    → torch 要求 kwarg 必须传，用例只有 output_size 时 harness 必须补 scale_factor=None。
    结构信号（op_spec 声明）驱动，不认算子名（§1.12）。"""

    def _harness(self, op, tc):
        from ascendc_devkit.adapters.npu.precision_comparer import DevkitComparer
        r = _runner()
        return r._build_test_harness(
            op, tc,
            golden_contract={"path": "/tmp/g.py", "entry": "r", "input_type": "numpy"},
            deploy_result=_deploy(),
            callable_target={"kind": "torch_op", "symbol": "torch.ops.cann_bench.op"},
            rule=CompareRule(dtype_thresholds={"*": 1e-2}),
            comparer=DevkitComparer())

    def test_renders_attr_specs_and_fill_loop(self):
        from ascendc_devkit.domain.operator import AttrSpec
        op = OperatorSpec(name="op", attrs={
            "output_size": AttrSpec(name="output_size", type="list[int]", default=None),
            "scale_factor": AttrSpec(name="scale_factor", type="list[float]", default=None),
            "align_corners": AttrSpec(name="align_corners", type="bool", default=False),
        })
        tc = [TestCase(name="c1", inputs=[{"name": "x", "shape": [8], "dtype": "fp16"}],
                       attrs={"output_size": [256, 256], "align_corners": False})]
        src = self._harness(op, tc)
        # op_spec attrs 烘进模板（含 default 语义）
        assert "attr_specs = [" in src
        assert "'output_size'" in src and "'scale_factor'" in src
        # 补齐循环：用例缺的 attr → None / 默认值
        assert "if _aspec[\"name\"] not in _attrs:" in src
        assert "_aspec.get(\"default\")" in src or "_aspec.get('default')" in src

    def test_fill_loop_produces_none_for_omitted_optional(self):
        """模拟渲染后 harness 的补齐逻辑：用例只有 output_size/align_corners，
        scale_factor 缺失 → 补齐为 None（m.def 要求 kwarg 存在，None 合法）。"""
        attr_specs = [
            {"name": "output_size", "default": None},
            {"name": "scale_factor", "default": None},
            {"name": "align_corners", "default": False},
        ]
        _attrs = {"output_size": [256, 256], "align_corners": False}
        for _aspec in attr_specs:
            if _aspec["name"] not in _attrs:
                _attrs[_aspec["name"]] = _aspec.get("default")
        assert _attrs == {"output_size": [256, 256], "align_corners": False,
                          "scale_factor": None}
