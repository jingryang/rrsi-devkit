#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Pytest coverage for the ``simd_vf_no_gm`` static check."""

from conftest import find_check

from KernelStaticCheck import check_regbase_source


def test_gm_addr_parameter_in_vf_fails():
    source = '''
template <typename T>
__simd_vf__ inline void BadVf(__ubuf__ T* dst, GM_ADDR src, uint32_t n)
{
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert not find_check(report, "simd_vf_no_gm").passed


def test_gm_type_in_vf_body_fails():
    source = '''
template <typename T>
__simd_vf__ inline void BadVf(__ubuf__ T* dst, uint32_t n)
{
    __gm__ T* gm = nullptr;
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert not find_check(report, "simd_vf_no_gm").passed


def test_global_tensor_in_vf_body_fails():
    source = '''
template <typename T>
__simd_vf__ inline void BadVf(__ubuf__ T* dst, uint32_t n)
{
    GlobalTensor<T> gm;
    gm.SetGlobalBuffer((__gm__ T*)nullptr, n);
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert not find_check(report, "simd_vf_no_gm").passed


def test_no_gm_in_vf_passes():
    source = '''
template <typename T>
__simd_vf__ inline void GoodVf(__ubuf__ T* dst, __ubuf__ T* src, uint32_t n)
{
    for (uint16_t i = 0; i < n; ++i) {
        AscendC::Reg::Duplicate(dst, 0.0f);
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert find_check(report, "simd_vf_no_gm").passed


def test_gm_in_kernel_entry_is_allowed():
    """GM access is allowed in the regular __aicore__ kernel entry, not in SIMD."""
    source = '''
template <typename T>
__aicore__ inline void Kernel(GM_ADDR x, GM_ADDR y, GM_ADDR workspace, GM_ADDR tiling)
{
    GlobalTensor<T> xGm;
    xGm.SetGlobalBuffer((__gm__ T*)x, 1024);
}

template <typename T>
__simd_vf__ inline void GoodVf(__ubuf__ T* dst, __ubuf__ T* src, uint32_t n)
{
}
'''
    report = check_regbase_source(source, "Kernel", raise_on_failure=False)
    assert find_check(report, "simd_vf_no_gm").passed


def test_gm_in_comment_is_ignored():
    source = '''
template <typename T>
__simd_vf__ inline void GoodVf(__ubuf__ T* dst, __ubuf__ T* src, uint32_t n)
{
    // GM_ADDR would be bad if it were real code
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert find_check(report, "simd_vf_no_gm").passed
