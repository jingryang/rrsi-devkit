#include "kernel_operator.h"

using namespace AscendC;
constexpr uint32_t UB_BLOCK_SIZE = 32;

template <typename T>
__aicore__ inline void CopyTilingData(T *tiling, GM_ADDR tilingGM) {
    uint8_t *dst = reinterpret_cast<uint8_t *>(tiling);
    auto *src = reinterpret_cast<__gm__ uint8_t *>(tilingGM);
    for (size_t i = 0; i < sizeof(T); ++i) {
        dst[i] = src[i];
    }
}

template <typename T>
__aicore__ inline void DataCopyInTensor1D(LocalTensor<T>& dst, GlobalTensor<T>& gm, uint64_t gmOffset,
        uint32_t len)
{
    DataCopyExtParams copyParams{
        static_cast<uint16_t>(1),                  // blockCount
        static_cast<uint32_t>(len * sizeof(T)),    // blockLen
        static_cast<uint32_t>(0),                  // srcStride
        static_cast<uint32_t>(0),                  // dstStride
        0                                          // rsv
    };
    DataCopyPadExtParams<T> padParams{
        false,                   // isPad
        static_cast<uint8_t>(0), // leftPadding
        static_cast<uint8_t>(0), // rightPadding
        static_cast<T>(0.0)      // paddingValue
    };
    DataCopyPad(dst, gm[gmOffset], copyParams, padParams);
}

template <typename T>
__aicore__ inline void DataCopyOutTensor1D(GlobalTensor<T>& gm, LocalTensor<T>& src, uint64_t gmOffset,
        uint32_t len)
{
    DataCopyExtParams copyParams{
        static_cast<uint16_t>(1),                  // blockCount
        static_cast<uint32_t>(len * sizeof(T)),    // blockLen
        static_cast<uint32_t>(0),          // srcStride
        static_cast<uint32_t>(0),                  // dstStride
        0                                          // rsv
    };
    DataCopyPad(gm[gmOffset], src, copyParams);
}

// 混合类型 tiling 结构体
struct MixedTilingData {
    uint64_t totalLength;   // 数据长度
    float    eps;           // 浮点偏置
    float    repeat;        // 重复次数
};

__aicore__ inline void MixedCompute(LocalTensor<float>& dst, LocalTensor<float>& src,
            float repeat, float eps, uint32_t len)
{
    Muls(src, src, repeat, len);
    PipeBarrier<PIPE_V>();
    Adds(dst, src, eps, len);
}

extern "C" __global__ __aicore__ void mixed_tiling_custom(
    GM_ADDR x, GM_ADDR y, GM_ADDR workspace, GM_ADDR tiling)
{
    MixedTilingData tilingData_;
    CopyTilingData(&tilingData_, tiling);

    uint32_t blockLength = tilingData_.totalLength / GetBlockNum();
    uint32_t blockLengthAlign = AscendC::CeilDivision(blockLength * sizeof(float), UB_BLOCK_SIZE) * UB_BLOCK_SIZE / sizeof(float);

    TPipe pipe;
    TQue<TPosition::VECIN, 1> inQueueX;
    TQue<TPosition::VECOUT, 1> outQueueY;
    GlobalTensor<float> xGm;
    GlobalTensor<float> yGm;

    xGm.SetGlobalBuffer((__gm__ float*)x + blockLength * GetBlockIdx(), blockLength);
    yGm.SetGlobalBuffer((__gm__ float*)y + blockLength * GetBlockIdx(), blockLength);

    pipe.InitBuffer(inQueueX, 1, blockLengthAlign * sizeof(float));
    pipe.InitBuffer(outQueueY, 1, blockLengthAlign * sizeof(float));

    LocalTensor<float> xLocal = inQueueX.AllocTensor<float>();
    DataCopyInTensor1D<float>(xLocal, xGm, 0, blockLength);
    inQueueX.EnQue(xLocal);

    xLocal = inQueueX.DeQue<float>();
    LocalTensor<float> yLocal = outQueueY.AllocTensor<float>();

    MixedCompute(yLocal, xLocal, tilingData_.repeat, tilingData_.eps, blockLength);

    outQueueY.EnQue<float>(yLocal);
    inQueueX.FreeTensor(xLocal);

    yLocal = outQueueY.DeQue<float>();
    DataCopyOutTensor1D<float>(yGm, yLocal, 0, blockLength);
    outQueueY.FreeTensor(yLocal);
}
