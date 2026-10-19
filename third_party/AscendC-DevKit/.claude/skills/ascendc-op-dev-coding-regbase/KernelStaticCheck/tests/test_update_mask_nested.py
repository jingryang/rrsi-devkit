#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Pytest coverage for nested-loop ``hardware_loop_var_mutation`` checks."""

from conftest import find_check

from KernelStaticCheck import check_regbase_source

COMMON_PREAMBLE = '''
template <typename T>
__simd_vf__ inline void Vf(__ubuf__ T* dst, uint32_t n)
{
'''

COMMON_SUFFIX = '''
}
'''


def make_source(body: str) -> str:
    return COMMON_PREAMBLE + body + COMMON_SUFFIX


def test_nested_outer_update_mask_var_mutated_in_outer_fails():
    source = make_source('''
    uint32_t remaining = n;
    uint16_t outerCount = 2;
    for (uint16_t i = 0; i < outerCount; ++i) {
        uint16_t innerCount = 2;
        for (uint16_t j = 0; j < innerCount; ++j) {
            AscendC::Reg::MaskReg preg =
                AscendC::Reg::UpdateMask<float>(remaining);
        }
        remaining -= 64;
    }
''')
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert not find_check(report, "hardware_loop_var_mutation").passed


def test_nested_inner_update_mask_var_mutated_in_inner_fails():
    source = make_source('''
    uint16_t outerCount = 2;
    for (uint16_t i = 0; i < outerCount; ++i) {
        uint32_t remaining = n;
        uint16_t innerCount = 2;
        for (uint16_t j = 0; j < innerCount; ++j) {
            AscendC::Reg::MaskReg preg =
                AscendC::Reg::UpdateMask<float>(remaining);
            remaining -= 64;
        }
    }
''')
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert not find_check(report, "hardware_loop_var_mutation").passed


def test_nested_outer_update_mask_var_mutated_in_inner_fails():
    source = make_source('''
    uint32_t remaining = n;
    uint16_t outerCount = 2;
    for (uint16_t i = 0; i < outerCount; ++i) {
        uint16_t innerCount = 2;
        for (uint16_t j = 0; j < innerCount; ++j) {
            AscendC::Reg::MaskReg preg =
                AscendC::Reg::UpdateMask<float>(remaining);
            remaining -= 64;
        }
    }
''')
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert not find_check(report, "hardware_loop_var_mutation").passed


def test_nested_inner_update_mask_var_not_mutated_passes():
    """Inner UpdateMask(var); var not mutated anywhere. Must pass."""
    source = make_source('''
    for (uint16_t i = 0; i < 2; ++i) {
        for (uint16_t j = 0; j < n; ++j) {
            AscendC::Reg::MaskReg pregLoop =
                AscendC::Reg::UpdateMask<float>(n);
            AscendC::Reg::LoadAlign<float>(dst, dst + j);
        }
    }
''')
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert find_check(report, "hardware_loop_var_mutation").passed


def test_nested_both_levels_update_mask_same_var_mutated_fails():
    source = make_source('''
    uint32_t remaining = n;
    uint16_t outerCount = 2;
    for (uint16_t i = 0; i < outerCount; ++i) {
        AscendC::Reg::MaskReg pregOuter =
            AscendC::Reg::UpdateMask<float>(remaining);
        uint16_t innerCount = 2;
        for (uint16_t j = 0; j < innerCount; ++j) {
            AscendC::Reg::MaskReg pregInner =
                AscendC::Reg::UpdateMask<float>(remaining);
            remaining -= 64;
        }
    }
''')
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert not find_check(report, "hardware_loop_var_mutation").passed


def test_nested_three_levels_outer_update_mask_mutated_in_inner_fails():
    source = make_source('''
    uint32_t remaining = n;
    uint16_t c1 = 2;
    for (uint16_t i = 0; i < c1; ++i) {
        AscendC::Reg::MaskReg preg1 =
            AscendC::Reg::UpdateMask<float>(remaining);
        uint16_t c2 = 2;
        for (uint16_t j = 0; j < c2; ++j) {
            uint16_t c3 = 2;
            for (uint16_t k = 0; k < c3; ++k) {
                remaining -= 64;
            }
        }
    }
''')
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert not find_check(report, "hardware_loop_var_mutation").passed


def test_nested_different_vars_not_mutated_passes():
    source = '''
template <typename T>
__simd_vf__ inline void Vf(__ubuf__ T* dst, uint32_t n, uint32_t m)
{
    uint32_t outerRemaining = n;
    uint32_t innerRemaining = m;
    uint16_t outerCount = 2;
    uint16_t innerCount = 2;
    for (uint16_t i = 0; i < outerCount; ++i) {
        AscendC::Reg::MaskReg pregOuter =
            AscendC::Reg::UpdateMask<float>(outerRemaining);
        for (uint16_t j = 0; j < innerCount; ++j) {
            AscendC::Reg::MaskReg pregInner =
                AscendC::Reg::UpdateMask<float>(innerRemaining);
        }
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert find_check(report, "hardware_loop_var_mutation").passed


def test_update_mask_var_mutated_between_loops_passes():
    """Mutation between loops (not inside a loop that uses UpdateMask) is fine."""
    source = make_source('''
    uint32_t remaining = n;
    uint16_t count = 2;
    for (uint16_t i = 0; i < count; ++i) {
        AscendC::Reg::MaskReg preg =
            AscendC::Reg::UpdateMask<float>(remaining);
    }
    remaining -= 64;
''')
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert find_check(report, "hardware_loop_var_mutation").passed


def test_update_mask_var_mutated_after_loop_passes():
    source = make_source('''
    uint32_t remaining = n;
    uint16_t count = 2;
    for (uint16_t i = 0; i < count; ++i) {
        AscendC::Reg::MaskReg preg =
            AscendC::Reg::UpdateMask<float>(remaining);
    }
    remaining -= 64;
''')
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert find_check(report, "hardware_loop_var_mutation").passed


def test_update_mask_var_mutated_before_loop_passes():
    source = make_source('''
    uint32_t remaining = n;
    remaining -= 64;
    uint16_t count = 2;
    for (uint16_t i = 0; i < count; ++i) {
        AscendC::Reg::MaskReg preg =
            AscendC::Reg::UpdateMask<float>(remaining);
    }
''')
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert find_check(report, "hardware_loop_var_mutation").passed


def test_no_update_mask_passes():
    source = make_source('''
    uint32_t remaining = n;
    uint16_t count = 2;
    for (uint16_t i = 0; i < count; ++i) {
        remaining -= 64;
    }
''')
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert find_check(report, "hardware_loop_var_mutation").passed
