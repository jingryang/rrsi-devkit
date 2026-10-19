#include "kernel_operator.h"
#include <cstdint>

using namespace AscendC;
constexpr uint32_t UB_BLOCK_SIZE = 32;

// ==========================================================================
// RegBase Cast implementation for f32 <-> f16 only
// ==========================================================================
namespace CustomRegImpl {

constexpr AscendC::Reg::CastTrait castTraitF322F16 = {
    AscendC::Reg::RegLayout::ZERO,
    AscendC::Reg::SatMode::NO_SAT,
    AscendC::Reg::MaskMergeMode::ZEROING,
    AscendC::RoundMode::CAST_RINT,
};

constexpr AscendC::Reg::CastTrait castTraitF162F32 = {
    AscendC::Reg::RegLayout::ZERO,
    AscendC::Reg::SatMode::UNKNOWN,
    AscendC::Reg::MaskMergeMode::ZEROING,
    AscendC::RoundMode::UNKNOWN,
};

__simd_vf__ inline void CastRegImplF32ToF16(
    __ubuf__ half *dst, __ubuf__ float *src, const uint32_t calCount)
{
    constexpr uint32_t oneRepSize = AscendC::GetVecLen() / sizeof(float); // 64
    uint32_t sreg = static_cast<uint32_t>(calCount);
    AscendC::Reg::MaskReg mask;
    AscendC::Reg::RegTensor<float> srcReg;
    AscendC::Reg::RegTensor<half> dstReg;
    uint16_t repeatTime = static_cast<uint16_t>((calCount + oneRepSize - 1) / oneRepSize);

    for (uint16_t i = 0; i < repeatTime; ++i) {
        mask = AscendC::Reg::UpdateMask<float, AscendC::Reg::RegTensor<float>::trait>(sreg);
        AscendC::Reg::LoadAlign(srcReg, src + i * oneRepSize);
        AscendC::Reg::Cast<half, float, castTraitF322F16>(dstReg, srcReg, mask);
        AscendC::Reg::StoreAlign<half, AscendC::Reg::StoreDist::DIST_PACK_B32>(dst + i * oneRepSize, dstReg, mask);
    }
}

__simd_vf__ inline void CastRegImplF16ToF32(
    __ubuf__ float *dst, __ubuf__ half *src, const uint32_t calCount)
{
    constexpr uint32_t oneRepSize = AscendC::GetVecLen() / sizeof(float); // 64
    uint32_t sreg = static_cast<uint32_t>(calCount);
    AscendC::Reg::MaskReg mask;
    AscendC::Reg::RegTensor<half> srcReg;
    AscendC::Reg::RegTensor<float> dstReg;
    uint16_t repeatTime = static_cast<uint16_t>((calCount + oneRepSize - 1) / oneRepSize);

    for (uint16_t i = 0; i < repeatTime; ++i) {
        mask = AscendC::Reg::UpdateMask<float, AscendC::Reg::RegTensor<float>::trait>(sreg);
        AscendC::Reg::LoadAlign<half, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(srcReg, src + i * oneRepSize);
        AscendC::Reg::Cast<float, half, castTraitF162F32>(dstReg, srcReg, mask);
        AscendC::Reg::StoreAlign(dst + i * oneRepSize, dstReg, mask);
    }
}

} // namespace CustomRegImpl

struct CastCustomTilingData
{
    uint32_t totalLength;
    uint32_t mode; // 0: f32 -> f16, 1: f16 -> f32
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
        static_cast<T>(0.0)
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

extern "C" __global__ __aicore__ void cast(GM_ADDR x, GM_ADDR y, GM_ADDR workspace, GM_ADDR tiling)
{
    CastCustomTilingData tilingData_;
    CopyTilingData(&tilingData_, tiling);
    uint32_t totalLength = tilingData_.totalLength;
    uint32_t mode = tilingData_.mode;

    TPipe pipe;
    TQue<TPosition::VECIN, 1> inQueueX;
    TQue<TPosition::VECOUT, 1> outQueueY;
    GlobalTensor<float> xGmF32;
    GlobalTensor<half>  xGmF16;
    GlobalTensor<float> yGmF32;
    GlobalTensor<half>  yGmF16;

    if (mode == 0) {
        // f32 -> f16
        uint32_t inputAlign = AscendC::CeilDivision(totalLength * sizeof(float), UB_BLOCK_SIZE) * UB_BLOCK_SIZE / sizeof(float);
        uint32_t outputAlign = AscendC::CeilDivision(totalLength * sizeof(half), UB_BLOCK_SIZE) * UB_BLOCK_SIZE / sizeof(half);

        xGmF32.SetGlobalBuffer((__gm__ float*)x, totalLength);
        yGmF16.SetGlobalBuffer((__gm__ half*)y, totalLength);

        pipe.InitBuffer(inQueueX, 1, inputAlign * sizeof(float));
        pipe.InitBuffer(outQueueY, 1, outputAlign * sizeof(half));

        LocalTensor<float> xLocal = inQueueX.AllocTensor<float>();
        DataCopyInTensor1D<float>(xLocal, xGmF32, totalLength);
        inQueueX.EnQue(xLocal);

        xLocal = inQueueX.DeQue<float>();
        LocalTensor<half> yLocal = outQueueY.AllocTensor<half>();

        __ubuf__ half *yUb = reinterpret_cast<__ubuf__ half*>(yLocal.GetPhyAddr());
        __ubuf__ float *xUb = reinterpret_cast<__ubuf__ float*>(xLocal.GetPhyAddr());
        CustomRegImpl::CastRegImplF32ToF16(yUb, xUb, totalLength);

        outQueueY.EnQue<half>(yLocal);
        inQueueX.FreeTensor(xLocal);
        yLocal = outQueueY.DeQue<half>();
        DataCopyOutTensor1D<half>(yGmF16, yLocal, totalLength);
        outQueueY.FreeTensor(yLocal);
    } else {
        // f16 -> f32
        uint32_t inputAlign = AscendC::CeilDivision(totalLength * sizeof(half), UB_BLOCK_SIZE) * UB_BLOCK_SIZE / sizeof(half);
        uint32_t outputAlign = AscendC::CeilDivision(totalLength * sizeof(float), UB_BLOCK_SIZE) * UB_BLOCK_SIZE / sizeof(float);

        xGmF16.SetGlobalBuffer((__gm__ half*)x, totalLength);
        yGmF32.SetGlobalBuffer((__gm__ float*)y, totalLength);

        pipe.InitBuffer(inQueueX, 1, inputAlign * sizeof(half));
        pipe.InitBuffer(outQueueY, 1, outputAlign * sizeof(float));

        LocalTensor<half> xLocal = inQueueX.AllocTensor<half>();
        DataCopyInTensor1D<half>(xLocal, xGmF16, totalLength);
        inQueueX.EnQue(xLocal);

        xLocal = inQueueX.DeQue<half>();
        LocalTensor<float> yLocal = outQueueY.AllocTensor<float>();

        __ubuf__ float *yUb = reinterpret_cast<__ubuf__ float*>(yLocal.GetPhyAddr());
        __ubuf__ half *xUb = reinterpret_cast<__ubuf__ half*>(xLocal.GetPhyAddr());
        CustomRegImpl::CastRegImplF16ToF32(yUb, xUb, totalLength);

        outQueueY.EnQue<float>(yLocal);
        inQueueX.FreeTensor(xLocal);
        yLocal = outQueueY.DeQue<float>();
        DataCopyOutTensor1D<float>(yGmF32, yLocal, totalLength);
        outQueueY.FreeTensor(yLocal);
    }
}
