"""L7 Infrastructure — 编排主进程纯 Python 守卫（step 104）。

不变式：编排主进程（``ascendc-devkit run``）不加载 torch/torch_npu/CANN——
进程内原生加载会间歇性写坏其堆（轻则 State/task_request 字典塌缩、重则整进程
SIGSEGV；根因与证据见 docs/plan/dispatch-npu-probe-subprocess/ 及其引用的
issue 文档）。设备访问一律下沉子进程（M1 / P69 既有边界）。

本守卫把对该不变式的违反从「概率性原生崩溃（不可诊断）」变为「import 当刻的
确定性报错」（§1.3 加载期校验优于运行期暴露）。装在三条主进程编排入口
（dispatch / dispatch_single_stage / dispatch_single_skill，幂等可重复安装）；
探测/smoke/run-cases 等子进程是全新解释器，不受影响（其内 import 合法且必要）。

逃生门：``DEVKIT_ALLOW_INPROC_TORCH=1``（仅应急——放行即失去不变式保护，
报错文案明示；真有合法主进程 torch 需求时应先改方案再放行）。
"""
from __future__ import annotations

import os
import sys

GUARDED_MODULES = ("torch", "torch_npu")

_PLAN_DOC = "docs/plan/dispatch-npu-probe-subprocess/01-analysis.md"


class InProcessTorchImportError(RuntimeError):
    """主进程纯 Python 不变式被违反：编排进程内 import torch/torch_npu。

    故意不继承 ImportError：调用方历史模式 ``try: import torch_npu
    except Exception/ImportError: <降级>`` 会把 ImportError 静默吞掉——
    守卫的价值在于响亮失败，不被旧降级分支掩埋（§1.2 可诊断）。
    """


def _is_guarded(fullname: str) -> bool:
    return any(
        fullname == name or fullname.startswith(name + ".")
        for name in GUARDED_MODULES
    )


class _PurityBlocker:
    """sys.meta_path finder：被守护模块的首次 import 即刻抛错。

    必须 insert 到 meta_path **第 0 位**：append 尾部时标准 PathFinder 先于
    我们解析出真实 spec，torch 父模块已开始执行、只在某个（恰好不存在的）
    子模块上才轮到本 finder——拦截点漂移且父模块已半加载。第 0 位保证
    find_spec("torch") 在任何真实解析前抛错，父模块一行都不执行。
    """

    def find_spec(self, fullname, path=None, target=None):  # noqa: ANN001
        if _is_guarded(fullname):
            raise InProcessTorchImportError(
                f"编排主进程禁止 import {fullname!r}：进程内加载 torch/torch_npu/"
                f"CANN 会间歇性损坏主进程堆（字典塌缩/整进程 SIGSEGV，"
                f"见 {_PLAN_DOC}）。设备访问请走子进程（探测/烟雾/run-cases 均已"
                f"子进程化）。应急放行：DEVKIT_ALLOW_INPROC_TORCH=1（失去不变式保护）。"
            )
        return None


def _blocker_installed() -> bool:
    return any(isinstance(finder, _PurityBlocker) for finder in sys.meta_path)


def install_purity_guard() -> None:
    """在 run CLI 入口安装守卫（幂等；逃生门 env 下为 no-op）。

    安装时若 torch/torch_npu 已被预载，直接抛错——守卫必须在任何可能触发
    import 的工作开始前安装，预载即已违反不变式。
    """
    if os.environ.get("DEVKIT_ALLOW_INPROC_TORCH") == "1":
        return
    preloaded = [name for name in GUARDED_MODULES if name in sys.modules]
    if preloaded:
        raise InProcessTorchImportError(
            f"编排主进程启动时已加载 {preloaded}（违反纯 Python 不变式，"
            f"见 {_PLAN_DOC}）——入口安装守卫前不应有任何 torch/torch_npu "
            f"import 链。应急放行：DEVKIT_ALLOW_INPROC_TORCH=1。"
        )
    if _blocker_installed():
        return
    # 第 0 位：先于 PathFinder 等真实解析器（见 _PurityBlocker docstring）。
    sys.meta_path.insert(0, _PurityBlocker())


def uninstall_purity_guard() -> None:
    """摘除守卫（测试隔离用；生产路径不摘）。"""
    sys.meta_path[:] = [f for f in sys.meta_path if not isinstance(f, _PurityBlocker)]
