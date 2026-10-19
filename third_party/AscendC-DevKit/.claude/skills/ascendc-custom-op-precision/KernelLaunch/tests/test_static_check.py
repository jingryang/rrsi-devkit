"""Unit tests for the built-in static check in KernelLaunch.

Covers:
- KernelLaunch.static_check standalone API (CheckResult / StaticCheckReport /
  RegBaseChecker / check_regbase_source / auto_detect_kernel_name)
- KernelLauncher.locate_op_source / static_check integration
- Optional auto static-check before compile()/run() when enabled
"""

import os
import pytest
from unittest.mock import MagicMock, patch

from KernelLaunch import KernelLauncher, check_regbase_source, auto_detect_kernel_name
from KernelLaunch.static_check import (
    RegBaseChecker,
    StaticCheckReport,
    CheckResult,
)


def find_check(report, name):
    for r in report.results:
        if r.name == name:
            return r
    raise AssertionError(f"Check {name!r} not found in report")


def _make_dirs(path):
    """Create nested directories, bypassing the os.makedirs mock."""
    missing = []
    p = path
    while not os.path.isdir(p):
        missing.append(p)
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    for part in reversed(missing):
        os.mkdir(part)


def _write_source(src_dir, filename, content):
    _make_dirs(src_dir)
    with open(os.path.join(src_dir, filename), "w") as f:
        f.write(content)


# --------------------------------------------------------------------------- #
# Built-in checker API
# --------------------------------------------------------------------------- #
class TestBuiltInChecker:
    def test_check_regbase_source_passes(self):
        source = '''
template <typename T>
__simd_vf__ inline void GoodVf(__ubuf__ T* dst, uint16_t n)
{
    for (uint16_t i = 0; i < n; ++i) {
        AscendC::Reg::RegTensor<T> r;
        AscendC::Reg::Duplicate(r, 0.0f);
    }
}
'''
        report = check_regbase_source(source, "good", raise_on_failure=False)
        assert report.passed, str(report)

    def test_check_regbase_source_raises_on_failure(self):
        source = '''
__simd_vf__ void BadVf(__ubuf__ float* dst, uint16_t n)
{
    for (uint16_t i = 0; i < n; ++i) {
        if (i == 0) {
            dst[0] = 1.0f;
        }
    }
}
'''
        with pytest.raises(RuntimeError, match="RegBase static check failed"):
            check_regbase_source(source, "bad")

    def test_check_regbase_source_non_simd_passes(self):
        source = '''
extern "C" __global__ __aicore__ void add_custom(
    __gm__ uint8_t* x, __gm__ uint8_t* y, uint32_t totalLength)
{
    for (int i = 0; i < totalLength; ++i) {
    }
}
'''
        report = check_regbase_source(source, "add_custom", raise_on_failure=False)
        assert report.passed, str(report)

    def test_regbase_checker_class(self):
        source = "__simd_vf__ inline void F(__ubuf__ float* p) { }"
        checker = RegBaseChecker(source, "f")
        report = checker.run_all()
        assert isinstance(report, StaticCheckReport)
        assert report.passed

    def test_check_result_dataclass(self):
        r = CheckResult(name="x", passed=True, message="ok", line_no=3)
        assert r.name == "x" and r.passed and r.line_no == 3

    def test_report_failures_property(self):
        report = StaticCheckReport()
        report.add(CheckResult("a", True, "ok"))
        report.add(CheckResult("b", False, "bad"))
        assert report.passed is False
        assert len(report.failures) == 1
        assert report.failures[0].name == "b"

    def test_auto_detect_kernel_name_extern_c(self):
        source = 'extern "C" __global__ __aicore__ void my_kernel(GM_ADDR x) {}'
        assert auto_detect_kernel_name(source) == "my_kernel"

    def test_auto_detect_kernel_name_plain(self):
        source = "__global__ __aicore__ void my_kernel(GM_ADDR x) {}"
        assert auto_detect_kernel_name(source) == "my_kernel"

    def test_auto_detect_kernel_name_none(self):
        assert auto_detect_kernel_name("int x = 1;") is None

    def test_injected_runtime_branch_fails(self):
        source = '''
template <typename T>
__simd_vf__ inline void BadReduce(
    __ubuf__ float* dstUb,
    uint16_t rows,
    uint32_t colAlign)
{
    for (uint16_t i = 0; i < rows; ++i) {
        if (i == 0) {
            uint32_t offset = i * colAlign;
        }
    }
}
'''
        report = check_regbase_source(source, "bad", raise_on_failure=False)
        assert not report.passed
        assert not find_check(report, "hardware_loop_branch").passed

    def test_gm_access_in_vf_fails(self):
        source = '''
__simd_vf__ inline void BadVf(__ubuf__ float* dst, GM_ADDR src, uint16_t n)
{
    for (uint16_t i = 0; i < n; ++i) {
    }
}
'''
        report = check_regbase_source(source, "bad", raise_on_failure=False)
        assert not report.passed
        assert not find_check(report, "simd_vf_no_gm").passed


# --------------------------------------------------------------------------- #
# KernelLauncher integration
# --------------------------------------------------------------------------- #
class TestLauncherStaticCheck:
    def _op_info(self, impl_base, ops_group="ops_math", op_file="add_apt",
                 op_interface="add"):
        return {
            "_impl_base_path": impl_base,
            "_ops_group": ops_group,
            "opFile.value": op_file,
            "opInterface.value": op_interface,
        }

    def test_locate_op_source_found(self, mock_ttk_env, tmp_path):
        impl_base = str(tmp_path)
        ops_group = "ops_math"
        src_dir = os.path.join(impl_base, "impl", ops_group, "ascendc", "add")
        _write_source(src_dir, "add_apt.cpp",
                      'extern "C" __global__ __aicore__ void add(GM_ADDR x) {}')

        launcher = KernelLauncher("add")
        with patch("KernelLaunch.launcher.OpInfoKeeper") as MockKeeper:
            MockKeeper.return_value.info_of.return_value = self._op_info(impl_base)
            assert launcher.locate_op_source("add") == os.path.join(src_dir, "add_apt.cpp")

    def test_locate_op_source_missing(self, mock_ttk_env, tmp_path):
        impl_base = str(tmp_path)
        launcher = KernelLauncher("add")
        with patch("KernelLaunch.launcher.OpInfoKeeper") as MockKeeper:
            MockKeeper.return_value.info_of.return_value = self._op_info(impl_base)
            assert launcher.locate_op_source("add") is None

    def test_static_check_passes(self, mock_ttk_env, tmp_path):
        impl_base = str(tmp_path)
        src_dir = os.path.join(impl_base, "impl", "ops_math", "ascendc", "add")
        _write_source(src_dir, "add_apt.cpp",
                      'extern "C" __global__ __aicore__ void add(GM_ADDR x) {}')

        launcher = KernelLauncher("add")
        with patch("KernelLaunch.launcher.OpInfoKeeper") as MockKeeper:
            MockKeeper.return_value.info_of.return_value = self._op_info(impl_base)
            report = launcher.static_check("add")
        assert isinstance(report, StaticCheckReport)
        assert report.passed, str(report)

    def test_static_check_fails_and_raises(self, mock_ttk_env, tmp_path):
        impl_base = str(tmp_path)
        src_dir = os.path.join(impl_base, "impl", "ops_math", "ascendc", "add")
        _write_source(src_dir, "add_apt.cpp",
                      "__simd_vf__ void BadVf(__ubuf__ float* dst, GM_ADDR src) {}")

        launcher = KernelLauncher("add")
        with patch("KernelLaunch.launcher.OpInfoKeeper") as MockKeeper:
            MockKeeper.return_value.info_of.return_value = self._op_info(impl_base)
            with pytest.raises(RuntimeError, match="RegBase static check failed"):
                launcher.static_check("add")

    def test_static_check_no_raise_returns_report(self, mock_ttk_env, tmp_path):
        impl_base = str(tmp_path)
        src_dir = os.path.join(impl_base, "impl", "ops_math", "ascendc", "add")
        _write_source(src_dir, "add_apt.cpp",
                      "__simd_vf__ void BadVf(__ubuf__ float* dst, GM_ADDR src) {}")

        launcher = KernelLauncher("add")
        with patch("KernelLaunch.launcher.OpInfoKeeper") as MockKeeper:
            MockKeeper.return_value.info_of.return_value = self._op_info(impl_base)
            report = launcher.static_check("add", raise_on_failure=False)
        assert not report.passed
        assert not find_check(report, "simd_vf_no_gm").passed

    def test_static_check_missing_source_raises(self, mock_ttk_env, tmp_path):
        launcher = KernelLauncher("add")
        with patch("KernelLaunch.launcher.OpInfoKeeper") as MockKeeper:
            MockKeeper.return_value.info_of.return_value = self._op_info(str(tmp_path))
            with pytest.raises(RuntimeError, match="Cannot locate AscendC kernel source"):
                launcher.static_check("add")

    def test_static_check_default_op_name(self, mock_ttk_env, tmp_path):
        impl_base = str(tmp_path)
        src_dir = os.path.join(impl_base, "impl", "ops_math", "ascendc", "add")
        _write_source(src_dir, "add_apt.cpp",
                      'extern "C" __global__ __aicore__ void add(GM_ADDR x) {}')

        launcher = KernelLauncher("add")
        with patch("KernelLaunch.launcher.OpInfoKeeper") as MockKeeper:
            MockKeeper.return_value.info_of.return_value = self._op_info(impl_base)
            report = launcher.static_check()
        assert report.passed, str(report)

    def test_constructor_static_check_flag(self, mock_ttk_env):
        launcher = KernelLauncher("add")
        assert launcher._static_check is False
        launcher = KernelLauncher("add", static_check=True)
        assert launcher._static_check is True

    def test_run_with_static_check_enabled(self, mock_ttk_env, tmp_path):
        impl_base = str(tmp_path)
        src_dir = os.path.join(impl_base, "impl", "ops_math", "ascendc", "add")
        _write_source(src_dir, "add_apt.cpp",
                      "__simd_vf__ void BadVf(__ubuf__ float* dst, GM_ADDR src) {}")

        launcher = KernelLauncher("add", static_check=True)
        with patch("KernelLaunch.launcher.OpInfoKeeper") as MockKeeper, \
             patch("KernelLaunch.launcher.clear_error_manager"), \
             patch("KernelLaunch.launcher.RTSInterface") as MockRTS, \
             patch("KernelLaunch.launcher.OperatorInterface") as MockOI, \
             patch("KernelLaunch.launcher.binary_kernel_match") as MockMatch:
            MockKeeper.return_value.info_of.return_value = self._op_info(impl_base)
            MockMatch.return_value = None
            with pytest.raises(RuntimeError, match="RegBase static check failed"):
                launcher.run()
