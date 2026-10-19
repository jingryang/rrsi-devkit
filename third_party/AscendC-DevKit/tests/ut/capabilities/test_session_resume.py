"""UT for Proposal #1: cross-run session resume via a durable sidecar.

The sidecar (<run>/agents/<agent>.session.json) is written by the backend at
session_id capture (mid-spawn, before any crash/kill) and deleted on clean
finish. A later resume reads it and re-enters the interrupted session instead
of a fresh spawn. This covers BOTH a graceful crash (429 captured → salvage →
transition) AND a hard kill (SIGKILL/OOM — no transition runs, but the sidecar
was already flushed to disk at capture).

These tests stub claude_agent_sdk.query and drive SDKBackend._spawn directly,
mirroring tests/ut/capabilities/test_capabilities.py::TestSDKBackendFailureHandling.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import mock as umock


# ---------------------------------------------------------------------------
# Pure helpers (no SDK)
# ---------------------------------------------------------------------------

def test_session_sidecar_path_no_branch(tmp_path):
    from ascendc_devkit.infra.workspace import session_sidecar_path
    assert (session_sidecar_path(tmp_path, "ascendc-coder")
            == tmp_path / "agents" / "ascendc-coder.session.json")


def test_session_sidecar_path_with_branch(tmp_path):
    from ascendc_devkit.infra.workspace import session_sidecar_path
    assert (session_sidecar_path(tmp_path, "coder", "tiling_a")
            == tmp_path / "agents" / "coder-tiling_a.session.json")


def test_session_sidecar_path_falsy_run_dir():
    from ascendc_devkit.infra.workspace import session_sidecar_path
    assert session_sidecar_path(None, "x") is None
    assert session_sidecar_path("", "x") is None


# —— review M2：sidecar 键含 stage_name（不同 stage 复用同 agent 时构造性分离）——

def test_session_sidecar_path_stage_disambiguates_tasks(tmp_path):
    """M2 (review 坐实): 键只含 (agent, branch_label) 时，不同 stage 复用同 agent
    会撞同一 sidecar 文件（如 ascendc-design-generator 被 general-design/dd-intake/
    template-division 复用；ascendc-coder 被 smoke/codegen 复用）——前任务被切留的
    sidecar 会被后一不同任务 auto-resume 误续。stage_name 并入键后构造性分离
    （§2.9）；同 stage 内键稳定（跨迭代/cross-run resume 行为不变）。"""
    from ascendc_devkit.infra.workspace import session_sidecar_path
    # 不同 stage、同 agent、同 branch → 键不同（不再撞文件）
    p1 = session_sidecar_path(tmp_path, "ascendc-design-generator",
                              branch_label="", stage_name="general-design")
    p2 = session_sidecar_path(tmp_path, "ascendc-design-generator",
                              branch_label="", stage_name="dd-intake")
    assert p1 != p2
    assert p1.name == "ascendc-design-generator-general-design.session.json"
    assert p2.name == "ascendc-design-generator-dd-intake.session.json"
    # 同 stage 同 agent 同 branch → 键稳定（resume 句柄复用）
    assert (session_sidecar_path(tmp_path, "ascendc-coder", "",
                                 stage_name="codegen")
            == session_sidecar_path(tmp_path, "ascendc-coder", "",
                                    stage_name="codegen"))
    # 无 stage（既有调用/旧测试路径）→ 键不变（向后兼容：测试直接 _spawn 不带
    # stage_name 时仍落 <agent>.session.json）
    assert session_sidecar_path(tmp_path, "ascendc-coder").name \
        == "ascendc-coder.session.json"


def test_session_sidecar_path_branch_isolates_parallel_batch(tmp_path):
    """同 stage 内并行批次成员靠 branch_label 构造性分离 sidecar 键。

    回归：A5 codegen 并行 VF 批次（4.C.6.VT.1 / 4.C.6.VT.2）此前不带
    branch_label，同 (agent, stage) 共享同一 sidecar 文件——后 spawn 读到
    先 spawn 刚写入的 sidecar 而误 auto-resume 其会话（4.C.6.VT.2 被
    VT.1 会话顶替，VT.2 空跑返回 COMPLETED 被标 done）。branch_label 折入
    键后各 VF 独立 sidecar，互不误续；同子阶段跨迭代 resume 键仍稳定。
    """
    from ascendc_devkit.infra.workspace import session_sidecar_path
    p1 = session_sidecar_path(tmp_path, "ascendc-vf-test-agent",
                              branch_label="4.C.6.VT.1", stage_name="codegen")
    p2 = session_sidecar_path(tmp_path, "ascendc-vf-test-agent",
                              branch_label="4.C.6.VT.2", stage_name="codegen")
    assert p1 != p2  # 并行兄弟不撞同一 sidecar 文件
    assert p1.name == "ascendc-vf-test-agent-codegen-4.C.6.VT.1.session.json"
    assert p2.name == "ascendc-vf-test-agent-codegen-4.C.6.VT.2.session.json"
    # 同子阶段键稳定（跨迭代/cross-run resume 不受影响）
    assert (session_sidecar_path(tmp_path, "ascendc-vf-test-agent",
                                 branch_label="4.C.6.VT.2", stage_name="codegen")
            == p2)


def test_is_session_gone_markers():
    from ascendc_devkit.capabilities.agent.sdk_backend import _is_session_gone
    assert _is_session_gone("Error: session not found")
    assert _is_session_gone("Session Expired")          # case-insensitive
    assert _is_session_gone("could not resume session abc")
    assert _is_session_gone("no such session")
    # Real claude_agent_sdk wording (observed via the stderr callback on a
    # bogus/expired resume): "conversation" is the SDK's term for a resumable
    # session. This is the case the heavy_llm ST surfaced — without it the
    # cross-run resume degrade never fires on a real gone/expired session.
    assert _is_session_gone(
        "No conversation found with session ID: 00000000-0000-0000-0000-000000000000")
    assert _is_session_gone("Conversation not found")
    assert not _is_session_gone("RuntimeError: boom")
    assert not _is_session_gone("API Error: Content block not found")
    assert not _is_session_gone("Usage limit reached")  # infra, not session-gone
    assert not _is_session_gone("")
    assert not _is_session_gone(None)


# ---------------------------------------------------------------------------
# SDKBackend sidecar lifecycle
# ---------------------------------------------------------------------------

def _backend(tmp_path, **overrides):
    from ascendc_devkit.capabilities.agent.sdk_backend import SDKBackend
    return SDKBackend(interactive=False, working_dir=tmp_path,
                      on_decision="default", decision_workspace=tmp_path,
                      **overrides)


def _patches(fake_query):
    return (
        umock.patch(
            "ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
            return_value={}),
        umock.patch("claude_agent_sdk.query", side_effect=fake_query),
    )


def test_sidecar_written_at_capture_and_preserved_on_crash(tmp_path):
    """session_id captured mid-spawn → sidecar flushed immediately. A crash
    (no clean finish) must NOT delete it — this is the hard-kill guarantee:
    the sidecar is on disk before the process can be killed."""
    (tmp_path / "agents").mkdir()

    async def fake_query(*args, **kwargs):
        # First event carries the session_id → captured → sidecar written.
        yield SimpleNamespace(session_id="S-CAP-1")
        # Agent wrote a file before crashing (salvageable → status partial).
        (tmp_path / "out.cpp").write_text("// half-written")
        raise RuntimeError("boom")

    with umock.patch(
        "ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
        return_value={}), umock.patch("claude_agent_sdk.query", side_effect=fake_query):
        b = _backend(tmp_path)
        result = asyncio.run(b._spawn("coder", "code it", {}))

    assert result.status == "partial"
    sc = tmp_path / "agents" / "coder.session.json"
    assert sc.exists(), "sidecar must survive a crash (hard-kill guarantee)"
    data = json.loads(sc.read_text())
    assert data["session_id"] == "S-CAP-1"
    assert data["agent_name"] == "coder"


def test_sidecar_cleared_on_clean_finish(tmp_path):
    """A clean finish (status ok) deletes the sidecar — a completed session is
    not resumable, and a later resume must not re-enter it."""
    (tmp_path / "agents").mkdir()
    # Pre-write a stale sidecar (as if a prior crash left it).
    sc = tmp_path / "agents" / "coder.session.json"
    sc.write_text(json.dumps({"agent_name": "coder", "session_id": "STALE"}))

    async def fake_query(*args, **kwargs):
        from claude_agent_sdk.types import AssistantMessage, TextBlock
        (tmp_path / "out.cpp").write_text("// done")
        yield AssistantMessage(content=[TextBlock(text="done")],
                               model="claude-sonnet-4-6")

    with umock.patch(
        "ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
        return_value={}), umock.patch("claude_agent_sdk.query", side_effect=fake_query):
        b = _backend(tmp_path)
        result = asyncio.run(b._spawn("coder", "code it", {}))

    assert result.status == "ok"
    assert not sc.exists(), "clean finish must clear the sidecar"


def test_resume_init_uses_resume_options(tmp_path):
    """resume_session_id → first query is issued with resume=<id> + the resume
    prompt (not the stage's fresh prompt)."""
    (tmp_path / "agents").mkdir()
    calls = []

    async def fake_query(*args, **kwargs):
        from claude_agent_sdk.types import AssistantMessage, TextBlock
        calls.append({"options": kwargs.get("options"),
                      "prompt": kwargs.get("prompt")})
        (tmp_path / "out.cpp").write_text("// done")
        yield AssistantMessage(content=[TextBlock(text="done")],
                               model="claude-sonnet-4-6")

    with umock.patch(
        "ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
        return_value={}), umock.patch("claude_agent_sdk.query", side_effect=fake_query):
        b = _backend(tmp_path)
        asyncio.run(b._spawn("coder", "code it", {},
                             resume_session_id="S-RES-1"))

    assert len(calls) == 1
    from ascendc_devkit.capabilities.agent.sdk_backend import _RESUME_PROMPT
    assert getattr(calls[0]["options"], "resume", None) == "S-RES-1"
    assert calls[0]["prompt"] == _RESUME_PROMPT


def test_resume_init_uses_resume_prompt_when_provided(tmp_path):
    """Part 3: resume_session_id + resume_prompt → first query carries the
    feedback prompt (not the default ``_RESUME_PROMPT``). 深修场景把上一轮失败
    反馈作为 resume 首条消息送达，agent 无需重读设计/代码。"""
    (tmp_path / "agents").mkdir()
    calls = []

    async def fake_query(*args, **kwargs):
        from claude_agent_sdk.types import AssistantMessage, TextBlock
        calls.append({"options": kwargs.get("options"),
                      "prompt": kwargs.get("prompt")})
        (tmp_path / "out.cpp").write_text("// done")
        yield AssistantMessage(content=[TextBlock(text="done")],
                               model="claude-sonnet-4-6")

    with umock.patch(
        "ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
        return_value={}), umock.patch("claude_agent_sdk.query", side_effect=fake_query):
        b = _backend(tmp_path)
        asyncio.run(b._spawn("coder", "code it", {},
                             resume_session_id="S-RES-1",
                             resume_prompt="上一轮 smoke 失败：aclnnInterpolate 缺失，"
                                           "请修正 CMake 注册并回验"))

    assert len(calls) == 1
    assert getattr(calls[0]["options"], "resume", None) == "S-RES-1"
    assert "aclnnInterpolate" in calls[0]["prompt"]
    assert "请修正 CMake" in calls[0]["prompt"]


def test_session_gone_degrades_to_fresh(tmp_path):
    """Resuming a gone/expired session (TTL lapsed) degrades to a fresh spawn
    inside the backend: second query has no resume, sidecar cleared, result ok.
    The stage never learns the resume failed — degrade is internal (§D2)."""
    (tmp_path / "agents").mkdir()
    calls = []

    async def fake_query(*args, **kwargs):
        from claude_agent_sdk.types import AssistantMessage, TextBlock
        calls.append({"options": kwargs.get("options")})
        if len(calls) == 1:
            raise RuntimeError("Error: session not found")
        (tmp_path / "out.cpp").write_text("// done")
        yield AssistantMessage(content=[TextBlock(text="done")],
                               model="claude-sonnet-4-6")

    with umock.patch(
        "ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
        return_value={}), umock.patch("claude_agent_sdk.query", side_effect=fake_query):
        b = _backend(tmp_path)
        result = asyncio.run(b._spawn("coder", "code it", {},
                                      resume_session_id="S-GONE"))

    assert len(calls) == 2
    assert getattr(calls[0]["options"], "resume", None) == "S-GONE"   # 1st = resume
    assert getattr(calls[1]["options"], "resume", None) in (None, "")  # 2nd = fresh
    assert result.status == "ok"
    assert not (tmp_path / "agents" / "coder.session.json").exists()


# ---------------------------------------------------------------------------
# step-57 (P80): 429 burst backoff-resume
# ---------------------------------------------------------------------------

def _backend_fast_backoff(tmp_path, **overrides):
    """SDKBackend with tiny backoff params so tests don't actually sleep long
    (asyncio.sleep is monkeypatched to a no-op anyway, but keep values sane)."""
    from ascendc_devkit.capabilities.agent.sdk_backend import SDKBackend
    kw = dict(interactive=False, working_dir=tmp_path, on_decision="default",
              decision_workspace=tmp_path, rate_limit_max_retries=3,
              rate_limit_backoff_base_s=1.0, rate_limit_backoff_factor=2.0,
              rate_limit_backoff_max_total_s=1000.0)
    kw.update(overrides)
    return SDKBackend(**kw)


def test_429_sleeps_then_resumes_same_session(tmp_path, monkeypatch):
    """A 429 crash → backend sleeps (backoff) → resumes the SAME session with
    '继续' → succeeds. The 429 must NOT be treated as a logic failure."""
    (tmp_path / "agents").mkdir()
    slept = []

    async def _fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr(
        "ascendc_devkit.capabilities.agent.sdk_backend.asyncio.sleep",
        _fake_sleep)

    calls = []

    async def fake_query(*args, **kwargs):
        from claude_agent_sdk.types import AssistantMessage, TextBlock
        calls.append({"options": kwargs.get("options"),
                      "prompt": kwargs.get("prompt")})
        # Always emit a session_id so resume is possible.
        yield SimpleNamespace(session_id="S-429")
        if len(calls) == 1:
            # First attempt: emit a ResultMessage carrying the 429 text, then
            # crash (mirrors the real proxy: result text set, then stream dies).
            yield SimpleNamespace(
                result="API Error: Request rejected (429) · Weekly/Monthly "
                       "Limit Exhausted")
            raise RuntimeError("stream aborted after 429")
        # Second attempt: clean success.
        (tmp_path / "out.cpp").write_text("// done after backoff")
        yield AssistantMessage(content=[TextBlock(text="done")],
                               model="claude-sonnet-4-6")

    with umock.patch(
        "ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
        return_value={}), umock.patch("claude_agent_sdk.query", side_effect=fake_query):
        b = _backend_fast_backoff(tmp_path)
        result = asyncio.run(b._spawn("coder", "code it", {}))

    from ascendc_devkit.capabilities.agent.sdk_backend import _RESUME_PROMPT
    assert result.status == "ok"
    assert len(calls) == 2, "must retry exactly once after the 429"
    assert slept == [1.0], "first backoff sleep = base_s (factor**0)"
    # 2nd call must be a resume of the SAME session with the continue nudge.
    assert getattr(calls[1]["options"], "resume", None) == "S-429"
    assert calls[1]["prompt"] == _RESUME_PROMPT


def test_thinking_error_resumes_immediately_same_session(tmp_path, monkeypatch):
    """A1.3（20260812 策略分离）：非 infra 服务端错误（APIError thinking 回传）→
    sdk backend 走立即 resume（策略 'resume'，不 sleep——避免误判空等），成功推进。"""
    (tmp_path / "agents").mkdir()
    slept = []

    async def _fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr(
        "ascendc_devkit.capabilities.agent.sdk_backend.asyncio.sleep",
        _fake_sleep)
    calls = []

    async def fake_query(*args, **kwargs):
        from claude_agent_sdk.types import AssistantMessage, TextBlock
        calls.append({"options": kwargs.get("options"),
                      "prompt": kwargs.get("prompt")})
        yield SimpleNamespace(session_id="S-THINK")
        if len(calls) == 1:
            yield SimpleNamespace(
                result="The `content[].thinking` in the thinking mode must be "
                       "passed back to the API. (request id: 20260811191716...)")
            raise RuntimeError("stream aborted after APIError")
        (tmp_path / "out.cpp").write_text("// done after resume")
        yield AssistantMessage(content=[TextBlock(text="done")],
                               model="claude-sonnet-4-6")

    with umock.patch(
        "ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
        return_value={}), umock.patch("claude_agent_sdk.query", side_effect=fake_query):
        b = _backend_fast_backoff(tmp_path)
        result = asyncio.run(b._spawn("coder", "code it", {}))

    from ascendc_devkit.capabilities.agent.sdk_backend import _RESUME_PROMPT
    assert result.status == "ok"
    assert len(calls) == 2, "must retry exactly once after the thinking APIError"
    assert slept == [], "策略 'resume' 立即续跑，不 sleep（不空等）"
    assert getattr(calls[1]["options"], "resume", None) == "S-THINK"
    assert calls[1]["prompt"] == _RESUME_PROMPT


def test_infra_message_error_no_backoff(tmp_path, monkeypatch):
    """A1.3: infra（不可重试 401）→ 不进 in-session backoff，只 query 一次即 halt
    （P116 infra 语义不变，对齐 opencode 侧 test_infra_message_error_no_backoff）。"""
    (tmp_path / "agents").mkdir()
    slept = []

    async def _fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr(
        "ascendc_devkit.capabilities.agent.sdk_backend.asyncio.sleep",
        _fake_sleep)
    calls = []

    async def fake_query(*args, **kwargs):
        calls.append(1)
        yield SimpleNamespace(session_id="S-401")
        yield SimpleNamespace(result="API Error: 401 Unauthorized")
        raise RuntimeError("stream aborted after 401")

    with umock.patch(
        "ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
        return_value={}), umock.patch("claude_agent_sdk.query", side_effect=fake_query):
        b = _backend_fast_backoff(tmp_path)
        result = asyncio.run(b._spawn("coder", "code it", {}))

    assert len(calls) == 1, "infra 不 backoff，只 query 一次"
    assert slept == [], "无 backoff sleep"
    assert result.status in ("fatal", "partial")


def test_429_backoff_exhausted_halts_with_reason(tmp_path, monkeypatch):
    """Persistent 429 (never clears) → backoff budget exhausted → halt. The
    failure_reason must name the exhausted-429 cause so nothing is silently
    swallowed (user requirement: retry info in the log/result)."""
    (tmp_path / "agents").mkdir()
    slept = []

    async def _fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr(
        "ascendc_devkit.capabilities.agent.sdk_backend.asyncio.sleep",
        _fake_sleep)

    calls = []

    async def fake_query(*args, **kwargs):
        calls.append(1)
        yield SimpleNamespace(session_id="S-429H")
        yield SimpleNamespace(
            result="Request rejected (429) · Weekly/Monthly Limit Exhausted")
        raise RuntimeError("stream aborted after 429")

    with umock.patch(
        "ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
        return_value={}), umock.patch("claude_agent_sdk.query", side_effect=fake_query):
        # max_retries=2 → attempts: initial + 2 resumes, then give up.
        b = _backend_fast_backoff(tmp_path, rate_limit_max_retries=2)
        result = asyncio.run(b._spawn("coder", "code it", {}))

    # Bounded: it must NOT loop forever. 1 initial + 2 backoff resumes = 3 calls.
    assert len(calls) == 3
    assert slept == [1.0, 2.0], "exponential backoff base=1, factor=2"
    assert result.status in ("fatal", "partial")
    reason = (result.metrics or {}).get("failure_reason", "")
    assert "429" in reason and "hard quota" in reason, reason


def test_429_total_time_cap_stops_retrying(tmp_path, monkeypatch):
    """The total-time cap is the hard-quota stop-loss: once cumulative sleep
    would exceed it, retrying stops even if max_retries is not yet reached."""
    (tmp_path / "agents").mkdir()
    slept = []

    async def _fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr(
        "ascendc_devkit.capabilities.agent.sdk_backend.asyncio.sleep",
        _fake_sleep)

    async def fake_query(*args, **kwargs):
        yield SimpleNamespace(session_id="S-CAP")
        yield SimpleNamespace(result="Request rejected (429) throttled")
        raise RuntimeError("boom 429")

    with umock.patch(
        "ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
        return_value={}), umock.patch("claude_agent_sdk.query", side_effect=fake_query):
        # base=10, factor=2, cap=25 → sleeps 10, then 15 (clamped from 20), then
        # cap reached → stop. High max_retries so the CAP is what stops it.
        b = _backend_fast_backoff(
            tmp_path, rate_limit_max_retries=100,
            rate_limit_backoff_base_s=10.0, rate_limit_backoff_factor=2.0,
            rate_limit_backoff_max_total_s=25.0)
        result = asyncio.run(b._spawn("coder", "code it", {}))

    assert slept == [10.0, 15.0], slept  # 2nd clamped to remaining budget
    assert result.status in ("fatal", "partial")



# ---------------------------------------------------------------------------
# 20260810 批根因修复 Part 1 — silent-cut 检测（thinking-only 终止 → 保留 sidecar）
# Part 2 — 后端自动 resume（sidecar 存在 → 自动续跑，对所有 agent）
# ---------------------------------------------------------------------------

def test_cut_detection_preserves_sidecar_and_marks_result(tmp_path):
    """Part 1: 末条 assistant 消息只有 thinking（无 text、无 tool_use）= 第三方
    网关静默切流（"一段吐字后突然中断"）。检测到 → 保留 sidecar（自动 resume 句柄）
    + result.cut=True。与自然结束（清 sidecar）区分。"""
    (tmp_path / "agents").mkdir()

    async def fake_query(*args, **kwargs):
        from claude_agent_sdk.types import AssistantMessage, ThinkingBlock
        yield SimpleNamespace(session_id="S-CUT-1")
        # thinking-only 终止 —— cut 签名
        yield AssistantMessage(content=[
            ThinkingBlock(thinking="(thinking...)", signature="sig")],
            model="claude-sonnet-4-6")

    with umock.patch(
        "ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
        return_value={}), umock.patch("claude_agent_sdk.query", side_effect=fake_query):
        b = _backend(tmp_path)
        result = asyncio.run(b._spawn("coder", "code it", {}))

    assert result.cut is True
    sc = tmp_path / "agents" / "coder.session.json"
    assert sc.exists(), "cut → sidecar 必须保留（Part 2 自动 resume 的句柄）"
    assert json.loads(sc.read_text())["session_id"] == "S-CUT-1"


def test_natural_end_clears_sidecar_no_cut(tmp_path):
    """Part 1: 自然结束（末条有 text）→ cut=False + sidecar 清除（照旧）。"""
    (tmp_path / "agents").mkdir()
    sc = tmp_path / "agents" / "coder.session.json"
    sc.write_text(json.dumps({"agent_name": "coder", "session_id": "STALE"}))

    async def fake_query(*args, **kwargs):
        from claude_agent_sdk.types import AssistantMessage, TextBlock
        yield SimpleNamespace(session_id="S-OK")
        (tmp_path / "out.cpp").write_text("// done")
        yield AssistantMessage(content=[TextBlock(text="done")],
                               model="claude-sonnet-4-6")

    with umock.patch(
        "ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
        return_value={}), umock.patch("claude_agent_sdk.query", side_effect=fake_query):
        b = _backend(tmp_path)
        result = asyncio.run(b._spawn("coder", "code it", {}))

    assert result.cut is False
    assert not sc.exists(), "自然结束必须清 sidecar（不 resume）"


def test_auto_resume_when_sidecar_present(tmp_path):
    """Part 2: stage 未显式传 resume_session_id 时，sidecar 存在 → 后端自动
    resume（程序化"继续"，_RESUME_PROMPT）。对所有 agent 生效（后端单点）。"""
    (tmp_path / "agents").mkdir()
    sc = tmp_path / "agents" / "coder.session.json"
    sc.write_text(json.dumps({"agent_name": "coder", "session_id": "S-AUTO"}))
    calls = []

    async def fake_query(*args, **kwargs):
        from claude_agent_sdk.types import AssistantMessage, TextBlock
        calls.append(kwargs)
        yield AssistantMessage(content=[TextBlock(text="done")],
                               model="claude-sonnet-4-6")

    with umock.patch(
        "ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
        return_value={}), umock.patch("claude_agent_sdk.query", side_effect=fake_query):
        b = _backend(tmp_path)
        asyncio.run(b._spawn("coder", "code it", {}))  # 不传 resume_session_id

    assert len(calls) == 1
    from ascendc_devkit.capabilities.agent.sdk_backend import _RESUME_PROMPT
    assert getattr(calls[0]["options"], "resume", None) == "S-AUTO"
    assert calls[0]["prompt"] == _RESUME_PROMPT


def test_auto_resume_not_cross_stage_for_same_agent(tmp_path):
    """M2 (review 坐实，spawn 级): sidecar 键含 stage_name——同一 agent 被不同
    stage 复用（如 ascendc-design-generator 用于 general-design/dd-intake、或
    ascendc-coder 用于 smoke/codegen）时，前一个任务被切留下的 sidecar 不得被
    后一不同任务误 resume（否则"继续"续跑前任务 session、本任务 prompt 不注入，
    跨任务静默污染）。不同 stage 的 sidecar → fresh spawn（不 resume）。"""
    (tmp_path / "agents").mkdir()
    # stage="smoke" 留下的 sidecar（同 agent "coder"）
    sc = tmp_path / "agents" / "coder-smoke.session.json"
    sc.write_text(json.dumps({"agent_name": "coder",
                              "session_id": "S-OTHER-STAGE", "stage_name": "smoke"}))
    calls = []

    async def fake_query(*args, **kwargs):
        from claude_agent_sdk.types import AssistantMessage, TextBlock
        calls.append(kwargs)
        yield AssistantMessage(content=[TextBlock(text="done")],
                               model="claude-sonnet-4-6")

    with umock.patch(
        "ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
        return_value={}), umock.patch("claude_agent_sdk.query", side_effect=fake_query):
        b = _backend(tmp_path)
        # stage="codegen" 的 spawn —— 键 = coder-codegen.session.json，读不到
        # coder-smoke 的 sidecar → fresh（无 resume）
        asyncio.run(b._spawn("coder", "build codegen op", {},
                             stage_name="codegen"))

    assert len(calls) == 1
    # 未 resume（fresh）：prompt 是原 prompt（非 _RESUME_PROMPT），resume 未设
    assert getattr(calls[0]["options"], "resume", None) is None
    from ascendc_devkit.capabilities.agent.sdk_backend import _RESUME_PROMPT
    assert calls[0]["prompt"] != _RESUME_PROMPT
    assert "build codegen op" in calls[0]["prompt"]


def test_explicit_resume_session_id_not_doubled(tmp_path):
    """Part 2: stage 显式传 resume_session_id（如 codegen）→ 用显式值，不叠加
    自动 resume（auto-resume 仅在未显式传时触发）。"""
    (tmp_path / "agents").mkdir()
    # 故意写一个与显式值不同的 sidecar，验证显式优先
    sc = tmp_path / "agents" / "coder.session.json"
    sc.write_text(json.dumps({"agent_name": "coder", "session_id": "S-SIDECAR"}))
    calls = []

    async def fake_query(*args, **kwargs):
        from claude_agent_sdk.types import AssistantMessage, TextBlock
        calls.append(kwargs)
        yield AssistantMessage(content=[TextBlock(text="done")],
                               model="claude-sonnet-4-6")

    with umock.patch(
        "ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
        return_value={}), umock.patch("claude_agent_sdk.query", side_effect=fake_query):
        b = _backend(tmp_path)
        asyncio.run(b._spawn("coder", "code it", {},
                             resume_session_id="S-EXPLICIT"))

    assert getattr(calls[0]["options"], "resume", None) == "S-EXPLICIT"


def test_no_sidecar_fresh_no_resume(tmp_path):
    """Part 2: 无 sidecar → fresh spawn（无 resume），prompt 用 stage 的。"""
    (tmp_path / "agents").mkdir()
    calls = []

    async def fake_query(*args, **kwargs):
        from claude_agent_sdk.types import AssistantMessage, TextBlock
        calls.append(kwargs)
        yield AssistantMessage(content=[TextBlock(text="done")],
                               model="claude-sonnet-4-6")

    with umock.patch(
        "ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
        return_value={}), umock.patch("claude_agent_sdk.query", side_effect=fake_query):
        b = _backend(tmp_path)
        asyncio.run(b._spawn("coder", "code it", {}))

    assert getattr(calls[0]["options"], "resume", None) is None


# ---------------------------------------------------------------------------
# 退化 spawn 设计（docs/plan/turn-stall-resume-escalation/）：resume 连续失败计数
# ---------------------------------------------------------------------------

def test_sidecar_write_carries_resume_fails(tmp_path):
    """_write_session_sidecar 显式带 resume_fails → 落盘该值（fresh 退化后
    新 session 写 0 的对称语义）。"""
    b = _backend(tmp_path)
    b._write_session_sidecar("coder", "", "S-1", stage_name="", resume_fails=2)
    data = json.loads((tmp_path / "agents" / "coder.session.json").read_text())
    assert data["session_id"] == "S-1"
    assert data["resume_fails"] == 2


def test_sidecar_default_resume_fails_zero(tmp_path):
    """缺省 resume_fails=0（fresh 新 session 的语义）。"""
    b = _backend(tmp_path)
    b._write_session_sidecar("coder", "", "S-1")
    data = json.loads((tmp_path / "agents" / "coder.session.json").read_text())
    assert data["resume_fails"] == 0


def test_bump_session_resume_fails_increments(tmp_path):
    """_bump_session_resume_fails 对既有 sidecar read-modify-write +1。"""
    b = _backend(tmp_path)
    b._write_session_sidecar("coder", "", "S-1", resume_fails=1)
    b._bump_session_resume_fails("coder", "", "")
    data = json.loads((tmp_path / "agents" / "coder.session.json").read_text())
    assert data["resume_fails"] == 2
    assert data["session_id"] == "S-1", "bump 只动计数，不动 session 句柄"


def test_bump_session_resume_fails_noop_without_sidecar(tmp_path):
    """无 sidecar（fresh 首跑 abort）→ bump 是 no-op，不新建文件、不崩。"""
    b = _backend(tmp_path)
    b._bump_session_resume_fails("coder", "", "")
    assert not (tmp_path / "agents" / "coder.session.json").exists()


def test_sdk_auto_resume_degrades_when_resume_fails_ge_threshold(tmp_path):
    """退化 spawn（sdk 对称）: sidecar resume_fails >= resume_attempts → 退化
    spawn（fresh：全量 prompt、无 resume option），不再续死 session。"""
    (tmp_path / "agents").mkdir()
    sc = tmp_path / "agents" / "coder.session.json"
    sc.write_text(json.dumps({"agent_name": "coder", "session_id": "S-DEAD",
                              "resume_fails": 3}))
    calls = []

    async def fake_query(*args, **kwargs):
        from claude_agent_sdk.types import AssistantMessage, TextBlock
        calls.append(kwargs)
        yield SimpleNamespace(session_id="S-FRESH")
        yield AssistantMessage(content=[TextBlock(text="done")],
                               model="claude-sonnet-4-6")

    with umock.patch(
        "ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
        return_value={}), umock.patch("claude_agent_sdk.query", side_effect=fake_query):
        b = _backend(tmp_path)
        asyncio.run(b._spawn("coder", "code it", {}))

    assert len(calls) == 1
    from ascendc_devkit.capabilities.agent.sdk_backend import _RESUME_PROMPT
    assert getattr(calls[0]["options"], "resume", None) is None, \
        "resume_fails 达阈 → 不得 resume 死 session"
    assert calls[0]["prompt"] != _RESUME_PROMPT, \
        "退化 spawn 必须用全量 stage prompt，不是 '继续'"


def test_sdk_hard_timeout_abort_bumps_resume_fails(tmp_path):
    """sdk 硬超时 abort（deadline 到点）→ sidecar resume_fails +1。覆盖 sidecar 自动
    resume 的会话（标志 _spawn_was_resume 跨出被 cancel 的 _spawn）。"""
    (tmp_path / "agents").mkdir()
    sc = tmp_path / "agents" / "coder.session.json"
    sc.write_text(json.dumps({"agent_name": "coder", "session_id": "S-AUTO",
                              "resume_fails": 1}))
    import time as _time
    hang = asyncio.Event()

    async def fake_query(*args, **kwargs):
        await hang.wait()  # 永不返回 → 卡住 → fail_after 超时
        yield  # 使之为 async generator（不可达——挂死在上面）

    with umock.patch(
        "ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
        return_value={}), umock.patch("claude_agent_sdk.query", side_effect=fake_query):
        b = _backend(tmp_path)
        res = b.spawn("coder", "code it", {},
                      deadline_monotonic=_time.monotonic() + 0.5)

    assert res.aborted == "hard_timeout"
    data = json.loads(sc.read_text())
    assert data["resume_fails"] == 2, "sdk 硬超时 abort（自动 resume）必须 bump"


def test_sdk_resume_preserves_counter_below_threshold(tmp_path):
    """sdk 未达阈 resume：mid-stream sidecar 写保留 resume_fails（不清零）。"""
    (tmp_path / "agents").mkdir()
    sc = tmp_path / "agents" / "coder.session.json"
    sc.write_text(json.dumps({"agent_name": "coder", "session_id": "S-AUTO",
                              "resume_fails": 1}))
    sidecar_snapshots = []

    async def fake_query(*args, **kwargs):
        from claude_agent_sdk.types import AssistantMessage, TextBlock
        yield SimpleNamespace(session_id="S-AUTO")
        # 此刻 sidecar 已被 mid-stream 写（resume_fails=_resume_fails）覆盖
        sidecar_snapshots.append(json.loads(sc.read_text()))
        yield AssistantMessage(content=[TextBlock(text="done")],
                               model="claude-sonnet-4-6")

    with umock.patch(
        "ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
        return_value={}), umock.patch("claude_agent_sdk.query", side_effect=fake_query):
        b = _backend(tmp_path)
        asyncio.run(b._spawn("coder", "code it", {}))

    assert sidecar_snapshots, "mid-stream 必须捕捉到 sidecar"
    assert sidecar_snapshots[0]["session_id"] == "S-AUTO"
    assert sidecar_snapshots[0]["resume_fails"] == 1, "resume 续写保留计数（不清零）"


# ---------------------------------------------------------------------------
# F4 (20260821)：无效 resume 计数——resume 后仍 silent-cut 纳入 resume_fails。
# 根因：resume_fails 只计"resume 调用失败"（硬杀/turn_stall）；"resume 成功但
# 恢复无效（又 cut）"无人计数 → 同一 thinking 泥潭 session 被无限 resume，
# fresh 退化（resume_fails >= resume_attempts → agent_degrade）永不触发。
# runner cut_streak(=5) 是最终兜底，但 5 轮里 4 轮 resume 泥潭 = token 空烧。
# ---------------------------------------------------------------------------

def test_resume_then_cut_bumps_resume_fails(tmp_path):
    """F4：sidecar resume 的会话再次 cut → resume_fails +1（"这次恢复尝试无效"）。"""
    (tmp_path / "agents").mkdir()
    sc = tmp_path / "agents" / "coder.session.json"
    sc.write_text(json.dumps({"agent_name": "coder", "session_id": "S-MIRE",
                              "resume_fails": 0}))

    async def fake_query(*args, **kwargs):
        from claude_agent_sdk.types import AssistantMessage, ThinkingBlock
        yield SimpleNamespace(session_id="S-MIRE")
        # resume 后又 thinking-only 终止 —— 无效恢复签名
        yield AssistantMessage(content=[
            ThinkingBlock(thinking="(still thinking...)", signature="sig")],
            model="claude-sonnet-4-6")

    with umock.patch(
        "ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
        return_value={}), umock.patch("claude_agent_sdk.query", side_effect=fake_query):
        # P6：thinking-only cut 且流内实时证据 → 默认判硬切（不 bump）。本用例
        # 守护未知中断（soft）路径——gap 阈值置 0 构造"思考距结束较远"的软切。
        b = _backend(tmp_path, thinking_active_gap_s=0.0)
        result = asyncio.run(b._spawn("coder", "code it", {}))

    assert result.cut is True
    data = json.loads(sc.read_text())
    assert data["resume_fails"] == 1, "resume 后仍 cut 必须 bump（无效 resume 计数）"


def test_fresh_cut_does_not_bump_resume_fails(tmp_path):
    """F4：fresh 首跑的 cut 不计数（首次 cut 先原地 resume——对齐'同一 session
    resume 符合预期'）。sidecar 保留（resume 句柄），resume_fails 保持 0。"""
    (tmp_path / "agents").mkdir()

    async def fake_query(*args, **kwargs):
        from claude_agent_sdk.types import AssistantMessage, ThinkingBlock
        yield SimpleNamespace(session_id="S-FIRST")
        yield AssistantMessage(content=[
            ThinkingBlock(thinking="(first cut...)", signature="sig")],
            model="claude-sonnet-4-6")

    with umock.patch(
        "ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
        return_value={}), umock.patch("claude_agent_sdk.query", side_effect=fake_query):
        b = _backend(tmp_path)
        result = asyncio.run(b._spawn("coder", "code it", {}))

    assert result.cut is True
    sc = tmp_path / "agents" / "coder.session.json"
    assert sc.exists(), "fresh cut 仍保留 sidecar（下次 resume 的句柄）"
    assert json.loads(sc.read_text())["resume_fails"] == 0, "fresh cut 不 bump"


def test_consecutive_ineffective_resumes_reach_degrade_threshold(tmp_path):
    """F4 端到端：已两次无效 resume → 本次 resume 又 cut（bump→3）→ 下一次
    spawn 退化 fresh（agent_degrade：全量 prompt、不 resume 死 session）。
    既有 degrade 分支行为不变——本用例证明计数路径能喂到它。"""
    (tmp_path / "agents").mkdir()
    sc = tmp_path / "agents" / "coder.session.json"
    sc.write_text(json.dumps({"agent_name": "coder", "session_id": "S-MIRE",
                              "resume_fails": 2}))  # 已两次无效 resume

    async def fake_query(*args, **kwargs):
        from claude_agent_sdk.types import AssistantMessage, ThinkingBlock
        yield SimpleNamespace(session_id="S-MIRE")
        yield AssistantMessage(content=[
            ThinkingBlock(thinking="(third cut...)", signature="sig")],
            model="claude-sonnet-4-6")

    with umock.patch(
        "ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
        return_value={}), umock.patch("claude_agent_sdk.query", side_effect=fake_query):
        # P6：同 test_resume_then_cut_bumps——gap 阈值 0 构造软切走 bump 路径
        b = _backend(tmp_path, thinking_active_gap_s=0.0)
        result = asyncio.run(b._spawn("coder", "code it", {}))

    assert result.cut is True
    assert json.loads(sc.read_text())["resume_fails"] == 3, "第三次无效 resume → 3"

    # 下一次 spawn：resume_fails=3 >= resume_attempts(3) → 退化 fresh
    calls = []

    async def fake_query2(*args, **kwargs):
        from claude_agent_sdk.types import AssistantMessage, TextBlock
        calls.append(kwargs)
        yield SimpleNamespace(session_id="S-FRESH")
        yield AssistantMessage(content=[TextBlock(text="done")],
                               model="claude-sonnet-4-6")

    with umock.patch(
        "ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
        return_value={}), umock.patch("claude_agent_sdk.query",
                                      side_effect=fake_query2):
        asyncio.run(b._spawn("coder", "code it", {}))

    from ascendc_devkit.capabilities.agent.sdk_backend import _RESUME_PROMPT
    assert getattr(calls[0]["options"], "resume", None) is None, \
        "连续无效 resume 达阈后必须 fresh，不再 resume 泥潭 session"
    assert calls[0]["prompt"] != _RESUME_PROMPT, "fresh 用全量 stage prompt"


# ---------------------------------------------------------------------------
# P6（step-110）硬切分类：classify_cut 单点 + sidecar 分类键 + 恢复路由三态
# + 硬切不 bump resume_fails（唯一控制流变化）。
# ---------------------------------------------------------------------------

def test_hard_cut_classified_sidecar_and_metrics(tmp_path):
    """硬切（thinking-only 终止 + 流内实时证据 → gap≈0）：分类 True 落 sidecar
    （下一次 spawn 的 resume 路由依据）+ metrics 携带固定键（runner 呈现）。"""
    (tmp_path / "agents").mkdir()

    async def fake_query(*args, **kwargs):
        from claude_agent_sdk.types import AssistantMessage, ThinkingBlock
        yield SimpleNamespace(session_id="S-HARD")
        yield AssistantMessage(content=[
            ThinkingBlock(thinking="(deep reasoning...)", signature="sig")],
            model="claude-sonnet-4-6")

    with umock.patch(
        "ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
        return_value={}), umock.patch("claude_agent_sdk.query", side_effect=fake_query):
        b = _backend(tmp_path)
        result = asyncio.run(b._spawn("coder", "code it", {}))

    assert result.cut is True
    assert result.metrics["cut_hard"] is True
    facts = result.metrics["cut_facts"]
    assert facts["thinking_chars"] == len("(deep reasoning...)")
    assert facts["last_delta_to_end_s"] <= 0.6, "流内实时证据 → gap≈0"
    assert "attempt_duration_s" in facts
    sc = tmp_path / "agents" / "coder.session.json"
    data = json.loads(sc.read_text())
    assert data["cut_hard"] is True, "分类单点写入 sidecar（resume 路由此读）"
    assert data["cut_facts"]["thinking_chars"] == facts["thinking_chars"]


def test_hard_cut_on_resume_does_not_bump_resume_fails(tmp_path):
    """P6 唯一控制流变化：resume 后硬切 → 不 bump（resume_attempts=3 是未知
    中断试探语义，管确定性事件错配；达阈退化 fresh 会丢上下文重放再撞墙）。
    上限归 runner cut_streak。"""
    (tmp_path / "agents").mkdir()
    sc = tmp_path / "agents" / "coder.session.json"
    sc.write_text(json.dumps({"agent_name": "coder", "session_id": "S-MIRE",
                              "resume_fails": 0}))

    async def fake_query(*args, **kwargs):
        from claude_agent_sdk.types import AssistantMessage, ThinkingBlock
        yield SimpleNamespace(session_id="S-MIRE")
        yield AssistantMessage(content=[
            ThinkingBlock(thinking="(still deep thinking...)", signature="s")],
            model="claude-sonnet-4-6")

    with umock.patch(
        "ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
        return_value={}), umock.patch("claude_agent_sdk.query", side_effect=fake_query):
        b = _backend(tmp_path)
        result = asyncio.run(b._spawn("coder", "code it", {}))

    assert result.cut is True and result.metrics["cut_hard"] is True
    data = json.loads(sc.read_text())
    assert data["resume_fails"] == 0, "硬切不进未知中断计数（不走 fresh 退化）"


def test_soft_cut_writes_explicit_false_classification(tmp_path):
    """软切（有思考证据但 gap 大）：分类显式 False 落 sidecar——分类键始终
    反映最近一次 cut（下一次 resume 走裸「继续」原路径）。"""
    (tmp_path / "agents").mkdir()
    sc = tmp_path / "agents" / "coder.session.json"
    sc.write_text(json.dumps({"agent_name": "coder", "session_id": "S-OLD",
                              "cut_hard": True,   # 上一次硬切的残留
                              "resume_fails": 0}))

    async def fake_query(*args, **kwargs):
        from claude_agent_sdk.types import AssistantMessage, ThinkingBlock
        yield SimpleNamespace(session_id="S-OLD")
        yield AssistantMessage(content=[
            ThinkingBlock(thinking="(stalled then closed...)", signature="s")],
            model="claude-sonnet-4-6")

    with umock.patch(
        "ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
        return_value={}), umock.patch("claude_agent_sdk.query", side_effect=fake_query):
        b = _backend(tmp_path, thinking_active_gap_s=0.0)  # gap 阈值 0 → 软切
        result = asyncio.run(b._spawn("coder", "code it", {}))

    assert result.cut is True and result.metrics["cut_hard"] is False
    assert result.metrics["cut_facts"]["thinking_chars"] > 0, "证据在、仅不命中"
    data = json.loads(sc.read_text())
    assert data["cut_hard"] is False, "软切覆写旧分类（stale 防护）"


def test_resume_routes_hard_cut_facts_prompt(tmp_path):
    """路由三态之一：sidecar cut_hard=True 且无显式 resume_prompt → resume
    首条消息 = 硬切兜底提示（仅此判定注入；首次 fresh 执行零注入）。"""
    (tmp_path / "agents").mkdir()
    sc = tmp_path / "agents" / "coder.session.json"
    sc.write_text(json.dumps({"agent_name": "coder", "session_id": "S-HC",
                              "cut_hard": True}))
    calls = []

    async def fake_query(*args, **kwargs):
        from claude_agent_sdk.types import AssistantMessage, TextBlock
        calls.append(kwargs)
        yield AssistantMessage(content=[TextBlock(text="done")],
                               model="claude-sonnet-4-6")

    with umock.patch(
        "ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
        return_value={}), umock.patch("claude_agent_sdk.query", side_effect=fake_query):
        b = _backend(tmp_path)
        asyncio.run(b._spawn("coder", "code it", {}))

    from ascendc_devkit.capabilities.agent._shared import _HARD_CUT_RESUME_PROMPT
    assert calls[0]["prompt"] == _HARD_CUT_RESUME_PROMPT
    assert getattr(calls[0]["options"], "resume", None) == "S-HC"


def test_resume_prompt_wins_over_hard_cut_facts(tmp_path):
    """路由三态优先级：显式 resume_prompt（深修反馈）> 硬切兜底提示。"""
    (tmp_path / "agents").mkdir()
    sc = tmp_path / "agents" / "coder.session.json"
    sc.write_text(json.dumps({"agent_name": "coder", "session_id": "S-HC",
                              "cut_hard": True}))
    calls = []

    async def fake_query(*args, **kwargs):
        from claude_agent_sdk.types import AssistantMessage, TextBlock
        calls.append(kwargs)
        yield AssistantMessage(content=[TextBlock(text="done")],
                               model="claude-sonnet-4-6")

    with umock.patch(
        "ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
        return_value={}), umock.patch("claude_agent_sdk.query", side_effect=fake_query):
        b = _backend(tmp_path)
        asyncio.run(b._spawn("coder", "code it", {},
                             resume_session_id="S-HC",
                             resume_prompt="修 CMake 注册并回验"))

    assert calls[0]["prompt"] == "修 CMake 注册并回验"


def test_sidecar_without_cut_key_routes_bare_continue(tmp_path):
    """旧 sidecar（无分类键）→ 裸「继续」原路径（缺键 False，不假设）。"""
    (tmp_path / "agents").mkdir()
    sc = tmp_path / "agents" / "coder.session.json"
    sc.write_text(json.dumps({"agent_name": "coder", "session_id": "S-LEGACY"}))
    calls = []

    async def fake_query(*args, **kwargs):
        from claude_agent_sdk.types import AssistantMessage, TextBlock
        calls.append(kwargs)
        yield AssistantMessage(content=[TextBlock(text="done")],
                               model="claude-sonnet-4-6")

    with umock.patch(
        "ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
        return_value={}), umock.patch("claude_agent_sdk.query", side_effect=fake_query):
        b = _backend(tmp_path)
        asyncio.run(b._spawn("coder", "code it", {}))

    from ascendc_devkit.capabilities.agent.sdk_backend import _RESUME_PROMPT
    assert calls[0]["prompt"] == _RESUME_PROMPT


def test_hard_cut_resume_inner_retry_stays_bare_continue(tmp_path, monkeypatch):
    """P6 路由只作用于 resume **首条**消息：spawn 内层的服务端错误重试/瞬态
    crash 重试重置为裸「继续」（crash 重试非 cut resume，兜底提示不重复注入）。"""
    (tmp_path / "agents").mkdir()
    sc = tmp_path / "agents" / "coder.session.json"
    sc.write_text(json.dumps({"agent_name": "coder", "session_id": "S-HC",
                              "cut_hard": True}))
    calls = []

    async def fake_query(*args, **kwargs):
        from claude_agent_sdk.types import AssistantMessage, TextBlock
        calls.append(kwargs.get("prompt"))
        yield SimpleNamespace(session_id="S-HC")
        if len(calls) == 1:
            yield SimpleNamespace(
                result="The `content[].thinking` in the thinking mode must be "
                       "passed back to the API. (request id: x)")
            raise RuntimeError("stream aborted after APIError")
        yield AssistantMessage(content=[TextBlock(text="done")],
                               model="claude-sonnet-4-6")

    async def _fake_sleep(s):
        return None

    monkeypatch.setattr(
        "ascendc_devkit.capabilities.agent.sdk_backend.asyncio.sleep",
        _fake_sleep)
    with umock.patch(
        "ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
        return_value={}), umock.patch("claude_agent_sdk.query", side_effect=fake_query):
        b = _backend_fast_backoff(tmp_path)
        result = asyncio.run(b._spawn("coder", "code it", {}))

    from ascendc_devkit.capabilities.agent._shared import _HARD_CUT_RESUME_PROMPT
    from ascendc_devkit.capabilities.agent.sdk_backend import _RESUME_PROMPT
    assert result.status == "ok" and len(calls) == 2
    assert calls[0] == _HARD_CUT_RESUME_PROMPT, "首条 resume 消息 = 兜底提示"
    assert calls[1] == _RESUME_PROMPT, "内层服务端错误重试 = 裸「继续」（非兜底提示）"


def test_set_sidecar_cut_noop_without_sidecar(tmp_path):
    """判切点分类写入要求 sidecar 已存在（无 resume 句柄可指时不凭空造）。"""
    b = _backend(tmp_path)
    b._set_sidecar_cut("coder", "", "", None, True)
    assert not (tmp_path / "agents" / "coder.session.json").exists()


def test_read_sidecar_cut_hard_corrupt_json_is_false(tmp_path):
    """损坏 sidecar → 分类读 False（分类是路由优化非正确性不变式）。"""
    (tmp_path / "agents").mkdir()
    sc = tmp_path / "agents" / "coder.session.json"
    sc.write_text("{not json")
    b = _backend(tmp_path)
    assert b._read_sidecar_cut_hard("coder", "", "") is False
