"""L7 Infrastructure — NPU 卡数探测（env + npu-smi 子进程，零原生加载）。

step 104（docs/plan/dispatch-npu-probe-subprocess/）：编排主进程纯 Python——
卡数探测不得在主进程 ``import torch_npu``（原生层堆损坏根因，见方案文档引用的
issue）。单点实现 env 优先序 + ``npu-smi info`` 子进程解析，供
``adapters/npu/slot.py``（兜底后默认 8）与 ``infra/provenance.py``（兜底后
None=未知）共用（§1.15 唯一通路）。

语义声明：``npu-smi`` 数的是**物理卡**；被替换的
``torch_npu.device_count()`` 数的是 ``ASCEND_RT_VISIBLE_DEVICES`` 过滤后的
**可见卡**。受限可见性场景必须显式声明 ``ASCEND_NPU_COUNT`` /
``ASCEND_DEVICE_NUM``（在所有调用点优先级最高）。

版式依据（driver 25.5.1 实测，2026-08-29）：每张卡**两行**——主行
``| <NPU号> <Name> | Health | ...``（编号与名字**合并格**）+ 子行
``| <Chip号> | <Bus-Id> | ...``（首格为 Chip 号，单芯恒 0）。**卡数 = 数主行**：
子行数 = 卡数 × 芯数，数子行在多芯卡上必然高估（batch 脚本 grep 数子行
"碰巧对"仅因当前单芯）。主行判定 = 首格以数字开头且后随非竖线字符
（合并格名字）；子行首格为纯数字后直接竖线，天然被排除。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess

# 卡主行：`| 0     910B3   | ...` —— 首格「NPU号 名字」合并，数字后必须跟
# 非竖线字符（排除子行 `| 0        | bus-id |`——其首格纯数字后直接竖线）。
_CARD_ROW = re.compile(r"^\|\s*(\d+)\s+[^|\s]")


def env_device_count() -> int | None:
    """``ASCEND_NPU_COUNT`` / ``ASCEND_DEVICE_NUM`` 显式声明（两键同义，先到先用）。

    返回 None 表示未声明或全部不可解析——调用方自持兜底。
    """
    for var in ("ASCEND_NPU_COUNT", "ASCEND_DEVICE_NUM"):
        raw = os.environ.get(var)
        if raw:
            try:
                return int(raw)
            except ValueError:
                continue
    return None


def npu_smi_device_count(timeout_sec: float = 8.0) -> int | None:
    """物理卡数（``npu-smi info`` 子进程，父进程零原生加载）。

    数**卡主行**（NPU 号+名字合并格行），按 NPU 号去重；子行（Chip/Bus）天然
    排除——多芯卡下数子行会按芯数高估（见模块 docstring 版式依据）。
    返回 None 表示 npu-smi 缺失/失败/输出无可解析行——调用方自持兜底。
    与 provenance._driver_version 同款子进程卫生（which 定位 + timeout + 合并
    stderr）。
    """
    bin_ = shutil.which("npu-smi")
    if not bin_:
        return None
    try:
        r = subprocess.run([bin_, "info"], capture_output=True, text=True,
                           timeout=timeout_sec)
        out = (r.stdout or "") + (r.stderr or "")
    except Exception:
        return None
    ids = {m.group(1) for m in map(_CARD_ROW.match, out.splitlines()) if m}
    return len(ids) if ids else None
