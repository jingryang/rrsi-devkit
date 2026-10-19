#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Smoke tests for the KernelStaticCheck CLI."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

CLI_MODULE = [
    sys.executable,
    "-m",
    "KernelStaticCheck",
]

DIRECT_SCRIPT = [
    sys.executable,
    str(Path(__file__).resolve().parent.parent / "check_kernel.py"),
]


@pytest.fixture
def good_kernel(tmp_path: Path) -> Path:
    src = tmp_path / "good_kernel.cpp"
    src.write_text(
        '''
template <typename T>
__simd_vf__ inline void GoodVf(__ubuf__ T* dst, uint32_t n)
{
    for (uint16_t i = 0; i < n; ++i) {
        AscendC::Reg::Duplicate(dst, 0.0f);
    }
}
''',
        encoding="utf-8",
    )
    return src


@pytest.fixture
def bad_kernel(tmp_path: Path) -> Path:
    src = tmp_path / "bad_kernel.cpp"
    src.write_text(
        '''
template <typename T>
__simd_vf__ void BadVf(__ubuf__ T* dst, __ubuf__ T* src, uint32_t n)
{
}
''',
        encoding="utf-8",
    )
    return src


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        CLI_MODULE + list(args),
        capture_output=True,
        text=True,
    )


def run_direct_script(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        DIRECT_SCRIPT + list(args),
        capture_output=True,
        text=True,
    )


def test_cli_help():
    result = run_cli("--help")
    assert result.returncode == 0
    assert "KernelStaticCheck" in result.stdout


def test_cli_passes_on_good_kernel(good_kernel: Path):
    result = run_cli(str(good_kernel), "--kernel-name", "good_kernel")
    assert result.returncode == 0
    assert "PASS" in result.stdout


def test_cli_fails_on_bad_kernel(bad_kernel: Path):
    result = run_cli(str(bad_kernel), "--kernel-name", "bad_kernel")
    assert result.returncode == 1
    assert "FAIL" in result.stdout
    assert "simd_vf_modifiers" in result.stdout


def test_cli_no_strict_ignores_exit_code(bad_kernel: Path):
    result = run_cli(
        str(bad_kernel),
        "--kernel-name",
        "bad_kernel",
        "--no-strict",
    )
    assert result.returncode == 0


def test_cli_quiet_suppresses_output(bad_kernel: Path):
    result = run_cli(
        str(bad_kernel),
        "--kernel-name",
        "bad_kernel",
        "--quiet",
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == ""


def test_cli_json_format(good_kernel: Path):
    result = run_cli(
        str(good_kernel),
        "--kernel-name",
        "good_kernel",
        "--format",
        "json",
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert len(data) == 1
    assert data[0]["passed"]
    assert data[0]["file"] == str(good_kernel)


def test_cli_auto_detects_kernel_name(good_kernel: Path):
    src = good_kernel.parent / "detect.cpp"
    src.write_text(
        '''
template <typename T>
__simd_vf__ inline void GoodVf(__ubuf__ T* dst, uint32_t n)
{
    for (uint16_t i = 0; i < n; ++i) {
        AscendC::Reg::Duplicate(dst, 0.0f);
    }
}

extern "C" __global__ __aicore__ void my_custom_kernel(GM_ADDR x, GM_ADDR y, GM_ADDR tiling)
{
}
''',
        encoding="utf-8",
    )
    result = run_cli(str(src))
    assert result.returncode == 0
    data = json.loads(
        run_cli(str(src), "--format", "json").stdout
    )
    assert data[0]["detected_kernel_name"] == "my_custom_kernel"


def test_cli_recursive_scan(tmp_path: Path, good_kernel: Path, bad_kernel: Path):
    # Create a subdirectory with one source file.
    subdir = tmp_path / "sub"
    subdir.mkdir()
    (subdir / "another.cpp").write_text(good_kernel.read_text(), encoding="utf-8")

    result = run_cli(str(tmp_path), "--kernel-name", "kernel")
    assert result.returncode == 1
    assert "Summary:" in result.stdout
    assert "1 source file(s) failed." in result.stdout


def test_cli_no_source_files_prints_error(tmp_path: Path):
    result = run_cli(str(tmp_path))
    assert result.returncode == 1
    assert "No source files found" in result.stderr


def test_direct_script_runs_without_module_flag(good_kernel: Path):
    result = run_direct_script(
        str(good_kernel),
        "--kernel-name",
        "good_kernel",
    )
    assert result.returncode == 0
    assert "PASS" in result.stdout


def test_direct_script_fails_on_bad_kernel(bad_kernel: Path):
    result = run_direct_script(
        str(bad_kernel),
        "--kernel-name",
        "bad_kernel",
    )
    assert result.returncode == 1
    assert "FAIL" in result.stdout


def test_direct_script_help():
    result = run_direct_script("--help")
    assert result.returncode == 0
    assert "KernelStaticCheck" in result.stdout


def test_direct_script_json(good_kernel: Path):
    result = run_direct_script(
        str(good_kernel),
        "--kernel-name",
        "good_kernel",
        "--format",
        "json",
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data[0]["passed"]
