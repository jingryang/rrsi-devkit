# Baddbmm 算子 API 描述

## 1. 算子简介

Baddbmm（batch add batch matrix multiply）对两个批量三维张量做批量矩阵乘，
再与第三个张量做加权相加，是 Transformer 注意力与批量线性层中最常见的融合形态之一。
相比「先 bmm 再 add」，融合成单算子可省掉一次中间张量的读写。

**主要应用场景**：
- Transformer 注意力打分：`scores = beta * mask + alpha * (Q @ K^T)`
- 批量全连接层的 batched GEMM + bias 累加
- 图神经网络中批量邻接矩阵传播
- 需要带缩放系数的残差累加场景

**算子特征**：
- 难度等级：L3（Contraction）
- 三输入单输出，含两个标量缩放属性 `beta` / `alpha`
- 输入全部为 3D，四个符号维度 `B` / `N` / `M` / `P` 在三个输入间共享
- contraction 维为 `M`，低精度下累加误差随 `M` 增大而放大

## 2. 算子定义

### 数学公式

$$
y = \beta \cdot \text{input} + \alpha \cdot (\text{batch1} \mathbin{@} \text{batch2})
$$

逐 batch 展开（$b \in [0, B)$）：

$$
y[b] = \beta \cdot \text{input}[b] + \alpha \cdot \sum_{k=0}^{M-1}
\text{batch1}[b, :, k] \cdot \text{batch2}[b, k, :]
$$

### Shape 变量说明

| 符号 | 含义 | 出现位置 |
|---|---|---|
| `B` | batch 大小 | `input[0]`、`batch1[0]`、`batch2[0]` |
| `N` | 输出行数 | `input[1]`、`batch1[1]` |
| `M` | contraction（收缩）维 | `batch1[2]`、`batch2[1]` |
| `P` | 输出列数 | `input[2]`、`batch2[2]` |

即：`input: [B, N, P]`，`batch1: [B, N, M]`，`batch2: [B, M, P]`，`y: [B, N, P]`。

### 特殊情况

| 条件 | 行为 |
|------|------|
| `beta = 0` | 退化为纯批量矩阵乘 `y = alpha * (batch1 @ batch2)`，`input` 不参与数值 |
| `alpha = 0` | 退化为 `y = beta * input` |
| `M = 1` | 秩 1 外积累加 |
| `N = P = 1` | 每个 batch 退化为向量内积 |
| `input` 含 inf / nan | 按 IEEE 754 传播到输出对应位置 |

## 3. 接口规范

### 算子原型

```python
torch.ops.npu.baddbmm(Tensor input, Tensor batch1, Tensor batch2, float beta=1.0, float alpha=1.0) -> Tensor y
```

### 输入参数说明

| 参数 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| input | Tensor | 必选 | 被累加的张量，shape `[B, N, P]` |
| batch1 | Tensor | 必选 | 批量矩阵乘左操作数，shape `[B, N, M]` |
| batch2 | Tensor | 必选 | 批量矩阵乘右操作数，shape `[B, M, P]` |
| beta | float | 1.0 | `input` 的缩放系数 |
| alpha | float | 1.0 | 批量矩阵乘结果的缩放系数 |

### 输出

| 参数 | Shape | dtype | 描述 |
|------|-------|-------|------|
| y | `[B, N, P]` | 与输入相同 | 加权累加结果 |

### 数据类型

| 输入 (input, batch1, batch2) dtype | 输出 dtype |
|-----------------------------------|-----------|
| float16 | float16 |
| float32 | float32 |
| bfloat16 | bfloat16 |

三个输入的 dtype 必须一致，输出 dtype 与之相同。

### 规则与约束

- **三输入必须全为 3D**，不支持广播到不同维度数
- **`B` 一致性**：`input.shape[0] == batch1.shape[0] == batch2.shape[0]`
- **`N` 一致性**：`input.shape[1] == batch1.shape[1]`
- **`M` 一致性**（contraction 维）：`batch1.shape[2] == batch2.shape[1]`
- **`P` 一致性**：`input.shape[2] == batch2.shape[2]`
- `input`、`batch1`、`batch2` 的 dtype 必须一致
- `beta` / `alpha` 为标量浮点，允许取 0（此时对应项不参与数值）
- **精度**：contraction 维 `M` 上的累加在 fp16/bf16 下误差随 `M` 增大而放大，
  NPU 实现应以 fp32 累加后再降型（golden 即如此）

### 支持范围

输入 tensor 各维度与参数的支持范围：

| 维度 / 参数 | 范围 | 备注 |
|---|---|---|
| `B`（batch） | 1 ~ 1024 | cases.csv 实测 1 ~ 64；含 `B=1` 退化情形 |
| `N`（输出行数） | 1 ~ 4096 | cases.csv 实测 1 ~ 1024；含 `N=1` |
| `M`（contraction 维） | 1 ~ 4096 | cases.csv 实测 1 ~ 512；含 `M=1`（秩 1 外积） |
| `P`（输出列数） | 1 ~ 4096 | cases.csv 实测 1 ~ 512；含 `P=1` |
| `numel` 单例总元素数 | 1 ~ 64M | cases.csv 实测 ~0.001M ~ 3.25M（三输入之和） |
| `beta` | -1024.0 ~ 1024.0 | cases.csv 实测 0.0 / 0.5 / 1.0 / 2.0；`beta=0` 时退化为纯 bmm |
| `alpha` | -1024.0 ~ 1024.0 | cases.csv 实测 0.5 / 1.0 / 2.0 |
| dtype | float16 / float32 / bfloat16 | cases.csv 三种均覆盖，三输入 dtype 恒一致 |

约束：四个符号维度在三个输入间共享，必须同时满足
`input[0]==batch1[0]==batch2[0]`（B）、`input[1]==batch1[1]`（N）、
`batch1[2]==batch2[1]`（M，contraction 维）、`input[2]==batch2[2]`（P）；
输出 `y.shape == input.shape == [B, N, P]`。
**下游造数时必须按上述四条关系联动生成三个输入的 shape，任一条不满足都会直接报错。**
cases 中 17/20 例刻意让 `N`、`M`、`P` 互不相等，以覆盖真实的非方阵形态。

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

> contraction 维 `M` 越大，低精度累加误差越大。若 fp16 用例出现 MERE 超阈，
> 应优先检查 kernel 是否以 fp32 累加（而非直接用 fp16 累加器）。

## 5. 标准 Golden 代码

```python
import torch

"""
Baddbmm算子Torch Golden参考实现

批量矩阵乘加
公式: y = beta * input + alpha * (batch1 @ batch2)
"""
def baddbmm(
    input: torch.Tensor, batch1: torch.Tensor, batch2: torch.Tensor,
    beta: float = 1.0, alpha: float = 1.0
) -> torch.Tensor:
    """
    批量矩阵乘加

    公式: y = beta * input + alpha * (batch1 @ batch2)

    Args:
        input: 被累加的张量，shape [B, N, P]
        batch1: 批量矩阵乘左操作数，shape [B, N, M]
        batch2: 批量矩阵乘右操作数，shape [B, M, P]
        beta: input 的缩放系数
        alpha: 批量矩阵乘结果的缩放系数

    Returns:
        输出张量，shape [B, N, P]
    """
    input_dtype = input.dtype

    # FP16/BF16 升到 FP32 计算：contraction 维 M 上的累加在低精度会显著放大误差
    compute_dtype = torch.float32 if input_dtype in (torch.float16, torch.bfloat16) else input_dtype

    y = torch.baddbmm(
        input.to(compute_dtype), batch1.to(compute_dtype), batch2.to(compute_dtype),
        beta=beta, alpha=alpha,
    )

    if input_dtype in (torch.float16, torch.bfloat16):
        return y.to(input_dtype)
    return y
```

## 6. 额外信息

### 算子调用示例

```python
import torch
import torch_npu

# Transformer 注意力打分：scores = mask + (Q @ K^T) / sqrt(d)
B, N, M, P = 8, 128, 64, 128
mask = torch.zeros(B, N, P, dtype=torch.float16).npu()
q = torch.randn(B, N, M, dtype=torch.float16).npu()
k_t = torch.randn(B, M, P, dtype=torch.float16).npu()
scores = torch.ops.npu.baddbmm(mask, q, k_t, beta=1.0, alpha=1.0 / (M ** 0.5))

# beta=0：退化为纯批量矩阵乘
y = torch.ops.npu.baddbmm(mask, q, k_t, beta=0.0, alpha=1.0)

torch.npu.synchronize()
```


### 相关算子

| 算子 | 关系 |
|---|---|
| `bmm` | Baddbmm 在 `beta=0, alpha=1` 时的退化形式 |
| `addmm` | 二维版本（无 batch 维） |
| `quant_matmul` | 同为 Contraction 类，但带量化 scale/offset |
