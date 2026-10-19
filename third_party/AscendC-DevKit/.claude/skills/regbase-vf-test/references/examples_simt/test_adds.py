#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Example: Test SIMT adds (CustomRegImpl::AddsSimtImpl) on Ascend NPU.

SIMT 逐元素标量加：y[i] = x[i] + scalar，thread-per-element + stride 循环，
GM 直读直写。与 SIMD 版 adds（__simd_vf__）对应，展示两种模式区别。
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

setup_log_separation(log_file="log_adds.txt", result_file="result_adds.txt")

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_KERNEL_SRC_PATH = os.path.join(_SCRIPT_DIR, "adds.cpp")


def test_adds(adds_func, mod, total_length, scalar, seed=0):
    """测试 SIMT adds VF 精度。"""
    rng = np.random.default_rng(seed)
    x = rng.standard_normal(total_length).astype(np.float32)
    y = np.zeros(total_length, dtype=np.float32)

    tiling_data = pack_tiling_data(
        [("totalLength", np.uint32), ("scalar", np.float32)],
        {"totalLength": total_length, "scalar": float(scalar)},
    )

    adds_func(x, y, *mod.workspace_arrays, tiling_data=tiling_data, output_indices={1})

    golden = x + scalar
    verdict = compare_tensor(y, golden, dtype='float32')
    is_pass = verdict.passed
    if is_pass:
        print(f"  [PASS] length={total_length}, scalar={scalar:.4f} passed!")
    else:
        max_abs = np.max(np.abs(y.astype(np.float64) - golden.astype(np.float64)))
        print(f"  [FAIL] length={total_length}, scalar={scalar:.4f}, max_abs_diff={max_abs}")
        print(f"    y[first 8]: {y[:8]}")
        print(f"    golden[first 8]: {golden[:8]}")
    return is_pass


def main():
    parser = argparse.ArgumentParser(description="Single-operator SIMT adds test")
    parser.add_argument("--device_id", type=int, default=0, help="Target NPU device ID (default: 0).")
    parser.add_argument("--kernel_src", type=str, default=_DEFAULT_KERNEL_SRC_PATH,
                        help="Path to the AscendC kernel source file (default: adds.cpp in script dir).")
    args = parser.parse_args()

    dev = DeviceInfo()
    print("=" * 60)
    print(dev)
    print("=" * 60)

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
        kernel_meta=os.path.join(_SCRIPT_DIR, "kernel_meta"),
    )
    print(f"  Compiled kernel metadata dir: {mod.kernel_meta}")
    func = mod.get_function()

    # 对齐/非对齐、极小/常规/大、正负标量
    test_cases = [
        (1, 1.5, 0),
        (7, -2.25, 1),
        (64, 0.5, 2),
        (1023, 3.1415, 3),
        (1024, -1.0, 4),
        (4096, 0.01, 5),
        (65537, 2.0, 6),
    ]

    results = []
    for length, scalar, seed in test_cases:
        print(f"\n--- Testing length {length}, scalar {scalar:.4f} ---")
        results.append(test_adds(func, mod, length, scalar, seed))

    if all(results):
        print("\n[ALL PASSED] All SIMT adds tests passed!")
    else:
        print("\n[ SOME FAILED ] Some SIMT adds tests failed!")


if __name__ == "__main__":
    main()
