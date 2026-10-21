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
Softsign算子Torch Golden参考实现

Softsign 激活函数，将输入平滑压缩到 (-1, 1) 区间
公式: y = x / (1 + |x|)
"""
def softsign(
    x: torch.Tensor
) -> torch.Tensor:
    """
    Softsign 激活函数

    公式: y = x / (1 + |x|)

    Args:
        x: 输入张量

    Returns:
        输出张量，Softsign 激活结果，取值落在 (-1, 1)
    """
    input_dtype = x.dtype

    # FP16/BF16 输入升到 FP32 计算：分母 1 + |x| 在大值域下于低精度会溢出饱和
    compute_dtype = torch.float32 if input_dtype in (torch.float16, torch.bfloat16) else input_dtype
    x_compute = x.to(compute_dtype)

    y = torch.nn.functional.softsign(x_compute)

    if input_dtype in (torch.float16, torch.bfloat16):
        return y.to(input_dtype)
    return y
