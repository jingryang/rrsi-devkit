#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Pytest coverage for the ``hardware_loop_var_type`` and
``hardware_loop_branch`` static checks (incl. nested loops)."""

import pytest
from conftest import find_check

from KernelStaticCheck import check_regbase_source


@pytest.mark.parametrize(
    "loop_var_decl",
    [
        "int i = 0",
        "uint32_t i = 0",
        "auto i = 0",
    ],
)
def test_non_uint16_loop_variable_fails(loop_var_decl):
    source = f'''
template <typename T>
__simd_vf__ inline void BadVf(__ubuf__ T* dst, uint32_t n)
{{
    for ({loop_var_decl}; i < n; ++i) {{
    }}
}}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert not find_check(report, "hardware_loop_var_type").passed


def test_uint16_loop_variable_passes():
    source = '''
template <typename T>
__simd_vf__ inline void GoodVf(__ubuf__ T* dst, uint32_t n)
{
    for (uint16_t i = 0; i < n; ++i) {
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert find_check(report, "hardware_loop_var_type").passed


@pytest.mark.parametrize(
    "loop_body",
    [
        "if (i > 0) { dst[i] = 0; }",
        "uint32_t x = i > 0 ? 1 : 0;",
        "if (i == 0) { x = 1; } else { x = 2; }",
    ],
)
def test_runtime_branch_in_loop_fails(loop_body):
    source = f'''
template <typename T>
__simd_vf__ inline void BadVf(__ubuf__ T* dst, uint32_t n)
{{
    for (uint16_t i = 0; i < n; ++i) {{
        {loop_body}
    }}
}}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert not find_check(report, "hardware_loop_branch").passed


def test_if_constexpr_in_loop_passes():
    source = '''
template <typename T, int Mode>
__simd_vf__ inline void GoodVf(__ubuf__ T* dst, uint32_t n)
{
    for (uint16_t i = 0; i < n; ++i) {
        if constexpr (Mode == 0) {
            dst[i] = 0;
        } else {
            dst[i] = 1;
        }
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    # Note: the [] subscript inside VF will still fail the ubuf access check,
    # but the branch check itself should pass.
    assert find_check(report, "hardware_loop_branch").passed


def test_for_one_pattern_passes():
    """The recommended ``for(1)`` replacement for runtime if."""
    source = '''
template <typename T>
__simd_vf__ inline void GoodVf(__ubuf__ T* dst, uint32_t n)
{
    uint16_t hasTail = static_cast<uint16_t>(n & 1);
    for (uint16_t i = 0; i < hasTail; ++i) {
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert find_check(report, "hardware_loop_branch").passed


def test_nested_loop_with_uint16_passes():
    source = '''
template <typename T>
__simd_vf__ inline void GoodVf(__ubuf__ T* dst, uint32_t n)
{
    for (uint16_t i = 0; i < n; ++i) {
        for (uint16_t j = 0; j < n; ++j) {
            AscendC::Reg::Duplicate(dst, 0.0f);
        }
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert find_check(report, "hardware_loop_var_type").passed
    assert find_check(report, "hardware_loop_branch").passed


def test_inner_loop_has_bad_type_outer_loop_is_fine():
    source = '''
template <typename T>
__simd_vf__ inline void BadVf(__ubuf__ T* dst, uint32_t n)
{
    for (uint16_t i = 0; i < n; ++i) {
        for (size_t j = 0; j < 8; ++j) {
        }
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert not find_check(report, "hardware_loop_var_type").passed


def test_single_statement_loop_body_runtime_branch_fails():
    """A loop body without braces still must not contain a runtime branch."""
    source = '''
template <typename T>
__simd_vf__ inline void BadVf(__ubuf__ T* dst, uint32_t n)
{
    for (uint16_t i = 0; i < n; ++i)
        if (i > 0) dst[i] = 0;
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert not find_check(report, "hardware_loop_branch").passed


@pytest.mark.parametrize(
    "loop_body",
    [
        "AscendC::Reg::Duplicate(dst, 0.0f);",
        "uint32_t offset = i * 4;",
    ],
)
def test_loop_body_without_braces_passes(loop_body):
    source = f'''
template <typename T>
__simd_vf__ inline void GoodVf(__ubuf__ T* dst, uint32_t n)
{{
    for (uint16_t i = 0; i < n; ++i)
        {loop_body}
}}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert find_check(report, "hardware_loop_branch").passed


def test_non_simd_function_loops_are_ignored():
    """Loops outside __simd_vf__ / __simd_callee__ are not hardware-loop checked."""
    source = '''
void NormalFunction(int* arr, int n)
{
    for (int i = 0; i < n; ++i) {
        if (i > 0) {
            arr[i] = 0;
        }
    }
}

template <typename T>
__simd_vf__ inline void GoodVf(__ubuf__ T* dst, uint32_t n)
{
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert find_check(report, "hardware_loop_var_type").passed
    assert find_check(report, "hardware_loop_branch").passed


def test_static_cast_uint16_init_passes():
    """Loop init like ``auto i = static_cast<uint16_t>(0)`` should be accepted."""
    source = '''
template <typename T>
__simd_vf__ inline void GoodVf(__ubuf__ T* dst, uint32_t n)
{
    for (auto i = static_cast<uint16_t>(0); i < n; ++i) {
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert find_check(report, "hardware_loop_var_type").passed
