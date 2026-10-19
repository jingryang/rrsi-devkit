#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Example: Test RegBase CustomRegImpl::DuplicateImpl on Ascend NPU.
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

setup_log_separation(log_file="log_duplicate.txt", result_file="result_duplicate.txt")

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_KERNEL_SRC_PATH = os.path.join(_SCRIPT_DIR, "duplicate.cpp")


def test_duplicate(func, mod, total_length, scalar_value):
    # The kernel entry still expects an x argument; pass a minimal dummy buffer.
    dummy_x = np.zeros(1, dtype=np.float32)
    # Initialize output with ones so the OOB data-change guard can detect writes
    # even when the scalar fill value happens to be 0.0.
    y = np.ones(total_length, dtype=np.float32)

    tiling_data = pack_tiling_data(
        [("totalLength", np.uint32), ("scalarValue", np.float32)],
        {"totalLength": total_length, "scalarValue": scalar_value},
    )
    func(dummy_x, y, *mod.workspace_arrays, tiling_data=tiling_data, output_indices={1})

    golden = np.full(total_length, scalar_value, dtype=np.float32)

    verdict = compare_tensor(y, golden, dtype='float32')
    if verdict.passed:
        print(f"  [PASS] length={total_length}, scalar={scalar_value:.6f} passed!")
        return True
    else:
        max_diff = np.max(np.abs(y - golden))
        print(f"\nlength={total_length}, scalar={scalar_value:.6f}:")
        print(f"  Output y (first 8): {y[:8]}")
        print(f"  Golden  (first 8): {golden[:8]}")
        print(f"  [FAIL] max difference: {max_diff}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Single-operator Duplicate test")
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
        help="Path to the AscendC kernel source file (default: duplicate.cpp in script dir).",
    )
    args = parser.parse_args()

    with open(args.kernel_src, "r", encoding="UTF-8") as f:
        kernel_src = f.read()

    mod = SourceModule(
        source=kernel_src,
        kernel_name="duplicate",
        block_dim=1,
        core_type="VectorCore",
        device_id=args.device_id,
        ascendc_dump=True,
        workspace_sizes=1024,
    )
    func = mod.get_function()

    test_lengths = [
        1, 7, 15, 16, 17, 31, 32, 33, 63, 64, 65,
        127, 128, 129, 1023, 1024, 1025, 4096, 4097, 8192,
    ]
    scalar_values = [
        0.0,
        3.141592,
        -2.718281,
        np.random.uniform(-10.0, 10.0),
    ]

    results = []
    for scalar_value in scalar_values:
        for length in test_lengths:
            print(f"\n--- Testing length {length}, scalar {scalar_value:.6f} ---")
            results.append(test_duplicate(func, mod, length, scalar_value))

    if all(results):
        print("\n[ALL PASSED] All Duplicate tests passed!")
    else:
        print("\n[ SOME FAILED ] Some Duplicate tests failed!")


if __name__ == "__main__":
    main()
