# HardSwish 算子 API 描述

## 1. 算子简介

HardSwish 是 Swish（SiLU）激活函数的分段线性近似，用 ReLU6 替代 sigmoid，
去掉了指数运算，在移动端与量化推理场景下显著更快，精度损失可忽略。
由 MobileNetV3 提出并广泛用于轻量级视觉骨干网络。

**主要应用场景**：
- MobileNetV3 / EfficientNet-Lite 等轻量级 CNN 骨干的激活层
- 移动端与边缘侧量化推理（分段线性对量化友好）
- 需要替换 Swish/SiLU 以降低计算开销的推理优化场景

**算子特征**：
- 难度等级：L1（Elementwise）
- 单输入单输出，逐元素运算，输出 shape 与输入完全一致
- 无属性参数，三段分段线性，分段点在 x = -3 与 x = 3

## 2. 算子定义

### 数学公式

$$
y = x \cdot \frac{\text{ReLU6}(x + 3)}{6}
= \begin{cases}
0, & x \leq -3 \\
x \cdot \dfrac{x + 3}{6}, & -3 < x < 3 \\
x, & x \geq 3
\end{cases}
$$

### 特殊情况

| 输入 | 输出 | 说明 |
|------|------|------|
| x ≤ -3 | y = 0 | 左侧完全截断 |
| x = 0 | y = 0 | 过原点 |
| x ≥ 3 | y = x | 右侧退化为恒等映射 |
| x = -1.5 | y = -0.375 | 全局最小值点 |
| x → +∞ | y → +∞ | 右侧无界（与 Softsign 不同） |
| x = NaN | y = NaN | NaN 传播 |

## 3. 接口规范

### 算子原型

```python
torch.ops.npu.hardswish(Tensor x) -> Tensor y
```

### 输入参数说明

| 参数 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| x | Tensor | 必选 | 输入张量，支持 0~8 维 |

### 输出

| 参数 | Shape | dtype | 描述 |
|------|-------|-------|------|
| y | 与输入 x 相同 | 与输入 x 相同 | HardSwish 激活结果 |

### 数据类型

| 输入 dtype | 输出 dtype |
|-----------|-----------|
| float16 | float16 |
| float32 | float32 |
| bfloat16 | bfloat16 |

### 规则与约束

- 输出 shape 与输入 shape 完全一致，输出 dtype 与输入 dtype 一致
- 本算子无属性参数
- **分段点 x = -3 与 x = 3 必须精确处理**：两侧表达式在分段点处连续
  （x=-3 时两侧均为 0，x=3 时两侧均为 3），kernel 的比较需用 `<=` / `>=`
  与公式保持一致，否则边界元素会产生偏差
- 中间段 `x * (x + 3) / 6` 在 float16 下先乘后除会损失精度，
  建议以 float32 计算后降型（golden 即如此实现）
- 输入支持 0~8 维

### 支持范围

输入 tensor 各维度与参数的支持范围：

| 维度 / 参数 | 范围 | 备注 |
|---|---|---|
| `x` 维度数 | 0 ~ 8 | cases.csv 实测 1D ~ 5D；接口规范支持 0 ~ 8 维 |
| `x` 各维大小 | 1 ~ 1048576 | cases.csv 各维实测 2 ~ 1000003（含 1D 张量长度 1000003） |
| `x` 元素总数 | 1 ~ 64M | cases.csv 实测 ~0.95M ~ 64M |
| `x` dtype | float16 / float32 / bfloat16 | cases.csv 三种 dtype 均覆盖 |

约束：cases 专门布置了分段点邻域用例（case 7 `[-3.5, -2.5]`、case 8 `[2.5, 3.5]`、
case 2 `[-3, 3]`、case 18 `[-3.0, 3.0]`），用于验证两个分段点的边界处理。

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


## 5. 标准 Golden 代码

```python
import torch

"""
HardSwish算子Torch Golden参考实现

HardSwish 激活函数，Swish 的分段线性近似
公式: y = x * ReLU6(x + 3) / 6
"""
def hardswish(
    x: torch.Tensor
) -> torch.Tensor:
    """
    HardSwish 激活函数

    公式: y = x * ReLU6(x + 3) / 6
      - x <= -3      : y = 0
      - x >= 3       : y = x
      - -3 < x < 3   : y = x * (x + 3) / 6

    Args:
        x: 输入张量

    Returns:
        输出张量，HardSwish 激活结果
    """
    input_dtype = x.dtype

    # FP16/BF16 输入升到 FP32 计算：分段点附近 (x+3)/6 的舍入在低精度下误差放大
    compute_dtype = torch.float32 if input_dtype in (torch.float16, torch.bfloat16) else input_dtype
    x_compute = x.to(compute_dtype)

    y = torch.nn.functional.hardswish(x_compute)

    if input_dtype in (torch.float16, torch.bfloat16):
        return y.to(input_dtype)
    return y
```

## 6. 额外信息

### 算子调用示例

```python
import torch
import torch_npu

# MobileNetV3 激活层
x = torch.randn(1, 64, 112, 112, dtype=torch.float16).npu()
y = torch.ops.npu.hardswish(x)

x = torch.randn(1024, 1024, dtype=torch.float32).npu()
y = torch.ops.npu.hardswish(x)

torch.npu.synchronize()
```


### 相关算子

| 算子 | 关系 |
|---|---|
| `swish` / `silu` | HardSwish 是其分段线性近似，`silu(x) = x * sigmoid(x)` |
| `hardsigmoid` | `hardswish(x) = x * hardsigmoid(x)`，两者共用 ReLU6(x+3)/6 |
| `relu6` | HardSwish 的构成部件 |
