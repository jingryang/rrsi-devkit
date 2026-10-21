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

from typing import List, Optional

import torch
import torch.nn.functional as F


def _expand3(value: List[int]) -> List[int]:
    """Expand a length-1 window parameter to (D, H, W); a length-3 list is kept as is."""
    if len(value) == 1:
        return [value[0], value[0], value[0]]
    return [value[0], value[1], value[2]]


def max_pool3d_with_argmax_v2(
    x: torch.Tensor,
    kernelSize: List[int],
    stride: List[int],
    padding: List[int],
    dilation: Optional[List[int]] = None,
    ceilMode: bool = False,
    data_format: str = "NCDHW",
    indices_dtype: int = 3,
) -> List[torch.Tensor]:
    """3D max pooling that also returns the position of every maximum.

    For each output element the window of shape kernelSize = (kD, kH, kW) anchored at
    (d * sD - pD, h * sH - pH, w * sW - pW) is scanned with step (dD, dH, dW); positions that fall
    outside the input are ignored (treated as negative infinity). The reported index is the offset of
    the selected element inside its own channel, i.e. d_in * H_in * W_in + h_in * W_in + w_in, so it is
    independent of the batch and channel position.

    Args:
        x: input tensor, 5-dimensional (N, C, D, H, W) or 4-dimensional (C, D, H, W).
        kernelSize: pooling window, either a single value (kD = kH = kW) or (kD, kH, kW).
        stride: pooling step, either an empty list (equals kernelSize), a single value
            (sD = sH = sW) or (sD, sH, sW).
        padding: padding layers added on both sides of the D, H and W axes, either a single value
            (pD = pH = pW) or (pD, pH, pW); each value is at most half of the matching kernelSize value.
        dilation: spacing between the elements of one window, either a single value
            (dD = dH = dW) or (dD, dH, dW); None means (1, 1, 1).
        ceilMode: when True the output shape is rounded up instead of down, and a window that starts
            entirely inside the trailing padding is dropped.
        data_format: "NCDHW" for a channel-first tensor or "NDHWC" for a channel-last tensor.
        indices_dtype: type code of the index output, 3 for int32 and 9 for int64.

    Returns:
        [y, argmax]: the pooled values (same dtype as x) and the flattened indices, both shaped
        (N, C, D_out, H_out, W_out) for NCDHW and (N, D_out, H_out, W_out, C) for NDHWC; the batch
        axis is dropped for a 4-dimensional input.
    """
    input_dtype = x.dtype
    if input_dtype in (torch.float16, torch.bfloat16):
        compute_x = x.to(torch.float32)
    else:
        compute_x = x

    is_ndhwc = str(data_format).upper() == "NDHWC"

    # The channel axis is the last one for NDHWC: compute on the NCDHW view, restore afterwards.
    if is_ndhwc:
        compute_x = compute_x.permute(0, 4, 1, 2, 3)

    # A 4-dimensional input is (C, D, H, W) with an implicit batch of 1.
    squeeze = compute_x.dim() == 4
    if squeeze:
        compute_x = compute_x.unsqueeze(0)

    k_dhw = _expand3(list(kernelSize))
    s_dhw = _expand3(list(stride)) if len(stride) != 0 else list(k_dhw)
    p_dhw = _expand3(list(padding))
    d_dhw = _expand3(list(dilation)) if dilation is not None and len(dilation) != 0 else [1, 1, 1]

    y, argmax = F.max_pool3d(
        compute_x,
        kernel_size=k_dhw,
        stride=s_dhw,
        padding=p_dhw,
        dilation=d_dhw,
        ceil_mode=ceilMode,
        return_indices=True,
    )

    y = y.to(input_dtype)
    argmax = argmax.to(torch.int32 if indices_dtype == 3 else torch.int64)

    if squeeze:
        y = y.squeeze(0)
        argmax = argmax.squeeze(0)

    if is_ndhwc:
        y = y.permute(0, 2, 3, 4, 1)
        argmax = argmax.permute(0, 2, 3, 4, 1)

    return [y, argmax]
