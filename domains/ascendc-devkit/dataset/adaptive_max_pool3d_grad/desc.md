# AdaptiveMaxPool3DGrad 算子 API 描述

## 1. 算子简介

AdaptiveMaxPool3DGrad 是三维自适应最大池化（`AdaptiveMaxPool3d`）的反向传播算子。正向算子对每个自适应窗口取最大值并记录该最大值在输入中的位置；反向算子把正向输出的梯度按这些位置“散射”回正向输入的空间，同一坐标被多个窗口选中时梯度相加。

**主要应用场景**：
- 三维卷积/池化网络（视频、体数据、医学影像）中 `AdaptiveMaxPool3d` 的反向传播
- 需要把池化输出梯度还原到原始分辨率的训练流程

**算子特征**：
- 难度等级：L2（Pooling，索引散射）
- 三输入单输出；输出 `y` 的 shape 与 dtype 与输入 `x` 完全一致
- `x` 只贡献 shape 与 dtype，其数值不参与计算

## 2. 算子定义

### 数学公式

记输入 `x` 的 shape 为 $[N, C, D, H, W]$，`grad` 与 `argmax` 的 shape 为 $[N, C, D_o, H_o, W_o]$（即正向输出的 shape），输出 `y` 与 `x` 同 shape、同 dtype。

先把 `y` 全部置零，再对每个 $(n, c, l, m, k)$ 执行：

$$
y[n, c,\ o] \mathrel{+}= grad[n, c, l, m, k]
$$

其中 $o$ 是由 `argmax` 给出的 $(D, H, W)$ 平面内一维偏移：

$$
o = argmax[n, c, l, m, k], \qquad 0 \le o < D \cdot H \cdot W
$$

即 `argmax` 以每个 $(N, C)$ 平面为单位、在 $D \cdot H \cdot W$ 个位置上编号，而不是全局编号。所有 `grad` 元素恰好被使用一次；当多个 $(l, m, k)$ 指向同一 $o$ 时，对应梯度累加。

### 特殊情况

| 条件 | 结果 |
|---|---|
| 正向窗口互不重叠（各空间维均整除） | 每个 `argmax` 互不相同，`y` 的每个非零位置最多来自一个 `grad` 元素 |
| 正向窗口存在重叠 | 同一输入坐标可能被多个窗口选中，`grad` 在其上累加 |
| 输出空间大于输入空间（$D_o > D$ 等） | 正向窗口可小于 1 个元素的步长，`argmax` 大量重复，`y` 的少数坐标累积多个梯度 |
| 空间维为 1（$D=H=W=1$） | 平面大小为 1，`argmax` 恒为 0，所有梯度累加到同一坐标 |
| 某 `(N, C)` 平面没有任何 `grad` 元素 | 该平面 `y` 保持全 0 |
| 4 维输入 CDHW | 按 $N=1$ 处理，输出同样为 4 维 |
| `grad` 或 `argmax` 的 N、C 与 `x` 不一致、或 `argmax` 越界 | 属于非法输入，不在本需求正常用例范围内 |

## 3. 接口规范

### 算子原型

```python
cann_bench.adaptive_max_pool3d_grad(Tensor x, Tensor grad, Tensor argmax) -> Tensor y
```

### 输入参数说明

| 参数 | 类型 | 默认值 | 描述 |
|---|---|---|---|
| x | Tensor | 必选 | 正向输入张量，4 维 CDHW 或 5 维 NCDHW。只使用其 shape 与 dtype |
| grad | Tensor | 必选 | 正向输出对应的梯度，shape 与 `argmax` 相同，dtype 与 `x` 相同 |
| argmax | Tensor | 必选 | 正向 argmax 索引，shape 与 `grad` 相同，dtype 为 int32 或 int64；每个 (N, C) 平面内的一维偏移，取值 [0, D*H*W) |

### 输出

| 参数 | Shape | dtype | 描述 |
|---|---|---|---|
| y | 与 `x` 相同 | 与 `x` 相同 | 梯度回填结果 |

### 数据类型

| x | grad | argmax | y | 适用芯片 |
|---|---|---|---|---|
| float16 | float16 | int32 / int64 | float16 | A5 |
| float32 | float32 | int32 / int64 | float32 | A5 |
| bfloat16 | bfloat16 | int32 / int64 | bfloat16 | A5 |

`x`、`grad`、`y` 必须为同一 dtype；`argmax` 可为 int32 或 int64，两者语义相同，只是索引的表示宽度不同。

### 规则与约束

- `x` 与 `y` 必须为 4 维（CDHW）或 5 维（NCDHW）；4 维输入按 $N=1$ 处理，输出保持 4 维。
- `grad` 与 `argmax` 的维度数与 `x` 相同；两者的 N、C 必须与 `x` 一致，空间维为正向输出尺寸，须大于 0。
- `x` 的每一维都必须大于 0；不支持空 Tensor。`grad`、`argmax` 同样不允许空 Tensor。
- `grad` 与 `argmax` 的 shape 必须完全一致；`x` 与 `grad` 的 N、C 必须一致。
- `argmax` 的每个元素都必须落在 $[0, D \cdot H \cdot W)$ 内。
- 数据格式为 ND；输入允许非连续视图，按逻辑元素值参与计算。
- 不支持的 dtype、维度数、shape 关系与越界索引属于非法输入，由接口按自身状态码报告。
- 单平面元素数 $D \cdot H \cdot W$ 必须可由 `argmax` 的 dtype 表示；本需求不额外施加比接口更严格的规模上限。
- 输出缓冲在设备侧要求连续，或由适配层负责转换；这不改变外部可观察的数值与 shape。

需求决策：

- **D1**：`argmax` 的编号基准为每个 $(N, C)$ 平面内的 $D \cdot H \cdot W$ 一维偏移。该规则同时由正向算子的索引定义、算子实现的坐标计算方式与在图框架中的索引语义确认；影响是 Golden 以 `scatter_add_` 在平面上累加，而不是在整张量上累加。
- **D2**：4 维输入按 $N=1$ 处理，输出保持 4 维。接口对 4 维与 5 维输入都给出支持，4 维被理解为去掉 batch 维的 CDHW；影响是 Golden 统一按“平面数 = N*C、平面大小 = D*H*W”组织计算，并对 4 维输入返回 4 维结果。
- **D3**：`argmax` 允许 int32 与 int64 两种 dtype。本需求面向 A5，接口在该芯片上同时接受两者；影响是用例需覆盖两种索引 dtype。
- **D4**：`x` 的数值不参与计算，只提供 shape 与 dtype。正向 argmax 已由正向算子给出，反向不需要重新比较 `x` 的数值；影响是 Golden 只读取 `x` 的 shape/dtype，用例的 `x` 数值用于推导向量索引本身。
- **D5**：非重叠窗口下同一坐标不会重复累加，重叠窗口下会累加；这由 `argmax` 的取值决定，不由 shape 单独决定。影响是 Golden 必须使用“累加”语义而非“赋值”语义。

### 支持范围

本需求面向 Ascend 950PR/950DT 系列（A5）。其他芯片（Atlas A3 系列、Atlas A2 系列及其他未列出的产品）不在本次范围内。支持范围是需求合同，不代表测试样本已覆盖全部合法输入。

## 4. 精度要求

采用生态算子精度标准验证。

**误差指标**：

1. 平均相对误差（MERE）：采样点中相对误差的平均值

   $$
   \text{MERE} = \text{avg}\left(\frac{\text{abs}(actual - golden)}{\text{abs}(golden) + 1e-7}\right)
   $$

2. 最大相对误差（MARE）：采样点中相对误差的最大值

   $$
   \text{MARE} = \max\left(\frac{\text{abs}(actual - golden)}{\text{abs}(golden) + 1e-7}\right)
   $$

**通过标准**：当 MERE < Threshold 且 MARE < 10 × Threshold 时判定为通过。

| 数据类型 | FLOAT16 | BFLOAT16 | FLOAT32 |
|---|---|---|---|
| Threshold | 2^-10 | 2^-7 | 2^-13 |

`y` 按 `x` 的 dtype 选择阈值；单输出，无需区分多输出阈值。累加顺序不同带来的浮点舍入是唯一误差来源，金标准计算顺序不构成硬件实现必须复现的约束。NaN、Inf 不参与相对误差统计：期望为 NaN 的位置要求实际同样为 NaN，期望为 ±Inf 的位置要求实际为同符号 Inf。

## 5. 标准 Golden 代码

```python
import torch


def adaptive_max_pool3d_grad(
    x: torch.Tensor,
    grad: torch.Tensor,
    argmax: torch.Tensor,
) -> torch.Tensor:
    """AdaptiveMaxPool3DGrad 标准 Golden（CPU）。

    正向自适应最大池化的反向传播：输出先置零，再把每个正向输出位置上的梯度
    累加回该位置 argmax 所指的输入坐标。

    Args:
        x: 正向输入张量，4 维 CDHW 或 5 维 NCDHW，dtype 为 float16/float32/bfloat16。
        grad: 正向输出对应的梯度，shape 与 argmax 相同，dtype 与 x 相同。
        argmax: 正向 argmax 索引，dtype 为 int32 或 int64；每个 (N, C) 平面内的
            一维偏移，取值范围 [0, D*H*W)。

    Returns:
        y: 梯度回填结果，shape 与 x 相同，dtype 与 x 相同。
    """
    if x.dim() not in (4, 5):
        raise ValueError("x 必须为 4 维 CDHW 或 5 维 NCDHW")
    if grad.dim() != x.dim() or argmax.dim() != x.dim():
        raise ValueError("x、grad、argmax 的维度数必须一致")
    if tuple(grad.shape) != tuple(argmax.shape):
        raise ValueError("grad 与 argmax 的 shape 必须一致")
    if tuple(x.shape[:-3]) != tuple(grad.shape[:-3]):
        raise ValueError("x 与 grad 的 N、C 维必须一致")
    if grad.dtype != x.dtype:
        raise ValueError("grad 的 dtype 必须与 x 一致")
    if argmax.dtype not in (torch.int32, torch.int64):
        raise ValueError("argmax 的 dtype 必须为 int32 或 int64")

    plane = 1
    for dim in x.shape[-3:]:
        plane *= int(dim)
    planes = int(x.numel()) // plane
    if int(argmax.numel()) > 0:
        if bool(torch.any(argmax < 0)) or bool(torch.any(argmax >= plane)):
            raise ValueError("argmax 的每个元素必须落在 [0, D*H*W) 内")

    compute_dtype = torch.float32 if x.dtype in (torch.float16, torch.bfloat16) else x.dtype
    if planes == 0:
        return torch.zeros(tuple(x.shape), dtype=x.dtype, device=x.device)

    grad_flat = grad.reshape(planes, -1).to(compute_dtype)
    index_flat = argmax.reshape(planes, -1).to(torch.int64)

    y_flat = torch.zeros((planes, plane), dtype=compute_dtype, device=x.device)
    y_flat.scatter_add_(1, index_flat, grad_flat)
    return y_flat.reshape(tuple(x.shape)).to(x.dtype)
```

## 6. 额外信息

### 算子调用示例

```python
import torch
import cann_bench

x = torch.randn(2, 3, 4, 8, 8, dtype=torch.float32)
grad = torch.randn(2, 3, 2, 4, 4, dtype=torch.float32)
# 每个 (N, C) 平面内、在 D*H*W=256 个位置上的 argmax
argmax = torch.randint(0, 4 * 8 * 8, (2, 3, 2, 4, 4), dtype=torch.int32)

y = cann_bench.adaptive_max_pool3d_grad(x, grad, argmax)
print(y.shape, y.dtype)  # torch.Size([2, 3, 4, 8, 8]) torch.float32
```

### 用例执行与数据构造约定

- 用例的 `input_shape` 顺序固定为 `[x, grad, argmax]`，`grad` 与 `argmax` 的 shape 必须完全一致。
- `value_range` 顺序与之一致：`x`、`grad` 为有限区间 `[lo, hi]`；`argmax` 为索引取值范围 `[0, D*H*W-1]`。
- 索引来源：`argmax` 取正向自适应最大池化在 `x` 上的 argmax 结果（按 `grad` 的 shape 作为输出尺寸），保证索引与 `x` 的窗口划分自洽，并自然产生重叠窗口下的重复索引。用例 note 的 `index_source` 记录这一约定。
- `generator=uniform`：以 `seed = case_id` 在给定区间上均匀采样，再转目标 dtype；`generator=mixed`：`value_range` 给出显式值列表，按物理行优先循环填充后再转目标 dtype，其余输入仍按区间均匀生成。
- `view=noncontiguous_input`：按末维加倍的底层存储构造合法非连续视图作为 `x`，Golden 按逻辑张量计算；`view=contiguous` 表示连续张量。
- `expected` 只记录输出 `y` 的 shape、dtype 与布局；具体数值必须由本节的 Golden 计算，不得手工填写。
- 每个用例的 `seed` 固定为 `case_id`，保证数据可复现；不允许对无穷区间采样。
- 用例只覆盖合法输入域内的正常功能：不存在非法 dtype/shape、越界索引或预期报错用例。
- `chips` 固定为 `["A5"]`。
