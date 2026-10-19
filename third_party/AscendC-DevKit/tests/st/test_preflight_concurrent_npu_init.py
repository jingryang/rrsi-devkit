"""P113 实证:NPU runtime init 并发冲突诊断（坐实 batch resume 并发预检误杀根因）。

**为什么有这个测试**：batch resume 用 ThreadPoolExecutor 并发 dispatch，每 task 跑一次
`_preflight_runtime → NPURunner() → torch.zeros(1).npu()` smoke。memory/runlog 称多进程并发
触发 ERR99999，但代码实际是线程池——本测试坐实「线程 vs 进程」到底哪个触发 NPU runtime
init 冲突，给 batch 级共享预检（B3 修复）提供 ground truth。

**性质**：诊断性 ST——被测对象是 torch_npu runtime 的并发行为（外部依赖），**非**被测框架
代码。框架预检逻辑（batch 共享、cache 短路）的回归由 `test_application.py::TestPreflightToolchain`
+ `test_batch_runner.py`（UT）覆盖。本测试断言 baseline（NPU 本可用），并发结果以观察记录
呈现（torch_npu 并发行为非确定，不构成被测代码缺陷，故不强制断言其成败）。

**默认不跑**（§3.6/§3.11）：
    pytest -m npu tests/st/test_preflight_concurrent_npu_init.py -s
真机会真实引发并发冲突；跑后建议复位 NPU runtime（新进程重导 torch_npu）。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from ascendc_devkit.adapters.npu.runner import NPURunner

_N = 5  # 并发度（对齐 batch 默认 5 算子全并发）


def _npu_smoke() -> tuple[bool, str]:
    """单次 NPURunner() 构造 smoke；返回 (available, 诊断串)。供线程/进程并发调用。"""
    try:
        r = NPURunner()
        if r._torch_npu_available:
            return True, "ok"
        return False, "torch_npu_available=False（smoke 通过但 flag 为假）"
    except Exception as e:  # noqa: BLE001 — 诊断：捕获一切以记录冲突形态
        return False, f"{type(e).__name__}: {e}"


def _worker_process(_i: int = 0) -> tuple[bool, str]:
    """进程并发 worker（spawn 可 pickle 的模块级函数）。"""
    return _npu_smoke()


@pytest.mark.npu
@pytest.mark.slow
class TestConcurrentNpuInit:
    """P113 根因实证：NPU runtime init 在并发下是否冲突（线程 vs 进程）。"""

    def test_baseline_single_process_available(self):
        """baseline：单进程 NPURunner() 必须可用（确认 NPU 本身健康，否则实证无意义）。"""
        ok, msg = _npu_smoke()
        assert ok, (
            f"baseline 单进程 NPURunner 不可用：{msg}——NPU 环境本身有问题，"
            "并发实证失去对照基准。先修 NPU/驱动/torch_npu 配置。"
        )

    def test_thread_concurrent_init(self):
        """N 线程并发 NPURunner()：记录成功率。

        ThreadPoolExecutor = batch_runner 的并发模型。若 ok<N，坐实「线程并发 init
        冲突」即 P113 batch abort 的直接根因（同进程多线程并发 torch_npu runtime init）。
        """
        with ThreadPoolExecutor(max_workers=_N) as ex:
            results = list(ex.map(lambda _: _npu_smoke(), range(_N)))
        ok_count = sum(1 for ok, _ in results if ok)
        errs = [msg for ok, msg in results if not ok]
        print(f"\n[thread concurrent N={_N}] ok={ok_count}/{_N} failures={errs}")
        # 诊断性：记录现象供根因判读，不断言成败（torch_npu 并发行为非确定）。

    def test_process_concurrent_init(self):
        """N 进程并发 NPURunner()：对照（spawn 强制重新 init，避免 fork 继承父状态）。

        与线程结果对照，判读冲突触发维度：仅进程 / 仅线程 / 两者。memory 记「5 进程全
        ERR99999」，本用例证伪或证实之。
        """
        import multiprocessing as mp

        ctx = mp.get_context("spawn")
        with ctx.Pool(_N) as pool:
            results = pool.map(_worker_process, range(_N))
        ok_count = sum(1 for ok, _ in results if ok)
        errs = [msg for ok, msg in results if not ok]
        print(f"\n[process concurrent N={_N} spawn] ok={ok_count}/{_N} failures={errs}")
        # 诊断性：对照线程结果，定位冲突维度。
