#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Unit tests for SingleOperatorLaunch.precision_check (numpy 生态精度判定).

语义对齐 cann-bench RelativeErrorChecker / devkit precision_compare：
- 浮点 MERE/MARE + 小值域/相消/正常值域二阶段
- 整数/布尔精确匹配；threshold=0 浮点走 bit-exact
- golden 截断到 output dtype 再比较
"""

import numpy as np
import pytest

from SingleOperatorLaunch.precision_check import (
    DEFAULT_THRESHOLDS,
    CANCEL_BOUNDARY_THRESHOLDS,
    compare_tensor,
    compare_outputs,
    merge_thresholds,
    threshold_for_dtype,
)

FP32_THR = 2 ** -13
FP16_THR = 2 ** -10


# ---------------------------------------------------------------------------
# 阈值表 / 查表 / 合并
# ---------------------------------------------------------------------------

def test_default_thresholds_match_ecosystem():
    assert DEFAULT_THRESHOLDS["float16"] == 2 ** -10
    assert DEFAULT_THRESHOLDS["bfloat16"] == 2 ** -7
    assert DEFAULT_THRESHOLDS["float32"] == 2 ** -13
    assert DEFAULT_THRESHOLDS["float64"] == 2 ** -13
    assert DEFAULT_THRESHOLDS["float8_e4m3fn"] == 2 ** -3
    assert DEFAULT_THRESHOLDS["float8_e5m2"] == 2 ** -2
    assert DEFAULT_THRESHOLDS["int8"] == 0
    assert DEFAULT_THRESHOLDS["int32"] == 0


def test_threshold_lookup_alias_and_fallback():
    assert threshold_for_dtype("float16") == FP16_THR
    assert threshold_for_dtype("fp16") == FP16_THR       # 别名归一
    assert threshold_for_dtype("BFloat16") == 2 ** -7    # 大小写不敏感
    assert threshold_for_dtype("no_such_dtype") == FP32_THR  # 未知回退 float32


def test_merge_thresholds_override():
    merged = merge_thresholds({"float16": 1.0, "int8": 1.0})
    assert merged["float16"] == 1.0
    assert merged["int8"] == 1.0
    assert merged["float32"] == FP32_THR  # 未覆盖项保留默认


# ---------------------------------------------------------------------------
# 浮点 MERE/MARE stage-1
# ---------------------------------------------------------------------------

def test_float32_exact_pass():
    golden = np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float64)
    out = np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float32)
    v = compare_tensor(out, golden, dtype="float32")
    assert v.passed
    assert v.mere == 0.0 and v.mare == 0.0
    assert v.max_diff == 0.0
    assert v.threshold == FP32_THR


def test_float32_golden_truncated_to_output_dtype():
    # golden 在 fp32 上无法表示的尾数 → 截断后应与 output（fp32 舍入值）一致
    golden = np.array([1.0 + 1e-10, 2.0 + 3e-10], dtype=np.float64)
    out = golden.astype(np.float32)
    v = compare_tensor(out, golden, dtype="float32")
    assert v.passed
    assert v.max_diff == 0.0


def test_float32_large_error_fails():
    golden = np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float64)
    out = np.array([1.5, 2.0, 3.0, 4.0], dtype=np.float32)  # 1 号元素 rel err 0.5
    v = compare_tensor(out, golden, dtype="float32")
    assert not v.passed
    assert v.normal_passed is False   # 正常值域超标 + CPU 参考干净 → 严格失败
    assert v.mismatch_count == 1


def test_float32_mare_below_10x_threshold_passes_stage1():
    # 单点 rel err = 5*thr（< 10*thr）→ stage-1 MARE 仍达标 → 直接通过
    n = 10000
    golden = np.ones(n, dtype=np.float64)
    out = golden.copy()
    out[0] = 1.0 + 5 * FP32_THR
    v = compare_tensor(out.astype(np.float32), golden, dtype="float32")
    assert v.passed
    assert v.mare > FP32_THR           # 确实触发相对误差
    assert v.mare < 10 * FP32_THR


def test_float32_mare_above_10x_threshold_fails():
    n = 10000
    golden = np.ones(n, dtype=np.float64)
    out = golden.copy()
    out[0] = 1.0 + 11 * FP32_THR       # 单点 rel err > 10*thr
    v = compare_tensor(out.astype(np.float32), golden, dtype="float32")
    assert not v.passed
    assert v.normal_passed is False
    assert v.mismatch_count == 1


# ---------------------------------------------------------------------------
# 小值域兜底
# ---------------------------------------------------------------------------

def test_small_value_fallback_pass():
    # |golden| < 2^-14：单点误差计入小值域，ratio=1 <= 2 → 兜底通过
    small = 1e-7
    golden = np.array([small, 1.0, 2.0, 3.0], dtype=np.float64)
    out = np.array([small + 1e-6, 1.0, 2.0, 3.0], dtype=np.float32)
    v = compare_tensor(out, golden, dtype="float32")
    assert v.passed
    assert v.small_value_passed is True


def test_small_value_fallback_fail_ratio_over_2():
    # 3 个小值域误差 > 2 允许上限 → 失败
    small = 1e-7
    golden = np.array([small] * 4 + [1.0, 2.0, 3.0, 4.0], dtype=np.float64)
    out = np.array([small + 1e-6] * 4 + [1.0, 2.0, 3.0, 4.0], dtype=np.float32)
    v = compare_tensor(out, golden, dtype="float32")
    assert not v.passed
    assert v.small_value_passed is False


# ---------------------------------------------------------------------------
# 正常值域同精度兜底（native 脏时放宽）
# ---------------------------------------------------------------------------

def test_normal_region_native_dirty_relaxes():
    golden = np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float64)
    out = np.array([1.5, 2.0, 3.0, 4.0], dtype=np.float32)
    native = out.copy()  # 同精度参考自身也超标
    v = compare_tensor(out, golden, dtype="float32", native_ref=native)
    assert v.passed
    assert v.normal_passed is True


# ---------------------------------------------------------------------------
# 相消兜底
# ---------------------------------------------------------------------------

def test_cancel_fallback_pass():
    # golden = 1e-3 ∈ [svt, cancel_boundary)，output≈0 → 相消兜底通过
    golden = np.array([1e-3, 1.0, 2.0, 3.0], dtype=np.float64)
    out = np.array([0.0, 1.0, 2.0, 3.0], dtype=np.float32)
    v = compare_tensor(out, golden, dtype="float32")
    assert v.passed
    assert v.cancel_passed is True


# ---------------------------------------------------------------------------
# NaN / Inf
# ---------------------------------------------------------------------------

def test_nan_position_mismatch_fails():
    golden = np.array([1.0, 2.0, np.nan], dtype=np.float64)
    out = np.array([1.0, 2.0, 3.0], dtype=np.float32)
    v = compare_tensor(out, golden, dtype="float32")
    assert not v.passed
    assert v.error_msg == "NaN位置不匹配"


def test_nan_position_match_passes():
    golden = np.array([1.0, np.nan], dtype=np.float64)
    out = np.array([1.0, np.nan], dtype=np.float32)
    v = compare_tensor(out, golden, dtype="float32")
    assert v.passed


def test_inf_sign_mismatch_fails():
    golden = np.array([np.inf, 1.0], dtype=np.float64)
    out = np.array([-np.inf, 1.0], dtype=np.float32)
    v = compare_tensor(out, golden, dtype="float32")
    assert not v.passed
    assert v.error_msg == "Inf符号不匹配"


# ---------------------------------------------------------------------------
# bit-exact（threshold=0 浮点）
# ---------------------------------------------------------------------------

def test_bit_exact_distinguishes_signed_zero():
    golden = np.array([-0.0, 1.0], dtype=np.float64)
    out = np.array([0.0, 1.0], dtype=np.float32)
    v = compare_tensor(out, golden, dtype="float32", threshold=0.0)
    assert not v.passed
    assert v.mismatch_count == 1
    v2 = compare_tensor(out.copy(), np.array([0.0, 1.0], dtype=np.float64),
                        dtype="float32", threshold=0.0)
    assert v2.passed


# ---------------------------------------------------------------------------
# 整数 / 布尔
# ---------------------------------------------------------------------------

def test_integer_exact_pass_and_fail():
    g = np.arange(10, dtype=np.int32)
    o = g.copy()
    assert compare_tensor(o, g, dtype="int32").passed
    o[3] += 1
    v = compare_tensor(o, g, dtype="int32")
    assert not v.passed
    assert v.mismatch_count == 1
    assert v.max_diff == 1.0


def test_integer_absdiff_threshold_override():
    g = np.arange(10, dtype=np.int32)
    o = g.copy()
    o[3] += 1  # ±1
    v = compare_tensor(o, g, dtype="int32", thresholds={"int32": 1.0})
    assert v.passed


def test_bool_exact():
    g = np.array([True, False, True])
    o = g.copy()
    assert compare_tensor(o, g, dtype="bool").passed
    o[0] = False
    assert not compare_tensor(o, g, dtype="bool").passed


# ---------------------------------------------------------------------------
# 结构性问题 / 多输出
# ---------------------------------------------------------------------------

def test_shape_mismatch_fails():
    v = compare_tensor(np.zeros(4, dtype=np.float32),
                       np.zeros(5, dtype=np.float64), dtype="float32")
    assert not v.passed
    assert v.shape_mismatch


def test_compare_outputs_multi_and_aggregate():
    g1 = np.array([1.0, 2.0], dtype=np.float64)
    o1 = np.array([1.0, 2.0], dtype=np.float32)
    g2 = np.array([1, 2, 3], dtype=np.int64)
    o2 = np.array([1, 2, 9], dtype=np.int64)
    passed, verdicts = compare_outputs([o1, o2], [g1, g2])
    assert not passed
    assert verdicts[0].passed
    assert not verdicts[1].passed


def test_bfloat16_support():
    ml_dtypes = pytest.importorskip("ml_dtypes")
    bf16 = ml_dtypes.bfloat16
    golden = np.array([1.0, 2.0, 3.0], dtype=np.float64)
    out = golden.astype(bf16)
    v = compare_tensor(out, golden, dtype="bfloat16")
    assert v.passed
    assert v.threshold == 2 ** -7
    assert v.max_diff == 0.0
