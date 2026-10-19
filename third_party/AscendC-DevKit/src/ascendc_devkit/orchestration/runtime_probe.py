"""L3 Orchestration — runtime environment preflight (single point).

dispatcher 启动期的运行时探测编排（2026-09-03 KNOWN 清零 step-1）：CANN 工具链门 /
NPU 可用性门 / env 契约回环 / 芯片型号解析，原为 dispatcher(L2) 内联编排函数（跨层直连
L6 detect/CANN、L7 env_contract），收拢为本 L3 模块——dispatcher 只调本模块，设备机制留
各层原位（L6 detect_chip_version / CANNToolchain；L3 同层 orchestration/npu_probe
npu_runtime_available；L7 infra/env_contract）。
§1.1 层矩阵：本模块 import L6/L7 合法（3→6/7）；dispatcher(L2) import 本模块合法（2→3）。

迁自 application/dispatcher.py（P113 缓存 / M1 防 driver hang / step-34 双权威 chip /
step-108 env 契约回环），语义逐字不变。
"""
from __future__ import annotations

import os
import threading

from ascendc_devkit.infra.logger import Logger
from ascendc_devkit.domain.exit_codes import EX_CONFIG
from ascendc_devkit.adapters.npu.detect import detect_chip_version, EnvironmentProbeTimeout
from ascendc_devkit.orchestration.kernel.state import State


# 并发 dispatch，每 task 跑一次 _preflight_runtime → NPURunner() smoke。并发触发
# NPU runtime init（torch.zeros(1).npu()）冲突 → ERR99999 → 误判「NPU 缺失」致算子
# abort。缓存使同进程内 CANN+NPU smoke 只实跑一次；Lock 串行化 cache miss，并发 task
# 第一个持锁实跑、其余等锁后命中缓存，消除并发 init 冲突。cache 不跨进程（每次 CLI
# 独立进程），无串味——NPU/CANN 可用性在一次进程生命期内不变。
_RUNTIME_CHECK_CACHE: dict[tuple[str, bool], int | None] = {}
_RUNTIME_CHECK_LOCK = threading.Lock()


# M1: NPU smoke 子进程外墙（防 driver hang——memory npu-driver-hdcdrv-hang）。
# 卡级探测界 = hw_probe_sec（正常冷启动 ~7-10s、慢卡 open-device 实测 12-44s），
# 最坏首卡挂满卡级界后仍可探到后续健康卡，故外墙 120s 留足余量。单点实现与
# 策略（P113 串行逐卡 healthy_cards）见 orchestration/npu_probe.py。
_NPU_SMOKE_TIMEOUT_SEC = 120


def _check_runtime_once(workflow, enable_stubbed: bool) -> int | None:
    """CANN+NPU 可用性检查，按 ``(workflow.name, enable_stubbed)`` 进程内缓存 +
    Lock 串行化。返回非 None = 失败 exit code（应中止）；None = 通过。

    None 是合法缓存值（预检通过），用 ``key in cache`` 区分「未缓存」与「缓存 None」。
    """
    key = (getattr(workflow, "name", "") or "", enable_stubbed)
    with _RUNTIME_CHECK_LOCK:
        if key in _RUNTIME_CHECK_CACHE:
            Logger.info(
                f"preflight: runtime check cached ({key[0]}), skip 重复 NPU smoke")
            return _RUNTIME_CHECK_CACHE[key]
        code = _run_runtime_checks()
        _RUNTIME_CHECK_CACHE[key] = code
        return code


def _run_npu_smoke_subprocess(timeout_sec: float) -> tuple[bool, str]:
    """子进程 NPU smoke——L3 单点薄包装（orchestration/npu_probe 单点统一）。

    语义「存在能 open device 的健康卡」（串行逐卡、first-only），非「默认卡
    可用」；实现、防 hang 外墙语义与诊断格式见
    ``orchestration/npu_probe.py::npu_runtime_available``（§1.15 单通路）。
    """
    from ascendc_devkit.orchestration.npu_probe import npu_runtime_available
    return npu_runtime_available(timeout_sec)


def _run_runtime_checks() -> int | None:
    """CANN toolchain + NPU runtime 实际检查（无 state/workflow 依赖，可缓存）。

    Check 2 的 NPU smoke 放子进程 + timeout（M1）：主进程同步 smoke 在 driver hang
    时永久阻塞，P113 持锁后放大为全 batch 卡死；子进程隔离把 hang 限定在 timeout 内。
    """
    # Check 1: CANN toolchain (PATH/env 检查，毫秒级，进程本安全)
    from ascendc_devkit.adapters.toolchain.cann import CANNToolchain
    tc = CANNToolchain()
    if not tc.is_available:
        Logger.error(
            "CANN 工具链缺失，运行将中止"
            "（不会进入任何 Agent 阶段，避免数百秒的无效开销）：")
        Logger.error(f"  {tc.diagnostic_hint()}")
        return EX_CONFIG

    # Check 2: NPU runtime —— 子进程 smoke + timeout 防 driver hang（M1）
    ok, reason = _run_npu_smoke_subprocess(_NPU_SMOKE_TIMEOUT_SEC)
    if not ok:
        Logger.error(
            f"NPU 运行时缺失，运行将中止（不会进入任何 Agent 阶段）：{reason}")
        Logger.error(
            "  → 安装 torch_npu（确保 torch 为 GPU 版本而非 CPU-only），"
            "或传 --enable-stubbed 允许 stub 回退")
        return EX_CONFIG

    # Check 3: env 契约回环探针（step-108，批 20260829-142941-49134b P3）——
    # 合成但**形态忠实**的探测值（后缀必须与生产值同形——哑值触发不了后缀匹配
    # 类毒）经真实子进程回读比对。外部 sitecustomize 类毒在开跑秒级拦截，
    # 对照该批 10h 空烧。纯 stdlib 子进程，零 torch（step-104 红线）、不占卡。
    from ascendc_devkit.infra import env_contract
    violation = env_contract.probe_env_contract({
        **os.environ,
        "ASCEND_CUSTOM_OPP_PATH": env_contract.PREFLIGHT_PROBE_VALUE,
    })
    if violation is not None:
        Logger.error(f"环境契约失配，运行将中止：{violation}")
        for line in env_contract.diagnose_env_hooks():
            Logger.error(f"  候选成因：{line}")
        return EX_CONFIG

    return None


def _preflight_runtime(state: State, workflow) -> int | None:
    """Fail fast when an NPU-requiring workflow lacks CANN or NPU runtime.

    Uses ``workflow.requires_npu`` — an explicit per-workflow flag — rather
    than implicitly checking for a ``verify`` stage.  This covers workflows
    like ``self_evolve_op`` (deploy + cannbench_eval need NPU, but has no
    verify stage) and skips design-only workflows (SE) cleanly.

    Checks (cached + Lock-serialized per process, P113 — see
    ``_check_runtime_once`` for why concurrent dispatch must not re-run the
    NPU smoke):
      1. CANN toolchain (ccec)
      2. NPU runtime (torch_npu)

    Skips when:
      - workflow.requires_npu is False (design-only, runs on CPU machines)
      - --enable-stubbed is set (user opted into stub fallback)
    """
    if not getattr(workflow, "requires_npu", False):
        return None

    if state.enable_stubbed:
        return None

    return _check_runtime_once(workflow, state.enable_stubbed)


def _resolve_chip_fields(
    task_request: dict, probe_timeout_sec: float,
) -> tuple[str, str, str, str] | None:
    """Resolve the dual chip fields (step-34) with disjoint authority + sources.

    Replaces the single ``resolved_chip`` path that conflated CLI design intent
    with probed hardware truth (and let ``--assume-chip`` leak into the target
    side, making the run gate a tautology). Two fields, two authorities:

      - ``design_target_chip`` — CLI ``--design_target_chip`` only, here. The
        requirement-doc / profile-default layers of its authority chain are
        applied downstream in context/requirement stage; dispatch carries the
        CLI value (may be empty → resolved downstream, NOT silently probed).
      - ``runtime_target_chip`` — probe authority; ``--runtime_target_chip`` is
        ONLY a flaky-driver timeout fallback (the probe wins whenever it can
        answer, even with UNKNOWN — honest "cannot verify", not a guessed chip).

    The probe is BOUNDED. A timeout no longer hard-halts: if the user declared
    ``--runtime_target_chip``, the run continues with that fallback (+ warning,
    §1.2 可诊断); only a timeout with no fallback returns ``None`` → dispatch
    halts ``EX_DATAERR`` (§3.7: don't mask a dead driver, but don't strand a run
    where the user already declared their box either).

    Sources (recorded in the ``chip_decision`` event for observability):
      - ``design_source`` — ``"cli"`` when the user passed --design_target_chip,
        else ``""`` (downstream context/requirement stages own the other layers).
      - ``runtime_source`` — ``"probe"`` normally; ``"timeout_fallback"`` when
        the probe timed out and --runtime_target_chip stood in.

    Returns ``(design_chip, runtime_chip, design_source, runtime_source)`` or
    ``None`` if the runtime chip is unresolvable (probe timed out, no fallback).
    """
    design_chip = task_request.get("design_target_chip") or ""
    design_source = "cli" if design_chip else ""
    runtime_cli = task_request.get("runtime_target_chip") or ""
    runtime_source = "probe"
    try:
        runtime_chip = detect_chip_version(timeout_sec=probe_timeout_sec)
    except EnvironmentProbeTimeout as e:
        if runtime_cli:
            Logger.warn(
                f"NPU 探机超时，按 --runtime_target_chip={runtime_cli!r} 兜底：{e}")
            runtime_chip = runtime_cli
            runtime_source = "timeout_fallback"
        else:
            return None
    return design_chip, runtime_chip, design_source, runtime_source
