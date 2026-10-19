#!/usr/bin/env python3
"""Unified entry point for forge evaluation — wraps resolver + evaluator."""

import argparse
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def detect_soc() -> str:
    try:
        result = subprocess.run(
            ["npu-smi", "info"],
            capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"npu-smi not available: {exc}") from exc
    for line in result.stdout.splitlines():
        match = re.search(r"\b(910B\w*)\b", line, re.IGNORECASE)
        if match:
            return "ascend" + match.group(1).lower()
    raise RuntimeError(f"Could not detect SoC from npu-smi output:\n{result.stdout}")


def detect_repo_type(repo_root: str) -> str:
    build_sh = Path(repo_root) / "build.sh"
    if not build_sh.is_file():
        raise FileNotFoundError(f"build.sh not found in {repo_root}")
    content = build_sh.read_text(encoding="utf-8", errors="replace")
    match = re.search(r'REPOSITORY_NAME\s*=\s*["\']?(\S+?)["\']?\s', content)
    if match:
        return "omni-ops"
    return "omni-ops"


def resolve_op_path(repo_root: str, op_name: str) -> str:
    bare_name = op_name
    if bare_name.endswith("_custom"):
        bare_name = bare_name[:-len("_custom")]
    root = Path(repo_root)
    for category_dir in sorted(root.iterdir()):
        if not category_dir.is_dir() or category_dir.name.startswith("."):
            continue
        candidate = category_dir / bare_name
        if candidate.is_dir():
            return f"{category_dir.name}/{bare_name}"
    searched = [d.name for d in root.iterdir() if d.is_dir() and not d.name.startswith(".")]
    raise FileNotFoundError(
        f"Operator directory for '{bare_name}' not found under {repo_root}. "
        f"Searched categories: {searched}"
    )


def derive_shared_dir(install_path: str) -> str:
    p = Path(install_path)
    for ancestor in [p.parent, p.parent.parent, p.parent.parent.parent]:
        candidate = ancestor / "shared"
        if candidate.is_dir():
            return str(candidate)
    return str(p.parent / "shared")


def build_evaluator_command(
    *,
    forge_config: str,
    forge_config_dir: str,
    forge_bin: str,
    op_name: str,
    repo_root: str,
    install_path: str,
    test_path: str,
    test_script: str,
    zsearch_side: str,
    zsearch_build_success: str,
    zsearch_repo_type: str,
    zsearch_soc: str,
    zsearch_task_type: str,
    zsearch_precision_passed: str,
    zsearch_correctness_message: str,
    baseline_time_us: float,
    output: str,
    mode: str,
) -> list[str]:
    evaluator_script = str(Path(__file__).parent / "forge_evaluator.py")
    return [
        sys.executable, evaluator_script,
        "--forge-config", forge_config,
        "--forge-config-dir", forge_config_dir,
        "--forge-bin", forge_bin,
        "--op-name", op_name,
        "--repo-root", repo_root,
        "--install-path", install_path,
        "--test-path", test_path,
        "--test-script", test_script,
        "--zsearch-side", zsearch_side,
        "--zsearch-build-success", zsearch_build_success,
        "--zsearch-repo-type", zsearch_repo_type,
        "--zsearch-soc", zsearch_soc,
        "--zsearch-task-type", zsearch_task_type,
        "--zsearch-precision-passed", zsearch_precision_passed,
        "--zsearch-correctness-message", zsearch_correctness_message,
        "--baseline-time-us", str(baseline_time_us),
        "--output", output,
        "--mode", mode,
    ]


def main(argv=None) -> int:
    if os.environ.get("ZSEARCH_FORGE_ENABLE") != "1":
        sys.stderr.write(
            "forge_run.py 入口已临时禁用（forge 框架尚在迭代）。\n"
            "如需强制启用：export ZSEARCH_FORGE_ENABLE=1\n"
        )
        return 2
    parser = argparse.ArgumentParser(description="Unified forge evaluation entry point")
    parser.add_argument("--op-name", required=True, help="Operator name (e.g. ada_layer_norm_custom)")
    parser.add_argument("--repo-root", required=True, help="Ops repo root directory")
    parser.add_argument("--install-path", required=True, help="Install artifact path")
    parser.add_argument("--mode", required=True, choices=["build", "accuracy", "perf", "both"])
    parser.add_argument("--output", required=True, help="Output path for evaluation_results.json")
    parser.add_argument("--baseline-time-us", type=float, default=0.0)
    parser.add_argument("--zsearch-side", default="evolved", choices=["baseline", "evolved"])
    parser.add_argument("--forge-config", default="omni_ops_performance_pytest")
    parser.add_argument("--forge-config-dir", default="/mnt/workspace/forge/configs")
    parser.add_argument("--forge-bin", default="forge")
    parser.add_argument("--soc", default=None)
    parser.add_argument("--shared-dir", default=None)
    parser.add_argument("--generated-test-script", default=None)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    soc = args.soc or detect_soc()
    repo_type = detect_repo_type(args.repo_root)
    op_relative_path = resolve_op_path(args.repo_root, args.op_name)
    shared_dir = args.shared_dir or derive_shared_dir(args.install_path)
    generated_test_script = args.generated_test_script or f"{args.op_name}_custom.py"

    scripts_dir = Path(__file__).parent
    sys.path.insert(0, str(scripts_dir))
    from forge_test_resolver import resolve_forge_test_script

    resolver_result = resolve_forge_test_script(
        repo_root=args.repo_root,
        op_relative_path=op_relative_path,
        custom_op_name=args.op_name,
        generated_test_path=shared_dir,
        generated_test_script=generated_test_script,
    )
    logger.info("Resolver result: %s", json.dumps(resolver_result))

    cmd = build_evaluator_command(
        forge_config=args.forge_config,
        forge_config_dir=args.forge_config_dir,
        forge_bin=args.forge_bin,
        op_name=args.op_name,
        repo_root=args.repo_root,
        install_path=args.install_path,
        test_path=resolver_result["test_path"],
        test_script=resolver_result["test_script"],
        zsearch_side=args.zsearch_side,
        zsearch_build_success="true",
        zsearch_repo_type=repo_type,
        zsearch_soc=soc,
        zsearch_task_type="performance",
        zsearch_precision_passed="true",
        zsearch_correctness_message="PASS",
        baseline_time_us=args.baseline_time_us,
        output=args.output,
        mode=args.mode,
    )

    logger.info("Running: %s", " ".join(cmd))
    result = subprocess.run(cmd)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
