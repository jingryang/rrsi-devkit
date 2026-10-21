# Abs 算子 API 描述

## 1. 算子简介

Abs 算子逐元素计算输入张量的绝对值，是最基础的一元逐元素算子之一，同时支持浮点与整型数据。

**主要应用场景**：
- L1 范数（曼哈顿距离）与绝对误差的计算
- 梯度裁剪、异常值检测中的幅值提取
- 信号处理中的包络与幅度谱计算
- 损失函数（如 L1 Loss、Smooth L1 Loss）的中间步骤

**算子特征**：
- 难度等级：L1（Elementwise）
- 单输入单输出，逐元素运算，输出 shape 与输入完全一致
- 支持 0~8 维输入，同时支持浮点与有符号整型

## 2. 算子定义

### 数学公式

$$
y_i = |x_i| = \begin{cases} x_i, & x_i \geq 0 \\ -x_i, & x_i < 0 \end{cases}
$$

### 特殊情况

| 输入 | 输出 |
|------|------|
| x = +0.0 / -0.0 | y = +0.0 |
| x = +∞ / -∞ | y = +∞ |
| x = NaN | y = NaN（保持 NaN，仅清除符号位） |
| x = INT_MIN（如 int8 的 -128） | 溢出，结果未定义；cases 中整型值域取 ±(2^(n-1)-1) 规避 |

## 3. 接口规范

### 算子原型

```python
torch.ops.npu.abs(Tensor x) -> Tensor y
```

### 输入参数说明

| 参数 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| x | Tensor | 必选 | 输入张量，支持 0~8 维 |

### 输出

| 参数 | Shape | dtype | 描述 |
|------|-------|-------|------|
| y | 与输入 x 相同 | 与输入 x 相同 | 输入的逐元素绝对值 |

### 数据类型

| 输入 dtype | 输出 dtype |
|-----------|-----------|
| float16 | float16 |
| float32 | float32 |
| bfloat16 | bfloat16 |
| int8 | int8 |
| int32 | int32 |
| int64 | int64 |

### 规则与约束

- 输出 shape 与输入 shape 完全一致，输出 dtype 与输入 dtype 一致
- 本算子无属性参数
- 浮点输入下 `|x|` 仅清除符号位，不引入舍入误差，为保精度映射
- 有符号整型输入取到该类型最小值（INT_MIN）时结果溢出，属未定义行为；
  cases 的整型值域按 ±(2^(n-1)-1) 取值以规避
- 输入支持 0~8 维

### 支持范围

输入 tensor 各维度与参数的支持范围：

| 维度 / 参数 | 范围 | 备注 |
|---|---|---|
| `x` 维度数 | 0 ~ 8 | cases.csv 实测 1D ~ 5D；接口规范支持 0 ~ 8 维 |
| `x` 各维大小 | 1 ~ 1048576 | cases.csv 各维实测 2 ~ 1000003（含 1D 张量长度 1000003） |
| `x` 元素总数 | 1 ~ 64M | cases.csv 实测 ~0.95M ~ 64M |
| `x` dtype | float16 / float32 / bfloat16 / int8 / int32 / int64 | cases.csv 六种 dtype 均覆盖 |

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

- 浮点输入（float16 / bfloat16 / float32）按下表使用 MERE/MARE 判定
- 整型输入（int8 / int32 / int64）按逐元素精确相等判定，等价于 threshold = 0，不走 MERE/MARE

| 数据类型 | FLOAT16 | BFLOAT16 | FLOAT32 |
|----------|---------|----------|---------|
| **通过阈值(Threshold)** | 2^-10 | 2^-7 | 2^-13 |

当平均相对误差 MERE < Threshold，最大相对误差 MARE < 10 * Threshold 时判定为通过。


## 5. 标准 Golden 代码

```python
import torch

"""
Abs算子Torch Golden参考实现

逐元素计算输入张量的绝对值
公式: y = |x|
"""
def abs(
    x: torch.Tensor
) -> torch.Tensor:
    """
    逐元素计算输入张量的绝对值

    公式: y = |x|

    Args:
        x: 输入张量

    Returns:
        输出张量，输入的逐元素绝对值，dtype 与输入一致
    """

    y = torch.abs(x)
    return y
```

## 6. 额外信息

### 算子调用示例

```python
import torch
import torch_npu

# 浮点绝对值：输入需先搬到 NPU
x = torch.randn(1024, 1024, dtype=torch.float32).npu()
y = torch.ops.npu.abs(x)

# 整型绝对值（避开 INT_MIN）
x = torch.randint(-127, 128, (512, 512), dtype=torch.int32).npu()
y = torch.ops.npu.abs(x)

# 与 CPU golden 比对
torch.npu.synchronize()
assert torch.equal(y.cpu(), torch.abs(x.cpu()))
```
