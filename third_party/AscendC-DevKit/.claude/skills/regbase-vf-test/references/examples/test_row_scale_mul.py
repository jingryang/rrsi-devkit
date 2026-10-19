#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Example: Test RegBase CustomRegImpl::RowScaleMulImpl on Ascend NPU.

Compute: y[i][j] = x[i][j] * scale[i] * weight[j]
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

setup_log_separation(log_file="log_row_scale_mul.txt", result_file="result_row_scale_mul.txt")

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_KERNEL_SRC_PATH = os.path.join(_SCRIPT_DIR, "row_scale_mul.cpp")


def compute_col_align(cols):
    return int(np.ceil(cols * np.dtype(np.float32).itemsize / 32) * 32 / np.dtype(np.float32).itemsize)


def test_row_scale_mul(func, mod, rows, cols):
    col_align = compute_col_align(cols)

    x = np.random.randn(rows, cols).astype(np.float32)
    scale = np.random.randn(rows).astype(np.float32)
    weight = np.random.randn(cols).astype(np.float32)
    y = np.empty(rows * cols, dtype=np.float32).reshape(rows, cols)

    golden = x * scale.reshape(rows, 1) * weight.reshape(1, cols)

    tiling_data = pack_tiling_data(
        [("rows", np.uint32), ("cols", np.uint32), ("colAlign", np.uint32)],
        {"rows": rows, "cols": cols, "colAlign": col_align},
    )

    func(x, scale, weight, y, *mod.workspace_arrays, tiling_data=tiling_data, output_indices={3})

    verdict = compare_tensor(y, golden, dtype='float32')
    if verdict.passed:
        print(f"  [PASS] shape [{rows}, {cols}] (colAlign={col_align}) passed!")
        return True
    else:
        max_diff = np.max(np.abs(y - golden))
        print(f"\nshape [{rows}, {cols}]:")
        print(f"  Output (first 8): {y.flatten()[:8]}")
        print(f"  Golden (first 8): {golden.flatten()[:8]}")
        print(f"  [FAIL] Max difference: {max_diff}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Single-operator RowScaleMul test")
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
        help="Path to the AscendC kernel source file (default: row_scale_mul.cpp in script dir).",
    )
    args = parser.parse_args()

    with open(args.kernel_src, "r", encoding="UTF-8") as f:
        kernel_src = f.read()

    mod = SourceModule(
        source=kernel_src,
        kernel_name="row_scale_mul",
        block_dim=1,
        core_type="VectorCore",
        device_id=args.device_id,
        ascendc_dump=True,
        workspace_sizes=1024,
    )
    func = mod.get_function()

    test_shapes = [
        (3, 43),
        (3, 1024),
        (3, 1025),
        (16, 256),
        (32, 512),
        (130, 128),
        (30, 1000),
        (5, 4096),
    ]

    results = []
    for rows, cols in test_shapes:
        print(f"\n--- Testing shape [{rows}, {cols}] ---")
        results.append(test_row_scale_mul(func, mod, rows, cols))

    if all(results):
        print("\n[ALL PASSED] All RowScaleMul tests passed!")
    else:
        print("\n[ SOME FAILED ] Some RowScaleMul tests failed!")


if __name__ == "__main__":
    main()
