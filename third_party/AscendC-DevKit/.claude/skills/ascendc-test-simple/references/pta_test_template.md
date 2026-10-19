# PTA Direct-Call Test Template

生成的测试脚本必须**完全自包含**——所有精度函数直接内联，不 import 任何 skill 内部文件。

## 脚本结构

生成的脚本应按以下结构组织：

```
#!/usr/bin/env python3
# 1. Imports (只依赖 torch / torch_npu / numpy / time)
# 2. 精度工具函数（从 precision_utils.py 内联）
# 3. 算子专属实现（golden_impl / bench_impl / npu_custom_op）
# 4. 测试函数（test_correctness / test_performance）
# 5. main + FINAL SUMMARY
```

## Section 1: Imports

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test script for <op_name> operator"""

import time
import numpy as np
import torch
import torch_npu
import omni_training_custom_ops  # Must import after torch_npu
```

## Section 2: 精度工具函数（内联）

从 `precision_utils.py` 中选取需要的函数，直接写进脚本。按算子类别选择：

### 浮点计算算子 — 需要内联的函数

```python
# ==============================================================================
# Precision Utilities (inlined)
# ==============================================================================

def get_golden_dtype(input_dtype):
    if input_dtype in [torch.float16, torch.bfloat16]:
        return torch.float32
    return torch.float64

def get_level_thresholds(level="L2"):
    thresholds = {
        "L0": {"mare_ratio": 10.0, "mere_ratio": 2.0, "rmse_ratio": 2.0},
        "L1": {"mare_ratio": 5.0,  "mere_ratio": 1.5, "rmse_ratio": 1.5},
        "L2": {"mare_ratio": 2.0,  "mere_ratio": 1.2, "rmse_ratio": 1.2},
    }
    return thresholds[level]

def get_small_value_thresh(dtype_in):
    dtype_str = str(dtype_in).lower()
    if dtype_in == torch.bfloat16 or 'bfloat16' in dtype_str:
        return 2**-8
    elif dtype_in == torch.float16 or 'float16' in dtype_str:
        return 2**-11
    elif 'hifloat32' in dtype_str:
        return 2**-12
    elif 'e4m3' in dtype_str:
        return 2**-4
    elif 'e5m2' in dtype_str:
        return 2**-3
    else:
        return 2**-14

def get_small_value_error_thresh(dtype_in):
    dtype_str = str(dtype_in).lower()
    if dtype_in == torch.bfloat16 or 'bfloat16' in dtype_str:
        return 2**-16
    elif dtype_in == torch.float16 or 'float16' in dtype_str:
        return 2**-16
    elif 'hifloat32' in dtype_str:
        return 2**-28
    elif 'e4m3' in dtype_str:
        return 2**-6
    elif 'e5m2' in dtype_str:
        return 2**-5
    else:
        return 2**-30

def get_error_thd(dtype_in):
    if dtype_in == torch.float16:
        return 2**-11
    elif dtype_in == torch.bfloat16:
        return 2**-8
    else:
        return 2**-14

def calc_metrics_with_mask(actual, golden, small_value_thresh):
    mask = torch.abs(golden) > small_value_thresh
    actual_large = actual[mask]
    golden_large = golden[mask]
    inf_nan_mask = ~torch.isfinite(actual_large) | ~torch.isfinite(golden_large)
    if inf_nan_mask.all() or golden_large.numel() == 0:
        return 0.0, 0.0, 0.0
    abs_diff = torch.abs(actual_large - golden_large)
    re = abs_diff / (torch.abs(golden_large) + 1e-7)
    valid_re = re[~inf_nan_mask]
    mare = valid_re.max().item() if valid_re.numel() > 0 else 0.0
    mere = valid_re.mean().item() if valid_re.numel() > 0 else 0.0
    diff = actual_large[~inf_nan_mask] - golden_large[~inf_nan_mask]
    rmse = torch.sqrt(torch.sum(diff * diff) / diff.numel()).item() if diff.numel() > 0 else 0.0
    return mare, mere, rmse

def calc_small_value_error_count(actual, golden, dtype_in):
    small_thresh = get_small_value_thresh(dtype_in)
    error_thresh = get_small_value_error_thresh(dtype_in)
    small_mask = torch.abs(golden) <= small_thresh
    if not small_mask.any():
        return 0, 0
    abs_diff = torch.abs(actual[small_mask] - golden[small_mask])
    return int((abs_diff > error_thresh).sum().item()), int(small_mask.sum().item())

def compare_with_dual_benchmark(name, npu_val, bench_val, golden_val, input_dtype,
                                verbose=True, level="L2"):
    golden_dtype = get_golden_dtype(input_dtype)
    npu_f = npu_val.to(golden_dtype)
    bench_f = bench_val.to(golden_dtype)
    golden_f = golden_val.to(golden_dtype)
    sv_thresh = get_small_value_thresh(input_dtype)
    err_thd = get_error_thd(input_dtype)
    lv = get_level_thresholds(level)

    npu_mare, npu_mere, npu_rmse = calc_metrics_with_mask(npu_f, golden_f, sv_thresh)
    bench_mare, bench_mere, bench_rmse = calc_metrics_with_mask(bench_f, golden_f, sv_thresh)

    def ratio(x, y):
        if y == 0:
            if x == 0:
                return 1.0
            print(f"      [WARN] Bench metric=0 but NPU={x:.6e}, using error_thd as denom")
            return float(x / err_thd)
        return float(x / max(y, err_thd))

    r_mare, r_mere, r_rmse = ratio(npu_mare, bench_mare), ratio(npu_mere, bench_mere), ratio(npu_rmse, bench_rmse)
    p_mare = r_mare <= lv["mare_ratio"]
    p_mere = r_mere <= lv["mere_ratio"]
    p_rmse = r_rmse <= lv["rmse_ratio"]
    passed = p_mare and p_mere and p_rmse

    npu_sv, sv_total = calc_small_value_error_count(npu_f, golden_f, input_dtype)
    bench_sv, _ = calc_small_value_error_count(bench_f, golden_f, input_dtype)
    sv_ratio = npu_sv / max(bench_sv, 1) if sv_total > 0 else 0
    p_sv = sv_ratio <= 2
    passed = passed and p_sv

    if verbose:
        status = "PASS" if passed else "FAIL"
        print(f"    {name:15s} ({level}):")
        print(f"      NPU   - MARE={npu_mare:.6e}, MERE={npu_mere:.6e}, RMSE={npu_rmse:.6e}")
        print(f"      Bench - MARE={bench_mare:.6e}, MERE={bench_mere:.6e}, RMSE={bench_rmse:.6e}")
        print(f"      Ratio - MARE={r_mare:.2f}(<={lv['mare_ratio']}), "
              f"MERE={r_mere:.2f}(<={lv['mere_ratio']}), "
              f"RMSE={r_rmse:.2f}(<={lv['rmse_ratio']}) [{status}]")
        if sv_total > 0:
            print(f"      SmallValue - NPU_errors={npu_sv}, Bench_errors={bench_sv}, "
                  f"ratio={sv_ratio:.2f}(<=2) [{'PASS' if p_sv else 'FAIL'}]")
    return passed, {"r_mare": r_mare, "r_mere": r_mere, "r_rmse": r_rmse}

def print_failure_details(name, npu_val, bench_val, golden_val, input_dtype):
    golden_dtype = get_golden_dtype(input_dtype)
    npu_f = npu_val.to(golden_dtype)
    bench_f = bench_val.to(golden_dtype)
    golden_f = golden_val.to(golden_dtype)
    npu_diff = (npu_f - golden_f).abs()
    bench_diff = (bench_f - golden_f).abs()
    golden_abs = golden_f.abs() + 1e-7
    npu_re = npu_diff / golden_abs
    bench_re = bench_diff / golden_abs
    npu_idx = npu_re.argmax().item()
    bench_idx = bench_re.argmax().item()
    npu_pos = np.unravel_index(npu_idx, npu_val.shape)
    bench_pos = np.unravel_index(bench_idx, bench_val.shape)
    print(f"\n      [FAIL DEBUG] {name}:")
    print(f"        NPU   max RE at {npu_pos}: NPU={npu_f.flatten()[npu_idx]:.6e}, "
          f"Golden={golden_f.flatten()[npu_idx]:.6e}, RE={npu_re.flatten()[npu_idx]:.6e}")
    print(f"        Bench max RE at {bench_pos}: Bench={bench_f.flatten()[bench_idx]:.6e}, "
          f"Golden={golden_f.flatten()[bench_idx]:.6e}, RE={bench_re.flatten()[bench_idx]:.6e}")

def generate_tensor_with_distribution(shape, dtype, dist_type, seed=None, level="L2"):
    if seed is not None:
        torch.manual_seed(seed)
    if dist_type == 'uniform':
        t = torch.rand(shape) * 10 - 5
    elif dist_type == 'normal':
        mu = torch.rand(1).item() * 200 - 100
        sigma = torch.rand(1).item() * 24 + 1
        t = torch.randn(shape) * sigma + mu
    elif dist_type == 'outlier':
        t = torch.randn(shape)
        t[torch.rand(shape) < 0.001] *= 1000
    elif dist_type == 'small_uniform':
        t = torch.rand(shape) * 0.002 - 0.001
    else:
        t = torch.randn(shape)
    return t.to(dtype)

def get_distribution_type(test_idx, level="L2"):
    mod = test_idx % 10
    if level == "L0":
        return 'uniform' if mod < 5 else 'normal'
    else:
        if mod < 1: return 'small_uniform'
        elif mod < 4: return 'uniform'
        elif mod < 8: return 'normal'
        else: return 'outlier'
```

### 非计算类算子 — 需要内联的函数

```python
def compare_bitwise(name, actual, golden, verbose=True):
    match = torch.equal(actual, golden)
    mismatch = 0 if match else int((actual != golden).sum().item())
    if verbose:
        print(f"    {name:15s}: Bitwise Match [{'PASS' if match else 'FAIL'}] "
              f"(mismatches: {mismatch}/{actual.numel()})")
    return match, {"mismatch": mismatch}
```

### 整数计算算子 — 需要内联的函数

```python
def compare_integer(name, actual, golden, verbose=True):
    if torch.equal(actual, golden):
        if verbose: print(f"    {name:15s}: Integer Bitwise Match [PASS]")
        return True, {"max_ae": 0}
    ae = torch.abs(actual.long() - golden.long())
    max_ae = ae.max().item()
    passed = max_ae == 0
    if verbose:
        print(f"    {name:15s}: Integer AE [{('PASS' if passed else 'FAIL')}] (max_ae={max_ae})")
    return passed, {"max_ae": max_ae}
```

## Section 3: 算子专属实现

根据具体算子的计算逻辑实现。常见模式：

```python
# ==============================================================================
# Operator-Specific Implementations
# ==============================================================================

def golden_impl(*inputs_cpu, input_dtype):
    """CPU golden with precision +1. Returns single tensor or tuple."""
    golden_dtype = get_golden_dtype(input_dtype)
    # TODO: Convert inputs to golden_dtype, compute, return results
    pass

def bench_impl(*inputs_npu, input_dtype):
    """NPU small-ops bench (fp32 intermediate). Same return structure as golden."""
    # TODO: Compute using torch ops on NPU
    pass

def npu_custom_op(*inputs_npu):
    """Call custom AscendC operator. Same return structure as golden."""
    # return torch.ops.custom.npu_<op_name>(*inputs_npu)
    pass
```

## Section 4: 测试函数

### 精度测试（支持多输出）

```python
def test_correctness(test_idx=0, dtype=torch.float16, level="L2", **case_kwargs):
    seed = test_idx * 1000 + 42
    dist_type = get_distribution_type(test_idx, level=level)
    print(f"\n{'='*80}")
    print(f"Test #{test_idx}: params={case_kwargs}, dtype={dtype}, "
          f"dist={dist_type}, level={level}")
    print(f"{'='*80}")

    # TODO: Generate inputs, compute golden/bench/npu

    # --- Compare each output (multi-output pattern) ---
    # Normalize to tuples:
    # if not isinstance(golden_results, tuple):
    #     golden_results = (golden_results,)
    #     bench_results = (bench_results,)
    #     npu_results = (npu_results,)

    # output_names = ["grad_x", "grad_h_res", ...]
    # output_dtypes = [dtype, torch.float32, ...]

    all_passed = True
    # for name, npu_v, bench_v, golden_v, out_dtype in zip(
    #         output_names, npu_results, bench_results, golden_results, output_dtypes):
    #     gd = get_golden_dtype(out_dtype)
    #     passed, _ = compare_with_dual_benchmark(
    #         name, npu_v.cpu().to(gd), bench_v.cpu().to(gd),
    #         golden_v.to(gd), out_dtype, level=level)
    #     if not passed:
    #         print_failure_details(name, npu_v.cpu(), bench_v.cpu(), golden_v, out_dtype)
    #         all_passed = False

    print(f"\n  Test #{test_idx} Summary: [{'PASS' if all_passed else 'FAIL'}]")
    return all_passed
```

### 性能测试

```python
def test_performance(dtype=torch.float16, warmup=10, repeat=100, **case_kwargs):
    print(f"\n{'='*80}")
    print(f"Performance: params={case_kwargs}, dtype={dtype}")
    print(f"{'='*80}")
    # TODO: Create inputs, warmup, timing
    # torch_npu.npu.synchronize()
    # avg_ms = ...
    # print(f"  Average time: {avg_ms:.3f} ms")
    pass
```

## Section 5: Main + Final Summary

```python
def main():
    level = "L2"
    total_pass = 0
    total_fail = 0

    # test_cases = [
    #     {"B": 1, "S": 1024, "D": 5120, "dtype": torch.bfloat16, "desc": "typical bf16"},
    #     ...
    # ]

    # for idx, case in enumerate(test_cases):
    #     dtype = case.pop("dtype")
    #     desc = case.pop("desc", "")
    #     print(f"\n>>> Case {idx}: {desc}")
    #     if test_correctness(test_idx=idx, dtype=dtype, level=level, **case):
    #         total_pass += 1
    #     else:
    #         total_fail += 1

    # test_performance(...)

    print(f"\n{'='*80}")
    print("FINAL SUMMARY")
    print(f"{'='*80}")
    print(f"  Precision level: {level}")
    print(f"  Total cases: {total_pass + total_fail}")
    print(f"  Passed: {total_pass}")
    print(f"  Failed: {total_fail}")
    if total_pass + total_fail > 0:
        print(f"  Pass rate: {total_pass / (total_pass + total_fail) * 100:.1f}%")
    overall = "PASS" if total_fail == 0 else "FAIL"
    print(f"  Overall: [{overall}]")
    print(f"{'='*80}")

if __name__ == "__main__":
    main()
```
