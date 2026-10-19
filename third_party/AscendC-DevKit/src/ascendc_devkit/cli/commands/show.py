"""L1 CLI — show command: replay event stream."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import click



def _format_event(index: int, event: dict) -> None:
    """Format and print a single event with type-specific coloring."""
    etype = event.get("type", "unknown")
    ts = event.get("ts", "")[:19].replace("T", " ")

    prefix = click.style(f"[{index:4d}] {ts}", fg="white", dim=True)

    if etype == "stage_enter":
        stage = event.get("stage", "?")
        total = event.get("total", "?")
        idx = event.get("stage_index", "?")
        click.echo(f"{prefix} {click.style('STAGE', fg='cyan', bold=True)} "
                   f"{stage} ({idx}/{total})")

    elif etype == "stage_complete":
        stage = event.get("stage", "?")
        elapsed_s = event.get("elapsed_ms", 0) / 1000.0
        iterations = event.get("total_iterations", 0)
        status = event.get("status", "ok")
        color = "green" if status == "ok" else "yellow"
        click.echo(f"{prefix} {click.style('DONE', fg=color)} "
                   f"{stage} — {elapsed_s:.1f}s, {iterations} iterations"
                   + (f" [{status}]" if status != "ok" else ""))

    elif etype == "iteration_start":
        stage = event.get("stage", "?")
        it = event.get("iteration", 0)
        click.echo(f"{prefix} {click.style('ITER', fg='white', dim=True)} "
                   f"[{stage}#{it}]")

    elif etype == "iteration_complete":
        stage = event.get("stage", "?")
        it = event.get("iteration", 0)
        result = event.get("result", "ok")
        click.echo(f"{prefix} {click.style('ITER', fg='white', dim=True)} "
                   f"[{stage}#{it}] {result}")

    elif etype == "action_start":
        action = event.get("action", "?")
        extra = " ".join(f"{k}={v}" for k, v in event.items()
                         if k not in ("ts", "type", "action"))
        click.echo(f"{prefix} {click.style('  >', fg='white', dim=True)} "
                   f"{action}" + (f" {extra}" if extra else ""))

    elif etype == "action_complete":
        action = event.get("action", "?")
        result = event.get("result", "ok")
        click.echo(f"{prefix} {click.style('  <', fg='white', dim=True)} "
                   f"{action} [{result}]")

    elif etype == "decision_pending":
        question = event.get("question", "")
        click.echo(f"{prefix} {click.style('DECISION', fg='yellow', bold=True)} "
                   f"{question}")

    elif etype == "error":
        message = event.get("message", "unknown error")
        click.echo(f"{prefix} {click.style('ERROR', fg='red', bold=True)} "
                   f"{message}")

    elif etype == "workflow_complete":
        total_s = event.get("total_elapsed_ms", 0) / 1000.0
        click.echo(f"{prefix} {click.style('FINISHED', fg='green', bold=True)} "
                   f"total {total_s:.1f}s")

    else:
        extras = " ".join(f"{k}={v}" for k, v in event.items()
                          if k not in ("ts", "type"))
        click.echo(f"{prefix} {etype}" + (f" {extras}" if extras else ""))


def _tail_events(events_path: Path) -> None:
    """Tail events.jsonl in real-time, polling every 500ms."""
    if not events_path.exists():
        events_path.parent.mkdir(parents=True, exist_ok=True)
        events_path.touch()

    click.echo(f"Tailing {events_path} (Ctrl+C to stop)...")

    try:
        with open(events_path, "r") as f:
            f.seek(0, os.SEEK_END)
            line_count = 0
            while True:
                line = f.readline()
                if line:
                    line_count += 1
                    try:
                        event = json.loads(line.strip())
                        _format_event(line_count, event)
                    except json.JSONDecodeError:
                        click.echo(f"  [malformed: {line.strip()[:80]}...]")
                else:
                    time.sleep(0.5)
    except KeyboardInterrupt:
        click.echo("\nTail stopped.")


@click.command("show")
@click.option("--run", "run_id", required=True, help="Run ID to show")
@click.option("--tail", is_flag=True, help="Tail the event stream in real-time")
@click.option("--output-root", default="output", help="Output root directory")
def show_cmd(run_id, tail, output_root):
    """Show event stream for a past run."""
    events_path = Path(output_root) / run_id / "events.jsonl"

    if tail:
        _tail_events(events_path)
        return

    # KNOWN 清零 step-5：经 L2 application.read_run_events 读事件（L1 不直连 L7
    # EventLog，矩阵 1→{2,4}）；空 run / 无 events 由 L2 返回空 list 处理。
    from ascendc_devkit.application.report import read_run_events
    events = read_run_events(run_id, output_root)
    if not events:
        if not events_path.exists():
            click.echo(click.style(f"No events found for run '{run_id}'", fg="yellow"))
        else:
            click.echo(f"No events recorded for run '{run_id}'")
        return

    click.echo(f"Run: {run_id}  ({len(events)} events)")
    click.echo("-" * 60)
    for i, event in enumerate(events):
        _format_event(i + 1, event)
