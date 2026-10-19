#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Example: Test RegBase CustomRegImpl::ReduceSumImpl on Ascend NPU.

Reduce [A, R] -> [A] using a single core.
"""

import argparse
import os
import numpy as np
from SingleOperatorLaunch import DeviceInfo, SourceModule, pack_tiling_data, setup_log_separation
from SingleOperatorLaunch.precision_check import compare_tensor
# 配置日志分离：系统日志 -> log.txt，print 结果 -> 屏幕 + result.txt
setup_log_separation(log_file="log_reducesum.txt", result_file="result_reducesum.txt")

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_KERNEL_SRC_PATH = os.path.join(_SCRIPT_DIR, "reducesum_custom.cpp")

def test_reducesum(func, mod, A, R):
    x = np.random.randn(A, R).astype(np.float32)
    y = np.empty(A, dtype=np.float32)

    tiling_data = pack_tiling_data(
        [("A", np.uint32), ("R", np.uint32)],
        {"A": A, "R": R},
    )
    func(x, y, *mod.workspace_arrays, tiling_data=tiling_data)

    golden = np.sum(x, axis=1)

    verdict = compare_tensor(y, golden, dtype="float32")
    if verdict.passed:
        print("  [PASS] ReduceSum kernel result matches golden reference!")
        return True
    else:
        print(f"\nShape [{A}, {R}]:")
        print(f"  Output (first 8): {y[:8]}")
        print(f"  Golden (first 8): {golden[:8]}")
        print(f"  [FAIL] MARE={verdict.mare:.3e}, max_diff={verdict.max_diff:.3e}, "
              f"mismatch={verdict.mismatch_count}/{verdict.total_count}, {verdict.error_msg}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Single-operator Add test")
    parser.add_argument(
        "--device_id",
        type=int,
        default=0,
        help="Target NPU device ID (default: 0).",
    )
    parser.add_argument(
        "--kernel_src",
        type=str,
        default=_DEFAULT_KERNEL_SRC_PATH,
        help="Path to the AscendC kernel source file (default: reducesum_custom.cpp in script dir).",
    )
    args = parser.parse_args()

    # Read kernel source from file
    with open(args.kernel_src, "r", encoding="UTF-8") as f:
        kernel_src = f.read()

    mod = SourceModule(
        source=kernel_src,
        kernel_name="reducesum_custom",
        block_dim=1,
        core_type="VectorCore",
        device_id=args.device_id,
        ascendc_dump=True,
        workspace_sizes=1024,
    )
    func = mod.get_function()

    results = []
    test_shapes = [
        (3, 43),      # Branch A: cols <= 64
        (3, 1024),    # Branch C: cols > 128
        (3, 1025),    # Branch C: 非对齐
        (1, 1045),
        (16, 256),    # Branch C
        (32, 512),    # Branch C
        (130, 128),   # Branch B: 64 < cols <= 128
    ]
    for shape in test_shapes:
        print(f"\n--- Testing shape {shape} ---")
        results.append(test_reducesum(func, mod, *shape))

    if all(results):
        print("\n[ALL PASSED] All ReduceSum tests passed!")
    else:
        print("\n[ SOME FAILED ] Some ReduceSum tests failed!")


if __name__ == "__main__":
    main()
