"""Phase 0: State.routing_scopes / node_status — scoped routing counters."""

from ascendc_devkit.orchestration.kernel.state import State


class TestRoutingScopes:
    def test_defaults_empty(self):
        s = State.empty()
        assert s.routing_scopes == {}
        assert s.node_status == {}

    def test_with_updates_sets_scope(self):
        s = State.empty().with_updates(
            routing_scopes={"pipeline": {"corrective": 1, "escalation": 0,
                                         "history": [], "last_sig": ""}})
        assert s.routing_scopes["pipeline"]["corrective"] == 1

    def test_snapshot_round_trip_preserves_scopes(self):
        s = State.empty().with_updates(
            routing_scopes={"pipeline/design": {"corrective": 2, "escalation": 1,
                                                "history": [{"from": "a", "to": "a"}],
                                                "last_sig": "x"}},
            node_status={"pipeline/entry": "completed"})
        snap = s.to_snapshot()
        s2 = State.from_snapshot(snap)
        assert s2.routing_scopes["pipeline/design"]["corrective"] == 2
        assert s2.node_status["pipeline/entry"] == "completed"

    def test_from_snapshot_missing_fields_default(self):
        # Old snapshots have no routing_scopes / node_status
        s = State.from_snapshot({"run_id": "r1"})
        assert s.routing_scopes == {}
        assert s.node_status == {}

    def test_from_snapshot_strips_retired_flat_mirror_keys(self):
        """M4: pre-M4 snapshots carried flat corrective_count/escalation_count/
        last_error_signature/loopback_history mirror keys (write-only 镜像, deleted
        in M4 — routing_scopes is the sole authority). from_snapshot must drop them
        so an old snapshot resume doesn't TypeError on cls(**data). This strip is
        load-bearing (resume compat); guard it so a future change that drops one
        pop breaks loudly instead of silently corrupting resume."""
        # Pre-M4 snapshot with the retired flat keys → must load without error
        # (the pop loop strips them before cls(**data)), dropping to defaults.
        s = State.from_snapshot({
            "run_id": "pre-m4-resume",
            "mode": "new",
            "corrective_count": 3,
            "escalation_count": 1,
            "last_error_signature": "sig_x",
            "loopback_history": [{"from": "verify", "to": "codegen",
                                  "type": "corrective", "sig": "sig_x"}],
            # retired flat caps survive (still live as routing caps)
            "max_corrective": 5,
            "max_escalations": 2,
        })
        # Retired mirror fields no longer exist on State (deleted in M4).
        assert not hasattr(s, "corrective_count")
        assert not hasattr(s, "escalation_count")
        assert not hasattr(s, "last_error_signature")
        assert not hasattr(s, "loopback_history")
        # Live caps preserved.
        assert s.max_corrective == 5
        assert s.max_escalations == 2
        # The scoped authority was never written by a pre-M4 run → empty default.
        assert s.routing_scopes == {}

    def test_from_snapshot_retired_flat_keys_roundtrip_absent(self):
        """to_snapshot no longer emits the retired flat mirror keys."""
        s = State.empty().with_scope_counters(
            "pipeline", corrective=2, escalation=0, history=[], last_sig="")
        snap = s.to_snapshot()
        assert "corrective_count" not in snap
        assert "escalation_count" not in snap
        assert "loopback_history" not in snap
        assert "last_error_signature" not in snap
        # routing_scopes is the authority and round-trips.
        s2 = State.from_snapshot(snap)
        assert s2.routing_scopes["pipeline"]["corrective"] == 2


class TestScopeWrite:
    def test_scope_is_sole_authority(self):
        """with_scope_counters writes routing_scopes only (M4: flat mirror removed
        — scoped routing is the sole loop-back counter/history authority)."""
        s = State.empty().with_scope_counters(
            "pipeline", corrective=3, escalation=1,
            history=[{"from": "verify", "to": "codegen"}], last_sig="sig1")
        assert s.routing_scopes["pipeline"]["corrective"] == 3
        assert s.routing_scopes["pipeline"]["escalation"] == 1
        assert s.routing_scopes["pipeline"]["history"] == [{"from": "verify", "to": "codegen"}]
        assert s.routing_scopes["pipeline"]["last_sig"] == "sig1"

    def test_sub_scope_counts_in_own_scope(self):
        s = State.empty().with_scope_counters(
            "pipeline/design", corrective=2, escalation=0,
            history=[], last_sig="")
        assert s.routing_scopes["pipeline/design"]["corrective"] == 2
        # Independent scope: root untouched.
        assert "pipeline" not in s.routing_scopes


class TestTransientFieldsNotPersisted:
    """is_terminal / _stage_failed / _bubble_condition are TRANSIENT per-pass
    control-flow signals (state.py L203-204 documents them as "transient", the
    same role _loopback_feedback already plays). They must NOT survive a
    snapshot round-trip.

    Why this matters: a halt-terminated run sets is_terminal=True mid-pass. If
    that flag is written to state_snapshot.json, the next ``RESUME=...`` re-reads
    it and ``_execute_sequential`` (graph_executor.py:201) breaks BEFORE
    re-running the failed stage — the resume is a 0.0s no-op that re-reports the
    halt. node_status (the durable resume authority) already records "which stage
    to redo"; the transient flags only describe "the previous pass stopped early"
    and must reset on every fresh load.
    """

    def test_to_snapshot_drops_transient_fields(self):
        s = State.empty().with_updates(
            is_terminal=True,
            _stage_failed=("failed", "some-stage"),
            _bubble_condition="escalate:design")
        snap = s.to_snapshot()
        assert "is_terminal" not in snap
        assert "_stage_failed" not in snap
        assert "_bubble_condition" not in snap

    def test_from_snapshot_resets_persisted_transient_fields(self):
        # A snapshot written by an older (pre-fix) build carries the transient
        # flags. from_snapshot must drop them so they fall back to defaults.
        snap = {
            "run_id": "r1",
            "is_terminal": True,
            "_stage_failed": ["failed", "some-stage"],
            "_bubble_condition": "escalate:design",
        }
        s = State.from_snapshot(snap)
        assert s.is_terminal is False
        assert s._stage_failed is None
        assert s._bubble_condition == ""

    def test_round_trip_clears_transient_fields(self):
        # End-to-end: halt → snapshot → resume load. The resumed state is clean.
        s = State.empty().with_updates(is_terminal=True)
        resumed = State.from_snapshot(s.to_snapshot())
        assert resumed.is_terminal is False
