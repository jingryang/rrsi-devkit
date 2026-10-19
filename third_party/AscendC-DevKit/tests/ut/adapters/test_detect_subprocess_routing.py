"""Step 104（dispatch 主进程 NPU 探测子进程化）— detect 路由测试。

不变式：编排主进程纯 Python。``_probe_chip_blocking`` 按 torch_npu 是否已在
``sys.modules`` 路由：已加载（smoke/run-cases 等子进程上下文）→ 进程内直查
（零新增暴露、行为与旧实现一致）；未加载（编排主进程）→ 子进程探测（M1 模式）。
子进程超时必须还原为 ``EnvironmentProbeTimeout``（§3.7 驱动健康信号不可掩盖），
已知代际结果进程内缓存（静态硬件属性），UNKNOWN 不缓存（保持可重试）。

方案: docs/plan/dispatch-npu-probe-subprocess/02-impl.md 条目 1。
"""
from __future__ import annotations

import subprocess
import sys
import threading
import types

import pytest

import ascendc_devkit.adapters.npu.detect as detect_mod
from ascendc_devkit.adapters.npu.detect import (
    EnvironmentProbeTimeout, _probe_chip_blocking, detect_chip_version)
from ascendc_devkit.domain import chip


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    """每个用例独立缓存（缓存是进程级模块全局，测试间必须隔离）。"""
    monkeypatch.setattr(detect_mod, "_PROBE_CACHE", None)


def _fake_completed(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["py", "-c", "..."], returncode=returncode,
                                       stdout=stdout, stderr="")


def _ensure_not_loaded(monkeypatch):
    monkeypatch.delitem(sys.modules, "torch_npu", raising=False)


class TestSubprocessRouting:
    def test_unloaded_routes_to_subprocess_and_stays_pure(self, monkeypatch):
        """主进程形态：torch_npu 未加载 → 子进程探测；探测后主进程仍未加载。"""
        _ensure_not_loaded(monkeypatch)
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return _fake_completed("A3\n")

        monkeypatch.setattr(detect_mod.subprocess, "run", fake_run)
        assert _probe_chip_blocking() == chip.A3
        assert len(calls) == 1
        assert "torch_npu" not in sys.modules, "子进程探测不得把 torch_npu 灌回本进程"

    def test_loaded_shortcircuits_inproc(self, monkeypatch):
        """子进程上下文形态：torch_npu 已加载 → 进程内直查，不 spawn 孙进程。"""
        mod = types.ModuleType("torch_npu")
        mod.npu = types.SimpleNamespace(
            device_count=lambda: 1, get_device_name=lambda _i: "Ascend910C")
        monkeypatch.setitem(sys.modules, "torch_npu", mod)

        def fail_run(*a, **kw):  # 短路路径绝不应触达 subprocess
            raise AssertionError("short-circuit path must not spawn a subprocess")

        monkeypatch.setattr(detect_mod.subprocess, "run", fail_run)
        assert _probe_chip_blocking() == chip.A3

    def test_subprocess_nonzero_exit_returns_unknown(self, monkeypatch):
        _ensure_not_loaded(monkeypatch)
        monkeypatch.setattr(detect_mod.subprocess, "run",
                            lambda *a, **kw: _fake_completed("", returncode=3))
        assert _probe_chip_blocking() == chip.UNKNOWN

    def test_subprocess_nonzero_exit_warns_stderr_tail(self, monkeypatch):
        """rc≠0 可观测性对齐超时路径：Logger.warn 附 stderr 尾部（[-300:]）再
        返回 UNKNOWN——探针自身失败不是「硬件无法识别」，须留痕可诊断。"""
        _ensure_not_loaded(monkeypatch)
        monkeypatch.setattr(
            detect_mod.subprocess, "run",
            lambda *a, **kw: subprocess.CompletedProcess(
                args=["py", "-c"], returncode=3, stdout="",
                stderr="E" * 500))
        warned: list[str] = []
        monkeypatch.setattr(detect_mod.Logger, "warn",
                            staticmethod(lambda msg: warned.append(msg)))
        assert _probe_chip_blocking() == chip.UNKNOWN
        assert warned and "rc=3" in warned[0] and "stderr" in warned[0]
        assert warned[0].endswith("E" * 300)  # 尾部截断 [-300:]

    def test_subprocess_garbage_stdout_returns_unknown(self, monkeypatch):
        _ensure_not_loaded(monkeypatch)
        monkeypatch.setattr(detect_mod.subprocess, "run",
                            lambda *a, **kw: _fake_completed("not-a-chip\n"))
        assert _probe_chip_blocking() == chip.UNKNOWN


class TestTimeoutSemantics:
    def test_subprocess_timeout_raises_probe_timeout(self, monkeypatch):
        """子进程超时 → EnvironmentProbeTimeout（驱动健康信号，不得吞成 UNKNOWN）。"""
        _ensure_not_loaded(monkeypatch)

        def hang(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd, timeout=kw.get("timeout", 1))

        monkeypatch.setattr(detect_mod.subprocess, "run", hang)
        with pytest.raises(EnvironmentProbeTimeout):
            _probe_chip_blocking(timeout_sec=1.0)

    def test_detect_version_translates_inner_timeout(self, monkeypatch):
        """detect_chip_version 对内层超时抛同型异常（对齐外层 join 超时路径）。"""
        _ensure_not_loaded(monkeypatch)

        def hang(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd, timeout=kw.get("timeout", 1))

        monkeypatch.setattr(detect_mod.subprocess, "run", hang)
        with pytest.raises(EnvironmentProbeTimeout):
            detect_chip_version(timeout_sec=2.0)

    def test_thread_overrun_timeout_preserved(self, monkeypatch):
        """旧语义回归：探线程超时（如驱动 ioctl 死等）仍抛 EnvironmentProbeTimeout。"""
        import time
        # 已加载 → 短路分支；stub inproc 探测体模拟 ioctl 死等（返回 UNKNOWN，
        # 不落缓存——避免僵尸线程在用例结束后回写模块全局污染后续用例）。
        monkeypatch.setitem(sys.modules, "torch_npu", types.ModuleType("torch_npu"))

        def slow_probe():
            time.sleep(1.0)
            return chip.UNKNOWN

        monkeypatch.setattr(detect_mod, "_probe_chip_inproc", slow_probe)
        with pytest.raises(EnvironmentProbeTimeout):
            detect_chip_version(timeout_sec=0.2)


class TestCache:
    def test_known_generation_cached(self, monkeypatch):
        _ensure_not_loaded(monkeypatch)
        calls = []
        monkeypatch.setattr(detect_mod.subprocess, "run",
                            lambda *a, **kw: (calls.append(1), _fake_completed("A2\n"))[1])
        assert _probe_chip_blocking() == chip.A2
        assert _probe_chip_blocking() == chip.A2
        assert len(calls) == 1, "已知代际应命中缓存，不重复探测"

    def test_unknown_not_cached(self, monkeypatch):
        _ensure_not_loaded(monkeypatch)
        calls = []
        monkeypatch.setattr(detect_mod.subprocess, "run",
                            lambda *a, **kw: (calls.append(1), _fake_completed(""))[1])
        assert _probe_chip_blocking() == chip.UNKNOWN
        assert _probe_chip_blocking() == chip.UNKNOWN
        assert len(calls) == 2, "UNKNOWN 不缓存，保持可重试"

    def test_concurrent_first_probe_spawns_once(self, monkeypatch):
        """双检锁：并发首探只 spawn 一个子进程（§1.15 单点，防批内三路并发探测）。"""
        _ensure_not_loaded(monkeypatch)
        calls = []

        def slow_run(cmd, **kw):
            import time
            time.sleep(0.3)  # 放宽竞态窗口：无锁实现会让三个线程都越过缓存检查
            calls.append(1)
            return _fake_completed("A5\n")

        monkeypatch.setattr(detect_mod.subprocess, "run", slow_run)
        start = threading.Barrier(3)
        results = [None] * 3

        def _call(i: int) -> None:
            start.wait(timeout=5)
            results[i] = _probe_chip_blocking()

        ths = [threading.Thread(target=_call, args=(i,)) for i in range(3)]
        for t in ths:
            t.start()
        for t in ths:
            t.join(timeout=10)
        assert results == [chip.A5] * 3
        assert len(calls) == 1
