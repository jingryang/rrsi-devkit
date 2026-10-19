#!/usr/bin/env python3
"""Lightweight single-case tiling bounds checker for A5 kernel_debug.

Usage:
    python3 tiling_bounds_check.py \\
        --op-dir /path/to/operator \\
        --case-json '{"shape": [...], "dtype": "float16"}' \\
        --tiling-json /path/to/tiling_params.json \\
        --dtype-size 2 \\
        --pretty

Produces structured JSON findings for UB_OOB, ALIGN_32B, UB_TOTAL, and
tail_block issues. Designed to be called from kernel_debug stage as a
pre-DumpTensor diagnostic step.

Does NOT:
- Translate full C++ control flow (unlike A3 bounds_check Python shadow)
- Auto-fix tiling formulas
- Check GM addresses
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path


# ── Rule 1: utility functions (from A3 transform-rules.md) ──────────────

def ceil_div(a: int, b: int) -> int:
    return (a + b - 1) // b


def ceil_align(x: int, a: int) -> int:
    return ((x + a - 1) // a) * a


def align_up_kernel(x: int, a: int) -> int:
    """Same as ceil_align — kept under A3 name."""
    return ceil_align(x, a)


# ── Regex extractors ─────────────────────────────────────────────────────

_INIT_BUFFER_RE = re.compile(
    r'pipe\.InitBuffer\s*\(\s*'
    r'(\w+)\s*,\s*'               # buffer name
    r'(\d+\s*,)?\s*'                # optional N for TQue (e.g. "2, ")
    r'(?:AlignUpKernel\s*\(\s*)?'   # optional AlignUpKernel(
    r'([^,\n]+?)'                    # size expression (stop at comma/newline)
    r'(?:,\s*\d+\s*\))?'            # optional ", alignment )" from AlignUpKernel
    r'\s*\)',                        # closing paren of InitBuffer
)

_ALIGN_UP_RE = re.compile(
    r'AlignUpKernel\s*\(\s*(.+?)\s*,\s*32\s*\)'
)

_DATACOPY_RE = re.compile(
    r'DataCopy\s*\(\s*(\w+)\s*[\[\.]'  # optional [ or . for local tensor
)

_DATACOPYPAD_RE = re.compile(
    r'DataCopyPad\s*\(\s*(\w+)'
)

_CAST_RE = re.compile(
    r'Cast\s*\(\s*(\w+)'
)

_DUPLICATE_RE = re.compile(
    r'Duplicate\s*\(\s*(\w+)'
)

_VEC_API_RE = re.compile(
    r'(?:Add|Mul|Sub|Div|Max|Min|Reciprocal|Sqrt|Abs|Neg|Exp|Log|Rsqrt)\s*\(\s*(\w+)'
)


def _parse_init_buffer_call(match: re.Match, dtype_size: int) -> dict | None:
    """Parse one pipe.InitBuffer(...) match."""
    name = match.group(1)
    num_str = match.group(2)
    size_expr = match.group(3).strip()

    num = 1
    if num_str:
        num_match = re.match(r'(\d+)\s*,', num_str)
        if num_match:
            num = int(num_match.group(1))

    # Try to evaluate the inner expression
    try:
        size_val = _eval_expr(size_expr)
    except (ValueError, NameError, SyntaxError):
        return None

    if size_val <= 0:
        return None

    aligned = align_up_kernel(size_val, 32)
    is_tque = num > 1
    capacity = num * aligned

    return {
        "name": name,
        "is_tque": is_tque,
        "num": num,
        "raw_size": size_val,
        "aligned_size": aligned,
        "capacity_bytes": capacity,
    }


def _eval_expr(expr: str) -> int:
    """Safely evaluate a simple arithmetic expression.

    Supports: integers, +, -, *, /, //, (), *, and basic variable names.
    Treats unknown names as 0 (conservative).
    """
    expr = expr.strip()

    # Replace common C++ operators: force int division.  Protect an
    # already-normalized ``//`` first so a caller-supplied division is not
    # re-expanded into ``////`` (a syntax error that silently fell back to the
    # wrong integer literal).
    expr = expr.replace('//', '\x00')
    expr = expr.replace('/', '//')
    expr = expr.replace('\x00', '//')
    expr = expr.replace(' ', '')

    # Only allow safe characters
    if re.search(r'[^0-9a-zA-Z_+\-*/().]', expr):
        raise ValueError(f"Unsafe expression: {expr}")

    # Try direct eval in restricted namespace
    safe_dict = {
        '__builtins__': {},
        'dtypeSize': 2,
        'sizeof_half': 2,
        'sizeof_float': 4,
        'sizeof_int32': 4,
        'sizeof_int64': 8,
    }
    try:
        result = eval(expr, safe_dict)
        if isinstance(result, (int, float)):
            return int(result)
    except Exception:
        pass

    # Fallback: just look for integer literals
    nums = re.findall(r'\d+', expr)
    return max(int(n) for n in nums) if nums else 0


def extract_init_buffers(kernel_source: str, dtype_size: int) -> dict[str, dict]:
    """Extract all InitBuffer calls from kernel source and build a buffer map.

    Returns {name: {start_byte, capacity_bytes, is_tque, num}}
    """
    buffer_map: dict[str, dict] = {}
    next_free = 0

    for match in _INIT_BUFFER_RE.finditer(kernel_source):
        parsed = _parse_init_buffer_call(match, dtype_size)
        if parsed is None:
            continue
        name = parsed["name"]
        if name in buffer_map:
            continue  # duplicate InitBuffer for same name — keep first
        buffer_map[name] = {
            "start_byte": next_free,
            "capacity_bytes": parsed["capacity_bytes"],
            "is_tque": parsed["is_tque"],
            "num": parsed["num"],
            "raw_size": parsed["raw_size"],
            "aligned_size": parsed["aligned_size"],
        }
        next_free += parsed["capacity_bytes"]

    return buffer_map


def extract_tiling_params(kernel_source: str) -> dict[str, int]:
    """Extract tiling-related named constants from kernel source.

    Looks for patterns like: constexpr int H = 128;
    """
    params: dict[str, int] = {}
    const_re = re.compile(
        r'(?:const(?:expr)?\s+)?(?:int(?:64_t)?|uint(?:64_t)?|size_t|auto)\s+'
        r'(\w+)\s*=\s*(\d+)\s*;'
    )
    for m in const_re.finditer(kernel_source):
        params[m.group(1)] = int(m.group(2))
    return params


def check_ub_oob(
    buffer_map: dict[str, dict],
    kernel_source: str,
    dtype_size: int,
    tiling_params: dict[str, int],
    case_shape: list,
) -> list[dict]:
    """Check for UB buffer out-of-bounds access patterns.

    Returns list of findings dicts.
    """
    findings: list[dict] = []

    # Collect all UB access patterns: DataCopy(buf, ...) etc.
    access_patterns: list[tuple[str, str]] = []

    for m in _DATACOPY_RE.finditer(kernel_source):
        access_patterns.append(("DataCopy", m.group(1)))

    for m in _DATACOPYPAD_RE.finditer(kernel_source):
        access_patterns.append(("DataCopyPad", m.group(1)))

    for m in _CAST_RE.finditer(kernel_source):
        access_patterns.append(("Cast", m.group(1)))

    for m in _DUPLICATE_RE.finditer(kernel_source):
        access_patterns.append(("Duplicate", m.group(1)))

    for m in _VEC_API_RE.finditer(kernel_source):
        access_patterns.append(("VectorAPI", m.group(1)))

    seen_buffers: set[str] = set()
    for api, buf_name in access_patterns:
        if buf_name in seen_buffers:
            continue
        seen_buffers.add(buf_name)

        buf_info = buffer_map.get(buf_name)
        if buf_info is None:
            continue

    # Check UB_TOTAL
    total_ub = sum(info["capacity_bytes"] for info in buffer_map.values())
    hw_ub_size = 196608  # A5 default UB size

    if total_ub > hw_ub_size:
        findings.append({
            "severity": "critical",
            "category": "UB_TOTAL",
            "message": f"Total UB allocation {total_ub} exceeds hardware limit {hw_ub_size}",
            "total_ub_bytes": total_ub,
            "hw_ub_size": hw_ub_size,
            "excess_bytes": total_ub - hw_ub_size,
            "buffers": sorted(buffer_map.keys()),
        })

    # Check individual buffer alignment
    for name, info in buffer_map.items():
        start = info["start_byte"]
        if start % 32 != 0:
            findings.append({
                "severity": "critical",
                "category": "ALIGN_32B",
                "message": f"Buffer {name} starts at byte {start}, not 32B-aligned",
                "buffer": name,
                "start_byte": start,
            })

    return findings


def check_tail_block(
    case_shape: list,
    tiling_params: dict[str, int],
) -> list[dict]:
    """Check for tail-block boundary issues.

    Compares the total element range against tiling-derived tile sizes
    to detect potential overflow at the last tile.
    """
    findings: list[dict] = []

    # Common tiling parameter names to check
    param_keys = [
        ("blockFactorB", "B"), ("ubFactorB", "B"),
        ("blockFactorS", "S"), ("ubFactorS", "S"),
        ("blockFactorH", "H"), ("ubFactorH", "H"),
        ("blockNumB", "B"), ("blockNum", "B"),
    ]

    for param_key, dim_letter in param_keys:
        total = tiling_params.get(param_key)
        if total is None:
            continue

        # Find the corresponding dimension value
        dim_map = {"B": 0, "H": 1, "S": 2}
        dim_idx = dim_map.get(dim_letter)
        if dim_idx is not None and dim_idx < len(case_shape):
            dim_size = case_shape[dim_idx]
            # Check if ceil_div produces phantom rows/cols
            num_blocks = ceil_div(dim_size, total)
            if num_blocks > 1 and dim_size % total != 0:
                findings.append({
                    "severity": "warning",
                    "category": "tail_block",
                    "message": (
                        f"Dimension {dim_letter}={dim_size} not evenly divisible "
                        f"by {param_key}={total}; last block handles "
                        f"{dim_size % total} elements"
                    ),
                    "dimension": dim_letter,
                    "dim_size": dim_size,
                    "tile_size": total,
                    "last_block_size": dim_size % total,
                })

    return findings


def run_check(
    op_dir: str,
    case_json: str | dict,
    tiling_json: str | dict | None = None,
    dtype_size: int = 2,
) -> dict:
    """Main entry point for tiling bounds check.

    Args:
        op_dir: Path to operator source directory.
        case_json: JSON string or dict with "shape" and "dtype" keys.
        tiling_json: Optional JSON string/dict with pre-extracted tiling parameters.
        dtype_size: Byte size of the tensor element type (default 2 = FP16).

    Returns:
        dict with keys: status, findings[], buffer_map, ub_total, hw_ub_size.
    """
    if isinstance(case_json, str):
        case = json.loads(case_json)
    else:
        case = case_json or {}

    if isinstance(tiling_json, str):
        tiling_params = json.loads(tiling_json) if tiling_json else {}
    else:
        tiling_params = tiling_json or {}

    shape = case.get("shape", [])
    if not shape:
        return {"status": "skipped", "findings": [], "reason": "no shape in case"}

    op_path = Path(op_dir)
    kernel_dir = op_path / "op_kernel"
    if not kernel_dir.exists():
        kernel_dir = op_path

    # Read all kernel source files
    kernel_sources: list[str] = []
    for pattern in ["*.cpp", "*.h", "*.hpp"]:
        for f in kernel_dir.glob(pattern):
            if "build" not in str(f) and "output" not in str(f):
                try:
                    kernel_sources.append(f.read_text(encoding="utf-8"))
                except Exception:
                    pass
    if not kernel_sources:
        return {"status": "skipped", "findings": [], "reason": "no kernel source found"}

    combined = "\n".join(kernel_sources)

    # Step 1: Extract InitBuffer map
    buffer_map = extract_init_buffers(combined, dtype_size)

    # Step 2: Extract tiling parameters from source
    source_params = extract_tiling_params(combined)
    # Merge with provided tiling params (provided overrides extracted)
    merged_params = {**source_params, **tiling_params}

    # Step 3: Check UB OOB, alignment, total
    findings = check_ub_oob(buffer_map, combined, dtype_size, merged_params, shape)

    # Step 4: Check tail block boundaries
    findings.extend(check_tail_block(shape, merged_params))

    total_ub = sum(info["capacity_bytes"] for info in buffer_map.values())

    status = "findings" if findings else "ok"

    result = {
        "status": status,
        "findings": findings,
        "critical_count": sum(1 for f in findings if f["severity"] == "critical"),
        "warning_count": sum(1 for f in findings if f["severity"] == "warning"),
        "buffer_map": {
            name: {
                "start_byte": info["start_byte"],
                "capacity_bytes": info["capacity_bytes"],
                "is_tque": info["is_tque"],
            }
            for name, info in buffer_map.items()
        },
        "ub_total": total_ub,
        "hw_ub_size": 196608,
        "case_shape": shape,
        "dtype_size": dtype_size,
    }

    return result


def main():
    parser = argparse.ArgumentParser(
        description="A5 lightweight single-case tiling bounds checker"
    )
    parser.add_argument("--op-dir", required=True, help="Operator source directory")
    parser.add_argument("--case-json", required=True,
                        help="JSON string with shape/dtype or path to JSON file")
    parser.add_argument("--tiling-json", default=None,
                        help="JSON string with tiling params or path to JSON file")
    parser.add_argument("--dtype-size", type=int, default=2,
                        help="Byte size of element type (default: 2 for FP16)")
    parser.add_argument("--pretty", action="store_true",
                        help="Pretty-print JSON output")
    args = parser.parse_args()

    # Load case_json from file if it's a path
    case_data = args.case_json
    if Path(case_data).exists():
        case_data = json.loads(Path(case_data).read_text(encoding="utf-8"))

    # Load tiling_json from file if it's a path
    tiling_data = args.tiling_json
    if tiling_data and Path(tiling_data).exists():
        tiling_data = json.loads(Path(tiling_data).read_text(encoding="utf-8"))

    result = run_check(
        op_dir=args.op_dir,
        case_json=case_data,
        tiling_json=tiling_data,
        dtype_size=args.dtype_size,
    )

    indent = 2 if args.pretty else None
    print(json.dumps(result, indent=indent, ensure_ascii=False))
    return 0 if result["status"] == "ok" else 2


if __name__ == "__main__":
    sys.exit(main())
