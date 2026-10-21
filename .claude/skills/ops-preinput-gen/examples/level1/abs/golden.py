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
Abs算子Torch Golden参考实现

逐元素计算输入张量的绝对值
公式: y = |x|
"""
def abs(
    x: torch.Tensor
) -> torch.Tensor:
    """
    逐元素计算输入张量的绝对值

    公式: y = |x|

    Args:
        x: 输入张量

    Returns:
        输出张量，输入的逐元素绝对值，dtype 与输入一致
    """

    # abs 是保精度的单调映射（|x| 在浮点下精确可表示），无需升精度计算
    y = torch.abs(x)
    return y
