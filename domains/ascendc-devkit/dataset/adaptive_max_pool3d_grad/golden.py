import torch


def adaptive_max_pool3d_grad(
    x: torch.Tensor,
    grad: torch.Tensor,
    argmax: torch.Tensor,
) -> torch.Tensor:
    """AdaptiveMaxPool3DGrad 标准 Golden（CPU）。

    正向自适应最大池化的反向传播：输出先置零，再把每个正向输出位置上的梯度
    累加回该位置 argmax 所指的输入坐标。

    Args:
        x: 正向输入张量，4 维 CDHW 或 5 维 NCDHW，dtype 为 float16/float32/bfloat16。
        grad: 正向输出对应的梯度，shape 与 argmax 相同，dtype 与 x 相同。
        argmax: 正向 argmax 索引，dtype 为 int32 或 int64；每个 (N, C) 平面内的
            一维偏移，取值范围 [0, D*H*W)。

    Returns:
        y: 梯度回填结果，shape 与 x 相同，dtype 与 x 相同。
    """
    if x.dim() not in (4, 5):
        raise ValueError("x 必须为 4 维 CDHW 或 5 维 NCDHW")
    if grad.dim() != x.dim() or argmax.dim() != x.dim():
        raise ValueError("x、grad、argmax 的维度数必须一致")
    if tuple(grad.shape) != tuple(argmax.shape):
        raise ValueError("grad 与 argmax 的 shape 必须一致")
    if tuple(x.shape[:-3]) != tuple(grad.shape[:-3]):
        raise ValueError("x 与 grad 的 N、C 维必须一致")
    if grad.dtype != x.dtype:
        raise ValueError("grad 的 dtype 必须与 x 一致")
    if argmax.dtype not in (torch.int32, torch.int64):
        raise ValueError("argmax 的 dtype 必须为 int32 或 int64")

    plane = 1
    for dim in x.shape[-3:]:
        plane *= int(dim)
    planes = int(x.numel()) // plane
    if int(argmax.numel()) > 0:
        if bool(torch.any(argmax < 0)) or bool(torch.any(argmax >= plane)):
            raise ValueError("argmax 的每个元素必须落在 [0, D*H*W) 内")

    compute_dtype = torch.float32 if x.dtype in (torch.float16, torch.bfloat16) else x.dtype
    if planes == 0:
        return torch.zeros(tuple(x.shape), dtype=x.dtype, device=x.device)

    grad_flat = grad.reshape(planes, -1).to(compute_dtype)
    index_flat = argmax.reshape(planes, -1).to(torch.int64)

    y_flat = torch.zeros((planes, plane), dtype=compute_dtype, device=x.device)
    y_flat.scatter_add_(1, index_flat, grad_flat)
    return y_flat.reshape(tuple(x.shape)).to(x.dtype)
