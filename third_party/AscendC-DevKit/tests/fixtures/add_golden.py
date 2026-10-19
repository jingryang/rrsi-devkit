"""Golden reference for `add` — CORRECT (a + b).

Used by the P7 real-kernel precision guard (test_npu.py): the deployed `add`
kernel compared against this golden must yield max_diff ≈ 0 (pass).
"""
import numpy as np


def reference(a: "Tensor", b: "Tensor"):
    # `Tensor` annotations are REQUIRED by the harness bind_golden_args contract
    # (golden_binding.py: name-keyed binding keys on the Tensor annotation) —
    # bare params are misclassified as scalar attrs and the call raises
    # "reference() missing required arguments 'a' and 'b'".
    return np.asarray(a) + np.asarray(b)
