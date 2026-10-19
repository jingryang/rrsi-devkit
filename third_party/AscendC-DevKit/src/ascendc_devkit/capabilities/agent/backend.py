"""L5 Capabilities — Agent backend protocol and result types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AgentResult:
    agent_name: str
    status: str         # "ok" | "partial" | "fatal"
    # Status reports the PROCESS fact only (clean finish vs crashed), derived
    # in the single _build_result factory. A clean finish with zero products
    # is "ok" + artifacts={} — whether "no output" is legitimate is a
    # per-consumer business question (output_contract / artifacts presence),
    # NOT a status category (F5).
    # "partial": the query raised mid-run (e.g. a server-side API error) but the
    # agent had already written some files before crashing. The files are kept
    # for inspection, but the run MUST be treated as a failure by callers — the
    # output is half-baked and indistinguishable from a clean completion if
    # reported as "ok".
    transcript: Path | None = None
    artifacts: dict[str, str] = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)
    # {"elapsed_ms": ..., "tokens_in": ..., "tokens_out": ...}
    # P50: None = logic/default failure; "infra" = the agent never ran its
    # logic because the environment is misconfigured or unavailable (gateway
    # has no channel for the model, quota window, auth). Infra is NOT retryable
    # within the run and NOT a logic failure — stages use this to avoid burning
    # iteration/breaker budgets on something that would never succeed this pass.
    error_type: str | None = None
    # step-67: turns where the backend saw a length-class stop signal (output
    # truncated by max_tokens / limit.output). Runner emits one output_truncated
    # event per entry so the exact agent+turn is locatable in events.jsonl.
    truncated_turns: list[int] = field(default_factory=list)
    # step-67: the backend's native session id (claude_agent_sdk / opencode),
    # captured at spawn so pack-run can fish the SDK's native session log.
    session_id: str = ""
    # D4 (hard-timeout): None = 正常结束；"hard_timeout"/"cancelled"/"keepalive" =
    # 被硬终止。backend 硬墙触发时填，取代 failure_reason 文本匹配，让 stage 确定性消费。
    aborted: str | None = None
    # 最后一轮 assistant 回复的纯文本（不含 thinking）。供 stage 层解析 agent
    # 自报的 RETURN/完成信号（如 codegen s4 的 `## RETURN: status=COMPLETED`）。
    # None = 无可用回复（早期 fatal / 未跑完的流）。
    final_response: str | None = None
    # 20260810 批根因修复 Part 1 — silent-cut 检测：第三方网关静默切流（无错误），
    # 流在完整 chunk 后截断，末条 assistant 消息只有 thinking、无 text 且无 tool_use
    # （自然结束必有 text 或 tool_use）。检测到即置 True；sidecar 保留（供下一迭代
    # 自动 resume，Part 2），结果照旧走失败路径（不新增 status 值，消费方零影响）。
    cut: bool = False


class AgentBackend(ABC):
    """Agent execution backend protocol."""

    @abstractmethod
    def spawn(self, agent_name: str, prompt: str, context: dict,
              skills: list[str] | None = None,
              model: str | None = None,
              working_dir: Path | str | None = None,
              repo_baseline: str | None = None,
              repo_root: Path | str | None = None,
              stage_name: str = "",
              branch_label: str = "",
              resume_session_id: str | None = None,
              # Part 3 (2026-08-20): resume 时作为首条消息的反馈/指令（替代默认「继续」）。
              # None = 沿用默认 _RESUME_PROMPT。
              resume_prompt: str | None = None,
              primary_skill: str | None = None,
              # D3 (hard-timeout): monotonic 时间墙；None=不设硬墙（原行为）。backend
              # 内部据此自实现硬墙——到点必返回 aborted，保证 spawn 不无限挂。runner 传
              # 剩余 deadline（min of workflow/stage deadline），见 runner._execute_spawn_agent。
              deadline_monotonic: float | None = None) -> AgentResult:
        # primary_skill: the flat skill whose methodology this spawn delivers
        # (D2). Decoupled from ``skills`` (the session allowlist): the backend
        # renders the delivery natively (claude = leading ``/<skill>`` slash;
        # opencode = system "first call skill({name})" + permission closure).
        # None = deliver nothing (standalone/skill-less spawns).
        ...
