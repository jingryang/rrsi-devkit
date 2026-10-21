from typing import List

import torch


def deep_norm(
    x: torch.Tensor,
    gx: torch.Tensor,
    beta: torch.Tensor,
    gamma: torch.Tensor,
    alpha: float = 0.3,
    epsilon: float = 1e-6,
) -> List[torch.Tensor]:
    """DeepNorm reference implementation on CPU.

    The last ``gamma.dim()`` dimensions of ``x`` are the normalized dimensions.
    All arithmetic is performed in float32; ``mean``/``rstd`` are returned as
    float32 and ``y`` in the dtype of ``x``.

    Args:
        x: Input tensor, 2 to 8 dimensions.
        gx: Additive term with the same shape as ``x``.
        beta: Bias with the trailing shape of ``x``, 1 to 7 dimensions.
        gamma: Scale with the trailing shape of ``x``, 1 to 7 dimensions.
        alpha: Weight applied to ``x`` before adding ``gx``.
        epsilon: Numerical stability term added to the variance.

    Returns:
        ``[mean, rstd, y]`` in operator output order.
    """
    input_dtype = x.dtype
    # fp16 / bf16 are accumulated in fp32 and cast back at the very end.
    if input_dtype in (torch.float16, torch.bfloat16):
        compute_dtype = torch.float32
    else:
        compute_dtype = input_dtype

    x_compute = x.to(compute_dtype)
    gx_compute = gx.to(compute_dtype)
    beta_compute = beta.to(compute_dtype)
    gamma_compute = gamma.to(compute_dtype)

    reduce_axes = tuple(range(x_compute.dim() - gamma_compute.dim(), x_compute.dim()))
    hidden = x_compute * float(alpha) + gx_compute
    mean = torch.mean(hidden, dim=reduce_axes, keepdim=True)
    centered = hidden - mean
    variance = torch.mean(centered * centered, dim=reduce_axes, keepdim=True)
    rstd = torch.rsqrt(variance + float(epsilon))
    y = centered * rstd * gamma_compute + beta_compute

    return [mean, rstd, y.to(x.dtype)]