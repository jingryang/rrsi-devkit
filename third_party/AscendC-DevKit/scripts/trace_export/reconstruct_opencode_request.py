#!/usr/bin/env python3
"""Reconstruct the complete LLM request JSON from an opencode serve SQLite DB.

opencode does NOT persist the assembled provider request — it stores the raw
sessions/messages/parts and re-assembles the request per turn. This script
"pieces together" (拼凑) the request that was actually sent to the model, using
three sources:

  1. the DB itself                 -> model / agent / messages / parts / user system
  2. the per-spawn served config   -> agent blocks (agent.md body as `prompt`) /
                                      permission / mcp
  3. opencode v1.18.16 templates   -> system assembly order + env block + skills /
                                      instructions / mcp instruction blocks

System-prompt assembly order (mirrors opencode `LLMRequestPrep.prepare`):
    agent.prompt   (from .claude/agents/*.md body, replaces opencode's base prompt)
  + env block      (model name, working dir, worktree root, git, platform, date)
  + instructions   (AGENTS.md / CLAUDE.md)
  + mcp block      (engine resolve_ambiguity)
  + skills block   (all skills discovered in the worktree)
  + user system    (the skill steer sent in the message body — stored in the DB)

Usage:
    python scripts/reconstruct_opencode_request.py <opencode.db> [options]

Options:
    --session <session_id | agent | title>   filter (substring match)
    --out-dir <dir>                          write one <session_id>.json per session
    --format <json|text>                     stdout format (default json)
    --config <opencode-config.json>          explicit served config (default: auto-discover)

Output per session (SAME canonical record in every export mode; --fields /
--format trajectory only select a subset of its keys):

    session         metadata (id / title / agent / model / directory / worktree)
    system          full assembled system prompt (single string)
    system_sources  the named pieces that make it up (agent_prompt / env /
                    instructions / mcp / skills / user_system / base_prompt_source)
    spawn_request   the DevKit POST /session/:id/message body (agent+parts+system)
    messages        the trajectory: ui[] (opencode intermediate) + provider[]
                    (OpenAI-compatible, what actually goes over the wire)
    tools           the tool definitions the model could call
    permission      the served config permission block

stdout json is ONE valid document: a single session → the record object, several
sessions → an array of records. --out-dir writes one file per session with the
same projected record.
"""

from __future__ import annotations

import argparse
import datetime
import html
import json
import sqlite3
import sys
from pathlib import Path


# —————————————————————————————————————————————————————————————————————————————
# opencode v1.18.16 built-in tool catalog (name -> (description, input_schema))
# Extracted from packages/opencode/src/tool/*.ts at tag v1.18.16. Only tools that
# are registered in serve mode for a non-opencode provider are listed here.
# —————————————————————————————————————————————————————————————————————————————

def _json_schema(props, required):
    schema = {"type": "object", "properties": props}
    if required:
        schema["required"] = required
    return schema


def _str(desc, enum=None):
    p = {"type": "string"}
    if desc:
        p["description"] = desc
    if enum:
        p["enum"] = enum
    return p


def _num(desc):
    return {"type": "number", "description": desc} if desc else {"type": "number"}


def _bool(desc):
    return {"type": "boolean", "description": desc}


OPCODE_TOOL_CATALOG = {
    "read": (
        "Read a file or directory from the local filesystem. If the path does not exist, an error is returned.",
        _json_schema({
            "filePath": _str("The absolute path to the file or directory to read"),
            "offset": _num("The line number to start reading from (1-indexed)"),
            "limit": _num("The maximum number of lines to read (defaults to 2000)"),
        }, ["filePath"]),
    ),
    "write": (
        "Writes a file to the local filesystem.",
        _json_schema({
            "content": _str("The content to write to the file"),
            "filePath": _str("The absolute path to the file to write (must be absolute, not relative)"),
        }, ["content", "filePath"]),
    ),
    "edit": (
        "Performs exact string replacements in files.",
        _json_schema({
            "filePath": _str("The absolute path to the file to modify"),
            "oldString": _str("The text to replace"),
            "newString": _str("The text to replace it with (must be different from oldString)"),
            "replaceAll": _bool("Replace all occurrences of oldString (default false)"),
        }, ["filePath", "oldString", "newString"]),
    ),
    "bash": (
        "Executes a given bash command in a persistent shell session with optional timeout.",
        _json_schema({
            "command": _str("The command to execute"),
            "timeout": _num("Optional timeout in milliseconds"),
            "workdir": _str("The working directory to run the command in. Defaults to the current directory. Use this instead of 'cd' commands."),
        }, ["command"]),
    ),
    "glob": (
        "Fast file pattern matching tool that works with any codebase size.",
        _json_schema({
            "pattern": _str("The glob pattern to match files against"),
            "path": _str("The directory to search in. If not specified, the current working directory will be used."),
        }, ["pattern"]),
    ),
    "grep": (
        "Fast content search tool that works with any codebase size.",
        _json_schema({
            "pattern": _str("The regex pattern to search for in file contents"),
            "path": _str("The directory to search in. Defaults to the current working directory."),
            "include": _str('File pattern to include in the search (e.g. "*.js", "*.{ts,tsx}")'),
        }, ["pattern"]),
    ),
    "task": (
        "Launch a new agent to handle complex, multistep tasks autonomously.",
        _json_schema({
            "description": _str("A short (3-5 words) description of the task"),
            "prompt": _str("The task for the agent to perform"),
            "subagent_type": _str("The type of specialized agent to use for this task"),
            "task_id": _str("Resume a prior subagent session by task_id"),
            "command": _str("The command that triggered this task"),
        }, ["description", "prompt", "subagent_type"]),
    ),
    "skill": (
        "Load a specialized skill when the task at hand matches one of the skills listed in the system prompt.",
        _json_schema({
            "name": _str("The name of the skill from available_skills"),
        }, ["name"]),
    ),
    "webfetch": (
        "Fetches content from a specified URL.",
        _json_schema({
            "url": _str("The URL to fetch content from"),
            "format": _str("Convert the returned content to this format", ["text", "markdown", "html"]),
            "timeout": _num("Optional timeout in seconds (max 120)"),
        }, ["url"]),
    ),
    "websearch": (
        "Search the web using the session's web search provider.",
        _json_schema({
            "query": _str("Websearch query"),
            "numResults": _num("Number of results to return"),
            "livecrawl": _str("Crawl mode", ["fallback", "preferred"]),
            "type": _str("Search type", ["auto", "fast", "deep"]),
            "contextMaxCharacters": _num("Context length for LLM integration"),
        }, ["query"]),
    ),
    "todowrite": (
        "Create and maintain a structured task list for the current coding session.",
        _json_schema({
            "todos": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": _str("Brief description of the task"),
                        "status": _str("Task status", ["pending", "in_progress", "completed", "cancelled"]),
                        "priority": _str("Priority level of the task", ["high", "medium", "low"]),
                    },
                    "required": ["content", "status"],
                },
                "description": "The updated todo list",
            },
        }, ["todos"]),
    ),
    "apply_patch": (
        "Use the apply_patch tool to edit files.",
        _json_schema({
            "patchText": _str("The full patch text that describes all changes to be made"),
        }, ["patchText"]),
    ),
}

# engine MCP resolve_ambiguity (single-source contract in capabilities/mcp_tools.py)
ENGINE_MCP_TOOLS = {
    "engine_resolve_ambiguity": (
        "需要人类决策时调用此工具。仅在阻塞性歧义（tiling 策略、精度/性能 tradeoff、"
        "代码结构分歧）时使用。变量命名等小事自行决定。",
        _json_schema({
            "question": _str("The ambiguity question to resolve"),
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Candidate resolutions, first option is the default",
            },
        }, ["question", "options"]),
    ),
}


# —————————————————————————————————————————————————————————————————————————————
# opencode's built-in base system prompts (SystemPrompt.provider, system.ts:27-42).
# Used ONLY when the resolved agent has no `prompt` (no .md / no agent block) —
# the agent's own prompt replaces these. Embedded verbatim from tag v1.18.16
# packages/opencode/src/session/prompt/{default,anthropic}.txt (the two most
# relevant providers; others fall back to the default variant + a marker).
# —————————————————————————————————————————————————————————————————————————————

_DEFAULT_BASE_PROMPT = """\
You are opencode, an interactive CLI tool that helps users with software engineering tasks. Use the instructions below and the tools available to you to assist the user.

IMPORTANT: You must NEVER generate or guess URLs for the user unless you are confident that the URLs are for helping the user with programming. You may use URLs provided by the user in their messages or local files.

If the user asks for help or wants to give feedback inform them of the following:
- /help: Get help with using opencode
- To give feedback, users should report the issue at https://github.com/anomalyco/opencode/issues

When the user directly asks about opencode (eg 'can opencode do...', 'does opencode have...') or asks in second person (eg 'are you able...', 'can you do...'), first use the WebFetch tool to gather information to answer the question from opencode docs at https://opencode.ai

# Tone and style
You should be concise, direct, and to the point. When you run a non-trivial bash command, you should explain what the command does and why you are running it, to make sure the user understands what you are doing (this is especially important when you are running a command that will make changes to the user's system).
Remember that your output will be displayed on a command line interface. Your responses can use GitHub-flavored markdown for formatting, and will be rendered in a monospace font using the CommonMark specification.
Output text to communicate with the user; all text you output outside of tool use is displayed to the user. Only use tools to complete tasks. Never use tools like Bash or code comments as means to communicate with the user during the session.
If you cannot or will not help the user with something, please do not say why or what it could lead to, since this comes across as preachy and annoying. Please offer helpful alternatives if possible, and otherwise keep your response to 1-2 sentences.
Only use emojis if the user explicitly requests it. Avoid using emojis in all communication unless asked.
IMPORTANT: You should minimize output tokens as much as possible while maintaining helpfulness, quality, and accuracy. Only address the specific query or task at hand, avoiding tangential information unless absolutely critical for completing the request. If you can answer in 1-3 sentences or a short paragraph, please do.
IMPORTANT: You should NOT answer with unnecessary preamble or postamble (such as explaining your code or summarizing your action), unless the user asks you to.
IMPORTANT: Keep your responses short, since they will be displayed on a command line interface. You MUST answer concisely with fewer than 4 lines (not including tool use or code generation), unless user asks for detail. Answer the user's question directly, without elaboration, explanation, or details. One word answers are best. Avoid introductions, conclusions, and explanations. You MUST avoid text before/after your response, such as "The answer is <answer>.", "Here is the content of the file..." or "Based on the information provided, the answer is..." or "Here is what I will do next...". Here are some examples to demonstrate appropriate verbosity:
<example>
user: what is 2+2?
assistant: 4
</example>

<example>
user: is 11 a prime number?
assistant: Yes
</example>

<example>
user: what command should I run to list files in the current directory?
assistant: ls
</example>

<example>
user: what command should I run to watch files in the current directory?
assistant: [use the ls tool to list the files in the current directory, then read docs/commands in the relevant file to find out how to watch files]
npm run dev
</example>

<example>
user: what files are in the directory src/?
assistant: [runs ls and sees foo.c, bar.c, baz.c]
user: which file contains the implementation of foo?
assistant: src/foo.c
</example>

<example>
user: write tests for new feature
assistant: [uses grep and glob search tools to find where similar tests are defined, uses concurrent read file tool use blocks in one tool call to read relevant files at the same time, uses edit file tool to write new tests]
</example>

# Proactiveness
You are allowed to be proactive, but only when the user asks you to do something. You should strive to strike a balance between:
1. Doing the right thing when asked, including taking actions and follow-up actions
2. Not surprising the user with actions you take without asking
For example, if the user asks you how to approach something, you should do your best to answer their question first, and not immediately jump into taking actions.
3. Do not add additional code explanation summary unless requested by the user. After working on a file, just stop, rather than providing an explanation of what you did.

# Following conventions
When making changes to files, first understand the file's code conventions. Mimic code style, use existing libraries and utilities, and follow existing patterns.
- NEVER assume that a given library is available, even if it is well known. Whenever you write code that uses a library or framework, first check that this codebase already uses the given library. For example, you might look at neighboring files, or check the package.json (or cargo.toml, and so on depending on the language).
- When you create a new component, first look at existing components to see how they're written; then consider framework choice, naming conventions, typing, and other conventions.
- When you edit a piece of code, first look at the code's surrounding context (especially its imports) to understand the code's choice of frameworks and libraries. Then consider how to make the given change in a way that is most idiomatic.
- Always follow security best practices. Never introduce code that exposes or logs secrets and keys. Never commit secrets or keys to the repository.

# Code style
- IMPORTANT: DO NOT ADD ***ANY*** COMMENTS unless asked

# Doing tasks
The user will primarily request you perform software engineering tasks. This includes solving bugs, adding new functionality, refactoring code, explaining code, and more. For these tasks the following steps are recommended:
- Use the available search tools to understand the codebase and the user's query. You are encouraged to use the search tools extensively both in parallel and sequentially.
- Implement the solution using all tools available to you
- Verify the solution if possible with tests. NEVER assume specific test framework or test script. Check the README or search codebase to determine the testing approach.
- VERY IMPORTANT: When you have completed a task, you MUST run the lint and typecheck commands (e.g. npm run lint, npm run typecheck, ruff, etc.) with Bash if they were provided to you to ensure your code is correct. If you are unable to find the correct command, ask the user for the command to run and if they supply it, proactively suggest writing it to AGENTS.md so that you will know to run it next time.
NEVER commit changes unless the user explicitly asks you to. It is VERY IMPORTANT to only commit when explicitly asked, otherwise the user will feel that you are being too proactive.

- Tool results and user messages may include <system-reminder> tags. <system-reminder> tags contain useful information and reminders. They are NOT part of the user's provided input or the tool result.

# Tool usage policy
- When doing file search, prefer to use the Task tool in order to reduce context usage.
- You have the capability to call multiple tools in a single response. When multiple independent pieces of information are requested, batch your tool calls together for optimal performance. When making multiple bash tool calls, you MUST send a single message with multiple tools calls to run the calls in parallel. For example, if you need to run "git status" and "git diff", send a single message with two tool calls to run the calls in parallel.

You MUST answer concisely with fewer than 4 lines of text (not including tool use or code generation), unless user asks for detail.

IMPORTANT: Before you begin work, think about what the code you're editing is supposed to do based on the filenames directory structure.

# Code References

When referencing specific functions or pieces of code include the pattern `file_path:line_number` to allow the user to easily navigate to the source code location.

<example>
user: Where are errors from the client handled?
assistant: Clients are marked as failed in the `connectToServer` function in src/services/process.ts:712.
</example>
"""


# Anthropic variant (SystemPrompt.provider picks this for model ids containing
# "claude"). Embedded verbatim from tag v1.18.16 prompt/anthropic.txt.
_ANTHROPIC_BASE_PROMPT = """\
You are OpenCode, the best coding agent on the planet.

You are an interactive CLI tool that helps users with software engineering tasks. Use the instructions below and the tools available to you to assist the user.

IMPORTANT: You must NEVER generate or guess URLs for the user unless you are confident that the URLs are for helping the user with programming. You may use URLs provided by the user in their messages or local files.

If the user asks for help or wants to give feedback inform them of the following:
- ctrl+p to list available actions
- To give feedback, users should report the issue at
  https://github.com/anomalyco/opencode

When the user directly asks about OpenCode (eg. "can OpenCode do...", "does OpenCode have..."), or asks in second person (eg. "are you able...", "can you do..."), or asks how to use a specific OpenCode feature (eg. implement a hook, write a slash command, or install an MCP server), use the WebFetch tool to gather information to answer the question from OpenCode docs. The list of available docs is available at https://opencode.ai/docs

# Tone and style
- Only use emojis if the user explicitly requests it. Avoid using emojis in all communication unless asked.
- Your output will be displayed on a command line interface. Your responses should be short and concise. You can use GitHub-flavored markdown for formatting, and will be rendered in a monospace font using the CommonMark specification.
- Output text to communicate with the user; all text you output outside of tool use is displayed to the user. Only use tools to complete tasks. Never use tools like Bash or code comments as means to communicate with the user during the session.
- NEVER create files unless they're absolutely necessary for achieving your goal. ALWAYS prefer editing an existing file to creating a new one. This includes markdown files.

# Professional objectivity
Prioritize technical accuracy and truthfulness over validating the user's beliefs. Focus on facts and problem-solving, providing direct, objective technical info without any unnecessary superlatives, praise, or emotional validation. It is best for the user if OpenCode honestly applies the same rigorous standards to all ideas and disagrees when necessary, even if it may not be what the user wants to hear. Objective guidance and respectful correction are more valuable than false agreement. Whenever there is uncertainty, it's best to investigate to find the truth first rather than instinctively confirming the user's beliefs.

# Task Management
You have access to the TodoWrite tools to help you manage and plan tasks. Use these tools VERY frequently to ensure that you are tracking your tasks and giving the user visibility into your progress.
These tools are also EXTREMELY helpful for planning tasks, and for breaking down larger complex tasks into smaller steps. If you do not use this tool when planning, you may forget to do important tasks - and that is unacceptable.

It is critical that you mark todos as completed as soon as you are done with a task. Do not batch up multiple tasks before marking them as completed.

Examples:

<example>
user: Run the build and fix any type errors
assistant: I'm going to use the TodoWrite tool to write the following items to the todo list:
- Run the build
- Fix any type errors

I'm now going to run the build using Bash.

Looks like I found 10 type errors. I'm going to use the TodoWrite tool to write 10 items to the todo list.

marking the first todo as in_progress

Let me start working on the first item...
</example>

# Doing tasks
The user will primarily request you perform software engineering tasks. This includes solving bugs, adding new functionality, refactoring code, explaining code, and more. For these tasks the following steps are recommended:
- Use the TodoWrite tool to plan the task if required

- Tool results and user messages may include <system-reminder> tags. <system-reminder> tags contain useful information and reminders. They are automatically added by the system, and bear no direct relation to the specific tool results or user messages in which they appear.

# Tool usage policy
- When doing file search, prefer to use the Task tool in order to reduce context usage.
- You should proactively use the Task tool with specialized agents when the task at hand matches the agent's description.

- When WebFetch returns a message about a redirect to a different host, you should immediately make a new WebFetch request with the redirect URL provided in the response.
- You can call multiple tools in a single response. If you intend to call multiple tools and there are no dependencies between them, make all independent tool calls in parallel. Maximize use of parallel tool calls where possible to increase efficiency. However, if some tool calls depend on previous calls to inform dependent values, do NOT call these tools in parallel and instead call them sequentially. For instance, if one operation must complete before another starts, run these operations sequentially instead. Never use placeholders or guess missing parameters in tool calls.
- If the user specifies that they want you to run tools "in parallel", you MUST send a single message with multiple tool use content blocks. For example, if you need to launch multiple agents in parallel, send a single message with multiple Task tool calls.
- Use specialized tools instead of bash commands when possible, as this provides a better user experience. For file operations, use dedicated tools: Read for reading files instead of cat/head/tail, Edit for editing instead of sed/awk, and Write for creating files instead of cat with heredoc or echo redirection. Reserve bash tools exclusively for actual system commands and terminal operations that require shell execution. NEVER use bash echo or other command-line tools to communicate thoughts, explanations, or instructions to the user. Output all communication directly in your response text instead.
- VERY IMPORTANT: When exploring the codebase to gather context or to answer a question that is not a needle query for a specific file/class/function, it is CRITICAL that you use the Task tool instead of running search commands directly.

IMPORTANT: Always use the TodoWrite tool to plan and track tasks throughout the conversation.

# Code References

When referencing specific functions or pieces of code include the pattern `file_path:line_number` to allow the user to easily navigate to the source code location.

<example>
user: Where are errors from the client handled?
assistant: Clients are marked as failed in the `connectToServer` function in src/services/process.ts:712.
</example>
"""


def select_base_prompt(model_id: str) -> tuple[str, str]:
    """Mirror opencode SystemPrompt.provider: map a model id to its built-in base
    prompt file. Returns (prompt_text, source_file_name)."""
    low = (model_id or "").lower()
    if "muse-spark" in low:
        return _DEFAULT_BASE_PROMPT, "meta.txt (unembedded; default variant used)"
    if ("gpt-4" in low or "o1" in low or "o3" in low):
        return _DEFAULT_BASE_PROMPT, "beast.txt (unembedded; default variant used)"
    if "gpt" in low:
        if "codex" in low:
            return _DEFAULT_BASE_PROMPT, "codex.txt (unembedded; default variant used)"
        return _DEFAULT_BASE_PROMPT, "gpt.txt (unembedded; default variant used)"
    if "gemini-" in low:
        return _DEFAULT_BASE_PROMPT, "gemini.txt (unembedded; default variant used)"
    if "claude" in low:
        return _ANTHROPIC_BASE_PROMPT, "anthropic.txt"
    if "trinity" in low:
        return _DEFAULT_BASE_PROMPT, "trinity.txt (unembedded; default variant used)"
    if "kimi" in low:
        return _DEFAULT_BASE_PROMPT, "kimi.txt (unembedded; default variant used)"
    return _DEFAULT_BASE_PROMPT, "default.txt"


def _strip_frontmatter(text: str) -> str:
    """Strip a leading YAML frontmatter block (mirrors _shared._strip_frontmatter)."""
    if not text.startswith("---"):
        return text
    lines = text.splitlines(keepends=True)
    for i in range(1, len(lines)):
        if lines[i].rstrip() == "---":
            return "".join(lines[i + 1:]).lstrip("\n")
    return text


def find_config(db_path: Path) -> Path | None:
    """Auto-discover the per-spawn served config next to the DB.

    DB:  <run>/.opencode_home/data/opencode/opencode.db
    cfg: <run>/.opencode_home/opencode-config.json
    """
    candidate = db_path.parent.parent.parent / "opencode-config.json"
    return candidate if candidate.is_file() else None


def find_worktree_root(directory: str) -> Path:
    """Walk up from the session directory to the git worktree root."""
    cur = Path(directory)
    while cur != cur.parent:
        if (cur / ".git").exists():
            return cur
        cur = cur.parent
    return cur


def agent_prompt_from_config(config: dict | None, agent: str) -> str | None:
    if not config:
        return None
    block = (config.get("agent") or {}).get(agent)
    if isinstance(block, dict):
        return block.get("prompt")
    return None


def agent_prompt_from_repo(worktree: Path, agent: str) -> str | None:
    md = worktree / ".claude" / "agents" / f"{agent}.md"
    if md.is_file():
        return _strip_frontmatter(md.read_text(encoding="utf-8"))
    return None


def build_env_block(model: dict, directory: str, worktree: Path, ts_ms: int,
                    platform: str = "linux") -> str:
    """Reconstruct opencode's SystemPrompt.environment block verbatim.

    ``Today's date`` is derived from the session's own start time (ts_ms),
    not the run's wall-clock date.
    """
    model_id = model.get("modelID") or model.get("id", "?")
    provider_id = model.get("providerID", "?")
    date = datetime.datetime.fromtimestamp(
        ts_ms / 1000, tz=datetime.timezone.utc).date().strftime("%a %b %d %Y")
    is_git = (worktree / ".git").exists()
    return "\n".join([
        f"You are powered by the model named {model_id}. "
        f"The exact model ID is {provider_id}/{model_id}",
        "Here is some useful information about the environment you are running in:",
        "<env>",
        f"  Working directory: {directory}",
        f"  Workspace root folder: {worktree}",
        f"  Is directory a git repo: {'yes' if is_git else 'no'}",
        f"  Platform: {platform}",
        f"  Today's date: {date}",
        "</env>",
    ])


def build_instructions(worktree: Path) -> list[str]:
    """Reconstruct Instruction.system() output: first project-level AGENTS.md/CLAUDE.md."""
    blocks: list[str] = []
    for name in ("AGENTS.md", "CLAUDE.md", "CONTEXT.md"):
        f = worktree / name
        if f.is_file():
            content = f.read_text(encoding="utf-8", errors="replace")
            if content.strip():
                blocks.append(f"Instructions from: {f}\n{content}")
            return blocks  # first project-level match wins
    return blocks


def build_mcp_block(mcp_cfg: dict | None, tools: dict[str, tuple[str, dict]]) -> str | None:
    """Reconstruct the <mcp_instructions> block for the engine server."""
    if not mcp_cfg or not tools:
        return None
    lines = ["<mcp_instructions>"]
    for name in sorted(mcp_cfg):
        lines.append(f'  <server name="{name}">')
        lines.append(
            "    Use the tools listed below to interact with the server. To use "
            "a tool, read its input schema and call it with the required arguments.")
        lines.append("    Tools:")
        for tool, (desc, _schema) in tools.items():
            lines.append(f"      - {tool}: {desc}")
        lines.append("  </server>")
    lines.append("</mcp_instructions>")
    return "\n".join(lines)


def _frontmatter_description(text: str) -> str:
    """Extract the frontmatter `description` (handles plain, quoted, and YAML
    folded/block scalars like `>` / `|`, which a line-by-line split misses)."""
    if not text.startswith("---"):
        return ""
    fence_end = text.find("\n---", 3)
    if fence_end == -1:
        return ""
    fm = text[4:fence_end]
    lines = fm.splitlines()
    for i, line in enumerate(lines):
        if not line.startswith("description:"):
            continue
        first = line.split(":", 1)[1].strip()
        if not first:
            continue
        if first in (">", "|", ">+", "|+", ">-", "|-"):
            key_indent = len(line) - len(line.lstrip(" "))
            body = []
            for ln in lines[i + 1:]:
                if not ln.strip():
                    body.append("")
                    continue
                if len(ln) - len(ln.lstrip(" ")) <= key_indent:
                    break
                body.append(ln.strip())
            join_with = "\n" if first.startswith("|") else " "
            return join_with.join(body).strip()
        # plain scalar (possibly quoted)
        if first[0] in ("'", '"') and len(first) >= 2 and first[-1] == first[0]:
            return first[1:-1].strip()
        return first
    return ""


def build_skills_block(worktree: Path) -> str | None:
    """Reconstruct Skill.fmt(list, verbose) for every skill under the worktree.

    opencode discovers .claude/skills via the <cwd>/.claude/skills anchor the
    backend plants; the flat tree is the repo's .claude/skills. permission.skill
    is allow-all, so every described skill is listed.
    """
    skills: list[tuple[str, str, str]] = []
    skills_dir = worktree / ".claude" / "skills"
    if skills_dir.is_dir():
        for child in sorted(skills_dir.iterdir()):
            md = child / "SKILL.md"
            if not md.is_file():
                continue
            text = md.read_text(encoding="utf-8", errors="replace")
            desc = _frontmatter_description(text)
            if desc:
                skills.append((child.name, desc, str(md)))
    if not skills:
        return None
    lines = [
        "Skills provide specialized instructions and workflows for specific tasks.",
        "Use the skill tool to load a skill when a task matches its description.",
        "<available_skills>",
    ]
    for name, desc, location in skills:
        lines.append("  <skill>")
        lines.append(f"    <name>{name}</name>")
        lines.append(f"    <description>{desc}</description>")
        lines.append(f"    <location>{html.escape(location)}</location>")
        lines.append("  </skill>")
    lines.append("</available_skills>")
    return "\n".join(lines)


def assemble_system(*, agent: str, model: dict, directory: str, worktree: Path,
                    ts_ms: int, config: dict | None,
                    user_system: str | None,
                    engine_tools: dict[str, tuple[str, dict]]) -> dict:
    """Assemble the full system prompt (opencode prepare order) + the pieces.

    The agent-vs-builtin decision mirrors opencode LLMRequestPrep.prepare:
        agent.prompt ? agent.prompt : SystemPrompt.provider(model)
    An agent block whose `prompt` resolves (the .md body) REPLACES opencode's
    built-in base prompt; without one the model-matched built-in base is used.
    """
    prompt = (agent_prompt_from_config(config, agent)
              or agent_prompt_from_repo(worktree, agent))
    base_source = None
    if not prompt:
        model_id = model.get("modelID") or model.get("id") or ""
        prompt, base_source = select_base_prompt(model_id)
    env = build_env_block(model, directory, worktree, ts_ms)
    instructions = build_instructions(worktree)
    mcp_cfg = (config or {}).get("mcp") or {}
    mcp = build_mcp_block(mcp_cfg, engine_tools)
    skills = build_skills_block(worktree)

    pieces: list[str] = []
    sources: dict = {}
    if prompt:
        pieces.append(prompt)
    sources["agent_prompt"] = prompt
    if base_source:
        sources["base_prompt_source"] = base_source
    pieces.append(env)
    sources["env"] = env
    if instructions:
        pieces.extend(instructions)
    sources["instructions"] = instructions
    if mcp:
        pieces.append(mcp)
    sources["mcp"] = mcp
    if skills:
        pieces.append(skills)
    sources["skills"] = skills
    if user_system:
        pieces.append(user_system)
    sources["user_system"] = user_system

    return {
        "system": ["\n".join(p for p in pieces if p)],
        "system_sources": sources,
    }


def load_parts_for_messages(con: sqlite3.Connection, session_id: str) -> list[dict]:
    """Load message + part rows in creation order for a session."""
    rows = con.execute(
        "SELECT m.id, m.time_created, m.data, p.id, p.time_created, p.data "
        "FROM message m LEFT JOIN part p ON p.message_id = m.id "
        "WHERE m.session_id = ? "
        "ORDER BY m.time_created, m.id, p.time_created, p.id",
        (session_id,),
    ).fetchall()
    messages: dict[str, dict] = {}
    order: list[str] = []
    for mid, mtime, mdata, pid, ptime, pdata in rows:
        if mid not in messages:
            messages[mid] = {
                "id": mid,
                "time_created": mtime,
                "info": json.loads(mdata),
                "parts": [],
            }
            order.append(mid)
        if pid:
            messages[mid]["parts"].append(json.loads(pdata))
    return [messages[mid] for mid in order]


def to_ui_messages(messages: list[dict]) -> list[dict]:
    """Reconstruct opencode's UIMessage intermediate format (message-v2.ts).

    Mirrors toModelMessagesEffect: user text/file parts; assistant text /
    reasoning / tool-<name> (output) parts. step-start/step-finish dropped.
    """
    ui: list[dict] = []
    for msg in messages:
        info = msg["info"]
        role = info.get("role")
        if role == "user":
            parts = []
            for p in msg["parts"]:
                t = p.get("type")
                if t == "text" and not p.get("ignored") and p.get("text"):
                    parts.append({"type": "text", "text": p["text"]})
                elif t == "file" and p.get("mime") not in ("text/plain", "application/x-directory"):
                    parts.append({"type": "file", "url": p.get("url"),
                                  "mediaType": p.get("mime"),
                                  "filename": p.get("filename")})
            if parts:
                ui.append({"id": msg["id"], "role": "user", "parts": parts})
        elif role == "assistant":
            if info.get("error"):
                continue
            has_signed = any(
                p.get("type") == "reasoning"
                and (p.get("metadata") or {}).get("anthropic", {}).get("signature")
                for p in msg["parts"])
            parts = []
            for p in msg["parts"]:
                t = p.get("type")
                if t == "text":
                    text = p.get("text") or ""
                    if text == "" and has_signed:
                        text = " "
                    parts.append({"type": "text", "text": text})
                elif t == "reasoning":
                    parts.append({"type": "reasoning", "text": p.get("text", ""),
                                  "providerMetadata": p.get("metadata")})
                elif t == "tool":
                    st = p.get("state", {})
                    status = st.get("status")
                    if status == "completed":
                        parts.append({
                            "type": f"tool-{p.get('tool')}",
                            "state": "output-available",
                            "toolCallId": p.get("callID"),
                            "input": st.get("input"),
                            "output": st.get("output"),
                        })
                    elif status == "error":
                        out = st.get("output") if (st.get("metadata") or {}).get("interrupted") else None
                        if out is not None:
                            parts.append({
                                "type": f"tool-{p.get('tool')}",
                                "state": "output-available",
                                "toolCallId": p.get("callID"),
                                "input": st.get("input"),
                                "output": out,
                            })
            if parts:
                ui.append({"id": msg["id"], "role": "assistant", "parts": parts})
    return ui


def to_provider_messages(ui_messages: list[dict]) -> list[dict]:
    """Convert UIMessage[] to OpenAI-compatible provider messages.

    Mirrors @ai-sdk convertToModelMessages for an OpenAI-compatible provider:
    assistant tool-<name> parts become separate role:tool messages paired with
    the assistant's tool_calls. Reasoning surfaces as ``reasoning_content``
    (deepseek convention).
    """
    out: list[dict] = []
    for msg in ui_messages:
        if msg["role"] == "user":
            content = []
            for p in msg["parts"]:
                if p["type"] == "text":
                    content.append({"type": "text", "text": p["text"]})
                elif p["type"] == "file":
                    content.append({"type": "file", "file": {"url": p.get("url"),
                                                             "media_type": p.get("mediaType")}})
            if content:
                out.append({"role": "user", "content": content})
        elif msg["role"] == "assistant":
            content = []
            reasoning: list[str] = []
            tool_calls = []
            tool_outputs = []
            for p in msg["parts"]:
                ptype = p["type"]
                if ptype == "text":
                    content.append({"type": "text", "text": p["text"]})
                elif ptype == "reasoning":
                    if p.get("text"):
                        reasoning.append(p["text"])
                elif ptype.startswith("tool-") and p["state"] == "output-available":
                    tool_calls.append({
                        "id": p["toolCallId"],
                        "type": "function",
                        "function": {
                            "name": ptype[len("tool-"):],
                            "arguments": json.dumps(p.get("input")),
                        },
                    })
                    tool_outputs.append({
                        "tool_call_id": p["toolCallId"],
                        "name": ptype[len("tool-"):],
                        "content": p.get("output"),
                    })
            assistant = {"role": "assistant"}
            if content:
                assistant["content"] = content
            if reasoning:
                assistant["reasoning_content"] = reasoning
            if tool_calls:
                assistant["tool_calls"] = tool_calls
            out.append(assistant)
            for to in tool_outputs:
                out.append({"role": "tool", "tool_call_id": to["tool_call_id"],
                            "name": to["name"], "content": to["content"]})
    return out


def build_tools(config: dict | None) -> list[dict]:
    """The tools the model could call: built-in catalog (per serve flags) + engine MCP."""
    tools: list[dict] = []
    names = ["read", "write", "edit", "bash", "glob", "grep", "task", "skill",
             "webfetch", "todowrite", "apply_patch"]
    for name in names:
        if name in OPCODE_TOOL_CATALOG:
            desc, schema = OPCODE_TOOL_CATALOG[name]
            tools.append({"name": name, "description": desc, "input_schema": schema})
    mcp_cfg = (config or {}).get("mcp") or {}
    if mcp_cfg:
        for name, (desc, schema) in ENGINE_MCP_TOOLS.items():
            tools.append({"name": name, "description": desc, "input_schema": schema})
    return tools


def reconstruct_session(con: sqlite3.Connection, session_row, config: dict | None,
                        engine_tools: dict) -> dict:
    sid = session_row["id"]
    title = session_row["title"]
    directory = session_row["directory"]
    agent = session_row["agent"]
    model_json = session_row["model"]
    t_created = session_row["time_created"]
    model = json.loads(model_json) if isinstance(model_json, str) else model_json
    worktree = find_worktree_root(directory)

    messages = load_parts_for_messages(con, sid)
    ui = to_ui_messages(messages)

    # The first user message carries the skill steer (message body `system`).
    user_system = None
    for msg in messages:
        if msg["info"].get("role") == "user" and msg["info"].get("system"):
            user_system = msg["info"]["system"]
            break

    sys_result = assemble_system(
        agent=agent, model=model, directory=directory, worktree=worktree,
        ts_ms=t_created, config=config, user_system=user_system,
        engine_tools=engine_tools,
    )

    # spawn_request: the DevKit POST /session/:id/message body.
    spawn_body = {"agent": agent, "model": model}
    first_text = None
    for msg in messages:
        if msg["info"].get("role") == "user":
            for p in msg["parts"]:
                if p.get("type") == "text" and p.get("text"):
                    first_text = p["text"]
                    break
            if first_text:
                break
    spawn_body["parts"] = [{"type": "text", "text": first_text or ""}]
    if user_system:
        spawn_body["system"] = user_system

    return {
        "session": {
            "id": sid,
            "title": title,
            "agent": agent,
            "model": model,
            "directory": directory,
            "worktree_root": str(worktree),
            "time_created": t_created,
        },
        # Full assembled system prompt (single string) + its named sources.
        "system": sys_result["system"][0],
        "system_sources": sys_result["system_sources"],
        # The DevKit POST /session/:id/message body.
        "spawn_request": spawn_body,
        # The conversation trajectory: ui (opencode intermediate) + provider
        # (OpenAI-compatible messages, what actually goes over the wire).
        "messages": {
            "ui": ui,
            "provider": to_provider_messages(ui),
        },
        "tools": build_tools(config),
        "permission": (config or {}).get("permission"),
    }


# Canonical record fields (all output modes emit this same schema; --fields /
# --format trajectory just select a subset of these keys).
RECORD_FIELDS = ("session", "system", "system_sources", "spawn_request",
                 "messages", "tools", "permission")
TRAJECTORY_FIELDS = ("session", "system", "messages")


def project_record(rec: dict, fields: tuple[str, ...] | None) -> dict:
    """Select a subset of canonical record fields. None → the whole record."""
    if not fields:
        return rec
    return {k: rec[k] for k in fields if k in rec}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("db", type=Path, help="path to opencode.db")
    ap.add_argument("--session", help="filter: session id / agent / title substring")
    ap.add_argument("--out-dir", type=Path, help="write one <session_id>.json per session")
    ap.add_argument("--format", choices=["json", "text", "trajectory"], default="json")
    ap.add_argument("--fields", default=None,
                    help=f"comma-separated subset of {','.join(RECORD_FIELDS)} "
                         "(default: all)")
    ap.add_argument("--config", type=Path, help="explicit served opencode-config.json")
    args = ap.parse_args()

    if not args.db.is_file():
        print(f"db not found: {args.db}", file=sys.stderr)
        return 2

    cfg_path = args.config or find_config(args.db)
    config = None
    if cfg_path and cfg_path.is_file():
        config = json.loads(cfg_path.read_text(encoding="utf-8"))
    elif cfg_path:
        print(f"config not found: {cfg_path}", file=sys.stderr)

    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    rows = con.execute("SELECT * FROM session ORDER BY time_created").fetchall()
    if args.session:
        needle = args.session.lower()
        rows = [r for r in rows if needle in r["id"].lower()
                or needle in (r["agent"] or "").lower()
                or needle in (r["title"] or "").lower()]
        if not rows:
            print(f"no session matches: {args.session}", file=sys.stderr)
            return 2

    # Field projection: explicit --fields wins; --format trajectory is a preset
    # (session + system + messages) of the same canonical schema; else all.
    if args.fields:
        fields = tuple(f.strip() for f in args.fields.split(",") if f.strip())
        unknown = [f for f in fields if f not in RECORD_FIELDS]
        if unknown:
            print(f"unknown field(s): {', '.join(unknown)} "
                  f"(valid: {', '.join(RECORD_FIELDS)})", file=sys.stderr)
            return 2
    elif args.format == "trajectory":
        fields = TRAJECTORY_FIELDS
    else:
        fields = None

    out_dir = args.out_dir
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    results = [project_record(reconstruct_session(con, row, config, ENGINE_MCP_TOOLS),
                              fields) for row in rows]
    results.sort(key=lambda r: r["session"].get("time_created", 0))

    if out_dir:
        width = len(str(len(results)))
        for idx, rec in enumerate(results, 1):
            (out_dir / f"{idx:0{width}d}_{rec['session']['id']}.json").write_text(
                json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")

    if out_dir:
        print(f"wrote {len(results)} request(s) to {out_dir} (time-ordered)")
        return 0

    if args.format == "text":
        for rec in results:
            s = rec["session"]
            print("=" * 100)
            print(f"SESSION {s['id']}  {s['title']}  agent={s['agent']}  model={s['model']}")
            print("-" * 100)
            print("SPAWN REQUEST (POST /session/:id/message):")
            print(json.dumps({k: v for k, v in rec["spawn_request"].items()
                              if k != "parts"}, ensure_ascii=False, indent=2))
            print("  parts[0].text = " + (rec["spawn_request"]["parts"][0]["text"][:200] + "..."))
            print("LLM REQUEST.system:")
            print(rec["system"])
            print("LLM REQUEST.tools:", [t["name"] for t in rec["tools"]])
            print("LLM REQUEST.messages:")
            for m in rec["messages"]["ui"]:
                ptypes = [p["type"] for p in m["parts"]]
                print(f"  [{m['role']:9s}] {m['id'][:14]} parts={ptypes}")
    else:
        # json / trajectory: ONE valid JSON document — single session → object,
        # multiple sessions → array of objects (same canonical schema).
        if len(results) == 1:
            print(json.dumps(results[0], ensure_ascii=False, indent=2))
        else:
            print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
