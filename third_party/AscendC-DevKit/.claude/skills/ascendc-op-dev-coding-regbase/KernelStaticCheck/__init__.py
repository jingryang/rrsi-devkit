#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
KernelStaticCheck — standalone AscendC / RegBase kernel source static checker.

This package re-implements the static checking rules used by
``SingleOperatorLaunch`` in a self-contained way, so it can be used without
dragging in the full single-operator launch stack (compiler bindings, device
access, etc.).

Public API:
    check_regbase_source(source, kernel_name, raise_on_failure=True)
    RegBaseChecker(source, kernel_name).run_all()
    StaticCheckReport
    CheckResult

Example:
    from KernelStaticCheck import check_regbase_source

    report = check_regbase_source(source_code, "add_custom", raise_on_failure=False)
    if not report.passed:
        for failure in report.failures:
            print(failure.name, failure.message)
"""

from .checker import CheckResult, RegBaseChecker, StaticCheckReport, check_regbase_source

__all__ = [
    "CheckResult",
    "RegBaseChecker",
    "StaticCheckReport",
    "check_regbase_source",
]
