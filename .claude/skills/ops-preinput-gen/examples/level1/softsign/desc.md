# Softsign 算子 API 描述

## 1. 算子简介

Softsign 是一种平滑的饱和型激活函数，将任意实数输入压缩到 (-1, 1) 区间。与 tanh 相比，
它以多项式速率（而非指数速率）趋近饱和，梯度衰减更慢，且不含指数运算、计算开销更低。

**主要应用场景**：
- 循环神经网络（RNN/LSTM）中作为 tanh 的低成本替代
- 需要有界输出的回归任务输出层
- 强化学习中连续动作空间的动作压缩
- 对指数运算开销敏感的边缘侧推理场景

**算子特征**：
- 难度等级：L1（Elementwise）
- 单输入单输出，逐元素运算，输出 shape 与输入完全一致
- 无属性参数，支持 0~8 维输入

## 2. 算子定义

### 数学公式

$$
y = \frac{x}{1 + |x|}
$$

### 特殊情况

| 输入 | 输出 | 说明 |
|------|------|------|
| x = 0 | y = 0 | 过原点，且导数为 1 |
| x → +∞ | y → 1 | 有界，但**不可达** |
| x → -∞ | y → -1 | 有界，但**不可达** |
| x = ±inf | y = **NaN** | 分子分母同为 inf，∞/∞ 未定式 |
| x = NaN | y = NaN | NaN 传播 |

> 注意：`x = ±inf` 的输出是 **NaN 而非 ±1**（实测 `torch.nn.functional.softsign`
> 在 ±inf 上返回 nan）。这与「函数极限为 ±1」的数学直觉不同，是 IEEE 754
> ∞/∞ 的必然结果。cases 中 inf 用例据此判定。

## 3. 接口规范

### 算子原型

```python
torch.ops.npu.softsign(Tensor x) -> Tensor y
```

### 输入参数说明

| 参数 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| x | Tensor | 必选 | 输入张量，支持 0~8 维 |

### 输出

| 参数 | Shape | dtype | 描述 |
|------|-------|-------|------|
| y | 与输入 x 相同 | 与输入 x 相同 | Softsign 激活结果，取值落在 (-1, 1) |

### 数据类型

| 输入 dtype | 输出 dtype |
|-----------|-----------|
| float16 | float16 |
| float32 | float32 |
| bfloat16 | bfloat16 |

### 规则与约束

- 输出 shape 与输入 shape 完全一致，输出 dtype 与输入 dtype 一致
- 本算子无属性参数
- 输出恒落在开区间 (-1, 1)，端点不可达
- 分母 `1 + |x|` 在 float16 下当 `|x| > 65504` 时会饱和为 inf，
  建议 kernel 内部以 float32 累加后再降型（golden 即如此实现）
- 输入支持 0~8 维

### 支持范围

输入 tensor 各维度与参数的支持范围：

| 维度 / 参数 | 范围 | 备注 |
|---|---|---|
| `x` 维度数 | 0 ~ 8 | cases.csv 实测 1D ~ 5D；接口规范支持 0 ~ 8 维 |
| `x` 各维大小 | 1 ~ 1048576 | cases.csv 各维实测 2 ~ 1000003（含 1D 张量长度 1000003） |
| `x` 元素总数 | 1 ~ 64M | cases.csv 实测 ~0.95M ~ 64M |
| `x` dtype | float16 / float32 / bfloat16 | cases.csv 三种 dtype 均覆盖 |

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
Softsign算子Torch Golden参考实现

Softsign 激活函数，将输入平滑压缩到 (-1, 1) 区间
公式: y = x / (1 + |x|)
"""
def softsign(
    x: torch.Tensor
) -> torch.Tensor:
    """
    Softsign 激活函数

    公式: y = x / (1 + |x|)

    Args:
        x: 输入张量

    Returns:
        输出张量，Softsign 激活结果，取值落在 (-1, 1)
    """
    input_dtype = x.dtype

    # FP16/BF16 输入升到 FP32 计算：分母 1 + |x| 在大值域下于低精度会溢出饱和
    compute_dtype = torch.float32 if input_dtype in (torch.float16, torch.bfloat16) else input_dtype
    x_compute = x.to(compute_dtype)

    y = torch.nn.functional.softsign(x_compute)

    if input_dtype in (torch.float16, torch.bfloat16):
        return y.to(input_dtype)
    return y
```

## 6. 额外信息

### 算子调用示例

```python
import torch
import torch_npu

x = torch.randn(1024, 1024, dtype=torch.float32).npu()
y = torch.ops.npu.softsign(x)          # 输出落在 (-1, 1)

x = torch.randn(2, 8, 256, 256, dtype=torch.float16).npu()
y = torch.ops.npu.softsign(x)

torch.npu.synchronize()
```

