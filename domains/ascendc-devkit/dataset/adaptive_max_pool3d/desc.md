# AdaptiveMaxPool3d 算子 API 描述

## 1. 算子简介

AdaptiveMaxPool3d 对输入张量的最后三个维度（D、H、W）执行 3D 自适应最大池化：不需要用户给定 kernel/stride/padding，而是由输出空间大小 `output_size = (Do, Ho, Wo)` 反推每个输出点对应的输入窗口，并在窗口内取最大值。算子在输出池化结果 `y` 的同时，输出每个最大值点在输入单通道 `D*H*W` 空间内的展平索引 `indices`。

**主要应用场景**：

- 3D 检测/分割网络中把任意尺寸的特征体统一到固定输出分辨率；
- 需要复用池化位置（例如反池化、可解释性分析）的最大池化场景。

**算子特征**：

- 难度等级：L2（多输出 + 自适应索引计算）
- 两个输出 `y` 与 `indices`，二者 shape 相同
- 支持 4 维 (C,Di,Hi,Wi) 与 5 维 (N,C,Di,Hi,Wi) 输入

## 2. 算子定义

### 数学公式

设输入 `x` 的 shape 为 `(N, C, Di, Hi, Wi)`，`output_size = (Do, Ho, Wo)`。对输出位置 `(n, c, l, m, p)`，其窗口在三个方向上的起止下标为：

$$
D_{left}(l) = \left\lfloor \frac{l \cdot D_i}{D_o} \right\rfloor,\quad
D_{right}(l) = \left\lceil \frac{(l+1) \cdot D_i}{D_o} \right\rceil
$$

$$
H_{left}(m) = \left\lfloor \frac{m \cdot H_i}{H_o} \right\rfloor,\quad
H_{right}(m) = \left\lceil \frac{(m+1) \cdot H_i}{H_o} \right\rceil
$$

$$
W_{left}(p) = \left\lfloor \frac{p \cdot W_i}{W_o} \right\rfloor,\quad
W_{right}(p) = \left\lceil \frac{(p+1) \cdot W_i}{W_o} \right\rceil
$$

池化结果为窗口内的最大值：

$$
y(n,c,l,m,p) = \max_{\substack{i \in [D_{left}, D_{right}) \\ j \in [H_{left}, H_{right}) \\ k \in [W_{left}, W_{right})}} x(n,c,i,j,k)
$$

索引为该最大值在单通道 `D_i*H_i*W_i` 空间内的展平偏移：

$$
indices(n,c,l,m,p) = \arg\max_{i,j,k} x(n,c,i,j,k),\quad
\text{offset} = i \cdot H_i W_i + j \cdot W_i + k
$$

### 特殊情况

| 条件 | 行为 |
|------|------|
| 窗口内有多个相等最大值 | 取遍历顺序中首次出现的那个，其展平偏移作为索引 |
| `Do = Di`、`Ho = Hi`、`Wo = Wi` | 每个窗口只含 1 个元素，输出等于输入，索引为各元素的展平偏移 |
| `Do > Di` 等输出大于输入 | 相邻窗口会重复覆盖同一批输入点，窗口起点与终点按上方公式分别取 floor/ceil |
| 输入为 4 维 `(C,Di,Hi,Wi)` | 视为 `N = 1` 计算，输出保持 4 维，索引仍是单通道 `D_i*H_i*W_i` 内的展平偏移 |
| 窗口内出现 NaN | NaN 参与比较并被视为最大值向外传播；本需求不额外约定 NaN 之外的输入取值 |

## 3. 接口规范

### 算子原型

```python
cann_bench.adaptive_max_pool3d(Tensor x, int[] output_size, int indices_dtype=3) -> (Tensor y, Tensor indices)
```

### 输入参数说明

| 参数 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| x | Tensor | 必选 | 待池化输入，4 维 `(C,Di,Hi,Wi)` 或 5 维 `(N,C,Di,Hi,Wi)`，布局 ND |
| output_size | list[int] | 必选 | 输出空间大小 `[Do, Ho, Wo]`，长度必须为 3，每个元素不小于 1 |
| indices_dtype | int | 3 | 索引输出类型：3 表示 int32，9 表示 int64 |

### 输出

| 参数 | Shape | dtype | 描述 |
|------|-------|-------|------|
| y | `(N,C,Do,Ho,Wo)`，4 维输入时为 `(C,Do,Ho,Wo)` | 与输入 x 相同 | 窗口最大值 |
| indices | 与 y 相同 | int32 或 int64，由 `indices_dtype` 决定 | 最大值在单通道 `D_i*H_i*W_i` 空间内的展平偏移 |

### 数据类型

| 输入 x dtype | 输出 y dtype | indices dtype |
|--------------|--------------|---------------|
| float16 | float16 | int32 / int64 |
| bfloat16 | bfloat16 | int32 / int64 |
| float32 | float32 | int32 / int64 |

### 规则与约束

- `x` 除 D/H/W 外的维度必须不小于 1，D/H/W 每一维也必须不小于 1，不支持空张量。
- `x` 的 `Di*Hi*Wi` 不能超过 int32 的最大表示（2147483647），否则索引无法用 int32 表达。
- `output_size` 长度必须为 3，且每个元素均须大于 0。
- `y` 与 `x` 的 dtype 必须一致；`indices` 的 dtype 由 `indices_dtype` 决定（3 → int32，9 → int64）。
- 计算采用确定性实现：同一输入多次执行结果完全一致。
- 索引语义为**单通道内** `D_i*H_i*W_i` 的展平偏移，不含 N/C 维度偏移。

### 支持范围

本需求针对 Ascend 950PR/950DT 系列（A5）芯片。该芯片上：

| 维度 / 参数 | 范围 | 备注 |
|---|---|---|
| `x` 维度数 | 4 或 5 | ND 布局，前导维（N、C）与 D/H/W 均须 ≥ 1 |
| `x` 各维大小 | 1 ~ 301 | 硬约束为各维 ≥ 1 且 `D*H*W ≤ 2147483647`；用例实测最大 `301×300×300` |
| `x` 元素总数 | 1 ~ 1.1 亿 | 用例实测 24 ~ 108,360,000 |
| `output_size` | 长度 3，元素 1 ~ 256 | 每个元素不小于 1；允许大于对应输入维长度 |
| 输入 dtype | float16 / bfloat16 / float32 | 三者在 A5 均支持 |
| 索引 dtype | int32 / int64 | A5 同时支持两种索引类型 |

## 4. 精度要求

采用生态算子精度标准进行验证。

**误差指标**：

1. 平均相对误差（MERE）：

   $$
   \text{MERE} = \text{avg}\left(\frac{\text{abs}(actual - golden)}{\text{abs}(golden) + 10^{-7}}\right)
   $$

2. 最大相对误差（MARE）：

   $$
   \text{MARE} = \max\left(\frac{\text{abs}(actual - golden)}{\text{abs}(golden) + 10^{-7}}\right)
   $$

**通过标准**：

| 数据类型 | FLOAT16 | BFLOAT16 | FLOAT32 |
|----------|---------|----------|---------|
| **通过阈值(Threshold)** | 2^-10 | 2^-7 | 2^-13 |

当平均相对误差 MERE < Threshold 且最大相对误差 MARE < 10 × Threshold 时判定为通过。

**多输出判定**：

- `y` 按上表对应 dtype 的阈值单独判定，指数/最大值运算在通道内不引入累加，正常情况下应逐元素完全一致；
- `indices` 为整数输出，要求与 golden 逐元素完全相等，任何一位差异都判定为失败；
- 两个输出分别判定，任一不通过即整体判定失败。

## 5. 标准 Golden 代码

```python
from typing import List

import torch
import torch.nn.functional as F


def adaptive_max_pool3d(
    x: torch.Tensor,
    output_size: List[int],
    indices_dtype: int = 3,
) -> List[torch.Tensor]:
    """
    AdaptiveMaxPool3d 算子 Torch Golden 参考实现。

    对输入 x 的最后三个维度做 3D 自适应最大池化，同时返回最大值在窗口内的
    展平索引（索引基于单通道内的 D*H*W 空间展开，与输入是否 4 维无关）。

    Args:
        x: 输入张量，shape 为 (N, C, Di, Hi, Wi) 或 (C, Di, Hi, Wi)。
        output_size: 输出空间大小 (Do, Ho, Wo)，三个元素均不小于 1。
        indices_dtype: 索引输出类型，3 表示 int32，9 表示 int64；默认 3。

    Returns:
        [y, indices]，二者 shape 均为 (N, C, Do, Ho, Wo)（输入为 4 维时为
        (C, Do, Ho, Wo)）；y 与 x 同 dtype，indices 为 int32 或 int64。
    """
    if x.dim() == 4:
        x_5d = x.unsqueeze(0)
    else:
        x_5d = x

    x_dtype = x.dtype
    if x_dtype in (torch.float16, torch.bfloat16):
        compute_x = x_5d.to(torch.float32)
    else:
        compute_x = x_5d

    y, indices = F.adaptive_max_pool3d(compute_x, tuple(output_size), return_indices=True)

    y = y.to(x_dtype)
    indices = indices.to(torch.int32 if indices_dtype == 3 else torch.int64)

    if x.dim() == 4:
        y = y.squeeze(0)
        indices = indices.squeeze(0)

    return [y, indices]
```

## 6. 额外信息

### 算子调用示例

```python
import torch
import cann_bench

# 5 维输入，int32 索引
x = torch.randn(2, 32, 17, 16, 16, dtype=torch.float32, device="npu")
y, indices = cann_bench.adaptive_max_pool3d(x, [4, 4, 4])

# 4 维输入（无批次维），float16
x4 = torch.randn(32, 17, 16, 16, dtype=torch.float16, device="npu")
y4, idx4 = cann_bench.adaptive_max_pool3d(x4, [4, 4, 4])

# 输出 64 位索引
y64, idx64 = cann_bench.adaptive_max_pool3d(x, [4, 4, 4], indices_dtype=9)
```

### 用例执行与数据构造约定

`cases.yaml` 是主数据；`cases.csv` 的七个固定列（`operator,case_id,input_shape,dtype,attrs,value_range,note`）与 YAML 逐项对应，结构化单元格为 JSON。

- `chips` 固定为 `["A5"]`；`layout` 固定为 `ND`（逻辑形状为 NCDHW 或 CDHW）；`view` 固定为 `contiguous`。
- `attrs` 中 `outputSize` 为 `[Do, Ho, Wo]`；`indices_dtype` 仅在需要 int64 索引时显式写出，缺省为 3（int32）。
- `generator` 为 `uniform` 时，seed 固定为 `case_id`，在该输入的 `value_range` 有限区间 `[lo, hi]` 上均匀采样后转换为目标 dtype。
- `value_range` 与 `input_shape`、`dtype` 一样按输入顺序排列；本算子只有一个张量输入，因此长度为 1。
- `expected` 只记录 `y` 与 `indices` 的 shape、dtype、layout，具体数值由第 5 节 Golden 计算。
- 输入数据均为有限值域内的随机数，不构造 NaN/Inf 特殊值：`indices` 需要与 golden 完全一致，输入中出现特殊值时不同实现可能对"窗口内多个 NaN"的索引取舍不同，无法作为判定依据。
