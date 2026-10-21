# LayerNormV4 算子 API 描述

## 1. 算子简介

LayerNormV4 算子对输入张量的尾部若干维做「均值为 0、标准差为 1」的层归一化，并在输出归一化结果的同时返回每一行的均值与标准差倒数，供反向或后续计算复用。

**主要应用场景**：
- Transformer / Diffusion 等模型中 Attention 与 FFN 前的 LayerNorm
- 图像与视频生成网络中的通道归一化（例如 norm 维度为 88、1280 等）
- 需要复用统计量的场景（同时输出 mean 与 rstd）

**算子特征**：
- 难度等级：L2（Reduce 类，含行内归约 + 广播缩放）
- 多输入（含 2 个可选输入）、3 个输出中 2 个为附加统计量
- 归一化维度的长度可为 1 到数万元素，外层行数可从 1 到数万行

## 2. 算子定义

### 数学公式

设输入 `x` 的 shape 为 $[A_1, ..., A_i, R_1, ..., R_j]$，其中 $R_1 \times ... \times R_j$ 为需要归一化的部分（由 `normalized_shape` 给出），每一行（固定 $A_1 ... A_i$ 后的 $R_1 \times ... \times R_j$ 个元素）独立计算：

$$
\text{mean} = \mathrm{E}[x]
$$

$$
\text{Var}[x] = \mathrm{E}[(x - \text{mean})^2]
$$

$$
\text{rstd} = \frac{1}{\sqrt{\text{Var}[x] + \epsilon}}
$$

$$
y = \big((x - \text{mean}) \cdot \text{rstd}\big) \cdot \gamma + \beta
$$

其中 `Var[x]` 为**总体方差**（除以元素个数，而非元素个数减一），与 `torch.nn.LayerNorm` 的定义一致。

### 特殊情况

| 条件 | 影响 |
|------|------|
| `normalized_shape` 乘积为 1（如 `[1]`） | 单元素归一化：`mean = x`、`Var = 0`、`rstd = 1/sqrt(epsilon)`、`y = beta`（gamma 存在时乘 1） |
| `normalized_shape` 覆盖 `x` 的全部维度 | 外层行数为 1，整体作为一个归一化样本 |
| `gamma` 省略 | 等价于 shape 为 `normalized_shape`、数据全为 1 的 `gamma` |
| `beta` 省略 | 等价于 shape 为 `normalized_shape`、数据全为 0 的 `beta` |
| `x` 的所有元素相同 | `Var = 0`、`rstd = 1/sqrt(epsilon)`、`y = beta` |

## 3. 接口规范

### 算子原型

```python
cann_bench.layer_norm_v4(
    Tensor x,
    int[] normalized_shape,
    Tensor? gamma,
    Tensor? beta,
    float epsilon=1e-5,
    int impl_mode=0
) -> (Tensor y, Tensor mean, Tensor rstd)
```

### 输入参数说明

| 参数 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| x | Tensor（必选） | - | 待归一化的输入，shape 为 `[A1,...,Ai,R1,...,Rj]`，支持 FLOAT32 / FLOAT16 / BFLOAT16 |
| normalized_shape | int32/int64 一维序列（必选） | - | 需要归一化的尾部维度 `[R1,...,Rj]`，长度不小于 1 且不大于 `x` 的维度数；其乘积与 `x` 右对齐的对应维度必须相等 |
| gamma | Tensor（可选） | None | 缩放权重，shape 与 `normalized_shape` 相同。省略时按全 1 处理 |
| beta | Tensor（可选） | None | 偏移量，shape 与 `normalized_shape` 相同。省略时按全 0 处理 |
| epsilon | float | 1e-5 | 加到方差上的稳定项，需为正数 |
| impl_mode | int | 0 | 实现模式，取值 0 / 1 / 2，见下文「规则与约束」 |

### 输出

| 参数 | Shape | dtype | 描述 |
|------|-------|-------|------|
| y | 与 `x` 完全相同 | 与 `x` 相同 | 归一化并施加仿射后的结果 |
| mean | `x` 的 shape，且最后 `j = len(normalized_shape)` 维置 1 | FLOAT32 | 每一行的均值 E[x] |
| rstd | 同 `mean` | FLOAT32 | 每一行的标准差倒数 1/sqrt(Var[x] + epsilon) |

### 数据类型

| x dtype | gamma/beta dtype | 输出 y dtype | 输出 mean/rstd dtype |
|---------|------------------|--------------|----------------------|
| float32 | float32（或省略） | float32 | float32 |
| float16 | float16（或省略） | float16 | float32 |
| float16 | float32（或省略） | float16 | float32 |
| bfloat16 | bfloat16（或省略） | bfloat16 | float32 |
| bfloat16 | float32（或省略） | bfloat16 | float32 |

`gamma` 与 `beta` 同时存在时必须同 dtype；`normalized_shape` 支持 INT32 与 INT64。

### 规则与约束

- `y` 的 shape 与 `x` 完全一致，`y` 的 dtype 与 `x` 一致；`mean`、`rstd` 的形状始终按 `x` 去掉尾部 `j` 维后补齐 `j` 个 1 推导，两者形状相同。
- `mean`、`rstd` 的 dtype 恒为 FLOAT32（**需求决策 D1**，见第 6 节）。
- 归约使用**总体方差**（有偏估计），即除以 $R_1 \times ... \times R_j$。
- 数值计算精度：FLOAT16 / BFLOAT16 输入时，均值与方差按 FLOAT32 精度累加计算，`y` 最后转回输入 dtype（**需求决策 D2**）。
- `gamma` 省略时等价于全 1 张量，`beta` 省略时等价于全 0 张量；两者可同时省略，也可只省略其中一个（**需求决策 D3**）。
- `impl_mode` 语义：
  - `0`：高精度模式（默认），按第 4 节精度标准验证；
  - `1`：高性能模式，允许以累加顺序/精度换吞吐，结果存在精度损失，验证时按放宽后的阈值判定；
  - `2`：保持 FLOAT16 计算模式，仅当 `x`、`gamma`、`beta` 全部为 FLOAT16 时可用，计算精度最低。
  - `impl_mode` 只影响实现精度，不改变第 2 节的数学定义，也不改变输出 shape 与 dtype（**需求决策 D4**）。
- `x` 的维度数支持 1 ~ 8；`normalized_shape` 的元素个数支持 1 ~ 8 且不大于 `x` 的维度数。
- 不支持空 Tensor（`x` 元素个数需 ≥ 1）与 `normalized_shape` 为空。

### 支持范围

输入 tensor 各维度与参数的支持范围：

| 维度 / 参数 | 范围 | 备注 |
|---|---|---|
| `x` 维度数 | 1 ~ 8 | 含 1D 到 8D；高维按尾部维度归一化 |
| `normalized_shape` 元素个数 | 1 ~ 8 | 不大于 `x` 维度数 |
| `normalized_shape` 乘积（行内元素数） | 1 ~ 583705600 | 实测覆盖 1 / 8 / 20 / 32 / 88 / 512 / 768 / 1024 / 1280 / 2000 / 4096 / 23308 / 40960 / 57600 |
| 外层行数（`x` 元素总数 / 行内元素数） | 1 ~ 数万 | 实测覆盖 1 ~ 10656 |
| `epsilon` | 正浮点数 | 实测覆盖 1e-5 / 1e-7 / 1e-20 |
| `impl_mode` | 0 / 1 / 2 | 2 仅当全部输入为 FLOAT16 |

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

- `y`、`mean`、`rstd` 三个输出均按上述标准逐元素比较；`mean` 与 `rstd` 恒为 FLOAT32，按 FLOAT32 阈值（2^-13）判定；`y` 按其自身的 dtype 选择阈值。
- `impl_mode=0` 时必须满足上表阈值。
- `impl_mode=1`（高性能模式）与 `impl_mode=2`（保持 FLOAT16 计算）允许精度下降，判定阈值放宽到对应 dtype 阈值的 8 倍（MARE 相应按 10 倍放宽阈值判定）；该放宽仅适用于显式指定这两个模式的用例（**需求决策 D5**）。
- `epsilon` 极小时（如 1e-20），若某行方差接近 0，则 `rstd` 数值会显著增大，此时以相对误差判定，不接受绝对误差比较。

## 5. 标准 Golden 代码

```python
from typing import List, Optional, Tuple

import torch

"""
LayerNormV4算子Torch Golden参考实现

对输入张量 x 的后 j 维（j = len(normalized_shape)）做均值为 0、标准差为 1 的归一化：
- mean = E[x]
- rstd = 1 / sqrt(Var[x] + epsilon)
- y = ((x - mean) * rstd) * gamma + beta

其中 gamma/beta 省略时分别按全 1 / 全 0 参与计算；mean/rstd 始终以 FLOAT32 输出，
形状为 x.shape 且后 j 维置 1；y 的 dtype 与 x 一致。
FLOAT16/BFLOAT16 输入统一升到 FLOAT32 计算后再把 y 转回原 dtype。
"""


def layer_norm_v4(
    x: torch.Tensor,
    normalized_shape: List[int],
    gamma: Optional[torch.Tensor] = None,
    beta: Optional[torch.Tensor] = None,
    epsilon: float = 1e-5,
    impl_mode: int = 0,
) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """
    计算指定归一化维度的 LayerNorm，并同时返回均值与标准差倒数

    Args:
        x: 输入张量，shape 为 [A1, ..., Ai, R1, ..., Rj]，支持 FLOAT32/FLOAT16/BFLOAT16
        normalized_shape: 需要归一化的尾部维度 [R1, ..., Rj]，长度不超过 x 的维度数
        gamma: 可选缩放权重，shape 为 [R1, ..., Rj]；None 表示全 1
        beta: 可选偏移量，shape 为 [R1, ..., Rj]；None 表示全 0
        epsilon: 加到方差上的稳定项
        impl_mode: 实现模式，0 高精度 / 1 高性能 / 2 保持 FLOAT16 计算；
            不影响数学定义，仅影响实现精度，golden 统一按高精度语义计算

    Returns:
        (y, mean, rstd)：
        - y：shape 与 x 相同，dtype 与 x 相同
        - mean：FLOAT32，shape 为 [A1, ..., Ai, 1, ..., 1]
        - rstd：FLOAT32，shape 为 [A1, ..., Ai, 1, ..., 1]
    """
    origin_dtype = x.dtype
    # FP16/BF16 输入先升到 FP32 计算，避免统计量在低精度下损失
    if origin_dtype in (torch.float16, torch.bfloat16):
        compute_dtype = torch.float32
    else:
        compute_dtype = origin_dtype

    norm_dims = list(normalized_shape)
    axis_count = len(norm_dims)
    reduce_dims = tuple(range(x.dim() - axis_count, x.dim()))

    x_compute = x.to(compute_dtype)

    mean = x_compute.mean(dim=reduce_dims, keepdim=True)
    # 使用总体方差（与 torch.nn.LayerNorm 一致），即除以 R1*...*Rj
    variance = ((x_compute - mean) ** 2).mean(dim=reduce_dims, keepdim=True)
    rstd = torch.rsqrt(variance + epsilon)

    normalized = (x_compute - mean) * rstd

    if gamma is not None:
        # gamma 的 shape 为 [R1, ..., Rj]，补前导 1 后按尾部维度广播
        normalized = normalized * gamma.to(compute_dtype).reshape([1] * (x.dim() - axis_count) + norm_dims)
    if beta is not None:
        normalized = normalized + beta.to(compute_dtype).reshape([1] * (x.dim() - axis_count) + norm_dims)

    y = normalized.to(origin_dtype)
    return y, mean.to(torch.float32), rstd.to(torch.float32)
```

## 6. 额外信息

### 需求决策说明

以下规则由本需求基线自行确定（公开接口说明未逐条明确或存在多义），全部产物按此执行：

| 编号 | 决策 | 依据与影响 |
|------|------|-----------|
| D1 | `mean`、`rstd` 输出 dtype 恒为 FLOAT32，与 `x` 的 dtype 无关 | 接口文档允许 mean/rstd 为 FLOAT32/FLOAT16/BFLOAT16，但算子定义与形状推导均将二者固定为 FLOAT32；需求取固定 FLOAT32，保证 golden 与实现一致，并使统计量不因低精度损失 |
| D2 | FLOAT16/BFLOAT16 输入的统计量按 FLOAT32 累加，`y` 计算后转回输入 dtype | 与生态中 LayerNorm 的 CPU 参考算法「低精度先升 FLOAT32 计算再转回」一致；保证 fp16/bf16 用例按第 4 节阈值可判定 |
| D3 | `gamma` / `beta` 可独立省略，省略者分别等价于全 1 / 全 0 | 接口文档对可选输入的空构造有明确规定；此处确认为算子级语义，golden 与用例据此把 None 直接当作恒等元素参与计算 |
| D4 | `impl_mode` 只影响实现精度，不改变数学定义、输出 shape 与 dtype | 接口文档仅承诺 0/1/2 三种策略及精度差异；需求统一 golden 语义，差异只体现在精度阈值上 |
| D5 | `impl_mode=1/2` 的精度阈值放宽为对应 dtype 阈值的 8 倍 | 接口文档明确「高性能模式有精度损失」「保持 FLOAT16 计算精度最低」，但未给量化阈值；需求取 8 倍作为可执行判定，避免对允许降精度的模式过严 |
| D6 | 归约使用总体方差（除以元素个数），不使用无偏方差 | 对齐 `torch.nn.LayerNorm` 语义；与接口文档公式 Var[x] = E[x²] − (E[x])² 一致 |
| D7 | `epsilon` 允许取 1e-20 这类极小正值，不做下限截断 | 用例需覆盖极小 epsilon 下的稳定性；实现直接参与 `Var + epsilon` 计算，无需额外规则 |

### 算子调用示例

```python
import torch
import torch_npu
import cann_bench

x = torch.randn(2, 333, 16, 88, dtype=torch.float16, device="npu")
gamma = torch.ones(88, dtype=torch.float16, device="npu")
beta = torch.zeros(88, dtype=torch.float16, device="npu")

# 常规调用：1 维归一化 + 全仿射
y, mean, rstd = cann_bench.layer_norm_v4(x, [88], gamma, beta)

# 省略 gamma/beta：等价于全 1 / 全 0
y, mean, rstd = cann_bench.layer_norm_v4(x, [88], None, None)

# 多维归一化 + 自定义 epsilon
x2 = torch.randn(512, 16, 48, dtype=torch.float32, device="npu")
y, mean, rstd = cann_bench.layer_norm_v4(x2, [16, 48], None, None, epsilon=1e-7)

# 高性能模式
y, mean, rstd = cann_bench.layer_norm_v4(x, [88], gamma, beta, epsilon=1e-5, impl_mode=1)
```
