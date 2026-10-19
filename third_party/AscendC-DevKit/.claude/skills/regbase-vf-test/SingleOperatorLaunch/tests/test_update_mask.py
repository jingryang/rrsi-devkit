#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Pytest coverage for the ``hardware_loop_var_mutation`` static check
(UpdateMask argument mutation), incl. nested loops."""

from conftest import find_check

from SingleOperatorLaunch.static_check import check_regbase_source


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


def test_update_mask_expression_arg_fails():
    """UpdateMask called with an expression argument must be flagged."""
    source = '''
template <typename T>
__simd_vf__ inline void BadVf(__ubuf__ T* dst, uint32_t n)
{
    uint32_t remaining = n;
    uint16_t loopCount = static_cast<uint16_t>((n + 64 - 1) / 64);
    for (uint16_t i = 0; i < loopCount; ++i) {
        AscendC::Reg::MaskReg pregLoop =
            AscendC::Reg::UpdateMask<float>(remaining - i * 64);
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert not find_check(report, "hardware_loop_var_mutation").passed


def test_update_mask_simple_var_not_mutated_passes():
    """UpdateMask called with a simple variable not mutated passes."""
    source = '''
template <typename T>
__simd_vf__ inline void GoodVf(__ubuf__ T* dst, uint32_t n)
{
    uint32_t remaining = n;
    uint16_t loopCount = static_cast<uint16_t>((n + 64 - 1) / 64);
    for (uint16_t i = 0; i < loopCount; ++i) {
        AscendC::Reg::MaskReg pregLoop =
            AscendC::Reg::UpdateMask<float>(remaining);
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert find_check(report, "hardware_loop_var_mutation").passed


def test_update_mask_var_mutated_between_loops_passes():
    """Mutation between two for loops is legal (outside any loop body)."""
    source = '''
template <typename T>
__simd_vf__ inline void GoodVf(__ubuf__ T* dst, uint32_t n)
{
    uint32_t remaining = n;
    uint16_t loopCount = static_cast<uint16_t>((n + 64 - 1) / 64);
    for (uint16_t i = 0; i < loopCount; ++i) {
        AscendC::Reg::MaskReg pregLoop =
            AscendC::Reg::UpdateMask<float>(remaining);
    }
    remaining -= 64;
    for (uint16_t i = 0; i < loopCount; ++i) {
        AscendC::Reg::MaskReg pregLoop =
            AscendC::Reg::UpdateMask<float>(remaining);
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert find_check(report, "hardware_loop_var_mutation").passed


def test_update_mask_var_mutated_after_loop_passes():
    """Mutation after a for loop is legal (outside any loop body)."""
    source = '''
template <typename T>
__simd_vf__ inline void GoodVf(__ubuf__ T* dst, uint32_t n)
{
    uint32_t remaining = n;
    uint16_t loopCount = static_cast<uint16_t>((n + 64 - 1) / 64);
    for (uint16_t i = 0; i < loopCount; ++i) {
        AscendC::Reg::MaskReg pregLoop =
            AscendC::Reg::UpdateMask<float>(remaining);
    }
    remaining = 0;
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert find_check(report, "hardware_loop_var_mutation").passed


def test_update_mask_var_mutated_before_loop_passes():
    """Mutation before a for loop is legal (outside any loop body)."""
    source = '''
template <typename T>
__simd_vf__ inline void GoodVf(__ubuf__ T* dst, uint32_t n)
{
    uint32_t remaining = n;
    remaining -= 64;
    uint16_t loopCount = static_cast<uint16_t>((n + 64 - 1) / 64);
    for (uint16_t i = 0; i < loopCount; ++i) {
        AscendC::Reg::MaskReg pregLoop =
            AscendC::Reg::UpdateMask<float>(remaining);
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert find_check(report, "hardware_loop_var_mutation").passed


def test_no_update_mask_passes():
    """No UpdateMask calls means no mutation check triggered."""
    source = '''
template <typename T>
__simd_vf__ inline void GoodVf(__ubuf__ T* dst, uint32_t n)
{
    for (uint16_t i = 0; i < n; ++i) {
        AscendC::Reg::LoadAlign<float, AscendC::Reg::LoadDist::DIST_NORM>(
            dst, dst + i);
    }
}
'''
    report = check_regbase_source(source, "dummy", raise_on_failure=False)
    assert find_check(report, "hardware_loop_var_mutation").passed
