"""L1 CLI — respond command: async decision response."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import click

from ascendc_devkit.cli.exit_codes import EX_USAGE


@click.command("respond")
@click.option("--run", "run_id", required=True, help="Run ID to respond to")
@click.option("--choice", type=int, default=None,
              help="Choice number (1-based). Omit when using --text.")
@click.option("--text", "text", default=None,
              help="Free-text answer outside the option set (overrides --choice).")
@click.option("--output-root", default="output", help="Output root directory")
def respond_cmd(run_id, choice, text, output_root):
    """Respond to a pending decision point for a non-interactive run.

    Provide either --choice (pick a listed option) or --text (a free-text answer
    that bypasses the option set, mirroring the interactive custom-input slot).
    """
    pending_path = Path(output_root) / run_id / "pending_decision.json"

    if not pending_path.exists():
        click.echo(click.style("Error: ", fg="red") +
                   f"No pending decision found for run '{run_id}'. "
                   f"Check that the run is paused at a decision point.")
        raise SystemExit(1)

    data = json.loads(pending_path.read_text())
    options = data.get("options", [])
    question = data.get("question", "")

    custom = text.strip() if isinstance(text, str) else ""
    if custom:
        response = {
            "text": custom,
            "question": question,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        response_path = pending_path.parent / "decision_response.json"
        response_path.write_text(json.dumps(response, ensure_ascii=False, indent=2))
        click.echo(f"Decision recorded for run '{run_id}':")
        click.echo(f"  Q: {question}")
        click.echo(f"  A: (custom) {custom}")
        click.echo(f"\nRun 'ascendc-devkit run --resume {run_id}' to continue.")
        return

    if choice is None:
        click.echo(click.style("Error: ", fg="red") +
                   "Provide either --choice <n> or --text <answer>.")
        raise SystemExit(EX_USAGE)

    if choice < 1 or choice > len(options):
        click.echo(click.style("Error: ", fg="red") +
                   f"Choice {choice} out of range [1-{len(options)}]")
        raise SystemExit(EX_USAGE)

    selected = options[choice - 1]
    response = {
        "choice": choice,
        "selected": selected,
        "question": question,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    response_path = pending_path.parent / "decision_response.json"
    response_path.write_text(json.dumps(response, ensure_ascii=False, indent=2))

    click.echo(f"Decision recorded for run '{run_id}':")
    click.echo(f"  Q: {question}")
    click.echo(f"  A: [{choice}] {selected}")
    click.echo(f"\nRun 'ascendc-devkit run --resume {run_id}' to continue.")
