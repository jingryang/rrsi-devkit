#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Regression tests for conditional kernel-artifact reuse.

A SourceModule constructed with the same source + dump flag + core_type +
platform as the last SUCCESSFUL compile must reuse the cached binary (no
delete/reset dance and no needless recompilation per construction). Only a
changed source, changed dump flag, changed core_type / platform, or a
missing/prior-failed binary triggers a fresh build (S4/S5).
"""

import pathlib

from SingleOperatorLaunch.source_module import (
    _fresh_kernel_artifacts,
    _write_cache_marker,
)

_DUMP = True
_CORE = "VectorCore"
_PLAT = "Ascend950"


def _touch(meta: pathlib.Path, kernel_name: str, *exts):
    for ext in exts:
        (meta / (kernel_name + ext)).write_text(ext, encoding="UTF-8")


def _record_success(meta, kernel_name, src, dump=_DUMP, core=_CORE, plat=_PLAT):
    """Simulate a finished successful compile: artifacts on disk + cache marker."""
    _touch(meta, kernel_name, ".o", ".json", ".cce")
    _write_cache_marker(meta, kernel_name, src, dump, core, plat)


def test_first_build_is_fresh(tmp_path):
    assert _fresh_kernel_artifacts(tmp_path, "k", "int f(){return 0;}",
                                   _DUMP, _CORE, _PLAT) is False


def test_same_source_and_dump_reuse_artifacts(tmp_path):
    src = "int f(){return 0;}"
    assert _fresh_kernel_artifacts(tmp_path, "k", src, _DUMP, _CORE, _PLAT) is False
    _record_success(tmp_path, "k", src)
    assert _fresh_kernel_artifacts(tmp_path, "k", src, _DUMP, _CORE, _PLAT) is True
    # artifacts left untouched
    assert (tmp_path / "k.o").exists()


def test_changed_dump_trigger_fresh_build(tmp_path):
    src = "int f(){return 0;}"
    assert _fresh_kernel_artifacts(tmp_path, "k", src, _DUMP, _CORE, _PLAT) is False
    _record_success(tmp_path, "k", src)
    # dump flag flipped -> stale binary must be removed
    assert _fresh_kernel_artifacts(tmp_path, "k", src, False, _CORE, _PLAT) is False
    assert not (tmp_path / "k.o").exists()


def test_changed_source_trigger_fresh_build(tmp_path):
    assert _fresh_kernel_artifacts(tmp_path, "k", "int f(){return 0;}",
                                   _DUMP, _CORE, _PLAT) is False
    _record_success(tmp_path, "k", "int f(){return 0;}")
    assert _fresh_kernel_artifacts(tmp_path, "k", "int f(){return 1;}",
                                   _DUMP, _CORE, _PLAT) is False
    assert not (tmp_path / "k.o").exists()


def test_changed_core_type_trigger_fresh_build(tmp_path):
    """S4: core_type changes the compiled binary (ELF magic / ktype / mix flag)
    — a different core_type must NOT reuse the cached .o."""
    src = "int f(){return 0;}"
    assert _fresh_kernel_artifacts(tmp_path, "k", src, _DUMP, _CORE, _PLAT) is False
    _record_success(tmp_path, "k", src)
    assert _fresh_kernel_artifacts(tmp_path, "k", src, _DUMP, "AiCore", _PLAT) is False
    assert not (tmp_path / "k.o").exists()


def test_changed_platform_trigger_fresh_build(tmp_path):
    """S4: platform (target SoC) changes the compiled binary — must not reuse."""
    src = "int f(){return 0;}"
    assert _fresh_kernel_artifacts(tmp_path, "k", src, _DUMP, _CORE, _PLAT) is False
    _record_success(tmp_path, "k", src)
    assert _fresh_kernel_artifacts(
        tmp_path, "k", src, _DUMP, _CORE, "Ascend910B3") is False
    assert not (tmp_path / "k.o").exists()


def test_missing_binary_rebuilds_even_if_marker_matches(tmp_path):
    src = "int f(){return 0;}"
    # record a successful build, then simulate the binary disappearing
    assert _fresh_kernel_artifacts(tmp_path, "k", src, _DUMP, _CORE, _PLAT) is False
    _record_success(tmp_path, "k", src)
    (tmp_path / "k.o").unlink()
    # marker + source match, but .o is gone (prior compile failed / cleaned up)
    assert _fresh_kernel_artifacts(tmp_path, "k", src, _DUMP, _CORE, _PLAT) is False


def test_failed_compile_leaves_no_marker(tmp_path):
    """S5: the cache marker is written only after a SUCCESSFUL compile — a failed
    compile that left a partial/stale .o on disk must not be reusable on the next
    run (no marker written → artifacts removed → fresh build)."""
    src = "int f(){return 0;}"
    assert _fresh_kernel_artifacts(tmp_path, "k", src, _DUMP, _CORE, _PLAT) is False
    # simulate a failed compile: artifacts landed but NO _write_cache_marker call
    _touch(tmp_path, "k", ".o", ".cce")
    assert _fresh_kernel_artifacts(tmp_path, "k", src, _DUMP, _CORE, _PLAT) is False
    assert not (tmp_path / "k.o").exists()


def test_fully_recompiled_then_reused(tmp_path):
    """End-to-end: rebuild once, then the fresh build itself becomes cacheable."""
    src = "int f(){return 0;}"
    assert _fresh_kernel_artifacts(tmp_path, "k", src, _DUMP, _CORE, _PLAT) is False
    _record_success(tmp_path, "k", src)
    assert _fresh_kernel_artifacts(tmp_path, "k", src, _DUMP, _CORE, _PLAT) is True
