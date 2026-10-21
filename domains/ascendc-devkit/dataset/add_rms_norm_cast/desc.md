# AddRmsNormCast 算子 API 描述

## 1. 算子简介

AddRmsNormCast 算子把大模型中高频相邻出现的三个操作融合成一次计算：残差相加（Add）、RMSNorm 归一化（RmsNorm）与类型转换（Cast）。一次访存即可同时产出四个结果，省去了 AddRmsNorm 之后再起一个 Cast 算子的搬入搬出开销。

**主要应用场景**：
- Transformer 的残差分支：`hidden = x1 + x2` 后立即做 RMSNorm
- 需要同时保留高精度归一化结果（FP32）与低精度回写结果（FP16/BF16）的混合精度推理
- 需要把未归一化的残差和 `x = x1 + x2` 继续向后传递的残差连接

**算子特征**：
- 难度等级：L2（Normalization）
- 三输入四输出，沿 gamma 覆盖的末尾若干维做归约，其余维度为独立的归一化行
- 同一份输入同时产出 FP32 与低精度两路归一化结果，两路结果之间存在确定的舍入关系

## 2. 算子定义

### 数学公式

设 `x1`、`x2` 的 shape 相同，`gamma` 的 shape 等于 `x1` 末尾的 `r` 维（`r = rank(gamma)`），则对每个非归约位置上的行向量：

$$
x_i = float(x1_i) + float(x2_i)
$$

$$
\operatorname{Rms}(\mathbf{x}) = \sqrt{\frac{1}{n} \sum_{i=1}^{n} x_i^2 + \epsilon}, \quad n = \prod_{d=0}^{r-1} \operatorname{shape}(\gamma)[d]
$$

$$
rstd = \frac{1}{\operatorname{Rms}(\mathbf{x})}
$$

$$
y1_i = x_i \cdot rstd \cdot gamma_i
$$

$$
y2_i = cast(y1_i, \text{输入 dtype}), \qquad x^{out}_i = cast(x_i, \text{输入 dtype})
$$

其中 `n` 为归约维元素总数，`epsilon` 为属性值。所有乘加与归约在 FP32 中进行。

### 中间精度规则（需求决策）

`y1` 是 FP32 输出，`y2` 是它的低精度版本。两者之间的舍入关系必须唯一确定，否则同一份需求无法同时约束不同后端：

- **y1 不做中间低精度舍入**：`y1 = FP32(x) * FP32(rstd) * FP32(gamma)`，即 `y1` 保留全精度结果，不允许先把 `x * rstd` 舍入到输入 dtype 再乘 `gamma`。
- **y2 = cast(y1)**：`y2` 由 `y1` 一次性舍入得到，`y2` 与 `y1` 的差值不超过输入 dtype 在该量级上的半个 ulp。
- **x 由 FP32 和一次性舍入**：`x = cast(FP32(x1) + FP32(x2))`。

> 说明：该规则是需求决策，不是从任何单一后端逐行反推的结果。CANN 现有实现中，有的路径先把 `x * rstd` 舍入到输入 dtype 后再乘 `gamma`，并把 `y1` 写成 `y2` 的 FP32 提升值。本需求统一按上式定义 `y1`，并把由此产生的偏差交给第 4 节的精度阈值吸收（`y1` 按输入 dtype 的阈值判定，见 4.2）。依据与影响见 `design.md`。

### 特殊情况

| 条件 | 结果 |
|------|------|
| `rank(gamma) == rank(x1)` | 整张量归约为 1 个 rstd，`rstd` 的 shape 为全 1 |
| `gamma` 为 1 维 | 每个「行」独立归约，`rstd` 的 shape 为 `x1.shape[:-1] + [1]` |
| `gamma` 为多维 | 归约覆盖 `gamma` 对应的末尾多维，`rstd` 对应位置全部为 1 |
| `x1` 输入含 Inf | 对应位置的 `x`、`y1`、`y2` 为 Inf 或 NaN（取决于是否与 0 相乘） |
| `x1` 输入含 NaN | 含 NaN 的归约行，其 `rstd` 以及该行的 `y1`/`y2` 为 NaN |
| `epsilon = 0` | 公式退化为 `rstd = 1 / sqrt(mean(x^2))`，仅在全零行上结果为 Inf |

## 3. 接口规范

### 算子原型

```python
cann_bench.add_rms_norm_cast(Tensor x1, Tensor x2, Tensor gamma, float epsilon=1e-06) -> (Tensor y1, Tensor y2, Tensor rstd, Tensor x)
```

### 输入参数说明

| 参数 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| x1 | Tensor | 必选 | 第一个加数，ND 布局，1~8 维，dtype 为 float16/bfloat16 |
| x2 | Tensor | 必选 | 第二个加数，shape 与 dtype 必须与 `x1` 完全一致 |
| gamma | Tensor | 必选 | RmsNorm 缩放因子，dtype 与 `x1` 一致，shape 必须与 `x1` 末尾 `rank(gamma)` 维逐维相等，`rank(gamma) <= rank(x1)` |
| epsilon | float | 1e-6 | 加到均方值上的补偿项，要求 `epsilon >= 0` |

### 输出

| 参数 | Shape | dtype | 描述 |
|------|-------|-------|------|
| y1 | 与 `x1` 相同 | float32 | 归一化结果 `x * rstd * gamma`，未舍入到输入精度 |
| y2 | 与 `x1` 相同 | 与 `x1` 相同 | `y1` 舍入到输入 dtype 的结果 |
| rstd | 前 `rank(x1) - rank(gamma)` 维与 `x1` 相同，后 `rank(gamma)` 维全为 1 | float32 | 均方根标准差的倒数 |
| x | 与 `x1` 相同 | 与 `x1` 相同 | 加法结果 `x1 + x2` 舍入到输入 dtype |

输出顺序固定为 `(y1, y2, rstd, x)`，与上面的函数原型返回签名一致。

### 数据类型

| x1 / x2 / gamma dtype | y1 dtype | y2 dtype | rstd dtype | x dtype |
|-----------------------|----------|----------|------------|---------|
| float16 | float32 | float16 | float32 | float16 |
| bfloat16 | float32 | bfloat16 | float32 | bfloat16 |

`x1`、`x2`、`gamma` 三者 dtype 必须相同；不支持 FP32 输入。

### 规则与约束

- **shape 关系**：`x2` 的 shape 必须与 `x1` 逐维相等；`gamma` 的 shape 必须等于 `x1` 末尾 `rank(gamma)` 维；`rank(gamma)` 不得大于 `rank(x1)`。
- **rstd shape 推导**：取 `rank(x1)` 维，前 `rank(x1) - rank(gamma)` 维照抄 `x1`，后 `rank(gamma)` 维置 1。例如 `x1=(2,3,4,8)`、`gamma=(8)` 时 `rstd=(2,3,4,1)`；`gamma=(4,8)` 时 `rstd=(2,3,1,1)`。
- **非空输入（需求决策）**：`x1`、`x2`、`gamma` 的每个维度都必须 ≥ 1。空张量与「归约维元素数为 0 而其余维非空」的空归约场景不在本需求的语义与测试范围内：这类输入在不同代际产品上的可观察行为不一致（部分产品不支持，部分产品仅在 `rstd` 上给出 NaN），无法用同一份需求统一约束，故一律从支持域中排除。
- **epsilon 有效域（需求决策）**：`epsilon >= 0`。`epsilon < 0` 会让 `mean(x^2) + epsilon` 可能为负，`rstd` 失去定义，不属于支持域。`epsilon` 取 0 是有效输入。
- **y1 与 y2 的关系**：`y2` 必须等于 `y1` 舍入到输入 dtype 的结果，不允许两路各自独立计算后再各自舍入。
- **y1 的精度口径（需求决策）**：`y1` 虽然以 float32 承载，但其数值精度按输入 dtype 的阈值判定，见 4.2。原因是现有后端存在把 `y1` 写成 `y2` 的 FP32 提升值的实现，若要求 `y1` 达到 float32 阈值，则该类实现必然判为不通过。
- **NaN/Inf 传播**：输入含 Inf 或 NaN 时按 IEEE-754 语义传播，不做特殊屏蔽。
- **布局**：所有输入输出均为 ND 连续布局。

### 支持范围

| 维度 / 参数 | 范围 | 备注 |
|---|---|---|
| `x1` / `x2` 维度数 | 1 ~ 8 | 与本需求测试集的 2 ~ 8 维一致；逐行归一化对维度数不敏感 |
| `gamma` 维度数 | 1 ~ 8 | 不得超过 `rank(x1)` |
| 各维大小 | 1 ~ 2147483647 | 单维上限为 INT32 最大值 |
| 归约维元素数 `n` | 1 ~ 2147483647 | `n = prod(gamma.shape)`；`n` 为 0 不在支持域内 |
| 非归约行数 `m` | 1 ~ 2147483647 | `m = prod(x1.shape[:-rank(gamma)])`；`m` 为 0 不在支持域内 |
| `epsilon` | 0 ~ 1.0 | 默认 1e-6；测试集实测 1e-6 / 1e-5 / 1e-3 |

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

### 4.1 各输出的判定 dtype

| 输出 | 判定依据的 dtype | 说明 |
|------|------------------|------|
| `y1` | 输入 dtype（FP16 → 2^-10，BF16 → 2^-7） | 见 4.2 的精度口径说明 |
| `y2` | 输入 dtype | 本身就是舍入到输入精度的结果 |
| `rstd` | FLOAT32 → 2^-13 | 全精度归约结果，按 FP32 阈值判定 |
| `x` | 输入 dtype | 两输入之和舍入到输入精度，与 golden 的舍入点一致 |

### 4.2 中间舍入偏差的处理（需求决策）

第 2 节的中间精度规则要求 `y1` 全精度计算，而现有部分后端会先把 `x * rstd` 舍入到输入 dtype 再乘 `gamma`。该差异使 `y1` 的相对误差上界为「一次输入 dtype 舍入（相对误差 ≤ 2^-11 for FP16 / 2^-8 for BF16）叠加一次乘法舍入」。因此：

- `y1` 的通过阈值取**输入 dtype 的阈值**（FP16 2^-10、BF16 2^-7）而非 FLOAT32 的 2^-13。按此口径，上述偏差落在阈值内，不同后端可以在同一份需求下判定。
- 若某后端完全按第 2 节的规则全精度计算 `y1`，其误差远小于该阈值，同样判定通过。
- `rstd` 与 `x` 不受该偏差影响：`rstd` 与 golden 使用同一条 FP32 归约链路；`x` 两侧的舍入点相同，理论上逐位一致，若出现偏差应从实现缺陷角度排查而非放宽阈值。

## 5. 标准 Golden 代码

```python
import torch

"""
AddRmsNormCast算子Torch Golden参考实现

计算 Add + RmsNorm + Cast 的融合结果，全流程在 FP32 中完成
- x   = float(x1) + float(x2)
- rstd = 1 / sqrt(mean(x^2, 归约维) + epsilon)
- y1  = x * rstd * gamma      （FP32 输出，不做中间低精度舍入）
- y2  = cast(y1) 到输入 dtype
- x   归约为输入 dtype 的 x1 + x2
"""

from typing import List, Optional


def _reduce_keepdim(
    x_fp32: torch.Tensor, gamma_rank: int, gamma_numel: int
) -> torch.Tensor:
    """把末尾 gamma_rank 维展平后求均方，保留 gamma 各维为 1 的归约形状"""
    outer_shape = x_fp32.shape[: x_fp32.dim() - gamma_rank]
    # 外部维度含 0 时不能用 -1 推断归约长度，显式给出展平宽度
    if 0 in outer_shape:
        flat = x_fp32.reshape((*outer_shape, 0))
    else:
        flat = x_fp32.reshape((*outer_shape, gamma_numel))
    return flat.pow(2).mean(-1, keepdim=True).reshape((*outer_shape, *([1] * gamma_rank)))


def add_rms_norm_cast(
    x1: torch.Tensor,
    x2: torch.Tensor,
    gamma: torch.Tensor,
    epsilon: float = 1e-6,
) -> List[torch.Tensor]:
    """
    计算 Add + RmsNorm + Cast 融合结果

    Args:
        x1: 第一个加数，dtype 为 float16/bfloat16
        x2: 第二个加数，shape 与 dtype 与 x1 一致
        gamma: RmsNorm 缩放因子，shape 与 x1 末尾若干维一致
        epsilon: 分母数值稳定补偿项，默认 1e-6，要求非负

    Returns:
        [y1, y2, rstd, x]，其中 y1/rstd 为 float32，y2/x 与输入 dtype 一致
    """
    # 统一提升到 FP32 计算，输入 dtype 只用于最终输出舍入
    x_fp32 = x1.to(torch.float32) + x2.to(torch.float32)
    gamma_fp32 = gamma.to(torch.float32)

    # 归约维由 gamma 覆盖的末尾各维决定
    gamma_rank = gamma.dim()
    gamma_numel = gamma.numel()
    x_reduce = _reduce_keepdim(x_fp32, gamma_rank, gamma_numel)
    rstd = torch.rsqrt(x_reduce + epsilon)

    # 先乘 rstd 再乘 gamma，避免 x * gamma 提前溢出
    y1 = x_fp32 * rstd * gamma_fp32

    input_dtype = x1.dtype
    y2 = y1.to(input_dtype)
    x = x_fp32.to(input_dtype)
    return [y1, y2, rstd, x]
```

## 6. 额外信息

### 算子调用示例

```python
import torch
import torch_npu
import cann_bench

# x1 / x2 为同一 shape、同一 dtype（float16 或 bfloat16）
x1 = torch.randn(64, 2, 7168, dtype=torch.float16, device="npu")
x2 = torch.randn(64, 2, 7168, dtype=torch.float16, device="npu")
# gamma 覆盖末尾 1 维，因此每行 7168 个元素独立归一化
gamma = torch.randn(7168, dtype=torch.float16, device="npu")

y1, y2, rstd, x = cann_bench.add_rms_norm_cast(x1, x2, gamma, epsilon=1e-6)
# y1: float32, shape (64, 2, 7168)
# y2: float16, shape (64, 2, 7168)
# rstd: float32, shape (64, 2, 1)
# x: float16, shape (64, 2, 7168)
```

### 输出组织

- 四个输出一一对应第二节的公式，顺序固定为 `y1, y2, rstd, x`。
- 需要高精度归一化结果做后续 FP32 计算时用 `y1`；需要低精度回写时用 `y2`，两者满足 `y2 == cast(y1)`。
- `rstd` 保留了归约维上的长度为 1 的轴，可以直接与 `x` 广播相乘。
- `x` 是未归一化的残差和，用于残差连接的下一跳。

### 典型 shape 组合

| `x1` shape | `gamma` shape | `rstd` shape | 说明 |
|---|---|---|---|
| `(64, 2, 7168)` | `(7168)` | `(64, 2, 1)` | 大模型残差分支的典型形态 |
| `(4015, 9, 13)` | `(9, 13)` | `(4015, 1, 1)` | gamma 多维，归约覆盖末尾 2 维 |
| `(4, 10, 7, 10, 14, 13)` | `(14, 13)` | `(4, 10, 7, 10, 1, 1)` | 6 维输入，归约维在最后 |
| `(16, 16)` | `(16, 16)` | `(1, 1)` | `rank(gamma) == rank(x1)`，整张量归一化 |
