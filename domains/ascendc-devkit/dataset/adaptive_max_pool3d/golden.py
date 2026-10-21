#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
# ----------------------------------------------------------------------------
# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.
# ----------------------------------------------------------------------------

from typing import List

import torch
import torch.nn.functional as F


def adaptive_max_pool3d(
    x: torch.Tensor,
    output_size: List[int],
    indices_dtype: int = 3,
) -> List[torch.Tensor]:
    """
    AdaptiveMaxPool3d 算子 Torch Golden 参考实现。

    对输入 x 的最后三个维度做 3D 自适应最大池化，同时返回最大值在窗口内的
    展平索引（索引基于单通道内的 D*H*W 空间展开，与输入是否 4 维无关）。

    Args:
        x: 输入张量，shape 为 (N, C, Di, Hi, Wi) 或 (C, Di, Hi, Wi)。
        output_size: 输出空间大小 (Do, Ho, Wo)，三个元素均不小于 1。
        indices_dtype: 索引输出类型，3 表示 int32，9 表示 int64；默认 3。

    Returns:
        [y, indices]，二者 shape 均为 (N, C, Do, Ho, Wo)（输入为 4 维时为
        (C, Do, Ho, Wo)）；y 与 x 同 dtype，indices 为 int32 或 int64。
    """
    if x.dim() == 4:
        x_5d = x.unsqueeze(0)
    else:
        x_5d = x

    x_dtype = x.dtype
    if x_dtype in (torch.float16, torch.bfloat16):
        compute_x = x_5d.to(torch.float32)
    else:
        compute_x = x_5d

    y, indices = F.adaptive_max_pool3d(compute_x, tuple(output_size), return_indices=True)

    y = y.to(x_dtype)
    indices = indices.to(torch.int32 if indices_dtype == 3 else torch.int64)

    if x.dim() == 4:
        y = y.squeeze(0)
        indices = indices.squeeze(0)

    return [y, indices]
