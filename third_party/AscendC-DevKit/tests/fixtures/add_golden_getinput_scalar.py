"""Golden + get_input for `add` where get_input appends a SCALAR to its return
tuple — real-NPU regression guard for the precision_debug harness bug where
_run_kernel's blind npu-move crashed on the scalar.

Real-world origin: scatter_pa_kv_cache.get_input returns
``(key, key_cache, slot_mapping, value, value_cache, cache_mode)`` — the trailing
``cache_mode`` (str) crashed the harness with
``AttributeError("'str' object has no attribute 'npu'")`` (run 20260801-231442-99db86),
and scope_guard mis-halted it as an upstream(golden) defect. The real fix lives
in harness ``_apply_get_input`` (drop non-tensor elements), not in golden.

The `add` kernel is the VEHICLE (cann-bench pre-built, 2 tensors, no scalar
param) — the get_input return SHAPE is what's under test, not the operator.
The harness must drop the scalar and feed only tensors to the kernel (cann-bench
evaluator.py:208-227 contract). Structural signal (get_input returning a
trailing non-tensor), not op-name (§1.12).
"""
import numpy as np


def get_input(a, b, **kwargs):
    """Return tensors PLUS a trailing scalar — mirrors scatter_pa_kv_cache's
    get_input return shape. ``_apply_get_input`` must drop the scalar so
    ``_run_kernel`` never calls ``.npu()`` on it; the kernel receives only
    ``(a, b)``."""
    return a, b, "EXTRA_SCALAR"


def reference(a: "Tensor", b: "Tensor"):
    # Tensor annotations required by bind_golden_args (name-keyed binding keys
    # on the annotation); bare params are misclassified as scalar attrs.
    return np.asarray(a) + np.asarray(b)
