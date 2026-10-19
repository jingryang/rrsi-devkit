"""L5 Capabilities — SDK Backend using claude_agent_sdk."""

from __future__ import annotations

import anyio
import asyncio
import sys
import time
from pathlib import Path

from .backend import AgentResult
from .base_backend import BaseAgentBackend, IRConsumer, classify_cut
from ascendc_devkit.capabilities.mcp_tools import build_engine_mcp_server
from ascendc_devkit.infra.logger import Logger


from ._shared import (
    # transcript serialization (native→IR mapping; consumer in base_backend
    # owns all per-event signal extraction after the stream).
    _serialize_event,
    # frontmatter / agent-prompt loading
    _strip_frontmatter,
    _resolve_project_settings,
    _ensure_skills_anchor,
    _agent_prompt_search_paths,
    _find_agent_prompt,
    agent_prompt_is_placeholder,
    # crash-text / resume control-flow primitives retained by the subclass
    # (stall accounting + result construction moved to base_backend's
    # IRConsumer + _build_result factory — step-68 task 10).
    _is_session_gone,
    _is_transient_error,
    _is_rate_limit_error,
    server_backoff_strategy,
    advance_backoff,
    _ACLOSE_ERROR_MARKERS,
    _RESUME_PROMPT,
    _HARD_CUT_RESUME_PROMPT,
    # skill-injection rendering boundary (D2)
    render_skill_injection,
    # —— re-exported for UTs (canonical source is _shared) ——
    # test_stall_detection tests the stall pure helpers in isolation and
    # test_capabilities exercises _classify_error_type directly; these have no
    # in-module caller post-migration but stay importable here as the
    # test-facing surface.
    _tool_use_signature,
    _scan_tool_results,
    _classify_error_type,
    classify_spawn_exception,
    _TOOL_SIG_WINDOW,
    _ACLOSE_ERROR_MARKER,
    MAX_STALLED_TURNS,
    BOOTSTRAP_MAX_STALLED,
    format_attribution,
)


def _card_pin_options_env(card_pin: int | None) -> dict:
    """P13 (step-116)：op 卡 pin → ClaudeAgentOptions(env=...) 增量 env。

    SDK 把 env 合并进 CLI 子进程环境；bash 工具子树默认继承即被结构性锁卡
    （与 OpenCodeBackend._build_serve_env 的 pin 块对称，§1.15 单源经
    card_pin_env）。None → 空 dict（不传该选项，环境原样继承）。
    """
    if card_pin is None:
        return {}
    from ascendc_devkit.adapters.npu.card_pin import card_pin_env
    return {"env": card_pin_env(card_pin)}


class _SdkTurnStallAbort(RuntimeError):
    """turn-stall 看门狗触发：网关静默（无任何 stream 事件）超过 turn_stall_s 秒。

    与 turn-based stall（IRConsumer.should_stop，连续无进展 assistant turn）不同，
    这是 **wall-clock** 信号——一个请求发出后网关迟迟不回包，`async for` 不 yield
    任何事件，turn-based 判定根本不会执行（无新 turn 到达）。本异常由
    ``_stream_with_turn_stall`` 抛出，在 crash-salvage 里被识别为 aborted="turn_stall"
    → infra（短路由迭代 + resume 重跑），而非 logic failure。
    """


def _build_agent_definitions(exclude: set[str] | None = None) -> dict:
    """Load all .claude/agents/*.md files and convert to AgentDefinition objects.

    Programmatically registered subagents are required for the Agent tool to
    recognise custom ``subagent_type`` values in SDK ``query()`` sessions.
    Filesystem-based discovery (``.claude/agents/``) only happens at CLI startup;
    this function replicates that for programmatic spawns.
    """
    from claude_agent_sdk import AgentDefinition

    exclude = exclude or set()
    agents: dict[str, object] = {}

    project_root = Path(__file__).parent.parent.parent.parent.parent
    agents_dir = project_root / ".claude" / "agents"
    if not agents_dir.is_dir():
        return agents

    for agent_file in agents_dir.glob("*.md"):
        agent_name = agent_file.stem
        if agent_name in exclude:
            continue
        try:
            content = agent_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        # Parse frontmatter to extract manifest fields (tools, description, etc.)
        prompt_body = _strip_frontmatter(content)
        # Build a short description from the first line of the body
        # (agent .md files typically start with a role description line).
        first_line = ""
        for line in prompt_body.strip().split("\n"):
            line = line.strip()
            if line and not line.startswith("#"):
                first_line = line[:200]
                break

        # Load the manifest for tool/permission config
        try:
            from ascendc_devkit.capabilities.skill.loader import load_agent_manifest
            manifest = load_agent_manifest(agent_name)
            tools = manifest.allowed_tools if manifest.allowed_tools else None
            disallowed = manifest.disallowed_tools if manifest.disallowed_tools else None
            description_text = manifest.description or first_line or agent_name
            max_turns = manifest.max_turns
        except Exception:
            tools = None
            disallowed = None
            description_text = first_line or agent_name
            max_turns = None

        agents[agent_name] = AgentDefinition(
            description=description_text,
            prompt=prompt_body,
            tools=tools,
            disallowedTools=disallowed,
            maxTurns=max_turns,
        )

    return agents


class SDKBackend(BaseAgentBackend):
    """Default agent backend using claude_agent_sdk.

    Sets the agent's cwd to *working_dir* so Write/Edit/Bash output
    lands directly in the workspace artifacts directory.  After the
    agent completes, *working_dir* is scanned for generated files
    and those become ``AgentResult.artifacts``.
    """

    def __init__(self, interactive: bool = True,
                 allowed_tools: list[str] | None = None,
                 disallowed_tools: list[str] | None = None,
                 max_turns: int = 10000,
                 working_dir: Path | str | None = None,
                 on_decision: str = "default",
                 decision_workspace: Path | str | None = None,
                 webhook_url: str | None = None,
                 enable_stubbed: bool = False,
                 artifacts_ignore: list[str] | None = None,
                 resume_max_retries: int = 10,
                 resume_max_no_progress: int = 3,
                 rate_limit_max_retries: int = 6,
                 rate_limit_backoff_base_s: float = 30.0,
                 rate_limit_backoff_factor: float = 2.0,
                 rate_limit_backoff_max_total_s: float = 600.0,
                 # 退化 spawn 设计（docs/plan/turn-stall-resume-escalation/）：turn-stall/硬
                 # 超时后先原地 resume（续同一 session），连续失败 resume_attempts 次后
                 # 退化 spawn（清 sidecar + fresh）。与 OpenCodeBackend 对称。默认与
                 # runtime_config.infra_backoff().resume_attempts 一致。
                 resume_attempts: int = 3,
                 # turn-stall 看门狗（对齐 opencode 的 turn_stall_s）：网关静默（无任何
                 # stream 事件）超过 turn_stall_s 秒 → abort（aborted="turn_stall" →
                 # infra）。0 = 关闭。默认 180s（比 opencode 的 120s 更宽容，吸收慢网关
                 # 抖动；用户拍板）。
                 turn_stall_s: float = 180.0,
                 # P6 硬切分类判据（与 OpenCodeBackend 对称）：末次 thinking 增量距
                 # 截断 ≤ 此秒数 = 思考流仍活跃（外部输出墙形态）。默认来自
                 # runtime_config.retry_budgets().thinking_active_gap_s。
                 thinking_active_gap_s: float = 0.6,
                 # P13 (step-116)：op 级 NPU 卡号——经 ClaudeAgentOptions(env=...)
                 # 进入 CLI 子进程 env 的双变量 pin，bash 工具子树默认继承即被
                 # 结构性锁卡（与 OpenCodeBackend._build_serve_env 对称）。
                 # None=不 pin（无 NPU 语境）。
                 card_pin: int | None = None):
        super().__init__(decision_workspace=decision_workspace,
                         artifacts_ignore=artifacts_ignore)
        self._card_pin = card_pin
        self._interactive = interactive
        self._allowed_tools = allowed_tools or [
            "Read", "Edit", "Bash", "Glob", "Grep",
            # Skill enables model-invoked skills discovered from the flat
            # .claude/skills tree (anchored per-workspace, see
            # _ensure_skills_anchor). Without Skill in allowed_tools the model
            # cannot invoke them and falls back to reading SKILL.md via
            # Read/Bash.
            "Skill",
            # MCP tools are exposed to the agent under the qualified name
            # mcp__<server>__<tool>. The server key "engine" comes from
            # build_engine_mcp_server()'s create_sdk_mcp_server("engine", ...)
            # and mcp_servers={"engine": ...}. The bare "resolve_ambiguity" was
            # verified redundant by tests/st/test_decision_transcript.py
            # (full name alone reaches the tool), so only the full name is kept.
            "mcp__engine__resolve_ambiguity",
        ]
        self._disallowed_tools = disallowed_tools or ["Task", "AskUserQuestion"]
        self._max_turns = max_turns
        self._working_dir = Path(working_dir) if working_dir else None
        self._on_decision = on_decision
        self._webhook_url = webhook_url

        # Resume-retry gates (step-5a B2-resume). Defaults match
        # orchestration-config.json; the L2 dispatcher injects config-loaded
        # values (capabilities/L5 must not import orchestration/L3 itself).
        self._resume_max_retries = resume_max_retries
        self._resume_max_no_progress = resume_max_no_progress
        # step-57 (P80): 429 burst backoff-resume budget (independent gates).
        self._rl_max_retries = rate_limit_max_retries
        self._rl_backoff_base_s = rate_limit_backoff_base_s
        self._rl_backoff_factor = rate_limit_backoff_factor
        self._rl_backoff_max_total_s = rate_limit_backoff_max_total_s
        # resume 连续失败退化的阈值（与 OpenCodeBackend 对称）。
        self._resume_attempts = max(1, int(resume_attempts))
        # turn-stall 看门狗阈值（秒）；0 = 关闭。
        self._turn_stall_s = max(0.0, float(turn_stall_s))
        # P6 硬切分类 gap 判据阈值（构造注入 §1.6，与 OpenCodeBackend 对称）。
        self._thinking_active_gap_s = max(0.0, float(thinking_active_gap_s))

    def spawn(self, agent_name: str, prompt: str, context: dict,
              skills: list[str] | None = None,
              model: str | None = None,
              working_dir: Path | str | None = None,
              repo_baseline: str | None = None,
              repo_root: Path | str | None = None,
              stage_name: str = "",
              branch_label: str = "",
              resume_session_id: str | None = None,
              resume_prompt: str | None = None,
              primary_skill: str | None = None,
              deadline_monotonic: float | None = None) -> AgentResult:
        # S1b 方案 A: anyio.run + fail_after 包整个 _spawn。anyio cancel scope 是 SDK
        # transport.close() 的 anyio.CancelScope(shield=True) 认的取消方式 → SIGTERM/SIGKILL
        # escalation 正常 kill CLI（raw asyncio.cancel 会穿透 shield 致 CLI 孤儿，已 probe
        # 证伪）。到点 _spawn 被 cancel（其 finally 关 transcript；sidecar 在 session_id 捕获
        # 时已 flush，保留可 resume），这里 catch TimeoutError 返回 aborted。consumer 随
        # _spawn 栈丢失，session_id 靠 sidecar（硬终止场景的构造性 resume 保证）。
        start_ms = int(time.time() * 1000)
        # sidecar 自动 resume 在 _spawn 内部决定（局部变量），硬超时 cancel 后外层拿不到
        # —— 用实例标志把「本次 spawn 是否 resume」跨出 _spawn，供超时 handler 判断 bump。
        self._spawn_was_resume = bool(resume_session_id)

        async def _timed() -> AgentResult:
            coro = self._spawn(agent_name, prompt, context, skills,
                               model, working_dir, repo_baseline, repo_root,
                               stage_name, branch_label,
                               resume_session_id, resume_prompt,
                               primary_skill, deadline_monotonic)
            if deadline_monotonic is None:
                return await coro
            # max(..., 0.001): deadline 已过时仍给 anyio 一个正数（fail_after 拒绝 <=0）
            with anyio.fail_after(max(deadline_monotonic - time.monotonic(), 0.001)):
                return await coro

        try:
            return anyio.run(_timed)
        except TimeoutError:
            Logger.warn(
                f"Agent {agent_name} hard timeout (deadline_monotonic reached); "
                f"SDK close escalation killed the CLI subprocess")
            if self._spawn_was_resume or resume_session_id:
                # resume 会话被硬超时 kill → 连续失败 +1（Phase 1 失败计数）
                # （fresh 首跑不计数——符合「turn-stall 先原地 resume」）。
                # `self._spawn_was_resume` 覆盖 sidecar 自动 resume（在 _spawn 内决定，
                # 外层 param 为 None）；显式 resume_session_id 两者都真。
                self._bump_session_resume_fails(agent_name, branch_label,
                                                stage_name)
            return self._build_result(
                agent_name, consumer=None, crashed=True,
                crash_reason="hard timeout (deadline_monotonic reached)",
                artifacts={}, transcript_path=None,
                attempt=0, start_ms=start_ms, aborted="hard_timeout")

    async def _stream_with_turn_stall(self, query, prompt, options):
        """用可重置 deadline 的 CancelScope 包住 SDK query 流，实现 turn-stall 看门狗。

        每收到一个 stream 事件就刷新 deadline；若网关静默（`async for` 长时间不
        yield）超过 ``self._turn_stall_s`` 秒，CancelScope 到期取消，捕获后抛
        ``_SdkTurnStallAbort``。0/关闭时透传原流。这是 opencode 后端 turn_stall_s
        看门狗的 claude SDK 对称实现（opencode 用 worker 线程 + SSE liveness 轮询，
        此处用 anyio 可重置 deadline，语义一致：慢网关不回包 = 卡死，非「慢但活着」）。
        """
        stall = self._turn_stall_s
        if stall <= 0:
            async for event in query(prompt=prompt, options=options):
                yield event
            return
        from anyio import CancelScope, get_cancelled_exc_class
        _Cancelled = get_cancelled_exc_class()
        with CancelScope() as scope:
            def _kick() -> None:
                scope.deadline = time.monotonic() + stall
            _kick()
            try:
                async for event in query(prompt=prompt, options=options):
                    _kick()  # any event = liveness（含 thinking/tool_use/tool_result）
                    yield event
            except _Cancelled:
                if scope.cancel_called:
                    raise _SdkTurnStallAbort(
                        f"no stream event for {stall:.0f}s (turn-stall; "
                        f"gateway silent)") from None
                raise

    async def _spawn(self, agent_name: str, prompt: str, context: dict,
                      skills: list[str] | None = None,
                      model: str | None = None,
                      working_dir: Path | str | None = None,
                      repo_baseline: str | None = None,
                      repo_root: Path | str | None = None,
                      stage_name: str = "",
                      branch_label: str = "",
                      resume_session_id: str | None = None,
                      resume_prompt: str | None = None,
                      primary_skill: str | None = None,
                      deadline_monotonic: float | None = None) -> AgentResult:
        # S1b: 硬墙在 spawn 层 anyio.fail_after 实现（见 spawn 的 _timed wrapper）——anyio
        # cancel scope 是 SDK transport.close() shield 认的取消方式，到点 escalation kill CLI。
        # _spawn 内 deadline_monotonic 不直接消费（spawn 层 cancel 整个 _spawn task）。
        # Call-level working_dir overrides instance-level default (fallback).
        effective_cwd = Path(working_dir) if working_dir else self._working_dir
        # F4（20260821）：本 spawn 是否走了 resume——在 _spawn 入口初始化（外层
        # spawn() 只覆盖显式 resume_session_id 的情形；sidecar 自动 resume 在下方
        # 分支置位）。供 cut 判定处的"无效 resume"计数与外层硬超时 bump 判断。
        self._spawn_was_resume = bool(resume_session_id)
        # Display prefix for log/transcript attribution (D8/§P2): see
        # format_attribution's docstring for the [op_name/stage/branch] format.
        attribution = format_attribution(stage_name, branch_label)
        # Computed early so the SDK-import-fatal path below can use the single
        # _build_result factory (it needs a start_ms for elapsed_ms).
        start_ms = int(time.time() * 1000)
        try:
            from claude_agent_sdk import ClaudeAgentOptions, query
        except ImportError:
            Logger.warn(f"claude_agent_sdk not available; using stub for {agent_name}")
            return self._build_result(
                agent_name, consumer=None, crashed=True,
                crash_reason="claude_agent_sdk not available",
                artifacts={}, transcript_path=None,
                attempt=0, start_ms=start_ms)

        system_prompt = _find_agent_prompt(agent_name)

        try:
            mcp_servers = {"engine": build_engine_mcp_server(
                self._interactive,
                on_decision=self._on_decision,
                workspace_dir=str(self._decision_workspace) if self._decision_workspace else None,
                webhook_url=self._webhook_url,
            )}
        except Exception as e:
            Logger.warn(f"Failed to build MCP server: {e}")
            mcp_servers = {}

        # Ensure working_dir exists so agent can write files there
        if effective_cwd:
            effective_cwd.mkdir(parents=True, exist_ok=True)
            # Anchor the canonical flat skill tree at <cwd>/.claude/skills so
            # native discovery finds it from this deep artifacts cwd (claude
            # does not walk up; add_dirs does not trigger discovery — V7).
            _ensure_skills_anchor(effective_cwd)

        # Manifest-driven tool/permission contract (D3). Falls back to the
        # backend defaults when the agent manifest declares nothing, so existing
        # behavior is preserved for agents without these frontmatter fields.
        eff_allowed = self._allowed_tools
        eff_disallowed = self._disallowed_tools
        eff_max_turns = self._max_turns
        try:
            from ascendc_devkit.capabilities.skill.loader import (
                load_agent_manifest, validate_manifest,
            )
            manifest = load_agent_manifest(agent_name)
            errs = validate_manifest(manifest)
            if errs:
                for e in errs:
                    Logger.warn(f"agent manifest validation: {e}")
            if manifest.allowed_tools:
                eff_allowed = manifest.allowed_tools
            if manifest.disallowed_tools:
                eff_disallowed = manifest.disallowed_tools
            if manifest.max_turns is not None:
                eff_max_turns = manifest.max_turns
        except Exception as e:  # best-effort; never block a spawn on manifest issues
            Logger.warn(f"Failed to load agent manifest for {agent_name}: {e}")

        # Pin the project's .claude/settings.json explicitly (single config
        # source, shared with the TUI). Without this, the CLI walks up from the
        # deep artifacts cwd to find settings, which fails in headless mode and
        # surfaces as "Not logged in" (the env block carrying ANTHROPIC_* never
        # loads). setting_sources keeps loading to the project/local layers so a
        # stray user-level settings file can't silently override the run.
        settings_path = _resolve_project_settings()

        # Register custom agent types from .claude/agents/ so they are
        # available as subagent_type values for the Agent tool.  Filesystem
        # discovery only runs at CLI startup — programmatic query() sessions
        # must explicitly pass agents= (see agent-sdk-ref/subagents.md).
        sub_agents = _build_agent_definitions(exclude={agent_name})

        options = ClaudeAgentOptions(
            system_prompt=system_prompt,
            allowed_tools=eff_allowed,
            disallowed_tools=eff_disallowed,
            mcp_servers=mcp_servers,
            permission_mode="acceptEdits",
            # Pass skills through verbatim: None = inherit default (all flat
            # skills discoverable), [] = explicitly suppress all, list[str] =
            # expose only the assigned ones. `skills or []` here would collapse
            # "unassigned" (None) into "suppress all", which is what silently
            # disabled every agent's skills (see P1 root cause 4).
            skills=skills,
            max_turns=eff_max_turns,
            cwd=str(effective_cwd) if effective_cwd else None,
            model=model,
            settings=settings_path,
            setting_sources=["project", "local"],
            agents=sub_agents,
            # P13 (step-116)：op 卡 pin 随会话进 CLI 子进程 env（None → 空
            # dict 不传，环境原样继承）。
            **_card_pin_options_env(self._card_pin),
        )

        # IR consumer owns ALL per-event signal extraction + accounting that was
        # previously inlined in this loop (session_id capture, turn count,
        # full_response, truncation, stall detection). The subclass now only
        # maps native→IR (_serialize_event) and drives the stream (step-68
        # task 10); result construction is the single base _build_result factory.
        consumer = IRConsumer(agent_name)
        _session_id_written = False  # sidecar flushed once on first session_id capture
        Logger.action("agent_spawn", f"{agent_name} starting (max_turns={eff_max_turns})"
                     + (f", cwd={effective_cwd}" if effective_cwd else ""))

        # —— Transcript sink (Task 1.2) ——
        # Persist the full message stream (text + tool_use + tool_result) to
        # <run>/agents/<agent>-<seq>.jsonl so `show` can replay an agent session.
        # Best-effort: a write failure must never abort the run (D1/D2).
        transcript = self._open_transcript(agent_name, branch_label)
        # Capture the on-disk path so AgentResult can expose it (callers/tests
        # read the transcript to inspect what the agent actually did). Without
        # this, result.transcript was always None on this backend even though
        # the file exists — a silent observation blind spot.
        transcript_path = None
        if transcript is not None:
            try:
                transcript_path = Path(transcript.name)
            except Exception:  # noqa: BLE001 — path capture is best-effort
                transcript_path = None

        # —— Resume-retry loop (step-5a B2-resume) ——
        # A transient SSE fault ("Content block not found") crashes the query
        # mid-turn. Rather than failing the whole spawn (what made this worse
        # than the TUI, where a human just says "continue"), we resume the
        # crashed session by session_id. Two gates bound the loop: a total
        # budget (max_retries) and a no-progress gate (stop after
        # max_no_progress consecutive resumes adding no new text/tool/files).
        # Non-transient errors are NOT retried. All retries are consumed here,
        # so the caller still sees one AgentResult and the codegen circuit
        # breaker / F4 stall counter are unaffected (D3). Gate thresholds are
        # injected at construction (config resolved in L2; see __init__).
        _max_retries = self._resume_max_retries
        _max_no_progress = self._resume_max_no_progress
        no_progress = 0
        attempt = 0
        # step-57 (P80): independent 429 burst backoff-resume budget. Kept
        # separate from `no_progress` because a rejected 429 turn adds no
        # progress and would otherwise instantly trip the SSE no-progress gate.
        rl_attempt = 0
        rl_elapsed_s = 0.0
        crashed = False
        last_exc: Exception | None = None
        _crash_text: str = ""  # enriched diagnostic (exc + stderr); set on crash
        # Capture the CLI subprocess stderr via the SDK's options.stderr callback.
        # On a dead/expired resume session the SDK raises only a generic
        # ProcessError ("Command failed with exit code 1"); the actionable
        # diagnostic ("No conversation found with session ID: …") is printed to
        # the subprocess stderr only. With no callback the SDK inherits fd 2, so
        # that text reaches the terminal but never the exception — and
        # _is_session_gone() below could never match a real gone/expired session,
        # meaning the 提案#1 cross-run resume degrade would never fire. Registering
        # a callback makes the SDK PIPE stderr and hand us each line. We (a)
        # accumulate per-attempt lines for crash diagnosis and (b) tee each line
        # back to sys.stderr so existing terminal visibility of SDK diagnostics
        # is preserved (§1.2 可诊断 — nothing swallowed).
        _stderr_lines: list[str] = []

        def _on_sdk_stderr(line: str) -> None:
            _stderr_lines.append(line)
            try:
                sys.stderr.write(line + "\n")
            except Exception:  # noqa: BLE001 — teeing must never break the SDK
                pass

        import dataclasses as _dc
        if options.stderr is None:
            options = _dc.replace(options, stderr=_on_sdk_stderr)
        # Proposal #1: cross-run resume — when a prior run's session_id is
        # supplied, start by resuming it (reuse the crashed session's reasoning
        # memory) instead of a fresh query. The resume prompt is the backend's
        # own; the stage's prompt is ignored on resume (the session carries its
        # own context). If the session is gone/expired on the first query,
        # _spawn degrades to fresh below.
        # D2 (2.1): render the assigned skill's delivery into the FRESH-spawn
        # prompt at the backend boundary — the orchestration no longer prepends
        # `/<skill>` at the stage layer. `primary_skill` is decoupled from the
        # `skills` allowlist (codegen injects its coding skill while keeping an
        # open allowlist). No-op when primary_skill is falsy. NOT applied to a
        # resume prompt (_RESUME_PROMPT): a resumed session already loaded the
        # skill, so re-injecting the slash would be read as a fresh directive.
        initial_prompt = render_skill_injection(prompt, primary_skill)
        # 20260810 批根因修复 Part 2 — 后端自动 resume（对所有 agent）：stage 未
        # 显式传 resume_session_id 时，若本 (agent, branch_label) 的 sidecar 存在
        # （= 上一迭代会话被切/崩溃未 clean finish，Part 1 保留），自动续跑同一
        # session（程序化"继续"），不 fresh restart 丢进度。与 codegen 显式 resume
        # 同键同源；sidecar 生命周期门控：自然结束已删 sidecar → 不触发，行为不变；
        # resume-degrade（session gone/expired）→ fresh 由既有路径兜底。
        # review M2：键含 stage_name——不同 stage 复用同 agent 时构造性分离，
        # 前任务被切留的 sidecar 不会被后一不同任务误 resume。
        _resume_fails = 0   # 连续失败的 resume 次数（退化 spawn 阈值）
        if not resume_session_id:
            _sc = self._session_sidecar_path(agent_name, branch_label, stage_name)
            if _sc is not None and _sc.exists():
                import json as _json
                try:
                    _data = _json.loads(
                        _sc.read_text(encoding="utf-8"))
                    _sid = _data.get("session_id", "") or ""
                    _fails = int(_data.get("resume_fails", 0) or 0)
                except Exception:  # noqa: BLE001 — corrupt sidecar → fresh spawn
                    _sid, _fails = "", 0
                if _sid:
                    if _fails >= self._resume_attempts:
                        # resume 连续失败 N 次 → 退化 spawn（Phase 2）：清 sidecar，
                        # 下走 fresh 分支，全新 session + 全量 prompt。
                        self._clear_session_sidecar(agent_name, branch_label,
                                                    stage_name)
                        Logger.action(
                            "agent_degrade",
                            f"{attribution}{agent_name} resume failed "
                            f"{_fails}x >= resume_attempts "
                            f"{self._resume_attempts}; degrading to fresh spawn")
                    else:
                        resume_session_id = _sid
                        _resume_fails = _fails   # 续写保留计数
                        self._spawn_was_resume = True   # 供外层 spawn 硬超时 bump 判断
                        Logger.action(
                            "agent_resume",
                            f"{attribution}{agent_name} auto-resuming session "
                            f"{_sid} (sidecar present — silent-cut recovery)")
        if resume_session_id:
            active_options = _dc.replace(options, resume=resume_session_id)
            # Part 3: resume_prompt（深修反馈）> 硬切兜底提示（P6：仅上一次 cut
            # 分类为硬切时注入——「先落草稿，再边落边思考」；此处直读 sidecar：
            # sdk 的 sidecar 重写发生在流内 session 捕获时，路由在前不受消费影响）
            # > 默认「继续」。首次 fresh 执行零注入。
            if resume_prompt:
                active_prompt = resume_prompt
            elif self._read_sidecar_cut_hard(agent_name, branch_label,
                                             stage_name):
                active_prompt = _HARD_CUT_RESUME_PROMPT
            else:
                active_prompt = _RESUME_PROMPT
            Logger.action(
                "agent_resume",
                f"{attribution}{agent_name} resuming session {resume_session_id} "
                f"(cross-run resume)")
        else:
            active_prompt = initial_prompt
            active_options = options
        prev_artifacts = self._count_files(effective_cwd)
        try:
            while True:
                attempt += 1
                prev_response_len = len(consumer.full_response)
                crashed = False
                _stderr_lines.clear()  # fresh stderr window per attempt
                # Per-attempt stall reset: each query (incl. resume) is a fresh
                # stream, so consecutive-no-progress counting starts over. The
                # consumer's persistent signals (turn_count/full_response/
                # session_id/truncated_turns/last_result_text) survive — they
                # accumulate across resume attempts exactly as the old locals did.
                consumer.reset_stall()
                _stall_break = False  # P6: mark intentional stall-break for aclose() guard
                _turn_stall_tripped = False  # wall-clock 看门狗触发标志（每 attempt 重置）
                try:
                    async for event in self._stream_with_turn_stall(
                            query, active_prompt, active_options):
                        # native → IR; the consumer owns ALL signal extraction
                        # (session_id/stop_reason/turn_count/stall) and stamps the
                        # canonical turn onto the record (step-68 task 10).
                        ir = _serialize_event(event)
                        consumer.consume(ir)
                        # Proposal #1: flush session_id to the sidecar the instant
                        # it is captured — before any crash or hard kill can occur
                        # — so a later resume can re-enter this session.
                        # consumer.session_id is stable within a spawn (resume
                        # reuses the same id), so a single flush on first capture
                        # is sufficient; the flag resets on resume-degrade below.
                        if consumer.session_id and not _session_id_written:
                            self._write_session_sidecar(
                                agent_name, branch_label, consumer.session_id,
                                stage_name=stage_name, resume_fails=_resume_fails)
                            _session_id_written = True
                            Logger.action("agent_session",
                                          f"{agent_name} session_id={consumer.session_id}")
                        # Persist the IR record verbatim (transcript = IR).
                        self._write_transcript_record(transcript, ir, agent_name)
                        # Per-turn progress visibility (assistant messages only).
                        if ir.get("role") == "assistant":
                            _block_types: set[str] = set()
                            for b in ir.get("blocks", []) or []:
                                kind = b.get("kind")
                                if kind in ("text", "thinking"):
                                    _block_types.add(kind)
                                elif kind == "tool_use":
                                    _block_types.add(f"tool:{b.get('tool_name', '')}")
                            # Render block-type tag so adjacent text→tool turns
                            # are distinguishable even when chars stay flat.
                            type_tag = ",".join(sorted(_block_types))
                            elapsed = int(time.time() * 1000) - start_ms
                            # §P7.4: don't render "turn N/eff_max_turns" — the SDK
                            # does NOT hard-cap the streamed assistant-message count
                            # at max_turns (one query routinely streams more, e.g.
                            # "turn 23/15"), so a fraction falsely implies a hard
                            # ceiling the numerator obeys. Show the running turn and
                            # label max_turns as a budget, not a denominator. The
                            # cumulative count (across resume attempts) is the
                            # honest progress signal; note the attempt when resumed.
                            turn_label = f"turn {consumer.turn_count} (budget {eff_max_turns}/query"
                            if attempt > 1:
                                turn_label += f", attempt {attempt}"
                            turn_label += f", {type_tag})" if type_tag else ")"
                            Logger.action("agent_stream",
                                          f"{attribution}{agent_name} {turn_label}, "
                                          f"{len(consumer.full_response)} chars, "
                                          f"{elapsed / 1000:.1f}s")
                        # Stall decision: the consumer accounts consecutive
                        # no-progress assistant turns; the literal break stays
                        # here (can't break from a method). §P7.3: all signals
                        # are content-based, never wall-clock — a slow relay
                        # taking minutes per turn is progress, not a stall.
                        if consumer.should_stop:
                            Logger.warn(
                                f"Agent {agent_name} stalled: stopping early and "
                                f"collecting existing output.")
                            _stall_break = True
                            break
                except _SdkTurnStallAbort as e:
                    # wall-clock turn-stall：网关静默（无 stream 事件）超过
                    # turn_stall_s → 非 logic failure、非普通 crash。标记后走
                    # clean-finish 路径（不 retry/backoff——对着沉默网关重试是空转），
                    # 最终产生 aborted="turn_stall" → infra（短路由迭代 + resume）。
                    _turn_stall_tripped = True
                    _stall_break = True
                    Logger.warn(f"Agent {agent_name} turn-stall: {e}")
                except Exception as e:  # noqa: BLE001 — one query attempt crashed
                    # P6: stall-break causes async generator aclose() to race with
                    # background task → RuntimeError "asynchronous generator is
                    # already running". The stall detection already stopped cleanly;
                    # this is cleanup noise, not a real crash. Treat as non-crashed
                    # so the salvage+collect path runs and the caller sees "partial".
                    if (_stall_break and isinstance(e, RuntimeError)
                            and any(m in str(e) for m in _ACLOSE_ERROR_MARKERS)):
                        Logger.warn(
                            f"Agent {agent_name} stall aclose race (non-fatal): {e}")
                        # stay crashed=False; let the clean-finish path below run
                    else:
                        crashed = True
                        last_exc = e
                        detail = (f": {consumer.last_result_text}"
                                  if consumer.last_result_text else "")
                        Logger.error(
                            f"Agent {agent_name} query attempt {attempt} "
                            f"failed: {e}{detail}")

                # —— Gate evaluation (step-5a D5/D6) ——
                # Progress = new response text OR new product files this attempt
                # (tool_use already grew full_response or wrote files). The
                # product snapshot here doubles as the completion signal (D5).
                cur_artifacts = self._count_files(effective_cwd)
                made_round_progress = (
                    len(consumer.full_response) > prev_response_len
                    or cur_artifacts > prev_artifacts)
                prev_artifacts = cur_artifacts

                if not crashed:
                    break  # clean finish — done (artifacts collected below)
                # Proposal #1: cross-run resume degrade — this spawn began by
                # resuming a prior session and the very first query reports that
                # session gone/expired (TTL lapsed / transcript unavailable).
                # Abandon resume and restart fresh. One-shot (attempt 1 only) so
                # a genuine mid-run crash still salvages normally. The stage
                # never sees the failed resume — degrade is internal (§D2) and
                # does not burn the circuit breaker.
                # Enrich with the SDK subprocess stderr (see _on_sdk_stderr):
                # the exception message alone is a generic "Command failed with
                # exit code 1"; the session-gone diagnostic lives only on stderr.
                _exc_text = consumer.last_result_text or (
                    str(last_exc) if last_exc else "")
                _crash_text = "\n".join(
                    s for s in (_exc_text, "\n".join(_stderr_lines)) if s)
                if (resume_session_id and attempt == 1
                        and _is_session_gone(_crash_text)):
                    Logger.warn(
                        f"Agent {agent_name} resume session {resume_session_id} "
                        f"unavailable (gone/expired); degrading to fresh spawn.")
                    self._clear_session_sidecar(agent_name, branch_label,
                                                stage_name=stage_name)
                    consumer.clear_session()  # fresh spawn captures a new id
                    _session_id_written = False
                    resume_session_id = None
                    active_prompt = initial_prompt
                    active_options = options
                    attempt = 0
                    no_progress = 0
                    continue
                # step-57 (P80): 429 burst rate-limit — sleep (exponential
                # backoff) then resume the SAME session with "继续", on an
                # INDEPENDENT budget (not the SSE no_progress gate: a rejected
                # 429 turn is zero-progress and would trip it on the first hit).
                # Burst-vs-hard-quota is not distinguished by wording — a true
                # quota simply exhausts the total-time cap and halts. Logging
                # happens BEFORE the sleep and the run.log handle flushes per
                # write (Logger._emit + thread-local bind_run_log), so the retry
                # trail survives even a SIGKILL during the sleep — nothing is
                # lost (user requirement).
                _strategy = server_backoff_strategy(_crash_text)
                if _strategy is not None and not _is_transient_error(_crash_text):
                    # 黑名单排除语义（_shared 单一来源，§2.5）：非 infra 服务端错误
                    # （429/503/APIError/type validation/未知）→ 有限次 in-session
                    # resume。判定基于 _crash_text（last_result_text or last_exc +
                    # stderr）而非裸 last_result_text——SDK 内部失败时 last_result_text
                    # 可能含正常文本，崩溃上下文更可靠承载错误措辞。排除
                    # _is_transient_error（SSE 流故障）——transient 走下方 D2 立即
                    # resume（20260812 空等回归实证）。恢复策略经 server_backoff_strategy
                    # 区分：429/503 → backoff sleep 等窗口；其他非 infra → 立即 resume
                    # 不 sleep（误判时空等风险低，只浪费一次重试预算）。
                    if _strategy == "backoff":
                        sleep_s, rl_attempt, rl_elapsed_s = advance_backoff(
                            rl_attempt, rl_elapsed_s,
                            base_s=self._rl_backoff_base_s,
                            factor=self._rl_backoff_factor,
                            max_total_s=self._rl_backoff_max_total_s,
                            max_retries=self._rl_max_retries)
                        if sleep_s is None or not consumer.session_id:
                            _why = ("no session_id to resume"
                                    if not consumer.session_id
                                    else f"backoff exhausted "
                                         f"(attempts={rl_attempt}, "
                                         f"waited={rl_elapsed_s:.0f}s / "
                                         f"cap={self._rl_backoff_max_total_s:.0f}s)")
                            # P131b: 判定统一，但诊断保留类别词
                            # （429 burst→hard quota 与 503/APIError→halt 不 conflate）。
                            _is_429 = _is_rate_limit_error(_crash_text)
                            Logger.warn(
                                f"Agent {agent_name} "
                                f"{'429 rate-limit' if _is_429 else 'server error'}: "
                                f"{_why}; treating as "
                                f"{'hard quota' if _is_429 else 'hard failure'} → halt.")
                            _quota_suffix = (
                                f" [{'step-57: 429 burst backoff exhausted' if _is_429 else 'server-error backoff exhausted'} "
                                f"after {rl_attempt} attempt(s), {rl_elapsed_s:.0f}s "
                                f"total wait → {'hard quota' if _is_429 else 'halt'}: "
                                f"{str(consumer.last_result_text)[:120]}]")
                            # failure_reason downstream reads _crash_text (the single
                            # _build_result factory reads crash_reason, not
                            # consumer.last_result_text — N1, step-68 review), so the
                            # exhausted backoff cause must be enriched here or the halt
                            # reason would drop it.
                            _crash_text = (_crash_text or "") + _quota_suffix
                            break
                        Logger.action(
                            "agent_backoff",
                            f"{attribution}{agent_name} rate-limit/unavailable; sleeping "
                            f"{sleep_s:.0f}s then resuming session {consumer.session_id} "
                            f"(attempt {rl_attempt}/{self._rl_max_retries}, "
                            f"cumulative wait {rl_elapsed_s:.0f}s / "
                            f"{self._rl_backoff_max_total_s:.0f}s)")
                        await asyncio.sleep(sleep_s)
                    else:  # "resume" — 立即续跑同一会话，不 sleep（20260812 根治）。
                        # 与 backoff 共享 rl_attempt 预算：总重试有界是有意设计
                        # （review f7c7a88e #1），backoff 额外受 max_total 封顶。
                        rl_attempt += 1
                        if rl_attempt >= self._rl_max_retries or not consumer.session_id:
                            _why = ("no session_id to resume"
                                    if not consumer.session_id
                                    else f"resume exhausted "
                                         f"(attempts={rl_attempt}/{self._rl_max_retries})")
                            Logger.warn(
                                f"Agent {agent_name} server error: {_why}; "
                                f"treating as hard failure → halt.")
                            _quota_suffix = (
                                f" [server-error resume exhausted after "
                                f"{rl_attempt} attempt(s) → halt: "
                                f"{str(consumer.last_result_text)[:120]}]")
                            _crash_text = (_crash_text or "") + _quota_suffix
                            break
                        Logger.action(
                            "agent_resume",
                            f"{attribution}{agent_name} server error; immediately "
                            f"resuming session {consumer.session_id} "
                            f"(attempt {rl_attempt}/{self._rl_max_retries})")
                    active_options = _dc.replace(options, resume=consumer.session_id)
                    active_prompt = _RESUME_PROMPT   # "继续"
                    continue
                if not _is_transient_error(consumer.last_result_text):
                    break  # non-transient logic failure — do not retry (D2)
                # Transient crash: decide whether to resume.
                if made_round_progress:
                    no_progress = 0
                else:
                    no_progress += 1
                if attempt > _max_retries or no_progress >= _max_no_progress:
                    Logger.warn(
                        f"Agent {agent_name} giving up after {attempt} attempts "
                        f"(no_progress={no_progress}, budget={_max_retries}).")
                    break
                if not consumer.session_id:
                    Logger.warn(
                        f"Agent {agent_name} transient crash but no session_id "
                        f"captured; cannot resume.")
                    break
                # Resume the crashed session and continue (mirrors TUI "继续").
                active_options = _dc.replace(options, resume=consumer.session_id)
                active_prompt = _RESUME_PROMPT
                Logger.action(
                    "agent_resume",
                    f"{agent_name} resuming session {consumer.session_id} "
                    f"(attempt {attempt + 1}/{_max_retries + 1})")
        finally:
            if transcript is not None:
                try:
                    transcript.close()
                except Exception:  # noqa: BLE001
                    pass

        # M2（review 整改）: 判切「现在」时刻 = 流结束（消息循环退出）当场
        # 采样并显式传入——与 opencode 侧同一测量口径（实证标定基线），
        # 不依赖「分类点恰好紧邻流结束」这一时序巧合。
        _stream_end_ts = time.time()

        # Proposal #1: clean finish (not crashed) → the session completed and is
        # no longer resumable. Clear the sidecar so a later resume does not
        # re-enter a finished session. A crash leaves the sidecar in place —
        # that is the resume handle (covers graceful crash AND hard kill, since
        # the sidecar was flushed at capture above).
        # 20260810 批根因修复 Part 1 — silent cut：一个"clean finish"若末条
        # assistant 消息不可行动（只有 thinking、无 text、无 tool_use），是第三方
        # 网关静默切流（"一段吐字后突然中断"），不是自然结束。此时保留 sidecar
        # （Part 2 自动 resume 下一迭代续跑）并把结果标 cut（Part 3 计数用）；
        # 自然结束（有 text/tool）照旧清 sidecar → fresh spawn，行为不变。
        # F4（20260821 无效 resume 计数）：本次 spawn 是 resume 且又 cut →
        # "这次恢复尝试无效"——bump resume_fails。连续无效 resume 达
        # resume_attempts 后既有 agent_degrade 路径退化 fresh（全量 prompt 重开），
        # 不再无限 resume 同一 thinking 泥潭 session。fresh 首跑的 cut 不计数
        # （首次 cut 先原地 resume，对齐"同一 session resume 符合预期"）。
        _cut = (not crashed and not getattr(
            consumer, "_last_turn_actionable", True))
        # P6 硬切分类（与 OpenCodeBackend 对称——classify_cut 单点，判据同源）：
        # sdk 的 IR 记录即流内事件，consumer 的实时累计就是证据（到达时刻真实）。
        # 无思考流证据 → 分类 None → 走未知中断原路径。
        _cut_facts = None
        _cut_hard = False
        if _cut:
            _cls = classify_cut(
                consumer.thinking_chars, consumer.last_thinking_ts,
                gap_threshold_s=self._thinking_active_gap_s,
                now=_stream_end_ts)
            if _cls is not None:
                _cut_facts, _cut_hard = _cls
                _cut_facts["attempt_duration_s"] = round(
                    (time.time() * 1000 - start_ms) / 1000, 1)
            # 分类单点写入 sidecar（soft 显式 False；下一次 spawn 路由此读）。
            self._set_sidecar_cut(agent_name, branch_label, stage_name,
                                  _cut_facts, _cut_hard)
        if not crashed and not _cut:
            self._clear_session_sidecar(agent_name, branch_label,
                                        stage_name=stage_name)
        elif _cut and not _cut_hard and (self._spawn_was_resume
                                         or resume_session_id):
            # 硬切不 bump（P6，与 OpenCodeBackend 对称）：resume_attempts=3 是
            # 未知中断试探语义；硬切恢复走兜底提示路由，上限归 runner cut_streak。
            _fails_now = self._bump_session_resume_fails(
                agent_name, branch_label, stage_name)
            Logger.warn(
                f"{attribution}{agent_name} resume 后仍 silent-cut（无效 resume，"
                f"连续 {_fails_now}/{self._resume_attempts}）；达阈后下次 spawn "
                f"退化 fresh")

        # —— Loop exited. If turn-stall tripped, report as infra abort. ——
        # 网关静默（无 stream 事件）超过 turn_stall_s：不是 logic failure，也不是
        # 可重试的 transient——是「被看门狗杀死」，用 aborted="turn_stall" 显式标
        # 记（_build_result 里 aborted 非空 → error_type="infra"，短路由迭代 +
        # node_status failed + resume 重跑）。区别于上方 crash-salvage 的 retry/
        # backoff 路径（对着沉默网关重试是空转）。
        if _turn_stall_tripped:
            artifacts = self._collect_artifacts(effective_cwd, repo_baseline,
                                                repo_root)
            return self._build_result(
                agent_name, consumer=consumer, crashed=True,
                crash_reason=(f"no stream event for {self._turn_stall_s:.0f}s "
                              f"(turn-stall; gateway silent)"),
                artifacts=artifacts, transcript_path=transcript_path,
                attempt=attempt, start_ms=start_ms, aborted="turn_stall")

        # —— Loop exited. If the last attempt crashed, salvage + report. ——
        if crashed:
            # Agent may have written files before crashing. Collect them, but
            # never report "ok": the query raised. The single _build_result
            # factory decides partial (crashed+artifacts) vs fatal (crashed, no
            # artifacts) and injects session_id/truncated_turns/error_type/
            # failure_reason uniformly (step-68 task 10).
            artifacts = self._collect_artifacts(effective_cwd, repo_baseline,
                                                repo_root)
            return self._build_result(
                agent_name, consumer=consumer, crashed=True,
                crash_reason=_crash_text, artifacts=artifacts,
                transcript_path=transcript_path, attempt=attempt,
                start_ms=start_ms,
                error_type_override=classify_spawn_exception(last_exc, _crash_text))

        # Check if agent triggered a pending decision (on_decision="abort")
        if self._decision_workspace:
            pending_path = self._decision_workspace / "pending_decision.json"
            if pending_path.exists():
                from ascendc_devkit.domain.exceptions import DecisionPendingError
                import json
                data = json.loads(pending_path.read_text())
                raise DecisionPendingError(
                    question=data.get("question", ""),
                    options=data.get("options", []),
                    workspace_dir=str(self._decision_workspace),
                )

        # Primary: collect the run's changed files (self-report ∪ git diff,
        # degrading to a direct working_dir read when no baseline/git exists).
        artifacts = self._collect_artifacts(effective_cwd, repo_baseline,
                                            repo_root)
        return self._build_result(
            agent_name, consumer=consumer, crashed=False, crash_reason=None,
            artifacts=artifacts, transcript_path=transcript_path,
            attempt=attempt, start_ms=start_ms, cut=_cut,
            cut_facts=_cut_facts, cut_hard=_cut_hard)
