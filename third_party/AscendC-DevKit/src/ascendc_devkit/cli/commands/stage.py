"""L1 Presentation — stage subcommand group."""

from __future__ import annotations

import click
from pathlib import Path

from ascendc_devkit.application.dispatcher import dispatch_single_stage


@click.group()
def stage():
    """Run and manage pipeline stages."""
    pass


@click.command("run")
@click.option("--name", "-n", required=True, help="Stage name to run (e.g., codegen, verify)")
@click.option("--state", "-s", "state_file", type=click.Path(exists=True),
              help="State JSON file")
@click.option("--from-run", "from_run_id", help="Load state from a previous run")
@click.option("--sources", "sources_dir", type=click.Path(exists=True),
              help="Directory containing source files")
@click.option("--requirement", "-r", "requirement_file", type=click.Path(exists=True),
              help="Requirement file (.json/.yaml/.yml). Parsed directly into "
                   "test_cases/constraints; use the full 'run' command for prose docs.")
@click.option("--npu-id", type=int, help="NPU card ID")
@click.option("--non-interactive", is_flag=True, help="Run in non-interactive mode")
@click.option("--max-iterations", type=int, default=None, help="Explicit iteration cap (hard limit). Unset uses the stage default / interactive safety net.")
@click.option("--enable-stubbed/--no-stubbed", default=False, help="Allow stub fallback when CANN/NPU unavailable")
@click.option("--output-root", default="output", help="Output root directory")
def stage_run(name: str, state_file: str | None, from_run_id: str | None,
              sources_dir: str | None, requirement_file: str | None,
              npu_id: int | None, non_interactive: bool, max_iterations: int | None,
              enable_stubbed: bool, output_root: str):
    """Run a single Stage independently."""
    exit_code = dispatch_single_stage(
        stage_name=name,
        state_file=Path(state_file) if state_file else None,
        from_run_id=from_run_id,
        sources_dir=Path(sources_dir) if sources_dir else None,
        requirement_file=Path(requirement_file) if requirement_file else None,
        npu_id=npu_id,
        non_interactive=non_interactive,
        max_iterations=max_iterations,
        enable_stubbed=enable_stubbed,
        output_root=output_root,
    )
    raise SystemExit(exit_code)


stage.add_command(stage_run)
