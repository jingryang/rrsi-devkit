#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Pytest coverage for the RegBase static checker report structure,
error messages, raise_on_failure behaviour, and direct API."""

import pytest
from conftest import find_check

from SingleOperatorLaunch.static_check import (
    RegBaseChecker,
    StaticCheckReport,
    check_regbase_source,
)


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


def test_source_module_static_check_mandatory():
    """SourceModule constructor must run the static checker before compilation."""
    bad_source = '''
template <typename T>
__simd_vf__ void BadVf(__ubuf__ T* dst, __ubuf__ T* src, uint32_t n)
{
}
'''
    from SingleOperatorLaunch import SourceModule
    with pytest.raises(RuntimeError, match="RegBase static check failed"):
        SourceModule(source=bad_source, kernel_name="bad_kernel")
