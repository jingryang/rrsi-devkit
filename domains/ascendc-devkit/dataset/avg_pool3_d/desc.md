# AvgPool3D 算子 API 描述

## 1. 算子简介

AvgPool3D 在输入张量的深度（D）、高度（H）、宽度（W）三个方向做滑动窗口平均池化。每个输出元素是输入中以对应步长定位的 `kD * kH * kW` 窗口内元素的平均值，窗口可以带零填充，除数可由 `countIncludePad` 与 `divisorOverride` 控制。

**主要应用场景**：

- 三维卷积网络中的下采样
- 时空特征图（视频、点云体素、医学影像）的全局或局部平均
- 全局平均池化（`kernelSize` 取输入 D/H/W 三个维度）

**算子特征**：

- 难度等级：L2（Pooling）
- 单输入单输出，输出与输入同秩、同 dtype
- 支持 4 维（C, D, H, W）与 5 维（N, C, D, H, W）输入，数据格式为 ND

## 2. 算子定义

### 数学公式

输入 `input(N, C, D_in, H_in, W_in)`、输出 `out(N, C, D_out, H_out, W_out)`、窗口 `kernelSize(kD, kH, kW)`、步长 `stride(sD, sH, sW)`、补零 `padding(pD, pH, pW)`，输出形状为：

$$
D_{out} = \left\lfloor \frac{D_{in} + 2 \cdot pD - kD}{sD} \right\rfloor + 1
$$

$$
H_{out} = \left\lfloor \frac{H_{in} + 2 \cdot pH - kH}{sH} \right\rfloor + 1
$$

$$
W_{out} = \left\lfloor \frac{W_{in} + 2 \cdot pW - kW}{sW} \right\rfloor + 1
$$

当 `ceilMode` 为 True 时，先把分母上的减法换成 `+ sD - 1`（上取整），再对每个维度做一次修正：若 `(D_out - 1) * sD >= D_in + pD`，则 `D_out` 减 1；H、W 同理。

池化结果为：

$$
out(n, c, d, h, w) = \frac{1}{divisor}\sum_{kd=0}^{kD-1}\sum_{kh=0}^{kH-1}\sum_{kw=0}^{kW-1} input(n, c, d \cdot sD + kd, h \cdot sH + kh, w \cdot sW + kw)
$$

其中被求和的元素位于输入范围之外时按补零取 0。

### 特殊情况

| 条件 | 行为 |
|------|------|
| `divisorOverride` 非 0 | `divisor` 恒等于该值，与该窗口实际参与运算的元素个数无关 |
| `divisorOverride` 为 0 且 `countIncludePad=True` | `divisor` 为该窗口落在「输入 + 补零」范围内的元素个数 |
| `divisorOverride` 为 0 且 `countIncludePad=False` | `divisor` 为该窗口与输入真实范围的重叠元素个数，补零不计入 |
| `ceilMode=True` | 输出形状按上取整推导，并做上述减 1 修正 |
| `kernelSize` 取输入 D/H/W 三个维度且 `padding=0` | 退化为全局平均池化，输出 D/H/W 均为 1 |
| `kernelSize` 三个维度均为 1 | 输出形状与输入一致，结果按步长做等值/插值采样 |

## 3. 接口规范

### 算子原型

```python
cann_bench.avg_pool3_d(Tensor x, int[] kernelSize, int[] stride, int[] padding, bool ceilMode=False, bool countIncludePad=True, int divisorOverride=0) -> Tensor y
```

### 输入参数说明

| 参数 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| x | Tensor | 必选 | 输入张量，4 维 (C, D, H, W) 或 5 维 (N, C, D, H, W) |
| kernelSize | int 列表 | 必选 | 池化窗口，长度 1（kD=kH=kW）或 3（kD, kH, kW），取值 > 0 且不超过输入对应维度 |
| stride | int 列表 | 必选 | 池化步长，长度 0（与 kernelSize 相同）、1（sD=sH=sW）或 3（sD, sH, sW），取值 > 0 |
| padding | int 列表 | 必选 | D/H/W 方向补零层数，长度 1（pD=pH=pW）或 3（pD, pH, pW），取值在 [0, kernelSize/2] |
| ceilMode | bool | False | 输出形状是否向上取整 |
| countIncludePad | bool | True | 求平均时是否把补零计入除数 |
| divisorOverride | int | 0 | 固定除数；0 时不生效，除数由窗口自算 |

### 输出

| 参数 | Shape | dtype | 描述 |
|------|-------|-------|------|
| y | N、C 与输入一致，D/H/W 由公式推导 | 与输入一致 | 池化结果 |

### 数据类型

| 输入 dtype | 输出 dtype |
|-----------|-----------|
| float16 | float16 |
| float32 | float32 |
| bfloat16 | bfloat16 |

float16 / bfloat16 输入在内部按 float32 累加，最后转回原 dtype。

### 规则与约束

- 输入必须是 4 维或 5 维，输出与输入同秩，数据格式为 ND。
- `kernelSize` 每个维度的取值必须大于 0 且不超过输入对应维度的长度。
- `stride` 每个维度的取值必须大于 0；长度 0 时全部取 `kernelSize` 对应维度的值。
- `padding` 每个维度的取值在 `[0, kernelSize[d]/2]`，三个方向均只做尾部补零（前端由窗口起始位置自然产生）。
- 当某个维度的 `padding` 达到 `kernelSize / 2` 时，该方向最后一个窗口可能越过输入范围，越界部分按补零参与计算。
- 输出 D/H/W 必须非负；输出的 N、C 与输入保持一致。

### 支持范围

本次只描述 Ascend 950PR&950DT（A5）范围内的行为：

| 维度 / 参数 | 范围 | 备注 |
|---|---|---|
| `x` 维度数 | 4 或 5 | 5 维按 (N, C, D, H, W) 解释；4 维按 (C, D, H, W) 解释，batch 视为 1 |
| `x` 各维大小 | ≥ 1 | D/H/W 需满足输出形状非负 |
| `kernelSize` | 长度 1 或 3，取值 > 0 | 不超过输入对应维度 |
| `stride` | 长度 0、1 或 3，取值 > 0 | 长度 0 时等于 kernelSize |
| `padding` | 长度 1 或 3，取值 ∈ [0, kernelSize/2] | 三维同时满足 |
| `ceilMode` | True / False | 默认 False |
| `countIncludePad` | True / False | 默认 True |
| `divisorOverride` | 0 或正整数 | 默认 0（不生效） |

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

| 数据类型 | FLOAT16 | BFLOAT16 | FLOAT32 |
|----------|---------|----------|---------|
| **通过阈值(Threshold)** | 2^-10 | 2^-7 | 2^-13 |

当平均相对误差 MERE < Threshold，最大相对误差 MARE < 10 * Threshold 时判定为通过。本算子只有一个输出，按上述阈值整体判定。

## 5. 标准 Golden 代码

```python
import torch

from typing import List


def _pool_out_size(in_size: int, pad_front: int, pad_back: int, k: int, stride: int, ceil_mode: bool) -> int:
    """Output size of one spatial dimension of the 3D average pooling window."""
    if ceil_mode:
        out_size = (in_size + pad_front + pad_back - k + stride - 1) // stride + 1
        if (out_size - 1) * stride >= in_size + pad_front:
            out_size = out_size - 1
    else:
        out_size = (in_size + pad_front + pad_back - k) // stride + 1
    return out_size


def _expand3(value: List[int]) -> List[int]:
    """Expand a length-1 list into (D, H, W); keep a length-3 list unchanged."""
    if len(value) == 1:
        return [value[0], value[0], value[0]]
    return [value[0], value[1], value[2]]


def avg_pool3_d(
    x: torch.Tensor,
    kernelSize: List[int],
    stride: List[int],
    padding: List[int],
    ceilMode: bool = False,
    countIncludePad: bool = True,
    divisorOverride: int = 0,
) -> torch.Tensor:
    """Applies a 3D average pooling over an input tensor.

    The input is laid out as (N, C, D, H, W) when 5-dimensional, and as (C, D, H, W) when
    4-dimensional (an implicit batch of 1). For every output position (n, c, d, h, w) the
    window of shape kernelSize = (kD, kH, kW) starting at (d * sD, h * sH, w * sW) is
    averaged, where stride = (sD, sH, sW). Zero padding of `padding` layers is applied on
    the D, H and W dimensions.

    Args:
        x: 4-dimensional (C, D, H, W) or 5-dimensional (N, C, D, H, W) input tensor.
        kernelSize: the pooling window, either a single value (kD = kH = kW) or (kD, kH, kW).
        stride: the pooling step, either an empty list (equals kernelSize), a single value
            (sD = sH = sW) or (sD, sH, sW).
        padding: zero padding layers, either a single value (pD = pH = pW) or (pD, pH, pW).
        ceilMode: when True, ceil instead of floor is used to derive the output shape.
        countIncludePad: when True, the zero padding is included in the averaging divisor.
        divisorOverride: a fixed divisor; 0 means the divisor is derived from the window.

    Returns:
        The pooled tensor, with the same rank, dtype and element layout as the input.
    """
    input_dtype = x.dtype
    # fp16 / bf16 are accumulated in fp32 and cast back at the very end.
    if input_dtype in (torch.float16, torch.bfloat16):
        compute_dtype = torch.float32
    else:
        compute_dtype = input_dtype
    x_compute = x.to(compute_dtype)

    # A 4-dimensional input is a (C, D, H, W) tensor with an implicit batch of 1.
    squeeze = False
    if x_compute.dim() == 4:
        x_compute = x_compute.unsqueeze(0)
        squeeze = True

    k_dhw = _expand3(list(kernelSize))
    s_dhw = _expand3(list(stride)) if len(stride) != 0 else list(k_dhw)
    p_dhw = _expand3(list(padding))

    divisor = None if divisorOverride == 0 else int(divisorOverride)

    if all(p_dhw[i] < k_dhw[i] / 2 for i in range(3)):
        # The padding of every dimension stays below half of the kernel: the plain
        # pooling definition applies directly.
        out = torch.nn.functional.avg_pool3d(
            x_compute,
            k_dhw,
            stride=s_dhw,
            padding=p_dhw,
            ceil_mode=ceilMode,
            count_include_pad=countIncludePad,
            divisor_override=divisor,
        )
    else:
        # Some dimension pads half of its kernel or more, so the whole padding has to be
        # materialised in the buffer before pooling.
        in_d, in_h, in_w = x_compute.shape[2], x_compute.shape[3], x_compute.shape[4]

        out_d = _pool_out_size(in_d, p_dhw[0], p_dhw[0], k_dhw[0], s_dhw[0], ceilMode)
        out_h = _pool_out_size(in_h, p_dhw[1], p_dhw[1], k_dhw[1], s_dhw[1], ceilMode)
        out_w = _pool_out_size(in_w, p_dhw[2], p_dhw[2], k_dhw[2], s_dhw[2], ceilMode)

        # The outermost window may reach past the input, the extra rows/cols are zero.
        back_d = max((out_d - 1) * s_dhw[0] + k_dhw[0] - in_d - p_dhw[0], 0)
        back_h = max((out_h - 1) * s_dhw[1] + k_dhw[1] - in_h - p_dhw[1], 0)
        back_w = max((out_w - 1) * s_dhw[2] + k_dhw[2] - in_w - p_dhw[2], 0)
        x_padded = torch.nn.functional.pad(
            x_compute, (p_dhw[2], back_w, p_dhw[1], back_h, p_dhw[0], back_d), mode="constant", value=0
        )

        # A pure window sum: divisor_override=1 without padding makes the pooling return it.
        window_sum = torch.nn.functional.avg_pool3d(
            x_padded,
            k_dhw,
            stride=s_dhw,
            padding=0,
            ceil_mode=False,
            count_include_pad=False,
            divisor_override=1,
        )[..., :out_d, :out_h, :out_w]

        if divisor is not None:
            out = window_sum / divisor
        else:
            idx = torch.arange(out_d * out_h * out_w)
            d_idx = idx // (out_h * out_w)
            h_idx = idx % (out_h * out_w) // out_w
            w_idx = idx % out_w
            d_start = d_idx * s_dhw[0] - p_dhw[0]
            h_start = h_idx * s_dhw[1] - p_dhw[1]
            w_start = w_idx * s_dhw[2] - p_dhw[2]
            d_end = d_start + k_dhw[0]
            h_end = h_start + k_dhw[1]
            w_end = w_start + k_dhw[2]
            if countIncludePad:
                # Only the padding really appended to the input counts.
                d_end = d_end.clamp(max=in_d + p_dhw[0])
                h_end = h_end.clamp(max=in_h + p_dhw[1])
                w_end = w_end.clamp(max=in_w + p_dhw[2])
            else:
                # The padding is skipped entirely, only real elements are averaged.
                d_start = d_start.clamp(min=0)
                h_start = h_start.clamp(min=0)
                w_start = w_start.clamp(min=0)
                d_end = d_end.clamp(max=in_d)
                h_end = h_end.clamp(max=in_h)
                w_end = w_end.clamp(max=in_w)
            pool_size = ((d_end - d_start) * (h_end - h_start) * (w_end - w_start)).to(torch.float)
            pool_size = pool_size.reshape(1, 1, out_d, out_h, out_w)
            out = window_sum / pool_size

    if squeeze:
        out = out.reshape(out.shape[1], out.shape[2], out.shape[3], out.shape[4])

    return out.to(input_dtype)
```

## 6. 额外信息

### 算子调用示例

```python
import torch
import cann_bench

# 5 维输入，窗口与步长相同，无补零
x = torch.randn(2, 4, 8, 9, 10, dtype=torch.float16, device="npu")
y = cann_bench.avg_pool3_d(x, kernelSize=[2, 2, 2], stride=[2, 2, 2], padding=[0, 0, 0])

# 4 维输入，带补零且补零不计入除数
x4 = torch.randn(4, 8, 9, 10, dtype=torch.float32, device="npu")
y4 = cann_bench.avg_pool3_d(x4, kernelSize=[3, 3, 3], stride=[2, 2, 2], padding=[1, 1, 1],
                            countIncludePad=False)

# 全局平均池化
xg = torch.randn(2, 3, 4, 5, 6, dtype=torch.bfloat16, device="npu")
yg = cann_bench.avg_pool3_d(xg, kernelSize=[4, 5, 6], stride=[1, 1, 1], padding=[0, 0, 0])
```

### 用例执行与数据构造约定

`cases.yaml` 是主数据，`cases.csv` 的七个固定列与 YAML 逐项一致，结构化单元格为 JSON。

- `chips` 恒为 `["A5"]`；`layout` 恒为 `ND`。
- `view` 为 `contiguous` 或 `noncontiguous_input`；后者用末维加倍的底层存储、逻辑值写入 `base[..., ::2]` 构造非连续输入，golden 按逻辑张量计算。
- `generator` 为 `uniform` 时：`seed` 固定为 `case_id`，在有限区间 `[lo, hi]` 上均匀生成后转目标 dtype。
- `generator` 为 `mixed` 时：`value_range` 是显式取值列表，按物理行优先循环填充，再转目标 dtype。
- `expected` 记录输出 `y` 的 shape、dtype、layout；数值一律由第 5 节 Golden 计算，`expected` 不记录数值。
- `attrs` 的键名与接口参数一致（`kernelSize` / `stride` / `padding` / `ceilMode` / `countIncludePad` / `divisorOverride`）；`divisorOverride` 为 0 表示不生效。
- 本轮用例不构造 NaN/Inf 等特殊值，所有 `value_range` 均为有限区间或有限取值列表。
