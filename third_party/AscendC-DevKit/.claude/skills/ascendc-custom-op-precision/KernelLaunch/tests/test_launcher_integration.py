"""Integration tests for KernelLaunch that require a real Ascend NPU.

Run with:
    python3 -m pytest KernelLaunch/tests/test_launcher_integration.py -v
Or to skip them:
    python3 -m pytest KernelLaunch/tests/ -v -m "not npu"
"""

import numpy as np
import pytest

from KernelLaunch import KernelLauncher


pytestmark = pytest.mark.npu


@pytest.fixture
def add_launcher(device_id):
    launcher = KernelLauncher("add", device_id=device_id)
    yield launcher
    launcher.close()


def test_add_float32(add_launcher):
    shape = (256,)
    a = np.random.randn(*shape).astype(np.float32)
    b = np.random.randn(*shape).astype(np.float32)
    add_launcher.set_input(0, a)
    add_launcher.set_input(1, b)
    add_launcher.set_output(0, shape, dtype=np.float32)
    outputs = add_launcher.run()
    golden = a + b
    assert np.allclose(outputs[0], golden, rtol=1e-3, atol=1e-3)


def test_add_float16(add_launcher):
    shape = (256,)
    a = np.random.randn(*shape).astype(np.float16)
    b = np.random.randn(*shape).astype(np.float16)
    add_launcher.set_input(0, a)
    add_launcher.set_input(1, b)
    add_launcher.set_output(0, shape, dtype=np.float16)
    outputs = add_launcher.run()
    golden = a + b
    assert np.allclose(outputs[0], golden, rtol=1e-3, atol=1e-3)


def test_add_bf16(add_launcher):
    from ttk.utilities.dtypes import numpy_bfloat16
    BF16 = numpy_bfloat16()
    shape = (256,)
    a = np.random.randn(*shape).astype(np.float32).astype(BF16)
    b = np.random.randn(*shape).astype(np.float32).astype(BF16)
    add_launcher.set_input(0, a)
    add_launcher.set_input(1, b)
    add_launcher.set_output(0, shape, dtype=BF16)
    outputs = add_launcher.run()
    golden = (a.astype(np.float32) + b.astype(np.float32)).astype(np.float32)
    assert np.allclose(outputs[0].astype(np.float32), golden, rtol=1e-2, atol=1e-2)


def test_add_rms_norm(device_id):
    launcher = KernelLauncher("add_rms_norm", device_id=device_id)
    try:
        B, S, H = 4, 128, 256
        dtype = np.float32
        x1 = np.random.randn(B, S, H).astype(dtype)
        x2 = np.random.randn(B, S, H).astype(dtype)
        gamma = np.random.randn(H).astype(dtype)
        launcher.set_input(0, x1)
        launcher.set_input(1, x2)
        launcher.set_input(2, gamma)
        launcher.set_attr(0, 1e-5)
        launcher.set_output(0, (B, S, H), dtype=dtype)
        launcher.set_output(1, (B, S, 1), dtype=np.float32)
        launcher.set_output(2, (B, S, H), dtype=dtype)
        outputs = launcher.run()
        x = x1.astype(np.float64) + x2.astype(np.float64)
        rms = np.sqrt(np.mean(x ** 2, axis=-1, keepdims=True) + 1e-5)
        golden_y = (x / rms * gamma.astype(np.float64)).astype(dtype)
        assert np.allclose(outputs[0], golden_y, rtol=1e-3, atol=1e-3)
    finally:
        launcher.close()


def test_tensor_move_fp8(device_id):
    from ttk.utilities.dtypes import numpy_float8_e5m2
    FP8 = numpy_float8_e5m2()
    launcher = KernelLauncher("tensor_move", device_id=device_id)
    try:
        shape = (64, 128)
        x = np.random.randn(*shape).astype(np.float32).astype(FP8)
        launcher.set_input(0, x)
        launcher.set_output(0, shape, dtype=FP8)
        outputs = launcher.run()
        # TensorMove should preserve the FP8 bit pattern; compare via float32 cast.
        assert np.allclose(outputs[0].astype(np.float32), x.astype(np.float32), rtol=0, atol=0)
    finally:
        launcher.close()


def test_show_op_info_add():
    # Pure inspection, no device needed.
    launcher = KernelLauncher("add")
    launcher.show_op_info()


def test_for_case_runs(device_id):
    launcher = KernelLauncher.for_case("add", case_label="integ", device_id=device_id)
    try:
        shape = (128,)
        a = np.random.randn(*shape).astype(np.float32)
        b = np.random.randn(*shape).astype(np.float32)
        launcher.set_input(0, a)
        launcher.set_input(1, b)
        launcher.set_output(0, shape, dtype=np.float32)
        outputs = launcher.run()
        assert np.allclose(outputs[0], a + b, rtol=1e-3, atol=1e-3)
    finally:
        launcher.close()
