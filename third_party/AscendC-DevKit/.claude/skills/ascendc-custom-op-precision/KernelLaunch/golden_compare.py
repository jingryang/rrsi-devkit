"""KernelLaunch golden loading & precision comparison — devkit MERE/MARE standard.

Replicates the golden loading contract from NPURunner's harness template
(_harness_template.py:49-87: importlib spec + _golden_wrap) and delegates
comparison to ascendc_devkit's precision_compare (semantically equivalent to
cann-bench's compare_tensors, parity-UT guarded).

Usage::

    from KernelLaunch.golden_compare import load_golden, compare_outputs
    from KernelLaunch import KernelLauncher

    # Load golden per devkit contract: path / entry / input_type
    golden_fn = load_golden("golden.py", entry="add")
    golden = golden_fn(input_a, input_b)

    launcher = KernelLauncher("add", device_id=0)
    launcher.set_input(0, input_a); launcher.set_input(1, input_b)
    launcher.set_output(0, shape, dtype=dtype)
    outputs = launcher.run()

    # Compare using the same MERE/MARE standard as run-cases
    result = compare_outputs(outputs, golden)
    for k in ("passed", "mere", "mare", "max_diff"):
        print(f"{k}: {result[k]}")
    for po in result["per_output"]:
        print(f"  output[{po['index']}] {po['dtype']} "
              f"passed={po['passed']} mere={po['mere']:.2e} mare={po['mare']:.2e}")
"""

from __future__ import annotations

import csv
import importlib.util
import json
import os
import sys
from typing import Any, Callable, Optional

import numpy as np


def _resolve_bf16():
    """Return the custom bf16 dtype class available at runtime."""
    try:
        from ml_dtypes import bfloat16 as _ml_bf16
        return _ml_bf16
    except Exception:
        pass
    try:
        from ttk.utilities.dtypes import numpy_bfloat16
        bf = numpy_bfloat16()
        return type(bf)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
#  golden loading — replicates _harness_template.py:49-87
# ---------------------------------------------------------------------------

def load_golden(
    golden_path: str,
    entry: str = "reference",
    input_type: str = "numpy",
) -> Callable[..., list[np.ndarray]]:
    """Load golden.py and return a callable fn(*inputs, **attrs) -> List[np.ndarray].

    Replicates _harness_template.py:49-87 contract exactly:
    - ``golden_path``: absolute path to a .py file containing a golden function
    - ``entry``: function name (cann-bench convention: op name, e.g. "rms_norm";
      hand-written fixtures: "reference")
    - ``input_type``: "numpy" (default) or "torch" — type of inputs the golden expects

    The returned function:
    - Takes positional numpy arrays (converted to torch if input_type=="torch")
    - Takes ``**attrs`` as keyword arguments (op attrs)
    - Returns ``List[np.ndarray]`` (single tensor wrapped in a list)

    Raises:
        ValueError: if golden_path is not a .py file, or the entry function
            is not found in the module.
    """
    if not golden_path or not golden_path.endswith(".py"):
        raise ValueError(
            f"golden_path must be a .py file, got {golden_path!r}"
        )

    spec = importlib.util.spec_from_file_location("golden_ref", golden_path)
    golden_mod = importlib.util.module_from_spec(spec)
    sys.modules["golden_ref"] = golden_mod
    spec.loader.exec_module(golden_mod)

    golden_raw = getattr(golden_mod, entry, None)
    if golden_raw is None:
        raise ValueError(
            f"golden entry {entry!r} not found in {golden_path!r}"
        )

    def _golden_fn(*inputs, **attrs):
        if input_type == "torch":
            import torch
            inputs = [torch.from_numpy(a) for a in inputs]
        out = golden_raw(*inputs, **attrs)
        return _to_np_list(out)

    return _golden_fn


def _to_np(x):
    try:
        import torch
        if isinstance(x, torch.Tensor):
            return x.detach().cpu().float().numpy()
    except ImportError:
        pass
    return np.asarray(x)


def _to_np_list(out):
    if isinstance(out, (tuple, list)):
        return [_to_np(o) for o in out]
    return [_to_np(out)]


# ---------------------------------------------------------------------------
#  precision comparison — delegates to devkit compare_outputs
# ---------------------------------------------------------------------------

def compare_outputs(
    outputs: Any,
    golden_outputs: Any,
    thresholds: Optional[dict[str, float]] = None,
    proto: Optional[dict[str, float]] = None,
) -> dict[str, Any]:
    """Compare kernel outputs vs golden using devkit MERE/MARE standard.

    Same comparison as ascendc-devkit run-cases harness fallback path
    (_harness_template.py:340-366): output tensors (original dtype for
    threshold lookup) are compared against golden (float64) via
    ``precision_compare.compare_outputs``.

    Args:
        outputs: List[np.ndarray] from ``KernelLauncher.run()``, or single array.
        golden_outputs: List[np.ndarray] from golden function, or single array.
        thresholds: Per-dtype threshold overrides merged on top of defaults.
        proto: Proto ``precision_thresholds`` dict (e.g. ``{"int8": 1.0}``),
            merged with highest priority (proto > thresholds > defaults).

    Returns:
        dict:
            passed (bool)          — all outputs passed
            mere (float)           — weighted mean relative error
            mare (float)           — maximum relative error
            max_diff (float)       — maximum absolute difference
            mean_diff (float)      — weighted mean absolute difference
            mismatch_count (int)   — total mismatched elements
            total_count (int)      — total elements across all outputs
            threshold (float)      — threshold value of first failed output
            dtype (str)            — dtype of first failed output
            error_msg (str)        — top-level error message (empty on pass)
            per_output (list[dict]) — per-output verdict with keys: index,
                                      dtype, passed, mere, mare, max_diff,
                                      mismatch_count, total_count, threshold,
                                      error_msg
    """
    from ascendc_devkit.adapters.npu.precision_compare import (
        DEFAULT_THRESHOLDS,
        compare_outputs as devkit_compare,
        merge_thresholds,
    )

    merged = merge_thresholds(proto) if proto else dict(DEFAULT_THRESHOLDS)
    if thresholds:
        merged = dict(merged)
        merged.update(thresholds)

    out_norm = _normalize_outputs(outputs)
    gold_norm = _normalize_outputs(golden_outputs)

    k_tensors = [_to_torch_kernel(o) for o in out_norm]
    g_tensors = [_to_torch_golden(o) for o in gold_norm]

    verdict = devkit_compare(k_tensors, g_tensors, merged)

    return {
        "passed": verdict.passed,
        "mere": verdict.mere,
        "mare": verdict.mare,
        "max_diff": verdict.max_diff,
        "mean_diff": verdict.mean_diff,
        "mismatch_count": verdict.mismatch_count,
        "total_count": verdict.total_count,
        "threshold": verdict.threshold,
        "dtype": verdict.dtype,
        "error_msg": verdict.error_msg,
        "per_output": [
            {
                "index": v.index,
                "dtype": v.dtype,
                "passed": v.passed,
                "mere": v.mere,
                "mare": v.mare,
                "max_diff": v.max_diff,
                "mismatch_count": v.mismatch_count,
                "total_count": v.total_count,
                "threshold": v.threshold,
                "error_msg": v.error_msg,
            }
            for v in verdict.output_verdicts
        ],
    }


# ---------------------------------------------------------------------------
#  cann-bench cases loading
# ---------------------------------------------------------------------------

def load_cases(
    csv_path: str,
    case_ids: Optional[list[int]] = None,
    skip_large: Optional[set[int]] = None,
) -> list[dict]:
    """Read a cann-bench cases.csv → list of normalized case dicts.

    Parses the standard cann-bench CSV format (``operator, case_id,
    input_shape, dtype, attrs, value_range, note``) and normalizes each
    column into a ready-to-use dict.

    Args:
        csv_path: Path to ``cases.csv``.
        case_ids: Optional list of case ids to include (omit for all).
        skip_large: Optional set of case ids to skip (e.g. >10M elements).

    Returns:
        List of dicts, each with keys:
            - ``case_id`` (int)
            - ``shape`` (tuple of ints)
            - ``dtype`` (numpy dtype)
            - ``attrs`` (dict of str→float)
            - ``value_range`` (tuple of float, float — or NaN/Inf)
            - ``note`` (str)
    """
    bf16_t = _resolve_bf16()

    def _parse_shape(raw):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list) and parsed:
                inner = parsed[0]
                if isinstance(inner, list):
                    return tuple(inner)
                return (int(parsed[0]),)
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
        return (1024,)

    def _parse_dtype(raw):
        try:
            parsed = json.loads(raw)
            name = (parsed[0] if isinstance(parsed, list) and parsed
                    else str(parsed)).lower().strip()
        except (json.JSONDecodeError, TypeError):
            name = "float16"
        if name in ("float16", "fp16"):
            return np.float16
        if name in ("float32", "fp32"):
            return np.float32
        if name in ("float64", "fp64"):
            return np.float64
        if name in ("bfloat16", "bf16"):
            return bf16_t or name  # str fallback if bf16 is unavailable
        return np.float16

    def _parse_attrs(raw):
        try:
            return {k: float(v) for k, v in json.loads(raw).items()}
        except (json.JSONDecodeError, TypeError):
            return {}

    _sentinel = {"nan": float("nan"), "inf": float("inf"), "-inf": float("-inf")}

    def _parse_vrange(raw):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list) and len(parsed) >= 2:
                lo, hi = parsed[0], parsed[1]
                return (
                    _sentinel.get(str(lo).lower(), float(lo)),
                    _sentinel.get(str(hi).lower(), float(hi)),
                )
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
        return (-1.0, 1.0)

    skip = skip_large or set()
    cases: list[dict] = []

    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            cid = int(row.get("case_id", 0))
            if case_ids and cid not in case_ids:
                continue
            if cid in skip:
                continue
            cases.append({
                "case_id": cid,
                "shape": _parse_shape(row.get("input_shape", "[[1024]]")),
                "dtype": _parse_dtype(row.get("dtype", '["float16"]')),
                "attrs": _parse_attrs(row.get("attrs", "{}")),
                "value_range": _parse_vrange(row.get("value_range", "[-1, 1]")),
                "note": (row.get("note") or "").strip(),
            })

    return cases


def find_task_asset(
    task_dir: str,
    op_name: str,
    filename: str,
    levels: tuple[str, ...] = ("level0", "level1", "level2", "level3", "level4"),
) -> Optional[str]:
    """Auto-discover golden.py or cases.csv from a cann-bench task directory.

    Scans ``{task_dir}/tasks/{level}/{op_name}/{filename}`` across levels,
    returning the first match.

    Args:
        task_dir: Root of a cann-bench task repo (e.g. ``cann-bench_softmax/``).
        op_name: Operator name (e.g. ``"exp"``).
        filename: Asset to find (``"golden.py"`` or ``"cases.csv"``).
        levels: Directory levels under ``tasks/`` to scan.

    Returns:
        Absolute path or ``None`` if not found.
    """
    if not task_dir:
        return None
    for level in levels:
        path = os.path.join(task_dir, "tasks", level, op_name, filename)
        if os.path.isfile(path):
            return path
    return None


# ---------------------------------------------------------------------------
#  internal helpers
# ---------------------------------------------------------------------------

def _normalize_outputs(outputs):
    if isinstance(outputs, np.ndarray):
        return [outputs]
    if isinstance(outputs, (tuple, list)):
        return [np.asarray(o) for o in outputs]
    return [np.asarray(outputs)]


def _to_torch_kernel(arr: np.ndarray):
    """Convert kernel output numpy array → torch tensor, preserving bf16 dtype
    for correct threshold lookup (bf16=2^-7 vs fp32=2^-13)."""
    import torch

    if _is_numpy_bfloat16(arr):
        f32 = arr.astype(np.float32)
        return torch.from_numpy(f32).to(torch.bfloat16)
    return torch.from_numpy(arr)


def _to_torch_golden(arr: np.ndarray):
    """Convert golden output numpy array → torch float64 tensor.
    Matches harness behaviour (_harness_template.py:351)."""
    import torch

    if _is_numpy_bfloat16(arr):
        f32 = arr.astype(np.float32)
        return torch.from_numpy(f32.astype(np.float64))
    return torch.from_numpy(arr.astype(np.float64))


def _is_numpy_bfloat16(arr: np.ndarray) -> bool:
    """Detect custom bf16 dtypes (ttk numpy_bfloat16 / ml_dtypes.bfloat16)."""
    if not hasattr(arr, "dtype"):
        return False
    bf16_t = _resolve_bf16()
    if bf16_t is not None and isinstance(arr.dtype, bf16_t):
        return True
    dtype_name = getattr(arr.dtype, "name", "")
    if "bfloat16" in dtype_name.lower():
        return True
    return "bfloat16" in str(arr.dtype).lower()
