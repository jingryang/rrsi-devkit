"""Step 2 (chip-target-selection): probe missing-hardware → UNKNOWN sentinel.

The hardware probe (``_probe_chip_blocking``) historically returned
``_FALLBACK_CHIP`` (A2) on ANY failure to identify the hardware — torch_npu
missing, 0 devices, unknown device name. That was a silent lie: an unresolved
chip masqueraded as A2, defeating the run gate (design "A2" vs runtime "A2" →
spurious match) and only crashing later at ``to_soc_version`` if the user dared
pick a non-A2 target.

Step 2 makes the probe honest: every missing-hardware path returns
``chip.UNKNOWN`` (deliberately outside ``CHIP_GENERATIONS``, see Step 1). The run
gate (Step 5) then treats ``runtime=UNKNOWN`` as a distinct "cannot verify"
state. ``NPURunner`` must not crash on construction with UNKNOWN — the run-time
``soc_version`` guard raises a clear error only when actually building/running a
harness.
"""
from __future__ import annotations

import sys
import types

import pytest

from ascendc_devkit.adapters.npu.detect import _probe_chip_blocking
from ascendc_devkit.domain import chip

import ascendc_devkit.adapters.npu.detect as detect_mod


@pytest.fixture(autouse=True)
def _fresh_probe_cache(monkeypatch):
    """step 104 进程级探测缓存：用例间隔离（fake 硬件每例不同，真实硬件不变）。"""
    monkeypatch.setattr(detect_mod, "_PROBE_CACHE", None)


def _install_fake_torch_npu(monkeypatch, *, device_count=1, device_name="Ascend910B"):
    """Inject a stub torch_npu into sys.modules (auto-restored by monkeypatch)."""
    mod = types.ModuleType("torch_npu")
    mod.npu = types.SimpleNamespace(
        device_count=lambda: device_count,
        get_device_name=lambda _i: device_name,
    )
    monkeypatch.setitem(sys.modules, "torch_npu", mod)


class TestProbeMissingHardwareSentinel:
    def test_zero_devices_returns_unknown(self, monkeypatch):
        _install_fake_torch_npu(monkeypatch, device_count=0)
        assert _probe_chip_blocking() == chip.UNKNOWN

    def test_import_failure_returns_unknown(self, monkeypatch):
        # sys.modules[name]=None makes `import name` raise ImportError (CPython's
        # convention for explicit suppression) — simulates torch_npu uninstalled.
        monkeypatch.setitem(sys.modules, "torch_npu", None)
        assert _probe_chip_blocking() == chip.UNKNOWN

    def test_unknown_device_name_returns_unknown(self, monkeypatch):
        _install_fake_torch_npu(monkeypatch, device_name="AscendMystery9000")
        assert _probe_chip_blocking() == chip.UNKNOWN

    @pytest.mark.parametrize("name,expected", [
        ("Ascend910B", chip.A2),
        ("Ascend910C", chip.A3),
        ("Ascend950", chip.A5),
    ])
    def test_known_device_name_returns_generation(self, monkeypatch, name, expected):
        # Non-regression: a successfully identified device still maps to its
        # canonical generation (the sentinel ONLY replaces the missing-hardware
        # fallbacks, never a real match).
        _install_fake_torch_npu(monkeypatch, device_name=name)
        assert _probe_chip_blocking() == expected


class TestNPURunnerUnknownChipGuard:
    def test_construct_with_unknown_does_not_crash(self, monkeypatch):
        from ascendc_devkit.adapters.npu.runner import NPURunner
        # Stub _check_environment so construction needs no NPU/driver I/O (§3.8).
        monkeypatch.setattr(NPURunner, "_check_environment", lambda self: {})
        runner = NPURunner(chip_version=chip.UNKNOWN)
        assert runner._chip_version == chip.UNKNOWN

    def test_soc_version_raises_clear_error_on_unknown(self, monkeypatch):
        from ascendc_devkit.adapters.npu.runner import NPURunner
        monkeypatch.setattr(NPURunner, "_check_environment", lambda self: {})
        runner = NPURunner(chip_version=chip.UNKNOWN)
        # Clear RuntimeError naming the unknown chip — NOT to_soc_version's bare
        # ValueError ("no soc_version translation"), which would mislead.
        with pytest.raises(RuntimeError, match="未知"):
            runner._soc_version()

    def test_soc_version_translates_known_chip(self, monkeypatch):
        from ascendc_devkit.adapters.npu.runner import NPURunner
        monkeypatch.setattr(NPURunner, "_check_environment", lambda self: {})
        runner = NPURunner(chip_version=chip.A5)
        assert runner._soc_version() == "ascend950"
