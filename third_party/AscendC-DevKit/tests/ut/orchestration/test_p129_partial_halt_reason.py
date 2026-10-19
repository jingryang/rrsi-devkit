"""P129 (trial-20260730): partial/failed halt 必须带可读 reason。

根因：runner 组装 stage_status 时 own_error 只从**同 stage** 的 last_error 取；
agent 以 partial/fatal 收场但 stage 未记录自己的 last_error 时，真实原因只活在
agent_result 的 aborted / failure_reason / error_type，从不回填 last_error →
下游 halt reason（graph_executor 读 state.last_error）为空（只见 "halt" 不见
"为何 halt"）。

修复（与 P125 同思路——把 agent 权威失败信号翻译进下游消费的通道）：stage 非 ok
且无 own_error 时，从 agent_result 合成 last_error（name-scoped 到本 stage）。
"""
from __future__ import annotations

from unittest import mock as umock

from ascendc_devkit.orchestration.base import Stage
from ascendc_devkit.orchestration.kernel.runner import Runner
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.kernel.action import SpawnAgent
from ascendc_devkit.domain.contract import StageIOContract
from ascendc_devkit.capabilities.agent.backend import AgentBackend, AgentResult


class _AbortBackend(AgentBackend):
    """Returns a fixed AgentResult carrying aborted / failure_reason / error_type."""

    def __init__(self, status="fatal", error_type=None, failure_reason="",
                 aborted=None):
        self._status = status
        self._error_type = error_type
        self._fr = failure_reason
        self._aborted = aborted

    def spawn(self, agent_name, prompt, context, skills=None, model=None,
              working_dir=None, repo_baseline=None, repo_root=None,
              stage_name="", branch_label="", resume_session_id=None,
        resume_prompt=None,
              primary_skill=None, deadline_monotonic: float | None = None):
        return AgentResult(
            agent_name=agent_name, status=self._status,
            error_type=self._error_type, aborted=self._aborted,
            metrics=({"failure_reason": self._fr} if self._fr else None))


class _HaltStage(Stage):
    """fail_strategy='halt' → 首次失败即收尾（单 spawn，无迭代噪声）。"""
    name = "halt-stage"
    default_max_iterations = 3
    fail_strategy = "halt"

    def input_contract(self):
        return StageIOContract(requires=[])

    def output_contract(self):
        return StageIOContract(provides=[])  # 无 contract → status 只来自 agent

    def actions(self, state, iteration=1):
        return [SpawnAgent(agent_name="x", prompt="p", context={})]


def _run(backend):
    # P129 的意图是验证 aborted/infra 失败 → stage 合成可读 last_error；不关心
    # infra_backoff（P131c）对 transient infra abort 的真实退避 sleep（20s→40s→80s
    # 共 ~140s，aborted=turn_stall 会触发）。mock sleep 让退避快速走完重试（3 次）→
    # halt + 合成 last_error，避免真实 140s 拖慢测试（§3.4：问题必修，非卡死是慢）。
    with umock.patch("ascendc_devkit.orchestration.kernel.runner.time.sleep"):
        return Runner(agent_backend=backend).run_stage(State(mode="new"), _HaltStage())


def test_aborted_halt_synthesizes_reason():
    """aborted 置位的 halt → last_error 合成，message 含中断类型 + failure_reason。"""
    backend = _AbortBackend(status="fatal", error_type="infra",
                            aborted="turn_stall",
                            failure_reason="no new turn for 305s > turn_stall 300s")
    state = _run(backend)
    assert state.last_error is not None
    assert state.last_error.stage_name == "halt-stage"
    assert "turn_stall" in state.last_error.message
    assert "305s" in state.last_error.message
    assert state.last_error.error_type == "infra"


def test_failure_reason_only_synthesizes_reason():
    """无 aborted、仅 failure_reason 的失败 → 仍合成可读 last_error。"""
    backend = _AbortBackend(status="fatal", error_type=None,
                            failure_reason="schema mismatch: field foo")
    state = _run(backend)
    assert state.last_error is not None
    assert "schema mismatch" in state.last_error.message
    # 无 error_type → 落 unclassified，不误标 infra
    assert state.last_error.error_type == "unclassified"


def test_no_signal_no_fabricated_reason():
    """既无 aborted 又无 failure_reason → 不凭空造 last_error（不制造噪声）。"""
    backend = _AbortBackend(status="fatal", error_type=None,
                            failure_reason="", aborted=None)
    state = _run(backend)
    assert state.last_error is None


def test_ok_agent_no_synthesis():
    """agent ok（stage_status ok）→ 不合成 last_error。"""
    backend = _AbortBackend(status="ok", error_type=None,
                            failure_reason="", aborted=None)
    state = _run(backend)
    assert state.last_error is None
