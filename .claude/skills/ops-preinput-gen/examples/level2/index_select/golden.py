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
IndexSelect算子Torch Golden参考实现

沿指定维度按索引张量取出若干切片并拼接为新张量
公式: y[..., i, ...] = x[..., index[i], ...]
"""
def index_select(
    x: torch.Tensor, dim: int, index: torch.Tensor
) -> torch.Tensor:
    """
    沿指定维度按索引取切片

    公式: y[..., i, ...] = x[..., index[i], ...]

    Args:
        x: 被索引的输入张量
        dim: 沿哪一维取索引 (取值范围: -ndim ~ ndim-1)
        index: 索引张量，1D，元素取值范围 [0, x.shape[dim]-1]

    Returns:
        输出张量，与 x 同 shape，仅 dim 维大小变为 index 的长度 L
    """

    # index_select 是纯数据搬运（无算术），不引入精度误差，无需升精度计算
    # torch 要求 index 为 int32/int64 的 1D 张量
    y = torch.index_select(x, dim, index)
    return y
