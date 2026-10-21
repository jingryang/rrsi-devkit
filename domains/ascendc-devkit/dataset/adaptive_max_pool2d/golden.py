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
from typing import List, Tuple



def adaptive_max_pool2d(
    x: torch.Tensor,
    output_size: List[int],
) -> Tuple[torch.Tensor, torch.Tensor]:
    """二维自适应最大池化标准 Golden。

    Args:
        x: 输入张量，3 维 [C, H, W] 或 4 维 [N, C, H, W]。
        output_size: 输出在 H、W 维上的大小 [Ho, Wo]，长度为 2 且每个元素大于 0。

    Returns:
        y: 池化结果，shape 为 x 的 shape 把后两维替换为 [Ho, Wo]，dtype 与 x 相同。
        indices: 每个输出元素在对应 (N, C) 平面 H*W 内的一维偏移，shape 与 y 相同，dtype 为 int64。
    """
    if x.dim() not in (3, 4):
        raise ValueError("x 必须为 3 维 [C, H, W] 或 4 维 [N, C, H, W]")
    if len(output_size) != 2:
        raise ValueError("output_size 必须是长度为 2 的列表")
    out_h, out_w = int(output_size[0]), int(output_size[1])
    if out_h <= 0 or out_w <= 0:
        raise ValueError("output_size 的每个元素都必须大于 0")
    if x.numel() == 0:
        raise ValueError("x 不支持空张量")

    # 升 float32 是无损且保序的：避免低精度内置实现返回越界索引，同时保持最大值与并列关系
    y, indices = torch.nn.functional.adaptive_max_pool2d(
        x.to(torch.float32), (out_h, out_w), return_indices=True
    )
    return y.to(x.dtype), indices.to(torch.int64)
