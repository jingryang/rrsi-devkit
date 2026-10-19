"""§P7.1 + P2/P3/P5/P8 — stage failure status, fail_strategy halt signal, sticky error.

Coverage:
  1. runner.run_stage derives the stage status from the agent_result / last_error
     / unmet output_contract and passes it to stage_done + progress_callback
     (was hardcoded "ok").
  2. graph_executor._execute_atomic, on a swallowed non-control exception, marks
     the node "failed" (not "completed") so it is not resume-skipped and shows ✗.
  3. P2+P3: fail_strategy halt injects _stage_failed signal into State.
  4. P8: partial agent but contract satisfied → stage_status = "ok".
  5. P5→F6: sticky last_error 的收尾清除统一归 runner（delivered-success 归一化，
     §1.15 单点实现；stage 成功 return 不再各自手工清）。
"""

from __future__ import annotations

import pytest

import ascendc_devkit.orchestration.kernel.runner as runner_mod
from ascendc_devkit.orchestration.base import Stage
from ascendc_devkit.orchestration.kernel.runner import Runner
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.kernel.action import SpawnAgent, NoOp
from ascendc_devkit.domain.contract import StageIOContract
from ascendc_devkit.capabilities.agent.backend import AgentBackend, AgentResult


def _no_sleep(monkeypatch):
    """infra（error_type 非空）现走有界退避重试（真 sleep），测试里 no-op。"""
    monkeypatch.setattr(runner_mod.time, "sleep", lambda *_a, **_k: None)


class _StatusBackend(AgentBackend):
    """Returns an AgentResult with a fixed status (to exercise status derivation)."""

    def __init__(self, status, artifacts=None):
        self._status = status
        # None → the historical default payload; {} → clean finish, no products.
        self._artifacts = {"out.json": "{}"} if artifacts is None else artifacts

    def spawn(self, agent_name, prompt, context, skills=None,
              model=None, working_dir=None, repo_baseline=None, repo_root=None,
              stage_name="", branch_label="", resume_session_id=None, resume_prompt=None, primary_skill=None, deadline_monotonic: float | None = None):
        return AgentResult(agent_name=agent_name, status=self._status,
                           artifacts=self._artifacts)


class _AgentStage(Stage):
    name = "agent-stage"
    description = "spawns one agent"
    default_max_iterations = 1

    def input_contract(self):
        return StageIOContract(requires=[])

    def output_contract(self):
        return StageIOContract(provides=[])  # no contract → status from agent only

    def actions(self, state, iteration=1):
        return [SpawnAgent(agent_name="x", prompt="p", context={})]


def _run_status(agent_status):
    captured = {}

    def cb(event, stage_name, data):
        if event == "stage_complete":
            captured["status"] = data["status"]

    runner = Runner(agent_backend=_StatusBackend(agent_status),
                    progress_callback=cb)
    runner.run_stage(State(mode="new"), _AgentStage())
    return captured.get("status")


def _run_status_with(agent_status, artifacts):
    captured = {}

    def cb(event, stage_name, data):
        if event == "stage_complete":
            captured["status"] = data["status"]

    runner = Runner(agent_backend=_StatusBackend(agent_status, artifacts=artifacts),
                    progress_callback=cb)
    runner.run_stage(State(mode="new"), _AgentStage())
    return captured.get("status")


class TestRunnerStageStatus:
    def test_ok_agent_reports_ok(self):
        assert _run_status("ok") == "ok"

    def test_clean_agent_zero_artifacts_reports_ok(self):
        # F5: 干净完成 + 零产物不再有独立 status；无契约 stage 视为 ok。
        assert _run_status_with("ok", artifacts={}) == "ok"

    def test_partial_agent_reports_partial(self):
        # Crashed-but-salvaged: half-baked output must not look like success.
        assert _run_status("partial") == "partial"

    def test_fatal_agent_reports_failed(self):
        assert _run_status("fatal") == "failed"

    def test_compile_error_agent_reports_failed(self):
        assert _run_status("compile_error") == "failed"

    def test_done_glyph_reflects_failure(self, capsys):
        runner = Runner(agent_backend=_StatusBackend("fatal"))
        runner.run_stage(State(mode="new"), _AgentStage())
        err = capsys.readouterr().err
        assert "✗ agent-stage done" in err and "[failed]" in err
        assert "✓ agent-stage" not in err


class _InfraBackend(AgentBackend):
    """P93 (step-69): returns an infra-classified AgentResult (gateway/config/auth/
    spawn-timeout) to exercise the runner's infra iteration reason branch."""

    def spawn(self, agent_name, prompt, context, skills=None, model=None,
              working_dir=None, repo_baseline=None, repo_root=None,
              stage_name="", branch_label="", resume_session_id=None,
        resume_prompt=None,
              primary_skill=None, deadline_monotonic: float | None = None):
        return AgentResult(agent_name=agent_name, status="fatal", error_type="infra",
                           metrics={"failure_reason": "gateway price not configured"})


class TestIterationReasonInfra:
    """P93 (step-69): runner's iteration reason gains a 4th class — infrastructure
    error — so a spawn that crashed on an external infra fault (gateway/config/
    auth/spawn-timeout) is labeled infra, not misfiled as 'quality check not
    satisfied' / 'contract unsatisfied' (pipeline-observability P7 extension)."""

    def test_infra_agent_reason_labeled_infrastructure(self, monkeypatch):
        _no_sleep(monkeypatch)
        runner = Runner(agent_backend=_InfraBackend())
        runner.run_stage(State(mode="new"), _AgentStage())
        assert "infrastructure error" in runner._iteration_reason
        assert "gateway price not configured" in runner._iteration_reason

    def test_non_infra_reason_not_mislabeled(self):
        # 回归守护：普通 fatal（error_type=None）不被误标 infra
        runner = Runner(agent_backend=_StatusBackend("fatal"))
        runner.run_stage(State(mode="new"), _AgentStage())
        assert "infrastructure error" not in runner._iteration_reason


class _UnmetContractStage(Stage):
    name = "unmet"
    description = "promises a product it never produces"
    default_max_iterations = 1

    def input_contract(self):
        return StageIOContract(requires=[])

    def output_contract(self):
        return StageIOContract(provides=["never_produced"])

    def actions(self, state, iteration=1):
        return [NoOp()]


class _HalfMetContractStage(Stage):
    """Promises two products, delivers exactly one at transition."""
    name = "half-met"
    description = "partially delivers its contract"
    default_max_iterations = 1

    def input_contract(self):
        return StageIOContract(requires=[])

    def output_contract(self):
        return StageIOContract(provides=["design_spec", "vf_design"])

    def actions(self, state, iteration=1):
        return [NoOp()]

    def transition(self, state, result):
        return state.with_updates(design_spec={"inputs": []})


def test_unmet_output_contract_zero_provided_reports_failed():
    """F5: 契约未满足且零就位 → failed（该产出却空跑）。旧的恒 partial 把
    「一点没产出」含糊成「部分交付」，误导诊断。"""
    captured = {}

    def cb(event, stage_name, data):
        if event == "stage_complete":
            captured["status"] = data["status"]

    runner = Runner(progress_callback=cb)
    runner.run_stage(State(mode="new"), _UnmetContractStage())
    assert captured.get("status") == "failed"


def test_unmet_output_contract_partially_provided_reports_partial():
    """F5: 契约未满足但有部分就位 → partial（slow-but-salvageable）。"""
    captured = {}

    def cb(event, stage_name, data):
        if event == "stage_complete":
            captured["status"] = data["status"]

    runner = Runner(progress_callback=cb)
    runner.run_stage(State(mode="new"), _HalfMetContractStage())
    assert captured.get("status") == "partial"


def test_last_iter_ok_requires_artifacts_not_bare_ok():
    """F5: _last_iter_ok（deadline 抢救信号）只该为「干净完成且有产物」点亮；
    干净零产物轮保持 False，否则软超时会为空跑放行、丢掉"没产出"事实。"""
    runner = Runner(agent_backend=_StatusBackend("ok"))
    runner.run_stage(State(mode="new"), _AgentStage())
    assert runner._last_iter_ok is True

    runner = Runner(agent_backend=_StatusBackend("ok", artifacts={}))
    runner.run_stage(State(mode="new"), _AgentStage())
    assert runner._last_iter_ok is False


# —— graph_executor: swallowed exception marks "failed", not "completed" ——

class _RaisingStage(Stage):
    name = "boom"
    description = "raises a non-control exception"
    default_max_iterations = 1

    def input_contract(self):
        return StageIOContract(requires=[])

    def output_contract(self):
        return StageIOContract(provides=[])

    def actions(self, state, iteration=1):
        return [NoOp()]

    def transition(self, state, result):
        raise RuntimeError("kaboom")


def test_atomic_failure_marks_node_failed_not_completed():
    from ascendc_devkit.orchestration.graph_executor import GraphExecutor
    from ascendc_devkit.orchestration.node import AtomicStage

    node = AtomicStage(_RaisingStage())
    ex = GraphExecutor(runner=Runner())
    state = ex._execute_atomic(node, State(mode="new"), path="boom")
    # The node must be visibly failed, not silently completed (would resume-skip).
    assert state.node_status.get("boom") == "failed"
    assert state.node_status.get("boom") != "completed"


# —— §P7.1: a failed leaf propagates "failed" up its enclosing group/root ——

def test_failed_leaf_propagates_to_sequential_group():
    """A swallowed failure in one leaf must keep the enclosing group (and root)
    non-completed, else the whole run exits as a clean success despite a broken
    stage. The group is "failed", not "completed"."""
    from ascendc_devkit.orchestration.graph_executor import GraphExecutor
    from ascendc_devkit.orchestration.node import AtomicStage, SequentialGroup

    class _OkStage(_RaisingStage):
        name = "ok-leaf"
        def transition(self, state, result):
            return state

    group = SequentialGroup("grp", children=[AtomicStage(_OkStage()),
                                    AtomicStage(_RaisingStage())])
    ex = GraphExecutor(runner=Runner())
    state = ex._execute_node(group, State(mode="new"), scope_prefix="")
    assert state.node_status.get("grp/boom") == "failed"
    assert state.node_status.get("grp") == "failed"   # not "completed"


def test_all_ok_leaves_keep_group_completed():
    from ascendc_devkit.orchestration.graph_executor import GraphExecutor
    from ascendc_devkit.orchestration.node import AtomicStage, SequentialGroup

    class _OkStage(_RaisingStage):
        name = "ok-leaf"
        def transition(self, state, result):
            return state

    class _OkStage2(_OkStage):
        name = "ok-leaf-2"

    group = SequentialGroup("grp", children=[AtomicStage(_OkStage()),
                                    AtomicStage(_OkStage2())])
    ex = GraphExecutor(runner=Runner())
    state = ex._execute_node(group, State(mode="new"), scope_prefix="")
    assert state.node_status.get("grp") == "completed"


# —— §P7.1 fix: a STALE upstream last_error must not mis-mark a clean stage ——

class _NoErrorNoOpStage(Stage):
    name = "clean-noop"
    description = "no actions, no own error, empty output contract"
    default_max_iterations = 1

    def input_contract(self):
        return StageIOContract(requires=[])

    def output_contract(self):
        return StageIOContract(provides=[])

    def actions(self, state, iteration=1):
        return [NoOp()]


def test_stale_upstream_error_does_not_mark_clean_stage_failed():
    """last_error is sticky in State. A no-op / clean stage must report its OWN
    status, not inherit a failed-upstream stage's error (regression: dd-intake
    no-op showed ✗ failed only because requirement upstream had failed)."""
    from ascendc_devkit.orchestration.kernel.state import ErrorFeedback

    captured = {}

    def cb(event, stage_name, data):
        if event == "stage_complete":
            captured["status"] = data["status"]

    # NoOp stage with no own error, but State carries an upstream stage's error.
    state = State(mode="new").with_updates(
        last_error=ErrorFeedback(stage_name="requirement",
                                 error_type="x", message="upstream failed"))
    Runner(progress_callback=cb).run_stage(state, _NoErrorNoOpStage())
    assert captured.get("status") == "ok"


def test_own_error_still_marks_failed():
    """Sanity: an error THIS stage produced still marks it failed."""
    from ascendc_devkit.orchestration.kernel.state import ErrorFeedback

    class _SelfErrorStage(Stage):
        name = "self-err"
        default_max_iterations = 1
        def input_contract(self): return StageIOContract(requires=[])
        def output_contract(self): return StageIOContract(provides=[])
        def actions(self, state, iteration=1): return [NoOp()]
        def transition(self, state, result):
            return state.with_updates(last_error=ErrorFeedback(
                stage_name="self-err", error_type="x", message="my own error"))

    captured = {}
    def cb(event, stage_name, data):
        if event == "stage_complete":
            captured["status"] = data["status"]
    Runner(progress_callback=cb).run_stage(State(mode="new"), _SelfErrorStage())
    assert captured.get("status") == "failed"


# —— P2+P3: fail_strategy halt injects _stage_failed signal ——

class _HaltStage(Stage):
    """A stage with fail_strategy='halt' that returns a fatal agent status."""
    name = "halt-stage"
    description = "halts on failure"
    default_max_iterations = 1
    fail_strategy = "halt"

    def input_contract(self):
        return StageIOContract(requires=[])

    def output_contract(self):
        return StageIOContract(provides=[])

    def actions(self, state, iteration=1):
        return [SpawnAgent(agent_name="x", prompt="p", context={})]


class _ContinueStage(Stage):
    """A stage with fail_strategy='continue' that returns a fatal agent status."""
    name = "continue-stage"
    description = "continues on failure"
    default_max_iterations = 1
    fail_strategy = "continue"

    def input_contract(self):
        return StageIOContract(requires=[])

    def output_contract(self):
        return StageIOContract(provides=[])

    def actions(self, state, iteration=1):
        return [SpawnAgent(agent_name="x", prompt="p", context={})]


def test_halt_stage_sets_stage_failed():
    """fail_strategy='halt' + agent status!='ok' → _stage_failed is set."""
    from ascendc_devkit.capabilities.agent.backend import AgentBackend, AgentResult

    class FatalBackend(AgentBackend):
        def spawn(self, agent_name, prompt, context, skills=None,
                  model=None, working_dir=None, repo_baseline=None, repo_root=None,
                  stage_name="", branch_label="", resume_session_id=None, resume_prompt=None, primary_skill=None, deadline_monotonic: float | None = None):
            return AgentResult(agent_name="x", status="fatal")

    runner = Runner(agent_backend=FatalBackend())
    state = runner.run_stage(State(mode="new"), _HaltStage())
    assert getattr(state, "_stage_failed", None) is not None
    assert state._stage_failed[0] == "failed"
    assert state._stage_failed[1] == "halt-stage"


def test_continue_stage_does_not_set_stage_failed():
    """fail_strategy='continue' + agent status!='ok' → _stage_failed is NOT set."""
    from ascendc_devkit.capabilities.agent.backend import AgentBackend, AgentResult

    class FatalBackend(AgentBackend):
        def spawn(self, agent_name, prompt, context, skills=None,
                  model=None, working_dir=None, repo_baseline=None, repo_root=None,
                  stage_name="", branch_label="", resume_session_id=None, resume_prompt=None, primary_skill=None, deadline_monotonic: float | None = None):
            return AgentResult(agent_name="x", status="fatal")

    runner = Runner(agent_backend=FatalBackend())
    state = runner.run_stage(State(mode="new"), _ContinueStage())
    assert getattr(state, "_stage_failed", None) is None


def test_halt_with_own_error_also_sets_stage_failed():
    """fail_strategy='halt' + own last_error → _stage_failed is set."""
    from ascendc_devkit.orchestration.kernel.state import ErrorFeedback

    class _HaltSelfErrorStage(Stage):
        name = "halt-self-err"
        default_max_iterations = 1
        fail_strategy = "halt"
        def input_contract(self): return StageIOContract(requires=[])
        def output_contract(self): return StageIOContract(provides=[])
        def actions(self, state, iteration=1): return [NoOp()]
        def transition(self, state, result):
            return state.with_updates(last_error=ErrorFeedback(
                stage_name="halt-self-err", error_type="x", message="my own error"))

    runner = Runner()
    state = runner.run_stage(State(mode="new"), _HaltSelfErrorStage())
    assert getattr(state, "_stage_failed", None) is not None
    assert state._stage_failed[1] == "halt-self-err"


# —— P8: partial agent but contract satisfied → stage_status = "ok" ——

class _PartialButCompleteStage(Stage):
    """A stage that satisfies its contract even when agent reports partial."""
    name = "partial-ok"
    description = "partial agent, but contract met"
    default_max_iterations = 1
    fail_strategy = "continue"

    def input_contract(self):
        return StageIOContract(requires=[])

    def output_contract(self):
        return StageIOContract(provides=["generated_sources"])

    def actions(self, state, iteration=1):
        return [SpawnAgent(agent_name="x", prompt="p", context={})]

    def transition(self, state, result):
        return state.with_updates(generated_sources={"f.cpp": "// ok"})


class _PartialUnsatisfiedStage(Stage):
    """A stage that does NOT satisfy its contract; agent is partial."""
    name = "partial-nope"
    description = "partial agent, contract unsatisfied"
    default_max_iterations = 1
    fail_strategy = "continue"

    def input_contract(self):
        return StageIOContract(requires=[])

    def output_contract(self):
        return StageIOContract(provides=["generated_sources"])

    def actions(self, state, iteration=1):
        return [SpawnAgent(agent_name="x", prompt="p", context={})]

    def transition(self, state, result):
        # Does NOT set generated_sources → contract stays unsatisfied
        return state


def test_partial_agent_with_contract_satisfied_reports_ok():
    """P8: agent is 'partial' (crashed but salvaged) but the required contract
    is fully satisfied → stage_status must be 'ok', not 'partial'."""
    from ascendc_devkit.capabilities.agent.backend import AgentBackend, AgentResult

    captured = {}

    class PartialBackend(AgentBackend):
        def spawn(self, agent_name, prompt, context, skills=None,
                  model=None, working_dir=None, repo_baseline=None, repo_root=None,
                  stage_name="", branch_label="", resume_session_id=None, resume_prompt=None, primary_skill=None, deadline_monotonic: float | None = None):
            return AgentResult(agent_name="x", status="partial",
                              artifacts={"out.json": '{"ok": true}'})

    def cb(event, stage_name, data):
        if event == "stage_complete":
            captured["status"] = data["status"]

    runner = Runner(agent_backend=PartialBackend(), progress_callback=cb)
    runner.run_stage(State(mode="new"), _PartialButCompleteStage())
    # P8 fix: partial agent but contract satisfied → "ok"
    assert captured.get("status") == "ok"


def test_partial_agent_with_contract_unsatisfied_stays_partial():
    """P8: agent is 'partial' AND contract is NOT satisfied → stay 'partial'."""
    from ascendc_devkit.capabilities.agent.backend import AgentBackend, AgentResult

    captured = {}

    class PartialEmptyBackend(AgentBackend):
        def spawn(self, agent_name, prompt, context, skills=None,
                  model=None, working_dir=None, repo_baseline=None, repo_root=None,
                  stage_name="", branch_label="", resume_session_id=None, resume_prompt=None, primary_skill=None, deadline_monotonic: float | None = None):
            return AgentResult(agent_name="x", status="partial")

    def cb(event, stage_name, data):
        if event == "stage_complete":
            captured["status"] = data["status"]

    runner = Runner(agent_backend=PartialEmptyBackend(), progress_callback=cb)
    runner.run_stage(State(mode="new"), _PartialUnsatisfiedStage())
    # Contract NOT satisfied → remains "partial"
    assert captured.get("status") == "partial"


# —— P4 + P5: _working_dir pass-through + _parse_single reads from disk ——

def test_spawn_agent_forwards_working_dir():
    """Runner._execute_spawn_agent injects _working_dir into result dict (P4)."""
    from ascendc_devkit.capabilities.agent.backend import AgentBackend, AgentResult

    class EchoBackend(AgentBackend):
        def spawn(self, agent_name, prompt, context, skills=None,
                  model=None, working_dir=None, repo_baseline=None, repo_root=None,
                  stage_name="", branch_label="", resume_session_id=None, resume_prompt=None, primary_skill=None, deadline_monotonic: float | None = None):
            return AgentResult(agent_name="x", status="ok",
                              artifacts={"out.json": "{}"})

    runner = Runner(agent_backend=EchoBackend())
    action = SpawnAgent(agent_name="x", prompt="p", context={},
                       working_dir="/tmp/design/stage")
    result = {}
    runner._execute_spawn_agent(action, result)
    assert result.get("_working_dir") == "/tmp/design/stage"


def test_spawn_agent_no_working_dir_omits_key():
    """When action has no working_dir, _working_dir key is absent from result."""
    from ascendc_devkit.capabilities.agent.backend import AgentBackend, AgentResult

    class EchoBackend(AgentBackend):
        def spawn(self, agent_name, prompt, context, skills=None,
                  model=None, working_dir=None, repo_baseline=None, repo_root=None,
                  stage_name="", branch_label="", resume_session_id=None, resume_prompt=None, primary_skill=None, deadline_monotonic: float | None = None):
            return AgentResult(agent_name="x", status="ok",
                              artifacts={"out.json": "{}"})

    runner = Runner(agent_backend=EchoBackend())
    action = SpawnAgent(agent_name="x", prompt="p", context={})
    result = {}
    runner._execute_spawn_agent(action, result)
    assert "_working_dir" not in result


# —— P51: continue-stage crash classification → halt/loopback routing (Option E) ——
#
# A continue stage that hard-crashes used to mark "failed" + advance linearly
# (transition/resolve_condition short-circuited → stale "default" → downstream
# runs on broken state). P51 classifies the uncaught exception in the
# _execute_atomic except branch: non-fixable (infra / framework-state) → halt
# (_stage_failed); the rest (codegen-fixable + gray-zone) → loopback via the
# stage's on_uncaught_failure hook.
#
# P57 note: verify used to be the sole stage overriding on_uncaught_failure
# (bumping verify_iterations + marking build_result crash-failed). With verify
# deleted, no production stage overrides the hook anymore — the base no-op
# applies, and a recurring fixable/gray crash is bounded by the generic
# corrective quota (max_corrective) on the loopback edge, not a
# verify-specific counter. The _CrashStage double below exercises the hook
# path (build_result crash-failed = routing signal) generically.

class _CrashStage(Stage):
    """A continue stage whose actions() raises a fixed exception (P51 crash).

    ``hook=True`` exercises the on_uncaught_failure override path: marks
    build_result crash-failed so the crash leaves a routing signal (the
    resolve_condition/loopback machinery reads build_result). No production
    stage overrides the hook post-P57 (verify is gone); this double keeps the
    override-path branch under test.
    """
    default_max_iterations = 1
    fail_strategy = "continue"

    def __init__(self, exc, name="crash-stage", hook=False):
        self._exc = exc
        self.name = name
        self._hook = hook

    def input_contract(self):
        return StageIOContract(requires=[])

    def output_contract(self):
        return StageIOContract(provides=[])

    def actions(self, state, iteration=1):
        raise self._exc

    def on_uncaught_failure(self, state, exc):
        if not self._hook:
            return super().on_uncaught_failure(state, exc)
        from ascendc_devkit.domain.verification import BuildResult
        return state.with_updates(
            build_result=BuildResult(passed=False, stderr=str(exc)),
        )


class _HaltCrashStage(_CrashStage):
    """fail_strategy=halt variant — P46 unconditional halt on crash."""
    fail_strategy = "halt"


def _exec_crash(stage, path="crash-stage"):
    from ascendc_devkit.orchestration.graph_executor import GraphExecutor
    from ascendc_devkit.orchestration.node import AtomicStage
    ex = GraphExecutor(runner=Runner())
    return ex._execute_atomic(AtomicStage(stage), State(mode="new"), path=path)


class TestP51CrashClassifier:
    """Pure-function tests for the binary classifier (non-fixable → halt; else
    loopback; gray-zone folds into 'unclassified' → loopback)."""

    def test_classify_infra_crash(self):
        from ascendc_devkit.orchestration.graph_executor import (
            _classify_uncaught, _is_non_fixable)
        cls = _classify_uncaught(RuntimeError("API Error: 401 unauthorized"))
        assert cls == "infra"
        assert _is_non_fixable(cls) is True

    def test_classify_framework_state_crash(self):
        # The P48 shape: a primitive (dict) where a domain object (TestCase)
        # was expected — deserialization/state-layer bug, not codegen-fixable.
        from ascendc_devkit.orchestration.graph_executor import (
            _classify_uncaught, _is_non_fixable)
        cls = _classify_uncaught(
            AttributeError("'dict' object has no attribute 'inputs'"))
        assert cls == "framework"
        assert _is_non_fixable(cls) is True

    def test_classify_codegen_crash_unclassified(self):
        # A kernel-level crash (segfault surfaced as a runtime error) is
        # codegen-fixable → NOT non-fixable → loopback.
        from ascendc_devkit.orchestration.graph_executor import (
            _classify_uncaught, _is_non_fixable)
        cls = _classify_uncaught(
            RuntimeError("kernel raised illegal instruction / segfault"))
        assert cls == "unclassified"
        assert _is_non_fixable(cls) is False


class TestP51ContinueCrashRouting:
    def test_continue_crash_non_fixable_halts(self):
        # infra crash on a continue stage → halt (handoff), not advance.
        from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
        stage = _CrashStage(RuntimeError("No available channel for model"))
        state = _exec_crash(stage)
        assert state.node_status.get("crash-stage") == "failed"
        assert getattr(state, "_stage_failed", None) is not None
        assert state._stage_failed[1] == "crash-stage"
        assert isinstance(state.last_error, ErrorFeedback)
        assert state.last_error.error_type == "infra"

    def test_continue_crash_framework_halts(self):
        # framework/state-layer crash (P48 deserialization shape) → halt.
        stage = _CrashStage(
            AttributeError("'dict' object has no attribute 'inputs'"))
        state = _exec_crash(stage)
        assert getattr(state, "_stage_failed", None) is not None
        assert state.last_error.error_type == "framework"

    def test_continue_crash_codegen_loopbacks(self):
        # codegen-fixable crash → NOT halt; hook marks build_result failed
        # (routing signal for the loopback/resolve_condition machinery).
        stage = _CrashStage(
            RuntimeError("kernel segfault / illegal instruction"), hook=True)
        state = _exec_crash(stage)
        assert getattr(state, "_stage_failed", None) is None   # loopback, not halt
        assert state.build_result is not None
        assert state.build_result.passed is False              # routing signal set
        assert state.last_error.error_type == "unclassified"

    def test_continue_crash_gray_defaults_loopback(self):
        # A genuinely unclassifiable exception → default loopback (user: prefer
        # wasting tokens over missing a fix opportunity).
        class _Weird(Exception):
            pass
        stage = _CrashStage(_Weird("??? no precedent ???"), hook=True)
        state = _exec_crash(stage)
        assert getattr(state, "_stage_failed", None) is None   # gray → loopback
        assert state.build_result.passed is False


class TestP51HookAndP46Regression:
    def test_on_uncaught_failure_default_noop(self):
        # base Stage hook is a no-op: a non-overriding stage crash leaves state
        # unchanged (the post-P57 default — no production stage overrides it).
        s = _CrashStage(RuntimeError("boom"))  # hook=False → base no-op
        before = State(mode="new")
        after = s.on_uncaught_failure(before, RuntimeError("boom"))
        assert after is before or after == before

    def test_halt_stage_crash_halt_unconditional(self):
        # P46 regression guard: a halt stage halts on ANY crash, even one that
        # would otherwise classify as fixable/gray (unclassified).
        stage = _HaltCrashStage(
            RuntimeError("kernel segfault"), name="halt-crash")  # unclassified
        state = _exec_crash(stage, path="halt-crash")
        assert getattr(state, "_stage_failed", None) is not None
        assert state._stage_failed[1] == "halt-crash"


# —— P1: stage_complete event carries the real stage_status ——
#
# run 20260730-072625-bec36b: codegen halted yet report showed status=ok, because
# the stage_complete event was emitted BEFORE stage_status was computed (so it
# carried no status) and report.py hardcoded "ok". The emit now happens after
# stage_status is final and carries it on the event.

class _CaptureLog(list):
    """list subclass that stays truthy so runner's `if self._event_log:` guard
    fires even when empty (a plain [] is falsy → emit skipped)."""

    def __bool__(self):
        return True


def test_stage_complete_event_carries_failed_status():
    runner = Runner(agent_backend=_StatusBackend("fatal"))
    log = _CaptureLog()
    runner._event_log = log
    runner.run_stage(State(mode="new"), _AgentStage())
    completes = [e for e in log if e.get("type") == "stage_complete"]
    assert completes, "expected a stage_complete event"
    assert completes[-1]["status"] == "failed"


def test_stage_complete_event_carries_ok_status():
    runner = Runner(agent_backend=_StatusBackend("ok"))
    log = _CaptureLog()
    runner._event_log = log
    runner.run_stage(State(mode="new"), _AgentStage())
    completes = [e for e in log if e.get("type") == "stage_complete"]
    assert completes[-1]["status"] == "ok"


def test_iteration_reason_distinguishes_contract_broken():
    """P1: 契约不满足 + 本 stage 已记 last_error → reason 透出 error_type，
    区分「stage 主动判失败」与「agent 真没产出」（run 20260730 不可诊断）。"""
    from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
    from ascendc_devkit.capabilities.agent.backend import AgentBackend, AgentResult

    class _ContractBrokenStage(Stage):
        name = "broken"
        default_max_iterations = 1
        fail_strategy = "continue"

        def input_contract(self):
            return StageIOContract(requires=[])

        def output_contract(self):
            return StageIOContract(provides=["generated_sources"])

        def actions(self, state, iteration=1):
            return [SpawnAgent(agent_name="x", prompt="p", context={})]

        def transition(self, state, result):
            return state.with_updates(last_error=ErrorFeedback(
                stage_name="broken", error_type="incomplete_output",
                message="CMakeLists.txt missing on disk"))

    class _OkBackend(AgentBackend):
        def spawn(self, agent_name, prompt, context, skills=None, model=None,
                  working_dir=None, repo_baseline=None, repo_root=None,
                  stage_name="", branch_label="", resume_session_id=None,
                  resume_prompt=None,
                  primary_skill=None, deadline_monotonic: float | None = None):
            return AgentResult(agent_name="x", status="ok",
                               artifacts={"out.json": "{}"})

    runner = Runner(agent_backend=_OkBackend())
    runner.run_stage(State(mode="new"), _ContractBrokenStage())
    assert "contract broken" in runner._iteration_reason
    assert "incomplete_output" in runner._iteration_reason


def test_iteration_reason_plain_unsatisfied_without_last_error():
    """P1 对照：契约不满足但 stage 未记 last_error（agent 真没产出）→ 仍报
    'contract unsatisfied: <missing>'，不被误判为 contract broken。"""
    runner = Runner()  # _UnmetContractStage uses NoOp, no backend needed
    runner.run_stage(State(mode="new"), _UnmetContractStage())
    assert runner._iteration_reason.startswith("contract unsatisfied:")


# —— F6: stage 收尾统一错误归一化（通用行为统一抽象，CLAUDE.md §1.15）——
#
# d8d4d9 形态：round 1 记 own 错误（artifacts 缺要求的 key → schema_violation）、
# round 2 交付成功但【不清】last_error（requirement 当年的漏写）——runner 必须在
# stage 收尾统一归一化：已交付（agent 干净 + 契约满足 + 质量门过）⇒ 残留 own 错误
# 已过时，清除后再推导 status。

class _StickyErrorStage(Stage):
    """Two-round stage: round 1 misses the required artifact key (records own
    schema_violation), round 2 delivers — WITHOUT clearing last_error (models
    the pre-fix requirement transition)."""
    name = "sticky-err"
    description = "records an error then delivers without clearing it"
    default_max_iterations = 3
    fail_strategy = "continue"

    def input_contract(self):
        return StageIOContract(requires=[])

    def output_contract(self):
        return StageIOContract(provides=["design_spec"])

    def actions(self, state, iteration=1):
        return [SpawnAgent(agent_name="x", prompt="p", context={})]

    def transition(self, state, result):
        from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
        ar = result.get("agent_result")
        if ar is None:
            return state
        if "requirement.json" not in ar.artifacts:
            return state.with_updates(last_error=ErrorFeedback(
                stage_name=self.name, error_type="schema_violation",
                message="requirement.json: required artifact not produced"))
        return state.with_updates(design_spec={"ok": True})  # 故意不清错


def _run_sticky(stage_cls=_StickyErrorStage, **backend_kw):
    from ascendc_devkit.capabilities.agent.stub_backend import StubBackend
    captured = {}

    def cb(event, stage_name, data):
        if event == "stage_complete":
            captured["status"] = data["status"]

    runner = Runner(agent_backend=StubBackend(**backend_kw), progress_callback=cb)
    state = runner.run_stage(State(mode="new"), stage_cls())
    return captured.get("status"), state


class TestF6UnifiedErrorResolution:
    def test_delivered_success_clears_stale_own_error(self):
        """d8d4d9 回归：round1 记错、round2 交付且不清 → status=ok 且
        last_error 收尾为 None（归一化清除，而非判定无视）。"""
        from ascendc_devkit.capabilities.agent.backend import AgentResult
        status, state = _run_sticky(canned_responses=[
            AgentResult(agent_name="x", status="ok",
                        artifacts={"wrong.json": "{}"}),     # round 1: 记错
            AgentResult(agent_name="x", status="ok",
                        artifacts={"requirement.json": "{}"})])  # round 2: 交付
        assert status == "ok"
        assert state.last_error is None

    def test_clear_emits_observable_warn(self, capsys):
        from ascendc_devkit.capabilities.agent.backend import AgentResult
        _run_sticky(canned_responses=[
            AgentResult(agent_name="x", status="ok", artifacts={"wrong.json": "{}"}),
            AgentResult(agent_name="x", status="ok",
                        artifacts={"requirement.json": "{}"})])
        err = capsys.readouterr().err
        assert "cleared stale" in err and "sticky-err" in err

    def test_quality_gate_not_passed_keeps_error(self):
        """质量门未过 → 不算已交付，错误保留、status 非 ok。"""
        class _QualityFail(_StickyErrorStage):
            name = "sticky-quality"
            def is_satisfied(self, state) -> bool:
                return False

        from ascendc_devkit.capabilities.agent.backend import AgentResult
        status, state = _run_sticky(
            _QualityFail,
            canned_responses=[
                AgentResult(agent_name="x", status="ok",
                            artifacts={"wrong.json": "{}"}),
                AgentResult(agent_name="x", status="ok",
                            artifacts={"requirement.json": "{}"})])
        assert status != "ok"
        assert state.last_error is not None

    def test_contract_unsatisfied_keeps_error(self):
        """契约未满足 → 不算已交付，错误保留。"""
        class _NeverDelivers(_StickyErrorStage):
            name = "sticky-undelivered"
            def transition(self, state, result):
                from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
                ar = result.get("agent_result")
                if ar is None:
                    return state
                # 永远只记错、永不交付 design_spec
                return state.with_updates(last_error=ErrorFeedback(
                    stage_name=self.name, error_type="schema_violation",
                    message="never delivers"))

        from ascendc_devkit.capabilities.agent.backend import AgentResult
        status, state = _run_sticky(
            _NeverDelivers,
            canned_responses=[
                AgentResult(agent_name="x", status="ok",
                            artifacts={"wrong.json": "{}"}),
                AgentResult(agent_name="x", status="ok",
                            artifacts={"requirement.json": "{}"})])
        assert status != "ok"
        assert state.last_error is not None

    def test_infra_final_round_keeps_error(self):
        """末轮 infra（不可恢复）→ 不清除（P116：infra 错误必须保留）。"""
        from ascendc_devkit.capabilities.agent.backend import AgentResult
        from ascendc_devkit.orchestration.kernel.state import ErrorFeedback

        class _InfraThenDeliver(_StickyErrorStage):
            name = "sticky-infra"
            def transition(self, state, result):
                ar = result.get("agent_result")
                if ar is None:
                    return state
                if ar.error_type == "infra":
                    return state.with_updates(
                        design_spec={"ok": True},
                        last_error=ErrorFeedback(
                            stage_name=self.name, error_type="infra",
                            message="gateway down"))
                return super().transition(state, result)

        status, state = _run_sticky(
            _InfraThenDeliver,
            canned_responses=[
                AgentResult(agent_name="x", status="ok",
                            artifacts={"wrong.json": "{}"}),
                AgentResult(agent_name="x", status="fatal", error_type="infra",
                            artifacts={})])
        assert status != "ok"
        assert state.last_error is not None

    def test_inherited_upstream_error_survives_delivery(self):
        """上游 stage 遗留错误不被本 stage 的归一化顺手抹掉（只清署名本
        stage 的错误）——保留真实溯源。"""
        from ascendc_devkit.capabilities.agent.stub_backend import StubBackend
        from ascendc_devkit.capabilities.agent.backend import AgentResult
        from ascendc_devkit.orchestration.kernel.state import ErrorFeedback

        class _CleanDeliver(_StickyErrorStage):
            name = "clean-deliver"
            def transition(self, state, result):
                return state.with_updates(design_spec={"ok": True})

        captured = {}

        def cb(event, stage_name, data):
            if event == "stage_complete":
                captured["status"] = data["status"]

        runner = Runner(agent_backend=StubBackend(canned_responses=[
            AgentResult(agent_name="x", status="ok",
                        artifacts={"requirement.json": "{}"})]),
            progress_callback=cb)
        state = runner.run_stage(
            State(mode="new").with_updates(last_error=ErrorFeedback(
                stage_name="requirement", error_type="x",
                message="upstream failed")),
            _CleanDeliver())
        assert captured.get("status") == "ok"
        assert state.last_error is not None, "上游错误必须存活"
        assert state.last_error.stage_name == "requirement"
