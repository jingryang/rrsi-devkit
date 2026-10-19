"""L3 Orchestration — NPU 探测单点（多卡健康策略 + 运行时可用性）。

统一两族探测（§1.15 单通路）：

- **卡健康族**：机械探测在 L6 ``adapters.npu.probe``（``probe_device`` 单卡
  raise 变体，脚本/超时/诊断单一来源），本层承载**多卡编排策略**——串行逐卡 +
  子集/首卡语义（``healthy_cards``）。串行是硬策略（P113：并发 torch_npu init
  会与驱动竞争，可能把健康卡也探挂成 false all-dead）；batch_runner 卡池过滤
  与可用性探测共用本实现，禁止再各自内联副本或改用其它并发策略。
- **运行时可用性族**：``npu_runtime_available`` ——「存在能 open device 的健康
  卡」的子进程级单点，dispatcher 启动 smoke（L2）与 perf gate（L3）共用；
  原 ``infra/npu_probe.py`` 的 NPURunner 冒烟实现已删（机械探测与
  ``probe_device`` 重复、超时/诊断双轨漂移）。

L2 调用方（batch_runner / dispatcher）不能 import L6（分层矩阵 L2→L3,L4,L7），
故单点落在 L3（L3→L6 合法）。
"""

from __future__ import annotations

import os
import subprocess
import sys

from ascendc_devkit.adapters.npu.probe import probe_device  # L3 -> L6 合法
from ascendc_devkit.domain.exceptions import EnvironmentNotAvailableError
from ascendc_devkit.orchestration.runtime_config import hw_probe_timeout_sec


def healthy_cards(
    cards: list[int],
    timeout: float,
    first_only: bool = False,
) -> list[int]:
    """Return the subset of ``cards`` that can actually open a device context.

    Serial per-card bounded subprocess (P113 — parallel NPU init races the
    driver and can fail even healthy cards), preserving declaration order.
    ``first_only=True`` stops at the first healthy card — for callers whose
    semantic is only "at least one usable card" (e.g. the availability probe),
    so a single slow card cannot delay the answer.
    """
    healthy: list[int] = []
    for card in cards:
        try:
            probe_device(card, timeout=timeout)
        except EnvironmentNotAvailableError:
            continue
        healthy.append(card)
        if first_only:
            break
    return healthy


def npu_runtime_available(timeout_sec: float = 120.0) -> tuple[bool, str]:
    """子进程探测 NPU 运行时可用性（「存在能 open device 的健康卡」）。

    单点（§1.15）：dispatcher 启动 smoke 与 perf gate 共用。子进程内先
    ``import torch_npu`` 数卡（预载——孙进程探测共享 page cache），再经
    ``healthy_cards(first_only=True)`` 串行逐卡 ``set_device + alloc``。
    语义是「存在可用卡」而非「默认卡可用」——单卡（device 0）驱动 context
    泄漏/坏卡（507033 / TsdOpen failed）时，其余健康卡仍可承接任务。

    防 driver hang（memory npu-driver-hdcdrv-hang）：driver 偶发
    ``hdcdrv_connect_wait_reply`` 死等——无 timeout、不抛异常，主进程同步
    smoke 会永久阻塞；P113 的 cache+Lock 持锁实跑会放大为全 batch 等锁卡死
    （M1）。子进程隔离 + timeout：最多浪费 ``timeout_sec``，主流程不卡、锁必
    释放。卡级探测界 = ``hw_probe_sec``（正常冷启动 ~7-10s、慢卡 open-device
    实测 12-44s）；外墙 ``timeout_sec``（调用方传入，默认 120）覆盖「首卡挂
    满卡级界后仍探到后续健康卡」的最坏路径。

    返回 ``(ok, reason)``：ok=True 至少一张卡可用（reason 带 HEALTHY_CARDS
    卡号）；False 附**可诊断原因**（超时=疑 driver hang / 全卡不可用 / 子进程
    异常含 traceback 尾部）——绝不把异常静默折成一句 False（§3.7）。
    """
    import ascendc_devkit as _pkg
    _pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(_pkg.__file__)))
    _py_path = os.pathsep.join(
        filter(None, [_pkg_root, os.environ.get("PYTHONPATH", "")]))
    _env = {**os.environ, "PYTHONPATH": _py_path}
    _card_timeout = hw_probe_timeout_sec()
    code = (
        "import sys, traceback\n"
        "try:\n"
        "    import torch_npu\n"
        "    from ascendc_devkit.orchestration.npu_probe import healthy_cards\n"
        "    total = int(torch_npu.npu.device_count())\n"
        f"    healthy = healthy_cards(list(range(total)), timeout={_card_timeout!r}, first_only=True)\n"
        "    if healthy:\n"
        "        print('HEALTHY_CARDS=' + ','.join(str(c) for c in sorted(healthy)))\n"
        "        sys.exit(0)\n"
        "    sys.exit(2)\n"
        "except Exception:\n"
        "    sys.stderr.write(traceback.format_exc())\n"
        "    sys.exit(3)\n"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", code],
            env=_env, capture_output=True, text=True, timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired:
        return False, (
            f"NPU smoke 超时（{timeout_sec:.0f}s 未返回）—— 疑 driver hang"
            f"（memory npu-driver-hdcdrv-hang：hdcdrv_connect_wait_reply 死等）")
    if result.returncode == 0:
        healthy_line = next(
            (ln for ln in (result.stdout or "").splitlines()
             if ln.startswith("HEALTHY_CARDS=")), "")
        healthy = (healthy_line.split("=", 1)[1] if healthy_line else "?")
        return True, f"ok (healthy cards: {healthy})"
    tb = (result.stderr or "").strip()
    if result.returncode == 2:
        prefix = "全部 NPU 卡不可用（smoke 调用完成但无卡可 open device）"
    else:
        prefix = f"smoke 异常（exit {result.returncode}）"
    return False, prefix + (f"\n{tb[:500]}" if tb else "")
