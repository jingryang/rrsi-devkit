"""L1 CLI — pack-run / verify-run: thin click wrappers over
application.run_packaging (step-67). Logic stays in L2 so it may import L7
infra; this layer only parses args and prints (§1.1 layering)."""

from __future__ import annotations

import click


@click.command("pack-run")
@click.argument("run_id")
@click.option("--output-root", default="output",
              help="Output root containing the run directory.")
@click.option("--include-native/--no-native", default=True,
              help="Include SDK native sessions (claude ~/.claude / opencode ~/.local).")
def pack_run_cmd(run_id: str, output_root: str, include_native: bool):
    """Pack a run into a self-describing tar.gz with MANIFEST.json."""
    from ascendc_devkit.application.run_packaging import pack_run
    r = pack_run(run_id, output_root, include_native)
    click.echo(f"Packed: {r['out']}")
    click.echo(f"  backend={r['backend'] or 'unknown'}  "
               f"native sessions: {r['native_count']}")
    if r["include_native"] and not r["native_count"]:
        click.echo("  WARN: no native sessions found "
                   "(backend storage absent or session_ids empty — engineering "
                   "agents/*.jsonl copy still included)")


@click.command("verify-run")
@click.argument("run_dir", type=click.Path(exists=True))
def verify_run_cmd(run_dir: str):
    """Verify a run directory against its MANIFEST.json (integrity check)."""
    from ascendc_devkit.application.run_packaging import verify_run
    r = verify_run(run_dir)
    if r.get("error"):
        click.echo(f"FAIL: {r['error']}")
        raise SystemExit(1)
    click.echo(f"Run: {run_dir}")
    click.echo(f"  Provenance: {r.get('provenance_summary') or '(none)'}")
    for w in r.get("provenance_warnings", []):
        click.echo(f"  WARN: {w}")
    click.echo(f"  Files expected: {r['file_count']}")
    click.echo(f"  Missing: {len(r['missing'])}  "
               f"Mismatched: {len(r['mismatched'])}  Extra: {len(r['extra'])}")
    for m in r["missing"]:
        click.echo(f"  MISSING: {m}")
    for m in r["mismatched"]:
        click.echo(f"  MISMATCH (truncated/tampered): {m}")
    for m in r["extra"][:10]:
        click.echo(f"  extra: {m}")
    if r["ok"]:
        click.echo("OK: integrity verified.")
    else:
        raise SystemExit(1)
