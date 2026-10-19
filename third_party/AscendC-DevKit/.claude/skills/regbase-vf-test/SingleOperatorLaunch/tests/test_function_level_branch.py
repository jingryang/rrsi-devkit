#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Pytest coverage for the ``vf_function_level_branch`` static check."""

from conftest import find_check

from SingleOperatorLaunch.static_check import check_regbase_source


def test_vf_function_level_if_fails():
    """Function-level ``if`` in __simd_vf__ must be flagged (use for(1) pattern)."""
    source = '''
template <typename T>
__simd_vf__ inline void BadVf(__ubuf__ T* dst, __ubuf__ T* src, uint32_t n)
{
    uint32_t tail = n % 64;
    if (tail > 0) {
        AscendC::Reg::LoadAlign<float, AscendC::Reg::LoadDist::DIST_NORM>(dst, src);
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert not find_check(report, "vf_function_level_branch").passed


def test_vf_function_level_ternary_fails():
    """Function-level ternary ``?:`` in __simd_vf__ must be flagged."""
    source = '''
template <typename T>
__simd_vf__ inline void BadVf(__ubuf__ T* dst, uint32_t n)
{
    uint32_t x = n > 0 ? 1 : 0;
    for (uint16_t i = 0; i < x; ++i) {
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert not find_check(report, "vf_function_level_branch").passed


def test_vf_function_level_for_one_passes():
    """The ``for(uint16_t)`` replacement for function-level if should pass."""
    source = '''
template <typename T>
__simd_vf__ inline void GoodVf(__ubuf__ T* dst, uint32_t n)
{
    uint32_t tail = n % 64;
    uint16_t hasTail = static_cast<uint16_t>(tail != 0);
    for (uint16_t i = 0; i < hasTail; ++i) {
        AscendC::Reg::LoadAlign<float, AscendC::Reg::LoadDist::DIST_NORM>(dst, dst);
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert find_check(report, "vf_function_level_branch").passed


def test_vf_callee_function_level_if_fails():
    """Function-level ``if`` in __simd_callee__ must also be flagged."""
    source = '''
template <typename T>
__simd_callee__ inline void BadCallee(AscendC::Reg::RegTensor<float>& dst, uint32_t flag)
{
    if (flag == 0) {
        AscendC::Reg::Duplicate(dst, 0.0f);
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert not find_check(report, "vf_function_level_branch").passed


def test_vf_function_level_nested_loop_with_if_outside_passes():
    """A loop-inner branch should still fail hardward_loop_branch, but function-level check passes."""
    source = '''
template <typename T>
__simd_vf__ inline void GoodVf(__ubuf__ T* dst, uint32_t n)
{
    for (uint16_t i = 0; i < n; ++i) {
        // no inner branch
    }
    // no function-level branch either
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert find_check(report, "vf_function_level_branch").passed
