#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Pytest coverage for the ``simd_vf_ubuf_access`` static check."""

from conftest import find_check

from KernelStaticCheck import check_regbase_source


def test_ubuf_subscript_in_vf_fails():
    source = '''
template <typename T>
__simd_vf__ inline void BadVf(__ubuf__ T* dst, __ubuf__ T* src, uint32_t n)
{
    for (uint16_t i = 0; i < n; ++i) {
        dst[i] = src[i];
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert not find_check(report, "simd_vf_ubuf_access").passed


def test_multiplication_in_vf_body_is_allowed():
    """Multiplication `a * b` must not be confused with pointer dereference."""
    source = '''
template <typename T>
__simd_vf__ inline void GoodVf(__ubuf__ T* dst, __ubuf__ T* src, uint32_t n)
{
    uint32_t offset = n * sizeof(T);
    for (uint16_t i = 0; i < n; ++i) {
        uint32_t x = i * 4;
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert find_check(report, "simd_vf_ubuf_access").passed


def test_ubuf_subscript_in_callee_fails():
    source = '''
template <typename T>
__simd_callee__ inline void BadCallee(__ubuf__ T* dst, uint32_t n)
{
    for (uint16_t i = 0; i < n; ++i) {
        dst[i] = 0;
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert not find_check(report, "simd_vf_ubuf_access").passed


def test_array_index_in_non_simd_function_is_ignored():
    source = '''
void NormalFunction(int* arr, uint32_t n)
{
    for (uint16_t i = 0; i < n; ++i) {
        arr[i] = 0;
    }
}

template <typename T>
__simd_vf__ inline void GoodVf(__ubuf__ T* dst, uint32_t n)
{
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert find_check(report, "simd_vf_ubuf_access").passed


def test_ascendc_reg_api_calls_are_allowed():
    source = '''
template <typename T>
__simd_vf__ inline void GoodVf(__ubuf__ T* dst, __ubuf__ T* src, uint32_t n)
{
    for (uint16_t i = 0; i < n; ++i) {
        AscendC::Reg::LoadAlign<float, AscendC::Reg::LoadDist::DIST_NORM>(dst, src);
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert find_check(report, "simd_vf_ubuf_access").passed
