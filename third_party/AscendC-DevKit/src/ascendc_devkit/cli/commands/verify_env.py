"""L1 CLI — verify-env command: validate development environment."""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import click


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str


def _check_python() -> CheckResult:
    version = sys.version.split()[0]
    return CheckResult(
        name="Python",
        passed=True,
        detail=f"Python {version}",
    )


def _check_cann() -> CheckResult:
    toolkit_home = os.environ.get("ASCEND_TOOLKIT_HOME", "")
    if not toolkit_home:
        return CheckResult(
            name="CANN Toolkit",
            passed=False,
            detail="ASCEND_TOOLKIT_HOME not set",
        )
    # Detect the real CANN compiler driver on PATH. These sentinels mirror
    # CANNToolchain._COMPILER_SENTINELS; verify-env is a self-contained
    # diagnostic that probes PATH directly (like its NPU/npu-smi check), so it
    # inlines the names rather than importing the L6 adapter. We do NOT key on
    # ops_compile: current CANN (e.g. 9.0.0) does not ship it, and the in-repo
    # build path (build.sh → ccec) never calls it.
    compiler = next(
        (shutil.which(n) for n in ("ccec", "bishengir-compile", "asc_opc")
         if shutil.which(n)),
        None,
    )
    if compiler:
        return CheckResult(
            name="CANN Toolkit",
            passed=True,
            detail=f"ASCEND_TOOLKIT_HOME={toolkit_home}, compiler={compiler}",
        )
    return CheckResult(
        name="CANN Toolkit",
        passed=False,
        detail=(f"ASCEND_TOOLKIT_HOME={toolkit_home}, CANN compiler not in PATH "
                "(source set_env.sh to initialise the environment)"),
    )


def _check_bisheng_link() -> CheckResult:
    """BISHENG 链接器 (ld.lld/cceld) 硬依赖 ``/lib64/libc.so.6`` 可达。

    某些机器（如缺 ``/lib64`` 的 Ubuntu 22.04 aarch64，libc 实际在
    ``/usr/lib64``）会让 "BISHENG -xasc 直编 device object 成 .so" 的场景在
    link 阶段挂：``ld.lld: cannot open /lib64/libc.so.6``。这只影响把 kernel
    object 塞进 ``_C`` 的构建（cannbench_eval 的 cann_bench_utils 性能预热工具），
    标准算子仓 deploy / precision_debug 因 kernel-host 分离不受影响 —— 所以运行期
    只表现为性能打分 skip + 误导性的 ``ImportError: ... circular import``。此处在
    加载期（§1.3）把真障碍显式报出，替代运行期的假象暴露（§1.11 忠实信号）。
    详见 docs/plan/self-evolution/83-cannbench-eval-env-gotchas.md。
    """
    libc = Path("/lib64/libc.so.6")
    if libc.exists():
        return CheckResult(
            name="BISHENG link",
            passed=True,
            detail=f"{libc} present (BISHENG lld libc dependency satisfied)",
        )
    # 找真实 libc 给出可执行修复命令
    real = next(
        (p for p in (Path("/usr/lib64/libc.so.6"),
                     Path("/usr/lib/aarch64-linux-gnu/libc.so.6"))
         if p.exists()),
        None,
    )
    fix = (f"sudo ln -sfn {real} /lib64/libc.so.6" if real
           else "install libc / restore /lib64")
    return CheckResult(
        name="BISHENG link",
        passed=False,
        detail=(f"{libc} missing — BISHENG lld will fail to link device .so "
                f"(cannbench_eval cann_bench_utils). Fix: {fix} "
                "(see docs/plan/self-evolution/83-cannbench-eval-env-gotchas.md)"),
    )


def _check_torch_npu() -> CheckResult:
    try:
        import torch  # noqa: F401
        imported_torch = True
    except ImportError:
        imported_torch = False

    try:
        import torch_npu  # noqa: F401
    except ImportError:
        if imported_torch:
            return CheckResult(
                name="torch_npu",
                passed=False,
                detail="torch installed but torch_npu not available",
            )
        return CheckResult(
            name="torch_npu",
            passed=False,
            detail="torch not installed",
        )

    try:
        count = torch_npu.npu.device_count()
        return CheckResult(
            name="torch_npu",
            passed=True,
            detail=f"torch_npu available, {count} NPU device(s)",
        )
    except Exception as e:
        return CheckResult(
            name="torch_npu",
            passed=True,
            detail=f"torch_npu available (device count check failed: {e})",
        )


def _check_npu_driver() -> CheckResult:
    devices = list(Path("/dev").glob("davinci*"))
    if devices:
        names = ", ".join(d.name for d in sorted(devices))
        return CheckResult(
            name="NPU Driver",
            passed=True,
            detail=f"{len(devices)} device(s): {names}",
        )
    return CheckResult(
        name="NPU Driver",
        passed=False,
        detail="no /dev/davinci* devices found",
    )


def _check_npu_device() -> CheckResult:
    npu_smi = shutil.which("npu-smi")
    if not npu_smi:
        return CheckResult(
            name="NPU Device",
            passed=False,
            detail="npu-smi not found in PATH",
        )
    try:
        import subprocess
        result = subprocess.run(
            [npu_smi, "info", "-l"],
            capture_output=True, text=True, timeout=15,
        )
        return CheckResult(
            name="NPU Device",
            passed=result.returncode == 0,
            detail=result.stdout.strip() if result.returncode == 0 else result.stderr.strip(),
        )
    except Exception as e:
        return CheckResult(
            name="NPU Device",
            passed=False,
            detail=f"npu-smi failed: {e}",
        )


def _check_llm() -> CheckResult:
    """Check LLM is reachable via claude_agent_sdk (the project's real runtime).

    Uses the same code path as the SDKBackend / actual pipeline: claude_agent_sdk
    reads credentials from ANTHROPIC_AUTH_TOKEN / .claude/settings.json and
    handles auth internally.  No bare anthropic SDK needed.
    """
    import asyncio
    import json

    # ---- Phase 1: load settings.json into os.environ ----
    settings = Path(__file__).resolve().parent.parent.parent.parent / ".claude" / "settings.json"
    if settings.exists():
        data = json.loads(settings.read_text())
        for k, v in data.get("env", {}).items():
            if k not in os.environ:
                os.environ[k] = str(v)

    # ---- Phase 2: credentials ----
    api_key = (
        os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    )
    if not api_key:
        return CheckResult(
            name="LLM",
            passed=False,
            detail="no credentials found (set ANTHROPIC_AUTH_TOKEN or configure .claude/settings.json)",
        )

    # ---- Phase 3: probe via claude_agent_sdk (same path as the pipeline) ----
    try:
        from claude_agent_sdk import ClaudeAgentOptions, query
        from claude_agent_sdk.types import AssistantMessage, TextBlock
    except ImportError:
        return CheckResult(
            name="LLM", passed=False,
            detail="claude_agent_sdk not installed",
        )

    async def _probe():
        async for event in query(
            prompt="hi",
            options=ClaudeAgentOptions(
                max_turns=1,
                permission_mode="acceptEdits",
            ),
        ):
            if isinstance(event, AssistantMessage):
                for block in event.content:
                    if isinstance(block, TextBlock) and block.text:
                        return block.text[:200]
        return ""

    try:
        text = asyncio.run(_probe())
    except Exception as e:
        return CheckResult(
            name="LLM", passed=False,
            detail=f"SDK query failed: {e}",
        )

    if not text:
        return CheckResult(
            name="LLM", passed=False,
            detail="SDK query returned empty response",
        )

    return CheckResult(
        name="LLM", passed=True,
        detail=f"claude_agent_sdk OK, model responded: {text[:80]}",
    )


@click.command("verify-env")
@click.option("--target", type=click.Choice(["local", "ssh", "docker"]), default="local",
              help="Target environment type")
def verify_env_cmd(target):
    """Verify the AscendC development environment."""
    if target != "local":
        click.echo(f"Target '{target}' not yet supported. Only 'local' is available.")
        return

    checks = [
        _check_python(),
        _check_cann(),
        _check_bisheng_link(),
        _check_llm(),
        _check_torch_npu(),
        _check_npu_driver(),
        _check_npu_device(),
    ]

    passed = sum(1 for c in checks if c.passed)
    failed = len(checks) - passed

    for c in checks:
        symbol = "PASS" if c.passed else "FAIL"
        click.echo(f"  [{symbol}] {c.name}: {c.detail}")

    click.echo()
    if failed == 0:
        click.echo("All checks passed.")
    else:
        click.echo(f"{passed}/{len(checks)} checks passed, {failed} failed.")
