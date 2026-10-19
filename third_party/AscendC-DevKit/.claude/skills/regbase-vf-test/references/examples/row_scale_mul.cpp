#include "kernel_operator.h"
#include <cstdint>

using namespace AscendC;
constexpr uint32_t UB_BLOCK_SIZE = 32;

namespace CustomRegImpl {

template <typename T>
__simd_vf__ inline void RowScaleMulRegImpl(
    __ubuf__ T *dst,
    __ubuf__ T *src,
    __ubuf__ T *scaleUb,
    __ubuf__ T *weightUb,
    uint32_t rows,
    uint32_t cols,
    uint32_t colAlign)
{
    constexpr uint32_t oneRepSize = AscendC::GetVecLen() / sizeof(T);

    AscendC::Reg::RegTensor<T> xReg;
    AscendC::Reg::RegTensor<T> weightReg;
    AscendC::Reg::RegTensor<T> scaleReg;
    AscendC::Reg::RegTensor<T> tmpReg;
    AscendC::Reg::MaskReg mask;

    uint16_t repeatTime = static_cast<uint16_t>(
        (cols + oneRepSize - 1) / oneRepSize);

    for (uint16_t row = 0; row < static_cast<uint16_t>(rows); ++row) {
        AscendC::Reg::LoadAlign<T, AscendC::Reg::LoadDist::DIST_BRC_B32>(
            scaleReg, scaleUb + row);

        uint32_t sreg = cols;
        for (uint16_t i = 0; i < repeatTime; ++i) {
            mask = AscendC::Reg::UpdateMask<T, AscendC::Reg::RegTensor<T>::trait>(sreg);

            AscendC::Reg::LoadAlign(xReg, src + row * colAlign + i * oneRepSize);
            AscendC::Reg::LoadAlign(weightReg, weightUb + i * oneRepSize);

            AscendC::Reg::Mul<T, AscendC::Reg::MaskMergeMode::ZEROING>(
                tmpReg, xReg, scaleReg, mask);
            AscendC::Reg::Mul<T, AscendC::Reg::MaskMergeMode::ZEROING>(
                tmpReg, tmpReg, weightReg, mask);

            AscendC::Reg::StoreAlign(dst + row * colAlign + i * oneRepSize, tmpReg, mask);
        }
    }
}

template <typename T>
__aicore__ inline void RowScaleMulImpl(
    const AscendC::LocalTensor<T> &dst,
    const AscendC::LocalTensor<T> &src,
    const AscendC::LocalTensor<T> &scale,
    const AscendC::LocalTensor<T> &weight,
    uint32_t rows,
    uint32_t cols,
    uint32_t colAlign)
{
    __ubuf__ T *dstUb = reinterpret_cast<__ubuf__ T *>(dst.GetPhyAddr());
    __ubuf__ T *srcUb = reinterpret_cast<__ubuf__ T *>(src.GetPhyAddr());
    __ubuf__ T *scaleUb = reinterpret_cast<__ubuf__ T *>(scale.GetPhyAddr());
    __ubuf__ T *weightUb = reinterpret_cast<__ubuf__ T *>(weight.GetPhyAddr());
    RowScaleMulRegImpl<T>(dstUb, srcUb, scaleUb, weightUb, rows, cols, colAlign);
}

} // namespace CustomRegImpl

struct RowScaleMulTilingData {
    uint32_t rows;
    uint32_t cols;
    uint32_t colAlign;
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
__aicore__ inline void DataCopyInTensor2D(
    GlobalTensor<T>& gm, LocalTensor<T>& dst, uint64_t gmOffset,
    uint32_t rows, uint32_t cols, uint32_t colsAlign)
{
    uint32_t srcStride = 0;
    uint32_t dstStride = (colsAlign - cols) * sizeof(T) / UB_BLOCK_SIZE;
    DataCopyExtParams copyParams{
        static_cast<uint16_t>(rows),
        static_cast<uint32_t>(cols * sizeof(T)),
        srcStride,
        dstStride,
        0
    };
    DataCopyPadExtParams<T> padParams{
        false,
        static_cast<uint8_t>(0),
        static_cast<uint8_t>(0),
        static_cast<T>(0.0)
    };
    DataCopyPad(dst, gm[gmOffset], copyParams, padParams);
}

template <typename T>
__aicore__ inline void DataCopyInTensor1D(
    GlobalTensor<T>& gm, LocalTensor<T>& dst, uint64_t gmOffset,
    uint32_t len, uint32_t bufAlign)
{
    DataCopyExtParams copyParams{
        1,
        static_cast<uint32_t>(len * sizeof(T)),
        0,
        0,
        0
    };
    DataCopyPadExtParams<T> padParams{
        false,
        static_cast<uint8_t>(0),
        static_cast<uint8_t>(0),
        static_cast<T>(0.0)
    };
    DataCopyPad(dst, gm[gmOffset], copyParams, padParams);
}

template <typename T>
__aicore__ inline void DataCopyOutTensor2D(
    GlobalTensor<T>& gm, LocalTensor<T>& src, uint64_t gmOffset,
    uint32_t rows, uint32_t cols, uint32_t colsAlign)
{
    uint32_t srcStride = (colsAlign - cols) * sizeof(T) / UB_BLOCK_SIZE;
    uint32_t dstStride = 0;
    DataCopyExtParams copyParams{
        static_cast<uint16_t>(rows),
        static_cast<uint32_t>(cols * sizeof(T)),
        srcStride,
        dstStride,
        0
    };
    DataCopyPad(gm[gmOffset], src, copyParams);
}

extern "C" __global__ __aicore__ void row_scale_mul(
    GM_ADDR x, GM_ADDR scale, GM_ADDR weight, GM_ADDR y, GM_ADDR workspace, GM_ADDR tiling)
{
    RowScaleMulTilingData td;
    CopyTilingData(&td, tiling);
    uint32_t rows = td.rows;
    uint32_t cols = td.cols;
    uint32_t colAlign = td.colAlign;

    GlobalTensor<float> xGm;
    GlobalTensor<float> scaleGm;
    GlobalTensor<float> weightGm;
    GlobalTensor<float> yGm;
    xGm.SetGlobalBuffer((__gm__ float*)x, rows * cols);
    scaleGm.SetGlobalBuffer((__gm__ float*)scale, rows);
    weightGm.SetGlobalBuffer((__gm__ float*)weight, cols);
    yGm.SetGlobalBuffer((__gm__ float*)y, rows * cols);

    TPipe pipe;
    TQue<TPosition::VECIN, 1> inQueueX;
    TQue<TPosition::VECIN, 1> inQueueScale;
    TQue<TPosition::VECIN, 1> inQueueWeight;
    TQue<TPosition::VECOUT, 1> outQueueY;

    uint32_t xBufSize = AscendC::CeilDivision(rows * colAlign * sizeof(float), UB_BLOCK_SIZE) * UB_BLOCK_SIZE;
    uint32_t scaleBufSize = AscendC::CeilDivision(rows * sizeof(float), UB_BLOCK_SIZE) * UB_BLOCK_SIZE;
    uint32_t weightBufSize = AscendC::CeilDivision(colAlign * sizeof(float), UB_BLOCK_SIZE) * UB_BLOCK_SIZE;
    uint32_t yBufSize = xBufSize;

    pipe.InitBuffer(inQueueX, 1, xBufSize);
    pipe.InitBuffer(inQueueScale, 1, scaleBufSize);
    pipe.InitBuffer(inQueueWeight, 1, weightBufSize);
    pipe.InitBuffer(outQueueY, 1, yBufSize);

    LocalTensor<float> xLocal = inQueueX.AllocTensor<float>();
    LocalTensor<float> scaleLocal = inQueueScale.AllocTensor<float>();
    LocalTensor<float> weightLocal = inQueueWeight.AllocTensor<float>();
    LocalTensor<float> yLocal = outQueueY.AllocTensor<float>();

    DataCopyInTensor2D<float>(xGm, xLocal, 0, rows, cols, colAlign);
    DataCopyInTensor1D<float>(scaleGm, scaleLocal, 0, rows, rows);
    DataCopyInTensor1D<float>(weightGm, weightLocal, 0, cols, colAlign);

    inQueueX.EnQue(xLocal);
    inQueueScale.EnQue(scaleLocal);
    inQueueWeight.EnQue(weightLocal);

    xLocal = inQueueX.DeQue<float>();
    scaleLocal = inQueueScale.DeQue<float>();
    weightLocal = inQueueWeight.DeQue<float>();

    CustomRegImpl::RowScaleMulImpl<float>(
        yLocal, xLocal, scaleLocal, weightLocal, rows, cols, colAlign);

    outQueueY.EnQue<float>(yLocal);
    inQueueX.FreeTensor(xLocal);
    inQueueScale.FreeTensor(scaleLocal);
    inQueueWeight.FreeTensor(weightLocal);

    yLocal = outQueueY.DeQue<float>();
    DataCopyOutTensor2D<float>(yGm, yLocal, 0, rows, cols, colAlign);
    outQueueY.FreeTensor(yLocal);
}
