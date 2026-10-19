"""RotaryPositionEmbedding golden reference (pure NumPy, no torch dependency).

Implements all four rotation modes as specified in rope_requirements.md §3.2.
The harness imports this module and calls ``reference(x, cos, sin, mode)`` to
get the authoritative precision baseline for max_diff comparison.

Supports partial_rope: cos/sin cover only the first Dx elements of headDim
(where Dx ≤ headDim). The rotation applies to the first Dx elements; the
remaining headDim - Dx elements pass through unchanged.
"""
import numpy as np


def reference(x: np.ndarray, cos: np.ndarray, sin: np.ndarray,
              mode: int = 0) -> np.ndarray:
    """Compute ground-truth RotaryPositionEmbedding output.

    x:   shape (..., D)    — full headDim
    cos: shape (..., Dx)   — partial dim to rotate  (Dx ≤ D)
    sin: shape (..., Dx)   — same as cos
    """
    dx = cos.shape[-1]  # partial_rope: only rotate the first Dx elements
    x_rot = x[..., :dx]  # the portion that gets rotation
    x_tail = x[..., dx:]  # remainder passes through unchanged

    if mode == 0:
        y_rot = _half(x_rot, cos, sin)
    elif mode == 1:
        y_rot = _interleave(x_rot, cos, sin)
    elif mode == 2:
        y_rot = _quarter(x_rot, cos, sin)
    elif mode == 3:
        y_rot = _interleave_half(x_rot, cos, sin)
    else:
        raise ValueError(f"Unsupported mode: {mode}")

    if dx < x.shape[-1]:
        return np.concatenate((y_rot, x_tail), axis=-1)
    return y_rot


def _half(x, cos, sin):
    """Mode 0: split headDim in half, negate-pair, apply cos/sin."""
    half_d = x.shape[-1] // 2
    x1 = x[..., :half_d]
    x2 = x[..., half_d:]
    x_rotate = np.concatenate((-x2, x1), axis=-1)
    return x * cos + x_rotate * sin


def _interleave(x, cos, sin):
    """Mode 1: interleave pairs (even/odd), negate-pair, reshape back."""
    x1 = x[..., ::2]
    x2 = x[..., 1::2]
    x_rotate = np.stack((-x2, x1), axis=-1)
    x_rotate = x_rotate.reshape(x.shape)
    return x * cos + x_rotate * sin


def _quarter(x, cos, sin):
    """Mode 2: split into quarters, pair-negate (1,0,3,2)."""
    d = x.shape[-1]
    q = d // 4
    x1 = x[..., 0 * q:1 * q]
    x2 = x[..., 1 * q:2 * q]
    x3 = x[..., 2 * q:3 * q]
    x4 = x[..., 3 * q:4 * q]
    x_rotate = np.concatenate((-x2, x1, -x4, x3), axis=-1)
    return x * cos + x_rotate * sin


def _interleave_half(x, cos, sin):
    """Mode 3: interleave to split evens/odds, then half-pattern."""
    x1 = x[..., ::2]
    x2 = x[..., 1::2]
    x_part1 = np.concatenate((x1, x2), axis=-1)
    x_part2 = np.concatenate((-x2, x1), axis=-1)
    return x_part1 * cos + x_part2 * sin
