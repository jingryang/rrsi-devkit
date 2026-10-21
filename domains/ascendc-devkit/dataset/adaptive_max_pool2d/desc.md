# AdaptiveMaxPool2d 算子 API 描述

## 1. 算子简介

AdaptiveMaxPool2d 是二维自适应最大池化算子。与固定窗口的最大池化不同，调用方只给出输出在 H、W 维上的大小 `output_size = [Hout, Wout]`，算子按输出位置反推每个窗口在输入中的范围，对窗口取最大值，同时输出最大值在对应 (N, C) 平面 H*W 内的一维偏移。语义与 PyTorch `torch.nn.AdaptiveMaxPool2d(return_indices=True)` 一致。

**主要应用场景**：

- 目标检测与图像分类网络中需要固定输出尺寸、但输入分辨率可变的空间金字塔池化（SPP）层
- 需要保留最大值位置的池化结构，例如后续需要按索引回填的上采样/反向流程
- 任意 H、W 输入到指定 [Hout, Wout] 输出的降采样或上采样

**算子特征**：

- 难度等级：L2（Pooling，双输出，自适应窗口）
- 单输入双输出：`y` 与输入同 dtype，`indices` 恒为 int64
- 单属性 `output_size`，无默认值，长度固定为 2
- 允许输出空间大于输入空间（窗口重叠、结果重复）

## 2. 算子定义

### 数学公式

记输入 `x` 的 shape 为 $[N, C, H_i, W_i]$（3 维输入按 $N=1$、shape 为 $[C, H_i, W_i]$），输出尺寸为 $[H_o, W_o]$。对每个输出位置 $(n, c, oh, ow)$：

$$
h_{start} = \left\lfloor \frac{oh \cdot H_i}{H_o} \right\rfloor, \qquad
h_{end} = \left\lceil \frac{(oh+1) \cdot H_i}{H_o} \right\rceil
$$

$$
w_{start} = \left\lfloor \frac{ow \cdot W_i}{W_o} \right\rfloor, \qquad
w_{end} = \left\lceil \frac{(ow+1) \cdot W_i}{W_o} \right\rceil
$$

$$
y[n, c, oh, ow] = \max_{h \in [h_{start}, h_{end}),\; w \in [w_{start}, w_{end})} x[n, c, h, w]
$$

$$
indices[n, c, oh, ow] = h \cdot W_i + w
$$

其中 $(h, w)$ 是取得最大值的输入位置。多个元素并列最大时，取行优先扫描顺序（先 $h$ 后 $w$）中的第一个；窗口内出现 NaN 时 $y$ 为 NaN，$indices$ 指向该窗口最后一个 NaN 的位置。

### 特殊情况

| 条件 | 结果 |
|---|---|
| $H_i \bmod H_o = 0$ 且 $W_i \bmod W_o = 0$ | 所有窗口等大且互不重叠，每个输入元素最多被一个输出选中 |
| 存在不整除的维 | 窗口大小随输出位置变化，相邻窗口可能重叠，同一输入元素可被多个输出选中 |
| $H_o > H_i$ 或 $W_o > W_i$ | 输出空间大于输入空间，窗口可仅覆盖少量元素且彼此重叠，索引出现重复 |
| $H_i = 1$ 或 $W_i = 1$ | 退化为沿单一空间维的一维自适应池化 |
| 窗口内存在并列最大值 | 取扫描顺序中的第一个位置 |
| 窗口内存在 NaN | $y$ 为 NaN，$indices$ 指向最后一个 NaN |
| 任一维为 0 或输入为空 Tensor | 不属于本需求的正常输入域 |
| `output_size` 长度不为 2 或含非正值 | 非法输入，由接口按自身状态码拒绝 |

## 3. 接口规范

### 算子原型

```python
cann_bench.adaptive_max_pool2d(Tensor x, int[] output_size) -> (Tensor y, Tensor indices)
```

### 输入参数说明

| 参数 | 类型 | 默认值 | 描述 |
|---|---|---|---|
| x | Tensor | 必选 | 待池化输入张量。4 维为 `[N, C, H, W]`，3 维为 `[C, H, W]`，逻辑布局为通道优先 |
| output_size | List[int] | 必选 | 输出在 H、W 维上的大小 `[Hout, Wout]`，长度必须为 2，且每个元素大于 0 |

### 输出

| 参数 | Shape | dtype | 描述 |
|---|---|---|---|
| y | `x` 的 shape 把后两维替换为 `[Hout, Wout]` | 与 `x` 相同 | 池化结果 |
| indices | 与 `y` 相同 | int64 | 每个输出元素在对应 (N, C) 平面 H*W 内的一维偏移，取值范围 `[0, Hi*Wi)` |

### 数据类型

| x | y | indices | 适用芯片 |
|---|---|---|---|
| float16 | float16 | int64 | A5 |
| float32 | float32 | int64 | A5 |
| bfloat16 | bfloat16 | int64 | A5 |

`y` 的 dtype 必须与 `x` 相同；`indices` 固定为 int64。

### 规则与约束

- `x` 的维度数必须为 3 或 4；4 维为 `[N, C, H, W]`，3 维为 `[C, H, W]`。
- `x` 的每一维都必须大于 0，不支持空 Tensor；单平面元素数 `Hi*Wi` 不大于 int32 最大值。
- `output_size` 的长度必须为 2，两个元素都必须大于 0；`Hout`、`Wout` 可以大于 `Hi`、`Wi`。
- `y` 与 `indices` 的 shape 相同，等于 `x` 的 shape 把后两维替换为 `[Hout, Wout]`。
- `indices` 是每个 (N, C) 平面内的一维偏移（`h*Wi + w`），不包含 N、C 维偏移。
- 并列最大值取扫描顺序中的第一个；窗口含 NaN 时输出 NaN 并指向最后一个 NaN。
- 输入按通道优先的逻辑布局解释；3 维输入按单 batch 处理，输出保持 3 维。
- 输入允许非连续视图，按逻辑元素值参与计算。
- 不支持的 dtype、维度数、空 Tensor、非法 `output_size` 属于非法输入，由接口按自身状态码报告，不在本需求的正常用例范围内。

### 支持范围

本需求面向 Ascend 950PR/950DT 系列及 3510（A5）。其他芯片（Atlas A3 系列、Atlas A2 系列及其他未列出的产品）不在本次范围内。支持范围是需求合同，不代表测试样本已覆盖全部合法输入。

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

**判定标准**：MERE < Threshold 且 MARE < 10 × Threshold。

| dtype | Threshold |
|---|---|
| float16 | 2^-10 |
| bfloat16 | 2^-7 |
| float32 | 2^-13 |

**多输出判定**：`y` 为浮点输出，按上表阈值判定；`indices` 为整数索引，必须与 Golden 逐元素完全相等，不做数值容差。由于最大值选择是精确拷贝，`y` 的每个元素应等于输入中的对应元素，正常情况下误差为 0。

## 5. 标准 Golden 代码

```python
import torch
from typing import List, Tuple


"""
AdaptiveMaxPool2d 算子 Torch Golden 参考实现

直接调用 torch 内置的自适应最大池化，语义与源码 ST 参考实现一致：
- 输出位置 (oh, ow) 对应输入窗口
  [floor(oh*Hi/Ho), ceil((oh+1)*Hi/Ho)) x [floor(ow*Wi/Wo), ceil((ow+1)*Wi/Wo))
- y 取窗口内最大值；indices 取该最大值在每个 (N,C) 平面 H*W 内的一维偏移
- 多个相等最大值时取扫描顺序（先行后列）中的第一个；窗口含 NaN 时 y 为 NaN

输入支持 3 维 [C, H, W] 与 4 维 [N, C, H, W]，输出保持相同维数。
必须先升 float32 再调用内置实现：PyTorch CPU 在原生 float16/bfloat16 上对非整除窗口
会返回越界索引（例如 127x129 -> 32x33 时返回 16384，超过 Hi*Wi-1=16382）；
升 float32 是无损且保序的，最大值的选取与并列关系不变。
y 最后转回输入 dtype，indices 恒为 int64。
"""


def adaptive_max_pool2d(
    x: torch.Tensor,
    output_size: List[int],
) -> Tuple[torch.Tensor, torch.Tensor]:
    """二维自适应最大池化标准 Golden。

    Args:
        x: 输入张量，3 维 [C, H, W] 或 4 维 [N, C, H, W]。
        output_size: 输出在 H、W 维上的大小 [Ho, Wo]，长度为 2 且每个元素大于 0。

    Returns:
        y: 池化结果，shape 为 x 的 shape 把后两维替换为 [Ho, Wo]，dtype 与 x 相同。
        indices: 每个输出元素在对应 (N, C) 平面 H*W 内的一维偏移，shape 与 y 相同，dtype 为 int64。
    """
    if x.dim() not in (3, 4):
        raise ValueError("x 必须为 3 维 [C, H, W] 或 4 维 [N, C, H, W]")
    if len(output_size) != 2:
        raise ValueError("output_size 必须是长度为 2 的列表")
    out_h, out_w = int(output_size[0]), int(output_size[1])
    if out_h <= 0 or out_w <= 0:
        raise ValueError("output_size 的每个元素都必须大于 0")
    if x.numel() == 0:
        raise ValueError("x 不支持空张量")

    # 升 float32 是无损且保序的：避免低精度内置实现返回越界索引，同时保持最大值与并列关系
    y, indices = torch.nn.functional.adaptive_max_pool2d(
        x.to(torch.float32), (out_h, out_w), return_indices=True
    )
    return y.to(x.dtype), indices.to(torch.int64)
```

## 6. 额外信息

### 算子调用示例

```python
import torch
import cann_bench

# 4 维输入 [N, C, H, W]
x = torch.randn(2, 3, 12, 16, dtype=torch.float32)
y, indices = cann_bench.adaptive_max_pool2d(x, [4, 5])
# y.shape == (2, 3, 4, 5), indices.shape == (2, 3, 4, 5), indices.dtype == torch.int64

# 3 维输入 [C, H, W]
x3 = torch.randn(8, 7, 9, dtype=torch.float16)
y3, idx3 = cann_bench.adaptive_max_pool2d(x3, [3, 4])
# y3.shape == (8, 3, 4), idx3.shape == (8, 3, 4)
```

