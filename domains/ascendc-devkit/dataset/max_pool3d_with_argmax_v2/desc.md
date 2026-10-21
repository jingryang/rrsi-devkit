# MaxPool3DWithArgmaxV2 算子 API 描述

## 1. 算子简介

MaxPool3DWithArgmaxV2 在输入张量的深度（D）、高度（H）、宽度（W）三个方向做滑动窗口最大池化，
并同时输出每个窗口最大值的位置。位置以「该值在所属通道内的展平偏移」表示，即
`d_in * H_in * W_in + h_in * W_in + w_in`，因此与 batch、channel 位置以及内存排布无关。

**主要应用场景**：

- 三维卷积网络中的下采样与池化位置记录（反池化、上采样需要 argmax 索引）
- 视频、点云体素、医学影像等时空特征的最大值定位
- 目标检测 / 分割模型中的特征显著性与位置回溯

**算子特征**：

- 难度等级：L2（Pooling）
- 单输入双输出：池化值 `y` 与索引 `argmax`，两者 shape 完全一致
- 支持 5 维 (N, C, D, H, W) / (N, D, H, W, C) 与 4 维 (C, D, H, W) 输入
- 支持 `float16`、`bfloat16`、`float32` 输入，索引支持 `int32` 与 `int64`
- 支持任意窗口大小、步长、零填充、窗口内间隔（dilation）与向上取整模式

## 2. 算子定义

### 数学公式

设输入为 `x(N, C, D_in, H_in, W_in)`，输出为 `y(N, C, D_out, H_out, W_out)`，窗口
`kernelSize = (kD, kH, kW)`、步长 `stride = (sD, sH, sW)`、填充 `padding = (pD, pH, pW)`、
间隔 `dilation = (dD, dH, dW)`。

输出形状（`ceilMode=False`，向下取整）：

$$
D_{out} = \left\lfloor \frac{D_{in} + 2 \cdot pD - dD \cdot (kD - 1) - 1}{sD} \right\rfloor + 1
$$

$$
H_{out} = \left\lfloor \frac{H_{in} + 2 \cdot pH - dH \cdot (kH - 1) - 1}{sH} \right\rfloor + 1
$$

$$
W_{out} = \left\lfloor \frac{W_{in} + 2 \cdot pW - dW \cdot (kW - 1) - 1}{sW} \right\rfloor + 1
$$

当 `ceilMode=True` 时把上述除法改为向上取整，并做一次修正：若
`(D_out - 1) * sD >= D_in + pD` 则 `D_out` 减 1，H、W 同理。

窗口内取值与最大值：

$$
y(n, c, d, h, w) = \max_{\substack{0 \le kd < kD,\\ 0 \le kh < kH,\\ 0 \le kw < kW}}
x(n, c,\ d \cdot sD - pD + kd \cdot dD,\ h \cdot sH - pH + kh \cdot dH,\ w \cdot sW - pW + kw \cdot dW)
$$

其中越界的采样点不参与比较（等价于取 $-\infty$）。设取得最大值的采样点为
$(d_i, h_i, w_i)$，则索引输出为：

$$
argmax(n, c, d, h, w) = d_i \cdot H_{in} \cdot W_{in} + h_i \cdot W_{in} + w_i
$$

### 特殊情况

| 条件 | 行为 |
|------|------|
| `stride` 为空列表 | 步长取 `kernelSize` 的值（`sD=kD, sH=kH, sW=kW`） |
| `stride` / `padding` / `dilation` 长度为 1 | 三个方向取同一个值 |
| `dilation` 缺省（不传） | 等价于 `(1, 1, 1)` |
| `kernelSize = (1,1,1)` 且 `stride = (1,1,1)` | 输出与输入逐元素相同，索引为其自身的通道内展平偏移 |
| 窗口的一部分越界 | 越界位置按 $-\infty$ 参与比较，不会成为最大值；输出 shape 仍按公式推导 |
| `ceilMode=True` 且最后一个窗口完全落在右侧补零区域 | 该窗口被丢弃，输出 shape 相应减 1 |
| 窗口内出现多个相同的最大值 | 取扫描顺序上的第一个（`d`、`h`、`w` 由小到大）；由于扫描忽略越界点，越界点永不中选 |
| `data_format="NDHWC"` | 输入、输出的通道轴位于最后一维，索引语义不变（仍为通道内展平偏移） |
| 输入为 4 维 | 视为 (C, D, H, W)，batch 按 1 处理，输出同为 4 维 |

## 3. 接口规范

### 算子原型

```python
cann_bench.max_pool3d_with_argmax_v2(Tensor x, int[] kernelSize, int[] stride, int[] padding,
                                     int[] dilation=None, bool ceilMode=False, str data_format="NCDHW",
                                     int indices_dtype=3) -> (Tensor y, Tensor argmax)
```

### 输入参数说明

| 参数 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| x | Tensor | 必选 | 输入张量，5 维 (N, C, D, H, W) / (N, D, H, W, C) 或 4 维 (C, D, H, W) |
| kernelSize | int 列表 | 必选 | 池化窗口，长度 1 或 3，元素均大于 0 |
| stride | int 列表 | 必选 | 池化步长，长度 0、1 或 3；长度 0 时取 `kernelSize` |
| padding | int 列表 | 必选 | 三个方向两侧各补的层数，长度 1 或 3，元素在 `[0, kernelSize/2]` |
| dilation | int 列表 | `[1, 1, 1]` | 窗口内元素的间隔，长度 1 或 3，元素均大于 0 |
| ceilMode | bool | `False` | 输出形状是否向上取整 |
| data_format | str | `"NCDHW"` | 数据排布，取值 `NCDHW` 或 `NDHWC`；传入其他值（如 `ND`）按 `NCDHW` 解释 |
| indices_dtype | int | `3` | 索引输出类型：3 表示 int32，9 表示 int64 |

### 输出

| 参数 | Shape | dtype | 描述 |
|------|-------|-------|------|
| y | 与输入同秩；N、C 不变，D/H/W 由公式推导 | 与输入一致 | 每个窗口的最大值 |
| argmax | 与 `y` 完全一致 | int32 或 int64（由 `indices_dtype` 决定） | 最大值在通道内 D*H*W 空间的展平偏移 |

### 数据类型

| 输入 dtype | y dtype | argmax dtype |
|-----------|---------|--------------|
| float16 | float16 | int32 / int64 |
| bfloat16 | bfloat16 | int32 / int64 |
| float32 | float32 | int32 / int64 |

`float16` / `bfloat16` 输入在比较时按 `float32` 处理，输出再转回原 dtype。

### 规则与约束

- 输入必须是 4 维或 5 维，5 维按 `data_format` 解释为 (N, C, D, H, W) 或 (N, D, H, W, C)，4 维按 (C, D, H, W) 解释。
- 4 维输入请按 `ND`（或 `NCHW`）排布声明；把 4 维张量按 `NCDHW` 排布声明会被算子内部拒绝。
- `kernelSize` 长度只能是 1 或 3，元素必须大于 0。
- `stride` 长度只能是 0、1 或 3，元素必须大于 0。
- `padding` 长度只能是 1 或 3，元素必须非负且不超过对应方向 `kernelSize/2`。
- `dilation` 长度只能是 1 或 3，元素必须大于 0。
- 输出 `y` 的 dtype 必须与输入一致；`argmax` 只能是 int32 或 int64，两者 shape 必须一致。
- 输出 D/H/W 三个方向都必须大于等于 1，否则视为非法输入。
- 当输入通道内元素数 `D_in * H_in * W_in` 超过 int32 表示范围时，`argmax` 必须使用 int64。
- 相同最大值并列时取扫描顺序上的第一个；越界补零位置不参与比较。

### 支持范围

本次只描述 Ascend 950PR&950DT（A5）范围内的行为：

| 维度 / 参数 | 范围 | 备注 |
|---|---|---|
| `x` 维度数 | 4 或 5 | 4 维视为 (C, D, H, W)，batch = 1 |
| `data_format` | `NCDHW`、`NDHWC` | 4 维输入按 (C, D, H, W) 解释 |
| `x` dtype | float16、bfloat16、float32 | 无整型输入 |
| `argmax` dtype | int32、int64 | int64 在通道内元素数超过 int32 时可表达 |
| `kernelSize` | 长度 1 或 3，元素 > 0 | 无上界，但需保证输出非空 |
| `stride` | 长度 0、1 或 3，元素 > 0 | 长度 0 时等于 kernelSize |
| `padding` | 长度 1 或 3，元素 ∈ [0, kernelSize/2] | 三个方向分别判定 |
| `dilation` | 长度 1 或 3，元素 ≥ 1 | 缺省为 (1, 1, 1) |
| `ceilMode` | True / False | 默认 False |
| 非连续输入 | 支持 | 输入可以是带步长的视图 |

## 4. 精度要求

采用[生态算子精度标准](https://gitcode.com/cann/opbase/blob/master/docs/zh/ops_precision_standard/experimental_standard.md)进行验证。

**误差指标**：

1. 平均相对误差（MERE）：采样点中相对误差的平均值

   $$
   \text{MERE} = \text{avg}\left(\frac{\text{abs}(actual - golden)}{\text{abs}(golden)+1\text{e-}7}\right)
   $$

2. 最大相对误差（MARE）：采样点中相对误差的最大值

   $$
   \text{MARE} = \max\left(\frac{\text{abs}(actual - golden)}{\text{abs}(golden)+1\text{e-}7}\right)
   $$

**通过标准**：

| 数据类型 | FLOAT16 | BFLOAT16 | FLOAT32 |
|----------|---------|----------|---------|
| **通过阈值(Threshold)** | 2^-10 | 2^-7 | 2^-13 |

`y` 按上述阈值判定：MERE < Threshold 且 MARE < 10 x Threshold。
`argmax` 为索引输出，要求与 golden **逐元素完全一致**（不做容差判定）。

## 5. 标准 Golden 代码

```python
from typing import List, Optional

import torch
import torch.nn.functional as F


def _expand3(value: List[int]) -> List[int]:
    """Expand a length-1 window parameter to (D, H, W); a length-3 list is kept as is."""
    if len(value) == 1:
        return [value[0], value[0], value[0]]
    return [value[0], value[1], value[2]]


def max_pool3d_with_argmax_v2(
    x: torch.Tensor,
    kernelSize: List[int],
    stride: List[int],
    padding: List[int],
    dilation: Optional[List[int]] = None,
    ceilMode: bool = False,
    data_format: str = "NCDHW",
    indices_dtype: int = 3,
) -> List[torch.Tensor]:
    """3D max pooling that also returns the position of every maximum.

    For each output element the window of shape kernelSize = (kD, kH, kW) anchored at
    (d * sD - pD, h * sH - pH, w * sW - pW) is scanned with step (dD, dH, dW); positions that fall
    outside the input are ignored (treated as negative infinity). The reported index is the offset of
    the selected element inside its own channel, i.e. d_in * H_in * W_in + h_in * W_in + w_in, so it is
    independent of the batch and channel position.

    Args:
        x: input tensor, 5-dimensional (N, C, D, H, W) or 4-dimensional (C, D, H, W).
        kernelSize: pooling window, either a single value (kD = kH = kW) or (kD, kH, kW).
        stride: pooling step, either an empty list (equals kernelSize), a single value
            (sD = sH = sW) or (sD, sH, sW).
        padding: padding layers added on both sides of the D, H and W axes, either a single value
            (pD = pH = pW) or (pD, pH, pW); each value is at most half of the matching kernelSize value.
        dilation: spacing between the elements of one window, either a single value
            (dD = dH = dW) or (dD, dH, dW); None means (1, 1, 1).
        ceilMode: when True the output shape is rounded up instead of down, and a window that starts
            entirely inside the trailing padding is dropped.
        data_format: "NCDHW" for a channel-first tensor or "NDHWC" for a channel-last tensor.
        indices_dtype: type code of the index output, 3 for int32 and 9 for int64.

    Returns:
        [y, argmax]: the pooled values (same dtype as x) and the flattened indices, both shaped
        (N, C, D_out, H_out, W_out) for NCDHW and (N, D_out, H_out, W_out, C) for NDHWC; the batch
        axis is dropped for a 4-dimensional input.
    """
    input_dtype = x.dtype
    if input_dtype in (torch.float16, torch.bfloat16):
        compute_x = x.to(torch.float32)
    else:
        compute_x = x

    is_ndhwc = str(data_format).upper() == "NDHWC"

    # The channel axis is the last one for NDHWC: compute on the NCDHW view, restore afterwards.
    if is_ndhwc:
        compute_x = compute_x.permute(0, 4, 1, 2, 3)

    # A 4-dimensional input is (C, D, H, W) with an implicit batch of 1.
    squeeze = compute_x.dim() == 4
    if squeeze:
        compute_x = compute_x.unsqueeze(0)

    k_dhw = _expand3(list(kernelSize))
    s_dhw = _expand3(list(stride)) if len(stride) != 0 else list(k_dhw)
    p_dhw = _expand3(list(padding))
    d_dhw = _expand3(list(dilation)) if dilation is not None and len(dilation) != 0 else [1, 1, 1]

    y, argmax = F.max_pool3d(
        compute_x,
        kernel_size=k_dhw,
        stride=s_dhw,
        padding=p_dhw,
        dilation=d_dhw,
        ceil_mode=ceilMode,
        return_indices=True,
    )

    y = y.to(input_dtype)
    argmax = argmax.to(torch.int32 if indices_dtype == 3 else torch.int64)

    if squeeze:
        y = y.squeeze(0)
        argmax = argmax.squeeze(0)

    if is_ndhwc:
        y = y.permute(0, 2, 3, 4, 1)
        argmax = argmax.permute(0, 2, 3, 4, 1)

    return [y, argmax]
```

## 6. 额外信息

### 算子调用示例

```python
import torch
import cann_bench

x = torch.randn(2, 4, 8, 16, 16, dtype=torch.float32)
y, argmax = cann_bench.max_pool3d_with_argmax_v2(
    x,
    kernelSize=[2, 2, 2],
    stride=[2, 2, 2],
    padding=[0, 0, 0],
    dilation=[1, 1, 1],
    ceilMode=False,
    data_format="NCDHW",
    indices_dtype=3,
)
print(y.shape, y.dtype)        # torch.Size([2, 4, 4, 8, 8]) torch.float32
print(argmax.shape, argmax.dtype)  # torch.Size([2, 4, 4, 8, 8]) torch.int32
```

### 用例执行与数据构造约定

- `generator`：`uniform` 表示在 `value_range` 给出的有限区间 `[lo, hi]` 上均匀采样；不允许对无穷区间采样。
- `seed`：固定等于 `case_id`，保证每个用例可复现。
- `view`：`contiguous` 表示直接构造连续张量；`noncontiguous_input` 表示把逻辑值写入末维加倍的底层存储后
  以 `[..., ::2]` 视图作为输入，golden 按逻辑张量计算。
- `layout`：`NCDHW` 表示 (N, C, D, H, W)；`NDHWC` 表示 (N, D, H, W, C)。用例数据按该排布构造并解释。
- `expected`：只记录 `y` 与 `argmax` 的 shape、dtype 与 layout；期望数值一律由第 5 节 golden 计算，不得手工填写。
- 特殊值：本算子的用例只使用有限均匀分布；并列最大值在连续分布下概率为零，因此索引结果唯一。
- 多输出：`y` 按浮点阈值判定，`argmax` 要求逐元素完全一致。
