#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Device information query for Ascend NPU, similar to pycuda.driver.Device.
"""

from typing import Optional, Tuple

from ttk.core_modules.dsmi import DSMIInterface
from ttk.utilities.platform import get_npu_hw_info


class DeviceInfo:
    """Query Ascend NPU hardware information."""

    def __init__(self):
        self._dsmi = DSMIInterface()

    @property
    def device_count(self) -> int:
        """Return the number of available Ascend devices."""
        return self._dsmi.get_device_count()

    def list_logical_device_ids(self) -> Tuple[int, ...]:
        """Return all logical device IDs."""
        return self._dsmi.list_logical_device_id()

    def get_soc_version(self, device_id: int = 0) -> str:
        """Return the full SoC version (e.g. 'Ascend910B3')."""
        chip_info = self._dsmi.get_chip_info(device_id)
        if chip_info is None:
            raise RuntimeError(f"Failed to get chip info for device {device_id}")
        return chip_info.get_complete_platform()

    def get_short_soc_version(self, device_id: int = 0) -> str:
        """Return the short SoC version (e.g. 'Ascend910B')."""
        full_soc = self.get_soc_version(device_id)
        hw_info = get_npu_hw_info(full_soc)
        return hw_info.get("short_soc_version", full_soc)

    def get_device_health(self, device_id: int = 0) -> str:
        """Return device health state."""
        state = self._dsmi.get_device_health_state(device_id)
        return state.name if hasattr(state, "name") else str(state)

    def get_memory_info(self, device_id: int = 0):
        """Return device memory info."""
        return self._dsmi.get_memory_info(device_id)

    def get_hbm_info(self, device_id: int = 0):
        """Return device HBM info."""
        return self._dsmi.get_hbm_info(device_id)

    def get_temperature(self, device_id: int = 0) -> Optional[int]:
        """Return device temperature in Celsius."""
        return self._dsmi.get_device_temperature(device_id)

    def get_utilization(self, device_id: int = 0, device_type: int = 2) -> Optional[int]:
        """Return device utilization percentage.

        device_type: 1=MEMORY, 2=AICORE, 3=AICPU, 4=CTRLCPU, 5=BUS,
                     6=HBM, 8=DDR, 10=HBM_BANDWIDTH, 12=VECCORE
        """
        full_soc = self.get_soc_version(device_id)
        return self._dsmi.get_device_util(device_id, device_type, full_soc)

    def get_frequency(self, device_id: int = 0, device_type: int = 7) -> Optional[int]:
        """Return device frequency in MHz.

        device_type: 1=MEMORY, 2=CTRLCPU, 6=HBM, 7=AICORE_CURRENT,
                     9=AICORE_RATED, 12=VECCORE_CURRENT
        """
        full_soc = self.get_soc_version(device_id)
        return self._dsmi.get_device_frequency(device_id, device_type, full_soc)

    def get_hw_info(self, device_id: int = 0) -> dict:
        """Return comprehensive hardware info dict."""
        full_soc = self.get_soc_version(device_id)
        return get_npu_hw_info(full_soc)

    def __repr__(self):
        count = self.device_count
        if count == 0:
            return "DeviceInfo(no devices found)"
        ids = self.list_logical_device_ids()
        lines = [f"DeviceInfo({count} device(s))"]
        for dev_id in ids:
            try:
                soc = self.get_soc_version(dev_id)
                health = self.get_device_health(dev_id)
                temp = self.get_temperature(dev_id)
                temp_str = f"{temp}C" if temp is not None else "N/A"
                lines.append(f"  [{dev_id}] {soc} | Health:{health} | Temp:{temp_str}")
            except Exception as e:
                lines.append(f"  [{dev_id}] Error: {e}")
        return "\n".join(lines)
