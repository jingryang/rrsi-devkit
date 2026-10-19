"""L1 CLI — TUI: Rich-based pipeline progress visualization.

Supports --tui flag for interactive terminal UI with:
- 4-panel layout: stage progress, metrics, event stream, agent output
- Real-time stage status updates via progress callback
- Embedded resolve_ambiguity decision UI
"""

from __future__ import annotations

import logging
import time
import threading
from pathlib import Path

log = logging.getLogger(__name__)


class TUI:
    """Rich-based terminal UI for pipeline progress visualization."""

    _STAGE_ORDER = [
        "entry", "context", "requirement", "design", "codegen",
        "verify", "perf", "integrate", "finalize",
    ]

    def __init__(self, console=None):
        self._console = console
        self._stages: dict[str, str] = {
            s: "pending" for s in self._STAGE_ORDER
        }
        self._current_stage = ""
        self._events: list[str] = []
        self._agent_output: list[str] = []
        self._metrics: dict[str, str] = {}
        self._start_time = time.time()
        self._lock = threading.Lock()
        self._live = None

    def _get_console(self):
        if self._console:
            return self._console
        try:
            from rich.console import Console
            self._console = Console()
        except ImportError:
            self._console = None
        return self._console

    def start(self) -> None:
        try:
            from rich.live import Live
            from rich.table import Table
            from rich.panel import Panel
            table = Table(title="AscendC DevKit — Pipeline Progress")
            table.add_column("Stage", style="cyan")
            table.add_column("Status", style="magenta")
            for s in self._STAGE_ORDER:
                status = self._stages.get(s, "pending")
                icon = self._status_icon(status)
                table.add_row(s, f"{icon} {status}")
            panel = Panel(table, title="9-Stage Pipeline")
            console = self._get_console()
            if console:
                self._live = Live(panel, console=console, refresh_per_second=4, screen=False)
                self._live.start()
        except ImportError:
            log.warning("Rich library not installed — TUI disabled")
            self._live = None

    def stop(self) -> None:
        if self._live:
            self._live.stop()

    def update_stage(self, stage_name: str, status: str) -> None:
        with self._lock:
            self._stages[stage_name] = status
            self._current_stage = stage_name
        self._refresh()

    def add_event(self, event_type: str, detail: str = "") -> None:
        with self._lock:
            timestamp = time.strftime("%H:%M:%S")
            self._events.append(f"[{timestamp}] {event_type}: {detail}")
            if len(self._events) > 50:
                self._events = self._events[-50:]
        self._refresh()

    def ask_user(self, question: str, options: list[str]) -> int | None:
        """Display a question in TUI and return selected option index.

        Falls back to terminal input if Rich prompt is unavailable.
        """
        try:
            from rich.prompt import Prompt
            console = self._get_console()
            if console:
                if self._live:
                    self._live.stop()
                console.print(f"\n[bold yellow]Decision Required:[/bold yellow] {question}")
                for i, opt in enumerate(options):
                    console.print(f"  [{i+1}] {opt}")
                choice = Prompt.ask("Select option", default="1", choices=[str(i+1) for i in range(len(options))])
                if self._live:
                    try:
                        self._live.start()
                    except Exception:
                        pass
                return int(choice) - 1
        except ImportError:
            pass

        # Fallback to stdin
        print(f"\n{question}")
        for i, opt in enumerate(options):
            print(f"  [{i+1}] {opt}")
        try:
            choice = input("Select option (default 1): ").strip()
            if not choice:
                return 0
            return int(choice) - 1
        except (EOFError, ValueError):
            return 0

    def add_agent_output(self, agent_name: str, text: str) -> None:
        """Add a line from agent transcript output."""
        with self._lock:
            self._agent_output.append(f"[{agent_name}] {text}")
            if len(self._agent_output) > 80:
                self._agent_output = self._agent_output[-40:]

    def update_metrics(self, metrics: dict[str, str]) -> None:
        """Update metrics dashboard values."""
        with self._lock:
            self._metrics.update(metrics)

    def _refresh(self) -> None:
        if self._live is None:
            return
        try:
            from rich.table import Table
            from rich.panel import Panel
            from rich.layout import Layout

            elapsed = time.time() - self._start_time

            # Panel 1: Stage progress (top-left)
            table = Table(title="AscendC DevKit — Pipeline Progress", expand=True)
            table.add_column("Stage", style="cyan")
            table.add_column("Status", style="magenta")
            for s in self._STAGE_ORDER:
                status = self._stages.get(s, "pending")
                icon = self._status_icon(status)
                table.add_row(s, f"{icon} {status}")
            table.caption = f"Elapsed: {elapsed:.1f}s"
            progress_panel = Panel(table, title="9-Stage Pipeline", border_style="cyan")

            # Panel 2: Metrics (top-right)
            metrics_lines = [f"Elapsed: {elapsed:.1f}s"]
            if self._current_stage:
                metrics_lines.append(f"Stage: {self._current_stage}")
            for k, v in self._metrics.items():
                metrics_lines.append(f"{k}: {v}")
            metrics_text = "\n".join(metrics_lines) if metrics_lines else "Collecting..."
            metrics_panel = Panel(metrics_text, title="Metrics", border_style="green")

            # Panel 3: Event stream (bottom-left)
            event_text = "\n".join(self._events[-10:]) if self._events else "No events yet"
            event_panel = Panel(event_text, title="Event Stream", border_style="blue")

            # Panel 4: Agent output (bottom-right)
            agent_text = "\n".join(self._agent_output[-20:]) if self._agent_output else "Awaiting agents..."
            agent_panel = Panel(agent_text, title="Agent Output", border_style="magenta")

            # 2×2 grid layout
            top_row = Layout()
            top_row.split_row(
                Layout(progress_panel, name="progress", ratio=2),
                Layout(metrics_panel, name="metrics", ratio=1),
            )
            bottom_row = Layout()
            bottom_row.split_row(
                Layout(event_panel, name="events", ratio=2),
                Layout(agent_panel, name="agent_output", ratio=1),
            )
            layout = Layout()
            layout.split_column(top_row, bottom_row)

            self._live.update(layout)
        except Exception:
            pass

    @staticmethod
    def _status_icon(status: str) -> str:
        icons = {
            "pending": "[dim]○[/dim]",
            "running": "[yellow]◉[/yellow]",
            "done": "[green]●[/green]",
            "failed": "[red]✗[/red]",
            "skipped": "[dim]◌[/dim]",
        }
        return icons.get(status, "?")


def dispatch_with_tui(task_request: dict) -> int:
    """Run the full pipeline with TUI visualization.

    Wraps the standard dispatch() with a Rich-based TUI that shows
    stage progress and events in real time via a progress callback.
    """
    from ascendc_devkit.application.dispatcher import dispatch

    tui = TUI()
    tui.start()

    def on_progress(event_type: str, stage_name: str, metadata: dict | None) -> None:
        """Progress callback: maps dispatch events to TUI updates."""
        if event_type == "stage_start":
            tui.update_stage(stage_name, "running")
            tui.update_metrics({"current_stage": stage_name})
            if metadata and "total_stages" in metadata:
                tui.add_event("workflow", f"Starting stage '{stage_name}'")
        elif event_type == "stage_end":
            tui.update_stage(stage_name, "done")
            tui.add_event("stage_done", f"'{stage_name}' completed")
            if metadata:
                tui.update_metrics({
                    "last_stage": stage_name,
                    "last_iterations": str(metadata.get("iterations", "")),
                })
        elif event_type == "stage_error":
            tui.update_stage(stage_name, "failed")
            err = metadata.get("error", "") if metadata else ""
            tui.add_event("error", f"{stage_name}: {err}")
        elif event_type == "stage_skip":
            tui.update_stage(stage_name, "skipped")
            reason = metadata.get("reason", "") if metadata else ""
            tui.add_event("skip", f"{stage_name}: {reason}")
        elif event_type == "iteration_start":
            if metadata:
                tui.add_event("iteration",
                              f"{stage_name} iter {metadata.get('iteration', '?')}/{metadata.get('max', '?')}")
                tui.update_metrics({
                    "iteration": f"{metadata.get('iteration', '?')}/{metadata.get('max', '?')}",
                })
        elif event_type == "iteration_end":
            pass  # silently updated in metrics

    try:
        tui.add_event("workflow_start", f"mode={task_request.get('mode', 'new')}")
        exit_code = dispatch(task_request, progress_callback=on_progress)
        elapsed = time.time() - tui._start_time
        tui.add_event("workflow_complete", f"exit_code={exit_code} elapsed={elapsed:.1f}s")
        return exit_code
    except KeyboardInterrupt:
        tui.add_event("workflow_cancelled", "KeyboardInterrupt")
        return 130
    finally:
        tui.stop()
