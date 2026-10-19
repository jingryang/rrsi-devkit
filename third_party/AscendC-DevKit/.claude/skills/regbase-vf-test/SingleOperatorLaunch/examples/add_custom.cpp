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

struct AddCustomTilingData
{
    uint32_t totalLength;
};

__aicore__ inline void AddCompute(LocalTensor<float>& dst, LocalTensor<float>& xLocal,
            LocalTensor<float>& yLocal, uint32_t len)
{
    Add(dst, xLocal, yLocal, len);
}

extern "C" __global__ __aicore__ void add_custom(GM_ADDR x, GM_ADDR y, GM_ADDR z, GM_ADDR workspace, GM_ADDR tiling)
{
    AddCustomTilingData tilingData_;
    CopyTilingData(&tilingData_, tiling);   // Copy TilingData from GM
    uint32_t blockLength = tilingData_.totalLength / GetBlockNum();
    uint32_t blockLengthAlign = AscendC::CeilDivision(blockLength * sizeof(float), UB_BLOCK_SIZE) * UB_BLOCK_SIZE / sizeof(float);

    TPipe pipe;
    TQue<TPosition::VECIN, 1> inQueueX;
    TQue<TPosition::VECIN, 1> inQueueY;
    TQue<TPosition::VECOUT, 1> outQueueZ;
    GlobalTensor<float> xGm;
    GlobalTensor<float> yGm;
    GlobalTensor<float> zGm;

    xGm.SetGlobalBuffer((__gm__ float*)x + blockLength * GetBlockIdx(), blockLength);
    yGm.SetGlobalBuffer((__gm__ float*)y + blockLength * GetBlockIdx(), blockLength);
    zGm.SetGlobalBuffer((__gm__ float*)z + blockLength * GetBlockIdx(), blockLength);

    // 不开启 Double Buffer
    pipe.InitBuffer(inQueueX, 1, blockLengthAlign * sizeof(float));
    pipe.InitBuffer(inQueueY, 1, blockLengthAlign * sizeof(float));
    pipe.InitBuffer(outQueueZ, 1, blockLengthAlign * sizeof(float));

    LocalTensor<float> xLocal = inQueueX.AllocTensor<float>();
    LocalTensor<float> yLocal = inQueueY.AllocTensor<float>();
    DataCopyInTensor1D<float>(xLocal, xGm, 0, blockLength);
    DataCopyInTensor1D<float>(yLocal, yGm, 0, blockLength);
    inQueueX.EnQue(xLocal);
    inQueueY.EnQue(yLocal);

    xLocal = inQueueX.DeQue<float>();
    yLocal = inQueueY.DeQue<float>();
    LocalTensor<float> zLocal = outQueueZ.AllocTensor<float>();

    AddCompute(zLocal, xLocal, yLocal, blockLength);

    outQueueZ.EnQue<float>(zLocal);
    inQueueX.FreeTensor(xLocal);
    inQueueY.FreeTensor(yLocal);

    zLocal = outQueueZ.DeQue<float>();
    DataCopyOutTensor1D<float>(zGm, zLocal, 0, blockLength);
    outQueueZ.FreeTensor(zLocal);
}
