#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Pytest coverage for realistic full RegBase kernel sources, both clean and
with injected errors."""

from conftest import find_check

from KernelStaticCheck import check_regbase_source


def test_realistic_regbase_source_passes():
    """A realistic RegBase-style source that follows all rules should pass."""
    source = '''
#include "kernel_operator.h"
#include <cstdint>

using namespace AscendC;
constexpr uint32_t UB_BLOCK_SIZE = 32;

namespace CustomRegImpl {

constexpr uint32_t DEFAULT_VL_FP32 = 64;

template <typename T>
__simd_vf__ inline void ReduceSumCore(
    __ubuf__ float* dstUb,
    __ubuf__ T* srcUb,
    uint16_t rows,
    uint32_t colAlign,
    uint32_t cols)
{
    AscendC::Reg::RegTensor<float> x;
    AscendC::Reg::RegTensor<float> vMean;
    AscendC::Reg::MaskReg pregLoop = AscendC::Reg::UpdateMask<float>(cols);
    AscendC::Reg::MaskReg pregOne = AscendC::Reg::CreateMask<float, AscendC::Reg::MaskPattern::VL1>();

    for (uint16_t i = 0; i < rows; ++i) {
        uint32_t offset = i * colAlign;
        AscendC::Reg::LoadAlign<float, AscendC::Reg::LoadDist::DIST_NORM>(x, srcUb + offset);
        AscendC::Reg::ReduceSum(vMean, x, pregLoop);
        AscendC::Reg::StoreAlign<float, AscendC::Reg::StoreDist::DIST_FIRST_ELEMENT_B32>(dstUb + i, vMean, pregOne);
    }
}

} // namespace CustomRegImpl

struct ReduceSumTilingData {
    uint32_t A;
    uint32_t R;
};

template <typename T>
__aicore__ inline void CopyTilingData(T *tiling, GM_ADDR tilingGM) {
    uint8_t *dst = reinterpret_cast<uint8_t *>(tiling);
    auto *src = reinterpret_cast<__gm__ uint8_t *>(tilingGM);
    for (size_t i = 0; i < sizeof(T); ++i) {
        dst[i] = src[i];
    }
}

extern "C" __global__ __aicore__ void reducesum_custom(
    GM_ADDR x, GM_ADDR y, GM_ADDR workspace, GM_ADDR tiling)
{
    ReduceSumTilingData tilingData_;
    CopyTilingData(&tilingData_, tiling);
    uint32_t A = tilingData_.A;
    uint32_t R = tilingData_.R;
    uint32_t rAlign = AscendC::CeilDivision(R * sizeof(float), UB_BLOCK_SIZE) * UB_BLOCK_SIZE / sizeof(float);

    TPipe pipe;
    TQue<TPosition::VECIN, 1> inQueueX;
    TQue<TPosition::VECOUT, 1> outQueueY;
    GlobalTensor<float> xGm;
    GlobalTensor<float> yGm;

    xGm.SetGlobalBuffer((__gm__ float*)x, A * R);
    yGm.SetGlobalBuffer((__gm__ float*)y, A);

    pipe.InitBuffer(inQueueX, 1, A * rAlign * sizeof(float));
    pipe.InitBuffer(outQueueY, 1, A * sizeof(float));

    LocalTensor<float> xLocal = inQueueX.AllocTensor<float>();
    DataCopy(xLocal, xGm, A * R);
    inQueueX.EnQue(xLocal);

    xLocal = inQueueX.DeQue<float>();
    LocalTensor<float> yLocal = outQueueY.AllocTensor<float>();

    CustomRegImpl::ReduceSumCore<float>(yLocal, xLocal, A, rAlign, R);

    outQueueY.EnQue<float>(yLocal);
    inQueueX.FreeTensor(xLocal);
    yLocal = outQueueY.DeQue<float>();
    DataCopy(yGm, yLocal, A);
    outQueueY.FreeTensor(yLocal);
}
'''
    report = check_regbase_source(source, "reducesum_custom", raise_on_failure=False)
    assert report.passed, str(report)


def test_realistic_regbase_source_with_injected_error_fails():
    """The same realistic source with an injected runtime if should fail."""
    source = '''
#include "kernel_operator.h"

namespace CustomRegImpl {

template <typename T>
__simd_vf__ inline void ReduceSumCore(
    __ubuf__ float* dstUb,
    __ubuf__ T* srcUb,
    uint16_t rows,
    uint32_t colAlign,
    uint32_t cols)
{
    AscendC::Reg::RegTensor<float> x;
    AscendC::Reg::RegTensor<float> vMean;
    AscendC::Reg::MaskReg pregLoop = AscendC::Reg::UpdateMask<float>(cols);

    for (uint16_t i = 0; i < rows; ++i) {
        if (i == 0) {
            uint32_t offset = i * colAlign;
            AscendC::Reg::LoadAlign<float, AscendC::Reg::LoadDist::DIST_NORM>(x, srcUb + offset);
            AscendC::Reg::ReduceSum(vMean, x, pregLoop);
        }
    }
}

} // namespace CustomRegImpl

extern "C" __global__ __aicore__ void reducesum_custom(GM_ADDR x, GM_ADDR y, GM_ADDR workspace, GM_ADDR tiling)
{
}
'''
    report = check_regbase_source(source, "reducesum_custom", raise_on_failure=False)
    assert not report.passed
    assert not find_check(report, "hardware_loop_branch").passed


def test_simple_kernel_without_simd_passes():
    """A simple non-RegBase kernel should not trigger VF-specific checks."""
    source = '''
#include "kernel_operator.h"

extern "C" __global__ __aicore__ void add_custom(
    __gm__ uint8_t* x, __gm__ uint8_t* y, __gm__ uint8_t* z,
    uint32_t totalLength)
{
    // Simple AscendC vector code without __simd_vf__
    for (int i = 0; i < totalLength; ++i) {
        // ordinary scalar loop in __aicore__ is allowed
    }
}
'''
    report = check_regbase_source(source, "add_custom", raise_on_failure=False)
    assert report.passed, str(report)


def test_realistic_regbase_with_bad_update_mask_mutation_fails():
    source = '''
#include "kernel_operator.h"

namespace CustomRegImpl {

template <typename T>
__simd_vf__ inline void BadReduce(
    __ubuf__ float* dstUb,
    __ubuf__ T* srcUb,
    uint16_t rows,
    uint32_t colAlign,
    uint32_t cols)
{
    AscendC::Reg::RegTensor<float> x;
    AscendC::Reg::RegTensor<float> vMean;

    for (uint16_t i = 0; i < rows; ++i) {
        AscendC::Reg::MaskReg pregLoop = AscendC::Reg::UpdateMask<float>(cols);
        uint32_t offset = i * colAlign;
        AscendC::Reg::LoadAlign<float, AscendC::Reg::LoadDist::DIST_NORM>(x, srcUb + offset);
        AscendC::Reg::ReduceSum(vMean, x, pregLoop);
        cols -= colAlign;
    }
}

} // namespace CustomRegImpl

extern "C" __global__ __aicore__ void reducesum_custom(GM_ADDR x, GM_ADDR y, GM_ADDR workspace, GM_ADDR tiling)
{
}
'''
    report = check_regbase_source(source, "reducesum_custom", raise_on_failure=False)
    assert not report.passed
    assert not find_check(report, "hardware_loop_var_mutation").passed


def test_realistic_regbase_with_gm_in_vf_fails():
    source = '''
#include "kernel_operator.h"

namespace CustomRegImpl {

template <typename T>
__simd_vf__ inline void BadReduce(
    __ubuf__ float* dstUb,
    GM_ADDR srcGm,
    uint16_t rows,
    uint32_t colAlign,
    uint32_t cols)
{
    for (uint16_t i = 0; i < rows; ++i) {
    }
}

} // namespace CustomRegImpl

extern "C" __global__ __aicore__ void reducesum_custom(GM_ADDR x, GM_ADDR y, GM_ADDR workspace, GM_ADDR tiling)
{
}
'''
    report = check_regbase_source(source, "reducesum_custom", raise_on_failure=False)
    assert not report.passed
    assert not find_check(report, "simd_vf_no_gm").passed


def test_realistic_regbase_with_function_level_if_fails():
    source = '''
#include "kernel_operator.h"

namespace CustomRegImpl {

template <typename T>
__simd_vf__ inline void BadReduce(
    __ubuf__ float* dstUb,
    __ubuf__ T* srcUb,
    uint16_t rows,
    uint32_t colAlign,
    uint32_t cols)
{
    if (rows > 0) {
        for (uint16_t i = 0; i < rows; ++i) {
        }
    }
}

} // namespace CustomRegImpl

extern "C" __global__ __aicore__ void reducesum_custom(GM_ADDR x, GM_ADDR y, GM_ADDR workspace, GM_ADDR tiling)
{
}
'''
    report = check_regbase_source(source, "reducesum_custom", raise_on_failure=False)
    assert not report.passed
    assert not find_check(report, "vf_function_level_branch").passed


def test_realistic_kernel_with_templated_simd_callee_passes():
    source = '''
#include "kernel_operator.h"

template <typename T>
__simd_callee__ inline void Helper(AscendC::Reg::RegTensor<T>& r, uint32_t n)
{
    for (uint16_t i = 0; i < n; ++i) {
        AscendC::Reg::Duplicate(r, 0.0f);
    }
}

template <typename T>
__simd_vf__ inline void GoodVf(__ubuf__ T* dst, uint32_t n)
{
    AscendC::Reg::RegTensor<T> r;
    Helper(r, n);
}

extern "C" __global__ __aicore__ void kernel_custom(GM_ADDR x, GM_ADDR y, GM_ADDR workspace, GM_ADDR tiling)
{
}
'''
    report = check_regbase_source(source, "kernel_custom", raise_on_failure=False)
    assert report.passed, str(report)
