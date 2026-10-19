#include "kernel_operator.h"
#include <cstdint>

using namespace AscendC;
constexpr uint32_t UB_BLOCK_SIZE = 32;

// ==========================================================================
// 内联 cast_common.h 中 float 输入所需的部分
// ==========================================================================
namespace CustomRegImpl {

// 从 src 处加载 64 个 T_IN 类型的数据并转换为 64 个 float32 到 dst 寄存器，具体数量由 mask 控制。
template <typename T_IN>
__simd_callee__ inline void LoadTensorForDtypeTIn(
    __ubuf__ T_IN* src, AscendC::Reg::RegTensor<float>& dst, AscendC::Reg::MaskReg& preg, uint32_t offset)
{
    if constexpr (AscendC::IsSameType<T_IN, float>::value) {
        AscendC::Reg::LoadAlign<float, AscendC::Reg::LoadDist::DIST_NORM>(dst, src + offset);
    }
}

} // namespace CustomRegImpl

// ==========================================================================
// 内联 reducesum.h 内容
// ==========================================================================
namespace CustomRegImpl {

constexpr uint32_t DEFAULT_VL_FP32 = 64;      // Vector Length for float
constexpr uint32_t DEFAULT_BLK_B32 = 8;       // BLOCK_SIZE(32) / sizeof(float)(4)
constexpr int32_t  NUM_ONE = 1;
constexpr int32_t  NUM_TWO = 2;

// -------------------------------------------------------------------------
// Branch A: cols <= DEFAULT_VL_FP32
// -------------------------------------------------------------------------
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

// -------------------------------------------------------------------------
// Branch B: DEFAULT_VL_FP32 < cols <= 2*DEFAULT_VL_FP32
// -------------------------------------------------------------------------
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

// -------------------------------------------------------------------------
// Branch C: cols > 2*DEFAULT_VL_FP32  (通用二分累加折叠)
// -------------------------------------------------------------------------
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
    uint32_t sregRemainder = binaryAddRemainder - binaryAddRemainderFloorLoop * DEFAULT_VL_FP32;

    AscendC::Reg::RegTensor<float> x;
    AscendC::Reg::RegTensor<float> xFold;
    AscendC::Reg::RegTensor<float> sumReg;
    AscendC::Reg::RegTensor<float> vMean;
    AscendC::Reg::MaskReg pregFull = AscendC::Reg::CreateMask<float, AscendC::Reg::MaskPattern::ALL>();
    AscendC::Reg::MaskReg pregOne  = AscendC::Reg::CreateMask<float, AscendC::Reg::MaskPattern::VL1>();
    AscendC::Reg::MaskReg pregTail = AscendC::Reg::UpdateMask<float>(sregRemainder);

    // 阶段 1: 行内分块累加，结果暂存 tmpUb
    for (uint16_t i = 0; i < rows; ++i) {
        uint32_t baseOffset = i * colAlign;

        // floor 轮: 成对加载 src 与 src+binAddQuotient，相加后 ReduceSum
        for (uint16_t r = 0; r < binaryAddRemainderFloorLoop; ++r) {
            uint32_t offset = r * DEFAULT_VL_FP32 + baseOffset;
            LoadTensorForDtypeTIn<T>(srcUb, x, pregFull, offset);
            LoadTensorForDtypeTIn<T>(srcUb, xFold, pregFull, offset + binAddQuotient);
            AscendC::Reg::Add(sumReg, x, xFold, pregFull);
            AscendC::Reg::ReduceSum(vMean, sumReg, pregFull);
            AscendC::Reg::StoreAlign<float, AscendC::Reg::StoreDist::DIST_FIRST_ELEMENT_B32>(
                tmpUb + i * lastBinaryAddNumAlign + r, vMean, pregOne);
        }

        // remainder ceil 轮 (处理不足 DEFAULT_VL_FP32 的尾段)
        for (uint16_t r = 0; r < static_cast<uint16_t>(binaryAddRemainderCeilLoop - binaryAddRemainderFloorLoop); ++r) {
            uint32_t offset = baseOffset;
            LoadTensorForDtypeTIn<T>(srcUb, x, pregFull, offset + binaryAddRemainderFloorLoop * DEFAULT_VL_FP32);
            LoadTensorForDtypeTIn<T>(srcUb, xFold, pregTail, offset + binaryAddRemainderFloorLoop * DEFAULT_VL_FP32 + binAddQuotient);
            AscendC::Reg::ShiftLefts(
                reinterpret_cast<AscendC::Reg::RegTensor<uint32_t>&>(xFold),
                reinterpret_cast<AscendC::Reg::RegTensor<uint32_t>&>(xFold),
                static_cast<int16_t>(0), pregTail);
            AscendC::Reg::Add(sumReg, x, xFold, pregFull);
            AscendC::Reg::ReduceSum(vMean, sumReg, pregFull);
            AscendC::Reg::StoreAlign<float, AscendC::Reg::StoreDist::DIST_FIRST_ELEMENT_B32>(
                tmpUb + i * lastBinaryAddNumAlign + binaryAddRemainderFloorLoop, vMean, pregOne);
        }

        // 剩余单独段 (没有配对段，直接 ReduceSum)
        for (uint16_t r = 0; r < static_cast<uint16_t>(binaryAddQuotientLoop - binaryAddRemainderCeilLoop); ++r) {
            uint32_t offset = r * DEFAULT_VL_FP32 + baseOffset;
            LoadTensorForDtypeTIn<T>(srcUb, x, pregFull, offset + binaryAddRemainderCeilLoop * DEFAULT_VL_FP32);
            AscendC::Reg::ReduceSum(vMean, x, pregFull);
            AscendC::Reg::StoreAlign<float, AscendC::Reg::StoreDist::DIST_FIRST_ELEMENT_B32>(
                tmpUb + i * lastBinaryAddNumAlign + binaryAddRemainderCeilLoop + r, vMean, pregOne);
        }
    }

    // 阶段 2: 对 tmpUb 中的中间结果做最后一轮 ReduceSum
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

// -------------------------------------------------------------------------
// 辅助: 计算 binAddQuotient (小于 colAlign 的最大 2 的幂)
// -------------------------------------------------------------------------
__aicore__ inline uint32_t ComputeBinAddQuotient(uint32_t colAlign)
{
    if (colAlign == 0) return 1;
    uint32_t bq = 1U << (31 - __builtin_clz(colAlign));
    if (bq == colAlign) bq /= 2;
    return bq;
}

// -------------------------------------------------------------------------
// 顶层分发函数
// -------------------------------------------------------------------------
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

// ==========================================================================
// Kernel 数据搬运辅助
// ==========================================================================
struct AddCustomTilingData
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

// ==========================================================================
// Kernel 入口
// ==========================================================================
extern "C" __global__ __aicore__ void reducesum_custom(GM_ADDR x, GM_ADDR y, GM_ADDR workspace, GM_ADDR tiling)
{
    AddCustomTilingData tilingData_;
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

    // 计算 tmp 缓冲区大小（始终分配，小 shape 时开销可忽略）
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

    // 调用 RegBase ReduceSumImpl 进行 VF 单元测试
    CustomRegImpl::ReduceSumImpl<float>(yLocal, xLocal, tmpLocal, A, R);

    outQueueY.EnQue<float>(yLocal);
    inQueueX.FreeTensor(xLocal);
    yLocal = outQueueY.DeQue<float>();
    DataCopyOutTensor1D(yGm, yLocal, 0, A);
    outQueueY.FreeTensor(yLocal);
}
