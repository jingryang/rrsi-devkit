import torch

from typing import List


def _pool_out_size(in_size: int, pad_front: int, pad_back: int, k: int, stride: int, ceil_mode: bool) -> int:
    """Output size of one spatial dimension of the 3D average pooling window."""
    if ceil_mode:
        out_size = (in_size + pad_front + pad_back - k + stride - 1) // stride + 1
        if (out_size - 1) * stride >= in_size + pad_front:
            out_size = out_size - 1
    else:
        out_size = (in_size + pad_front + pad_back - k) // stride + 1
    return out_size


def _expand3(value: List[int]) -> List[int]:
    """Expand a length-1 list into (D, H, W); keep a length-3 list unchanged."""
    if len(value) == 1:
        return [value[0], value[0], value[0]]
    return [value[0], value[1], value[2]]


def avg_pool3_d(
    x: torch.Tensor,
    kernelSize: List[int],
    stride: List[int],
    padding: List[int],
    ceilMode: bool = False,
    countIncludePad: bool = True,
    divisorOverride: int = 0,
) -> torch.Tensor:
    """Applies a 3D average pooling over an input tensor.

    The input is laid out as (N, C, D, H, W) when 5-dimensional, and as (C, D, H, W) when
    4-dimensional (an implicit batch of 1). For every output position (n, c, d, h, w) the
    window of shape kernelSize = (kD, kH, kW) starting at (d * sD, h * sH, w * sW) is
    averaged, where stride = (sD, sH, sW). Zero padding of `padding` layers is applied on
    the D, H and W dimensions.

    Args:
        x: 4-dimensional (C, D, H, W) or 5-dimensional (N, C, D, H, W) input tensor.
        kernelSize: the pooling window, either a single value (kD = kH = kW) or (kD, kH, kW).
        stride: the pooling step, either an empty list (equals kernelSize), a single value
            (sD = sH = sW) or (sD, sH, sW).
        padding: zero padding layers, either a single value (pD = pH = pW) or (pD, pH, pW).
        ceilMode: when True, ceil instead of floor is used to derive the output shape.
        countIncludePad: when True, the zero padding is included in the averaging divisor.
        divisorOverride: a fixed divisor; 0 means the divisor is derived from the window.

    Returns:
        The pooled tensor, with the same rank, dtype and element layout as the input.
    """
    input_dtype = x.dtype
    # fp16 / bf16 are accumulated in fp32 and cast back at the very end.
    if input_dtype in (torch.float16, torch.bfloat16):
        compute_dtype = torch.float32
    else:
        compute_dtype = input_dtype
    x_compute = x.to(compute_dtype)

    # A 4-dimensional input is a (C, D, H, W) tensor with an implicit batch of 1.
    squeeze = False
    if x_compute.dim() == 4:
        x_compute = x_compute.unsqueeze(0)
        squeeze = True

    k_dhw = _expand3(list(kernelSize))
    s_dhw = _expand3(list(stride)) if len(stride) != 0 else list(k_dhw)
    p_dhw = _expand3(list(padding))

    divisor = None if divisorOverride == 0 else int(divisorOverride)

    if all(p_dhw[i] < k_dhw[i] / 2 for i in range(3)):
        # The padding of every dimension stays below half of the kernel: the plain
        # pooling definition applies directly.
        out = torch.nn.functional.avg_pool3d(
            x_compute,
            k_dhw,
            stride=s_dhw,
            padding=p_dhw,
            ceil_mode=ceilMode,
            count_include_pad=countIncludePad,
            divisor_override=divisor,
        )
    else:
        # Some dimension pads half of its kernel or more, so the whole padding has to be
        # materialised in the buffer before pooling.
        in_d, in_h, in_w = x_compute.shape[2], x_compute.shape[3], x_compute.shape[4]

        out_d = _pool_out_size(in_d, p_dhw[0], p_dhw[0], k_dhw[0], s_dhw[0], ceilMode)
        out_h = _pool_out_size(in_h, p_dhw[1], p_dhw[1], k_dhw[1], s_dhw[1], ceilMode)
        out_w = _pool_out_size(in_w, p_dhw[2], p_dhw[2], k_dhw[2], s_dhw[2], ceilMode)

        # The outermost window may reach past the input, the extra rows/cols are zero.
        back_d = max((out_d - 1) * s_dhw[0] + k_dhw[0] - in_d - p_dhw[0], 0)
        back_h = max((out_h - 1) * s_dhw[1] + k_dhw[1] - in_h - p_dhw[1], 0)
        back_w = max((out_w - 1) * s_dhw[2] + k_dhw[2] - in_w - p_dhw[2], 0)
        x_padded = torch.nn.functional.pad(
            x_compute, (p_dhw[2], back_w, p_dhw[1], back_h, p_dhw[0], back_d), mode="constant", value=0
        )

        # A pure window sum: divisor_override=1 without padding makes the pooling return it.
        window_sum = torch.nn.functional.avg_pool3d(
            x_padded,
            k_dhw,
            stride=s_dhw,
            padding=0,
            ceil_mode=False,
            count_include_pad=False,
            divisor_override=1,
        )[..., :out_d, :out_h, :out_w]

        if divisor is not None:
            out = window_sum / divisor
        else:
            idx = torch.arange(out_d * out_h * out_w)
            d_idx = idx // (out_h * out_w)
            h_idx = idx % (out_h * out_w) // out_w
            w_idx = idx % out_w
            d_start = d_idx * s_dhw[0] - p_dhw[0]
            h_start = h_idx * s_dhw[1] - p_dhw[1]
            w_start = w_idx * s_dhw[2] - p_dhw[2]
            d_end = d_start + k_dhw[0]
            h_end = h_start + k_dhw[1]
            w_end = w_start + k_dhw[2]
            if countIncludePad:
                # Only the padding really appended to the input counts.
                d_end = d_end.clamp(max=in_d + p_dhw[0])
                h_end = h_end.clamp(max=in_h + p_dhw[1])
                w_end = w_end.clamp(max=in_w + p_dhw[2])
            else:
                # The padding is skipped entirely, only real elements are averaged.
                d_start = d_start.clamp(min=0)
                h_start = h_start.clamp(min=0)
                w_start = w_start.clamp(min=0)
                d_end = d_end.clamp(max=in_d)
                h_end = h_end.clamp(max=in_h)
                w_end = w_end.clamp(max=in_w)
            pool_size = ((d_end - d_start) * (h_end - h_start) * (w_end - w_start)).to(torch.float)
            pool_size = pool_size.reshape(1, 1, out_d, out_h, out_w)
            out = window_sum / pool_size

    if squeeze:
        out = out.reshape(out.shape[1], out.shape[2], out.shape[3], out.shape[4])

    return out.to(input_dtype)
