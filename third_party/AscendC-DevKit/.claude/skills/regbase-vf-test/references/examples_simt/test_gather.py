#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Example: Test SIMT gather (CustomRegImpl::GatherRowSimtImpl) on Ascend NPU.

对应参考 gather.asc 的逻辑：input 为 [input_rows, in_width] 二维矩阵，
index 为长度 index_total_length 的行号表，输出 output 为
[index_total_length, in_width]，其中 output[r] = input[index[r]]。
使用 __simt_vf__（SIMT 编程模型）实现，经 asc_vf_call 启动。
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

setup_log_separation(log_file="log_gather.txt", result_file="result_gather.txt")

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_KERNEL_SRC_PATH = os.path.join(_SCRIPT_DIR, "gather.cpp")


def test_gather(gather_func, mod, input_rows, in_width, index, seed=0):
    """测试 SIMT gather VF 精度。"""
    # 1. 准备输入输出数据
    rng = np.random.default_rng(seed)
    input_data = rng.standard_normal(input_rows * in_width).astype(np.float32)
    output = np.zeros(len(index) * in_width, dtype=np.float32)

    # 2. 打包 tiling 数据
    tiling_data = pack_tiling_data(
        [("in_width", np.uint32), ("input_rows", np.uint32), ("index_total_length", np.uint32)],
        {"in_width": in_width, "input_rows": input_rows, "index_total_length": len(index)},
    )

    # 3. 调用 kernel，通过指定 output_indices 为输出变量下标开启 OOB 检查
    #    参数顺序：0=input, 1=index, 2=output, 3=workspace
    gather_func(input_data, index, output, *mod.workspace_arrays, tiling_data=tiling_data, output_indices={2})

    # 4. 精度验证（纯拷贝，bit-exact 比较）
    golden = input_data.reshape(input_rows, in_width)[index].reshape(-1)

    verdict = compare_tensor(output, golden, dtype='float32', threshold=0.0)
    is_pass = verdict.passed
    if is_pass:
        print(f"  [PASS] input_rows={input_rows}, in_width={in_width}, index_len={len(index)} passed!")
    else:
        n_diff = int(np.count_nonzero(output != golden))
        max_abs = np.max(np.abs(output.astype(np.float64) - golden.astype(np.float64)))
        print(f"  [FAIL] input_rows={input_rows}, in_width={in_width}, index_len={len(index)}")
        print(f"    output[first 8]: {output[:8]}")
        print(f"    golden [first 8]: {golden[:8]}")
        print(f"    num mismatches: {n_diff}/{output.size}, max_abs_diff: {max_abs}")
    return is_pass


def main():
    parser = argparse.ArgumentParser(description="Single-operator SIMT gather test")
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
        help="Path to the AscendC kernel source file (default: gather.cpp in script dir).",
    )
    args = parser.parse_args()

    dev = DeviceInfo()
    print("=" * 60)
    print(dev)
    print("=" * 60)

    with open(args.kernel_src, "r", encoding="UTF-8") as f:
        kernel_src = f.read()

    mod = SourceModule(
        source=kernel_src,
        kernel_name="gather",
        block_dim=1,
        core_type="VectorCore",
        device_id=args.device_id,
        ascendc_dump=True,
        workspace_sizes=1024,
        # 显式指定编译产物目录到测试脚本同目录，保证 fresh-build 与可清理
        kernel_meta=os.path.join(_SCRIPT_DIR, "kernel_meta"),
    )
    print(f"  Compiled kernel metadata dir: {mod.kernel_meta}")
    func = mod.get_function()

    # 测试用例：对齐/非对齐宽度、极小/常规/参考 gather.asc 原始规模
    test_cases = [
        (20001, 1023, 12288, 0),    # gather.asc 参考场景
        (5, 7, 17, 1),              # 极小非对齐
        (16, 32, 40, 2),            # 对齐宽度、行数非对齐
        (100, 33, 100, 3),          # 非对齐宽度
        (1000, 128, 256, 4),        # 常规
        (100000, 64, 8192, 5),      # 大输入、多输出行
    ]

    results = []
    for input_rows, in_width, index_len, seed in test_cases:
        # 构造行号表：覆盖顺序、逆序、重复、随机等形态
        if index_len <= input_rows:
            base = np.arange(index_len, dtype=np.uint32)
            index = np.where((base % 3) == 0, (base * 2) % input_rows, (input_rows - 1 - base) % input_rows).astype(np.uint32)
        else:
            rng = np.random.default_rng(seed)
            index = rng.integers(0, input_rows, size=index_len).astype(np.uint32)
        print(f"\n--- Testing input_rows={input_rows}, in_width={in_width}, index_len={index_len} ---")
        results.append(test_gather(func, mod, input_rows, in_width, index, seed=seed))

    if all(results):
        print("\n[ALL PASSED] All SIMT gather tests passed!")
    else:
        print("\n[ SOME FAILED ] Some SIMT gather tests failed!")


if __name__ == "__main__":
    main()
