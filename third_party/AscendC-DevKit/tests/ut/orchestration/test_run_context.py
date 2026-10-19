"""UT for RunContext (P27): single-source hardware params + unified env context.

Covers L4 Step 1 (UT-1.1..1.4). The loader is the single source for hardware
constants (cures P24 drift); RunContext is populated once and the hw_params slice
is auto-materialized to every design substage independent of _upstream_inputs
(cures 传递丢失). Chip identity is the canonical generation A2/A3/A5 (P29).
"""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest

from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.run_context import (
    RunContext, HardwareTarget, build_hardware_target, build_run_context,
    load_hw_params,
)
from ascendc_devkit.orchestration.stages.design_substages import (
    GeneralDesignStage,
)


# UT-1.1: hw_params single-source load — ub matches chip spec (not 240KB drift).
def test_load_hw_params_a2_ub_matches_chip_spec():
    params = load_hw_params("A2")
    assert params["ub_size_bytes"] == 196608  # 192KB, Gen2 — NOT the 245760/240KB drift
    assert build_hardware_target("A2").variant == "910B3"  # representative variant (Gen2 die)


# UT-1.1a: A3 (Ascend910C / 910_93xx) resolves to the 93xx spec.
def test_load_hw_params_a3_resolves_to_93xx_spec():
    params = load_hw_params("A3")
    # A3 shares A2's UB (192KB) + 32B alignment + 128B vec width (shared section).
    assert params["ub_size_bytes"] == 196608      # 192KB
    assert params["alignment_bytes"] == 32
    assert params["vec_calc_size_bytes"] == 128
    assert build_hardware_target("A3").variant == "910_9362"  # typical SKU


# UT-1.1b: A5 / Atlas 350 (950) resolves to the 910_95xx spec. Regression for the
# cann-bench e2e WARN: an unmapped chip left hw_params unverifiable for every
# A5 design run.
def test_load_hw_params_a5_resolves_to_atlas350_spec():
    params = load_hw_params("A5")
    # UB 248KB + 32B alignment + 128B vec width come from the 910_95xx shared
    # section (variant-independent); core counts come from the typical 910_9582
    # variant (32-core mainstream, NOT the 8-core entry 950z — P2).
    assert params["ub_size_bytes"] == 253952      # 248KB
    assert params["alignment_bytes"] == 32
    assert params["vec_calc_size_bytes"] == 128
    assert params["ai_core_cnt"] == 32            # 910_9582 typical SKU (32-core)
    assert params["cube_core_cnt"] == 32
    assert params["vector_core_cnt"] == 64        # 2 x cube_core_cnt


def test_build_hardware_target_a5_typical_variant():
    target = build_hardware_target("A5")
    assert target.chip == "A5"
    assert target.variant == "910_9582"           # bare A5 → typical SKU (32-core, P2)
    assert target.hw_params["ub_size_bytes"] == 253952


def test_load_hw_params_unknown_chip_raises_honestly():
    # §3.7: unknown chip must raise, not silently fall back to a hardcoded value.
    with pytest.raises(KeyError):
        load_hw_params("A9")


# UT-1.2: build_run_context assembles all three sections; software_env mirrors env.
def test_build_run_context_three_sections(monkeypatch):
    monkeypatch.setenv("ASCEND_TOOLKIT_HOME", "/fake/cann-9.1.0/ascend-toolkit/latest")
    rc = build_run_context("A2", npu_id=3)
    assert rc.hardware_target.hw_params["ub_size_bytes"] == 196608
    assert rc.hardware_env is not None and rc.hardware_env.npu_id == 3
    assert rc.software_env is not None
    assert rc.software_env.cann_toolkit_path == "/fake/cann-9.1.0/ascend-toolkit/latest"
    assert rc.software_env.cann_version == "9.1.0"
    assert rc.software_env.python_version  # always available


# UT-1.3: hw_params.json auto-materialized WITHOUT declaring it in _upstream_inputs.
# This is the mechanical proof that 传递丢失 is cured — a stage that does not list
# hw_params still receives hardware ground truth.
def test_hw_params_auto_materialized_without_upstream_declaration(tmp_path):
    rc = RunContext(hardware_target=build_hardware_target("A2"))
    state = State(run_context=rc)
    stage = GeneralDesignStage()

    # precondition: the stage does NOT declare hw_params in its upstream inputs
    upstream = stage._upstream_inputs(state)
    assert "hw_params" not in upstream, (
        "hw_params must flow via auto-materialization, not per-stage declaration")

    stage._materialize_inputs(state, tmp_path)

    written = tmp_path / "hw_params.json"
    assert written.is_file(), "hw_params.json must be auto-materialized to every substage"
    assert json.loads(written.read_text(encoding="utf-8"))["ub_size_bytes"] == 196608


def test_no_run_context_means_no_hw_params_file(tmp_path):
    # graceful: absent run_context writes nothing; skills treat hw as unverifiable.
    state = State()  # run_context defaults to None
    GeneralDesignStage()._materialize_inputs(state, tmp_path)
    assert not (tmp_path / "hw_params.json").exists()


# UT-1.4: RunContext is frozen and flows through State.with_updates (run-invariant).
def test_run_context_frozen_and_flows_through_state():
    rc = RunContext(hardware_target=build_hardware_target("A2"))
    with pytest.raises(FrozenInstanceError):
        rc.hardware_target = HardwareTarget(chip="x")  # type: ignore[misc]
    state = State(run_context=rc)
    new_state = state.with_updates(current_stage="next")
    assert new_state.run_context is rc  # unchanged, same object — run-invariant


# UT-1.5: run_context survives to_snapshot/from_snapshot round-trip (resume).
# to_snapshot uses asdict (→ nested dict); from_snapshot must rebuild the frozen
# dataclass so attribute access works after resume.
def test_run_context_survives_snapshot_round_trip():
    from ascendc_devkit.orchestration.run_context import run_context_from_dict
    state = State(run_context=RunContext(hardware_target=build_hardware_target("A2")))
    snap = state.to_snapshot()
    assert isinstance(snap["run_context"], dict)  # asdict flattens
    restored = State.from_snapshot(snap)
    assert isinstance(restored.run_context, RunContext)  # rebuilt, not a dict
    assert restored.run_context.hardware_target.hw_params["ub_size_bytes"] == 196608
    # the rebuilder is also directly testable on a plain dict
    assert isinstance(run_context_from_dict(snap["run_context"]), RunContext)
