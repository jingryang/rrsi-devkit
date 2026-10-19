"""VECTOR_ERROR evidence extraction and fingerprinting."""

from __future__ import annotations


UNKNOWN_FIELDS = {
    "case_id": "<unknown>",
    "kernel_name": "<unknown>",
    "error_code": "<unknown>",
    "pc_offset": "<unknown>",
    "pc": "<unknown>",
    "fault_va": "<unknown>",
    "exception_type": "<unknown>",
    "run_log": "<unknown>",
    "plog": "<unknown>",
    "tiling_key": "<unknown>",
    "source_phase": "<unknown>",
}


def normalize_vector_error_evidence(raw: dict, *, source_phase: str = "") -> dict:
    """Normalize raw evidence to a canonical dict with lowercase hex strings."""
    ev = dict(UNKNOWN_FIELDS)
    ev.update(raw)
    ev["source_phase"] = source_phase or ev.get("source_phase", "<unknown>")
    for k in ("error_code", "pc_offset", "pc", "tiling_key"):
        v = ev.get(k, "")
        if isinstance(v, str):
            ev[k] = v.lower().strip()
    if isinstance(ev.get("case_id"), str):
        ev["case_id"] = ev["case_id"].lower().strip()
    if isinstance(ev.get("kernel_name"), str):
        ev["kernel_name"] = ev["kernel_name"].lower().strip()
    return ev


def build_vector_error_fingerprint(ev: dict) -> str:
    """Stable fingerprint for VECTOR_ERROR episode identity.

    Matches are case-insensitive by construction (normalize before calling).
    """
    return (
        f"a5-vector-v1|case_id={ev.get('case_id', '')}|"
        f"kernel_name={ev.get('kernel_name', '')}|"
        f"error_code={ev.get('error_code', '')}|"
        f"pc_offset={ev.get('pc_offset', '')}|"
        f"source_phase={ev.get('source_phase', '')}|"
        f"tiling_key={ev.get('tiling_key', '')}"
    )


def evidence_quality(ev: dict) -> str:
    if ev.get("pc_offset") not in (None, "", "<unknown>"):
        return "pc_mapped"
    if ev.get("kernel_name") not in (None, "", "<unknown>"):
        return "runtime_identified"
    if ev.get("error_code") not in (None, "", "<unknown>"):
        return "partial"
    return "insufficient"


def _declares_resolved_crash(result: dict) -> bool:
    """Result structurally declares the vector crash resolved and verified.

    A dump_evidence mention of a device vector exception is *historical
    narrative* (pre-fix crash) when the agent also declares, via structured
    verification fields, that the crash was resolved and the rerun passed
    (e.g. kernel_debug ``debug_status=fixed`` + ``verification.crash=resolved``
    / ``verification.after_passed=true`` / ``vector_error_evidence.cleared``).
    The free-text heuristic must not override that structured declaration —
    routing a verified fix back to vector_error_debug would only reproduce
    ``not_reproduced`` and loop (业务语义优先，§1.10).
    """
    ver = result.get("verification") or {}
    if ver.get("crash") == "resolved":
        return True
    if ver.get("after_passed") is True:
        return True
    if (result.get("vector_error_evidence") or {}).get("cleared") is True:
        return True
    return False


def _extract_error_type(result: dict) -> str:
    """Extract error_type from result, giving nested failed_case vector_error priority."""
    failed = result.get("precision_result", {}).get("failed_cases", []) or []
    for case in failed:
        if case.get("failure_type") == "vector_error" or case.get("error_type") == "VECTOR_ERROR":
            return "VECTOR_ERROR"
    dump_evidence = str(result.get("dump_evidence", "") or "")
    if dump_evidence and not _declares_resolved_crash(result):
        import re
        if re.search(r'(VECTOR_EXCEPTION|VECTOR_CORE_EXCEPTION|ACL_ERROR_RT_VECTOR)', dump_evidence, re.IGNORECASE):
            return "VECTOR_ERROR"
    return result.get("error_type", "")


def _extract_vector_error_evidence(result: dict) -> dict:
    """Extract the first VECTOR_ERROR evidence from nested failed_cases."""
    failed = result.get("precision_result", {}).get("failed_cases", []) or []
    for case in failed:
        if case.get("failure_type") == "vector_error" or case.get("error_type") == "VECTOR_ERROR":
            ev = normalize_vector_error_evidence(case)
            ev["evidence_quality"] = evidence_quality(ev)
            return ev
    return {}


def _record_phase_error(cp: dict, result: dict, source_phase: str) -> str:
    """Record VECTOR_ERROR from a phase result into the checkpoint.

    Resets vector_error_round when a new episode is detected; preserves progress
    for the same episode.
    """
    error_type = _extract_error_type(result)
    if error_type != "VECTOR_ERROR":
        cp["error_type"] = error_type
        return error_type
    ev = _extract_vector_error_evidence(result)
    if not ev:
        top_ev = result.get("vector_error_evidence", {}) or {}
        ev = normalize_vector_error_evidence(top_ev, source_phase=source_phase)
        _augment_from_result(ev, result)
    ev["source_phase"] = source_phase
    ev["evidence_quality"] = evidence_quality(ev)
    new_fp = build_vector_error_fingerprint(ev)
    old_fp = cp.get("active_error_fingerprint", "")
    if old_fp and new_fp == old_fp:
        cp["error_type"] = "VECTOR_ERROR"
        return error_type
    cp["error_type"] = "VECTOR_ERROR"
    cp["active_error_fingerprint"] = new_fp
    cp["vector_error_evidence"] = ev
    cp["vector_error_round"] = 0
    cp["vector_error_status"] = ""
    cp["vector_error_source_phase"] = source_phase
    return error_type


def _augment_from_result(ev: dict, result: dict) -> None:
    """Augment vector error evidence with derived fields from result metadata."""
    dump_evidence = str(result.get("dump_evidence", "") or "")
    if dump_evidence:
        ev["deterministic_runtime_evidence"] = _has_det_runtime_evidence(dump_evidence)
    ev["reported_error_type"] = result.get("error_type", "")
    ev["suspected_root_cause"] = result.get("suspected_root_cause", "")


def _has_det_runtime_evidence(dump_evidence: str) -> bool:
    import re
    return bool(re.search(
        r'(VECTOR_EXCEPTION|VECTOR_CORE_EXCEPTION|ACL_ERROR_RT_VECTOR|error_code=\d+)',
        dump_evidence, re.IGNORECASE))
