"""P2 tests for deterministic A5 VECTOR_ERROR experiment planning/guards."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


_REPO = Path(__file__).resolve().parents[3]
_SCRIPT = (
    _REPO
    / ".claude/skills/ascendc-precision-vector-error-debug/scripts"
    / "plan_a5_vector_experiments.py"
)


def _load_planner():
    spec = importlib.util.spec_from_file_location(
        "a5_vector_experiment_planner", _SCRIPT
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


planner = _load_planner()


def _candidate(
    rank: int,
    subtype: str,
    *,
    rule: str | None = None,
    line: int | None = None,
    file: str = "kernel.cpp",
) -> dict:
    return {
        "rank": rank,
        "rule_id": rule or f"A5-TEST-{rank:03d}",
        "subtype": subtype,
        "file": file,
        "line": line or rank,
        "api": "TargetAPI",
        "reason": "fixture",
        "final_score": 100 - rank,
        "status": "candidate",
    }


def _scan(*subtypes: str) -> dict:
    return {
        "schema_version": "1.0",
        "candidate_ranking": [
            _candidate(index, subtype)
            for index, subtype in enumerate(subtypes, start=1)
        ],
    }


def _evidence(**extra) -> dict:
    evidence = {
        "active_error_fingerprint": "a5-vector-v1|case=case_7|pc=32",
        "vector_error_evidence": {
            "case_id": "case_7",
            "source_phase": "finalize",
            "buffer_mode": "double",
            "boundary_cases": ["vl-1", "vl", "vl+1"],
            "mode_commands": {"single": "runner --single"},
        },
        "reproducibility": {
            "status": "stable",
            "run_count": 2,
            "failure_count": 2,
        },
    }
    evidence.update(extra)
    return evidence


def _plan(scan: dict, **kwargs) -> dict:
    return planner.plan_experiments(
        scan,
        evidence=kwargs.pop("evidence", _evidence()),
        build_command=kwargs.pop("build_command", "bash build.sh"),
        test_command=kwargs.pop("test_command", "python run.py"),
        **kwargs,
    )


def _write_source(root: Path, relative: str = "kernel.cpp") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("void kernel() {}\n", encoding="utf-8")
    return path


def _valid_record(
    experiment: dict,
    outcome: str = "same_error",
    *,
    fingerprint: str = "a5-vector-v1|case=case_7|pc=32",
) -> dict:
    return {
        "id": experiment["id"],
        "outcome": outcome,
        "baseline_reproduced": True,
        "single_variable_verified": True,
        "invariants_verified": True,
        "changed_files": [experiment["file"]],
        "build": {"status": "passed", "evidence": "build.log"},
        "run": {
            "status": "completed",
            "evidence": "case.json",
            "original_error_observed": outcome == "same_error",
            "observed_fingerprint": (
                fingerprint if outcome == "same_error" else ""
            ),
        },
        "rollback": {
            "verified": True,
            "baseline_reproduced": True,
            "observed_fingerprint": fingerprint,
            "evidence": "restored-case.json",
        },
    }


def test_plan_is_stable_limited_to_four_and_has_auditable_schema():
    scan = _scan(
        "gm_ub_transport",
        "ub_reg_load_store",
        "mask_tail",
        "address_generation",
        "tiling_boundary",
        "queue_lifecycle",
    )
    first = _plan(scan)
    second = _plan(scan)

    assert first == second
    assert first["schema_version"] == "1.0"
    assert len(first["experiments"]) == 4
    assert first["summary"]["max_experiments"] == 4
    assert first["summary"]["source_modified"] is False
    assert len({item["id"] for item in first["experiments"]}) == 4
    assert all(item["status"] == "planned" for item in first["experiments"])
    assert all(item["oracle"]["identity"] == first["fingerprint"]
               for item in first["experiments"])
    assert any("per-round limit" in item["reason"]
               for item in first["deferred_candidates"])


def test_same_rule_and_line_with_distinct_symbols_get_distinct_ids():
    first = _candidate(1, "ub_reg_load_store", rule="A5-LS-001", line=9)
    second = dict(first, rank=2, api="StoreAlign")
    first["api"] = "LoadAlign"

    result = _plan({"candidate_ranking": [first, second]})

    assert len(result["experiments"]) == 2
    assert len({item["id"] for item in result["experiments"]}) == 2


def test_history_skips_examined_and_located_candidates():
    scan = _scan("gm_ub_transport", "mask_tail", "tiling_boundary")
    history = {
        "experiments": [{
            "file": "kernel.cpp",
            "line": 1,
            "rule": "A5-TEST-001",
            "subtype": "gm_ub_transport",
            "outcome": "same_error",
        }],
        "located_roots": [{
            "file": "kernel.cpp",
            "line": 2,
            "api": "UpdateMask",
        }],
    }
    result = _plan(scan, history=history)

    assert [item["subtype"] for item in result["experiments"]] == [
        "tiling_boundary"
    ]
    assert sum("history_skip" in item["reason"]
               for item in result["deferred_candidates"]) == 2


def test_subtype_recipes_are_conservative_and_dangerous_layout_is_deferred():
    scan = _scan(
        "gm_ub_transport",
        "ub_reg_load_store",
        "mask_tail",
        "layout_cast_dist",
        "crosscore_tscm",
        "tiling_boundary",
    )
    result = _plan(scan)
    kinds = {item["experiment_kind"] for item in result["experiments"]}

    assert {
        "transport_address_bounds_probe",
        "vf_load_compute_store_isolation",
        "mask_tail_boundary_matrix",
        "sync_buffer_core_differential",
    } <= kinds
    layout = next(
        item for item in result["deferred_candidates"]
        if item["candidate"]["subtype"] == "layout_cast_dist"
    )
    assert layout["blocked"] is True
    assert "equivalence proof" in layout["reason"]
    rendered = json.dumps(result, ensure_ascii=False).lower()
    assert "delete setflag" not in " ".join(
        change.lower()
        for experiment in result["experiments"]
        for change in experiment["allowed_changes"]
    )
    assert "comment out datacopy" not in " ".join(
        change.lower()
        for experiment in result["experiments"]
        for change in experiment["allowed_changes"]
    )
    assert "never delete" in rendered or "do not remove" in rendered


def test_layout_recipe_requires_explicit_equivalence_proof():
    evidence = _evidence()
    evidence["vector_error_evidence"]["layout_equivalence_proof"] = (
        "910D API reference X proves lane-for-lane equivalence"
    )
    result = _plan(_scan("layout_cast_dist"), evidence=evidence)

    assert result["experiments"][0]["experiment_kind"] == (
        "layout_equivalent_control"
    )
    assert any(
        item["name"] == "layout_equivalence_proven" and item["satisfied"]
        for item in result["experiments"][0]["preconditions"]
    )


def test_missing_case_commands_and_baseline_block_execution_readiness():
    result = planner.plan_experiments(
        _scan("gm_ub_transport"),
        evidence={"active_error_fingerprint": "fp"},
    )
    experiment = result["experiments"][0]

    assert result["summary"]["executable_count"] == 0
    assert set(result["baseline_gate"]["missing"]) == {
        "baseline_reproduced",
        "build_command",
        "case_id",
        "test_command",
    }
    assert experiment["build_command"] == ""
    assert experiment["test_command"] == ""
    assert experiment["case_id"] == ""
    assert not all(item["satisfied"] for item in experiment["preconditions"])


def test_case_index_does_not_masquerade_as_exact_case_selector():
    result = _plan(
        _scan("gm_ub_transport"),
        test_command="python run.py --case-index 7",
    )

    assert result["experiments"][0]["test_command"].endswith("--case case_7")


def test_manifest_hash_and_rollback_success_and_failure(tmp_path: Path):
    operator = tmp_path / "operator"
    source = _write_source(operator)
    plan = _plan(_scan("gm_ub_transport"))
    before = hashlib.sha256(source.read_bytes()).hexdigest()

    manifest = planner.create_baseline_manifest(operator, plan)
    assert manifest["files"] == [{
        "path": "kernel.cpp",
        "sha256": before,
        "size": source.stat().st_size,
    }]
    assert planner.verify_rollback(operator, manifest)["verified"] is True

    source.write_text("void kernel() { broken(); }\n", encoding="utf-8")
    failed = planner.verify_rollback(operator, manifest)
    assert failed["verified"] is False
    assert failed["files"][0]["restored"] is False


@pytest.mark.parametrize(
    ("outcome", "build_status", "expected_valid"),
    [
        ("same_error", "passed", True),
        ("error_disappeared", "passed", True),
        ("different_error", "passed", False),
        ("compile_fail", "failed", False),
        ("not_reproduced", "passed", False),
        ("not_run", "passed", False),
    ],
)
def test_inference_gate_rejects_invalid_outcomes(
    tmp_path: Path,
    outcome: str,
    build_status: str,
    expected_valid: bool,
):
    operator = tmp_path / "operator"
    _write_source(operator)
    plan = _plan(_scan("gm_ub_transport"))
    manifest = planner.create_baseline_manifest(operator, plan)
    record = _valid_record(plan["experiments"][0], outcome)
    record["build"]["status"] = build_status

    result = planner.validate_experiment_records(
        operator, plan, manifest, {"experiments": [record]}
    )
    validated = result["experiments"][0]
    assert validated["valid_for_inference"] is expected_valid
    assert validated["root_cause_confirmation_allowed"] is (
        expected_valid and outcome == "error_disappeared"
    )


def test_rollback_failure_overrides_execution_declaration(tmp_path: Path):
    operator = tmp_path / "operator"
    source = _write_source(operator)
    plan = _plan(_scan("gm_ub_transport"))
    manifest = planner.create_baseline_manifest(operator, plan)
    source.write_text("void changed() {}\n", encoding="utf-8")

    result = planner.validate_experiment_records(
        operator,
        plan,
        manifest,
        {"experiments": [_valid_record(plan["experiments"][0],
                                       "error_disappeared")]},
    )
    validated = result["experiments"][0]
    assert validated["rollback"]["verified"] is False
    assert validated["valid_for_inference"] is False
    assert validated["root_cause_confirmation_allowed"] is False
    assert "rollback_verified" in validated["invalid_reasons"]


def test_restore_and_reproduce_original_fingerprint_is_required(
    tmp_path: Path,
):
    operator = tmp_path / "operator"
    _write_source(operator)
    plan = _plan(_scan("gm_ub_transport"))
    manifest = planner.create_baseline_manifest(operator, plan)
    record = _valid_record(
        plan["experiments"][0], "error_disappeared"
    )
    record["rollback"]["observed_fingerprint"] = "different-fingerprint"

    result = planner.validate_experiment_records(
        operator, plan, manifest, {"experiments": [record]}
    )

    validated = result["experiments"][0]
    assert validated["valid_for_inference"] is False
    assert validated["root_cause_confirmation_allowed"] is False
    assert (
        "rollback_original_fingerprint_reproduced"
        in validated["invalid_reasons"]
    )


def test_modified_run_must_classify_against_original_fingerprint(
    tmp_path: Path,
):
    operator = tmp_path / "operator"
    _write_source(operator)
    plan = _plan(_scan("gm_ub_transport"))
    manifest = planner.create_baseline_manifest(operator, plan)
    record = _valid_record(plan["experiments"][0], "same_error")
    record["run"]["observed_fingerprint"] = "different-fingerprint"

    result = planner.validate_experiment_records(
        operator, plan, manifest, {"experiments": [record]}
    )

    validated = result["experiments"][0]
    assert validated["valid_for_inference"] is False
    assert "outcome_fingerprint_consistent" in validated["invalid_reasons"]


def test_manifest_must_belong_to_plan(tmp_path: Path):
    operator = tmp_path / "operator"
    _write_source(operator)
    plan = _plan(_scan("gm_ub_transport"))
    manifest = planner.create_baseline_manifest(operator, plan)
    manifest["fingerprint"] = "foreign-plan"

    with pytest.raises(ValueError, match="fingerprint"):
        planner.validate_experiment_records(
            operator,
            plan,
            manifest,
            {"experiments": [_valid_record(plan["experiments"][0])]},
        )


def test_malformed_execution_record_is_reported_not_used(tmp_path: Path):
    operator = tmp_path / "operator"
    _write_source(operator)
    plan = _plan(_scan("gm_ub_transport"))
    manifest = planner.create_baseline_manifest(operator, plan)
    malformed = {
        "id": plan["experiments"][0]["id"],
        "outcome": "same_error",
        "baseline_reproduced": "yes",
        "single_variable_verified": True,
        "invariants_verified": True,
        "build": {"status": "maybe"},
        "run": [],
        "rollback": {"verified": True},
    }

    result = planner.validate_experiment_records(
        operator, plan, manifest, {"experiments": [malformed]}
    )
    validated = result["experiments"][0]
    assert validated["valid_for_inference"] is False
    assert validated["gates"]["record_schema_valid"] is False
    assert any("must be" in reason for reason in validated["invalid_reasons"])


def test_cli_plan_manifest_validate_json_and_never_modifies_source(
    tmp_path: Path,
):
    operator = tmp_path / "operator"
    source = _write_source(operator)
    before = source.read_bytes()
    scan_path = tmp_path / "scan.json"
    evidence_path = tmp_path / "evidence.json"
    plan_path = tmp_path / "plan.json"
    manifest_path = tmp_path / "manifest.json"
    records_path = tmp_path / "records.json"
    validation_path = tmp_path / "validation.json"
    scan_path.write_text(json.dumps(_scan("gm_ub_transport")), encoding="utf-8")
    evidence_path.write_text(json.dumps(_evidence()), encoding="utf-8")

    plan_run = subprocess.run(
        [
            sys.executable, str(_SCRIPT), "plan",
            "--static-scan", str(scan_path),
            "--evidence", str(evidence_path),
            "--build-command", "bash build.sh",
            "--test-command", "python run.py",
            "--output", str(plan_path),
        ],
        check=True, text=True, capture_output=True,
    )
    plan = json.loads(plan_run.stdout)
    assert plan == json.loads(plan_path.read_text(encoding="utf-8"))

    manifest_run = subprocess.run(
        [
            sys.executable, str(_SCRIPT), "manifest",
            "--operator-dir", str(operator),
            "--plan", str(plan_path),
            "--output", str(manifest_path),
        ],
        check=True, text=True, capture_output=True,
    )
    assert json.loads(manifest_run.stdout) == json.loads(
        manifest_path.read_text(encoding="utf-8")
    )

    records_path.write_text(json.dumps({
        "experiments": [_valid_record(plan["experiments"][0])]
    }), encoding="utf-8")
    validate_run = subprocess.run(
        [
            sys.executable, str(_SCRIPT), "validate",
            "--operator-dir", str(operator),
            "--plan", str(plan_path),
            "--manifest", str(manifest_path),
            "--records", str(records_path),
            "--output", str(validation_path),
        ],
        check=True, text=True, capture_output=True,
    )
    validated = json.loads(validate_run.stdout)
    assert validated == json.loads(validation_path.read_text(encoding="utf-8"))
    assert validated["experiments"][0]["valid_for_inference"] is True
    assert source.read_bytes() == before


def test_manifest_rejects_absolute_parent_and_symlink_escape(tmp_path: Path):
    operator = tmp_path / "operator"
    operator.mkdir()
    outside = _write_source(tmp_path / "outside")

    for unsafe in (str(outside), "../outside/kernel.cpp"):
        plan = _plan({
            "candidate_ranking": [
                _candidate(1, "gm_ub_transport", file=unsafe)
            ]
        })
        with pytest.raises(ValueError, match="unsafe|escapes"):
            planner.create_baseline_manifest(operator, plan)

    link = operator / "linked.cpp"
    link.symlink_to(outside)
    plan = _plan({
        "candidate_ranking": [
            _candidate(1, "gm_ub_transport", file="linked.cpp")
        ]
    })
    with pytest.raises(ValueError, match="escapes"):
        planner.create_baseline_manifest(operator, plan)
