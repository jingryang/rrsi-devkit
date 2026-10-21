# GroupNormSilu 算子 API 描述

## 1. 算子简介

GroupNormSilu 算子把分组的层归一化（GroupNorm）与 SiLU 激活融合成一次计算：先按通道分组统计均值与方差，对每组做归一化并施加仿射，再对结果逐元素求 SiLU，一次访存同时产出激活结果与两路统计量。

**主要应用场景**：
- 扩散模型 / 视频生成网络中的通道分组归一化 + 激活（典型通道数 32 / 64 / 128 / 256 / 512）
- 需要复用统计量的场景（同时输出每组的 mean 与 rstd 供反向或其他算子使用）
- 以「空间维为 1」的形态做纯通道分组归一化

**算子特征**：
- 难度等级：L2（Reduce 类，含分组归约 + 广播缩放 + 逐元素激活）
- 三输入（其中 2 个可选）、三输出（其中 2 个为附加统计量）
- 归约集合同时跨越「组内通道」与「空间维」，归约长度可从 1 到数十万
- 归约集合彼此独立，不存在跨组归约

## 2. 算子定义

### 数学公式

设输入 `x` 的 shape 为 `[N, C, D_1, ..., D_k]`，组数为 `group`，则每组包含 `C/group` 个通道。对第 `n` 个样本的第 `g` 组（记为归约集合 $S_{n,g}$，共 `C/group × D_1 × ... × D_k` 个元素）：

$$
\text{mean}_{n,g} = \mathrm{E}[x \mid S_{n,g}]
$$

$$
\text{Var}_{n,g} = \mathrm{E}\left[(x - \text{mean}_{n,g})^2 \mid S_{n,g}\right]
$$

$$
\text{rstd}_{n,g} = \frac{1}{\sqrt{\text{Var}_{n,g} + \epsilon}}
$$

$$
z_i = (x_i - \text{mean}_{n,g}) \cdot \text{rstd}_{n,g} \cdot \gamma_c + \beta_c, \quad i \in S_{n,g},\ c = \text{该元素所在的通道}
$$

$$
y_i = z_i \cdot \sigma(z_i), \quad \sigma(z) = \frac{1}{1 + e^{-z}}
$$

其中 `Var` 为**总体方差**（除以元素个数，而非元素个数减一），与 `torch.nn.GroupNorm` 的定义一致。

### 特殊情况

| 条件 | 影响 |
|------|------|
| `gamma` 省略 | 等价于 shape 为 `[C]`、数据全为 1 的 `gamma` |
| `beta` 省略 | 等价于 shape 为 `[C]`、数据全为 0 的 `beta` |
| `gamma` 与 `beta` 同时省略 | 等价于恒等仿射，`z = (x - mean) * rstd` |
| `group == C` | 每组只含 1 个通道，归约集合大小等于空间维元素数；当空间维全为 1 时每组仅 1 个元素 |
| `group == 1` | 全部通道归入同一组，每个样本只有 1 组统计量 |
| `x` 所有元素相同 | `Var = 0`、`rstd = 1/sqrt(epsilon)`、`z = beta`、`y = beta * sigmoid(beta)` |
| 空间维存在为 1 的维度 | 该维不参与额外展开，归约只跨组内通道与其余空间维 |

### 数据类型与输出 dtype 的推导规则（需求决策 D1）

- `y` 的 dtype 恒等于 `x` 的 dtype。
- `mean` / `rstd` 的 dtype 按以下顺序确定：若 `gamma` 存在则取其 dtype；否则若 `beta` 存在则取其 dtype；否则取 `x` 的 dtype。
- `gamma` 与 `beta` 同时存在时，二者 dtype 必须一致。
- 该规则使「`x` 为低精度、`gamma`/`beta` 为 FLOAT32」的混合精度调用可以把统计量保留在 FLOAT32，避免统计量在低精度下损失。

## 3. 接口规范

### 算子原型

```python
cann_bench.group_norm_silu(Tensor x, int group, Tensor? gamma=None, Tensor? beta=None, float eps=1e-05) -> (Tensor y, Tensor mean, Tensor rstd)
```

### 输入参数说明

| 参数 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| x | Tensor | 必选 | 输入张量，ND 布局，2~8 维；第 0 维为 N，第 1 维为通道数 C；dtype 为 FLOAT16 / FLOAT32 / BFLOAT16 |
| group | int | 必选 | 将第 1 维 C 划分的组数，要求 `group > 0` 且 `C % group == 0` |
| gamma | Tensor | None | 可选缩放权重，shape 必须为 `[C]`；dtype 与 `x` 相同或为 FLOAT32；省略等价于全 1 |
| beta | Tensor | None | 可选偏移量，shape 必须为 `[C]`；dtype 与 `x` 相同或为 FLOAT32；省略等价于全 0 |
| eps | float | 1e-05 | 加到方差上的数值稳定补偿项，要求 `eps > 0` |

### 输出

| 参数 | Shape | dtype | 描述 |
|------|-------|-------|------|
| y | 与 `x` 完全相同 | 与 `x` 相同 | SiLU 激活后的归一化结果 |
| mean | `[N, group]` | 按 D1 推导 | 每个 `(n, g)` 归约集合的均值 |
| rstd | `[N, group]` | 与 `mean` 相同 | 每个 `(n, g)` 归约集合的标准差倒数 |

输出顺序固定为 `(y, mean, rstd)`，与上面的函数原型返回签名一致。

### 数据类型

| x dtype | gamma/beta dtype | y dtype | mean/rstd dtype |
|---------|------------------|---------|-----------------|
| float16 | float16（或省略） | float16 | float16 |
| float16 | float32 | float16 | float32 |
| float32 | float32（或省略） | float32 | float32 |
| bfloat16 | bfloat16（或省略） | bfloat16 | bfloat16 |
| bfloat16 | float32 | bfloat16 | float32 |

`gamma` 与 `beta` 同时存在时 dtype 必须相同；不支持「`x` 为 float32 而 `gamma` 为 float16/bfloat16」。`mean`/`rstd` 的 dtype 允许为 FLOAT16 / BFLOAT16 / FLOAT32，按 D1 规则推导。

### 规则与约束

- **shape 关系**：`x` 维度数为 2 ~ 8；`gamma`、`beta` 必须为 1 维且元素个数等于 `C`。
- **分组约束**：`group > 0` 且 `C % group == 0`；组内通道数为 `C / group`。
- **归约集合**：每个 `(n, g)` 独立归约，集合大小为 `(C / group) × D_1 × ... × D_k`，归约集合之间不共享元素。
- **整体精度（需求决策 D2）**：FLOAT16 / BFLOAT16 输入时，均值、方差与归一化按高精度（不低于 FLOAT32）累加与计算，`y` 最后一次性舍入到输入 dtype；`mean`/`rstd` 按 D1 的 dtype 一次性舍入。
- **`epsilon` 有效域**：`eps > 0`。
- **空张量（需求决策 D3）**：`x` 元素个数为 0 属于支持域。此时 `y` 为空张量（shape 与 `x` 相同、元素个数为 0），`mean`/`rstd` 仍按 `[N, group]` 输出，其数值不做约束（无元素可归约），调用方不应消费其内容。本条为显式支持声明，不构成必测场景。
- **NaN/Inf 传播**：输入含 Inf 或 NaN 时按 IEEE-754 语义传播，不做特殊屏蔽。
- **布局**：所有输入输出均为 ND 连续布局；二维输入（`k = 0`）表示无空间维。

### 支持范围

| 维度 / 参数 | 范围 | 备注 |
|---|---|---|
| `x` 维度数 | 2 ~ 8 | 第 0 维为 N，第 1 维为 C，其余为空间维 |
| `N` | 1 ~ 65536 | 测试集实测 1 ~ 512 |
| `C` | 1 ~ 65536 | 测试集实测 32 ~ 65536 |
| 空间维乘积 `D_1 × ... × D_k` | 1 ~ 数万 | 测试集实测 1 ~ 200000 |
| 组内通道数 `C / group` | 1 ~ C | 由 `group` 决定 |
| 归约集合大小 | 1 ~ 数万 | 测试集实测 1 ~ 200000 |
| `group` | 1 ~ C，且整除 C | 测试集实测 1 / 8 / 16 / 32 / 64 / 65536 |
| `eps` | 正浮点数 | 测试集实测 1e-05 |
| `gamma` / `beta` | 可独立省略 | 全仿射、仅 gamma、仅 beta、都省略均覆盖 |

## 4. 精度要求

采用[生态算子精度标准](https://gitcode.com/cann/opbase/blob/master/docs/zh/ops_precision_standard/experimental_standard.md)进行验证。

**误差指标**：

1. 平均相对误差（MERE）：采样点中相对误差平均值

   $$
   \text{MERE} = \text{avg}(\frac{\text{abs}(actual - golden)}{\text{abs}(golden)+\text{1e-7}})
   $$

2. 最大相对误差（MARE）：采样点中相对误差最大值

   $$
   \text{MARE} = \max(\frac{\text{abs}(actual - golden)}{\text{abs}(golden)+\text{1e-7}})
   $$

**通过标准**：

| 数据类型 | FLOAT16 | BFLOAT16 | FLOAT32 | HiFLOAT32 | FLOAT8 E4M3 | FLOAT8 E5M2 |
|----------|---------|----------|---------|-----------|-------------|-------------|
| **通过阈值(Threshold)** | 2^-10 | 2^-7 | 2^-13 | 2^-11 | 2^-3 | 2^-2 |

当平均相对误差 MERE < Threshold，最大相对误差 MARE < 10 * Threshold 时判定为通过。

**本算子说明**：

- `y`、`mean`、`rstd` 三个输出均按上述标准逐元素比较，各自按**自身 dtype** 选择阈值（`mean`/`rstd` 在混合精度场景下为 FLOAT32，按 2^-13 判定）。
- `y` 的计算包含 `x - mean` 这一步，当输入值接近该组均值时会出现相消，`|y|` 可远小于输入量级；此时相对误差的分母 `|golden|+1e-7` 趋零，单点相对误差会被放大数个数量级。**需求决策 D4**：沿用生态标准的小值处理——
  - **MERE 按全部有限元素统计**（含小值元素），阈值不变；
  - **MARE 只在 `|golden| >= small_value` 的元素上取最大**，`small_value` 见下表；
  - 小值元素不设单独的绝对误差判据，避免引入与数据量级绑定的额外参数。

  | 判定 dtype | small_value |
  |---|---|
  | FLOAT16 | 2^-11 |
  | BFLOAT16 | 2^-8 |
  | FLOAT32 | 2^-14 |

  该口径下 MERE 仍覆盖所有元素，若某实现整体偏差偏大，MERE 会直接暴露；同时避免近零单点主导 MARE 造成系统性误判。
- `mean`/`rstd` 为归约结果，按同一口径判定（同样适用 small_value 的小值处理）。
- 非有限值：NaN 位置必须两侧一致，Inf 必须两侧同号；否则该输出判为不通过。

## 5. 标准 Golden 代码

```python
from typing import List, Optional, Tuple

import torch

"""
GroupNormSilu算子Torch Golden参考实现

对输入张量 x 按通道分组做 GroupNorm，再对归一化结果做 SiLU 激活：
- 记 x 的 shape 为 [N, C, ...]，归约集合为「同一 (n, g) 下的 C/group 个通道 × 其余全部维」
- mean  = E[x]
- var   = E[(x - mean)^2]              （总体方差，除以元素个数）
- rstd  = 1 / sqrt(var + epsilon)
- z     = (x - mean) * rstd * gamma + beta
- y     = z * sigmoid(z)               （SiLU）

gamma / beta 省略时分别等价于全 1 / 全 0；gamma 与 beta 的 shape 必须为 [C]。
mean / rstd 的 shape 恒为 [N, group]，dtype 取 gamma（缺省时取 beta，再缺省取 x）的 dtype。
全部计算在 FLOAT64 中完成，最后一次性舍入到各自的输出 dtype。
"""


def group_norm_silu(
    x: torch.Tensor,
    group: int,
    gamma: Optional[torch.Tensor] = None,
    beta: Optional[torch.Tensor] = None,
    eps: float = 1e-5,
) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """
    计算按通道分组的 GroupNorm + SiLU 融合结果

    Args:
        x: 输入张量，shape 为 [N, C, ...]，维度数 2~8，dtype 为 FLOAT16/FLOAT32/BFLOAT16
        group: 将第 1 维 C 划分的组数，必须满足 group > 0 且 C 能被 group 整除
        gamma: 可选缩放权重，shape 为 [C]，dtype 与 x 相同或为 FLOAT32；None 表示全 1
        beta: 可选偏移量，shape 为 [C]，dtype 与 x 相同或为 FLOAT32；None 表示全 0
        eps: 加到方差上的数值稳定项，要求 eps > 0

    Returns:
        (y, mean, rstd)：
        - y：shape 与 x 相同，dtype 与 x 相同
        - mean：shape 为 [N, group]，dtype 取 gamma（缺省取 beta，再缺省取 x）的 dtype
        - rstd：shape 与 mean 相同，dtype 与 mean 相同
    """
    if x.dim() < 2:
        raise ValueError(f"GroupNormSilu requires x with at least 2 dims, got {x.dim()}")
    if group <= 0:
        raise ValueError(f"GroupNormSilu requires group > 0, got {group}")

    num_n = int(x.shape[0])
    num_c = int(x.shape[1])
    if num_c % group != 0:
        raise ValueError(f"GroupNormSilu requires C divisible by group, got C={num_c}, group={group}")

    channel_per_group = num_c // group
    spatial = 1
    for size in x.shape[2:]:
        spatial *= int(size)
    row = channel_per_group * spatial

    out_dtype = x.dtype
    if gamma is not None:
        stat_dtype = gamma.dtype
    elif beta is not None:
        stat_dtype = beta.dtype
    else:
        stat_dtype = x.dtype

    # 统一提升到 FLOAT64 计算，输入 dtype 只用于最终输出舍入
    x_compute = x.to(torch.float64)
    flat = x_compute.reshape(num_n * group, row)

    mean = flat.mean(dim=1)
    # 总体方差（除以元素个数），与 torch.nn.GroupNorm 一致
    variance = ((flat - mean.unsqueeze(1)) ** 2).mean(dim=1)
    rstd = torch.rsqrt(variance + eps)

    z = (flat - mean.unsqueeze(1)) * rstd.unsqueeze(1)
    z = z.reshape(num_n, group, channel_per_group, spatial)

    if gamma is not None:
        z = z * gamma.to(torch.float64).reshape(1, group, channel_per_group, 1)
    if beta is not None:
        z = z + beta.to(torch.float64).reshape(1, group, channel_per_group, 1)

    z = z.reshape(x.shape)
    # SiLU: z * sigmoid(z)
    y = z * torch.sigmoid(z)

    shape_stat = [num_n, group]
    return y.to(out_dtype), mean.reshape(shape_stat).to(stat_dtype), rstd.reshape(shape_stat).to(stat_dtype)
```

## 6. 额外信息

### 需求决策说明

以下规则由本需求基线自行确定（公开接口说明未逐条明确或存在多义），全部产物按此执行：

| 编号 | 决策 | 依据与影响 |
|------|------|-----------|
| D1 | `mean`/`rstd` 的 dtype 依次取 `gamma` → `beta` → `x` 的 dtype | 接口文档只承诺「与 self 保持一致」并在部分产品上补充「与 gamma/beta 相同」；统一成一条可执行规则，使混合精度调用能把统计量保留在 FLOAT32，同时保持纯低精度调用与原行为一致 |
| D2 | 低精度输入的统计量按不低于 FLOAT32 精度累加，`y` 最后一次性舍入 | 与生态中 GroupNorm 的参考算法一致；保证 fp16/bf16 用例按第 4 节阈值可判定 |
| D3 | `x` 元素个数为 0 属于支持域，`y` 为空、`mean`/`rstd` 按 `[N, group]` 输出且数值不做约束 | 接口文档声明支持空 Tensor；但空输入下统计量无定义，故不对其数值设约束，也不纳入必测场景 |
| D4 | MERE 全量统计；MARE 排除 `\|golden\| < small_value` 的元素（fp16 2^-11 / bf16 2^-8 / fp32 2^-14） | 生态标准只给出 MERE/MARE 公式，未说明小值处理；而 `y` 在 `x≈mean` 处存在相消放大，实测近零元素相对误差可达 0.26，MARE 完全由单点决定 | 采用小值剔除口径：MERE 覆盖全部元素保证整体偏差可见，MARE 只看有意义的量级；已用 golden 对 `torch.nn.functional.group_norm + silu` 交叉验证 20/20 通过 |
| D5 | `z = (x - mean) * rstd` 后再乘 `gamma` 加 `beta`，不做中间低精度舍入 | `y` 为唯一值输出，中间舍入点不改变数学定义；统一按高精度计算使不同后端可在同一阈值下判定 |

### 算子调用示例

```python
import torch
import torch_npu
import cann_bench

# x 的 shape 为 [N, C, ...]，这里 N=2、C=64、空间维 16x16
x = torch.randn(2, 64, 16, 16, dtype=torch.float16, device="npu")
# gamma / beta 的 shape 为 [C]，dtype 与 x 相同（也可用 float32 得到 float32 统计量）
gamma = torch.randn(64, dtype=torch.float16, device="npu")
beta = torch.randn(64, dtype=torch.float16, device="npu")

# 常规调用：8 组，每组 8 个通道
y, mean, rstd = cann_bench.group_norm_silu(x, 8, gamma, beta)
# y: float16, shape (2, 64, 16, 16)
# mean: float16, shape (2, 8)
# rstd: float16, shape (2, 8)

# 省略 gamma 与 beta：等价于全 1 / 全 0 仿射
y, mean, rstd = cann_bench.group_norm_silu(x, 8, None, None)

# 混合精度：x 为 fp16，gamma/beta 为 fp32，统计量按 fp32 输出
gamma32 = torch.randn(64, dtype=torch.float32, device="npu")
beta32 = torch.randn(64, dtype=torch.float32, device="npu")
y, mean, rstd = cann_bench.group_norm_silu(x, 8, gamma32, beta32)
# y: float16, mean/rstd: float32
```

### 输出组织

- 三个输出一一对应第二节的公式，顺序固定为 `y, mean, rstd`。
- `y` 是最终结果，可直接作为下一层的输入。
- `mean`/`rstd` 按 `(n, group)` 组织，可直接与按组广播的张量配合使用。
- `rstd` 的数值量级受 `eps` 影响：`eps` 越小、该组方差越接近 0 时 `rstd` 越大。

### 典型 shape 组合

| `x` shape | `group` | `mean`/`rstd` shape | 说明 |
|---|---|---|---|
| `(2, 64, 16, 16)` | 8 | `(2, 8)` | 典型扩散模型形态，每组 8 通道 × 256 空间元素 |
| `(64, 32, 1, 1)` | 8 | `(64, 8)` | 空间维为 1，纯通道分组 |
| `(64, 32, 1, 1)` | 32 | `(64, 32)` | 每组仅 1 个元素，`rstd` 恒为 `1/sqrt(eps)` |
| `(1, 32, 400, 500)` | 32 | `(1, 32)` | 归约集合远超片上存储容量 |
| `(1, 65536, 8, 8)` | 65536 | `(1, 65536)` | 通道数超片上容量，每组 1 通道 |
