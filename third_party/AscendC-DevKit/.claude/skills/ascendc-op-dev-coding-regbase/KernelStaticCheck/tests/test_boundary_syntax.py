#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Boundary / edge-case tests for the static checker."""

from conftest import find_check

from KernelStaticCheck import check_regbase_source


def test_string_literal_containing_bad_token_is_ignored():
    source = '''
template <typename T>
__simd_vf__ inline void GoodVf(__ubuf__ T* dst, uint32_t n)
{
    const char* hint = "GM_ADDR is not allowed here";
    for (uint16_t i = 0; i < n; ++i) {
        AscendC::Reg::Duplicate(dst, 0.0f);
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert find_check(report, "simd_vf_no_gm").passed


def test_comment_containing_bad_token_is_ignored():
    source = '''
template <typename T>
__simd_vf__ inline void GoodVf(__ubuf__ T* dst, uint32_t n)
{
    // if (n > 0) dst[0] = 0;  -- commented out, should be ignored
    for (uint16_t i = 0; i < n; ++i) {
        AscendC::Reg::Duplicate(dst, 0.0f);
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert find_check(report, "hardware_loop_branch").passed
    assert find_check(report, "simd_vf_ubuf_access").passed


def test_block_comment_ignored():
    source = '''
template <typename T>
__simd_vf__ inline void GoodVf(__ubuf__ T* dst, uint32_t n)
{
    /*
    if (n > 0) {
        dst[0] = 0;
    }
    */
    for (uint16_t i = 0; i < n; ++i) {
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert find_check(report, "hardware_loop_branch").passed


def test_escaped_quote_in_string_not_treated_as_string_end():
    source = r'''
template <typename T>
__simd_vf__ inline void GoodVf(__ubuf__ T* dst, uint32_t n)
{
    const char* hint = "if (n > 0) dst[0] = 0; \"not real\"";
    for (uint16_t i = 0; i < n; ++i) {
        AscendC::Reg::Duplicate(dst, 0.0f);
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert find_check(report, "hardware_loop_branch").passed


def test_multiline_signature_still_detected():
    source = '''
template <typename T>
__simd_vf__
inline
void
GoodVf(__ubuf__ T* dst,
       uint32_t n)
{
    for (uint16_t i = 0; i < n; ++i) {
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert find_check(report, "simd_vf_modifiers").passed


def test_multiline_signature_missing_inline_still_detected():
    source = '''
template <typename T>
__simd_vf__
void
BadVf(__ubuf__ T* dst,
      uint32_t n)
{
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert not find_check(report, "simd_vf_modifiers").passed


def test_no_simd_functions_source_passes_all():
    source = '''
#include "kernel_operator.h"

using namespace AscendC;

__aicore__ inline void add_custom(GM_ADDR x, GM_ADDR y, GM_ADDR z, GM_ADDR tiling)
{
    int a = 0;
    for (int i = 0; i < 10; ++i) {
        if (i > 0) {
            a = i;
        }
    }
}
'''
    report = check_regbase_source(source, "add_custom", raise_on_failure=False)
    assert report.passed


def test_multiple_attributes_on_same_line():
    source = '''
template <typename T>
__forceinline__ __simd_vf__ inline void GoodVf(__ubuf__ T* dst, uint32_t n)
{
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert find_check(report, "simd_vf_modifiers").passed


def test_update_mask_with_whitespace_in_argument():
    source = '''
template <typename T>
__simd_vf__ inline void GoodVf(__ubuf__ T* dst, uint32_t n)
{
    uint32_t remaining = n;
    uint16_t loopCount = 1;
    for (uint16_t i = 0; i < loopCount; ++i) {
        AscendC::Reg::MaskReg pregLoop =
            AscendC::Reg::UpdateMask<float>( remaining );
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert find_check(report, "hardware_loop_var_mutation").passed


def test_update_mask_with_cast_expression_argument_fails():
    source = '''
template <typename T>
__simd_vf__ inline void BadVf(__ubuf__ T* dst, uint32_t n)
{
    uint16_t loopCount = 1;
    for (uint16_t i = 0; i < loopCount; ++i) {
        AscendC::Reg::MaskReg pregLoop =
            AscendC::Reg::UpdateMask<float>(static_cast<uint16_t>(n));
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert not find_check(report, "hardware_loop_var_mutation").passed


def test_no_loop_in_vf_function_passes_all():
    source = '''
template <typename T>
__simd_vf__ inline void GoodVf(__ubuf__ T* dst, __ubuf__ T* src, uint32_t n)
{
    AscendC::Reg::Duplicate(dst, 0.0f);
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert report.passed
