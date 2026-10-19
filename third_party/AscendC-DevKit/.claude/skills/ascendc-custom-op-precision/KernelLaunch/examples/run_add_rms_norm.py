#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Example: Launch add_rms_norm kernel on Ascend NPU with multiple shapes,
hidden sizes, and dtypes, and compare outputs with golden.
"""

import argparse
import sys

import numpy as np

sys.path.insert(0, ".")
from KernelLaunch import KernelLauncher, setup_log_separation
from ttk.utilities.dtypes import numpy_bfloat16
BF16 = numpy_bfloat16()
setup_log_separation(log_file="log_add_rms_norm.log", result_file="result_add_rms_norm.log")

EPS = 1e-5


def compute_golden(inputs, epsilon=EPS):
    x1, x2, gamma = inputs
    x = x1 + x2
    rms = np.sqrt(np.mean(x.astype(np.float64) ** 2, axis=-1, keepdims=True) + epsilon)
    y = (x / rms) * gamma
    return [y.astype(x1.dtype), (1.0 / rms).astype(x1.dtype), x.astype(x1.dtype)]


def precision_test(output, golden, rtol=1e-3, atol=1e-3):
    is_pass = np.allclose(output, golden, rtol=rtol, atol=atol)
    max_diff = np.max(np.abs(output.astype(np.float64) - golden.astype(np.float64)))
    return is_pass, max_diff


def test_add_rms_norm(launcher, shape, hidden, dtype, label=""):
    B = shape[0] if len(shape) >= 1 else 1
    S = shape[1] if len(shape) >= 2 else 1

    is_bf16 = (dtype == BF16)

    if is_bf16:
        x1 = np.random.randn(B, S, hidden).astype(np.float32).astype(BF16)
        x2 = np.random.randn(B, S, hidden).astype(np.float32).astype(BF16)
        gamma = np.random.randn(hidden).astype(np.float32).astype(BF16)

        x1_g = x1.astype(np.float32)
        x2_g = x2.astype(np.float32)
        gamma_g = gamma.astype(np.float32)
        golden = compute_golden([x1_g, x2_g, gamma_g], EPS)
        golden = [g.astype(BF16).astype(np.float32) if i != 1 else g
                  for i, g in enumerate(golden)]
    else:
        x1 = np.random.randn(B, S, hidden).astype(dtype)
        x2 = np.random.randn(B, S, hidden).astype(dtype)
        gamma = np.random.randn(hidden).astype(dtype)
        golden = compute_golden([x1, x2, gamma], EPS)

    launcher.set_input(0, x1)
    launcher.set_input(1, x2)
    launcher.set_input(2, gamma)
    launcher.set_attr(0, EPS)

    launcher.set_output(0, (B, S, hidden), dtype=dtype)
    launcher.set_output(2, (B, S, hidden), dtype=dtype)
    launcher.set_output(1, (B, S, 1), dtype=np.float32)

    dtype_name = np.dtype(dtype).name
    print(f"  [{label:11s}] shape={str(shape):20s} hidden={hidden} dtype={dtype_name:10s}")

    try:
        outputs = launcher.run()
    except Exception as e:
        print(f"    [FAIL] {e}\n")
        return False

    all_pass = True
    for idx, name in enumerate(["yOut", "rstdOut", "xOut"]):
        result = outputs[idx]
        if is_bf16 and idx != 1:
            result = result.astype(np.float32)
        ref = golden[idx]
        rtol_val, atol_val = (1e-2, 1e-2) if is_bf16 else (1e-3, 1e-3)
        is_pass, max_diff = precision_test(result, ref, rtol=rtol_val, atol=atol_val)
        print(f"    [{name}] {'PASS' if is_pass else 'FAIL'}  max_diff={max_diff:.2e}  "
              f"shape={str(result.shape)}")
        if not is_pass:
            all_pass = False
    print()
    return all_pass


def main():
    parser = argparse.ArgumentParser(description="Kernel add_rms_norm test")
    parser.add_argument("--device_id", type=int, default=0, help="Target NPU device ID (default: 0)")
    args = parser.parse_args()

    OP_NAME = "add_rms_norm"
    launcher = KernelLauncher(OP_NAME, device_id=args.device_id)
    launcher.show_op_info()
    print()

    configs = [
        ((4, 128, 256), 256, np.float32, "aligned"),
        ((4, 128, 255), 255, np.float32, "non-aligned"),
        # ((2, 64, 128),  128, np.float32, "aligned"),
        # ((2, 64, 127),  127, np.float32, "non-aligned"),
        # ((9, 124, 256), 256, np.float16, "aligned"),
        # ((10, 28, 256), 256, np.float16, "aligned"),
        # ((4, 128, 256), 256, BF16, "aligned"),
        # ((4, 128, 255), 255, BF16, "non-aligned"),
        # ((2, 64, 128),  128, BF16, "aligned"),
        # ((2, 64, 127),  127, BF16, "non-aligned"),
    ]

    results = []
    print("=" * 60)
    print("Start testing add_rms_norm kernel")
    print("=" * 60)
    for shape, hidden, dtype, label in configs:
        results.append(test_add_rms_norm(launcher, shape, hidden, dtype, label))

    launcher.close()

    print("=" * 60)
    print("Test summary")
    print("=" * 60)
    passed = sum(1 for r in results if r is True)
    failed = sum(1 for r in results if r is False)
    if failed:
        print(f"[ SOME FAILED ] {OP_NAME}: {passed} passed, {failed} failed!")
    else:
        print(f"[ALL PASSED] {OP_NAME}: {passed} passed!")


if __name__ == "__main__":
    main()
