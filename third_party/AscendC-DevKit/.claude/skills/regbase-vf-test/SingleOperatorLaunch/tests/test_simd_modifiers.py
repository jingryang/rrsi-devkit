#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Pytest coverage for the ``simd_vf_modifiers`` static check."""

from conftest import find_check

from SingleOperatorLaunch.static_check import check_regbase_source


def test_simd_vf_without_inline_fails():
    source = '''
template <typename T>
__simd_vf__ void BadVf(__ubuf__ T* dst, __ubuf__ T* src, uint32_t n)
{
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert not find_check(report, "simd_vf_modifiers").passed


def test_simd_vf_with_inline_passes():
    source = '''
template <typename T>
__simd_vf__ inline void GoodVf(__ubuf__ T* dst, __ubuf__ T* src, uint32_t n)
{
    uint16_t repeatTime = 1;
    for (uint16_t i = 0; i < repeatTime; ++i) {
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert find_check(report, "simd_vf_modifiers").passed


def test_simd_callee_without_inline_fails():
    source = '''
template <typename T>
__simd_callee__ void BadCallee(AscendC::Reg::RegTensor<T>& r)
{
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert not find_check(report, "simd_vf_modifiers").passed


def test_multiple_simd_functions_all_checked():
    source = '''
template <typename T>
__simd_vf__ inline void FirstGood(__ubuf__ T* dst, uint32_t n)
{
    for (uint16_t i = 0; i < n; ++i) {
    }
}

template <typename T>
__simd_vf__ void SecondBad(__ubuf__ T* dst, uint32_t n)
{
    for (int i = 0; i < n; ++i) {
        if (i > 0) {
            dst[i] = 0;
        }
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert not find_check(report, "simd_vf_modifiers").passed
    assert not find_check(report, "hardware_loop_var_type").passed
    assert not find_check(report, "hardware_loop_branch").passed
    assert not find_check(report, "simd_vf_ubuf_access").passed


def test_multiple_callees_all_checked():
    source = '''
template <typename T>
__simd_callee__ inline void GoodCallee(AscendC::Reg::RegTensor<T>& r) {}

template <typename T>
__simd_callee__ void BadCallee(__ubuf__ T* dst, GM_ADDR src) {}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert not find_check(report, "simd_vf_modifiers").passed
    assert not find_check(report, "simd_vf_no_gm").passed
