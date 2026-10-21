# DeepNorm 算子 API 描述

## 1. 算子简介

DeepNorm 是一种带残差缩放的深度归一化算子。它先把输入 `x` 乘以权重 `alpha` 并与 `gx` 相加，再沿 `gamma` 覆盖的尾部维度计算均值与方差，对结果做零均值、单位方差归一化，最后施加缩放 `gamma` 与偏置 `beta`。算子同时输出归一化所用的均值 `mean` 和标准差倒数 `rstd`。

**主要应用场景**：

- Transformer 类网络的深层归一化
- 训练中需要残差缩放的归一化层
- 需要显式获取统计量的归一化流程

**算子特征**：

- 难度等级：L2（归一化类）
- 4 个输入、3 个输出、2 个可选属性
- 归一化维由 `gamma` 的维度数决定，可覆盖多个尾部维度
- `mean`、`rstd` 固定为 float32，`y` 与输入同 dtype

## 2. 算子定义

### 数学公式

设 `x` 的 shape 为 $[N_0, \ldots, N_{m-1}, D_0, \ldots, D_{k-1}]$，其中后 $k$ 维（$k$ 等于 `gamma` 的维度数）为归一化维。令

$$
h_i = \alpha \cdot x_i + gx_i
$$

$$
\bar{h} = \frac{1}{D} \sum_{i=1}^{D} h_i, \qquad
\operatorname{var} = \frac{1}{D} \sum_{i=1}^{D} (h_i - \bar{h})^2
$$

$$
\operatorname{rstd} = \frac{1}{\sqrt{\operatorname{var} + \epsilon}}
$$

$$
y_i = (h_i - \bar{h}) \cdot \operatorname{rstd} \cdot \gamma_i + \beta_i
$$

其中 $D = D_0 \times \cdots \times D_{k-1}$，$\gamma_i$、$\beta_i$ 按归一化维广播。

### 特殊情况

| 条件 | 行为 |
|------|------|
| 归一化维上方差为 0（例如每行取值恒定） | `rstd` 等于 $1/\sqrt{\epsilon}$，`y` 等于 `beta` |
| 输入含 `+inf` 或 `-inf` | 对应位置的 `mean`、`rstd`、`y` 按 IEEE 语义传播为 `inf` 或 `nan` |
| 输入含 `NaN` | 参与该归一化行的输出按 IEEE 语义传播为 `NaN` |
| 任一维度为 0 | 不属于合法输入域，算子不保证行为；本需求只覆盖所有维度大于 0 的输入 |

## 3. 接口规范

### 算子原型

```python
cann_bench.deep_norm(Tensor x, Tensor gx, Tensor beta, Tensor gamma, float alpha=0.3, float epsilon=1e-06) -> (Tensor mean, Tensor rstd, Tensor y)
```

### 输入参数说明

| 参数 | 类型 | 必选 | 描述 |
|------|------|------|------|
| x | Tensor | 是 | 输入张量，2-8 维，dtype 为 float16/float32/bfloat16 |
| gx | Tensor | 是 | 叠加项，shape 与 dtype 均与 `x` 相同 |
| beta | Tensor | 是 | 偏置，维度数与 `gamma` 相同且在 [1, 7] 内，shape 与 `x` 的尾部归一化维一致，dtype 与 `x` 相同 |
| gamma | Tensor | 是 | 缩放，维度数与 `beta` 相同且在 [1, 7] 内，必须小于 `x` 的维度数，shape 与 `x` 的尾部归一化维一致，dtype 与 `x` 相同 |
| alpha | float | 否 | `x` 的权重，默认 0.3 |
| epsilon | float | 否 | 方差稳定项，默认 1e-06，应取正数 |

### 输出

| 参数 | Shape | dtype | 描述 |
|------|-------|-------|------|
| mean | 前导维与 `x` 相同，尾部归一化维均为 1 | float32 | 归一化维上的均值 |
| rstd | 与 `mean` 相同 | float32 | 归一化维上方差倒数的平方根 |
| y | 与 `x` 相同 | 与 `x` 相同 | 归一化结果 |

### 数据类型

| x / gx / beta / gamma / y | mean / rstd |
|---------------------------|-------------|
| float16 | float32 |
| float32 | float32 |
| bfloat16 | float32 |

同一用例内 `x`、`gx`、`beta`、`gamma`、`y` 的 dtype 必须一致。

### 规则与约束

- `x` 的维度数范围为 [2, 8]；`gamma`、`beta` 的维度数范围为 [1, 7]，且必须严格小于 `x` 的维度数。
- `gx` 的 shape 必须与 `x` 完全一致；`gamma`、`beta` 的 shape 必须分别等于 `x` 的尾部归一化维。
- `mean`、`rstd` 的维度数等于 `x` 的维度数，前导维与 `x` 相同，尾部归一化维必须全部为 1。
- 所有输入维度必须大于 0；不支持空张量。
- 数据格式为 ND；支持非连续输入，算子按逻辑张量语义计算。
- 归一化维是 `gamma` 覆盖的最后若干个维度，可以跨多个轴。
- `alpha` 可取任意有限浮点数；`epsilon` 应为正数。

### 支持范围

本次需求限定为 **A5（Ascend 950PR/950DT 系列）**：

| 项目 | 范围 |
|------|------|
| 芯片 | Ascend 950PR、Ascend 950DT |
| `x` 维度数 | 2-8 |
| `gamma` / `beta` 维度数 | 1-7，且小于 `x` 的维度数 |
| 输入 dtype | float16、float32、bfloat16 |
| 数据格式 | ND |
| 非连续输入 | 支持 |

## 4. 精度要求

采用生态算子精度标准进行验证。

**误差指标**：

1. 平均相对误差（MERE）：

   $$
   \text{MERE} = \text{avg}\left(\frac{\text{abs}(actual - golden)}{\text{abs}(golden) + 1e-7}\right)
   $$

2. 最大相对误差（MARE）：

   $$
   \text{MARE} = \max\left(\frac{\text{abs}(actual - golden)}{\text{abs}(golden) + 1e-7}\right)
   $$

**通过标准**：

| 数据类型 | FLOAT16 | BFLOAT16 | FLOAT32 |
|----------|---------|----------|---------|
| 通过阈值（Threshold） | 2^-10 | 2^-7 | 2^-13 |

当 MERE < Threshold 且 MARE < 10 × Threshold 时判定为通过。

多输出分别判定：`mean`、`rstd` 固定为 float32，按 float32 阈值判定；`y` 按其自身 dtype 的阈值判定。三个输出必须全部通过。

## 5. 标准 Golden 代码

```python
from typing import List

import torch


def deep_norm(
    x: torch.Tensor,
    gx: torch.Tensor,
    beta: torch.Tensor,
    gamma: torch.Tensor,
    alpha: float = 0.3,
    epsilon: float = 1e-6,
) -> List[torch.Tensor]:
    """DeepNorm reference implementation on CPU.

    The last ``gamma.dim()`` dimensions of ``x`` are the normalized dimensions.
    All arithmetic is performed in float32; ``mean``/``rstd`` are returned as
    float32 and ``y`` in the dtype of ``x``.

    Args:
        x: Input tensor, 2 to 8 dimensions.
        gx: Additive term with the same shape as ``x``.
        beta: Bias with the trailing shape of ``x``, 1 to 7 dimensions.
        gamma: Scale with the trailing shape of ``x``, 1 to 7 dimensions.
        alpha: Weight applied to ``x`` before adding ``gx``.
        epsilon: Numerical stability term added to the variance.

    Returns:
        ``[mean, rstd, y]`` in operator output order.
    """
    input_dtype = x.dtype
    # fp16 / bf16 are accumulated in fp32 and cast back at the very end.
    if input_dtype in (torch.float16, torch.bfloat16):
        compute_dtype = torch.float32
    else:
        compute_dtype = input_dtype

    x_compute = x.to(compute_dtype)
    gx_compute = gx.to(compute_dtype)
    beta_compute = beta.to(compute_dtype)
    gamma_compute = gamma.to(compute_dtype)

    reduce_axes = tuple(range(x_compute.dim() - gamma_compute.dim(), x_compute.dim()))
    hidden = x_compute * float(alpha) + gx_compute
    mean = torch.mean(hidden, dim=reduce_axes, keepdim=True)
    centered = hidden - mean
    variance = torch.mean(centered * centered, dim=reduce_axes, keepdim=True)
    rstd = torch.rsqrt(variance + float(epsilon))
    y = centered * rstd * gamma_compute + beta_compute

    return [mean, rstd, y.to(x.dtype)]
```

## 6. 额外信息

### 算子调用示例

```python
import torch
import cann_bench

x = torch.randn(2, 3, 4, 5, dtype=torch.float32, device="npu")
gx = torch.randn(2, 3, 4, 5, dtype=torch.float32, device="npu")
beta = torch.zeros(4, 5, dtype=torch.float32, device="npu")
gamma = torch.ones(4, 5, dtype=torch.float32, device="npu")
mean, rstd, y = cann_bench.deep_norm(x, gx, beta, gamma, alpha=0.3, epsilon=1e-6)
```

### 用例执行与数据构造约定

cases.yaml 是主数据；cases.csv 的七个固定列与 YAML 完全对应，结构化单元格为 JSON。attrs 固定包含 `alpha` 与 `epsilon`。

- `note` 为一句话自然语言描述，只概括该用例的外部可观察特征（dtype、规模、对齐/尾块、属性取值、非连续视图等），不承载机器字段，也不写芯片种类。
- 默认数据构造为 `uniform`：`seed` 固定为 `case_id`，在有限区间 `[lo, hi]` 上均匀生成后转目标 dtype；`input_shape`、`dtype`、`value_range` 均按 `x, gx, beta, gamma` 的输入顺序排列。
- 当某输入的 `value_range` 为显式值列表时（用例 15 的 `x`、`gx`），按物理行优先循环；其余输入仍用均匀分布。
- 默认布局为 ND、连续视图；用例 16 的 `x` 使用末维步长 2 的非连续视图（`gx`、`beta`、`gamma` 连续），golden 按逻辑张量计算，该构造已在 `note` 中点明。
- 输出 `mean`、`rstd`、`y` 的 shape 与 dtype 由算子原型与 golden 推导，不在用例中重复记录；数值由第 5 节 Golden 计算。
- 特殊值（NaN/Inf）未纳入用例；本批 20 个用例只覆盖合法输入域内的正常取值。
