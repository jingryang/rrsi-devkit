"""L5 Capabilities — SDK-agnostic shared layer for agent backends.

Everything here is backend-neutral: transcript serialization, frontmatter /
agent-prompt loading, the flat-skill anchor, changed-source collection, error
classification, the stall-detection constants, and the skill-injection
rendering boundary. Both ``SDKBackend`` (claude_agent_sdk, in-process) and
``OpenCodeBackend`` (opencode serve, HTTP+SSE) import from this module so the
two backends share one implementation of these concerns (§1.6 dependency
injection / §2.5 single implementation path).

This module MUST NOT import any concrete SDK (``claude_agent_sdk`` etc.): SDK
coupling stays in the respective backend module. It depends only on stdlib +
``infra.logger``.

NOTE: ``Path(__file__).parent...`` walks here assume this file lives in
``capabilities/agent/`` (same directory as ``sdk_backend.py``); the repo-root
computation (5 levels up) is identical to the original in-place code.
"""

from __future__ import annotations

from pathlib import Path

from ascendc_devkit.domain.artifact import CONTRACT_FILES
from ascendc_devkit.domain.error import is_infra_error_type  # re-export (KNOWN 清零 step-4)
from ascendc_devkit.infra.logger import Logger
from ascendc_devkit.infra.log_capture import current_op_name


def format_attribution(stage_name: str, branch_label: str) -> str:
    """``[op_name/stage_name/branch_label] `` prefix for log/transcript lines (D8/§P2).

    Disambiguates a role agent reused across stages and N parallel branches;
    ``op_name`` (bound per-exec via ``bind_op_name``, AU-7) additionally
    disambiguates which op a line belongs to under batch concurrency, where
    several execs can share the same ``stage_name``/``branch_label``. Absent
    ``op_name`` (single-op runs never bind it) degrades cleanly to the
    original ``[stage_name/branch_label]`` format — no behavior change there.

    Q7 layer-2: an empty ``stage_name`` no longer short-circuits to ``""`` when
    ``op_name`` is bound — ``[op_name]`` alone still attributes the line to its
    op under batch concurrency (defence-in-depth: even if a stage forgets
    ``SpawnAgent.stage_name`` AND the runner fallback misses, the batch log
    keeps op attribution instead of bare unattributed lines).
    """
    op = current_op_name()
    if not stage_name and not op:
        return ""
    if op and stage_name:
        tag = f"{op}/{stage_name}"
    else:
        tag = op or stage_name
    if branch_label:
        tag += f"/{branch_label}"
    return f"[{tag}] "


def _serialize_block(block) -> dict:
    """Structure one content block from an SDK message into a jsonl-friendly dict.

    Covers the block kinds we care about for replay: text/thinking, tool_use
    (ToolUseBlock: name + input), tool_result (ToolResultBlock: content summary).
    Unknown blocks fall back to their class name so nothing is silently dropped.
    """
    kind = type(block).__name__
    # thinking has its own .thinking attribute; keep it distinct from plain
    # text so both backends are symmetric (opencode already emits kind=
    # "thinking"; the old `or`-merge here collapsed it to kind="text" by a
    # shortcut, not by design — step-68).
    thinking = getattr(block, "thinking", None)
    if thinking is not None:
        return {"kind": "thinking", "text": thinking}
    txt = getattr(block, "text", None)
    if txt is not None:
        return {"kind": "text", "text": txt}
    if getattr(block, "name", None) is not None and hasattr(block, "input"):
        return {"kind": "tool_use",
                "tool_name": block.name,
                "tool_input": block.input}
    if hasattr(block, "content") and "Result" in kind:
        content = block.content
        # Tool results may be a list of blocks or a string; summarize as text.
        if isinstance(content, list):
            parts = [getattr(c, "text", str(c)) for c in content]
            summary = "".join(parts)
        else:
            summary = str(content)
        return {"kind": "tool_result",
                "is_error": getattr(block, "is_error", None),
                "content": summary[:4000]}
    return {"kind": kind}


# IR role mapping: native SDK event class → canonical role. Replaces the old
# record["type"] (native class name) — no consumer reads "type" (harvest only
# reads block fields, verified step-68), so unifying to "role" lets both
# backends share one IR schema (the on-disk transcript record).
_EVENT_ROLE = {
    "AssistantMessage": "assistant",
    "UserMessage": "user",
    "SystemMessage": "system",
    "ResultMessage": "result",
}


def _serialize_event(event) -> dict:
    """Map one SDK message to a normalized IR record (= the on-disk transcript
    record, step-68). ``role`` replaces the native class name; ``stop_reason``
    / ``session_id`` are extracted here so the base IR consumer (not each
    subclass) owns signal extraction. ``result`` retained for ResultMessage.

    ``turn`` is NOT set here: ``IRConsumer.consume`` stamps the canonical turn
    on every record (single source of truth, step-68 task 10) — any preliminary
    value would be overwritten, so there is no ``turn`` parameter (N3, step-68
    review)."""
    import time as _time
    cls = type(event).__name__
    record = {
        "ts": int(_time.time() * 1000),
        "turn": 0,
        "role": _EVENT_ROLE.get(cls, cls),
    }
    content = getattr(event, "content", None)
    if isinstance(content, list):
        record["blocks"] = [_serialize_block(b) for b in content]
    elif content is not None:
        record["blocks"] = [{"kind": "text", "text": str(content)}]
    sr = getattr(event, "stop_reason", None) or getattr(event, "finish_reason", None)
    if sr:
        record["stop_reason"] = sr
    sid = getattr(event, "session_id", None)
    if not sid:
        # Some SDK events carry session_id nested in a `.data` dict (e.g.
        # SystemMessage(subtype="init", data={"session_id": ...})) rather than
        # as a top-level attribute. Preserves the inlined capture path
        # sdk_backend had before the IR migration (step-68 task 10) so the
        # sidecar is flushed at the FIRST event (hard-kill guarantee), not
        # delayed until a late ResultMessage that happens to expose it.
        _d = getattr(event, "data", None)
        if isinstance(_d, dict):
            sid = _d.get("session_id")
    if sid:
        record["session_id"] = sid
    # ResultMessage carries result/total_cost_usd etc.; capture a light summary.
    if getattr(event, "result", None) is not None:
        record["result"] = str(event.result)[:2000]
    return record


def _strip_frontmatter(text: str) -> str:
    """Strip a leading YAML frontmatter block from a subagent markdown file.

    Claude Code TUI discovers subagents via the ``name``/``description``
    frontmatter at the top of ``.claude/agents/*.md``. The SDK only needs the
    body as the system prompt, so we drop the frontmatter if present. Files
    without frontmatter are returned unchanged.
    """
    if not text.startswith("---"):
        return text
    lines = text.splitlines(keepends=True)
    # lines[0] is the opening '---'; find the closing fence.
    for i in range(1, len(lines)):
        if lines[i].rstrip() == "---":
            return "".join(lines[i + 1:]).lstrip("\n")
    # No closing fence — treat the whole file as body (malformed frontmatter).
    return text


def _resolve_project_settings() -> str | None:
    """Resolve the absolute path to the project's .claude/settings.json.

    The agent is spawned with cwd set to a deep artifacts dir (e.g.
    output/<run>/artifacts/<stage>). The Claude Code CLI discovers
    .claude/settings.json by walking *up* from cwd, and in headless mode that
    discovery does not reliably reach the project root from such a deep cwd —
    the symptom is "Not logged in" because the env block (ANTHROPIC_BASE_URL /
    ANTHROPIC_AUTH_TOKEN) is never loaded.

    Pinning ClaudeAgentOptions(settings=<abs path>) makes the CLI load this one
    file regardless of cwd depth, giving a single config source shared with the
    TUI. Returns the absolute path as a string, or None when the file is absent
    (e.g. in tests/installed layouts) so the SDK falls back to default discovery.
    """
    project_root = Path(__file__).parent.parent.parent.parent.parent
    for base in (project_root, Path.cwd()):
        candidate = base / ".claude" / "settings.json"
        if candidate.exists():
            return str(candidate.resolve())
    return None


def _ensure_skills_anchor(effective_cwd: Path | None) -> None:
    """Anchor the canonical flat skill tree at ``<cwd>/.claude/skills``.

    Claude discovers flat ``.claude/skills/<name>/SKILL.md`` ONLY at
    ``cwd/.claude/skills`` (shallow): it does not walk up from a deep artifacts
    cwd to the repo root, and ``add_dirs`` does not trigger discovery (verified
    empirically, V1/V5/V7). The agent is spawned with cwd set to a deep
    artifacts dir, so the canonical repo ``.claude/skills`` is invisible there
    unless anchored. Create an idempotent per-workspace symlink
    ``<cwd>/.claude/skills -> <repo>/.claude/skills`` so native discovery finds
    the single canonical tree without copying it.

    No-op when cwd already IS the repo root (the real tree is already at
    ``cwd/.claude/skills``) or the canonical tree is absent (installed/test
    layouts). A pre-existing non-symlink at the anchor is left untouched and
    warned (diagnosable, never clobbers a real dir).
    """
    if not effective_cwd:
        return
    repo_skills = (Path(__file__).parent.parent.parent.parent.parent
                   / ".claude" / "skills")
    if not repo_skills.is_dir():
        return  # nothing canonical to anchor (installed/test layout)
    target = repo_skills.resolve()
    anchor = effective_cwd / ".claude" / "skills"
    if anchor.is_symlink():
        try:
            if anchor.resolve() == target:
                return  # correct anchor already in place (idempotent)
        except OSError:
            pass
        try:
            anchor.unlink()  # wrong target — rebuild
        except OSError as e:
            Logger.warn(f"could not replace stale skills anchor {anchor}: {e}")
            return
    elif anchor.exists():
        try:
            if anchor.resolve() == target:
                return  # cwd is the repo root: real tree already here
        except OSError:
            pass
        Logger.warn(
            f"skills anchor {anchor} exists and is not a symlink; leaving as-is")
        return
    try:
        anchor.parent.mkdir(parents=True, exist_ok=True)
        anchor.symlink_to(target, target_is_directory=True)
    except OSError as e:
        Logger.warn(f"could not create skills anchor {anchor} -> {target}: {e}")


def _agent_prompt_search_paths(agent_name: str) -> list[Path]:
    project_root = Path(__file__).parent.parent.parent.parent.parent
    return [
        # Primary: shared with Claude Code TUI subagent discovery.
        project_root / ".claude" / "agents" / f"{agent_name}.md",
        Path.cwd() / ".claude" / "agents" / f"{agent_name}.md",
        # Legacy fallbacks.
        Path(__file__).parent.parent.parent.parent / "resources" / "agents" / f"{agent_name}.md",
        Path.cwd() / "resources" / "agents" / f"{agent_name}.md",
    ]


def _find_agent_prompt(agent_name: str) -> str:
    for p in _agent_prompt_search_paths(agent_name):
        if p.exists():
            return _strip_frontmatter(p.read_text(encoding="utf-8"))
    return f"You are {agent_name}. Complete the task as described."


def agent_prompt_is_placeholder(agent_name: str) -> bool:
    """True when no agent.md exists for ``agent_name`` and ``_find_agent_prompt``
    would fall back to the generic placeholder system prompt.

    Used by load-time validation (workflow.validate_chain) to fail fast on a
    spawn stage whose agent_name resolves to no real system prompt — the silent
    degradation that left P1's design agents running on a bare placeholder.
    This is a pure check: it does not change spawn-time behavior (the fallback
    stays, so a stray reference never hard-crashes a running spawn).
    """
    return not any(p.exists() for p in _agent_prompt_search_paths(agent_name))


def _scan_working_dir(working_dir: Path) -> dict[str, str]:
    """Scan working_dir for source files produced by the agent."""
    artifacts = {}
    if not working_dir or not working_dir.exists():
        return artifacts
    for f in working_dir.rglob("*"):
        if f.is_file() and f.suffix in (".cpp", ".h", ".hpp", ".py", ".yaml", ".json"):
            rel = str(f.relative_to(working_dir))
            try:
                artifacts[rel] = f.read_text(encoding="utf-8")
            except Exception:
                pass
    return artifacts


_SOURCE_SUFFIXES = (".cpp", ".h", ".hpp", ".py", ".yaml", ".json")

# Stall detection: if this many consecutive assistant turns produce neither new
# response text nor any tool_use block, the agent is spinning with no progress.
# We break out and collect whatever was already written rather than burning the
# remaining turn/stage-timeout budget. Kept conservative (>1) because a single
# pure tool-call turn legitimately produces no text.
#
# P6-a: fixed single threshold is too aggressive for bootstrapping agents that
# must Read 4+ upstream files before producing output. During the first
# BOOTSTRAP_GRACE_TURNS we allow up to BOOTSTRAP_MAX_STALLED no-progress turns;
# after that we tighten to NORMAL_MAX_STALLED_TURNS. This halves false-positive
# stalls (evidence: HalfRotation buffer-kernel survived 7 turns of Read-only
# bootstrap; InterleaveRotation was killed at turn 9 before it could produce).
MAX_STALLED_TURNS = 3              # keep as doc-default for non-adaptive paths
BOOTSTRAP_GRACE_TURNS = 8          # first N turns: relaxed stall threshold
BOOTSTRAP_MAX_STALLED = 5          # grace period: up to 5 consecutive idle turns
NORMAL_MAX_STALLED_TURNS = 4       # post-grace: tighten to 4

# §P7.3: how many recent tool_use fingerprints to remember when deciding whether
# a tool call is a "new" action vs a verbatim repeat (idle-spin). Small window:
# a legitimate re-read after editing a file is fine; it's the back-to-back
# identical calls within a few turns that signal a stall.
_TOOL_SIG_WINDOW = 6


def _tool_use_signature(block) -> str:
    """A stable fingerprint of a tool_use block = tool name + its input args.

    Two calls with the same name AND the same input are treated as the same
    action; re-issuing one verbatim is the hallmark of an idle-spin, not progress.
    """
    name = getattr(block, "name", "") or ""
    raw = getattr(block, "input", None)
    try:
        import json as _json
        args = _json.dumps(raw, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        args = str(raw)
    return f"{name}:{args}"


def _scan_tool_results(event) -> tuple[bool, bool]:
    """Inspect an event for tool_result blocks (they ride on UserMessage).

    Returns ``(all_errored, any_seen)``: ``any_seen`` is True when the event
    carried at least one tool_result; ``all_errored`` is True when every
    tool_result seen reported ``is_error``. Used so the next assistant turn can
    tell whether its prior tool calls actually accomplished anything — a turn
    whose tool calls all errored is not progress (§P7.3). Never raises.
    """
    content = getattr(event, "content", None)
    if not isinstance(content, list):
        return False, False
    seen = False
    errored = True
    for block in content:
        kind = type(block).__name__
        if hasattr(block, "content") and "Result" in kind:
            seen = True
            if not getattr(block, "is_error", False):
                errored = False
    return (errored if seen else False), seen

# step-5a B2-resume: the proxy intermittently mis-numbers SSE content_block
# indices when a turn carries thinking+text+tool_use, and the CLI streaming
# state machine then raises "Content block not found" (~1/3 of such turns;
# the same error the TUI hits, where a human just says "continue"). It is a
# transient, resumable fault — not a logic failure — so we resume the crashed
# session by session_id rather than failing the whole spawn.
_TRANSIENT_ERROR_MARKERS = ("Content block not found",)


# P50: infra-class failures — the agent never ran its logic because the
# environment is misconfigured or unavailable. These are intentionally NOT in
# _TRANSIENT_ERROR_MARKERS: retrying within the run is futile (a missing
# gateway channel won't appear, a quota window won't close, a bad credential
# won't heal). error_type="infra" lets stages avoid burning iteration/breaker
# budgets on something that would never succeed this pass, and halt cleanly
# with an actionable reason instead. "No available channel" is a local config
# gap (the distributor has no upstream for the requested model), NOT a
# transient gateway blip — confirmed by the user.
_INFRA_ERROR_MARKERS = (
    "No available channel",   # no upstream channel for the model (config gap)
    "Usage limit reached",    # quota window (hours) — retry futile until reset
    "API Error: 401",         # auth
    "API Error: 403",         # auth
    # P93 (run 20260720-095303-413565): two more infra shapes that burned a
    # design-substage's retry budget because they fell through to "logic
    # failure". Neither carries a parseable statusCode at the backend seam
    # (opencode except str(e) / gateway message text), so they are matched as
    # text like the rest of this set.
    "timed out",              # backend HTTP spawn timeout (message_timeout wall)
    "price not configured",   # gateway 400: model has no price (EN, new-api/one-api)
    "价格未配置",              # gateway 400: model has no price (ZH)
    "Invalid token",          # gateway 401 auth, new-api wrapper wording (P92 旁证)
)


def _classify_error_type(text: str | None) -> str | None:
    """Return ``"infra"`` when ``text`` names a config/quota/auth failure the
    agent cannot fix by retrying, else ``None`` (logic/default failure). See
    ``_INFRA_ERROR_MARKERS`` for the rationale."""
    if text and any(m in text for m in _INFRA_ERROR_MARKERS):
        return "infra"
    return None


def classify_spawn_exception(exc: BaseException | None,
                             crash_reason: str | None) -> str | None:
    """异常类型 → ``error_type`` 的单一分类点（§2.5 两 backend 共用）。

    - 连接类异常（``ConnectionError``，覆盖 ``http.client.RemoteDisconnected`` /
      ``ConnectionResetError`` 等 spawn 期连接重置/断开）→ ``"infra_transient"``
      （瞬时、值得 fresh resample）。
    - 其余回落到 ``_classify_error_type`` 文案分类（``"infra"``=永久 config/quota/
      auth，或 ``None``=logic/默认）。

    按异常**类型**判连接故障（文案变体几十种，marker 追不上）；``aborted``（看门狗
    杀活 spawn）由 backend 另行计算，与本函数正交、互不冒充（§1.10 不混淆语义）。
    """
    if exc is not None and isinstance(exc, ConnectionError):
        return "infra_transient"
    return _classify_error_type(crash_reason)




def is_infra_failure(result) -> bool:
    """业务语义（§1.10）：agent「没干净跑完一轮」——被杀(aborted) / 环境故障
    (error_type 非空，含 ``infra_transient`` 与 ``infra``)。

    这类失败值得**有界** fresh resample（默认 fail-open，halt 仅预算耗尽）。不含
    ``cut``（cut 有自己的 cut-streak 机制）；logic 失败（error_type 为 None 且未 aborted）
    不进此谓词。**不**用 ``status in ("partial","fatal")`` 判 infra——"fatal" 在
    AgentResult 上既表「spawn 崩」也（历史测试里）表「逻辑失败」，语义歧义；权威的
    「没干成活」信号是 ``_build_result`` 对**所有** crashed 结果都置非空 error_type
    （未知 crash → 兜底 ``infra_transient``），故本谓词只认 error_type / aborted。
    """
    return (getattr(result, "aborted", None) is not None
            or getattr(result, "error_type", None) is not None)


# step-57 (P80): 429 burst rate-limit — a server-side SOFT rejection where the
# session is NOT broken and a resume after a backoff sleep can continue (the
# batch 20260715 runlog proved this is a burst throttle, not an account hard
# cap: manifold hit 429 mid-integrate yet resumed 3× to a clean DONE while
# peer ops kept running). These are deliberately kept OUT of both
# _TRANSIENT_ERROR_MARKERS (which shares the no_progress gate — wrong for 429,
# whose rejected turn adds no text/tool/file and would trip that gate on the
# first hit) and _INFRA_ERROR_MARKERS (whose members — No available channel /
# 401 / 403 — are un-retryable config/auth gaps; retrying them is futile). 429
# gets its OWN bounded exponential-backoff resume budget (see the backend
# _spawn loop + compute_backoff_seconds). Burst-vs-hard-quota is NOT
# distinguished by wording (both may say "Weekly/Monthly Limit Exhausted") — a
# true hard quota simply exhausts the backoff/total-time cap and then halts
# with an actionable reason (step-57 L3 §6).
_RATE_LIMIT_MARKERS = (
    "Request rejected (429)",   # observed wording: "Request rejected (429) · …"
    "(429)",                    # fallback: variant phrasings still carry (429)
    # 本网关(new-api/oneapi distributor)的限流措辞——与 (429) 同义,都是可退避
    # 重试的 SOFT 拒绝;实测透传形如
    #   AI_APICallError: [1310][Weekly/Monthly Limit Exhausted. Your limit will reset at ...]
    #   AI_APICallError: [1313][...Fair Usage Policy...request frequency has been limited]
    # (不含 "(429)",故上面两项匹配不到——曾致框架重试未触发、run.log 静默爬行)。
    # burst vs 硬配额仍不靠措辞分(见上方注释),靠 backoff 预算耗尽→halt:
    "[1310]",                       # Weekly/Monthly Limit Exhausted
    "[1313]",                       # Fair Usage Policy frequency limited
    "Weekly/Monthly Limit Exhausted",
    "Fair Usage Policy",
    "frequency has been limited",
)


def _is_rate_limit_error(text: str | None) -> bool:
    """True when ``text`` names a 429 burst rate-limit that should be retried
    after a backoff sleep by resuming the same session (step-57). Distinct from
    ``_is_transient_error`` (SSE stream faults, no_progress gate) and
    ``_classify_error_type`` (infra, un-retryable) — see ``_RATE_LIMIT_MARKERS``."""
    if not text:
        return False
    return any(m in text for m in _RATE_LIMIT_MARKERS)


# P131b (trial-20260730): transient server-unavailable / upstream-timeout shapes
# that, like a 429, are a SOFT rejection where the session survives and a
# backoff-resume of the SAME session can continue. The trial storm showed the
# gateway rejecting with 503 / ServiceUnavailable / APITimeout amid the 429s;
# these fell through the 429 gate (no "(429)" substring) into "logic failure",
# so the in-session backoff never engaged. Kept OUT of _INFRA_ERROR_MARKERS
# (those are permanent config/auth gaps — retry futile) and OUT of
# _RATE_LIMIT_MARKERS (a 503 is not a rate limit; conflating them would mislabel
# the diagnostic). They share the 429 backoff-resume MECHANISM but keep their
# own honest wording. NOTE: this only helps when opencode surfaces the error
# cleanly; a silent gateway hang is caught by the turn-stall watchdog +
# cross-run backoff-resume (P131c) instead.
_SOFT_RETRY_MARKERS = (
    "API Error: 503",
    "Error: 503",
    "status 503",
    "ServiceUnavailable",
    "Service Unavailable",
    "APITimeout",
    "APIConnectionError",
)


def _is_soft_retry_error(text: str | None) -> bool:
    """True when ``text`` names a transient server-unavailable / upstream-timeout
    fault that should be backoff-resumed in-session like a 429 (P131b). Union
    with ``_is_rate_limit_error`` forms the backend's in-session soft-retry gate."""
    if not text:
        return False
    return any(m in text for m in _SOFT_RETRY_MARKERS)


def compute_backoff_seconds(attempt: int, base_s: float, factor: float,
                            elapsed_total_s: float,
                            max_total_s: float) -> float | None:
    """Seconds to sleep before the next 429 resume attempt, or ``None`` when the
    total-time cap is exhausted (caller must then stop retrying and halt).

    Exponential: the uncapped want is ``base_s * factor ** attempt`` (``attempt``
    is 0-based — the first backoff uses ``factor ** 0 == 1`` → ``base_s``). The
    returned sleep is clamped to the remaining total budget so cumulative sleep
    never exceeds ``max_total_s`` (step-57 L3 §5: the cap is the hard-quota
    stop-loss — never sleep for hours on a true quota wall). Returns ``None``
    the moment ``elapsed_total_s >= max_total_s`` so a caller loop terminates
    deterministically rather than sleeping 0s forever."""
    if elapsed_total_s >= max_total_s:
        return None
    want = base_s * (factor ** attempt)
    remaining = max_total_s - elapsed_total_s
    return min(want, remaining)


def should_server_backoff(text: str | None) -> bool:
    """黑名单排除语义（§2.5 单一来源，opencode/sdk 两 backend 共用）：非空错误文本
    且非 infra（不可重试 auth/quota/config）→ 应 in-session backoff resume。覆盖
    429/503/APIError/type validation/未知服务端错误；infra 不 backoff（P116 立即
    halt）；成功（空文本）不 backoff。"""
    if not text:
        return False
    return _classify_error_type(text) != "infra"


def advance_backoff(attempt: int, elapsed_s: float, *,
                    base_s: float, factor: float, max_total_s: float,
                    max_retries: int) -> tuple[float | None, int, float]:
    """一次 in-session backoff 预算推进（纯逻辑，无 I/O；两 backend 共用）。
    返回 ``(sleep_s, next_attempt, next_elapsed_s)``；预算耗尽（累计 sleep 达
    max_total_s 或 attempt 达 max_retries）→ ``sleep_s=None``（attempt/elapsed 不
    推进，调用方据此 break → halt）。adapter 特有条件（如 sdk 无 session_id）留
    调用方自行检查，不进本函数。"""
    sleep_s = compute_backoff_seconds(attempt, base_s, factor, elapsed_s, max_total_s)
    if sleep_s is None or attempt >= max_retries:
        return None, attempt, elapsed_s
    return sleep_s, attempt + 1, elapsed_s + sleep_s


def server_backoff_strategy(text: str | None) -> str | None:
    """服务端错误的恢复策略（§2.5 单一来源，两 backend 共用）：
    - ``"backoff"``：429/503 限流/不可用——需 sleep 等窗口再 resume（指数退避，有界）。
    - ``"resume"``：其他非 infra 服务端错误（APIError/type validation/未知）——
      **立即 resume 同一会话、不 sleep**，有限次。误判时空等风险低（只浪费一次重试
      预算，不空等）——SSE transient 空等回归（20260812）的根治方向。
    - ``None``：成功（空文本）/ infra（不可重试）——不处理，调用方决定。
    ``_is_transient_error``（SSE 流故障）判定由 sdk 调用方先做（走 D2 立即 resume），
    不进本函数（opencode 无 transient 概念）。"""
    if not text:
        return None
    if _is_rate_limit_error(text) or _is_soft_retry_error(text):
        return "backoff"
    if should_server_backoff(text):
        return "resume"
    return None

# Proposal #1: markers that the session being resumed is gone/expired (TTL
# lapsed, transcript unavailable, or the SDK never persisted it). Such a crash
# on the FIRST query of a resume spawn is NOT a logic failure and NOT worth
# salvaging — the right move is to abandon resume and start a fresh spawn
# (degrade, internal to the backend). Matched case-insensitively against the
# crash text (last_result_text OR str(last_exc) — the SDK usually raises rather
# than emitting a ResultMessage for this).
_SESSION_GONE_MARKERS = (
    "session not found",
    "session expired",
    "no such session",
    "session does not exist",
    "could not resume",
    "unable to resume session",
    # Real SDK wording observed on a bogus/expired resume (claude_agent_sdk
    # 0.2.x): the CLI prints "No conversation found with session ID: <id>" to
    # its stderr, which we tee into the crash text via the options.stderr
    # callback below. "conversation" is the SDK's term for a resumable session.
    "no conversation found",
    "conversation not found",
    "no such conversation",
)


def _is_session_gone(text: str | None) -> bool:
    """True when ``text`` indicates the resumed session is gone/expired (see
    ``_SESSION_GONE_MARKERS``). Case-insensitive — the SDK error wording varies."""
    if not text:
        return False
    low = text.lower()
    return any(m in low for m in _SESSION_GONE_MARKERS)


# M1 (step-68 review): opencode's session-gone signal — DIFFERENT shape from
# claude's. Probe-confirmed against a real ``opencode serve`` (1.18.x): a real
# ``ses_…`` session id that no longer exists (purged / TTL'd / cross-device
# sidecar reuse — the actual stale-resume scenario) returns
# ``HTTP 404 {"name":"NotFoundError","data":{"message":"Session not found: <id>"}}``.
# (Malformed ids 500 with a generic UnknownError; that is NOT the resume case —
# a sidecar only ever holds a real ``ses_`` id opencode itself issued.) So the
# canonical signal is the HTTP 404 STATUS (correct REST semantics for a missing
# resource), with the NotFoundError / "session not found" body wording as a
# belt so wording drift alone can't silently disable the degrade. This is an
# HTTP/JSON error raised by _http_json — NOT claude's SDK exception text (see
# ``_SESSION_GONE_MARKERS``) and NOT the ``info.error`` field ``_parts_to_records``
# surfaces (that field captures model-side errors returned as 200-with-info.error;
# a gone session never reaches a 200). Do not collapse the two detection paths.
_OPENCODE_SESSION_GONE_STATUS = 404
_OPENCODE_SESSION_GONE_MARKERS = (
    "session not found",
    "notfounderror",
)


def _opencode_gone_text(exc) -> str:
    """Best-effort status + body text from an opencode transport exception
    (urllib ``HTTPError``): ``str(exc)`` carries "HTTP Error 404: Not Found" but
    NOT the JSON body, so we also read ``.read()`` (which carries the
    ``Session not found`` wording). Consumes the body — callers must not re-read.
    Never raises."""
    bits = [str(exc)]
    code = getattr(exc, "code", None)
    if code:
        bits.append(f"status={code}")
    try:
        raw = exc.read()
        if raw:
            bits.append(raw.decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001 — body extraction is best-effort
        pass
    return " ".join(bits)


def _is_opencode_session_gone(exc) -> bool:
    """True when *exc* is opencode's session-gone signal: HTTP 404 (the canonical
    missing-resource status) OR the NotFoundError body wording (belt). See
    ``_OPENCODE_SESSION_GONE_MARKERS`` for the probe evidence and the rationale
    for NOT reusing claude's ``_is_session_gone`` (different error shape)."""
    if getattr(exc, "code", None) == _OPENCODE_SESSION_GONE_STATUS:
        return True
    text = _opencode_gone_text(exc).lower()
    return any(m in text for m in _OPENCODE_SESSION_GONE_MARKERS)

# P6: stall-break triggers async generator aclose() which can race with the
# background task and raise "asynchronous generator is already running". This is
# non-fatal: the stall detection already stopped cleanly — aclose() is just
# cleanup noise, not a real crash. Treated as a non-crash transparently.
# P6-a fix: use str(e) for matching (the exception __str__ may differ from its
# repr/args) and handle the common form "aclose(): asynchronous generator is
# already running" as well as the bare form.
_ACLOSE_ERROR_MARKERS = (
    "asynchronous generator is already running",
    "already running",
)
# Alias for backward compatibility with test imports expecting the singular name.
_ACLOSE_ERROR_MARKER = _ACLOSE_ERROR_MARKERS[0]

# Prompt used when resuming a crashed session. A resumed claude_agent_sdk
# session already carries its full conversation context, so — per real TUI
# resume experience — a bare "继续" is sufficient for the model to pick up
# where it left off. The stage's original prompt is deliberately NOT replayed:
# the session knows its own task, and a verbose re-instruction would over-
# constrain or be read as a fresh directive rather than a continue nudge.
_RESUME_PROMPT = "继续"

# 硬切分类的兜底提示（仅当判切点分类 cut_hard=True 时的 resume 首条消息，
# 显式 resume_prompt 恒优先；首次执行零注入）。语义：thinking 分步独立、被截
# 不可续——兜底只引导把后续思考转成落盘产物（落盘不丢 + 切步重置单步输出
# 预算）。事实 + 可执行建议，非门。
_HARD_CUT_RESUME_PROMPT = (
    "上一步思考在输出中被截断。请先把已得出的结论落成草稿，"
    "再边落边思考继续——已落盘的推导不会被截断丢失。")


def _is_transient_error(text: str | None) -> bool:
    """True when `text` names a known transient/resumable SDK streaming error
    (step-5a). Matches on the exact marker string so genuine logic failures
    are never silently retried."""
    if not text:
        return False
    return any(marker in text for marker in _TRANSIENT_ERROR_MARKERS)


def _collect_changed_sources(cwd: Path, repo_guard=None, baseline: str = "",
                             repo_root: Path | None = None,
                             has_baseline: bool = False) -> dict[str, str]:
    """Collect this run's changed files as {relative_path: content}.

    Authority = git only（step-109 单通路收口）：``repo_guard.changed_paths``
    （tracked diff ∪ untracked，含删除）+ ``deleted_paths``（删除标签）。
    agent 自报通路（changed_files.json 解析/并集/交叉校验 WARN）已删——其信息
    100% 可由 git 构造性派生（§1.14 不让模型填表、§2.5 唯一通路、§2.9 派生
    优于检查门）。

    Deleted files are recorded with an empty body (path kept, not read).

    Degradation: only when NO usable baseline exists (``has_baseline`` False)
    do we fall back to a scoped scan of op_dir. When a baseline IS available
    and git reports nothing, the run genuinely changed nothing — return an
    empty dict rather than mis-scanning a pre-existing operator directory as
    if it were this run's output (which would otherwise snapshot the whole
    op_dir on an early agent crash).

    契约元数据（``CONTRACT_FILES``：codegen_manifest / decision_log /
    changed_files 等）照常进本 dict（下游 ``artifacts.get`` 读点依赖），但
    **不进派生 changed-source 报告**（非算子改动）；落盘分类归
    ``_persist_sources`` 的名单路由（§1.15 单点两消费）。
    """
    if not cwd:
        return {}
    op_dir = Path(cwd)

    # git side (authority): changed paths + deletion labels.
    diff_paths: list[str] = []
    deleted_set: set[str] = set()
    rr = Path(repo_root) if repo_root else op_dir
    # M3（review 整改）：filebackup: 前缀基线是 repo_guard 的非 git 降级态——
    # git 侧对其恒空是「不适用」而非「零改动」。此形态按「无可用 git 真值
    # 基线」处理（降级 scan），否则非 git 环境的产物收集恒空零信号，与
    # 「本轮零产出」不可区分。
    _git_baseline = (repo_guard.is_git_baseline(baseline)
                     if repo_guard is not None and baseline else False)
    if repo_guard is not None and baseline and _git_baseline:
        try:
            for p in repo_guard.changed_paths(rr, op_dir, baseline):
                # changed_paths returns repo-relative; make them op_dir-relative.
                ap = (rr / p).resolve()
                try:
                    diff_paths.append(str(ap.relative_to(op_dir.resolve())))
                except ValueError:
                    continue  # outside op_dir → ignore (scope safety)
            for p in repo_guard.deleted_paths(rr, op_dir, baseline):
                ap = (rr / p).resolve()
                try:
                    deleted_set.add(str(ap.relative_to(op_dir.resolve())))
                except ValueError:
                    continue
        except Exception as e:
            # F6（review 整改）：文案与真实行为一致——git 侧失败后走「无 git
            # 信号」分支（基线在则空、否则 scan），不承诺 scan。
            Logger.warn(f"git diff collection failed; treating as no git "
                        f"signal: {e}")

    # No usable signal.
    if not diff_paths:
        if has_baseline and (repo_guard is None or _git_baseline):
            # git 真值基线在场 + 零改动 = this run produced nothing.
            # Do NOT scan the (pre-existing) op_dir as if it were our output.
            # （guard 缺位时无法核验基线性质——保守沿用「有基线即不 scan」；
            # 唯 filebackup 降级态翻 scan，见上方 M3 注释。）
            return {}
        # 无 git 真值基线（缺失/filebackup 降级态）→ degrade to a scoped scan
        # of op_dir（原始面，契约文件照带——分类归落盘名单路由，§1.15）。
        return _scan_working_dir(op_dir)

    def _git_op(p: str) -> str:
        return "deleted" if p in deleted_set else "modified"

    artifacts: dict[str, str] = {}
    for rel in sorted(diff_paths):
        if rel == "changed_files.json":
            continue  # agent 版自报文件不收集（框架派生版覆盖此键）
        if _git_op(rel) == "deleted":
            artifacts[rel] = ""  # record path, no content
            continue
        fpath = op_dir / rel
        if fpath.is_file():
            try:
                artifacts[rel] = fpath.read_text(encoding="utf-8")
            except Exception:
                artifacts[rel] = ""

    # §2.9 构造性保证：changed_files 报告由 git diff（真值）机械可派生。无论
    # agent 是否写了自报/写在哪/什么格式，框架都从 git 派生权威报告落进
    # artifacts——审计链永远完整，不依赖 LLM 纪律（20260810 批 6/6 假
    # "didn't report" 根因后所修；step-109 删自报双轨，此派生为唯一通路）。
    # 报告仅算子源码：CONTRACT_FILES 契约元数据不是算子改动，不进报告。
    report_paths = [p for p in sorted(diff_paths) if p not in CONTRACT_FILES]
    # F7（review 整改）：①派生报告带 ``derived`` 来源标记——降级 scan 照带的
    # agent 自写 changed_files.json 无此标记，消费方可辨真伪；②报告恒在：
    # 纯契约轮写空 changed_files 列表而非缺键（「本轮零算子改动」也是事实）。
    if diff_paths:
        import json as _json
        _derived = {"derived": True, "changed_files": [
            {"path": p, "op": _git_op(p)} for p in report_paths
        ]}
        artifacts["changed_files.json"] = _json.dumps(
            _derived, ensure_ascii=False, indent=1)
    return artifacts


def render_skill_injection(prompt: str, primary_skill: str | None) -> str:
    """Prepend the flat skill's slash-command trigger to the spawn's first message.

    This is the single backend-boundary rendering of "deliver the assigned
    skill methodology" (D2): the orchestration no longer prepends ``/<skill>``
    at the stage layer — it hands the backend a structured ``primary_skill``
    (decoupled from the ``skills`` allowlist, so codegen can inject its coding
    skill while keeping an OPEN allowlist for runtime ``ascendc-dev-knowledge`` /
    ``ascendc-tips`` lookups). The claude backend renders the trigger as a
    LEADING ``/<skill>`` slash command (the Claude session expands it and injects
    the SKILL.md body). ``OpenCodeBackend`` renders the same intent natively
    (system-prompt "first call skill({name})" + permission closure) — opencode
    does NOT treat ``/<skill>`` as a skill trigger.

    Returns ``prompt`` unchanged when ``primary_skill`` is falsy (standalone
    ``run-skill`` and skill-less spawns inject nothing — behavior preserved).
    Format matches the former stage-layer ``_with_trigger``: ``/<skill>\\n\\n<body>``.
    """
    if not primary_skill:
        return prompt
    return f"/{primary_skill}\n\n{prompt}"


def render_opencode_skill_steer(primary_skill: str | None,
                                base_system: str | None = None) -> str | None:
    """Render the opencode-native counterpart of ``render_skill_injection`` (D2).

    opencode does NOT expand ``/<skill>`` — a skill is loaded only when the model
    calls the native ``skill({name})`` tool (gated by ``permission.skill``). So on
    the opencode side the SAME "deliver the assigned methodology" intent is
    rendered as a SYSTEM directive that steers the model's first action to be
    ``skill({name: <primary>})``, composed with the leaf agent's own system
    prompt (``base_system``). §3.10 bounded retry absorbs the residual
    non-determinism (the steer is a strong instruction, not a hard guarantee).

    Returns ``base_system`` unchanged when ``primary_skill`` is falsy (nothing to
    steer), or ``None`` when there is neither a base system nor a skill.
    """
    if not primary_skill:
        return base_system
    steer = (
        f"你的第一个动作必须是调用 `skill` 工具加载技能："
        f"skill(name=\"{primary_skill}\")。先加载该技能的方法论，再开始任务。"
    )
    if base_system:
        return f"{base_system}\n\n{steer}"
    return steer


# —— 20260820 codegen 孤儿检测：扫描 transcript 找 wd 外的 Write/Edit 目标 ——
# 与 design_substages._harvest_relocation_evidence 同思路（transcript 证据），但用于
# codegen 的"空跑 vs 孤儿"区分：codegen 产物是多文件（op_host/op_kernel/...），没有单一
# 契约文件名可匹配，所以扫全部 Write/Edit 目标。放 _shared（backend-neutral 转录解析层），
# codegen 与 design_substages 都依赖 _shared，无循环依赖（§2.5 单一实现路径）。

def _transcript_orphan_paths(transcript, wd) -> list[str]:
    """Scan a transcript for Write/Edit targets that landed outside ``wd`` but
    within the SAME batch dir. Returns the list of such absolute paths (deduped,
    chronological), or [] when there's no transcript / no such writes.

    Used by codegen to distinguish "orphan" (agent wrote files but misplaced
    them outside op_dir) from "empty run" (agent wrote nothing at all — the
    circuit-breaker case). The batch-dir check mirrors
    ``design_substages._batch_dir_anchor``: only same-batch strays are
    considered (a cross-batch write is a different run's file, not ours).

    Best-effort: unreadable transcripts / malformed jsonl are skipped, never
    raised — this is diagnostic evidence, not a required input.
    """
    if not transcript or not wd:
        return []
    from pathlib import Path
    tp = Path(transcript)
    if not tp.is_file():
        return []
    wd_resolved = Path(wd).resolve()
    wd_batch = _batch_dir_anchor_shared(wd_resolved)
    out: list[str] = []
    seen: set[str] = set()
    try:
        lines = tp.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            import json as _json
            event = _json.loads(line)
        except _json.JSONDecodeError:
            continue
        for block in event.get("blocks", []) or []:
            target = _extract_write_target_shared(block)
            if not target:
                continue
            cand = Path(target)
            try:
                if cand.resolve().is_relative_to(wd_resolved):
                    continue  # inside wd — not an orphan
            except (OSError, ValueError):
                pass
            cand_batch = _batch_dir_anchor_shared(cand.resolve())
            # batch 判定分两情形（20260820）：
            #   - wd 有 batch 锚点（design 子阶段，wd 在 artifacts 树下）→ 孤儿必须
            #     同 batch，跨 batch 明确拒绝（防跨 run 误搬/误判）。
            #   - wd 无 batch 锚点（codegen，op_dir 在 cann-bench 仓、不在 artifacts
            #     树）→ batch 锚点无意义，只看"wd 外 + transcript 证据"就算孤儿。
            #     若孤儿恰好能解析 batch 锚点且 ≠ wd 的（跨 batch），仍拒绝。
            if wd_batch is not None:
                if cand_batch is None or cand_batch != wd_batch:
                    continue
            key = str(cand.resolve())
            if key not in seen:
                seen.add(key)
                out.append(key)
    return out


# —— 孤儿产物检测层（single authority，20260821 全局收口）—————————————————
# transcript → orphan evidence。本模块是孤儿检测的**唯一权威源**：design 子阶段、
# codegen、precision-debug（control.json）、test-design（CSV/report）全部从这里 import；
# 各 stage 不得再持有本地拷贝（F1/F2 时期 design_substages 与此处并存过两份"Mirrors"
# 拷贝，20260821 收编）。处置（搬回/反馈重生成）归 orchestration/artifact_recovery.py
# 与各 stage 策略；这里只回答"agent 是否把 X 写到了 wd 之外、在哪"。

def _normalize_stem(name: str) -> str:
    """Fold a filename stem for tolerant matching: lowercase + drop separators
    (underscore / hyphen / dot). ``tiling_buffer_kernel`` ≈ ``TilingBufferKernel``
    ≈ ``tiling-buffer-kernel`` ≈ ``tiling.buffer.kernel`` (P62 name relaxation)."""
    import re
    return re.sub(r"[_\-.]+", "", (name or "").lower())


def _extract_write_target_shared(block: dict) -> str | None:
    """Extract the written file path from a tool_use block, TOLERANT of both
    backend transcript schemas (§1.1 the harvester must not couple to one).

    - SDK backend: ``tool_name`` ∈ {"Write","Edit","MultiEdit"}, path at
      ``tool_input.file_path``.
    - opencode backend: ``tool_name`` is lowercase ("write"/"edit"), and the
      real args are nested one level under opencode's tool-state object
      (``tool_input.input.filePath`` — camelCase, nested). A harvester that
      reads only ``tool_input.file_path`` is silently blind to every opencode
      write (the exact gap of batch 20260729 d67f55).

    Returns the path string, or None when this block is not a write or carries
    no recognizable path key."""
    if block.get("kind") != "tool_use":
        return None
    name = str(block.get("tool_name") or "").lower()
    if name not in ("write", "edit", "multiedit"):
        return None
    ti = block.get("tool_input") or {}
    if not isinstance(ti, dict):
        return None
    for holder in (ti, ti.get("input") if isinstance(ti.get("input"), dict) else None):
        if not isinstance(holder, dict):
            continue
        fp = holder.get("file_path") or holder.get("filePath")
        if fp:
            return str(fp)
    return None


def _transcript_write_targets(transcript) -> list[str]:
    """All Write/Edit/MultiEdit targets in a transcript (any location).

    F9（2026-08-21）：判定"agent 是否尝试写过东西"（无论写在 wd 内/外/错位）——
    read-only 空转（大量 tool_use progress 却零写盘 = 思考泥潭）与"真 silent"
    的区分靠它，不靠 turn_count 代理（§1.10：判据用业务事实"有无写盘"，不用
    机制特征"有无 tool_use"）。与 ``_transcript_orphan_paths`` 同源（同一
    ``_extract_write_target_shared``），单一证据源；best-effort（不可读/malformed
    跳过，绝不 raise——诊断证据非必需输入）。
    """
    if not transcript:
        return []
    from pathlib import Path
    tp = Path(transcript)
    if not tp.is_file():
        return []
    targets = []
    try:
        lines = tp.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            import json as _json
            event = _json.loads(line)
        except _json.JSONDecodeError:
            continue
        for block in event.get("blocks", []) or []:
            target = _extract_write_target_shared(block)
            if target:
                targets.append(target)
    return targets


def _batch_dir_anchor_shared(path) -> "Path | None":
    """Find the batch dir (``output/<batch_id>``) enclosing a workspace path.

    ``wd`` looks like ``output/<batch_id>/<run_dir>/artifacts/design/<name>``:
    the run_dir is the ancestor that directly contains an ``artifacts`` dir,
    and the batch dir is its parent. Returns the resolved batch dir, or None
    when ``path`` doesn't sit under an artifacts tree (e.g. a stray written to
    the repo root, or a UT temp dir) — conservative: caller refuses to move.
    """
    from pathlib import Path
    p = path if isinstance(path, Path) else Path(path)
    while p.parent != p:
        if (p / "artifacts").is_dir():
            return p.parent
        p = p.parent
    return None


def _harvest_relocation_evidence(transcript, filename: str, wd):
    """Scan a SDK/opencode transcript jsonl for a Write/Edit call whose target
    landed outside ``wd`` but tolerantly matches ``filename``. Returns the
    resolved Path of the most recent such write, or None when there's no
    transcript, no match, or only non-write tool calls.

    Thin wrapper over ``_harvest_relocation_evidence_detailed`` keeping the
    Path-or-None contract (existing callers + tests); callers that need the
    refusal reason use the detailed variant directly."""
    path, _reason = _harvest_relocation_evidence_detailed(transcript, filename, wd)
    return path


def _harvest_relocation_evidence_detailed(transcript, filename: str, wd):
    """Like ``_harvest_relocation_evidence`` but returns ``(path, reason)``.

    ``reason`` is None when a relocatable evidence path was found (same batch),
    or a short string explaining why the evidence was refused:
      - ``"cross_batch"`` — the written target is under a DIFFERENT batch dir
        (output/<batch_id>) than wd; moving it into wd would steal another
        run's file.

    Evidence constraints (all four, detection-side):
      1. tolerant filename match (same ext + normalized stem);
      2. transcript proves THIS agent wrote it (Write/Edit tool_use);
      3. target resolves outside ``wd``;
      4. same batch dir — refused when BOTH sides resolve a batch anchor and
         they differ; an unresolved anchor on either side PASSES (the first
         three constraints already bound the risk; the anchor is extra
         cross-run insurance, not a hard precondition).
    """
    if transcript is None or wd is None:
        return None, None
    from pathlib import Path
    import json as _json
    transcript = Path(transcript)
    if not transcript.is_file():
        return None, None
    ext = Path(filename).suffix
    target = _normalize_stem(Path(filename).stem)
    if not target:
        return None, None
    wd_resolved = Path(wd).resolve()
    found = None
    refused_reason = None
    try:
        lines = transcript.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None, None
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            event = _json.loads(line)
        except _json.JSONDecodeError:
            continue
        for block in event.get("blocks", []) or []:
            file_path = _extract_write_target_shared(block)
            if not file_path:
                continue
            candidate = Path(file_path)
            if candidate.suffix != ext:
                continue
            if _normalize_stem(candidate.stem) != target:
                continue
            try:
                if candidate.resolve().is_relative_to(wd_resolved):
                    continue  # inside wd — not a misplacement
            except (OSError, ValueError):
                pass
            # 第 4 重：跨 batch 拒。判据见 docstring；拒时记录 reason 但继续扫描
            # ——后续可能有同 batch 的合法匹配（agent 可能既写错跨 run、又写了正确
            # 的）。若最终无合法匹配，reason 被调用方用于 WARN（§1.3 可诊断）。
            wd_batch = _batch_dir_anchor_shared(wd_resolved)
            cand_batch = _batch_dir_anchor_shared(candidate.resolve())
            if wd_batch is not None and cand_batch is not None and wd_batch != cand_batch:
                refused_reason = "cross_batch"
                continue
            found = candidate  # last match wins (chronologically latest)
    return found, refused_reason
