#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Precision check for RegBase VF unit tests (numpy implementation).

判定语义与 cann-bench ``kernel_eval/utils/compare.py``（RelativeErrorChecker，
生态算子开源精度标准）及 devkit ``precision_compare.py`` 逐分支一致：

- 按**输出 dtype** 查阈值：浮点走 MERE/MARE 相对误差，整数/布尔走精确匹配。
- 浮点阈值表 = 生态算子精度标准（cann-bench PRECISION_THRESHOLDS）：
  fp16=2^-10 / bf16=2^-7 / fp32=fp64=2^-13 / hifp32=2^-11 /
  fp8_e4m3fn=2^-3 / fp8_e5m2=2^-2；整数阈值 0（精确）。
- stage-1：MERE = mean(|a-g|/(|g|+1e-7))、MARE = max(...)；
  ``MERE < threshold AND MARE < 10*threshold`` → 通过。
- stage-2（stage-1 不过才触发）：小值域（|golden| < small_value_threshold）与
  相消（output≈0 且 golden 落在 [svt, cancel_boundary)）兜底，判据
  ``ErrorCount_npu / max(ErrorCount_native,1) <= 2``；正常值域有超标点时，
  仅当同精度参考自身也超标（native 脏）才允许 ratio<=2，否则严格失败。
- NaN 位置不匹配 → fail；单边 inf 饱和到 dtype 最大有限值续比；
  双边同号 inf 视为匹配并排除。
- golden 先截断到 output dtype 再升 fp64 比较（模拟算子输出精度限制）。
- threshold==0 的浮点（调用方显式要求 bit-exact）→ 字节级比较，
  区分 +0.0/-0.0、NaN payload、Inf 符号。

本模块仅依赖 numpy（低精度 dtype 由调用方用 ttk.utilities.dtypes 构造好再传入），
供 SingleOperatorLaunch 生成的 VF 测试脚本做精度验收——它是 vf-test 阶段
**唯一**的精度判定通路（§2.5 单通路），禁止在测试脚本里再手写 np.allclose 容差。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional, Union

import numpy as np

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 阈值数据（作传递数据，值对齐 cann-bench thresholds.py / devkit precision_compare）
# ---------------------------------------------------------------------------

# 浮点相对误差阈值（生态算子开源精度标准）。整数类型阈值 0 → 精确匹配。
DEFAULT_THRESHOLDS: dict[str, float] = {
    "float16": 2 ** -10,      # ≈ 9.77e-4
    "bfloat16": 2 ** -7,      # ≈ 7.81e-3
    "float32": 2 ** -13,      # ≈ 1.22e-4
    "float64": 2 ** -13,
    "hifloat32": 2 ** -11,
    "float8_e4m3fn": 2 ** -3,
    "float8_e5m2": 2 ** -2,
    "int8": 0,
    "int16": 0,
    "int32": 0,
    "int64": 0,
    "uint8": 0,
    "uint16": 0,
    "uint32": 0,
    "uint64": 0,
}

# 小值域阈值：|golden| < small_value_threshold 时启用小值域兜底判定。
SMALL_VALUE_THRESHOLDS: dict[str, float] = {
    "float16": 2 ** -11,
    "bfloat16": 2 ** -8,
    "float32": 2 ** -14,
    "float64": 2 ** -14,
    "hifloat32": 2 ** -12,
    "float8_e4m3fn": 2 ** -4,
    "float8_e5m2": 2 ** -3,
}

# 小值域误差阈值：小值域内 |actual - golden| > 此值 计入 ErrorCount。
SMALL_VALUE_ERROR_THRESHOLDS: dict[str, float] = {
    "float16": 2 ** -16,
    "bfloat16": 2 ** -16,
    "float32": 2 ** -30,
    "float64": 2 ** -30,
    "hifloat32": 2 ** -28,
    "float8_e4m3fn": 2 ** -6,
    "float8_e5m2": 2 ** -5,
}

# 相消边界：golden 落在 [small_value_threshold, cancel_boundary) 且 output≈0 → 相消嫌疑。
CANCEL_BOUNDARY_THRESHOLDS: dict[str, float] = {
    "float32": 2 ** -8,
    "float64": 2 ** -8,
    "float16": 2 ** -5,
    "bfloat16": 2 ** -3,
    "hifloat32": 2 ** -8,
    "float8_e4m3fn": 2 ** -1,
    "float8_e5m2": 2 ** -0,
}

# 相消 output 零值判定：|output| < cancel_zero_threshold → 视 output≈0。
CANCEL_ZERO_THRESHOLDS: dict[str, float] = {
    "float32": 2 ** -8,
    "float64": 2 ** -8,
    "float16": 2 ** -5,
    "bfloat16": 2 ** -3,
    "hifloat32": 2 ** -8,
    "float8_e4m3fn": 2 ** -1,
    "float8_e5m2": 2 ** -0,
}

# 各 dtype 的最大有限值（inf 饱和用；ml_dtypes 低精度类型无 np.finfo）。
_MAX_FINITE_BY_NAME: dict[str, float] = {
    "float16": float(np.finfo(np.float16).max),   # 65504.0
    "bfloat16": 2.0 ** 128 * (1.0 - 2.0 ** -8),    # ≈ 3.3895e38
    "float32": float(np.finfo(np.float32).max),    # ≈ 3.4028e38
    "float64": float(np.finfo(np.float64).max),    # ≈ 1.7977e308
    "float8_e4m3fn": 448.0,
    "float8_e5m2": 57344.0,
    "hifloat32": 2.0 ** 128 * (1.0 - 2.0 ** -16),
}

# numpy float 系 dtype（含 ml_dtypes / en_dtypes 自定义低精度浮点）。
_FLOAT_DTYPE_NAMES = frozenset(DEFAULT_THRESHOLDS.keys()) - frozenset(
    {"int8", "int16", "int32", "int64", "uint8", "uint16", "uint32", "uint64"}
)

# 常见别名 → 规范名（threshold 表键）。
_DTYPE_ALIASES = {
    "fp16": "float16",
    "bf16": "bfloat16",
    "fp32": "float32",
    "fp64": "float64",
    "f16": "float16",
    "f32": "float32",
    "s8": "int8",
    "int4": "int4",
}

_FLOAT32_FALLBACK = DEFAULT_THRESHOLDS["float32"]

# itemsize → 无符号整型 view（bit-exact 字节级比较用）。
_BIT_VIEW_UINT = {1: np.uint8, 2: np.uint16, 4: np.uint32, 8: np.uint64}


def _canonical_dtype(name: str) -> str:
    return _DTYPE_ALIASES.get(name.lower(), name.lower())


def _lookup(dtype_str: str, table: dict[str, float]) -> float:
    """按 dtype 查表，大小写不敏感，未知 dtype 回退 float32 项。"""
    lower = dtype_str.lower()
    if lower in table:
        return table[lower]
    return table.get("float32", _FLOAT32_FALLBACK)


def merge_thresholds(overrides: Optional[dict[str, float]] = None) -> dict[str, float]:
    """合并默认表 ⊕ 覆盖（overrides 优先）→ 传给 ``compare_tensor(thresholds=...)``。"""
    merged = dict(DEFAULT_THRESHOLDS)
    if overrides:
        merged.update(overrides)
    return merged


def threshold_for_dtype(dtype_str: str, thresholds: Optional[dict[str, float]] = None) -> float:
    """逐输出阈值：merged（含 overrides）优先 → DEFAULT_THRESHOLDS → float32 回退。"""
    lower = _canonical_dtype(dtype_str)
    if thresholds is not None and lower in thresholds:
        return thresholds[lower]
    return _lookup(lower, DEFAULT_THRESHOLDS)


def _small_value_threshold(dtype_str: str) -> float:
    return _lookup(dtype_str, SMALL_VALUE_THRESHOLDS)


def _small_value_error(dtype_str: str) -> float:
    return _lookup(dtype_str, SMALL_VALUE_ERROR_THRESHOLDS)


def _cancel_boundary(dtype_str: str) -> float:
    return _lookup(dtype_str, CANCEL_BOUNDARY_THRESHOLDS)


def _cancel_zero_threshold(dtype_str: str) -> float:
    return _lookup(dtype_str, CANCEL_ZERO_THRESHOLDS)


def _max_finite(dtype_name: str, dtype_obj: Any) -> float:
    """dtype 最大有限值：已知表 → np.finfo（内置浮点）→ 保守 inf。"""
    name = dtype_name.lower()
    if name in _MAX_FINITE_BY_NAME:
        return _MAX_FINITE_BY_NAME[name]
    try:
        return float(np.finfo(dtype_obj).max)
    except Exception:
        return float("inf")


def _as_numpy(x: Any) -> np.ndarray:
    """归一化输入为 numpy 数组（容忍 torch CPU tensor）。"""
    if hasattr(x, "cpu") and hasattr(x, "numpy"):
        x = x.detach().cpu().numpy()
    return np.asarray(x)


def _dtype_info(arr: np.ndarray) -> tuple[str, Any, str]:
    """返回 (canonical_name, dtype_obj, category)。category ∈ {'float','int','bool'}。"""
    dtype_obj = arr.dtype
    name = _canonical_dtype(str(np.dtype(dtype_obj).name))
    kind = np.dtype(dtype_obj).kind
    if kind in "iu":
        return name, dtype_obj, "int"
    if kind == "b":
        return name, dtype_obj, "bool"
    if kind == "f" or name in _FLOAT_DTYPE_NAMES:
        return name, dtype_obj, "float"
    raise ValueError(
        f"precision_check: 不支持的输出 dtype {dtype_obj}（kind={kind}）。"
        "浮点/整数/布尔之外的 dtype 无法按生态精度标准判定。"
    )


# ---------------------------------------------------------------------------
# 结果数据类
# ---------------------------------------------------------------------------

@dataclass
class PrecisionVerdict:
    """单个输出（单张量）的精度判定结果。"""
    passed: bool
    dtype: str
    threshold: float
    mere: float = 0.0
    mare: float = 0.0
    max_diff: float = 0.0
    mean_diff: float = 0.0
    mismatch_count: int = 0
    total_count: int = 0
    mismatch_ratio: float = 0.0
    small_value_passed: bool = True
    cancel_passed: bool = True
    normal_passed: bool = True
    error_msg: str = ""
    shape_mismatch: bool = False
    empty_output_suspect: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "dtype": self.dtype,
            "threshold": self.threshold,
            "mere": self.mere,
            "mare": self.mare,
            "max_diff": self.max_diff,
            "mean_diff": self.mean_diff,
            "mismatch_count": self.mismatch_count,
            "total_count": self.total_count,
            "mismatch_ratio": self.mismatch_ratio,
            "small_value_passed": self.small_value_passed,
            "cancel_passed": self.cancel_passed,
            "normal_passed": self.normal_passed,
            "error_msg": self.error_msg,
            "shape_mismatch": self.shape_mismatch,
            "empty_output_suspect": self.empty_output_suspect,
        }


def _fail(name: str, dtype: str, threshold: float, total: int, msg: str,
          shape_mismatch: bool = False, empty_suspect: bool = False,
          mismatch_count: int = 0, max_diff: float = 0.0,
          mean_diff: float = 0.0) -> PrecisionVerdict:
    return PrecisionVerdict(
        passed=False, dtype=dtype, threshold=threshold, total_count=total,
        mismatch_count=mismatch_count,
        mismatch_ratio=mismatch_count / total if total > 0 else 0.0,
        max_diff=max_diff, mean_diff=mean_diff,
        error_msg=msg, shape_mismatch=shape_mismatch, empty_output_suspect=empty_suspect,
    )


# ---------------------------------------------------------------------------
# 单输出比较
# ---------------------------------------------------------------------------

def compare_tensor(
    output: Union[np.ndarray, Any],
    golden: Union[np.ndarray, Any],
    dtype: Optional[str] = None,
    threshold: Optional[float] = None,
    thresholds: Optional[dict[str, float]] = None,
    native_ref: Optional[Union[np.ndarray, Any]] = None,
) -> PrecisionVerdict:
    """按生态精度标准比较单个输出张量与 golden。

    Args:
        output: 算子输出（numpy 数组；dtype 为输出声明 dtype，如 np.float16 /
            ml_dtypes bfloat16 / fp8 等低精度对象构造的数组）。
        golden: golden 参考输出（通常更高精度，如 np.float32/float64；
            内部先截断到 output dtype 再升 fp64 比较）。
        dtype: 输出 dtype 规范名（如 ``"float16"``）。缺省按 ``output.dtype``
            推断；bfloat16/fp8 等自定义 dtype 建议显式传入以保证查表正确。
        threshold: 显式阈值覆盖（如 0.0 强制 bit-exact）。优先级高于 thresholds 表。
        thresholds: 合并后的 dtype→threshold 表（``merge_thresholds`` 产出）。
        native_ref: 同精度参考输出（可选）；None 时用 golden 截断当参考（同
            cann-bench 无 native_output 行为）。

    Returns:
        PrecisionVerdict（passed/mere/mare/max_diff/mismatch_count/...）。
    """
    out = _as_numpy(output)
    gold = _as_numpy(golden)
    total = int(out.size)

    # ---- dtype 解析 ----
    # 显式 dtype 名只用于阈值/小值域等表查键（bfloat16/fp8 等建议显式传）；
    # category 与 golden 截断目标始终按 output 数组的真实 dtype 对象。
    if dtype is not None:
        dtype_name = _canonical_dtype(str(dtype))
    else:
        dtype_name, _, _ = _dtype_info(out)

    try:
        _, _, category = _dtype_info(out)
    except ValueError:
        category = "float"
    if threshold is None:
        threshold = threshold_for_dtype(dtype_name, thresholds)

    # ---- 形状不匹配 → 直接失败 ----
    if out.shape != gold.shape:
        empty_suspect = (out.size == 0 and gold.size > 0)
        hint = ("；output 为空而 golden 非空 → 疑似输出缓冲/长度传参缺陷"
                "（非 kernel 数值问题）" if empty_suspect else "")
        return _fail(dtype_name, dtype_name, threshold, total,
                     f"形状不匹配: output={out.shape}, golden={gold.shape}{hint}",
                     shape_mismatch=True, empty_suspect=empty_suspect)

    # ---- 布尔：精确匹配 ----
    if category == "bool":
        if np.array_equal(out, gold):
            return PrecisionVerdict(
                passed=True, dtype=dtype_name, threshold=threshold, total_count=total)
        return _fail(dtype_name, dtype_name, threshold, total,
                     f"布尔输出不匹配: {int((out != gold).sum())}/{total}")

    # ---- bit-exact 浮点（threshold==0）：字节级比较 ----
    if category == "float" and threshold == 0.0:
        int_dtype = _BIT_VIEW_UINT.get(int(np.dtype(out.dtype).itemsize))
        if int_dtype is not None:
            gold_cast = gold.astype(out.dtype)
            # golden cast 到更窄 output dtype 时新产生 inf（数据超 dtype）→ 告警。
            gold_f64 = gold.astype(np.float64)
            gold_cast_f64 = gold_cast.astype(np.float64)
            new_inf = np.isinf(gold_cast_f64) & ~np.isinf(gold_f64)
            if bool(new_inf.any()):
                _logger.warning(
                    "precision_check(bit-exact): golden cast 到 %s 产生 %d 处新 inf "
                    "（数据范围超 output dtype），bit-exact 失败可能源自溢出而非计算错误。",
                    out.dtype, int(new_inf.sum()),
                )
            out_bits = np.ascontiguousarray(out).view(int_dtype)
            gold_bits = np.ascontiguousarray(gold_cast).view(int_dtype)
            if np.array_equal(out_bits, gold_bits):
                return PrecisionVerdict(
                    passed=True, dtype=dtype_name, threshold=0.0, total_count=total)
            mismatch_count = int((out_bits != gold_bits).sum())
            return _fail(
                dtype_name, dtype_name, 0.0, total,
                f"bit-exact 比较失败: {mismatch_count}/{total} 个元素字节不等 "
                f"(含 ±0.0、NaN payload、Inf 符号等差异)",
                mismatch_count=mismatch_count,
            )
        # itemsize 不在映射表（理论不达）→ 落到 MERE/MARE。

    # ---- 整数：array_equal 精确匹配，不等则 abs-diff 容差 ----
    if category == "int":
        if np.array_equal(out, gold):
            return PrecisionVerdict(
                passed=True, dtype=dtype_name, threshold=threshold, total_count=total)
        diff = np.abs(out.astype(np.int64) - gold.astype(np.int64))
        mismatch_count = int((diff > max(threshold, 0)).sum())
        max_diff = float(diff.max()) if diff.size > 0 else 0.0
        mean_diff = float(diff.mean()) if diff.size > 0 else 0.0
        if mismatch_count == 0:
            return PrecisionVerdict(
                passed=True, dtype=dtype_name, threshold=threshold,
                max_diff=max_diff, mean_diff=mean_diff, total_count=total)
        return _fail(
            dtype_name, dtype_name, threshold, total,
            f"整数类型差值超出容差({threshold}): {mismatch_count}/{total} 个元素不匹配",
            mismatch_count=mismatch_count, max_diff=max_diff, mean_diff=mean_diff,
        )

    # ---- 浮点 MERE/MARE ----
    # golden 主动截断到 output.dtype，模拟算子输出的精度限制。
    target_dtype = out.dtype
    golden_truncated = gold.astype(target_dtype).astype(np.float64)
    output_fp64 = out.astype(np.float64)

    # NaN：位置不匹配 → fail。
    if bool(np.isnan(output_fp64).any()) or bool(np.isnan(golden_truncated).any()):
        nan_out = np.isnan(output_fp64)
        nan_gold = np.isnan(golden_truncated)
        if not bool((nan_out == nan_gold).all()):
            return _fail(dtype_name, dtype_name, threshold, total, "NaN位置不匹配")

    # Inf：单边 inf 饱和到 dtype 最大有限值续比；双边同号 inf 视为匹配并排除。
    inf_match_mask = np.zeros_like(output_fp64, dtype=bool)
    if bool(np.isinf(output_fp64).any()) or bool(np.isinf(golden_truncated).any()):
        inf_out = np.isinf(output_fp64)
        inf_gold = np.isinf(golden_truncated)
        inf_mismatch = inf_out != inf_gold
        if bool(inf_mismatch.any()):
            max_finite = _max_finite(dtype_name, target_dtype)
            if bool((inf_out & ~inf_gold).any()):
                mask = inf_out & ~inf_gold
                output_fp64 = output_fp64.copy()
                output_fp64[mask] = np.sign(output_fp64[mask]) * max_finite
            if bool((inf_gold & ~inf_out).any()):
                mask = inf_gold & ~inf_out
                golden_truncated = golden_truncated.copy()
                golden_truncated[mask] = np.sign(golden_truncated[mask]) * max_finite
        both_inf = inf_out & inf_gold
        if bool(both_inf.any()):
            out_sign = np.sign(output_fp64[both_inf])
            gold_sign = np.sign(golden_truncated[both_inf])
            # ±inf 的 sign() 为 ±1；同号判断按符号一致。
            if not bool((out_sign == gold_sign).all()):
                return _fail(dtype_name, dtype_name, threshold, total, "Inf符号不匹配")
            inf_match_mask[both_inf] = True

    # 相对误差：|actual - golden| / (|golden| + 1e-7)
    diff = np.abs(output_fp64 - golden_truncated)
    golden_abs = np.abs(golden_truncated)
    relative_error = diff / (golden_abs + 1e-7)

    valid_mask = ~(np.isnan(relative_error) | np.isinf(relative_error) | inf_match_mask)
    valid_re = relative_error[valid_mask]

    if valid_re.size == 0:
        has_nan = bool(np.isnan(out).any()) if total > 0 else False
        if has_nan:
            _logger.warning(
                "precision_check: 所有有效位置均为 NaN/Inf 且匹配（total=%d, dtype=%s）；"
                "两端同出 NaN 的极端情况可能掩盖独立数值 bug，请人工核查。",
                total, dtype_name,
            )
        return PrecisionVerdict(
            passed=True, dtype=dtype_name, threshold=threshold, total_count=total)

    overall_mere = float(valid_re.mean())
    overall_mare = float(valid_re.max())
    valid_diff = diff[valid_mask]
    max_diff = float(valid_diff.max()) if valid_diff.size > 0 else 0.0
    mean_diff = float(valid_diff.mean()) if valid_diff.size > 0 else 0.0

    # stage-1：整体相对误差达标 → 直接通过。
    mare_threshold = 10 * threshold
    if overall_mere < threshold and overall_mare < mare_threshold:
        return PrecisionVerdict(
            passed=True, dtype=dtype_name, threshold=threshold,
            mere=overall_mere, mare=overall_mare,
            max_diff=max_diff, mean_diff=mean_diff, total_count=total,
        )

    # stage-2：分析失败位置，小值域/相消/正常值域兜底判定。
    mismatch_mask = relative_error > mare_threshold
    mismatch_mask[~valid_mask] = False
    mismatch_count = int(mismatch_mask.sum())

    svt = _small_value_threshold(dtype_name)
    sv_error = _small_value_error(dtype_name)

    small_value_mask = golden_abs < svt
    small_value_mask[~valid_mask] = False
    small_value_total_count = int(small_value_mask.sum())
    small_value_error_count = int((small_value_mask & (diff > sv_error)).sum())

    # 同精度参考：native_ref 为 None 时用「原始 golden 重新截断」当参考。注意不能
    # 简写成 0——golden_truncated 可能已被单边 inf 饱和改写（inf→max_finite），而
    # 重新截断会保留 inf，|inf - max_finite| = inf → CPU 参考在 inf 位置"脏"，
    # 与小值域/相消/正常值域兜底判据 ratio<=2 联动（对齐 cann-bench compare.py）。
    if native_ref is not None:
        native_arr = _as_numpy(native_ref)
        if native_arr.shape != out.shape:
            return _fail(dtype_name, dtype_name, threshold, total,
                         f"同精度参考形状不匹配: native={native_arr.shape}, output={out.shape}")
        cpu_diff = np.abs(native_arr.astype(np.float64) - golden_truncated)
    else:
        cpu_diff = np.abs(gold.astype(target_dtype).astype(np.float64) - golden_truncated)
    small_value_cpu_error_count = int((small_value_mask & (cpu_diff > sv_error)).sum())

    # === 小值域兜底判定（ErrorCount_npu / max(ErrorCount_cpu, 1) <= 2）===
    if small_value_total_count > 0:
        small_value_passed = (small_value_error_count / max(small_value_cpu_error_count, 1)) <= 2
    else:
        small_value_passed = True

    # 相消位置：output≈0 且 golden 在 [small_value_threshold, cancel_boundary)。
    cancel_boundary = _cancel_boundary(dtype_name)
    cancel_zero_threshold = _cancel_zero_threshold(dtype_name)
    output_near_zero = np.abs(output_fp64) < cancel_zero_threshold
    golden_in_cancel_range = (golden_abs < cancel_boundary) & (golden_abs >= svt)
    cancel_mask = output_near_zero & golden_in_cancel_range & valid_mask
    cancel_total_count = int(cancel_mask.sum())
    cancel_error_count = int((cancel_mask & (relative_error > mare_threshold)).sum())
    cpu_relative_error = cpu_diff / (golden_abs + 1e-7)
    cancel_cpu_error_count = int((cancel_mask & (cpu_relative_error > mare_threshold)).sum())

    # === 相消兜底判定（对齐 cann-bench，ratio<=2）===
    if cancel_total_count > 0:
        cancel_passed = (cancel_error_count / max(cancel_cpu_error_count, 1)) <= 2
    else:
        cancel_passed = True

    # === 正常值域兜底判定（cann-bench issue #92 对齐）===
    # 仅当同精度参考自身在正常值域也超标时才 ratio<=2 放宽；参考干净（或缺失，
    # 缺 native 时 cpu_relative_error≡0）维持严格失败。
    normal_region_mask = ~small_value_mask & ~cancel_mask & valid_mask
    normal_total_count = int(normal_region_mask.sum())
    normal_error_count = int((mismatch_mask & ~small_value_mask & ~cancel_mask).sum())
    normal_cpu_error_count = int(
        (normal_region_mask & (cpu_relative_error > mare_threshold)).sum())
    if normal_error_count == 0:
        normal_passed = True
    elif normal_cpu_error_count == 0:
        normal_passed = False
    else:
        normal_passed = (normal_error_count / normal_cpu_error_count) <= 2

    passed = normal_passed and small_value_passed and cancel_passed

    # 显示用 MERE/MARE（对齐 cann-bench 显示逻辑）
    normal_re = relative_error[normal_region_mask]
    if not normal_passed:
        if normal_re.size > 0:
            display_mere = float(normal_re.mean())
            display_mare = float(normal_re.max())
        else:
            display_mere = overall_mere
            display_mare = overall_mare
    elif passed:
        if normal_re.size > 0:
            display_mere = float(normal_re.mean())
            display_mare = float(normal_re.max())
        else:
            display_mere = 0.0
            display_mare = 0.0
    else:
        display_mere = overall_mere
        display_mare = overall_mare

    return PrecisionVerdict(
        passed=passed, dtype=dtype_name, threshold=threshold,
        mere=display_mere, mare=display_mare,
        max_diff=max_diff, mean_diff=mean_diff,
        mismatch_count=mismatch_count, total_count=total,
        mismatch_ratio=mismatch_count / total if total > 0 else 0.0,
        small_value_passed=small_value_passed,
        cancel_passed=cancel_passed,
        normal_passed=normal_passed,
        error_msg="" if passed else "浮点相对误差未通过（MERE/MARE + 小值域/相消/正常值域同精度兜底判定）",
    )


# ---------------------------------------------------------------------------
# 多输出比较
# ---------------------------------------------------------------------------

def compare_outputs(
    output: Union[np.ndarray, list, tuple],
    golden: Union[np.ndarray, list, tuple],
    thresholds: Optional[dict[str, float]] = None,
    native_refs: Optional[Union[np.ndarray, list, tuple]] = None,
) -> tuple[bool, list[PrecisionVerdict]]:
    """逐个输出按 ``compare_tensor`` 判定，passed = 全输出 AND。

    返回 ``(passed, verdicts)``。单输出时可直接用 ``compare_tensor``。
    """
    out_list = [output] if isinstance(output, np.ndarray) else list(output)
    gold_list = [golden] if isinstance(golden, np.ndarray) else list(golden)
    native_list = None
    if native_refs is not None:
        native_list = [native_refs] if isinstance(native_refs, np.ndarray) else list(native_refs)

    if len(out_list) != len(gold_list):
        return False, [PrecisionVerdict(
            passed=False, dtype="", threshold=0.0,
            error_msg=f"输出数量不匹配: output={len(out_list)}, golden={len(gold_list)}")]

    verdicts: list[PrecisionVerdict] = []
    for i, (o, g) in enumerate(zip(out_list, gold_list)):
        nat = native_list[i] if native_list is not None else None
        verdicts.append(compare_tensor(o, g, thresholds=thresholds, native_ref=nat))
    return all(v.passed for v in verdicts), verdicts
