"""step 104 — infra/npu_smi 单点卡数探测测试（env 优先序 + npu-smi 子进程解析）。

语义钉住（docs/plan/dispatch-npu-probe-subprocess/02-impl.md 条目 2/2b）：
- env 两键同义、先到先用、坏值跳下一键；
- npu-smi 数**物理卡 = 数卡主行**（NPU 号+名字合并格；子行 Chip/Bus 天然排除）——
  review 整改实证（driver 25.5.1 真机输出对拍）：数子行在多芯卡上按芯数高估，
  旧脚本 grep 数子行"碰巧对"仅因当前单芯；
- 子进程缺失/失败/无可解析行 → None（调用方自持兜底，本模块不发明默认值）。
"""
from __future__ import annotations

import subprocess
from types import SimpleNamespace

import ascendc_devkit.infra.npu_smi as npu_smi_mod
from ascendc_devkit.infra.npu_smi import env_device_count, npu_smi_device_count

# 真机实样（driver 25.5.1，2026-08-29 抓取）：每卡两行——
# 主行 `| <NPU号> <Name> | Health | ...`（合并格），子行 `| <Chip号> | <Bus-Id> | ...`
# （Chip 号单芯恒 0——数子行去重会得 1，数子行不去重会高估多芯）。
_REAL_NPU_SMI_HEAD = """\
+------------------------------------------------------------------------------------------------+
| npu-smi 25.5.1                   Version: 25.5.1                                               |
+---------------------------+---------------+----------------------------------------------------+
| NPU   Name                | Health        | Power(W)    Temp(C)           Hugepages-Usage(page)|
| Chip                      | Bus-Id        | AICore(%)   Memory-Usage(MB)  HBM-Usage(MB)        |
+===========================+===============+====================================================+
| 0     910B3               | Alarm         | 100.5       46                0    / 0             |
| 0                         | 0000:C1:00.0  | 0           0    / 0          3438 / 65536         |
+===========================+===============+====================================================+
| 1     910B3               | OK            | 100.1       48                0    / 0             |
| 0                         | 0000:01:00.0  | 0           0    / 0          3426 / 65536         |
+===========================+===============+====================================================+
"""


def _fake_smi(monkeypatch, stdout: str):
    monkeypatch.setattr(npu_smi_mod.shutil, "which", lambda _n: "/usr/bin/npu-smi")
    monkeypatch.setattr(
        npu_smi_mod.subprocess, "run",
        lambda *a, **kw: SimpleNamespace(stdout=stdout, stderr=""))


class TestEnvDeviceCount:
    def test_npu_count_key(self, monkeypatch):
        monkeypatch.setenv("ASCEND_NPU_COUNT", "4")
        monkeypatch.delenv("ASCEND_DEVICE_NUM", raising=False)
        assert env_device_count() == 4

    def test_device_num_fallback_key(self, monkeypatch):
        monkeypatch.delenv("ASCEND_NPU_COUNT", raising=False)
        monkeypatch.setenv("ASCEND_DEVICE_NUM", "2")
        assert env_device_count() == 2

    def test_npu_count_wins_when_both(self, monkeypatch):
        monkeypatch.setenv("ASCEND_NPU_COUNT", "4")
        monkeypatch.setenv("ASCEND_DEVICE_NUM", "2")
        assert env_device_count() == 4

    def test_bad_value_falls_to_next_key(self, monkeypatch):
        monkeypatch.setenv("ASCEND_NPU_COUNT", "not-a-number")
        monkeypatch.setenv("ASCEND_DEVICE_NUM", "3")
        assert env_device_count() == 3

    def test_unset_returns_none(self, monkeypatch):
        monkeypatch.delenv("ASCEND_NPU_COUNT", raising=False)
        monkeypatch.delenv("ASCEND_DEVICE_NUM", raising=False)
        assert env_device_count() is None


class TestNpuSmiDeviceCount:
    def test_counts_card_main_rows_from_real_format(self, monkeypatch):
        """真机版式对拍：两卡（各一主行一子行）→ 2。

        回归锚点：旧实现数子行（Chip 号恒 0）去重得 1——真实输出上必错。
        """
        _fake_smi(monkeypatch, _REAL_NPU_SMI_HEAD)
        assert npu_smi_device_count() == 2

    def test_multichip_cards_not_overcounted(self, monkeypatch):
        """多芯卡（一卡两子行）：卡数仍按主行数=2，不按子行数=4 高估。"""
        _fake_smi(monkeypatch, _REAL_NPU_SMI_HEAD
                  + "| 0                         | 0000:C1:00.1  | 0           0    / 0   |\n"
                  + "+===========================+===============+========================+\n"
                  + "| 1     910B3               | OK            | 100.1       48          |\n"
                  + "| 0                         | 0000:01:00.1  | 0           0    / 0   |\n")
        assert npu_smi_device_count() == 2

    def test_no_bin_returns_none(self, monkeypatch):
        monkeypatch.setattr(npu_smi_mod.shutil, "which", lambda _n: None)
        assert npu_smi_device_count() is None

    def test_no_parseable_rows_returns_none(self, monkeypatch):
        _fake_smi(monkeypatch, "garbage output")
        assert npu_smi_device_count() is None

    def test_subprocess_failure_returns_none(self, monkeypatch):
        monkeypatch.setattr(npu_smi_mod.shutil, "which", lambda _n: "/usr/bin/npu-smi")

        def boom(*a, **kw):
            raise subprocess.TimeoutExpired(["npu-smi"], timeout=8)

        monkeypatch.setattr(npu_smi_mod.subprocess, "run", boom)
        assert npu_smi_device_count() is None
