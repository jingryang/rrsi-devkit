#include "kernel_operator.h"
#include <cstdint>

using namespace AscendC;
constexpr uint32_t UB_BLOCK_SIZE = 32;

struct RsqrtCustomTilingData
{
    uint32_t totalLength;
};

template <typename T>
__aicore__ inline void CopyTilingData(T *tiling, GM_ADDR tilingGM)
{
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

namespace CustomRegImpl {

template <typename T>
__simd_vf__ inline void RsqrtRegImpl(__ubuf__ T *dst, __ubuf__ T *src, const uint32_t count)
{
    constexpr uint32_t oneRepSize = AscendC::GetVecLen() / sizeof(T);
    AscendC::Reg::RegTensor<T> srcReg;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::RegTensor<T> onesReg;
    AscendC::Reg::RegTensor<T> zerosReg;
    AscendC::Reg::MaskReg fullMask =
        AscendC::Reg::CreateMask<T, AscendC::Reg::MaskPattern::ALL>();
    AscendC::Reg::Duplicate(onesReg, static_cast<T>(1.0f), fullMask);
    AscendC::Reg::Duplicate(zerosReg, static_cast<T>(0.0f), fullMask);

    uint32_t sreg = static_cast<uint32_t>(count);
    AscendC::Reg::MaskReg mask;
    AscendC::Reg::MaskReg cmpMask;
    uint16_t repeatTime = static_cast<uint16_t>((count + oneRepSize - 1) / oneRepSize);
    for (uint16_t i = 0; i < repeatTime; ++i) {
        mask = AscendC::Reg::UpdateMask<T, AscendC::Reg::RegTensor<T>::trait>(sreg);
        AscendC::Reg::LoadAlign(srcReg, src + i * oneRepSize);
        AscendC::Reg::Compares<T, AscendC::CMPMODE::LT>(
            cmpMask, srcReg, static_cast<T>(0.0f), mask);
        AscendC::Reg::Sqrt(srcReg, srcReg, mask);
        AscendC::Reg::Div(dstReg, onesReg, srcReg, mask);
        AscendC::Reg::Select<T>(dstReg, zerosReg, dstReg, cmpMask);
        AscendC::Reg::StoreAlign(dst + i * oneRepSize, dstReg, mask);
    }
}

template <typename T>
__aicore__ inline void RsqrtImpl(const AscendC::LocalTensor<T> &dst,
    const AscendC::LocalTensor<T> &src, const int32_t calCount)
{
    __ubuf__ T *dstUb = reinterpret_cast<__ubuf__ T *>(dst.GetPhyAddr());
    __ubuf__ T *srcUb = reinterpret_cast<__ubuf__ T *>(src.GetPhyAddr());
    RsqrtRegImpl<T>(dstUb, srcUb, static_cast<uint32_t>(calCount));
}

} // namespace CustomRegImpl

extern "C" __global__ __aicore__ void rsqrt(GM_ADDR x, GM_ADDR y,
    GM_ADDR workspace, GM_ADDR tiling)
{
    RsqrtCustomTilingData tilingData_;
    CopyTilingData(&tilingData_, tiling);
    uint32_t totalLength = tilingData_.totalLength;
    uint32_t lenAlign = AscendC::CeilDivision(totalLength * sizeof(float), UB_BLOCK_SIZE) *
                        UB_BLOCK_SIZE / sizeof(float);

    TPipe pipe;
    TQue<TPosition::VECIN, 1> inQueueX;
    TQue<TPosition::VECOUT, 1> outQueueY;
    GlobalTensor<float> xGm;
    GlobalTensor<float> yGm;

    xGm.SetGlobalBuffer((__gm__ float *)x, totalLength);
    yGm.SetGlobalBuffer((__gm__ float *)y, totalLength);

    pipe.InitBuffer(inQueueX, 1, lenAlign * sizeof(float));
    pipe.InitBuffer(outQueueY, 1, lenAlign * sizeof(float));

    LocalTensor<float> xLocal = inQueueX.AllocTensor<float>();
    DataCopyInTensor1D<float>(xLocal, xGm, totalLength);
    inQueueX.EnQue(xLocal);

    xLocal = inQueueX.DeQue<float>();
    LocalTensor<float> yLocal = outQueueY.AllocTensor<float>();

    CustomRegImpl::RsqrtImpl<float>(yLocal, xLocal, totalLength);

    outQueueY.EnQue<float>(yLocal);
    inQueueX.FreeTensor(xLocal);

    yLocal = outQueueY.DeQue<float>();
    DataCopyOutTensor1D<float>(yGm, yLocal, totalLength);
    outQueueY.FreeTensor(yLocal);
}
