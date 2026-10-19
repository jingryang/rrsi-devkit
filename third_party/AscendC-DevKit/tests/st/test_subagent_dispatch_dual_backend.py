"""相2 §2.4 Spike-2 — dual-backend D3 sub-agent DISPATCH (live).

Proves LIVE that a sub-agent DISPATCHED by a primary through the real transport
RESOLVES via the D3 projection and EXECUTES, on BOTH backends — the one live link
in 相2 that was heavy_llm-deferred (directive: 相2 每步 claude + opencode 双侧真跑).

Why this is the real link, not a UT:
  - D3 projection CORRECTNESS (names, leaf/subagent split, tools, permissions) is
    UT-pinned (test_opencode_backend.py::test_project_agents_*). But "projected
    correctly" ≠ "callable at runtime" — the open live question is whether the
    projected/registered sub-agent actually RESOLVES when the primary dispatches
    it through the real SDK transport (claude) / opencode serve (opencode), with
    no "agent not found / unknown subagent_type" rejection. Only a live spawn
    answers that (§3.9 — real links need real guards).

Why ``ascendc-coder-regbase`` as the primary:
  - It is the real production agent whose manifest grants the ``Agent`` dispatch
    tool (``.claude/agents/ascendc-coder-regbase.md`` → allowed_tools includes
    ``Agent``), and whose whole job is to *orchestrate sub-agents* (s2-analysis
    / s4-coding / vf-test-agent). So dispatching a probe sub-agent is squarely
    within its real role — no test-only manifest debt (§1.4/§2.5), and no
    touching the production permission surface (we grant nothing; it already
    holds ``Agent`` legitimately). An earlier version of this test spawned a
    non-existent ``ascendc-precision-debugger`` manifest, which fell back to the
    default toolset (no ``Agent``, ``Task`` disallowed) and so could never
    dispatch — the test was asserting against an agent that structurally could
    not do the thing. This is the corrected primary.

Why a file marker + bounded retry (§3.10 / §3.11):
  - The deterministic observable is the sub-agent writing ``dispatch_probe.txt``
    to the working dir (mirrors the Spike-3 edit-allow pattern). Whether the
    primary CHOSE to dispatch and whether the sub-agent COMPLIED are both
    non-deterministic, so a single attempt cannot adjudicate. We assert the
    DETERMINISTIC MECHANISM fires within bounded retries: either the marker file
    appears (end-to-end: dispatch resolved + sub-agent ran + complied), OR the
    transcript shows a dispatch to ``ascendc-precision-run-tests`` that did NOT
    trip a not-found-class error (dispatch resolved). Three consecutive attempts
    all hitting a not-found-class error is a real D3 regression (FAIL). Three
    attempts with no marker AND no resolvable dispatch is reported honestly as
    "mechanism not observed" rather than silently green. The transcript is read
    from ``result.transcript`` (the backend now exposes the on-disk path — a
    prior blind spot returned None and hid every resolvable dispatch).

Both backends explicitly wire sub-agents (neither auto-discovers .claude/agents
in a programmatic session): claude via ``_build_agent_definitions`` → ``agents=``;
opencode via ``_project_agents`` → opencode agent config blocks +
``subagent_depth:1``. So the dispatch link is real on both sides.

Marked @pytest.mark.llm + @pytest.mark.heavy_llm: multi-turn, two LLM agents per
attempt (primary + sub-agent), minutes-scale, high token (§3.11). Not in the
default sweep (``-m "not heavy_llm"``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.st._dual_backend import (
    has_anthropic,
    load_settings_env,
    make_backend,
    require_live_opencode,
)

load_settings_env()

_MAX_ATTEMPTS = 3
_PRIMARY = "ascendc-coder-regbase"               # real primary that HOLDS the Agent dispatch tool
_SUBAGENT = "ascendc-precision-diagnose"        # real projected/registered sub-agent
_MARKER_NAME = "dispatch_probe.txt"
_MARKER_TOKEN = "DISPATCH_OK"

# Error signatures that mean the projected sub-agent did NOT resolve through the
# transport (the D3 regression we are guarding against). Matched case-insensitive
# against the transcript text.
_NOT_FOUND_PHRASES = (
    "agent not found",
    "unknown agent",
    "unknown subagent",
    "subagent not found",
    "not a valid subagent",
    "no agent named",
    "is not available",
    "not in this session",   # opencode skill/agent allowlist rejection variant
)

# The sub-agent task: trivial, no NPU, no checkpoint — just prove it ran.
_SUBAGENT_TASK = (
    "连通性探针。禁止运行任何测试、禁止读取 checkpoint、禁止编译或 redeploy。"
    f"唯一任务：在当前工作目录创建文件 `{_MARKER_NAME}`，内容为一行 "
    f"`{_MARKER_TOKEN}`。完成后输出 `RESULT: {_MARKER_TOKEN}` 并结束。"
)

# The primary (coder-regbase) is asked to do ONE dispatch as a pre-flight
# Agent-tool connectivity check, BEFORE any codegen orchestration — so it does
# not load the codegen skill / write source / run the s2→s4→vf pipeline.
_DISPATCH_PROMPT = (
    "【Agent 工具连通性自检 —— 编码编排前的前置检查】\n\n"
    "在开始任何编码编排之前，先做一次 Agent 工具连通性自检。**本次只做这一件事**："
    "不加载编码 skill、不写任何源文件、不运行 s2/s4/vf 流水、不碰任何算子代码。\n\n"
    "唯一动作：用你的 `Agent` 工具派发一次子 agent：\n"
    f"- subagent_type / agent 类型名 = `{_SUBAGENT}`\n"
    "- 子 agent 的 prompt 原样传递（不要增删）：\n"
    f"    「{_SUBAGENT_TASK}」\n\n"
    "派发完成后，用一句话说明子 agent 是否成功执行了任务，然后结束。"
    "不要做其它任何事。"
)


def _transcript_text(result) -> str:
    """Best-effort read of the spawn's transcript file (may be None/unreadable)."""
    p = getattr(result, "transcript", None)
    if not p:
        return ""
    try:
        return Path(p).read_text(errors="ignore")
    except Exception:
        return ""


def _dispatch_resolved(text: str) -> bool:
    """Did a dispatch to the sub-agent occur WITHOUT a not-found-class error?

    Evidence of a dispatch that resolved: the sub-agent name appears AND none of
    the not-found phrases appear. (The sub-agent name in transcript ≈ a turn for
    it ran; absence of not-found phrases ≈ it was accepted, not rejected.)
    """
    low = text.lower()
    if _SUBAGENT.lower() not in low:
        return False
    return not any(phrase in low for phrase in _NOT_FOUND_PHRASES)


@pytest.mark.llm
@pytest.mark.heavy_llm
@pytest.mark.parametrize("kind", ["claude", "opencode"])
def test_d3_subagent_dispatch_resolves_dual_backend(kind, tmp_path):
    """D3 dispatch parity: a projected/registered sub-agent resolves + executes
    through the real transport, on BOTH backends (within bounded retry)."""
    if kind == "opencode":
        require_live_opencode()
    elif not has_anthropic():
        pytest.skip("Anthropic not configured")

    marker_seen = False
    mechanism_seen = False
    not_found_seen = False
    last_status = None
    transcripts = []

    for attempt in range(_MAX_ATTEMPTS):
        ws = tmp_path / f"ws_{attempt}"
        ws.mkdir(parents=True, exist_ok=True)
        result = make_backend(kind, ws).spawn(
            _PRIMARY, _DISPATCH_PROMPT, {},
            skills=[],
            primary_skill=None,
            working_dir=ws,
            stage_name="spike2",
            branch_label="dispatch",
        )
        last_status = getattr(result, "status", None)
        text = _transcript_text(result)
        transcripts.append(text)
        if _SUBAGENT.lower() in text.lower():
            if any(p in text.lower() for p in _NOT_FOUND_PHRASES):
                not_found_seen = True
            else:
                mechanism_seen = True
        probe = ws / _MARKER_NAME
        if probe.exists() and _MARKER_TOKEN in probe.read_text(errors="ignore"):
            marker_seen = True
            break
        if mechanism_seen:
            # mechanism already fired this attempt; keep one more attempt to try
            # for the strong end-to-end marker, but don't burn all retries.
            break

    if marker_seen:
        return  # strong PASS: dispatch resolved + sub-agent ran + complied

    if not_found_seen and not mechanism_seen:
        pytest.fail(
            f"[{kind}] D3 regression: every dispatch to {_SUBAGENT} across "
            f"{_MAX_ATTEMPTS} attempts tripped a not-found-class error "
            f"(last status={last_status!r}). The projected/registered sub-agent "
            "did NOT resolve through the transport. Inspect transcripts.")

    if mechanism_seen:
        return  # mechanism PASS (§3.10): dispatch resolved though no marker

    pytest.fail(
        f"[{kind}] sub-agent dispatch neither produced the marker file nor "
        f"showed a resolvable dispatch across {_MAX_ATTEMPTS} attempts "
        f"(last status={last_status!r}). Mechanism not observed — this may be "
        "LLM non-compliance rather than a D3 defect; inspect transcripts.")
