#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Pytest coverage for the RegBase static checker report structure,
error messages, raise_on_failure behaviour, and direct API."""

import pytest
from conftest import find_check

from KernelStaticCheck import RegBaseChecker, StaticCheckReport, check_regbase_source


def test_raise_on_failure_default_raises():
    source = '''
template <typename T>
__simd_vf__ void BadVf(__ubuf__ T* dst, __ubuf__ T* src, uint32_t n)
{
}
'''
    with pytest.raises(RuntimeError):
        check_regbase_source(source, "bad_kernel")


def test_raise_on_failure_disabled_returns_report():
    source = '''
template <typename T>
__simd_vf__ void BadVf(__ubuf__ T* dst, __ubuf__ T* src, uint32_t n)
{
}
'''
    report = check_regbase_source(source, "bad_kernel", raise_on_failure=False)
    assert not report.passed


def test_report_passed_matches_results():
    source = '''
template <typename T>
__simd_vf__ inline void ok_vf(__ubuf__ T* dst, uint32_t n)
{
    for (uint16_t i = 0; i < n; ++i) {
    }
}
'''
    report = check_regbase_source(source, "ok_kernel", raise_on_failure=False)
    assert report.passed == all(r.passed for r in report.results)


def test_failures_only_contains_failed_results():
    source = '''
template <typename T>
__simd_vf__ void BadVf(__ubuf__ T* dst, __ubuf__ T* src, uint32_t n)
{
}
'''
    report = check_regbase_source(source, "bad_kernel", raise_on_failure=False)
    failed = report.failures
    assert len(failed) > 0
    assert all(not r.passed for r in failed)


def test_error_messages_include_line_numbers():
    source = '''
#include "kernel_operator.h"

// some comment line

template <typename T>
__simd_vf__ void BadVf(__ubuf__ T* dst, __ubuf__ T* src, uint32_t n)
{
}
'''
    report = check_regbase_source(source, "bad_kernel", raise_on_failure=False)
    entry = find_check(report, "simd_vf_modifiers")
    assert entry.line_no is not None
    assert entry.line_no > 1


def test_checker_api_returns_named_results():
    source = '''
template <typename T>
__simd_vf__ inline void ok_vf(__ubuf__ T* dst, uint32_t n)
{
    for (uint16_t i = 0; i < n; ++i) {
    }
}
'''
    checker = RegBaseChecker(source, "ok_kernel")
    report = checker.run_all()
    assert isinstance(report, StaticCheckReport)
    assert all(r.name for r in report.results)


def test_report_string_contains_all_checks():
    source = '''
template <typename T>
__simd_vf__ inline void ok_vf(__ubuf__ T* dst, uint32_t n)
{
    for (uint16_t i = 0; i < n; ++i) {
    }
}
'''
    report = check_regbase_source(source, "ok_kernel", raise_on_failure=False)
    text = str(report)
    assert "PASS" in text
    assert "simd_vf_modifiers" in text
    assert "hardware_loop_var_type" in text


def test_all_rules_run_on_clean_source():
    source = '''
template <typename T>
__simd_vf__ inline void CleanVf(__ubuf__ T* dst, __ubuf__ T* src, uint32_t n)
{
    for (uint16_t i = 0; i < n; ++i) {
        AscendC::Reg::Duplicate(dst, 0.0f);
    }
}
'''
    report = check_regbase_source(source, "clean", raise_on_failure=False)
    assert report.passed
    names = {r.name for r in report.results}
    expected = {
        "simd_vf_modifiers",
        "simd_vf_ubuf_access",
        "simd_vf_no_gm",
        "hardware_loop_var_type",
        "hardware_loop_branch",
        "hardware_loop_var_mutation",
        "vf_function_level_branch",
    }
    assert expected <= names


def test_report_str_for_failed_check_includes_line_number():
    source = '''
template <typename T>
__simd_vf__ void BadVf(__ubuf__ T* dst, __ubuf__ T* src, uint32_t n)
{
}
'''
    report = check_regbase_source(source, "bad_kernel", raise_on_failure=False)
    text = str(report)
    assert "FAIL" in text
    assert "line" in text


def test_empty_source_does_not_crash():
    report = check_regbase_source("", "empty", raise_on_failure=False)
    assert report.passed


def test_kernel_name_is_not_validated():
    """The checker currently does not enforce that the kernel entry exists."""
    source = '''
template <typename T>
__simd_vf__ inline void GoodVf(__ubuf__ T* dst, uint32_t n)
{
}
'''
    report = check_regbase_source(source, "totally_different_name", raise_on_failure=False)
    assert report.passed
