#!/usr/bin/env python3
"""
Analyze in-core synchronization SetFlag/WaitFlag risks for a file or directory.

Scope:
- Parses SetFlag/WaitFlag (including SET_FLAG/WAIT_FLAG macros)
- Builds per-function event-channel state machines
- Produces TOP-N suspicious functions and signals

This is a lightweight static analyzer by design (high recall, heuristic ranking).
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


CPP_EXTS = {".h", ".hpp", ".hh", ".hxx", ".c", ".cc", ".cpp", ".cxx", ".cu"}
CONTROL_KEYWORDS = {"if", "for", "while", "switch", "catch"}
LIFECYCLE_FN_PATTERNS = (
    "AllocEventID",
    "FreeEventID",
    "InitEventID",
    "DeInitEventID",
)
WRAPPER_FN_EXACT = {
    "SetFlag",
    "WaitFlag",
    "CrossCoreSetFlag",
    "CrossCoreWaitFlag",
}
AGGRESSIVE_LIFECYCLE_RE = re.compile(r".*(Alloc|Free).*(Event|Flag).*", re.IGNORECASE)

SETWAIT_RE = re.compile(
    r"\b(?P<api>SetFlag|WaitFlag)\s*<\s*(?:AscendC::)?HardEvent::(?P<he>[A-Za-z0-9_]+)\s*>\s*\((?P<ev>[^)]*)\)"
)
MACRO_RE = re.compile(
    r"\b(?P<api>SET_FLAG|WAIT_FLAG)\s*\(\s*(?P<trig>[A-Za-z0-9_]+)\s*,\s*(?P<waiter>[A-Za-z0-9_]+)\s*,\s*(?P<ev>[^)]*)\)"
)


@dataclass
class Op:
    api: str  # SetFlag / WaitFlag
    hard_event: str
    event_expr: str
    line: int
    in_loop: bool = False
    loop_depth: int = 0
    in_if: bool = False


@dataclass
class SignalRisk:
    key: str
    hard_event: str
    event_expr: str
    score: int = 0
    hard_wait_on_unset: int = 0
    hard_double_set: int = 0
    risk_entry_wait: int = 0
    risk_imbalance: int = 0
    risk_split_contract: int = 0
    risk_loop_mismatch: int = 0
    set_count: int = 0
    wait_count: int = 0
    set_in_loop: int = 0
    wait_in_loop: int = 0
    set_max_loop_depth: int = 0
    wait_max_loop_depth: int = 0
    has_if_guard: bool = False
    issue_types: List[str] = field(default_factory=list)
    evidence_lines: List[int] = field(default_factory=list)


@dataclass
class FunctionRisk:
    file: str
    function: str
    start_line: int
    end_line: int
    score: int = 0
    ops_total: int = 0
    hard_wait_on_unset: int = 0
    hard_double_set: int = 0
    risk_entry_wait: int = 0
    risk_imbalance: int = 0
    signals: List[SignalRisk] = field(default_factory=list)


@dataclass
class FunctionBlock:
    name: str
    start_line: int
    end_line: int
    ops: List[Op]
    loop_ranges: List[Tuple[int, int]] = field(default_factory=list)


def strip_inline_comments(line: str, in_block_comment: bool) -> Tuple[str, bool]:
    s = line
    if in_block_comment:
        end = s.find("*/")
        if end == -1:
            return "", True
        s = s[end + 2 :]
        in_block_comment = False

    out = []
    i = 0
    while i < len(s):
        if i + 1 < len(s) and s[i : i + 2] == "/*":
            end = s.find("*/", i + 2)
            if end == -1:
                return "".join(out), True
            i = end + 2
            continue
        if i + 1 < len(s) and s[i : i + 2] == "//":
            break
        out.append(s[i])
        i += 1
    return "".join(out), in_block_comment


def looks_like_function_header(header: str) -> bool:
    h = " ".join(header.strip().split())
    if "(" not in h or ")" not in h or "{" not in h:
        return False
    if h.endswith(";"):
        return False
    low = h.lower()
    if low.startswith(("class ", "struct ", "namespace ", "enum ", "union ", "typedef ")):
        return False
    return True


def extract_function_name(header: str) -> Optional[str]:
    h = " ".join(header.strip().split())
    # Match only callable signatures that terminate with '{'.
    matches = re.findall(
        r"([~A-Za-z_][\w:]*)\s*\([^;{}()]*\)\s*(?:const\s*)?(?:noexcept\s*)?\{",
        h,
    )
    if not matches:
        return None
    blacklist = {
        "__attribute__",
        "constexpr",
        "decltype",
        "sizeof",
        "alignof",
        "if",
        "for",
        "while",
        "switch",
        "catch",
    }
    name = None
    for cand in matches:
        short = cand.split("::")[-1]
        if short in blacklist:
            continue
        name = cand
    if not name:
        return None
    short = name.split("::")[-1]
    if short in CONTROL_KEYWORDS:
        return None
    return name


def parse_ops_from_text(text: str, lineno: int) -> List[Op]:
    ops: List[Op] = []
    for m in SETWAIT_RE.finditer(text):
        api = m.group("api")
        he = m.group("he")
        ev = " ".join(m.group("ev").strip().split())
        ops.append(Op(api=api, hard_event=he, event_expr=ev, line=lineno))

    for m in MACRO_RE.finditer(text):
        api = "SetFlag" if m.group("api") == "SET_FLAG" else "WaitFlag"
        he = f"{m.group('trig')}_{m.group('waiter')}"
        ev = " ".join(m.group("ev").strip().split())
        ops.append(Op(api=api, hard_event=he, event_expr=ev, line=lineno))

    return ops


def line_in_ranges(lineno: int, ranges: List[Tuple[int, int]]) -> bool:
    for s, e in ranges:
        if s <= lineno <= e:
            return True
    return False


def line_loop_depth(lineno: int, ranges: List[Tuple[int, int]]) -> int:
    depth = 0
    for s, e in ranges:
        if s <= lineno <= e:
            depth += 1
    return depth


def detect_loop_ranges(lines_with_no: List[Tuple[int, str]]) -> List[Tuple[int, int]]:
    loop_ranges: List[Tuple[int, int]] = []
    stack: List[Tuple[str, int]] = []  # (kind, start_line)
    pending_loop = False

    for lineno, clean in lines_with_no:
        line = clean.strip()
        has_loop_hdr = bool(re.search(r"\b(for|while)\s*\(", line))
        opens = clean.count("{")
        closes = clean.count("}")

        if has_loop_hdr and opens == 0:
            pending_loop = True

        for i in range(opens):
            kind = "block"
            if pending_loop:
                kind = "loop"
                pending_loop = False
            elif has_loop_hdr and i == 0:
                kind = "loop"
            stack.append((kind, lineno))

        for _ in range(closes):
            if not stack:
                break
            kind, start = stack.pop()
            if kind == "loop":
                loop_ranges.append((start, lineno))

    return loop_ranges


def detect_if_ranges(lines_with_no: List[Tuple[int, str]]) -> List[Tuple[int, int]]:
    if_ranges: List[Tuple[int, int]] = []
    stack: List[Tuple[str, int]] = []  # (kind, start_line)
    pending_if = False

    for lineno, clean in lines_with_no:
        line = clean.strip()
        has_if_hdr = bool(re.search(r"\bif\s*\(", line))
        opens = clean.count("{")
        closes = clean.count("}")

        if has_if_hdr and opens == 0:
            pending_if = True

        for i in range(opens):
            kind = "block"
            if pending_if:
                kind = "if"
                pending_if = False
            elif has_if_hdr and i == 0:
                kind = "if"
            stack.append((kind, lineno))

        for _ in range(closes):
            if not stack:
                break
            kind, start = stack.pop()
            if kind == "if":
                if_ranges.append((start, lineno))

    return if_ranges


def parse_functions(path: Path) -> List[FunctionBlock]:
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    functions: List[FunctionBlock] = []

    in_block_comment = False
    brace_depth = 0
    current_fn: Optional[Dict] = None
    recent: List[Tuple[int, str]] = []
    stmt_buf = ""

    for idx, raw in enumerate(lines, start=1):
        clean, in_block_comment = strip_inline_comments(raw, in_block_comment)
        recent.append((idx, clean))
        if len(recent) > 8:
            recent.pop(0)

        open_cnt = clean.count("{")
        close_cnt = clean.count("}")

        if current_fn is None and "{" in clean:
            header = "\n".join(t for _, t in recent)
            if looks_like_function_header(header):
                name = extract_function_name(header)
                if name:
                    current_fn = {
                        "name": name,
                        "start": idx,
                        "ops": [],
                        "start_depth": brace_depth + open_cnt - close_cnt,
                        "body_lines": [],
                    }

        if current_fn is not None:
            current_fn["body_lines"].append((idx, clean))
            stmt_buf += " " + clean.strip()
            if ";" in clean:
                current_fn["ops"].extend(parse_ops_from_text(stmt_buf, idx))
                stmt_buf = ""

        brace_depth += open_cnt - close_cnt

        if current_fn is not None and brace_depth < current_fn["start_depth"]:
            if stmt_buf.strip():
                current_fn["ops"].extend(parse_ops_from_text(stmt_buf, idx))
                stmt_buf = ""
            loop_ranges = detect_loop_ranges(current_fn["body_lines"])
            if_ranges = detect_if_ranges(current_fn["body_lines"])
            for op in current_fn["ops"]:
                op.in_loop = line_in_ranges(op.line, loop_ranges)
                op.loop_depth = line_loop_depth(op.line, loop_ranges)
                op.in_if = line_in_ranges(op.line, if_ranges)
            functions.append(
                FunctionBlock(
                    name=current_fn["name"],
                    start_line=current_fn["start"],
                    end_line=idx,
                    ops=current_fn["ops"],
                    loop_ranges=loop_ranges,
                )
            )
            current_fn = None

    return functions


def analyze_function(path: Path, fn: FunctionBlock) -> Optional[FunctionRisk]:
    if not fn.ops:
        return None

    signals: Dict[str, SignalRisk] = {}
    state: Dict[str, str] = {}
    first_seen: Dict[str, bool] = {}

    for op in fn.ops:
        key = f"{op.hard_event}::{op.event_expr}"
        if key not in signals:
            signals[key] = SignalRisk(
                key=key,
                hard_event=op.hard_event,
                event_expr=op.event_expr,
            )
            state[key] = "UNKNOWN"
            first_seen[key] = True

        sig = signals[key]
        if op.api == "SetFlag":
            sig.set_count += 1
            if op.in_if:
                sig.has_if_guard = True
            if op.in_loop:
                sig.set_in_loop += 1
                sig.set_max_loop_depth = max(sig.set_max_loop_depth, op.loop_depth)
            if state[key] == "SET":
                sig.hard_double_set += 1
                sig.score += 30
                if "DOUBLE_SET" not in sig.issue_types:
                    sig.issue_types.append("DOUBLE_SET")
                sig.evidence_lines.append(op.line)
            state[key] = "SET"
        else:
            sig.wait_count += 1
            if op.in_if:
                sig.has_if_guard = True
            if op.in_loop:
                sig.wait_in_loop += 1
                sig.wait_max_loop_depth = max(sig.wait_max_loop_depth, op.loop_depth)
            if state[key] == "UNSET":
                sig.hard_wait_on_unset += 1
                sig.score += 50
                if "WAIT_ON_UNSET" not in sig.issue_types:
                    sig.issue_types.append("WAIT_ON_UNSET")
                sig.evidence_lines.append(op.line)
            elif state[key] == "UNKNOWN":
                sig.risk_entry_wait += 1
                # Unknown->Wait may be legitimate for split producer/consumer contract.
                sig.score += 4
                if "ENTRY_WAIT_UNKNOWN" not in sig.issue_types:
                    sig.issue_types.append("ENTRY_WAIT_UNKNOWN")
                sig.evidence_lines.append(op.line)
            state[key] = "UNSET"

        first_seen[key] = False

    for sig in signals.values():
        imbalance = abs(sig.set_count - sig.wait_count)
        if imbalance > 0:
            sig.risk_imbalance = imbalance
            # Stronger penalty for mixed-function imbalance; lighter for pure producer/consumer split.
            if sig.set_count > 0 and sig.wait_count > 0:
                sig.score += imbalance * 8
                if "SET_WAIT_IMBALANCE" not in sig.issue_types:
                    sig.issue_types.append("SET_WAIT_IMBALANCE")
            else:
                sig.risk_split_contract = imbalance
                sig.score += imbalance * 2
                if "SPLIT_CONTRACT" not in sig.issue_types:
                    sig.issue_types.append("SPLIT_CONTRACT")

        # Loop-aware risk: Wait inside loop but Set only outside loop (or much fewer inside-loop sets).
        if sig.wait_in_loop > 0 and sig.set_in_loop == 0 and sig.set_count > 0:
            sig.risk_loop_mismatch += 1
            # High-confidence hang risk: consumer in loop, producer only outside loop.
            sig.score += 100
            if "LOOP_WAIT_SET_SCOPE_MISMATCH" not in sig.issue_types:
                sig.issue_types.append("LOOP_WAIT_SET_SCOPE_MISMATCH")
            sig.evidence_lines.append(sig.evidence_lines[0] if sig.evidence_lines else 0)
        elif sig.wait_in_loop > sig.set_in_loop and sig.set_in_loop > 0:
            sig.risk_loop_mismatch += sig.wait_in_loop - sig.set_in_loop
            sig.score += 20 * (sig.wait_in_loop - sig.set_in_loop)
            if "LOOP_WAIT_SET_COUNT_MISMATCH" not in sig.issue_types:
                sig.issue_types.append("LOOP_WAIT_SET_COUNT_MISMATCH")

        # Strong signal: waits happen deeper in nested loops than sets.
        if sig.wait_max_loop_depth > sig.set_max_loop_depth and sig.wait_in_loop > 0:
            sig.risk_loop_mismatch += sig.wait_max_loop_depth - sig.set_max_loop_depth
            sig.score += 80 * (sig.wait_max_loop_depth - sig.set_max_loop_depth)
            if "LOOP_DEPTH_MISMATCH" not in sig.issue_types:
                sig.issue_types.append("LOOP_DEPTH_MISMATCH")
        elif sig.set_max_loop_depth > sig.wait_max_loop_depth and sig.wait_in_loop > 0:
            sig.risk_loop_mismatch += sig.set_max_loop_depth - sig.wait_max_loop_depth
            sig.score += 80 * (sig.set_max_loop_depth - sig.wait_max_loop_depth)
            if "LOOP_DEPTH_MISMATCH" not in sig.issue_types:
                sig.issue_types.append("LOOP_DEPTH_MISMATCH")

        # Symmetric high-risk case: wait is outside loop but set happens in loop.
        # This often means one wait is trying to consume multiple per-iteration sets.
        if sig.set_in_loop > 0 and sig.wait_in_loop == 0 and sig.wait_count > 0:
            sig.risk_loop_mismatch += 1
            sig.score += 100
            if "LOOP_WAIT_OUTSIDE_SET_INSIDE" not in sig.issue_types:
                sig.issue_types.append("LOOP_WAIT_OUTSIDE_SET_INSIDE")

        # If loop-mismatch signals are guarded by if-branches, request confirmation and lower confidence.
        if sig.risk_loop_mismatch > 0 and sig.has_if_guard:
            sig.score = int(sig.score * 0.4)
            if "CONFIRM_NEEDED" not in sig.issue_types:
                sig.issue_types.append("CONFIRM_NEEDED")

    # Local consistency rule:
    # If the function has some well-paired signals, but also has single-sided signal(s),
    # treat the single-sided ones as high-risk likely regressions.
    has_paired_signal = any(s.set_count > 0 and s.wait_count > 0 for s in signals.values())
    if has_paired_signal:
        for sig in signals.values():
            if (sig.set_count > 0 and sig.wait_count == 0) or (sig.wait_count > 0 and sig.set_count == 0):
                sig.score += 70
                if "LOCAL_UNPAIRED_SIGNAL" not in sig.issue_types:
                    sig.issue_types.append("LOCAL_UNPAIRED_SIGNAL")

    fr = FunctionRisk(
        file=str(path),
        function=fn.name,
        start_line=fn.start_line,
        end_line=fn.end_line,
        ops_total=len(fn.ops),
        signals=list(signals.values()),
    )

    for sig in fr.signals:
        fr.score += sig.score
        fr.hard_wait_on_unset += sig.hard_wait_on_unset
        fr.hard_double_set += sig.hard_double_set
        fr.risk_entry_wait += sig.risk_entry_wait
        fr.risk_imbalance += sig.risk_imbalance

    # Function-level boost for loop-mismatch red flags.
    max_loop_mismatch = max((s.risk_loop_mismatch for s in fr.signals), default=0)
    if max_loop_mismatch > 0:
        fr.score += 60 * max_loop_mismatch

    # Small complexity bonus to prioritize dense functions when risk ties.
    fr.score += min(10, fr.ops_total // 4)

    return fr


def collect_files(target: Path) -> List[Path]:
    if target.is_file():
        return [target]
    files: List[Path] = []
    for p in target.rglob("*"):
        if p.is_file() and p.suffix in CPP_EXTS:
            files.append(p)
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze in-core SetFlag/WaitFlag risks and report TOP-N.")
    parser.add_argument("input", help="Input file or directory")
    parser.add_argument("--topn", type=int, default=10, help="Top-N items for functions/signals")
    parser.add_argument("--md-out", default="", help="Optional markdown report path")
    parser.add_argument("--json-out", default="", help="Optional JSON output path")
    parser.add_argument(
        "--include-lifecycle",
        action="store_true",
        help="Include lifecycle helper functions (AllocEventID/FreeEventID...) in Top-N",
    )
    args = parser.parse_args()

    target = Path(args.input)
    if not target.exists():
        raise SystemExit(f"Input not found: {target}")

    files = collect_files(target)
    if not files:
        raise SystemExit("No source files found under input path")

    function_results: List[FunctionRisk] = []
    signal_global: Dict[str, Dict] = {}

    for fp in files:
        try:
            functions = parse_functions(fp)
        except Exception:
            continue

        for fn in functions:
            fr = analyze_function(fp, fn)
            if fr is None:
                continue
            function_results.append(fr)

            for sig in fr.signals:
                g = signal_global.setdefault(
                    sig.key,
                    {
                        "key": sig.key,
                        "hard_event": sig.hard_event,
                        "event_expr": sig.event_expr,
                        "score": 0,
                        "hard_wait_on_unset": 0,
                        "hard_double_set": 0,
                        "risk_entry_wait": 0,
                        "risk_imbalance": 0,
                        "functions": [],
                        "evidence_lines": [],
                    },
                )
                g["score"] += sig.score
                g["hard_wait_on_unset"] += sig.hard_wait_on_unset
                g["hard_double_set"] += sig.hard_double_set
                g["risk_entry_wait"] += sig.risk_entry_wait
                g["risk_imbalance"] += sig.risk_imbalance
                if fr.function not in g["functions"]:
                    g["functions"].append(fr.function)
                for ln in sig.evidence_lines[:3]:
                    g["evidence_lines"].append(f"{fp}:{ln}")

    function_results.sort(key=lambda x: x.score, reverse=True)
    if not args.include_lifecycle:
        function_results = [
            fr
            for fr in function_results
            if not any(pat in fr.function for pat in LIFECYCLE_FN_PATTERNS)
            and fr.function.split("::")[-1] not in WRAPPER_FN_EXACT
            and not AGGRESSIVE_LIFECYCLE_RE.match(fr.function.split("::")[-1])
        ]

    topn = max(1, args.topn)
    top_funcs = function_results[:topn]

    print("=" * 100)
    print("In-core Sync Risk TOP Functions")
    print("=" * 100)
    if not top_funcs:
        print("No functions with SetFlag/WaitFlag found.")
    for i, fr in enumerate(top_funcs, start=1):
        print(
            f"{i:02d}. score={fr.score:3d} | ops={fr.ops_total:3d} | "
            f"hard(wait_unset={fr.hard_wait_on_unset}, double_set={fr.hard_double_set}) | "
            f"risk(entry_wait={fr.risk_entry_wait}, imbalance={fr.risk_imbalance})"
        )
        print(f"    {fr.function} [{fr.file}:{fr.start_line}]")
        sigs = sorted(fr.signals, key=lambda s: s.score, reverse=True)
        shown = 0
        for sig in sigs:
            if sig.score <= 0:
                continue
            shown += 1
            print(
                f"      - signal={sig.hard_event}::{sig.event_expr} | score={sig.score} "
                f"(hard_wait_unset={sig.hard_wait_on_unset}, hard_double_set={sig.hard_double_set}, "
                f"entry_wait={sig.risk_entry_wait}, imbalance={sig.risk_imbalance}, "
                f"loop_mismatch={sig.risk_loop_mismatch})"
            )
            if sig.issue_types:
                print(f"        issue_types={','.join(sig.issue_types)}")
            if shown >= 5:
                break
        if shown == 0:
            print("      - signal=<none with positive risk score>")

    print()
    print("=" * 100)
    print("Summary")
    print("=" * 100)
    print(f"functions_scanned={len(function_results)}")
    print(f"topn={topn}")
    print(f"lifecycle_filtered={'no' if args.include_lifecycle else 'yes'}")

    if args.md_out:
        md_lines: List[str] = []
        md_lines.append("# In-core Sync Risk Report")
        md_lines.append("")
        md_lines.append("## Summary")
        md_lines.append(f"- input: `{target}`")
        md_lines.append(f"- files_scanned: `{len(files)}`")
        md_lines.append(f"- functions_scanned: `{len(function_results)}`")
        md_lines.append(f"- topn: `{topn}`")
        md_lines.append(
            f"- lifecycle_filtered: `{'no' if args.include_lifecycle else 'yes'}`"
        )
        md_lines.append("")
        md_lines.append("## Top Functions")
        if not top_funcs:
            md_lines.append("- No functions with SetFlag/WaitFlag found.")
        else:
            for i, fr in enumerate(top_funcs, start=1):
                md_lines.append(
                    f"### {i}. `{fr.function}` ({fr.score})"
                )
                md_lines.append(
                    f"- location: `{fr.file}:{fr.start_line}`"
                )
                md_lines.append(
                    f"- ops: `{fr.ops_total}`, hard(wait_unset={fr.hard_wait_on_unset}, double_set={fr.hard_double_set}), "
                    f"risk(entry_wait={fr.risk_entry_wait}, imbalance={fr.risk_imbalance})"
                )
                sigs = [s for s in sorted(fr.signals, key=lambda x: x.score, reverse=True) if s.score > 0][:5]
                if not sigs:
                    md_lines.append("- suspicious_signals: none")
                else:
                    md_lines.append("- suspicious_signals:")
                    for s in sigs:
                        md_lines.append(
                            f"  - `{s.hard_event}::{s.event_expr}` score={s.score} "
                            f"(hard_wait_unset={s.hard_wait_on_unset}, hard_double_set={s.hard_double_set}, "
                            f"entry_wait={s.risk_entry_wait}, imbalance={s.risk_imbalance})"
                        )
                        if s.issue_types:
                            md_lines.append(f"    - issue_types: `{', '.join(s.issue_types)}`")
                md_lines.append("")

        md_path = Path(args.md_out)
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text("\n".join(md_lines), encoding="utf-8")
        print(f"Markdown report written to: {md_path}")

    if args.json_out:
        out = {
            "input": str(target),
            "files_scanned": len(files),
            "functions_analyzed": len(function_results),
            "top_functions": [
                {
                    "file": fr.file,
                    "function": fr.function,
                    "start_line": fr.start_line,
                    "end_line": fr.end_line,
                    "score": fr.score,
                    "ops_total": fr.ops_total,
                    "hard_wait_on_unset": fr.hard_wait_on_unset,
                    "hard_double_set": fr.hard_double_set,
                    "risk_entry_wait": fr.risk_entry_wait,
                    "risk_imbalance": fr.risk_imbalance,
                    "suspicious_signals": [
                        {
                            "hard_event": s.hard_event,
                            "event_expr": s.event_expr,
                            "score": s.score,
                            "hard_wait_on_unset": s.hard_wait_on_unset,
                            "hard_double_set": s.hard_double_set,
                            "risk_entry_wait": s.risk_entry_wait,
                            "risk_imbalance": s.risk_imbalance,
                            "risk_loop_mismatch": s.risk_loop_mismatch,
                            "set_in_loop": s.set_in_loop,
                            "wait_in_loop": s.wait_in_loop,
                            "issue_types": s.issue_types,
                            "evidence_lines": s.evidence_lines[:8],
                        }
                        for s in sorted(fr.signals, key=lambda x: x.score, reverse=True)
                        if s.score > 0
                    ],
                }
                for fr in top_funcs
            ],
        }
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON report written to: {out_path}")


if __name__ == "__main__":
    main()
