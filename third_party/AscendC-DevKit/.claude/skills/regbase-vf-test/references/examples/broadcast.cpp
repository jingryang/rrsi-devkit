#include "kernel_operator.h"
#include <cstdint>

using namespace AscendC;
constexpr uint32_t UB_BLOCK_SIZE = 32;

namespace CustomRegImpl {

template <typename T>
__simd_vf__ inline void RowBroadcast2DRegImpl(
    __ubuf__ T *dst,
    __ubuf__ T *src,
    uint32_t rows,
    uint32_t cols,
    uint32_t colAlign)
{
    constexpr uint32_t oneRepSize = AscendC::GetVecLen() / sizeof(T);

    AscendC::Reg::RegTensor<T> srcReg;
    AscendC::Reg::MaskReg mask;

    uint16_t repeatTime = static_cast<uint16_t>(
        (cols + oneRepSize - 1) / oneRepSize);

    for (uint16_t row = 0; row < static_cast<uint16_t>(rows); ++row) {
        uint32_t sreg = cols;
        for (uint16_t i = 0; i < repeatTime; ++i) {
            mask = AscendC::Reg::UpdateMask<T, AscendC::Reg::RegTensor<T>::trait>(sreg);
            AscendC::Reg::LoadAlign(srcReg, src + i * oneRepSize);
            AscendC::Reg::StoreAlign(dst + row * colAlign + i * oneRepSize, srcReg, mask);
        }
    }
}

template <typename T>
__simd_vf__ inline void ColBroadcast2DRegImpl(
    __ubuf__ T *dst,
    __ubuf__ T *src,
    uint32_t rows,
    uint32_t cols,
    uint32_t colAlign)
{
    constexpr uint32_t oneRepSize = AscendC::GetVecLen() / sizeof(T);

    AscendC::Reg::RegTensor<T> valReg;
    AscendC::Reg::MaskReg mask;

    uint16_t repeatTime = static_cast<uint16_t>(
        (cols + oneRepSize - 1) / oneRepSize);

    for (uint16_t row = 0; row < static_cast<uint16_t>(rows); ++row) {
        AscendC::Reg::LoadAlign<T, AscendC::Reg::LoadDist::DIST_BRC_B32>(
            valReg, src + row);

        uint32_t sreg = cols;
        for (uint16_t i = 0; i < repeatTime; ++i) {
            mask = AscendC::Reg::UpdateMask<T, AscendC::Reg::RegTensor<T>::trait>(sreg);
            AscendC::Reg::StoreAlign(dst + row * colAlign + i * oneRepSize, valReg, mask);
        }
    }
}

template <typename T>
__aicore__ inline void Broadcast2DImpl(
    const AscendC::LocalTensor<T> &dst,
    const AscendC::LocalTensor<T> &src,
    uint32_t rows,
    uint32_t cols,
    uint32_t colAlign,
    uint32_t mode)
{
    __ubuf__ T *dstUb = reinterpret_cast<__ubuf__ T *>(dst.GetPhyAddr());
    __ubuf__ T *srcUb = reinterpret_cast<__ubuf__ T *>(src.GetPhyAddr());
    if (mode == 0) {
        RowBroadcast2DRegImpl<T>(dstUb, srcUb, rows, cols, colAlign);
    } else {
        ColBroadcast2DRegImpl<T>(dstUb, srcUb, rows, cols, colAlign);
    }
}

} // namespace CustomRegImpl

struct BroadcastTilingData {
    uint32_t rows;
    uint32_t cols;
    uint32_t colAlign;
    uint32_t mode;
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

extern "C" __global__ __aicore__ void broadcast(
    GM_ADDR src, GM_ADDR dst, GM_ADDR workspace, GM_ADDR tiling)
{
    BroadcastTilingData td;
    CopyTilingData(&td, tiling);
    uint32_t rows = td.rows;
    uint32_t cols = td.cols;
    uint32_t colAlign = td.colAlign;
    uint32_t mode = td.mode;

    uint32_t srcSize = (mode == 0) ? colAlign : rows;
    uint32_t dstSize = rows * colAlign;

    GlobalTensor<float> srcGm;
    GlobalTensor<float> dstGm;
    srcGm.SetGlobalBuffer((__gm__ float*)src, srcSize);
    dstGm.SetGlobalBuffer((__gm__ float*)dst, dstSize);

    TPipe pipe;
    TQue<TPosition::VECIN, 1> inQueueSrc;
    TQue<TPosition::VECOUT, 1> outQueueDst;

    uint32_t srcBufSize = (mode == 0)
        ? (AscendC::CeilDivision(colAlign * sizeof(float), UB_BLOCK_SIZE) * UB_BLOCK_SIZE)
        : (AscendC::CeilDivision(rows * sizeof(float), UB_BLOCK_SIZE) * UB_BLOCK_SIZE);
    uint32_t dstBufSize = AscendC::CeilDivision(rows * colAlign * sizeof(float), UB_BLOCK_SIZE) * UB_BLOCK_SIZE;

    pipe.InitBuffer(inQueueSrc, 1, srcBufSize);
    pipe.InitBuffer(outQueueDst, 1, dstBufSize);

    LocalTensor<float> srcLocal = inQueueSrc.AllocTensor<float>();
    LocalTensor<float> dstLocal = outQueueDst.AllocTensor<float>();

    if (mode == 0) {
        DataCopyExtParams copyParams{
            1,
            static_cast<uint32_t>(cols * sizeof(float)),
            0,
            0,
            0
        };
        DataCopyPadExtParams<float> padParams{
            false,
            static_cast<uint8_t>(0),
            static_cast<uint8_t>(0),
            static_cast<float>(0.0)
        };
        DataCopyPad(srcLocal, srcGm[0], copyParams, padParams);
    } else {
        DataCopyExtParams copyParams{
            1,
            static_cast<uint32_t>(rows * sizeof(float)),
            0,
            0,
            0
        };
        DataCopyPadExtParams<float> padParams{
            false,
            static_cast<uint8_t>(0),
            static_cast<uint8_t>(0),
            static_cast<float>(0.0)
        };
        DataCopyPad(srcLocal, srcGm[0], copyParams, padParams);
    }
    inQueueSrc.EnQue(srcLocal);

    srcLocal = inQueueSrc.DeQue<float>();

    CustomRegImpl::Broadcast2DImpl<float>(dstLocal, srcLocal, rows, cols, colAlign, mode);

    outQueueDst.EnQue<float>(dstLocal);
    inQueueSrc.FreeTensor(srcLocal);
    dstLocal = outQueueDst.DeQue<float>();
    DataCopyOutTensor2D<float>(dstGm, dstLocal, 0, rows, cols, colAlign);
    outQueueDst.FreeTensor(dstLocal);
}
