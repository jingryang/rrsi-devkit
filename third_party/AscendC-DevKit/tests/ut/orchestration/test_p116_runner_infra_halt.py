"""P116 — runner 层通用 infra halt（requirement 漏修 P93 infra 感知的根治）。

根因：infra halt（横切控制流，§1.10）此前只在 stage 层各加（codegen step-27 /
_DesignSubstage step-69），顶层 stage 如 requirement（fail_strategy="continue"）漏修
→ 撞网关 401 等不可恢复 infra error 时：① 空烧 max_iterations 重试；② 产物缺失却
node_status="completed"（误判）→ resume 跳过 → 下游 abort。

修复：runner 层通用 infra halt —— agent_result.error_type=="infra" 时首次即 break
（不烧重试）+ 无视 fail_strategy 强制 _stage_failed（标 node_status=failed → resume
重跑）。逻辑失败（error_type=None）仍按原 fail_strategy（continue 重试 / halt）。
"""
from __future__ import annotations

import pytest

import ascendc_devkit.orchestration.kernel.runner as runner_mod
from ascendc_devkit.orchestration.base import Stage
from ascendc_devkit.orchestration.kernel.runner import Runner
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.kernel.action import SpawnAgent
from ascendc_devkit.domain.contract import StageIOContract
from ascendc_devkit.capabilities.agent.backend import AgentBackend, AgentResult


def _no_sleep(monkeypatch):
    """infra 现走有界退避重试（会真 sleep），测试里 no-op 掉。"""
    monkeypatch.setattr(runner_mod.time, "sleep", lambda *_a, **_k: None)


# infra（error_type 非空）现按 fail-open 做有界重试：初始 1 发 + cap(4) 次重试 = 5 发。
_INFRA_SPAWNS = 5


class _CountingBackend(AgentBackend):
    """Returns a fixed AgentResult and counts spawns (to assert no budget burn)."""

    def __init__(self, status="fatal", error_type=None, failure_reason=""):
        self.spawn_count = 0
        self._status = status
        self._error_type = error_type
        self._fr = failure_reason

    def spawn(self, agent_name, prompt, context, skills=None, model=None,
              working_dir=None, repo_baseline=None, repo_root=None,
              stage_name="", branch_label="", resume_session_id=None,
        resume_prompt=None,
              primary_skill=None, deadline_monotonic: float | None = None):
        self.spawn_count += 1
        return AgentResult(
            agent_name=agent_name, status=self._status,
            error_type=self._error_type,
            metrics=({"failure_reason": self._fr} if self._fr else None))


class _ContinueAgentStage(Stage):
    """fail_strategy='continue', multi-iteration budget (mirrors requirement)."""
    name = "continue-agent-stage"
    default_max_iterations = 10
    fail_strategy = "continue"

    def input_contract(self):
        return StageIOContract(requires=[])

    def output_contract(self):
        return StageIOContract(provides=[])  # no contract → status from agent only

    def actions(self, state, iteration=1):
        return [SpawnAgent(agent_name="x", prompt="p", context={})]


class _HaltAgentStage(Stage):
    """fail_strategy='halt', multi-iteration budget."""
    name = "halt-agent-stage"
    default_max_iterations = 10
    fail_strategy = "halt"

    def input_contract(self):
        return StageIOContract(requires=[])

    def output_contract(self):
        return StageIOContract(provides=[])

    def actions(self, state, iteration=1):
        return [SpawnAgent(agent_name="x", prompt="p", context={})]


# —— P116 core: continue stage + infra → runner halt (was: not set → completed) ——

def test_continue_stage_infra_sets_stage_failed(monkeypatch):
    """continue stage + infra error → _stage_failed IS set (P116).

    Pre-P116: requirement (continue) + 401 → _stage_failed None → node_status
    "completed" → resume skip → downstream abort. This is the root-case UT.
    """
    _no_sleep(monkeypatch)
    backend = _CountingBackend(status="fatal", error_type="infra",
                               failure_reason="401 Invalid token")
    runner = Runner(agent_backend=backend)
    state = runner.run_stage(State(mode="new"), _ContinueAgentStage())
    assert getattr(state, "_stage_failed", None) is not None
    assert state._stage_failed[1] == "continue-agent-stage"


def test_continue_stage_infra_iteration_reason_labeled(monkeypatch):
    """infra → iteration reason labels 'infrastructure error' (P93 reason retained)."""
    _no_sleep(monkeypatch)
    backend = _CountingBackend(status="fatal", error_type="infra",
                               failure_reason="401 Invalid token")
    runner = Runner(agent_backend=backend)
    runner.run_stage(State(mode="new"), _ContinueAgentStage())
    assert "infrastructure error" in runner._iteration_reason
    assert "401 Invalid token" in runner._iteration_reason


# —— P116 (revised fail-open): infra 做有界重试，不烧满 max_iterations ——

def test_infra_bounded_retry_then_halt(monkeypatch):
    """infra → 有界重试（初始 1 发 + cap 4 次重试 = 5 发），非「首见即 halt」也非
    「烧满 max_iterations=10」。

    run 20260725-152037 abeb6c: requirement spun 10× on 401, each identical, 38min
    （无界重试）；P116 曾改为 1 发即停；现 fail-open 折中为有界重试 5 发。
    """
    _no_sleep(monkeypatch)
    backend = _CountingBackend(status="fatal", error_type="infra")
    runner = Runner(agent_backend=backend)
    runner.run_stage(State(mode="new"), _ContinueAgentStage())  # max=10
    assert backend.spawn_count == _INFRA_SPAWNS, \
        f"infra must bounded-retry {_INFRA_SPAWNS} spawns, got {backend.spawn_count}"


# —— P116 regression guards: logic failures (error_type=None) unaffected ——

def test_logic_failure_continue_still_retries():
    """non-infra logic fatal + continue → still burns full budget, no halt (P51 loopback)."""
    backend = _CountingBackend(status="fatal", error_type=None)  # logic failure
    runner = Runner(agent_backend=backend)
    state = runner.run_stage(State(mode="new"), _ContinueAgentStage())  # max=10
    assert getattr(state, "_stage_failed", None) is None, \
        "logic failure on continue stage must NOT set _stage_failed (P51 loopback)"
    assert backend.spawn_count == 10, \
        f"logic failure on continue must burn full budget, got {backend.spawn_count}"


def test_logic_failure_halt_still_halts():
    """non-infra logic fatal + halt → still halts (fail_strategy honored, regression)."""
    backend = _CountingBackend(status="fatal", error_type=None)
    runner = Runner(agent_backend=backend)
    state = runner.run_stage(State(mode="new"), _HaltAgentStage())
    assert getattr(state, "_stage_failed", None) is not None


def test_infra_halt_on_halt_stage_no_double_fail(monkeypatch):
    """halt stage + infra → _stage_failed set once (fail_strategy or infra, no double)."""
    _no_sleep(monkeypatch)
    backend = _CountingBackend(status="fatal", error_type="infra")
    runner = Runner(agent_backend=backend)
    state = runner.run_stage(State(mode="new"), _HaltAgentStage())
    assert getattr(state, "_stage_failed", None) is not None
    assert backend.spawn_count == _INFRA_SPAWNS  # infra 有界重试，不因 fail_strategy 而少试


# —— P116 Change D: requirement transition propagates error_type=infra ——


def test_requirement_transition_infra_propagates_error_type():
    """P116 Change D: requirement transition propagates error_type=infra.

    Pre-P116: ``error_type=agent_result.status`` dropped the infra signal (wrote
    "fatal"). Other consumers (own_error display, halt_reason.message, downstream
    prompts, stage-level guards) read state.last_error.error_type and need the
    honest class. Mirrors codegen.py:1325-1338.
    """
    from ascendc_devkit.orchestration.stages.requirement import RequirementStage
    ar = AgentResult(agent_name="requirement-analyst", status="fatal",
                     error_type="infra",
                     metrics={"failure_reason": "401 Invalid token"})
    out = RequirementStage().transition(State(mode="new"), {"agent_result": ar})
    assert out.last_error is not None
    assert out.last_error.error_type == "infra"  # was: "fatal" (bug)
    assert out.last_error.stage_name == "requirement"
    assert "401 Invalid token" in out.last_error.message


def test_requirement_transition_infra_transient_propagates():
    """fail-open：infra_transient（连接重置）也透传 error_type（不降级 fatal）。"""
    from ascendc_devkit.orchestration.stages.requirement import RequirementStage
    ar = AgentResult(
        agent_name="requirement-analyst", status="fatal",
        error_type="infra_transient",
        metrics={"failure_reason": "Remote end closed connection without response"})
    out = RequirementStage().transition(State(mode="new"), {"agent_result": ar})
    assert out.last_error is not None
    assert out.last_error.error_type == "infra_transient"  # was: "fatal" (bug)
    assert out.last_error.stage_name == "requirement"


def test_requirement_transition_logic_failure_keeps_status():
    """P116 Change D regression: non-infra logic failure → error_type=status (unchanged)."""
    from ascendc_devkit.orchestration.stages.requirement import RequirementStage
    ar = AgentResult(agent_name="requirement-analyst", status="fatal",
                     error_type=None)  # logic failure
    out = RequirementStage().transition(State(mode="new"), {"agent_result": ar})
    assert out.last_error is not None
    assert out.last_error.error_type == "fatal"  # status fallback (not infra)


# —— P116 Change C: infra partial not absorbed by P8 into ok ——


def test_infra_partial_not_absorbed_by_p8(monkeypatch):
    _no_sleep(monkeypatch)
    """P116 Change C: infra partial + contract satisfied → NOT absorbed into 'ok'.

    infra is unrecoverable + half-crashed artifacts untrustworthy; P8's
    slow-but-successful salvage must NOT apply. Pre-Change-C: P8 flipped
    stage_status to 'ok' → stage_complete event mis-reported status='ok' (Change
    B's _stage_failed was already set above, so node_status stayed 'failed', but
    stage_status honesty + defense-in-depth require the gate).
    """
    from ascendc_devkit.orchestration.base import Stage
    from ascendc_devkit.orchestration.kernel.action import SpawnAgent
    from ascendc_devkit.domain.contract import StageIOContract

    class _PartialInfraStage(Stage):
        name = "partial-infra"
        default_max_iterations = 1
        fail_strategy = "continue"

        def input_contract(self):
            return StageIOContract(requires=[])

        def output_contract(self):
            return StageIOContract(provides=["generated_sources"])

        def actions(self, state, iteration=1):
            return [SpawnAgent(agent_name="x", prompt="p", context={})]

        def transition(self, state, result):
            return state.with_updates(generated_sources={"f.cpp": "// partial"})

    captured = {}

    def cb(event, stage_name, data):
        if event == "stage_complete":
            captured["status"] = data["status"]

    backend = _CountingBackend(status="partial", error_type="infra",
                               failure_reason="401 Invalid token")
    runner = Runner(agent_backend=backend, progress_callback=cb)
    state = runner.run_stage(State(mode="new"), _PartialInfraStage())
    # Change C: infra partial must NOT be P8-absorbed → status stays partial (not 'ok')
    assert captured.get("status") != "ok", \
        "infra partial must not be P8-absorbed into 'ok' (Change C)"
    # Change B: infra → _stage_failed set regardless of fail_strategy
    assert getattr(state, "_stage_failed", None) is not None


# —— P116 ①b: continue stage + infra → node_status='failed' (resume 不跳过) ——


def test_continue_stage_infra_node_marked_failed(monkeypatch):
    """P116 ①b: continue stage + infra → graph_executor 标 node_status='failed'
    (not 'completed') → resume 不跳过。这是 P116 的核心价值。

    Pre-P116: requirement (continue) + 401 → node_status 'completed' → resume
    skip → downstream abort (run 20260725-152037 abeb6c). Change B (runner infra
    halt 无视 fail_strategy) → _stage_failed → graph_executor node_status
    'failed' → _group_status 传播到根 → dispatcher resume 不误判 all_done → 重跑。
    Mirrors test_graph_executor.py TestHaltMarksNodeFailed (P35) but for the
    P116 infra-on-continue path (no fail_strategy=halt declaration needed).
    """
    _no_sleep(monkeypatch)
    from ascendc_devkit.capabilities.agent.backend import AgentBackend, AgentResult
    from ascendc_devkit.orchestration.graph_executor import GraphExecutor
    from ascendc_devkit.orchestration.node import AtomicStage, SequentialGroup
    from ascendc_devkit.orchestration.kernel.action import SpawnAgent

    class _ContinueInfraStage(Stage):
        name = "continue-infra-stage"
        default_max_iterations = 1
        fail_strategy = "continue"

        def input_contract(self):
            return StageIOContract(requires=[])

        def output_contract(self):
            return StageIOContract(provides=[])

        def actions(self, state, iteration=1):
            return [SpawnAgent(agent_name="x", prompt="p", context={})]

    class _InfraBackend(AgentBackend):
        def spawn(self, agent_name, prompt, context, skills=None, model=None,
                  working_dir=None, repo_baseline=None, repo_root=None,
                  stage_name="", branch_label="", resume_session_id=None,
            resume_prompt=None,
                  primary_skill=None, deadline_monotonic=None):
            return AgentResult(agent_name="x", status="fatal", error_type="infra",
                               metrics={"failure_reason": "401 Invalid token"})

    root = SequentialGroup(name="pipeline", children=[
        AtomicStage(_ContinueInfraStage())])
    s = State.empty().with_updates(non_interactive=True, user_max_iterations=1)
    out = GraphExecutor(runner=Runner(agent_backend=_InfraBackend())).execute(root, s)
    assert out.node_status.get("pipeline/continue-infra-stage") == "failed", \
        "P116: continue stage + infra must mark node_status 'failed' (was: completed)"
    assert out.node_status.get("pipeline") == "failed", \
        "infra halt must propagate to root via _group_status (resume authority)"
