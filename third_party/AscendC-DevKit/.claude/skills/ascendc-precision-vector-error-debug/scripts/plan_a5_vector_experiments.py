#!/usr/bin/env python3
"""Plan and validate controlled A5 VECTOR_ERROR experiments.

This tool is deliberately device-independent.  It never edits operator
sources, runs build/test commands, reads global logs, or performs rollback.
It turns P1 candidates into auditable recipes and provides a SHA256 guard that
can prove experiment-local source changes were restored before the result is
used for inference.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "1.0"
MANIFEST_SCHEMA_VERSION = "1.0"
VALIDATION_SCHEMA_VERSION = "1.0"
MAX_EXPERIMENTS = 4
SOURCE_SUFFIXES = {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx"}
OUTCOMES = {
    "same_error",
    "error_disappeared",
    "different_error",
    "compile_fail",
    "not_reproduced",
    "not_run",
}
INFERENCE_OUTCOMES = {"same_error", "error_disappeared"}

_PLAN_REQUIRED_FIELDS = {
    "id",
    "candidate",
    "rule",
    "subtype",
    "file",
    "line",
    "hypothesis",
    "experiment_kind",
    "preconditions",
    "exact_scope",
    "invariants",
    "allowed_changes",
    "forbidden_changes",
    "build_command",
    "test_command",
    "case_id",
    "oracle",
    "rollback",
    "interpretation",
    "status",
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
        "reproducibility",
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
            "reproducibility",
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
                for bundle in (
                    "vector_error_evidence",
                    "runtime_evidence",
                    "reproducibility",
                ):
                    value = _mapping(case.get(bundle))
                    if value:
                        sources.append(value)
                sources.append(case)
    sources.append(payload)
    return sources


def extract_context(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Extract planner context without reading logs or recomputing identity."""
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


def _reproduced(context: Mapping[str, Any]) -> bool:
    explicit = context.get("baseline_reproduced")
    if isinstance(explicit, bool):
        return explicit
    reproduction = context.get("reproducibility")
    if isinstance(reproduction, Mapping):
        status = str(reproduction.get("status", "")).lower()
        failures = reproduction.get("failure_count")
        return status in {"stable", "intermittent"} and (
            not isinstance(failures, int) or failures > 0
        )
    status = str(context.get("status", "")).lower()
    failures = context.get("failure_count")
    return status in {"stable", "intermittent"} and (
        not isinstance(failures, int) or failures > 0
    )


def _candidate_key(
    candidate: Mapping[str, Any],
) -> tuple[str, str, int, str, str]:
    try:
        line = int(candidate.get("line", 0))
    except (TypeError, ValueError):
        line = 0
    return (
        str(candidate.get("file", "")),
        str(candidate.get("rule_id") or candidate.get("rule", "")),
        line,
        str(candidate.get("subtype", "")),
        str(candidate.get("api") or candidate.get("symbol", "")),
    )


def _history_keys(
    history: Mapping[str, Any] | None,
) -> set[tuple[str, str, int, str, str]]:
    if not isinstance(history, Mapping):
        return set()
    keys: set[tuple[str, str, int, str, str]] = set()
    containers: list[tuple[Any, bool]] = [
        (history.get("experiments", []), False),
        (history.get("located_roots", []), True),
    ]
    nested_history = history.get("history")
    if isinstance(nested_history, list):
        for item in nested_history:
            nested = _mapping(item)
            if nested:
                keys.update(_history_keys(nested))
    for container, site_is_confirmed in containers:
        if isinstance(container, Mapping):
            items = [container]
        elif isinstance(container, list):
            items = container
        else:
            continue
        for item in items:
            record = _mapping(item)
            candidate = dict(record)
            candidate.update(_mapping(record.get("candidate")))
            key = _candidate_key(candidate)
            if key[0] and (key[1] or key[2]):
                keys.add(key)
                if site_is_confirmed and key[2]:
                    keys.add((key[0], "", key[2], "", ""))
    return keys


def _exact_test_command(command: str, case_id: str) -> str:
    if not command or not case_id:
        return ""
    quoted = shlex.quote(case_id)
    if "{case_id}" in command:
        return command.replace("{case_id}", quoted)
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    if "--case" in tokens:
        return command
    return f"{command} --case {quoted}"


def _precondition(name: str, satisfied: bool, evidence: str) -> dict[str, Any]:
    return {
        "name": name,
        "satisfied": bool(satisfied),
        "evidence": evidence,
    }


def _common_recipe(
    candidate: Mapping[str, Any],
    *,
    fingerprint: str,
    case_id: str,
    build_command: str,
    test_command: str,
    baseline_reproduced: bool,
) -> dict[str, Any]:
    file = str(candidate.get("file", ""))
    line = int(candidate.get("line", 0) or 0)
    rule = str(candidate.get("rule_id") or candidate.get("rule", ""))
    subtype = str(candidate.get("subtype", "unknown"))
    symbol = str(candidate.get("api") or candidate.get("symbol", ""))
    return {
        "candidate": {
            "rank": candidate.get("rank"),
            "final_score": candidate.get("final_score"),
            "status": candidate.get("status", "candidate"),
            "api": symbol,
            "reason": candidate.get("reason", ""),
        },
        "rule": rule,
        "subtype": subtype,
        "file": file,
        "line": line,
        "preconditions": [
            _precondition(
                "baseline_reproduced",
                baseline_reproduced,
                "The unmodified target case must reproduce the original fingerprint.",
            ),
            _precondition(
                "build_command_available",
                bool(build_command),
                build_command or "missing",
            ),
            _precondition(
                "target_case_available",
                bool(case_id),
                case_id or "missing",
            ),
            _precondition(
                "test_command_available",
                bool(test_command),
                test_command or "missing",
            ),
        ],
        "exact_scope": {
            "file": file,
            "line": line,
            "symbol": symbol,
            "rule_id": rule,
            "constraint": (
                "Only this site in the declared target file may change. If a "
                "semantics-closed control needs another source file, defer and "
                "generate a new explicitly scoped plan."
            ),
        },
        "invariants": [
            "The target case, original fingerprint oracle, tiling and source buffer mode remain unchanged unless this recipe explicitly requests a runtime differential.",
            "Every consumer reads initialized data and every produced value keeps a valid consumer.",
            "Queue, event and producer-consumer protocols remain complete on every participating path/core.",
            "Exactly one diagnosed factor changes; unrelated arithmetic and addresses remain unchanged.",
        ],
        "allowed_changes": [],
        "forbidden_changes": [
            "Do not delete or comment out a DataCopy/Load/Store while leaving its consumer active.",
            "Do not remove only one side of Alloc/EnQue/DeQue/Free, Set/Wait, CrossCore or LocalMemBar dependencies.",
            "Do not change multiple algorithms, tiling variables, buffer modes or synchronization protocols in one experiment.",
            "Do not use device printf, uninitialized UB/RegTensor placeholders, git reset, git checkout or whole-file overwrite as rollback.",
        ],
        "build_command": build_command,
        "test_command": _exact_test_command(test_command, case_id),
        "case_id": case_id,
        "oracle": {
            "identity": fingerprint or "<missing>",
            "identity_fields": "Use the P0 fingerprint; log text/path is audit evidence only.",
            "outcomes": sorted(OUTCOMES),
        },
        "rollback": {
            "method": "Reverse only the experiment-local patch after recording the run.",
            "manifest_required": True,
            "target_files": [file] if file else [],
            "verification": "SHA256 must match baseline manifest before inference.",
            "destructive_commands_allowed": False,
        },
        "interpretation": {
            "same_error": "Candidate is examined for this recipe; continue ranking.",
            "error_disappeared": "Candidate becomes suspect_root only; line confirmation still requires restore-and-reproduce.",
            "different_error": "Invalid for root-cause inference; restore and record the new signature.",
            "compile_fail": "Invalid experiment; restore and do not rank the candidate down.",
            "not_reproduced": "Baseline/runner is unstable; invalid for inference.",
            "not_run": "No inference is permitted.",
        },
        "status": "planned",
    }


def _recipe_for(
    candidate: Mapping[str, Any],
    context: Mapping[str, Any],
    **common_args: Any,
) -> tuple[dict[str, Any] | None, str]:
    subtype = str(candidate.get("subtype", "unknown"))
    base = _common_recipe(candidate, **common_args)

    if subtype == "layout_cast_dist":
        proof = (
            candidate.get("layout_equivalence_proof")
            or context.get("layout_equivalence_proof")
        )
        if not _nonempty(proof):
            return None, (
                "blocked: no current-SoC/CANN layout-equivalence proof; changing "
                "Cast/LoadDist/StoreDist could alter logical lane order"
            )
        base.update({
            "hypothesis": (
                "The selected Cast/distribution contract changes the intended "
                "lane layout at this site."
            ),
            "experiment_kind": "layout_equivalent_control",
        })
        base["preconditions"].append(_precondition(
            "layout_equivalence_proven", True, str(proof)
        ))
        base["allowed_changes"] = [
            "Substitute only the API-documented, lane-for-lane equivalent layout expression identified by the supplied proof.",
            "Keep input/output dtype, logical lane order, active mask and address progression identical.",
        ]
        return base, ""

    if subtype in {"gm_ub_transport", "address_generation"}:
        base.update({
            "hypothesis": (
                "The target transport/address expression crosses its initialized "
                "source, destination or tail boundary."
            ),
            "experiment_kind": "transport_address_bounds_probe",
        })
        base["allowed_changes"] = [
            "Safely reduce only the target tile/burst/repeat to a documented in-bounds value while keeping the complete producer-consumer chain.",
            "Alternatively redirect only this site to a correctly sized, initialized diagnostic buffer with identical dtype/layout and a valid consumer.",
        ]
        base["invariants"].append(
            "Use SingleOperatorLaunch sentinel plus unchanged-output checks, or an explicit memcheck run, when the existing harness supports it; do not access a device automatically."
        )
        base["oracle"]["auxiliary_checks"] = [
            "SingleOperatorLaunch sentinel guard",
            "expected output changed check",
            "mssanitizer/memcheck if explicitly configured",
        ]
        return base, ""

    if subtype in {"ub_reg_load_store", "vf_call_abi"}:
        base.update({
            "hypothesis": (
                "The VECTOR_ERROR is introduced at the VF boundary or in the "
                "Load→Compute→Store segment containing this site."
            ),
            "experiment_kind": "vf_load_compute_store_isolation",
        })
        base["allowed_changes"] = [
            "Keep Load and Store protocols intact while replacing only the compute expression with a type/layout-equivalent identity.",
            "If isolating Load or Store, provide a fully initialized UB/RegTensor placeholder with the same mask, lane count, dtype and consumer coverage.",
        ]
        base["invariants"].append(
            "VF_CALL ABI, GetPhyAddr provenance, Load/Store distribution, post-update progression and active-lane coverage remain valid."
        )
        return base, ""

    if subtype == "mask_tail":
        base.update({
            "hypothesis": (
                "The failure depends on active-lane/tail state rather than the "
                "aligned full-vector path."
            ),
            "experiment_kind": "mask_tail_boundary_matrix",
        })
        boundary_cases = context.get("boundary_cases")
        base["preconditions"].append(_precondition(
            "boundary_cases_available",
            isinstance(boundary_cases, list) and bool(boundary_cases),
            json.dumps(boundary_cases, ensure_ascii=False)
            if isinstance(boundary_cases, list) and boundary_cases
            else "missing: provide safe aligned and VL-1/VL/VL+1 cases",
        ))
        base["allowed_changes"] = [
            "Prefer runtime case differential: aligned shape versus VL-1, VL and VL+1 using existing valid cases.",
            "A controlled all-valid mask is diagnostic-only and allowed only when allocation/padding proves every activated lane is in bounds; otherwise do not run it.",
            "Reset only the target mask counter at the same row/tile scope for a single-variable comparison.",
        ]
        base["forbidden_changes"].append(
            "Never force all-valid lanes over an unpadded tail or change Store mask dtype."
        )
        return base, ""

    if subtype in {"incore_sync", "queue_lifecycle", "crosscore_tscm"}:
        base.update({
            "hypothesis": (
                "The failure depends on scheduling, buffer reuse or producer/"
                "consumer visibility rather than a deterministic arithmetic value."
            ),
            "experiment_kind": "sync_buffer_core_differential",
        })
        mode_controls = context.get("mode_commands") or context.get(
            "diagnostic_mode_commands"
        )
        base["preconditions"].append(_precondition(
            "controlled_mode_switch_available",
            isinstance(mode_controls, Mapping) and bool(mode_controls),
            "explicit runner/build mode commands supplied"
            if isinstance(mode_controls, Mapping) and mode_controls
            else "missing: do not synthesize buffer/core switches",
        ))
        base["allowed_changes"] = [
            "Use existing, explicitly supplied controls to compare single/double buffer or one/original core count without editing only one synchronization endpoint.",
            "For intermittent failures, repeat the identical target case and compare fingerprint frequency before changing code.",
            "Isolate only a complete Alloc→EnQue→DeQue→Free or Set→Wait producer-consumer chain while preserving all participating cores.",
        ]
        base["forbidden_changes"].append(
            "Never delete, bypass or reorder only one Set/Wait/LocalMemBar/CrossCore/queue endpoint."
        )
        return base, ""

    if subtype == "tiling_boundary":
        base.update({
            "hypothesis": (
                "Only zero/one work, the last core, last repeat or non-aligned "
                "tail reaches an invalid address or empty operation."
            ),
            "experiment_kind": "tiling_boundary_case_matrix",
        })
        boundary_cases = context.get("boundary_cases")
        base["preconditions"].append(_precondition(
            "boundary_cases_available",
            isinstance(boundary_cases, list) and bool(boundary_cases),
            json.dumps(boundary_cases, ensure_ascii=False)
            if isinstance(boundary_cases, list) and boundary_cases
            else "missing: provide zero/1/last-core/last-repeat valid cases",
        ))
        base["allowed_changes"] = [
            "Run existing valid zero/one/tail/last-core/last-repeat cases with identical code.",
            "If code instrumentation is required, guard only the proven zero-work branch while preserving all mandatory synchronization participation.",
        ]
        return base, ""

    return None, f"blocked: no semantics-closed A5 recipe for subtype {subtype!r}"


def _experiment_id(
    fingerprint: str,
    candidate: Mapping[str, Any],
    experiment_kind: str,
) -> str:
    material = "|".join(str(item) for item in (
        fingerprint or "<missing>",
        *_candidate_key(candidate),
        experiment_kind,
    ))
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]
    return f"a5ve-{digest}"


def plan_experiments(
    static_scan: Mapping[str, Any],
    *,
    evidence: Mapping[str, Any] | None = None,
    history: Mapping[str, Any] | None = None,
    build_command: str = "",
    test_command: str = "",
    max_experiments: int = MAX_EXPERIMENTS,
    baseline_reproduced: bool | None = None,
) -> dict[str, Any]:
    if max_experiments < 1 or max_experiments > MAX_EXPERIMENTS:
        raise ValueError(f"max_experiments must be between 1 and {MAX_EXPERIMENTS}")
    ranking = static_scan.get("candidate_ranking")
    if not isinstance(ranking, list):
        raise ValueError("static scan is missing candidate_ranking list")
    context = extract_context(evidence or {})
    fingerprint = str(context.get("fingerprint", ""))
    source_phase = str(context.get("source_phase", ""))
    buffer_mode = str(context.get("buffer_mode", ""))
    case_id = str(context.get("case_id", ""))
    baseline_ok = (
        bool(baseline_reproduced)
        if baseline_reproduced is not None
        else _reproduced(context)
    )
    examined = _history_keys(history)
    experiments: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []

    ranked = sorted(
        (_mapping(item) for item in ranking if isinstance(item, Mapping)),
        key=lambda item: (
            int(item.get("rank", 10**9) or 10**9),
            -int(item.get("final_score", 0) or 0),
            *_candidate_key(item),
        ),
    )
    for candidate in ranked:
        key = _candidate_key(candidate)
        if (
            key in examined
            or (key[0], key[1], key[2], key[3], "") in examined
            or (key[0], "", key[2], "", "") in examined
        ):
            deferred.append({
                "candidate": dict(candidate),
                "reason": "history_skip: candidate already examined or located",
                "blocked": False,
            })
            continue
        if len(experiments) >= max_experiments:
            deferred.append({
                "candidate": dict(candidate),
                "reason": f"deferred: per-round limit {max_experiments} reached",
                "blocked": False,
            })
            continue
        recipe, reason = _recipe_for(
            candidate,
            context,
            fingerprint=fingerprint,
            case_id=case_id,
            build_command=build_command,
            test_command=test_command,
            baseline_reproduced=baseline_ok,
        )
        if recipe is None:
            deferred.append({
                "candidate": dict(candidate),
                "reason": reason,
                "blocked": True,
            })
            continue
        recipe["id"] = _experiment_id(
            fingerprint, candidate, recipe["experiment_kind"]
        )
        experiments.append(recipe)

    missing = [
        name
        for name, value in (
            ("fingerprint", fingerprint),
            ("case_id", case_id),
            ("build_command", build_command),
            ("test_command", test_command),
        )
        if not value
    ]
    if not baseline_ok:
        missing.append("baseline_reproduced")
    executable = sum(
        all(item["satisfied"] for item in experiment["preconditions"])
        for experiment in experiments
    )
    plan = {
        "schema_version": SCHEMA_VERSION,
        "fingerprint": fingerprint or "<missing>",
        "source_phase": source_phase,
        "buffer_mode": buffer_mode,
        "baseline_gate": {
            "required": True,
            "status": "reproduced" if baseline_ok else "not_reproduced",
            "original_fingerprint": fingerprint or "<missing>",
            "case_id": case_id,
            "missing": sorted(set(missing)),
            "logs_are_identity": False,
        },
        "experiments": experiments,
        "deferred_candidates": deferred,
        "summary": {
            "planned_count": len(experiments),
            "executable_count": executable,
            "deferred_count": len(deferred),
            "max_experiments": max_experiments,
            "source_modified": False,
            "device_accessed": False,
            "note": (
                "Plans are recipes only. Apply one experiment at a time, build/"
                "run externally, reverse its local patch, then validate SHA256."
            ),
        },
    }
    validate_plan_schema(plan)
    return plan


def validate_plan_schema(plan: Mapping[str, Any]) -> None:
    if plan.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported experiment plan schema_version")
    experiments = plan.get("experiments")
    if not isinstance(experiments, list):
        raise ValueError("plan.experiments must be a list")
    if len(experiments) > MAX_EXPERIMENTS:
        raise ValueError(f"plan exceeds maximum {MAX_EXPERIMENTS} experiments")
    ids: set[str] = set()
    for index, value in enumerate(experiments):
        experiment = _mapping(value)
        missing = sorted(_PLAN_REQUIRED_FIELDS - experiment.keys())
        if missing:
            raise ValueError(
                f"experiment[{index}] missing fields: {', '.join(missing)}"
            )
        if experiment.get("status") != "planned":
            raise ValueError(f"experiment[{index}].status must be planned")
        exp_id = str(experiment.get("id", ""))
        if not exp_id or exp_id in ids:
            raise ValueError(f"experiment[{index}] has empty/duplicate id")
        ids.add(exp_id)
        if not isinstance(experiment.get("preconditions"), list):
            raise ValueError(f"experiment[{index}].preconditions must be a list")
        forbidden_text = " ".join(
            str(item) for item in experiment.get("allowed_changes", [])
        ).lower()
        dangerous = (
            "delete setflag",
            "delete waitflag",
            "remove localmembar",
            "comment out datacopy",
            "git reset",
            "git checkout",
        )
        if any(token in forbidden_text for token in dangerous):
            raise ValueError(f"experiment[{index}] contains a destructive recipe")


def _safe_source(operator_dir: Path, relative: str) -> tuple[Path, str]:
    rel = Path(relative)
    if not relative or rel.is_absolute() or ".." in rel.parts:
        raise ValueError(f"unsafe source path: {relative!r}")
    root = operator_dir.resolve()
    target = (root / rel).resolve()
    try:
        normalized = target.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError(f"source escapes operator_dir: {relative!r}") from exc
    if target.suffix.lower() not in SOURCE_SUFFIXES or not target.is_file():
        raise ValueError(f"target is not a readable C/C++ source: {relative!r}")
    return target, normalized


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def create_baseline_manifest(
    operator_dir: Path,
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    validate_plan_schema(plan)
    targets: dict[str, Path] = {}
    for value in plan["experiments"]:
        experiment = _mapping(value)
        path, relative = _safe_source(operator_dir, str(experiment["file"]))
        targets[relative] = path
    files = [
        {
            "path": relative,
            "sha256": _sha256(path),
            "size": path.stat().st_size,
        }
        for relative, path in sorted(targets.items())
    ]
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "algorithm": "sha256",
        "fingerprint": plan.get("fingerprint", "<missing>"),
        "files": files,
        "source_modified": False,
    }


def verify_rollback(
    operator_dir: Path,
    manifest: Mapping[str, Any],
    *,
    target_files: Sequence[str] | None = None,
) -> dict[str, Any]:
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ValueError("unsupported baseline manifest schema_version")
    entries = manifest.get("files")
    if not isinstance(entries, list):
        raise ValueError("manifest.files must be a list")
    selected = set(target_files or ())
    results: list[dict[str, Any]] = []
    for value in entries:
        entry = _mapping(value)
        relative = str(entry.get("path", ""))
        if selected and relative not in selected:
            continue
        path, normalized = _safe_source(operator_dir, relative)
        actual = _sha256(path)
        expected = str(entry.get("sha256", ""))
        results.append({
            "path": normalized,
            "expected_sha256": expected,
            "actual_sha256": actual,
            "restored": bool(expected) and actual == expected,
        })
    missing = sorted(selected - {item["path"] for item in results})
    return {
        "verified": bool(results) and not missing
        and all(item["restored"] for item in results),
        "files": results,
        "missing_manifest_files": missing,
    }


def _validate_manifest_for_plan(
    plan: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> None:
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ValueError("unsupported baseline manifest schema_version")
    if manifest.get("algorithm") != "sha256":
        raise ValueError("baseline manifest algorithm must be sha256")
    if manifest.get("fingerprint") != plan.get("fingerprint"):
        raise ValueError("baseline manifest fingerprint does not match plan")
    entries = manifest.get("files")
    if not isinstance(entries, list):
        raise ValueError("manifest.files must be a list")
    manifest_paths: list[str] = []
    for index, value in enumerate(entries):
        entry = _mapping(value)
        path = str(entry.get("path", ""))
        digest = str(entry.get("sha256", ""))
        if not path:
            raise ValueError(f"manifest.files[{index}].path is missing")
        if len(digest) != 64 or any(
            char not in "0123456789abcdef" for char in digest.lower()
        ):
            raise ValueError(
                f"manifest.files[{index}].sha256 is not a SHA256 digest"
            )
        manifest_paths.append(path)
    if len(manifest_paths) != len(set(manifest_paths)):
        raise ValueError("manifest.files contains duplicate paths")
    plan_paths = {
        str(_mapping(item).get("file", ""))
        for item in plan.get("experiments", [])
    }
    if set(manifest_paths) != plan_paths:
        raise ValueError("baseline manifest source set does not match plan")


def _execution_records(payload: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    value = payload.get("experiments", payload.get("records", []))
    if not isinstance(value, list):
        raise ValueError("records.experiments must be a list")
    records: dict[str, Mapping[str, Any]] = {}
    for index, item in enumerate(value):
        record = _mapping(item)
        exp_id = str(record.get("id") or record.get("experiment_id") or "")
        if not exp_id or exp_id in records:
            raise ValueError(f"record[{index}] has empty/duplicate experiment id")
        records[exp_id] = record
    return records


def validate_experiment_records(
    operator_dir: Path,
    plan: Mapping[str, Any],
    manifest: Mapping[str, Any],
    records_payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Gate experiment outcomes without applying or rolling back changes."""
    validate_plan_schema(plan)
    _validate_manifest_for_plan(plan, manifest)
    records = _execution_records(records_payload)
    planned_ids = {
        str(_mapping(item).get("id", "")) for item in plan["experiments"]
    }
    unknown_ids = sorted(set(records) - planned_ids)
    if unknown_ids:
        raise ValueError(
            "records contain experiment ids not present in plan: "
            + ", ".join(unknown_ids)
        )
    validated: list[dict[str, Any]] = []
    for value in plan["experiments"]:
        experiment = _mapping(value)
        exp_id = str(experiment["id"])
        record = records.get(exp_id, {})
        outcome = str(record.get("outcome", "not_run"))
        schema_errors: list[str] = []
        if outcome not in OUTCOMES:
            schema_errors.append(f"invalid outcome: {outcome!r}")
            outcome = "not_run"
        build = _mapping(record.get("build"))
        run = _mapping(record.get("run"))
        rollback_record = _mapping(record.get("rollback"))
        changed_files = record.get("changed_files")
        for field in (
            "baseline_reproduced",
            "single_variable_verified",
            "invariants_verified",
        ):
            if not isinstance(record.get(field), bool):
                schema_errors.append(f"{field} must be bool")
        if not isinstance(record.get("build"), Mapping):
            schema_errors.append("build must be an object")
        elif build.get("status") not in {"passed", "failed", "not_run"}:
            schema_errors.append(
                "build.status must be passed/failed/not_run"
            )
        if not isinstance(record.get("run"), Mapping):
            schema_errors.append("run must be an object")
        elif run.get("status") not in {"completed", "failed", "not_run"}:
            schema_errors.append(
                "run.status must be completed/failed/not_run"
            )
        elif not isinstance(run.get("original_error_observed"), bool):
            schema_errors.append("run.original_error_observed must be bool")
        elif not isinstance(run.get("observed_fingerprint"), str):
            schema_errors.append("run.observed_fingerprint must be a string")
        if not isinstance(record.get("rollback"), Mapping):
            schema_errors.append("rollback must be an object")
        elif not isinstance(rollback_record.get("verified"), bool):
            schema_errors.append("rollback.verified must be bool")
        else:
            if not isinstance(
                rollback_record.get("baseline_reproduced"), bool
            ):
                schema_errors.append(
                    "rollback.baseline_reproduced must be bool"
                )
            if not isinstance(
                rollback_record.get("observed_fingerprint"), str
            ):
                schema_errors.append(
                    "rollback.observed_fingerprint must be a string"
                )
        if not isinstance(changed_files, list) or any(
            not isinstance(item, str) or not item for item in changed_files
        ):
            schema_errors.append(
                "changed_files must be a list of non-empty strings"
            )
            changed_files = []
        elif len(changed_files) != len(set(changed_files)):
            schema_errors.append("changed_files must not contain duplicates")
        target_files = [
            str(item) for item in _mapping(experiment.get("rollback"))
            .get("target_files", [])
        ]
        rollback = verify_rollback(
            operator_dir, manifest, target_files=target_files
        )
        original_fingerprint = str(plan.get("fingerprint", ""))
        fingerprint_available = (
            bool(original_fingerprint)
            and original_fingerprint != "<missing>"
        )
        if outcome == "same_error":
            outcome_fingerprint_consistent = (
                run.get("original_error_observed") is True
                and run.get("observed_fingerprint")
                == original_fingerprint
            )
        elif outcome == "error_disappeared":
            outcome_fingerprint_consistent = (
                run.get("original_error_observed") is False
                and not run.get("observed_fingerprint")
            )
        else:
            outcome_fingerprint_consistent = True
        gates = {
            "original_fingerprint_available": fingerprint_available,
            "baseline_reproduced": (
                plan.get("baseline_gate", {}).get("status") == "reproduced"
                and record.get("baseline_reproduced") is True
            ),
            "single_variable_verified": (
                record.get("single_variable_verified") is True
            ),
            "invariants_verified": record.get("invariants_verified") is True,
            "build_passed": build.get("status") == "passed",
            "build_evidence_recorded": _nonempty(build.get("evidence")),
            "run_completed": run.get("status") == "completed",
            "run_evidence_recorded": _nonempty(run.get("evidence")),
            "outcome_fingerprint_consistent": (
                outcome_fingerprint_consistent
            ),
            "changed_files_within_scope": (
                set(changed_files) <= set(target_files)
            ),
            "rollback_verified": (
                rollback["verified"]
                and rollback_record.get("verified") is True
            ),
            "rollback_original_fingerprint_reproduced": (
                rollback_record.get("baseline_reproduced") is True
                and rollback_record.get("observed_fingerprint")
                == original_fingerprint
                and _nonempty(rollback_record.get("evidence"))
            ),
            "inference_outcome": outcome in INFERENCE_OUTCOMES,
            "record_schema_valid": not schema_errors,
        }
        valid = all(gates.values())
        invalid_reasons = [
            name for name, passed in gates.items() if not passed
        ] + schema_errors
        validated.append({
            "id": exp_id,
            "outcome": outcome,
            "valid_for_inference": valid,
            "root_cause_confirmation_allowed": (
                valid and outcome == "error_disappeared"
            ),
            "gates": gates,
            "invalid_reasons": invalid_reasons,
            "rollback": rollback,
        })
    return {
        "schema_version": VALIDATION_SCHEMA_VERSION,
        "fingerprint": plan.get("fingerprint", "<missing>"),
        "experiments": validated,
        "summary": {
            "validated_count": len(validated),
            "valid_for_inference_count": sum(
                item["valid_for_inference"] for item in validated
            ),
            "root_cause_confirmation_count": sum(
                item["root_cause_confirmation_allowed"] for item in validated
            ),
            "rollback_all_verified": bool(validated) and all(
                item["rollback"]["verified"] for item in validated
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
        description="Plan/guard A5 VECTOR_ERROR controlled experiments."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan")
    plan.add_argument("--static-scan", type=Path, required=True)
    plan.add_argument("--evidence", type=Path)
    plan.add_argument("--history", type=Path)
    plan.add_argument("--build-command", default="")
    plan.add_argument("--test-command", default="")
    plan.add_argument("--baseline-reproduced", action="store_true", default=None)
    plan.add_argument("--max-experiments", type=int, default=MAX_EXPERIMENTS)
    plan.add_argument("--output", type=Path)
    plan.add_argument("--pretty", action="store_true")

    manifest = subparsers.add_parser("manifest")
    manifest.add_argument("--operator-dir", type=Path, required=True)
    manifest.add_argument("--plan", type=Path, required=True)
    manifest.add_argument("--output", type=Path)
    manifest.add_argument("--pretty", action="store_true")

    validate = subparsers.add_parser("validate")
    validate.add_argument("--operator-dir", type=Path, required=True)
    validate.add_argument("--plan", type=Path, required=True)
    validate.add_argument("--manifest", type=Path, required=True)
    validate.add_argument("--records", type=Path, required=True)
    validate.add_argument("--output", type=Path)
    validate.add_argument("--pretty", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "plan":
            result = plan_experiments(
                _load_json(args.static_scan),
                evidence=_load_json(args.evidence),
                history=_load_json(args.history),
                build_command=args.build_command,
                test_command=args.test_command,
                max_experiments=args.max_experiments,
                baseline_reproduced=args.baseline_reproduced,
            )
        elif args.command == "manifest":
            result = create_baseline_manifest(
                args.operator_dir, _load_json(args.plan)
            )
        else:
            result = validate_experiment_records(
                args.operator_dir,
                _load_json(args.plan),
                _load_json(args.manifest),
                _load_json(args.records),
            )
        _write_or_print(result, args.output, args.pretty)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"plan_a5_vector_experiments: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
