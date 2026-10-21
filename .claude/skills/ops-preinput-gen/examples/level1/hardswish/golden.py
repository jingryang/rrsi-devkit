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
HardSwish算子Torch Golden参考实现

HardSwish 激活函数，Swish 的分段线性近似
公式: y = x * ReLU6(x + 3) / 6
"""
def hardswish(
    x: torch.Tensor
) -> torch.Tensor:
    """
    HardSwish 激活函数

    公式: y = x * ReLU6(x + 3) / 6
      - x <= -3      : y = 0
      - x >= 3       : y = x
      - -3 < x < 3   : y = x * (x + 3) / 6

    Args:
        x: 输入张量

    Returns:
        输出张量，HardSwish 激活结果
    """
    input_dtype = x.dtype

    # FP16/BF16 输入升到 FP32 计算：分段点附近 (x+3)/6 的舍入在低精度下误差放大
    compute_dtype = torch.float32 if input_dtype in (torch.float16, torch.bfloat16) else input_dtype
    x_compute = x.to(compute_dtype)

    y = torch.nn.functional.hardswish(x_compute)

    if input_dtype in (torch.float16, torch.bfloat16):
        return y.to(input_dtype)
    return y
