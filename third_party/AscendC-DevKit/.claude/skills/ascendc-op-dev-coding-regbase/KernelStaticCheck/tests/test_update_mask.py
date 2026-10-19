#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Pytest coverage for the ``hardware_loop_var_mutation`` static check
(UpdateMask argument mutation), incl. nested loops."""

from conftest import find_check

from KernelStaticCheck import check_regbase_source


def test_update_mask_var_mutated_with_minus_equal_fails():
    """UpdateMask argument mutated via ``-=`` inside the loop must be flagged."""
    source = '''
template <typename T>
__simd_vf__ inline void BadVf(__ubuf__ T* dst, uint32_t n)
{
    AscendC::Reg::MaskReg pregFull =
        AscendC::Reg::CreateMask<float, AscendC::Reg::MaskPattern::ALL>();
    uint32_t remaining = n;
    uint16_t loopCount = static_cast<uint16_t>((n + 64 - 1) / 64);
    for (uint16_t i = 0; i < loopCount; ++i) {
        AscendC::Reg::MaskReg pregLoop =
            AscendC::Reg::UpdateMask<float>(remaining);
        AscendC::Reg::LoadAlign<float, AscendC::Reg::LoadDist::DIST_NORM>(
            dst, dst + i * 64);
        AscendC::Reg::Exp<float, AscendC::Reg::MaskMergeMode::ZEROING>(
            dst, dst, pregLoop);
        remaining -= 64;
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert not find_check(report, "hardware_loop_var_mutation").passed


def test_update_mask_var_mutated_with_assignment_fails():
    """UpdateMask argument reassigned via ``=`` inside the loop must be flagged."""
    source = '''
template <typename T>
__simd_vf__ inline void BadVf(__ubuf__ T* dst, uint32_t n)
{
    uint32_t remaining = n;
    uint16_t loopCount = static_cast<uint16_t>((n + 64 - 1) / 64);
    for (uint16_t i = 0; i < loopCount; ++i) {
        AscendC::Reg::MaskReg pregLoop =
            AscendC::Reg::UpdateMask<float>(remaining);
        AscendC::Reg::LoadAlign<float, AscendC::Reg::LoadDist::DIST_NORM>(
            dst, dst + i * 64);
        remaining = remaining - 64;
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert not find_check(report, "hardware_loop_var_mutation").passed


def test_update_mask_var_mutated_with_prefix_decrement_fails():
    """UpdateMask argument with ``--var`` inside the loop must be flagged."""
    source = '''
template <typename T>
__simd_vf__ inline void BadVf(__ubuf__ T* dst, uint32_t n)
{
    uint32_t remaining = n;
    uint16_t loopCount = static_cast<uint16_t>((n + 64 - 1) / 64);
    for (uint16_t i = 0; i < loopCount; ++i) {
        AscendC::Reg::MaskReg pregLoop =
            AscendC::Reg::UpdateMask<float>(remaining);
        AscendC::Reg::LoadAlign<float, AscendC::Reg::LoadDist::DIST_NORM>(
            dst, dst + i * 64);
        --remaining;
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert not find_check(report, "hardware_loop_var_mutation").passed


def test_update_mask_var_not_mutated_passes():
    """UpdateMask argument that is NOT mutated inside the loop must pass."""
    source = '''
template <typename T>
__simd_vf__ inline void GoodVf(__ubuf__ T* dst, uint32_t n)
{
    AscendC::Reg::MaskReg pregFull =
        AscendC::Reg::CreateMask<float, AscendC::Reg::MaskPattern::ALL>();
    uint32_t cols = n;
    uint16_t loopCount = static_cast<uint16_t>((n + 64 - 1) / 64);
    for (uint16_t i = 0; i < loopCount; ++i) {
        AscendC::Reg::MaskReg pregLoop =
            AscendC::Reg::UpdateMask<float>(cols);
        AscendC::Reg::LoadAlign<float, AscendC::Reg::LoadDist::DIST_NORM>(
            dst, dst + i * 64);
        AscendC::Reg::Exp<float, AscendC::Reg::MaskMergeMode::ZEROING>(
            dst, dst, pregLoop);
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert find_check(report, "hardware_loop_var_mutation").passed


def test_update_mask_expression_argument_fails():
    """UpdateMask must receive a simple lvalue, not an expression."""
    source = '''
template <typename T>
__simd_vf__ inline void BadVf(__ubuf__ T* dst, uint32_t n)
{
    uint16_t loopCount = static_cast<uint16_t>((n + 64 - 1) / 64);
    for (uint16_t i = 0; i < loopCount; ++i) {
        AscendC::Reg::MaskReg pregLoop =
            AscendC::Reg::UpdateMask<float>(n - i * 64);
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert not find_check(report, "hardware_loop_var_mutation").passed


def test_update_mask_not_in_loop_is_not_checked():
    """UpdateMask outside loops is not subject to the mutation rule."""
    source = '''
template <typename T>
__simd_vf__ inline void GoodVf(__ubuf__ T* dst, uint32_t n)
{
    uint32_t remaining = n;
    AscendC::Reg::MaskReg preg =
        AscendC::Reg::UpdateMask<float>(remaining);
    remaining -= 64;
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert find_check(report, "hardware_loop_var_mutation").passed


def test_update_mask_with_multiple_variables_in_loop_passes():
    source = '''
template <typename T>
__simd_vf__ inline void GoodVf(__ubuf__ T* dst, uint32_t n)
{
    uint32_t remaining = n;
    uint16_t loopCount = static_cast<uint16_t>((n + 64 - 1) / 64);
    for (uint16_t i = 0; i < loopCount; ++i) {
        AscendC::Reg::MaskReg pregLoop =
            AscendC::Reg::UpdateMask<float>(remaining);
        uint32_t other = remaining;
        other -= 64;
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert find_check(report, "hardware_loop_var_mutation").passed


def test_update_mask_var_mutated_with_postfix_decrement_fails():
    source = '''
template <typename T>
__simd_vf__ inline void BadVf(__ubuf__ T* dst, uint32_t n)
{
    uint32_t remaining = n;
    uint16_t loopCount = static_cast<uint16_t>((n + 64 - 1) / 64);
    for (uint16_t i = 0; i < loopCount; ++i) {
        AscendC::Reg::MaskReg pregLoop =
            AscendC::Reg::UpdateMask<float>(remaining);
        remaining--;
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert not find_check(report, "hardware_loop_var_mutation").passed


def test_update_mask_var_mutated_with_plus_equal_fails():
    source = '''
template <typename T>
__simd_vf__ inline void BadVf(__ubuf__ T* dst, uint32_t n)
{
    uint32_t remaining = n;
    uint16_t loopCount = static_cast<uint16_t>((n + 64 - 1) / 64);
    for (uint16_t i = 0; i < loopCount; ++i) {
        AscendC::Reg::MaskReg pregLoop =
            AscendC::Reg::UpdateMask<float>(remaining);
        remaining += 64;
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert not find_check(report, "hardware_loop_var_mutation").passed


def test_update_mask_var_mutated_in_nested_loop_only_fails():
    """Variable is mutated in the inner loop where it is also used as UpdateMask arg."""
    source = '''
template <typename T>
__simd_vf__ inline void BadVf(__ubuf__ T* dst, uint32_t n)
{
    uint16_t loopCount = static_cast<uint16_t>((n + 64 - 1) / 64);
    for (uint16_t i = 0; i < loopCount; ++i) {
        uint32_t remaining = n;
        for (uint16_t j = 0; j < 2; ++j) {
            AscendC::Reg::MaskReg pregLoop =
                AscendC::Reg::UpdateMask<float>(remaining);
            remaining -= 64;
        }
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert not find_check(report, "hardware_loop_var_mutation").passed
