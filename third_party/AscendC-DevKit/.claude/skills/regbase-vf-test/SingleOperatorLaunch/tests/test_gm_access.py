#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Pytest coverage for the ``simd_vf_no_gm`` static check."""

from conftest import find_check

from SingleOperatorLaunch.static_check import check_regbase_source


def test_gm_addr_in_vf_fails():
    source = '''
template <typename T>
__simd_vf__ inline void BadVf(__ubuf__ T* dst, GM_ADDR src, uint32_t n)
{
    for (uint16_t i = 0; i < n; ++i) {
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert not find_check(report, "simd_vf_no_gm").passed


def test_global_tensor_in_vf_fails():
    source = '''
template <typename T>
__simd_vf__ inline void BadVf(__ubuf__ T* dst, uint32_t n)
{
    GlobalTensor<T> gm;
    gm.SetGlobalBuffer((__gm__ T*)dst, n);
    for (uint16_t i = 0; i < n; ++i) {
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert not find_check(report, "simd_vf_no_gm").passed


def test_gm_access_in_callee_fails():
    source = '''
template <typename T>
__simd_callee__ inline void BadCallee(__ubuf__ T* dst, GM_ADDR src)
{
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert not find_check(report, "simd_vf_no_gm").passed
