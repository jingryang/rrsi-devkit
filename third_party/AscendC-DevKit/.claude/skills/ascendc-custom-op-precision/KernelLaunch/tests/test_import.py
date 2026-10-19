import pytest


def test_import_kernel_launch():
    from KernelLaunch import KernelLauncher, setup_log_separation
    assert callable(KernelLauncher)
    assert callable(setup_log_separation)


def test_kernel_launcher_default_args():
    """KernelLauncher should not accept compile_mode after dynamic compile removal."""
    from KernelLaunch import KernelLauncher
    with pytest.raises(TypeError):
        KernelLauncher("add", compile_mode="dynamic")
