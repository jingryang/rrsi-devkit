#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Example: Test RegBase CustomRegImpl::AddsImpl on Ascend NPU.

Input dtype: float32 / float16 / bfloat16.
Output dtype is the same as input dtype.
The scalar addend is passed as float32 in tiling and cast to the input dtype on device.
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

setup_log_separation(log_file="log_adds.txt", result_file="result_adds.txt")

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_KERNEL_SRC_PATH = os.path.join(_SCRIPT_DIR, "adds.cpp")

_DTYPE_MAP = {
    "float32": (np.float32, 0),
    "float16": (np.float16, 1),
    "bfloat16": (numpy_bfloat16(), 2),
}


def test_adds(func, mod, total_length, scalar, dtype_name):
    np_dtype, dtype_mode = _DTYPE_MAP[dtype_name]

    x = np.random.uniform(-1.0, 1.0, size=total_length).astype(np.float32).astype(np_dtype)
    y = np.zeros(total_length, dtype=np_dtype)

    tiling_data = pack_tiling_data(
        [("totalLength", np.uint32), ("scalarValue", np.float32), ("dtype", np.uint32)],
        {"totalLength": total_length, "scalarValue": float(scalar), "dtype": dtype_mode},
    )
    func(x, y, *mod.workspace_arrays, tiling_data=tiling_data, output_indices={1})

    golden = x.astype(np.float32) + scalar

    # 生态精度标准：MERE/MARE + per-dtype 阈值（golden 内部截断到 output dtype）
    verdict = compare_tensor(y, golden, dtype=dtype_name)
    if verdict.passed:
        print(f"  [PASS] dtype={dtype_name}, length={total_length}, scalar={scalar} "
              f"(MERE={verdict.mere:.3e}, MARE={verdict.mare:.3e})")
        return True
    else:
        print(f"\ndtype={dtype_name}, length={total_length}, scalar={scalar}:")
        print(f"  Input x (first 8): {x.astype(np.float32)[:8]}")
        print(f"  Output y (first 8): {y.astype(np.float32)[:8]}")
        print(f"  Golden  (first 8): {golden[:8]}")
        print(f"  [FAIL] MARE={verdict.mare:.3e}, max_diff={verdict.max_diff:.3e}, "
              f"mismatch={verdict.mismatch_count}/{verdict.total_count}, {verdict.error_msg}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Single-operator Adds test")
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
        help="Path to the AscendC kernel source file (default: adds.cpp in script dir).",
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
        kernel_name="adds",
        block_dim=1,
        core_type="VectorCore",
        device_id=args.device_id,
        ascendc_dump=True,
        workspace_sizes=1024,
    )
    func = mod.get_function()

    dtypes = [args.dtype] if args.dtype else list(_DTYPE_MAP.keys())
    test_lengths = [4, 64, 65, 1024, 1025, 1453]
    scalars = [2.0, -1.5, 0.125]

    results = []
    for dtype_name in dtypes:
        print(f"\n========== Testing input dtype: {dtype_name} ==========")
        for length in test_lengths:
            for scalar in scalars:
                print(f"\n--- Testing length={length}, scalar={scalar} ---")
                results.append(test_adds(func, mod, length, scalar, dtype_name))

    if all(results):
        print("\n[ALL PASSED] All Adds tests passed!")
    else:
        print("\n[ SOME FAILED ] Some Adds tests failed!")


if __name__ == "__main__":
    main()
