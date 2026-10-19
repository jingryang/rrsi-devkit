#include "kernel_operator.h"
#include "simt_api/common_functions.h"
#include <cstdint>

using namespace AscendC;
constexpr uint32_t THREAD_COUNT = 256;

namespace CustomRegImpl {

/*
 * simt_scatter: SIMT 一维 scatter，线程每元素，间接写。
 *
 * output[index[i]] = input[i]。index 需为置换（无重复目标），否则多线程写同一
 * 目标位置是数据竞争（last-writer-wins 不确定）。与 gather（间接读）互为反向。
 * 注意：数据竞争保护不在此 VF 内做——测试用例用置换保证确定性。
 */
__simt_vf__ __launch_bounds__(THREAD_COUNT) inline void ScatterSimtImpl(
    __gm__ float *input, __gm__ uint32_t *index, __gm__ float *output,
    const uint32_t total_length, const uint32_t index_max)
{
    uint32_t tid = blockIdx.x * blockDim.x + threadIdx.x;
    uint32_t stride = gridDim.x * blockDim.x;

    for (uint32_t i = tid; i < total_length; i += stride) {
        // 越界钳制：防止 GM 写越界（SIMT 允许运行时分支）
        uint32_t dst = index[i];
        if (dst >= index_max) {
            dst = index_max - 1;
        }
        output[dst] = input[i];
    }
}

} // namespace CustomRegImpl

struct ScatterTilingData
{
    uint32_t totalLength;
    uint32_t indexMax;
};

template <typename T>
__aicore__ inline void CopyTilingData(T *tiling, GM_ADDR tilingGM) {
    uint8_t *dst = reinterpret_cast<uint8_t *>(tiling);
    auto *src = reinterpret_cast<__gm__ uint8_t *>(tilingGM);
    for (size_t i = 0; i < sizeof(T); ++i) {
        dst[i] = src[i];
    }
}

extern "C" __global__ __aicore__ void scatter(
    GM_ADDR input, GM_ADDR index, GM_ADDR output, GM_ADDR workspace, GM_ADDR tiling)
{
    (void)workspace;
    ScatterTilingData tilingData_;
    CopyTilingData(&tilingData_, tiling);

    asc_vf_call<CustomRegImpl::ScatterSimtImpl>(
        cce::dim3(THREAD_COUNT),
        (__gm__ float *)input, (__gm__ uint32_t *)index, (__gm__ float *)output,
        tilingData_.totalLength, tilingData_.indexMax);
}
