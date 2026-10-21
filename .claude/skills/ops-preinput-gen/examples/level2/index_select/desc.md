# IndexSelect 算子 API 描述

## 1. 算子简介

IndexSelect 沿指定维度按索引张量取出若干切片并拼接为新张量。与 `gather` 不同，
它的索引是**一维**的、作用在**单一维度**上，其余维度整片保留，属于典型的行/列选择操作。

**主要应用场景**：
- Embedding 查表：按 token id 从词表矩阵中取出对应词向量
- 推荐系统中按候选集下标抽取特征行
- 数据重排、batch 内采样与负采样
- MoE 路由中按专家分配下标抽取 token

**算子特征**：
- 难度等级：L2（IndexGather）
- 双输入单输出：被索引张量 `x` + 一维索引 `index`
- 输出 shape 与 `x` 相同，仅 `dim` 维大小变为索引长度 `L`
- 纯数据搬运，不含算术运算，理论上逐位精确

## 2. 算子定义

### 数学公式

设 `x` 的 shape 为 $(D_0, D_1, \dots, D_{r-1})$，`dim = d`，`index` 长度为 $L$，则：

$$
y[i_0, \dots, i_{d-1},\ j,\ i_{d+1}, \dots, i_{r-1}]
= x[i_0, \dots, i_{d-1},\ \text{index}[j],\ i_{d+1}, \dots, i_{r-1}]
$$

其中 $j \in [0, L)$，输出 shape 为 $(D_0, \dots, D_{d-1}, L, D_{d+1}, \dots, D_{r-1})$。

### 特殊情况

| 情况 | 行为 |
|------|------|
| `L = 1` | 输出在 `dim` 维退化为长度 1，维度数不变（不做 squeeze） |
| `L = D_d` 且 index 为 `[0,1,...,D_d-1]` | 输出与 `x` 完全相同（恒等变换） |
| index 中有重复值 | 合法，对应切片被复制多份 |
| `x` 含 inf / nan | 原样搬运，不做任何数值处理 |

## 3. 接口规范

### 算子原型

```python
torch.ops.npu.index_select(Tensor x, int dim, Tensor index) -> Tensor y
```

### 输入参数说明

| 参数 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| x | Tensor | 必选 | 被索引的输入张量，支持 1~8 维 |
| dim | int | 必选 | 沿哪一维取索引，取值范围 `-ndim ~ ndim-1` |
| index | Tensor | 必选 | **一维**索引张量，长度 `L`，元素取值范围 `[0, x.shape[dim]-1]` |

### 输出

| 参数 | Shape | dtype | 描述 |
|------|-------|-------|------|
| y | 与 `x` 相同，但 `dim` 维大小变为 `L` | 与 `x` 相同 | 按索引选取的结果 |

### 数据类型

| 输入 x dtype | 输入 index dtype | 输出 y dtype |
|-------------|-----------------|-------------|
| float16 | int32 / int64 | float16 |
| float32 | int32 / int64 | float32 |
| bfloat16 | int32 / int64 | bfloat16 |
| int32 | int32 / int64 | int32 |
| int64 | int32 / int64 | int64 |

> `index` 的 dtype 与 `x` 的 dtype **相互独立**：`index` 只能是 int32/int64，
> `x` 可为浮点或整型；输出 dtype 恒等于 `x` 的 dtype。

### 规则与约束

- **索引合法性**：`index` 的每个元素必须落在 `[0, x.shape[dim]-1]`，
  越界为未定义行为；本算子**不支持负数索引**（与 `dim` 参数不同）
- **index 必须是 1D**：高维索引请使用 `gather`
- **index 长度 `L` 与 `x.shape[dim]` 无需相等**：`L` 可大于、等于或小于 `x.shape[dim]`
  （大于时必然出现重复索引，合法）
- `dim` 支持负数索引，取值范围 `-ndim ~ ndim-1`
- 输出 shape 与 `x` 一致，仅 `dim` 维变为 `L`；输出 dtype 与 `x` 一致
- 纯数据搬运，无算术运算，NPU 实现应做到与 golden 逐位一致

### 支持范围

输入 tensor 各维度与参数的支持范围：

| 维度 / 参数 | 范围 | 备注 |
|---|---|---|
| `ndim`（`x` 维度数） | 1 ~ 8 | cases.csv 实测 1D / 2D / 3D / 4D / 5D |
| `D_i`（`x` 各维大小） | 1 ~ 2^20 | cases.csv 各维实测 2 ~ 1000003（含 1D 张量长度 1000003） |
| `numel(x)`（总元素数） | 1 ~ 64M | cases.csv 实测 ~0.95M ~ 64M |
| `L`（index 长度 / 输出 dim 维大小） | 1 ~ 2^20 | cases.csv 实测 1 ~ 4096；含 `L=1`（单索引）与 `L=D_d`（全维选取） |
| `dim` | -ndim ~ ndim-1 | cases.csv 实测 0 / 1 / 2 / 3 / 4；支持负数索引 |
| `index` 元素值 | 0 ~ `D_d - 1` | cases.csv 逐例取满 `[0, x.shape[dim]-1]`，20/20 例与 `dim` 维严格对应 |
| `x.dtype` | float16 / float32 / bfloat16 / int32 / int64 | cases.csv 五种均覆盖 |
| `index.dtype` | int32 / int64 | cases.csv 两种均覆盖，且与 `x.dtype` 正交组合 |

约束：`index` 必须为 1D，且每个元素满足 `0 ≤ index[j] ≤ x.shape[dim] - 1`
（**这是本算子唯一的跨输入约束，下游造数时必须按当前用例的 `x.shape[dim]` 动态确定索引上界，
不可写死**）；`dim` 必须落在 `[-ndim, ndim-1]`；输出 `y` 满足
`y.shape[i] == x.shape[i]`（`i ≠ dim`）且 `y.shape[dim] == L`。

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

> 本算子为纯数据搬运，不引入任何舍入误差，实际应达到**逐位精确**；
> 上述阈值为兜底标准。

## 5. 标准 Golden 代码

```python
import torch

"""
IndexSelect算子Torch Golden参考实现

沿指定维度按索引张量取出若干切片并拼接为新张量
公式: y[..., i, ...] = x[..., index[i], ...]
"""
def index_select(
    x: torch.Tensor, dim: int, index: torch.Tensor
) -> torch.Tensor:
    """
    沿指定维度按索引取切片

    公式: y[..., i, ...] = x[..., index[i], ...]

    Args:
        x: 被索引的输入张量
        dim: 沿哪一维取索引 (取值范围: -ndim ~ ndim-1)
        index: 索引张量，1D，元素取值范围 [0, x.shape[dim]-1]

    Returns:
        输出张量，与 x 同 shape，仅 dim 维大小变为 index 的长度 L
    """

    y = torch.index_select(x, dim, index)
    return y
```

## 6. 额外信息

### 算子调用示例

```python
import torch
import torch_npu

# Embedding 查表：从 10000 词表中取 512 个 token 的词向量
table = torch.randn(10000, 768, dtype=torch.float16).npu()
ids = torch.randint(0, 10000, (512,), dtype=torch.int32).npu()
y = torch.ops.npu.index_select(table, 0, ids)          # -> [512, 768]

# 沿最后一维选取特征子集
x = torch.randn(4, 255, 2049, dtype=torch.float32).npu()
idx = torch.randint(0, 2049, (1024,), dtype=torch.int64).npu()
y = torch.ops.npu.index_select(x, 2, idx)              # -> [4, 255, 1024]

torch.npu.synchronize()
```


### 相关算子

| 算子 | 关系 |
|---|---|
| `gather` | index 与 x 同维、逐元素给出下标；IndexSelect 的 index 是 1D、按整片选取 |
| `scatter` | IndexSelect 的逆操作（按索引写回） |
| `unsorted_segment_sum` | 同为索引类，但按段聚合而非选取 |
