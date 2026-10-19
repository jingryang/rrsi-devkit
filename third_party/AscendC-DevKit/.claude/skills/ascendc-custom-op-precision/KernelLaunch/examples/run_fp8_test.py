#!/usr/bin/env python3
"""
Test float8_e4m3fn / float8_e5m2 on ZerosLike and TensorMove operators.
Verifies kernel launch + TTK dtype integration for FP8 types.
"""

import argparse
import sys

import numpy as np

sys.path.insert(0, ".")
from KernelLaunch import KernelLauncher, setup_log_separation
from ttk.utilities.dtypes import numpy_float8_e5m2, numpy_float8_e4m3fn
setup_log_separation(log_file="log_fp8_test.log", result_file="result_fp8_test.log")

FP8_E5M2 = numpy_float8_e5m2()
FP8_E4M3 = numpy_float8_e4m3fn()


def precision_test(output, golden, rtol=1e-1, atol=1e-1):
    is_pass = np.allclose(output.astype(np.float32), golden.astype(np.float32),
                          rtol=rtol, atol=atol)
    max_diff = np.max(np.abs(output.astype(np.float64) - golden.astype(np.float64)))
    return is_pass, max_diff


def test_zeros_like(launcher, shape, fp8_dtype, label=""):
    x = np.random.randn(*shape).astype(np.float32).astype(fp8_dtype)
    golden = np.zeros(shape, dtype=np.float32)

    launcher.set_input(0, x)
    launcher.set_output(0, shape, dtype=fp8_dtype)
    dtype_name = np.dtype(fp8_dtype).name
    print(f"  [{label:11s}] shape={str(shape):20s} dtype={dtype_name}")

    try:
        outputs = launcher.run()
    except Exception as e:
        print(f"    [FAIL] {e}\n")
        return False

    result = outputs[0].astype(np.float32)
    is_pass, max_diff = precision_test(result, golden, rtol=0, atol=0)
    print(f"    [Output] {'PASS' if is_pass else 'FAIL'}  max_diff={max_diff:.2e}\n")
    return is_pass


def test_tensor_move(launcher, shape, fp8_dtype, label=""):
    x = np.random.randn(*shape).astype(np.float32).astype(fp8_dtype)
    golden = x.astype(np.float32)

    launcher.set_input(0, x)
    launcher.set_output(0, shape, dtype=fp8_dtype)
    dtype_name = np.dtype(fp8_dtype).name
    print(f"  [{label:11s}] shape={str(shape):20s} dtype={dtype_name}")

    try:
        outputs = launcher.run()
    except Exception as e:
        print(f"    [FAIL] {e}\n")
        return False

    result = outputs[0].astype(np.float32)
    is_pass, max_diff = precision_test(result, golden, rtol=0, atol=0)
    print(f"    [Output] {'PASS' if is_pass else 'FAIL'}  max_diff={max_diff:.2e}\n")
    return is_pass


def main():
    parser = argparse.ArgumentParser(description="FP8 kernel test")
    parser.add_argument("--device_id", type=int, default=0)
    parser.add_argument("--op", choices=["zeros_like", "tensor_move"],
                        default="tensor_move", help="Operator to test")
    args = parser.parse_args()

    results = []
    for op_name in [args.op]:
        launcher = KernelLauncher(op_name, device_id=args.device_id)
        launcher.show_op_info()
        print()

        test_fn = test_zeros_like if op_name == "zeros_like" else test_tensor_move

        shapes = [
            (32,),
            (64, 128),
            (16, 32, 64),
        ]

        for fp8_dtype in [FP8_E5M2, FP8_E4M3]:
            print(f"\n[Dtype: {np.dtype(fp8_dtype).name}]")
            print("-" * 60)
            for shape in shapes:
                label = "aligned" if all(s % 16 == 0 for s in shape) else "non-aligned"
                results.append(test_fn(launcher, shape, fp8_dtype, label))

        launcher.close()

    print("=" * 60)
    print("Test summary")
    print("=" * 60)
    passed = sum(1 for r in results if r is True)
    failed = sum(1 for r in results if r is False)
    if failed:
        print(f"[ SOME FAILED ] {passed} passed, {failed} failed!")
    else:
        print(f"[ALL PASSED] {passed} passed!")


if __name__ == "__main__":
    main()
