# 线程映射模式

> 线程↔数据单元的映射方式决定了算子的访存形态与负载均衡。两仓库归纳出统一的 grid-stride 三范式 + 4 种映射粒度 + 多级线程块。

## 1. grid-stride 三范式

```cpp
// 范式 A：核内段循环（tiling 已分好 [coreBase, +coreElements) 区间）
for (uint32_t i = threadIdx.x; i < count; i += blockDim.x) { ... }

// 范式 B：全局跨核 grid-stride（不依赖 tiling 分核偏移，最通用）
for (int64_t i = blockIdx.x * blockDim.x + threadIdx.x; i < total; i += gridDim.x * blockDim.x) { ... }

// 范式 C：等价变体（步长只用 blockDim，gridDim=核数）
for (uint32_t idx = blockIdx * blockDim.x + threadIdx.x; idx < outputSize; idx += blockNum * blockDim.x) { ... }
```

- 范式 B/C 使同一 kernel 适配任意核数与总量，**tiling 只需保证总线程数覆盖数据量**，是绝大多数算子的默认选择。
- 全程用 **uint64** 计算 index/stride，避免 `blockIdx*threadNum` 在 32-bit 下溢出（大元素数下越界）。

```cpp
uint64_t threadNum = Simt::GetThreadNum();
uint64_t blockNum = Simt::GetBlockNum();
uint64_t stride = threadNum * blockNum;
for (uint64_t index = blockIdx * threadNum + threadIdx; index < total; index += stride) { ... }
```

- 出处：`math/atanh/op_kernel/arch35/atanh_simt.h`（uint64 防溢出注释）

## 2. 四种"线程↔数据"映射粒度

| 映射 | 形态 | 适用 | 代表算子 |
|------|------|------|---------|
| 一线程一元素 | 线程=输出元素，坐标分解后 gather/scatter | 逐元素、离散访存 | gather、scatter、pooling 前向 |
| 一线程一段/一行 | 线程=一行/一段，段内串行 | 行级归约、扫描 | cummin、embedding_bag、unsorted_segment |
| 一线程一条扫描线 | 线程沿扫描轴串行推进 | 顺序依赖（累积） | cummin SIMT、ctc_loss |
| 每 warp 一个输出 | lane 分摊规约轴 + shuffle | 规约类 | cosine_similarity、trace |

```cpp
// 一线程一元素（间接寻址 gather，SIMT 最典型形态）
for (INDEX_T index = threadIdx.x; index < currentCoreElements; index += blockDim.x) {
    INDEX_T gatherI = Simt::UintDiv(yIndex, m0, shift0);   // 坐标分解
    INDEX_T innerI  = yIndex - gatherI * innerSize;
    y[yIndex] = x[indices[gatherI] * innerSize + innerI];  // 间接寻址
}
// 每 warp 一个输出（lane 分摊规约轴 + asc_reduce_add）
for (IdxT r = laneId; r < reduceSize; r += WARP_SIZE) { w1 += v1*v1; w2 += v2*v2; }
w1 = asc_reduce_add(w1); w2 = asc_reduce_add(w2);
```

- 出处：`index/gather_v2/op_kernel/arch35/gather_v2_simt_two_dim.h`、`math/cosine_similarity/op_kernel/arch35/cosine_similarity_simt.h`

## 3. 2D/3D 线程块

SIMT 线程块支持多维。常见用途：**x 维覆盖连续列（如 innerDim / embeddingDim / 尾轴），y 维覆盖行/段/bag/key**——保证同一 warp 访问连续 GM 地址：

```cpp
// segment_sum：dim3{colSize, threadBlock}，x=列、y=段（段内串行累加列元素）
asc_vf_call<Compute<TX, Index>>(dim3{threadNum, threadBlock}, ...);
for (uint32_t i = threadIdx.y; i < uniqueIdNum; i += blockDim.y) {
    for (int32_t j = uniqueIdPosAddr[i]; j < nextIdPos; j++) {
        res += xAddr[(baseOffset + j) * colSize + threadIdx.x];   // x 维覆盖列
    }
    outputAddr[outputOffset] = res;
}

// 2D 线程块核心原则：让"相邻线程处理相邻 GM 地址"
// NHWC 布局从最内维 C 开始分解（C 最内先除，寄存器链最短）；NCHW 从 W 开始
```

- 出处：`index/segment_sum/op_kernel/arch35/segment_sum_simt.h`、`pooling/dilation2_d`（布局选轴序）、`hash/embedding_hash_table_*`（threadX=embeddingDim、threadY=key）

## 4. warp 协作与 shuffle

```cpp
// warp 归约：asc_reduce_add 仅支持部分 dtype；手写 asc_shfl_down 兼容 double/bf16/complex
__simt_callee__ inline float FloatManualReduce(float val) {
    for (int32_t offset = 16; offset > 0; offset >>= 1) { val += asc_shfl_down(val, offset); }
    return val;
}
// warp 广播：__shfl(var, 0, groupSize) —— 控制线程（lane0）算结果，组内广播
succ = __shfl(succ, 0, threadXNum);       // hash 表：lane0 做探测，全组广播
// warp 扫描：asc_shfl_up Kogge-Stone（radix_sort 全局前缀和）
warpPrefix += ShflUpMask(warpPrefix, 1, laneId); ... // 1,2,4,8,16
```

- 出处：`math/trace`（shfl_down）、`hash/embedding_hash_table_lookup_or_insert`（__shfl 广播）、`experimental/math/radix_sort`（shfl_up）

## 5. 线程数分档与自适应

- 线程数按算子寄存器压力选 2048/1024/512/256/128/64（见 vf-programming.md 第 2 节）；
- 核数利用不足时**线程数自适应减半**（见 tiling-advanced.md 第 4 节）；
- 数据量小时按工作量选择刚好够用的线程档位（`SimtDispatch` 多档）：

```cpp
template <template <uint32_t> class FuncT, typename... Args>
__aicore__ inline void SimtDispatch(uint32_t workSize, Args... args) {
    if (workSize <= 128) { asc_vf_call<FuncT<128>::Run>(dim3(128), args...); }
    else if (workSize <= 256) { ... }
    else { asc_vf_call<FuncT<2048>::Run>(dim3(2048), args...); }
}
// diag_part 按 processNum 分 2048/1024/512/256/128 五档
```

- 出处：`math/diag_part/op_kernel/arch35/diag_part_simt.h`、`conversion/matrix_set_diag_v2`
