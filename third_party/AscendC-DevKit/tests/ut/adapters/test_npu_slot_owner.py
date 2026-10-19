"""step-95 — slot owner 归因（acquire 记 owner，等待/超时/死卡告警可归因）。

L4 改动1（docs/plan/npu-card-lease-lifecycle/03-impl.md）：99c4c0 批 8 卡租约
泄漏时 `_acquired` 是无主 set，等待者只知「池空」不知「谁持有」。本套守护：
  - owner 记录（auto + hard-pin）与释放清除；
  - 等待分支日志含 holders（进入等待时一次，不逐 poll 刷屏）；
  - CardAcquireTimeout 消息带 holders（诊断随失败走）；
  - 死卡告警含 owner；
  - acquire_context owner 透传。
"""
from __future__ import annotations

import logging

import pytest

from ascendc_devkit.adapters.npu.slot import NPUSlotManager
from ascendc_devkit.domain.exceptions import CardAcquireTimeout


class TestOwnerRecording:
    def test_auto_acquire_records_owner(self):
        pool = NPUSlotManager(max_devices=4, allowed=[0, 1])
        pool.acquire(owner="unique/precision_debug")
        assert pool.acquired_holders() == {0: "unique/precision_debug"}

    def test_hardpin_records_owner(self):
        pool = NPUSlotManager(max_devices=4, allowed=[0, 1])
        pool.acquire(npu_id=1, owner="gelu/diagnose")
        assert pool.acquired_holders() == {1: "gelu/diagnose"}

    def test_release_clears_owner(self):
        pool = NPUSlotManager(max_devices=4, allowed=[0, 1])
        card = pool.acquire(owner="moe/precision_debug")
        pool.release(card)
        assert pool.acquired_holders() == {}
        assert pool.list_acquired() == []

    def test_default_owner_empty_label(self):
        pool = NPUSlotManager(max_devices=4, allowed=[0, 1])
        pool.acquire()
        assert pool.acquired_holders() == {0: ""}

    def test_acquire_context_passes_owner(self):
        pool = NPUSlotManager(max_devices=4, allowed=[0, 1])
        with pool.acquire_context(owner="op/cannbench_eval") as card:
            assert pool.acquired_holders() == {card: "op/cannbench_eval"}
        assert pool.acquired_holders() == {}


class TestWaitAttribution:
    def test_wait_log_carries_holders(self, caplog):
        pool = NPUSlotManager(max_devices=4, allowed=[0, 1])
        pool.acquire(owner="gelu/diagnose")
        pool.acquire(owner="unique/precision_debug")
        with caplog.at_level(logging.INFO, logger="ascendc_devkit.adapters.npu.slot"):
            with pytest.raises(CardAcquireTimeout):
                pool.acquire(timeout=0.05, owner="moe/precision_debug")
        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert "waiting for NPU card" in joined
        assert "gelu/diagnose" in joined and "unique/precision_debug" in joined

    def test_timeout_message_carries_holders(self):
        pool = NPUSlotManager(max_devices=2, allowed=[0])
        pool.acquire(owner="holder/stage")
        with pytest.raises(CardAcquireTimeout) as ei:
            pool.acquire(timeout=0.01)
        assert "holder/stage" in str(ei.value)


class TestDeadCardWarning:
    def test_dead_card_warning_names_owner(self, caplog):
        pool = NPUSlotManager(max_devices=2, allowed=[0],
                              lease_warn_threshold=0.0)
        pool.acquire(owner="leaky/stage")
        with caplog.at_level(logging.WARNING,
                             logger="ascendc_devkit.adapters.npu.slot"):
            with pytest.raises(CardAcquireTimeout):
                pool.acquire(timeout=0.01)
        warnings = [r.getMessage() for r in caplog.records
                    if r.levelno == logging.WARNING and "held for" in r.getMessage()]
        assert warnings and "leaky/stage" in warnings[0]


# —— step 104 — 卡数兜底去 torch_npu（主进程纯 Python 不变式）———————————————

class TestDetectDeviceCountNoTorchNpu:
    """优先序 env → npu-smi 子进程 → 默认 8；全程不得 import torch_npu。

    语义声明（docs/plan/dispatch-npu-probe-subprocess/02-impl.md 条目 2）：
    npu-smi 数物理卡（原 torch_npu.device_count() 数 VISIBLE_DEVICES 过滤后
    的可见卡）；受限可见性场景必须显式声明 env。
    """

    def test_env_wins(self, monkeypatch):
        import ascendc_devkit.adapters.npu.slot as slot_mod
        monkeypatch.setenv("ASCEND_NPU_COUNT", "4")
        called = []
        import ascendc_devkit.infra.npu_smi as smi_mod
        monkeypatch.setattr(smi_mod, "npu_smi_device_count",
                            lambda: (called.append(1), None)[1])
        assert slot_mod.NPUSlotManager._detect_device_count() == 4
        assert not called, "env 已声明时不得触达 npu-smi"

    def test_smi_fallback(self, monkeypatch):
        import ascendc_devkit.adapters.npu.slot as slot_mod
        monkeypatch.delenv("ASCEND_NPU_COUNT", raising=False)
        monkeypatch.delenv("ASCEND_DEVICE_NUM", raising=False)
        import ascendc_devkit.infra.npu_smi as smi_mod
        monkeypatch.setattr(smi_mod, "npu_smi_device_count", lambda: 6)
        assert slot_mod.NPUSlotManager._detect_device_count() == 6

    def test_default_8_when_both_unavailable(self, monkeypatch):
        import ascendc_devkit.adapters.npu.slot as slot_mod
        monkeypatch.delenv("ASCEND_NPU_COUNT", raising=False)
        monkeypatch.delenv("ASCEND_DEVICE_NUM", raising=False)
        import ascendc_devkit.infra.npu_smi as smi_mod
        monkeypatch.setattr(smi_mod, "npu_smi_device_count", lambda: None)
        assert slot_mod.NPUSlotManager._detect_device_count() == 8

    def test_never_imports_torch_npu(self, monkeypatch):
        """兜底全程零 torch_npu import（主进程纯度，方案核心断言）。

        本 pytest 环境有插件在启动期预载 torch_npu（与被测代码无关），故先
        摘除再断言"本轮调用没有把它带回来"——测的是被测路径，非整个会话。
        """
        import sys
        import ascendc_devkit.adapters.npu.slot as slot_mod
        monkeypatch.delitem(sys.modules, "torch_npu", raising=False)
        monkeypatch.delenv("ASCEND_NPU_COUNT", raising=False)
        monkeypatch.delenv("ASCEND_DEVICE_NUM", raising=False)
        import ascendc_devkit.infra.npu_smi as smi_mod
        monkeypatch.setattr(smi_mod, "npu_smi_device_count", lambda: None)
        slot_mod.NPUSlotManager._detect_device_count()
        assert "torch_npu" not in sys.modules
