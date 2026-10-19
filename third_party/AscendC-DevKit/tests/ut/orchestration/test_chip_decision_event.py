"""Step 9 (D8): the ``chip_decision`` event records chip-target provenance.

Origin: a cross-generation mismatch (A2 box, A5 declared) was invisible until
codegen's build gate rejected it — no record of HOW each chip target was
resolved survived. The ``chip_decision`` event (emitted once per new run at
dispatch) makes the resolution auditable: design/runtime values, their sources
(cli / probe / timeout_fallback), and whether they mismatch.

These UTs guard the event shape + the mismatch flag. The source attribution
itself is covered by ``test_dispatcher_chip_resolution.py`` (the
``_resolve_chip_fields`` sources); this file guards the event helper that turns
a resolution into an events.jsonl record.
"""
from ascendc_devkit.orchestration.kernel import event as evt


def test_chip_decision_records_fields_and_type():
    e = evt.chip_decision(
        design_chip="A5", design_source="cli",
        runtime_chip="A2", runtime_source="probe",
        mismatch=True)
    assert e["type"] == "chip_decision"
    assert e["design_chip"] == "A5"
    assert e["design_source"] == "cli"
    assert e["runtime_chip"] == "A2"
    assert e["runtime_source"] == "probe"
    assert e["mismatch"] is True
    # every event carries a timestamp (events.jsonl ordering / audit)
    assert "ts" in e


def test_chip_decision_marks_mismatch_only_when_both_known_and_differ():
    # The originating bug: explicit cross-generation declaration → mismatch.
    assert evt.chip_decision("A5", "cli", "A2", "probe", mismatch=True)["mismatch"] is True
    # Same generation → no mismatch (the common, healthy case).
    assert evt.chip_decision("A2", "cli", "A2", "probe", mismatch=False)["mismatch"] is False
    # Design unresolved at dispatch (no CLI; req/profile fill it downstream) →
    # mismatch stays False: nothing to compare yet (honest "unknown", not a
    # false-positive cross-generation flag).
    assert evt.chip_decision("", "", "A2", "probe", mismatch=False)["mismatch"] is False
