"""step-106 — perf 第五向量收口 + NPURunner probe-free 通路 UT。

钉住 docs/plan/dispatch-npu-probe-subprocess/02-impl.md（第五向量收口节）：
- ``NPURunner.__init__`` 构造期探测在进程内 import torch/torch_npu——主进程
  构造一律走 ``probe_free``（探测字段 None=未知，设备真值源=子进程 harness）；
- ``execute`` 可用性闸门：False=探测实证不可用→诚实报缺；None=probe-free→跳过
  （主进程无权裁决设备可用性）；
- perf ``_check_npu_available`` 走 L3 子进程探测单点（不再 ``except Exception``
  吞错——那会连纯度守卫错误一起静默折成 False，§1.2 最恶劣形态）；
- dispatcher smoke 与 perf gate 收敛至同一单点
  ``orchestration/npu_probe.npu_runtime_available``（子进程数卡 + healthy_cards
  first_only；原 ``infra/npu_probe`` NPURunner 冒烟实现已删，§1.15 单通路）。
"""
from __future__ import annotations

import pytest

import ascendc_devkit.orchestration.stages.perf as perf_mod
from ascendc_devkit.adapters.npu.runner import NPURunner


@pytest.fixture(autouse=True)
def _fresh_perf_probe_cache(monkeypatch):
    """perf 可用性缓存是进程级模块全局——用例间隔离（fake 探测结果每例不同）。"""
    monkeypatch.setattr(perf_mod, "_NPU_AVAILABLE_CACHE", None)


class TestProbeFreeConstruction:
    def test_probe_free_no_env_probe(self):
        """probe-free 构造不触发 _check_environment（不 import torch）。"""
        runner = NPURunner.probe_free(chip_version="A3")
        assert runner._chip_version == "A3"
        # None = 未知（不是 False——False 表示探测实证不可用）
        assert runner._torch_npu_available is None
        assert runner._device_count is None
        assert runner._env_info["probe"] == "probe-free"

    def test_probe_free_no_chip_stays_none_and_loud(self):
        """M5：空 chip 不再静默缺省 A2（detect「never a silent A2 guess」不变式）
        ——保持 None 传入，真正需要 soc_version 时由 _soc_version 响亮报错。"""
        runner = NPURunner.probe_free()
        assert runner._chip_version is None
        with pytest.raises(RuntimeError, match="soc_version"):
            runner._soc_version()

    def test_execute_gate_false_raises(self):
        """探测实证不可用（False）→ 诚实报缺（§3.7）。"""
        from ascendc_devkit.domain.exceptions import EnvironmentNotAvailableError
        runner = NPURunner.probe_free()
        runner._torch_npu_available = False
        with pytest.raises(EnvironmentNotAvailableError, match="NPU runtime"):
            runner.execute(_op(), _cases(), 0, deploy_result=None)

    def test_execute_gate_none_skips(self):
        """probe-free（None）→ 跳过闸门（主进程不裁决；子进程 harness 是真值源）。"""
        runner = NPURunner.probe_free()
        # execute 会继续往下走（deploy 产物检查等后续闸门），此处验证 torch_npu
        # 闸门不再拦截：直接构造调用会因缺 deploy 产物报 EnvironmentNotAvailable，
        # 报缺文案必须是 deploy 侧而非 NPU runtime 侧。
        from ascendc_devkit.domain.exceptions import EnvironmentNotAvailableError
        with pytest.raises(EnvironmentNotAvailableError) as ei:
            runner.execute(
                _op(), _cases(), 0, deploy_result=None)
        assert "deploy artifacts" in str(ei.value), \
            f"probe-free 不得被 NPU runtime 闸门拦住: {ei.value}"

    def test_full_init_still_probes(self):
        """正常 __init__ 构造仍探测（子进程调用方语义不变）——非 probe-free
        构造路径不受影响。探测结果取决于宿主环境（有 torch_npu=True/无=False），
        只断言"探测发生过且产出布尔真值"，不对环境做假设（§3.5 真实依赖）。"""
        runner = NPURunner(chip_version="A3")
        assert runner._chip_version == "A3"
        assert isinstance(runner._torch_npu_available, bool)
        assert runner._env_info.get("torch_available") is not None


def _gate_raises(runner):
    runner.execute(_op(), _cases(), 0, deploy_result=None)


def _op():
    from ascendc_devkit.domain.operator import OperatorSpec
    return OperatorSpec(name="t")


def _cases():
    from types import SimpleNamespace
    return [SimpleNamespace(name="c", inputs=[{"shape": [4], "dtype": "fp16"}],
                            attrs={}, expected={})]


class TestPerfAvailabilityProbe:
    def test_check_npu_available_delegates_subprocess(self, monkeypatch):
        """perf 可用性检查走 infra 子进程单点（不再进程内构造 NPURunner）。"""
        import ascendc_devkit.orchestration.npu_probe as probe_mod
        called = {}
        def _fake_probe(timeout_sec=60.0):
            called["hit"] = True
            return (True, "ok")
        monkeypatch.setattr(
            probe_mod, "npu_runtime_available", _fake_probe)
        stage = perf_mod.PerfStage()
        assert stage._check_npu_available() is True
        assert called.get("hit") is True

    def test_unavailable_logs_reason(self, monkeypatch):
        """不可用：reason 必须进日志（不再静默 except 折成 False）。"""
        import ascendc_devkit.orchestration.npu_probe as probe_mod
        monkeypatch.setattr(
            probe_mod, "npu_runtime_available",
            lambda timeout_sec=60.0: (False, "smoke 异常（exit 3）\nTraceback..."))
        assert perf_mod.PerfStage()._check_npu_available() is False

    def test_probe_cached_once_per_process(self, monkeypatch):
        """M6：探测结果进程级缓存——同一进程内第二次调用不再 spawn 子进程。"""
        import ascendc_devkit.orchestration.npu_probe as probe_mod
        calls = []
        def _fake_probe(timeout_sec=60.0):
            calls.append(1)
            return (True, "ok")
        monkeypatch.setattr(probe_mod, "npu_runtime_available", _fake_probe)
        stage = perf_mod.PerfStage()
        assert stage._check_npu_available() is True
        assert stage._check_npu_available() is True
        assert len(calls) == 1


class TestDispatcherProbeConverged:
    def test_runtime_probe_delegates_single_point(self, monkeypatch):
        """dispatcher 启动 smoke 是 L3 runtime_probe 薄包装——与 perf gate、
        batch_runner 卡池过滤共用 ``orchestration/npu_probe``（§1.15 同一通路），
        不得在 runtime_probe 层重写探测逻辑。mock 单点边界（不碰真机），断言
        透传 timeout 与返回值。"""
        import ascendc_devkit.orchestration.runtime_probe as rp_mod
        import ascendc_devkit.orchestration.npu_probe as probe_mod

        seen: dict = {}

        def _fake_probe(timeout_sec=120.0):
            seen["timeout_sec"] = timeout_sec
            return (True, "ok (healthy cards: 3)")

        monkeypatch.setattr(probe_mod, "npu_runtime_available", _fake_probe)
        ok, reason = rp_mod._run_npu_smoke_subprocess(120.0)
        assert (ok, reason) == (True, "ok (healthy cards: 3)")
        assert seen["timeout_sec"] == 120.0


class TestNpuProbeSubprocess:
    """L3 单点 ``orchestration/npu_probe.npu_runtime_available`` 的子进程契约。"""

    def _probe_code(self, monkeypatch, fake_run) -> str:
        import ascendc_devkit.orchestration.npu_probe as probe_mod
        seen: dict = {}

        def _run(argv, **kwargs):
            seen["code"] = argv[-1]
            return fake_run(argv)

        monkeypatch.setattr(probe_mod.subprocess, "run", _run)
        return probe_mod, seen

    def test_code_uses_healthy_cards_not_runner(self, monkeypatch):
        """探针代码必须复用 ``healthy_cards`` 单点（P113 串行逐卡），且**不构造
        NPURunner**——可用性判定是纯卡健康语义，不得混入框架 runner 构造
        （原 infra 实现的形态，已删）。"""
        import subprocess as sp
        probe_mod, seen = self._probe_code(
            monkeypatch,
            lambda argv: sp.CompletedProcess(argv, 0, stdout="HEALTHY_CARDS=0\n", stderr=""))
        ok, reason = probe_mod.npu_runtime_available()
        assert ok is True and "healthy cards: 0" in reason
        assert ("from ascendc_devkit.orchestration.npu_probe import healthy_cards"
                in seen["code"]), "探针须复用 healthy_cards 单点"
        assert "NPURunner" not in seen["code"], "探针不得构造 NPURunner"

    def test_timeout_returns_diagnostic_reason(self, monkeypatch):
        import subprocess as sp
        import ascendc_devkit.orchestration.npu_probe as probe_mod

        def boom(*a, **kw):
            raise sp.TimeoutExpired(cmd=["x"], timeout=5)
        monkeypatch.setattr(probe_mod.subprocess, "run", boom)
        ok, reason = probe_mod.npu_runtime_available(timeout_sec=5)
        assert ok is False and "超时" in reason and "driver hang" in reason

    def test_unavailable_returns_reason(self, monkeypatch):
        from types import SimpleNamespace
        import ascendc_devkit.orchestration.npu_probe as probe_mod
        monkeypatch.setattr(
            probe_mod.subprocess, "run",
            lambda *a, **kw: SimpleNamespace(returncode=2, stderr="", stdout=""))
        ok, reason = probe_mod.npu_runtime_available()
        assert ok is False and "全部 NPU 卡不可用" in reason

    def test_exception_carries_traceback(self, monkeypatch):
        from types import SimpleNamespace
        import ascendc_devkit.orchestration.npu_probe as probe_mod
        monkeypatch.setattr(
            probe_mod.subprocess, "run",
            lambda *a, **kw: SimpleNamespace(
                returncode=3, stderr="Traceback (most recent call last): boom", stdout=""))
        ok, reason = probe_mod.npu_runtime_available()
        assert ok is False and "Traceback" in reason
