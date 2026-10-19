#include "kernel_operator.h"
#include <cstdint>

using namespace AscendC;
constexpr uint32_t UB_BLOCK_SIZE = 32;

namespace CustomRegImpl {

constexpr AscendC::Reg::CastTrait castTraitF162F32 = {
    AscendC::Reg::RegLayout::ZERO,
    AscendC::Reg::SatMode::UNKNOWN,
    AscendC::Reg::MaskMergeMode::ZEROING,
    AscendC::RoundMode::UNKNOWN,
};

constexpr AscendC::Reg::CastTrait castTraitF322F16 = {
    AscendC::Reg::RegLayout::ZERO,
    AscendC::Reg::SatMode::NO_SAT,
    AscendC::Reg::MaskMergeMode::ZEROING,
    AscendC::RoundMode::CAST_RINT,
};

// Direct Adds for float / half (input dtype == output dtype).
template <typename T>
__simd_vf__ inline void AddsRegImpl(__ubuf__ T *dst, __ubuf__ T *src, T scalarValue,
    const uint32_t calCount)
{
    AscendC::Reg::RegTensor<T> srcReg;
    AscendC::Reg::RegTensor<T> dstReg;
    uint32_t count = static_cast<uint32_t>(calCount);
    constexpr uint32_t oneRepSize = AscendC::GetVecLen() / sizeof(T);
    AscendC::Reg::MaskReg mask;
    uint16_t repeatTime = static_cast<uint16_t>(
        (calCount + oneRepSize - 1) / oneRepSize);
    for (uint16_t i = 0; i < repeatTime; ++i) {
        mask = AscendC::Reg::UpdateMask<T, AscendC::Reg::RegTensor<T>::trait>(count);
        AscendC::Reg::LoadAlign(srcReg, src + i * oneRepSize);
        AscendC::Reg::Adds<T, T, AscendC::Reg::MaskMergeMode::ZEROING>(dstReg, srcReg, scalarValue, mask);
        AscendC::Reg::StoreAlign(dst + i * oneRepSize, dstReg, mask);
    }
}

// Bfloat16 path: hardware Reg::Adds does not support bf16, so cast to fp32 internally
// but input/output remain bf16 (output is not upgraded to fp32).
__simd_vf__ inline void AddsRegImplBf16(__ubuf__ bfloat16_t *dst, __ubuf__ bfloat16_t *src,
    float scalarValue, const uint32_t calCount)
{
    // DIST_UNPACK_B16 loads 64 packed bf16 elements and produces 64 float lanes;
    // DIST_PACK_B32 stores 64 bf16 elements back in packed format.
    constexpr uint32_t oneRepSize = AscendC::GetVecLen() / sizeof(float); // 64
    AscendC::Reg::RegTensor<bfloat16_t> srcReg;
    AscendC::Reg::RegTensor<bfloat16_t> dstReg;
    AscendC::Reg::RegTensor<float> fp32Reg;
    uint32_t sreg = calCount;
    AscendC::Reg::MaskReg mask;
    uint16_t repeatTime = static_cast<uint16_t>((calCount + oneRepSize - 1) / oneRepSize);
    for (uint16_t i = 0; i < repeatTime; ++i) {
        mask = AscendC::Reg::UpdateMask<float>(sreg);
        AscendC::Reg::LoadAlign<bfloat16_t, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(srcReg, src + i * oneRepSize);
        AscendC::Reg::Cast<float, bfloat16_t, castTraitF162F32>(fp32Reg, srcReg, mask);
        AscendC::Reg::Adds<float, float, AscendC::Reg::MaskMergeMode::ZEROING>(fp32Reg, fp32Reg, scalarValue, mask);
        AscendC::Reg::Cast<bfloat16_t, float, castTraitF322F16>(dstReg, fp32Reg, mask);
        AscendC::Reg::StoreAlign<bfloat16_t, AscendC::Reg::StoreDist::DIST_PACK_B32>(dst + i * oneRepSize, dstReg, mask);
    }
}

template <typename T>
__aicore__ inline void AddsImpl(const AscendC::LocalTensor<T> &dst,
    const AscendC::LocalTensor<T> &src, const T &scalarValue,
    const int32_t calCount)
{
    __ubuf__ T *dstUb = (__ubuf__ T *)dst.GetPhyAddr();
    __ubuf__ T *srcUb = (__ubuf__ T *)src.GetPhyAddr();
    AddsRegImpl<T>(dstUb, srcUb, scalarValue, static_cast<uint32_t>(calCount));
}

} // namespace CustomRegImpl

struct AddsTilingData
{
    uint32_t totalLength;
    float scalarValue;
    uint32_t dtype; // 0: float32, 1: half/fp16, 2: bfloat16_t
};

template <typename T>
__aicore__ inline void CopyTilingData(T *tiling, GM_ADDR tilingGM) {
    uint8_t *dst = reinterpret_cast<uint8_t *>(tiling);
    auto *src = reinterpret_cast<__gm__ uint8_t *>(tilingGM);
    for (size_t i = 0; i < sizeof(T); ++i) {
        dst[i] = src[i];
    }
}

template <typename T>
__aicore__ inline void DataCopyInTensor1D(LocalTensor<T>& dst, GlobalTensor<T>& gm, uint32_t len)
{
    DataCopyExtParams copyParams{
        static_cast<uint16_t>(1),
        static_cast<uint32_t>(len * sizeof(T)),
        static_cast<uint32_t>(0),
        static_cast<uint32_t>(0),
        0
    };
    DataCopyPadExtParams<T> padParams{
        false,
        static_cast<uint8_t>(0),
        static_cast<uint8_t>(0),
        static_cast<T>(0)
    };
    DataCopyPad(dst, gm[0], copyParams, padParams);
}

template <typename T>
__aicore__ inline void DataCopyOutTensor1D(GlobalTensor<T>& gm, LocalTensor<T>& src, uint32_t len)
{
    DataCopyExtParams copyParams{
        static_cast<uint16_t>(1),
        static_cast<uint32_t>(len * sizeof(T)),
        static_cast<uint32_t>(0),
        static_cast<uint32_t>(0),
        0
    };
    DataCopyPad(gm[0], src, copyParams);
}

template <typename T>
__aicore__ inline void RunAdds(GM_ADDR x, GM_ADDR y, GM_ADDR workspace, GM_ADDR tiling,
        uint32_t totalLength, float scalar)
{
    (void)workspace;
    uint32_t ubSize = AscendC::CeilDivision(totalLength * sizeof(T), UB_BLOCK_SIZE) * UB_BLOCK_SIZE;

    TPipe pipe;
    TQue<TPosition::VECIN, 1> inQueueX;
    TQue<TPosition::VECOUT, 1> outQueueY;
    GlobalTensor<T> xGm;
    GlobalTensor<T> yGm;

    xGm.SetGlobalBuffer((__gm__ T*)x, totalLength);
    yGm.SetGlobalBuffer((__gm__ T*)y, totalLength);

    pipe.InitBuffer(inQueueX, 1, ubSize);
    pipe.InitBuffer(outQueueY, 1, ubSize);

    LocalTensor<T> xLocal = inQueueX.AllocTensor<T>();
    DataCopyInTensor1D<T>(xLocal, xGm, totalLength);
    inQueueX.EnQue(xLocal);

    xLocal = inQueueX.DeQue<T>();
    LocalTensor<T> yLocal = outQueueY.AllocTensor<T>();

    if constexpr (AscendC::IsSameType<T, bfloat16_t>::value) {
        __ubuf__ bfloat16_t *dstUb = (__ubuf__ bfloat16_t *)yLocal.GetPhyAddr();
        __ubuf__ bfloat16_t *srcUb = (__ubuf__ bfloat16_t *)xLocal.GetPhyAddr();
        CustomRegImpl::AddsRegImplBf16(dstUb, srcUb, scalar, static_cast<int32_t>(totalLength));
    } else if constexpr (AscendC::IsSameType<T, half>::value) {
        half scalarValue = static_cast<half>(scalar);
        CustomRegImpl::AddsImpl<half>(yLocal, xLocal, scalarValue, static_cast<int32_t>(totalLength));
    } else {
        CustomRegImpl::AddsImpl<float>(yLocal, xLocal, scalar, static_cast<int32_t>(totalLength));
    }

    outQueueY.EnQue<T>(yLocal);
    inQueueX.FreeTensor(xLocal);
    yLocal = outQueueY.DeQue<T>();
    DataCopyOutTensor1D<T>(yGm, yLocal, totalLength);
    outQueueY.FreeTensor(yLocal);
}

extern "C" __global__ __aicore__ void adds(GM_ADDR x, GM_ADDR y, GM_ADDR workspace, GM_ADDR tiling)
{
    (void)workspace;
    AddsTilingData tilingData_;
    CopyTilingData(&tilingData_, tiling);
    uint32_t totalLength = tilingData_.totalLength;
    float scalarValue = tilingData_.scalarValue;
    uint32_t dtype = tilingData_.dtype;

    if (dtype == 0) {
        RunAdds<float>(x, y, workspace, tiling, totalLength, scalarValue);
    } else if (dtype == 1) {
        RunAdds<half>(x, y, workspace, tiling, totalLength, scalarValue);
    } else if (dtype == 2) {
        RunAdds<bfloat16_t>(x, y, workspace, tiling, totalLength, scalarValue);
    }
}
