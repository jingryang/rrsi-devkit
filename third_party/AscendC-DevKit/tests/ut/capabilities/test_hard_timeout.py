"""UT: backend 硬墙（deadline_monotonic）— StubBackend 层。

S1a 协议层验证：spawn(deadline_monotonic) 到点必返回 aborted='hard_timeout' 且不留
半个产物；未到点 / None 时原行为不变。真实 backend（claude B' / opencode）的硬墙
见 ST（heavy_llm，S5 用户确认，§3.11）。

对应 L3 决策 D3（默认硬）/ D4（aborted 字段）；L4 `03-impl-s1a-backend-hard-wall.md`。
"""
import time

from ascendc_devkit.capabilities.agent.stub_backend import StubBackend
from ascendc_devkit.capabilities.agent.backend import AgentResult


def test_deadline_passed_returns_aborted(tmp_path):
    """deadline 已过 → 立即 aborted='hard_timeout'，status='fatal'。"""
    stub = StubBackend(canned_responses=[
        AgentResult(agent_name="a", status="ok", artifacts={"f.txt": "data"})])
    result = stub.spawn("a", "p", {},
                        deadline_monotonic=time.monotonic() - 1.0,
                        working_dir=tmp_path)
    assert result.aborted == "hard_timeout"
    assert result.status == "fatal"


def test_deadline_passed_leaves_no_artifacts(tmp_path):
    """硬终止不留半个产物（构造性保证）：canned 的 artifacts 不落盘、result.artifacts 为空。"""
    stub = StubBackend(canned_responses=[
        AgentResult(agent_name="a", status="ok", artifacts={"f.txt": "data"})])
    result = stub.spawn("a", "p", {},
                        deadline_monotonic=time.monotonic() - 1.0,
                        working_dir=tmp_path)
    assert result.artifacts == {}
    assert not (tmp_path / "f.txt").exists()


def test_no_deadline_returns_canned():
    """deadline_monotonic=None → 原 canned 行为不变，aborted=None。"""
    stub = StubBackend(canned_responses=[
        AgentResult(agent_name="a", status="ok")])
    result = stub.spawn("a", "p", {}, deadline_monotonic=None)
    assert result.aborted is None
    assert result.status == "ok"


def test_deadline_future_returns_canned():
    """deadline 在未来 → 未到点，原 canned 行为，aborted=None。"""
    stub = StubBackend(canned_responses=[
        AgentResult(agent_name="a", status="ok")])
    result = stub.spawn("a", "p", {},
                        deadline_monotonic=time.monotonic() + 100.0)
    assert result.aborted is None
    assert result.status == "ok"


def test_spawn_calls_record_deadline():
    """deadline_monotonic 被记录进 spawn_calls（可观测 / 调试）。"""
    stub = StubBackend()
    dl = time.monotonic() + 50.0
    stub.spawn("a", "p", {}, deadline_monotonic=dl)
    assert stub.spawn_calls[-1]["deadline_monotonic"] == dl


def test_opencode_deadline_passed_returns_aborted_no_serve(tmp_path):
    """opencode: deadline 已过 → 不启动 serve，直接 aborted（不烧 spawn 预算）。"""
    from ascendc_devkit.capabilities.agent.opencode_backend import OpenCodeBackend
    b = OpenCodeBackend(working_dir=tmp_path)
    result = b.spawn("a", "p", {}, deadline_monotonic=time.monotonic() - 1.0)
    assert result.aborted == "hard_timeout"
    assert result.status == "fatal"
    assert result.artifacts == {}


def test_claude_spawn_hard_wall_aborts_overrun(monkeypatch, tmp_path):
    """S1b: claude SDK spawn 层 anyio.fail_after 硬墙 —— _spawn 超过 deadline 时，
    spawn 到点返回 aborted='hard_timeout'，且不等满慢路径（证明是硬墙 cancel，不是
    慢路径自然结束）。"""
    import asyncio
    from ascendc_devkit.capabilities.agent.sdk_backend import SDKBackend

    b = SDKBackend(interactive=False, working_dir=tmp_path,
                   on_decision="default", decision_workspace=tmp_path)

    async def slow_spawn(*a, **kw):
        # 远超 deadline：若硬墙失效，spawn 会阻塞到这 30s sleep 跑完。
        await asyncio.sleep(30)
        return AgentResult(agent_name="coder", status="ok")

    monkeypatch.setattr(b, "_spawn", slow_spawn)

    dl = time.monotonic() + 0.2
    start = time.monotonic()
    result = b.spawn("coder", "code it", {}, deadline_monotonic=dl)
    elapsed = time.monotonic() - start

    assert result.aborted == "hard_timeout"
    assert result.status == "fatal"
    # 硬墙生效：0.2s 到点即返回，远未等满 30s（给 anyio cancel + teardown 余量）。
    assert elapsed < 5.0, f"hard wall did not fire; elapsed={elapsed:.1f}s"


def test_claude_spawn_no_deadline_runs_spawn(monkeypatch, tmp_path):
    """S1b: deadline_monotonic=None → 不套 fail_after，_spawn 正常跑完，aborted=None。"""
    from ascendc_devkit.capabilities.agent.sdk_backend import SDKBackend

    b = SDKBackend(interactive=False, working_dir=tmp_path,
                   on_decision="default", decision_workspace=tmp_path)

    async def fast_spawn(*a, **kw):
        return AgentResult(agent_name="coder", status="ok", artifacts={"x.txt": "1"})

    monkeypatch.setattr(b, "_spawn", fast_spawn)

    result = b.spawn("coder", "code it", {}, deadline_monotonic=None)
    assert result.aborted is None
    assert result.status == "ok"


def test_claude_spawn_deadline_in_future_runs_to_completion(monkeypatch, tmp_path):
    """S1b: deadline 在未来且 _spawn 快速完成 → 未到点，正常返回，aborted=None。"""
    from ascendc_devkit.capabilities.agent.sdk_backend import SDKBackend

    b = SDKBackend(interactive=False, working_dir=tmp_path,
                   on_decision="default", decision_workspace=tmp_path)

    async def fast_spawn(*a, **kw):
        return AgentResult(agent_name="coder", status="ok")

    monkeypatch.setattr(b, "_spawn", fast_spawn)

    result = b.spawn("coder", "code it", {},
                     deadline_monotonic=time.monotonic() + 100.0)
    assert result.aborted is None
    assert result.status == "ok"


def test_runner_passes_min_deadline_to_spawn():
    """runner 把 min(workflow, stage) deadline 传给 spawn(deadline_monotonic)。"""
    from ascendc_devkit.orchestration.kernel.runner import Runner
    from ascendc_devkit.orchestration.kernel.action import SpawnAgent
    stub = StubBackend()
    runner = Runner(agent_backend=stub)
    runner._current_stage_name = "test"
    wf_dl = time.monotonic() + 100.0
    runner._workflow_deadline = wf_dl
    runner._stage_deadline = time.monotonic() + 200.0  # workflow 更紧 → min=wf_dl
    runner._execute_spawn_agent(
        SpawnAgent(agent_name="ascendc-coder", prompt="p"), result={})
    assert stub.spawn_calls[-1]["deadline_monotonic"] == wf_dl


def test_runner_no_deadline_when_unset():
    """无 deadline 时传 None（不影响原行为）。"""
    from ascendc_devkit.orchestration.kernel.runner import Runner
    from ascendc_devkit.orchestration.kernel.action import SpawnAgent
    stub = StubBackend()
    runner = Runner(agent_backend=stub)
    runner._current_stage_name = "test"
    runner._execute_spawn_agent(
        SpawnAgent(agent_name="ascendc-coder", prompt="p"), result={})
    assert stub.spawn_calls[-1]["deadline_monotonic"] is None
