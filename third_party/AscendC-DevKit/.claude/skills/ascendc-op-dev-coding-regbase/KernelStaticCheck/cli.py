#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Command-line entry point for KernelStaticCheck.

Recursively scans one or more directories (or individual files) containing
AscendC kernel source and reports RegBase/AscendC static-check results.

Typical usage:

    python3 -m KernelStaticCheck /path/to/op_kernel
    python3 -m KernelStaticCheck op_kernel.cpp --kernel-name add_custom
    python3 -m KernelStaticCheck ./ops --format json --strict

Exit codes:
    0  : all scanned sources passed the static checks.
    1  : one or more sources failed a static check (or a runtime error).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from .checker import StaticCheckReport, check_regbase_source

# Source extensions that may contain AscendC kernel code.
SOURCE_EXTENSIONS = (".cpp", ".h", ".hpp", ".cc", ".cxx", ".c")


def _auto_detect_kernel_name(source: str) -> Optional[str]:
    """Try to detect the kernel entry name from ``extern "C" __global__ ..."""
    match = re.search(
        r'extern\s+"C"\s+__global__\s+__aicore__\s+void\s+(\w+)\s*\(',
        source,
    )
    if match:
        return match.group(1)
    # Fallback: any __global__ __aicore__ void name(...)
    match = re.search(
        r'__global__\s+__aicore__\s+void\s+(\w+)\s*\(',
        source,
    )
    if match:
        return match.group(1)
    return None


def _collect_source_files(paths: Sequence[str], recursive: bool) -> List[Path]:
    """Collect all source files from the given paths."""
    files: List[Path] = []
    for p in paths:
        path = Path(p)
        if not path.exists():
            print(f"ERROR: path does not exist: {path}", file=sys.stderr)
            sys.exit(1)
        if path.is_file():
            if path.suffix in SOURCE_EXTENSIONS:
                files.append(path)
            else:
                print(
                    f"WARNING: skipping non-source file: {path}",
                    file=sys.stderr,
                )
        elif path.is_dir():
            if recursive:
                for ext in SOURCE_EXTENSIONS:
                    files.extend(path.rglob(f"*{ext}"))
            else:
                for ext in SOURCE_EXTENSIONS:
                    files.extend(path.glob(f"*{ext}"))
        else:
            print(f"WARNING: unsupported path type: {path}", file=sys.stderr)
    # Sort and de-duplicate while preserving order.
    seen = set()
    unique_files = []
    for f in files:
        resolved = f.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique_files.append(f)
    return unique_files


def _scan_file(
    file_path: Path,
    kernel_name: Optional[str],
) -> Tuple[Path, StaticCheckReport, Optional[str]]:
    """Read a single source file and run the static checker.

    Returns:
        A tuple of (file_path, report, detected_kernel_name).
    """
    with open(file_path, encoding="utf-8") as f:
        source = f.read()
    detected = _auto_detect_kernel_name(source)
    used_name = kernel_name or detected or "kernel"
    report = check_regbase_source(source, used_name, raise_on_failure=False)
    return file_path, report, detected


def _format_text(results: List[Tuple[Path, StaticCheckReport, Optional[str]]]) -> str:
    """Render a human-readable text report."""
    lines: List[str] = []
    total = len(results)
    failed = 0
    for file_path, report, detected in results:
        status = "PASS" if report.passed else "FAIL"
        lines.append(f"=== {file_path} [{status}] ===")
        if detected and not report.passed:
            lines.append(f"  (auto-detected kernel name: {detected})")
        if not report.passed:
            failed += 1
            for r in report.results:
                if not r.passed:
                    loc = f" (line {r.line_no})" if r.line_no is not None else ""
                    lines.append(f"  [FAIL] {r.name}{loc}: {r.message}")
        else:
            lines.append("  No RegBase static-check issues detected.")
        lines.append("")
    lines.append(f"Summary: {total - failed}/{total} source file(s) passed.")
    if failed:
        lines.append(f"         {failed} source file(s) failed.")
    return "\n".join(lines)


def _format_json(results: List[Tuple[Path, StaticCheckReport, Optional[str]]]) -> str:
    """Render a JSON report."""
    data = []
    for file_path, report, detected in results:
        data.append(
            {
                "file": str(file_path),
                "passed": report.passed,
                "detected_kernel_name": detected,
                "checks": [
                    {
                        "name": r.name,
                        "passed": r.passed,
                        "message": r.message,
                        "line_no": r.line_no,
                    }
                    for r in report.results
                ],
            }
        )
    return json.dumps(data, indent=2, ensure_ascii=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="KernelStaticCheck",
        description=(
            "Recursively scan AscendC kernel source files for RegBase "
            "static-check compliance."
        ),
    )
    parser.add_argument(
        "paths",
        nargs="+",
        help=(
            "One or more source files or directories to scan. "
            "Directories are searched for *.cpp / *.h / *.hpp / *.cc / *.cxx / *.c."
        ),
    )
    parser.add_argument(
        "-k",
        "--kernel-name",
        default=None,
        help=(
            "Kernel entry name to use for all files. If omitted, the checker "
            "tries to auto-detect the name from each file's "
            "``extern 'C' __global__ __aicore__ void ...`` entry."
        ),
    )
    parser.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        default=True,
        help="Recursively scan directories (default: True).",
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="Do not recurse into subdirectories.",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Exit with a non-zero code if any source file fails a check. "
            "This is the default behavior."
        ),
    )
    parser.add_argument(
        "--no-strict",
        action="store_true",
        help=(
            "Always exit with 0, even if failures are found. "
            "Useful when only the report is needed."
        ),
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Print nothing to stdout; only set the exit code.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    recursive = not args.no_recursive if args.no_recursive else args.recursive
    files = _collect_source_files(args.paths, recursive)

    if not files:
        print("No source files found.", file=sys.stderr)
        return 1

    results = []
    for file_path in sorted(files):
        try:
            results.append(_scan_file(file_path, args.kernel_name))
        except Exception as exc:  # pragma: no cover - defensive
            print(
                f"ERROR: failed to scan {file_path}: {exc}",
                file=sys.stderr,
            )
            return 1

    has_failures = any(not report.passed for _, report, _ in results)

    if not args.quiet:
        if args.format == "json":
            print(_format_json(results))
        else:
            print(_format_text(results))

    if args.no_strict:
        return 0
    return 1 if has_failures else 0


if __name__ == "__main__":
    sys.exit(main())
