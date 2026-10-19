#include "kernel_operator.h"
#include <cstdint>

using namespace AscendC;
constexpr uint32_t UB_BLOCK_SIZE = 32;

struct MulCustomTilingData
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
__simd_vf__ inline void MulRegImpl(__ubuf__ T *dst, __ubuf__ T *src0, __ubuf__ T *src1,
    const int32_t calCount)
{
    constexpr uint32_t oneRepSize = AscendC::GetVecLen() / sizeof(T);
    AscendC::Reg::RegTensor<T> src0Reg;
    AscendC::Reg::RegTensor<T> src1Reg;
    AscendC::Reg::RegTensor<T> dstReg;
    uint32_t sreg = static_cast<uint32_t>(calCount);
    AscendC::Reg::MaskReg mask;
    uint16_t repeatTime = static_cast<uint16_t>(
        (static_cast<uint32_t>(calCount) + oneRepSize - 1) / oneRepSize);
    for (uint16_t i = 0; i < repeatTime; ++i) {
        mask = AscendC::Reg::UpdateMask<T, AscendC::Reg::RegTensor<T>::trait>(sreg);
        AscendC::Reg::LoadAlign(src0Reg, src0 + i * oneRepSize);
        AscendC::Reg::LoadAlign(src1Reg, src1 + i * oneRepSize);
        AscendC::Reg::Mul<T, AscendC::Reg::MaskMergeMode::ZEROING>(dstReg, src0Reg, src1Reg, mask);
        AscendC::Reg::StoreAlign(dst + i * oneRepSize, dstReg, mask);
    }
}

template <typename T>
__aicore__ inline void MulImpl(const AscendC::LocalTensor<T> &dst,
    const AscendC::LocalTensor<T> &src0, const AscendC::LocalTensor<T> &src1,
    const int32_t calCount)
{
    __ubuf__ T *dstUb = reinterpret_cast<__ubuf__ T *>(dst.GetPhyAddr());
    __ubuf__ T *src0Ub = reinterpret_cast<__ubuf__ T *>(src0.GetPhyAddr());
    __ubuf__ T *src1Ub = reinterpret_cast<__ubuf__ T *>(src1.GetPhyAddr());
    MulRegImpl<T>(dstUb, src0Ub, src1Ub, calCount);
}

} // namespace CustomRegImpl

extern "C" __global__ __aicore__ void mul(GM_ADDR x0, GM_ADDR x1, GM_ADDR y,
    GM_ADDR workspace, GM_ADDR tiling)
{
    MulCustomTilingData tilingData_;
    CopyTilingData(&tilingData_, tiling);
    uint32_t totalLength = tilingData_.totalLength;
    uint32_t lenAlign = AscendC::CeilDivision(totalLength * sizeof(float), UB_BLOCK_SIZE) *
                        UB_BLOCK_SIZE / sizeof(float);

    TPipe pipe;
    TQue<TPosition::VECIN, 1> inQueueX0;
    TQue<TPosition::VECIN, 1> inQueueX1;
    TQue<TPosition::VECOUT, 1> outQueueY;
    GlobalTensor<float> x0Gm;
    GlobalTensor<float> x1Gm;
    GlobalTensor<float> yGm;

    x0Gm.SetGlobalBuffer((__gm__ float *)x0, totalLength);
    x1Gm.SetGlobalBuffer((__gm__ float *)x1, totalLength);
    yGm.SetGlobalBuffer((__gm__ float *)y, totalLength);

    pipe.InitBuffer(inQueueX0, 1, lenAlign * sizeof(float));
    pipe.InitBuffer(inQueueX1, 1, lenAlign * sizeof(float));
    pipe.InitBuffer(outQueueY, 1, lenAlign * sizeof(float));

    LocalTensor<float> x0Local = inQueueX0.AllocTensor<float>();
    LocalTensor<float> x1Local = inQueueX1.AllocTensor<float>();
    DataCopyInTensor1D<float>(x0Local, x0Gm, totalLength);
    DataCopyInTensor1D<float>(x1Local, x1Gm, totalLength);
    inQueueX0.EnQue(x0Local);
    inQueueX1.EnQue(x1Local);

    x0Local = inQueueX0.DeQue<float>();
    x1Local = inQueueX1.DeQue<float>();
    LocalTensor<float> yLocal = outQueueY.AllocTensor<float>();

    CustomRegImpl::MulImpl<float>(yLocal, x0Local, x1Local, totalLength);

    outQueueY.EnQue<float>(yLocal);
    inQueueX0.FreeTensor(x0Local);
    inQueueX1.FreeTensor(x1Local);

    yLocal = outQueueY.DeQue<float>();
    DataCopyOutTensor1D<float>(yGm, yLocal, totalLength);
    outQueueY.FreeTensor(yLocal);
}
