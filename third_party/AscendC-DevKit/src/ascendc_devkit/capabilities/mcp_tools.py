"""L5 Capabilities — MCP tools for agent interaction.

Provides resolve_ambiguity @tool and build_engine_mcp_server().
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from ascendc_devkit.infra.terminal import Terminal

log = logging.getLogger(__name__)

_DECISION_PENDING_MARKER = "__DECISION_PENDING__"

# —— Single-source resolve_ambiguity tool contract (§2.5) ——
# Both delivery paths — claude in-process (build_engine_mcp_server) and the
# opencode stdio MCP (engine_mcp_stdio) — expose the SAME tool. Name /
# description / schema live here once so the two backends cannot drift.
RESOLVE_AMBIGUITY_TOOL_NAME = "resolve_ambiguity"
RESOLVE_AMBIGUITY_DESCRIPTION = (
    "需要人类决策时调用此工具。仅在阻塞性歧义（tiling 策略、精度/性能 tradeoff、"
    "代码结构分歧）时使用。变量命名等小事自行决定。"
)
# claude's @tool takes a Python-typed dict; the stdio path (JSON-RPC tools/list)
# needs a JSON-Schema object. Keep both here, derived from one intent.
RESOLVE_AMBIGUITY_PARAMS = {"question": str, "options": list[str]}
RESOLVE_AMBIGUITY_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "question": {"type": "string"},
        "options": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["question", "options"],
}


def _render_ask_user_ui(
    question: str, options: list[str], default_index: int = 0
) -> str:
    """Render a decision prompt and read the user's choice from stdin.

    Raises EOFError when stdin is not an interactive terminal (CI, backgrounded
    runs, piped/redirected stdin). The caller is responsible for deciding what a
    non-interactive environment should do (apply the configured on_decision
    strategy: default / abort / webhook) — this function must NOT silently pick
    the default, which would quietly take the decision away from the operator.
    """
    # Gate on stdin specifically: input() reads stdin, so stdin's TTY status is
    # what determines whether interaction is possible. (Terminal.is_tty() checks
    # stderr, which is used for rendering and may differ from stdin.)
    if not Terminal.stdin_is_tty():
        raise EOFError("stdin is not a TTY; cannot prompt for an interactive choice")

    use_unicode = Terminal.supports_unicode()
    width = min(Terminal.width(), 78)

    if use_unicode:
        top = "┌" + "─" * (width - 2) + "┐"
        bot = "└" + "─" * (width - 2) + "┘"
        sep = "│"
    else:
        top = bot = "+" + "-" * (width - 2) + "+"
        sep = "|"

    def _pad_line(text: str) -> str:
        return f"{sep} {text:<{width - 4}} {sep}"

    print(f"\n{top}")
    print(_pad_line(f"Agent: {question}"))
    print(_pad_line(""))

    for i, opt in enumerate(options):
        marker = " (default)" if i == default_index else ""
        line = f"  [{i + 1}] {opt}{marker}"
        print(_pad_line(line))

    # The custom-input slot is always the last entry. It lets the operator
    # override a malformed choice set (e.g. the agent offered a "default mode"
    # that should not exist) by typing a free-text resolution that is returned
    # to the agent verbatim, instead of being forced to pick a wrong option.
    custom_index = len(options)
    custom_pencil = "✏️ " if use_unicode else ""
    print(_pad_line(f"  [{custom_index + 1}] {custom_pencil}自定义输入（自由文本）"))

    print(bot)

    while True:
        # EOFError here (stdin closed mid-session) propagates to the caller so
        # the on_decision strategy can take over — we never spin on a dead stream.
        prompt_text = (
            f"  Choice [1-{custom_index + 1}] (Enter={default_index + 1}) > "
        )
        choice = input(prompt_text).strip()
        try:
            if choice == "":
                idx = default_index
            else:
                idx = int(choice) - 1
            if idx == custom_index:
                custom = input("  请输入自定义内容（Enter 提交，空输入用默认项）: ").strip()
                if custom:
                    mark = "✔" if use_unicode else "->"
                    print(f"  {mark} 已采用自定义输入: {custom}\n")
                    return custom
                idx = default_index
            if 0 <= idx < len(options):
                selected = options[idx]
                mark = "✔" if use_unicode else "->"
                print(f"  {mark} Selected: {selected}\n")
                return selected
        except ValueError:
            pass
        print(f"  Please enter 1-{custom_index + 1}")


def _send_webhook_notification(
    webhook_url: str, question: str, options: list[str], timeout_sec: int = 300
) -> str | None:
    """POST decision request to webhook URL, wait for callback response.

    Returns the selected option text, or None if timed out.
    """
    import urllib.request

    payload = json.dumps({
        "question": question,
        "options": options,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }).encode("utf-8")

    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=min(timeout_sec, 30)) as resp:
            if resp.status in (200, 201, 202):
                data = json.loads(resp.read().decode("utf-8"))
                choice = data.get("choice")
                if isinstance(choice, int) and 0 <= choice < len(options):
                    return options[choice]
                if isinstance(choice, str):
                    return choice
    except Exception as e:
        log.warning("Webhook notification failed: %s", e)

    return None


def create_resolve_ambiguity_handler(
    interactive: bool,
    on_decision: str = "default",
    workspace_dir: str | None = None,
    webhook_url: str | None = None,
) -> Callable:
    """Create the resolve_ambiguity handler.

    Args:
        interactive: If True, prompt user on terminal.
        on_decision: "default" to auto-select first option; "abort" to stop pipeline;
                     "notify-webhook" to POST to webhook and wait.
        workspace_dir: Workspace root for decision file I/O.
        webhook_url: URL for notify-webhook mode.
    """

    async def resolve_ambiguity(args: dict) -> dict:
        # The agent awaits this handler, so the call is synchronous from the
        # agent's perspective: its tool-use step blocks until we return. Whether
        # a human is involved depends on the mode:
        #   1. interactive + TTY  -> real-time: block on the terminal prompt,
        #      return the user's choice in the same agent session.
        #   2. notify-webhook     -> near real-time: block on a webhook round
        #      trip, fall back to the first option on timeout.
        #   3. abort (non-interactive) -> NOT real-time: persist
        #      pending_decision.json and return a marker; the caller raises
        #      DecisionPendingError to pause the pipeline. The user answers
        #      later via `respond`, and a subsequent resume reads it back
        #      (see the "Resume case" branch below).
        #   4. default (non-interactive) -> no human: auto-select first option.
        question = args.get("question", "")
        options = args.get("options", [])

        # —— Path 1: real-time terminal interaction ——
        if interactive:
            try:
                answer = _render_ask_user_ui(question, options)
                return {"content": [{"type": "text", "text": answer}]}
            except EOFError:
                # stdin is not interactive (CI / backgrounded / piped). Do not
                # spin or silently default inside the UI — fall through to the
                # configured non-interactive strategy below so the operator's
                # on_decision choice governs (default / abort / webhook).
                log.warning(
                    "interactive prompt requested but stdin is non-TTY; "
                    "falling back to on_decision=%s for '%s'",
                    on_decision, question)

        # —— Path 2: webhook notification (near real-time) ——
        if on_decision == "notify-webhook" and webhook_url:
            answer = _send_webhook_notification(webhook_url, question, options)
            if answer:
                return {"content": [{"type": "text", "text": answer}]}
            # Fallback to default if webhook times out
            answer = options[0] if options else ""
            log.warning("Webhook timed out, auto-selecting default for '%s'", question)
            return {"content": [{"type": "text", "text": answer}]}

        # Non-interactive modes
        ws = Path(workspace_dir) if workspace_dir else None

        # Resume case: a prior `respond` wrote the answer (completes Path 3).
        if ws:
            response_path = ws / "decision_response.json"
            if response_path.exists():
                data = json.loads(response_path.read_text())
                # A free-text override (respond --text) takes precedence over a
                # numeric choice, mirroring the interactive custom-input slot:
                # it lets the operator answer outside the agent's option set.
                custom = data.get("text")
                if isinstance(custom, str) and custom.strip():
                    log.info("resume custom decision applied for '%s': %s",
                             question, custom)
                    response_path.unlink()
                    return {"content": [{"type": "text", "text": custom}]}
                choice_idx = int(data.get("choice", 1)) - 1
                if 0 <= choice_idx < len(options):
                    selected = options[choice_idx]
                    log.info("resume decision applied for '%s': [%d] %s",
                             question, choice_idx + 1, selected)
                    response_path.unlink()
                    return {"content": [{"type": "text", "text": selected}]}

        # —— Path 3: abort — persist and pause for later resume ——
        if on_decision == "abort":
            if ws:
                pending = {
                    "question": question,
                    "options": options,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                ws.mkdir(parents=True, exist_ok=True)
                (ws / "pending_decision.json").write_text(
                    json.dumps(pending, ensure_ascii=False, indent=2))
                log.info("pending decision written for '%s' in %s",
                         question, ws)
            return {
                "content": [{"type": "text", "text": _DECISION_PENDING_MARKER}]
            }

        # —— Path 4: default — auto-select first option, no human ——
        answer = options[0] if options else ""
        log.info("auto-selected default for '%s': %s", question, answer)
        return {"content": [{"type": "text", "text": answer}]}

    return resolve_ambiguity


def build_engine_mcp_server(
    interactive: bool = True,
    on_decision: str = "default",
    workspace_dir: str | None = None,
    webhook_url: str | None = None,
):
    """Build the engine MCP server config with resolve_ambiguity tool.

    Args:
        interactive: Terminal prompt mode.
        on_decision: "default" | "abort" | "notify-webhook" non-interactive strategy.
        workspace_dir: Path for pending/response decision files.
        webhook_url: URL for notify-webhook mode.

    Returns McpSdkServerConfig if claude_agent_sdk is available.
    """
    from claude_agent_sdk import tool, create_sdk_mcp_server

    handler = create_resolve_ambiguity_handler(
        interactive, on_decision=on_decision, workspace_dir=workspace_dir,
        webhook_url=webhook_url,
    )

    @tool(RESOLVE_AMBIGUITY_TOOL_NAME,
          RESOLVE_AMBIGUITY_DESCRIPTION,
          RESOLVE_AMBIGUITY_PARAMS)
    async def resolve_ambiguity_tool(args):
        return await handler(args)

    return create_sdk_mcp_server("engine", tools=[resolve_ambiguity_tool])
