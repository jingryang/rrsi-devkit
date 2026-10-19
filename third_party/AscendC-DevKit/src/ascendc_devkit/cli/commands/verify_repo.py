"""L1 CLI — verify-repo command: validate repository profile."""

from __future__ import annotations

import yaml
from pathlib import Path

import click

from ascendc_devkit.domain.repository import RepositoryProfile


def _find_profile_file(profile_name: str) -> Path | None:
    """Search for profile YAML in project resources."""
    # Walk up from this file to find project root
    current = Path(__file__).resolve().parent
    for _ in range(6):
        if (current / "pyproject.toml").exists():
            p = current / "resources" / "repository-profiles" / f"{profile_name}.yaml"
            if p.exists():
                return p
            break
        current = current.parent
    return None


@click.command("verify-repo")
@click.option("--profile", help="Repository profile name (optional when --op-dir is given)")
@click.option("--repo-root", type=click.Path(exists=True), help="Repository root path")
@click.option("--op-dir", "op_dir", type=click.Path(), default=None,
              help="Absolute operator directory; resolves profile/repo_root/variant and validates them.")
def verify_repo_cmd(profile, repo_root, op_dir):
    """Verify a repository profile configuration.

    Two modes:
      - ``--op-dir``: resolve everything from one absolute path (§9), then
        confirm the build variant matches and the reference root exists.
      - ``--profile [--repo-root]``: load and print the profile, validating its
        reference roots against the given repo root.
    """
    if op_dir:
        _verify_op_dir(op_dir, profile, repo_root)
        return

    if not profile:
        click.echo("FAIL: provide --profile or --op-dir.")
        raise SystemExit(1)

    profile_path = _find_profile_file(profile)
    if profile_path is None:
        click.echo(f"FAIL: Profile '{profile}' not found.")
        raise SystemExit(1)

    try:
        data = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
        p = RepositoryProfile.from_dict(data)
    except (yaml.YAMLError, ValueError, KeyError) as e:
        click.echo(f"FAIL: Cannot parse profile '{profile}': {e}")
        raise SystemExit(1)

    click.echo(f"Profile: {p.name}")
    click.echo(f"  Display Name: {p.display_name}")
    click.echo(f"  Naming prefix: '{p.op_naming.prefix}'")
    click.echo(f"  Build variants: {[v.name for v in p.build_variants]}")
    for v in p.build_variants:
        click.echo(f"    - {v.name}: match_prefix='{v.match_prefix}', "
                   f"reference_root='{v.default_reference_root}', "
                   f"stages={[s.name for s in v.stages]}")

    issues = []
    if repo_root:
        repo_path = Path(repo_root).resolve()
        click.echo(f"  Repo Root: {repo_path}")
        for v in p.build_variants:
            if v.default_reference_root:
                ref_dir = repo_path / v.default_reference_root
                if not ref_dir.exists():
                    issues.append(
                        f"variant '{v.name}' reference root "
                        f"'{v.default_reference_root}' → '{ref_dir}' does not exist")

    if issues:
        click.echo()
        for issue in issues:
            click.echo(f"  WARN: {issue}")
        click.echo()
        click.echo("Profile loaded with warnings.")
    else:
        click.echo()
        click.echo("Profile loaded successfully.")


def _verify_op_dir(op_dir: str, profile: str | None, repo_root: str | None) -> None:
    """Resolve --op-dir and validate the resulting repo/variant/reference."""
    from ascendc_devkit.application.op_dir_resolver import (
        resolve_op_dir, OpDirResolveError,
    )
    from ascendc_devkit.application.profile_loader import load_profile

    try:
        res = resolve_op_dir(
            op_dir, profile_override=profile, repo_root_override=repo_root,
        )
    except OpDirResolveError as e:
        click.echo(f"FAIL: {e}")
        raise SystemExit(1)

    click.echo(f"op_dir resolution:")
    click.echo(f"  profile:      {res.profile_name}")
    click.echo(f"  repo_root:    {res.repo_root}")
    click.echo(f"  rel_op_dir:   {res.rel_op_dir}")
    click.echo(f"  full_op_name: {res.full_op_name}")
    click.echo(f"  op_name:      {res.op_name}")
    click.echo(f"  variant:      {res.variant_name}")
    click.echo(f"  confidence:   {res.confidence}")

    issues = []
    try:
        p = load_profile(res.profile_name)
        cmds = p.build_commands(res.rel_op_dir, res.full_op_name)
        click.echo(f"  build commands:")
        for c in cmds:
            click.echo(f"    {c}")
        roots = p.reference_roots(res.rel_op_dir)
        repo_path = Path(res.repo_root)
        for r in roots:
            rp = Path(r) if Path(r).is_absolute() else repo_path / r
            click.echo(f"  reference root: {rp}")
            if not rp.exists():
                issues.append(f"reference root '{rp}' does not exist")
    except FileNotFoundError as e:
        issues.append(str(e))

    if issues:
        click.echo()
        for issue in issues:
            click.echo(f"  WARN: {issue}")
        click.echo()
        click.echo("Resolved with warnings.")
    else:
        click.echo()
        click.echo("op_dir verified successfully.")
