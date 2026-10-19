"""P3 tests for evidence-gated A5 VECTOR_ERROR repair planning."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest


_REPO = Path(__file__).resolve().parents[3]
_SCRIPT = (
    _REPO
    / ".claude/skills/ascendc-precision-vector-error-debug/scripts"
    / "plan_a5_vector_repairs.py"
)


def _load_planner():
    spec = importlib.util.spec_from_file_location(
        "a5_vector_repair_planner", _SCRIPT
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


planner = _load_planner()
FP = "a5-vector-v1|case_id=case_7|pc_offset=32"


def _evidence() -> dict:
    return {
        "active_error_fingerprint": FP,
        "vector_error_evidence": {
            "case_id": "case_7",
            "source_phase": "finalize",
            "buffer_mode": "double",
            "verification_cases": {
                "aligned_tail": ["aligned", "tail"],
                "zero_one": ["zero", "one"],
                "last_core": ["last_core"],
            },
            "mode_commands": {
                "single": "runner --single",
                "double": "runner --double",
                "one_core": "runner --cores 1",
                "original_core": "runner --cores original",
            },
        },
    }


def _experiment(subtype: str = "gm_ub_transport", exp_id: str = "a5ve-1") -> dict:
    return {
        "id": exp_id,
        "candidate": {"api": "DataCopy", "status": "suspected"},
        "rule": "A5-TEST-001",
        "subtype": subtype,
        "file": "kernel.cpp",
        "line": 17,
        "exact_scope": {"symbol": "DataCopy"},
    }


def _p2_inputs(subtype: str = "gm_ub_transport") -> tuple[dict, dict, dict, dict]:
    experiment = _experiment(subtype)
    plan = {
        "schema_version": "1.0",
        "fingerprint": FP,
        "experiments": [experiment],
    }
    gates = {gate: True for gate in planner._P2_REQUIRED_GATES}
    validation = {
        "schema_version": "1.0",
        "fingerprint": FP,
        "experiments": [{
            "id": experiment["id"],
            "outcome": "error_disappeared",
            "valid_for_inference": True,
            "root_cause_confirmation_allowed": True,
            "gates": gates,
            "rollback": {"verified": True},
        }],
    }
    records = {
        "experiments": [{
            "id": experiment["id"],
            "outcome": "error_disappeared",
            "run": {
                "status": "completed",
                "evidence": "modified_case.json",
                "original_error_observed": False,
                "observed_fingerprint": "",
            },
            "rollback": {
                "verified": True,
                "baseline_reproduced": True,
                "observed_fingerprint": FP,
                "evidence": "restored_case.json",
            },
        }]
    }
    static = {
        "candidate_ranking": [{
            "rule_id": experiment["rule"],
            "subtype": subtype,
            "file": "kernel.cpp",
            "line": 17,
            "api": experiment["candidate"]["api"],
            "status": "suspected",
        }]
    }
    return static, plan, validation, records


def _api(
    *,
    status: str = "verified",
    target: str = "910D/current CANN",
) -> dict:
    return {
        "entries": [{
            "experiment_id": "a5ve-1",
            "status": status,
            "target": target,
            "soc": "Ascend950",
            "cann_version": "9.1.0",
            "doc": "LoadAlign API",
            "source": "910D_knowledge_extra/load_align.md",
            "version": "2026-07",
            "claim": "Target API contract checked.",
        }]
    }


def _located_roots() -> dict:
    return {
        "located_roots": [{
            "experiment_id": "a5ve-1",
            "file": "kernel.cpp",
            "line": 17,
            "api": "DataCopy",
            "fingerprint": FP,
            "confidence": "confirmed",
            "evidence": "baseline -> disappeared -> restored",
            "confirmation": {
                "baseline_reproduced": True,
                "error_disappeared": True,
                "restored_original_fingerprint": True,
                "invariants_verified": True,
            },
        }]
    }


def _plan(
    subtype: str = "gm_ub_transport",
    *,
    api: dict | None = None,
    evidence: dict | None = None,
) -> dict:
    static, exp_plan, validation, records = _p2_inputs(subtype)
    return planner.plan_repairs(
        evidence or _evidence(),
        static,
        exp_plan,
        validation,
        records,
        located_roots=_located_roots(),
        api_verification=api if api is not None else _api(),
    )


def _valid_repair_record(repair: dict) -> dict:
    original_case = next(
        item for item in repair["verification_matrix"]
        if item["name"] == "original_case_repeat"
    )["case_ids"][0]
    return {
        "repair_id": repair["repair_id"],
        "build": {"status": "passed", "evidence": "repair_build.log"},
        "target_case_runs": [
            {
                "case_id": original_case,
                "status": "completed",
                "original_error_observed": False,
                "observed_fingerprint": "",
                "different_device_exception": False,
                "evidence": f"run_{index}.json",
            }
            for index in range(2)
        ],
        "scope_matches_plan": True,
        "invariants_verified": True,
        "changed_scope": [{
            "file": repair["target"]["file"],
            "line_start": repair["target"]["line"],
            "line_end": repair["target"]["line"],
            "justification": "P2 confirmed anchor and its minimal statement.",
        }],
        "api_verification": {
            key: repair["api_verification"][key]
            for key in (
                "status", "target", "soc", "cann_version",
                "doc", "source", "version", "claim",
            )
        },
        "rollback_restore": {
            "available": True,
            "method": "reverse repair-local patch",
            "evidence": "repair.patch",
            "target_files": [repair["target"]["file"]],
        },
        "verification_matrix": [
            {
                "name": item["name"],
                "status": "passed",
                "evidence": f"{item['name']}.json",
                "original_error_observed": False,
                "different_device_exception": False,
            }
            for item in repair["verification_matrix"]
            if item["status"] == "ready"
        ],
    }


def test_refuses_without_valid_p2_error_disappeared():
    static, exp_plan, validation, records = _p2_inputs()
    validation["experiments"][0]["valid_for_inference"] = False
    validation["experiments"][0]["root_cause_confirmation_allowed"] = False
    validation["experiments"][0]["outcome"] = "same_error"
    records["experiments"][0]["outcome"] = "same_error"

    result = planner.plan_repairs(
        _evidence(), static, exp_plan, validation, records,
        located_roots=_located_roots(),
        api_verification=_api(),
    )

    assert result["status"] == "refused"
    assert result["repairs"] == []
    assert result["summary"]["static_root_promotions"] == 0
    reasons = " ".join(result["refused_candidates"][0]["reasons"])
    assert "error_disappeared" in reasons
    assert "valid_for_inference" in reasons


def test_refuses_missing_rollback_fingerprint_reproduction_gate():
    static, exp_plan, validation, records = _p2_inputs()
    validation["experiments"][0]["gates"][
        "rollback_original_fingerprint_reproduced"
    ] = False
    records["experiments"][0]["rollback"]["observed_fingerprint"] = "other"

    result = planner.plan_repairs(
        _evidence(), static, exp_plan, validation, records,
        located_roots=_located_roots(),
        api_verification=_api(),
    )

    assert result["repairs"] == []
    reasons = " ".join(result["refused_candidates"][0]["reasons"])
    assert "rollback_original_fingerprint_reproduced" in reasons
    assert "original fingerprint" in reasons


def test_refuses_fingerprint_mismatch_even_with_forged_valid_flags():
    static, exp_plan, validation, records = _p2_inputs()
    validation["fingerprint"] = "foreign"

    result = planner.plan_repairs(
        _evidence(), static, exp_plan, validation, records,
        located_roots=_located_roots(),
        api_verification=_api(),
    )

    assert result["status"] == "refused"
    assert any(
        "does not match P2 validation" in reason
        for reason in result["refused_candidates"][0]["reasons"]
    )


@pytest.mark.parametrize(
    "roots",
    [
        {},
        {"located_roots": [{
            **_located_roots()["located_roots"][0],
            "confidence": "suspected",
        }]},
        {"located_roots": [{
            **_located_roots()["located_roots"][0],
            "confirmation": {
                **_located_roots()["located_roots"][0]["confirmation"],
                "restored_original_fingerprint": False,
            },
        }]},
    ],
)
def test_refuses_without_complete_line_level_confirmation(roots: dict):
    static, exp_plan, validation, records = _p2_inputs()

    result = planner.plan_repairs(
        _evidence(),
        static,
        exp_plan,
        validation,
        records,
        located_roots=roots,
        api_verification=_api(),
    )

    assert result["status"] == "refused"
    assert result["repairs"] == []
    assert any(
        "line-level confirmation" in reason
        for reason in result["refused_candidates"][0]["reasons"]
    )


@pytest.mark.parametrize(
    ("subtype", "kind", "required_tokens"),
    [
        ("gm_ub_transport", "repair_transport_bounds", ("TQue", "tail")),
        ("address_generation", "repair_address_generation", ("AddrReg", "Last repeat")),
        ("ub_reg_load_store", "repair_vf_load_store_contract", ("RegTensor", "PostUpdate")),
        ("vf_call_abi", "repair_vf_call_abi", ("GetPhyAddr", "Load→Compute→Store")),
        ("mask_tail", "repair_mask_tail_lifecycle", ("MaskReg", "UpdateMask")),
        ("layout_cast_dist", "repair_cast_distribution_layout", ("Cast", "LoadDist")),
        ("incore_sync", "repair_incore_dependency", ("LocalMemBar", "double-buffer")),
        ("queue_lifecycle", "repair_queue_lifecycle", ("Alloc→EnQue→DeQue→Free", "double-buffer")),
        ("crosscore_tscm", "repair_crosscore_tscm_visibility", ("TSCM", "Set/Wait")),
        ("tiling_boundary", "repair_tiling_boundary", ("Zero-work", "Last repeat")),
    ],
)
def test_a5_subtype_templates(
    subtype: str,
    kind: str,
    required_tokens: tuple[str, str],
):
    result = _plan(subtype)
    repair = result["repairs"][0]
    rendered = json.dumps(repair, ensure_ascii=False)

    assert repair["status"] == "ready"
    assert repair["executable"] is True
    assert repair["minimal_change_intent"]["kind"] == kind
    assert all(token in rendered for token in required_tokens)
    assert repair["root_evidence"]["static_context"]["status"] == "suspected"
    assert repair["root_evidence"]["status"] == (
        "line_level_confirmed_for_repair_planning"
    )
    assert "32B" not in rendered
    assert "VL=256" not in rendered


@pytest.mark.parametrize(
    ("api", "expected_status"),
    [
        (_api(status="unverified"), "deferred"),
        (_api(status="verified", target="generic docs"), "deferred"),
        ({"entries": []}, "deferred"),
        (_api(), "ready"),
    ],
)
def test_api_verification_controls_executability(api: dict, expected_status: str):
    result = _plan("layout_cast_dist", api=api)
    repair = result["repairs"][0]

    assert repair["status"] == expected_status
    assert repair["executable"] is (expected_status == "ready")
    if expected_status == "deferred":
        assert repair["deferred_reasons"]


def test_repair_plan_and_id_are_stable():
    first = _plan("mask_tail")
    second = _plan("mask_tail")

    assert first == second
    assert first["repairs"][0]["repair_id"].startswith("a5vr-")
    assert first["summary"]["source_modified"] is False
    assert first["summary"]["device_accessed"] is False


def test_verification_matrix_never_synthesizes_missing_cases_or_controls():
    evidence = _evidence()
    evidence["vector_error_evidence"].pop("verification_cases")
    evidence["vector_error_evidence"].pop("mode_commands")
    result = _plan("crosscore_tscm", evidence=evidence)
    matrix = result["repairs"][0]["verification_matrix"]

    assert next(item for item in matrix
                if item["name"] == "original_case_repeat")["status"] == "ready"
    deferred = [item for item in matrix if item["name"] != "original_case_repeat"]
    assert deferred
    assert all(item["status"] == "deferred" for item in deferred)
    assert all(not item["case_ids"] or item["case_ids"] == ["case_7"]
               for item in deferred)
    assert all(item["prerequisite"] for item in deferred)


def test_valid_repair_record_allows_vector_error_fixed():
    plan = _plan("ub_reg_load_store")
    repair = plan["repairs"][0]
    result = planner.validate_repair_records(
        plan, {"repairs": [_valid_repair_record(repair)]}
    )

    validated = result["repairs"][0]
    assert validated["repair_verified"] is True
    assert validated["vector_error_fixed_allowed"] is True
    assert result["summary"]["vector_error_fixed_allowed"] is True


@pytest.mark.parametrize(
    ("mutation", "failed_gate"),
    [
        ("one_repeat", "original_case_repeat_count"),
        ("fingerprint_reappeared", "original_fingerprint_absent"),
        ("new_exception", "no_different_device_exception"),
        ("build_failed", "build_passed"),
        ("scope_mismatch", "scope_matches_plan"),
        ("api_mismatch", "api_verification_consistent"),
        ("rollback_missing", "rollback_restore_complete"),
        ("matrix_missing", "ready_verification_matrix_passed"),
        ("matrix_new_exception", "ready_verification_matrix_passed"),
        ("duplicate_run_evidence", "original_case_runs_independent"),
    ],
)
def test_validator_rejects_incomplete_or_inconsistent_repairs(
    mutation: str,
    failed_gate: str,
):
    plan = _plan("crosscore_tscm")
    repair = plan["repairs"][0]
    record = _valid_repair_record(repair)
    if mutation == "one_repeat":
        record["target_case_runs"] = record["target_case_runs"][:1]
    elif mutation == "fingerprint_reappeared":
        record["target_case_runs"][0]["original_error_observed"] = True
        record["target_case_runs"][0]["observed_fingerprint"] = FP
    elif mutation == "new_exception":
        record["target_case_runs"][0]["different_device_exception"] = True
    elif mutation == "build_failed":
        record["build"]["status"] = "failed"
    elif mutation == "scope_mismatch":
        record["changed_scope"][0]["file"] = "other.cpp"
    elif mutation == "api_mismatch":
        record["api_verification"]["version"] = "other"
    elif mutation == "rollback_missing":
        record["rollback_restore"]["evidence"] = ""
    elif mutation == "matrix_new_exception":
        record["verification_matrix"][0][
            "different_device_exception"
        ] = True
    elif mutation == "duplicate_run_evidence":
        record["target_case_runs"][1]["evidence"] = (
            record["target_case_runs"][0]["evidence"]
        )
    else:
        record["verification_matrix"] = []

    result = planner.validate_repair_records(
        plan, {"repairs": [record]}
    )
    validated = result["repairs"][0]
    assert validated["repair_verified"] is False
    assert validated["vector_error_fixed_allowed"] is False
    assert failed_gate in validated["invalid_reasons"]


def test_deferred_repair_can_never_validate_as_fixed():
    plan = _plan("layout_cast_dist", api=_api(status="unverified"))
    repair = plan["repairs"][0]
    record = _valid_repair_record(repair)

    result = planner.validate_repair_records(
        plan, {"repairs": [record]}
    )

    assert result["repairs"][0]["repair_verified"] is False
    assert "repair_was_executable" in result["repairs"][0]["invalid_reasons"]


def test_tampered_repair_plan_cannot_forge_root_or_api_proof():
    plan = _plan()
    repair = plan["repairs"][0]
    repair["root_evidence"]["located_root"]["confidence"] = "suspected"
    repair["api_verification"]["target"] = "generic docs"

    with pytest.raises(ValueError, match="line-level|API"):
        planner.validate_repair_records(
            plan, {"repairs": [_valid_repair_record(repair)]}
        )


def test_ordinary_precision_failure_becomes_next_hint_not_vector_failure():
    plan = _plan()
    repair = plan["repairs"][0]
    record = _valid_repair_record(repair)
    record["ordinary_precision_failure"] = {
        "observed": True,
        "next_hint": "Continue PREC debugging in pipeline_sync.",
    }

    result = planner.validate_repair_records(
        plan, {"repairs": [record]}
    )

    assert result["repairs"][0]["repair_verified"] is True
    assert result["repairs"][0]["next_hint"] == (
        "Continue PREC debugging in pipeline_sync."
    )


def test_cli_plan_validate_is_json_and_read_only(tmp_path: Path):
    static, exp_plan, validation, experiment_records = _p2_inputs()
    operator_source = tmp_path / "kernel.cpp"
    operator_source.write_text("void kernel() {}\n", encoding="utf-8")
    before = operator_source.read_bytes()
    inputs = {
        "evidence": _evidence(),
        "static": static,
        "exp_plan": exp_plan,
        "validation": validation,
        "experiment_records": experiment_records,
        "api": _api(),
        "roots": _located_roots(),
    }
    paths = {}
    for name, payload in inputs.items():
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        paths[name] = path
    repair_plan_path = tmp_path / "repair_plan.json"

    completed = subprocess.run(
        [
            sys.executable, str(_SCRIPT), "plan",
            "--evidence", str(paths["evidence"]),
            "--static-scan", str(paths["static"]),
            "--experiment-plan", str(paths["exp_plan"]),
            "--experiment-validation", str(paths["validation"]),
            "--experiment-records", str(paths["experiment_records"]),
            "--located-roots", str(paths["roots"]),
            "--api-verification", str(paths["api"]),
            "--output", str(repair_plan_path),
        ],
        check=True, text=True, capture_output=True,
    )
    repair_plan = json.loads(completed.stdout)
    assert repair_plan == json.loads(
        repair_plan_path.read_text(encoding="utf-8")
    )
    record_path = tmp_path / "repair_record.json"
    record_path.write_text(json.dumps({
        "repairs": [_valid_repair_record(repair_plan["repairs"][0])]
    }), encoding="utf-8")
    validated = subprocess.run(
        [
            sys.executable, str(_SCRIPT), "validate",
            "--repair-plan", str(repair_plan_path),
            "--records", str(record_path),
        ],
        check=True, text=True, capture_output=True,
    )
    assert json.loads(validated.stdout)["summary"][
        "vector_error_fixed_allowed"
    ] is True
    assert operator_source.read_bytes() == before


def test_unsafe_target_path_is_rejected():
    static, exp_plan, validation, records = _p2_inputs()
    exp_plan["experiments"][0]["file"] = "../outside.cpp"

    with pytest.raises(ValueError, match="unsafe repair target"):
        planner.plan_repairs(
            _evidence(), static, exp_plan, validation, records,
            located_roots=_located_roots(),
            api_verification=_api(),
        )
