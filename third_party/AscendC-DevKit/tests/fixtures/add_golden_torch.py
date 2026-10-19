"""Torch golden for `add` — used by the A4 golden-contract real-NPU guard.

cann-bench goldens are torch-based with the operator name as the entry function
(input_type=torch, entry=op). This fixture mirrors that contract for the
pre-built `add` kernel so the golden-adapter's numpy→torch conversion +
entry-by-name resolution can be exercised on real hardware (no cann-bench op
except add/sqrt is pre-built, and neither has a cann-bench task/golden).
"""
import torch


def add(a: "Tensor", b: "Tensor"):  # Tensor annotation required by bind_golden_args
    return a + b
