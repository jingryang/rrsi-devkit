#include "kernel_operator.h"
#include <cstdint>
#include <cfloat>

using namespace AscendC;
constexpr uint32_t UB_BLOCK_SIZE = 32;

// ==========================================================================
// RegBase ReduceMax implementation
// ==========================================================================
namespace CustomRegImpl {

constexpr uint32_t DEFAULT_VL_FP32 = 64;
constexpr uint32_t DEFAULT_BLK_B32 = 8;
constexpr int32_t  NUM_ONE = 1;
constexpr int32_t  NUM_TWO = 2;

template <typename T>
__simd_vf__ inline void ReduceMaxLessThanVL(
    __ubuf__ T* dstUb,
    __ubuf__ T* srcUb,
    uint16_t        rows,
    uint32_t        colAlign,
    uint32_t        cols)
{
    AscendC::Reg::RegTensor<T> x;
    AscendC::Reg::RegTensor<T> vMax;
    AscendC::Reg::MaskReg pregLoop = AscendC::Reg::UpdateMask<T>(cols);
    AscendC::Reg::MaskReg pregOne  = AscendC::Reg::CreateMask<T, AscendC::Reg::MaskPattern::VL1>();

    for (uint16_t i = 0; i < rows; ++i) {
        uint32_t offset = i * colAlign;
        AscendC::Reg::LoadAlign(x, srcUb + offset);
        AscendC::Reg::ReduceMax<T, AscendC::Reg::MaskMergeMode::ZEROING>(vMax, x, pregLoop);
        AscendC::Reg::StoreAlign<T, AscendC::Reg::StoreDist::DIST_FIRST_ELEMENT_B32>(dstUb + i, vMax, pregOne);
    }
}

template <typename T>
__simd_vf__ inline void ReduceMaxLessThanTwoVL(
    __ubuf__ T* dstUb,
    __ubuf__ T* srcUb,
    uint16_t        rows,
    uint32_t        colAlign,
    uint32_t        cols)
{
    uint32_t tailLen = cols - DEFAULT_VL_FP32;
    AscendC::Reg::RegTensor<T> x;
    AscendC::Reg::RegTensor<T> xFold;
    AscendC::Reg::RegTensor<T> maxReg;
    AscendC::Reg::RegTensor<T> vMax;
    AscendC::Reg::RegTensor<T> negInf;
    AscendC::Reg::MaskReg pregFull = AscendC::Reg::CreateMask<T, AscendC::Reg::MaskPattern::ALL>();
    AscendC::Reg::MaskReg pregOne  = AscendC::Reg::CreateMask<T, AscendC::Reg::MaskPattern::VL1>();
    AscendC::Reg::MaskReg pregTail = AscendC::Reg::UpdateMask<T>(tailLen);

    AscendC::Reg::Duplicate(negInf, T(-FLT_MAX), pregFull);
    for (uint16_t i = 0; i < rows; ++i) {
        uint32_t baseOffset = i * colAlign;
        AscendC::Reg::LoadAlign(x, srcUb + baseOffset);
        AscendC::Reg::LoadAlign(xFold, srcUb + baseOffset + DEFAULT_VL_FP32);
        AscendC::Reg::Select(xFold, xFold, negInf, pregTail);
        AscendC::Reg::Max<T, AscendC::Reg::MaskMergeMode::ZEROING>(maxReg, x, xFold, pregFull);
        AscendC::Reg::ReduceMax<T, AscendC::Reg::MaskMergeMode::ZEROING>(vMax, maxReg, pregFull);
        AscendC::Reg::StoreAlign<T, AscendC::Reg::StoreDist::DIST_FIRST_ELEMENT_B32>(dstUb + i, vMax, pregOne);
    }
}

template <typename T, int32_t LAST_LOOP_NUMS>
__simd_vf__ inline void ReduceMaxCommon(
    __ubuf__ T* dstUb,
    __ubuf__ T* srcUb,
    __ubuf__ T* tmpUb,
    uint16_t        rows,
    uint32_t        colAlign,
    uint32_t        cols,
    uint32_t        binAddQuotient)
{
    uint16_t binaryAddQuotientLoop = static_cast<uint16_t>((binAddQuotient + DEFAULT_VL_FP32 - 1) / DEFAULT_VL_FP32);
    uint32_t lastBinaryAddNum      = binAddQuotient / DEFAULT_VL_FP32;
    uint32_t lastBinaryAddNumAlign = (binaryAddQuotientLoop + DEFAULT_BLK_B32 - 1) / DEFAULT_BLK_B32 * DEFAULT_BLK_B32;

    uint32_t binaryAddRemainder       = cols - binAddQuotient;
    uint16_t binaryAddRemainderCeilLoop = static_cast<uint16_t>((binaryAddRemainder + DEFAULT_VL_FP32 - 1) / DEFAULT_VL_FP32);
    uint16_t binaryAddRemainderFloorLoop = static_cast<uint16_t>(binaryAddRemainder / DEFAULT_VL_FP32);

    AscendC::Reg::RegTensor<T> x;
    AscendC::Reg::RegTensor<T> xFold;
    AscendC::Reg::RegTensor<T> maxReg;
    AscendC::Reg::RegTensor<T> vMax;
    AscendC::Reg::RegTensor<T> negInf;
    AscendC::Reg::MaskReg pregFull = AscendC::Reg::CreateMask<T, AscendC::Reg::MaskPattern::ALL>();
    AscendC::Reg::MaskReg pregOne  = AscendC::Reg::CreateMask<T, AscendC::Reg::MaskPattern::VL1>();
    AscendC::Reg::MaskReg pregLoop;

    AscendC::Reg::Duplicate(negInf, T(-FLT_MAX), pregFull);

    for (uint16_t i = 0; i < rows; ++i) {
        uint32_t baseOffset = i * colAlign;

        for (uint16_t r = 0; r < binaryAddRemainderFloorLoop; ++r) {
            uint32_t offset = r * DEFAULT_VL_FP32 + baseOffset;
            AscendC::Reg::LoadAlign(x, srcUb + offset);
            AscendC::Reg::LoadAlign(xFold, srcUb + offset + binAddQuotient);
            AscendC::Reg::Max<T, AscendC::Reg::MaskMergeMode::ZEROING>(maxReg, x, xFold, pregFull);
            AscendC::Reg::ReduceMax<T, AscendC::Reg::MaskMergeMode::ZEROING>(vMax, maxReg, pregFull);
            AscendC::Reg::StoreAlign<T, AscendC::Reg::StoreDist::DIST_FIRST_ELEMENT_B32>(
                tmpUb + i * lastBinaryAddNumAlign + r, vMax, pregOne);
        }

        uint32_t sregRemainder = binaryAddRemainder - binaryAddRemainderFloorLoop * DEFAULT_VL_FP32;
        for (uint16_t r = 0; r < static_cast<uint16_t>(binaryAddRemainderCeilLoop - binaryAddRemainderFloorLoop); ++r) {
            uint32_t offset = baseOffset;
            pregLoop = AscendC::Reg::UpdateMask<T>(sregRemainder);
            AscendC::Reg::LoadAlign(x, srcUb + offset + binaryAddRemainderFloorLoop * DEFAULT_VL_FP32);
            AscendC::Reg::LoadAlign(xFold, srcUb + offset + binaryAddRemainderFloorLoop * DEFAULT_VL_FP32 + binAddQuotient);
            AscendC::Reg::Select(xFold, xFold, negInf, pregLoop);
            AscendC::Reg::Max<T, AscendC::Reg::MaskMergeMode::ZEROING>(maxReg, x, xFold, pregFull);
            AscendC::Reg::ReduceMax<T, AscendC::Reg::MaskMergeMode::ZEROING>(vMax, maxReg, pregFull);
            AscendC::Reg::StoreAlign<T, AscendC::Reg::StoreDist::DIST_FIRST_ELEMENT_B32>(
                tmpUb + i * lastBinaryAddNumAlign + binaryAddRemainderFloorLoop, vMax, pregOne);
        }

        for (uint16_t r = 0; r < static_cast<uint16_t>(binaryAddQuotientLoop - binaryAddRemainderCeilLoop); ++r) {
            uint32_t offset = r * DEFAULT_VL_FP32 + baseOffset;
            AscendC::Reg::LoadAlign(x, srcUb + offset + binaryAddRemainderCeilLoop * DEFAULT_VL_FP32);
            AscendC::Reg::ReduceMax<T, AscendC::Reg::MaskMergeMode::ZEROING>(vMax, x, pregFull);
            AscendC::Reg::StoreAlign<T, AscendC::Reg::StoreDist::DIST_FIRST_ELEMENT_B32>(
                tmpUb + i * lastBinaryAddNumAlign + binaryAddRemainderCeilLoop + r, vMax, pregOne);
        }
    }

    AscendC::Reg::LocalMemBar<AscendC::Reg::MemType::VEC_STORE, AscendC::Reg::MemType::VEC_LOAD>();
    if constexpr (LAST_LOOP_NUMS == 1) {
        AscendC::Reg::MaskReg pregLast = AscendC::Reg::UpdateMask<T>(lastBinaryAddNum);
        for (uint16_t i = 0; i < rows; ++i) {
            AscendC::Reg::LoadAlign(x, tmpUb + i * lastBinaryAddNumAlign);
            AscendC::Reg::ReduceMax<T, AscendC::Reg::MaskMergeMode::ZEROING>(vMax, x, pregLast);
            AscendC::Reg::StoreAlign<T, AscendC::Reg::StoreDist::DIST_FIRST_ELEMENT_B32>(dstUb + i, vMax, pregOne);
        }
    } else if constexpr (LAST_LOOP_NUMS == 2) {
        uint32_t lastTail = lastBinaryAddNum - DEFAULT_VL_FP32;
        AscendC::Reg::MaskReg pregLast = AscendC::Reg::UpdateMask<T>(lastTail);
        for (uint16_t i = 0; i < rows; ++i) {
            AscendC::Reg::LoadAlign(x, tmpUb + i * lastBinaryAddNumAlign);
            AscendC::Reg::LoadAlign(xFold, tmpUb + i * lastBinaryAddNumAlign + DEFAULT_VL_FP32);
            AscendC::Reg::Select(xFold, xFold, negInf, pregLast);
            AscendC::Reg::Max<T, AscendC::Reg::MaskMergeMode::ZEROING>(maxReg, x, xFold, pregFull);
            AscendC::Reg::ReduceMax<T, AscendC::Reg::MaskMergeMode::ZEROING>(vMax, maxReg, pregFull);
            AscendC::Reg::StoreAlign<T, AscendC::Reg::StoreDist::DIST_FIRST_ELEMENT_B32>(dstUb + i, vMax, pregOne);
        }
    }
}

__aicore__ inline uint32_t ComputeBinAddQuotient(uint32_t colAlign)
{
    if (colAlign == 0) return 1;
    uint32_t bq = 1U << (31 - __builtin_clz(colAlign));
    if (bq == colAlign) bq /= 2;
    return bq;
}

template <typename T>
__aicore__ inline void ReduceMaxImpl(
    const AscendC::LocalTensor<T> &dst,
    const AscendC::LocalTensor<T> &src,
    const AscendC::LocalTensor<T> &tmp,
    uint32_t        rows,
    uint32_t        cols)
{
    constexpr uint32_t vlFp32 = DEFAULT_VL_FP32;

    __ubuf__ T* dstUb = reinterpret_cast<__ubuf__ T*>(dst.GetPhyAddr());
    __ubuf__ T* srcUb = reinterpret_cast<__ubuf__ T*>(src.GetPhyAddr());
    __ubuf__ T* tmpUb = reinterpret_cast<__ubuf__ T*>(tmp.GetPhyAddr());

    uint16_t u16Rows = static_cast<uint16_t>(rows);
    uint32_t colAlign = ((cols * sizeof(T) + UB_BLOCK_SIZE - 1) / UB_BLOCK_SIZE) * UB_BLOCK_SIZE / sizeof(T);
    uint32_t binAddQuotient = ComputeBinAddQuotient(colAlign);
    if (cols <= vlFp32) {
        ReduceMaxLessThanVL<T>(dstUb, srcUb, u16Rows, colAlign, cols);
    } else if (cols <= vlFp32 + vlFp32) {
        ReduceMaxLessThanTwoVL<T>(dstUb, srcUb, u16Rows, colAlign, cols);
    } else if (cols <= vlFp32 * vlFp32 * NUM_TWO) {
        ReduceMaxCommon<T, NUM_ONE>(dstUb, srcUb, tmpUb, u16Rows, colAlign, cols, binAddQuotient);
    } else {
        ReduceMaxCommon<T, NUM_TWO>(dstUb, srcUb, tmpUb, u16Rows, colAlign, cols, binAddQuotient);
    }
}

} // namespace CustomRegImpl

struct ReduceMaxCustomTilingData
{
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

template <typename T>
__aicore__ inline void DataCopyInTensor2D(LocalTensor<T>& dst, GlobalTensor<T>& gm, uint64_t gmOffset,
        uint32_t rows, uint32_t cols, uint32_t colsAlign)
{
    uint32_t dstStride = (colsAlign - cols) * sizeof(T) / UB_BLOCK_SIZE;
    DataCopyExtParams copyParams{
        static_cast<uint16_t>(rows),
        static_cast<uint32_t>(cols * sizeof(T)),
        static_cast<uint32_t>(0),
        static_cast<uint32_t>(dstStride),
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
__aicore__ inline void DataCopyOutTensor1D(GlobalTensor<T>& gm, LocalTensor<T>& src, uint64_t gmOffset,
        uint32_t len)
{
    DataCopyExtParams copyParams{
        static_cast<uint16_t>(1),
        static_cast<uint32_t>(len * sizeof(T)),
        static_cast<uint32_t>(0),
        static_cast<uint32_t>(0),
        0
    };
    DataCopyPad(gm[gmOffset], src, copyParams);
}

extern "C" __global__ __aicore__ void reducemax(GM_ADDR x, GM_ADDR y, GM_ADDR workspace, GM_ADDR tiling)
{
    ReduceMaxCustomTilingData tilingData_;
    CopyTilingData(&tilingData_, tiling);
    uint32_t A = tilingData_.A;
    uint32_t R = tilingData_.R;
    uint32_t rAlign = AscendC::CeilDivision(R * sizeof(float), UB_BLOCK_SIZE) * UB_BLOCK_SIZE / sizeof(float);

    TPipe pipe;
    TQue<TPosition::VECIN, 1> inQueueX;
    TQue<TPosition::VECOUT, 1> outQueueY;
    TBuf<TPosition::VECCALC> tmpBuf;
    GlobalTensor<float> xGm;
    GlobalTensor<float> yGm;

    uint32_t srcSize = A * R;
    xGm.SetGlobalBuffer((__gm__ float*)x, srcSize);
    yGm.SetGlobalBuffer((__gm__ float*)y, A);

    uint32_t colAlign = rAlign;
    uint32_t binAddQuotient = CustomRegImpl::ComputeBinAddQuotient(colAlign);
    uint16_t binaryAddQuotientLoop = static_cast<uint16_t>((binAddQuotient + CustomRegImpl::DEFAULT_VL_FP32 - 1) / CustomRegImpl::DEFAULT_VL_FP32);
    uint32_t lastBinaryAddNumAlign = ((binaryAddQuotientLoop + CustomRegImpl::DEFAULT_BLK_B32 - 1) / CustomRegImpl::DEFAULT_BLK_B32) * CustomRegImpl::DEFAULT_BLK_B32;
    uint32_t tmpSize = lastBinaryAddNumAlign * A * sizeof(float);

    pipe.InitBuffer(inQueueX, 1, A * rAlign * sizeof(float));
    pipe.InitBuffer(outQueueY, 1, AscendC::CeilDivision(A * sizeof(float), UB_BLOCK_SIZE) * UB_BLOCK_SIZE);
    pipe.InitBuffer(tmpBuf, tmpSize);

    LocalTensor<float> xLocal = inQueueX.AllocTensor<float>();
    DataCopyInTensor2D(xLocal, xGm, 0, A, R, rAlign);
    inQueueX.EnQue(xLocal);

    xLocal = inQueueX.DeQue<float>();
    LocalTensor<float> yLocal = outQueueY.AllocTensor<float>();
    LocalTensor<float> tmpLocal = tmpBuf.Get<float>();

    CustomRegImpl::ReduceMaxImpl<float>(yLocal, xLocal, tmpLocal, A, R);

    outQueueY.EnQue<float>(yLocal);
    inQueueX.FreeTensor(xLocal);
    yLocal = outQueueY.DeQue<float>();
    DataCopyOutTensor1D(yGm, yLocal, 0, A);
    outQueueY.FreeTensor(yLocal);
}
