#!/usr/bin/env python3
"""Conservative static risk scanner for A5 RegBase/VF VECTOR_ERROR.

The scanner is intentionally device-independent and read-only with respect to
the operator sources.  It does not attempt to prove a root cause: every item is
reported as ``candidate`` or ``suspected`` for a later controlled experiment.
"""

from __future__ import annotations

import argparse
import bisect
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = "1.0"
SOURCE_SUFFIXES = {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx"}
EXCLUDED_DIR_NAMES = {
    ".cache",
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    "artifacts",
    "build",
    "build_out",
    "cmake-build",
    "dist",
    "install",
    "output",
    "outputs",
}
EXCLUDED_DIR_PREFIXES = ("cmake-build-",)

API_REFERENCE = {
    "gm_ub_transport": "A5-RegBase/DataCopy-TQue; verify current 910D/CANN API",
    "ub_reg_load_store": "A5-RegBase/load_store; verify current 910D/CANN API",
    "mask_tail": "A5-RegBase/mask_reg; verify dtype-specific VL with current 910D/CANN API",
    "address_generation": "A5-RegBase/addr_reg; verify element units with current 910D/CANN API",
    "layout_cast_dist": "A5-RegBase/RB-CAST-R1,RB-LD-R1; verify current 910D/CANN API",
    "vf_call_abi": "A5-RegBase/simd_vf_basics; verify current 910D/CANN API",
    "incore_sync": "A5-RegBase/local_mem_bar; verify current 910D/CANN API",
    "queue_lifecycle": "A5-RegBase/TQue-lifecycle; verify current 910D/CANN API",
    "crosscore_tscm": "A5-RegBase/CrossCore-TSCM; verify current 910D/CANN API",
    "tiling_boundary": "A5-RegBase/tail-empty-core boundary review",
}

DOMAIN_BY_SUBTYPE = {
    "gm_ub_transport": "MTE",
    "ub_reg_load_store": "VF_MEMORY",
    "mask_tail": "VF_MASK",
    "address_generation": "ADDRESS",
    "layout_cast_dist": "VF_LAYOUT",
    "vf_call_abi": "VF_ABI",
    "incore_sync": "VF_SYNC",
    "queue_lifecycle": "QUEUE",
    "crosscore_tscm": "CROSS_CORE_SYNC",
    "tiling_boundary": "TILING",
}


@dataclass(frozen=True)
class Call:
    name: str
    start: int
    end: int
    line: int
    args: tuple[str, ...]


@dataclass(frozen=True)
class VfScope:
    kind: str
    name: str
    start: int
    body_start: int
    end: int
    line: int
    signature: str
    params: str


def _mask_non_code(text: str) -> str:
    """Replace comments and string/character literals, preserving newlines."""
    out = list(text)
    state = "code"
    quote = ""
    i = 0
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if state == "code":
            if ch == "/" and nxt == "/":
                out[i] = out[i + 1] = " "
                state = "line_comment"
                i += 2
                continue
            if ch == "/" and nxt == "*":
                out[i] = out[i + 1] = " "
                state = "block_comment"
                i += 2
                continue
            if ch in {'"', "'"}:
                quote = ch
                out[i] = " "
                state = "literal"
                i += 1
                continue
        elif state == "line_comment":
            if ch == "\n":
                state = "code"
            else:
                out[i] = " "
        elif state == "block_comment":
            if ch == "*" and nxt == "/":
                out[i] = out[i + 1] = " "
                state = "code"
                i += 2
                continue
            if ch != "\n":
                out[i] = " "
        else:
            if ch == "\\" and nxt:
                out[i] = " "
                if nxt != "\n":
                    out[i + 1] = " "
                i += 2
                continue
            if ch == quote:
                out[i] = " "
                state = "code"
            elif ch != "\n":
                out[i] = " "
        i += 1
    return "".join(out)


def _line_starts(text: str) -> list[int]:
    starts = [0]
    starts.extend(i + 1 for i, char in enumerate(text) if char == "\n")
    return starts


def _line_number(starts: Sequence[int], offset: int) -> int:
    return bisect.bisect_right(starts, offset)


def _matching(text: str, start: int, opening: str, closing: str) -> int:
    depth = 0
    for pos in range(start, len(text)):
        char = text[pos]
        if char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return pos
    return -1


def _split_args(args: str) -> tuple[str, ...]:
    parts: list[str] = []
    start = 0
    depths = {"(": 0, "[": 0, "{": 0, "<": 0}
    closes = {")": "(", "]": "[", "}": "{", ">": "<"}
    for i, char in enumerate(args):
        if char in depths:
            depths[char] += 1
        elif char in closes and depths[closes[char]] > 0:
            depths[closes[char]] -= 1
        elif char == "," and not any(depths.values()):
            part = args[start:i].strip()
            if part:
                parts.append(part)
            start = i + 1
    final = args[start:].strip()
    if final:
        parts.append(final)
    return tuple(parts)


def _find_calls(code: str, names: Iterable[str], starts: Sequence[int]) -> list[Call]:
    escaped = "|".join(sorted((re.escape(n) for n in names), key=len, reverse=True))
    pattern = re.compile(
        rf"(?<![\w])(?P<name>{escaped})\s*(?:<[^;(){{}}]*>)?\s*\("
    )
    calls: list[Call] = []
    for match in pattern.finditer(code):
        open_pos = code.find("(", match.start(), match.end())
        close_pos = _matching(code, open_pos, "(", ")")
        if close_pos < 0:
            continue
        calls.append(Call(
            name=match.group("name"),
            start=match.start(),
            end=close_pos + 1,
            line=_line_number(starts, match.start()),
            args=_split_args(code[open_pos + 1:close_pos]),
        ))
    return calls


def _find_vf_scopes(code: str, starts: Sequence[int]) -> list[VfScope]:
    scopes: list[VfScope] = []
    annotation = re.compile(r"\b__(simd|simt)_vf__\b")
    for match in annotation.finditer(code):
        semi = code.find(";", match.end())
        body = code.find("{", match.end())
        if body < 0 or (semi >= 0 and semi < body):
            continue
        end = _matching(code, body, "{", "}")
        if end < 0:
            continue
        signature = code[match.start():body]
        name_match = re.search(
            r"(?:inline\s+)?(?:[\w:<>]+\s+)+(?P<name>\w+)\s*\(",
            signature,
        )
        name = name_match.group("name") if name_match else "<anonymous_vf>"
        open_pos = signature.find("(", name_match.end("name") if name_match else 0)
        close_pos = (
            _matching(signature, open_pos, "(", ")") if open_pos >= 0 else -1
        )
        params = signature[open_pos + 1:close_pos] if close_pos >= 0 else ""
        scopes.append(VfScope(
            kind=match.group(1),
            name=name,
            start=match.start(),
            body_start=body,
            end=end + 1,
            line=_line_number(starts, match.start()),
            signature=signature,
            params=params,
        ))
    return scopes


def _scope_for(offset: int, scopes: Sequence[VfScope]) -> VfScope | None:
    return next((scope for scope in scopes if scope.start <= offset < scope.end), None)


def _excluded(path: Path, root: Path) -> bool:
    try:
        parts = path.relative_to(root).parts[:-1]
    except ValueError:
        parts = path.parts[:-1]
    for part in parts:
        if part in EXCLUDED_DIR_NAMES:
            return True
        if any(part.startswith(prefix) for prefix in EXCLUDED_DIR_PREFIXES):
            return True
    return False


def collect_sources(
    operator_dir: Path | None,
    explicit_sources: Sequence[Path] | None,
) -> tuple[Path, list[Path]]:
    if operator_dir is not None:
        root = operator_dir.resolve()
        if not root.is_dir():
            raise ValueError(f"operator_dir is not a directory: {operator_dir}")
        files = [
            path.resolve()
            for path in root.rglob("*")
            if path.is_file()
            and path.suffix.lower() in SOURCE_SUFFIXES
            and not _excluded(path, root)
        ]
    else:
        resolved = [path.resolve() for path in explicit_sources or ()]
        if not resolved:
            raise ValueError("at least one source file is required")
        invalid = [
            str(path) for path in resolved
            if not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES
        ]
        if invalid:
            raise ValueError(f"invalid source files: {', '.join(invalid)}")
        common = Path(__import__("os").path.commonpath([str(p.parent) for p in resolved]))
        root = common.resolve()
        files = [path for path in resolved if not _excluded(path, root)]
    return root, sorted(set(files), key=lambda path: path.as_posix())


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def _source_line(original: str, line: int) -> str:
    lines = original.splitlines()
    return lines[line - 1].strip()[:240] if 0 < line <= len(lines) else ""


def _mask_shaped(expression: str, known_masks: set[str] | None = None) -> bool:
    if known_masks and any(
        re.search(rf"\b{re.escape(name)}\b", expression)
        for name in known_masks
    ):
        return True
    return bool(re.search(
        r"\b(?:mask\w*|preg\w*|predicate\w*|CreateMask|UpdateMask)\b",
        expression,
        re.I,
    ))


class FindingSink:
    def __init__(self, root: Path, evidence: Mapping[str, Any]) -> None:
        self.root = root
        self.evidence = evidence
        self.items: list[dict[str, Any]] = []
        self._keys: set[tuple[str, str, int, str]] = set()

    def add(
        self,
        *,
        rule_id: str,
        subtype: str,
        path: Path,
        line: int,
        symbol: str,
        evidence: str,
        reason: str,
        confidence: float,
        base_score: int,
        status: str = "candidate",
    ) -> None:
        if status not in {"candidate", "suspected"}:
            raise ValueError(f"invalid static status: {status}")
        rel = _relative(path, self.root)
        key = (rule_id, rel, line, symbol)
        if key in self._keys:
            return
        self._keys.add(key)
        boost, evidence_notes = _evidence_boost(subtype, self.evidence)
        final_score = max(0, min(100, base_score + boost))
        combined_reason = reason
        if evidence_notes:
            combined_reason += " Runtime ranking: " + "; ".join(evidence_notes) + "."
        self.items.append({
            "rule_id": rule_id,
            "fault_domain": DOMAIN_BY_SUBTYPE[subtype],
            "subtype": subtype,
            "file": rel,
            "line": int(line),
            "api": symbol,
            "symbol": symbol,
            "evidence": evidence,
            "reason": combined_reason,
            "confidence": round(max(0.0, min(1.0, confidence)), 2),
            "base_score": int(max(0, min(100, base_score))),
            "final_score": int(final_score),
            "status": status,
            "reference": API_REFERENCE[subtype],
        })


def _nested_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _is_vector_mapping(value: Mapping[str, Any]) -> bool:
    own_type = value.get("error_type") or value.get("failure_type")
    if str(own_type or "").strip().upper() == "VECTOR_ERROR":
        return True
    runtime = _nested_mapping(value.get("runtime_evidence"))
    runtime_type = runtime.get("error_type") or runtime.get("failure_type")
    return str(runtime_type or "").strip().upper() == "VECTOR_ERROR"


def _evidence_sources(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Return P0-compatible evidence locations in priority order."""
    nodes: list[Mapping[str, Any]] = [payload]
    for key in ("precision_result", "onboard_result"):
        nested = _nested_mapping(payload.get(key))
        if nested:
            nodes.append(nested)

    cases: list[Mapping[str, Any]] = []
    for node in nodes:
        failed = node.get("failed_cases")
        if isinstance(failed, list):
            cases.extend(item for item in failed if isinstance(item, Mapping))
    vector_cases = [case for case in cases if _is_vector_mapping(case)]
    if not vector_cases and _is_vector_mapping(payload) and cases:
        # Legacy phase results may classify only the enclosing result.
        vector_cases = cases[:1]

    sources: list[Mapping[str, Any]] = []

    def add_bundles(mapping: Mapping[str, Any]) -> None:
        for key in (
            "vector_error_evidence", "error_signature", "runtime_evidence"
        ):
            nested = _nested_mapping(mapping.get(key))
            if nested:
                sources.append(nested)

    # Preserve the explicit top-level P0/checkpoint contract as authority.
    add_bundles(payload)
    for case in vector_cases:
        add_bundles(case)
        sources.append(case)
    for node in nodes[1:]:
        add_bundles(node)
        sources.append(node)
    sources.append(payload)
    return sources


def extract_evidence(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {}
    evidence: dict[str, Any] = {}
    for source in _evidence_sources(payload):
        for key, value in source.items():
            if value not in (None, "", [], {}):
                evidence.setdefault(key, value)
    return evidence


def _evidence_quality(evidence: Mapping[str, Any]) -> str:
    explicit = evidence.get("evidence_quality")
    if explicit in {"pc_mapped", "runtime_identified", "partial", "insufficient"}:
        return str(explicit)
    if evidence.get("kernel_name") and (
        evidence.get("pc") or evidence.get("pc_offset")
    ):
        return "pc_mapped"
    if evidence.get("kernel_name") and evidence.get("error_code"):
        return "runtime_identified"
    if evidence.get("case_id") or evidence.get("error_code"):
        return "partial"
    return "insufficient"


def _evidence_boost(
    subtype: str, evidence: Mapping[str, Any]
) -> tuple[int, list[str]]:
    boost = 0
    notes: list[str] = []
    exception = " ".join(
        str(evidence.get(key, "")) for key in ("exception_type", "message")
    ).lower()
    runtime_fault = any(
        evidence.get(key) not in (None, "", [], {})
        for key in ("error_code", "fault_va")
    ) or "trap" in exception
    if runtime_fault and subtype in {
        "gm_ub_transport", "ub_reg_load_store", "address_generation"
    }:
        boost += 14
        notes.append("error_code/trap/fault address favors memory/address candidates")

    source_phase = str(evidence.get("source_phase", "")).lower()
    if (
        source_phase == "vf_test"
        or "vector" in exception
        or "aiv" in exception
    ) and subtype in {
        "ub_reg_load_store", "mask_tail", "layout_cast_dist",
        "vf_call_abi", "incore_sync",
    }:
        boost += 12
        notes.append("VF/vector runtime context favors RegBase candidates")

    reproduction = evidence.get("reproducibility")
    if isinstance(reproduction, Mapping):
        reproduction = reproduction.get("status", "")
    intermittent = str(reproduction or "").lower() == "intermittent"
    buffer_mode = str(evidence.get("buffer_mode", "")).lower()
    if (
        source_phase == "finalize"
        or buffer_mode in {"double", "double_buffer"}
        or intermittent
    ) and subtype in {
        "incore_sync", "queue_lifecycle", "crosscore_tscm",
    }:
        boost += 18
        notes.append("double-buffer/finalize/intermittent context favors synchronization")
    return min(boost, 30), notes


ALL_CALLS = {
    "AllocTensor", "Cast", "CreateAddrReg", "CrossCoreSetFlag",
    "CrossCoreWaitFlag", "DataCopy", "DataCopyPad", "DeQue", "EnQue",
    "FreeTensor", "GetValue", "LoadAlign", "LoadUnAlign", "LoadUnAlignPre",
    "LocalMemBar", "SetFlag", "StoreAlign", "StoreUnAlign",
    "StoreUnAlignPost", "SetValue", "UpdateMask", "VF_CALL", "WaitFlag",
    "asc_vf_call",
}


def _scan_file(path: Path, root: Path, sink: FindingSink) -> None:
    original = path.read_text(encoding="utf-8", errors="replace")
    code = _mask_non_code(original)
    starts = _line_starts(code)
    calls = _find_calls(code, ALL_CALLS, starts)
    scopes = _find_vf_scopes(code, starts)
    calls_by_name: dict[str, list[Call]] = defaultdict(list)
    for call in calls:
        calls_by_name[call.name].append(call)
    mask_vars = set(re.findall(r"\bMaskReg\s+([A-Za-z_]\w*)", code))

    def add_call(
        call: Call, rule: str, subtype: str, reason: str,
        confidence: float, score: int, status: str = "candidate",
        symbol: str | None = None,
    ) -> None:
        sink.add(
            rule_id=rule,
            subtype=subtype,
            path=path,
            line=call.line,
            symbol=symbol or call.name,
            evidence=_source_line(original, call.line),
            reason=reason,
            confidence=confidence,
            base_score=score,
            status=status,
        )

    # GM/UB transport sites are candidates; sizes and units require runtime
    # tiling values and the current API contract before they can be judged.
    for name in ("DataCopy", "DataCopyPad"):
        for call in calls_by_name[name]:
            add_call(
                call, "A5-MTE-001", "gm_ub_transport",
                "Review source/destination provenance, length, burst/stride and tail bounds.",
                0.48, 55,
            )
    for match in re.finditer(r"\bTQue\s*<", code):
        line = _line_number(starts, match.start())
        sink.add(
            rule_id="A5-MTE-002",
            subtype="gm_ub_transport",
            path=path,
            line=line,
            symbol="TQue",
            evidence=_source_line(original, line),
            reason="TQue frames a GM/UB producer-consumer path; correlate its endpoints with transport sizes and bounds.",
            confidence=0.32,
            base_score=43,
        )

    # UB <-> RegTensor access and unaligned protocol.
    for name in ("LoadAlign", "StoreAlign", "LoadUnAlign", "StoreUnAlign"):
        for call in calls_by_name[name]:
            add_call(
                call, "A5-LS-001", "ub_reg_load_store",
                "Review address provenance, element count/distribution and post-update semantics.",
                0.52, 62,
            )

    for scope in scopes:
        scope_calls = [
            call for call in calls
            if scope.body_start <= call.start < scope.end
        ]
        names = Counter(call.name for call in scope_calls)
        if names["LoadUnAlign"] and not names["LoadUnAlignPre"]:
            call = next(call for call in scope_calls if call.name == "LoadUnAlign")
            add_call(
                call, "A5-LS-002", "ub_reg_load_store",
                f"{scope.name} uses LoadUnAlign without a visible LoadUnAlignPre in the same VF.",
                0.88, 84, "suspected",
            )
        if names["StoreUnAlign"] and not names["StoreUnAlignPost"]:
            call = next(call for call in scope_calls if call.name == "StoreUnAlign")
            add_call(
                call, "A5-LS-003", "ub_reg_load_store",
                f"{scope.name} uses StoreUnAlign without a visible StoreUnAlignPost in the same VF.",
                0.9, 86, "suspected",
            )

    for call in calls_by_name["StoreAlign"]:
        # RegTensor StoreAlign overloads normally carry a MaskReg.  Do not
        # reject MaskReg-store overloads, where an AddrReg may follow the mask.
        has_mask_argument = any(
            _mask_shaped(argument, mask_vars)
            for argument in call.args[1:]
        )
        if len(call.args) >= 3 and not has_mask_argument:
            add_call(
                call, "A5-LS-004", "ub_reg_load_store",
                "No StoreAlign argument is visibly mask-shaped; verify the selected overload and MaskReg dtype.",
                0.78, 78, "suspected",
                "StoreAlign(mask-form)",
            )

    # Mask/tail lifecycle. UpdateMask mutates its scalar argument, so each use
    # is worth ranking even when the static form looks valid.
    for call in calls_by_name["UpdateMask"]:
        add_call(
            call, "A5-MASK-001", "mask_tail",
            "UpdateMask decrements its scalar; verify reset scope, dtype-specific VL and tail reuse.",
            0.5, 63,
        )
    for call in calls_by_name["StoreAlign"]:
        if call.args and _mask_shaped(call.args[-1], mask_vars):
            add_call(
                call, "A5-MASK-002", "mask_tail",
                "Verify Store mask dtype and active-lane count match the stored element type.",
                0.45, 57,
                symbol="StoreAlign(mask)",
            )

    # Address register units and pointer arithmetic.
    for call in calls_by_name["CreateAddrReg"]:
        add_call(
            call, "A5-ADDR-001", "address_generation",
            "CreateAddrReg indices/strides are typed and element-based; verify width, units and overflow.",
            0.53, 64,
        )
    for call in calls:
        if call.name not in {
            "DataCopy", "DataCopyPad", "LoadAlign", "LoadUnAlign",
            "StoreAlign", "StoreUnAlign",
        }:
            continue
        if any(re.search(r"(?<!\+)\+(?!\+)|\*|<<", arg) for arg in call.args):
            add_call(
                call, "A5-ADDR-002", "address_generation",
                "Memory-call argument contains address arithmetic; verify byte/element units and tail range.",
                0.46, 58,
                symbol=f"{call.name}(address-expression)",
            )

    # Cast/distribution are layout-sensitive, but static syntax alone cannot
    # establish that a selected distribution is wrong.
    dist_pattern = re.compile(r"\b(?:LoadDist|StoreDist)::\w+")
    dist_lines = [
        _line_number(starts, match.start()) for match in dist_pattern.finditer(code)
    ]
    for call in calls_by_name["Cast"]:
        add_call(
            call, "A5-LAYOUT-001", "layout_cast_dist",
            "Verify width-changing Cast layout groups and any required layout restoration.",
            0.43, 54,
        )
        scope = _scope_for(call.start, scopes)
        if scope and any(
            scope.line <= line <= _line_number(starts, scope.end)
            for line in dist_lines
        ):
            add_call(
                call, "A5-LAYOUT-002", "layout_cast_dist",
                "Cast and LoadDist/StoreDist occur in one VF; verify their dtype/layout contract together.",
                0.58, 66,
                symbol="Cast+LoadDist/StoreDist",
            )
    for match in dist_pattern.finditer(code):
        line = _line_number(starts, match.start())
        sink.add(
            rule_id="A5-LAYOUT-003",
            subtype="layout_cast_dist",
            path=path,
            line=line,
            symbol=match.group(0),
            evidence=_source_line(original, line),
            reason="Distribution mode changes register layout; verify mode and dtype in current API documentation.",
            confidence=0.42,
            base_score=52,
        )

    # VF signature and call boundary.
    for scope in scopes:
        compact_signature = " ".join(scope.signature.split())
        after_annotation = re.sub(r"^.*?__(?:simd|simt)_vf__", "", compact_signature)
        signature_issues: list[str] = []
        if not re.search(r"\bvoid\b", after_annotation):
            signature_issues.append("return type is not visibly void")
        if not re.search(r"\binline\b", after_annotation):
            signature_issues.append("inline is missing")
        if re.search(r"(?<!&)&(?!&)", scope.params):
            signature_issues.append("reference parameter is present")
        if "[" in scope.params or re.search(r"\bstruct\b", scope.params):
            signature_issues.append("array/struct parameter is present")
        if signature_issues:
            sink.add(
                rule_id="A5-VF-001",
                subtype="vf_call_abi",
                path=path,
                line=scope.line,
                symbol=scope.name,
                evidence=_source_line(original, scope.line),
                reason="VF signature review: " + ", ".join(signature_issues) + ".",
                confidence=0.9,
                base_score=88,
                status="suspected",
            )

    local_tensors = set(re.findall(
        r"\bLocalTensor\s*<[^;{}>]+>\s+([A-Za-z_]\w*)", code
    ))
    for name in ("VF_CALL", "asc_vf_call"):
        for call in calls_by_name[name]:
            add_call(
                call, "A5-VF-004", "vf_call_abi",
                "Review VF boundary, programming-model match and UB pointer provenance.",
                0.42, 55,
            )
            direct = sorted({
                var for arg in call.args for var in local_tensors
                if re.fullmatch(rf"(?:\([^)]*\))?\s*{re.escape(var)}\s*", arg)
            })
            if direct:
                add_call(
                    call, "A5-VF-002", "vf_call_abi",
                    "LocalTensor variable(s) are passed directly to a VF call without visible GetPhyAddr: "
                    + ", ".join(direct),
                    0.9, 90, "suspected",
                    f"{name}(LocalTensor)",
                )

    forbidden = {"AllocTensor", "DataCopy", "DataCopyPad", "DeQue", "EnQue", "FreeTensor"}
    for call in calls:
        scope = _scope_for(call.start, scopes)
        if scope and call.name in forbidden:
            add_call(
                call, "A5-VF-003", "vf_call_abi",
                f"{call.name} appears inside {scope.kind.upper()} VF {scope.name}; keep queue/high-level transport outside VF.",
                0.92, 91, "suspected",
                f"{scope.name}:{call.name}",
            )
    for scope in scopes:
        body = code[scope.body_start:scope.end]
        for match in re.finditer(r"\bTQue\s*<", body):
            line = _line_number(starts, scope.body_start + match.start())
            sink.add(
                rule_id="A5-VF-003",
                subtype="vf_call_abi",
                path=path,
                line=line,
                symbol=f"{scope.name}:TQue",
                evidence=_source_line(original, line),
                reason=f"TQue declaration appears inside {scope.kind.upper()} VF; queue lifecycle belongs outside VF.",
                confidence=0.93,
                base_score=92,
                status="suspected",
            )

    # VF-local memory ordering. Only report an actual same-pointer Store->Load
    # chain and keep it a candidate because the compiler may insert sync.
    for scope in scopes:
        scope_calls = sorted(
            (call for call in calls if scope.body_start <= call.start < scope.end),
            key=lambda call: call.start,
        )
        for index, store in enumerate(scope_calls):
            if store.name != "StoreAlign" or not store.args:
                continue
            stored = _base_identifier(store.args[0])
            if not stored:
                continue
            for later in scope_calls[index + 1:]:
                if later.name == "LocalMemBar":
                    break
                if later.name == "LoadAlign" and len(later.args) >= 2:
                    if _base_identifier(later.args[1]) == stored:
                        add_call(
                            later, "A5-SYNC-001", "incore_sync",
                            f"{scope.name} loads {stored} after StoreAlign without a visible intervening LocalMemBar; verify compiler ordering.",
                            0.47, 61,
                            symbol="StoreAlign→LoadAlign",
                        )
                        break
        for index, first in enumerate(scope_calls):
            if first.name not in {"SetValue", "StoreAlign", "GetValue"}:
                continue
            expected = {
                "SetValue": {"LoadAlign", "StoreAlign"},
                "StoreAlign": {"GetValue"},
                "GetValue": {"StoreAlign"},
            }[first.name]
            for later in scope_calls[index + 1:]:
                if later.name == "LocalMemBar":
                    break
                if later.name in expected:
                    add_call(
                        later, "A5-SYNC-003", "incore_sync",
                        f"{scope.name} has a possible Scalar/Vector memory dependency ({first.name}→{later.name}) without a visible LocalMemBar; verify address alias and compiler ordering.",
                        0.38, 56,
                        symbol=f"{first.name}→{later.name}",
                    )
                    break
    for call in calls_by_name["LocalMemBar"]:
        add_call(
            call, "A5-SYNC-002", "incore_sync",
            "Verify LocalMemBar source/destination pipelines match the actual RAW/WAR/WAW dependency.",
            0.4, 50,
        )

    # Queue lifecycle is checked per receiver over the complete source file so
    # CopyIn/Compute/CopyOut member functions can jointly satisfy the protocol.
    queue_pattern = re.compile(
        r"\b(?P<receiver>[A-Za-z_]\w*)\s*\.\s*"
        r"(?P<api>AllocTensor|FreeTensor|EnQue|DeQue)\s*(?:<[^;(){}]*>)?\s*\("
    )
    queue_ops: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for match in queue_pattern.finditer(code):
        queue_ops[match.group("receiver")][match.group("api")].append(
            _line_number(starts, match.start())
        )
    for match in re.finditer(r"\bTQue\s*<", code):
        if _scope_for(match.start(), scopes):
            continue
        line = _line_number(starts, match.start())
        sink.add(
            rule_id="A5-QUEUE-001",
            subtype="queue_lifecycle",
            path=path,
            line=line,
            symbol="TQue",
            evidence=_source_line(original, line),
            reason="Review buffer count and complete Alloc/EnQue/DeQue/Free lifecycle for this queue.",
            confidence=0.4,
            base_score=49,
        )
    for receiver, operations in sorted(queue_ops.items()):
        for left, right, rule in (
            ("AllocTensor", "FreeTensor", "A5-QUEUE-002"),
            ("EnQue", "DeQue", "A5-QUEUE-003"),
        ):
            if bool(operations[left]) == bool(operations[right]):
                continue
            present = left if operations[left] else right
            line = operations[present][0]
            sink.add(
                rule_id=rule,
                subtype="queue_lifecycle",
                path=path,
                line=line,
                symbol=f"{receiver}.{present}",
                evidence=_source_line(original, line),
                reason=f"{receiver} has {present} but no visible {right if present == left else left} in this source file.",
                confidence=0.76,
                base_score=76,
                status="suspected",
            )

    # Cross-core/event pairing and shared-memory candidates.
    for setter, waiter in (("CrossCoreSetFlag", "CrossCoreWaitFlag"),):
        set_calls = calls_by_name[setter]
        wait_calls = calls_by_name[waiter]
        if bool(set_calls) != bool(wait_calls):
            present = set_calls[0] if set_calls else wait_calls[0]
            add_call(
                present, "A5-CROSS-001", "crosscore_tscm",
                f"{setter}/{waiter} are not both visible in this source file; verify path and event-ID pairing.",
                0.72, 75, "suspected",
                f"{setter}/{waiter}",
            )
        for call in (*set_calls, *wait_calls):
            add_call(
                call, "A5-CROSS-003", "crosscore_tscm",
                "Verify Set/Wait path symmetry, event identifier and pipeline/template parameters.",
                0.43, 54,
            )
    set_calls = calls_by_name["SetFlag"]
    wait_calls = calls_by_name["WaitFlag"]
    if bool(set_calls) != bool(wait_calls):
        present = set_calls[0] if set_calls else wait_calls[0]
        add_call(
            present, "A5-SYNC-004", "incore_sync",
            "SetFlag/WaitFlag are not both visible in this source file; verify path, HardEvent and event-ID pairing.",
            0.7, 74, "suspected",
            "SetFlag/WaitFlag",
        )
    for call in (*set_calls, *wait_calls):
        add_call(
            call, "A5-SYNC-005", "incore_sync",
            "Verify SetFlag/WaitFlag path symmetry, HardEvent direction and event identifier.",
            0.42, 53,
        )

    shared_memory_pattern = re.compile(
        r"\bTSCM\b|\bL1\b|TPosition::(?:A1|B1|CO1)\b"
    )
    for match in list(shared_memory_pattern.finditer(code))[:10]:
        line = _line_number(starts, match.start())
        sink.add(
            rule_id="A5-CROSS-002",
            subtype="crosscore_tscm",
            path=path,
            line=line,
            symbol=match.group(0),
            evidence=_source_line(original, line),
            reason="TSCM/L1 visibility may depend on cross-core and producer/consumer synchronization.",
            confidence=0.4,
            base_score=53,
        )

    # Boundary candidates are deliberately low-confidence context anchors.
    boundary_pattern = re.compile(
        r"\b(?:tail|remain(?:der)?|valid\w*(?:len|count)|actual\w*(?:len|size)|"
        r"GetBlockIdx|GetBlockNum|blockIdx|coreNum|repeatTimes)\b",
        re.I,
    )
    for match in list(boundary_pattern.finditer(code))[:12]:
        line = _line_number(starts, match.start())
        sink.add(
            rule_id="A5-TILE-001",
            subtype="tiling_boundary",
            path=path,
            line=line,
            symbol=match.group(0),
            evidence=_source_line(original, line),
            reason="Review zero work, last core/repeat and non-aligned tail bounds at this boundary.",
            confidence=0.3,
            base_score=38,
        )


def _base_identifier(expression: str) -> str:
    expression = re.sub(r"^\s*\([^)]*\)\s*", "", expression)
    match = re.search(r"\b([A-Za-z_]\w*)\b", expression)
    return match.group(1) if match else ""


def scan_sources(
    operator_dir: Path | None = None,
    explicit_sources: Sequence[Path] | None = None,
    evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    root, sources = collect_sources(operator_dir, explicit_sources)
    normalized_evidence = extract_evidence(evidence)
    sink = FindingSink(root, normalized_evidence)
    for source in sources:
        _scan_file(source, root, sink)

    findings = sorted(
        sink.items,
        key=lambda item: (
            item["file"], item["line"], item["rule_id"], item["symbol"]
        ),
    )
    candidates = sorted(
        (dict(item) for item in findings),
        key=lambda item: (
            -item["final_score"],
            -item["confidence"],
            item["file"],
            item["line"],
            item["rule_id"],
            item["symbol"],
        ),
    )
    for rank, candidate in enumerate(candidates, start=1):
        candidate["rank"] = rank

    if candidates:
        top = candidates[0]
        classification = {
            "fault_domain": top["fault_domain"],
            "subtype": top["subtype"],
            "confidence": top["confidence"],
            "evidence_quality": _evidence_quality(normalized_evidence),
        }
    else:
        classification = {
            "fault_domain": "UNKNOWN",
            "subtype": "unknown",
            "confidence": 0.0,
            "evidence_quality": _evidence_quality(normalized_evidence),
        }

    subtype_counts = Counter(item["subtype"] for item in findings)
    return {
        "schema_version": SCHEMA_VERSION,
        "scanned_files": [_relative(source, root) for source in sources],
        "classification": classification,
        "static_findings": findings,
        "candidate_ranking": candidates,
        "summary": {
            "scanned_file_count": len(sources),
            "finding_count": len(findings),
            "suspected_count": sum(
                item["status"] == "suspected" for item in findings
            ),
            "subtype_counts": dict(sorted(subtype_counts.items())),
            "score_range": [0, 100],
            "root_cause_confirmed": False,
            "note": (
                "Static findings are candidates only. Confirm with a "
                "semantics-preserving experiment and current 910D/CANN API docs."
            ),
        },
    }


def _load_json(path: Path | None) -> Mapping[str, Any]:
    if path is None:
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError(f"evidence JSON must contain an object: {path}")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scan A5 RegBase/VF sources for VECTOR_ERROR risk candidates."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--operator-dir", type=Path)
    source.add_argument("--source", type=Path, nargs="+", dest="sources")
    parser.add_argument(
        "--evidence", type=Path,
        help="Optional P0 evidence/checkpoint/result JSON used only for ranking.",
    )
    parser.add_argument("--output", type=Path, help="Also write JSON to this file.")
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = scan_sources(
            operator_dir=args.operator_dir,
            explicit_sources=args.sources,
            evidence=_load_json(args.evidence),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"scan_a5_vector_risks: {exc}", file=sys.stderr)
        return 2

    indent = 2 if args.pretty else None
    rendered = json.dumps(
        result, ensure_ascii=False, indent=indent, sort_keys=True
    ) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
