#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AscendC Operator Testing - Precision Utilities

Multi-type, multi-level precision verification for operator correctness testing.
Supports non-compute, integer, quantized, and floating-point operator categories
with L0/L1/L2 precision levels.

Usage:
    from precision_utils import (
        generate_tensor_with_distribution,
        get_golden_dtype,
        compare_with_dual_benchmark,
        compare_bitwise,
        compare_integer,
        compare_quantized,
        recheck_with_bootstrap,
    )
"""

import torch
import numpy as np


# ==============================================================================
# Data Generation
# ==============================================================================

def generate_tensor_with_distribution(shape, dtype, dist_type, seed=None, level="L2"):
    """
    Generate tensor with specified distribution.

    Distribution strategy varies by precision level:
        L0: 50% uniform[-5,5] + 50% normal
        L1/L2: 10% small uniform[-0.001,0.001] + 30% uniform[-5,5]
                + 40% normal + 20% outlier

    Args:
        shape: Tensor shape
        dtype: Data type (torch.float16, torch.bfloat16, torch.float32)
        dist_type: Distribution type ('uniform', 'normal', 'outlier',
                   'small_uniform', 'default')
        seed: Random seed (optional)
        level: Precision level ("L0", "L1", "L2"), affects distribution mix

    Returns:
        Generated tensor
    """
    if seed is not None:
        torch.manual_seed(seed)

    if dist_type == 'uniform':
        # Uniform distribution [-5, 5]
        tensor = torch.rand(shape) * 10 - 5
    elif dist_type == 'normal':
        # Normal distribution mu in [-100, 100], sigma in [1, 25]
        mu = torch.rand(1).item() * 200 - 100
        sigma = torch.rand(1).item() * 24 + 1
        tensor = torch.randn(shape) * sigma + mu
    elif dist_type == 'outlier':
        # Outlier distribution: normal + 0.1% values * 1000
        tensor = torch.randn(shape)
        outlier_mask = torch.rand(shape) < 0.001
        tensor[outlier_mask] *= 1000
    elif dist_type == 'small_uniform':
        # Small uniform distribution [-0.001, 0.001]
        tensor = torch.rand(shape) * 0.002 - 0.001
    else:
        # Default: standard normal
        tensor = torch.randn(shape)

    return tensor.to(dtype)


def get_distribution_type(test_idx, level="L2"):
    """
    Get distribution type based on test index and precision level.

    L0 coverage: 50% uniform, 50% normal
    L1/L2 coverage: 10% small_uniform, 30% uniform, 40% normal, 20% outlier

    Args:
        test_idx: Test case index
        level: Precision level ("L0", "L1", "L2")

    Returns:
        Distribution type string
    """
    mod = test_idx % 10
    if level == "L0":
        # L0: 50% uniform, 50% normal
        if mod < 5:
            return 'uniform'
        else:
            return 'normal'
    else:
        # L1/L2: 10% small, 30% uniform, 40% normal, 20% outlier
        if mod < 1:
            return 'small_uniform'
        elif mod < 4:
            return 'uniform'
        elif mod < 8:
            return 'normal'
        else:
            return 'outlier'


# ==============================================================================
# Precision Helpers
# ==============================================================================

def get_golden_dtype(input_dtype):
    """
    Get golden dtype (precision +1 level).

    Rules:
        fp16/bf16 -> fp32
        fp32 -> fp64

    Args:
        input_dtype: Input data type

    Returns:
        Golden data type
    """
    if input_dtype in [torch.float16, torch.bfloat16]:
        return torch.float32
    return torch.float64


def get_small_value_thresh(dtype_in):
    """
    Get small value domain threshold (SmallValueThreshold).

    Values where |golden| <= threshold are excluded from MARE/MERE/RMSE
    and evaluated separately via SmallValueErrorThreshold.

    Args:
        dtype_in: Input data type (torch dtype or string)

    Returns:
        Small value threshold
    """
    dtype_str = str(dtype_in).lower()
    # Check bfloat16 before float16 (bfloat16 string contains 'float16')
    if dtype_in == torch.bfloat16 or 'bfloat16' in dtype_str:
        return 2**-8    # ~3.91e-3
    elif dtype_in == torch.float16 or 'float16' in dtype_str:
        return 2**-11   # ~4.88e-4
    elif 'hifloat32' in dtype_str:
        return 2**-12   # ~2.44e-4
    elif 'e4m3' in dtype_str:
        return 2**-4    # ~6.25e-2
    elif 'e5m2' in dtype_str:
        return 2**-3    # ~1.25e-1
    else:  # float32 default
        return 2**-14   # ~6.10e-5


def get_small_value_error_thresh(dtype_in):
    """
    Get small value error threshold (SmallValueErrorThreshold).

    In the small value domain (|golden| <= SmallValueThreshold),
    if |actual - golden| > SmallValueErrorThreshold, it counts as an error.

    Args:
        dtype_in: Input data type (torch dtype or string)

    Returns:
        Small value error threshold
    """
    dtype_str = str(dtype_in).lower()
    # Check bfloat16 before float16 (bfloat16 string contains 'float16')
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
    else:  # float32 default
        return 2**-30


def get_error_thd(dtype_in):
    """
    Get error threshold for ratio calculation.

    Used in: ratio = npu_metric / max(bench_metric, error_thd)

    Args:
        dtype_in: Input data type

    Returns:
        Error threshold
    """
    if dtype_in == torch.float16:
        return 2**-11
    elif dtype_in == torch.bfloat16:
        return 2**-8
    else:  # float32
        return 2**-14


def get_level_thresholds(level="L2"):
    """
    Get MARE/MERE/RMSE ratio thresholds for a given precision level.

    Args:
        level: Precision level ("L0", "L1", "L2")

    Returns:
        Dict with keys 'mare_ratio', 'mere_ratio', 'rmse_ratio'
    """
    thresholds = {
        "L0": {"mare_ratio": 10.0, "mere_ratio": 2.0, "rmse_ratio": 2.0},
        "L1": {"mare_ratio": 5.0,  "mere_ratio": 1.5, "rmse_ratio": 1.5},
        "L2": {"mare_ratio": 2.0,  "mere_ratio": 1.2, "rmse_ratio": 1.2},
    }
    if level not in thresholds:
        raise ValueError(f"Unknown precision level: {level}. Must be L0, L1, or L2.")
    return thresholds[level]


def real_ratio(x, y, error_thd, default_value=1.0):
    """
    Calculate ratio with threshold protection.

    Args:
        x: Numerator (NPU metric)
        y: Denominator (Bench metric)
        error_thd: Error threshold
        default_value: Default when y=0 and x!=0

    Returns:
        ratio: x / max(y, error_thd)
    """
    if y == 0:
        if x == 0:
            return 1.0
        # Bench has zero error but NPU doesn't — likely a bench implementation issue.
        # Return ratio against error_thd so the threshold still gates the result,
        # rather than silently passing with default_value=1.0.
        print(f"      [WARN] Bench metric=0 but NPU metric={x:.6e}, "
              f"using error_thd={error_thd:.6e} as denominator")
        return float(x / error_thd)
    return float(x / max(y, error_thd))


# ==============================================================================
# Metrics Calculation
# ==============================================================================

def calc_metrics_with_mask(actual, golden, small_value_thresh):
    """
    Calculate MARE, MERE, RMSE excluding small value domain.

    Args:
        actual: Actual values (golden dtype)
        golden: Golden values (golden dtype)
        small_value_thresh: Small value threshold

    Returns:
        mare: Max Absolute Relative Error
        mere: Mean Absolute Relative Error
        rmse: Root Mean Squared Error
    """
    # Partition: small value domain vs non-small value domain
    mask = torch.abs(golden) > small_value_thresh

    # Non-small value domain data
    actual_large = actual[mask]
    golden_large = golden[mask]

    # Compute inf/nan mask
    inf_nan_mask = ~torch.isfinite(actual_large) | ~torch.isfinite(golden_large)

    if inf_nan_mask.all() or golden_large.numel() == 0:
        return 0.0, 0.0, 0.0

    # Relative error: diff / (|golden| + 1e-7)
    abs_diff = torch.abs(actual_large - golden_large)
    re = abs_diff / (torch.abs(golden_large) + 1e-7)

    # MARE/MERE excluding inf/nan
    valid_re = re[~inf_nan_mask]
    mare = valid_re.max().item() if valid_re.numel() > 0 else 0.0
    mere = valid_re.mean().item() if valid_re.numel() > 0 else 0.0

    # RMSE: sqrt(sum((a-g)^2) / numel)
    diff = actual_large[~inf_nan_mask] - golden_large[~inf_nan_mask]
    rmse = torch.sqrt(torch.sum(diff * diff) / diff.numel()).item() if diff.numel() > 0 else 0.0

    return mare, mere, rmse


def calc_small_value_error_count(actual, golden, dtype_in):
    """
    Count errors in the small value domain.

    In the small value domain (|golden| <= SmallValueThreshold),
    an element is an error if |actual - golden| > SmallValueErrorThreshold.

    Args:
        actual: Actual values tensor
        golden: Golden values tensor
        dtype_in: Input data type (for threshold lookup)

    Returns:
        error_count: Number of elements exceeding SmallValueErrorThreshold
        total_small: Total number of elements in small value domain
    """
    small_thresh = get_small_value_thresh(dtype_in)
    error_thresh = get_small_value_error_thresh(dtype_in)

    # Small value domain mask
    small_mask = torch.abs(golden) <= small_thresh

    if not small_mask.any():
        return 0, 0

    actual_small = actual[small_mask]
    golden_small = golden[small_mask]

    abs_diff = torch.abs(actual_small - golden_small)
    error_count = int((abs_diff > error_thresh).sum().item())
    total_small = int(small_mask.sum().item())

    return error_count, total_small


# ==============================================================================
# Comparison — By Operator Type
# ==============================================================================

def compare_bitwise(name, actual, golden, verbose=True):
    """
    Bitwise comparison for non-compute operators (Gather, Scatter, Cast, etc.).

    All elements must match exactly (bitwise identical).

    Args:
        name: Output name for logging
        actual: NPU output tensor
        golden: Golden output tensor
        verbose: Print detailed info

    Returns:
        passed: Whether all elements match
        metrics: Dict with match info
    """
    match = torch.equal(actual, golden)
    mismatch_count = 0
    total = actual.numel()

    if not match:
        mismatch_count = int((actual != golden).sum().item())

    status = "PASS" if match else "FAIL"

    if verbose:
        print(f"    {name:15s}: Bitwise Match [{status}]"
              f" (mismatches: {mismatch_count}/{total})")

    metrics = {
        "bitwise_match": match,
        "mismatch_count": mismatch_count,
        "total_elements": total,
    }
    return match, metrics


def compare_integer(name, actual, golden, verbose=True):
    """
    Integer comparison for integer compute operators (INT8/16/32 Add, Mul, etc.).

    Primary: Bitwise Match. Fallback: AE = 0 for all elements.

    Args:
        name: Output name for logging
        actual: NPU output tensor (integer type)
        golden: Golden output tensor (integer type)
        verbose: Print detailed info

    Returns:
        passed: Whether test passed
        metrics: Dict with match info
    """
    bitwise_match = torch.equal(actual, golden)

    if bitwise_match:
        if verbose:
            print(f"    {name:15s}: Integer Bitwise Match [PASS]")
        return True, {"bitwise_match": True, "max_ae": 0}

    # Fallback: check AE = 0
    ae = torch.abs(actual.long() - golden.long())
    max_ae = ae.max().item()
    passed = max_ae == 0

    status = "PASS" if passed else "FAIL"
    if verbose:
        print(f"    {name:15s}: Integer AE check [{status}]"
              f" (max_ae={max_ae}, bitwise={bitwise_match})")

    metrics = {
        "bitwise_match": bitwise_match,
        "max_ae": max_ae,
    }
    return passed, metrics


def compare_quantized(name, actual, golden, output_is_int=True,
                      bench_val=None, input_dtype=None, verbose=True, level="L2"):
    """
    Comparison for quantized operators (FLOAT4/8/INT8 Quant/Dequant/QLinear).

    If output is integer: AE <= 1 for all elements.
    If output is float: delegate to dual-benchmark comparison.

    Args:
        name: Output name for logging
        actual: NPU output tensor
        golden: Golden output tensor
        output_is_int: Whether output type is integer
        bench_val: Bench output (required when output_is_int=False)
        input_dtype: Input dtype (required when output_is_int=False)
        verbose: Print detailed info
        level: Precision level for float output path

    Returns:
        passed: Whether test passed
        metrics: Dict with match info
    """
    if output_is_int:
        ae = torch.abs(actual.long() - golden.long())
        max_ae = ae.max().item()
        passed = max_ae <= 1

        status = "PASS" if passed else "FAIL"
        if verbose:
            print(f"    {name:15s}: Quantized int output [{status}]"
                  f" (max_ae={max_ae}, threshold=1)")

        return passed, {"max_ae": max_ae, "output_type": "int"}
    else:
        if bench_val is None or input_dtype is None:
            raise ValueError("bench_val and input_dtype required for float output quantized comparison")
        return compare_with_dual_benchmark(
            name, actual, bench_val, golden, input_dtype,
            verbose=verbose, level=level)


# ==============================================================================
# Dual Benchmark Comparison
# ==============================================================================

def compare_with_dual_benchmark(name, npu_val, bench_val, golden_val, input_dtype,
                                verbose=True, level="L2"):
    """
    Dual benchmark comparison with L0/L1/L2 thresholds.

    Three-way comparison:
        Golden (CPU, precision +1) vs Bench (NPU/CPU) vs NPU (custom kernel)

    Threshold levels:
        L0: MARE<=10, MERE<=2.0, RMSE<=2.0
        L1: MARE<=5,  MERE<=1.5, RMSE<=1.5
        L2: MARE<=2,  MERE<=1.2, RMSE<=1.2

    Args:
        name: Output name for logging
        npu_val: NPU operator output (CPU tensor)
        bench_val: Bench output (CPU tensor)
        golden_val: Golden output (high precision)
        input_dtype: Input data type (for threshold selection)
        verbose: Print detailed info
        level: Precision level ("L0", "L1", "L2"), default "L2"

    Returns:
        passed: Whether test passed
        metrics: Dict with detailed metrics
    """
    # Golden dtype is one level higher than input
    golden_dtype = get_golden_dtype(input_dtype)
    npu_val_for_diff = npu_val.to(golden_dtype)
    bench_val_for_diff = bench_val.to(golden_dtype)
    golden_val_for_diff = golden_val.to(golden_dtype)

    # Get thresholds
    small_value_thresh = get_small_value_thresh(input_dtype)
    error_thd = get_error_thd(input_dtype)
    level_thresholds = get_level_thresholds(level)

    # Calculate metrics
    npu_mare, npu_mere, npu_rmse = calc_metrics_with_mask(
        npu_val_for_diff, golden_val_for_diff, small_value_thresh)
    bench_mare, bench_mere, bench_rmse = calc_metrics_with_mask(
        bench_val_for_diff, golden_val_for_diff, small_value_thresh)

    # Calculate ratios
    ratio_mare = real_ratio(npu_mare, bench_mare, error_thd)
    ratio_mere = real_ratio(npu_mere, bench_mere, error_thd)
    ratio_rmse = real_ratio(npu_rmse, bench_rmse, error_thd)

    # Level-based thresholds
    pass_mare = ratio_mare <= level_thresholds["mare_ratio"]
    pass_mere = ratio_mere <= level_thresholds["mere_ratio"]
    pass_rmse = ratio_rmse <= level_thresholds["rmse_ratio"]
    passed = pass_mare and pass_mere and pass_rmse

    # Small value domain check
    npu_sv_errors, sv_total = calc_small_value_error_count(
        npu_val_for_diff, golden_val_for_diff, input_dtype)
    bench_sv_errors, _ = calc_small_value_error_count(
        bench_val_for_diff, golden_val_for_diff, input_dtype)
    sv_ratio = npu_sv_errors / max(bench_sv_errors, 1) if sv_total > 0 else 0
    pass_sv = sv_ratio <= 2
    passed = passed and pass_sv

    status = "PASS" if passed else "FAIL"

    if verbose:
        print(f"    {name:15s} ({level}):")
        print(f"      NPU   - MARE={npu_mare:.6e}, MERE={npu_mere:.6e}, RMSE={npu_rmse:.6e}")
        print(f"      Bench - MARE={bench_mare:.6e}, MERE={bench_mere:.6e}, RMSE={bench_rmse:.6e}")
        print(f"      Ratio - MARE={ratio_mare:.2f}(<={level_thresholds['mare_ratio']}), "
              f"MERE={ratio_mere:.2f}(<={level_thresholds['mere_ratio']}), "
              f"RMSE={ratio_rmse:.2f}(<={level_thresholds['rmse_ratio']}) [{status}]")
        if sv_total > 0:
            print(f"      SmallValue - NPU_errors={npu_sv_errors}, Bench_errors={bench_sv_errors}, "
                  f"ratio={sv_ratio:.2f}(<=2) [{'PASS' if pass_sv else 'FAIL'}]")

    metrics = {
        "npu_mare": npu_mare, "npu_mere": npu_mere, "npu_rmse": npu_rmse,
        "bench_mare": bench_mare, "bench_mere": bench_mere, "bench_rmse": bench_rmse,
        "ratio_mare": ratio_mare, "ratio_mere": ratio_mere, "ratio_rmse": ratio_rmse,
        "pass_mare": pass_mare, "pass_mere": pass_mere, "pass_rmse": pass_rmse,
        "level": level,
        "sv_npu_errors": npu_sv_errors, "sv_bench_errors": bench_sv_errors,
        "sv_ratio": sv_ratio, "pass_sv": pass_sv,
    }

    return passed, metrics


# ==============================================================================
# Bootstrap Recheck
# ==============================================================================

def recheck_with_bootstrap(test_fn, n_runs=1000):
    """
    Bootstrap statistical recheck for borderline test cases.

    When a single test case fails, run test_fn with different random seeds
    and check if the median error ratio's 95% CI includes values <= 1.

    Args:
        test_fn: Callable(seed) -> dict with ratio keys
                 (e.g. {"ratio_mare": 2.1, "ratio_mere": 1.3, "ratio_rmse": 1.1})
        n_runs: Number of bootstrap runs (default 1000)

    Returns:
        passed: Whether recheck passed (CI_lower <= 1 for all metrics)
        stats: Dict with median, CI_lower, CI_upper, n_runs per metric
    """
    if n_runs < 200:
        return False, {"reason": "n_runs < 200, insufficient for bootstrap", "n_runs": n_runs}

    # Collect ratios from all runs
    all_ratios = {"ratio_mare": [], "ratio_mere": [], "ratio_rmse": []}

    for i in range(n_runs):
        seed = 10000 + i
        result = test_fn(seed)
        for key in all_ratios:
            if key in result:
                all_ratios[key].append(result[key])

    stats = {"n_runs": n_runs}
    all_pass = True

    for key, values in all_ratios.items():
        if not values:
            continue
        arr = np.array(sorted(values))
        median = float(np.median(arr))
        ci_lower = float(np.percentile(arr, 2.5))
        ci_upper = float(np.percentile(arr, 97.5))

        metric_pass = ci_lower <= 1.0
        all_pass = all_pass and metric_pass

        stats[key] = {
            "median": median,
            "CI_lower": ci_lower,
            "CI_upper": ci_upper,
            "passed": metric_pass,
        }

    return all_pass, stats


# ==============================================================================
# Debug Utilities
# ==============================================================================

def print_failure_details(name, npu_val, bench_val, golden_val, input_dtype):
    """
    Print detailed debug info when test fails.

    Args:
        name: Output name
        npu_val: NPU output
        bench_val: Bench output
        golden_val: Golden output
        input_dtype: Input data type
    """
    golden_dtype = get_golden_dtype(input_dtype)
    npu_val_for_diff = npu_val.to(golden_dtype)
    bench_val_for_diff = bench_val.to(golden_dtype)
    golden_val_for_diff = golden_val.to(golden_dtype)

    print(f"\n      [FAIL DEBUG] {name} Tensor Details:")
    print(f"      Shape: {npu_val.shape}")

    # Absolute error
    npu_diff = (npu_val_for_diff - golden_val_for_diff).abs()
    bench_diff = (bench_val_for_diff - golden_val_for_diff).abs()

    # Relative error
    golden_abs = golden_val_for_diff.abs() + 1e-7
    npu_re = npu_diff / golden_abs
    bench_re = bench_diff / golden_abs

    # MARE - max relative error position
    npu_max_re_idx = npu_re.argmax().item()
    bench_max_re_idx = bench_re.argmax().item()
    npu_max_re_pos = np.unravel_index(npu_max_re_idx, npu_val.shape)
    bench_max_re_pos = np.unravel_index(bench_max_re_idx, bench_val.shape)

    print(f"      [MARE - Max Relative Error Position]")
    print(f"        NPU   at {npu_max_re_pos}: "
          f"NPU={npu_val_for_diff.flatten()[npu_max_re_idx]:.6e}, "
          f"Golden={golden_val_for_diff.flatten()[npu_max_re_idx]:.6e}, "
          f"RE={npu_re.flatten()[npu_max_re_idx]:.6e}")
    print(f"        Bench at {bench_max_re_pos}: "
          f"Bench={bench_val_for_diff.flatten()[bench_max_re_idx]:.6e}, "
          f"Golden={golden_val_for_diff.flatten()[bench_max_re_idx]:.6e}, "
          f"RE={bench_re.flatten()[bench_max_re_idx]:.6e}")

    # Small value domain info
    sv_npu_errors, sv_total = calc_small_value_error_count(
        npu_val_for_diff, golden_val_for_diff, input_dtype)
    sv_bench_errors, _ = calc_small_value_error_count(
        bench_val_for_diff, golden_val_for_diff, input_dtype)
    if sv_total > 0:
        print(f"      [Small Value Domain]")
        print(f"        Total small values: {sv_total}")
        print(f"        NPU errors: {sv_npu_errors}, Bench errors: {sv_bench_errors}")

    # Statistics
    print(f"      [Statistics]")
    print(f"        NPU   - min={npu_val_for_diff.min():.6e}, max={npu_val_for_diff.max():.6e}, "
          f"mean={npu_val_for_diff.mean():.6e}")
    print(f"        Bench - min={bench_val_for_diff.min():.6e}, max={bench_val_for_diff.max():.6e}, "
          f"mean={bench_val_for_diff.mean():.6e}")
    print(f"        Golden- min={golden_val_for_diff.min():.6e}, max={golden_val_for_diff.max():.6e}, "
          f"mean={golden_val_for_diff.mean():.6e}")
    print()
