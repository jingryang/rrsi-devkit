"""L4 Domain — Precision comparison policy (P79).

``CompareRule`` 是精度判定的**策略数据**（「比什么、用什么阈值」），与
``PrecisionComparer``（「谁来算」，adapters 层协议）正交：

- 维度 A（阈值）：proto ``precision_thresholds`` 经 ``OperatorSpec`` → 合并默认表
  → ``CompareRule.dtype_thresholds``，作单一真相源贯穿到 runner harness。
- 维度 B（方法）：backend 由 adapters 的 ``PrecisionComparer`` 协议实现
  （``DevkitComparer`` 默认 §1.7 自包含 / ``CannbenchComparer`` 可选注入），
  本模块只持有协议消费的**数据**。

rule 用对象（非散参数）承载，预留 L3 比较模式扩展（双标杆/区间只加字段，
adapters 的 ``PrecisionComparer`` 签名不动）——形状预留，不实现（§2.7 YAGNI）。

step-104 起阈值核心（``DEFAULT_THRESHOLDS`` / ``merge_thresholds`` /
``threshold_for_dtype`` 及小值域/相消表）从 ``adapters/npu/precision_compare.py``
上移至此：比较实现需要 torch（张量在那），而编排主进程（harness 生成、默认
rule 解析）只需要阈值数据——主进程纯 Python 不变式（docs/plan/
dispatch-npu-probe-subprocess/）要求二者分家，且阈值表本就是 CompareRule 的
语义（§1.15 单点）。domain 层纯数据：不 import adapters（§1.1 不反向依赖）。
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# 阈值数据（作传递数据，值对齐 cann-bench thresholds.py per-dtype 语义）
# ---------------------------------------------------------------------------

DEFAULT_THRESHOLDS: dict[str, float] = {
    "float16": 2 ** -10,
    "bfloat16": 2 ** -7,
    "float32": 2 ** -13,
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


def merge_thresholds(proto: dict[str, float] | None) -> dict[str, float]:
    """合并默认表 ⊕ proto 覆盖（proto 优先）→ ``CompareRule.dtype_thresholds``。

    单一规范默认表 = ``DEFAULT_THRESHOLDS``（cann-bench thresholds.py 对齐）。
    proto ``precision_thresholds`` 覆盖默认（如 DQ 声明 ``int8: 1.0`` 允许 ±1 量化）。
    P79 三表合一收口：``runner._DTYPE_THRESHOLDS_FALLBACK`` /
    ``task_loader.DEFAULT_DTYPE_THRESHOLDS`` / ``task_loader._derive_thresholds``
    均已删除（§2.5 单通路）——所有阈值来源经此一处。P79 维度 A 桥接的唯一入口。
    """
    merged = dict(DEFAULT_THRESHOLDS)
    if proto:
        merged.update(proto)
    return merged


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

_FLOAT32_FALLBACK = DEFAULT_THRESHOLDS["float32"]


def _lookup(dtype_str: str, table: dict[str, float]) -> float:
    """按 dtype 查表，大小写不敏感，未知 dtype 回退 float32 项。"""
    lower = dtype_str.lower()
    if lower in table:
        return table[lower]
    return table.get("float32", _FLOAT32_FALLBACK)


def threshold_for_dtype(dtype_str: str, merged: dict[str, float]) -> float:
    """逐输出阈值：merged（含 proto 覆盖）优先 → DEFAULT_THRESHOLDS → float32 回退。

    ``merged`` 由调用方合并好（``dict(DEFAULT_THRESHOLDS); merged.update(proto)``），
    故 merged 命中即等价于 proto 覆盖优先、默认表兜底——与 cann-bench
    ``_get_output_threshold`` 同语义。
    """
    lower = dtype_str.lower()
    if lower in merged:
        return merged[lower]
    return _lookup(dtype_str, DEFAULT_THRESHOLDS)


def _small_value_threshold(dtype_str: str) -> float:
    return _lookup(dtype_str, SMALL_VALUE_THRESHOLDS)


def _small_value_error(dtype_str: str) -> float:
    return _lookup(dtype_str, SMALL_VALUE_ERROR_THRESHOLDS)


def _cancel_boundary(dtype_str: str) -> float:
    return _lookup(dtype_str, CANCEL_BOUNDARY_THRESHOLDS)


def _cancel_zero_threshold(dtype_str: str) -> float:
    return _lookup(dtype_str, CANCEL_ZERO_THRESHOLDS)


@dataclass(frozen=True)
class CompareRule:
    """精度判定规则（数据）。

    当前只承载 per-dtype 阈值（单标杆）。``dtype_thresholds`` 是合并后的
    ``{dtype: tolerance}``（默认表 ⊕ proto 覆盖，proto 优先），由调用方
    （``debug_service``）用 ``merge_thresholds`` 组装后传入。

    预留：未来双标杆/区间比较只扩字段（如 ``tolerances``/``mode``），
    adapters 的 ``PrecisionComparer`` 协议签名（``aggregate(rule, ...)``）不变。
    """

    dtype_thresholds: dict[str, float]
