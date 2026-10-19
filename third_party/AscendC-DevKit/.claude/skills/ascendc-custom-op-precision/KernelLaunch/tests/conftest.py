import os
import sys

import pytest
from unittest.mock import MagicMock, patch


def pytest_configure(config):
    config.addinivalue_line("markers", "npu: mark test as requiring an Ascend NPU")


def pytest_addoption(parser):
    parser.addoption(
        "--device-id",
        action="store",
        default="0",
        help="Ascend NPU device id for integration tests (default: 0)",
    )


@pytest.fixture
def device_id(request):
    return int(request.config.getoption("--device-id"))


@pytest.fixture
def mock_ttk_env(tmp_path, monkeypatch):
    """Mock TTK environment so KernelLauncher can be unit-tested without NPU."""
    mock_sw = MagicMock()
    mock_sw.dev_plat = "Ascend950DT_9582"
    mock_sw.short_soc_version = "Ascend950"
    mock_sw.compile_options = {}

    # Redirect cwd to tmp_path so kernel_meta dirs don't pollute the repo.
    monkeypatch.chdir(tmp_path)

    with patch("KernelLaunch.launcher.get_global_storage", return_value=mock_sw), \
         patch("KernelLaunch.launcher.set_global_storage"), \
         patch("KernelLaunch.launcher.get_npu_hw_info", return_value={"short_soc_version": "Ascend950"}), \
         patch("KernelLaunch.launcher.os.makedirs"):
        yield mock_sw
