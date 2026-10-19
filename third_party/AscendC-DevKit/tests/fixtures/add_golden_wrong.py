"""Golden reference for `add` — DELIBERATELY WRONG (a - b).

Used by the P7 real-kernel precision guard (test_npu.py): the deployed `add`
kernel compared against this wrong golden must yield a large max_diff (fail),
proving the precision check is real and not a max_diff=0 stub.
"""
import numpy as np


def reference(a: "Tensor", b: "Tensor"):  # Tensor annotation required by bind_golden_args
    return np.asarray(a) - np.asarray(b)
