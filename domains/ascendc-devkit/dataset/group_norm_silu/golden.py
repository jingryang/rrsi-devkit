#!/usr/bin/python3
# coding=utf-8

# ----------------------------------------------------------------------------------------------------------
# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.
# ----------------------------------------------------------------------------------------------------------

from typing import List, Optional, Tuple

import torch

"""
GroupNormSilu算子Torch Golden参考实现

对输入张量 x 按通道分组做 GroupNorm，再对归一化结果做 SiLU 激活：
- 记 x 的 shape 为 [N, C, ...]，归约集合为「同一 (n, g) 下的 C/group 个通道 × 其余全部维」
- mean  = E[x]
- var   = E[(x - mean)^2]              （总体方差，除以元素个数）
- rstd  = 1 / sqrt(var + epsilon)
- z     = (x - mean) * rstd * gamma + beta
- y     = z * sigmoid(z)               （SiLU）

gamma / beta 省略时分别等价于全 1 / 全 0；gamma 与 beta 的 shape 必须为 [C]。
mean / rstd 的 shape 恒为 [N, group]，dtype 取 gamma（缺省时取 beta，再缺省取 x）的 dtype。
全部计算在 FLOAT64 中完成，最后一次性舍入到各自的输出 dtype。
"""


def group_norm_silu(
    x: torch.Tensor,
    group: int,
    gamma: Optional[torch.Tensor] = None,
    beta: Optional[torch.Tensor] = None,
    eps: float = 1e-5,
) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """
    计算按通道分组的 GroupNorm + SiLU 融合结果

    Args:
        x: 输入张量，shape 为 [N, C, ...]，维度数 2~8，dtype 为 FLOAT16/FLOAT32/BFLOAT16
        group: 将第 1 维 C 划分的组数，必须满足 group > 0 且 C 能被 group 整除
        gamma: 可选缩放权重，shape 为 [C]，dtype 与 x 相同或为 FLOAT32；None 表示全 1
        beta: 可选偏移量，shape 为 [C]，dtype 与 x 相同或为 FLOAT32；None 表示全 0
        eps: 加到方差上的数值稳定项，要求 eps > 0

    Returns:
        (y, mean, rstd)：
        - y：shape 与 x 相同，dtype 与 x 相同
        - mean：shape 为 [N, group]，dtype 取 gamma（缺省取 beta，再缺省取 x）的 dtype
        - rstd：shape 与 mean 相同，dtype 与 mean 相同
    """
    if x.dim() < 2:
        raise ValueError(f"GroupNormSilu requires x with at least 2 dims, got {x.dim()}")
    if group <= 0:
        raise ValueError(f"GroupNormSilu requires group > 0, got {group}")

    num_n = int(x.shape[0])
    num_c = int(x.shape[1])
    if num_c % group != 0:
        raise ValueError(f"GroupNormSilu requires C divisible by group, got C={num_c}, group={group}")

    channel_per_group = num_c // group
    spatial = 1
    for size in x.shape[2:]:
        spatial *= int(size)
    row = channel_per_group * spatial

    out_dtype = x.dtype
    if gamma is not None:
        stat_dtype = gamma.dtype
    elif beta is not None:
        stat_dtype = beta.dtype
    else:
        stat_dtype = x.dtype

    # 统一提升到 FLOAT64 计算，输入 dtype 只用于最终输出舍入
    x_compute = x.to(torch.float64)
    flat = x_compute.reshape(num_n * group, row)

    mean = flat.mean(dim=1)
    # 总体方差（除以元素个数），与 torch.nn.GroupNorm 一致
    variance = ((flat - mean.unsqueeze(1)) ** 2).mean(dim=1)
    rstd = torch.rsqrt(variance + eps)

    z = (flat - mean.unsqueeze(1)) * rstd.unsqueeze(1)
    z = z.reshape(num_n, group, channel_per_group, spatial)

    if gamma is not None:
        z = z * gamma.to(torch.float64).reshape(1, group, channel_per_group, 1)
    if beta is not None:
        z = z + beta.to(torch.float64).reshape(1, group, channel_per_group, 1)

    z = z.reshape(x.shape)
    # SiLU: z * sigmoid(z)
    y = z * torch.sigmoid(z)

    shape_stat = [num_n, group]
    return y.to(out_dtype), mean.reshape(shape_stat).to(stat_dtype), rstd.reshape(shape_stat).to(stat_dtype)
