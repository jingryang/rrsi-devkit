#!/usr/bin/env python3
"""动态找一张当前可用的 NPU 卡（供 s5-compile 等 agent 运行时调用，现场决定卡号）。

背景（2026-08-10 exp run）：batch 并发下 state_snapshot.npu_id 静态预分配的卡可能被
其他任务占用（507033 / device open failed），s5-compile 曾现场编写 for id in ...;
timeout python3 -c "torch.npu.set_device" 探测循环反复找卡——串行探测会被坏卡 timeout
拖死，且并发新起 torch_npu 子进程初始化自身可能 segfault（RC=139），把"卡坏"与
"探测方法崩"混淆，导致 52 分钟 LLM 找卡空耗。

本脚本把找卡固化为确定性工具，关键设计：
1. npu-smi 健康过滤（Health=OK）作为第一层筛选；
2. 对每张健康卡【串行】起子进程实测 torch_npu 能否 open（子进程隔离：单张坏卡
   hang 只消耗它自己的 timeout，不阻塞后续卡；串行避免并发 torch_npu init 与驱动
   竞争误伤健康卡——与框架单点 orchestration/npu_probe.py::healthy_cards 的
   P113 串行策略一致）；
3. 输出：stdout=第一个可用的卡 id；全部不可用 → exit 1 + stderr "NO_AVAILABLE_CARD"。

重试语义：batch 并发下卡状态动态变化（同一张卡不同时刻可能 OK/被占交替）。--max-wait
指定总重试窗口（秒）——窗口内循环探测，卡一旦释放立即返回；窗口耗尽仍无卡才失败。
不固定次数：并发任务时长未知，按时间窗口重试比按次数更稳（次数可能在等待期耗尽）。

纯标准库实现，不依赖 ascendc_devkit——skill 可单独取出运行（即插即用）。

用法:
  python3 pick_available_card.py [--timeout 25] [--max-wait 500] [--poll-interval 10] [--all]
  --timeout         单卡子进程探测超时（秒），默认 25
  --max-wait        总重试窗口（秒），默认 500；0 = 单轮探测不重试
  --poll-interval   每轮探测之间的等待（秒），默认 10
  --all             打印全部健康卡的实测结果后退出（诊断用，仍正常返回可用卡）
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time


def smi_healthy_cards() -> list[int]:
    """解析 ``npu-smi info`` 中 Health=OK 的卡 id 列表。

    失败（命令不可用/超时）返回空列表——不掩盖，调用方据此判无可筛卡片。
    健康卡行形如 ``| 0 | Ascend950DT | OK | ... |`` → split("|")[1]=id, [3]=Health。
    """
    try:
        out = subprocess.run(["npu-smi", "info"], capture_output=True,
                             text=True, timeout=60).stdout
    except Exception as exc:  # noqa: BLE001 — 探测命令不可用即无可筛卡片
        print(f"npu-smi 失败: {exc}", file=sys.stderr)
        return []
    cards: list[int] = []
    for line in out.splitlines():
        parts = line.split("|")
        if len(parts) >= 4:
            try:
                cid = int(parts[1].strip())
            except ValueError:
                continue
            if parts[3].strip() == "OK":
                cards.append(cid)
    return cards


def _probe(card: int, timeout: float) -> tuple[int, bool, str]:
    """子进程实测单卡能否 open（torch_npu set_device + 建 tensor + sync）。

    独立子进程：torch_npu 初始化崩溃 / 卡 hang 只影响本卡，不影响其他卡探测。
    """
    code = (
        "import sys\n"
        "import torch, torch_npu\n"
        f"torch.npu.set_device({card})\n"
        f"x = torch.ones(4, dtype=torch.float16, device='npu')\n"
        f"y = x + x\n"
        "torch.npu.synchronize()\n"
        "print('OK')\n"
    )
    try:
        r = subprocess.run([sys.executable, "-c", code],
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return card, False, f"timeout>{timeout:.0f}s"
    if r.returncode == 0:
        return card, True, ""
    detail = (r.stderr or r.stdout or "").strip().splitlines()
    return card, False, (detail[-1][:120] if detail else "unknown error")


def _probe_round(timeout: float, print_all: bool) -> int | None:
    """单轮探测：npu-smi 健康过滤 + 串行隔离实测，返回第一张可用卡 id。

    全不可用返回 None（调用方据此进入下一轮或放弃）。结果打到 stderr 供诊断。
    串行策略（P113，与框架 orchestration/npu_probe.py::healthy_cards 一致）：
    并发 torch_npu init 会与驱动竞争、可能把健康卡也探挂；单张坏卡最多消耗它
    自己的 ``timeout`` 秒，不会阻塞后续卡。
    """
    healthy = smi_healthy_cards()
    if not healthy:
        print("npu-smi 未发现 Health=OK 的卡", file=sys.stderr)
        return None
    print(f"健康卡(npu-smi): {healthy}", file=sys.stderr)
    results: list[tuple[int, bool, str]] = []
    for cid in healthy:
        result = _probe(cid, timeout)
        results.append(result)
        ok = result[1]
        tag = "OK" if ok else "FAIL " + result[2]
        print(f"card {cid}: {tag}", file=sys.stderr)
        if ok:
            return cid
    return None


def find_available_card(timeout: float = 25.0, max_wait: float = 500.0,
                        poll_interval: float = 10.0,
                        print_all: bool = False) -> int | None:
    """在 ``max_wait`` 窗口内循环探测，返回第一张可用卡 id；窗口耗尽仍无卡返回 None。

    - ``max_wait <= 0``：单轮探测，不重试。
    - ``max_wait > 0``：窗口内每轮并行探测，间隔 ``poll_interval``；卡一旦释放即返回。
    - ``print_all``：每轮把各卡实测结果打到 stderr（诊断用，不改变返回值语义）。
    """
    deadline = time.monotonic() + max_wait if max_wait > 0 else 0.0
    while True:
        card = _probe_round(timeout=timeout, print_all=print_all)
        if card is not None:
            return card
        if max_wait <= 0 or time.monotonic() >= deadline:
            return None
        # 未到窗口截止：等待后进入下一轮。间隔不超过剩余时间。
        sleep = min(poll_interval, max(0.0, deadline - time.monotonic()))
        print(f"本轮无可用卡，等待 {sleep:.0f}s 后重试（窗口剩余 "
              f"{max(0.0, deadline - time.monotonic()):.0f}s）", file=sys.stderr)
        if sleep > 0:
            time.sleep(sleep)


def _non_negative(value: str) -> float:
    """argparse type：非负 float。负值/非法直接报错（§1.3 加载期校验）。"""
    f = float(value)
    if f < 0:
        raise argparse.ArgumentTypeError(f"必须是 >= 0，收到 {value}")
    return f


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--timeout", type=_non_negative, default=25.0,
                    help="单卡子进程探测超时（秒），默认 25")
    ap.add_argument("--max-wait", type=_non_negative, default=500.0,
                    help="总重试窗口（秒），默认 500；0 = 单轮探测不重试")
    ap.add_argument("--poll-interval", type=_non_negative, default=10.0,
                    help="每轮探测之间的等待（秒），默认 10")
    ap.add_argument("--all", action="store_true",
                    help="打印全部健康卡实测结果后仍返回可用卡（诊断用）")
    a = ap.parse_args(argv)

    card = find_available_card(timeout=a.timeout, max_wait=a.max_wait,
                               poll_interval=a.poll_interval, print_all=a.all)
    if card is None:
        print("NO_AVAILABLE_CARD", file=sys.stderr)
        return 1
    print(card)
    return 0


if __name__ == "__main__":
    sys.exit(main())
