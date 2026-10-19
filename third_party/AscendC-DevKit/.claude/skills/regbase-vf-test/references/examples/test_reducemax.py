#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Test RegBase CustomRegImpl::ReduceMaxImpl on Ascend NPU.

Reduce [A, R] -> [A] using a single VectorCore.
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

setup_log_separation(log_file="log_reducemax.txt", result_file="result_reducemax.txt")

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_KERNEL_SRC_PATH = os.path.join(_SCRIPT_DIR, "reducemax.cpp")


def test_reducemax(func, mod, A, R):
    x = np.random.randn(A, R).astype(np.float32)
    y = np.empty(A, dtype=np.float32)

    tiling_data = pack_tiling_data(
        [("A", np.uint32), ("R", np.uint32)],
        {"A": A, "R": R},
    )
    func(x, y, *mod.workspace_arrays, tiling_data=tiling_data, output_indices={1})

    golden = np.max(x, axis=1)

    verdict = compare_tensor(y, golden, dtype='float32')
    if verdict.passed:
        print("  [PASS] ReduceMax kernel result matches golden reference!")
        return True
    else:
        max_diff = np.max(np.abs(y - golden))
        print(f"\nShape [{A}, {R}]:")
        print(f"  Output (first 8): {y[:8]}")
        print(f"  Golden (first 8): {golden[:8]}")
        print(f"  [FAIL] Max difference: {max_diff}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Single-operator ReduceMax test")
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
        help="Path to the AscendC kernel source file (default: reducemax.cpp in script dir).",
    )
    args = parser.parse_args()

    with open(args.kernel_src, "r", encoding="UTF-8") as f:
        kernel_src = f.read()

    mod = SourceModule(
        source=kernel_src,
        kernel_name="reducemax",
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
        (4, 80),      # Branch B: 64 < cols <= 128
        (3, 1024),    # Branch C: cols > 128, aligned
        (3, 1025),    # Branch C: cols > 128, unaligned
        (16, 256),    # Branch C
        (32, 512),    # Branch C
        (130, 128),   # Branch B with multiple rows
    ]
    for shape in test_shapes:
        print(f"\n--- Testing shape {shape} ---")
        results.append(test_reducemax(func, mod, *shape))

    if all(results):
        print("\n[ALL PASSED] All ReduceMax tests passed!")
    else:
        print("\n[ SOME FAILED ] Some ReduceMax tests failed!")


if __name__ == "__main__":
    main()
