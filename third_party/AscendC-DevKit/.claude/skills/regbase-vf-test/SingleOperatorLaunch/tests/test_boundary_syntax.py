#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Pytest coverage for boundary syntax: comments, strings and multi-line
declarations in the RegBase static checker."""

from conftest import find_check

from SingleOperatorLaunch.static_check import check_regbase_source


def test_comments_are_ignored_for_branch_detection():
    source = '''
template <typename T>
__simd_vf__ inline void GoodVf(__ubuf__ T* dst, uint32_t n)
{
    for (uint16_t i = 0; i < n; ++i) {
        // if (i > 0) { dst[i] = 0; }   /* ternary ?: also ignored */
        AscendC::Reg::LoadAlign(x, dst + i);
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert find_check(report, "hardware_loop_branch").passed
    assert find_check(report, "simd_vf_ubuf_access").passed


def test_strings_are_ignored_for_branch_detection():
    source = '''
template <typename T>
__simd_vf__ inline void GoodVf(__ubuf__ T* dst, uint32_t n)
{
    for (uint16_t i = 0; i < n; ++i) {
        AscendC::printf("if (i > 0) ? 1 : 0\\n");
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert find_check(report, "hardware_loop_branch").passed


def test_multiline_simd_vf_declaration_is_recognized():
    source = '''
template <typename T>
__simd_vf__
inline
void
MultiLineVf(__ubuf__ T* dst, __ubuf__ T* src, uint32_t n)
{
    for (uint16_t i = 0; i < n; ++i) {
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert find_check(report, "simd_vf_modifiers").passed
    assert find_check(report, "hardware_loop_var_type").passed
    assert find_check(report, "hardware_loop_branch").passed
