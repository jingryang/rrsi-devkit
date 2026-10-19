#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Pytest coverage for the ``hardware_loop_var_mutation`` static check:
UpdateMask mutation in nested loops."""

from conftest import find_check

from SingleOperatorLaunch.static_check import check_regbase_source


def test_nested_outer_update_mask_var_mutated_in_outer_fails():
    """Outer loop has UpdateMask(var); var mutated in outer body. Must fail."""
    source = '''
template <typename T>
__simd_vf__ inline void BadVf(__ubuf__ T* dst, uint32_t rows, uint32_t cols)
{
    uint32_t remaining = rows;
    uint16_t loopCount = static_cast<uint16_t>((rows + 64 - 1) / 64);
    for (uint16_t i = 0; i < loopCount; ++i) {
        AscendC::Reg::MaskReg pregLoop =
            AscendC::Reg::UpdateMask<float>(remaining);
        for (uint16_t j = 0; j < cols; ++j) {
            AscendC::Reg::Duplicate(dst, 0.0f);
        }
        remaining -= 64;
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert not find_check(report, "hardware_loop_var_mutation").passed


def test_nested_inner_update_mask_var_mutated_in_inner_fails():
    """Inner loop has UpdateMask(var); var mutated in inner body. Must fail."""
    source = '''
template <typename T>
__simd_vf__ inline void BadVf(__ubuf__ T* dst, uint32_t rows, uint32_t cols)
{
    uint32_t remaining = cols;
    uint16_t loopCount = static_cast<uint16_t>((cols + 64 - 1) / 64);
    for (uint16_t i = 0; i < rows; ++i) {
        for (uint16_t j = 0; j < loopCount; ++j) {
            AscendC::Reg::MaskReg pregLoop =
                AscendC::Reg::UpdateMask<float>(remaining);
            AscendC::Reg::LoadAlign<float>(dst, dst + j * 64);
            remaining -= 64;
        }
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert not find_check(report, "hardware_loop_var_mutation").passed


def test_nested_outer_update_mask_var_mutated_in_inner_fails():
    """Outer UpdateMask(var); var mutated in inner loop body. Must fail."""
    source = '''
template <typename T>
__simd_vf__ inline void BadVf(__ubuf__ T* dst, uint32_t rows, uint32_t cols)
{
    uint32_t remaining = rows;
    uint16_t loopCount = static_cast<uint16_t>((rows + 64 - 1) / 64);
    for (uint16_t i = 0; i < loopCount; ++i) {
        AscendC::Reg::MaskReg pregLoop =
            AscendC::Reg::UpdateMask<float>(remaining);
        for (uint16_t j = 0; j < cols; ++j) {
            AscendC::Reg::Duplicate(dst, 0.0f);
            --remaining;
        }
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert not find_check(report, "hardware_loop_var_mutation").passed


def test_nested_inner_update_mask_var_not_mutated_passes():
    """Inner UpdateMask(var); var not mutated anywhere. Must pass."""
    source = '''
template <typename T>
__simd_vf__ inline void GoodVf(__ubuf__ T* dst, uint32_t rows, uint32_t cols)
{
    for (uint16_t i = 0; i < rows; ++i) {
        for (uint16_t j = 0; j < cols; ++j) {
            AscendC::Reg::MaskReg pregLoop =
                AscendC::Reg::UpdateMask<float>(cols);
            AscendC::Reg::LoadAlign<float>(dst, dst + j);
        }
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert find_check(report, "hardware_loop_var_mutation").passed


def test_nested_both_levels_update_mask_same_var_mutated_fails():
    """Both levels have UpdateMask(var); var mutated after inner. Must fail."""
    source = '''
template <typename T>
__simd_vf__ inline void BadVf(__ubuf__ T* dst, uint32_t rows, uint32_t cols)
{
    uint32_t remaining = rows * cols;
    uint16_t outerCount = static_cast<uint16_t>((rows + 64 - 1) / 64);
    uint16_t innerCount = static_cast<uint16_t>((cols + 64 - 1) / 64);
    for (uint16_t i = 0; i < outerCount; ++i) {
        AscendC::Reg::MaskReg pregOuter =
            AscendC::Reg::UpdateMask<float>(remaining);
        for (uint16_t j = 0; j < innerCount; ++j) {
            AscendC::Reg::MaskReg pregInner =
                AscendC::Reg::UpdateMask<float>(remaining);
            AscendC::Reg::LoadAlign<float>(dst, dst + j * 64);
            remaining -= 64;
        }
        remaining -= 64;
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert not find_check(report, "hardware_loop_var_mutation").passed


def test_nested_three_levels_outer_update_mask_mutated_in_inner_fails():
    """3-level nested: outermost UpdateMask(var); var mutated in innermost."""
    source = '''
template <typename T>
__simd_vf__ inline void BadVf(__ubuf__ T* dst, uint32_t d1, uint32_t d2, uint32_t d3)
{
    uint32_t remaining = d1;
    uint16_t l1 = static_cast<uint16_t>((d1 + 64 - 1) / 64);
    uint16_t l2 = static_cast<uint16_t>((d2 + 64 - 1) / 64);
    uint16_t l3 = static_cast<uint16_t>((d3 + 64 - 1) / 64);
    for (uint16_t i = 0; i < l1; ++i) {
        AscendC::Reg::MaskReg preg1 =
            AscendC::Reg::UpdateMask<float>(remaining);
        for (uint16_t j = 0; j < l2; ++j) {
            for (uint16_t k = 0; k < l3; ++k) {
                AscendC::Reg::LoadAlign<float>(dst, dst + k * 64);
                remaining -= 64;
            }
        }
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert not find_check(report, "hardware_loop_var_mutation").passed


def test_nested_different_vars_not_mutated_passes():
    """Outer and inner each have UpdateMask with distinct vars, neither mutated."""
    source = '''
template <typename T>
__simd_vf__ inline void GoodVf(__ubuf__ T* dst, uint32_t rows, uint32_t cols)
{
    uint32_t outerRemaining = rows;
    uint32_t innerRemaining = cols;
    uint16_t outerCount = static_cast<uint16_t>((rows + 64 - 1) / 64);
    uint16_t innerCount = static_cast<uint16_t>((cols + 64 - 1) / 64);
    for (uint16_t i = 0; i < outerCount; ++i) {
        AscendC::Reg::MaskReg pregOuter =
            AscendC::Reg::UpdateMask<float>(outerRemaining);
        for (uint16_t j = 0; j < innerCount; ++j) {
            AscendC::Reg::MaskReg pregInner =
                AscendC::Reg::UpdateMask<float>(innerRemaining);
            AscendC::Reg::LoadAlign<float>(dst, dst + j * 64);
        }
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert find_check(report, "hardware_loop_var_mutation").passed
