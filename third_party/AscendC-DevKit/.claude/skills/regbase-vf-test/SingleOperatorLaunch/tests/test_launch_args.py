#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Coverage for the SIMT share-memory window (simt_share_memory_size)
pass-through in SingleOperatorLaunch launch paths.

Regression guard: the SIMT 共享内存窗口 must be configurable from the public
API (default 0 / None -> RTS runtime default, measured 8KB). Before this
file existed, LaunchKernelArgs was built without the field, so isolated VF
tests could never run a __simt_vf__ kernel that touches UB beyond the 8KB
default window.
"""

import ctypes
import inspect

import numpy
import pytest

from SingleOperatorLaunch import source_module as sm
from SingleOperatorLaunch.source_module import _make_launch_args, _KernelFunction


# ---------------------------------------------------------------------------
# Pure seam: _make_launch_args
# ---------------------------------------------------------------------------

def _stub_kernel_func():
    return ctypes.c_void_p(0x1)


def test_make_launch_args_default_resolves_to_zero():
    args = _make_launch_args(
        func_or_binary_hdl=_stub_kernel_func(),
        op_args=[ctypes.c_void_p(0x1000)],
        block_dim=1,
        mix_kernel=False,
    )
    assert args.simt_share_memory_size == 0
    assert args.block_dim == 1
    assert args.tiling_data is None


def test_make_launch_args_explicit_value_forwarded():
    args = _make_launch_args(
        func_or_binary_hdl=_stub_kernel_func(),
        op_args=[],
        block_dim=1,
        mix_kernel=False,
        simt_share_memory_size=65536,
    )
    assert args.simt_share_memory_size == 65536


def test_make_launch_args_zero_is_allowed():
    args = _make_launch_args(
        func_or_binary_hdl=_stub_kernel_func(),
        op_args=[],
        block_dim=1,
        mix_kernel=False,
        simt_share_memory_size=0,
    )
    assert args.simt_share_memory_size == 0


def test_make_launch_args_negative_raises():
    with pytest.raises(ValueError):
        _make_launch_args(
            func_or_binary_hdl=_stub_kernel_func(),
            op_args=[],
            block_dim=1,
            mix_kernel=False,
            simt_share_memory_size=-1,
        )


# ---------------------------------------------------------------------------
# Public entry points accept the kwarg
# ---------------------------------------------------------------------------

def test_public_apis_expose_simt_share_memory_size():
    sig_call = inspect.signature(_KernelFunction.__call__)
    sig_profile = inspect.signature(_KernelFunction.profile)
    sig_sm = inspect.signature(sm.SourceModule.__call__)
    assert "simt_share_memory_size" in sig_call.parameters
    assert "simt_share_memory_size" in sig_profile.parameters
    assert "simt_share_memory_size" in sig_sm.parameters


# ---------------------------------------------------------------------------
# Forwarding into the actual launch (fake device / diag, no NPU needed)
# ---------------------------------------------------------------------------

class _FakeDevice:
    def __init__(self):
        self.launched = []
        self.device_id = 0

    def create_stream(self):
        return object()

    def launch_kernel_with_flag(self, launch_args, stream):
        self.launched.append(launch_args)

    def synchronize_with_stream(self, stream):
        pass

    def destroy_stream_force(self, stream):
        pass

    def copy_nparray_to_hbm(self, arr, fill_oob_flag=False):
        return ctypes.c_void_p(0x10000)

    def get_data_from_hbm(self, ptr, byte_size):
        return bytes(byte_size)

    def free(self, ptr):
        pass


class _FakeDiag:
    def run_pipeline(self, np_args, output_mask):
        return {"saved_hbm": {}}

    def finish_pipeline(self, np_args, saved_hbm, output_mask, kernel_status=None):
        return False


def _make_kfn(device):
    k = _KernelFunction.__new__(_KernelFunction)
    k._device = device
    k._diag = _FakeDiag()
    k._kernel_func = ctypes.c_void_p(0x1)
    k._kernel_name = "k"
    k._kernel_json = {}
    k._block_dim = 1
    k._core_type = "VectorCore"
    k._workspace_arrays = []
    k._ascendc_dump = False
    k._short_soc = ""
    k._kernel_dir = "/tmp"
    return k


def test_call_default_leaves_simt_window_zero(monkeypatch):
    monkeypatch.setattr(sm, "clear_error_manager", lambda: None)
    dev = _FakeDevice()
    k = _make_kfn(dev)
    k(numpy.zeros(16, dtype=numpy.uint32))
    assert dev.launched, "kernel launch was never recorded"
    assert dev.launched[-1].simt_share_memory_size == 0


def test_call_forwards_simt_share_memory_size(monkeypatch):
    monkeypatch.setattr(sm, "clear_error_manager", lambda: None)
    dev = _FakeDevice()
    k = _make_kfn(dev)
    k(numpy.zeros(16, dtype=numpy.uint32), simt_share_memory_size=65536)
    assert dev.launched and dev.launched[-1].simt_share_memory_size == 65536


def test_profile_forwards_simt_share_memory_size(monkeypatch):
    monkeypatch.setattr(sm, "clear_error_manager", lambda: None)

    class _FakeOpDfx:
        def __init__(self, **kwargs):
            pass

    class _FakeProfiler:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def step(self):
            pass

        def report_op_dfx(self, op_dfx):
            pass

    monkeypatch.setattr(sm, "MsProfOpDfx", _FakeOpDfx)
    monkeypatch.setattr(sm, "MsProfiler", _FakeProfiler)

    dev = _FakeDevice()
    k = _make_kfn(dev)
    k.profile(
        numpy.zeros(16, dtype=numpy.uint32),
        repeat_times=1, warmup_times=0,
        result_path="/tmp/sol_prof_test",
        simt_share_memory_size=65536,
    )
    assert dev.launched, "profile run never launched"
    assert all(a.simt_share_memory_size == 65536 for a in dev.launched)
