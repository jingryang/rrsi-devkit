"""P68 — user-triggered rerun of an arbitrary completed stage/substage.

Rerun ≠ resume. Resume continues a run from where it stopped (skips completed
nodes, re-runs the failed/interrupted one, AND resumes that agent's SDK session
to reuse its reasoning memory). Rerun re-executes a user-chosen COMPLETED node
FRESH — the prior agent session is intentionally discarded — so the user can
iteratively optimize a stage and re-validate it against upstream outputs.

The fresh-not-resume guarantee is the load-bearing invariant: a rerun must NOT
pick up the prior session's sidecar. See test_rerun_deletes_sidecars_*.

The causal-invalidity mechanism reuses the P52 clean-prefix primitive that
loopback and resume already share (_invalidate_subtree / _invalidate_sequential_range),
with the user-chosen target as the inclusive break point.
"""

import types

from ascendc_devkit.orchestration.base import Stage
from ascendc_devkit.orchestration.graph_executor import GraphExecutor
from ascendc_devkit.orchestration.kernel.runner import Runner
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.node import AtomicStage, SequentialGroup
from ascendc_devkit.orchestration.node_forkjoin import ForkJoinGroup
from ascendc_devkit.domain.contract import StageIOContract


class _Prov(Stage):
    """Minimal stage that declares provides + records its execution in `log`.

    `reset_extra` simulates an internal counter not in the output contract (like
    codegen's circuit breaker) so we can verify rerun_reset_fields composition.
    """
    default_max_iterations = 1

    def __init__(self, name, log, provides=None, reset_extra=None):
        self._name = name
        self._log = log
        self._provides = list(provides or [])
        self._reset_extra = list(reset_extra or [])

    @property
    def name(self):
        return self._name

    def input_contract(self):
        return StageIOContract()

    def output_contract(self):
        return StageIOContract(provides=list(self._provides))

    def actions(self, state, iteration=1):
        return []

    def transition(self, state, result):
        self._log.append(self._name)
        return state

    def rerun_reset_fields(self):
        return list(self._provides) + list(self._reset_extra)


def _seq_wf(*stages, name="pipe"):
    """Build a SequentialGroup workflow namespace with logging stages."""
    log = []
    root = SequentialGroup(name=name, children=[AtomicStage(s) for s in stages])
    return types.SimpleNamespace(root=root, name=name), log


# ---------------------------------------------------------------------------
# _rerun_invalidate — pure tree walk (target subtree + causal downstream)
# ---------------------------------------------------------------------------

class TestRerunInvalidate:
    def test_sequential_invalidates_target_plus_downstream(self):
        from ascendc_devkit.application.dispatcher import _rerun_invalidate
        wf, _ = _seq_wf(
            _Prov("a", [], provides=["a_out"]),
            _Prov("b", [], provides=["b_out"]),
            _Prov("c", [], provides=["c_out"]),
            _Prov("d", [], provides=["d_out"]),
        )
        ns = {f"pipe/{n}": "completed" for n in "abcd"}
        new_ns, found, stages = _rerun_invalidate(ns, wf, "pipe/b")
        assert found is True
        # b is the inclusive break point: b, c, d invalidated; a stays completed.
        assert new_ns == {"pipe/a": "completed"}
        names = {s.name for s in stages}
        assert names == {"b", "c", "d"}

    def test_sequential_first_node_invalidates_everything(self):
        from ascendc_devkit.application.dispatcher import _rerun_invalidate
        wf, _ = _seq_wf(_Prov("a", []), _Prov("b", []), _Prov("c", []))
        ns = {"pipe/a": "completed", "pipe/b": "completed", "pipe/c": "completed"}
        new_ns, found, _ = _rerun_invalidate(ns, wf, "pipe/a")
        assert found is True
        assert new_ns == {}

    def test_sequential_last_node_invalidates_only_itself(self):
        from ascendc_devkit.application.dispatcher import _rerun_invalidate
        wf, _ = _seq_wf(_Prov("a", []), _Prov("b", []), _Prov("c", []))
        ns = {"pipe/a": "completed", "pipe/b": "completed", "pipe/c": "completed"}
        new_ns, found, _ = _rerun_invalidate(ns, wf, "pipe/c")
        assert found is True
        assert new_ns == {"pipe/a": "completed", "pipe/b": "completed"}

    def test_group_target_invalidates_whole_subtree_plus_downstream(self):
        """Rerunning a SequentialGroup drops its entire subtree + downstream siblings."""
        from ascendc_devkit.application.dispatcher import _rerun_invalidate
        log = []
        inner = SequentialGroup(name="design", children=[
            AtomicStage(_Prov("d1", log)), AtomicStage(_Prov("d2", log))])
        root = SequentialGroup(name="pipe", children=[
            AtomicStage(_Prov("req", log)), inner, AtomicStage(_Prov("codegen", log))])
        wf = types.SimpleNamespace(root=root, name="pipe")
        ns = {"pipe/req": "completed", "pipe/design": "completed",
              "pipe/design/d1": "completed", "pipe/design/d2": "completed",
              "pipe/codegen": "completed"}
        new_ns, found, stages = _rerun_invalidate(ns, wf, "pipe/design")
        assert found is True
        # design + its subtree (d1,d2) + downstream codegen all invalidated; req stays.
        assert new_ns == {"pipe/req": "completed"}
        names = {s.name for s in stages}
        assert names == {"d1", "d2", "codegen"}

    def test_forkjoin_sibling_not_invalidated(self):
        """ForkJoin branches are parallel-independent: rerunning one branch leaves
        its siblings completed (they are NOT causal downstream)."""
        from ascendc_devkit.application.dispatcher import _rerun_invalidate
        log = []
        fj = ForkJoinGroup(name="suite", children=[
            AtomicStage(_Prov("a", log)), AtomicStage(_Prov("b", log))])
        root = SequentialGroup(name="pipe", children=[fj])
        wf = types.SimpleNamespace(root=root, name="pipe")
        ns = {"pipe/suite": "completed", "pipe/suite/a": "completed",
              "pipe/suite/b": "completed"}
        new_ns, found, stages = _rerun_invalidate(ns, wf, "pipe/suite/a")
        assert found is True
        # Only branch a invalidated; b stays completed (parallel-independent).
        assert new_ns == {"pipe/suite/b": "completed"}
        assert {s.name for s in stages} == {"a"}

    def test_forkjoin_downstream_in_parent_sequential_invalidated(self):
        """A node inside a forkjoin is rerun → that branch only; but siblings of
        the forkjoin in the enclosing sequential scope ARE downstream → invalidated."""
        from ascendc_devkit.application.dispatcher import _rerun_invalidate
        log = []
        fj = ForkJoinGroup(name="suite", children=[
            AtomicStage(_Prov("a", log)), AtomicStage(_Prov("b", log))])
        root = SequentialGroup(name="pipe", children=[fj, AtomicStage(_Prov("c", log))])
        wf = types.SimpleNamespace(root=root, name="pipe")
        ns = {"pipe/suite": "completed", "pipe/suite/a": "completed",
              "pipe/suite/b": "completed", "pipe/c": "completed"}
        new_ns, found, stages = _rerun_invalidate(ns, wf, "pipe/suite/a")
        assert found is True
        # a invalidated; b stays (parallel); c (after the forkjoin) invalidated.
        assert new_ns == {"pipe/suite/b": "completed"}
        assert {s.name for s in stages} == {"a", "c"}

    def test_unknown_target_returns_not_found_unchanged(self):
        from ascendc_devkit.application.dispatcher import _rerun_invalidate
        wf, _ = _seq_wf(_Prov("a", []), _Prov("b", []))
        ns = {"pipe/a": "completed", "pipe/b": "completed"}
        new_ns, found, stages = _rerun_invalidate(ns, wf, "pipe/zzz")
        assert found is False
        assert new_ns == ns
        assert stages == []

    def test_executor_reruns_target_and_downstream_after_invalidate(self):
        """End-to-end: after _rerun_invalidate, GraphExecutor re-runs exactly the
        invalidated set and skips the valid prefix (mirrors test_graph_resume pattern)."""
        from ascendc_devkit.application.dispatcher import _rerun_invalidate
        log = []
        wf, _ = _seq_wf(
            _Prov("a", log), _Prov("b", log), _Prov("c", log), _Prov("d", log))
        s = State.empty().with_updates(
            non_interactive=True, user_max_iterations=1,
            node_status={f"pipe/{n}": "completed" for n in "abcd"})
        new_ns, found, _ = _rerun_invalidate(dict(s.node_status), wf, "pipe/c")
        s = s.with_updates(node_status=new_ns)
        GraphExecutor(runner=Runner()).execute(wf.root, s)
        # a, b skipped (valid prefix); c, d re-run.
        assert log == ["c", "d"]


# ---------------------------------------------------------------------------
# _resolve_rerun_target — accept full path / bare name / suffix
# ---------------------------------------------------------------------------

class TestResolveRerunTarget:
    def test_resolves_full_path(self):
        from ascendc_devkit.application.dispatcher import _resolve_rerun_target
        wf, _ = _seq_wf(_Prov("a", []), _Prov("codegen", []), _Prov("c", []))
        assert _resolve_rerun_target(wf, "pipe/codegen") == "pipe/codegen"

    def test_resolves_bare_name(self):
        from ascendc_devkit.application.dispatcher import _resolve_rerun_target
        wf, _ = _seq_wf(_Prov("a", []), _Prov("codegen", []), _Prov("c", []))
        assert _resolve_rerun_target(wf, "codegen") == "pipe/codegen"

    def test_unknown_returns_none(self):
        from ascendc_devkit.application.dispatcher import _resolve_rerun_target
        wf, _ = _seq_wf(_Prov("a", []))
        assert _resolve_rerun_target(wf, "zzz") is None

    def test_ambiguous_bare_name_returns_none(self):
        """Two nodes sharing a bare name → ambiguous → None (user must give full path)."""
        from ascendc_devkit.application.dispatcher import _resolve_rerun_target
        log = []
        inner = SequentialGroup(name="design", children=[
            AtomicStage(_Prov("codegen", log))])
        root = SequentialGroup(name="pipe", children=[
            inner, AtomicStage(_Prov("codegen", log))])
        wf = types.SimpleNamespace(root=root, name="pipe")
        assert _resolve_rerun_target(wf, "codegen") is None
        # ... but the full path disambiguates.
        assert _resolve_rerun_target(wf, "pipe/codegen") == "pipe/codegen"


# ---------------------------------------------------------------------------
# Stage.rerun_reset_fields hook
# ---------------------------------------------------------------------------

class TestStageRerunResetFields:
    def test_default_returns_output_provides(self):
        """Base Stage.rerun_reset_fields defaults to its output_contract().provides."""
        s = _Prov("x", [], provides=["x_out", "x_iter"])
        assert set(s.rerun_reset_fields()) == {"x_out", "x_iter"}

    def test_codegen_includes_circuit_breaker(self):
        """CodegenStage overrides rerun_reset_fields to add codegen_consecutive_failures
        (the circuit breaker is NOT in output_contract.provides but gates re-entry)."""
        from ascendc_devkit.orchestration.stages.codegen import CodegenStage
        cg = CodegenStage()
        fields = set(cg.rerun_reset_fields())
        assert "codegen_consecutive_failures" in fields
        # ... and it still covers its declared outputs.
        assert "codegen_iterations" in fields

    def test_perf_covers_loop_guard_counters(self):
        """PerfStage's provides already cover perf_iterations / performance_result
        (the verify↔perf loop guard at perf.py:344), so the default suffices."""
        from ascendc_devkit.orchestration.stages.perf import PerfStage
        pf = PerfStage()
        fields = set(pf.rerun_reset_fields())
        assert {"perf_iterations", "performance_result", "perf_needs_redesign"} <= fields


# ---------------------------------------------------------------------------
# State.defaults_for — dataclass-default lookup for rerun reset
# ---------------------------------------------------------------------------

class TestStateDefaultsFor:
    def test_returns_defaults_for_named_fields(self):
        resets = State.defaults_for(["codegen_iterations", "generated_sources",
                                      "perf_iterations", "debug_result"])
        assert resets == {"codegen_iterations": 0, "generated_sources": None,
                          "perf_iterations": 0, "debug_result": None}

    def test_skips_unknown_fields(self):
        resets = State.defaults_for(["codegen_iterations", "not_a_real_field"])
        assert resets == {"codegen_iterations": 0}


# ---------------------------------------------------------------------------
# _apply_rerun — composite (node_status + sidecar deletion + counter reset)
# ---------------------------------------------------------------------------

class TestApplyRerun:
    def _ws_with_sidecars(self, tmp_path, stems):
        from ascendc_devkit.infra.workspace import Workspace
        ws = Workspace.create(output_root=str(tmp_path), run_id="rerun-test")
        agents = ws.dir / "agents"
        for stem in stems:
            (agents / f"{stem}.session.json").write_text('{"session_id": "abc"}')
        # a non-sidecar file in agents/ must survive (transcripts etc.)
        (agents / "ascendc-coder-00.jsonl").write_text("[]")
        return ws

    def test_resets_target_provides_to_defaults(self, tmp_path):
        from ascendc_devkit.application.dispatcher import _apply_rerun
        log = []
        wf, _ = _seq_wf(
            _Prov("req", log),
            _Prov("codegen", log, provides=["generated_sources", "codegen_iterations"]),
            _Prov("verify", log))
        ws = self._ws_with_sidecars(tmp_path, ["ascendc-coder"])
        s = State.empty().with_updates(
            non_interactive=True, user_max_iterations=1,
            node_status={f"pipe/{n}": "completed" for n in ("req", "codegen", "verify")},
            generated_sources={"k": "v"}, codegen_iterations=7,
            _workspace=ws)
        s2 = _apply_rerun(s, wf, "pipe/codegen", ws)
        # codegen + verify invalidated (downstream); req stays.
        assert s2.node_status == {"pipe/req": "completed"}
        # codegen's provides reset to defaults.
        assert s2.generated_sources is None
        assert s2.codegen_iterations == 0

    def test_resets_codegen_circuit_breaker(self, tmp_path):
        """Real CodegenStage rerun must zero codegen_consecutive_failures or the
        breaker (codegen.py:156) strands the fresh attempt."""
        from ascendc_devkit.application.dispatcher import _apply_rerun
        from ascendc_devkit.orchestration.stages.codegen import CodegenStage
        log = []
        root = SequentialGroup(name="pipe", children=[
            AtomicStage(CodegenStage())])
        wf = types.SimpleNamespace(root=root, name="pipe")
        ws = self._ws_with_sidecars(tmp_path, ["ascendc-coder"])
        s = State.empty().with_updates(
            non_interactive=True, user_max_iterations=1,
            node_status={"pipe/codegen": "completed"},
            codegen_consecutive_failures=5, codegen_iterations=3,
            _workspace=ws)
        s2 = _apply_rerun(s, wf, "pipe/codegen", ws)
        assert s2.codegen_consecutive_failures == 0
        assert s2.codegen_iterations == 0

    def test_deletes_sidecars_for_fresh_spawn(self, tmp_path):
        """THE load-bearing invariant: rerun must delete prior session sidecars so
        the re-run agent spawns FRESH (codegen.actions finds no sidecar → no
        resume_session_id). rerun ≠ resume."""
        from ascendc_devkit.application.dispatcher import _apply_rerun
        log = []
        wf, _ = _seq_wf(_Prov("req", log), _Prov("codegen", log))
        ws = self._ws_with_sidecars(tmp_path, ["ascendc-coder", "incremental-developer"])
        s = State.empty().with_updates(
            non_interactive=True, user_max_iterations=1,
            node_status={"pipe/req": "completed", "pipe/codegen": "completed"},
            _workspace=ws)
        _apply_rerun(s, wf, "pipe/codegen", ws)
        agents = ws.dir / "agents"
        # All session sidecars gone (fresh-spawn guarantee) ...
        assert list(agents.glob("*.session.json")) == []
        # ... but unrelated agent files (transcripts) survive.
        assert (agents / "ascendc-coder-00.jsonl").exists()

    def test_clears_last_error_pointing_at_rerun_stage(self, tmp_path):
        from ascendc_devkit.application.dispatcher import _apply_rerun
        from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
        log = []
        wf, _ = _seq_wf(_Prov("req", log), _Prov("codegen", log), _Prov("perf", log))
        ws = self._ws_with_sidecars(tmp_path, [])
        le = ErrorFeedback(stage_name="codegen", error_type="logic",
                            message="stale failure from prior run")
        s = State.empty().with_updates(
            non_interactive=True, user_max_iterations=1,
            node_status={f"pipe/{n}": "completed" for n in ("req", "codegen", "perf")},
            last_error=le, _workspace=ws)
        s2 = _apply_rerun(s, wf, "pipe/codegen", ws)
        assert s2.last_error is None  # cleared: codegen is being re-run fresh

    def test_keeps_last_error_pointing_elsewhere(self, tmp_path):
        from ascendc_devkit.application.dispatcher import _apply_rerun
        from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
        log = []
        wf, _ = _seq_wf(_Prov("req", log), _Prov("codegen", log), _Prov("perf", log))
        ws = self._ws_with_sidecars(tmp_path, [])
        le = ErrorFeedback(stage_name="perf", error_type="logic", message="x")
        s = State.empty().with_updates(
            non_interactive=True, user_max_iterations=1,
            node_status={f"pipe/{n}": "completed" for n in ("req", "codegen", "perf")},
            last_error=le, _workspace=ws)
        s2 = _apply_rerun(s, wf, "pipe/codegen", ws)
        # perf is downstream of codegen → also re-run → its last_error cleared too.
        # Use an upstream stage to prove a non-rerun error is kept:
        le2 = ErrorFeedback(stage_name="req", error_type="logic", message="x")
        s3 = s.with_updates(last_error=le2)
        s4 = _apply_rerun(s3, wf, "pipe/codegen", ws)
        assert s4.last_error is le2  # req not re-run → its error preserved

    def test_unknown_target_raises(self, tmp_path):
        from ascendc_devkit.application.dispatcher import _apply_rerun
        wf, _ = _seq_wf(_Prov("a", []))
        ws = self._ws_with_sidecars(tmp_path, [])
        s = State.empty().with_updates(
            non_interactive=True, user_max_iterations=1,
            node_status={"pipe/a": "completed"}, _workspace=ws)
        import pytest
        with pytest.raises(ValueError):
            _apply_rerun(s, wf, "pipe/zzz", ws)


# ---------------------------------------------------------------------------
# Stage.rerun_reset_files — per-stage checkpoint-file cleanup on rerun
# ---------------------------------------------------------------------------

class TestStageRerunResetFiles:
    def test_base_default_is_noop(self):
        """Stage.rerun_reset_files defaults to no-op (pass)."""
        s = _Prov("x", [])
        # Must not raise — base implementation is pass
        s.rerun_reset_files(None)

    def test_codegen_cleans_staging_files(self, tmp_path):
        """CodegenStage.rerun_reset_files deletes s4 scheduler checkpoint files."""
        from ascendc_devkit.orchestration.stages.codegen import CodegenStage
        from ascendc_devkit.infra.workspace import Workspace
        ws = Workspace.create(output_root=str(tmp_path), run_id="test-rf")
        staging = ws.artifacts / "staging"
        staging.mkdir(parents=True)
        # Create the 5 checkpoint files
        for fn in ["progress.md", "coding_index.md", "coding_plan.md",
                   "history.log", "meta.json"]:
            (staging / fn).write_text("old content")
        # Also create vf_verified dir with a fake result
        vf_dir = staging / "vf_verified" / "kernel_test" / "some_test"
        vf_dir.mkdir(parents=True)
        (vf_dir / "result.txt").write_text("pass")
        cg = CodegenStage()
        cg.rerun_reset_files(ws)
        for fn in ["progress.md", "coding_index.md", "coding_plan.md",
                   "history.log", "meta.json"]:
            assert not (staging / fn).exists(), f"{fn} should be deleted"
        assert not (staging / "vf_verified").exists(), "vf_verified should be deleted"

    def test_apply_rerun_calls_rstaged_files(self, tmp_path):
        """_apply_rerun calls rerun_reset_files on every invalidated stage."""
        calls = []
        class _Tracker(_Prov):
            def rerun_reset_files(self, ws): calls.append(self._name)
        from ascendc_devkit.application.dispatcher import _apply_rerun
        from ascendc_devkit.infra.workspace import Workspace
        ws = Workspace.create(output_root=str(tmp_path), run_id="test-rf2")
        wf, _ = _seq_wf(_Tracker("trk", []), _Prov("b", []),
                        name="pipe")
        s = State.empty().with_updates(
            non_interactive=True, user_max_iterations=1,
            node_status={"pipe/trk": "completed", "pipe/b": "completed"},
            _workspace=ws)
        _apply_rerun(s, wf, "pipe/trk", ws)
        assert "trk" in calls, "_apply_rerun must call rerun_reset_files"
