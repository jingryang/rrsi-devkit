#include "kernel_operator.h"
#include <cstdint>

using namespace AscendC;
constexpr uint32_t UB_BLOCK_SIZE = 32;

namespace CustomRegImpl {

template <typename T>
__simd_vf__ inline void DuplicateRegImpl(__ubuf__ T *dst, const T scalarValue, const uint32_t calCount)
{
    constexpr uint32_t oneRepSize = AscendC::GetVecLen() / sizeof(T);
    AscendC::Reg::RegTensor<T> dstReg;
    uint32_t sreg = static_cast<uint32_t>(calCount);
    AscendC::Reg::MaskReg mask;
    uint16_t repeatTime = static_cast<uint16_t>((calCount + oneRepSize - 1) / oneRepSize);
    for (uint16_t i = 0; i < repeatTime; ++i) {
        mask = AscendC::Reg::UpdateMask<T, AscendC::Reg::RegTensor<T>::trait>(sreg);
        AscendC::Reg::Duplicate(dstReg, scalarValue, mask);
        AscendC::Reg::StoreAlign(dst + i * oneRepSize, dstReg, mask);
    }
}

template <typename T>
__aicore__ inline void DuplicateImpl(const AscendC::LocalTensor<T> &dst,
    const T scalarValue, const uint32_t calCount)
{
    __ubuf__ T *dstUb = (__ubuf__ T *)dst.GetPhyAddr();
    DuplicateRegImpl<T>(dstUb, scalarValue, calCount);
}

} // namespace CustomRegImpl

struct DuplicateCustomTilingData
{
    uint32_t totalLength;
    float scalarValue;
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

extern "C" __global__ __aicore__ void duplicate(GM_ADDR x, GM_ADDR y, GM_ADDR workspace, GM_ADDR tiling)
{
    (void)x;
    (void)workspace;
    DuplicateCustomTilingData tilingData_;
    CopyTilingData(&tilingData_, tiling);
    uint32_t totalLength = tilingData_.totalLength;
    float scalarValue = tilingData_.scalarValue;
    uint32_t ubSize = AscendC::CeilDivision(totalLength * sizeof(float), UB_BLOCK_SIZE) * UB_BLOCK_SIZE;

    TPipe pipe;
    TQue<TPosition::VECOUT, 1> outQueueY;
    GlobalTensor<float> yGm;

    yGm.SetGlobalBuffer((__gm__ float*)y, totalLength);

    pipe.InitBuffer(outQueueY, 1, ubSize);

    LocalTensor<float> yLocal = outQueueY.AllocTensor<float>();

    CustomRegImpl::DuplicateImpl<float>(yLocal, scalarValue, totalLength);

    outQueueY.EnQue<float>(yLocal);
    yLocal = outQueueY.DeQue<float>();
    DataCopyOutTensor1D(yGm, yLocal, totalLength);
    outQueueY.FreeTensor(yLocal);
}
