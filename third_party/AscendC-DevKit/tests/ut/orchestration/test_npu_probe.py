"""UT for orchestration/npu_probe.py::healthy_cards — the single multi-card
health-probe policy authority (M1: batch_runner + dispatcher share this one
implementation; serial per-card P113 policy lives here).

§3.8 pure logic — the underlying L6 probe_device is mocked, no NPU dependency.
"""

from unittest import mock

from ascendc_devkit.domain.exceptions import EnvironmentNotAvailableError
from ascendc_devkit.orchestration.npu_probe import healthy_cards


class _EnvError(EnvironmentNotAvailableError):
    def __init__(self, stage_name="npu_probe", missing="NPU device"):
        super().__init__(stage_name=stage_name, missing=missing)


def _ok(card: int) -> mock.Mock:
    return mock.Mock(returncode=0, stdout="", stderr="")


class TestHealthyCards:
    def test_returns_all_healthy_in_order(self):
        """全部卡健康 → 原序返回全子集（batch_runner 卡池语义）。"""
        with mock.patch(
            "ascendc_devkit.orchestration.npu_probe.probe_device",
            side_effect=lambda card, timeout: None,
        ) as probe:
            assert healthy_cards([0, 1, 2, 3], 30.0) == [0, 1, 2, 3]
        assert [c.args[0] for c in probe.call_args_list] == [0, 1, 2, 3]

    def test_skips_failed_cards(self):
        """坏卡（probe_device raise EnvironmentNotAvailableError）被跳过。"""
        def probe(card, timeout):
            if card == 1:
                raise _EnvError(stage_name="npu_probe", missing="NPU device 1")
            return None

        with mock.patch(
            "ascendc_devkit.orchestration.npu_probe.probe_device", side_effect=probe,
        ) as m:
            assert healthy_cards([0, 1, 2], 30.0) == [0, 2]
        # 坏卡被探到后继续下一张（串行，不中断）
        assert [c.args[0] for c in m.call_args_list] == [0, 1, 2]

    def test_first_only_stops_at_first_healthy(self):
        """first_only=True 在首张健康卡处停止（dispatcher smoke「至少一张可用」语义）。"""
        def probe(card, timeout):
            if card in (0, 1):
                raise _EnvError(stage_name="npu_probe", missing="NPU device")
            return None

        with mock.patch(
            "ascendc_devkit.orchestration.npu_probe.probe_device", side_effect=probe,
        ) as m:
            assert healthy_cards([0, 1, 2, 3], 30.0, first_only=True) == [2]
        # 2 之后的卡不再探测
        assert [c.args[0] for c in m.call_args_list] == [0, 1, 2]

    def test_all_failed_returns_empty(self):
        """全卡不可用 → 空子集（调用方据此报 ConfigError / smoke fail，不静默）。"""
        def probe(card, timeout):
            raise _EnvError(stage_name="npu_probe", missing="NPU device")

        with mock.patch(
            "ascendc_devkit.orchestration.npu_probe.probe_device", side_effect=probe,
        ):
            assert healthy_cards([0, 1], 30.0) == []

    def test_empty_input_returns_empty_without_probe(self):
        """空卡表 → 空结果且不发起任何探测。"""
        with mock.patch(
            "ascendc_devkit.orchestration.npu_probe.probe_device",
        ) as m:
            assert healthy_cards([], 30.0) == []
        m.assert_not_called()
