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
LayerNormV4算子Torch Golden参考实现

对输入张量 x 的后 j 维（j = len(normalized_shape)）做均值为 0、标准差为 1 的归一化：
- mean = E[x]
- rstd = 1 / sqrt(Var[x] + epsilon)
- y = ((x - mean) * rstd) * gamma + beta

其中 gamma/beta 省略时分别按全 1 / 全 0 参与计算；mean/rstd 始终以 FLOAT32 输出，
形状为 x.shape 且后 j 维置 1；y 的 dtype 与 x 一致。
FLOAT16/BFLOAT16 输入统一升到 FLOAT32 计算后再把 y 转回原 dtype。
"""


def layer_norm_v4(
    x: torch.Tensor,
    normalized_shape: List[int],
    gamma: Optional[torch.Tensor] = None,
    beta: Optional[torch.Tensor] = None,
    epsilon: float = 1e-5,
    impl_mode: int = 0,
) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """
    计算指定归一化维度的 LayerNorm，并同时返回均值与标准差倒数

    Args:
        x: 输入张量，shape 为 [A1, ..., Ai, R1, ..., Rj]，支持 FLOAT32/FLOAT16/BFLOAT16
        normalized_shape: 需要归一化的尾部维度 [R1, ..., Rj]，长度不超过 x 的维度数
        gamma: 可选缩放权重，shape 为 [R1, ..., Rj]；None 表示全 1
        beta: 可选偏移量，shape 为 [R1, ..., Rj]；None 表示全 0
        epsilon: 加到方差上的稳定项
        impl_mode: 实现模式，0 高精度 / 1 高性能 / 2 保持 FLOAT16 计算；
            不影响数学定义，仅影响实现精度，golden 统一按高精度语义计算

    Returns:
        (y, mean, rstd)：
        - y：shape 与 x 相同，dtype 与 x 相同
        - mean：FLOAT32，shape 为 [A1, ..., Ai, 1, ..., 1]
        - rstd：FLOAT32，shape 为 [A1, ..., Ai, 1, ..., 1]
    """
    origin_dtype = x.dtype
    # FP16/BF16 输入先升到 FP32 计算，避免统计量在低精度下损失
    if origin_dtype in (torch.float16, torch.bfloat16):
        compute_dtype = torch.float32
    else:
        compute_dtype = origin_dtype

    norm_dims = list(normalized_shape)
    axis_count = len(norm_dims)
    reduce_dims = tuple(range(x.dim() - axis_count, x.dim()))

    x_compute = x.to(compute_dtype)

    mean = x_compute.mean(dim=reduce_dims, keepdim=True)
    # 使用总体方差（与 torch.nn.LayerNorm 一致），即除以 R1*...*Rj
    variance = ((x_compute - mean) ** 2).mean(dim=reduce_dims, keepdim=True)
    rstd = torch.rsqrt(variance + epsilon)

    normalized = (x_compute - mean) * rstd

    if gamma is not None:
        # gamma 的 shape 为 [R1, ..., Rj]，补前导 1 后按尾部维度广播
        normalized = normalized * gamma.to(compute_dtype).reshape([1] * (x.dim() - axis_count) + norm_dims)
    if beta is not None:
        normalized = normalized + beta.to(compute_dtype).reshape([1] * (x.dim() - axis_count) + norm_dims)

    y = normalized.to(origin_dtype)
    return y, mean.to(torch.float32), rstd.to(torch.float32)
