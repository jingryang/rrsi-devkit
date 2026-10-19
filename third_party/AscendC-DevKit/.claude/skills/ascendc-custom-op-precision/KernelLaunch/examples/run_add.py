#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Example: Launch add kernel on Ascend NPU with multiple shapes and dtypes,
and compare outputs with golden.
"""

import argparse
import sys

import numpy as np

sys.path.insert(0, ".")
from KernelLaunch import KernelLauncher, setup_log_separation
from ttk.utilities.dtypes import numpy_bfloat16
BF16 = numpy_bfloat16()
setup_log_separation(log_file="log_add.log", result_file="result_add.log")

def compute_golden(inputs):
    return [inputs[0] + inputs[1]]

def precision_test(output, golden, rtol=1e-3, atol=1e-3):
    is_pass = np.allclose(output, golden, rtol=rtol, atol=atol)
    max_diff = np.max(np.abs(output.astype(np.float64) - golden.astype(np.float64)))
    return is_pass, max_diff

def test_add(launcher, shape, dtype, label=""):
    is_bf16 = (dtype == BF16)
    if is_bf16:
        a = np.random.randn(*shape).astype(np.float32).astype(BF16)
        b = np.random.randn(*shape).astype(np.float32).astype(BF16)
        golden = compute_golden([a.astype(np.float32), b.astype(np.float32)])[0]
    else:
        a = np.random.randn(*shape).astype(dtype)
        b = np.random.randn(*shape).astype(dtype)
        golden = compute_golden([a, b])[0]

    launcher.set_input(0, a)
    launcher.set_input(1, b)
    launcher.set_output(0, shape, dtype=dtype)
    print(f"  [{label:11s}] shape={str(shape):20s} dtype={np.dtype(dtype).name:10s}")
    try:
        outputs = launcher.run()
    except Exception as e:
        print(f"    [FAIL] {e}\n")
        return False

    result = outputs[0].astype(np.float32) if is_bf16 else outputs[0]
    rtol_val, atol_val = (1e-2, 1e-2) if is_bf16 else (1e-3, 1e-3)
    is_pass, max_diff = precision_test(result, golden, rtol=rtol_val, atol=atol_val)
    print(f"    [Output 0] {'PASS' if is_pass else 'FAIL'}  max_diff={max_diff:.2e}\n")
    return is_pass

def main():
    parser = argparse.ArgumentParser(description="Kernel add test")
    parser.add_argument("--device_id", type=int, default=0, help="Target NPU device ID (default: 0)")
    args = parser.parse_args()

    OP_NAME = "add"
    launcher = KernelLauncher(OP_NAME, device_id=args.device_id)
    launcher.show_op_info()
    print()

    test_shapes = [
        ((256,),        "aligned"),
        ((257,),        "non-aligned"),
        ((64, 128),     "aligned"),
        ((64, 127),     "non-aligned"),
        ((32, 64, 128), "aligned"),
        ((32, 63, 127), "non-aligned"),
    ]
    dtypes = [np.float32, np.float16, BF16]

    results = []
    print("=" * 60)
    print("Start testing add kernel")
    print("=" * 60)
    for dtype in dtypes:
        print(f"\n[Dtype: {np.dtype(dtype).name}]")
        print("-" * 60)
        for shape, label in test_shapes:
            results.append(test_add(launcher, shape, dtype, label))

    launcher.close()

    print("=" * 60)
    print("Test summary")
    print("=" * 60)
    if all(results):
        print(f"[ALL PASSED] {OP_NAME} kernel tests passed!")
    else:
        print(f"[ SOME FAILED ] Some {OP_NAME} kernel tests failed!")

if __name__ == "__main__":
    main()
