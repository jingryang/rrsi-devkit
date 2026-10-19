"""Unit tests for KernelLaunch that do not require an NPU device.

These tests mock the TTK environment and exercise the KernelLauncher API
surface (construction, input/output setup, testcase building, context
management, etc.).
"""

import numpy as np
import pytest
from unittest.mock import MagicMock, patch

from KernelLaunch import KernelLauncher


class TestConstruction:
    def test_kernel_meta_property(self, mock_ttk_env):
        launcher = KernelLauncher("add", kernel_meta="/tmp/kl_test")
        assert launcher.kernel_meta == "/tmp/kl_test/add"

    def test_for_case_factory(self, mock_ttk_env):
        launcher = KernelLauncher.for_case("add", case_label="unit")
        assert launcher._op_name == "add"
        assert launcher.kernel_meta.startswith("kernel_meta_add_unit_")


class TestInputOutputSetup:
    def test_set_input_numpy(self, mock_ttk_env):
        launcher = KernelLauncher("add")
        arr = np.array([1.0, 2.0])
        launcher.set_input(0, arr)
        assert launcher._inputs[0] is arr

    def test_set_input_dtype_override(self, mock_ttk_env):
        launcher = KernelLauncher("add")
        arr = np.array([1.0, 2.0], dtype=np.float32)
        launcher.set_input(0, arr, dtype_override="float16")
        assert launcher._input_dtype_overrides[0] == "float16"

    def test_set_output(self, mock_ttk_env):
        launcher = KernelLauncher("add")
        launcher.set_output(0, (2, 3), dtype=np.float32)
        assert launcher._output_specs[0] == {"shape": (2, 3), "dtype": "float32"}

    def test_set_attr(self, mock_ttk_env):
        launcher = KernelLauncher("add")
        launcher.set_attr(0, 1e-5)
        assert launcher._attrs[0] == 1e-5


class TestBuildTestcase:
    def test_build_testcase_shapes_and_dtypes(self, mock_ttk_env):
        launcher = KernelLauncher("add")
        launcher.set_input(0, np.zeros((2, 3), dtype=np.float16))
        launcher.set_input(1, np.ones((2, 3), dtype=np.float16))
        launcher.set_output(0, (2, 3), dtype=np.float16)

        with patch("KernelLaunch.launcher.OpInfoKeeper") as MockKeeper, \
             patch("ttk.core_modules.operator.op_info_keeper.OpInfoKeeper") as MockKeeperTc:
            MockKeeper.return_value.op_output_defined.return_value = False
            MockKeeper.return_value.info_of.return_value = {}
            MockKeeperTc.return_value.info_of.return_value = {}
            tc = launcher._build_testcase()

        assert tc.op_name == "add"
        assert tc.input_shapes == ((2, 3), (2, 3))
        assert tc.input_dtypes == ("float16", "float16")
        assert tc.output_shapes == ((2, 3),)
        assert tc.output_dtypes == ("float16",)
        assert tc.input_formats == ("ND", "ND")

    def test_build_testcase_with_attrs(self, mock_ttk_env):
        launcher = KernelLauncher("add")
        launcher.set_input(0, np.zeros((2,), dtype=np.float32))
        launcher.set_output(0, (2,), dtype=np.float32)
        launcher.set_attr(0, 42)

        with patch("KernelLaunch.launcher.OpInfoKeeper") as MockKeeper, \
             patch("ttk.core_modules.operator.op_info_keeper.OpInfoKeeper") as MockKeeperTc:
            MockKeeper.return_value.op_output_defined.return_value = False
            MockKeeper.return_value.info_of.return_value = {
                "attr": [{"name": "scale"}]
            }
            MockKeeperTc.return_value.info_of.return_value = {
                "inputs": [{"name": "x"}],
                "outputs": [{"name": "y"}],
                "attr": [{"name": "scale"}],
            }
            tc = launcher._build_testcase()

        assert tc.attributes == {"scale": 42}


class TestLifecycle:
    def test_context_manager_closes_device(self, mock_ttk_env):
        launcher = KernelLauncher("add")
        mock_device = MagicMock()
        launcher._device = mock_device

        with launcher as ctx:
            assert ctx is launcher

        mock_device.reset.assert_called_once()
        assert launcher._device is None

    def test_close_is_idempotent(self, mock_ttk_env):
        launcher = KernelLauncher("add")
        mock_device = MagicMock()
        mock_device.reset.side_effect = RuntimeError("already closed")
        launcher._device = mock_device

        # Should not raise even though reset raises.
        launcher.close()
        launcher.close()

    def test_show_op_info(self, mock_ttk_env, capsys):
        launcher = KernelLauncher("add")
        with patch("KernelLaunch.launcher.OpInfoKeeper") as MockKeeper:
            MockKeeper.return_value.info_of.return_value = {
                "inputs": [{"name": "x", "dtype": ["float32"], "format": ["ND"]}],
                "outputs": [{"name": "y", "dtype": ["float32"], "format": ["ND"]}],
                "attr": [{"name": "epsilon", "type": "float", "defaultValue": "1e-5"}],
            }
            MockKeeper.return_value.op_type_of.return_value = "Add"
            launcher.show_op_info()

        captured = capsys.readouterr()
        assert "Operator: add" in captured.out
        assert "epsilon" in captured.out
