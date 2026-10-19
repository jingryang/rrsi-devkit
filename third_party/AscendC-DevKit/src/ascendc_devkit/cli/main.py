"""L1 Presentation — Main CLI entry point."""

from __future__ import annotations

import sys
import click

# Command imports pull in the orchestration config loader (runtime_config),
# which fails fast with ConfigError on an invalid orchestration-config.json.
# Catch it here at the entry point so a broken config produces a clear,
# actionable message + EX_CONFIG exit code rather than a raw import traceback.
try:
    from ascendc_devkit.cli.commands.stage import stage
    from ascendc_devkit.cli.commands.run import run_cmd
    from ascendc_devkit.cli.commands.verify_env import verify_env_cmd
    from ascendc_devkit.cli.commands.verify_repo import verify_repo_cmd
    from ascendc_devkit.cli.commands.show import show_cmd
    from ascendc_devkit.cli.commands.respond import respond_cmd
    from ascendc_devkit.cli.commands.skill import skill as skill_cmd
    from ascendc_devkit.cli.commands.debug_agent import debug_agent_cmd
    from ascendc_devkit.cli.commands.debug import redeploy_cmd, run_cases_cmd
    from ascendc_devkit.cli.commands.pack import pack_run_cmd, verify_run_cmd
except Exception as _import_err:  # noqa: BLE001
    from ascendc_devkit.domain.exceptions import ConfigError
    from ascendc_devkit.cli.exit_codes import EX_CONFIG
    if isinstance(_import_err, ConfigError):
        click.echo(f"Configuration error: {_import_err}", err=True)
        sys.exit(EX_CONFIG)
    raise


@click.group()
def main():
    """ascendc-devkit — AI-driven AscendC operator development platform."""
    pass


main.add_command(stage)
main.add_command(run_cmd)
main.add_command(verify_env_cmd)
main.add_command(verify_repo_cmd)
main.add_command(show_cmd)
main.add_command(respond_cmd)
main.add_command(skill_cmd)
main.add_command(debug_agent_cmd)
main.add_command(redeploy_cmd)
main.add_command(run_cases_cmd)
main.add_command(pack_run_cmd)
main.add_command(verify_run_cmd)


if __name__ == "__main__":
    sys.exit(main())
