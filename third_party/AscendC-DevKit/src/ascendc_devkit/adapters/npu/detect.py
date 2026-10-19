"""L4 Adapter (NPU) — hardware chip detection.

Queries torch_npu for the actual hardware device name and maps it to a
canonical chip generation (``A2``/``A3``/``A5``). Returns ``chip.UNKNOWN`` when
the hardware cannot be identified (torch_npu unavailable, 0 devices, unknown
device name) — never a silent A2 guess.

Chip identity / compatibility / soc_version translation live in the domain
layer (``ascendc_devkit.domain.chip``); this adapter only probes hardware and
returns the canonical generation.

Coverage: 910 family only (A2/A3/A5); other chips have no development scenario.

Routing (step 104, docs/plan/dispatch-npu-probe-subprocess/): the orchestrator
main process must stay pure Python — in-process torch_npu/CANN loading corrupts
its heap (intermittent dict collapse / whole-process SIGSEGV; see the issue doc
referenced by the plan). ``_probe_chip_blocking`` therefore routes by exposure:
torch_npu ALREADY in ``sys.modules`` (smoke/run-cases/runner subprocess contexts
— zero NEW native exposure) → in-process query; otherwise (orchestrator main
process) → subprocess probe (M1 pattern). A load-time import guard at the run
CLI entry enforces the same invariant for future code.
"""

from __future__ import annotations

import subprocess
import sys
import threading

from ascendc_devkit.domain.chip import (
    A2, A3, A5, UNKNOWN, is_known_generation, runtime_supports_design)
from ascendc_devkit.infra.logger import Logger

# Hardware device-name substring → canonical generation.
# Order matters: more specific suffixes (910C/910B) must precede the bare
# "Ascend910" so a 910C device isn't mis-read as 910B/A2 via the 910 prefix.
_DEVICE_TO_CHIP: dict[str, str] = {
    "Ascend950":  A5,
    "Ascend910C": A3,
    "Ascend910B": A2,
    "Ascend910":  A2,
}

# Bound on the hardware probe. A healthy driver answers device_count() /
# get_device_name() in well under a second; the NPU driver is intermittently
# unstable (hdcdrv_connect_wait_reply → a kernel ioctl with NO timeout and NO
# Python-visible exception — observed 7.4s degraded, 13min+ stuck). 60s cleanly
# separates "healthy" cold-start (8-12s/card, slow cards 12-44s) from "stuck"
# and is overridable from config (orchestration-config.json
# timeouts.hw_probe_sec), threaded in by the L3 callers (this L4 adapter
# cannot import the L3 config module — §1.1).
_DEFAULT_HW_PROBE_TIMEOUT = 60.0


class EnvironmentProbeTimeout(Exception):
    """The NPU driver probe did not answer within the bound (hung on
    hdcdrv_connect_wait_reply).

    A driver-health signal, NOT maskable (§3.7): never silently fall back to a
    guessed chip — that would both let a real mismatch slip through the build
    gate AND hide the broken driver. Propagate it so the caller halts honestly
    (codegen.validate_inputs / Deployer.deploy → a halt-class error) or the user
    bypasses it (``--assume-chip`` skips the probe when they know their box).
    """

    def __init__(self, timeout_sec: float):
        self.timeout_sec = timeout_sec
        super().__init__(
            f"NPU 驱动探机超时（{timeout_sec:g}s 无响应，疑似 hdcdrv 死等）：无法探测当前"
            f"硬件代际，不能校验构建代际一致性。请重启/修复驱动后重试，或用 --assume-chip "
            f"显式声明硬件代际后放行。"
        )


def _probe_chip_inproc() -> str:
    """The actual torch_npu I/O, in-process. Returns the canonical generation,
    or ``UNKNOWN`` when the hardware cannot be identified. MAY HANG on an
    unstable driver — a blocked kernel ioctl that raises nothing — so callers
    MUST bound it via a thread (``detect_chip_version`` does).

    Only legitimate where torch_npu is ALREADY loaded (subprocess contexts).
    The orchestrator main process reaches it never — ``_probe_chip_blocking``
    routes to a subprocess probe there (step 104).

    The UNKNOWN sentinel (deliberately NOT in ``CHIP_GENERATIONS``, see
    ``domain.chip``) replaces the old silent A2 fallback: an unresolved chip is
    honestly "unknown", never a guessed A2 that would spuriously satisfy the run
    gate (design "A2" == runtime "A2"). Callers needing a real generation guard
    with ``is_known_generation`` (Step 5 run gate, ``NPURunner._soc_version``).
    """
    try:
        import torch_npu  # noqa: F811 — optional at import time

        if torch_npu.npu.device_count() == 0:
            return UNKNOWN

        device_name = torch_npu.npu.get_device_name(0)
    except Exception:
        return UNKNOWN

    # Match device name against known chips (substring match, ordered).
    for keyword, gen in _DEVICE_TO_CHIP.items():
        if keyword.lower() in device_name.lower():
            return gen

    return UNKNOWN


# Subprocess probe body (step 104): fresh interpreter, no import guard, loads
# torch_npu in the CHILD only — the parent's heap stays pure Python.
_PROBE_CHILD_CODE = (
    "from ascendc_devkit.adapters.npu.detect import _probe_chip_inproc\n"
    "print(_probe_chip_inproc())\n"
)

# Process-level cache of the last KNOWN generation. Chip model is a static
# hardware property, so caching it changes truth-freshness vs today no more
# than sys.modules already does (import happens once per process either way).
# UNKNOWN is deliberately NOT cached — it means "cannot identify (now)" and
# stays retryable by the next dispatch.
_PROBE_CACHE: str | None = None
_PROBE_LOCK = threading.Lock()


def _probe_chip_subprocess(timeout_sec: float) -> str:
    """Probe via a child interpreter (M1 pattern). Child timeout is a driver
    hang — re-raise as ``EnvironmentProbeTimeout`` so the §3.7 signal survives
    (a hang is NOT the same as "cannot identify" and must not become UNKNOWN)."""
    try:
        result = subprocess.run(
            [sys.executable, "-c", _PROBE_CHILD_CODE],
            capture_output=True, text=True, timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired as exc:
        raise EnvironmentProbeTimeout(timeout_sec) from exc
    if result.returncode != 0:
        # 对齐超时路径的可观测性（§1.2 可诊断）：rc≠0 = 探针子进程自身失败
        # （解释器/import 问题），不是「硬件无法识别」——stderr 尾部留痕后再按
        # UNKNOWN 诚实返回（UNKNOWN 不进缓存，保持可重试）。
        tail = (result.stderr or "").strip()[-300:]
        suffix = f"，stderr 尾部: {tail}" if tail else ""
        Logger.warn(
            f"NPU 探针子进程异常退出 rc={result.returncode}，按未知代际处理{suffix}")
        return UNKNOWN
    stdout = (result.stdout or "").strip()
    value = stdout.splitlines()[-1].strip() if stdout else ""
    return value if is_known_generation(value) else UNKNOWN


def _probe_chip_blocking(timeout_sec: float = _DEFAULT_HW_PROBE_TIMEOUT) -> str:
    """Route the probe by torch_npu exposure (step 104).

    - torch_npu already in ``sys.modules`` (smoke/run-cases/runner subprocess
      contexts) → in-process query: zero NEW native exposure, identical to the
      historical behavior — no grandchild subprocess, no extra latency.
    - not loaded (orchestrator main process) → subprocess probe: the main
      process must stay pure Python (see module docstring).

    Double-checked lock: concurrent first probes (batch N dispatch threads)
    spawn ONE child, the rest hit the cache. MAY still overrun ``timeout_sec``
    on the in-process path (uninterruptible ioctl) — ``detect_chip_version``
    bounds it via its probe thread as before.
    """
    global _PROBE_CACHE
    if _PROBE_CACHE is not None:
        return _PROBE_CACHE
    with _PROBE_LOCK:
        if _PROBE_CACHE is not None:
            return _PROBE_CACHE
        if "torch_npu" in sys.modules:
            value = _probe_chip_inproc()
        else:
            value = _probe_chip_subprocess(timeout_sec)
        if is_known_generation(value):
            _PROBE_CACHE = value
        return value


def detect_chip_version(
    timeout_sec: float = _DEFAULT_HW_PROBE_TIMEOUT,
) -> str:
    """Detect the canonical chip generation from the first NPU device.

    Returns one of ``"A2"``/``"A3"``/``"A5"``, or ``UNKNOWN`` when the hardware
    cannot be identified (torch_npu unavailable, 0 devices, unknown device name)
    — an honest "unknown", never a silent A2 guess. A probe that overruns
    ``timeout_sec`` raises ``EnvironmentProbeTimeout`` (§3.7: do NOT mask a
    driver failure as a wrong chip). The probe runs in a daemon thread so the
    bound holds even though the blocked ioctl itself ignores interrupts; an
    overrunning thread is abandoned (cleaned up at process exit). Bounded HERE
    so every caller — dispatcher auto-detect, run_context, NPURunner — is
    uniformly protected (§1.2 可扩展: one fix auto-applies at every detect site).

    A flaky driver (hdcdrv hang) no longer has a per-call declared-chip bypass:
    the bounded probe + dispatch's ``--runtime_target_chip`` timeout fallback
    (step-34) cover that case at the single resolution point, so callers always
    see real (or honestly UNKNOWN) hardware.
    """
    holder: dict[str, str] = {}

    def _run() -> None:
        try:
            holder["chip"] = _probe_chip_blocking(timeout_sec)
        except EnvironmentProbeTimeout:
            # Subprocess-probe hang (child killed at its own timeout): surface
            # the SAME §3.7 signal as a thread overrun below — a driver hang is
            # not "cannot identify" and must not degrade to UNKNOWN.
            holder["timeout"] = "1"
        except Exception:
            # Historical behavior: probe failure = UNKNOWN (honest sentinel).
            holder["chip"] = UNKNOWN

    probe = threading.Thread(target=_run, daemon=True)
    probe.start()
    probe.join(timeout_sec)
    if probe.is_alive() or holder.get("timeout"):
        raise EnvironmentProbeTimeout(timeout_sec)
    return holder["chip"]


def chip_mismatch_reason(
    design_target_chip: str,
    runtime_target_chip: str,
) -> str | None:
    """Return a concrete reason if ``design_target_chip`` != the resolved runtime
    hardware, else ``None``.

    Pure comparison (step-34): the runtime chip was resolved ONCE at dispatch
    (probe authority → ``runtime_target_chip``, Step 3), so the gate no longer
    probes here. This eliminates the old double-probe (dispatch + gate) and makes
    ``codegen.validate_inputs`` a cheap pure gate (§3.8: no NPU-driver I/O).
    Single source for the build-chip gate (§1.9, §2.5), called by BOTH
    ``codegen.validate_inputs`` (the primary gate — raises ``PreconditionError``,
    codegen never spawns) and ``Deployer.deploy()`` (secondary deep-defense for
    the ``redeploy`` CLI / direct callers that bypass the pipeline). Compatibility
    is by PROGRAMMING MODEL (P65), NOT strict generation equality: a low-gen
    Membase design (A2/A3) is forward-compatible with an A5 box (A5 hardware runs
    Membase too), but an A5 Regbase design cannot run on A2/A3. Only the latter
    is a hard precondition (the compiled binary — CANN ``soc_version``/VF
    instructions fixed at compile time — genuinely cannot run); a compatible
    mismatch in programming model is allowed because the code itself is portable.

    Args:
        design_target_chip: design/compile intent ``"A2"``/``"A3"``/``"A5"``.
            Empty → no constraint (mirrors deploy's empty-chip auto-detect: an
            unset target lets the repo's ``build.sh`` auto-detect).
        runtime_target_chip: on-box hardware truth resolved at dispatch
            (``"A2"``/``"A3"``/``"A5"`` or ``UNKNOWN``).

    Returns:
        ``None`` when design is empty (no constraint) or the runtime hardware
        supports the design's programming model (compatible — includes same-gen
        AND low-gen-Membase-on-A5 forward-compat). A DISTINCT "cannot verify"
        reason when the runtime is unknown (probe couldn't identify the
        hardware) — the gate cannot verify what it cannot see, but surfaces it
        honestly (§1.2 可诊断) rather than silently passing;
        ``codegen.validate_inputs`` turns it into a precondition error so a
        hardware-less box fails at the gate, not later at ``NPURunner``.
        Otherwise a concrete mismatch reason naming BOTH values + a fix hint.
    """
    design = (design_target_chip or "").strip()
    if not design:
        return None
    runtime = (runtime_target_chip or "").strip()
    if not is_known_generation(runtime):
        return (
            f"无法校验构建代际一致性：本机硬件代际未知（{runtime or '未解析'!r}），"
            f"design_target_chip={design!r} 无法与硬件比对。请修复 NPU/驱动环境，"
            f"或用 --runtime_target_chip 显式声明硬件代际后重试。"
        )
    if runtime_supports_design(design, runtime):
        return None
    return (
        f"build target chip {design!r} 与当前硬件 {runtime!r} 不兼容："
        f"design 的编程模型无法在本机运行（A5 Regbase 产物不可降级到 A2/A3，"
        f"CANN soc_version/VF 指令编译期固定）。请在匹配硬件运行，"
        f"或将 design_target_chip 声明为 {runtime!r}（或更低的 Membase 代际）。"
    )
