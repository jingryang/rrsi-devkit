#!/usr/bin/env python3
"""Plan and validate evidence-gated A5 VECTOR_ERROR repairs.

The tool is intentionally read-only with respect to operator sources.  It
never creates a patch, edits code, builds, runs a case/NPU, or searches global
logs.  A repair becomes executable only after the P2 experiment validator and
the original execution record jointly prove a reversible, fingerprint-stable
``error_disappeared`` experiment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "1.0"
VALIDATION_SCHEMA_VERSION = "1.0"
API_STATUSES = {"required", "verified", "unverified"}
REPAIR_STATUSES = {"ready", "deferred"}
SOURCE_SUFFIXES = {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx"}

_P2_REQUIRED_GATES = {
    "original_fingerprint_available",
    "baseline_reproduced",
    "single_variable_verified",
    "invariants_verified",
    "build_passed",
    "build_evidence_recorded",
    "run_completed",
    "run_evidence_recorded",
    "outcome_fingerprint_consistent",
    "changed_files_within_scope",
    "rollback_verified",
    "rollback_original_fingerprint_reproduced",
    "inference_outcome",
    "record_schema_valid",
}

_REPAIR_REQUIRED_FIELDS = {
    "repair_id",
    "status",
    "executable",
    "root_evidence",
    "subtype",
    "target",
    "minimal_change_intent",
    "a5_invariants",
    "forbidden_changes",
    "api_verification",
    "semantic_risks",
    "rollback_restore",
    "verification_matrix",
}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _nonempty(value: Any) -> bool:
    return value not in (None, "", [], {})


def _load_json(path: Path | None) -> Mapping[str, Any]:
    if path is None:
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError(f"JSON must contain an object: {path}")
    return value


def _evidence_sources(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    sources: list[Mapping[str, Any]] = []
    for key in (
        "vector_error_evidence",
        "error_signature",
        "runtime_evidence",
    ):
        nested = _mapping(payload.get(key))
        if nested:
            sources.append(nested)
    for key in ("precision_result", "onboard_result"):
        nested = _mapping(payload.get(key))
        if not nested:
            continue
        for bundle in (
            "vector_error_evidence",
            "error_signature",
            "runtime_evidence",
        ):
            value = _mapping(nested.get(bundle))
            if value:
                sources.append(value)
        failed = nested.get("failed_cases")
        if isinstance(failed, list):
            for item in failed:
                case = _mapping(item)
                if not case:
                    continue
                for bundle in ("vector_error_evidence", "runtime_evidence"):
                    value = _mapping(case.get(bundle))
                    if value:
                        sources.append(value)
                sources.append(case)
    sources.append(payload)
    return sources


def extract_context(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {}
    context: dict[str, Any] = {}
    for source in _evidence_sources(payload):
        for key, value in source.items():
            if _nonempty(value):
                context.setdefault(key, value)
    fingerprint = (
        payload.get("active_error_fingerprint")
        or _mapping(payload.get("error_signature")).get("fingerprint")
        or _mapping(payload.get("vector_error_evidence")).get("fingerprint")
        or context.get("active_error_fingerprint")
        or context.get("fingerprint")
    )
    if _nonempty(fingerprint):
        context["fingerprint"] = str(fingerprint)
    return context


def _indexed(items: Any, id_fields: Sequence[str], label: str) -> dict[str, Mapping[str, Any]]:
    if not isinstance(items, list):
        raise ValueError(f"{label} must be a list")
    result: dict[str, Mapping[str, Any]] = {}
    for index, value in enumerate(items):
        item = _mapping(value)
        identifier = ""
        for field in id_fields:
            if _nonempty(item.get(field)):
                identifier = str(item[field])
                break
        if not identifier or identifier in result:
            raise ValueError(f"{label}[{index}] has empty/duplicate id")
        result[identifier] = item
    return result


def _safe_relative_source(value: Any) -> str:
    text = str(value or "")
    path = Path(text)
    if (
        not text
        or path.is_absolute()
        or ".." in path.parts
        or path.suffix.lower() not in SOURCE_SUFFIXES
    ):
        raise ValueError(f"unsafe repair target source: {text!r}")
    return path.as_posix()


def _static_candidate(
    static_scan: Mapping[str, Any],
    experiment: Mapping[str, Any],
) -> Mapping[str, Any]:
    ranking = static_scan.get("candidate_ranking")
    if not isinstance(ranking, list):
        return {}
    for value in ranking:
        candidate = _mapping(value)
        if (
            str(candidate.get("file", "")) == str(experiment.get("file", ""))
            and int(candidate.get("line", 0) or 0)
            == int(experiment.get("line", 0) or 0)
            and str(candidate.get("subtype", ""))
            == str(experiment.get("subtype", ""))
        ):
            return candidate
    return {}


def _record_proves_p2_root(
    record: Mapping[str, Any],
    fingerprint: str,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    run = _mapping(record.get("run"))
    rollback = _mapping(record.get("rollback"))
    if record.get("outcome") != "error_disappeared":
        reasons.append("experiment record outcome is not error_disappeared")
    if run.get("status") != "completed" or not _nonempty(run.get("evidence")):
        reasons.append("modified experiment run is incomplete or lacks evidence")
    if (
        run.get("original_error_observed") is not False
        or _nonempty(run.get("observed_fingerprint"))
    ):
        reasons.append("modified run is inconsistent with error_disappeared")
    if rollback.get("verified") is not True:
        reasons.append("experiment rollback declaration is not verified")
    if (
        rollback.get("baseline_reproduced") is not True
        or rollback.get("observed_fingerprint") != fingerprint
        or not _nonempty(rollback.get("evidence"))
    ):
        reasons.append("rollback did not re-observe the original fingerprint")
    return not reasons, reasons


def _validation_proves_p2_root(
    validation: Mapping[str, Any],
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    gates = _mapping(validation.get("gates"))
    if validation.get("outcome") != "error_disappeared":
        reasons.append("P2 validation outcome is not error_disappeared")
    if validation.get("valid_for_inference") is not True:
        reasons.append("P2 validation is not valid_for_inference")
    if validation.get("root_cause_confirmation_allowed") is not True:
        reasons.append("P2 validation disallows root-cause confirmation")
    missing = sorted(
        gate for gate in _P2_REQUIRED_GATES if gates.get(gate) is not True
    )
    if missing:
        reasons.append("P2 gates failed/missing: " + ", ".join(missing))
    rollback = _mapping(validation.get("rollback"))
    if rollback.get("verified") is not True:
        reasons.append("P2 SHA256 rollback verification is not true")
    return not reasons, reasons


def _api_entry(
    payload: Mapping[str, Any],
    experiment: Mapping[str, Any],
) -> dict[str, Any]:
    candidates: list[Mapping[str, Any]] = []
    for key in ("entries", "repairs", "api_verifications"):
        value = payload.get(key)
        if isinstance(value, list):
            candidates.extend(_mapping(item) for item in value)
    if _nonempty(payload.get("status")):
        candidates.insert(0, payload)
    exp_id = str(experiment.get("id", ""))
    subtype = str(experiment.get("subtype", ""))
    file = str(experiment.get("file", ""))
    line = int(experiment.get("line", 0) or 0)
    selected: Mapping[str, Any] = {}
    for item in candidates:
        if item.get("experiment_id") == exp_id:
            selected = item
            break
    if not selected:
        for item in candidates:
            if (
                item.get("subtype") == subtype
                and (not item.get("file") or item.get("file") == file)
                and (
                    not item.get("line")
                    or int(item.get("line", 0) or 0) == line
                )
            ):
                selected = item
                break
    status = str(selected.get("status", "required")).lower()
    if status not in API_STATUSES:
        status = "unverified"
    result = {
        "status": status,
        "required_for_execution": True,
        "target": str(selected.get("target", "")),
        "soc": str(selected.get("soc", "")),
        "cann_version": str(selected.get("cann_version", "")),
        "doc": str(selected.get("doc", "")),
        "source": str(selected.get("source", "")),
        "version": str(selected.get("version", "")),
        "claim": str(selected.get("claim", "")),
    }
    required_fields = ("target", "cann_version", "doc", "source", "version")
    result["missing"] = [
        field for field in required_fields if not result[field]
    ]
    if status == "verified" and result["missing"]:
        result["status"] = "unverified"
    return result


def _template(subtype: str) -> dict[str, Any]:
    common_forbidden = [
        "Do not retain P2 identity/placeholder code as the final repair.",
        "Do not change unrelated arithmetic, tiling or kernel variants.",
        "Do not hardcode alignment, VL, dtype support or API units without current 910D/CANN verification.",
        "Do not break producer-consumer, queue, event or participating-core symmetry.",
    ]
    templates: dict[str, dict[str, Any]] = {
        "gm_ub_transport": {
            "kind": "repair_transport_bounds",
            "intent": "Correct only the proven GM/UB source, destination, length, stride or tail bound while preserving the complete producer-consumer chain.",
            "invariants": [
                "Destination capacity and initialized source coverage include every transferred element.",
                "TQue ownership and DataCopy/DataCopyPad producer-consumer ordering stay complete.",
                "Main and tail paths cover each logical output exactly once.",
            ],
            "risks": ["A unit or padding change can silently shift later tiles or expose unwritten output."],
            "matrix": ["aligned_tail", "zero_one", "last_core"],
        },
        "address_generation": {
            "kind": "repair_address_generation",
            "intent": "Correct only the proven address expression/AddrReg index, stride, width or tail progression in documented element units.",
            "invariants": [
                "GM/UB base provenance, logical tensor mapping and all loop extents remain unchanged.",
                "AddrReg and pointer progression address the same logical element sequence.",
                "Last repeat/core remains within allocated source and destination ranges.",
            ],
            "risks": ["Changing byte/element units or integer width can fix one case while corrupting larger shapes."],
            "matrix": ["aligned_tail", "zero_one", "last_core"],
        },
        "ub_reg_load_store": {
            "kind": "repair_vf_load_store_contract",
            "intent": "Correct only the proven UB↔RegTensor Load/Store, Mask/AddrReg, distribution or PostUpdate contract while retaining Load→Compute→Store coverage.",
            "invariants": [
                "Every RegTensor consumed by Compute is initialized by a valid Load.",
                "Store active lanes, dtype/layout and destination coverage match the logical output.",
                "Load/Store PostUpdate and AddrReg progression remain mutually consistent.",
            ],
            "risks": ["A locally valid Load/Store overload can still change lane order or pointer advancement."],
            "matrix": ["aligned_tail", "zero_one"],
        },
        "vf_call_abi": {
            "kind": "repair_vf_call_abi",
            "intent": "Correct only the proven VF signature/call boundary, GetPhyAddr provenance or SIMD/SIMT callee-domain mismatch.",
            "invariants": [
                "VF remains inline void with supported pointer/POD parameters.",
                "LocalTensor is converted to the correct physical address before VF use.",
                "The original RegTensor Load→Compute→Store semantics and queue ownership remain unchanged.",
            ],
            "risks": ["Changing a VF ABI can affect all template instantiations and programming-model boundaries."],
            "matrix": ["aligned_tail"],
        },
        "mask_tail": {
            "kind": "repair_mask_tail_lifecycle",
            "intent": "Correct only the proven MaskReg dtype/active lanes or UpdateMask reset scope for the row/tile/tail path.",
            "invariants": [
                "Mask dtype matches the documented operation/store element type.",
                "Mask counters reset at the correct row/tile boundary without changing address progression.",
                "Inactive tail lanes are never read from or stored beyond proven allocation/padding.",
            ],
            "risks": ["Forcing all-valid or hardcoding a VL can create an out-of-bounds repair."],
            "matrix": ["aligned_tail", "zero_one"],
        },
        "layout_cast_dist": {
            "kind": "repair_cast_distribution_layout",
            "intent": "Apply only the API-verified CastTrait/LoadDist/StoreDist/layout restoration that preserves the intended logical lane sequence.",
            "invariants": [
                "Input/output dtype, logical element order and active mask remain unchanged.",
                "Width-changing Cast component groups are explicitly restored before consumers/store.",
                "LoadDist/StoreDist semantics are verified for the target SoC and current CANN.",
            ],
            "risks": ["An unverified layout substitution can remove the exception while silently permuting data."],
            "matrix": ["aligned_tail"],
        },
        "incore_sync": {
            "kind": "repair_incore_dependency",
            "intent": "Correct only the proven RAW/WAR/WAW pipeline dependency or LocalMemBar direction without serializing unrelated VF work.",
            "invariants": [
                "Vector/Scalar load-store dependency direction matches the actual shared UB address.",
                "All producer and consumer operations remain present.",
                "Single and double-buffer behavior use the same logical values.",
            ],
            "risks": ["Over-broad barriers can mask buffer reuse defects and alter pipeline behavior."],
            "matrix": ["single_double_buffer"],
        },
        "queue_lifecycle": {
            "kind": "repair_queue_lifecycle",
            "intent": "Restore only the proven complete Alloc→EnQue→DeQue→Free lifecycle and buffer reuse ordering.",
            "invariants": [
                "Every acquired tensor is released exactly once on every executed path.",
                "Producer and consumer use the same queue slot and initialized payload.",
                "Single/double-buffer ownership and event allocation stay consistent.",
            ],
            "risks": ["Adding one queue endpoint without its paired path can move or hide the vector exception."],
            "matrix": ["single_double_buffer", "aligned_tail"],
        },
        "crosscore_tscm": {
            "kind": "repair_crosscore_tscm_visibility",
            "intent": "Correct only the proven CrossCore/TSCM producer-consumer role, Set/Wait pairing, event identity or visibility boundary.",
            "invariants": [
                "All producer/consumer cores participate in the required protocol on every branch.",
                "TSCM/L1 data is fully produced before the matching consumer observes it.",
                "Event identity and occurrence counts remain symmetric across single/double buffer.",
            ],
            "risks": ["A one-core success can hide a missing multi-core participant or event reuse conflict."],
            "matrix": ["single_double_buffer", "one_original_core", "last_core"],
        },
        "tiling_boundary": {
            "kind": "repair_tiling_boundary",
            "intent": "Correct only the proven zero-work, one-element, tail, last-repeat or last-core boundary while preserving mandatory synchronization.",
            "invariants": [
                "Non-empty main tiles retain their original mapping and work coverage.",
                "Zero-work cores skip invalid memory operations but still join mandatory synchronization.",
                "Last repeat/core processes exactly its valid logical elements.",
            ],
            "risks": ["An early return can deadlock peers or leave output regions uncovered."],
            "matrix": ["aligned_tail", "zero_one", "last_core"],
        },
    }
    template = templates.get(subtype)
    if template is None:
        raise ValueError(f"unsupported A5 repair subtype: {subtype!r}")
    result = dict(template)
    result["forbidden"] = list(common_forbidden)
    return result


def _case_values(context: Mapping[str, Any], kind: str) -> list[Any]:
    value = context.get("verification_cases")
    if isinstance(value, Mapping):
        selected = value.get(kind)
        if isinstance(selected, list):
            return selected
    aliases = {
        "aligned_tail": ("boundary_cases", "aligned_tail_cases"),
        "zero_one": ("zero_one_cases",),
        "last_core": ("last_core_cases",),
    }
    for key in aliases.get(kind, ()):
        selected = context.get(key)
        if isinstance(selected, list):
            return selected
    return []


def _verification_matrix(
    template: Mapping[str, Any],
    context: Mapping[str, Any],
) -> list[dict[str, Any]]:
    original_case = str(context.get("case_id", ""))
    matrix: list[dict[str, Any]] = [{
        "name": "original_case_repeat",
        "required": True,
        "status": "ready" if original_case else "deferred",
        "case_ids": [original_case] if original_case else [],
        "minimum_repeats": 2,
        "controls": {},
        "prerequisite": "" if original_case else "missing original case_id",
    }]
    mode_commands = context.get("mode_commands")
    if not isinstance(mode_commands, Mapping):
        mode_commands = context.get("diagnostic_mode_commands")
    if not isinstance(mode_commands, Mapping):
        mode_commands = {}
    for kind in template["matrix"]:
        if kind in {"single_double_buffer", "one_original_core"}:
            required_keys = (
                ("single", "double")
                if kind == "single_double_buffer"
                else ("one_core", "original_core")
            )
            controls = {
                key: mode_commands[key]
                for key in required_keys if _nonempty(mode_commands.get(key))
            }
            ready = len(controls) == len(required_keys)
            matrix.append({
                "name": kind,
                "required": True,
                "status": "ready" if ready else "deferred",
                "case_ids": [original_case] if original_case else [],
                "minimum_repeats": 1,
                "controls": controls,
                "prerequisite": (
                    "" if ready and original_case
                    else "missing explicit existing mode controls and/or case_id"
                ),
            })
            continue
        cases = _case_values(context, kind)
        matrix.append({
            "name": kind,
            "required": True,
            "status": "ready" if cases else "deferred",
            "case_ids": cases,
            "minimum_repeats": 1,
            "controls": {},
            "prerequisite": "" if cases else (
                f"missing existing valid {kind} cases; do not synthesize commands"
            ),
        })
    return matrix


def _located_root(
    roots_payload: Mapping[str, Any],
    experiment: Mapping[str, Any],
) -> Mapping[str, Any]:
    value = roots_payload.get("located_roots", roots_payload.get("roots", []))
    if not isinstance(value, list):
        return {}
    for item in value:
        root = _mapping(item)
        if (
            str(root.get("file", "")) == str(experiment.get("file", ""))
            and int(root.get("line", 0) or 0)
            == int(experiment.get("line", 0) or 0)
        ):
            return root
    return {}


def _line_confirmation_proves_root(
    root: Mapping[str, Any],
    experiment: Mapping[str, Any],
    fingerprint: str,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    exp_id = str(experiment.get("id", ""))
    if not root:
        return False, ["line-level confirmation record is missing"]
    if root.get("experiment_id") != exp_id:
        reasons.append(
            "line-level confirmation is not bound to the P2 experiment"
        )
    if root.get("confidence") != "confirmed":
        reasons.append("line-level confirmation confidence is not confirmed")
    if root.get("fingerprint") != fingerprint:
        reasons.append(
            "line-level confirmation fingerprint does not match P0"
        )
    if not _nonempty(root.get("evidence")):
        reasons.append("line-level confirmation evidence is missing")
    confirmation = _mapping(root.get("confirmation"))
    required = (
        "baseline_reproduced",
        "error_disappeared",
        "restored_original_fingerprint",
        "invariants_verified",
    )
    missing = [
        field for field in required if confirmation.get(field) is not True
    ]
    if missing:
        reasons.append(
            "line-level confirmation gates failed/missing: "
            + ", ".join(missing)
        )
    return not reasons, reasons


def _history_repair_ids(history: Mapping[str, Any]) -> set[str]:
    ids: set[str] = set()
    for key in ("repairs", "repair_results"):
        value = history.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            repair = _mapping(item)
            if _nonempty(repair.get("repair_id")):
                ids.add(str(repair["repair_id"]))
    nested = history.get("history")
    if isinstance(nested, list):
        for item in nested:
            ids.update(_history_repair_ids(_mapping(item)))
    return ids


def _repair_id(
    fingerprint: str,
    experiment: Mapping[str, Any],
    kind: str,
) -> str:
    material = "|".join(str(item) for item in (
        fingerprint,
        experiment.get("id", ""),
        experiment.get("subtype", ""),
        experiment.get("file", ""),
        experiment.get("line", 0),
        experiment.get("api", ""),
        kind,
    ))
    return "a5vr-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]


def plan_repairs(
    evidence: Mapping[str, Any],
    static_scan: Mapping[str, Any],
    experiment_plan: Mapping[str, Any],
    experiment_validation: Mapping[str, Any],
    experiment_records: Mapping[str, Any],
    *,
    located_roots: Mapping[str, Any] | None = None,
    history: Mapping[str, Any] | None = None,
    api_verification: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    context = extract_context(evidence)
    fingerprint = str(context.get("fingerprint", ""))
    plan_fingerprint = str(experiment_plan.get("fingerprint", ""))
    validation_fingerprint = str(experiment_validation.get("fingerprint", ""))
    global_refusals: list[str] = []
    if not fingerprint or fingerprint == "<missing>":
        global_refusals.append("P0 original fingerprint is missing")
    if fingerprint != plan_fingerprint:
        global_refusals.append("P0 fingerprint does not match P2 experiment plan")
    if fingerprint != validation_fingerprint:
        global_refusals.append("P0 fingerprint does not match P2 validation")
    experiments = _indexed(
        experiment_plan.get("experiments", []), ("id",), "experiment_plan.experiments"
    )
    validations = _indexed(
        experiment_validation.get("experiments", []),
        ("id", "experiment_id"),
        "experiment_validation.experiments",
    )
    records = _indexed(
        experiment_records.get("experiments", experiment_records.get("records", [])),
        ("id", "experiment_id"),
        "experiment_records.experiments",
    )
    unknown_validations = sorted(set(validations) - set(experiments))
    unknown_records = sorted(set(records) - set(experiments))
    if unknown_validations:
        global_refusals.append(
            "validation contains unknown experiment ids: "
            + ", ".join(unknown_validations)
        )
    if unknown_records:
        global_refusals.append(
            "records contain unknown experiment ids: "
            + ", ".join(unknown_records)
        )

    roots_payload = located_roots or {}
    api_payload = api_verification or {}
    previous_ids = _history_repair_ids(history or {})
    repairs: list[dict[str, Any]] = []
    refused: list[dict[str, Any]] = []
    for exp_id, experiment in experiments.items():
        normalized_file = _safe_relative_source(experiment.get("file"))
        if int(experiment.get("line", 0) or 0) < 1:
            raise ValueError(
                f"invalid repair target line for experiment {exp_id!r}"
            )
        validation = validations.get(exp_id, {})
        record = records.get(exp_id, {})
        located = _located_root(roots_payload, experiment)
        validation_ok, validation_reasons = _validation_proves_p2_root(validation)
        record_ok, record_reasons = _record_proves_p2_root(record, fingerprint)
        confirmation_ok, confirmation_reasons = (
            _line_confirmation_proves_root(
                located, experiment, fingerprint
            )
        )
        reasons = (
            list(global_refusals)
            + validation_reasons
            + record_reasons
            + confirmation_reasons
        )
        if reasons:
            refused.append({
                "experiment_id": exp_id,
                "subtype": experiment.get("subtype", ""),
                "target": {
                    "file": experiment.get("file", ""),
                    "line": experiment.get("line", 0),
                    "api": _mapping(experiment.get("candidate")).get("api", ""),
                },
                "status": "refused",
                "reasons": sorted(set(reasons)),
            })
            continue

        subtype = str(experiment.get("subtype", ""))
        try:
            template = _template(subtype)
        except ValueError as exc:
            refused.append({
                "experiment_id": exp_id,
                "subtype": subtype,
                "target": {
                    "file": experiment.get("file", ""),
                    "line": experiment.get("line", 0),
                    "api": _mapping(experiment.get("candidate")).get("api", ""),
                },
                "status": "refused",
                "reasons": [str(exc)],
            })
            continue
        file = normalized_file
        line = int(experiment.get("line", 0) or 0)
        api = str(
            _mapping(experiment.get("candidate")).get("api")
            or _mapping(experiment.get("exact_scope")).get("symbol")
            or ""
        )
        api_check = _api_entry(api_payload, experiment)
        api_ready = _api_verified(api_check)
        matrix = _verification_matrix(template, context)
        repair_id = _repair_id(fingerprint, experiment, template["kind"])
        if repair_id in previous_ids:
            refused.append({
                "experiment_id": exp_id,
                "repair_id": repair_id,
                "subtype": subtype,
                "target": {"file": file, "line": line, "api": api},
                "status": "refused",
                "reasons": ["history_skip: repair already planned/recorded"],
            })
            continue
        static = _static_candidate(static_scan, experiment)
        deferred_reasons: list[str] = []
        if not api_ready:
            deferred_reasons.append(
                "current 910D/SoC/CANN API verification is not complete"
            )
        if not context.get("case_id"):
            deferred_reasons.append("original case_id is missing")
        repair = {
            "repair_id": repair_id,
            "status": "ready" if not deferred_reasons else "deferred",
            "executable": not deferred_reasons,
            "deferred_reasons": deferred_reasons,
            "root_evidence": {
                "status": "line_level_confirmed_for_repair_planning",
                "experiment_id": exp_id,
                "outcome": "error_disappeared",
                "fingerprint": fingerprint,
                "p2_valid_for_inference": True,
                "p2_root_cause_confirmation_allowed": True,
                "p2_gate_snapshot": {
                    gate: True for gate in sorted(_P2_REQUIRED_GATES)
                },
                "rollback_sha256_verified": True,
                "rollback_original_fingerprint_reproduced": True,
                "modified_run_evidence": _mapping(record.get("run")).get(
                    "evidence", ""
                ),
                "rollback_run_evidence": _mapping(record.get("rollback")).get(
                    "evidence", ""
                ),
                "located_root": dict(located),
                "static_context": {
                    "rule_id": static.get("rule_id", ""),
                    "status": static.get("status", ""),
                    "note": (
                        "Static candidate/suspected context is not root proof."
                    ),
                },
            },
            "subtype": subtype,
            "target": {
                "file": file,
                "line": line,
                "api": api,
                "rule": experiment.get("rule", ""),
                "allowed_scope": (
                    "Anchor and minimal dependency closure in this file only; "
                    "additional files require a new repair plan."
                ),
            },
            "minimal_change_intent": {
                "kind": template["kind"],
                "statement": template["intent"],
                "patch": None,
            },
            "a5_invariants": template["invariants"],
            "forbidden_changes": template["forbidden"],
            "api_verification": api_check,
            "semantic_risks": template["risks"],
            "rollback_restore": {
                "required": True,
                "method": (
                    "Keep a repair-local reverse patch/restore artifact for "
                    "only the declared target scope; no git reset/checkout."
                ),
                "target_files": [file],
                "evidence_required": True,
            },
            "verification_matrix": matrix,
        }
        repairs.append(repair)

    result = {
        "schema_version": SCHEMA_VERSION,
        "fingerprint": fingerprint or "<missing>",
        "source_phase": str(context.get("source_phase", "")),
        "buffer_mode": str(context.get("buffer_mode", "")),
        "status": (
            "ready" if any(item["executable"] for item in repairs)
            else "deferred" if repairs
            else "refused"
        ),
        "repairs": repairs,
        "refused_candidates": refused,
        "summary": {
            "ready_count": sum(item["executable"] for item in repairs),
            "deferred_count": sum(not item["executable"] for item in repairs),
            "refused_count": len(refused),
            "static_root_promotions": 0,
            "source_modified": False,
            "device_accessed": False,
            "note": (
                "Repair plans contain intent only. Apply externally, then "
                "validate real build/run/scope/API evidence."
            ),
        },
    }
    validate_repair_plan_schema(result)
    return result


def validate_repair_plan_schema(plan: Mapping[str, Any]) -> None:
    if plan.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported repair plan schema_version")
    fingerprint = str(plan.get("fingerprint", ""))
    if not fingerprint or fingerprint == "<missing>":
        raise ValueError("repair plan original fingerprint is missing")
    repairs = plan.get("repairs")
    if not isinstance(repairs, list):
        raise ValueError("repair plan repairs must be a list")
    ids: set[str] = set()
    for index, value in enumerate(repairs):
        repair = _mapping(value)
        missing = sorted(_REPAIR_REQUIRED_FIELDS - repair.keys())
        if missing:
            raise ValueError(
                f"repair[{index}] missing fields: {', '.join(missing)}"
            )
        repair_id = str(repair.get("repair_id", ""))
        if not repair_id or repair_id in ids:
            raise ValueError(f"repair[{index}] has empty/duplicate repair_id")
        ids.add(repair_id)
        if repair.get("status") not in REPAIR_STATUSES:
            raise ValueError(f"repair[{index}] has invalid status")
        if repair.get("executable") is not (
            repair.get("status") == "ready"
        ):
            raise ValueError(f"repair[{index}] executable/status mismatch")
        api_status = _mapping(repair.get("api_verification")).get("status")
        if api_status not in API_STATUSES:
            raise ValueError(f"repair[{index}] has invalid API status")
        root = _mapping(repair.get("root_evidence"))
        gates = _mapping(root.get("p2_gate_snapshot"))
        if any(gates.get(gate) is not True for gate in _P2_REQUIRED_GATES):
            raise ValueError(f"repair[{index}] lacks mandatory P2 gate proof")
        if (
            root.get("status")
            != "line_level_confirmed_for_repair_planning"
            or root.get("outcome") != "error_disappeared"
            or root.get("fingerprint") != fingerprint
            or root.get("p2_valid_for_inference") is not True
            or root.get("p2_root_cause_confirmation_allowed") is not True
            or root.get("rollback_sha256_verified") is not True
            or root.get(
                "rollback_original_fingerprint_reproduced"
            ) is not True
        ):
            raise ValueError(
                f"repair[{index}] lacks complete P2 root evidence"
            )
        located = _mapping(root.get("located_root"))
        confirmation = _mapping(located.get("confirmation"))
        if (
            located.get("experiment_id") != root.get("experiment_id")
            or located.get("confidence") != "confirmed"
            or located.get("fingerprint") != fingerprint
            or not _nonempty(located.get("evidence"))
            or any(
                confirmation.get(field) is not True
                for field in (
                    "baseline_reproduced",
                    "error_disappeared",
                    "restored_original_fingerprint",
                    "invariants_verified",
                )
            )
        ):
            raise ValueError(
                f"repair[{index}] lacks complete line-level confirmation"
            )
        target = _mapping(repair.get("target"))
        target_file = _safe_relative_source(target.get("file"))
        target_line = target.get("line")
        if not isinstance(target_line, int) or target_line < 1:
            raise ValueError(f"repair[{index}] has invalid target line")
        if (
            located.get("file") != target_file
            or located.get("line") != target_line
        ):
            raise ValueError(
                f"repair[{index}] line-level confirmation target mismatch"
            )
        intent = _mapping(repair.get("minimal_change_intent"))
        if intent.get("patch") is not None:
            raise ValueError(
                f"repair[{index}] must contain intent, not an automatic patch"
            )
        api = _mapping(repair.get("api_verification"))
        if repair.get("executable") is True and not _api_verified(api):
            raise ValueError(
                f"repair[{index}] executable repair lacks verified 910D API"
            )
        matrix = repair.get("verification_matrix")
        if not isinstance(matrix, list):
            raise ValueError(
                f"repair[{index}].verification_matrix must be a list"
            )
        originals = [
            _mapping(item) for item in matrix
            if _mapping(item).get("name") == "original_case_repeat"
        ]
        if (
            len(originals) != 1
            or originals[0].get("status") != "ready"
            or originals[0].get("minimum_repeats", 0) < 2
            or not originals[0].get("case_ids")
        ):
            raise ValueError(
                f"repair[{index}] lacks original-case repeat verification"
            )


def _repair_records(payload: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return _indexed(
        payload.get("repairs", payload.get("records", [])),
        ("repair_id", "id"),
        "repair_records.repairs",
    )


def _api_verified(api: Mapping[str, Any]) -> bool:
    return (
        api.get("status") == "verified"
        and not api.get("missing")
        and "910d" in str(api.get("target", "")).lower()
        and all(
            _nonempty(api.get(field))
            for field in ("target", "cann_version", "doc", "source", "version")
        )
    )


def validate_repair_records(
    repair_plan: Mapping[str, Any],
    records_payload: Mapping[str, Any],
) -> dict[str, Any]:
    validate_repair_plan_schema(repair_plan)
    records = _repair_records(records_payload)
    planned = {
        str(_mapping(item).get("repair_id", "")): _mapping(item)
        for item in repair_plan["repairs"]
    }
    unknown = sorted(set(records) - set(planned))
    if unknown:
        raise ValueError(
            "repair records contain ids not present in plan: "
            + ", ".join(unknown)
        )
    validated: list[dict[str, Any]] = []
    for repair_id, repair in planned.items():
        record = records.get(repair_id, {})
        schema_errors: list[str] = []
        build = _mapping(record.get("build"))
        rollback = _mapping(record.get("rollback_restore"))
        runs = record.get("target_case_runs")
        scopes = record.get("changed_scope")
        matrix_records = record.get("verification_matrix")
        if not isinstance(runs, list):
            schema_errors.append("target_case_runs must be a list")
            runs = []
        if not isinstance(scopes, list):
            schema_errors.append("changed_scope must be a list")
            scopes = []
        if not isinstance(matrix_records, list):
            schema_errors.append("verification_matrix must be a list")
            matrix_records = []
        if not isinstance(record.get("scope_matches_plan"), bool):
            schema_errors.append("scope_matches_plan must be bool")
        if not isinstance(record.get("invariants_verified"), bool):
            schema_errors.append("invariants_verified must be bool")
        if not isinstance(record.get("build"), Mapping):
            schema_errors.append("build must be an object")
        if not isinstance(record.get("rollback_restore"), Mapping):
            schema_errors.append("rollback_restore must be an object")
        if isinstance(record.get("build"), Mapping) and (
            build.get("status") not in {"passed", "failed", "not_run"}
        ):
            schema_errors.append("build.status must be passed/failed/not_run")

        original_case_entry = next(
            (
                item for item in repair["verification_matrix"]
                if item.get("name") == "original_case_repeat"
            ),
            {},
        )
        original_case_ids = original_case_entry.get("case_ids", [])
        original_case = (
            str(original_case_ids[0]) if original_case_ids else ""
        )
        original_runs = [
            _mapping(item) for item in runs
            if _mapping(item).get("case_id") == original_case
        ]
        original_positions = [
            index for index, item in enumerate(runs)
            if _mapping(item).get("case_id") == original_case
        ]
        consecutive_original_runs = any(
            right == left + 1
            for left, right in zip(
                original_positions, original_positions[1:]
            )
        )
        run_schema_valid = True
        for run in original_runs:
            if (
                run.get("status") != "completed"
                or not isinstance(run.get("original_error_observed"), bool)
                or not isinstance(run.get("different_device_exception"), bool)
                or not isinstance(run.get("observed_fingerprint"), str)
                or not _nonempty(run.get("evidence"))
            ):
                run_schema_valid = False
        target = _mapping(repair.get("target"))
        target_file = str(target.get("file", ""))
        scope_files = {
            str(_mapping(item).get("file", "")) for item in scopes
        }
        scope_evidence_complete = bool(scopes) and all(
            _nonempty(_mapping(item).get("justification"))
            and isinstance(_mapping(item).get("line_start"), int)
            and isinstance(_mapping(item).get("line_end"), int)
            and _mapping(item).get("line_start")
            <= _mapping(item).get("line_end")
            for item in scopes
        )
        anchor_line = int(target.get("line", 0) or 0)
        anchor_covered = any(
            _mapping(item).get("file") == target_file
            and isinstance(_mapping(item).get("line_start"), int)
            and isinstance(_mapping(item).get("line_end"), int)
            and _mapping(item).get("line_start") <= anchor_line
            <= _mapping(item).get("line_end")
            for item in scopes
        )
        plan_api = _mapping(repair.get("api_verification"))
        record_api = _mapping(record.get("api_verification"))
        api_consistent = all(
            record_api.get(field) == plan_api.get(field)
            for field in (
                "status", "target", "soc", "cann_version",
                "doc", "source", "version", "claim",
            )
        )
        matrix_by_name = {
            str(_mapping(item).get("name", "")): _mapping(item)
            for item in matrix_records
            if _nonempty(_mapping(item).get("name"))
        }
        matrix_names = [
            str(_mapping(item).get("name", ""))
            for item in matrix_records
            if _nonempty(_mapping(item).get("name"))
        ]
        if len(matrix_names) != len(set(matrix_names)):
            schema_errors.append(
                "verification_matrix must not contain duplicate names"
            )
        ready_matrix = [
            item for item in repair["verification_matrix"]
            if item.get("status") == "ready"
        ]
        ready_matrix_passed = all(
            _mapping(matrix_by_name.get(str(item["name"]), {})).get("status")
            == "passed"
            and _nonempty(
                _mapping(matrix_by_name.get(str(item["name"]), {})).get(
                    "evidence"
                )
            )
            and _mapping(
                matrix_by_name.get(str(item["name"]), {})
            ).get("original_error_observed") is False
            and _mapping(
                matrix_by_name.get(str(item["name"]), {})
            ).get("different_device_exception") is False
            for item in ready_matrix
        )
        root = _mapping(repair.get("root_evidence"))
        p2_gates = _mapping(root.get("p2_gate_snapshot"))
        gates = {
            "repair_was_executable": repair.get("executable") is True,
            "p2_root_evidence_valid": (
                root.get("outcome") == "error_disappeared"
                and root.get("p2_valid_for_inference") is True
                and root.get("p2_root_cause_confirmation_allowed") is True
                and root.get("rollback_sha256_verified") is True
                and root.get(
                    "rollback_original_fingerprint_reproduced"
                ) is True
                and all(
                    p2_gates.get(gate) is True
                    for gate in _P2_REQUIRED_GATES
                )
            ),
            "build_passed": build.get("status") == "passed",
            "build_evidence_recorded": _nonempty(build.get("evidence")),
            "original_case_repeat_count": len(original_runs) >= 2,
            "original_case_runs_consecutive": consecutive_original_runs,
            "original_case_runs_independent": (
                len(original_runs) >= 2
                and len({
                    str(run.get("evidence", ""))
                    for run in original_runs
                }) == len(original_runs)
            ),
            "original_case_runs_schema_valid": (
                bool(original_runs) and run_schema_valid
            ),
            "original_fingerprint_absent": bool(original_runs) and all(
                run.get("original_error_observed") is False
                and not run.get("observed_fingerprint")
                for run in original_runs
            ),
            "no_different_device_exception": bool(original_runs) and all(
                run.get("different_device_exception") is False
                for run in original_runs
            ),
            "scope_matches_plan": (
                record.get("scope_matches_plan") is True
                and scope_files == {target_file}
                and scope_evidence_complete
                and anchor_covered
            ),
            "invariants_verified": record.get("invariants_verified") is True,
            "api_verification_consistent": api_consistent,
            "required_api_verified": _api_verified(plan_api),
            "rollback_restore_complete": (
                rollback.get("available") is True
                and _nonempty(rollback.get("method"))
                and _nonempty(rollback.get("evidence"))
                and rollback.get("target_files") == [target_file]
            ),
            "ready_verification_matrix_passed": ready_matrix_passed,
            "record_schema_valid": not schema_errors,
        }
        verified = all(gates.values())
        ordinary_precision = _mapping(record.get("ordinary_precision_failure"))
        next_hint = ""
        if ordinary_precision.get("observed") is True:
            next_hint = str(
                ordinary_precision.get("next_hint")
                or "VECTOR_ERROR cleared; continue ordinary precision debugging."
            )
        validated.append({
            "repair_id": repair_id,
            "repair_verified": verified,
            "vector_error_fixed_allowed": verified,
            "gates": gates,
            "invalid_reasons": [
                name for name, passed in gates.items() if not passed
            ] + schema_errors,
            "next_hint": next_hint,
        })
    return {
        "schema_version": VALIDATION_SCHEMA_VERSION,
        "fingerprint": repair_plan.get("fingerprint", "<missing>"),
        "repairs": validated,
        "summary": {
            "validated_count": len(validated),
            "repair_verified_count": sum(
                item["repair_verified"] for item in validated
            ),
            "vector_error_fixed_allowed": any(
                item["vector_error_fixed_allowed"] for item in validated
            ),
        },
    }


def _write_or_print(result: Mapping[str, Any], output: Path | None, pretty: bool) -> None:
    rendered = json.dumps(
        result, ensure_ascii=False, sort_keys=True, indent=2 if pretty else None
    ) + "\n"
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    sys.stdout.write(rendered)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Plan/validate evidence-gated A5 VECTOR_ERROR repairs."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan = subparsers.add_parser("plan")
    plan.add_argument("--evidence", type=Path, required=True)
    plan.add_argument("--static-scan", type=Path, required=True)
    plan.add_argument("--experiment-plan", type=Path, required=True)
    plan.add_argument("--experiment-validation", type=Path, required=True)
    plan.add_argument("--experiment-records", type=Path, required=True)
    plan.add_argument("--located-roots", type=Path)
    plan.add_argument("--history", type=Path)
    plan.add_argument("--api-verification", type=Path)
    plan.add_argument("--output", type=Path)
    plan.add_argument("--pretty", action="store_true")

    validate = subparsers.add_parser("validate")
    validate.add_argument("--repair-plan", type=Path, required=True)
    validate.add_argument("--records", type=Path, required=True)
    validate.add_argument("--output", type=Path)
    validate.add_argument("--pretty", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "plan":
            result = plan_repairs(
                _load_json(args.evidence),
                _load_json(args.static_scan),
                _load_json(args.experiment_plan),
                _load_json(args.experiment_validation),
                _load_json(args.experiment_records),
                located_roots=_load_json(args.located_roots),
                history=_load_json(args.history),
                api_verification=_load_json(args.api_verification),
            )
        else:
            result = validate_repair_records(
                _load_json(args.repair_plan),
                _load_json(args.records),
            )
        _write_or_print(result, args.output, args.pretty)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"plan_a5_vector_repairs: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
