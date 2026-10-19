#!/usr/bin/env python3
"""Initialize control.json + empty phase relay files for a precision_debug run.

First-round initializer for the run_tests phase (54-*.md §4.2). Backs up the
operator source (under ``{operator_dir}/.precision-fix/original_backup/``),
records the git baseline, and writes the orchestrator artifacts to
``--output-dir`` (``{workspace.artifacts}/debug/{op_name}/``):

  - ``control.json`` — the FW routing slice + cross-domain shared state. Holds
    every field the framework routes on (status / failed_case_queue /
    history / current_case_index / best_* / upstream_signal) AND init config
    (precision_debug loop knobs: max_iterations / max_attempts_per_case /
    time_budget_sec) read by all sub-agents. The FW reads ONLY this file for
    routing.
  - ``precision_run_tests.json`` — run_tests' single-owner deep-data artifact
    (last_result_json / last_run_log), seeded empty under ``phases/run_tests/``.
  - ``report.json`` — cross-phase narrative log, seeded empty.

Repo-self-contained (CLAUDE.md §1.7): all paths come from CLI args; no
``~/.claude`` / ``Path.home()``.

D3 (54-*.md §4.3) — these dead fields are NOT written: current_stage,
trim_retry, consecutive_failures, current_iteration, top-level bisect.
"""
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def init_control(operator_dir, output_dir, test_command, build_command,
                 compile_work_dir=None, op_name=None,
                 max_iterations=15,
                 max_attempts_per_case=8, time_budget_sec=12000):
    """Initialize precision_debug artifacts.

    Args:
        operator_dir: Operator source root (for original_backup + git baseline).
        output_dir: Artifact root (``{workspace.artifacts}/debug/{op_name}/``).
            control.json + report.json are written here; phase files go under
            ``phases/{phase_stem}/``.
        test_command, build_command, compile_work_dir, op_name:
            Passed through to control.json init config.
        max_iterations, max_attempts_per_case, time_budget_sec:
            precision_debug loop knobs written to control.json
            top level. Defaults mirror orchestration-config.json's
            precision_debug section (self-contained §2.1); the framework passes
            explicit values from runtime_config so a global edit propagates.
            Hand-editing this run's control.json overrides (the substage reads
            control.json, not the global config).
    """
    os.makedirs(output_dir, exist_ok=True)

    # —— original_backup ————————————————————————————————————————————————
    # Source backup stays under operator_dir (it's a source snapshot, not a
    # workspace artifact). Keep a .gitignore so old .precision-fix/ doesn't
    # leak into git.
    pf_dir = os.path.join(operator_dir, ".precision-fix")
    os.makedirs(pf_dir, exist_ok=True)
    with open(os.path.join(pf_dir, ".gitignore"), "w") as f:
        f.write("*\n")

    backup_dir = os.path.join(pf_dir, "original_backup")
    if os.path.exists(backup_dir):
        shutil.rmtree(backup_dir)
    shutil.copytree(operator_dir, backup_dir,
                    ignore=shutil.ignore_patterns(".git", ".precision-fix", ".claude"))

    # —— git baseline ———————————————————————————————————————————————————
    is_git = False
    initial_commit = None
    try:
        is_git = subprocess.check_output(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=operator_dir, text=True, stderr=subprocess.DEVNULL
        ).strip() == "true"
        initial_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=operator_dir, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        pass

    # —— control.json: FW routing slice + cross-domain shared state (§4.2) ——
    control = {
        # init config (read-only for all sub-agents)
        "operator": os.path.basename(operator_dir.rstrip("/")),
        "operator_dir": operator_dir,
        "output_dir": output_dir,
        "test_command": test_command,
        "build_command": build_command,
        "compile_work_dir": compile_work_dir or operator_dir,
        "op_name": op_name,
        "is_git_repo": is_git,
        "original_backup_dir": backup_dir,
        "initial_commit": initial_commit,

        # FW routing fields
        "status": "running",          # run_tests sets "passed" on all-pass
        # precision_debug loop knobs — per-run config (the substage reads
        # control.json, never the global config, so hand-editing here wins).
        # Defaults mirror orchestration-config.json's precision_debug section;
        # the framework passes explicit values from runtime_config on first run.
        "max_iterations": max_iterations,                # big-loop (run_tests↔diagnose) round ceiling
        "max_attempts_per_case": max_attempts_per_case,  # per-case stop-loss (all cases share one value)
        "time_budget_sec": time_budget_sec,              # total wall-clock; first run_test starts the timer
        "current_case_index": 0,      # FW advances this between dispatches
        # §P3 upstream: diagnose 入口判据上报上游缺陷 → halt（替代 scope_guard upstream）
        "upstream_signal": False,        # True = diagnose 判上游编译/注册/契约错 → halt
        "upstream_stage": None,          # codegen | test_design | golden | deploy | framework | env
        "upstream_reason": None,         # 一句话事实（diagnose 写，框架 halt 展示）
        "run_iter_counter": 0,         # auto-incrementing iter-N for run-cases
        "phase_counter": 0,            # monotonic phase-spawn index (archives)
        # §abort: consecutive agent-abort annealing counter (P9 — init writes 0;
        # FW _bump_consecutive_aborts/_reset_consecutive_aborts in substages).
        # >= _ABORT_EXHAUST_THRESHOLD → resolve_condition "abort_exhausted".
        "consecutive_aborts": 0,
        # §step-119: 不再初始化 best_* 字段——最优被测 identity / 计数从 history 测量史
        # 现算派生（framework-owned，agent 无可写对象）。initial_commit 保留为独立
        # 入口锚点（converge fallback / entry commit 校验用），不承载「最优」语义。
        # §time-budget: 首次 run_test 起算; 超 time_budget_sec (上方 knob) 退出
        "run_tests_start_ts": None,

        # cross-domain shared structures (single file → no三方写冲突, D2)
        "failed_case_queue": [],      # run_tests writes; fix updates case status
        "history": [],                # each phase appends its round entry

        "last_updated": _now_iso(),
    }
    ctrl_path = os.path.join(output_dir, "control.json")
    with open(ctrl_path, "w") as f:
        json.dump(control, f, indent=2, ensure_ascii=False)

    # —— precision_run_tests.json: run_tests' single-owner deep data (§4.1) ——
    phase_dir = os.path.join(output_dir, "phases", "run_tests")
    os.makedirs(phase_dir, exist_ok=True)
    phase_path = os.path.join(phase_dir, "precision_run_tests.json")
    with open(phase_path, "w") as f:
        json.dump({"last_result_json": None, "last_run_log": None},
                  f, indent=2, ensure_ascii=False)

    # —— report.json: cross-phase narrative log ——
    report_path = os.path.join(output_dir, "report.json")
    with open(report_path, "w") as f:
        json.dump({"operator": control["operator"],
                   "iterations": [],
                   "created_at": _now_iso()},
                  f, indent=2, ensure_ascii=False)

    print(f"control.json initialized at {ctrl_path}")
    print(f"  git_repo={is_git} initial_commit={initial_commit}")
    print(f"  backup={backup_dir}")
    print(f"  phases={phase_dir}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="Initialize precision_debug control.json + phase relay files"
    )
    parser.add_argument("--operator-dir", required=True,
                        help="Operator source root (for original_backup + git baseline)")
    parser.add_argument("--output-dir", required=True,
                        help="Artifact root ({workspace.artifacts}/debug/{op_name}/)")
    parser.add_argument("--test-command", required=True,
                        help="Full-suite run-cases shell command")
    parser.add_argument("--build-command", required=True,
                        help="redeploy shell command (compile precheck)")
    parser.add_argument("--compile-work-dir", default="",
                        help="Compile cwd (defaults to operator-dir)")
    parser.add_argument("--op-name", default=None)
    # precision_debug loop knobs — defaults mirror orchestration-config.json's
    # precision_debug section (self-contained §2.1). The framework passes
    # explicit values from runtime_config so a global edit propagates to here.
    parser.add_argument("--max-iterations", type=int, default=15,
                        help="big-loop (run_tests<->diagnose) round ceiling")
    parser.add_argument("--max-attempts-per-case", type=int, default=8,
                        help="per-case stop-loss (single value, all cases)")
    parser.add_argument("--time-budget-sec", type=int, required=True,
                        help="total wall-clock budget (seconds)")
    args = parser.parse_args()

    init_control(
        operator_dir=args.operator_dir,
        output_dir=args.output_dir,
        test_command=args.test_command,
        build_command=args.build_command,
        compile_work_dir=args.compile_work_dir or None,
        op_name=args.op_name,
        max_iterations=args.max_iterations,
        max_attempts_per_case=args.max_attempts_per_case,
        time_budget_sec=args.time_budget_sec,
    )
