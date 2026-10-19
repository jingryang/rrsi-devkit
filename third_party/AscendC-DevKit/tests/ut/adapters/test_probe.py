"""UT for adapters.npu.probe.probe_device — per-card open-device health probe.

Probe 在 stage 把长 subprocess（kernel_eval / precision run）交给某张卡之前，验证
该卡真能 open device context（set_device + alloc）。捕获驱动级 device-context pool
耗尽（507033 / TsdOpen failed / device retain error）——这是 in-memory card pool
（slot.py）结构性看不见的：一张卡在 Python 记账里"空闲"，但子进程 zombie 泄漏后
驱动侧可能已开不了（run 20260727-144633-2a1db8 末尾 cannbench_eval 被 507033 吞成
LOSS 的根因）。

失败 raise EnvironmentNotAvailableError（控制流异常 → dispatcher halt + 保留产物；
§3.7 诚实报错），非 RuntimeError——设备不可用是环境前置条件，非算子缺陷。
不依赖真实 NPU（mock OS 边界 subprocess.run），确定性、毫秒级 → 不标 npu。
"""

import subprocess
from unittest import mock

import pytest

from ascendc_devkit.adapters.npu.probe import probe_device
from ascendc_devkit.domain.exceptions import EnvironmentNotAvailableError


def _ok() -> mock.Mock:
    return mock.Mock(returncode=0, stdout="", stderr="")


def _fail(rc: int = 1,
          stderr: str = "open device 0 failed, runtime result = 507033") -> mock.Mock:
    return mock.Mock(returncode=rc, stdout="", stderr=stderr)


class TestProbeDevice:
    def test_passes_silently_on_zero_exit(self):
        with mock.patch(
            "ascendc_devkit.adapters.npu.probe.subprocess.run", return_value=_ok()
        ):
            assert probe_device(0) is None  # 不 raise

    def test_nonzero_exit_raises_env_error(self):
        with mock.patch(
            "ascendc_devkit.adapters.npu.probe.subprocess.run", return_value=_fail()
        ):
            with pytest.raises(EnvironmentNotAvailableError) as ei:
                probe_device(3)
        assert "device 3" in str(ei.value)  # 含卡号（可定位）
        assert ei.value.help_hint  # 留下诊断信号（§1.2 可诊断）

    def test_timeout_raises_env_error(self):
        with mock.patch(
            "ascendc_devkit.adapters.npu.probe.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="python", timeout=60),
        ):
            with pytest.raises(EnvironmentNotAvailableError) as ei:
                probe_device(0, timeout=60)
        msg = str(ei.value).lower()
        assert "timed out" in msg  # hang（context 耗尽时 open device 可能挂起）

    def test_script_targets_probed_card(self):
        """探活脚本 set_device({card}) —— 卡号进脚本（非写死 0）。"""
        with mock.patch(
            "ascendc_devkit.adapters.npu.probe.subprocess.run", return_value=_ok()
        ) as mrun:
            probe_device(5)
        script = mrun.call_args.args[0][2]  # ["python", "-c", <script>]
        assert "set_device(5)" in script

    def test_propagates_caller_env(self):
        """探活复用调用方 env（autoload=0 / PYTHONPATH 等），走与真实 eval 同一条
        open-device 路径——不裸用 os.environ（会掩盖autoload/usercustomize 注入的故障）。"""
        env = {"TORCH_DEVICE_BACKEND_AUTOLOAD": "0", "PYTHONPATH": "/x"}
        with mock.patch(
            "ascendc_devkit.adapters.npu.probe.subprocess.run", return_value=_ok()
        ) as mrun:
            probe_device(0, env=env)
        assert mrun.call_args.kwargs["env"] is env

    def test_stage_name_attributable(self):
        """stage_name 由调用方指定（默认 npu_probe），halt 时定位是哪个 stage 探活失败。"""
        with mock.patch(
            "ascendc_devkit.adapters.npu.probe.subprocess.run", return_value=_fail()
        ):
            with pytest.raises(EnvironmentNotAvailableError) as ei:
                probe_device(0, stage_name="cannbench_eval")
        assert ei.value.stage_name == "cannbench_eval"
