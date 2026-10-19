"""L1 CLI — run command: full workflow execution."""

from __future__ import annotations

import click
import dataclasses
from pathlib import Path

from ascendc_devkit.application.batch_runner import (
    load_manifest, resolve_card_pool, resume_batch, run_batch)
from ascendc_devkit.application.dispatcher import dispatch
from ascendc_devkit.application.op_dir_resolver import (
    resolve_op_dir, OpDirResolveError,
)
from ascendc_devkit.application.resume_resolver import resolve_resume_target
from ascendc_devkit.cli.exit_codes import EX_OK, EX_USAGE


@click.command("run")
# default=None 而非 "generate_ascendc":让 None 真正代表「用户未提供」,
# 这样 dispatcher 能区分「未传」(resume 应以 state.workflow_name 为唯一权威)
# 与「显式传了某个 workflow」。若给 default,click 会在用户未传时也填入该值,
# 导致 resume 不传 --workflow 时被误判为「显式传了 generate_ascendc」,
# 触发与 state 的不一致报错。new run 的默认值在 dispatcher 用 `or` 兜底。
@click.option("--workflow", default=None, help="Workflow name")
@click.option("--mode", default="new", type=click.Choice(["new", "incremental"]), help="Run mode")
@click.option("--op-dir", "op_dir", type=click.Path(), default=None,
              help="Absolute path to the operator directory (its last segment is the operator's full name). "
                   "One path resolves repo profile, repo root, build variant and operator name.")
@click.option("--reference", "references", multiple=True,
              help="Reference operator search root. May be a repo-relative dir or another repo's absolute path. "
                   "Repeatable; values are appended after the profile's default reference root.")
@click.option("--repo-root", "repo_root", type=click.Path(), default=None,
              help="Repo root fallback used when repo identification from --op-dir fails (renamed repo).")
@click.option("--target-repo", type=click.Path(exists=True), help="Target repository path (legacy; prefer --op-dir)")
@click.option("--repo-profile", default=None, help="Repository profile name (fallback when --op-dir identification fails/ambiguous)")
@click.option("--op-name", default="", help="Operator short name (default: derived from --op-dir's last segment minus the profile prefix)")
@click.option("--design-target-chip", "design_target_chip",
              type=click.Choice(["A2", "A3", "A5"]), default=None,
              help="Design/compile target chip generation: A2=Ascend910B, "
                   "A3=Ascend910C, A5=950. Authority: this flag > requirement doc "
                   "constraint > profile default_chip > probe-if-known (downstream "
                   "layers applied in context/requirement stage). Drives the build "
                   "(CANN soc_version is fixed at compile time).")
@click.option("--runtime-target-chip", "runtime_target_chip",
              type=click.Choice(["A2", "A3", "A5"]), default=None,
              help="On-box hardware generation, ONLY a fallback for when the NPU "
                   "probe times out on a flaky driver (hdcdrv connect_wait_reply "
                   "hang). The bounded probe is authoritative whenever it can "
                   "answer (even UNKNOWN); this flag never overrides a working "
                   "probe. Default: probe the hardware (bounded).")
@click.option("--requirement", "requirement_path", type=click.Path(exists=True), help="需求/问题描述文档 (.md/.yaml/.txt/.json)。仅承载需求，不是概设/详设；概设文档请用 --general-design。")
@click.option("--requirement-aux", "requirement_aux_paths", multiple=True, type=click.Path(exists=True), default=None,
              help="附加需求材料（可重复，如同 task 目录的 desc.md）。随主需求文档（--requirement）一起进"
                   "需求分析工作目录供 agent 阅读，作为需求理解的补充；不是确定性解析源"
                   "（schema/精度容差仍只读主需求，golden 仍为行为权威）。")
@click.option("--general-design", "design_doc_path", type=click.Path(exists=True), help="概要设计文档：已有概设时提供，general-design-generator 走 pass-through/增量补全而非从零生成。映射 design_doc_path。")
@click.option("--detailed-design", "detailed_design_path", type=click.Path(exists=True), help="详细设计文档：已有详设时提供，详设 group 短路（解析三件套→仅跑 validate→直接进 codegen），跳过 division/tiling/anchor/integrate/docgen。")
@click.option("--golden", "golden_path", type=click.Path(exists=True), help="golden 全链路参考实现/数据文件：design 阶段作设计依据，verify 阶段作精度基准（13 E4 / P12 正名）。与 --golden-entry / --golden-input-type 配套提供（13 E3）。")
@click.option("--golden-entry", "golden_entry", default=None,
              help="golden 入口函数名（如 exp）。与 --golden / --golden-input-type 配套（13 E3：golden 三参须配套）。")
@click.option("--golden-input-type", "golden_input_type",
              type=click.Choice(["torch", "numpy"]), default=None,
              help="golden 入口期望的张量类型：torch | numpy。CLI 层枚举校验（13 E3/E5：dispatch 期环境无关语法校验）。")
@click.option("--golden-precision", "golden_precision",
              type=click.Choice(["fp64_cpu", "native_cpu"]), default=None,
              help="golden 参考计算精度：fp64_cpu（默认，对齐 cann-bench 评测标准，升 fp64 计算参考）| native_cpu（保持原生 dtype）。")

@click.option("--cann-bench-cases", "cases_path", type=click.Path(exists=True), default=None,
              help="外部 cann-bench 用例 CSV 路径（参数名编码格式，loader 内不再分派；13 E2）。")
@click.option("--npu-id", type=int, default=None,
              help="NPU device ID. Unset = None → card resolved per subprocess "
                   "from the card pool (subprocess-level pinning, P69 stage 2); "
                   "a literal int hard-pins that card (--npu-id / task npu_id).")
@click.option("--non-interactive/--interactive", default=None,
              help="Run in non-interactive mode. 未传=None 让 resume 沿用 state; "
                   "--non-interactive=True / --interactive=False 显式覆盖。new run 的 "
                   "默认(交互模式)由 dispatcher 用 `or` 兜底。")
@click.option("--max-iterations", type=int, default=None, help="Explicit per-stage iteration cap (hard limit in both modes). Unset: interactive uses a safety net, non-interactive uses each stage's default.")
@click.option("--max-corrective", type=int, default=None, help="Max corrective loopbacks (codegen<->verify) in non-interactive mode. Unset: use orchestration-config.json (iterations.max_corrective).")
@click.option("--max-escalations", type=int, default=None, help="Max strategic escalations (design rewrites), both modes. Unset: use orchestration-config.json (iterations.max_escalations).")
@click.option("--workflow-timeout", type=int, default=0, help="Workflow timeout in seconds (0=disabled)")
@click.option("--stage-timeout", type=int, default=None, help="Per-stage timeout in seconds. Explicit value (incl. 0=disabled) overrides config; unset: per-stage budget from orchestration-config.json (timeouts.stages.<name>), else no timeout.")
@click.option("--on-decision", type=click.Choice(["default", "abort", "notify-webhook"]), default=None,
              help="Non-interactive decision strategy. 未传=None 让 resume 沿用 state; "
                   "new run 默认由 dispatcher 兜底 'default'。")
@click.option("--webhook-url", help="Webhook URL for async decision notifications (requires --on-decision notify-webhook)")
@click.option("--tui", is_flag=True, help="Enable Rich-based TUI visualization")
@click.option("--enable-stubbed/--no-stubbed", default=None,
              help="Allow stub fallback when CANN/NPU unavailable. 未传=None 让 resume "
                   "沿用 state; new run 默认由 dispatcher 兜底 False。")
@click.option("--resume", "resume_from", help="Resume a previous run by run ID")
@click.option("--resume-iteration", type=int, default=0, help="Resume from specific iteration within the first pending stage")
@click.option("--rerun-from", "rerun_from", default=None,
              help="Re-run a completed stage AND its downstream FRESH (requires --resume "
                   "<run_id>). Accepts a full node path or bare stage name (e.g. codegen). "
                   "Unlike --resume, the prior agent session is NOT continued — agents "
                   "spawn fresh. Use to re-validate a stage after iteratively optimizing it.")
@click.option("--output-root", default="output", help="Output root directory")
@click.option("--batch", "batch", type=click.Path(exists=True, dir_okay=False),
              default=None,
              help="Batch manifest YAML path: run multiple ops concurrently over a card pool "
                   "(stage 1 = run-level exclusive card occupancy). When set, single-op options "
                   "(--op-dir/--requirement/...) are ignored — each task in the manifest carries "
                   "its own fields.")
@click.option("--cards", type=str, default=None,
              help="NPU card pool as comma-separated ints (e.g. '0,1,2'). Fallback when the "
                   "manifest has no 'cards'; ignored when manifest.cards is present (manifest is "
                   "authoritative).")
@click.option("--design-concurrency", "design_concurrency", type=int, default=None,
              help="Run-level concurrency cap (overrides manifest design_concurrency). A LOCAL-"
                   "resource valve (CPU/memory/handles on large batches); orthogonal to the card "
                   "pool (NPU critical resource).")
def run_cmd(workflow, mode, op_dir, references, repo_root, target_repo, repo_profile,
            op_name, design_target_chip, runtime_target_chip, requirement_path,
            requirement_aux_paths, design_doc_path, detailed_design_path, golden_path,
            golden_entry, golden_input_type, golden_precision, cases_path,
            npu_id, non_interactive, max_iterations, max_corrective, max_escalations,
            on_decision, webhook_url, tui, enable_stubbed, resume_from,
            resume_iteration, rerun_from, output_root, workflow_timeout, stage_timeout,
            batch, cards, design_concurrency):
    """Run a complete AscendC operator development workflow."""
    if batch and resume_from:
        click.echo(
            "ERR: --batch 与 --resume 互斥（--batch 首跑批；--resume <id> 续跑，"
            "id 可是 run_id 或 batch_id）", err=True)
        raise SystemExit(EX_USAGE)
    if batch:
        manifest = load_manifest(batch)
        if design_concurrency is not None:
            manifest = dataclasses.replace(
                manifest, design_concurrency=design_concurrency)
        cli_cards = None
        if cards:
            cli_cards = [int(c.strip()) for c in cards.split(",") if c.strip()]
        pool = resolve_card_pool(manifest, cli_cards=cli_cards)
        result = run_batch(manifest, pool)
        # batch_id is the resume handle: run --resume <batch_id> 续全批，
        # run --resume <execution_id> 续批内单算子（L4 §54 分层 ID）。
        click.echo(f"batch_id: {result.batch_id}", err=True)
        click.echo(result.summary(), err=True)
        raise SystemExit(
            EX_OK if all(r.exit_code == EX_OK for r in result.results) else 1)

    # --resume <id>: unify single-run / batch resume by id LOCATION (L4 §54).
    # flat output/<run_id>/ or nested output/<batch_id>/<run_id>/ → single;
    # output/<batch_id>/ containing exec dirs → batch (resume all executions).
    effective_output_root = output_root
    if resume_from:
        target = resolve_resume_target(resume_from, output_root)
        if target.kind == "batch":
            cli_cards = None
            if cards:
                cli_cards = [int(c.strip()) for c in cards.split(",") if c.strip()]
            result = resume_batch(
                target.id, output_root=target.output_root, cli_cards=cli_cards)
            click.echo(f"resume batch {target.id}", err=True)
            click.echo(result.summary(), err=True)
            raise SystemExit(
                EX_OK if all(r.exit_code == EX_OK for r in result.results) else 1)
        # single run (flat or nested execution): scope output_root so dispatch
        # loads it from the right place (nested → output/<batch_id>).
        effective_output_root = target.output_root

    task_request = {
        "mode": mode,
        "workflow": workflow,
        "target_repo": target_repo,
        "repo_profile": repo_profile,
        "op_name": op_name,
        "design_target_chip": design_target_chip,
        "runtime_target_chip": runtime_target_chip,
        "references": list(references),
        "requirement_path": requirement_path,
        "requirement_aux_paths": list(requirement_aux_paths or []),
        "design_doc_path": design_doc_path,
        "detailed_design_path": detailed_design_path,
        "golden_path": golden_path,
        "golden_entry": golden_entry,
        "golden_input_type": golden_input_type,
        "golden_precision": golden_precision,
        "cases_path": cases_path,
        "npu_id": npu_id,
        "non_interactive": non_interactive,
        "max_iterations": max_iterations,
        "on_decision": on_decision,
        "webhook_url": webhook_url,
        "enable_stubbed": enable_stubbed,
        "resume_from": resume_from,
        "resume_iteration": resume_iteration,
        "rerun_from": rerun_from,
        "output_root": effective_output_root,
        "workflow_timeout_sec": workflow_timeout,
        "stage_timeout_sec": stage_timeout,
        "max_corrective": max_corrective,
        "max_escalations": max_escalations,
    }

    # Resolve --op-dir at the L1→L2 boundary (§11.4): one absolute path yields
    # profile / repo_root / rel_op_dir / full_op_name / op_name. Downstream
    # stages read the resolved State fields only and never re-import the
    # resolver. Resume runs already carry these fields, so skip resolution.
    if op_dir and not resume_from:
        try:
            res = resolve_op_dir(
                op_dir,
                profile_override=repo_profile,
                repo_root_override=repo_root,
                op_name_override=op_name or None,
            )
        except OpDirResolveError as e:
            click.echo(f"FAIL: {e}", err=True)
            raise SystemExit(EX_USAGE)
        if res.confidence == "ambiguous" and not (repo_profile and repo_root):
            click.echo(
                f"WARN: repository name appears multiple times in --op-dir; "
                f"using '{res.repo_root}' as the repo root. "
                f"Pass --repo-root/--repo-profile to confirm the boundary if this is wrong.",
                err=True,
            )
        task_request.update({
            "op_dir": op_dir,
            "repo_profile": res.profile_name,
            "repo_root": res.repo_root,
            "rel_op_dir": res.rel_op_dir,
            "full_op_name": res.full_op_name,
            "op_name": res.op_name,
            "variant_name": res.variant_name,
            # target_repo defaults to the resolved repo root so existing
            # repo-aware stages keep working without a separate --target-repo.
            "target_repo": target_repo or res.repo_root,
        })

    if tui:
        from ascendc_devkit.cli.tui import dispatch_with_tui
        exit_code = dispatch_with_tui(task_request)
    else:
        exit_code = dispatch(task_request)

    raise SystemExit(exit_code)
