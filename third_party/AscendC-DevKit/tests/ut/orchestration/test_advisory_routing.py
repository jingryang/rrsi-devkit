"""P0 (D1): forward advisory route_type.

anchor-consistency issues whose owner is a downstream stage (synthesize) flow
FORWARD as non-blocking advisories, consumed in place by the owner — no
corrective/escalation quota, no invalidate, no backward jump. The deeper root
(D8): the issue's ``target`` is judged by owner capability (written in the
skill), so the Python router only maps ``target -> condition`` mechanically —
verdict/blast-radius never enter routing. Gray-area (D9): an owner-ambiguous
advisory defaults forward but is surfaced (logged), never silently swallowed.

See docs/plan/self-evolution/36-loopback-routing-and-incremental-impl.md §1.
"""

from unittest import mock

from ascendc_devkit.orchestration.graph_executor import GraphExecutor
from ascendc_devkit.orchestration.node import AtomicStage, SequentialGroup
from ascendc_devkit.orchestration.kernel.runner import Runner
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.base import Stage
from ascendc_devkit.domain.contract import StageIOContract


class _AdvisoryGate(Stage):
    """A gate that resolves ``advisory_synthesize`` and reports one forward issue."""
    name = "anchor-consistency"
    default_max_iterations = 1

    def __init__(self, issue):
        self._issue = issue

    def input_contract(self): return StageIOContract()
    def output_contract(self): return StageIOContract()
    def actions(self, state, iteration=1): return []
    def transition(self, state, result): return state
    def resolve_condition(self, state): return "advisory_synthesize"
    def blocking_issues(self, state): return [self._issue]


class _Record(Stage):
    default_max_iterations = 1

    def __init__(self, name, log):
        self._n = name
        self._log = log

    @property
    def name(self): return self._n

    def input_contract(self): return StageIOContract()
    def output_contract(self): return StageIOContract()
    def actions(self, state, iteration=1): return []
    def transition(self, state, result):
        self._log.append(self._n)
        return state


class TestAdvisoryRouting:
    """graph_executor: an ``advisory`` edge carries the issue forward into
    ``pending_advisories`` and advances — it does NOT consume corrective quota,
    does NOT invalidate the rerun range, does NOT jump backward."""

    def _pipeline(self, issue, log):
        root = SequentialGroup(
            name="pipeline",
            children=[AtomicStage(_AdvisoryGate(issue)),
                      AtomicStage(_Record("synthesize", log))],
            transition_table={"anchor-consistency": {
                "advisory_synthesize": ("synthesize", "advisory")}},
            max_corrective=5)
        return root

    def test_advisory_forwards_without_loopback(self):
        log = []
        issue = {"code": "AC3", "target": "synthesize", "severity": "warning",
                 "detail": "R5 字段命名不一致", "acceptance": "两模板 R5 命名统一"}
        root = self._pipeline(issue, log)
        s = State.empty().with_updates(
            non_interactive=True, user_max_iterations=1, max_corrective=5)
        out = GraphExecutor(runner=Runner()).execute(root, s)

        # forward: synthesize ran (not skipped)
        assert "synthesize" in log
        # no corrective quota consumed (a backward jump would)
        assert out.routing_scopes.get("pipeline", {}).get("corrective", 0) == 0
        # the advisory is carried forward into state for the owner to consume
        assert any(a.get("detail") == "R5 字段命名不一致"
                   for a in out.pending_advisories), out.pending_advisories

    def test_advisory_does_not_invalidate_rerun_range(self):
        # A pre-completed synthesize must stay completed: advisory is pure info
        # carry, not a corrective rollback (which would clear node_status).
        log = []
        issue = {"code": "AC3", "target": "synthesize", "severity": "warning",
                 "detail": "d", "acceptance": "a"}
        root = self._pipeline(issue, log)
        s = State.empty().with_updates(
            non_interactive=True, user_max_iterations=1, max_corrective=5,
            node_status={"pipeline/synthesize": "completed"})
        out = GraphExecutor(runner=Runner()).execute(root, s)
        # synthesize was already completed → resume-skip keeps it (advisory did
        # not invalidate it the way a corrective rollback would).
        assert out.node_status.get("pipeline/synthesize") == "completed"
        # the advisory still flowed forward (gate ran this pass)
        assert out.pending_advisories

    def test_advisory_owner_ambiguous_is_surfaced(self):
        # D9: an owner-ambiguous advisory defaults forward but is LOGGED — never
        # silently swallowed. The operator sees the裁定 request.
        log = []
        issue = {"code": "AC3", "target": "synthesize", "severity": "warning",
                 "detail": "d", "acceptance": "a", "owner_ambiguous": True}
        root = self._pipeline(issue, log)
        s = State.empty().with_updates(
            non_interactive=True, user_max_iterations=1)
        with mock.patch("ascendc_devkit.infra.logger.Logger.action") as m:
            GraphExecutor(runner=Runner()).execute(root, s)
        msgs = [str(c.args[1]) for c in m.call_args_list
                if c.args and c.args[0] == "advisory"]
        assert msgs, "advisory forward must be logged"
        assert any("owner_ambiguous" in x or "待人工裁定" in x for x in msgs), msgs


class TestSynthesizeConsumesAdvisory:
    """The owner (synthesize) renders forwarded advisories as an in-place
    resolution section, and clears them once its product is parsed (one-way)."""

    def test_prompt_includes_advisory_section(self):
        from ascendc_devkit.orchestration.stages.design_substages import \
            SynthesizeStage
        st = SynthesizeStage()
        s = State.empty().with_updates(pending_advisories=[{
            "target": "synthesize", "code": "AC3", "detail": "R5 命名冲突",
            "remediation": "统一为 R5", "acceptance": "两模板 R5 一致"}])
        secs = st._extra_prompt_sections(s)
        assert secs and any("R5 命名冲突" in x for x in secs), secs

    def test_empty_advisories_yield_no_section(self):
        from ascendc_devkit.orchestration.stages.design_substages import \
            SynthesizeStage
        st = SynthesizeStage()
        assert st._extra_prompt_sections(State.empty()) == []

    def test_owner_ambiguous_flagged_in_section(self):
        from ascendc_devkit.orchestration.stages.design_substages import \
            SynthesizeStage
        st = SynthesizeStage()
        s = State.empty().with_updates(pending_advisories=[{
            "target": "synthesize", "code": "AC3", "detail": "d",
            "acceptance": "a", "owner_ambiguous": True}])
        secs = st._extra_prompt_sections(s)
        assert secs and any("待人工裁定" in x for x in secs), secs

    def test_transition_clears_consumed_advisories(self, tmp_path):
        # One-way forward: once synthesize produces its artifact, the advisories it
        # consumed are cleared so a downstream re-entry does not re-render them.
        from ascendc_devkit.orchestration.stages.design_substages import \
            SynthesizeStage
        st = SynthesizeStage()
        s = State.empty().with_updates(pending_advisories=[{
            "target": "synthesize", "code": "AC3", "detail": "d",
            "acceptance": "a"}])

        class _Contract:
            def parse(self, artifacts):
                return ({"design_spec": {}, "tiling_strategy": {},
                         "data_flow": {}}, [])

        # P62: synthesize reads its products from disk under working_dir
        # (design_spec.json + tiling_strategy.json required, data_flow optional)
        # plus the docgen md (merged owner).
        wd = tmp_path / "wd"
        wd.mkdir(parents=True, exist_ok=True)
        (wd / "design_spec.json").write_text("{}", encoding="utf-8")
        (wd / "tiling_strategy.json").write_text("{}", encoding="utf-8")
        (wd / "x_详细设计说明书.md").write_text("# x\n", encoding="utf-8")
        with mock.patch.object(st, "artifact_contract",
                               return_value=_Contract()):
            out = st.transition(s, {"_working_dir": str(wd)})
        assert out.pending_advisories == []
