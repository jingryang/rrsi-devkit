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

import torch

"""
AddRmsNormCast算子Torch Golden参考实现

计算 Add + RmsNorm + Cast 的融合结果，全流程在 FP32 中完成
- x   = float(x1) + float(x2)
- rstd = 1 / sqrt(mean(x^2, 归约维) + epsilon)
- y1  = x * rstd * gamma      （FP32 输出，不做中间低精度舍入）
- y2  = cast(y1) 到输入 dtype
- x   归约为输入 dtype 的 x1 + x2
"""

from typing import List, Optional


def _reduce_keepdim(
    x_fp32: torch.Tensor, gamma_rank: int, gamma_numel: int
) -> torch.Tensor:
    """把末尾 gamma_rank 维展平后求均方，保留 gamma 各维为 1 的归约形状"""
    outer_shape = x_fp32.shape[: x_fp32.dim() - gamma_rank]
    # 外部维度含 0 时不能用 -1 推断归约长度，显式给出展平宽度
    if 0 in outer_shape:
        flat = x_fp32.reshape((*outer_shape, 0))
    else:
        flat = x_fp32.reshape((*outer_shape, gamma_numel))
    return flat.pow(2).mean(-1, keepdim=True).reshape((*outer_shape, *([1] * gamma_rank)))


def add_rms_norm_cast(
    x1: torch.Tensor,
    x2: torch.Tensor,
    gamma: torch.Tensor,
    epsilon: float = 1e-6,
) -> List[torch.Tensor]:
    """
    计算 Add + RmsNorm + Cast 融合结果

    Args:
        x1: 第一个加数，dtype 为 float16/bfloat16
        x2: 第二个加数，shape 与 dtype 与 x1 一致
        gamma: RmsNorm 缩放因子，shape 与 x1 末尾若干维一致
        epsilon: 分母数值稳定补偿项，默认 1e-6，要求非负

    Returns:
        [y1, y2, rstd, x]，其中 y1/rstd 为 float32，y2/x 与输入 dtype 一致
    """
    # 统一提升到 FP32 计算，输入 dtype 只用于最终输出舍入
    x_fp32 = x1.to(torch.float32) + x2.to(torch.float32)
    gamma_fp32 = gamma.to(torch.float32)

    # 归约维由 gamma 覆盖的末尾各维决定
    gamma_rank = gamma.dim()
    gamma_numel = gamma.numel()
    x_reduce = _reduce_keepdim(x_fp32, gamma_rank, gamma_numel)
    rstd = torch.rsqrt(x_reduce + epsilon)

    # 先乘 rstd 再乘 gamma，避免 x * gamma 提前溢出
    y1 = x_fp32 * rstd * gamma_fp32

    input_dtype = x1.dtype
    y2 = y1.to(input_dtype)
    x = x_fp32.to(input_dtype)
    return [y1, y2, rstd, x]
