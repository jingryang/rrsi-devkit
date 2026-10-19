#!/usr/bin/env python3
"""
哨兵越界检测示例。

输出数组小于 kernel 写入长度 → DataCopyOut 写入超尾，覆盖哨兵 guard。
"""
import numpy as np
from SingleOperatorLaunch import DeviceInfo, SourceModule, pack_tiling_data, setup_log_separation
setup_log_separation(log_file="log_sentinel_oob.txt", result_file="result_sentinel_oob.txt")

KERNEL_SRC = R'''
#include "kernel_operator.h"
using namespace AscendC;
constexpr uint32_t UB_BLOCK_SIZE = 32;

template <typename T>
__aicore__ inline void CopyTilingData(T *tiling, GM_ADDR tilingGM) {
    uint8_t *dst = reinterpret_cast<uint8_t *>(tiling);
    auto *src = reinterpret_cast<__gm__ uint8_t *>(tilingGM);
    for (size_t i = 0; i < sizeof(T); ++i) { dst[i] = src[i]; }
}

template <typename T>
__aicore__ inline void DataCopyOutTensor1D(GlobalTensor<T>& gm, LocalTensor<T>& src,
        uint64_t gmOffset, uint32_t len) {
    DataCopyExtParams copyParams{1, static_cast<uint32_t>(len * sizeof(T)), 0, 0, 0};
    DataCopyPad(gm[gmOffset], src, copyParams);
}

struct AddTilingData { uint32_t totalLength; };

__aicore__ inline void AddCompute(LocalTensor<float>& dst, LocalTensor<float>& x,
        LocalTensor<float>& y, uint32_t len) { Add(dst, x, y, len); }

extern "C" __global__ __aicore__ void add_custom(
        GM_ADDR x, GM_ADDR y, GM_ADDR z, GM_ADDR workspace, GM_ADDR tiling) {
    AddTilingData td;
    CopyTilingData(&td, tiling);
    uint32_t len = td.totalLength / GetBlockNum();
    uint32_t lenAlign = CeilDivision(len * sizeof(float), UB_BLOCK_SIZE) * UB_BLOCK_SIZE / sizeof(float);

    TPipe pipe;
    TQue<TPosition::VECIN, 1> inQ;
    TQue<TPosition::VECOUT, 1> outQ;
    GlobalTensor<float> xGm, yGm, zGm;
    xGm.SetGlobalBuffer((__gm__ float*)x, len);
    yGm.SetGlobalBuffer((__gm__ float*)y, len);
    zGm.SetGlobalBuffer((__gm__ float*)z, len);

    pipe.InitBuffer(inQ, 2, lenAlign * sizeof(float));
    pipe.InitBuffer(outQ, 1, lenAlign * sizeof(float));
    LocalTensor<float> xL = inQ.AllocTensor<float>();
    LocalTensor<float> yL = inQ.AllocTensor<float>();
    DataCopyPad(xL, xGm[0], {1, static_cast<uint32_t>(len * sizeof(float)), 0, 0, 0},
                {false, 0, 0, 0.0f});
    DataCopyPad(yL, yGm[0], {1, static_cast<uint32_t>(len * sizeof(float)), 0, 0, 0},
                {false, 0, 0, 0.0f});
    inQ.EnQue(xL); inQ.EnQue(yL);
    xL = inQ.DeQue<float>(); yL = inQ.DeQue<float>();
    LocalTensor<float> zL = outQ.AllocTensor<float>();
    AddCompute(zL, xL, yL, len);
    outQ.EnQue<float>(zL); inQ.FreeTensor(xL); inQ.FreeTensor(yL);
    zL = outQ.DeQue<float>();
    DataCopyOutTensor1D<float>(zGm, zL, 0, len);
    outQ.FreeTensor(zL);
}
'''

def main():
    mod = SourceModule(source=KERNEL_SRC, kernel_name="add_custom",
                       device_id=0, block_dim=1, core_type="VectorCore",
                       workspace_sizes=1024)
    add_func = mod.get_function()

    total_length = 1023
    # z 比 kernel 预期的少 16 个元素 → DataCopyOut 多写 64 字节，冲入哨兵区
    x = np.random.randn(total_length).astype(np.float32)
    y = np.random.randn(total_length).astype(np.float32)
    z = np.empty(total_length - 16, dtype=np.float32)

    tiling_data = pack_tiling_data(
        [("totalLength", np.uint32)], {"totalLength": total_length},
    )
    print(f"\nz: {len(z)} floats ({z.nbytes} bytes), kernel writes {total_length} floats")
    print(f"Expect sentinel OOB detection:\n")
    add_func(x, y, z, *mod.workspace_arrays, tiling_data=tiling_data, output_indices={2})

if __name__ == "__main__":
    main()
