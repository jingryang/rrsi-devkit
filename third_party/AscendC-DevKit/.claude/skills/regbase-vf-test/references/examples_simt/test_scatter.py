#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Example: Test SIMT scatter (CustomRegImpl::ScatterSimtImpl) on Ascend NPU.

SIMT 一维 scatter：output[index[i]] = input[i]，thread-per-element + stride 循环，
间接写（与 gather 间接读互为反向）。
index 为置换（无重复目标）时结果确定；有重复目标为数据竞争，不在本样例覆盖。
"""

import argparse
import importlib.util
import os
import sys

import numpy as np

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

setup_log_separation(log_file="log_scatter.txt", result_file="result_scatter.txt")

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_KERNEL_SRC_PATH = os.path.join(_SCRIPT_DIR, "scatter.cpp")


def test_scatter(scatter_func, mod, total_length, index, seed=0):
    """测试 SIMT scatter VF 精度（index 为置换）。"""
    rng = np.random.default_rng(seed)
    input_data = rng.standard_normal(total_length).astype(np.float32)
    output = np.zeros(total_length, dtype=np.float32)

    tiling_data = pack_tiling_data(
        [("totalLength", np.uint32), ("indexMax", np.uint32)],
        {"totalLength": total_length, "indexMax": total_length},
    )

    scatter_func(input_data, index, output, *mod.workspace_arrays, tiling_data=tiling_data, output_indices={2})

    # 置换 scatter：output[index[i]] = input[i] → output[index] = input
    golden = np.empty(total_length, dtype=np.float32)
    golden[index] = input_data

    verdict = compare_tensor(output, golden, dtype='float32', threshold=0.0)
    is_pass = verdict.passed
    if is_pass:
        print(f"  [PASS] length={total_length} passed!")
    else:
        n_diff = int(np.count_nonzero(output != golden))
        print(f"  [FAIL] length={total_length}, num mismatches: {n_diff}/{output.size}")
        print(f"    output[first 8]: {output[:8]}")
        print(f"    golden [first 8]: {golden[:8]}")
    return is_pass


def main():
    parser = argparse.ArgumentParser(description="Single-operator SIMT scatter test")
    parser.add_argument("--device_id", type=int, default=0, help="Target NPU device ID (default: 0).")
    parser.add_argument("--kernel_src", type=str, default=_DEFAULT_KERNEL_SRC_PATH,
                        help="Path to the AscendC kernel source file (default: scatter.cpp in script dir).")
    args = parser.parse_args()

    dev = DeviceInfo()
    print("=" * 60)
    print(dev)
    print("=" * 60)

    with open(args.kernel_src, "r", encoding="UTF-8") as f:
        kernel_src = f.read()

    mod = SourceModule(
        source=kernel_src,
        kernel_name="scatter",
        block_dim=1,
        core_type="VectorCore",
        device_id=args.device_id,
        ascendc_dump=True,
        workspace_sizes=1024,
        kernel_meta=os.path.join(_SCRIPT_DIR, "kernel_meta"),
    )
    print(f"  Compiled kernel metadata dir: {mod.kernel_meta}")
    func = mod.get_function()

    # 对齐/非对齐、极小/常规/大；index 用伪随机置换
    test_cases = [
        (1, 0),
        (17, 1),
        (64, 2),
        (1023, 3),
        (4096, 4),
        (65537, 5),
    ]

    results = []
    for total_length, seed in test_cases:
        rng = np.random.default_rng(seed)
        index = rng.permutation(total_length).astype(np.uint32)
        print(f"\n--- Testing scatter length {total_length} ---")
        results.append(test_scatter(func, mod, total_length, index, seed))

    if all(results):
        print("\n[ALL PASSED] All SIMT scatter tests passed!")
    else:
        print("\n[ SOME FAILED ] Some SIMT scatter tests failed!")


if __name__ == "__main__":
    main()
