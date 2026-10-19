"""Precision comparison aligned with cann-bench semantics (P69).

devkit 自实现 cann-bench 所用的**标准精度方法**（MERE/MARE、bit-exact、exact-int
都是通用指标，非 cann-bench 专有）；阈值作**数据**（dict literal，值对齐 cann-bench
per-dtype 语义，经 spec 管线传递）。零 import cann-bench（§1.7 自闭环）——语义对齐由
parity UT（tests/ut/adapters/test_precision_compare.py::TestParityCannBench）守护。

设计依据（cann-bench 行为，本模块逐分支复刻，行号仅供 parity 对照）：
- 逐输出按运行时 dtype 查阈值；passed = 全输出 AND。
- 阈值合并：merged = dict(DEFAULT_THRESHOLDS) ⊕ proto 覆盖（proto 优先）。
- dtype→方法派生：bit-exact(thr==0 浮点) / 整数(torch.equal+abs-diff) /
  浮点(MERE/MARE stage1 + 小值域/相消 stage2 + NaN-Inf 饱和)。
- 三值域兜底**完全对齐 cann-bench**：小值域/相消恒 ratio≤2（ErrorCount_npu /
  max(ErrorCount_cpu,1) ≤ 2）；正常值域补 #92 同精度兜底（native 自身脏时 ≤2×，
  否则严格）。2026-08-01 的"无 CPU 参考零容忍"有意偏离已反转（见 docs/plan
  对齐记录）——parity 对拍覆盖全部场景。
- native_ref=None → golden 截断到目标精度当同精度参考（cpu_diff=0），与
  cann-bench compare_tensors 无 native_output 行为一致。

纯 torch（CPU）实现——张量先 .cpu()，可在 harness subprocess 跑。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import torch

from ascendc_devkit.domain.precision import (
    DEFAULT_THRESHOLDS,
    threshold_for_dtype,
    _cancel_boundary,
    _cancel_zero_threshold,
    _small_value_error,
    _small_value_threshold,
)

_logger = logging.getLogger(__name__)


# 阈值核心（上表）已上移 domain/precision.py（step-104 主进程纯度：本模块顶层
# import torch，而编排主进程的 harness 生成/默认 rule 解析只需要阈值数据）。


# 整数 dtype 走 exact + abs-diff 路径，而非浮点 MERE/MARE。
_INTEGER_DTYPES = (
    torch.int8, torch.int16, torch.int32, torch.int64,
    torch.uint8, torch.uint16, torch.uint32, torch.uint64,
)

# bit-exact（thr==0 浮点）字节级 view 映射。
_BIT_VIEW = {
    torch.float16: torch.int16,
    torch.bfloat16: torch.int16,
    torch.float32: torch.int32,
    torch.float64: torch.int64,
}


# ---------------------------------------------------------------------------
# 结果数据类
# ---------------------------------------------------------------------------

@dataclass
class OutputVerdict:
    """单个输出的精度判定。"""
    index: int
    dtype: str
    threshold: float
    passed: bool
    mere: float = 0.0
    mare: float = 0.0
    max_diff: float = 0.0
    mean_diff: float = 0.0
    mismatch_count: int = 0
    total_count: int = 0
    mismatch_ratio: float = 0.0
    small_value_passed: bool = True
    cancel_passed: bool = True
    # 正常值域同精度兜底判定（cann-bench issue #92 对齐）：当同精度参考(native)
    # 自身在正常值域也超标时，允许候选不差于 2× 参考；否则严格失败。与 cann-bench
    # CompareResult.normal_* 字段对称。
    normal_error_count: int = 0
    normal_cpu_error_count: int = 0
    normal_total_count: int = 0
    normal_passed: bool = True
    error_msg: str = ""
    # F4 结构化信号：输出 shape 与 golden 不一致时置位，供 scope_guard/diagnose
    # 把「输出定型缺陷」（plugin/harness/codegen 层）与「kernel 数值问题」区分，
    # 避免把 shape 缺陷当精度问题烧 precision_debug 预算（unique 20260808 P4
    # y=Size([0]) vs golden Size([19058]) 实证）。
    shape_mismatch: bool = False
    empty_output_suspect: bool = False  # output 空而 golden 非空 → 高度疑似定型缺陷

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "dtype": self.dtype,
            "threshold": self.threshold,
            "passed": self.passed,
            "mere": self.mere,
            "mare": self.mare,
            "max_diff": self.max_diff,
            "mean_diff": self.mean_diff,
            "mismatch_count": self.mismatch_count,
            "total_count": self.total_count,
            "mismatch_ratio": self.mismatch_ratio,
            "small_value_passed": self.small_value_passed,
            "cancel_passed": self.cancel_passed,
            "normal_error_count": self.normal_error_count,
            "normal_cpu_error_count": self.normal_cpu_error_count,
            "normal_total_count": self.normal_total_count,
            "normal_passed": self.normal_passed,
            "error_msg": self.error_msg,
            "shape_mismatch": self.shape_mismatch,
            "empty_output_suspect": self.empty_output_suspect,
        }


@dataclass
class PrecisionVerdict:
    """多输出聚合判定。"""
    passed: bool
    mere: float = 0.0
    mare: float = 0.0
    max_diff: float = 0.0
    mean_diff: float = 0.0
    mismatch_count: int = 0
    total_count: int = 0
    threshold: float = 0.0
    dtype: str = ""
    error_msg: str = ""
    output_verdicts: list[OutputVerdict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 标准化（tensor / list / tuple / None → tensor 列表，保留 None 占位维持索引对齐）
# ---------------------------------------------------------------------------

def _normalize_tensors(x: Any) -> list[Any]:
    if isinstance(x, torch.Tensor):
        return [x]
    if isinstance(x, (tuple, list)):
        result: list[Any] = []
        for item in x:
            if isinstance(item, torch.Tensor):
                result.append(item)
            elif isinstance(item, (tuple, list)):
                for sub in item:
                    if isinstance(sub, torch.Tensor):
                        result.append(sub)
                    else:
                        result.append(None)
            else:
                result.append(None)
        return result
    return []


# ---------------------------------------------------------------------------
# 单输出比较
# ---------------------------------------------------------------------------

def _compare_single(
    output: torch.Tensor,
    golden: torch.Tensor,
    threshold: float,
    dtype: str,
    native_ref: Optional[torch.Tensor] = None,
) -> OutputVerdict:
    """按 dtype 派生方法比较单个输出 tensor（复刻 cann-bench _compare_single_tensor）。"""
    # 归一到 CPU：golden 跑在 CPU、算子在 NPU，统一到 CPU 做 subtract/equal。
    if output.is_cuda or output.device.type == "npu":
        output = output.cpu()
    if golden.is_cuda or golden.device.type == "npu":
        golden = golden.cpu()

    total = output.numel()

    # 形状不匹配 → 直接失败。F4：给结构化信号（shape_mismatch / empty_output_suspect），
    # 让 scope_guard/diagnose 能区分「输出定型缺陷」（plugin/harness/codegen 层，如
    # workspace readback 读错导致 y 恒空）与「kernel 数值问题」——空输出 vs 非空 golden
    # 是定型缺陷的高度疑似特征（unique 20260808 P4 实证 y=Size([0]) vs golden Size([19058])）。
    if output.shape != golden.shape:
        empty_suspect = (output.numel() == 0 and golden.numel() > 0)
        hint = ("；output 为空而 golden 非空 → 疑似输出定型缺陷（plugin/harness 未正确"
                "回读有效长度，归 codegen/harness 层，非 kernel 数值问题）" if empty_suspect else "")
        return OutputVerdict(
            index=-1, dtype=dtype, threshold=threshold, passed=False,
            total_count=total,
            error_msg=(
                f"形状不匹配: output={output.shape}, golden={golden.shape}{hint}"),
            shape_mismatch=True,
            empty_output_suspect=empty_suspect,
        )

    # ---- bit-exact 浮点（threshold==0 且浮点）：.view(int) 字节级比较 ----
    # 区分 ±0.0 / NaN payload / Inf 符号——IEEE754 相等性会把 +0.0/-0.0 当同值放过。
    if threshold == 0 and output.is_floating_point():
        int_dtype = _BIT_VIEW.get(output.dtype)
        if int_dtype is not None:
            golden_cast = golden.to(output.dtype).contiguous()
            # golden cast 到更窄 output.dtype 时新产生 inf（如 fp64→fp16 溢出），
            # bit-exact 失败可能源自数据范围超 dtype 而非计算错误——告警避免误判方向。
            new_inf = torch.isinf(golden_cast) & ~torch.isinf(golden)
            if new_inf.any().item():
                _logger.warning(
                    "precision_compare(bit-exact): golden cast 到 %s 产生 %d 处新 inf "
                    "（数据范围超 output dtype），bit-exact 失败可能源自溢出而非计算错误。",
                    output.dtype, int(new_inf.sum().item()),
                )
            out_bits = output.contiguous().view(int_dtype)
            gold_bits = golden_cast.view(int_dtype)
            if torch.equal(out_bits, gold_bits):
                return OutputVerdict(
                    index=-1, dtype=dtype, threshold=threshold, passed=True,
                    total_count=total,
                )
            mismatch_count = int((out_bits != gold_bits).sum())
            return OutputVerdict(
                index=-1, dtype=dtype, threshold=threshold, passed=False,
                mismatch_count=mismatch_count, total_count=total,
                mismatch_ratio=mismatch_count / total if total > 0 else 0.0,
                error_msg=(
                    f"bit-exact 比较失败: {mismatch_count}/{total} 个元素字节不等 "
                    f"(含 ±0.0、NaN payload、Inf 符号等差异)"
                ),
            )
        # 不支持 view 的浮点（如 fp8）继续走 MERE/MARE。

    # ---- 整数：torch.equal 精确匹配，不等则 abs-diff 容差 ----
    if output.dtype in _INTEGER_DTYPES:
        if torch.equal(output, golden):
            return OutputVerdict(
                index=-1, dtype=dtype, threshold=threshold, passed=True,
                total_count=total,
            )
        diff = torch.abs(output.long() - golden.long())
        mismatch_count = int((diff > max(threshold, 0)).sum())
        max_diff = float(diff.max()) if diff.numel() > 0 else 0.0
        mean_diff = float(diff.float().mean()) if diff.numel() > 0 else 0.0
        if mismatch_count == 0:
            return OutputVerdict(
                index=-1, dtype=dtype, threshold=threshold, passed=True,
                max_diff=max_diff, mean_diff=mean_diff, total_count=total,
            )
        return OutputVerdict(
            index=-1, dtype=dtype, threshold=threshold, passed=False,
            max_diff=max_diff, mean_diff=mean_diff,
            mismatch_count=mismatch_count, total_count=total,
            mismatch_ratio=mismatch_count / total if total > 0 else 0.0,
            error_msg=(
                f"整数类型差值超出容差({threshold}): {mismatch_count}/{total} 个元素不匹配"
            ),
        )

    # ---- 浮点 MERE/MARE ----
    # golden 主动截断到 output.dtype 模拟算子输出精度限制。
    target_dtype = output.dtype
    golden_truncated = golden.to(target_dtype).double()
    output_fp64 = output.double()

    # NaN：位置不匹配 → fail。
    if torch.any(torch.isnan(output_fp64)) or torch.any(torch.isnan(golden_truncated)):
        nan_out = torch.isnan(output_fp64)
        nan_gold = torch.isnan(golden_truncated)
        if not torch.all(nan_out == nan_gold):
            return OutputVerdict(
                index=-1, dtype=dtype, threshold=threshold, passed=False,
                total_count=total, error_msg="NaN位置不匹配",
            )

    # Inf：单边 inf 饱和到 dtype 最大有限值续比；双边同号 inf 视为匹配并排除。
    inf_match_mask = torch.zeros_like(output_fp64, dtype=torch.bool)
    if torch.any(torch.isinf(output_fp64)) or torch.any(torch.isinf(golden_truncated)):
        inf_out = torch.isinf(output_fp64)
        inf_gold = torch.isinf(golden_truncated)
        inf_mismatch = inf_out != inf_gold
        if torch.any(inf_mismatch):
            max_finite = float(torch.finfo(target_dtype).max)
            if torch.any(inf_out & ~inf_gold):
                mask = inf_out & ~inf_gold
                output_fp64[mask] = torch.sign(output_fp64[mask]) * max_finite
            if torch.any(inf_gold & ~inf_out):
                mask = inf_gold & ~inf_out
                golden_truncated[mask] = torch.sign(golden_truncated[mask]) * max_finite
        both_inf = inf_out & inf_gold
        if torch.any(both_inf):
            if not torch.all(
                torch.sign(output_fp64[both_inf]) == torch.sign(golden_truncated[both_inf])
            ):
                return OutputVerdict(
                    index=-1, dtype=dtype, threshold=threshold, passed=False,
                    total_count=total, error_msg="Inf符号不匹配",
                )
            inf_match_mask[both_inf] = True

    # 相对误差：|actual - golden| / (|golden| + 1e-7)
    diff = torch.abs(output_fp64 - golden_truncated)
    golden_abs = torch.abs(golden_truncated)
    relative_error = diff / (golden_abs + 1e-7)

    valid_mask = ~(torch.isnan(relative_error) | torch.isinf(relative_error) | inf_match_mask)
    valid_re = relative_error[valid_mask]

    if len(valid_re) == 0:
        # 全部位置为 NaN/Inf 且匹配 → 视为通过（维持兼容；warn 提示可能掩盖独立 bug）。
        has_nan = bool(torch.isnan(output).any().item()) if total > 0 else False
        if has_nan:
            _logger.warning(
                "precision_compare: 所有有效位置均为 NaN/Inf 且匹配（total=%d, dtype=%s）；"
                "两端同出 NaN 的极端情况可能掩盖独立数值 bug，请人工核查。",
                total, dtype,
            )
        return OutputVerdict(
            index=-1, dtype=dtype, threshold=threshold, passed=True,
            total_count=total,
        )

    overall_mere = float(valid_re.mean())
    overall_mare = float(valid_re.max())
    valid_diff = diff[valid_mask]
    max_diff = float(valid_diff.max()) if len(valid_diff) > 0 else 0.0
    mean_diff = float(valid_diff.mean()) if len(valid_diff) > 0 else 0.0

    # stage1：整体相对误差达标 → 直接通过。
    mare_threshold = 10 * threshold
    if overall_mere < threshold and overall_mare < mare_threshold:
        return OutputVerdict(
            index=-1, dtype=dtype, threshold=threshold, passed=True,
            mere=overall_mere, mare=overall_mare,
            max_diff=max_diff, mean_diff=mean_diff, total_count=total,
        )

    # stage2：分析失败位置，小值域/相消兜底判定。
    mismatch_mask = relative_error > mare_threshold
    mismatch_mask[~valid_mask] = False
    mismatch_count = int(mismatch_mask.sum())

    small_value_threshold = _small_value_threshold(dtype)
    small_value_error = _small_value_error(dtype)

    small_value_mask = golden_abs < small_value_threshold
    small_value_mask[~valid_mask] = False
    small_value_total_count = int(small_value_mask.sum())
    small_value_error_count = int((small_value_mask & (diff > small_value_error)).sum())

    # 同精度参考：native_ref 为 None 时用 golden 截断当参考（cpu_diff=0）。
    if native_ref is not None:
        if native_ref.device.type != "cpu":
            native_ref = native_ref.cpu()
        cpu_diff = torch.abs(native_ref.double() - golden_truncated)
    else:
        cpu_diff = torch.abs(golden.to(target_dtype).double() - golden_truncated)
    small_value_cpu_error_count = int((small_value_mask & (cpu_diff > small_value_error)).sum())

    # === 小值域兜底判定（对齐 cann-bench compare_tensors，恒 ratio≤2）===
    # ErrorCount_npu / max(ErrorCount_cpu, 1) ≤ 2。CPU 参考缺失时 cpu_diff≡0 →
    # cpu_error_count=0 → 分母为 1，即容忍 ≤2 个小值域误差（与 cann-bench 一致，
    # 不再刻意收严——2026-08-01 的零容忍决策已反转，见 docs/plan 对齐记录）。
    if small_value_total_count > 0:
        small_value_passed = (small_value_error_count / max(small_value_cpu_error_count, 1)) <= 2
    else:
        small_value_passed = True

    # 相消位置：output≈0 且 golden 在 [small_value_threshold, cancel_boundary)。
    cancel_boundary = _cancel_boundary(dtype)
    cancel_zero_threshold = _cancel_zero_threshold(dtype)
    output_near_zero = torch.abs(output_fp64) < cancel_zero_threshold
    golden_in_cancel_range = (golden_abs < cancel_boundary) & (golden_abs >= small_value_threshold)
    cancel_mask = output_near_zero & golden_in_cancel_range & valid_mask
    cancel_total_count = int(cancel_mask.sum())
    cancel_error_count = int((cancel_mask & (relative_error > mare_threshold)).sum())
    cpu_relative_error = cpu_diff / (golden_abs + 1e-7)
    cancel_cpu_error_count = int((cancel_mask & (cpu_relative_error > mare_threshold)).sum())
    # === 相消兜底判定（对齐 cann-bench，恒 ratio≤2）===
    if cancel_total_count > 0:
        cancel_passed = (cancel_error_count / max(cancel_cpu_error_count, 1)) <= 2
    else:
        cancel_passed = True

    # === 正常值域兜底判定（cann-bench issue #92 对齐）===
    # 与小值域/相消一致：仅当同精度参考(native)自身在正常值域也超标时（深归约/
    # 病态 fp32，如 conv K=9216 固有舍入）才用 ratio≤2 放宽；参考干净（或缺失，
    # 缺 native 时 cpu_relative_error≡0）则维持严格失败。与 cann-bench compare.py
    # normal_passed 语义逐分支一致。
    normal_region_mask = ~small_value_mask & ~cancel_mask & valid_mask
    normal_total_count = int(normal_region_mask.sum())
    normal_mismatch_count = int((mismatch_mask & ~small_value_mask & ~cancel_mask).sum())
    normal_error_count = normal_mismatch_count  # NPU 在正常值域的超标点数
    normal_cpu_error_count = int(
        (normal_region_mask & (cpu_relative_error > mare_threshold)).sum())
    if normal_error_count == 0:
        normal_passed = True
    elif normal_cpu_error_count == 0:
        normal_passed = False
    else:
        normal_passed = (normal_error_count / normal_cpu_error_count) <= 2

    # 最终判定：三个值域各自兜底判定，全部通过才算通过。
    passed = normal_passed and small_value_passed and cancel_passed

    # 显示用 MERE/MARE（对齐 cann-bench compare.py 显示逻辑）
    normal_relative_error = relative_error[normal_region_mask]
    if not normal_passed:
        # 正常值域导致失败：显示排除小值域/相消后的 MERE/MARE
        if len(normal_relative_error) > 0:
            display_mere = float(normal_relative_error.mean())
            display_mare = float(normal_relative_error.max())
        else:
            display_mere = overall_mere
            display_mare = overall_mare
    elif passed:
        # 全部通过：显示排除小值域/相消后的 MERE/MARE，
        # 避免 overall 值被小值域的巨大相对误差拉高，造成"MARE 大却通过"的误解。
        if len(normal_relative_error) > 0:
            display_mere = float(normal_relative_error.mean())
            display_mare = float(normal_relative_error.max())
        else:
            display_mere = 0.0
            display_mare = 0.0
    else:
        # 正常值域通过、但小值域/相消兜底失败：显示 overall MERE/MARE，
        # 让用户看到实际误差大小（失败源于小值域/相消而非正常值域）。
        display_mere = overall_mere
        display_mare = overall_mare

    return OutputVerdict(
        index=-1, dtype=dtype, threshold=threshold, passed=passed,
        mere=display_mere, mare=display_mare,
        max_diff=max_diff, mean_diff=mean_diff,
        mismatch_count=mismatch_count, total_count=total,
        mismatch_ratio=mismatch_count / total if total > 0 else 0.0,
        small_value_passed=small_value_passed, cancel_passed=cancel_passed,
        normal_error_count=normal_error_count,
        normal_cpu_error_count=normal_cpu_error_count,
        normal_total_count=normal_total_count,
        normal_passed=normal_passed,
        error_msg="" if passed else "浮点相对误差未通过（含小值域/相消/正常值域同精度兜底判定）",
    )


# ---------------------------------------------------------------------------
# index_gather（TopK idx 输出：tie 顺序无关的"指向值"校验）
# ---------------------------------------------------------------------------

def validate_index_gather_outputs(
    output_index: int,
    spec: dict[str, Any],
    inputs: list[Any],
    outputs: list[Any],
    case_attrs: dict[str, Any],
) -> tuple[bool, str]:
    """校验声明了 ``index_gather`` 的输出：``x.gather(dim, idx) == values``。

    tie 顺序无关：只要索引指向的元素值正确即通过（TopK 并列元素顺序非确定）。
    语义移植自 cann-bench ``kernel_eval/eval/index_check.py``（issue #40），
    消息串对齐，诊断可互认；防"返回正确数值却乱填索引也能过"缺口。

    Args:
        output_index: 本输出在 outputs 中的索引。
        spec: ``{"input_idx": int, "dim_attr": str, "value_output_idx": int}``
            （名字已在 runner 渲染 harness 时解析为索引）。
        inputs: proto 顺序的输入张量（可含 None 占位）。
        outputs: 归一化的算子输出（torch 张量列表）。
        case_attrs: 本用例的 attrs（含 dim 等）。

    Returns:
        ``(ok, msg)``——ok=False 时 msg 为失败原因（不含则空串）。
    """
    input_idx = int(spec.get("input_idx", -1))
    dim_attr = str(spec.get("dim_attr", "dim"))
    value_output_idx = int(spec.get("value_output_idx", -1))

    if not (0 <= input_idx < len(inputs)) or not isinstance(inputs[input_idx], torch.Tensor):
        return False, f"index_gather[{output_index}]: 找不到源输入张量（input_idx={input_idx} 为 None 或越界）"
    x = inputs[input_idx]

    if not (0 <= value_output_idx < len(outputs)) or not isinstance(outputs[value_output_idx], torch.Tensor):
        return False, f"index_gather[{output_index}]: 缺少配对值输出（value_output_idx={value_output_idx}）"
    values = outputs[value_output_idx]

    idx = outputs[output_index]
    if not isinstance(idx, torch.Tensor):
        return False, f"index_gather[{output_index}]: 缺少索引输出（为 None）"

    # dim 是索引校验的必要信息：缺失不静默兜底（会在错误维度上 gather、给出错误
    # 的通过/失败），直接判失败暴露配置问题（对齐 batch index_check 语义）。
    if dim_attr not in case_attrs:
        return False, (f"index_gather[{output_index}]: 缺少维度属性 {dim_attr!r}"
                       f"（index_gather 声明的 dim_attr 未在 case attrs 中找到）")
    dim = int(case_attrs[dim_attr])

    x_c = x.detach().cpu()
    idx_c = idx.detach().cpu().to(torch.int64)
    val_c = values.detach().cpu()

    if idx_c.dim() != x_c.dim():
        return False, (f"index_gather: 索引维度 {idx_c.dim()} 与输入维度 {x_c.dim()} 不一致，"
                       f"无法 gather")
    dim_n = dim if dim >= 0 else x_c.dim() + dim
    if not (0 <= dim_n < x_c.dim()):
        return False, f"index_gather: dim={dim} 越界（输入 {x_c.dim()} 维）"

    if idx_c.shape != val_c.shape:
        return False, (f"index_gather: 索引输出形状 {tuple(idx_c.shape)} 与值输出形状 "
                       f"{tuple(val_c.shape)} 不一致")

    # gather 要求除 dim 外各维 idx.size(d) <= x.size(d)
    for d in range(x_c.dim()):
        if d != dim_n and idx_c.size(d) > x_c.size(d):
            return False, (f"index_gather: 第 {d} 维索引尺寸 {idx_c.size(d)} 超过输入 "
                           f"{x_c.size(d)}")

    dim_size = x_c.size(dim_n)
    if idx_c.numel() > 0:
        lo = int(idx_c.min().item())
        hi = int(idx_c.max().item())
        if lo < 0 or hi >= dim_size:
            return False, f"index_gather: 索引越界 [{lo},{hi}]，合法区间 [0,{dim_size})"

    gathered = torch.gather(x_c, dim_n, idx_c).to(val_c.dtype)
    # 不能直接用 torch.equal——它对 NaN 返回不等（NaN != NaN），会把
    # value_range=[nan,nan] 这类全 NaN 用例（如 top_k case 15）即便索引完全正确
    # 也误判失败。故按位置做 NaN-aware 比较：两侧同为 NaN 视为相等。
    if gathered.is_floating_point() or val_c.is_floating_point():
        both_nan = torch.isnan(gathered) & torch.isnan(val_c)
        eq = (gathered == val_c) | both_nan
    else:
        eq = gathered == val_c
    if not bool(eq.all()):
        mism = int((~eq).sum().item())
        return False, (f"index_gather: 候选索引指向的元素与其值输出不一致（{mism} 处不符），"
                       f"索引无效")
    return True, ""


# ---------------------------------------------------------------------------
# 多输出主入口
# ---------------------------------------------------------------------------

def compare_outputs(
    output: Any,
    golden: Any,
    merged_thresholds: dict[str, float],
    ignore_indices: Optional[list[int]] = None,
    native_refs: Optional[Any] = None,
    inputs: Optional[list[Any]] = None,
    index_gather_specs: Optional[dict[int, dict[str, Any]]] = None,
    case_attrs: Optional[dict[str, Any]] = None,
) -> PrecisionVerdict:
    """逐输出按运行时 dtype 比较，passed = 全输出 AND。

    Args:
        output: 算子输出（单 tensor 或 tensor 列表/元组，可含 None 占位）。
        golden: golden 参考输出（同结构），通常 FP64。
        merged_thresholds: 合并后的 dtype→threshold（``dict(DEFAULT_THRESHOLDS) ⊕
            proto 覆盖``）；逐输出按运行时 ``str(t.dtype)`` 查表。
        ignore_indices: 跳过比较的输出索引（对应 proto output ``compare: false``），
            被跳过的输出视为通过、不计入聚合。
        native_refs: 同精度参考输出（可选）；None 时用 golden 截断当参考（cpu_diff=0）。
        inputs: proto 顺序的输入张量（可含 None 占位）；index_gather 校验用。
        index_gather_specs: ``{输出索引: {"input_idx", "dim_attr",
            "value_output_idx"}}``——声明了 index_gather 的输出跳过逐元素比较
            （spec 隐含 ignore 语义，与 batch evaluator 一致），改为
            ``x.gather(dim, idx) == values`` 自洽校验；校验失败该输出 passed=False。
        case_attrs: 本用例的 attrs（含 dim 等）；index_gather 校验用。

    Returns:
        PrecisionVerdict（含逐输出 output_verdicts）。
    """
    outputs = _normalize_tensors(output)
    goldens = _normalize_tensors(golden)
    natives = _normalize_tensors(native_refs) if native_refs is not None else None

    if len(outputs) != len(goldens):
        return PrecisionVerdict(
            passed=False,
            error_msg=f"输出数量不匹配: output={len(outputs)}, golden={len(goldens)}",
        )

    # F5（review 整改）：native_refs 数量与 golden 不匹配 → 显式失败，不 IndexError/
    # 静默忽略——对齐 cann-bench compare_tensors 的「同精度输出数量不匹配」守卫
    # （compare.py 对应分支返回 passed=False + 明确 error_msg）。
    if natives is not None and len(natives) != len(goldens):
        return PrecisionVerdict(
            passed=False,
            error_msg=(
                f"同精度输出数量不匹配: native_refs={len(natives)}, "
                f"golden={len(goldens)}"),
        )

    all_passed = True
    mere_sum = 0.0
    mare_max = 0.0
    max_diff = 0.0
    mean_diff_sum = 0.0
    mismatch_count = 0
    total_count = 0
    output_verdicts: list[OutputVerdict] = []

    for i, (out_t, gold_t) in enumerate(zip(outputs, goldens)):
        # None 处理：双边 None → 跳过（通过）；单边 None → 失败。
        if out_t is None or gold_t is None:
            both_none = out_t is None and gold_t is None
            output_verdicts.append(OutputVerdict(
                index=i, dtype="none", threshold=0.0, passed=both_none,
                error_msg="" if both_none else f"output[{i}] 单边为 None",
            ))
            if not both_none:
                all_passed = False
            continue

        # index_gather 输出（TopK idx）：跳过逐元素比较，改跑"指向值"自洽校验。
        # 优先级高于 ignore_indices：spec 存在即校验，校验失败不能靠 ignore 蒙混。
        gather_spec = (index_gather_specs or {}).get(i)
        if gather_spec:
            _ok, _msg = validate_index_gather_outputs(
                i, gather_spec, inputs or [], outputs, case_attrs or {})
            _dt = str(out_t.dtype).replace("torch.", "")
            output_verdicts.append(OutputVerdict(
                index=i, dtype=_dt,
                threshold=threshold_for_dtype(_dt, merged_thresholds),
                passed=_ok, error_msg="" if _ok else _msg,
            ))
            if not _ok:
                all_passed = False
            continue

        # 跳过指定输出（compare: false）。
        if ignore_indices and i in ignore_indices:
            out_dtype_str = str(out_t.dtype).replace("torch.", "")
            output_verdicts.append(OutputVerdict(
                index=i, dtype=out_dtype_str,
                threshold=threshold_for_dtype(out_dtype_str, merged_thresholds),
                passed=True, error_msg="(跳过对比)",
            ))
            continue

        out_dtype_str = str(out_t.dtype).replace("torch.", "")
        out_threshold = threshold_for_dtype(out_dtype_str, merged_thresholds)
        native_t = natives[i] if natives is not None else None

        verdict = _compare_single(out_t, gold_t, out_threshold, out_dtype_str, native_t)
        verdict.index = i
        output_verdicts.append(verdict)

        all_passed = all_passed and verdict.passed
        mere_sum += verdict.mere * verdict.total_count
        mare_max = max(mare_max, verdict.mare)
        max_diff = max(max_diff, verdict.max_diff)
        mean_diff_sum += verdict.mean_diff * verdict.total_count
        mismatch_count += verdict.mismatch_count
        total_count += verdict.total_count

    mere = mere_sum / total_count if total_count > 0 else 0.0
    mean_diff = mean_diff_sum / total_count if total_count > 0 else 0.0

    # 聚合 threshold/dtype 取第一个失败输出（无失败则首个输出）用于诊断展示。
    result_dtype = ""
    result_threshold = 0.0
    for v in output_verdicts:
        if not v.passed and v.error_msg != "(跳过对比)":
            result_dtype = v.dtype
            result_threshold = v.threshold
            break
    if result_dtype == "" and output_verdicts:
        result_dtype = output_verdicts[0].dtype
        result_threshold = output_verdicts[0].threshold

    return PrecisionVerdict(
        passed=all_passed,
        mere=mere, mare=mare_max,
        max_diff=max_diff, mean_diff=mean_diff,
        mismatch_count=mismatch_count, total_count=total_count,
        threshold=result_threshold, dtype=result_dtype,
        output_verdicts=output_verdicts,
    )
