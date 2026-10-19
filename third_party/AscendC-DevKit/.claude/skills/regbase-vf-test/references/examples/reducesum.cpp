#include "kernel_operator.h"
#include <cstdint>

using namespace AscendC;
constexpr uint32_t UB_BLOCK_SIZE = 32;

// ==========================================================================
// Inlined cast_common helpers for float / half / bfloat16_t inputs
// ==========================================================================
namespace CustomRegImpl {

constexpr AscendC::Reg::CastTrait castTraitF162F32 = {
    AscendC::Reg::RegLayout::ZERO,
    AscendC::Reg::SatMode::UNKNOWN,
    AscendC::Reg::MaskMergeMode::ZEROING,
    AscendC::RoundMode::UNKNOWN,
};

// Load 64 source elements (float / half / bfloat16_t) and cast to float lanes.
template <typename T_IN>
__simd_callee__ inline void LoadTensorForDtypeTIn(
    __ubuf__ T_IN* src, AscendC::Reg::RegTensor<float>& dst, AscendC::Reg::MaskReg& preg, uint32_t offset)
{
    if constexpr (AscendC::IsSameType<T_IN, float>::value) {
        AscendC::Reg::LoadAlign<float, AscendC::Reg::LoadDist::DIST_NORM>(dst, src + offset);
    } else {
        // half and bfloat16_t share the same load+cast path
        AscendC::Reg::RegTensor<T_IN> xIn;
        AscendC::Reg::LoadAlign<T_IN, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(xIn, src + offset);
        AscendC::Reg::Cast<float, T_IN, castTraitF162F32>(dst, xIn, preg);
    }
}

constexpr uint32_t DEFAULT_VL_FP32 = 64;
constexpr uint32_t DEFAULT_BLK_B32 = 8;
constexpr int32_t  NUM_ONE = 1;
constexpr int32_t  NUM_TWO = 2;

template <typename T>
__simd_vf__ inline void ReduceSumLessThanVL(
    __ubuf__ float* dstUb,
    __ubuf__ T* srcUb,
    uint16_t        rows,
    uint32_t        colAlign,
    uint32_t        cols)
{
    AscendC::Reg::RegTensor<float> x;
    AscendC::Reg::RegTensor<float> vMean;
    AscendC::Reg::MaskReg pregLoop = AscendC::Reg::UpdateMask<float>(cols);
    AscendC::Reg::MaskReg pregOne  = AscendC::Reg::CreateMask<float, AscendC::Reg::MaskPattern::VL1>();

    for (uint16_t i = 0; i < rows; ++i) {
        uint32_t offset = i * colAlign;
        LoadTensorForDtypeTIn<T>(srcUb, x, pregLoop, offset);
        AscendC::Reg::ReduceSum(vMean, x, pregLoop);
        AscendC::Reg::StoreAlign<float, AscendC::Reg::StoreDist::DIST_FIRST_ELEMENT_B32>(dstUb + i, vMean, pregOne);
    }
}

template <typename T>
__simd_vf__ inline void ReduceSumLessThanTwoVL(
    __ubuf__ float* dstUb,
    __ubuf__ T* srcUb,
    uint16_t        rows,
    uint32_t        colAlign,
    uint32_t        cols)
{
    uint32_t tailLen = cols - DEFAULT_VL_FP32;
    AscendC::Reg::RegTensor<float> x;
    AscendC::Reg::RegTensor<float> xFold;
    AscendC::Reg::RegTensor<float> sumReg;
    AscendC::Reg::RegTensor<float> vMean;
    AscendC::Reg::MaskReg pregFull = AscendC::Reg::CreateMask<float, AscendC::Reg::MaskPattern::ALL>();
    AscendC::Reg::MaskReg pregOne  = AscendC::Reg::CreateMask<float, AscendC::Reg::MaskPattern::VL1>();
    AscendC::Reg::MaskReg pregTail = AscendC::Reg::UpdateMask<float>(tailLen);

    for (uint16_t i = 0; i < rows; ++i) {
        uint32_t baseOffset = i * colAlign;
        LoadTensorForDtypeTIn<T>(srcUb, x, pregFull, baseOffset);
        LoadTensorForDtypeTIn<T>(srcUb, xFold, pregTail, baseOffset + DEFAULT_VL_FP32);
        AscendC::Reg::ShiftLefts(
            reinterpret_cast<AscendC::Reg::RegTensor<uint32_t>&>(xFold),
            reinterpret_cast<AscendC::Reg::RegTensor<uint32_t>&>(xFold),
            static_cast<int16_t>(0), pregTail);
        AscendC::Reg::Add(sumReg, x, xFold, pregFull);
        AscendC::Reg::ReduceSum(vMean, sumReg, pregFull);
        AscendC::Reg::StoreAlign<float, AscendC::Reg::StoreDist::DIST_FIRST_ELEMENT_B32>(dstUb + i, vMean, pregOne);
    }
}

template <typename T, int32_t LAST_LOOP_NUMS>
__simd_vf__ inline void ReduceSumCommon(
    __ubuf__ float* dstUb,
    __ubuf__ T* srcUb,
    __ubuf__ float* tmpUb,
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

    AscendC::Reg::RegTensor<float> x;
    AscendC::Reg::RegTensor<float> xFold;
    AscendC::Reg::RegTensor<float> sumReg;
    AscendC::Reg::RegTensor<float> vMean;
    AscendC::Reg::MaskReg pregFull = AscendC::Reg::CreateMask<float, AscendC::Reg::MaskPattern::ALL>();
    AscendC::Reg::MaskReg pregOne  = AscendC::Reg::CreateMask<float, AscendC::Reg::MaskPattern::VL1>();
    AscendC::Reg::MaskReg pregLoop;

    for (uint16_t i = 0; i < rows; ++i) {
        uint32_t baseOffset = i * colAlign;

        for (uint16_t r = 0; r < binaryAddRemainderFloorLoop; ++r) {
            uint32_t offset = r * DEFAULT_VL_FP32 + baseOffset;
            LoadTensorForDtypeTIn<T>(srcUb, x, pregFull, offset);
            LoadTensorForDtypeTIn<T>(srcUb, xFold, pregFull, offset + binAddQuotient);
            AscendC::Reg::Add(sumReg, x, xFold, pregFull);
            AscendC::Reg::ReduceSum(vMean, sumReg, pregFull);
            AscendC::Reg::StoreAlign<float, AscendC::Reg::StoreDist::DIST_FIRST_ELEMENT_B32>(
                tmpUb + i * lastBinaryAddNumAlign + r, vMean, pregOne);
        }

        uint32_t sregRemainder = binaryAddRemainder - binaryAddRemainderFloorLoop * DEFAULT_VL_FP32;
        for (uint16_t r = 0; r < static_cast<uint16_t>(binaryAddRemainderCeilLoop - binaryAddRemainderFloorLoop); ++r) {
            uint32_t offset = baseOffset;
            pregLoop = AscendC::Reg::UpdateMask<float>(sregRemainder);
            LoadTensorForDtypeTIn<T>(srcUb, x, pregFull, offset + binaryAddRemainderFloorLoop * DEFAULT_VL_FP32);
            LoadTensorForDtypeTIn<T>(srcUb, xFold, pregLoop, offset + binaryAddRemainderFloorLoop * DEFAULT_VL_FP32 + binAddQuotient);
            AscendC::Reg::ShiftLefts(
                reinterpret_cast<AscendC::Reg::RegTensor<uint32_t>&>(xFold),
                reinterpret_cast<AscendC::Reg::RegTensor<uint32_t>&>(xFold),
                static_cast<int16_t>(0), pregLoop);
            AscendC::Reg::Add(sumReg, x, xFold, pregFull);
            AscendC::Reg::ReduceSum(vMean, sumReg, pregFull);
            AscendC::Reg::StoreAlign<float, AscendC::Reg::StoreDist::DIST_FIRST_ELEMENT_B32>(
                tmpUb + i * lastBinaryAddNumAlign + binaryAddRemainderFloorLoop, vMean, pregOne);
        }

        for (uint16_t r = 0; r < static_cast<uint16_t>(binaryAddQuotientLoop - binaryAddRemainderCeilLoop); ++r) {
            uint32_t offset = r * DEFAULT_VL_FP32 + baseOffset;
            LoadTensorForDtypeTIn<T>(srcUb, x, pregFull, offset + binaryAddRemainderCeilLoop * DEFAULT_VL_FP32);
            AscendC::Reg::ReduceSum(vMean, x, pregFull);
            AscendC::Reg::StoreAlign<float, AscendC::Reg::StoreDist::DIST_FIRST_ELEMENT_B32>(
                tmpUb + i * lastBinaryAddNumAlign + binaryAddRemainderCeilLoop + r, vMean, pregOne);
        }
    }

    AscendC::Reg::LocalMemBar<AscendC::Reg::MemType::VEC_STORE, AscendC::Reg::MemType::VEC_LOAD>();
    if constexpr (LAST_LOOP_NUMS == 1) {
        AscendC::Reg::MaskReg pregLast = AscendC::Reg::UpdateMask<float>(lastBinaryAddNum);
        for (uint16_t i = 0; i < rows; ++i) {
            LoadTensorForDtypeTIn<float>(tmpUb, x, pregLast, i * lastBinaryAddNumAlign);
            AscendC::Reg::ReduceSum(vMean, x, pregLast);
            AscendC::Reg::StoreAlign<float, AscendC::Reg::StoreDist::DIST_FIRST_ELEMENT_B32>(dstUb + i, vMean, pregOne);
        }
    } else if constexpr (LAST_LOOP_NUMS == 2) {
        uint32_t lastTail = lastBinaryAddNum - DEFAULT_VL_FP32;
        AscendC::Reg::MaskReg pregLast = AscendC::Reg::UpdateMask<float>(lastTail);
        for (uint16_t i = 0; i < rows; ++i) {
            LoadTensorForDtypeTIn<float>(tmpUb, x, pregFull, i * lastBinaryAddNumAlign);
            LoadTensorForDtypeTIn<float>(tmpUb, xFold, pregLast, i * lastBinaryAddNumAlign + DEFAULT_VL_FP32);
            AscendC::Reg::ShiftLefts(
                reinterpret_cast<AscendC::Reg::RegTensor<uint32_t>&>(xFold),
                reinterpret_cast<AscendC::Reg::RegTensor<uint32_t>&>(xFold),
                static_cast<int16_t>(0), pregLast);
            AscendC::Reg::Add(sumReg, x, xFold, pregFull);
            AscendC::Reg::ReduceSum(vMean, sumReg, pregFull);
            AscendC::Reg::StoreAlign<float, AscendC::Reg::StoreDist::DIST_FIRST_ELEMENT_B32>(dstUb + i, vMean, pregOne);
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
__aicore__ inline void ReduceSumImpl(
    const AscendC::LocalTensor<float> &dst,
    const AscendC::LocalTensor<T> &src,
    const AscendC::LocalTensor<float> &tmp,
    uint32_t        rows,
    uint32_t        cols)
{
    constexpr uint32_t vlFp32 = DEFAULT_VL_FP32;

    __ubuf__ float* dstUb = reinterpret_cast<__ubuf__ float*>(dst.GetPhyAddr());
    __ubuf__ T* srcUb = reinterpret_cast<__ubuf__ T*>(src.GetPhyAddr());
    __ubuf__ float* tmpUb = reinterpret_cast<__ubuf__ float*>(tmp.GetPhyAddr());

    uint16_t u16Rows = static_cast<uint16_t>(rows);
    uint32_t colAlign = ((cols * sizeof(T) + UB_BLOCK_SIZE - 1) / UB_BLOCK_SIZE) * UB_BLOCK_SIZE / sizeof(T);
    uint32_t binAddQuotient = ComputeBinAddQuotient(colAlign);
    if (cols <= vlFp32) {
        ReduceSumLessThanVL<T>(dstUb, srcUb, u16Rows, colAlign, cols);
    } else if (cols <= vlFp32 + vlFp32) {
        ReduceSumLessThanTwoVL<T>(dstUb, srcUb, u16Rows, colAlign, cols);
    } else if (cols <= vlFp32 * vlFp32 * NUM_TWO) {
        ReduceSumCommon<T, NUM_ONE>(dstUb, srcUb, tmpUb, u16Rows, colAlign, cols, binAddQuotient);
    } else {
        ReduceSumCommon<T, NUM_TWO>(dstUb, srcUb, tmpUb, u16Rows, colAlign, cols, binAddQuotient);
    }
}

} // namespace CustomRegImpl

struct ReduceSumTilingData
{
    uint32_t A;
    uint32_t R;
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
        static_cast<T>(0)
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

template <typename T>
__aicore__ inline void RunReduceSum(GM_ADDR x, GM_ADDR y, GM_ADDR workspace, GM_ADDR tiling,
        uint32_t A, uint32_t R)
{
    uint32_t rAlign = AscendC::CeilDivision(R * sizeof(T), UB_BLOCK_SIZE) * UB_BLOCK_SIZE / sizeof(T);

    TPipe pipe;
    TQue<TPosition::VECIN, 1> inQueueX;
    TQue<TPosition::VECOUT, 1> outQueueY;
    TBuf<TPosition::VECCALC> tmpBuf;
    GlobalTensor<T> xGm;
    GlobalTensor<float> yGm;

    xGm.SetGlobalBuffer((__gm__ T*)x, A * R);
    yGm.SetGlobalBuffer((__gm__ float*)y, A);

    uint32_t colAlign = rAlign;
    uint32_t binAddQuotient = CustomRegImpl::ComputeBinAddQuotient(colAlign);
    uint16_t binaryAddQuotientLoop = static_cast<uint16_t>((binAddQuotient + CustomRegImpl::DEFAULT_VL_FP32 - 1) / CustomRegImpl::DEFAULT_VL_FP32);
    uint32_t lastBinaryAddNumAlign = ((binaryAddQuotientLoop + CustomRegImpl::DEFAULT_BLK_B32 - 1) / CustomRegImpl::DEFAULT_BLK_B32) * CustomRegImpl::DEFAULT_BLK_B32;
    uint32_t tmpSize = lastBinaryAddNumAlign * A * sizeof(float);

    pipe.InitBuffer(inQueueX, 1, A * rAlign * sizeof(T));
    pipe.InitBuffer(outQueueY, 1, AscendC::CeilDivision(A * sizeof(float), UB_BLOCK_SIZE) * UB_BLOCK_SIZE);
    pipe.InitBuffer(tmpBuf, tmpSize);

    LocalTensor<T> xLocal = inQueueX.AllocTensor<T>();
    DataCopyInTensor2D<T>(xLocal, xGm, 0, A, R, rAlign);
    inQueueX.EnQue(xLocal);

    xLocal = inQueueX.DeQue<T>();
    LocalTensor<float> yLocal = outQueueY.AllocTensor<float>();
    LocalTensor<float> tmpLocal = tmpBuf.Get<float>();

    CustomRegImpl::ReduceSumImpl<T>(yLocal, xLocal, tmpLocal, A, R);

    outQueueY.EnQue<float>(yLocal);
    inQueueX.FreeTensor(xLocal);
    yLocal = outQueueY.DeQue<float>();
    DataCopyOutTensor1D<float>(yGm, yLocal, 0, A);
    outQueueY.FreeTensor(yLocal);
}

extern "C" __global__ __aicore__ void reducesum(GM_ADDR x, GM_ADDR y, GM_ADDR workspace, GM_ADDR tiling)
{
    ReduceSumTilingData tilingData_;
    CopyTilingData(&tilingData_, tiling);
    uint32_t A = tilingData_.A;
    uint32_t R = tilingData_.R;
    uint32_t dtype = tilingData_.dtype;

    if (dtype == 0) {
        RunReduceSum<float>(x, y, workspace, tiling, A, R);
    } else if (dtype == 1) {
        RunReduceSum<half>(x, y, workspace, tiling, A, R);
    } else if (dtype == 2) {
        RunReduceSum<bfloat16_t>(x, y, workspace, tiling, A, R);
    }
}
