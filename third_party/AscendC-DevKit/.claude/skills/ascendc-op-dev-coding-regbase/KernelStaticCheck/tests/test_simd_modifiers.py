#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Pytest coverage for the ``simd_vf_modifiers`` static check."""

import pytest
from conftest import find_check

from KernelStaticCheck import check_regbase_source


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


@pytest.mark.parametrize("attribute", ["__simd_vf__", "__simd_callee__"])
def test_missing_inline_for_both_attributes(attribute):
    source = f'''
template <typename T>
{attribute} void BadFunc(__ubuf__ T* dst, uint32_t n)
{{
}}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert not find_check(report, "simd_vf_modifiers").passed


def test_template_inline_before_attribute_is_not_supported():
    """The checker only looks for inline after the SIMD attribute.

    This matches the original SingleOperatorLaunch behavior; supporting
    ``inline __simd_vf__`` would require extending the parser.
    """
    source = '''
template <typename T>
inline __simd_vf__ void GoodVf(__ubuf__ T* dst, uint32_t n)
{
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    # The function is still detected, but inline is not seen in the
    # attribute-to-brace window, so the modifier check fails.
    assert not find_check(report, "simd_vf_modifiers").passed


def test_no_simd_functions_skips_modifiers_pass():
    source = '''
__aicore__ inline void Kernel(GM_ADDR x, GM_ADDR y)
{
}
'''
    report = check_regbase_source(source, "kernel", raise_on_failure=False)
    assert find_check(report, "simd_vf_modifiers").passed


def test_non_simd_functions_do_not_require_inline():
    """Only SIMD functions need inline; ordinary helper functions are fine."""
    source = '''
void OrdinaryHelper(int x)
{
    if (x > 0) {
        x = 0;
    }
}

template <typename T>
__simd_vf__ inline void GoodVf(__ubuf__ T* dst, uint32_t n)
{
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert find_check(report, "simd_vf_modifiers").passed
