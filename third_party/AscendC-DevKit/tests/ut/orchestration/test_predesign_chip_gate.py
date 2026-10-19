"""Step 8 (D3): the pre-design cross-generation confirmation gate.

Origin: a user on A2 hardware declared an A5 target. The inconsistency was
caught only at codegen's build gate — after requirement / general-design /
detailed-design / test-design work was already spent, all wasted. The gate
moves the decision to *before* design work, inside the design group's first
stage (``GeneralDesignStage.actions``), riding the existing
AskUserQuestion → DecisionPendingError → ``respond`` resume path (path A;
Step 0 wired the ``decision_response.json`` replay that makes path A
resumable in non-interactive abort mode).

Gate fires iff ALL hold:
  - design_target_chip is set (a design intent was declared),
  - runtime_target_chip is a KNOWN generation (real on-box hardware present),
  - the runtime hardware does NOT support the design's programming model (P65:
    the ONLY such case is an A5/Regbase design on A2/A3/Membase-only hardware),
  - the run hasn't already confirmed cross-generation this pass, AND
  - the workflow builds/runs locally (requires_npu) — a pure-design workflow
    (generate_ascendc_se) can target any generation regardless of the box.

A low-generation Membase design on a higher-gen A5 box is FORWARD-compatible
(A5 runs Membase) and must NOT fire the gate (P65).

These tests guard the trigger conditions (4 cases) + the two transition
outcomes (retarget vs confirm). They are pure-logic UT (§3.8): no probe, no
LLM — the gate is a pure comparison over the two already-resolved chip fields.
"""

from ascendc_devkit.domain.chip import UNKNOWN
from ascendc_devkit.orchestration.kernel.action import AskUserQuestion, SpawnAgent
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.stages.design_substages import GeneralDesignStage


def _actions(design, runtime, workflow="generate_ascendc", confirmed=False):
    state = State(
        design_target_chip=design,
        runtime_target_chip=runtime,
        workflow_name=workflow,
        cross_gen_confirmed=confirmed,
    )
    return GeneralDesignStage().actions(state)


def _gate_fires(actions) -> bool:
    return bool(actions) and isinstance(actions[0], AskUserQuestion)


# —— trigger conditions ————————————————————————————————————————————————

def test_gate_does_not_fire_when_design_equals_runtime():
    # design==runtime → nothing to confirm; proceed straight to the design agent.
    assert not _gate_fires(_actions("A2", "A2"))


def test_gate_does_not_fire_when_runtime_unknown():
    # runtime UNKNOWN → no on-box hardware to mismatch against (probe could not
    # identify the chip). Let design proceed; codegen's gate handles the rest.
    assert not _gate_fires(_actions("A5", UNKNOWN))


def test_gate_does_not_fire_for_pure_design_workflow():
    # generate_ascendc_se has requires_npu=False (no local build/run), so a
    # cross-generation design is harmless — the product simply isn't validated
    # on this box. The gate must not block design-only runs.
    assert not _gate_fires(_actions("A5", "A2", workflow="generate_ascendc_se"))


def test_gate_does_not_fire_for_forward_compat_low_gen_on_a5():
    # P65: A2/A3 are Membase; A5 hardware runs Membase (backward compatible).
    # So a low-gen Membase design on an A5 box is forward-compatible — the
    # product CAN build/run locally — and must NOT fire the gate. (This was the
    # user's core ask: validate A2/A3 Membase codegen on the A5 box.)
    assert not _gate_fires(_actions("A2", "A5", workflow="generate_ascendc"))
    assert not _gate_fires(_actions("A3", "A5", workflow="generate_ascendc"))


def test_gate_does_not_fire_for_membase_across_a2_a3():
    # P65: A2↔A3 are the same Membase generation — portable, no incompatibility.
    assert not _gate_fires(_actions("A2", "A3", workflow="generate_ascendc"))
    assert not _gate_fires(_actions("A3", "A2", workflow="generate_ascendc"))


def test_gate_fires_on_cross_generation_with_local_build():
    # The originating failure: A2 box, A5 declared, full pipeline (builds/runs
    # locally). Design must not start until the user acknowledges.
    actions = _actions("A5", "A2", workflow="generate_ascendc")
    assert _gate_fires(actions)
    # Both recovery options are offered (retarget-to-local | proceed cross-gen).
    labels = [opt.label for opt in actions[0].options]
    assert "改打本机" in labels and "跨代设计" in labels


def test_gate_does_not_refire_after_confirmation():
    # Once the run confirmed cross-generation, re-entry (loopback / next
    # iteration) must NOT re-ask — the confirmation marker sticks for the run.
    assert not _gate_fires(_actions("A5", "A2", confirmed=True))


def test_non_gate_path_spawns_design_agent():
    # Sanity: when the gate does not fire, actions() returns the normal design
    # spawn (proves we fall through to super().actions, not return [] or raise).
    actions = _actions("A2", "A2")
    assert any(isinstance(a, SpawnAgent) for a in actions)


# —— transition outcomes ————————————————————————————————————————————————

def test_transition_retarget_sets_design_equal_runtime():
    # "改打本机": rewrite design_target_chip to the on-box chip so the (now
    # single-generation) build/run succeeds. Confirms so the gate won't refire.
    state = State(design_target_chip="A5", runtime_target_chip="A2",
                  workflow_name="generate_ascendc")
    new_state = GeneralDesignStage().transition(
        state, {"decision": "改打本机"})
    assert new_state.design_target_chip == "A2" == new_state.runtime_target_chip
    assert new_state.cross_gen_confirmed is True


def test_transition_confirm_sets_marker_keeps_design():
    # "跨代设计": keep the declared design target (cross-generation), just mark
    # the run as user-acknowledged so the gate doesn't refire.
    state = State(design_target_chip="A5", runtime_target_chip="A2",
                  workflow_name="generate_ascendc")
    new_state = GeneralDesignStage().transition(
        state, {"decision": "跨代设计"})
    assert new_state.design_target_chip == "A5"  # unchanged
    assert new_state.cross_gen_confirmed is True
