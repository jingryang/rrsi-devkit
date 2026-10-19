#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Test RegBase CustomRegImpl::ReduceSumImpl on Ascend NPU.

Reduce [A, R] -> [A] using a single VectorCore.
Input dtype: float32 / float16 / bfloat16 (selected by tiling).
Reduce accumulation is performed in float32; output is float32.
"""

import argparse
import os
import numpy as np
import importlib.util
import sys
# 稳健自举：sys.path 目录搜索可能被 editable finder 破坏，用 importlib 按文件路径
# 注册 SingleOperatorLaunch，避免 ModuleNotFoundError（见 SKILL.md §3.4）。
_SOL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "SingleOperatorLaunch")
if _SOL_DIR not in sys.path:
    sys.path.insert(0, _SOL_DIR)
if "SingleOperatorLaunch" not in sys.modules:
    _spec = importlib.util.spec_from_file_location(
        "SingleOperatorLaunch",
        os.path.join(_SOL_DIR, "__init__.py"),
        submodule_search_locations=[_SOL_DIR],
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules["SingleOperatorLaunch"] = _mod
    _spec.loader.exec_module(_mod)
from SingleOperatorLaunch import DeviceInfo, SourceModule, pack_tiling_data, setup_log_separation
from SingleOperatorLaunch.precision_check import compare_tensor
from ttk.utilities.dtypes import numpy_bfloat16

setup_log_separation(log_file="log_reducesum.txt", result_file="result_reducesum.txt")

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_KERNEL_SRC_PATH = os.path.join(_SCRIPT_DIR, "reducesum.cpp")

_DTYPE_MAP = {
    "float32": (np.float32, 0),
    "float16": (np.float16, 1),
    "bfloat16": (numpy_bfloat16(), 2),
}


def cast_input(x, dtype_name):
    np_dtype, _ = _DTYPE_MAP[dtype_name]
    return x.astype(np_dtype)


def compute_golden(x, dtype_name):
    """Golden reduce-sum in float32."""
    return np.sum(x.astype(np.float32), axis=1)


def test_reducesum(func, mod, A, R, dtype_name):
    x_fp32 = np.random.randn(A, R).astype(np.float32)
    x = cast_input(x_fp32, dtype_name)
    y = np.empty(A, dtype=np.float32)

    _, dtype_mode = _DTYPE_MAP[dtype_name]
    tiling_data = pack_tiling_data(
        [("A", np.uint32), ("R", np.uint32), ("dtype", np.uint32)],
        {"A": A, "R": R, "dtype": dtype_mode},
    )
    func(x, y, *mod.workspace_arrays, tiling_data=tiling_data, output_indices={1})

    golden = compute_golden(x, dtype_name)

    # 生态精度标准：输出 dtype = float32（归约在 fp32 累加）
    verdict = compare_tensor(y, golden, dtype="float32")
    if verdict.passed:
        print(f"  [PASS] dtype={dtype_name}, shape=[{A}, {R}] "
              f"(MERE={verdict.mere:.3e}, MARE={verdict.mare:.3e})")
        return True
    else:
        print(f"\ndtype={dtype_name}, shape=[{A}, {R}]:")
        print(f"  Output (first 8): {y[:8]}")
        print(f"  Golden (first 8): {golden[:8]}")
        print(f"  [FAIL] MARE={verdict.mare:.3e}, max_diff={verdict.max_diff:.3e}, "
              f"mismatch={verdict.mismatch_count}/{verdict.total_count}, {verdict.error_msg}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Single-operator ReduceSum test")
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
        help="Path to the AscendC kernel source file (default: reducesum.cpp in script dir).",
    )
    parser.add_argument(
        "--dtype",
        type=str,
        choices=list(_DTYPE_MAP.keys()),
        default=None,
        help="Input dtype to test. If not set, all supported dtypes are tested.",
    )
    args = parser.parse_args()

    with open(args.kernel_src, "r", encoding="UTF-8") as f:
        kernel_src = f.read()

    mod = SourceModule(
        source=kernel_src,
        kernel_name="reducesum",
        block_dim=1,
        core_type="VectorCore",
        device_id=args.device_id,
        ascendc_dump=True,
        workspace_sizes=1024,
    )
    func = mod.get_function()

    dtypes = [args.dtype] if args.dtype else list(_DTYPE_MAP.keys())
    test_shapes = [
        (3, 43),      # Branch A: cols <= 64
        (4, 80),      # Branch B: 64 < cols <= 128
        (3, 1024),    # Branch C: cols > 128, aligned
        (3, 1025),    # Branch C: cols > 128, unaligned
        (16, 256),    # Branch C
        (32, 512),    # Branch C
        (130, 128),   # Branch B with multiple rows
    ]

    results = []
    for dtype_name in dtypes:
        print(f"\n========== Testing input dtype: {dtype_name} ==========")
        for shape in test_shapes:
            print(f"\n--- Testing shape {shape} ---")
            results.append(test_reducesum(func, mod, *shape, dtype_name))

    if all(results):
        print("\n[ALL PASSED] All ReduceSum tests passed!")
    else:
        print("\n[ SOME FAILED ] Some ReduceSum tests failed!")


if __name__ == "__main__":
    main()
