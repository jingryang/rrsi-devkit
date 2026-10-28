"""L5 Capabilities — OpenCode agent backend (D1–D4).

The second concrete ``AgentBackend`` alongside ``SDKBackend``. Where the claude
backend drives the model in-process via ``claude_agent_sdk.query()``, opencode
has no Python binding — the only driver is an ``opencode serve`` subprocess
spoken to over HTTP. This backend implements the SAME ``spawn`` contract on top
of that transport, so the orchestration runs identically on either SDK.

Design (frozen L3/L4 + Gate 2.0 findings):

  D1 — Transport: one short-lived ``opencode serve`` per spawn. Per-spawn config
       (agent projection, MCP env, model, permissions) is written to a file and
       named via the ``OPENCODE_CONFIG`` env path — a runtime layer merged over
       the project ``opencode.json``. (The inline ``OPENCODE_CONFIG_CONTENT`` env
       cannot carry it: the D3 agent projections push the config past the Linux
       128KB ``MAX_ARG_STRLEN`` per-env-string cap.) Provider credentials are
       kept out of that file — they travel as ephemeral serve-env vars, referenced
       by ``{env:VAR}`` placeholders. Start serve → poll health → create session →
       POST the (blocking) message → collect artifacts → stop serve.

  D2 — Skill injection rendered natively: opencode does NOT expand ``/<skill>``.
       The assigned ``primary_skill`` becomes a SYSTEM steer ("first call
       skill({name})", ``render_opencode_skill_steer``) plus a global
       ``permission.skill: "allow"`` (Gate 2.0: a closed skill glob DROPS the
       skill tool, so we allow-all and rely on the steer + §3.10 bounded retry).

  D3 — Subagent projection: ``.claude/agents/*.md`` → opencode ``agent`` config
       blocks (opencode discovers skills natively but NOT ``.claude/agents/``).
       The spawned agent is the primary; the rest are subagents it can dispatch.

  D4 — resolve_ambiguity as a stdio MCP: ``mcp.engine`` runs
       ``python -m ascendc_devkit.capabilities.engine_mcp_stdio`` with per-spawn
       params passed through ``environment`` (the shared SDK-agnostic handler).

Correctness note: ``POST /session/:id/message`` BLOCKS and returns the full
``{info, parts}``. That return is the completion signal — this backend does NOT
depend on parsing opencode's SSE event vocabulary. Artifacts are collected from
the filesystem the agent wrote to (``_collect_artifacts``, shared with claude),
so both backends surface identical product semantics.

The SDK-specific event loop (start/poll/session/message/stop) lives here; every
backend-neutral concern (transcript sink, session sidecar, product collection)
is inherited from ``BaseAgentBackend``.
"""

from __future__ import annotations

import atexit
import copy
import json
import os
import signal
import socket
import sqlite3
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
import re

from .backend import AgentResult
from .base_backend import BaseAgentBackend, IRConsumer, classify_cut
from ._shared import (
    _find_agent_prompt,
    _strip_frontmatter,
    render_opencode_skill_steer,
    _is_opencode_session_gone,
    _classify_error_type,
    classify_spawn_exception,
    server_backoff_strategy,
    advance_backoff,
    _RESUME_PROMPT,
    _HARD_CUT_RESUME_PROMPT,
    _ensure_skills_anchor,
    format_attribution,
)
from .opencode_sse import (
    _part_to_block,
    parse_sse_frames,
    event_session_id,
    event_tokens,
    is_session_compacted,
)
from ascendc_devkit.infra.logger import Logger
from ascendc_devkit.infra.log_capture import spawn_context_thread
from ascendc_devkit.domain.exceptions import ConfigError

# claude tool name → opencode permission key. opencode keys its permission map by
# tool name (see permissions.mdx): read/edit/write/bash/glob/grep/skill/task/
# question/webfetch/websearch/todowrite. We translate the manifest's
# allowed/disallowed_tools (claude vocabulary) into this space.
_TOOL_PERM_KEY = {
    "Read": "read", "Edit": "edit", "Write": "write", "Bash": "bash",
    "Glob": "glob", "Grep": "grep", "Skill": "skill", "Task": "task",
    "AskUserQuestion": "question", "WebFetch": "webfetch",
    "WebSearch": "websearch", "TodoWrite": "todowrite",
}

_ENGINE_MCP_MODULE = "ascendc_devkit.capabilities.engine_mcp_stdio"


# S4 (hard-timeout): track every live ``opencode serve`` subprocess so an atexit
# backstop can stop any still alive on interpreter exit (a spawn interrupted
# mid-flight never reaches ``_stop_serve`` → without this the serve + its engine
# MCP child would orphan). Populated by ``_start_serve``, drained by ``_stop_serve``.
_ACTIVE_SERVE_PROCS: set = set()


def _cleanup_serve_proc(proc) -> None:
    """Stop a serve proc AND its whole process group (serve + engine MCP child).

    ``_start_serve`` uses ``start_new_session=True`` so the serve becomes a
    session/group leader; ``os.killpg`` then reaches its children too (the engine
    MCP stdio subprocess) — ``proc.terminate()`` alone only hits the serve,
    orphaning the child. SIGTERM → wait 5s → SIGKILL escalation. Module-level so
    the atexit backstop can call it without a backend instance. Best-effort:
    swallows all errors (runs at interpreter exit where logging is unreliable;
    the serve-log file retains opencode's own output for post-mortem)."""
    try:
        pgid = os.getpgid(proc.pid)
    except Exception:  # noqa: BLE001 — proc already reaped / fake proc in UT
        pgid = None
    try:
        if pgid is not None:
            try:
                os.killpg(pgid, signal.SIGTERM)
            except Exception:  # noqa: BLE001
                pass
            try:
                proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                try:
                    os.killpg(pgid, signal.SIGKILL)
                except Exception:  # noqa: BLE001
                    pass
        else:
            # Fallback (e.g. a UT fake proc not started in a new session).
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:  # noqa: BLE001
                    proc.kill()
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass
    # P-BC2 fd hygiene: close the serve-log handle opened in _start_serve.
    handle = getattr(proc, "serve_log_handle", None)
    if handle is not None:
        try:
            handle.close()
        except Exception:  # noqa: BLE001
            pass


def _atexit_cleanup_serve_procs() -> None:
    """atexit backstop: stop any serve proc still alive on interpreter exit."""
    for proc in list(_ACTIVE_SERVE_PROCS):
        _cleanup_serve_proc(proc)
    _ACTIVE_SERVE_PROCS.clear()


atexit.register(_atexit_cleanup_serve_procs)


class _KeepaliveAbort(RuntimeError):
    """P-BC3: the keepalive/hard-timeout watchdog aborted a blocking message
    POST. Raised by ``_post_message_watched`` when SSE liveness goes idle or the
    hard wall-clock cap is hit; spawn's crash-salvage turns it into an actionable
    fatal (no more 1h空烧 waiting on ``message_timeout``).

    §P9: carries ``kind`` — the TRUE control-flow reason ("turn_stall" /
    "keepalive" / "hard_timeout" / "gateway_stream_error"[P16 证据速杀]) — so
    the crash-salvage ``aborted=`` label never masquerades one kill reason as
    another (§1.10)."""

    def __init__(self, message: str, kind: str = "hard_timeout"):
        super().__init__(message)
        self.kind = kind


def _abort_kind(e: BaseException) -> str | None:
    """§P9: the honest ``aborted=`` label for a spawn exception — the watchdog
    kill's own kind, or "hard_timeout" for a POST socket timeout (the socket
    backstop racing the watchdog, belt-and-suspenders). None when the exception
    is not a hard termination (logic failure — no aborted label). Replaces the
    old ``_is_hard_timeout_exc`` that lumped turn_stall/keepalive kills into
    "hard_timeout" (one error masquerading as another)."""
    if isinstance(e, _KeepaliveAbort):
        return e.kind
    if isinstance(e, TimeoutError):
        return "hard_timeout"
    reason = getattr(e, "reason", None)
    if isinstance(reason, TimeoutError):
        return "hard_timeout"
    return None


class OpenCodeBackend(BaseAgentBackend):
    """Agent backend driving an ``opencode serve`` subprocess over HTTP.

    Matches ``AgentBackend.spawn`` 1:1. The HTTP/serve seams
    (``_pick_free_port`` / ``_start_serve`` / ``_wait_healthy`` / ``_http_json`` /
    ``_stop_serve``) are small overridable methods so a UT can drive the full
    spawn against a simulated server with no real subprocess.
    """

    def __init__(self, interactive: bool = False,
                 on_decision: str = "default",
                 decision_workspace: Path | str | None = None,
                 webhook_url: str | None = None,
                 working_dir: Path | str | None = None,
                 artifacts_ignore: list[str] | None = None,
                 model: str | None = None,
                 disallowed_tools: list[str] | None = None,
                 opencode_bin: str = "opencode",
                 host: str = "127.0.0.1",
                 serve_startup_timeout: float = 30.0,
                 spawn_attempts: int = 3,
                 spawn_retry_backoff_s: float = 1.5,
                 message_timeout: float = 3600.0,
                 project_config_path: Path | str | None = None,
                 rate_limit_max_retries: int = 6,
                 rate_limit_backoff_base_s: float = 30.0,
                 rate_limit_backoff_factor: float = 2.0,
                 rate_limit_backoff_max_total_s: float = 600.0,
                 keepalive_idle_s: float = 600.0,
                 keepalive_poll_s: float = 10.0,
                 # P117 route C: opencode can't be modified (unbounded session-
                 # layer retry + silent-swallow of gateway errors), so the
                 # framework stops a hung spawn via a turn-stall gate: no new
                 # turn for this long → trip (0 disables). The trip reason
                 # carries the stalled turn's number + active block types (e.g.
                 # tool:read) so an operator knows what the agent was doing when
                 # it stalled. message_timeout (above) is the configurable hard
                 # cap (0 = disabled). Defaults mirror
                 # runtime_config.opencode_timeouts(); the dispatcher threads
                 # config values in, these are the code fallbacks.
                 # step-115 (P16)：300→180，与 sdk 构造默认/config 统一（原三值
                 # 漂移）；语义=无证据静默的残差兜底（分型见 gateway_error_probe_s）。
                 turn_stall_s: float = 180.0,
                 # §step-97 (docs/plan/turn-stall-pretrip-evidence/): pre-trip
                 # 取证后的工具容忍界——判死前查本 spawn 的 opencode db，最新
                 # tool part status=running ⇒「工具在飞」（SSE 静默是预期的，
                 # 复位不判死）；running 超过本界 ⇒ 工具挂死，杀**工具进程树**
                 # 而非 serve（opencode 把工具错误交还 agent，会话/上下文/工作
                 # 树全保住）。0 = 禁用杀工具（running 只复位）。
                 tool_grace_s: float = 1800.0,
                 # 退化 spawn 设计（docs/plan/turn-stall-resume-escalation/）：turn-stall 后
                 # 先原地 resume（续同一 session，满窗 turn_stall_s），连续失败
                 # resume_attempts 次后退化 spawn（清 sidecar + fresh 新 session）。
                 # 须 < infra_retry_max_retries 才有预算内的一发 fresh（加载期校验）。
                 resume_attempts: int = 3,
                 # P6 硬切分类判据：末次 thinking 增量距截断 ≤ 此秒数 = 思考流
                 # 仍活跃（外部输出墙形态）。网关 flush 粒度行为参数，默认来自
                 # runtime_config.retry_budgets().thinking_active_gap_s。
                 thinking_active_gap_s: float = 0.6,
                 # step-115 (P16)：阳性网关错误证据探针——chars 静止超过该值后
                 # 读本 spawn scratch 的 opencode app log，发现晚于静默起点
                 # 的 stream error → 立即 trip（gateway_stream_error，<1min 出局
                 # vs 残差界满窗）。0 = 禁用。每 poll 直读证据（无节流——
                 # 15s 节流已删，设计中途移除，L4 17 号文档同口径）。
                 gateway_error_probe_s: float = 30.0,
                 # P13 (step-116)：op 级 NPU 卡号——写进 serve 子进程 env 的双变量
                 # pin（ASCEND_RT_VISIBLE_DEVICES=<物理卡>+ASCEND_NPU_ID=0），
                 # bash 工具子树默认继承即被结构性锁卡。None=不 pin（无 NPU 语境）。
                 card_pin: int | None = None):
        super().__init__(decision_workspace=decision_workspace,
                         artifacts_ignore=artifacts_ignore)
        self._card_pin = card_pin
        self._interactive = interactive
        self._on_decision = on_decision
        self._webhook_url = webhook_url
        self._working_dir = Path(working_dir) if working_dir else None
        # Default model override (used when neither the spawn arg nor the
        # project opencode.json names one).
        self._model = model
        # Leaf-agent tools denied by default (mirrors SDKBackend: no Task /
        # AskUserQuestion for a plain leaf). Manifest disallowed_tools add to it.
        self._disallowed_tools = disallowed_tools or ["Task", "AskUserQuestion"]
        self._opencode_bin = opencode_bin
        self._host = host
        self._serve_startup_timeout = serve_startup_timeout
        # P-BC5: bounded serve-startup retry. opencode-serve shares one global
        # SQLite DB ($XDG_DATA_HOME/opencode, kept for global config/auth
        # discovery). Under parallel spawn (e.g. design anchor fork-join T1/T2/T3)
        # concurrent serves contend on the DB lock → "database is locked" → one
        # serve crashes before binding → Connection refused for the full startup
        # window. Probe-reproduced (~2% at N=10). Per §3.10 a bounded retry
        # absorbs this transient: kill the crashed serve, fresh port + config,
        # back off, respawn. Data-dir isolation would break the global-auth
        # invariant (§_cfg_scratch_dir), so retry — not isolation — is the fix.
        self._spawn_attempts = max(1, spawn_attempts)
        self._spawn_retry_backoff_s = spawn_retry_backoff_s
        self._message_timeout = message_timeout
        self._project_config_path = (
            Path(project_config_path) if project_config_path else None)
        # step-57 (P80): 429 burst backoff-resume budget (parity with SDKBackend).
        self._rl_max_retries = rate_limit_max_retries
        self._rl_backoff_base_s = rate_limit_backoff_base_s
        self._rl_backoff_factor = rate_limit_backoff_factor
        self._rl_backoff_max_total_s = rate_limit_backoff_max_total_s
        # P-BC3: keepalive watchdog around the blocking POST. ``keepalive_idle_s``
        # = max gap between SSE frames before the agent is deemed hung (the SSE
        # stream is the only liveness signal — the POST socket is byte-idle for
        # the whole turn). 600s default tolerates long single tool calls (compile
        # / test) while still catching a true hang in minutes, not the
        # ``message_timeout`` hour. ``message_timeout`` remains the hard wall-clock
        # backstop (trips if the SSE watchdog itself fails). Both configurable.
        self._keepalive_idle_s = keepalive_idle_s
        self._keepalive_poll_s = keepalive_poll_s
        # P117 route C (see runtime_config.opencode_timeouts).
        self._turn_stall_s = turn_stall_s
        # §step-97: pre-trip 取证的工具容忍界（见 __init__ docstring）。
        self._tool_grace_s = max(0.0, float(tool_grace_s))
        # resume 连续失败退化的阈值（见 runtime_config.infra_backoff().resume_attempts）。
        self._resume_attempts = max(1, int(resume_attempts))
        # P6 硬切分类 gap 判据阈值（见 __init__ docstring；构造注入 §1.6）。
        self._thinking_active_gap_s = max(0.0, float(thinking_active_gap_s))
        # step-115 (P16)：阳性网关错误证据探针起始静默时长（0 = 禁用）。
        self._gateway_error_probe_s = max(0.0, float(gateway_error_probe_s))

    # —— spawn (the D1 event loop) ————————————————————————————————————————

    # —————————————————————————————————————————————————————————————————————————
    # Streaming observability (design B, L4 03-impl-streaming.md)
    # —————————————————————————————————————————————————————————————————————————
    # A daemon GET /event reader runs concurrently with the blocking POST,
    # surfacing each turn's parts as ``agent_stream`` Logger lines in real time
    # (the user's core ask) + capturing tokens for an opportunistic metrics fill.
    # Pure observability: the blocking POST + 429/resume-degrade logic remains
    # the correctness/retry authority (unchanged). SSE and POST serve different
    # responsibilities, so this is single-path-per-responsibility (§2.5), not a
    # dual transport for one concern.
    def _new_sse_log_state(self) -> dict:
        return {"turn": 0, "chars": 0, "block_types": set(),
                "tokens": None, "current_role": None,
                # P-BC3 keepalive baseline: updated on every parsed SSE frame in
                # _subscribe_sse's reader. The blocking-POST watchdog reads this
                # to tell a working agent (frames flowing) from a dead one.
                "last_event_ts": time.time(),
                # P117 route C (B): turn-stall backstop. Stamped when turn bumps
                # (message.updated role=user in _handle_sse_event); the POST
                # watchdog trips if no new turn for turn_stall_s (0 disables).
                "turn_ts": time.time(),
                # P6 硬切分类证据（判切点读取）：reasoning 增量的实时按步累计 +
                # 末次到达时刻。SSE 增量流是 opencode 侧唯一带真实到达时刻的
                # 思考信号（transcript 是 POST 后回读，时刻失真不可用于 gap）。
                "step_reasoning_chars": 0,
                "last_reasoning_delta_ts": None,
                # P6 分型表（partID → IR kind）：delta.field 恒 "text"（指 part
                # 属性名，text/reasoning part 同名——binary 实证，见
                # docs/plan/opencode-cut-classification/01-problems.md F3），
                # 思考流分型只能按 partID 关联 message.part.updated 先行的
                # part 类型标记。生命周期对齐 step_reasoning_chars（step-start
                # /换轮清空——跨步跨轮 partID 不串）。
                "part_kinds": {},
                # step-113 (P11-C)：本 spawn 流内观测到的上下文冲刷次数
                # （session.compacted）。spawn 级累计——不随 turn/step 重置，
                # 观测对象是整条流发生了几次，供 metrics `compactions`。
                "compactions": 0}

    def _handle_sse_event(self, event: dict, state: dict, *, session_id: str,
                          agent_name: str, attribution: str, start_ms: int) -> None:
        """Process one parsed SSE event for real-time ``agent_stream`` logging.

        Filters by ``session_id`` (the GET /event bus is global), tracks the
        active message role from ``message.updated``, accumulates char count
        from ``message.part.delta`` (per-token logging would flood run.log),
        and emits one ``agent_stream`` line per completed assistant text/tool
        part — mirroring claude's per-turn block-type visibility (P13). User
        echoes / step markers are skipped (noise). Tokens captured from
        ``message.updated``. Pure except for the Logger side effect, so directly
        unit-testable by monkeypatching ``Logger.action``.
        """
        if not isinstance(event, dict):
            return
        sid = event_session_id(event)
        if sid and session_id and sid != session_id:
            return  # another session's event — bus is global
        etype = event.get("type")
        props = event.get("properties") or {}
        if etype == "message.part.delta":
            # deltas stream only from the model (the user prompt never deltas),
            # so this is unambiguous agent output — accumulate length for the
            # running turn's char count.
            if props.get("field", "text") in ("text", "reasoning"):
                state["chars"] += len(props.get("delta", "") or "")
            # P6 硬切分类证据：delta.field 恒 "text"（指 part 属性名，text/
            # reasoning part 同名——binary 实证，opencode-cut-classification/
            # 01-problems.md F3），分型按 partID 查 part_kinds（由
            # message.part.updated 先行的类型标记维护）。思考流才实时累计体量
            # （按步）+ 打末次到达时刻（gap 判据时间源——到达即打点，不留到
            # 回读）；无标记的 partID 不累计（诚实无证据 → classify_cut None）。
            if (state["part_kinds"].get(props.get("partID"))
                    == "thinking"):
                state["step_reasoning_chars"] += len(props.get("delta", "") or "")
                state["last_reasoning_delta_ts"] = time.time()
            return
        if etype == "message.part.updated":
            # opencode fires message.updated(role) at message COMPLETION, so the
            # role label lags behind the parts (assistant parts stream while the
            # bus still reports the prior user message). We therefore log by
            # BLOCK TYPE, not by message role — tool calls + text/reasoning are
            # the real-time signal the user wants; role would wrongly skip them.
            block = _part_to_block(props.get("part") or {})
            kind = block.get("kind")
            if kind == "step-start":
                # P6：新步重置按步 reasoning 计数（输出墙按步计——写文件/调
                # 工具 = 切步 = 重置单步预算，体量语义同源）。part 类型表随同
                # 清空（表生命周期=步）。若网关不推送 step 标记则退化为按轮
                # 累计（仅影响呈现数值，不影响 gap 判据）。
                state["step_reasoning_chars"] = 0
                state["part_kinds"] = {}
                return
            # P6：part 类型标记（part-start 先行到达、part 完成重发，幂等覆写）
            # ——delta 分型按 partID 查此表（delta.field 恒 "text"，见上）。
            _pid = (props.get("part") or {}).get("id")
            if _pid is not None:
                state["part_kinds"][_pid] = kind
            if kind in ("text", "thinking"):
                state["block_types"].add(kind)
            elif kind == "tool_use":
                state["block_types"].add(f"tool:{block.get('tool_name', '')}")
            else:
                return  # step-start / step-finish / unknown — reduce noise
            self._emit_agent_stream(state, agent_name, attribution, start_ms)
            return
        if etype == "message.updated":
            info = props.get("info") or {}
            role = info.get("role")
            state["current_role"] = role
            if role == "user":
                # new exchange (user prompt / tool-result message) → bump turn +
                # reset accumulators. opencode fires this BEFORE the response's
                # parts stream, so the turn number is correct during streaming
                # (role=assistant lags to completion and only carries tokens).
                state["turn"] += 1
                state["block_types"] = set()
                state["chars"] = 0
                state["step_reasoning_chars"] = 0
                state["part_kinds"] = {}
                # P117 route C (B): a new turn is real progress — stamp the
                # turn-stall baseline so the watchdog resets here, not at the
                # (noise-driven) last_event_ts.
                state["turn_ts"] = time.time()
            tk = event_tokens(event)
            if tk:
                state["tokens"] = tk
            return
        if is_session_compacted(event):
            # step-113 (P11-C)：唯一被消费的 session.* 事件——冲刷计数（进
            # metrics，不打 agent_stream 流水）。
            # R8（review 整改）：session.* 是总线级广播事件，载荷无 sid 即无法
            # 归属到本会话——不计入（防串会话污染），留事实行线索。
            if not sid:
                Logger.action(
                    "agent_compact_unattributed",
                    "session.compacted event carries no session id — "
                    "not counted into this spawn")
                return
            state["compactions"] += 1
            return
        # 其余 session.*/server.*/plugin.* → no logging.

    def _compaction_metrics(self, sse, agent_name: str, attribution: str) -> dict:
        """step-113 (P11-C)：spawn 流内冲刷计数 → ``metrics["compactions"]``。

        SSE 流启动过 → 键恒在（0 也是「有观测、零冲刷」）；SSE 未启动（早夭/
        预 spawn 超时）→ 键缺失，**缺失 ≠ 零冲刷**（无观测，sdk 侧同理由——
        无等价事件，计数单点在 SSE 层，§1.15）。N>0 时事实性日志一行（实测
        数字，无判断词——阈值 WARN 无算术依据，不设）。
        """
        if sse is None:
            return {}
        n = int(sse.state.get("compactions") or 0)
        if n:
            Logger.action(
                "agent_compacted",
                f"{attribution}{agent_name} session compacted x{n} in spawn")
        return {"compactions": n}

    def _emit_agent_stream(self, state: dict, agent_name: str,
                          attribution: str, start_ms: int) -> None:
        types = ",".join(sorted(state["block_types"]))
        elapsed = int(time.time() * 1000) - start_ms
        label = f"turn {state['turn']}"
        if types:
            label += f" ({types})"
        Logger.action("agent_stream",
                      f"{attribution}{agent_name} {label}, "
                      f"{state['chars']} chars, {elapsed / 1000:.1f}s")

    def _subscribe_sse(self, base_url: str, session_id: str, agent_name: str,
                       attribution: str, start_ms: int):
        """Start a GET /event reader for real-time logging.

        Transport seam (sibling of ``_http_json`` / ``_start_serve``): the real
        impl spawns a daemon thread; tests override to feed scripted events
        synchronously via ``_handle_sse_event``. Returns a handle exposing
        ``state`` (captured tokens) + ``stop_and_join()``.
        """
        import types as _types
        state = self._new_sse_log_state()
        stop = threading.Event()
        box: dict = {"resp": None}

        def _handle(event):
            # P-BC3: ANY parsed frame = liveness (even filtered noise / deltas).
            # Stamped before _handle_sse_event so a frame that is later dropped
            # still resets the keepalive watchdog.
            state["last_event_ts"] = time.time()
            try:
                self._handle_sse_event(
                    event, state, session_id=session_id, agent_name=agent_name,
                    attribution=attribution, start_ms=start_ms)
            except Exception:  # noqa: BLE001 — logging must never crash the spawn
                pass

        def _run():
            try:
                req = urllib.request.Request(
                    f"{base_url}/event",
                    headers={"Accept": "text/event-stream"})
                box["resp"] = urllib.request.urlopen(req, timeout=None)

                def _lines():
                    while not stop.is_set():
                        try:
                            raw = box["resp"].readline()
                        except Exception:  # noqa: BLE001 — resp closed mid-read
                            break
                        if not raw:
                            break
                        yield raw.decode("utf-8", "replace")
                for frame in parse_sse_frames(_lines()):
                    if stop.is_set():
                        break
                    _handle(frame)
            except Exception:  # noqa: BLE001 — observability must never crash spawn
                pass

        # AU-6: a plain threading.Thread would start with a fresh, empty
        # contextvars context and never see this worker thread's bound
        # run.log/op_name — agent_stream lines would land in console/batch
        # log only, never the per-op run.log. spawn_context_thread copies the
        # CALLER's (this worker thread's) current context so the daemon
        # reader inherits the binding.
        thread = spawn_context_thread(_run)

        def stop_and_join(timeout: float = 5.0):
            stop.set()
            if box["resp"] is not None:
                try:
                    box["resp"].close()
                except Exception:  # noqa: BLE001
                    pass
            if thread.is_alive():
                thread.join(timeout=timeout)

        return _types.SimpleNamespace(state=state, stop_and_join=stop_and_join)

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
        effective_cwd = Path(working_dir) if working_dir else self._working_dir
        attribution = format_attribution(stage_name, branch_label)
        if effective_cwd:
            effective_cwd.mkdir(parents=True, exist_ok=True)
            # Anchor the canonical flat skill tree at <cwd>/.claude/skills so
            # opencode's native cwd→git-root discovery finds it even when the
            # spawn cwd is a temp workspace OUTSIDE the repo (same anchor the
            # claude backend plants — §2.5 single skill-delivery path). Without
            # it opencode sees only its built-in skill and the D2 steer's
            # skill({name}) call fails ("skill does not exist").
            _ensure_skills_anchor(effective_cwd)

        start_ms = int(time.time() * 1000)
        # D3 硬墙：deadline 已过 → 不启动 serve，直接 aborted 返回（不烧 spawn）。
        # deadline_monotonic 是 monotonic 绝对值；下方转剩余秒数收紧 message_timeout。
        if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
            Logger.warn(
                f"{attribution}Agent {agent_name} hard timeout: deadline passed "
                f"before spawn")
            return self._build_result(
                agent_name, consumer=None, crashed=True,
                crash_reason="hard timeout: deadline passed before spawn",
                artifacts={}, transcript_path=None,
                attempt=1, start_ms=start_ms, aborted="hard_timeout")
        if deadline_monotonic is not None:
            _remaining = deadline_monotonic - time.monotonic()
            eff_msg_timeout = min(max(_remaining, 1.0), self._message_timeout)
        else:
            eff_msg_timeout = None  # None → _post_message_watched 用实例 self._message_timeout
        project_cfg = self._load_project_config(effective_cwd, repo_root)
        # Fail-fast before serve startup: opencode serve requires an explicit
        # model in the message body (probe-confirmed — it does NOT auto-resolve
        # the config's single provider model). The model comes from the SDK's
        # canonical top-level ``model`` field (project opencode.json); there is
        # deliberately no fabricated last-resort fallback (that shipped the
        # wrong provider → HTTP 500). Missing model → ConfigError here, not a
        # wrong-model 500 mid-spawn.
        self._resolve_model(model, project_cfg)
        scratch_dir = self._cfg_scratch_dir()
        cwd_tag = f", cwd={effective_cwd}" if effective_cwd else ""

        proc = None
        transcript = None
        transcript_path = None
        sse = None  # streaming-observability handle (design B); stopped in finally
        base_url: str | None = None
        try:
            # P-BC5: bounded serve-startup retry — absorbs the transient SQLite
            # DB-lock crash under parallel spawn (see self._spawn_attempts). Each
            # attempt picks a fresh port + rebuilds config/env (port is baked into
            # the D1 config). On _start_serve/_wait_healthy failure: stop the
            # crashed serve, back off, respawn. Exhaustion → raise → outer except
            # → degraded AgentResult (same surface as pre-retry, just rarer).
            spawn_err: Exception | None = None
            for attempt in range(1, self._spawn_attempts + 1):
                port = self._pick_free_port()
                config = self._assemble_config(agent_name, primary_skill, skills,
                                               model, port, project_cfg,
                                               effective_cwd)
                env = self._build_serve_env(config, scratch_dir, project_cfg,
                                            effective_cwd)
                Logger.action(
                    "agent_spawn",
                    f"{attribution}{agent_name} starting (opencode serve :{port})"
                    + cwd_tag
                    + (f", attempt {attempt}/{self._spawn_attempts}"
                       if attempt > 1 else ""))
                attempt_proc = None
                try:
                    attempt_proc = self._start_serve(env, effective_cwd, port)
                    base_url = f"http://{self._host}:{port}"
                    self._wait_healthy(base_url)
                    proc = attempt_proc  # healthy — hand off to session/message
                    spawn_err = None
                    break
                except Exception as se:  # noqa: BLE001 — transient startup failure
                    spawn_err = se
                    if attempt_proc is not None:
                        try:
                            self._stop_serve(attempt_proc)
                        except Exception:  # noqa: BLE001 — best-effort cleanup
                            pass
                    if attempt < self._spawn_attempts:
                        Logger.warn(
                            f"{attribution}opencode serve :{port} startup failed "
                            f"(attempt {attempt}/{self._spawn_attempts}): {se}; "
                            f"retrying in {self._spawn_retry_backoff_s}s")
                        time.sleep(self._spawn_retry_backoff_s)
                    else:
                        Logger.error(
                            f"{attribution}opencode serve :{port} startup failed "
                            f"after {self._spawn_attempts} attempts: {se}")
            if spawn_err is not None or proc is None:
                raise spawn_err or RuntimeError("opencode serve failed to start")

            # 断链② fix (step-68): opencode sessions survive a serve restart
            # (probe-confirmed, task 7), so a cross-run resume reuses the prior
            # session_id instead of POSTing a fresh /session — parity with
            # claude's resume_session_id path. The resumed session already
            # carries its context, so the first message is the bare continue
            # nudge and the skill steer is NOT re-applied (the session already
            # loaded it).
            # 20260810 批根因修复 Part 2 — 后端自动 resume（对齐 sdk_backend）：
            # stage 未显式传 resume_session_id 时，sidecar 存在（= 上一迭代会话被切/
            # 崩溃未 clean finish，Part 1 保留）→ 自动续跑同一 session（程序化
            # "继续"），不 fresh restart 丢进度。sidecar 生命周期门控：自然结束已删
            # sidecar → 不触发；resume-degrade（session gone）→ fresh 既有路径兜底。
            # review M2：键含 stage_name——不同 stage 复用同 agent 时构造性分离，
            # 前任务被切留的 sidecar 不会被后一不同任务误 resume。
            _resume_fails = 0   # 连续失败的 resume 次数（退化 spawn 阈值）
            # F4（20260821 无效 resume 计数）：本 spawn 是否走了 resume（显式参数
            # 或 sidecar 自动）——供下方 cut 判定处的"无效 resume"计数。
            _was_resume = bool(resume_session_id)
            # P6：上一次 cut 的硬切分类（resume 消息路由用；须在 sidecar 重写前
            # 读出——重写不含分类键 = 消费）。
            _sidecar_cut_hard = False
            if not resume_session_id:
                _sc = self._session_sidecar_path(agent_name, branch_label,
                                                 stage_name)
                if _sc is not None and _sc.exists():
                    import json as _json
                    try:
                        _data = _json.loads(
                            _sc.read_text(encoding="utf-8"))
                        _sid = _data.get("session_id", "") or ""
                        _fails = int(_data.get("resume_fails", 0) or 0)
                    except Exception:  # noqa: BLE001 — corrupt sidecar → fresh
                        _sid, _fails = "", 0
                    if _sid:
                        if _fails >= self._resume_attempts:
                            # resume 连续失败 N 次 → 退化 spawn（Phase 2）：
                            # 清 sidecar，下走 fresh 分支，全新 session + 全量 prompt。
                            self._clear_session_sidecar(
                                agent_name, branch_label, stage_name)
                            Logger.action(
                                "agent_degrade",
                                f"{attribution}{agent_name} resume failed "
                                f"{_fails}x >= resume_attempts "
                                f"{self._resume_attempts}; degrading to fresh spawn")
                        else:
                            resume_session_id = _sid
                            _resume_fails = _fails   # 续写保留计数
                            _was_resume = True
                            Logger.action(
                                "agent_resume",
                                f"{attribution}{agent_name} auto-resuming session "
                                f"{_sid} (sidecar present — silent-cut recovery)")
            if resume_session_id:
                # P6：sidecar 重写即消费分类键——路由依据须先读出（覆盖显式
                # resume 与 sidecar 自动两条来路）。
                _sidecar_cut_hard = self._read_sidecar_cut_hard(
                    agent_name, branch_label, stage_name)
                session_id = resume_session_id
                self._write_session_sidecar(agent_name, branch_label, session_id,
                                            stage_name=stage_name,
                                            resume_fails=_resume_fails)
                Logger.action(
                    "agent_session",
                    f"{agent_name} session_id={session_id} (cross-run resume)")
            else:
                session = self._http_json(
                    "POST", f"{base_url}/session",
                    {"title": f"{stage_name or agent_name}"})
                session_id = (session.get("id")
                              if isinstance(session, dict) else None)
                if session_id:
                    # Durable resume handle (parity with claude sidecar), flushed
                    # before any crash can occur.
                    self._write_session_sidecar(agent_name, branch_label,
                                                session_id, stage_name=stage_name)
                    Logger.action("agent_session",
                                  f"{agent_name} session_id={session_id}")
                else:
                    raise RuntimeError(
                        f"opencode session create returned no id: {session}")

            # Streaming observability (design B): subscribe GET /event BEFORE
            # the blocking POST so the daemon reader captures every part from
            # the start. session_id="" → no bus filter: this spawn's serve is
            # dedicated + single-tenant (one /session, or two on rare resume-
            # degrade), so no cross-session leak is possible and the degrade
            # path's fresh session is captured too. Pure observability — the
            # POST below remains the correctness/retry authority.
            sse = self._subscribe_sse(base_url, "", agent_name,
                                       attribution, start_ms)

            # D2: skill delivery as a system steer (opencode has no /<skill>).
            system = render_opencode_skill_steer(primary_skill)
            # A resumed session already carries its context + loaded skill, so
            # the first message is the bare continue nudge (not the stage prompt)
            # and the skill steer is skipped — parity with claude's resume path.
            # Part 3: resume_prompt（深修反馈）> 硬切兜底提示（P6：仅上一次 cut
            # 分类为硬切时注入——「先落草稿，再边落边思考」；事实+建议非门）
            # > 默认「继续」。首次 fresh 执行零注入。
            if resume_session_id:
                first_prompt = (resume_prompt
                                or (_HARD_CUT_RESUME_PROMPT if _sidecar_cut_hard
                                    else _RESUME_PROMPT))
            else:
                first_prompt = prompt
            body = {
                "agent": agent_name,
                "model": self._resolve_model(model, project_cfg),
                "parts": [{"type": "text", "text": first_prompt}],
            }
            if system and not resume_session_id:
                body["system"] = system

            # Blocking: returns the full {info, parts} — the completion signal.
            # step-57 (P80): 429 burst backoff-resume. opencode is single-shot
            # (no in-spawn loop like the SDK backend), so wrap the message POST:
            # on a 429 (clean error field OR raised) sleep (exponential backoff,
            # via the shared compute_backoff_seconds — one source, §2.5) then
            # re-POST "继续" to the SAME session (the opencode session survives a
            # 429; POST /session/:id/message continues it). Logging precedes the
            # sleep and the run.log tee flushes per write, so the retry trail is
            # never lost even if killed mid-sleep (user requirement). A true
            # hard quota exhausts the total-time cap and falls through to the
            # normal build_result / crash-salvage path with an actionable reason.
            rl_attempt = 0
            rl_elapsed_s = 0.0
            # M1 (step-68 review): cross-run resume session-gone degrade. A stale
            # sidecar may point at a session opencode purged/TTL'd (or a sidecar
            # reused across devices); the resume message POST then raises HTTP 404
            # NotFoundError "Session not found" (probe-confirmed — see
            # _is_opencode_session_gone). On that signal, abandon the resume and
            # restart FRESH on this serve (clear sidecar + new /session + full
            # stage prompt + skill steer) — parity with claude's
            # _SESSION_GONE_MARKERS degrade. One-shot: `resume_session_id` is
            # nulled on degrade so a genuine mid-run crash on the fresh session
            # still falls through to crash-salvage. The stage never sees the
            # failed resume (degrade is internal).
            degraded_from_resume = False
            while True:
                try:
                    # P-BC3: POST under keepalive + hard-timeout watchdog (no
                    # 1h空烧). A worker exception (e.g. 404 session-gone) or a
                    # _KeepaliveAbort propagates to the handlers below / spawn's
                    # crash-salvage as appropriate.
                    message = self._post_message_watched(
                        base_url, session_id, body, sse, proc,
                        agent_name, attribution, message_timeout=eff_msg_timeout,
                        app_log=(Path(scratch_dir) / "data" / "opencode"
                                 / "log" / "opencode.log"))
                except Exception as post_exc:  # noqa: BLE001 — one message POST failed
                    if (resume_session_id and not degraded_from_resume
                            and _is_opencode_session_gone(post_exc)):
                        Logger.warn(
                            f"Agent {agent_name} resume session {resume_session_id} "
                            f"unavailable (gone/not-found on opencode: "
                            f"{post_exc}); degrading to fresh spawn.")
                        self._clear_session_sidecar(agent_name, branch_label,
                                                    stage_name=stage_name)
                        degraded_from_resume = True
                        resume_session_id = None  # subsequent iterations are fresh
                        # Fresh session on THIS serve (the gone one is unusable).
                        session = self._http_json(
                            "POST", f"{base_url}/session",
                            {"title": f"{stage_name or agent_name}"})
                        session_id = (session.get("id")
                                      if isinstance(session, dict) else None)
                        if not session_id:
                            raise RuntimeError(
                                f"opencode degrade session create returned no id: "
                                f"{session}") from post_exc
                        self._write_session_sidecar(
                            agent_name, branch_label, session_id,
                            stage_name=stage_name)
                        Logger.action(
                            "agent_session",
                            f"{agent_name} session_id={session_id} "
                            f"(fresh spawn after resume degrade)")
                        # Fresh session carries no context → full stage prompt +
                        # skill steer (NOT the bare continue nudge).
                        body = {
                            "agent": agent_name,
                            "model": self._resolve_model(model, project_cfg),
                            "parts": [{"type": "text", "text": prompt}],
                        }
                        if system:
                            body["system"] = system
                        continue
                    raise  # not a gone signal, or already degraded → crash-salvage
                err = self._message_error(message)
                if not err:
                    break  # success → build_result decides
                strategy = server_backoff_strategy(err)
                if strategy is None:
                    # infra（不可重试 auth/quota/config）→ 立即 halt，不进 backoff
                    Logger.error(
                        f"Agent {agent_name} infra (un-retryable) message error: {err}")
                    break  # → build_result → P116 infra halt
                Logger.warn(
                    f"Agent {agent_name} server-side message error (retryable): {err}")
                if strategy == "backoff":
                    # 429/503 限流/不可用 → 指数退避 sleep 等窗口再 resume（有界）。
                    sleep_s, rl_attempt, rl_elapsed_s = advance_backoff(
                        rl_attempt, rl_elapsed_s,
                        base_s=self._rl_backoff_base_s,
                        factor=self._rl_backoff_factor,
                        max_total_s=self._rl_backoff_max_total_s,
                        max_retries=self._rl_max_retries)
                    if sleep_s is None:
                        Logger.warn(
                            f"Agent {agent_name} server-side backoff exhausted "
                            f"(attempts={rl_attempt}, waited={rl_elapsed_s:.0f}s "
                            f"/ cap={self._rl_backoff_max_total_s:.0f}s); treating "
                            f"as hard failure → halt: {err}")
                        break  # → build_result → partial/fatal
                    Logger.action(
                        "agent_backoff",
                        f"{attribution}{agent_name} rate-limit/unavailable; sleeping "
                        f"{sleep_s:.0f}s then resuming session {session_id} "
                        f"(attempt {rl_attempt}/{self._rl_max_retries}, "
                        f"cumulative wait {rl_elapsed_s:.0f}s / "
                        f"{self._rl_backoff_max_total_s:.0f}s)")
                    time.sleep(sleep_s)
                else:  # "resume" — 其他非 infra 服务端错误（APIError/type validation/
                    # 未知）→ 立即续跑同一会话、不 sleep（避免误判时空等；20260812
                    # SSE transient 空等回归的根治方向）。有限次（max_retries）。
                    # 与 backoff 共享 rl_attempt 预算：总重试（含 backoff 与立即 resume）
                    # 有界是有意设计（review f7c7a88e #1），backoff 额外受
                    # rate_limit_backoff_max_total_s 累计 sleep 封顶。
                    rl_attempt += 1
                    if rl_attempt >= self._rl_max_retries:
                        Logger.warn(
                            f"Agent {agent_name} server-side resume exhausted "
                            f"(attempts={rl_attempt}/{self._rl_max_retries}); "
                            f"treating as hard failure → halt: {err}")
                        break  # → build_result → partial/fatal
                    Logger.action(
                        "agent_resume",
                        f"{attribution}{agent_name} server error; immediately "
                        f"resuming session {session_id} "
                        f"(attempt {rl_attempt}/{self._rl_max_retries})")
                # Resume the SAME session with the bare continue nudge.
                body = {
                    "agent": agent_name,
                    "model": self._resolve_model(model, project_cfg),
                    "parts": [{"type": "text", "text": _RESUME_PROMPT}],
                }
                if system and not resume_session_id:
                    body["system"] = system
                retry_note = ("429/503 backoff" if strategy == "backoff"
                              else "server-error retry")
                Logger.action(
                    "agent_resume",
                    f"{agent_name} resuming session {session_id} after {retry_note} "
                    f"(attempt {rl_attempt}/{self._rl_max_retries})")

            # M2（review 整改）: 判切「现在」时刻 = 流结束（最后一次 POST/SSE
            # 循环退出）当场采样，非后面的分类调用点——两者之间隔着全量
            # transcript 回读（HTTP）与产物收集（git 子进程），用调用点会把
            # 后处理耗时灌进 gap，把硬切误翻成 soft（实证口径是流结束时刻）。
            _stream_end_ts = time.time()

            # Persist transcript (step 61 P2): walk the full session history so
            # intermediate tool calls (Write/Edit file_path for 落点取证) and real
            # turn indices are captured, not just the final message. Best-effort.
            transcript = self._open_transcript(agent_name, branch_label)
            if transcript is not None:
                try:
                    transcript_path = Path(transcript.name)
                except Exception:  # noqa: BLE001 — best-effort path capture
                    transcript_path = None
            # IR consumer owns per-record signal extraction (session_id /
            # truncation / full_response), fed from the session-history records;
            # opencode's message-level error maps to the base factory's
            # crashed/crash_reason (step-68 task 11). The consumer stamps the
            # canonical turn onto each record (single source of truth).
            consumer = IRConsumer(agent_name)
            for rec in self._session_transcript_records(
                    base_url, session_id, message):
                consumer.consume(rec)
                self._write_transcript_record(transcript, rec, agent_name)

            err = self._message_error(message)
            artifacts = self._collect_artifacts(effective_cwd, repo_baseline,
                                                repo_root)
            # Clean finish (no message error) → session completed, no longer
            # resumable → clear the sidecar. An error leaves it in place as the
            # resume handle (parity with claude's crashed-keeps-sidecar).
            # 20260810 批根因修复 Part 1 — silent cut（对齐 sdk_backend）：一个
            # "clean finish"若末条 assistant 消息不可行动（只有 thinking、无 text、
            # 无 tool_use），是第三方网关静默切流，不是自然结束 → 保留 sidecar
            # （Part 2 自动 resume 句柄）+ 结果标 cut。自然结束才清 sidecar。
            # F4（20260821 无效 resume 计数，对齐 sdk_backend）：本次 spawn 是
            # resume 且又 cut → "这次恢复尝试无效"——bump resume_fails。连续无效
            # resume 达 resume_attempts 后既有 agent_degrade 路径退化 fresh，
            # 不再无限 resume 同一 thinking 泥潭 session。fresh 首跑不计数。
            _cut = (not err and not getattr(consumer, "_last_turn_actionable", True))
            # P6 硬切分类：判切点单点组装 facts + 分类（gap 判据，零模型参数）。
            # 时间源 = SSE 增量流的 reasoning 打点（transcript 是 POST 后回读、
            # 时刻失真，不进判据）；SSE 缺席/无 reasoning 证据 → 分类 None →
            # 走未知中断原路径（resume_attempts 语义不变）。
            _cut_facts = None
            _cut_hard = False
            if _cut:
                _ts = (sse.state.get("last_reasoning_delta_ts")
                       if sse is not None else None)
                _cls = (classify_cut(
                            sse.state.get("step_reasoning_chars") or 0, _ts,
                            gap_threshold_s=self._thinking_active_gap_s,
                            now=_stream_end_ts)
                        if sse is not None else None)
                if _cls is not None:
                    _cut_facts, _cut_hard = _cls
                    _cut_facts["attempt_duration_s"] = round(
                        (time.time() * 1000 - start_ms) / 1000, 1)
                # 分类单点写入 sidecar（soft 显式 False——始终反映最近一次 cut，
                # 下一次 spawn 的 resume 路由此读）。
                self._set_sidecar_cut(agent_name, branch_label, stage_name,
                                      _cut_facts, _cut_hard)
            if not err and not _cut:
                self._clear_session_sidecar(agent_name, branch_label,
                                            stage_name=stage_name)
            elif _cut and _was_resume and not _cut_hard:
                # 硬切不 bump（P6）：resume_attempts=3 是未知中断试探语义，管
                # 确定性事件错配；且达阈退化 fresh 会丢上下文、重放同一深推理
                # 再撞墙。硬切恢复走兜底提示路由，上限由 runner cut_streak 管。
                _fails_now = self._bump_session_resume_fails(
                    agent_name, branch_label, stage_name)
                Logger.warn(
                    f"{attribution}{agent_name} resume 后仍 silent-cut（无效 "
                    f"resume，连续 {_fails_now}/{self._resume_attempts}）；"
                    f"达阈后下次 spawn 退化 fresh")
            # P114: silent failure 检测（不改 crashed/status，保留重试行为）。
            self._maybe_warn_silent_failure(agent_name, err, consumer, artifacts, proc)
            return self._build_result(
                agent_name, consumer=consumer, crashed=bool(err),
                crash_reason=err, artifacts=artifacts,
                extra_metrics=self._compaction_metrics(sse, agent_name, attribution),
                transcript_path=transcript_path, attempt=1, start_ms=start_ms,
                cut=_cut, cut_facts=_cut_facts, cut_hard=_cut_hard)
        except Exception as e:  # noqa: BLE001 — one opencode spawn crashed
            Logger.error(f"Agent {agent_name} opencode spawn failed: {e}")
            # P94 (step-69): crash 轮留证。crash 可能发生在 _open_transcript（:530）
            # 之前（如 message POST timed out）——彼时 transcript 仍为 None，若不补，
            # 失败轮连一个 transcript 文件都没有（run 20260720-095303-413565 第 1 轮
            # timed out 正是如此：-01 号 jsonl 实为 split 内容、第 1 轮无文件）。此处
            # 当场补开一个 transcript 写 crash record，让失败轮留下"为何崩溃"的证据；
            # native session 兜底见 step-67，此处补工程 transcript 副本的 crash 信号。
            if transcript is None:
                transcript = self._open_transcript(agent_name, branch_label)
                if transcript is not None:
                    try:
                        transcript_path = Path(transcript.name)
                    except Exception:  # noqa: BLE001 — best-effort path capture
                        transcript_path = None
            if transcript is not None:
                self._write_transcript_record(transcript, {
                    "ts": start_ms, "type": "crash", "turn": 0,
                    "blocks": [], "result": "crashed", "error": str(e),
                }, agent_name)
            # Salvage whatever the agent wrote before the crash (parity with
            # claude's crash-salvage path). Sidecar stays in place as the resume
            # handle. consumer=None: the stream didn't complete, so no IR was
            # consumed (the factory degrades cleanly with session_id="" /
            # truncated_turns=[]).
            artifacts = self._collect_artifacts(effective_cwd, repo_baseline,
                                                repo_root)
            # §P9: aborted= carries the TRUE kill kind (turn_stall / keepalive
            # / hard_timeout), not a blanket "hard_timeout" — one error must
            # not masquerade as another (§1.10); downstream is_infra_failure
            # only checks aborted is not None, so routing is unchanged.
            _aborted = _abort_kind(e)
            if _aborted and resume_session_id:
                # resume 会话被 stall-kill → 连续失败 +1（Phase 1 失败计数）。
                # fresh 首跑（resume_session_id=None，或 within-spawn degrade 后）不计数
                # —— 符合「turn-stall 先原地 resume」：fresh 卡死，下轮先 resume。
                self._bump_session_resume_fails(agent_name, branch_label,
                                                stage_name)
            return self._build_result(
                agent_name, consumer=None, crashed=True, crash_reason=str(e),
                artifacts=artifacts, transcript_path=transcript_path,
                attempt=1, start_ms=start_ms, aborted=_aborted,
                extra_metrics=self._compaction_metrics(sse, agent_name, attribution),
                error_type_override=classify_spawn_exception(e, str(e)))
        finally:
            if sse is not None:
                try:
                    sse.stop_and_join()
                except Exception:  # noqa: BLE001 — observability teardown
                    pass
            if transcript is not None:
                try:
                    transcript.close()
                except Exception:  # noqa: BLE001
                    pass
            if proc is not None:
                self._stop_serve(proc)

    @staticmethod
    def _tail_serve_log(proc, n: int = 20) -> str:
        """P114: 读 opencode serve log 末 n 行（silent failure 辅助诊断）。

        serve log = ``.opencode-serve-<port>.log``（co-located with run.log）。
        silent 场景 POST 正常返回、proc 仍活，在 finally ``_stop_serve`` 前可读。
        best-effort：读不到返回空串（绝不阻塞诊断）。
        """
        if proc is None:
            return ""
        path = getattr(proc, "serve_log_path", None)
        if not path:
            return ""
        try:
            lines = Path(path).read_text(
                encoding="utf-8", errors="replace").splitlines()
            return "\n".join(lines[-n:]) if lines else ""
        except Exception:  # noqa: BLE001 — best-effort 诊断，绝不阻塞
            return ""

    @staticmethod
    def _maybe_warn_silent_failure(agent_name, err, consumer, artifacts, proc,
                              transcript_path=None):
        """P114: gateway 200 但 agent 0 文本产出 → opencode silent 吞网关错误。

        opencode 单次 POST 收网关非 200（503 model_not_found / 429 limit / 401）
        时 silent 吞成空 stream（status ok, 0 chars），framework/agent 看不到
        错误码 → agent silent 卡死空等（runlog 20260725-152037 P114）。

        仅留可诊断信号：**不改 crashed/status/error_type** → 下游 stage /
        graph_executor 重试链路完全不变（用户意愿：重试是吸收服务器抖动的
        增强行为，保留）。判据 = err is None + full_response 空（gateway 声称成功
        但无产出）+（turn_count==0 或 stalled>=1）；m1 已排除「合法 read-only 空产出」
        （turn_count>=1 且 stalled==0，有 tool_use progress），只对真 silent 报警，
        不漏报 silent 卡死。

        F9（2026-08-21）：m1 豁免过宽——把 F9 实证的"思考泥潭"（大量 read tool_use
        progress 却零写盘，最该干预的信号）也挡了。修：豁免前先查 transcript 写盘
        证据（§1.10 判据用业务事实"有无写盘"，不用 turn_count 代理）。有 tool_use
        progress 但**零写盘** → 仍报警，message 区分"read-only 空转（思考泥潭）"；
        有写盘尝试（写错位置）→ 归孤儿体系处理，不在此报警。同样只加 WARN，不改
        任何状态/重试路径。
        """
        if err is not None:
            return  # 显式错误走正常 crash 路径，非 silent
        if consumer is None:
            return  # 无 IR 可判（crash salvage 路径；clean path 必有 consumer）
        full = getattr(consumer, "full_response", "") or ""
        stalled = getattr(consumer, "stalled_turns", 0) or 0
        turn_count = getattr(consumer, "turn_count", 0) or 0
        if full.strip():
            return  # 有文本产出，非 silent
        # m1: 排除「合法 read-only 空产出」（有 tool_use progress：turn_count>=1
        # 且 stalled==0）——只对「真 silent」（turn_count==0 无 assistant 记录 /
        # stalled>=1 空 turn）报警，减少误报噪音。
        if turn_count >= 1 and stalled == 0:
            # F9：有 tool_use progress 但零写盘 = read-only 空转（思考泥潭）——
            # 不是"合法 read-only"，是"读了很久却没动手写"，最该干预。查 transcript
            # 写盘证据区分：有写盘尝试 → 归孤儿/空跑体系，此层不报警；零写盘 → 报警。
            from ascendc_devkit.capabilities.agent._shared import (
                _transcript_write_targets,
            )
            if _transcript_write_targets(transcript_path):
                return  # 有写盘尝试（含错位孤儿）→ 不在此层报警
            serve_tail = OpenCodeBackend._tail_serve_log(proc, n=20)
            Logger.warn(
                f"read-only 空转: agent {agent_name} 产出 0 chars 且无写盘 "
                f"(turns={turn_count}, stalled={stalled}, "
                f"artifacts={len(artifacts) if artifacts else 0}) "
                f"— 有 tool_use progress 但零 Write/Edit，疑思考泥潭/只读不写；"
                f"下游空跑熔断会兜底，此 WARN 供排查"
                + (f"\n  serve log tail:\n{serve_tail}" if serve_tail else ""))
            return
        serve_tail = OpenCodeBackend._tail_serve_log(proc, n=20)
        Logger.warn(
            f"silent failure: agent {agent_name} 产出 0 chars 且无错误码 "
            f"(turns={turn_count}, stalled={stalled}, "
            f"artifacts={len(artifacts) if artifacts else 0}) "
            f"— 疑 opencode 吞网关错误（model 不可用 / token 失效 / 限流）；"
            f"建议 curl 网关验证 model + token"
            + (f"\n  serve log tail:\n{serve_tail}" if serve_tail else ""))

    # —— Config assembly (pure, unit-tested) ——————————————————————————————

    @staticmethod
    def _host_checkout_root(effective_cwd: "Path | str | None") -> "Path | None":
        """批量模式下返回 agent cwd 所在产品仓的根（``<checkout>/runs/…``）。

        判据是结构事实，不认任何具体路径字面量（§1.12）：自 cwd 向上找同时
        含 ``.git`` 与 ``runs/`` 的祖先，且 cwd 确实落在该祖先的 ``runs/`` 下。
        不满足（standalone / TUI / 仓外 workspace）→ None，权限保持全放行。

        为什么需要它：批量跑时 agent 的 cwd 是
        ``<checkout>/runs/<domain>/jobs/<job>/batches/<stamp>/devkit/…``，
        同一轮的真实产物根就在 ``<checkout>/runs/`` 之内；``<checkout>`` 下
        其余目录（``domains/`` ``third_party/`` ``jobs/`` …）对 agent 只读。
        """
        if not effective_cwd:
            return None
        from pathlib import Path as _Path
        try:
            cwd = _Path(effective_cwd).resolve()
        except OSError:
            return None
        for anc in cwd.parents:
            try:
                if not ((anc / ".git").exists() and (anc / "runs").is_dir()):
                    continue
                if cwd.is_relative_to((anc / "runs").resolve()):
                    return anc
            except OSError:
                continue
        return None

    def _external_directory_rules(
        self, effective_cwd: "Path | str | None"
    ) -> dict[str, str]:
        """opencode ``permission.external_directory`` 规则表。

        背景（20261028 批次实证）：agent 把绝对路径少写了两级，产物落到
        ``<checkout>/jobs/…`` 而非 ``<checkout>/runs/<domain>/jobs/…``。写工具
        自动建父目录、静默成功，agent 随后按错误路径 readdir 看不到自己写的
        文件，误判为「环境级数据丢失」并重建 staging —— 与真实构建输入分叉，
        单算子白烧 7 小时。当年把 external_directory 设成全放行是为修 P-BC4
        的 headless 阻塞，代价就是这种写越界无人拦截。

        规则语义（opencode 1.19 实测）：按声明顺序展开，**最后命中的规则生效**。
        故 ``*`` 必须排首位，收窄规则排后面才能压过它。

        收窄面刻意最小：默认仍放行（agent 需要读 CANN/skill/worktree 等大量
        仓外路径，收紧白名单会误伤），只在「cwd 落在某产品仓 runs/ 下」时，
        把该仓 ``runs/`` 之外设为只读 —— 正常产物全部在 ``runs/`` 内，不受影响。
        """
        rules: dict[str, str] = {"*": "allow"}
        root = self._host_checkout_root(effective_cwd)
        if root is not None:
            rules[f"{root}/**"] = "deny"
            rules[f"{root}/runs/**"] = "allow"
        return rules

    def _assemble_config(self, leaf_agent: str, primary_skill: str | None,
                         skills: list[str] | None, model: str | None,
                         port: int, project_cfg: dict,
                         effective_cwd: "Path | str | None" = None) -> dict:
        """Build the per-spawn config dict (D1/D2/D3/D4), written to the
        ``OPENCODE_CONFIG`` file by ``_build_serve_env``.

        Pure w.r.t. I/O beyond reading agent prompt files — assembled from the
        project config (provider creds + default model) plus this spawn's leaf
        agent / skill / model. UT asserts every projection here.
        """
        cfg: dict = {
            "$schema": "https://opencode.ai/config.json",
            # Provider block from the project opencode.json, but with every
            # credential replaced by an opencode {env:VAR} placeholder — the real
            # value travels via ephemeral serve env (_build_serve_env), so the
            # config FILE we write to disk carries no secret. Non-secret fields
            # (baseURL, models) stay literal.
            "provider": self._split_provider_secrets(
                project_cfg.get("provider", {}))[0],
            # D3: project .claude/agents → opencode agent blocks.
            "agent": self._project_agents(leaf_agent),
            # D4: resolve_ambiguity stdio MCP, per-spawn params via environment.
            "mcp": {"engine": {
                "type": "local",
                "command": self._engine_mcp_command(),
                "environment": self._decision_env(),
                "enabled": True,
            }},
            # D2 + headless safety: skill allow-all (Gate 2.0 — a closed glob
            # drops the tool), no user questions in headless, edits/bash allowed.
            "permission": {
                "skill": "allow",
                "question": "deny",
                "edit": "allow",
                "bash": "allow",
                "webfetch": "allow",
                "websearch": "allow",
                # P-BC4: agents operate on the worktree (task files / proto /
                # examples) which is EXTERNAL to the per-stage artifacts cwd.
                # opencode's external_directory defaults to "ask" — in headless
                # non-interactive batch there is no permission resolver, so an
                # "ask" blocks the agent indefinitely (5-concurrent design-
                # generator stalled here for 12+ min in run 20260721-004437).
                # Must allow so agents can read the worktree they operate on.
                # 但"全放行"让绝对路径幻觉可以写到宿主仓任意位置（见
                # ``_external_directory_rules``），故收窄为"默认放行 + 宿主仓
                # 只开放 runs/"。
                "external_directory": self._external_directory_rules(
                    effective_cwd),
            },
            "server": {"port": port, "hostname": self._host},
            # opencode's default subagent_depth is 1 (subagents cannot launch
            # subagents), which matches claude's single-level dispatch — no
            # need to set it explicitly. Writing ``"subagent_depth": 1`` was
            # rejected by opencode ≤1.17.x (ConfigInvalidError even though the
            # online schema lists the field — only newer runtimes accept it),
            # so omitting is both the default-correct and version-portable choice.
            "default_agent": leaf_agent,
        }
        # The overlay deliberately carries NO ``model``: the model lives only in
        # the project opencode.json's canonical top-level field, which opencode
        # itself reads natively (SDK's own config capability — the framework does
        # NOT duplicate or re-implement model selection). The framework only
        # needs the model for the message body (the serve API requires it
        # explicitly), resolved in ``_resolve_model`` — a thin pass-through of
        # that same field, or an explicit override (CLI --model / spawn arg).
        return cfg

    def _project_agents(self, leaf_agent: str) -> dict:
        """D3 projection: every ``.claude/agents/*.md`` → an opencode agent block.

        The spawned ``leaf_agent`` becomes the primary; all others become
        subagents it may dispatch. frontmatter (description / allowed /
        disallowed tools / model) → opencode ``description`` / ``permission`` /
        ``model``; the markdown body → ``prompt``.
        """
        agents: dict[str, dict] = {}
        agents_dir = self._agents_dir()
        if not agents_dir.is_dir():
            # At minimum project the leaf so the message `agent` resolves.
            agents[leaf_agent] = {
                "mode": "primary",
                "prompt": _find_agent_prompt(leaf_agent),
                "permission": self._leaf_permission(leaf_agent),
            }
            return agents

        for agent_file in sorted(agents_dir.glob("*.md")):
            name = agent_file.stem
            try:
                content = agent_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            block: dict = {
                "mode": "primary" if name == leaf_agent else "subagent",
                "prompt": _strip_frontmatter(content),
            }
            desc, perm, model = self._agent_manifest_projection(name)
            if desc:
                block["description"] = desc
            elif name != leaf_agent:
                # opencode requires a description for a subagent to be
                # dispatchable; fall back to the name.
                block["description"] = name
            if perm:
                block["permission"] = perm
            if model:
                block["model"] = model
            agents[name] = block

        # Guarantee the leaf is present even if its .md is missing.
        if leaf_agent not in agents:
            agents[leaf_agent] = {
                "mode": "primary",
                "prompt": _find_agent_prompt(leaf_agent),
                "permission": self._leaf_permission(leaf_agent),
            }
        return agents

    def _agent_manifest_projection(self, name: str):
        """Return (description, permission, model) for an agent from its manifest.

        permission maps disallowed_tools → ``deny`` (the safety constraint we
        must preserve). allowed_tools are left implicit (opencode defaults to
        allow), matching how the claude side treats an unset tool as available.
        """
        try:
            from ascendc_devkit.capabilities.skill.loader import load_agent_manifest
            manifest = load_agent_manifest(name)
        except Exception:
            return "", {}, None
        perm: dict[str, str] = {}
        for tool in (manifest.disallowed_tools or []):
            key = _TOOL_PERM_KEY.get(tool)
            if key:
                perm[key] = "deny"
        return manifest.description or "", perm, None

    def _leaf_permission(self, leaf_agent: str) -> dict:
        """Deny the leaf's disallowed tools (backend default ∪ manifest)."""
        perm: dict[str, str] = {}
        for tool in self._disallowed_tools:
            key = _TOOL_PERM_KEY.get(tool)
            if key:
                perm[key] = "deny"
        _, mperm, _ = self._agent_manifest_projection(leaf_agent)
        perm.update(mperm)
        return perm

    def _decision_env(self) -> dict:
        """Per-spawn params for the engine stdio MCP (D4), passed via env."""
        env = {
            "ASCENDC_INTERACTIVE": "1" if self._interactive else "0",
            "ASCENDC_ON_DECISION": self._on_decision,
        }
        if self._decision_workspace:
            env["ASCENDC_DECISION_WORKSPACE"] = str(self._decision_workspace)
        if self._webhook_url:
            env["ASCENDC_WEBHOOK_URL"] = self._webhook_url
        return env

    def _engine_mcp_command(self) -> list[str]:
        import sys
        return [sys.executable, "-m", _ENGINE_MCP_MODULE]

    # —— Model resolution ————————————————————————————————————————————————

    def _resolve_model(self, model: str | None, project_cfg: dict) -> dict:
        """Resolve the message body's ``{providerID, modelID}`` from the
        project opencode.json's canonical top-level ``model`` field.

        Priority: explicit spawn arg > backend default > the project
        opencode.json's ``model`` (the SDK's own field — opencode itself reads
        it natively). Deliberately NO last-resort default: opencode serve
        requires the model in the message body and does not auto-resolve the
        config's provider model (probe-confirmed). A fabricated fallback is
        exactly what shipped the wrong provider (``anthropic/claude-sonnet-4-5``)
        on single-provider configs → HTTP 500. ``None`` → ConfigError (fail-fast).

        A ``provider/id`` string splits on the first ``/``. A bare id (e.g.
        ``"GLM-5.2"``) takes its provider from the single configured provider
        key, defaulting to ``anthropic``.
        """
        model_str = model or self._model or project_cfg.get("model")
        if not model_str:
            raise ConfigError(
                "opencode.json (top-level model)",
                "no model to send: opencode serve requires the model in the "
                "message body and does not auto-resolve the config's single "
                "provider model. Set a top-level \"model\" in the project "
                "opencode.json (e.g. \"92bpangu/pangu_ultra_moe\"), or pass one "
                "explicitly (CLI --model / runtime_config / spawn arg).")
        if "/" in model_str:
            provider_id, model_id = model_str.split("/", 1)
            return {"providerID": provider_id, "modelID": model_id}
        providers = list((project_cfg.get("provider") or {}).keys())
        provider_id = providers[0] if providers else "anthropic"
        return {"providerID": provider_id, "modelID": model_str}

    # —— Project config + serve env ————————————————————————————————————————

    def _load_project_config(self, effective_cwd, repo_root) -> dict:
        """Read the project ``opencode.json`` (provider creds + default model).

        Walk cwd → repo_root looking for opencode.json (opencode's own discovery
        order), or use the explicit ``project_config_path``. Reading it and
        folding it into the per-spawn ``OPENCODE_CONFIG`` file makes the backend
        cwd-independent (mirrors claude pinning settings.json). Returns {} when
        none found.

        Devkit-root fallback: when the cwd walk-up misses the devkit project
        root (notably when ``effective_cwd`` is an op_dir in a sibling tree —
        batch runs under ``cann-bench-batch/`` next to ``AscendC-DevKit/``, or
        any external repo whose path is not a descendant of the devkit root),
        the provider creds in ``<devkit_root>/opencode.json`` would never be
        reached. Append it as a last-resort candidate so spawn does not degrade
        to the model fallback (which then 400s with no provider credentials).
        The devkit root is derived from this file's location
        (``src/ascendc_devkit/capabilities/agent/`` → ``parents[4]``); under a
        non-editable install without an adjacent opencode.json the candidate
        simply does not exist and is skipped, so the fallback is safe.
        """
        candidates: list[Path] = []
        if self._project_config_path:
            candidates.append(self._project_config_path)
        # Machine-local config parked outside the checkout (e.g. a driver that
        # runs the harness from git worktrees, where the ignored project
        # ``opencode.json`` is absent). Highest priority; unset by default.
        override = os.environ.get("ASCENDC_OPENCODE_PROJECT_CONFIG", "").strip()
        if override:
            candidates.append(Path(override).expanduser())
        start = Path(effective_cwd) if effective_cwd else Path.cwd()
        root = Path(repo_root) if repo_root else None
        cur = start
        seen = set()
        while True:
            if cur in seen:
                break
            seen.add(cur)
            candidates.append(cur / "opencode.json")
            if root and cur == root:
                break
            if cur.parent == cur:
                break
            cur = cur.parent
        # Devkit-root anchor (sibling-tree case): only added if not already
        # covered by the walk-up (avoids a duplicate stat in the common case).
        devkit_root = Path(__file__).resolve().parents[4]
        devkit_cfg = devkit_root / "opencode.json"
        if devkit_cfg not in candidates:
            candidates.append(devkit_cfg)
        for c in candidates:
            try:
                if c and c.is_file():
                    cfg = json.loads(c.read_text(encoding="utf-8"))
                    self._validate_project_config(cfg, c)
                    return cfg
            except ConfigError:
                raise
            except Exception as e:  # noqa: BLE001
                Logger.warn(f"could not read opencode config {c}: {e}")
        return {}

    @staticmethod
    def _validate_project_config(cfg: dict, path: Path) -> None:
        """Load-time guard for opencode-specific transport quirks (§1.3).

        The anthropic ai-sdk provider POSTs ``${baseURL}/messages`` (baseURL is
        expected to already carry the version segment), whereas claude's own SDK
        appends ``/v1/messages`` itself. A baseURL missing ``/v1`` therefore hits
        the gateway's dashboard (HTML) instead of the messages endpoint and the
        stream comes back empty — a SILENT failure (status ok, 0 tokens). We turn
        that into a fail-fast ConfigError naming the fix, so the same gotcha
        never has to be re-diagnosed at runtime (see
        docs/plan/opencode-sdk-backend/03-headless-env-gotchas.md §一.A).
        """
        opts = (((cfg.get("provider") or {}).get("anthropic") or {})
                .get("options") or {})
        base_url = opts.get("baseURL")
        if isinstance(base_url, str) and base_url.strip():
            if not base_url.rstrip("/").endswith("/v1"):
                raise ConfigError(
                    str(path),
                    "provider.anthropic.options.baseURL must end with '/v1' "
                    f"(got {base_url!r}); opencode's ai-sdk posts "
                    "'${baseURL}/messages'. Note claude's ANTHROPIC_BASE_URL "
                    "does NOT carry /v1 — the two backends need different "
                    "baseURL strings for the same gateway.")

    _SECRET_OPTION_KEYS = ("apiKey", "authToken", "accessKey", "secretKey")

    @classmethod
    def _split_provider_secrets(cls, provider: dict) -> tuple[dict, dict]:
        """Split provider credentials out of the on-disk config (D1 secret path).

        opencode reads the per-spawn config from a FILE (``OPENCODE_CONFIG``
        path) — the inline ``OPENCODE_CONFIG_CONTENT`` env hits the Linux
        128KB ``MAX_ARG_STRLEN`` per-string cap once the D3 agent projections
        (~234KB) are folded in. Since the config now lands on disk, every
        provider ``options`` credential is replaced by an opencode
        ``{env:VAR}`` interpolation placeholder and the real value is returned
        as a serve-env entry (ephemeral) — the credential never touches disk.
        Non-secret fields (baseURL, models) stay literal.

        Returns ``(sanitized_provider, secret_env)``.
        """
        sanitized = copy.deepcopy(provider) if provider else {}
        secret_env: dict[str, str] = {}
        for pid, pcfg in sanitized.items():
            if not isinstance(pcfg, dict):
                continue
            opts = pcfg.get("options")
            if not isinstance(opts, dict):
                continue
            for key in list(opts.keys()):
                if key in cls._SECRET_OPTION_KEYS and isinstance(opts[key], str):
                    var = f"OPENCODE_SECRET_{pid.upper()}_{key.upper()}"
                    secret_env[var] = opts[key]
                    opts[key] = f"{{env:{var}}}"
        return sanitized, secret_env

    def _cfg_scratch_dir(self) -> str:
        """Scratch directory for the framework ``OPENCODE_CONFIG`` file.

        The per-spawn D1–D4 config is written here (see ``_build_serve_env``),
        independent of the operator's real HOME. The serve subprocess keeps its
        real HOME so opencode natively discovers the user's global config
        (``$XDG_CONFIG_HOME``/``$HOME/.config/opencode``) and auth
        (``$XDG_DATA_HOME``/``$HOME/.local/share/opencode``) — the whole point of
        supporting global configuration. Created under the run workspace when
        available (co-located, cleaned with the run), else a temp dir.
        """
        if self._decision_workspace:
            scratch = Path(self._decision_workspace) / ".opencode_home"
        else:
            scratch = Path(tempfile.mkdtemp(prefix="opencode_home_"))
        scratch.mkdir(parents=True, exist_ok=True)
        return str(scratch)

    def _build_serve_env(self, config: dict, scratch_dir: str,
                         project_cfg: dict | None = None,
                         effective_cwd: Path | str | None = None) -> dict:
        """Assemble the serve subprocess env (D1 file config + real HOME).

        Passes the corporate proxy through (inherited from os.environ), keeps
        PATH (so ``rg`` stays reachable — /tmp is noexec), and **keeps the real
        HOME** so opencode natively discovers the user's global config/auth
        (global-configuration support). The framework config is written to a
        scratch FILE (not the operator's HOME, and not the inline
        ``OPENCODE_CONFIG_CONTENT`` env, which caps at 128KB ``MAX_ARG_STRLEN``
        and the D3 agent projections blow past it) and pointed at via
        ``OPENCODE_CONFIG`` — the highest-priority merge layer, so headless
        invariants win over any global/project value. Provider credentials are
        NOT in that file — they travel here as ephemeral env vars (see
        ``_split_provider_secrets``), so the secret never lands on disk.
        """
        env = dict(os.environ)  # proxy vars + PATH + real HOME/XDG pass through
        cfg_path = Path(scratch_dir) / "opencode-config.json"
        cfg_path.write_text(json.dumps(config, ensure_ascii=False),
                            encoding="utf-8")
        try:
            cfg_path.chmod(0o600)
        except OSError:  # pragma: no cover — best-effort hardening
            pass
        env["OPENCODE_CONFIG"] = str(cfg_path)
        # Disambiguate: a stray inherited override would shadow our file.
        env.pop("OPENCODE_CONFIG_CONTENT", None)
        env.pop("OPENCODE_CONFIG_DIR", None)
        # P13 (step-116): the op card pin — every bash tool descendant of this
        # serve inherits it (structural: new spawn kinds correct by default).
        if self._card_pin is not None:
            from ascendc_devkit.adapters.npu.card_pin import card_pin_env
            env.update(card_pin_env(self._card_pin))
        # G (P115): per-spawn opencode data/config isolation. opencode serve
        # otherwise shares ONE global SQLite DB ($XDG_DATA_HOME/opencode — real
        # HOME passes through above) across every concurrent serve → under
        # parallel spawn (batch 5 ops × ForkJoin T1/T2/T3 design-generators)
        # the DB lock contends → "database is locked" (serve-log 铁证) → opencode
        # stalls mid-turn → engine MCP initialize never starts → design-generator
        # hangs until message_timeout=3600 (1h). Pointing XDG at a per-spawn
        # subdir gives each serve its own SQLite DB (no shared lock, no contention).
        # Safe: the framework injects credentials via OPENCODE_SECRET_* env (not
        # opencode's global auth DB) and anchors skills at cwd
        # (_ensure_skills_anchor) — so opencode's global auth/config is NOT a
        # framework dependency for batch runs (P-BC5's "global-auth invariant"
        # concern does not apply here). Covers BOTH concurrency layers because
        # every serve (batch-level + intra-op ForkJoin) funnels through this
        # single _build_serve_env entry (§1.2 可扩展).
        env["XDG_DATA_HOME"] = str(Path(scratch_dir) / "data")
        env["XDG_CONFIG_HOME"] = str(Path(scratch_dir) / "config")
        # File-watcher guard (opencode issue #26981): opencode's file watcher
        # (@parcel/watcher inotify) hangs during init when cwd's .git is a FILE
        # (linked git worktree) rather than a directory — the serve then stalls
        # before ever issuing the LLM call and the framework's turn_stall gate
        # misreads the hang as a dead agent. The framework's serve is a headless
        # agent runner (agents do file I/O via their own tools), so realtime FS
        # change detection is dead weight — disable unconditionally so every
        # future spawn (batch + ForkJoin, any cwd) is immune without per-op
        # detection code.
        env["OPENCODE_EXPERIMENTAL_DISABLE_FILEWATCHER"] = "1"
        # Provider secrets referenced by {env:VAR} placeholders in the file.
        _, secret_env = self._split_provider_secrets(
            (project_cfg or {}).get("provider", {}))
        env.update(secret_env)
        # P126: agent-side Bash commits (precision_debug fix/printf agents) hit
        # the same "no git identity" wall in bare CI/container envs. Merge a
        # conditional synthetic identity into the serve env (over the already-
        # assembled env — real HOME/XDG — so the probe matches what the serve
        # subprocess will actually resolve). No-op when git already resolves an
        # identity; never writes git config. Applied to all spawns (harmless
        # fallback) to avoid backend↔stage coupling — precision_debug is the sole
        # real committer.
        from ascendc_devkit.infra.repo_guard import git_commit_identity_env
        env.update(git_commit_identity_env(effective_cwd, env))
        return env

    # —— Result / transcript building ————————————————————————————————————

    def _parts_to_records(self, message: dict, turn: int = 1,
                          *, session_id: str = "") -> list[dict]:
        """Map a message's ``parts`` to one normalized IR record (step-68).

        ``role`` replaces the legacy ``"opencode_message"`` type so both backends
        share one IR schema (the on-disk transcript record). Block fields
        (``kind`` / ``tool_name`` / ``tool_input``) are unchanged, so the single
        consumer of transcript blocks — ``_harvest_relocation_evidence`` (step
        51) — reads one schema across both backends (step 61 P1, decision (b):
        normalize at the producing boundary, not in every consumer). ``turn``
        carries the real per-message index when the caller walks the session
        history (step 61 P2). ``stop_reason`` (opencode AI SDK v5 finish signal)
        and ``session_id`` let ``IRConsumer`` own truncation + capture (parity
        with claude, where ``_serialize_event`` puts them on records); ``error``
        is transcript diagnostic (the factory gets the crash reason directly)."""
        parts = (message or {}).get("parts") or []
        # Block extraction is shared with the streaming SSE mapper
        # (``opencode_sse._part_to_block``) so the live transport and the
        # post-hoc assembler emit one identical block schema (§2.5 single
        # mapping path; slice 2 of streaming transport).
        blocks = [_part_to_block(p) for p in parts if isinstance(p, dict)]
        info = (message or {}).get("info")
        info_d = info if isinstance(info, dict) else {}
        record: dict = {"ts": int(time.time() * 1000), "role": "assistant",
                        "turn": turn, "blocks": blocks}
        # opencode AI SDK v5 finish signal → IR stop_reason (length /
        # max-output-tokens → truncation, captured by IRConsumer). Best-effort
        # across field names; absent → no truncation recorded.
        finish = (info_d.get("finishReason") or info_d.get("stop_reason")
                  or info_d.get("finish_reason"))
        if finish:
            record["stop_reason"] = finish
        # N2 (step-68 review): ``error`` here is the model-side error opencode
        # returns as 200-with-info.error (transcript diagnostic only — the
        # IRConsumer does not read it; the factory gets the crash reason via the
        # ``crashed``/``crash_reason`` path). This is NOT the session-gone hook:
        # a gone/stale resume session raises HTTP 404 from _http_json BEFORE any
        # message is returned (probe-confirmed, M1), so it never reaches this
        # field — gone-detection lives in the spawn's POST try/except, not here.
        err = info_d.get("error")
        if err:
            record["error"] = str(err)
        if session_id:
            record["session_id"] = session_id
        return [record]

    def _session_transcript_records(self, base_url, session_id, fallback_message):
        """Transcript records for the whole session (step 61 P2).

        The blocking POST returns only the final assembled message, so its parts
        miss the turn's intermediate tool calls (Write/Edit ``file_path`` that
        落点取证 needs) and carry no real turn index. opencode persists every
        message/part server-side; ``GET /session/:id/message`` returns them all.
        Walk that history, mapping each message with its real 1-based turn.

        Best-effort (§1.2 diagnosable, non-masking, non-blocking): any GET failure
        or an unrecognized shape falls back to the single blocking message
        (turn 1), so a transient hiccup never loses the reply or aborts the spawn.
        """
        history = None
        try:
            history = self._http_json(
                "GET", f"{base_url}/session/{session_id}/message",
                timeout=self._message_timeout)
        except Exception as e:  # noqa: BLE001 — transcript is diagnostic, not required
            Logger.warn(
                f"opencode session history GET failed ({e}); transcript falls "
                f"back to the final message only")
        messages = self._extract_history_messages(history)
        if not messages:
            return self._parts_to_records(fallback_message, turn=1,
                                           session_id=session_id)
        records: list[dict] = []
        for i, msg in enumerate(messages, start=1):
            records.extend(self._parts_to_records(msg, turn=i,
                                                  session_id=session_id))
        return records

    @staticmethod
    def _extract_history_messages(history) -> list[dict]:
        """Normalize ``GET /session/:id/message`` into a list of message dicts
        (each carrying ``parts``). Tolerates a bare list or a ``{messages:[...]}``
        envelope; anything else → empty (caller falls back)."""
        if isinstance(history, list):
            return [m for m in history if isinstance(m, dict)]
        if isinstance(history, dict):
            msgs = history.get("messages")
            if isinstance(msgs, list):
                return [m for m in msgs if isinstance(m, dict)]
        return []

    @staticmethod
    def _message_error(message: dict) -> str | None:
        info = (message or {}).get("info")
        if isinstance(info, dict):
            err = info.get("error")
            if err:
                return str(err)
        return None

    # —— HTTP / serve seams (overridable for tests) ————————————————————————

    def _agents_dir(self) -> Path:
        # <repo>/.claude/agents — this file is at
        # src/ascendc_devkit/capabilities/agent/opencode_backend.py.
        return Path(__file__).resolve().parents[4] / ".claude" / "agents"

    @staticmethod
    def _pick_free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def _start_serve(self, env: dict, cwd, port: int) -> subprocess.Popen:
        # P-BC2: opencode serve stdout/stderr must NOT be DEVNULL. When a design
        # stalls the framework needs the daemon's own output to locate the hang
        # (§1.3 expose-don't-hide; external-infra "leave a diagnostic signal" —
        # we don't fix opencode internals, but we keep their signal instead of
        # /dev/null-ing it). The log is co-located with the run: scratch_dir
        # (OPENCODE_CONFIG's parent) sits under the run workspace beside run.log,
        # NOT in the agent's working_dir → never pollutes collected artifacts.
        # stderr merges into stdout (one stream to read post-hang). The handle is
        # closed in _stop_serve (no fd leak).
        serve_log = self._serve_log_path(env, port)
        handle = open(serve_log, "ab")  # binary append; opencode writes UTF-8
        # S4: start_new_session makes the serve a session/group leader so
        # _stop_serve's os.killpg reaches its children (engine MCP stdio subprocess)
        # too — proc.terminate alone orphans them.
        proc = subprocess.Popen(
            [self._opencode_bin, "serve", "--port", str(port),
             "--hostname", self._host],
            cwd=str(cwd) if cwd else None,
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        proc.serve_log_handle = handle
        proc.serve_log_path = str(serve_log)
        _ACTIVE_SERVE_PROCS.add(proc)  # S4: atexit backstop tracking
        Logger.info(f"opencode serve :{port} log → {serve_log}")
        return proc

    @staticmethod
    def _serve_log_path(env: dict, port: int) -> Path:
        # scratch_dir = parent of OPENCODE_CONFIG (set by _build_serve_env), i.e.
        # <run workspace>/.opencode_home. Falls back to a temp dir if unset
        # (defensive — _build_serve_env always sets it). Co-located with run.log,
        # isolated from the agent's artifacts dir.
        cfg = env.get("OPENCODE_CONFIG")
        base = Path(cfg).parent if cfg else Path(tempfile.gettempdir())
        base.mkdir(parents=True, exist_ok=True)
        return base / f".opencode-serve-{port}.log"

    def _wait_healthy(self, base_url: str) -> None:
        deadline = None  # set on first loop (Date.now-free clock via time.time)
        start = time.time()
        last_err: Exception | None = None
        while time.time() - start < self._serve_startup_timeout:
            try:
                out = self._http_json("GET", f"{base_url}/global/health",
                                      timeout=5.0)
                if isinstance(out, dict) and out.get("healthy"):
                    return
            except Exception as e:  # noqa: BLE001 — not up yet
                last_err = e
            time.sleep(0.2)
        raise RuntimeError(
            f"opencode serve did not become healthy within "
            f"{self._serve_startup_timeout}s ({last_err})")

    def _http_json(self, method: str, url: str, body: dict | None = None,
                   timeout: float = 30.0) -> dict:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            url, data=data, method=method,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}

    # —— §step-97: pre-trip evidence（判死前取证）——————————————————————
    #
    # 本批 99c4c0 四杀实证：看门狗判死只看 SSE 静默，而 bash 执行期 opencode
    # 不发任何帧——三信号（turn/chars/last_event_ts）同时失明；同一时刻「正在跑
    # 哪条命令、跑了多久、已吐什么」就躺在本 spawn 的 opencode db 里（kill-3：
    # bash status="running" 605s + 部分输出）。取证在判死单点（_post_message_
    # watched 看门狗）内做，不开旁路（§1.15）；查询失败退化现行行为（fail-open
    # 有界，§1.2）。

    def _probe_running_tool(self, session_id: str) -> dict | None:
        """Read-only probe of this spawn's opencode db for the session's
        latest tool part (§step-97).

        Returns ``{"status", "command", "output_tail", "started_ms"}`` for the
        most recent tool part, or ``None`` (no db / no session / no tool part /
        query failure) — ``None`` means "no evidence", the caller degrades to
        the pre-step-97 behavior. sqlite readonly + 1s timeout: the probe must
        never block the watchdog loop.
        """
        ws = getattr(self, "_decision_workspace", None)
        if not ws or not session_id:
            return None
        db = (Path(ws) / ".opencode_home" / "data" / "opencode"
              / "opencode.db")
        if not db.is_file():
            return None
        try:
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True,
                                   timeout=1.0)
            try:
                rows = conn.execute(
                    "SELECT data FROM part WHERE session_id = ? "
                    "ORDER BY time_created DESC LIMIT 20",
                    (session_id,)).fetchall()
            finally:
                conn.close()
        except sqlite3.Error:
            return None  # locked / busy / corrupt → degrade, never block
        for (raw,) in rows:
            try:
                d = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if not isinstance(d, dict) or d.get("type") != "tool":
                continue
            st = d.get("state") or {}
            inp = st.get("input")
            cmd = (str(inp.get("command") or inp.get("filePath") or "")
                   if isinstance(inp, dict) else "")
            meta = st.get("metadata")
            out = (meta.get("output") if isinstance(meta, dict) else None)
            if not out:
                out = st.get("output")
            tm = st.get("time")
            started = tm.get("start") if isinstance(tm, dict) else None
            return {
                "status": str(st.get("status") or ""),
                "command": cmd,
                "output_tail": str(out or "")[-200:],
                "started_ms": int(started) if started else None,
            }
        return None

    def _kill_running_tool_subtree(self, proc, command: str) -> bool:
        """SIGKILL the hung tool's process subtree — **not** the serve.

        Scope: descendants of this serve only (opencode runs tool commands as
        serve children), so a match can never hit another execution's
        processes. Matching: distinctive tokens of the tool command (path-like
        or long words) against each descendant's /proc cmdline. Returns True
        when a live match was found and killed; False (no distinctive token /
        no match — e.g. the process already died and the serve wedged without
        updating the part) means the caller falls through to kill-serve, which
        is the serve-wedge detector.
        """
        root = getattr(proc, "pid", None)
        if not root or not command:
            return False
        tokens = {t for t in command.split()
                  if ("/" in t and len(t) > 6) or len(t) >= 12}
        if not tokens:
            return False
        children: dict[int, list[int]] = {}
        try:
            entries = os.listdir("/proc")
        except OSError:  # pragma: no cover — /proc always present on linux
            return False
        for entry in entries:
            if not entry.isdigit():
                continue
            try:
                with open(f"/proc/{entry}/stat", "rb") as f:
                    stat = f.read().decode("utf-8", "replace")
                rparen = stat.rindex(")")
                ppid = int(stat[rparen + 2:].split()[1])
            except (OSError, ValueError, IndexError):
                continue
            children.setdefault(ppid, []).append(int(entry))
        matched: list[int] = []
        stack, seen = [root], {root}
        while stack:
            pid = stack.pop()
            for child in children.get(pid, []):
                if child in seen:
                    continue
                seen.add(child)
                stack.append(child)
                try:
                    with open(f"/proc/{child}/cmdline", "rb") as f:
                        cmdline = f.read().decode("utf-8", "replace")
                except OSError:
                    continue
                if any(tok in cmdline for tok in tokens):
                    matched.append(child)
        for pid in matched:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        return bool(matched)

    def _pretrip_tool_evidence(self, proc, sse, session_id: str,
                               agent_name: str, attribution: str,
                               now: float) -> str:
        """Gate both transport-silence watchdogs on db evidence (§step-97).

        Called only when a gate is about to trip. Verdicts:

        - ``"alive"`` — the session's latest tool part is ``running`` and
          within ``tool_grace_s``: a tool is demonstrably in flight, SSE
          silence is expected. Stall baselines are reset (the agent is NOT
          dead) and one throttled ``agent_stream`` line surfaces the running
          command + partial output tail for operability.
        - ``"killed"`` — ``running`` beyond ``tool_grace_s`` (the tool itself
          hung, e.g. a device-sync wedge) and a live descendant matched: the
          tool subtree is SIGKILLed — opencode hands the tool error back to
          the agent, which continues WITH the fact (session/context/worktree
          all preserved). ``tool_grace_s == 0`` disables this branch (alive
          reset only).
        - ``"trip"`` — no running part (真静默), or over-grace with no live
          match (the serve wedged without reaping — kill-serve is the wedge
          detector). The gate proceeds as before step-97.
        """
        ev = self._probe_running_tool(session_id)
        if not ev or ev.get("status") != "running":
            return "trip"
        started = ev.get("started_ms")
        running_s = ((now * 1000.0 - started) / 1000.0
                     if started else None)
        over_grace = (self._tool_grace_s > 0 and running_s is not None
                      and running_s > self._tool_grace_s)
        if not over_grace:
            sse.state["turn_ts"] = now
            sse.state["last_event_ts"] = now
            last_log = sse.state.get("_tool_probe_log_ts") or 0.0
            if now - last_log > 60.0:  # throttle: once per stale episode-ish
                sse.state["_tool_probe_log_ts"] = now
                Logger.action(
                    "agent_stream",
                    f"{attribution}{agent_name} tool in flight "
                    f"{running_s:.0f}s (db evidence, alive — watchdog re-armed), "
                    f"cmd={ev.get('command', '')[:120]!r}, "
                    f"output tail: {ev.get('output_tail', '')!r}")
            return "alive"
        killed = self._kill_running_tool_subtree(proc, ev.get("command", ""))
        if killed:
            sse.state["turn_ts"] = now
            sse.state["last_event_ts"] = now
            Logger.warn(
                f"Agent {agent_name} {attribution}tool hung "
                f"{running_s:.0f}s > grace {self._tool_grace_s:.0f}s — "
                f"killed the TOOL subtree (serve + session preserved; the "
                f"agent receives the tool error and continues)")
            return "killed"
        # running-but-no-live-descendant: the part status is stale — the serve
        # wedged without reaping. Falling through lets kill-serve own it.
        return "trip"

    def _gateway_error_evidence(self, app_log: Path,
                                since_epoch: float) -> list[float]:
        """step-115 (P16)：阳性网关错误证据——读本 spawn scratch 的 opencode
        app log 尾部，返回**晚于** ``since_epoch``（静默起点）的全部
        ``level=ERROR message="stream error"``（上游 AI_APICallError 族）行
        时刻；空表 = 无证据。

        消费判据（调用方）：**≥2 条**才 trip——坏窗口的错误是持续复发的
        （实测 6-12s/轮连发），瞬态错误是单发的（opencode 内部重试自愈后
        不会再现）；「复发」是比静默时长更强的判据（§1.10 证据优先于时长
        代理），单发瞬态 + 首 token 迟到（>probe_s）不再可能误杀。慢循环
        坏窗口（每轮上游 300s 才报错）凑不齐 2 条，由 180s 时长界兜底——
        分工正确。保守标记集：只认 ``stream error``，不把无关 ERROR（权限/
        配置等）当网关死亡证据。日志不存在/不可读 = 无证据（时长界兜底，
        不 fail）。信号源在本 spawn 的 XDG scratch 内（:1474），非外部路径
        （§1.7——runtime_config 旧注释「framework does NOT read opencode.log」
        的外部路径前提随 per-spawn XDG 隔离已不成立）。
        """
        try:
            with open(app_log, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - 65536))  # tail 64KB — 重试循环行数有界
                tail = f.read().decode("utf-8", errors="replace")
        except OSError:
            return []
        fresh = []
        _saw_error_line = False
        for ln in tail.splitlines():
            # F11（review 整改）：字段序无关匹配——原 regex 钉死
            # 「timestamp→level→run→message」四段顺序且强制含 run=，opencode
            # 升级改日志字段序即静默失配（evidence 恒空 → 退回时长界，特性
            # 失效且无告警）。现改为行内子串判定 + timestamp 独立提取。
            if "level=ERROR" not in ln or 'message="stream error"' not in ln:
                continue
            _saw_error_line = True
            m = re.search(r"timestamp=(\S+?)Z?(?=\s|$)", ln)
            if not m:
                continue
            try:
                dt = datetime.fromisoformat(m.group(1))
                # 带 offset 的时刻保原值（旧 .replace(tzinfo=utc) 会把非 Z
                # 时区抹成 UTC）；naive 视作 UTC。
                ts = (dt.replace(tzinfo=timezone.utc).timestamp()
                      if dt.tzinfo is None else dt.timestamp())
            except ValueError:
                continue
            if ts > since_epoch:
                fresh.append(ts)
        if _saw_error_line and not fresh:
            Logger.action(
                "gateway_evidence_mismatch",
                "app log tail has ERROR stream-error lines but none matched "
                "the evidence shape (timestamp unparseable / all older than "
                "silence onset) — duration bound remains the backstop")
        return fresh

    def _post_message_watched(self, base_url: str, session_id: str,
                              body: dict, sse, proc, agent_name: str,
                              attribution: str,
                              message_timeout: float | None = None,
                              app_log: Path | None = None) -> dict:
        """POST one message under keepalive + hard-timeout watchdog (P-BC3).

        The blocking POST runs in a worker thread; the calling thread polls SSE
        liveness (``sse.state["last_event_ts"]``) every ``keepalive_poll_s``. The
        SSE stream is the only liveness signal — the POST socket is byte-idle for
        the whole turn (one JSON blob at completion), so urllib's socket timeout
        can't tell a working agent from a dead one. If no SSE frame arrives for
        ``keepalive_idle_s`` the agent is hung → ``_stop_serve`` breaks the POST
        connection and we raise ``_KeepaliveAbort`` so spawn's crash-salvage gets
        an actionable reason (no more 1h空烧 on ``message_timeout``).
        ``message_timeout`` is the hard wall-clock backstop (trips if the SSE
        watchdog itself fails / the daemon reader died).

        Race-safe: if the worker produced a result it wins even if the watchdog
        tripped in the same poll window. The 429/session-gone loop wraps this
        call, so a worker HTTP error (e.g. 404 session-gone) is re-raised as-is
        and handled by the loop's existing degrade logic.
        """
        box: dict = {"msg": None, "exc": None}
        url = f"{base_url}/session/{session_id}/message"
        # D3: 外部 deadline 收紧（spawn 算 eff_msg_timeout 传入）；None → 实例默认
        mt = message_timeout if message_timeout is not None else self._message_timeout

        def _worker():
            try:
                # S5 fix: the POST socket timeout is a DUMB backstop for total
                # socket death — it must NOT be the tightened deadline (mt). The
                # opencode POST is byte-idle for the whole turn (one JSON blob at
                # completion), so a socket timeout == mt would fire at the deadline
                # BEFORE the keepalive watchdog, raising a plain URLError that
                # bypasses _KeepaliveAbort → aborted=None (the hard-wall regression).
                # The deadline is the WATCHDOG's job (hard-cap mt below); the socket
                # stays at the instance default (≥ mt) so the watchdog always wins.
                # P117 route C: timeout=0 means disabled hard cap → the worker
                # socket stays blocking (None); turn-stall/keepalive own the stop
                # via _stop_serve breaking the connection. (urlopen timeout=0 is
                # non-blocking and would fail instantly, so map 0 → None.)
                _sock_timeout = (self._message_timeout
                                 if self._message_timeout > 0 else None)
                box["msg"] = self._http_json(
                    "POST", url, body, timeout=_sock_timeout)
            except BaseException as e:  # noqa: BLE001 — surfaced via box
                box["exc"] = e

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        # P117 route C: mt=0 means the hard cap is disabled (rely on turn-stall /
        # keepalive only) — same '0 = no timeout' semantic as stage timeouts. A
        # naive time.time()+0 would set deadline=now and trip hard_timeout on the
        # first poll, so map 0 (and any non-positive value) to +inf.
        deadline = time.time() + mt if mt > 0 else float("inf")
        reason: tuple[str, str] | None = None
        # P137: turn_ts is bumped only on role=user (new exchange); a
        # genuinely long single-turn generation streams delta text WITHOUT a new
        # exchange, so turn_ts alone misreads slow-but-alive as dead. Track the
        # chars snapshot + last-growth time: the turn-stall gate below trips only
        # when BOTH the turn is stale AND chars have been static for turn_stall_s
        # — the honest signal of a hung turn, not a long one.
        _chars_snap = (sse.state.get("chars", 0) if sse is not None else 0)
        _last_chars_ts = time.time()
        # P3: one-shot warn for a turn-stall deferred due to an in-flight tool
        # call (real long compile/test), so the deferral is observable without
        # spamming one line per keepalive poll.
        while thread.is_alive():
            thread.join(timeout=self._keepalive_poll_s)
            if not thread.is_alive():
                break
            now = time.time()
            last = (sse.state.get("last_event_ts")
                    if sse is not None else None)
            if sse is not None:
                _chars = sse.state.get("chars", 0)
                if _chars != _chars_snap:
                    _chars_snap = _chars
                    _last_chars_ts = now
            # step-115 (P16)：判死分型速杀腿——chars 静止超 probe 界时读本
            # spawn 的 opencode app log；发现**晚于静默起点且 ≥2 条**的
            # stream error（错误在复发 = 网关坏窗口而非单发瞬态）且 chars 仍
            # 静止 → 立即 trip，不等残差时长界满窗（坏窗口实测错误 +14s 即
            # 现、6-12s/轮连发，~30s 即凑满 2 条；600s 等待属纯浪费）。
            # 二维判据各防一个误杀面（正交）：静默前置防 flappy-alive（输出
            # burst 间隙连出 2 条瞬态错误的活会话）；≥2 复发防单发瞬态 + 首
            # token 迟到。探针随 poll 直读（尾 64KB 页缓存读成本可忽略，不
            # 设节流——IO 动机的复杂度不值）。证据 trip 不走 db 工具探针：
            # 工具执行期无活跃流，不会产生新鲜 stream error，两证据源天然
            # 不相交。
            if (self._gateway_error_probe_s > 0 and sse is not None
                    and app_log is not None
                    and (now - _last_chars_ts) > self._gateway_error_probe_s):
                _fresh = self._gateway_error_evidence(
                    app_log, _last_chars_ts)
                if (len(_fresh) >= 2
                        and sse.state.get("chars", 0) == _chars_snap):
                    _newest = max(_fresh)
                    reason = (
                        "gateway_stream_error",
                        f"app-log stream error x{len(_fresh)} recurring "
                        f"(newest {_newest - _last_chars_ts:.0f}s into "
                        f"silence; chars static "
                        f"{now - _last_chars_ts:.0f}s > probe "
                        f"{self._gateway_error_probe_s:.0f}s) — gateway "
                        f"failure confirmed, tripping early instead of "
                        f"waiting turn_stall {self._turn_stall_s:.0f}s")
                    break
            # P117 route C (B): turn-stall gate. sse.state["turn_ts"] is bumped on
            # every new turn (message.updated role=user); no bump for the gate's
            # stall bound → trip. 0 disables (rely on keepalive / hard cap). The
            # reason carries the stalled turn's number + its active block types
            # (e.g. ``tool:read``) so the operator knows what the agent was doing
            # when it stalled — opencode emits no SSE progress during a tool
            # call, so this is the honest signal that a long-looking stall is a
            # tool, not a hang.
            if self._turn_stall_s > 0 and sse is not None:
                turn_ts = sse.state.get("turn_ts")
                if turn_ts is not None:
                    # §step-97: the old §P9 static concession (max(turn_stall,
                    # keepalive) for tool-active turns) is DELETED — it was
                    # numerically cancelled when both knobs converged to 600,
                    # and no static bound can tell a hung tool from a
                    # slow-but-legitimate one. That discrimination is now
                    # evidence-based: before tripping, the pre-trip probe reads
                    # this spawn's opencode db — a running tool part means the
                    # silence is expected (opencode emits no SSE during a tool
                    # call; 99c4c0 kill-3: bash status="running" 605s with
                    # partial output on disk while this gate killed it).
                    stall_bound = self._turn_stall_s
                    if (now - turn_ts) > stall_bound:
                        # Producer-liveness guard (P137): turn_ts is bumped
                        # only on role=user (new exchange); a genuinely long
                        # single-turn generation streams delta WITHOUT a new
                        # exchange, so turn_ts alone misreads slow-but-alive
                        # as dead. chars still growing → the turn is ALIVE
                        # (just long) — don't trip; trip only when chars have
                        # ALSO been static for stall_bound (a real hang).
                        # P117's SSE-noise case keeps chars static (noise
                        # carries no delta), preserving the gate's anti-hang
                        # role. The reason carries the chars-static window so
                        # the trip is distinguishable from a slow-but-alive
                        # turn.
                        if not ((now - _last_chars_ts) <= stall_bound):
                            if self._pretrip_tool_evidence(
                                    proc, sse, session_id, agent_name,
                                    attribution, now) != "trip":
                                # alive (tool in flight) or killed (hung tool
                                # subtree — the agent wakes with the tool
                                # error): the probe reset the baselines;
                                # re-arm instead of tripping.
                                continue
                            turn = sse.state.get("turn", 0)
                            blocks = ",".join(
                                sorted(sse.state.get("block_types") or ()))
                            activity = (f" — last turn {turn}: {blocks}" if blocks
                                        else (f" — last turn {turn}" if turn else ""))
                            reason = ("no_turn_progress",
                                      f"no new turn for {now - turn_ts:.0f}s > "
                                      f"stall bound {stall_bound:.0f}s"
                                      f" (chars static {now - _last_chars_ts:.0f}s)"
                                      + activity)
                            break
            if last is not None and (now - last) > self._keepalive_idle_s:
                # §step-97: keepalive (no SSE frame at all) is equally blind
                # during a tool call — same pre-trip evidence gate before it
                # declares death.
                if (sse is not None
                        and self._pretrip_tool_evidence(
                            proc, sse, session_id, agent_name,
                            attribution, now) != "trip"):
                    continue
                reason = ("keepalive",
                          f"no SSE activity for {now - last:.0f}s "
                          f"> idle cap {self._keepalive_idle_s:.0f}s")
                break
            if now >= deadline:
                reason = ("hard_timeout",
                          f"exceeded {mt:.0f}s hard cap")
                break

        # Worker produced a result → honor it (race-safe vs a late trip).
        if box["msg"] is not None:
            return box["msg"]
        if reason is None:
            # Worker finished without a result and without a watchdog trip → its
            # own exception (e.g. 404 session-gone) is the real signal.
            if box["exc"] is not None:
                raise box["exc"]
            return {}

        # Watchdog tripped, no result: kill serve so the blocked POST connection
        # breaks, log the actionable reason, then surface _KeepaliveAbort.
        # (spawn's finally re-stops serve idempotently.)
        # §P9: the abort carries the TRUE kind (turn_stall / keepalive /
        # hard_timeout) so crash-salvage's aborted= label never masquerades.
        Logger.error(
            f"Agent {agent_name} {attribution}abort: {reason[1]} (POST {url}); "
            f"killing opencode serve to unblock.")
        if proc is not None:
            try:
                self._stop_serve(proc)
            except Exception:  # noqa: BLE001 — best-effort connection unblock
                pass
        thread.join(timeout=5.0)
        _kind = {"no_turn_progress": "turn_stall"}.get(reason[0], reason[0])
        raise _KeepaliveAbort(f"{agent_name}: {reason[1]}", kind=_kind)

    def _stop_serve(self, proc: subprocess.Popen) -> None:
        # S4: stop the serve + its whole process group (serve + engine MCP child)
        # and drop it from the atexit-tracked set. The killpg/handle-close logic
        # lives in _cleanup_serve_proc (shared with the atexit backstop).
        _cleanup_serve_proc(proc)
        _ACTIVE_SERVE_PROCS.discard(proc)
