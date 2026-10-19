#include "kernel_operator.h"
#include "simt_api/common_functions.h"
#include <cstdint>

using namespace AscendC;
constexpr uint32_t THREAD_COUNT = 256;

namespace CustomRegImpl {

/*
 * simt_adds: SIMT 逐元素标量加，线程每元素。
 *
 * 与 SIMD 版 adds（__simd_vf__ + Reg::Adds + UpdateMask 尾块）对应，
 * 展示 SIMT 形态：thread-per-element + stride 循环 + GM 直读直写，
 * 无 mask/尾块/硬件循环约束。
 */
__simt_vf__ __launch_bounds__(THREAD_COUNT) inline void AddsSimtImpl(
    __gm__ float *x, __gm__ float *y, const float scalar, const uint32_t total_length)
{
    uint32_t tid = blockIdx.x * blockDim.x + threadIdx.x;
    uint32_t stride = gridDim.x * blockDim.x;

    for (uint32_t i = tid; i < total_length; i += stride) {
        y[i] = x[i] + scalar;
    }
}

} // namespace CustomRegImpl

struct AddsTilingData
{
    uint32_t totalLength;
    float scalar;
};

template <typename T>
__aicore__ inline void CopyTilingData(T *tiling, GM_ADDR tilingGM) {
    uint8_t *dst = reinterpret_cast<uint8_t *>(tiling);
    auto *src = reinterpret_cast<__gm__ uint8_t *>(tilingGM);
    for (size_t i = 0; i < sizeof(T); ++i) {
        dst[i] = src[i];
    }
}

extern "C" __global__ __aicore__ void adds(
    GM_ADDR x, GM_ADDR y, GM_ADDR workspace, GM_ADDR tiling)
{
    (void)workspace;
    AddsTilingData tilingData_;
    CopyTilingData(&tilingData_, tiling);

    asc_vf_call<CustomRegImpl::AddsSimtImpl>(
        cce::dim3(THREAD_COUNT),
        (__gm__ float *)x, (__gm__ float *)y,
        tilingData_.scalar, tilingData_.totalLength);
}
