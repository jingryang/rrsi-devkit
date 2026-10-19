#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Test RegBase CustomRegImpl::SigmoidImpl on Ascend NPU.
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

setup_log_separation(log_file="log_sigmoid.txt", result_file="result_sigmoid.txt")

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_KERNEL_SRC_PATH = os.path.join(_SCRIPT_DIR, "sigmoid.cpp")


def golden_sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def test_sigmoid(func, mod, total_length):
    x = np.random.uniform(-5.0, 5.0, size=total_length).astype(np.float32)
    y = np.empty(total_length, dtype=np.float32)

    tiling_data = pack_tiling_data(
        [("totalLength", np.uint32)],
        {"totalLength": total_length},
    )
    func(x, y, *mod.workspace_arrays, tiling_data=tiling_data,
         output_indices={1})

    golden = golden_sigmoid(x)

    verdict = compare_tensor(y, golden, dtype='float32')
    if verdict.passed:
        print(f"  [PASS] length={total_length}")
        return True
    else:
        max_diff = np.max(np.abs(y - golden))
        print(f"\nlength={total_length}:")
        print(f"  Output (first 8): {y[:8]}")
        print(f"  Golden (first 8): {golden[:8]}")
        print(f"  [FAIL] Max difference: {max_diff}")
        return False


def try_device(device_id, kernel_src):
    with open(kernel_src, "r", encoding="UTF-8") as f:
        kernel_src_str = f.read()

    mod = SourceModule(
        source=kernel_src_str,
        kernel_name="sigmoid",
        block_dim=1,
        core_type="VectorCore",
        device_id=device_id,
        ascendc_dump=True,
        workspace_sizes=1024,
    )
    func = mod.get_function()

    test_lengths = [
        1,
        4,
        7,
        64,
        65,
        1024,
        1025,
        4096,
        4099,
    ]
    results = []
    for length in test_lengths:
        print(f"\n--- Testing length {length} ---")
        results.append(test_sigmoid(func, mod, length))

    if all(results):
        print("\n[ALL PASSED] All Sigmoid tests passed!")
        return True
    else:
        print("\n[ SOME FAILED ] Some Sigmoid tests failed!")
        return False


def main():
    parser = argparse.ArgumentParser(description="Single-operator Sigmoid test")
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
        help="Path to the AscendC kernel source file (default: sigmoid.cpp in script dir).",
    )
    args = parser.parse_args()

    ok = try_device(args.device_id, args.kernel_src)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
