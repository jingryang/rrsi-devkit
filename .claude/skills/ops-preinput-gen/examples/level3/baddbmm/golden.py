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

    # FP16/BF16 升到 FP32 计算：contraction 维 M 上的累加在低精度会显著放大误差，
    # M 越大越明显（本算子 cases 的 M 最大到 512）
    compute_dtype = torch.float32 if input_dtype in (torch.float16, torch.bfloat16) else input_dtype

    y = torch.baddbmm(
        input.to(compute_dtype), batch1.to(compute_dtype), batch2.to(compute_dtype),
        beta=beta, alpha=alpha,
    )

    if input_dtype in (torch.float16, torch.bfloat16):
        return y.to(input_dtype)
    return y
