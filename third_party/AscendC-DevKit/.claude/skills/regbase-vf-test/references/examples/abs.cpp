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

// Direct Abs for float / half (input dtype == output dtype).
template <typename T>
__simd_vf__ inline void AbsRegImpl(__ubuf__ T *dst, __ubuf__ T *src, const uint32_t count)
{
    constexpr uint32_t oneRepSize = AscendC::GetVecLen() / sizeof(T);
    AscendC::Reg::RegTensor<T> srcReg;
    AscendC::Reg::RegTensor<T> dstReg;
    uint32_t sreg = count;
    AscendC::Reg::MaskReg mask;
    uint16_t repeatTime = static_cast<uint16_t>((count + oneRepSize - 1) / oneRepSize);
    for (uint16_t i = 0; i < repeatTime; ++i) {
        mask = AscendC::Reg::UpdateMask<T, AscendC::Reg::RegTensor<T>::trait>(sreg);
        AscendC::Reg::LoadAlign(srcReg, src + i * oneRepSize);
        AscendC::Reg::Abs<T, AscendC::Reg::MaskMergeMode::ZEROING>(dstReg, srcReg, mask);
        AscendC::Reg::StoreAlign(dst + i * oneRepSize, dstReg, mask);
    }
}

// Bfloat16 path: hardware Reg::Abs does not support bf16, so cast to fp32 internally
// but input/output remain bf16 (output is not upgraded to fp32).
__simd_vf__ inline void AbsRegImplBf16(__ubuf__ bfloat16_t *dst, __ubuf__ bfloat16_t *src, const uint32_t count)
{
    // DIST_UNPACK_B16 loads 64 packed bf16 elements and produces 64 float lanes;
    // DIST_PACK_B32 stores 64 bf16 elements back in packed format.
    constexpr uint32_t oneRepSize = AscendC::GetVecLen() / sizeof(float); // 64
    AscendC::Reg::RegTensor<bfloat16_t> srcReg;
    AscendC::Reg::RegTensor<bfloat16_t> dstReg;
    AscendC::Reg::RegTensor<float> fp32Reg;
    uint32_t sreg = count;
    AscendC::Reg::MaskReg mask;
    uint16_t repeatTime = static_cast<uint16_t>((count + oneRepSize - 1) / oneRepSize);
    for (uint16_t i = 0; i < repeatTime; ++i) {
        mask = AscendC::Reg::UpdateMask<float>(sreg);
        AscendC::Reg::LoadAlign<bfloat16_t, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(srcReg, src + i * oneRepSize);
        AscendC::Reg::Cast<float, bfloat16_t, castTraitF162F32>(fp32Reg, srcReg, mask);
        AscendC::Reg::Abs<float, AscendC::Reg::MaskMergeMode::ZEROING>(fp32Reg, fp32Reg, mask);
        AscendC::Reg::Cast<bfloat16_t, float, castTraitF322F16>(dstReg, fp32Reg, mask);
        AscendC::Reg::StoreAlign<bfloat16_t, AscendC::Reg::StoreDist::DIST_PACK_B32>(dst + i * oneRepSize, dstReg, mask);
    }
}

template <typename T>
__aicore__ inline void AbsImpl(const AscendC::LocalTensor<T> &dst,
    const AscendC::LocalTensor<T> &src, const int32_t calCount)
{
    __ubuf__ T *dstUb = (__ubuf__ T *)dst.GetPhyAddr();
    __ubuf__ T *srcUb = (__ubuf__ T *)src.GetPhyAddr();
    if constexpr (AscendC::IsSameType<T, bfloat16_t>::value) {
        AbsRegImplBf16(dstUb, srcUb, static_cast<uint32_t>(calCount));
    } else {
        AbsRegImpl<T>(dstUb, srcUb, static_cast<uint32_t>(calCount));
    }
}

} // namespace CustomRegImpl

struct AbsTilingData
{
    uint32_t totalLength;
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
__aicore__ inline void RunAbs(GM_ADDR x, GM_ADDR y, GM_ADDR workspace, GM_ADDR tiling, uint32_t totalLength)
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

    CustomRegImpl::AbsImpl<T>(yLocal, xLocal, static_cast<int32_t>(totalLength));

    outQueueY.EnQue<T>(yLocal);
    inQueueX.FreeTensor(xLocal);
    yLocal = outQueueY.DeQue<T>();
    DataCopyOutTensor1D<T>(yGm, yLocal, totalLength);
    outQueueY.FreeTensor(yLocal);
}

extern "C" __global__ __aicore__ void abs(GM_ADDR x, GM_ADDR y, GM_ADDR workspace, GM_ADDR tiling)
{
    (void)workspace;
    AbsTilingData tilingData_;
    CopyTilingData(&tilingData_, tiling);
    uint32_t totalLength = tilingData_.totalLength;
    uint32_t dtype = tilingData_.dtype;

    if (dtype == 0) {
        RunAbs<float>(x, y, workspace, tiling, totalLength);
    } else if (dtype == 1) {
        RunAbs<half>(x, y, workspace, tiling, totalLength);
    } else if (dtype == 2) {
        RunAbs<bfloat16_t>(x, y, workspace, tiling, totalLength);
    }
}
