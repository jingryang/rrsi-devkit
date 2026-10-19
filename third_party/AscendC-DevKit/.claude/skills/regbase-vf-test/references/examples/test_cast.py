#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Test RegBase CustomRegImpl::CastImpl on Ascend NPU.

Cast f32 <-> f16 using a single VectorCore.
mode = 0: f32 -> f16
mode = 1: f16 -> f32
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

setup_log_separation(log_file="log_cast.txt", result_file="result_cast.txt")

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_KERNEL_SRC_PATH = os.path.join(_SCRIPT_DIR, "cast.cpp")


def test_cast_f32_to_f16(func, mod, total_length):
    x = np.random.randn(total_length).astype(np.float32)
    y = np.empty(total_length, dtype=np.float16)

    tiling_data = pack_tiling_data(
        [("totalLength", np.uint32), ("mode", np.uint32)],
        {"totalLength": total_length, "mode": 0},
    )
    func(x, y, *mod.workspace_arrays, tiling_data=tiling_data, output_indices={1})

    golden = x.astype(np.float16)

    verdict = compare_tensor(y, golden, dtype='float16')
    if verdict.passed:
        print(f"  [PASS] f32->f16 length={total_length} matches golden reference!")
        return True
    else:
        max_diff = np.max(np.abs(y.astype(np.float32) - golden.astype(np.float32)))
        print(f"\nf32->f16 length={total_length}:")
        print(f"  Output (first 8): {y[:8]}")
        print(f"  Golden (first 8): {golden[:8]}")
        print(f"  [FAIL] Max difference: {max_diff}")
        return False


def test_cast_f16_to_f32(func, mod, total_length):
    x = np.random.randn(total_length).astype(np.float16)
    y = np.empty(total_length, dtype=np.float32)

    tiling_data = pack_tiling_data(
        [("totalLength", np.uint32), ("mode", np.uint32)],
        {"totalLength": total_length, "mode": 1},
    )
    func(x, y, *mod.workspace_arrays, tiling_data=tiling_data, output_indices={1})

    golden = x.astype(np.float32)

    verdict = compare_tensor(y, golden, dtype='float32')
    if verdict.passed:
        print(f"  [PASS] f16->f32 length={total_length} matches golden reference!")
        return True
    else:
        max_diff = np.max(np.abs(y - golden))
        print(f"\nf16->f32 length={total_length}:")
        print(f"  Output (first 8): {y[:8]}")
        print(f"  Golden (first 8): {golden[:8]}")
        print(f"  [FAIL] Max difference: {max_diff}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Single-operator Cast test")
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
        help="Path to the AscendC kernel source file (default: cast.cpp in script dir).",
    )
    args = parser.parse_args()

    with open(args.kernel_src, "r", encoding="UTF-8") as f:
        kernel_src = f.read()

    mod = SourceModule(
        source=kernel_src,
        kernel_name="cast",
        block_dim=1,
        core_type="VectorCore",
        device_id=args.device_id,
        ascendc_dump=True,
        workspace_sizes=1024,
    )
    func = mod.get_function()

    results = []
    test_lengths = [
        1024,   # aligned
        1023,   # unaligned
        10000,  # aligned
        10001,  # unaligned
    ]

    for length in test_lengths:
        print(f"\n--- Testing f32->f16 length={length} ---")
        results.append(test_cast_f32_to_f16(func, mod, length))

    for length in test_lengths:
        print(f"\n--- Testing f16->f32 length={length} ---")
        results.append(test_cast_f16_to_f32(func, mod, length))

    if all(results):
        print("\n[ALL PASSED] All Cast tests passed!")
    else:
        print("\n[ SOME FAILED ] Some Cast tests failed!")


if __name__ == "__main__":
    main()
