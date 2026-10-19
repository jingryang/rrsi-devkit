#include "kernel_operator.h"
#include "simt_api/common_functions.h"
#include <cstdint>

using namespace AscendC;
constexpr uint32_t UB_BLOCK_SIZE = 32;
constexpr uint32_t THREAD_COUNT = 256;

namespace CustomRegImpl {

/*
 * simt_gather_row: 二维行 gather 的 SIMT 实现，对应参考 gather.asc 中
 * "单线程处理一整行（所有列）" 的语义。
 *
 * 每个 SIMT 线程负责一个输出行 out_row，从 index 表读出源行号后，把输入行
 * input[in_row * in_width : +in_width] 逐列拷贝到输出行
 * output[out_row * in_width : +in_width]。
 *
 * SIMT 可直接读写 GM（经 DCache），因此本 VF 不申请任何 __ubuf__ 缓冲，
 * 不受 SingleOperatorLaunch 的 8KB UB 窗口约束。
 *
 * 为支持单核内行数超过线程数的场景，使用 stride 循环摊开所有输出行：
 *   for (row = tid; row < index_total_length; row += stride)
 */
__simt_vf__ __launch_bounds__(THREAD_COUNT) inline void GatherRowSimtImpl(
    __gm__ float *input, __gm__ uint32_t *index, __gm__ float *output,
    const uint32_t in_width, const uint32_t input_rows, const uint32_t index_total_length)
{
    // 全局线程号 = 当前核号 * 每核线程数 + 核内线程号。
    uint32_t out_row = blockIdx.x * blockDim.x + threadIdx.x;
    uint32_t stride = gridDim.x * blockDim.x;

    for (uint32_t row = out_row; row < index_total_length; row += stride) {
        // 从 index 表读取源行号；越界时钳制到最后一个合法行，防止 GM 读越界。
        uint32_t in_row = index[row];
        if (in_row >= input_rows) {
            in_row = input_rows - 1;
        }
        uint32_t in_base = in_row * in_width;
        uint32_t out_base = row * in_width;
        // 单线程处理整行（所有列）。
        for (uint32_t col = 0; col < in_width; ++col) {
            output[out_base + col] = input[in_base + col];
        }
    }
}

} // namespace CustomRegImpl

struct GatherTilingData
{
    uint32_t in_width;
    uint32_t input_rows;
    uint32_t index_total_length;
};

template <typename T>
__aicore__ inline void CopyTilingData(T *tiling, GM_ADDR tilingGM) {
    uint8_t *dst = reinterpret_cast<uint8_t *>(tiling);
    auto *src = reinterpret_cast<__gm__ uint8_t *>(tilingGM);
    for (size_t i = 0; i < sizeof(T); ++i) {
        dst[i] = src[i];
    }
}

extern "C" __global__ __aicore__ void gather(
    GM_ADDR input, GM_ADDR index, GM_ADDR output, GM_ADDR workspace, GM_ADDR tiling)
{
    (void)workspace;
    GatherTilingData tilingData_;
    CopyTilingData(&tilingData_, tiling);

    uint32_t in_width = tilingData_.in_width;
    uint32_t input_rows = tilingData_.input_rows;
    uint32_t index_total_length = tilingData_.index_total_length;

    // 启动 SIMT VF：单核内 THREAD_COUNT 个线程，跨核由 gridDim/blockIdx 拆分。
    asc_vf_call<CustomRegImpl::GatherRowSimtImpl>(
        cce::dim3(THREAD_COUNT),
        (__gm__ float *)input, (__gm__ uint32_t *)index, (__gm__ float *)output,
        in_width, input_rows, index_total_length);
}
