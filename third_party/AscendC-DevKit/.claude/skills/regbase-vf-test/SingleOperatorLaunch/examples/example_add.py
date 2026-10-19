#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Example: Compile and launch a custom Add operator on Ascend NPU.

This demonstrates the PyCUDA-like API provided by SingleOperatorLaunch.
"""

import argparse
import os
import numpy as np
from SingleOperatorLaunch import DeviceInfo, SourceModule, pack_tiling_data, setup_log_separation
from SingleOperatorLaunch.precision_check import compare_tensor
# 配置日志分离：系统日志 -> log.txt，print 结果 -> 屏幕 + result.txt
setup_log_separation(log_file="log_add.txt", result_file="result_add.txt")

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_KERNEL_SRC_PATH = os.path.join(_SCRIPT_DIR, "add_custom.cpp")

def compute_golden(x, y):
    """计算真值（golden reference）"""
    return x + y

def precision_test(output, golden):
    """生态精度标准判定（float32 输出，MERE/MARE + per-dtype 阈值）。

    Args:
        output: 算子输出
        golden: 真值参考

    Returns:
        (is_pass, max_diff): 是否通过测试，最大误差值
    """
    verdict = compare_tensor(output, golden, dtype='float32')
    return verdict.passed, verdict.max_diff

def test_add(add_func, mod, total_length, block_dim=1):
    """Test Add kernel with a specific shape."""
    # 1. Prepare data
    x = np.random.randn(total_length).astype(np.float32)
    y = np.random.randn(total_length).astype(np.float32)
    z = np.empty(total_length, dtype=np.float32)

    # Tiling data packed as raw bytes (little-endian uint32)
    tiling_data = pack_tiling_data(
        [("total_length", np.uint32)],
        {"total_length": total_length},
    )
    # 6. Launch kernel
    add_func(x, y, z, *mod.workspace_arrays, tiling_data=tiling_data)

    # 7. Verify result
    golden = compute_golden(x, y)

    is_pass, max_diff = precision_test(z, golden)
    if is_pass:
        print(f"  [PASS] Shape [{total_length}] passed!")
    else:
        print(f"  Input x (first 8): {x[:8]}")
        print(f"  Input y (first 8): {y[:8]}")
        print(f"  Output z (first 8): {z[:8]}")
        print(f"  Golden  (first 8): {golden[:8]}")
        print(f"  [FAIL] Shape [{total_length}] max difference: {max_diff}")
    return is_pass

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
        help="Path to the AscendC kernel source file (default: add_custom.cpp in script dir).",
    )
    args = parser.parse_args()

    # Define test shapes
    test_shapes = [
        4, 19, 37, 
        1024, 
        1453, 
        4096,
    ]
    block_dim = 1

    # Read kernel source from file
    with open(args.kernel_src, "r", encoding="UTF-8") as f:
        kernel_src = f.read()

    # Compile once, get function once
    mod = SourceModule(
        source=kernel_src,
        kernel_name="add_custom",
        block_dim=block_dim,
        core_type="VectorCore",
        ascendc_dump=False,
        workspace_sizes=1024,
        device_id=args.device_id,
    )
    print(f"  Compiled kernel metadata dir: {mod.kernel_meta}")
    add_func = mod.get_function()

    results = []
    for shape in test_shapes:
        print(f"\nTesting shape: total_length={shape}, block_dim={block_dim}")
        results.append(test_add(add_func, mod, shape, block_dim))

    if all(results):
        print("\n[ALL PASSED] All Add tests passed!")
    else:
        print("\n[ SOME FAILED ] Some Add tests failed!")

if __name__ == "__main__":
    main()
