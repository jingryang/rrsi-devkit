"""P131c (trial-20260730): 跨-run 退避重跑 —— 瞬态 infra abort 重采样新网关窗口。

根因：turn_stall/keepalive/hard_timeout 看门狗杀掉一个「活着但停滞」的 spawn
（AgentResult.aborted 置位），P125 归为 infra，P116 立即 halt 整个 run。但这类
abort 是**瞬态**的（网关一时慢/拒，换个窗口常常就好——用户判断「不如早重试」），
与**永久** infra（401/config，aborted 为空）不同。本特性：aborted 置位的瞬态
infra → 框架自身 sleep 有界退避后**重跑本 iteration**（新 spawn=新网关窗口），
不依赖外部 harbor；预算（重试数 + 累计退避 + stage deadline）耗尽才落回 P116 halt。

与 §1.10 一致：判据用业务语义（aborted=「杀掉一个活着的 spawn」瞬态）而非机制特征；
永久 infra 不置 aborted → 直落 P116 立即 halt（换窗口也修不好坏凭证）。
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


class _FlakyBackend(AgentBackend):
    """前 ``fail_times`` 次 spawn 返回瞬态 infra abort，之后返回 ok。计数 spawns。"""

    def __init__(self, fail_times: int):
        self._fail_times = fail_times
        self.spawns = 0

    def spawn(self, agent_name, prompt, context, skills=None, model=None,
              working_dir=None, repo_baseline=None, repo_root=None,
              stage_name="", branch_label="", resume_session_id=None,
        resume_prompt=None,
              primary_skill=None, deadline_monotonic: float | None = None):
        self.spawns += 1
        if self.spawns <= self._fail_times:
            return AgentResult(
                agent_name=agent_name, status="fatal",
                error_type="infra", aborted="hard_timeout",
                metrics={"failure_reason": "no new turn for 605s > turn_stall 600s"})
        return AgentResult(agent_name=agent_name, status="ok")


class _OneShotStage(Stage):
    """单 iteration、无契约（status 只来自 agent）、无安全网 → ceiling==1。"""
    name = "flaky-stage"
    default_max_iterations = 1
    fail_strategy = "continue"           # P116：infra 不看 fail_strategy 仍 halt
    needs_iteration_safety_net = False   # 强制 ceiling = stage_budget = 1

    def input_contract(self):
        return StageIOContract(requires=[])

    def output_contract(self):
        return StageIOContract(provides=[])

    def actions(self, state, iteration=1):
        return [SpawnAgent(agent_name="x", prompt="p", context={})]


def _run(backend):
    return Runner(agent_backend=backend).run_stage(
        State(mode="new", non_interactive=True), _OneShotStage())


def _no_sleep(monkeypatch):
    monkeypatch.setattr(runner_mod.time, "sleep", lambda *_a, **_k: None)


def test_transient_abort_resumes_then_succeeds(monkeypatch):
    """2 次瞬态 abort 后 ok → 框架重采样 3 次(2 abort + 1 ok)，stage 不 halt。"""
    _no_sleep(monkeypatch)
    backend = _FlakyBackend(fail_times=2)
    state = _run(backend)
    assert backend.spawns == 3, "应重跑到第 3 次 ok（默认 cap=4 够用）"
    assert getattr(state, "_stage_failed", None) is None, "最终 ok → 不 halt"


def test_persistent_abort_exhausts_budget_then_halts(monkeypatch):
    """abort 不停 → 退避预算(默认 cap=4)耗尽后落回 P116 halt。"""
    _no_sleep(monkeypatch)
    backend = _FlakyBackend(fail_times=99)
    state = _run(backend)
    # 初始 spawn + cap 次重试 = 1 + 4 = 5；不再无限重试。
    assert backend.spawns == 5, "初始 + cap(4) 次重试后停止"
    assert getattr(state, "_stage_failed", None) is not None, "耗尽 → P116 halt"
    assert state.last_error is not None
    assert state.last_error.error_type == "infra"


def test_backoff_bounded_by_config(monkeypatch):
    """cap 由 infra_backoff() 配置驱动：置 cap=1 → 只重试 1 次(总 2 spawn)。"""
    _no_sleep(monkeypatch)
    import ascendc_devkit.orchestration.runtime_config as rc
    monkeypatch.setattr(
        rc, "infra_backoff",
        lambda: {"max_retries": 1, "backoff_base_s": 5.0,
                 "backoff_factor": 2.0, "backoff_max_total_s": 600.0})
    backend = _FlakyBackend(fail_times=99)
    state = _run(backend)
    assert backend.spawns == 2, "cap=1 → 初始 + 1 次重试"
    assert getattr(state, "_stage_failed", None) is not None


class _TeardownStage(_OneShotStage):
    """带 teardown hook 的 stage：记录每次 hard-kill 的 interrupt_reason。"""
    name = "flaky-teardown-stage"

    def __init__(self):
        self.teardowns: list[str] = []

    def teardown(self, state, *, interrupt_reason):
        self.teardowns.append(interrupt_reason)
        return state


def test_teardown_skipped_when_loop_resumes(monkeypatch):
    """§step-98-B（docs/plan/precision-teardown-turnstall-mismatch/）：teardown 是
    循环真退出的 finally 钩子——abort 后若 infra-retry 将续跑（resume 同一
    session），**不得触发 teardown/rollback**（99c4c0 实证：kill→rollback→resume
    =「记忆 vs 代码」发散，agent 工作被系统性蒸发）。

    2 次 abort + 1 次 ok：全程循环未从 abort 退出 → teardown 0 次。"""
    _no_sleep(monkeypatch)
    backend = _FlakyBackend(fail_times=2)
    stage = _TeardownStage()
    Runner(agent_backend=backend).run_stage(
        State(mode="new", non_interactive=True), stage)
    assert stage.teardowns == [], (
        "将 resume 的 abort 不得触发 teardown——树必须原样保留（记忆==树）")
    assert backend.spawns == 3


def test_teardown_fires_once_at_terminal_exhaustion(monkeypatch):
    """§step-98-B：退避预算耗尽 = 循环真退出 → teardown（rollback 语义）恰一次，
    在**最终** abort 上（不在中途每次 kill 上）。"""
    _no_sleep(monkeypatch)
    backend = _FlakyBackend(fail_times=99)
    stage = _TeardownStage()
    Runner(agent_backend=backend).run_stage(
        State(mode="new", non_interactive=True), stage)
    assert stage.teardowns == ["hard_timeout"], (
        "只应在循环退出（预算耗尽）时的最终 abort 上 teardown 一次")


def test_teardown_not_called_on_timeout_raise_after_abort(monkeypatch):
    """§step-98-B 异常出口：backoff 通过后 _check_timeout 抛出（deadline 恰在
    退避后到）——异常冲出循环、terminal 分支不执行、teardown 不触发、树保留
    （resume 语义：记忆==树；退出清洁由 converge 自身 checkout best 兜底）。"""
    _no_sleep(monkeypatch)
    calls = {"n": 0}
    orig = Runner._check_timeout

    def _raise_on_second(self, stage_name):
        calls["n"] += 1
        if calls["n"] == 2:
            raise TimeoutError("stage deadline")
        return orig(self, stage_name)

    monkeypatch.setattr(Runner, "_check_timeout", _raise_on_second)
    backend = _FlakyBackend(fail_times=99)
    stage = _TeardownStage()
    with pytest.raises(TimeoutError):
        Runner(agent_backend=backend).run_stage(
            State(mode="new", non_interactive=True), stage)
    assert stage.teardowns == [], "异常出口不得触发 teardown（树保留给 resume）"


class _ConnResetBackend(AgentBackend):
    """前 ``fail_times`` 次 spawn 返回连接重置（infra_transient，**无 aborted**），
    之后 ok —— 正是 batch grid_sampler_3d 的「Remote end closed connection without
    response」失败模式（旧实现掉夹缝直接 halt，新实现应走有界重试）。"""

    def __init__(self, fail_times: int):
        self._fail_times = fail_times
        self.spawns = 0

    def spawn(self, agent_name, prompt, context, skills=None, model=None,
              working_dir=None, repo_baseline=None, repo_root=None,
              stage_name="", branch_label="", resume_session_id=None,
        resume_prompt=None,
              primary_skill=None, deadline_monotonic: float | None = None):
        self.spawns += 1
        if self.spawns <= self._fail_times:
            return AgentResult(
                agent_name=agent_name, status="fatal",
                error_type="infra_transient",
                metrics={"failure_reason": "Remote end closed connection without response"})
        return AgentResult(agent_name=agent_name, status="ok")


def test_connection_reset_infra_transient_retries_then_succeeds(monkeypatch):
    """连接重置（infra_transient，无 aborted）→ 有界重试后 ok，stage 不 halt。
    （P1 根因回归：旧实现因 aborted=None 掉夹缝 → fail_strategy=halt 无重试。）"""
    _no_sleep(monkeypatch)
    backend = _ConnResetBackend(fail_times=2)
    state = _run(backend)
    assert backend.spawns == 3, "连接重置应重采样到第 3 次 ok（默认 cap=4 够用）"
    assert getattr(state, "_stage_failed", None) is None, "最终 ok → 不 halt"


def test_connection_reset_does_not_teardown(monkeypatch):
    """连接重置（infra_transient，无 aborted）→ 有界重试**不**触发 teardown（spawn
    没写 op_dir，无可回滚的半写状态）。teardown 仅 aborted（被杀活 spawn）触发。"""
    _no_sleep(monkeypatch)
    backend = _ConnResetBackend(fail_times=2)
    stage = _TeardownStage()
    Runner(agent_backend=backend).run_stage(
        State(mode="new", non_interactive=True), stage)
    assert stage.teardowns == [], (
        "连接重置不应触发 teardown（无 op_dir 半写状态可回滚）")
    assert backend.spawns == 3


# ── P9: 并行批次 infra 毒化整批 ─────────────────────────────────────────────
# runner._execute_actions 现在支持一次迭代多个 SpawnAgent（codegen A5 VF 预验证）。
# 批内**任何** infra 失败成员（aborted / infra / infra_transient）都应毒化整批走
# P131c 有界退避重跑——不能因为该成员恰好不是「最先完成者」（last_agent）就被静默
# 丢弃（P9 review：旧实现把 abort 扫描写成死代码，语义随完成顺序竞态）。


class _BatchStage(_OneShotStage):
    """每 iteration 派发 2 个 SpawnAgent（p1 干净先完成、p2 为毒化成员）。"""
    name = "parallel-batch-stage"

    def actions(self, state, iteration=1):
        return [SpawnAgent(agent_name="x", prompt="p1", context={}),
                SpawnAgent(agent_name="x", prompt="p2", context={})]


class _BatchTeardownStage(_BatchStage):
    """记录每次 hard-kill 的 interrupt_reason（P131c×D5）。"""
    def __init__(self):
        self.teardowns: list[str] = []

    def teardown(self, state, *, interrupt_reason):
        self.teardowns.append(interrupt_reason)
        return state


class _BatchAbortBackend(AgentBackend):
    """首个批次的 p2 返回 hard-abort，且**刻意后完成**（sleep 拖后）→
    last_agent（最先完成者）是干净的 p1。修复前此成员被静默丢弃；修复后毒化整批。"""

    def __init__(self):
        self.spawns = 0
        self._p2_seen = 0

    def spawn(self, agent_name, prompt, context, skills=None, model=None,
              working_dir=None, repo_baseline=None, repo_root=None,
              stage_name="", branch_label="", resume_session_id=None,
        resume_prompt=None,
              primary_skill=None, deadline_monotonic: float | None = None):
        self.spawns += 1
        if "p2" in prompt:
            self._p2_seen += 1
            if self._p2_seen == 1:
                import time
                time.sleep(0.1)  # 后完成 → 批内首个完成者是干净的 p1
                return AgentResult(
                    agent_name=agent_name, status="fatal",
                    error_type="infra", aborted="hard_timeout",
                    metrics={"failure_reason": "hard wall kill"})
        return AgentResult(agent_name=agent_name, status="ok")


class _BatchTransientBackend(AgentBackend):
    """首个批次的 p2 返回 infra_transient（无 aborted），后完成。"""

    def __init__(self):
        self.spawns = 0
        self._p2_seen = 0

    def spawn(self, agent_name, prompt, context, skills=None, model=None,
              working_dir=None, repo_baseline=None, repo_root=None,
              stage_name="", branch_label="", resume_session_id=None,
        resume_prompt=None,
              primary_skill=None, deadline_monotonic: float | None = None):
        self.spawns += 1
        if "p2" in prompt:
            self._p2_seen += 1
            if self._p2_seen == 1:
                import time
                time.sleep(0.1)
                return AgentResult(
                    agent_name=agent_name, status="fatal",
                    error_type="infra_transient",
                    metrics={"failure_reason": "Remote end closed connection"})
        return AgentResult(agent_name=agent_name, status="ok")


class _BatchPersistentTransientBackend(AgentBackend):
    """p2 **永远** infra_transient（无 aborted）→ 退避预算必耗尽 → P116 halt。"""

    def __init__(self):
        self.spawns = 0

    def spawn(self, agent_name, prompt, context, skills=None, model=None,
              working_dir=None, repo_baseline=None, repo_root=None,
              stage_name="", branch_label="", resume_session_id=None,
        resume_prompt=None,
              primary_skill=None, deadline_monotonic: float | None = None):
        self.spawns += 1
        if "p2" in prompt:
            return AgentResult(
                agent_name=agent_name, status="fatal",
                error_type="infra_transient",
                metrics={"failure_reason": "Remote end closed connection"})
        return AgentResult(agent_name=agent_name, status="ok")


def test_parallel_batch_aborted_member_poisons_batch(monkeypatch):
    """并行批：非最先完成成员的 hard-abort 毒化整批 → 只重跑失败成员（P2）。

    last_agent 是干净的 p1（先完成），修复前 abort 扫描是死代码、p2 被静默丢弃；
    P2 修复后不再整批重跑：干净成员 p1 的结果被保留（transition 提交 done），只
    重 spawn 失败成员 p2 → 总 spawn 3 次（首批 2 + 只重跑 p2 1），最终 transition
    结果含 p1（未被重跑、其产物被保留）。teardown 语义随 §step-98-B：只真退出
    触发，重试路径不回滚。"""
    _no_sleep(monkeypatch)
    backend = _BatchAbortBackend()
    stage = _BatchTeardownStage()
    _recorded: dict = {}

    class _RecordingTransition(_BatchTeardownStage):
        def transition(self, state, result):
            _recorded["result"] = result
            return state

    stage = _RecordingTransition()
    state = Runner(agent_backend=backend).run_stage(
        State(mode="new", non_interactive=True), stage)
    assert backend.spawns == 3, "首批(2) + 只重跑失败成员 p2(1)，干净成员 p1 不得重跑"
    # §step-98-B：teardown 只在循环**真退出**（terminal 分支）对 aborted 触发——
    # 重试分支绝不回滚（resume ⇒ 不动树；重采样前回滚曾系统性毁掉 agent 工作，
    # 99c4c0 w1/w3/w4 实证）。本用例重试后成功 → 循环正常 break → 无 teardown。
    assert stage.teardowns == [], "重试路径不得 teardown（step-98-B：resume 不动树）"
    assert getattr(state, "_stage_failed", None) is None, "重跑成功 → 不 halt"
    # P2 关键：干净成员 p1 的产物被保留进 transition 结果（未被整批重跑丢弃）
    prompts = {e.get("action").prompt for e in
               (_recorded["result"].get("agent_results") or [])}
    assert prompts == {"p1", "p2"}, "成功成员 p1 与重跑成功的 p2 都进入 transition 提交"


def test_parallel_batch_infra_transient_member_poisons_batch(monkeypatch):
    """并行批：非最先完成成员的 infra_transient（无 aborted）→ 只重跑失败成员、不
    teardown；干净成员 p1 结果保留。"""
    _no_sleep(monkeypatch)
    backend = _BatchTransientBackend()
    stage = _BatchTeardownStage()
    _recorded: dict = {}

    class _RecordingTransition(_BatchTeardownStage):
        def transition(self, state, result):
            _recorded["result"] = result
            return state

    stage = _RecordingTransition()
    state = Runner(agent_backend=backend).run_stage(
        State(mode="new", non_interactive=True), stage)
    assert backend.spawns == 3, "首批(2) + 只重跑失败成员 p2(1)"
    assert stage.teardowns == [], "infra_transient 无 aborted → 不 teardown"
    assert getattr(state, "_stage_failed", None) is None
    prompts = {e.get("action").prompt for e in
               (_recorded["result"].get("agent_results") or [])}
    assert prompts == {"p1", "p2"}, "干净成员结果保留 + 重跑结果一并提交"


def test_parallel_batch_persistent_infra_exhausts_then_halts_failed(monkeypatch):
    """并行批：失败成员持续 infra_transient → 只重跑该成员直至预算耗尽 → stage 标
    failed + halt；干净成员 p1 不再被整批重跑浪费预算。

    修复前按整批最差推导 failed、P129 合成 last_error 供 halt 诊断。P2 修复后重试
    只落在失败成员上 → spawn 数 = 初始批 2 + cap(4) 次单成员重跑 = 6（旧行为 5 批
    × 2 = 10）。"""
    _no_sleep(monkeypatch)
    backend = _BatchPersistentTransientBackend()
    state = Runner(agent_backend=backend).run_stage(
        State(mode="new", non_interactive=True), _BatchStage())
    assert backend.spawns == 6, "初始批(2) + cap(4) 次只重跑失败成员 = 6，干净成员不被反复重跑"
    assert getattr(state, "_stage_failed", None) is not None, "预算耗尽 → halt 传播"
    assert state.last_error is not None, "P129 从批内最差 agent 合成 halt 原因"
    assert state.last_error.error_type == "infra_transient"
