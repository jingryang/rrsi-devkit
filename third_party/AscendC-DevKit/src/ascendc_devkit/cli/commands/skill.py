"""L1 CLI — skill command: skill discovery and management."""

from __future__ import annotations

import click

from ascendc_devkit.application.skill_service import list_available_skills, validate_skills
from ascendc_devkit.application.dispatcher import dispatch_single_skill


@click.group()
def skill():
    """Discover and manage skills."""
    pass


@click.command("list")
def skill_list():
    """List all available skills."""
    skills = list_available_skills()
    if not skills:
        click.echo("No skills found in project skill directory.")
        return

    click.echo(f"Available skills ({len(skills)}):")
    for s in skills:
        desc = f" — {s.description}" if s.description else ""
        click.echo(f"  {s.name}{desc}")


@click.command("validate")
@click.argument("skill_names", nargs=-1)
def skill_validate(skill_names):
    """Validate that named skills exist."""
    missing = validate_skills(list(skill_names))
    if missing:
        click.echo(f"MISSING skills: {', '.join(missing)}")
        raise SystemExit(1)
    click.echo("All skills available.")


@click.command("run")
@click.option("--name", required=True, help="Skill name to run")
@click.option("--prompt", default="", help="Task description for the skill")
@click.option("--output-root", default="output", help="Output root directory")
def skill_run(name, prompt, output_root):
    """Run a single skill independently."""
    exit_code = dispatch_single_skill(
        skill_name=name,
        prompt=prompt,
        output_root=output_root,
    )
    raise SystemExit(exit_code)


skill.add_command(skill_list)
skill.add_command(skill_validate)
skill.add_command(skill_run)
