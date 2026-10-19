"""P2 (step-2b) — merge_forkjoin same-field dict shallow-merge (R1)."""

import pytest
from ascendc_devkit.orchestration.node import AtomicStage
from ascendc_devkit.orchestration.node_forkjoin import merge_forkjoin, StateConflictError
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.base import Stage
from ascendc_devkit.domain.contract import StageIOContract


class _Provider(Stage):
    """Stage declaring a single provided field, used to drive merge_forkjoin."""
    default_max_iterations = 1
    def __init__(self, name, provide):
        self._name = name; self._provide = provide
    @property
    def name(self): return self._name
    def input_contract(self): return StageIOContract()
    def output_contract(self): return StageIOContract(provides=[self._provide])
    def actions(self, state, iteration=1): return []


def _branch(name, provide):
    return AtomicStage(_Provider(name, provide))


class TestDictMerge:
    def test_disjoint_keys_merge(self):
        base = State.empty()
        c1, c2 = _branch("T1", "tiling_results"), _branch("T2", "tiling_results")
        s1 = base.with_updates(tiling_results={"T1": {"split": {}}})
        s2 = base.with_updates(tiling_results={"T2": {"split": {}}})
        merged = merge_forkjoin(base, [c1, c2], [s1, s2])
        assert merged.tiling_results == {"T1": {"split": {}}, "T2": {"split": {}}}

    def test_overlapping_keys_raise(self):
        base = State.empty()
        c1, c2 = _branch("T1", "tiling_results"), _branch("Tdup", "tiling_results")
        s1 = base.with_updates(tiling_results={"T1": {"split": {}}})
        s2 = base.with_updates(tiling_results={"T1": {"buffer_kernel": {}}})
        with pytest.raises(StateConflictError):
            merge_forkjoin(base, [c1, c2], [s1, s2])

    def test_partial_rerun_preserves_untouched(self):
        # C2 (base shallow-merge): on an anchor→tiling rerun of only one template,
        # base already carries both T1 and T2; the single rerun branch contributes
        # only {T2: new} (C1 isolation). merge must shallow-merge into base so T1's
        # prior result survives and T2 is updated. The clash guard must check only
        # sibling-vs-sibling keys, NOT treat base's pre-existing T1 as a conflict.
        base = State.empty().with_updates(tiling_results={
            "T1": {"split": {"axis": "N"}}, "T2": {"split": {"axis": "old"}}})
        c2 = _branch("T2", "tiling_results")
        s2 = base.with_updates(tiling_results={"T2": {"split": {"axis": "new"}}})
        merged = merge_forkjoin(base, [c2], [s2])
        assert merged.tiling_results == {
            "T1": {"split": {"axis": "N"}},
            "T2": {"split": {"axis": "new"}}}

    def test_multi_branch_rerun_against_populated_base(self):
        # C2: both templates rerun. Each branch contributes only its own key (C1);
        # base carries prior T1+T2. Disjoint sibling keys → both merge into base,
        # no false clash from base's pre-existing keys.
        base = State.empty().with_updates(tiling_results={
            "T1": {"split": {"axis": "old1"}}, "T2": {"split": {"axis": "old2"}}})
        c1, c2 = _branch("T1", "tiling_results"), _branch("T2", "tiling_results")
        s1 = base.with_updates(tiling_results={"T1": {"split": {"axis": "n1"}}})
        s2 = base.with_updates(tiling_results={"T2": {"split": {"axis": "n2"}}})
        merged = merge_forkjoin(base, [c1, c2], [s1, s2])
        assert merged.tiling_results == {
            "T1": {"split": {"axis": "n1"}}, "T2": {"split": {"axis": "n2"}}}


class TestRegressionProtection:
    def test_same_nondict_field_still_conflicts(self):
        base = State.empty()
        c1, c2 = _branch("a", "design_spec"), _branch("b", "design_spec")
        s1 = base.with_updates(design_spec={"op_name": "x"})
        # second branch writes a non-dict on a field already written → still conflict.
        s2 = base.with_updates(design_spec="not-a-dict")
        with pytest.raises(StateConflictError):
            merge_forkjoin(base, [c1, c2], [s1, s2])

    def test_distinct_fields_independent(self):
        base = State.empty()
        c1, c2 = _branch("a", "general_design"), _branch("b", "template_division")
        s1 = base.with_updates(general_design={"op_name": "x"})
        s2 = base.with_updates(template_division={"templates": []})
        merged = merge_forkjoin(base, [c1, c2], [s1, s2])
        assert merged.general_design == {"op_name": "x"}
        assert merged.template_division == {"templates": []}


class TestFailedBranchNoneGuard:
    """step-60 B: a branch that never wrote its provided field (value stayed
    None because it failed before producing it) must not be mistaken for a
    deliberate non-dict write colliding with a sibling's dict."""

    def test_none_field_skipped_no_conflict(self):
        # Regression for the real StateConflictError crash: a failed branch's
        # tiling_results is None (never written); a succeeded sibling writes a
        # dict. merge must NOT raise, and must fold only the succeeded dict.
        base = State.empty()
        c_fail = _branch("T1", "tiling_results")   # failed: never wrote
        c_ok = _branch("T2", "tiling_results")     # ok: wrote dict
        s_fail = base                               # tiling_results stays None
        s_ok = base.with_updates(tiling_results={"T2": {"split": {}}})
        merged = merge_forkjoin(base, [c_fail, c_ok], [s_fail, s_ok])
        assert merged.tiling_results == {"T2": {"split": {}}}

    def test_none_field_order_independent(self):
        # Same, with the succeeded branch first — the None sibling coming later
        # must also not collide.
        base = State.empty()
        c_ok = _branch("T2", "tiling_results")
        c_fail = _branch("T1", "tiling_results")
        s_ok = base.with_updates(tiling_results={"T2": {"split": {}}})
        s_fail = base
        merged = merge_forkjoin(base, [c_ok, c_fail], [s_ok, s_fail])
        assert merged.tiling_results == {"T2": {"split": {}}}

    def test_empty_children_returns_base_unchanged(self):
        # step-60: when every branch failed, the executor passes an empty ok list
        # to merge → base returned unchanged, no crash.
        base = State.empty().with_updates(tiling_results={"prior": {}})
        merged = merge_forkjoin(base, [], [])
        assert merged.tiling_results == {"prior": {}}
