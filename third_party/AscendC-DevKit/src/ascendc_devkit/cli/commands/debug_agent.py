"""L1 CLI — debug-agent: interactive agent debugging.

Launch an interactive claude session with the same system prompt, skills,
and workspace as a previously spawned agent in a pipeline run.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import click


@click.command("debug-agent")
@click.option("--run", "run_id", required=True, help="Run ID to debug")
@click.option("--agent-name", help="Agent name to debug (required unless --list)")
@click.option("--list", "list_agents", is_flag=True, help="List agents found in the run")
@click.option("--output-root", default="output", help="Output root directory")
def debug_agent_cmd(run_id, agent_name, list_agents, output_root):
    """Launch an interactive debugging session for a specific agent in a run.

    Reads events.jsonl from the run workspace to reconstruct the agent's
    original context (system prompt, skills, working directory) and launches
    a claude CLI subprocess for interactive debugging.
    """
    events_path = Path(output_root) / run_id / "events.jsonl"

    if not events_path.exists():
        click.echo(f"Error: events.jsonl not found at {events_path}")
        raise SystemExit(1)

    events = _load_events(events_path)

    if list_agents:
        _list_agents_from_events(events)
        return

    if not agent_name:
        click.echo("Error: --agent-name is required (use --list to see available agents)")
        raise SystemExit(64)

    ctx = _find_spawn_context(events, agent_name)
    if ctx is None:
        click.echo(f"No spawn context found for agent '{agent_name}' in run '{run_id}'")
        raise SystemExit(1)

    _launch_debug_session(ctx)


def _load_events(events_path: Path) -> list[dict]:
    """Load events from a JSONL file."""
    events = []
    with open(events_path, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return events


def _list_agents_from_events(events: list[dict]) -> None:
    """Print agents found in spawn_context events."""
    agents = set()
    for evt in events:
        if evt.get("type") == "spawn_context":
            agents.add(evt.get("agent", "unknown"))
        elif evt.get("type") == "action_start" and evt.get("action") == "spawn_agent":
            agents.add(evt.get("agent", "unknown"))

    if not agents:
        click.echo("No agent spawns found in this run.")
        return

    click.echo("Agents found in run:")
    for agent in sorted(agents):
        click.echo(f"  - {agent}")
    click.echo(f"\nRun: ascendc-devkit debug-agent --run <id> --agent-name <name>")


def _find_spawn_context(events: list[dict], agent_name: str) -> dict | None:
    """Extract agent spawn context from events."""
    for evt in events:
        if evt.get("type") == "spawn_context" and evt.get("agent") == agent_name:
            return {
                "agent_name": agent_name,
                "prompt": evt.get("prompt", ""),
                "context_keys": evt.get("context_keys", []),
                "skills": evt.get("skills", []),
                "working_dir": evt.get("working_dir", ""),
            }

    # Fallback: look for action_start + action_complete for spawn_agent
    for i, evt in enumerate(events):
        if evt.get("type") == "action_start" and evt.get("action") == "spawn_agent" and evt.get("agent") == agent_name:
            return {
                "agent_name": agent_name,
                "prompt": "",
                "context_keys": [],
                "skills": evt.get("skills", []),
                "working_dir": "",
            }

    return None


def _launch_debug_session(ctx: dict) -> None:
    """Launch claude CLI subprocess with the agent's context."""
    if not shutil.which("claude"):
        click.echo("Error: 'claude' CLI not found in PATH.")
        click.echo("Install Claude Code to use this feature: https://claude.ai/code")
        raise SystemExit(1)

    cmd = ["claude", "--print"]

    if ctx.get("working_dir"):
        working_dir = ctx["working_dir"]
    else:
        working_dir = str(Path.cwd())

    prompt = ctx.get("prompt", "")
    if prompt:
        cmd.extend(["--prompt", prompt])

    agent_name = ctx.get("agent_name", "")
    click.echo(f"Launching debug session for agent: {agent_name}")
    if ctx.get("skills"):
        click.echo(f"Skills: {', '.join(ctx['skills'])}")
    click.echo(f"Working directory: {working_dir}")

    try:
        proc = subprocess.run(
            cmd,
            cwd=working_dir,
            text=True,
        )
        raise SystemExit(proc.returncode)
    except KeyboardInterrupt:
        click.echo("\nDebug session cancelled.")
        raise SystemExit(130)
