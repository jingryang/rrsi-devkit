"""registry 懒加载并发安全 UT。

历史缺陷（回归守护目标）：``_ensure_stages_loaded`` 曾是无锁 check-then-act，
批内多 dispatch 线程并发首调 ``get_workflow`` 时，多线程同时进入导入块，
导入链跨线程交错下 from-import 可见半初始化模块——真实批 6 并发 dispatch
5 路 ``ImportError: cannot import name 'CodegenStage'``。修复 = 双检锁（RLock）。

真实不变式（非 mock）：新进程内 N 线程 barrier 同步并发首调，全部成功且注册表
完整；同线程持锁嵌套调 loader 不死锁（RLock 重入语义）。
"""

from __future__ import annotations

import subprocess
import sys
import threading

import pytest

from ascendc_devkit.orchestration import registry


_CONCURRENT_SCRIPT = """
import sys
import threading
from ascendc_devkit.orchestration.registry import get_workflow, get_stage, STAGE_REGISTRY

N = int(sys.argv[1])
bar = threading.Barrier(N)
errs = []

def hammer():
    try:
        bar.wait()
        wf = get_workflow("self_evolve_op")
        assert wf is not None, "workflow 实例为 None"
        # 历史失败点：并发窗口内 from-import 半初始化 stages.codegen
        stage_cls = get_stage("codegen")
        assert stage_cls is not None
    except BaseException as exc:  # noqa: BLE001 - 收集一切失败证据
        errs.append(repr(exc))

threads = [threading.Thread(target=hammer) for _ in range(N)]
for t in threads:
    t.start()
for t in threads:
    t.join()
assert not errs, f"并发首调失败 {len(errs)}/{N}: {errs[:3]}"
assert len(STAGE_REGISTRY) >= 12, f"注册表不完整: {len(STAGE_REGISTRY)}"
print("OK")
"""


def test_concurrent_first_load_in_fresh_process():
    """N 线程并发首调 get_workflow/get_stage：零失败、注册表完整。

    每轮独立子进程（fresh sys.modules），复刻批 dispatch 的真实并发形态。
    """
    rounds = 3
    for i in range(rounds):
        proc = subprocess.run(
            [sys.executable, "-c", _CONCURRENT_SCRIPT, "8"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert proc.returncode == 0, (
            f"round {i}: 并发首调失败\nstdout={proc.stdout[-500:]}\nstderr={proc.stderr[-800:]}"
        )


def test_reentrant_lock_no_self_deadlock():
    """同线程持 _LOAD_LOCK 再调 loader：RLock 重入语义下不得自死锁。

    防回归：锁若退化为非重入 Lock，stage 模块导入链嵌套调回 loader 即挂死。
    用带超时的 worker 线程探测，避免测试本身挂死。
    """
    result: dict = {}

    def worker():
        try:
            with registry._LOAD_LOCK:
                # 持锁嵌套调 loader——修复后（RLock）应直接重入成功
                registry._ensure_stages_loaded()
                registry._ensure_workflows_loaded()
            result["ok"] = True
        except BaseException as exc:  # noqa: BLE001
            result["ok"] = False
            result["err"] = repr(exc)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout=30)
    assert not t.is_alive(), "嵌套调 loader 挂死（锁非重入？）"
    assert result.get("ok") is True, f"嵌套调用异常: {result.get('err')}"
