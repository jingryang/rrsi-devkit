#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Shared helpers for KernelStaticCheck tests."""

from KernelStaticCheck import StaticCheckReport


def find_check(result: StaticCheckReport, name: str) -> object:
    for r in result.results:
        if r.name == name:
            return r
    raise AssertionError(f"Check {name!r} not found in report")
