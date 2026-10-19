#!/usr/bin/env python3
"""Merge L0/L1 test-case CSVs into the unified 13-column format consumed by
``csv_to_testcases.py``.  L2 cases are intentionally excluded.

Source CSVs (produced by ``generate_test_cases.py``) carry columns::

    testcase_name, api_name, tensor_view_shapes, tensor_dtypes, scalar_dtypes,
    attributes, output_tensor_indexes, precision_tolerances,
    absolute_precision, input_data_ranges, scalar_data_ranges,
    tensor_list_distribution

Target 13 columns (contract defined in ``schema/testcase_csv.json``)::

    testcase_name, op_name, stc_input_dtypes, other_compilation_params,
    stc_inputs, output_dtypes, stc_outputs, stc_input_formats, output_formats,
    stc_op_name, input_data_ranges, absolute_precision, error_message

**Format contract** — ``stc_input_dtypes``/``stc_inputs``/``stc_input_formats``
(and their ``output_*`` counterparts) MUST be valid Python tuple/list repr
strings parseable by ``ast.literal_eval``.  The downstream adapter
(``csv_to_testcases.py``) calls ``ast.literal_eval`` on these cells; a bare
``float32`` fails but a quoted ``('float32',)`` succeeds.

**Proto-aligned arrays** — ``stc_inputs``/``stc_input_dtypes``/
``stc_input_formats``/``input_data_ranges`` are equal-length, position-aligned
to the operator's proto inputs.  An absent optional input keeps its slot as a
bare ``None`` (mirrors cann-bench ``cases.csv`` ``null``) — the slot is NEVER
compacted away, because the harness binds golden/kernel inputs positionally.
The upstream ``tensor_view_shapes``/``tensor_dtypes`` already carry ``None`` at
the absent slot (produced by ``generate_test_cases.py``); this module only
preserves it.

Usage::

    python merge_test_cases.py \\
        --op-name foreach_norm \\
        --aclnn-name aclnnForeachNorm \\
        [--default-precision 1e-05] \\
        [--default-format ND] \\
        [--output 合并_测试用例.csv] \\
        [--testcase-dir testcases/] \\
        [--l0 aclnnForeachNorm_l0_test_cases.csv] \\
        [--l1 aclnnForeachNorm_l1_test_cases.csv] \\
        [--l2 aclnnForeachNorm_l2_test_cases.csv]
"""

from __future__ import annotations

import argparse
import ast
import csv
import re
import sys
from pathlib import Path


# ── helpers ────────────────────────────────────────────────────────────────

def _parse_output_indices(raw: str) -> set[int]:
    """Parse ``output_tensor_indexes`` like ``(4,5,)`` → ``{4, 5}``."""
    if not raw:
        return set()
    nums = re.findall(r"\d+", raw)
    return {int(n) for n in nums}


def _parse_top_level_items(field: str) -> list[str]:
    """Split a top-level tuple string into its items at depth 0.

    ``((3,3,),(2,488,),nan,(4,),)`` → ``['(3,3,)', '(2,488,)', 'nan', '(4,)']``
    ``('float32','float16','bfloat16',)`` → ``['float32', 'float16', 'bfloat16']``

    Handles both quoted dtype strings and parenthesised shape tuples.
    """
    if not field:
        return []
    s = field.strip()
    if s.startswith("(") and s.endswith(")"):
        s = s[1:-1]
    items: list[str] = []
    depth = 0
    in_quote = False
    start = 0
    for i, ch in enumerate(s):
        if ch == "'" and (i == 0 or s[i - 1] != "\\"):
            in_quote = not in_quote
        elif in_quote:
            continue
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            items.append(s[start:i].strip())
            start = i + 1
    last = s[start:].strip()
    if last:
        items.append(last)
    # Strip surrounding quotes from dtype tokens
    return [it.strip("'") for it in items]


def _is_nan_item(item) -> bool:
    """True when the item is the literal ``nan`` (output-shape sentinel)."""
    return isinstance(item, str) and item.strip() == "nan"


def _absent_norm(item):
    """``"None"`` token (缺省可选输入占位) → Python ``None``；其余原样返回。

    生成器把缺省可选输入渲染为裸 ``None``（shape/dtype/range 三个并行数组同
    位置），``_parse_top_level_items`` 读回是字符串 ``"None"``。这里还原成
    ``None``，使 ``_listify``/``_tuplify`` 输出裸 ``None``（下游按位置识别缺省）。
    """
    return None if item == "None" else item


def _tuplify(values: list) -> str:
    """``['float32']`` → ``"('float32',)"``; ``['a','b']`` → ``"('a','b',)"``.

    The trailing comma ensures ``ast.literal_eval`` produces a tuple even for a
    single element.  ``None`` (缺省可选输入占位) 渲染为**裸 None**——用 ``repr``
    天然得到 ``None``，非字符串 ``'None'``，下游按位置识别缺省位。
    """
    return f"({','.join(repr(v) for v in values)},)"


def _listify(values: list) -> str:
    """``['(3,3)']`` → ``"[(3,3)]"``；``[None, '(3,3)']`` → ``"[None,(3,3)]"``.

    形状条目是 repr 片段字符串；``None`` 占位（缺省可选输入）渲染为裸 ``None``。
    """
    return f"[{','.join('None' if v is None else v for v in values)}]"


# error_type 结构信号（L2 生成器显式填写的列）→ 人类可读 error_message。
# 优先走结构信号（§1.12/§2.12），不依赖 testcase_name 命名约定；未带 error_type
# 列的旧 CSV 才退回名字匹配兜底（§1.2 宽容兜底 + 可观测）。
_ERROR_MESSAGES = {
    "dtype_not_supported": "unsupported dtype",
    "dtype_combo_mismatch": "dtype combination mismatch",
    "dimension_overflow": "dimension exceeds maximum supported rank (8)",
    "format_not_supported": "unsupported format (only ND supported)",
    "shape_dimension_mismatch": "shape dimension mismatch",
    "empty_tensor": "empty tensor exception",
    "attr_special_value": "attribute special value exception",
    "attr_boundary_overflow": "attribute boundary overflow",
}


def _detect_error(row: dict[str, str]) -> str:
    error_type = (row.get("error_type") or "").strip()
    if error_type:
        return _ERROR_MESSAGES.get(error_type, "exception case")
    name = row.get("testcase_name", "")
    if "_dim_exception" in name:
        return "dimension exceeds maximum supported rank (8)"
    if "_format_exception" in name:
        return "unsupported format (only ND supported)"
    if "_exception" in name:
        return "exception case"
    return ""


# ── row conversion ─────────────────────────────────────────────────────────

def _normalize_data_ranges(raw: str) -> str:
    """Normalize an ``input_data_ranges`` cell to a Python-literal-safe string.

    Source CSVs from ``generate_test_cases.py`` emit raw ``inf``/``-inf``/``nan``
    tokens (without quotes) inside the range tuples; ``ast.literal_eval`` rejects
    these as bare names.  We quote them so the cell round-trips cleanly.
    """
    if not raw:
        return raw
    out = raw
    # Order matters: -inf before inf to avoid partial replacements.
    for token in ("-inf", "+inf", "inf", "nan"):
        # Quote the token only when it is NOT already inside a string literal.
        # Cheapest correct heuristic: replace bare token occurrences (not
        # preceded by a quote char).
        out = re.sub(rf"(?<!['\w]){re.escape(token)}(?![\w'])",
                     f"'{token}'", out)
    return out


def _row_to_unified(row: dict[str, str], op_name: str, aclnn_name: str,
                    default_precision: str, default_format: str) -> dict[str, str]:
    shapes_field = row.get("tensor_view_shapes", "") or ""
    dtypes_field = row.get("tensor_dtypes", "") or ""

    # Parse output_tensor_indexes to determine which indices are outputs.
    # For a multi-input operator like apply_rotary_pos_emb (4 inputs + 2 outputs),
    # output_tensor_indexes=(4,5) — indices 0-3 are inputs, 4-5 are outputs.
    # The old _split_two_entry heuristic only split at the *first* top-level comma,
    # which put all but the first shape into outputs — broken for multi-input ops.
    output_indices = _parse_output_indices(row.get("output_tensor_indexes", "") or "")

    all_shapes = _parse_top_level_items(shapes_field)
    all_dtypes = _parse_top_level_items(dtypes_field)

    n_outputs = len(output_indices)
    if n_outputs == 0 and all_shapes:
        # Fallback: no output_tensor_indexes — assume last 1 is output (single-output ops).
        # Build output_indices accordingly so the split logic below works correctly.
        n_outputs = 1
        output_indices = {len(all_shapes) - 1}

    # Split shapes into (inputs, outputs) by output_tensor_indexes.
    # Also handle the nan sentinel: when an output shape position is nan
    # (unknown/same-as-input), substitute ().
    x_shapes: list[str] = []
    y_shapes: list[str] = []
    x_dtypes: list[str] = []
    y_dtypes: list[str] = []

    has_nan_output = any(
        i in output_indices and _is_nan_item(all_shapes[i])
        for i in range(len(all_shapes))
    )

    if has_nan_output:
        # Output shapes are nan sentinel → use () placeholders and derive
        # input shapes as all non-output, non-nan items. Input-side None
        # placeholders (absent optional) are preserved in position.
        for i, s in enumerate(all_shapes):
            if i not in output_indices and not _is_nan_item(s):
                x_shapes.append(_absent_norm(s))
        y_shapes = ["()" for _ in range(n_outputs)]
    else:
        for i, s in enumerate(all_shapes):
            if i in output_indices:
                y_shapes.append(_absent_norm(s))
            else:
                x_shapes.append(_absent_norm(s))

    # Split dtypes analogously (None placeholders preserved in position).
    for i, d in enumerate(all_dtypes):
        if i in output_indices:
            y_dtypes.append(_absent_norm(d))
        else:
            x_dtypes.append(_absent_norm(d))

    n_outputs_final = len(y_dtypes)
    # stc_input_formats 与 stc_inputs 逐位对齐：缺省可选位置同样留 None，
    # 使下游按索引取 format 时不因压缩而错位。
    x_formats = [None if s is None else default_format for s in x_shapes]
    if not x_formats:
        x_formats = [default_format]

    error_msg = _detect_error(row)
    attrs = row.get("attributes", "") or ""
    input_ranges = _normalize_data_ranges(row.get("input_data_ranges", "") or "")
    precision = row.get("absolute_precision", "") or default_precision

    return {
        "testcase_name": row.get("testcase_name", ""),
        "op_name": op_name,
        "stc_input_dtypes": _tuplify(x_dtypes),
        "other_compilation_params": attrs,
        "stc_inputs": _listify(x_shapes),
        "output_dtypes": _tuplify(y_dtypes),
        "stc_outputs": _listify(y_shapes),
        "stc_input_formats": _tuplify(x_formats),
        "output_formats": _tuplify([default_format] * max(n_outputs_final, 1)),
        "stc_op_name": aclnn_name,
        "input_data_ranges": input_ranges,
        "absolute_precision": precision,
        "error_message": error_msg,
    }


# ── merge ───────────────────────────────────────────────────────────────────

TARGET_HEADER = [
    "testcase_name", "op_name", "stc_input_dtypes", "other_compilation_params",
    "stc_inputs", "output_dtypes", "stc_outputs", "stc_input_formats",
    "output_formats", "stc_op_name", "input_data_ranges", "absolute_precision",
    "error_message",
]


def merge(testcase_dir: Path, l0: str, l1: str, l2: str,
          op_name: str, aclnn_name: str,
          default_precision: str, default_format: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    levels = [("L0", l0), ("L1", l1)]  # L2 cases intentionally excluded

    for level, fname in levels:
        if not fname:  # 该级别未提供文件名 → 跳过（否则 path=dir/"" 即目录本身，
            # exists() 恒真 → open 目录抛 IsADirectoryError）
            continue
        path = testcase_dir / fname
        if not path.exists():
            print(f"[merge] skip missing: {path}", file=sys.stderr)
            continue
        n = 0
        with path.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                rows.append(_row_to_unified(
                    row, op_name, aclnn_name, default_precision, default_format))
                n += 1
        print(f"[merge] {level}: loaded {n} rows from {path.name}", file=sys.stderr)

    return rows


# ── main ────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Merge L0/L1/L2 test-case CSVs into 13-column format")
    parser.add_argument("--op-name", required=True,
                        help="Operator name (op_name column)")
    parser.add_argument("--aclnn-name", required=True,
                        help="ACLNN interface name (stc_op_name column)")
    parser.add_argument("--default-precision", default="1e-05",
                        help="Fallback absolute_precision (default: 1e-05)")
    parser.add_argument("--default-format", default="ND",
                        help="Input/output format (default: ND)")
    parser.add_argument("--output", default="合并_测试用例.csv",
                        help="Output CSV filename (default: 合并_测试用例.csv)")
    parser.add_argument("--testcase-dir", default="testcases",
                        help="Directory containing L0/L1/L2 CSVs (default: testcases)")
    parser.add_argument("--l0", default="",
                        help="L0 CSV filename (auto-detected if empty)")
    parser.add_argument("--l1", default="",
                        help="L1 CSV filename (auto-detected if empty)")
    parser.add_argument("--l2", default="",
                        help="L2 CSV filename (auto-detected if empty)")
    args = parser.parse_args()

    testcase_dir = Path(args.testcase_dir)
    if not testcase_dir.is_dir():
        print(f"ERROR: testcase directory not found: {testcase_dir}", file=sys.stderr)
        sys.exit(1)

    # Auto-detect level filenames when not explicitly given
    l0 = args.l0
    l1 = args.l1
    l2 = args.l2
    if not (l0 and l1 and l2):
        for csv_path in sorted(testcase_dir.glob("*.csv")):
            name = csv_path.name
            if not l0 and ("l0" in name.lower() or "L0" in name):
                l0 = name
            elif not l1 and ("l1" in name.lower() or "L1" in name):
                l1 = name
            elif not l2 and ("l2" in name.lower() or "L2" in name):
                l2 = name
    if not (l0 or l1 or l2):
        print("ERROR: no L0/L1/L2 CSV files found; specify --l0/--l1/--l2",
              file=sys.stderr)
        sys.exit(1)

    rows = merge(
        testcase_dir=testcase_dir,
        l0=l0, l1=l1, l2=l2,
        op_name=args.op_name,
        aclnn_name=args.aclnn_name,
        default_precision=args.default_precision,
        default_format=args.default_format,
    )

    if not rows:
        print("ERROR: no rows produced", file=sys.stderr)
        sys.exit(1)

    out_path = Path(args.output)
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=TARGET_HEADER)
        writer.writeheader()
        writer.writerows(rows)
    print(f"[merge] wrote {len(rows)} rows → {out_path.resolve()}", file=sys.stderr)


if __name__ == "__main__":
    main()
