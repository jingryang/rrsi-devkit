"""Guard: sys.executable -c subprocesses must be time-bounded (driver-hang).

防 driver hang（memory npu-driver-hdcdrv-hang）：``hdcdrv_connect_wait_reply``
是内核 ioctl、无超时无异常，主进程同步跑一个起 torch_npu 的子进程若 driver 死等会
永久阻塞。全仓所有 ``sys.executable -c`` 子进程（设备探针 probe/card_pin/detect/
npu_probe/env_contract + eval/harness）均已带 ``timeout=``；本守卫防**未来的漏写**
（§1.3 加载期校验）。

判据 = 纯形态（review M2 修正）：凡 ``subprocess.run/Popen`` 的 cmd 含
``sys.executable``（或 python 解释器）且含 ``-c`` 的调用，**必须显式传 ``timeout``
kwarg**——不依赖脚本是字面量还是变量（旧版只看字面量、漏掉全仓真实的变量脚本形态
``[sys.executable, "-c", _PROBE_CODE]``，是空转）。任何 ``sys.executable -c`` 子进程
无界都该拦：不限于 torch 探针，凡起解释器跑代码都应防 hang。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[3] / "src" / "ascendc_devkit"


def _unbounded_py_c_calls(path: Path) -> list[str]:
    """Return offending sys.executable -c subprocess calls lacking a timeout kwarg."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: list[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("run", "Popen")):
            continue
        if not node.args:
            continue
        cmd = node.args[0]
        if not isinstance(cmd, (ast.List, ast.Tuple)):
            continue
        els = cmd.elts
        # cmd 首元素是 sys.executable（Attribute.attr==executable）或 python 解释器常量
        is_py = any(
            (isinstance(c, ast.Attribute) and c.attr == "executable")
            or (isinstance(c, ast.Constant) and "python" in str(c.value))
            for c in els
        )
        if not is_py:
            continue
        has_dash_c = any(
            isinstance(c, ast.Constant) and c.value == "-c" for c in els)
        if not has_dash_c:
            continue
        has_timeout = any(k.arg == "timeout" for k in node.keywords)
        if not has_timeout:
            out.append(f"{path.relative_to(_SRC.parent)}:{node.lineno}")
    return out


def test_sys_executable_dash_c_subprocesses_are_time_bounded():
    """Any sys.executable -c subprocess MUST pass a timeout (driver-hang guard)."""
    offenders: list[str] = []
    for f in sorted(_SRC.rglob("*.py")):
        try:
            offenders.extend(_unbounded_py_c_calls(f))
        except SyntaxError:
            continue
    assert not offenders, (
        "sys.executable -c 子进程必须带 timeout（防 driver hang——memory "
        "npu-driver-hdcdrv-hang）：\n  " + "\n  ".join(offenders))
