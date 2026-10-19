"""L1 CLI — debug command family: ``redeploy`` + ``run-cases`` (P54 D11).

Thin click wrappers over the L2 ``DebugService`` (§1.1 layering: L1 → L2 → L3;
L1 never imports orchestration/adapter internals). The precision-debug agent
drives its closed loop through these commands (no orchestration imports):

    改码 → git commit → redeploy → run-cases → 读 dumptensor 日志 → 再改

Both locate the run via ``--workspace <run_dir>`` (absolute path to the run
directory, written into the debug agent's prompt); the snapshot/events stay
authoritative (read-only), and the per-deploy handoff between the two commands
is a file (``last_deploy.json``, §2.3). See ``application/debug_service.py``
for the actual deploy/case-run logic.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from ascendc_devkit.domain.exceptions import HarnessContractError
from ascendc_devkit.application.debug_service import DebugService


@click.command("redeploy")
@click.option("--workspace", "run_dir", required=True,
              type=click.Path(exists=True, file_okay=False, path_type=Path),
              help="Absolute path to the run directory (output/<run_id>/)")
def redeploy_cmd(run_dir: Path):
    """Rebuild + reinstall + smoke the current op's code (Deployer.deploy).

    Reads the run's state snapshot for op context (profile / chip /
    codegen_manifest / callable_target), runs the profile-driven deploy chain
    against the CURRENT repo code (the agent's latest commit), and writes the
    fresh DeployResult to ``<run>/artifacts/debug/<op>/last_deploy.json`` for
    ``run-cases`` to consume. Prints a deploy summary + smoke result.
    """
    svc = DebugService()
    try:
        op_name, deploy_result, err, last_deploy = svc.redeploy(run_dir)
    except FileNotFoundError as e:
        raise click.ClickException(str(e))

    click.echo(f"op: {op_name}")
    click.echo(f"smoke_passed: {deploy_result.smoke_passed}")
    click.echo(f"install_path: {deploy_result.install_path}")
    click.echo(f"python_path: {deploy_result.python_path}")
    click.echo(f"run_package: {deploy_result.run_package}")
    click.echo(f"wheel_package: {deploy_result.wheel_package}")
    click.echo(f"last_deploy: {last_deploy}")

    if err is not None:
        click.echo(f"error: {err.message}", err=True)
        if err.details:
            click.echo(f"detail: {err.details}", err=True)
        sys.exit(1)


@click.command("run-cases")
@click.option("--workspace", "run_dir", required=True,
              type=click.Path(exists=True, file_okay=False, path_type=Path),
              help="Absolute path to the run directory (output/<run_id>/)")
@click.option("--case", "case_names", multiple=True,
              help="Run only named cases (repeatable); default = all cases")
@click.option("--iter", "iter_n", type=int, default=0,
              help="Iteration number for the log dir (default 0)")
@click.option("--label", "label", default="",
              help="Phase label prepended to iter dir (e.g. 'run_tests', 'fix')")
@click.option("--case-id", "case_id", default=None,
              help="Single case by ID (maps to --case)")
def run_cases_cmd(run_dir: Path, case_names: tuple[str, ...], iter_n: int,
                  label: str = "", case_id: str | None = None):
    """Run precision cases against the redeployed op (NPURunner.execute).

    Reads ``last_deploy.json`` (from ``redeploy``) for the fresh per-op paths,
    runs the cases via the shared precision runner, and dumps the raw
    DumpTensor stdout/stderr to ``<run>/artifacts/debug/<op>/<label>_iter-N/run.log``
    (落盘 D7). Prints max_diff + per-case diff + the log path so the debug
    agent can read the root-cause signal off disk and iterate.
    """
    svc = DebugService()
    if case_id:
        case_names = (*case_names, case_id)
    try:
        op_name, result, run_log, result_path = svc.run_cases(
            run_dir, case_names, iter_n, label=label)
    except HarnessContractError as e:
        # M2 §2.4: preserve [PD-CONTRACT] marker for framework classification.
        raise click.ClickException(str(e))
    except (FileNotFoundError, ValueError) as e:
        # Honest errors (no last_deploy / no cases / no op_identity): §3.4/§3.7.
        raise click.ClickException(str(e))
    except Exception as e:  # noqa: BLE001 — surface NPU/env failures honestly
        raise click.ClickException(f"run-cases failed: {e}")

    click.echo(f"op: {op_name}")
    click.echo(f"passed: {result.get('passed', False)}")
    click.echo(f"max_diff: {result.get('max_diff', 0.0)}")
    per_case = result.get("per_shape", {}) or {}
    case_details = result.get("case_details", []) or []
    click.echo("per_case:")
    for name, case_info in per_case.items():
        if isinstance(case_info, dict):
            diff = case_info.get("diff", case_info)
            elapsed = case_info.get("elapsed_ms", -1.0)
            click.echo(f"  {name}: diff={diff}, elapsed_ms={elapsed}")
            for comp in case_info.get("output_comparisons", []):
                idx = comp.get("output_index", 0)
                k10 = comp.get("kernel_first10", [])
                g10 = comp.get("golden_first10", [])
                click.echo(f"    output[{idx}] ({comp.get('dtype','?')}) passed={comp.get('passed','?')} thr={comp.get('threshold','?')} diff={comp.get('diff', '?')}")
                click.echo(f"    output[{idx}] kernel_first10={k10}")
                click.echo(f"    output[{idx}] golden_first10={g10}")
                mloc = comp.get("max_diff_location")
                if mloc:
                    click.echo(
                        f"    output[{idx}] max_diff_location: flat_idx={mloc['flat_index']}, "
                        f"multi_idx={mloc['multi_index']}, "
                        f"kernel={mloc['kernel_value']:.10f}, "
                        f"golden={mloc['golden_value']:.10f}"
                    )
                    kctx = mloc.get("kernel_context", [])
                    gctx = mloc.get("golden_context", [])
                    cs = mloc.get("context_start", 0)
                    ce = mloc.get("context_end", 0)
                    if kctx:
                        click.echo(f"    output[{idx}] kernel_context[{cs}:{ce}]: {kctx}")
                    if gctx:
                        click.echo(f"    output[{idx}] golden_context[{cs}:{ce}]: {gctx}")
            if case_info.get("error"):
                click.echo(f"    error: {case_info['error']}")
        else:
            click.echo(f"  {name}: {case_info}")
    # P69: 权威 pass/fail = case_details[].outputs[].passed（runner 按 proto
    # precision_thresholds + cann-bench 语义逐输出判）。不再用标量 threshold 兜底。
    failed = [
        cd for cd in case_details
        if cd.get('error')
        or cd.get('passed') is False
        or any(not o.get('passed', False) for o in cd.get('outputs', []))
    ]
    if failed:
        click.echo(f"failed_cases ({len(failed)}/{len(case_details)}):")
        for cd in failed:
            bad = [o for o in cd.get('outputs', []) if not o.get('passed', False)]
            detail = ', '.join(
                f"output[{o.get('index')}] ({o.get('dtype','?')}) "
                f"diff={o.get('diff','?')} thr={o.get('threshold','?')}"
                for o in bad
            ) or ('diff=' + str(cd.get('diff', '?')))
            click.echo(f"  {cd['case']}: {detail} error={cd.get('error', '')}")
    click.echo(f"log: {run_log}")
    click.echo(f"result: {result_path}")
